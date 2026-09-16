# -*- coding: utf-8 -*-
"""诊断：采集时抖音到底调了哪些接口？钩子为什么没命中？

用法：
    python tools/probe_api_urls.py [主页URL] [滚动秒数]

思路：QtWebEngine 的拦截器能看到**所有**请求 URL（包括页面自己发的
XHR/fetch），所以不需要改页面钩子就能知道接口真实长什么样。
同时把页面里 ``__dyMeta`` 读出来，对比「拦截器看到的 post 请求数」和
「钩子实际处理的条数」，就能判断钩子是不是漏了。
"""
import os
import sys
import json
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-dev-shm-usage")

from PySide6.QtCore import QTimer, QUrl                    # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel  # noqa: E402

from app.config import UA                                  # noqa: E402
from app.webengine import ProfileManager                   # noqa: E402
from app.scraper import SCROLL_JS                          # noqa: E402

URL = (sys.argv[1] if len(sys.argv) > 1 else
       "https://www.douyin.com/user/MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
       "?from_tab_name=main")
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0

T0 = time.time()


def el():
    return time.time() - T0


seen = []            # (url,) 全部请求
ajax = Counter()     # 疑似接口请求（含 json / aweme / post 等关键词）


def sink(u):
    seen.append(u)
    low = u.lower()
    if any(k in low for k in ("aweme", "/post", "cursor", "count=", "api")):
        # 去掉签名参数，便于归类
        base = u.split("?")[0]
        ajax[base] += 1


app = QApplication(sys.argv)
app.setApplicationName("DouyinProbe")
pm = ProfileManager.instance()
pm.interceptor.set_sink(sink)

host = QWidget()
host.setWindowTitle("API 诊断")
host.resize(1100, 780)
lay = QVBoxLayout(host)
lay.setContentsMargins(0, 0, 0, 0)
tip = QLabel("诊断中…")
tip.setStyleSheet("background:#17191F;color:#E5E7EB;padding:6px 10px;font-size:12px;")
tip.setFixedHeight(30)
lay.addWidget(tip)

view = pm.new_view(host)
lay.addWidget(view, 1)
host.show()

META_JS = ("(function(){try{return JSON.stringify({"
           "meta: window.__dyMeta||null, "
           "order: (window.__dyOrder||[]).length, "
           "posts: Object.keys(window.__dyPosts||{}).length, "
           "hooked: !!window.__dyMeta, "
           "dom: document.querySelectorAll('a[href*=\"/video/\"]').length"
           "});}catch(e){return '{}';}})()")

n_scroll = [0]


def scroll():
    n_scroll[0] += 1
    try:
        view.page().runJavaScript(SCROLL_JS, 0, lambda r: None)
    except Exception:
        pass
    # 每 10 轮汇报一次页面内钩子状态
    if n_scroll[0] % 10 == 0:
        view.page().runJavaScript(META_JS, 0, report)
    tip.setText("诊断中… 第 %d 次滚动（%.0fs）" % (n_scroll[0], el()))


def report(raw):
    try:
        d = json.loads(raw or "{}")
    except Exception:
        d = {}
    print("[%6.1fs] 页面内钩子: hooked=%s order=%s posts=%s dom=%s meta=%s"
          % (el(), d.get("hooked"), d.get("order"), d.get("posts"),
             d.get("dom"), d.get("meta")), flush=True)


def finish():
    print("\n" + "=" * 70, flush=True)
    print("总请求数: %d" % len(seen), flush=True)
    print("\n=== 疑似接口请求 TOP 30 ===", flush=True)
    for u, c in ajax.most_common(30):
        print("  %4d  %s" % (c, u), flush=True)

    print("\n=== 含 aweme 的全部请求（前 20 条完整 URL，看签名）===", flush=True)
    n = 0
    for u in seen:
        if "aweme" in u.lower():
            print("  %s" % u[:180], flush=True)
            n += 1
            if n >= 20:
                break
    if n == 0:
        print("  （一个都没有）", flush=True)

    print("\n=== 最后一次页面内钩子状态 ===", flush=True)
    view.page().runJavaScript(META_JS, 0, lambda r: (report(r), app.quit()))


view.load(QUrl(URL))
tm = QTimer()
tm.timeout.connect(scroll)
tm.setInterval(1000)
QTimer.singleShot(4000, lambda: tm.start())
QTimer.singleShot(int(SECS * 1000) + 5000, finish)
# 兜底退出
QTimer.singleShot(int(SECS * 1000) + 20000, app.quit)
app.exec()
