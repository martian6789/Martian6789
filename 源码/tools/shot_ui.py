# -*- coding: utf-8 -*-
"""截取界面截图，用于确认「登录徽标 / 登出按钮 / 常见问题」的实际效果。

输出到 tools/shots/ 下。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, Qt                        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.main_window import MainWindow                       # noqa: E402

OUT = os.path.join(ROOT, "tools", "shots")
os.makedirs(OUT, exist_ok=True)


def main():
    app = QApplication(sys.argv[:1])
    w = MainWindow()
    w.resize(1180, 780)
    w.show()

    def shot(name):
        p = os.path.join(OUT, name)
        w.grab().save(p)
        print("已保存", p)

    def to_browser():
        w.nav.setCurrentRow(1)
        print("切换到浏览器页，导航行 =", w.nav.currentRow())
        print("徽标 =", w.pageBrowser.lblLogin.text(),
              "| tooltip =", w.pageBrowser.lblLogin.toolTip())
        print("登出按钮 =", w.pageBrowser.btnLogout.text(),
              "| 可见 =", w.pageBrowser.btnLogout.isVisible())

    def to_settings():
        w.nav.setCurrentRow(2)

    QTimer.singleShot(15000, to_browser)
    QTimer.singleShot(19000, lambda: shot("browser_page.png"))
    QTimer.singleShot(21000, to_settings)
    QTimer.singleShot(24000, lambda: shot("settings_page.png"))
    QTimer.singleShot(26000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
