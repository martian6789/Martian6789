# -*- coding: utf-8 -*-
"""测速：默认 vs 关闭图片加载，看首个 douyinvod 流出现的时间。

用法：probe_noimg.py <vid> [default|noimg]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QUrl                              # noqa: E402
from PySide6.QtWidgets import QApplication                           # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineSettings               # noqa: E402

from app.webengine import make_view                                  # noqa: E402

VID = sys.argv[1] if len(sys.argv) > 1 else "7028953425052323087"
MODE = sys.argv[2] if len(sys.argv) > 2 else "default"

PROBE = r"""
(function(){
  try {
    var r = performance.getEntriesByType('resource'), i, n, o = 0;
    for (i = 0; i < r.length; i++) {
      n = r[i].name; if (n.indexOf('douyinvod') >= 0) o++;
    }
    return JSON.stringify({vod: o, res: r.length});
  } catch(e) { return JSON.stringify({err: String(e)}); }
})()
"""

START = time.time()


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


app = QApplication(sys.argv[:1])
view = make_view()
view.resize(1000, 700)
if MODE == "noimg":
    view.page().settings().setAttribute(
        QWebEngineSettings.WebAttribute.AutoLoadImages, False)
    log("图片加载已关闭")
log("加载 %s" % VID)
view.loadFinished.connect(lambda ok: log("loadFinished ok=%s" % ok))
view.load(QUrl("https://www.douyin.com/video/%s" % VID))

st = {"n": 0, "first": None}


def poll():
    st["n"] += 1
    if st["n"] > 34:
        log("结果：首个流在第 %s 秒" % st["first"])
        app.quit()
        return
    view.page().runJavaScript(PROBE, 0, cb)


def cb(raw):
    try:
        d = json.loads(raw or "{}")
    except Exception:
        d = {}
    if d.get("vod") and st["first"] is None:
        st["first"] = st["n"]
        log("   >>> 首个 douyinvod 流出现，res=%(res)s vod=%(vod)s" % d)
    elif st["n"] % 4 == 0:
        log("   res=%(res)s vod=%(vod)s" % d)


t = QTimer()
t.timeout.connect(poll)
t.start(1000)
app.exec()
