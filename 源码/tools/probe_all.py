# -*- coding: utf-8 -*-
"""诊断 4：记录**每个**完成的 XHR / fetch 的状态与响应体长度，找出真正携带作品数据的请求。

XHR 用一个"包装类"代替原型补丁，确保 loadend 一定能触发（排除原型被覆盖的情况）。
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

WATCH = r"""
(function(){
  if (window.__w) return;
  window.__w = {done: [], fetchDone: [], frames: 0, err: []};
  var W = window.__w;
  W.isTop = (window === window.top);
  W.href = location.href;

  function rec(x, url, kind){
    var r = {k: kind, p: String(url || '').split('?')[0]};
    try { r.st = x.status; } catch(e){ r.st = -1; }
    try { r.rt = x.responseType || 'text'; } catch(e){ r.rt = '?'; }
    try {
      var t = x.responseText;
      r.len = (t === null || typeof t === 'undefined') ? -2 : t.length;
      r.head = String(t || '').slice(0, 120);
    } catch(e){ r.len = -3; r.head = 'ERR ' + e.message; }
    if (W.done.length < 400) W.done.push(r);
  }

  var XO = window.XMLHttpRequest;
  try {
    XO.prototype.__wrapped = 1;
    var oOpen = XO.prototype.open;
    XO.prototype.open = function(m, u){
      var self = this;
      try {
        self.__u = String(u || '');
        if (!self.__b){
          self.__b = 1;
          var h = function(){ try { rec(self, self.__u, 'xhr'); } catch(e){ W.err.push('' + e); } };
          self.addEventListener('loadend', h);
          self.addEventListener('abort', function(){ W.err.push('abort ' + self.__u); });
          self.addEventListener('error', function(){ W.err.push('error ' + self.__u); });
          self.addEventListener('timeout', function(){ W.err.push('timeout ' + self.__u); });
        }
      } catch(e){ W.err.push('open:' + e); }
      return oOpen.apply(this, arguments);
    };
  } catch(e){ W.err.push('xhr patch: ' + e); }

  try {
    var of = window.fetch;
    if (of && !of.__wrapped){
      var nf = function(){
        var u = '';
        try {
          var a0 = arguments[0];
          u = (a0 && typeof a0 === 'object' && a0.url) ? String(a0.url) : String(a0 || '');
        } catch(e){}
        var p = of.apply(window, arguments);
        try {
          p.then(function(resp){
            try {
              resp.clone().text().then(function(t){
                if (W.fetchDone.length < 300){
                  W.fetchDone.push({p: u.split('?')[0], st: resp.status,
                                    len: (t || '').length,
                                    head: String(t || '').slice(0, 120)});
                }
              }).catch(function(e){ W.err.push('fetch text: ' + e); });
            } catch(e){ W.err.push('fetch clone: ' + e); }
            return resp;
          }).catch(function(e){ W.err.push('fetch rej: ' + e); });
        } catch(e){ W.err.push('fetch then: ' + e); }
        return p;
      };
      nf.__wrapped = 1;
      window.fetch = nf;
    }
  } catch(e){ W.err.push('fetch patch: ' + e); }
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
  var W = window.__w || {done: [], fetchDone: []};
  return JSON.stringify({
    li: document.querySelectorAll('ul[data-e2e="scroll-list"] li').length,
    isTop: W.isTop,
    xhrN: (W.done || []).length,
    fetchN: (W.fetchDone || []).length,
    big: (W.done || []).filter(function(r){ return r.len > 1500; }),
    bigF: (W.fetchDone || []).filter(function(r){ return r.len > 1500; }),
    errs: (W.err || []).slice(0, 12)
  });
})()
"""


def main():
    app = QApplication(sys.argv)
    prof = QWebEngineProfile("probe4", app)
    prof.setPersistentStoragePath(profile_dir())
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("watch")
    sc.setSourceCode(WATCH)
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
            print("step %2d li=%s isTop=%s xhrN=%s fetchN=%s"
                  % (st["n"], d.get("li"), d.get("isTop"),
                     d.get("xhrN"), d.get("fetchN")), flush=True)
            if d.get("errs"):
                print("   errs:", d["errs"], flush=True)
            for r in (d.get("big") or [])[-10:]:
                print("   XHR ", r.get("st"), r.get("rt"), r.get("len"), r.get("p"), flush=True)
                print("        head:", (r.get("head") or "")[:110], flush=True)
            for r in (d.get("bigF") or [])[-10:]:
                print("   FETCH", r.get("st"), r.get("len"), r.get("p"), flush=True)
                print("         head:", (r.get("head") or "")[:110], flush=True)
            if st["n"] >= 6:
                app.quit()
            else:
                QTimer.singleShot(1000, step)

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
