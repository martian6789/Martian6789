# -*- coding: utf-8 -*-
"""抓取自测：滚取主播主页全部视频"""
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.scraper import ScrapeController

URL = (sys.argv[1] if len(sys.argv) > 1 else
       "https://www.douyin.com/user/MS4wLjABAAAAMpy2JhmaM0izeM-2kup44D-jVvjimg57_g8KEoWgoYYDtTqqenEXXUuX1171DTdz")

app = QApplication(sys.argv)
sc = ScrapeController()

HOST = QWidget()
HOST.setWindowTitle("采集中（自测）")
HOST.resize(1120, 800)
_lay = QVBoxLayout(HOST)
_lay.setContentsMargins(0, 0, 0, 0)
_lay.addWidget(QLabel("采集中…"))
HOST.show()


def on_items(items):
    print("TOTAL", len(items))
    for it in items[:12]:
        print("  ", it["id"], "|", (it["title"] or "(无标题)")[:52])
    QTimer.singleShot(300, app.quit)


def on_err(msg):
    print("ERROR:", msg)
    QTimer.singleShot(300, app.quit)


sc.sigProgress.connect(lambda m: print("  ...", m))
sc.sigFinished.connect(on_items)
sc.sigError.connect(on_err)
sc.start(URL, host=HOST)
QTimer.singleShot(300000, app.quit)
app.exec()
print("EXIT")
