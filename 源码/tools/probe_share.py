# -*- coding: utf-8 -*-
"""探测：用内置浏览器的登录 Cookie，直接 HTTP 请求分享页拿直链（不开浏览器）"""
import os
import re
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

app = QApplication(sys.argv)

from app.webengine import ProfileManager
pm = ProfileManager.instance()

# 等待 cookie 加载
loop = QEventLoop()
QTimer.singleShot(3000, loop.quit)
loop.exec()

print("logged_in:", pm.logged_in)
print("cookie 数量:", len(pm.cookie_dict))

import requests

S = requests.Session()
S.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
})
S.cookies.update(pm.cookie_dict)

VID = sys.argv[1] if len(sys.argv) > 1 else "7650636256003016049"

for tpl in ("https://www.iesdouyin.com/share/video/{v}",
            "https://www.douyin.com/video/{v}"):
    url = tpl.format(v=VID)
    try:
        r = S.get(url, timeout=20, allow_redirects=True)
    except Exception as e:
        print(f"\n[{tpl}] 请求异常: {e}")
        continue
    print(f"\n=== {tpl}")
    print("  status:", r.status_code, "len:", len(r.content), "final:", r.url[:110])
    txt = r.text
    print("  含 _ROUTER_DATA:", "_ROUTER_DATA" in txt)
    print("  含 play_addr:", "play_addr" in txt)
    print("  含 url_list:", "url_list" in txt)
    m = re.search(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", txt, re.S)
    if m:
        print("  ROUTER_DATA 长度:", len(m.group(1)))
        try:
            d = json.loads(m.group(1))
            keys = list(d.keys())
            print("  顶层键:", keys)
            loader = d.get("loaderData", {})
            print("  loaderData 键:", list(loader.keys())[:6])
        except Exception as e:
            print("  JSON 解析失败:", e)
    if not m:
        print("  头部 300 字符:", txt[:300].replace("\n", " "))
