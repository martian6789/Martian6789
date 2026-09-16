# -*- coding: utf-8 -*-
"""功能自测：解析一个真实视频并下载到临时目录"""
import os
import sys
import tempfile

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QCoreApplication
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.resolver import ResolveController
from app.downloader import DownloadManager, DownloadTask
from app.config import safe_filename

VID = sys.argv[1] if len(sys.argv) > 1 else "7665936241304656379"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), "dy_test")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
dm = DownloadManager()
res = ResolveController()

state = {"phase": "resolve"}
KEEP = []


def on_resolved(row, payload):
    print("RESOLVED", payload.get("mode"), "br=", payload.get("br"))
    print("  url:", (payload.get("url") or payload.get("v") or "")[:110])
    name = safe_filename("自测视频_" + VID[-6:]) + ".mp4"
    t = DownloadTask(row, payload, OUT, name, dm.cancel)
    t.signals.sigProgress.connect(lambda r, p, s: None)
    t.signals.sigDone.connect(on_done)
    t.signals.sigError.connect(on_err)
    t.signals.sigLog.connect(lambda r, m: print("  LOG:", m))
    KEEP.append(t)          # 保持引用，避免被 GC 后信号丢失
    dm.submit(t)


def on_done(row, path, size):
    print("DONE", path, size, "bytes")
    state["phase"] = "done"
    QTimer.singleShot(300, app.quit)


def on_err(row, msg):
    print("ERROR", msg)
    state["phase"] = "err"
    QTimer.singleShot(300, app.quit)


res.sigResolved.connect(on_resolved)
res.sigFailed.connect(on_err)
res.sigProgress.connect(lambda r, m: print("  ...", m))
res.sigAllDone.connect(lambda: print("ALL_RESOLVED"))

res.start([(0, VID, "自测视频")], 0)
QTimer.singleShot(120000, app.quit)   # 安全超时
app.exec()
print("EXIT", state["phase"])
