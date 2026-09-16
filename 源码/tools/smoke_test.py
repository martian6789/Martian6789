# -*- coding: utf-8 -*-
"""冒烟测试：启动主窗口并在 N 秒后自动退出，用于验证 GUI 可正常构建"""
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main_window import MainWindow
from app.style import QSS

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(QSS)
w = MainWindow()
w.show()
print("MAINWINDOW_OK")


def quit_app():
    print("CLOSE")
    app.quit()


QTimer.singleShot(int(sys.argv[1]) if len(sys.argv) > 1 else 8000, quit_app)
sys.exit(app.exec())
