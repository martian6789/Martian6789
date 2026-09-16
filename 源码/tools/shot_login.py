# -*- coding: utf-8 -*-
"""截取「浏览器」页顶部，展示登录徽标（验证「已登录却显示未登录」的修复）。

输出：tools/shots/login_badge.png
只截窗口顶部一条（头部栏），因为要突出的是右上角的徽标。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --no-sandbox --disable-dev-shm-usage")

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow      # noqa: E402

from app.config import APP_TITLE, APP_VERSION                # noqa: E402
from app.webengine import ProfileManager                     # noqa: E402
from app.ui_browser import BrowserPage                       # noqa: E402

OUT = os.path.join(ROOT, "tools", "shots")
os.makedirs(OUT, exist_ok=True)


def main():
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DouyinDownloader")
    pm = ProfileManager.instance()          # 触发轮询同步
    w = QMainWindow()
    w.setWindowTitle("%s  v%s" % (APP_TITLE, APP_VERSION))
    w.resize(1180, 780)
    page = BrowserPage(w)
    w.setCentralWidget(page)
    w.show()

    def shoot():
        # 只截头部一条：徽标就在那里
        head = page.findChild(type(page)).__class__ if False else None
        pix = w.grab()
        top = pix.copy(0, 0, pix.width(), 150)
        p = os.path.join(OUT, "login_badge.png")
        top.save(p)
        print("徽标文字 =", page.lblLogin.text())
        print("徽标提示 =", page.lblLogin.toolTip())
        print("logged_in =", pm.logged_in)
        print("session   =", sorted(pm._session.keys()))
        print("jar 条数  =", len(pm._jar), " _forgotten =", len(pm._forgotten))
        print("_disk_sig =", pm._disk_sig)
        try:
            n = pm._load_cookies_from_disk()
            print("手动再同步一次 → 新增", n, "条；此时 session =",
                  sorted(pm._session.keys()), "logged_in =", pm.logged_in)
        except Exception as e:
            print("手动同步异常:", e)
        print("已保存:", p, flush=True)
        app.quit()

    # 轮询同步 4s 一次，页面加载也要时间；等太短会截到还没同步完的中间态
    QTimer.singleShot(22000, shoot)
    QTimer.singleShot(45000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
