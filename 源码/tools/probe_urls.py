# -*- coding: utf-8 -*-
"""诊断 2：记录页面发出的**全部** XHR / fetch URL，找出作品列表真正的加载接口。

同时统计滚动过程中视频链接数的增长，判断列表是网络加载还是服务端直出。
"""
import json
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer, QUrl                      # noqa: E402
from PySide6.QtWebEngineCore import (QWebEnginePage,         # noqa: E402
                                     QWebEngineProfile,
                                     QWebEngineScript)
from PySide6.QtWebEngineWidgets import QWebEngineView        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.config import UA, profile_dir                       # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

RECORDER = r"""
(function(){
  if (window.__rec) return;
  window.__rec = {xhr: [], fetch: null, fetchOk: false, json: []};
  var R = window.__rec;
  function push(arr, s){ if (arr.length < 400) arr.push(s); }

  try {
    var XO = window.XMLHttpRequest;
    if (XO && XO.prototype && !XO.prototype.__recPatched){
      XO.prototype.__recPatched = 1;
      var P = XO.prototype, oOpen = P.open;
      P.open = function(m, u){
        try { push(R.xhr, String(u || '')); } catch(e){}
        var self = this;
        try {
          if (!self.__recBound){
            self.__recBound = 1;
            self.addEventListener('load', function(){
              try {
                var t = self.responseText || '';
                if (t && t.charAt(0) === '{' && t.length > 500){
                  push(R.json, (self.__recUrl || '') + '  ||  len=' + t.length);
                }
              } catch(e){}
            });
          }
          self.__recUrl = String(u || '');
        } catch(e){}
        return oOpen.apply(this, arguments);
      };
    }
  } catch(e){}

  try {
    R.fetchOk = !!window.fetch;
    if (window.fetch && !window.fetch.__recPatched){
      var of = window.fetch;
      var nf = function(){
        var u = '';
        try {
          var a0 = arguments[0];
          u = (a0 && typeof a0 === 'object' && a0.url) ? String(a0.url) : String(a0 || '');
        } catch(e){}
        push(R.xhr, '[fetch] ' + u);
        R.fetch = 'patched';
        return of.apply(window, arguments);
      };
      nf.__recPatched = 1;
      window.fetch = nf;
      R.fetch = 'ok';
    } else {
      R.fetch = 'skip(no fetch or already patched)';
    }
  } catch(e){ R.fetch = 'ERR ' + e.message; }
})()
"""

STEP_JS = r"""
(function(){
  var ih = window.innerHeight || 800;
  var el = null;
  try {
    var seed = document.querySelector('ul[data-e2e="scroll-list"]')
            || document.querySelector('[data-e2e="user-post-list"]')
            || document.querySelector('#slidelist');
    var p = seed;
    while (p && p !== document.body && p !== document.documentElement){
      if (p.scrollHeight > p.clientHeight + 80){ el = p; break; }
      p = p.parentElement;
    }
  } catch(e){}
  if (el){ el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.floor(el.clientHeight * 0.9)); }
  else { window.scrollBy(0, Math.max(600, Math.floor(ih * 1.2))); }

  var R = window.__rec || {xhr: [], json: []};
  var uniq = {}, ux = [];
  for (var i = 0; i < R.xhr.length; i++){
    var k = String(R.xhr[i]).split('?')[0];
    if (!uniq[k]){ uniq[k] = 1; ux.push(k); }
  }
  return JSON.stringify({
    links: document.querySelectorAll('a[href*="/video/"]').length,
    xhrTotal: R.xhr.length,
    uniq: ux,
    json: R.json.slice(-40),
    fetchState: R.fetch
  });
})()
"""


def main():
    app = QApplication(sys.argv)
    prof = QWebEngineProfile("probe2", app)
    prof.setPersistentStoragePath(profile_dir())
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("recorder")
    sc.setSourceCode(RECORDER)
    sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    sc.setRunsOnSubFrames(True)
    sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    prof.scripts().insert(sc)

    view = QWebEngineView()
    view.setPage(QWebEnginePage(prof, view))
    view.resize(1280, 900)
    view.show()

    st = {"n": 0}

    def step():
        st["n"] += 1

        def cb(raw):
            try:
                d = json.loads(raw)
            except Exception:
                d = {}
            print("step %2d links=%-5s xhrTotal=%-4s fetch=%s"
                  % (st["n"], d.get("links"), d.get("xhrTotal"),
                     d.get("fetchState")), flush=True)
            if st["n"] in (1, 3, 6, 10, 15, 20):
                print("   接口(去重):", flush=True)
                for u in (d.get("uniq") or []):
                    print("      ", u, flush=True)
                print("   大 JSON 响应:", flush=True)
                for j in (d.get("json") or []):
                    print("      ", j, flush=True)
            if st["n"] >= 20:
                app.quit()
            else:
                QTimer.singleShot(800, step)

        view.page().runJavaScript(STEP_JS, 0, cb)

    def on_load(ok):
        print("loadFinished =", ok, flush=True)
        QTimer.singleShot(6000, step)

    view.loadFinished.connect(on_load)
    view.load(QUrl(URL))
    QTimer.singleShot(180000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
