# -*- coding: utf-8 -*-
"""诊断：打开主播主页，检查登录态 / 页面状态 / 接口捕获情况（标准事件循环）"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.webengine import ProfileManager

pm = ProfileManager.instance()

URL = (sys.argv[1] if len(sys.argv) > 1 else
       "https://www.douyin.com/user/MS4wLjABAAAAofJ9HDJwdACju_MpRu9FaP3a6wEpMSDn0SwH5hg6EbMh-e_171MkhhsY1nSfxo-F")

URLS = []
pm.interceptor.set_sink(lambda u: URLS.append(u))

view = pm.new_view()
view.resize(1280, 900)
view.show()
loaded = {"ok": None}
view.loadFinished.connect(lambda ok: loaded.update(ok=ok))

PROBE = ("(function(){try{var m=window.__dyMeta||{};"
         "return JSON.stringify({url:location.href,title:document.title.slice(0,50),"
         "h:document.body?document.body.scrollHeight:0,"
         "n:document.querySelectorAll('a[href*=\"/video/\"]').length,"
         "api:(window.__dyOrder||[]).length,calls:m.calls||0,"
         "author:(window.__dyAuthor||'').slice(0,36),"
         "text:(document.body?document.body.innerText.replace(/\\s+/g,' ').slice(0,100):'')});"
         "}catch(e){return 'ERR '+e;}})()")


def report(tag):
    def got(r):
        print(f"\n[{tag}]")
        try:
            d = json.loads(r)
            for k, v in d.items():
                print(f"   {k}: {v}")
        except Exception:
            print("   raw:", r)
        print(f"   已捕获请求 {len(URLS)} 条, aweme/post "
              f"{len([u for u in URLS if 'aweme/post' in u])} 次"
              f", loaded={loaded['ok']}")

    view.page().runJavaScript(PROBE, 0, got)


def start():
    print(f"启动时 cookie {len(pm.cookie_dict)} 条, logged_in={pm.logged_in}")
    view.load(QUrl(URL))
    QTimer.singleShot(6000, lambda: report("6s"))


def s2():
    report("12s")


def fin():
    report("18s")
    print(f"\ncookie 总数: {len(pm.cookie_dict)}  logged_in={pm.logged_in}")
    for u in [x for x in URLS if "aweme/post" in x][:2]:
        print("  post:", u[:150])
    app.quit()


QTimer.singleShot(1000, start)
QTimer.singleShot(12000, s2)
QTimer.singleShot(18000, fin)
QTimer.singleShot(60000, app.quit)
app.exec()
