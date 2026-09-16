# -*- coding: utf-8 -*-
"""验证：打开若干"空标题"视频的详情页，看抖音上是否真的有文案。

同时对比列表接口返回的 desc 是否被裁剪（详情接口通常更完整）。
"""
import json
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer, QUrl                      # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.webengine import make_view                          # noqa: E402

TARGETS = [
    "6652175997519039747",
    "6650721223040978179",
    "6649977147203095822",
    "7359798501699570979",
]

PROBE = r"""
(function(){
  // 详情页里抖音自己渲染的文案区域
  var out = {title: document.title, href: location.href, descs: []};
  var sels = ['[data-e2e="video-desc"]', '[data-e2e="detail-video-desc"]',
              'h1', '[data-e2e="user-detail"] span'];
  for (var i = 0; i < sels.length; i++){
    var ns = document.querySelectorAll(sels[i]);
    for (var j = 0; j < ns.length && j < 4; j++){
      var t = (ns[j].innerText || '').trim();
      if (t) out.descs.push(sels[i] + ' => ' + t.slice(0, 160));
    }
  }
  // 详情接口里的 desc
  try {
    var st = window.__dyDetail || null;
    out.detailDesc = st ? st.desc : null;
    out.detailKeys = st ? Object.keys(st).slice(0, 30) : null;
  } catch(e){}
  return JSON.stringify(out);
})()
"""

HOOK_DETAIL = r"""
(function(){
  if (window.__dyDetailHooked) return;
  window.__dyDetailHooked = 1;
  function handle(url, txt){
    if (!txt || typeof txt !== 'string') return;
    if (txt.length < 20 || txt.charAt(0) !== '{') return;
    if (String(url).indexOf('aweme/detail') < 0) return;
    var o = null;
    try { o = JSON.parse(txt); } catch(e){ return; }
    var a = o.aweme_detail || (o.data && o.data.aweme_detail);
    if (!a) return;
    window.__dyDetail = {id: String(a.aweme_id || ''), desc: a.desc,
                         item_title: a.item_title, caption: a.caption,
                         preview_title: a.preview_title,
                         seo: a.seo_info ? a.seo_info.title : null};
  }
  var XO = window.XMLHttpRequest;
  try {
    var oOpen = XO.prototype.open;
    XO.prototype.open = function(m, u){
      var self = this;
      try {
        self.__u = String(u || '');
        if (!self.__b){
          self.__b = 1;
          self.addEventListener('load', function(){
            try { handle(self.__u, self.responseText); } catch(e){}
          });
        }
      } catch(e){}
      return oOpen.apply(this, arguments);
    };
  } catch(e){}
})()
"""


def main():
    from PySide6.QtWebEngineCore import QWebEngineScript
    from app.webengine import ProfileManager

    app = QApplication(sys.argv)
    host = QWidget()
    host.resize(1100, 800)
    host.show()

    prof = ProfileManager.instance().profile
    sc = QWebEngineScript()
    sc.setName("detail_hook")
    sc.setSourceCode(HOOK_DETAIL)
    sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    sc.setRunsOnSubFrames(True)
    sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    prof.scripts().insert(sc)

    view = make_view(host)
    view.resize(1100, 800)
    view.show()

    st = {"i": -1}

    def next_one():
        st["i"] += 1
        if st["i"] >= len(TARGETS):
            app.quit()
            return
        vid = TARGETS[st["i"]]
        print("\n===== 打开视频页 %s =====" % vid, flush=True)

        def on_load(ok):
            print("loadFinished =", ok, flush=True)
            QTimer.singleShot(9000, report)

        def report():
            def cb(raw):
                try:
                    d = json.loads(raw)
                except Exception:
                    d = {}
                print("  document.title:", d.get("title"), flush=True)
                for x in (d.get("descs") or []):
                    print("  页面文本:", x, flush=True)
                print("  详情接口 desc:", repr(d.get("detailDesc")), flush=True)
                if d.get("detailKeys"):
                    print("  详情字段:", d["detailKeys"], flush=True)
                try:
                    view.loadFinished.disconnect(on_load)
                except Exception:
                    pass
                QTimer.singleShot(800, next_one)

            view.page().runJavaScript(PROBE, 0, cb)

        view.loadFinished.connect(on_load)
        view.load(QUrl("https://www.douyin.com/video/" + vid))

    QTimer.singleShot(1500, next_one)
    QTimer.singleShot(300000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
