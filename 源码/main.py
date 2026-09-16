# -*- coding: utf-8 -*-
"""抖音视频下载器 —— 程序入口"""
import os
import sys

# 让 QtWebEngine 在部分显卡环境正常初始化
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import Qt, QCoreApplication, QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.style import QSS
from app.config import APP_TITLE, APP_VERSION


def _taskbar_id():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "DouyinDownloader.Desktop.1")
        except Exception:
            pass


def main():
    if hasattr(Qt, "AA_ShareOpenGLContexts"):
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)

    _taskbar_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("DouyinDownloader")
    # 不要设置 applicationDisplayName：Qt 会把它拼到窗口标题后面，
    # 变成「抖音视频下载器 v1.2.0 - 抖音视频下载器」这种重复标题。
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "app", "app.ico")
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    if os.path.exists(icon_path):
        from PySide6.QtGui import QIcon
        w.setWindowIcon(QIcon(icon_path))
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
