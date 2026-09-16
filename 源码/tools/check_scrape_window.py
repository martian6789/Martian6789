# -*- coding: utf-8 -*-
"""验证采集窗口顶部黑条已被压成一行（不再吃掉大半个窗口）。

做法：构造 ScrapeWindow，往布局里塞一个「会膨胀」的假视图（模仿真实的
QWebEngineView），然后测量顶部 QLabel 的实际高度。修复前它会被拉成几百
像素高（截图里上半屏全黑），修复后应恒为 32。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QObject, Signal, QTimer                     # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel, QSizePolicy,      # noqa: E402
                               QVBoxLayout, QWidget)


class DummyController(QObject):
    sigProgress = Signal(str)


def main():
    app = QApplication(sys.argv[:1])
    from app.ui_download import ScrapeWindow

    c = DummyController()
    w = ScrapeWindow(c)
    w.resize(1120, 780)

    # 假的「网页视图」：和 QWebEngineView 一样是 Expanding，用来把多余空间吃掉
    fake = QWidget()
    fake.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    fake.setStyleSheet("background:#0B0B0D;")
    w.layout().addWidget(fake)
    w.show()

    def check():
        h = w.lblTop.height()
        avail = w.height() - h
        print("顶部黑条高度 = %d px" % h, flush=True)
        print("留给网页的高度 = %d px（占 %.0f%%）"
              % (avail, avail * 100.0 / w.height()), flush=True)
        if h <= 40:
            print("结论：黑条已压成一行 ✅", flush=True)
        else:
            print("结论：黑条仍然过高 ❌", flush=True)
        # 顺便让进度文本走一遍，确认标签能正常更新
        c.sigProgress.emit("滚动采集第 20 次，已采集 428 / 共 630 个…")
        QTimer.singleShot(300, shot)

    def shot():
        w.grab().save(os.path.join(ROOT, "tools", "shots", "scrape_window.png"))
        print("截图已保存 tools/shots/scrape_window.png", flush=True)
        app.quit()

    QTimer.singleShot(1500, check)
    app.exec()


if __name__ == "__main__":
    main()
