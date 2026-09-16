# -*- coding: utf-8 -*-
"""离屏冒烟：三个页面都能实例化（捕获导入期/构建期错误）"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.ui_download import DownloadPage
from app.ui_settings import SettingsPage
d = DownloadPage(); s = SettingsPage()
print("PAGES_OK")
