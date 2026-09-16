# -*- coding: utf-8 -*-
"""诊断 5：遍历主框架 + 所有 iframe，找出 aweme/post 到底在哪个 frame 里完成。

每个 frame 各自记录自己完成的 aweme/post 请求；最后从主框架递归扫描所有 frame 汇报。
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

PERFRAME = r"""
(function(){
  if (window.__pf) return;
  window.__pf = {posts: [], xhrDone: 0};
  var F = window.__pf;

  var XO = window.XMLHttpRequest;
  try {
    var oOpen = XO.prototype.open;
    if (!XO.prototype.__pfPatched){
      XO.prototype.__pfPatched = 1;
      XO.prototype.open = function(m, u){
        var self = this;
        try {
          self.__pfU = String(u || '');
          if (!self.__pfB){
            self.__pfB = 1;
            self.addEventListener('loadend', function(){
              try {
                F.xhrDone += 1;
                var uu = String(self.__pfU || '');
                if (uu.indexOf('aweme/post') >= 0){
                  var t = '';
                  try { t = self.responseText || ''; } catch(e){}
                  var r = {u: uu.split('?')[0], st: self.status, len: t.length,
                           head: String(t).slice(0, 200)};
                  if (F.posts.length < 40) F.posts.push(r);
                }
              } catch(e){}
            });
          }
        } catch(e){}
        return oOpen.apply(this, arguments);
      };
    }
  } catch(e){}

  try {
    var of = window.fetch;
    if (of && !of.__pfFetch){
      var nf = function(){
        var u = '';
        try {
          var a0 = arguments[0];
          u = (a0 && typeof a0 === 'object' && a0.url) ? String(a0.url) : String(a0 || '');
        } catch(e){}
        if (u.indexOf('aweme/post') >= 0){ F.posts.push({u: '[fetch] ' + u.split('?')[0], st: -9, len: -9, head: ''}); }
        return of.apply(window, arguments);
      };
      nf.__pfFetch = 1;
      window.fetch = nf;
    }
  } catch(e){}
})()
"""

SCAN = r"""
(function(){
  var out = [];
  function walk(w, depth, tag){
    if (depth > 4) return;
    var o = {tag: tag, depth: depth, href: '?', pf: 'no', posts: -1,
             xhrDone: -1, links: -1, li: -1, err: ''};
    try {
      o.href = String(w.location.href || '');
      o.pf = typeof w.__pf;
      if (w.__pf){ o.posts = w.__pf.posts.length; o.xhrDone = w.__pf.xhrDone; }
      o.links = w.document.querySelectorAll('a[href*="/video/"]').length;
      o.li = w.document.querySelectorAll('ul[data-e2e="scroll-list"] li').length;
    } catch(e){ o.err = '' + e.message; }
    out.push(o);
    try {
      var fs = w.frames || [];
      for (var i = 0; i < fs.length; i++) walk(fs[i], depth + 1, tag + '.' + i);
    } catch(e){}
  }
  walk(window, 0, 'top');
  // 汇总所有 frame 的 aweme/post 记录
  var allPosts = [];
  try {
    (function collect(w){
      try { if (w.__pf && w.__pf.posts) allPosts = allPosts.concat(w.__pf.posts); } catch(e){}
      try { var fs = w.frames || []; for (var i = 0; i < fs.length; i++) collect(fs[i]); } catch(e){}
    })(window);
  } catch(e){}
  return JSON.stringify({frames: out, allPosts: allPosts.slice(-12),
                         totalPosts: allPosts.length,
                         iframes: document.querySelectorAll('iframe').length});
})()
"""

STEP = r"""
(function(){
  var ih = window.innerHeight || 800;
  var el = null;
  try {
    var seed = document.querySelector('ul[data-e2e="scroll-list"]');
    var p = seed;
    while (p && p !== document.body && p !== document.documentElement){
      if (p.scrollHeight > p.clientHeight + 80){ el = p; break; }
      p = p.parentElement;
    }
  } catch(e){}
  if (el){ el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.floor(el.clientHeight * 0.9)); }
  else { window.scrollBy(0, Math.max(600, Math.floor(ih * 1.2))); }
  return JSON.stringify({li: document.querySelectorAll('ul[data-e2e="scroll-list"] li').length});
})()
"""


def main():
    app = QApplication(sys.argv)
    prof = QWebEngineProfile("probe5", app)
    prof.setPersistentStoragePath(profile_dir())
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("perframe")
    sc.setSourceCode(PERFRAME)
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

        def cb(_):
            def cb2(raw):
                try:
                    d = json.loads(raw)
                except Exception as e:
                    print("err", e, repr(raw)[:200]); app.quit(); return
                print("\n===== step %d  iframes=%s totalPosts=%s ====="
                      % (st["n"], d.get("iframes"), d.get("totalPosts")), flush=True)
                for f in d.get("frames") or []:
                    print("  [%s] d=%s pf=%s posts=%s xhrDone=%s links=%s li=%s %s %s"
                          % (f.get("tag"), f.get("depth"), f.get("pf"), f.get("posts"),
                             f.get("xhrDone"), f.get("links"), f.get("li"),
                             (f.get("href") or "")[:70], f.get("err") or ""), flush=True)
                for p in d.get("allPosts") or []:
                    print("     POST", json.dumps(p, ensure_ascii=False)[:260], flush=True)
                if st["n"] >= 4:
                    app.quit()
                else:
                    QTimer.singleShot(1200, step)

            view.page().runJavaScript(SCAN, 0, cb2)

        view.page().runJavaScript(STEP, 0, cb)

    def on_load(ok):
        print("loadFinished =", ok, flush=True)
        QTimer.singleShot(7000, step)

    view.loadFinished.connect(on_load)
    view.load(QUrl(URL))
    QTimer.singleShot(150000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
