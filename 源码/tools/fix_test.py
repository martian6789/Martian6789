# -*- coding: utf-8 -*-
"""修复验证：10 路并发解析 + 并发下载 + 成品完整性校验"""
import os
import sys
import time
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.resolver import ResolveController
from app.downloader import DownloadManager, DownloadTask

OUT = os.path.join(ROOT, "output", "_fix_test")
os.makedirs(OUT, exist_ok=True)

N_VIDS = int(os.environ.get("N_VIDS", "12"))
CONC = int(os.environ.get("CONC", "10"))

ids = []
src = os.path.join(os.path.dirname(ROOT), "work", "all_ids.txt")
if os.path.exists(src):
    with open(src, encoding="utf-8") as f:
        for line in f:
            v = line.strip().split()[-1] if line.strip() else ""
            if v.isdigit() and len(v) >= 15:
                ids.append(v)

# 已知可用的样本兜底
for v in ("7650636256003016049", "7671645036421718457",
          "7657697525026036913", "7642560584685440697"):
    if v not in ids:
        ids.append(v)

ids = ids[:N_VIDS]
print(f"待测 {len(ids)} 个视频，解析并发 {CONC}")

rc = ResolveController(concurrency=CONC)
dm = DownloadManager(None, max_workers=CONC)
dm.reset_cancel()

refs = []
stat = {"resolved": 0, "res_fail": 0, "ok": 0, "fail": 0}
t0 = time.time()


def on_resolved(row, payload):
    dt = time.time() - t0
    stat["resolved"] += 1
    print(f"  [解析] #{row:02d} {payload['vid']} "
          f"mode={payload['mode']} br={payload.get('br', 0)} "
          f"dur={payload.get('dur', 0):.1f}  ({dt:.1f}s)")
    name = f"{row:02d}_{payload['vid']}.mp4"
    t = DownloadTask(row, payload, OUT, name, dm.cancel)
    t.signals.sigDone.connect(
        lambda r, p, s: (stat.__setitem__("ok", stat["ok"] + 1),
                         print(f"  [完成] #{r:02d} {s/1e6:.2f}MB ok")))
    t.signals.sigError.connect(
        lambda r, m: (stat.__setitem__("fail", stat["fail"] + 1),
                      print(f"  [失败] #{r:02d} {m}")))
    t.signals.sigLog.connect(lambda r, m: print(f"     [#{r:02d}] {m}"))
    refs.append(t)
    dm.submit(t)


def on_failed(row, msg):
    stat["res_fail"] += 1
    print(f"  [解析失败] #{row:02d} {msg}")


def on_progress(row, msg):
    if "[解析]" not in msg:
        print(f"     [#{row:02d}] {msg}")


rc.sigResolved.connect(on_resolved)
rc.sigFailed.connect(on_failed)
rc.sigProgress.connect(on_progress)

tasks = [(i, v, "") for i, v in enumerate(ids)]
rc.start(tasks, quality=0)

state = {"n": 0}


def poll():
    state["n"] += 1
    if not rc.running and dm.active == 0:
        print(f"\n===== 汇总（{time.time()-t0:.1f}s） =====")
        print(f"解析成功 {stat['resolved']} / 失败 {stat['res_fail']}")
        print(f"下载成功 {stat['ok']} / 失败 {stat['fail']}")
        files = sorted(os.listdir(OUT))
        print(f"产物 {len(files)} 个：")
        import subprocess
        from app.config import ffmpeg_path
        good = 0
        for f in files:
            p = os.path.join(OUT, f)
            if not f.endswith(".mp4"):
                continue
            sz = os.path.getsize(p)
            r = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", p],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            s = r.stdout.decode("utf-8", "ignore")
            import re
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", s)
            dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                   + float(m.group(3))) if m else 0
            has_v = "Video:" in s
            flag = "OK " if (has_v and dur > 1) else "BAD"
            if flag == "OK ":
                good += 1
            print(f"   {flag} {f}  {sz/1e6:.2f}MB  {dur:.1f}s  视频流={has_v}")
        print(f"\n可播放 {good} / {len([f for f in files if f.endswith('.mp4')])}")
        app.quit()
        return
    if state["n"] > 400:      # 约 200 秒保护
        print("!! 超时")
        app.quit()
        return
    QTimer.singleShot(500, poll)


QTimer.singleShot(1000, poll)
QTimer.singleShot(300000, app.quit)
app.exec()
