# -*- coding: utf-8 -*-
"""诊断 3：专门抓 aweme/post 请求的状态码 / responseType / 响应体长度。

回答：为什么列表在增长，但我们读不到 aweme_list。
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

SPY = r"""
(function(){
  if (window.__spy) return;
  window.__spy = {post: [], all: 0, listLen: []};
  var S = window.__spy;

  function info(x, url){
    var rec = {u: String(url || '').split('?')[0], status: -1,
               rtype: null, tlen: -1, rlen: -1, head: '', err: ''};
    try { rec.status = x.status; } catch(e){ rec.err += 'status:' + e.message; }
    try { rec.rtype = x.responseType === '' ? 'text' : x.responseType; } catch(e){}
    try {
      var t = x.responseText;
      rec.tlen = (t === null || typeof t === 'undefined') ? -2 : t.length;
      rec.head = String(t || '').slice(0, 160);
    } catch(e){ rec.tlen = -3; rec.err += ' text:' + e.message; }
    try {
      var r = x.response;
      if (r && typeof r === 'object' && !(r instanceof ArrayBuffer)){
        var s = JSON.stringify(r);
        rec.rlen = (s || '').length;
        if (!rec.head) rec.head = (s || '').slice(0, 160);
      } else if (r instanceof ArrayBuffer){ rec.rlen = -10; rec.head = 'ArrayBuffer'; }
    } catch(e){ rec.err += ' resp:' + e.message; }
    return rec;
  }

  try {
    var XO = window.XMLHttpRequest;
    if (XO && XO.prototype && !XO.prototype.__spyPatched){
      XO.prototype.__spyPatched = 1;
      var P = XO.prototype, oOpen = P.open;
      P.open = function(m, u){
        var self = this;
        S.all += 1;
        try {
          self.__spyUrl = String(u || '');
          if (!self.__spyBound){
            self.__spyBound = 1;
            self.addEventListener('loadend', function(){
              try {
                var r = info(self, self.__spyUrl);
                if (r.u.indexOf('aweme/post') >= 0){ if (S.post.length < 60) S.post.push(r); }
              } catch(e){}
            });
          }
        } catch(e){}
        return oOpen.apply(this, arguments);
      };
    }
  } catch(e){}

  // DOM 层面统计每个卡片容器里的条目数
  function stat(){
    var sels = ['ul[data-e2e="scroll-list"] li',
                '[data-e2e="user-post-list"] li',
                'a[href*="/video/"]'];
    var o = {};
    for (var i = 0; i < sels.length; i++){
      try { o[sels[i]] = document.querySelectorAll(sels[i]).length; } catch(e){ o[sels[i]] = -1; }
    }
    S.listLen.push(o);
    return o;
  }
  window.__spyStat = stat;

  try {
    var XO2 = window.XMLHttpRequest;   // fetch 也顺手记一下
    S.fetchOk = !!window.fetch;
  } catch(e){}
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
  var st = window.__spyStat ? window.__spyStat() : {};
  var S = window.__spy || {post: [], all: 0};
  return JSON.stringify({dom: st, xhrAll: S.all, posts: S.post});
})()
"""


def main():
    app = QApplication(sys.argv)
    prof = QWebEngineProfile("probe3", app)
    prof.setPersistentStoragePath(profile_dir())
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("spy")
    sc.setSourceCode(SPY)
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
            except Exception as e:
                print("parse err", e); app.quit(); return
            print("step %2d dom=%s xhrAll=%s posts=%d"
                  % (st["n"], json.dumps(d.get("dom"), ensure_ascii=False),
                     d.get("xhrAll"), len(d.get("posts") or [])), flush=True)
            posts = d.get("posts") or []
            if posts:
                for p in posts[-6:]:
                    print("     POST", json.dumps(p, ensure_ascii=False)[:400], flush=True)
            if st["n"] >= 8:
                app.quit()
            else:
                QTimer.singleShot(900, step)

        view.page().runJavaScript(STEP_JS, 0, cb)

    def on_load(ok):
        print("loadFinished =", ok, flush=True)
        QTimer.singleShot(6000, step)

    view.loadFinished.connect(on_load)
    view.load(QUrl(URL))
    QTimer.singleShot(120000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
