# -*- coding: utf-8 -*-
"""复现用户操作序列：先滚采集（626 条），再立刻并发解析前 N 条。

目的：验证「采集完立刻下载 → 整批失败」是否可复现，并在失败时把页面真实状态
（location.href / 标题 / 正文片段 / douyinvod 流数量 / 是否有 <video>）打出来。

用法：probe_scrape_then_resolve.py [N] [URL]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
os.environ["DY_DEBUG"] = "1"

from PySide6.QtCore import QTimer, QUrl                               # noqa: E402
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout)    # noqa: E402

from app.scraper import ScrapeController                              # noqa: E402
from app.resolver import ResolveController                            # noqa: E402
from app.webengine import ProfileManager, make_view                   # noqa: E402

URL = (sys.argv[2] if len(sys.argv) > 2
       else "https://www.douyin.com/user/"
            "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 9
SCROLL_LIMIT = 240

START = time.time()

DIAG_JS = ("(function(){try{var r=performance.getEntriesByType('resource'),"
           "o=0,i;for(i=0;i<r.length;i++){if(r[i].name.indexOf('douyinvod')>=0)o++;}"
           "return JSON.stringify({h:location.href,t:document.title,"
           "b:(document.body?(document.body.innerText||''):'').replace(/\\n/g,' ')"
           ".slice(0,150),res:r.length,vod:o,"
           "v:!!document.querySelector('video')});}catch(e){return '{}';}})()")


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


def main():
    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()
    log("登录态 = %s" % pm.logged_in)

    # 复刻应用真实栈：批量下载页常驻一个 douyin.com 浏览器视图
    home = make_view()
    home.resize(1000, 700)
    home.load(QUrl("https://www.douyin.com/"))

    host = QWidget()
    host.setWindowTitle("采集探针（可见）")
    host.resize(1120, 780)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    host.show()

    sc = ScrapeController()
    state = {"items": [], "expected": 0}

    def on_prog(msg):
        if "已采集" in msg:
            try:
                seg = msg.split("已采集")[-1]
                a, b = seg.split("/")
                log("采集进度 %s/%s" % (a.strip(), b.split(" ")[0].strip()))
            except Exception:
                pass
        elif "采集完成" in msg:
            log(msg)

    def on_scraped(payload):
        items = payload.get("items") if isinstance(payload, dict) else payload
        exp = payload.get("expected", 0) if isinstance(payload, dict) else 0
        state["items"], state["expected"] = items or [], exp
        log("采集到 %d 条（网页显示 %s）" % (len(items or []), exp))
        host.close()
        QTimer.singleShot(1500, phase2)

    def on_scrape_err(msg):
        log("采集失败：%s" % msg)
        app.quit()

    sc.sigProgress.connect(on_prog)
    sc.sigFinished.connect(on_scraped)
    sc.sigError.connect(on_scrape_err)
    sc.start(URL, host=host)
    QTimer.singleShot(SCROLL_LIMIT * 1000,
                      lambda: (log("采集超时"), phase2()))

    # ---------------- 阶段二：立刻解析 ----------------
    started = {"v": False}

    def phase2():
        if started["v"] or not state["items"]:
            return
        started["v"] = True
        items = state["items"][:N]
        log("=" * 56)
        log("开始解析前 %d 条（并发 5）" % len(items))

        rc = ResolveController()
        rc.set_concurrency(5)
        t0 = {}
        ok = {"n": 0, "f": 0}

        orig_timeout = rc._timeout

        def patched_timeout(sid):
            st = rc._slots.get(sid)
            row = st["row"] if st else -1
            try:
                view = rc._pool[sid]["view"]
                t0[row] = time.time()
                view.page().runJavaScript(
                    DIAG_JS, 0,
                    lambda r, rw=row: log("诊断 #%d %s" % (rw, r)))
            except Exception as e:
                log("诊断失败 %s" % e)
            return orig_timeout(sid)

        rc._timeout = patched_timeout

        def on_res(row, payload):
            ok["n"] += 1
            log("#%-3d OK  %s" % (row, payload.get("mode")))

        def on_fail(row, msg):
            ok["f"] += 1
            log("#%-3d FAIL %s" % (row, msg))

        rc.sigResolved.connect(on_res)
        rc.sigFailed.connect(on_fail)

        def done():
            log("=" * 56)
            log("解析结束：成功 %d 失败 %d" % (ok["n"], ok["f"]))
            log("结论：%s" % ("全部成功" if ok["f"] == 0 else "❌ 有失败"))
            app.quit()

        rc.sigAllDone.connect(done)
        q = [(i, it.get("id"), it.get("title") or "", it.get("dur") or 0)
             for i, it in enumerate(items)]
        rc.start(q, quality=0)
        QTimer.singleShot(120 * 1000, lambda: (log("解析超时"), app.quit()))

    app.exec()


if __name__ == "__main__":
    main()
