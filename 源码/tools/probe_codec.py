# -*- coding: utf-8 -*-
"""探测内置浏览器（QtWebEngine）支持哪些视频/音频编解码。

抖音的视频是 H.264 + AAC。如果 QtWebEngine 编译时没带 proprietary
codecs，页面就会显示「不支持的音频/视频格式」——解析不受影响
（只需要页面发起 douyinvod 网络请求，不需要解码播放），但用户看着
播放器是黑的。

用法：python tools/probe_codec.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --no-sandbox --disable-dev-shm-usage")

from PySide6.QtCore import QTimer, QUrl          # noqa: E402
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

PROBE_JS = r"""
(function(){
  var v = document.createElement('video');
  var a = document.createElement('audio');
  return JSON.stringify({
    h264: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
    h264hi: v.canPlayType('video/mp4; codecs="avc1.640028"'),
    hevc: v.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"'),
    aac: a.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
    vp9: v.canPlayType('video/webm; codecs="vp9"'),
    opus: a.canPlayType('audio/webm; codecs="opus"'),
    ua: navigator.userAgent.match(/Chrom(?:e|ium)\/(\S+)/) ? RegExp.$1 : ''
  });
})();
"""

UA_JS_PROBE = None

app = QApplication(sys.argv)
view = QWebEngineView()
view.load(QUrl("about:blank"))


def report(raw):
    import json
    try:
        d = json.loads(raw or "{}")
    except Exception:
        d = {}
    print("Chromium 版本:", d.get("ua") or "?")
    print()
    rows = [("H.264 (Baseline)", "h264"), ("H.264 (High)", "h264hi"),
            ("HEVC", "hevc"), ("AAC", "aac"),
            ("VP9 (WebM)", "vp9"), ("Opus (WebM)", "opus")]
    print("%-18s %-12s %s" % ("编解码", "canPlayType", "抖音需要"))
    need = {"h264", "h264hi", "aac"}
    for label, k in rows:
        v = d.get(k, "?")
        ok = v not in ("", "?")
        mark = "需要" if k in need else "    "
        print("%-16s %-12s %s  %s" % (label, v or "不支持", mark,
                                      "✅" if ok else "❌"))
    print()
    if d.get("h264") in ("", None) or d.get("aac") in ("", None):
        print("结论：本机 QtWebEngine 不带 H.264/AAC（专有编解码器），")
        print("      内置浏览器无法播放抖音视频，但解析/下载不受影响。")
    else:
        print("结论：QtWebEngine 支持 H.264/AAC，播放问题另有原因（如防盗链/网络）。")
    app.quit()


view.loadFinished.connect(
    lambda ok: QTimer.singleShot(300, lambda: view.page().runJavaScript(
        PROBE_JS, 0, report)))
QTimer.singleShot(8000, app.quit)
view.show()
app.exec()
