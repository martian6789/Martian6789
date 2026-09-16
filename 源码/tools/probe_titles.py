# -*- coding: utf-8 -*-
"""诊断探针：抓取指定主播主页的原始 aweme/post 响应，回答两个问题：

1. 为什么有些视频标题是空的（desc 为空时还有哪些字段可用）？
2. 页面显示的作品数 vs 实际捕获数是否一致，差在哪？

使用配置目录的**副本**，避免与正在运行的下载器抢同一个 profile。
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer, QUrl                      # noqa: E402
from PySide6.QtWebEngineCore import (QWebEngineProfile,     # noqa: E402
                                     QWebEngineScript)
from PySide6.QtWebEngineWidgets import QWebEngineView        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.config import UA, profile_dir                       # noqa: E402
from app.scraper import SCROLL_JS                            # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

# ---- 探针钩子：不做作者过滤，记录全部条目 + 元信息 ----
HOOK = r"""
(function(){
  if (window.__pAll) return;
  window.__pAll = {};
  window.__pOrder = [];
  window.__pMeta = {calls: 0, has_more: 1, noid: 0, eps: {}};

  function addList(list){
    if (!list || !list.length) return;
    for (var i = 0; i < list.length; i++){
      var a = list[i];
      if (!a) continue;
      var id = a.aweme_id || (a.aweme_info && a.aweme_info.aweme_id);
      if (!id){ window.__pMeta.noid++; continue; }
      if (!window.__pAll[id]){ window.__pAll[id] = a; window.__pOrder.push(id); }
    }
  }

  function handle(url, txt){
    if (!txt || typeof txt !== 'string') return;
    if (txt.length < 20 || txt.charAt(0) !== '{') return;
    var o = null;
    try { o = JSON.parse(txt); } catch(e){ return; }
    if (!o || typeof o !== 'object') return;
    var u = String(url || '');
    var ep = u.split('?')[0];
    if (/aweme\/(post|detail)/i.test(u)){
      window.__pMeta.eps[ep] = (window.__pMeta.eps[ep] || 0) + 1;
    }
    var isPost = /aweme\/post/i.test(u);
    if (o.aweme_list) addList(o.aweme_list);
    if (o.data && o.data.aweme_list) addList(o.data.aweme_list);
    if (o.awemeList) addList(o.awemeList);
    if (isPost){
      var m = window.__pMeta;
      m.calls += 1;
      var hm = (typeof o.has_more !== 'undefined') ? o.has_more
             : (o.data && typeof o.data.has_more !== 'undefined') ? o.data.has_more : null;
      if (hm !== null && typeof hm !== 'undefined') m.has_more = hm ? 1 : 0;
    }
  }

  function readResp(x){
    try {
      if (x.responseType && x.responseType !== '' && x.responseType !== 'text'){
        try { return JSON.stringify(x.response); } catch(e){ return ''; }
      }
      return x.responseText;
    } catch(e){ return ''; }
  }

  try {
    var XO = window.XMLHttpRequest;
    if (XO && XO.prototype && !XO.prototype.__pPatched){
      XO.prototype.__pPatched = 1;
      var P = XO.prototype, origOpen = P.open;
      P.open = function(){
        try { this.__pUrl = String(arguments[1] || ''); } catch(e){}
        try {
          var self = this;
          if (!self.__pBound){
            self.__pBound = 1;
            self.addEventListener('load', function(){
              try { handle(self.__pUrl, readResp(self)); } catch(e){}
            });
          }
        } catch(e){}
        return origOpen.apply(this, arguments);
      };
    }
  } catch(e){}

  try {
    if (window.fetch && !window.fetch.__pPatched){
      var of = window.fetch;
      var nf = function(){
        var u = '';
        try {
          var a0 = arguments[0];
          u = (a0 && typeof a0 === 'object' && a0.url) ? String(a0.url) : String(a0 || '');
        } catch(e){}
        var p;
        try { p = of.apply(window, arguments); } catch(e){ return of.apply(window, arguments); }
        try {
          p.then(function(r){
            try { r.clone().text().then(function(t){ handle(u, t); }); } catch(e){}
            return r;
          });
        } catch(e){}
        return p;
      };
      nf.__pPatched = 1;
      window.fetch = nf;
    }
  } catch(e){}
})()
"""

DUMP_JS = r"""
(function(){
  var out = [];
  var ord = window.__pOrder || [];
  for (var i = 0; i < ord.length; i++){
    var a = window.__pAll[ord[i]];
    if (!a) continue;
    var v = a.video || {}, au = a.author || {};
    out.push({
      i: i,
      id: String(a.aweme_id || ''),
      desc: (typeof a.desc === 'undefined') ? null : a.desc,
      item_title: (typeof a.item_title === 'undefined') ? null : a.item_title,
      preview_title: (typeof a.preview_title === 'undefined') ? null : a.preview_title,
      caption: (typeof a.caption === 'undefined') ? null : a.caption,
      seo_title: a.seo_info ? a.seo_info.title : null,
      text_extra: (a.text_extra || []).map(function(x){
        return x.hashtag_name || x.text || ''; }).filter(function(s){ return s; }),
      is_top: a.is_top || 0,
      aweme_type: a.aweme_type,
      imgs: (a.images || []).length,
      ct: a.create_time || 0,
      dur: v.duration || 0,
      au: String(au.sec_uid || au.uid || ''),
      nick: String(au.nickname || ''),
      keys: Object.keys(a)
    });
  }
  var txt = '';
  try { txt = (document.body ? document.body.innerText : '').slice(0, 2000); } catch(e){}
  var cnt = null;
  try {
    var els = document.querySelectorAll('[data-e2e]');
    for (var k = 0; k < els.length; k++){
      var de = els[k].getAttribute('data-e2e') || '';
      if (de.indexOf('tab') >= 0 || de.indexOf('count') >= 0){
        var t = (els[k].innerText || '').trim();
        if (t && t.length < 30) { cnt = (cnt || '') + '[' + de + '=' + t + ']'; }
      }
    }
  } catch(e){}
  return JSON.stringify({
    n: out.length, meta: window.__pMeta || {},
    page: txt, tabcount: cnt, items: out
  });
})()
"""


def main():
    app = QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="dyprobe_")
    dst = os.path.join(tmp, "WebProfile")
    shutil.copytree(profile_dir(), dst)
    print("profile 副本:", dst)

    prof = QWebEngineProfile("probe", app)
    prof.setPersistentStoragePath(dst)
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("probe_hook")
    sc.setSourceCode(HOOK)
    sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    sc.setRunsOnSubFrames(True)
    sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    prof.scripts().insert(sc)

    from PySide6.QtWebEngineCore import QWebEnginePage
    view = QWebEngineView()
    view.setPage(QWebEnginePage(prof, view))
    view.resize(1280, 900)
    view.show()

    state = {"steps": 0, "last": -1, "no_new": 0, "calls": -1}

    def run_js(js, cb):
        view.page().runJavaScript(js, 0, cb)

    def dump():
        def on_dump(raw):
            try:
                d = json.loads(raw)
            except Exception as e:
                print("解析失败:", e, repr(raw)[:200])
                app.quit()
                return
            items = d.get("items", [])
            print("\n================ 结果 ================")
            print("捕获条目数 n =", d.get("n"))
            print("meta =", json.dumps(d.get("meta", {}), ensure_ascii=False))
            print("tabcount =", d.get("tabcount"))
            print("\n---- 页面可见文本（前 700 字）----")
            print((d.get("page") or "")[:700])
            empty = [it for it in items if not (it.get("desc") or "").strip()]
            print("\n---- desc 为空的条目: %d / %d ----" % (len(empty), len(items)))
            for it in empty[:15]:
                print("  id=%s dur=%s ct=%s top=%s type=%s imgs=%s nick=%s"
                      % (it["id"], it["dur"], it["ct"], it["is_top"],
                         it["aweme_type"], it["imgs"], it["nick"]))
                print("     desc=%r item_title=%r preview=%r caption=%r seo=%r te=%s"
                      % (it["desc"], it["item_title"], it["preview_title"],
                         it["caption"], it["seo_title"], it["text_extra"]))
            keys = set()
            for it in items:
                keys.update(it.get("keys") or [])
            print("\n---- 全部出现过的字段（%d 个）----" % len(keys))
            print(sorted(keys))
            with open(os.path.join(ROOT, "tools", "probe_dump.json"), "w",
                      encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            print("\n原始数据已写入 tools/probe_dump.json")
            app.quit()

        run_js(DUMP_JS, on_dump)

    def step():
        state["steps"] += 1

        def on_scrolled(raw):
            try:
                s = json.loads(raw)
            except Exception:
                s = {}
            total = int(s.get("total", -1))
            calls = int(s.get("calls", 0))
            more = int(s.get("has_more", -1))
            print("step %d: captured=%d calls=%d has_more=%d dom=%s"
                  % (state["steps"], total, calls, more, s.get("n")))
            grew = total > state["last"] or calls != state["calls"]
            state["no_new"] = 0 if grew else state["no_new"] + 1
            state["last"], state["calls"] = total, calls
            done = (more == 0) or state["steps"] >= 120 or state["no_new"] >= 12
            if done:
                print("滚动结束，开始导出…")
                QTimer.singleShot(2500, dump)
            else:
                QTimer.singleShot(900, step)

        run_js(SCROLL_JS, on_scrolled)

    def on_loaded(ok):
        print("loadFinished ok =", ok)
        if not ok:
            print("页面加载失败")
            app.quit()
            return
        QTimer.singleShot(5000, step)

    view.loadFinished.connect(on_loaded)
    view.load(QUrl(URL))
    QTimer.singleShot(300000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
