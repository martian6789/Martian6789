# -*- coding: utf-8 -*-
"""断点续传验证：解析一条真实直链 → 下到一半暂停 → 确认 .part 保留 → 续传完成。

同时验证抖音 CDN 是否支持 HTTP Range（决定续传能不能只下剩下的部分）。
"""
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

import requests                                                    # noqa: E402
from PySide6.QtCore import QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from app.downloader import DownloadTask                            # noqa: E402
from app.resolver import ResolveController                         # noqa: E402

VID = sys.argv[1] if len(sys.argv) > 1 else "7028953425052323087"
PAUSE_MS = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
SAVE = os.path.join(tempfile.gettempdir(), "dytest_resume")

OUT = {}


def log(m):
    print(m, flush=True)


def main():
    app = QApplication(sys.argv[:1])
    # 记录下载任务真正发出的请求（含 Range 头与响应码），这是「续传」的硬证据
    import app.downloader as dlm
    orig_get = dlm.requests.get
    calls = []

    def patched(url, **kw):
        r = orig_get(url, **kw)
        rng = (kw.get("headers") or {}).get("Range", "-")
        calls.append((r.status_code, rng))
        return r

    dlm.requests.get = patched
    OUT["calls"] = calls

    os.makedirs(SAVE, exist_ok=True)
    for f in os.listdir(SAVE):
        try:
            os.remove(os.path.join(SAVE, f))
        except Exception:
            pass

    rc = ResolveController()
    rc.set_concurrency(1)

    def on_resolved(row, payload):
        log("解析成功：mode=%s br=%s" % (payload.get("mode"), payload.get("br")))
        OUT["payload"] = payload
        QTimer.singleShot(200, phase1)

    def on_failed(row, msg):
        log("解析失败：%s" % msg)
        app.quit()

    rc.sigResolved.connect(on_resolved)
    rc.sigFailed.connect(on_failed)
    rc.start([(0, VID, "resume-test", 0)], 0)

    def phase1():
        pay = OUT["payload"]
        url = pay.get("url") or pay.get("v")
        # --- 1) CDN 是否支持 Range ---
        try:
            from app.downloader import HEADERS
            h = dict(HEADERS)
            h["Range"] = "bytes=0-2047"
            r = requests.get(url, headers=h, stream=True, timeout=20)
            log("Range 探测：HTTP %s  Content-Range=%s"
                % (r.status_code, r.headers.get("Content-Range")))
            OUT["range_ok"] = (r.status_code == 206)
            r.close()
        except Exception as e:
            log("Range 探测失败：%s" % e)

        # --- 2) 启动下载，1.5 秒后暂停 ---
        cancel = threading.Event()
        pause = threading.Event()
        name = "resume_test.mp4"
        task = DownloadTask(0, pay, SAVE, name, cancel, pause)
        task.signals.sigDone.connect(
            lambda *a: (log("!! 第 1 轮就完成了（太快，改用更短延时）"),
                        app.quit()))
        task.signals.sigError.connect(lambda r, m: (log("第 1 轮失败：%s" % m),
                                                    app.quit()))
        task.signals.sigAborted.connect(lambda r: log("第 1 轮已中断（暂停）"))
        task.signals.sigProgress.connect(
            lambda r, p, b: OUT.setdefault("prog1", p))
        task.run = task.run          # 保持接口
        t = threading.Thread(target=task.run, daemon=True)
        OUT["thread1"] = t
        t.start()
        QTimer.singleShot(PAUSE_MS, lambda: pause.set())
        QTimer.singleShot(PAUSE_MS + 3500, phase2)

    def phase2():
        part = os.path.join(SAVE, "resume_test.part.mp4")
        target = os.path.join(SAVE, "resume_test.mp4")
        size = os.path.getsize(part) if os.path.exists(part) else -1
        log("暂停后 .part 存在=%s 大小=%s 字节" % (os.path.exists(part), size))
        log("最终文件是否已生成=%s" % os.path.exists(target))
        OUT["part_size"] = size
        if size <= 0:
            log("结论：暂停没有留下断点文件 —— 续传会失败")
            app.quit()
            return
        # --- 3) 续传 ---
        cancel2 = threading.Event()
        pause2 = threading.Event()
        task2 = DownloadTask(0, OUT["payload"], SAVE, "resume_test.mp4",
                             cancel2, pause2)
        task2.signals.sigDone.connect(lambda r, p, s: phase3(s))
        task2.signals.sigError.connect(lambda r, m: (log("续传失败：%s" % m),
                                                     app.quit()))
        threading.Thread(target=task2.run, daemon=True).start()

    def phase3(size):
        target = os.path.join(SAVE, "resume_test.mp4")
        log("续传完成：%s（%s 字节）" % (target, size))
        log("断点时 %s 字节 → 最终 %s 字节，增量 %s 字节"
            % (OUT.get("part_size"), size, size - (OUT.get("part_size") or 0)))
        log("任务实际发出的 HTTP 请求（状态码, Range 头）：")
        for c in OUT.get("calls") or []:
            log("    %s   Range=%s" % c)
        used_range = any(c[1] != "-" for c in (OUT.get("calls") or []))
        got206 = any(c[0] == 206 for c in (OUT.get("calls") or []))
        log("结论：CDN 支持 Range=%s；续传请求带了 Range=%s（响应 206=%s）"
            % (OUT.get("range_ok"), used_range, got206))
        app.quit()

    QTimer.singleShot(300000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
