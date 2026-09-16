# -*- coding: utf-8 -*-
"""视频直链解析器（并发版）

要点：
* 媒体流只认 douyinvod 域名的 CDN 地址。旧实现把 douyinstatic 的 JS/CSS
  也当成媒体流，带来两个致命后果：
    1) 静默判定永不成立 —— 页面持续加载静态资源，每个视频都死等到超时，
       这是「解析很慢」的根因；
    2) 会把 player-*.js 当成视频挑走下载 —— 这是「下完只有几百 KB
       且播不了」的根因。
* **视图必须复用，绝不能「用完就销毁再新建」**。实测在 10 路并发下，前面
  10 个视图工作正常，一旦它们被销毁、新建第 11 个起就再也拿不到视频流
  （Chromium 的渲染进程数量有上限），表现就是「下到第 10 个以后整批失败」。
  所以这里维护一个固定大小的视图池，每个槽位把同一个视图反复 load 新地址。
* 播放页要 9 秒以上才能真正拉流，所以超时给到 30 秒；原来只给 18 秒，
  很多「慢一点但完全正常」的视频被误判成失败。
"""
import json
import re
import time
from collections import deque
from typing import List, Optional, Dict, Any

from PySide6.QtCore import QObject, Signal, QTimer, QUrl

from .webengine import make_view
from . import runlog

SHARE_TPL = "https://www.iesdouyin.com/share/video/{vid}"
PAGE_TPL = "https://www.douyin.com/video/{vid}"

# 失败时把页面真实状态记进日志：是登录墙、人机验证，还是压根没加载出来？
DIAG_JS = ("(function(){try{var r=performance.getEntriesByType('resource'),"
           "o=0,i;for(i=0;i<r.length;i++){if(r[i].name.indexOf('douyinvod')>=0)o++;}"
           "return JSON.stringify({h:location.href,t:document.title,"
           "b:(document.body?(document.body.innerText||''):'')"
           ".replace(/\\s+/g,' ').slice(0,180),"
           "res:r.length,vod:o,v:!!document.querySelector('video')});}"
           "catch(e){return '{}';}})()")

KICK_JS = ("(function(){try{var v=document.querySelector('video');"
           "if(v){v.muted=true;v.volume=0;try{v.play()}catch(e){}}"
           "return 1;}catch(e){return 0;}})()")

# 一次 JS 调用同时拿到五件事：
#   u = 已加载的 douyinvod 媒体流地址
#   d = 页面是否明确提示「作品不存在」
#   c = 页面是否要求人机验证（拖动滑块等）
#   h = 当前文档地址（用来确认页面确实已经切到目标视频，避免复用的视图
#       把上一条视频的流算到这一条头上）
# 验证码判定必须同时看 document.title：实测风控触发的「验证码中间页」
# 把内容画在 canvas/iframe 里，body.innerText 几乎是空的（日志实锤：
# t="验证码中间页" 而 b=" "），只查正文永远检测不到，弹窗就从不触发。
PERF_JS = ("(function(){try{var r=performance.getEntriesByType('resource'),"
           "o=[],i,n;for(i=0;i<r.length;i++){n=r[i].name;"
           "if(n.indexOf('douyinvod')>=0){o.push(n);}}"
           "var t=document.body?(document.body.innerText||''):'';"
           "var ti=document.title||'';"
           "var dead=0;"
           "if(t.indexOf('作品不存在')>=0||t.indexOf('该作品已被删除')>=0"
           "||t.indexOf('内容不存在')>=0||t.indexOf('页面不存在')>=0"
           "||t.indexOf('该内容无法查看')>=0)dead=1;"
           "var cap=0;"
           "if(t.indexOf('拖动滑块')>=0||t.indexOf('安全验证')>=0"
           "||t.indexOf('验证码')>=0||t.indexOf('请完成验证')>=0"
           "||t.indexOf('滑动验证')>=0"
           "||ti.indexOf('验证码')>=0||ti.indexOf('安全验证')>=0"
           "||ti.indexOf('请完成验证')>=0"
           "||document.querySelector('.captcha_verify_container,#captcha_container,.verify-wrap')"
           ")cap=1;"
           "return JSON.stringify({u:o,d:dead,c:cap,h:location.href});}"
           "catch(e){return JSON.stringify({u:[],d:0,c:0,h:''});}})()")


def _br(url: str) -> int:
    m = re.search(r"[?&]br=(\d+)", url)
    return int(m.group(1)) if m else 0


def _tos_id(url: str) -> str:
    """提取 CDN 资源 ID，用于把「推荐位视频」与「目标视频」分开"""
    m = re.search(r"/video/tos/[^/]+/[^/]+/([^/?]+)", url)
    return m.group(1) if m else ""


def _is_media(url: str) -> bool:
    """严格判定：只有 CDN 媒体流才算，静态资源一律排除"""
    low = url.lower()
    if "douyinvod" in low:
        return True
    if "douyinstatic" in low or "douyinpic" in low or "bytescm" in low:
        return False
    if low.endswith(".js") or low.endswith(".css") or ".js?" in low:
        return False
    return "/video/tos/" in low


def pick_streams(urls: List[str], vid: str, quality: int = 0) -> Dict[str, Any]:
    """从捕获到的流地址里挑选目标视频的最优流。

    quality: 0=最高画质 1=中等 2=最低
    返回 {"mode":"mux"|"dash", "url":..., "v":..., "a":..., "br":...}
    """
    uniq, seen = [], set()
    for u in urls:
        if not _is_media(u) or u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    if not uniq:
        return {}

    def own(u):
        return f"__vid={vid}" in u

    owned = [u for u in uniq if own(u)]
    pool = owned or uniq

    # 按 CDN 资源 ID 分组：视频页会预加载「推荐视频」，同组才是同一支片子。
    # 取条目最多的那组，避免把推荐位的内容当成本条视频。
    groups: Dict[str, List[str]] = {}
    for u in pool:
        groups.setdefault(_tos_id(u) or "_", []).append(u)
    if len(groups) > 1:
        if owned:
            best = pool
        else:
            best = max(groups.values(), key=len)
    else:
        best = pool

    muxed = [u for u in best if "media-video" not in u and "media-audio" not in u]
    dash_v = [u for u in best if "media-video" in u]
    dash_a = [u for u in best if "media-audio" in u]

    def choose(lst: List[str]) -> Optional[str]:
        if not lst:
            return None
        s = sorted(lst, key=_br, reverse=True)
        if quality == 0:
            return s[0]
        if quality == 1:
            return s[len(s) // 2]
        return s[-1]

    m = choose(muxed)
    v = choose(dash_v)
    a = choose(dash_a)

    # 分离流码率明显更高时，最高画质档位改选分离流
    if m and v and quality == 0 and _br(v) > _br(m) * 1.25:
        return {"mode": "dash", "v": v, "a": a, "br": _br(v)}
    if m:
        return {"mode": "mux", "url": m, "br": _br(m)}
    if v:
        return {"mode": "dash", "v": v, "a": a, "br": _br(v)}
    return {}


class ResolveController(QObject):
    """并发解析队列：固定数量的视图池，轮流解析每一条视频"""

    sigResolved = Signal(int, object)     # row, payload
    sigFailed = Signal(int, str)          # row, reason
    sigProgress = Signal(int, str)        # row, message
    sigAllDone = Signal()
    sigStalled = Signal(int)              # 连续失败条数（疑似登录态/风控问题）
    sigCaptcha = Signal()                 # 检测到人机验证（拖动滑块等）

    TICK_MS = 500
    SILENT = 1.2        # 拿到流后再静默多久收尾（秒）
    MAX_WAIT = 30.0     # 单个视频最长等待（秒）
    DEAD_AFTER = 9.0    # 超过这个时间还没流、且页面明确说不存在 → 立刻放弃
    MAX_RETRY = 1       # 失败重试次数
    # 连续这么多条「一条流都没拿到」就判定为系统性问题（登录失效 / 人机验证 /
    # 网络异常），停止排队并提示用户，而不是让几百条挨个失败。
    STALL_N = 3

    def __init__(self, parent=None, concurrency: int = 5):
        super().__init__(parent)
        self.queue: deque = deque()
        self.quality = 0
        self.concurrency = self._clamp(concurrency)
        self._running = False
        self._pool: List[dict] = []          # 常驻视图池（长度 = concurrency）
        self._slots: Dict[int, dict] = {}    # sid -> 当前正在解析的任务
        self._consec = 0                     # 连续失败计数（见 STALL_N）
        self._captcha_seen = False           # 本轮是否已经弹过验证提醒
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    # ---------------- 对外接口 ----------------
    @staticmethod
    def _clamp(n) -> int:
        try:
            n = int(n)
        except Exception:
            n = 5
        return max(1, min(10, n))

    def set_concurrency(self, n: int):
        self.concurrency = self._clamp(n)
        if not self._running:
            self._ensure_pool()

    def start(self, items: List[tuple], quality: int = 0):
        """items: [(row, vid, title, dur), ...]"""
        self.queue = deque(items)
        self.quality = quality
        self._running = True
        self._consec = 0
        self._captcha_seen = False
        self._ensure_pool()
        self._timer.start()
        self._fill()

    def stop(self):
        self._running = False
        self.queue.clear()
        self._timer.stop()
        self._slots.clear()
        # 保留视图池（只把它们停在空白页）。删除视图后再新建，很可能
        # 再也拿不到视频流，所以只在退出程序时才真正销毁。
        self._idle_pool()

    def pause(self):
        """暂停解析：返回「还没解析完」的条目，供恢复时重新入队。"""
        remain = list(self.queue)
        for st in list(self._slots.values()):
            try:
                remain.append((st["row"], st["vid"], st["title"],
                               st.get("dur", 0)))
            except Exception:
                continue
        self._running = False
        self.queue.clear()
        self._timer.stop()
        self._slots.clear()
        for ent in self._pool:
            try:
                ent["view"].stop()
            except Exception:
                pass
        return remain

    @property
    def running(self):
        return self._running

    @property
    def pending_count(self):
        return len(self.queue) + len(self._slots)

    # ---------------- 视图池 ----------------
    def _ensure_pool(self):
        """维持固定大小的视图池。

        复用而非重建是这里的核心：新建视图超过一定数量后就拿不到流了。
        """
        while len(self._pool) < self.concurrency:
            view = make_view()
            view.resize(1000, 700)
            self._pool.append({"view": view, "gen": 0})
        # 收缩只在末尾有空闲视图时做，避免把正在用的视图删掉
        while len(self._pool) > self.concurrency:
            last = len(self._pool) - 1
            if last in self._slots:
                break
            ent = self._pool.pop()
            self._drop_view(ent["view"])

    def _dispose_pool(self):
        for ent in self._pool:
            self._drop_view(ent["view"])
        self._pool = []

    def _idle_pool(self):
        """一轮跑完：把视图停在空白页。

        既释放页面占用的资源，又保留视图本身——因为「销毁后重建」正是
        「下到第 10 个以后整批失败」的根源，绝不能删。
        """
        for ent in self._pool:
            try:
                ent["view"].stop()
                ent["view"].setUrl(QUrl("about:blank"))
            except Exception:
                pass

    def shutdown(self):
        """退出程序时释放视图池"""
        self._running = False
        self.queue.clear()
        self._timer.stop()
        self._slots.clear()
        self._dispose_pool()

    @staticmethod
    def _drop_view(view):
        if not view:
            return
        try:
            view.stop()
            view.setParent(None)
            view.deleteLater()
        except Exception:
            pass

    # ---------------- 调度 ----------------
    def _free_slot(self) -> Optional[int]:
        for i in range(len(self._pool)):
            if i not in self._slots:
                return i
        return None

    def _fill(self):
        if not self._running:
            return
        while self.queue:
            sid = self._free_slot()
            if sid is None:
                break
            item = self.queue.popleft()
            row, vid, title = item[0], item[1], item[2]
            try:
                dur = float(item[3] or 0) if len(item) > 3 else 0.0
            except Exception:
                dur = 0.0
            self._slots[sid] = {
                "sid": sid, "row": row, "vid": str(vid), "title": title,
                "dur": dur, "urls": set(), "retry": 0, "gen": -1,
                "t0": time.time(), "last_new": time.time(), "done": False,
                "expect": str(vid),
            }
            self._open(sid)

    # ---------------- 单个任务 ----------------
    def _open(self, sid: int):
        st = self._slots.get(sid)
        if not st:
            return
        ent = self._pool[sid]
        ent["gen"] = ent.get("gen", 0) + 1
        gen = ent["gen"]
        st["gen"] = gen
        st["urls"] = set()
        st["t0"] = time.time()
        st["last_new"] = time.time()
        st["done"] = False

        view = ent["view"]
        try:
            view.stop()          # 掐掉上一条视频还在跑的请求
        except Exception:
            pass
        # 实测：iesdouyin 的分享页现在会返回「验证码中间页」，永远拿不到流，
        # 白等一整个超时。所以主路径直接用播放页，分享页只当失败后的备选。
        url = (PAGE_TPL.format(vid=st["vid"]) if st["retry"] == 0
               else SHARE_TPL.format(vid=st["vid"]))
        self.sigProgress.emit(st["row"], "解析中…")
        view.load(QUrl(url))
        QTimer.singleShot(1500, lambda s=sid, g=gen: self._kick(s, g))
        QTimer.singleShot(4500, lambda s=sid, g=gen: self._kick(s, g))

    def _kick(self, sid: int, gen: int):
        ent = self._pool[sid] if sid < len(self._pool) else None
        st = self._slots.get(sid)
        if not ent or not st or st.get("gen") != gen or st.get("done"):
            return
        try:
            ent["view"].page().runJavaScript(KICK_JS, 0, lambda r: None)
        except Exception:
            pass

    def _on_tick(self):
        if not self._running:
            return
        now = time.time()
        for sid in list(self._slots):
            st = self._slots.get(sid)
            if not st or st.get("done"):
                continue
            if sid < len(self._pool):
                try:
                    self._pool[sid]["view"].page().runJavaScript(
                        PERF_JS, 0,
                        lambda r, s=sid, g=st["gen"]: self._on_perf(s, g, r))
                except Exception:
                    pass
            if now - st["t0"] >= self.MAX_WAIT:
                self._timeout(sid)

    def _on_perf(self, sid: int, gen: int, raw):
        st = self._slots.get(sid)
        if not st or st.get("done") or st.get("gen") != gen:
            return
        d = {}
        try:
            d = json.loads(raw if raw is not None else "{}")
        except Exception:
            d = {}
        if isinstance(d, list):            # 兼容旧格式
            urls, dead, cap, href = d, False, False, ""
        elif isinstance(d, dict):
            urls = d.get("u") or []
            dead = bool(d.get("d"))
            cap = bool(d.get("c"))
            href = d.get("h") or ""
        else:
            urls, dead, cap, href = [], False, False, ""

        # 人机验证要在 href 检查**之前**看：验证可能是整页跳转，
        # 那时 href 已经不含目标 vid，再往下判就全被 return 掉了。
        if cap and not self._captcha_seen:
            self._captcha_seen = True
            runlog.log("resolve", "检测到人机验证（拖动滑块/安全验证）")
            self.sigCaptcha.emit()

        # 视图是复用的：如果当前文档还没切到目标视频，读到的是上一条的数据，
        # 必须丢掉，否则会把上一个视频的直链算到这一条头上。
        if href and st["vid"] not in href:
            return

        added = 0
        for u in urls:
            if _is_media(u) and u not in st["urls"]:
                st["urls"].add(u)
                added += 1
        if added:
            st["last_new"] = time.time()

        picked = pick_streams(list(st["urls"]), st["vid"], self.quality)
        if picked:
            if (time.time() - st["last_new"]) >= self.SILENT:
                self._finish(sid, picked)
            return

        # 页面已经明确说「作品不存在」，就别再干等了
        if dead and (time.time() - st["t0"]) >= self.DEAD_AFTER:
            row = st["row"]
            self._slots.pop(sid, None)
            self._note_fail(sid, row, st["vid"], "作品不存在或已被删除")

    def _timeout(self, sid: int):
        st = self._slots.get(sid)
        if not st or st.get("done"):
            return
        picked = pick_streams(list(st["urls"]), st["vid"], self.quality)
        if picked:
            self._finish(sid, picked)
            return
        if st["retry"] < self.MAX_RETRY:
            st["retry"] += 1
            self.sigProgress.emit(st["row"], "重试中…")
            self._open(sid)
            return
        row = st["row"]
        self._slots.pop(sid, None)
        self._note_fail(sid, row, st["vid"],
                        "未能获取视频地址（可能已删除、私密或需要登录）")

    # ---------------- 失败记录 / 系统性故障判定 ----------------
    def _note_fail(self, sid: int, row: int, vid: str, reason: str):
        """记一次失败；连续失败到阈值就上报「系统性问题」。

        「下到一半整批失败」时，界面只显示一句失败原因会让人无从下手。
        这里把每一条的失败原因 + 页面当时的真实状态（地址/标题/正文片段/
        是否有人机验证）写进日志，并把「连续失败」这件事单独上报，
        由界面停下来给出可操作的建议。
        """
        self._consec += 1
        runlog.log("resolve", "FAIL row=%s vid=%s reason=%s consec=%d"
                   % (row, vid, reason, self._consec))
        self._dump_page(sid, row, vid)
        self.sigFailed.emit(row, reason)
        if self._consec == self.STALL_N:      # 一轮连续失败只上报一次
            runlog.log("resolve",
                       "连续 %d 条拿不到视频流 → 判定为系统性问题" % self._consec)
            self.sigStalled.emit(self._consec)
        self._after_one()

    def _dump_page(self, sid: int, row: int, vid: str):
        """把失败时页面的真实状态写进日志（登录墙？验证码？没加载出来？）"""
        ent = self._pool[sid] if 0 <= sid < len(self._pool) else None
        if not ent:
            return
        try:
            ent["view"].page().runJavaScript(
                DIAG_JS, 0,
                lambda r, rw=row, vv=vid: runlog.log(
                    "page", "row=%s vid=%s %s" % (rw, vv, r)))
        except Exception:
            pass

    def _finish(self, sid: int, picked: Dict[str, Any]):
        st = self._slots.get(sid)
        if not st:
            return
        st["done"] = True
        self._consec = 0                  # 拿到流就重置「连续失败」计数
        # 验证码提醒标记也一并重置：风控可能在同一轮下载里多次出现
        # （上次过完验证、下几百条后又触发），只弹一次会让后续验证被静默吞掉。
        self._captcha_seen = False
        picked["vid"] = st["vid"]
        picked["title"] = st["title"]
        picked["dur"] = st.get("dur", 0) or 0
        row = st["row"]
        runlog.log("resolve", "OK   row=%s vid=%s mode=%s br=%s"
                   % (row, st["vid"], picked.get("mode"), picked.get("br", 0)))
        self.sigProgress.emit(
            row, f"已获取直链（{'分离流' if picked.get('mode') == 'dash' else '合并流'} "
                 f"码率 {picked.get('br', 0)}）")
        self.sigResolved.emit(row, picked)
        self._slots.pop(sid, None)
        self._after_one()

    def _after_one(self):
        if not self._running:
            return
        if self.queue:
            self._fill()
            return
        if not self._slots:
            self._running = False
            self._timer.stop()
            self._idle_pool()
            self.sigAllDone.emit()
