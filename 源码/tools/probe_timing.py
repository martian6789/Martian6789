# -*- coding: utf-8 -*-
"""解析耗时诊断：单条视频，逐 500ms 记录「页面加载 / 静态 JSON / 媒体流」的出现时机。

目的：查清为什么每条视频都要等满 18 秒。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QUrl                             # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from app.webengine import make_view                                 # noqa: E402

VID = sys.argv[1] if len(sys.argv) > 1 else "7028953425052323087"
WHICH = sys.argv[2] if len(sys.argv) > 2 else "page"

URL = ("https://www.iesdouyin.com/share/video/%s" % VID if WHICH == "share"
       else "https://www.douyin.com/video/%s" % VID)

START = time.time()
STATS_JS = r"""
(function(){
  try {
    var out = {res: 0, vod: 0, play: 0, first: '', router: false,
               routerVod: 0, initial: false, videoEl: 0, curSrc: '',
               dl: !!document.querySelector('video'),
               body: (document.body ? document.body.innerText.length : 0)};
    var r = performance.getEntriesByType('resource'), i, n;
    for (i = 0; i < r.length; i++) {
      n = r[i].name;
      if (n.indexOf('douyinvod') >= 0) {
        out.vod++;
        if (!out.first) out.first = n.slice(0, 90);
      }
      if (n.indexOf('play') >= 0) out.play++;
      out.res++;
    }
    var html = document.documentElement ? document.documentElement.innerHTML : '';
    out.router = html.indexOf('_ROUTER_DATA') >= 0;
    out.initial = html.indexOf('__INITIAL_STATE__') >= 0;
    out.routerVod = (html.match(/douyinvod/g) || []).length;
    var v = document.querySelector('video');
    if (v) {
      out.videoEl = 1;
      out.curSrc = (v.currentSrc || v.src || '').slice(0, 90);
    }
    return JSON.stringify(out);
  } catch(e) { return JSON.stringify({err: String(e)}); }
})()
"""


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


def main():
    app = QApplication(sys.argv[:1])
    log("加载 %s" % URL)
    view = make_view()
    view.resize(1000, 700)
    done = {"load": None}

    def on_finish(ok):
        done["load"] = time.time()
        log("loadFinished ok=%s" % ok)

    view.loadFinished.connect(on_finish)
    view.load(QUrl(URL))

    tick = {"n": 0}

    def poll():
        tick["n"] += 1
        if tick["n"] > 60:
            app.quit()
            return
        view.page().runJavaScript(STATS_JS, 0, cb)

    def cb(raw):
        try:
            d = json.loads(raw or "{}")
        except Exception:
            d = {}
        log("res=%-4s vod=%-3s play=%-4s router=%-5s routerVod=%-3s init=%-5s "
            "videoEl=%s body=%s" % (d.get("res"), d.get("vod"), d.get("play"),
                                    d.get("router"), d.get("routerVod"),
                                    d.get("initial"), d.get("videoEl"),
                                    d.get("body")))
        if d.get("first"):
            log("   首个CDN: %s" % d["first"])
        if d.get("curSrc"):
            log("   video.src: %s" % d["curSrc"])

    t = QTimer()
    t.timeout.connect(poll)
    t.start(500)
    QTimer.singleShot(31000, app.quit)
    app.exec()
    log("结束")


if __name__ == "__main__":
    main()
