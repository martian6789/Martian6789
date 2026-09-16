# -*- coding: utf-8 -*-
"""下载执行器：线程池并发下载 + 完整性校验 + 自动重试 + ffmpeg 合并"""
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Optional

import requests
from PySide6.QtCore import QObject, QRunnable, Signal, QThreadPool

from .config import UA, safe_filename, ffmpeg_path, fmt_size

MIN_FREE_BYTES = 300 * 1024 * 1024      # 低于此剩余空间直接拒绝写入


def free_bytes(path: str) -> int:
    try:
        p = path
        while p and not os.path.isdir(p):
            p = os.path.dirname(p)
        return shutil.disk_usage(p or ".").free
    except Exception:
        return -1


def friendly_error(e: Exception) -> str:
    """把底层异常翻译成用户能看懂的话"""
    msg = str(e) or e.__class__.__name__
    err = getattr(e, "errno", None)
    low = msg.lower()
    if err == 28 or "no space left" in low or "not enough space" in low:
        return ("磁盘空间不足，写入失败。请清理磁盘或把保存目录换到其它分区"
                "（例如 D:\\ 或 E:\\）。")
    if "timed out" in low or "timeout" in low:
        return "网络超时，请检查网络后重试。"
    if "connection" in low or "max retries" in low:
        return "网络连接中断，请检查网络后重试。"
    if "403" in msg:
        return "服务器拒绝访问（403），直链可能已过期，请重新解析。"
    if "404" in msg:
        return "视频地址不存在（404），可能已被删除。"
    return msg[:180]

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.douyin.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
}

# 低于此体积视为无效（正常视频至少几百 KB）
MIN_VALID_BYTES = 64 * 1024


class _Interrupted(Exception):
    """暂停 / 停止导致的中断——不是下载失败，不该计入失败数。

    discard=True 表示「停止」：临时文件要删掉；
    discard=False 表示「暂停」：临时文件必须保留，下次用 HTTP Range 续传。
    """

    def __init__(self, discard: bool):
        super().__init__("已中断")
        self.discard = discard


def _startup_info():
    import sys
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


class _Signals(QObject):
    sigStart = Signal(int)
    sigProgress = Signal(int, int, int)      # row, percent, bytes
    sigDone = Signal(int, str, int)          # row, path, size
    sigError = Signal(int, str)
    sigLog = Signal(int, str)
    sigAborted = Signal(int)                 # 因暂停/停止而中断（不算失败）


class DownloadTask(QRunnable):
    """单个视频下载任务：带重试、断点续传与成品校验"""

    MAX_RETRY = 3
    CHUNK = 1 << 16

    def __init__(self, row: int, payload: dict, save_dir: str,
                 filename: str, cancel: threading.Event,
                 pause: threading.Event = None):
        super().__init__()
        self.row = row
        self.payload = payload
        self.save_dir = save_dir
        self.filename = filename
        self.cancel = cancel
        self.pause = pause or threading.Event()
        self.signals = _Signals()
        self._target = ""
        self._tmp = ""
        self._vtmp = ""
        self._atmp = ""
        self._mark = ""

    # ------------- 中断 -------------
    def _check_break(self):
        """在每个数据块之间检查暂停/停止。"""
        if self.cancel.is_set():
            raise _Interrupted(discard=True)
        if self.pause.is_set():
            raise _Interrupted(discard=False)

    # ------------- 网络 -------------
    def _emit_prog(self, pct, size):
        self.signals.sigProgress.emit(self.row, int(pct), int(size))

    def _fetch(self, url: str, path: str,
               min_bytes: int = MIN_VALID_BYTES) -> int:
        """下载到 path，支持断点续传。

        若 path 已存在且有内容，会带上 ``Range`` 头从断点续传：
        服务器返回 206 就追加，返回 200（不支持续传）则从头重下。
        """
        have = os.path.getsize(path) if os.path.exists(path) else 0
        headers = dict(HEADERS)
        mode = "wb"
        if have > 0:
            headers["Range"] = "bytes=%d-" % have
            mode = "ab"

        r = requests.get(url, headers=headers, stream=True, timeout=(15, 60))
        code = r.status_code

        if code == 416:
            # Range 越界：说明本地文件已经 >= 服务端总长度，交给上层校验
            r.close()
            return have
        if code not in (200, 206):
            r.raise_for_status()

        ctype = (r.headers.get("Content-Type") or "").lower()
        if any(k in ctype for k in ("text/", "html", "json", "xml")):
            r.close()
            raise RuntimeError(f"服务器返回的不是视频内容（{ctype}）")

        if code == 200 and mode == "ab":
            # 服务器忽略了 Range，只能重新开始
            have = 0
            mode = "wb"

        # 总长度：206 时 Content-Length 只是本段长度，要看 Content-Range
        total = 0
        cr = r.headers.get("Content-Range") or ""
        m = re.search(r"/\s*(\d+)\s*$", cr)
        if m:
            total = int(m.group(1))
        elif code == 200:
            total = int(r.headers.get("Content-Length") or 0)
        else:
            total = have + int(r.headers.get("Content-Length") or 0)

        got = have
        with open(path, mode) as f:
            for chunk in r.iter_content(self.CHUNK):
                self._check_break()
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                if total:
                    self._emit_prog(got * 100.0 / total, got)
                else:
                    self._emit_prog(50, got)

        if total and got < total * 0.98:
            raise RuntimeError(f"下载不完整（{fmt_size(got)} / {fmt_size(total)}）")
        if got < min_bytes:
            raise RuntimeError(f"文件过小（{fmt_size(got)}），疑似无效地址")
        return got


    # ------------- 校验 -------------
    def _verify(self, path: str, expect_dur: float = 0.0):
        """用 ffmpeg 校验成品是否可播放，返回 (ok, 实际时长, 原因)"""
        try:
            p = subprocess.run(
                [ffmpeg_path(), "-hide_banner", "-i", path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                startupinfo=_startup_info(), timeout=120)
            s = (p.stdout or b"").decode("utf-8", "ignore")
        except Exception as e:
            return False, 0.0, f"校验失败：{e}"
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", s)
        dur = 0.0
        if m:
            dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if not re.search(r"Stream #\d+:\d+.*?: Video:", s):
            return False, dur, "文件内没有视频流，无法播放"
        if dur < 1.0:
            return False, dur, f"时长异常（{dur:.2f}s）"
        if expect_dur and expect_dur > 3.0:
            if abs(dur - expect_dur) > max(3.0, expect_dur * 0.2):
                return False, dur, (f"时长不符（实际 {dur:.1f}s / 期望 "
                                    f"{expect_dur:.1f}s），可能下错视频")
        return True, dur, ""

    def _merge(self, vpath: str, apath: Optional[str], out: str):
        ff = ffmpeg_path()
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", vpath]
        if apath and os.path.exists(apath):
            cmd += ["-i", apath, "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-shortest"]
        else:
            cmd += ["-c", "copy"]
        cmd += [out]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=1800,
                           startupinfo=_startup_info())
        if p.returncode != 0 or not os.path.exists(out):
            raise RuntimeError((p.stderr or "ffmpeg 合并失败").strip()[-200:])

    # ------------- 主流程 -------------
    def run(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
        except Exception as e:
            self.signals.sigError.emit(self.row, f"无法创建保存目录：{e}")
            return
        self._resolve_target()
        if free_bytes(self.save_dir) < MIN_FREE_BYTES:
            self.signals.sigError.emit(
                self.row,
                "磁盘空间不足，已跳过下载。请清理磁盘或把保存目录换到其它分区。")
            return
        last_err = ""
        for attempt in range(self.MAX_RETRY):
            if self._stopped():
                self._abort()
                return
            try:
                self.signals.sigStart.emit(self.row)
                self._run_once(attempt)
                if os.path.exists(self._target):
                    # 已经把成品改名到位，即使这期间收到暂停也算完成
                    size = os.path.getsize(self._target)
                    self.signals.sigDone.emit(self.row, self._target, size)
                    return
                self._abort()          # 暂停落在收尾阶段：保住 .part，下次续传
                return
            except _Interrupted as brk:
                # 暂停 / 停止：不算失败，不发 sigError。
                # 停止要清干净；暂停必须把 .part 留着，下次才能续传。
                if brk.discard:
                    self._cleanup_tmp()
                self._abort()
                return
            except Exception as e:
                last_err = friendly_error(e)
                # 网络类问题保留 .part（直链过期后重新解析还能接着下）；
                # 校验类问题说明数据本身是坏的，必须清掉重来。
                if not isinstance(e, requests.exceptions.RequestException):
                    self._cleanup_tmp()
                if self._stopped():
                    self._abort()
                    return
                if attempt < self.MAX_RETRY - 1:
                    self.signals.sigLog.emit(
                        self.row, f"下载失败，重试 {attempt + 2}/{self.MAX_RETRY}…")
                    time.sleep(1.2 * (attempt + 1))
        self.signals.sigError.emit(self.row, last_err or "下载失败")

    def _stopped(self) -> bool:
        return self.cancel.is_set() or self.pause.is_set()

    def _abort(self):
        self.signals.sigAborted.emit(self.row)


    def _resolve_target(self):
        """确定最终文件名与临时文件名。

        页面在提交任务前已经把唯一文件名排好（暂停/继续会沿用同一个名字），
        所以这里不再自作主张加序号——一旦加序号，续传就找不到原来的 .part，
        等于把断点续传废掉。
        """
        target = os.path.join(self.save_dir, self.filename)
        if os.path.exists(target) and not os.path.exists(self._part_of(target)):
            # 正常流程不会走到这里（页面已避免冲突），真撞上就退让一个序号，
            # 绝不覆盖用户已有的文件。
            base, ext = os.path.splitext(target)
            n = 1
            while os.path.exists(target):
                n += 1
                target = "%s (%d)%s" % (base, n, ext)
        self._target = target
        self._tmp = self._part_of(target)
        self._mark = self._tmp + ".done"
        stem = os.path.splitext(target)[0]
        self._vtmp = stem + ".vpart.mp4"
        self._atmp = stem + ".apart.mp4"

    @staticmethod
    def _part_of(target: str) -> str:
        # 临时文件必须带真实扩展名，否则 ffmpeg 无法推断输出容器格式，
        # 合并时会直接报 "Invalid argument" 写不出文件。
        stem, ext = os.path.splitext(target)
        return stem + ".part" + ext

    @staticmethod
    def _drop(*paths):
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    def _touch_mark(self):
        """给「已完整下载并通过校验」的临时文件打个标记。

        没有这个标记就不能凭「.part 存在」判定它是完整文件：
        部分下载的 MP4 在 moov 前置时照样能被 ffmpeg 读出时长和视频流，
        校验会误判通过，续传时直接把半成品改名成成品（实测踩过）。
        """
        try:
            with open(self._mark, "w", encoding="utf-8") as f:
                f.write(str(int(time.time())))
        except Exception:
            pass

    def _finalize(self):
        os.replace(self._tmp, self._target)
        self._drop(self._mark)

    def _cleanup_tmp(self):
        self._drop(self._tmp, self._vtmp, self._atmp, self._mark)

    def _run_once(self, attempt: int):
        mode = self.payload.get("mode")
        expect = float(self.payload.get("dur") or 0)

        # 上次可能正好暂停在「已下完、还没改名」这一步。
        # 必须有 .done 标记才认，否则会把半成品当成品。
        if os.path.exists(self._mark) and os.path.exists(self._tmp):
            ok, _d, _w = self._verify(self._tmp, expect)
            if ok:
                self._finalize()
                return
            self._drop(self._mark)

        if mode == "mux":
            self.signals.sigLog.emit(self.row, "下载中…")
            self._fetch(self.payload["url"], self._tmp)
            self._touch_mark()
            ok, _dur, why = self._verify(self._tmp, expect)
            if not ok:
                self._cleanup_tmp()
                raise RuntimeError(why)
            self._finalize()
            return

        vurl = self.payload.get("v")
        aurl = self.payload.get("a")
        if not vurl:
            raise RuntimeError("未获取到视频流")
        try:
            self.signals.sigLog.emit(self.row, "下载视频流…")
            self._fetch(vurl, self._vtmp)
            if aurl:
                self.signals.sigLog.emit(self.row, "下载音频流…")
                try:
                    # 音频流本来就小，阈值放宽
                    self._fetch(aurl, self._atmp, min_bytes=8 * 1024)
                except _Interrupted:
                    raise
                except Exception:
                    # 音频拿不到就只留视频，总比整条失败强
                    self._drop(self._atmp)
                    aurl = None
            self.signals.sigLog.emit(self.row, "合并音视频…")
            self._merge(self._vtmp, aurl and self._atmp or None, self._tmp)
            self._touch_mark()
        except _Interrupted:
            raise                     # 暂停/停止：分片留着，下次接着下
        except Exception:
            self._drop(self._vtmp, self._atmp)   # 合并失败：分片不可信
            raise
        else:
            self._drop(self._vtmp, self._atmp)   # 合并成功，分片已完成使命

        ok, _dur, why = self._verify(self._tmp, expect)
        if not ok:
            self._cleanup_tmp()
            raise RuntimeError(why)
        self._finalize()



class DownloadManager(QObject):
    """管理下载线程池（独立线程池，不干扰界面其他任务）"""

    def __init__(self, parent=None, max_workers: int = 3):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.max_workers = self._clamp(max_workers)
        self.pool.setMaxThreadCount(self.max_workers)
        self.cancel = threading.Event()     # 停止：丢弃临时文件
        self.pause = threading.Event()      # 暂停：保留临时文件，支持续传
        self._active = 0
        self._lock = threading.Lock()
        # 必须持有任务引用，否则 Python 侧被回收后信号无法送达
        self._tasks: list = []

    @staticmethod
    def _clamp(n) -> int:
        try:
            n = int(n)
        except Exception:
            n = 3
        return max(1, min(16, n))

    def set_max_workers(self, n: int):
        self.max_workers = self._clamp(n)
        self.pool.setMaxThreadCount(self.max_workers)

    def reset_control(self):
        self.cancel.clear()
        self.pause.clear()

    # 兼容旧调用
    def reset_cancel(self):
        self.reset_control()

    def request_cancel(self):
        self.cancel.set()
        self.pause.clear()

    def request_pause(self):
        self.pause.set()

    def resume(self):
        self.pause.clear()

    def submit(self, task: DownloadTask):
        with self._lock:
            self._active += 1
            self._tasks.append(task)
        task.signals.sigDone.connect(lambda *a, t=task: self._release(t))
        task.signals.sigError.connect(lambda *a, t=task: self._release(t))
        task.signals.sigAborted.connect(lambda *a, t=task: self._release(t))
        self.pool.start(task)

    def _release(self, task):
        with self._lock:
            try:
                self._tasks.remove(task)
            except ValueError:
                pass
            self._active = max(0, self._active - 1)

    @property
    def active(self):
        with self._lock:
            return self._active

    def wait_idle(self, timeout_ms=60000):
        self.pool.waitForDone(timeout_ms)

