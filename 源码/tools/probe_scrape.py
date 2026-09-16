# -*- coding: utf-8 -*-
"""采集完整性验证：真实跑一次主页滚动采集，对照网页显示的作品总数。

用法：probe_scrape.py [主页URL] [超时秒]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
os.environ["DY_DEBUG"] = "1"

from PySide6.QtCore import QTimer                                   # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from app.scraper import ScrapeController                            # noqa: E402

URL = (sys.argv[1] if len(sys.argv) > 1
       else "https://www.douyin.com/user/"
            "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0")
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 300

START = time.time()
LAST = {"exp": 0, "n": 0}


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


def main():
    app = QApplication(sys.argv[:1])
    c = ScrapeController()

    def on_prog(msg):
        log(msg)
        # 从进度文本里抠出「已采集 X / 共 Y」
        try:
            if "共" in msg:
                seg = msg.split("已采集")[-1]
                a, b = seg.split("/")
                LAST["n"] = int(a.strip())
                LAST["exp"] = int(b.split(" ")[0].strip())
        except Exception:
            pass

    def on_done(payload):
        items = payload.get("items") if isinstance(payload, dict) else payload
        exp = payload.get("expected", 0) if isinstance(payload, dict) else 0
        log("=" * 56)
        log("采集到 %d 条；网页显示作品总数 = %s" % (len(items or []), exp))
        if exp:
            pct = len(items) * 100.0 / exp
            log("完整度 = %.1f%%" % pct)
            log("结论：%s" % ("完整 ✅" if len(items) >= exp * 0.98
                              else "不完整 ❌（少了 %d 条）" % (exp - len(items))))
        else:
            log("（没读到网页作品数，无法校准）")
        for it in (items or [])[:5]:
            log("    %s  %s" % (it.get("id"), (it.get("title") or "")[:26]))
        with open(os.path.join(ROOT, "scrape_probe_out.json"), "w",
                  encoding="utf-8") as f:
            json.dump(items or [], f, ensure_ascii=False)
        app.quit()

    def on_err(msg):
        log("采集失败：%s" % msg)
        app.quit()

    c.sigProgress.connect(on_prog)
    c.sigFinished.connect(on_done)
    c.sigError.connect(on_err)

    # 必须是「可见」窗口：抖音的懒加载在隐藏/后台页面不会触发，
    # 用离屏视图采不到数据，探针会误判。
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    host = QWidget()
    host.setWindowTitle("采集探针（可见）")
    host.resize(1120, 780)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    host.show()
    c.start(URL, host=host)

    QTimer.singleShot(LIMIT * 1000, lambda: (log("超时退出"), app.quit()))
    app.exec()


if __name__ == "__main__":
    main()
