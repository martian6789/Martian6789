# -*- coding: utf-8 -*-
"""对比：隐藏视图 vs WA_DontShowOnScreen+show()，逐秒打印，看得到活性。

用法：probe_fast.py <vid> hidden|shown|hidden_play
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import Qt, QTimer, QUrl                          # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402

from app.webengine import make_view                                  # noqa: E402

VID = sys.argv[1] if len(sys.argv) > 1 else "7028953425052323087"
MODE = sys.argv[2] if len(sys.argv) > 2 else "hidden"

PROBE = r"""
(function(){
  try {
    var r = performance.getEntriesByType('resource'), i, n, out = 0;
    for (i = 0; i < r.length; i++) {
      n = r[i].name;
      if (n.indexOf('douyinvod') >= 0) out++;
    }
    var v = document.querySelector('video');
    return JSON.stringify({vod: out, res: r.length,
      vis: document.visibilityState, hid: document.hidden,
      vw: v ? v.videoWidth : -1, rs: v ? v.readyState : -1,
      src: v ? (v.currentSrc || '').slice(0, 60) : ''});
  } catch(e) { return JSON.stringify({err: String(e)}); }
})()
"""

START = time.time()


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


app = QApplication(sys.argv[:1])

if MODE == "shown":
    view = make_view(offscreen=True)
else:
    view = make_view()
view.resize(1000, 700)
log("模式=%s  isVisible=%s" % (MODE, view.isVisible()))
log("加载 https://www.douyin.com/video/%s" % VID)
view.loadFinished.connect(lambda ok: log("loadFinished ok=%s" % ok))
view.load(QUrl("https://www.douyin.com/video/%s" % VID))

tick = {"n": 0, "first": None}


def poll():
    tick["n"] += 1
    if tick["n"] > 40:
        log("结束（首个流在第 %s 秒拿到）" % tick["first"])
        app.quit()
        return
    view.page().runJavaScript(PROBE, 0, cb)
    if MODE in ("shown", "hidden_play") and tick["n"] % 4 == 0:
        view.page().runJavaScript(
            "(function(){var v=document.querySelector('video');"
            "if(v){v.muted=true;v.volume=0;try{v.play()}catch(e){}}return 1;})()",
            0, lambda r: None)


def cb(raw):
    try:
        d = json.loads(raw or "{}")
    except Exception:
        d = {}
    log("res=%-4s vod=%-3s vis=%-8s hidden=%-5s vw=%-5s readyState=%s"
        % (d.get("res"), d.get("vod"), d.get("vis"), d.get("hid"),
           d.get("vw"), d.get("rs")))
    if d.get("vod") and tick["first"] is None:
        tick["first"] = tick["n"]
        log("   >>> 首个 douyinvod 流出现")
        log("   src=%s" % d.get("src"))


t = QTimer()
t.timeout.connect(poll)
t.start(1000)
app.exec()
