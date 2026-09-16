# -*- coding: utf-8 -*-
"""探测：打开一个视频页，dump 抖音接口返回的原始 JSON（含 play_addr 结构）"""
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QUrl, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.webengine import ProfileManager, make_view

pm = ProfileManager.instance()

URLS = []


def sink(u):
    URLS.append(u)

VID = sys.argv[1] if len(sys.argv) > 1 else "7650636256003016049"
url = f"https://www.douyin.com/video/{VID}"

view = make_view()
view.resize(1280, 900)
pm.interceptor.set_sink(sink)

loaded = {"ok": False}
view.loadFinished.connect(lambda ok: loaded.update(ok=ok))
view.load(QUrl(url))


def wait(ms):
    lp = QEventLoop()
    QTimer.singleShot(ms, lp.quit)
    lp.exec()


wait(12000)
print("loaded:", loaded)

raw = None
lp = QEventLoop()


def got(r):
    global raw
    raw = r
    lp.quit()


view.page().runJavaScript(
    "(function(){try{var v=document.querySelector('video');if(v){v.muted=true;v.play()}"
    "}catch(e){}"
    "return JSON.stringify({cookies:document.cookie.length,"
    "title:document.title,hasVideo:!!document.querySelector('video'),"
    "url:location.href});})()", 0, got)
wait(4000)
print("page:", raw)

wait(6000)

print("\n=== 捕获到的媒体/接口 URL ===")
seen = set()
for u in URLS:
    if any(k in u for k in ("aweme", "douyinvod", "media-video", "media-audio",
                            "play")):
        k = u.split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        print(" ", u[:180])

# dump 钩子捕获的原始 JSON
lp2 = QEventLoop()
res = {"v": None}


def got2(r):
    res["v"] = r
    lp2.quit()


view.page().runJavaScript(
    "(function(){try{var o=window.__dyOrder||[];var out=[];"
    "for(var i=0;i<Math.min(o.length,2);i++){out.push(window.__dyPosts[o[i]]);}"
    "return JSON.stringify({n:o.length,items:out});}catch(e){return 'ERR '+e;}})()",
    0, got2)
wait(5000)
d = res["v"]
if d:
    try:
        obj = json.loads(d)
        print("\n=== 钩子捕获条数:", obj.get("n"))
        if obj.get("items"):
            it = obj["items"][0]
            print("=== 第一条 aweme 字段 ===")
            print(" keys:", sorted(it.keys())[:40])
            v = it.get("video", {})
            print(" video keys:", sorted(v.keys()))
            print(" play_addr:", json.dumps(v.get("play_addr", {}))[:600])
            print(" download_addr:", json.dumps(v.get("download_addr", {}))[:300])
            brs = v.get("bit_rate") or []
            print(" bit_rate 档数:", len(brs))
            for b in brs[:3]:
                print("   gear:", b.get("gear_name"), "br:", b.get("bitrate"))
                print("   ", json.dumps(b.get("play_addr", {}).get("url_list", []))[:400])
            au = it.get("author", {})
            print(" author uid:", au.get("uid"), "sec_uid:", (au.get("sec_uid") or "")[:40])
            print(" author nickname:", au.get("nickname"))
    except Exception as e:
        print("解析失败:", e, repr(d)[:300])
else:
    print("!! 未取到钩子数据")

view.stop()
