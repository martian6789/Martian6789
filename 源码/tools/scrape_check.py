# -*- coding: utf-8 -*-
"""用应用自己的 ScrapeController 跑一次抓取，检查标题与数量。

复用真实 ProfileManager（含钩子注入），输出：
- 抓到多少条、来源（接口捕获 / 页面解析）
- 标题为空的条目数
- 抽样打印
"""
import json
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.scraper import ScrapeController                     # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

got = {}


def main():
    app = QApplication(sys.argv)
    host = QWidget()
    host.resize(1280, 900)
    host.show()

    sc = ScrapeController()

    def on_fin(items):
        got["items"] = items
        app.quit()

    def on_err(m):
        print("ERROR:", m, flush=True)
        app.quit()

    sc.sigProgress.connect(lambda m: print("PROG:", m, flush=True))
    sc.sigFinished.connect(on_fin)
    sc.sigError.connect(on_err)

    sc.start(URL, host)
    QTimer.singleShot(600000, app.quit)
    app.exec()

    items = got.get("items") or []
    print("\n================ 抓取结果 ================", flush=True)
    print("总条数:", len(items), flush=True)

    empty = [it for it in items if not str(it.get("title") or "").strip()]
    print("标题为空:", len(empty), flush=True)

    authors = {}
    for it in items:
        k = (str(it.get("au") or ""), str(it.get("nick") or ""))
        authors[k] = authors.get(k, 0) + 1
    print("作者分布:", json.dumps(
        {"%s|%s" % k: v for k, v in authors.items()}, ensure_ascii=False), flush=True)

    print("\n---- 前 25 条 ----", flush=True)
    for it in items[:25]:
        print("  %-20s dur=%-6s %s" % (it.get("id"), it.get("dur"),
                                       (str(it.get("title"))[:60] or "<空>")), flush=True)

    print("\n---- 标题为空的条目（最多 20）----", flush=True)
    for it in empty[:20]:
        print("  id=%s dur=%s urls=%d dl=%d bit=%d"
              % (it.get("id"), it.get("dur"), len(it.get("urls") or []),
                 len(it.get("dl") or []), len(it.get("bit") or [])), flush=True)

    with open(os.path.join(ROOT, "tools", "scrape_items.json"), "w",
              encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    print("\n已写入 tools/scrape_items.json", flush=True)


if __name__ == "__main__":
    main()
