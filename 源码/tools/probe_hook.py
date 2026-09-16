# -*- coding: utf-8 -*-
"""诊断：确认注入钩子是否执行、aweme 接口请求是否真的发出。

回答：为什么 probe_titles.py 捕获 0 条。
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
from PySide6.QtWebEngineCore import (QWebEnginePage,         # noqa: E402
                                     QWebEngineProfile,
                                     QWebEngineScript)
from PySide6.QtWebEngineWidgets import QWebEngineView        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.config import UA, profile_dir                       # noqa: E402
from app.scraper import HOOK_JS, SCROLL_JS                   # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

DIAG_JS = r"""
(function(){
  var res = [];
  try {
    var es = performance.getEntriesByType('resource') || [];
    for (var i = 0; i < es.length; i++){
      var n = es[i].name || '';
      if (n.indexOf('/aweme/') >= 0) res.push(n.split('?')[0]);
    }
  } catch(e){}
  var uniq = {};
  var out = [];
  for (var j = 0; j < res.length; j++){ if (!uniq[res[j]]) { uniq[res[j]] = 1; out.push(res[j]); } }
  return JSON.stringify({
    dyHooked: typeof window.__dyHooked,
    dyOrder: (window.__dyOrder ? window.__dyOrder.length : -1),
    dyMeta: window.__dyMeta || null,
    fetchPatched: !!(window.fetch && window.fetch.__dyPatched),
    xhrPatched: !!(window.XMLHttpRequest && window.XMLHttpRequest.prototype.__dyPatched),
    resourceAwemeCount: res.length,
    resourceAwemeUrls: out,
    videoLinks: document.querySelectorAll('a[href*="/video/"]').length,
    readyState: document.readyState
  });
})()
"""


def main():
    use_copy = "--copy" in sys.argv
    app = QApplication(sys.argv)

    if use_copy:
        tmp = tempfile.mkdtemp(prefix="dydiag_")
        path = os.path.join(tmp, "WebProfile")
        shutil.copytree(profile_dir(), path)
    else:
        path = profile_dir()
    print("profile:", path, "(copy)" if use_copy else "(直接使用)")

    prof = QWebEngineProfile("diag", app)
    prof.setPersistentStoragePath(path)
    prof.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    prof.setHttpUserAgent(UA)

    sc = QWebEngineScript()
    sc.setName("dy_hook")
    sc.setSourceCode(HOOK_JS)
    sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    sc.setRunsOnSubFrames(True)
    sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    prof.scripts().insert(sc)
    print("已注入钩子脚本:", sc.name())

    view = QWebEngineView()
    view.setPage(QWebEnginePage(prof, view))
    view.resize(1280, 900)
    view.show()

    def after_load(ok):
        print("loadFinished =", ok)
        QTimer.singleShot(9000, diag)

    def diag():
        def cb(raw):
            print("\n---- 诊断 ----")
            try:
                print(json.dumps(json.loads(raw), ensure_ascii=False, indent=1))
            except Exception:
                print(raw)
            # 再滚一次，看钩子是否开始计数
            def cb2(r2):
                print("\n---- 滚动一次后 ----")
                try:
                    print(json.dumps(json.loads(r2), ensure_ascii=False, indent=1))
                except Exception:
                    print(r2)
                app.quit()
            view.page().runJavaScript(SCROLL_JS, 0, lambda _r: QTimer.singleShot(
                4000, lambda: view.page().runJavaScript(DIAG_JS, 0, cb2)))
        view.page().runJavaScript(DIAG_JS, 0, cb)

    view.loadFinished.connect(after_load)
    view.load(QUrl(URL))
    QTimer.singleShot(120000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
