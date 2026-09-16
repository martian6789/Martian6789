# -*- coding: utf-8 -*-
"""解析稳定性诊断：用真实的 ResolveController 跑一批视频，逐条记录耗时与结果。

用来定位「下到第 10 个之后开始失败」这类问题。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from app.resolver import ResolveController                         # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 10

START = time.time()
results = []
t0s = {}


def log(msg):
    print("[%7.1fs] %s" % (time.time() - START, msg), flush=True)


def load_items():
    p = os.path.join(ROOT, "tools", "scrape_items.json")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data[:N]


def main():
    app = QApplication(sys.argv[:1])
    items = load_items()
    log("准备解析 %d 条，并发 %d" % (len(items), CONC))

    rc = ResolveController()
    rc.set_concurrency(CONC)

    def on_prog(row, msg):
        pass

    def on_resolved(row, payload):
        dt = time.time() - t0s.get(row, START)
        results.append((row, "OK", dt, payload.get("br", 0), payload.get("mode")))
        log("#%-3d OK   %5.1fs br=%-7s %s" % (row, dt, payload.get("br", 0),
                                              payload.get("mode")))

    def on_failed(row, msg):
        dt = time.time() - t0s.get(row, START)
        results.append((row, "FAIL", dt, 0, msg))
        log("#%-3d FAIL %5.1fs %s" % (row, dt, msg))

    rc.sigProgress.connect(on_prog)
    rc.sigResolved.connect(on_resolved)
    rc.sigFailed.connect(on_failed)

    tasks = []
    for i, it in enumerate(items):
        t0s[i] = time.time()
        tasks.append((i, it["id"], (it.get("title") or "")[:20], it.get("dur", 0)))
    rc.start(tasks, 0)

    def watch():
        if rc.running:
            return
        ok = sum(1 for r in results if r[1] == "OK")
        bad = sum(1 for r in results if r[1] == "FAIL")
        log("=" * 52)
        log("总计 %d   成功 %d   失败 %d   用时 %.1fs" %
            (len(results), ok, bad, time.time() - START))
        # 失败的时间分布（看看是否集中在后半段）
        fails = [r[0] for r in results if r[1] == "FAIL"]
        if fails:
            log("失败的行号: %s" % fails)
        with open(os.path.join(ROOT, "tools", "resolve_probe.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"row": r[0], "res": r[1], "sec": round(r[2], 1),
                        "br": r[3], "extra": str(r[4])[:60]} for r in results],
                      f, ensure_ascii=False, indent=1)
        app.quit()

    rc.sigAllDone.connect(watch)
    QTimer.singleShot(int(len(items) * 60 * 1000 / max(1, CONC)) + 120000, watch)
    app.exec()


if __name__ == "__main__":
    main()
