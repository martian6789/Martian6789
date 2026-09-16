# -*- coding: utf-8 -*-
"""验证「启动瞬间」恢复的 Cookie 真的进了浏览器。

做法：在沙箱里预先写一份 session.json（含一个非 HttpOnly 的探针 Cookie），
启动后打开抖音，直接在页面里读 document.cookie —— 能看到探针就说明
启动时的注入在页面加载前就生效了（用户不必重新登录）。
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_SANDBOX = os.path.join(tempfile.gettempdir(), "dytest_live")
shutil.rmtree(_SANDBOX, ignore_errors=True)
os.environ["LOCALAPPDATA"] = _SANDBOX
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QUrl                        # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

from app.webengine import ProfileManager                       # noqa: E402

PROBE = "dy_restore_probe"
VALUE = "RESTORED-OK-456"
SESSION_COOKIE = "sessionid"
SESSION_VALUE = "FAKE-SESSION-FOR-TEST"


def seed():
    d = os.path.join(_SANDBOX, "DouyinDownloader")
    os.makedirs(d, exist_ok=True)
    exp = int(time.time()) + 30 * 24 * 3600
    data = {"version": 1, "saved_at": int(time.time()), "logged_out": False,
            "cookies": [
                {"name": PROBE, "value": VALUE, "domain": ".douyin.com",
                 "path": "/", "expires": exp},
                {"name": SESSION_COOKIE, "value": SESSION_VALUE,
                 "domain": ".douyin.com", "path": "/", "expires": exp},
            ]}
    with open(os.path.join(d, "session.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("已写入沙箱 session.json：", os.path.join(d, "session.json"))


def main():
    seed()
    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()          # 这里就会触发启动恢复
    print("启动时 logged_in =", pm.logged_in, "(应为 True)")
    print("启动时内存罐 =", {k[2]: v["value"][:16] for k, v in pm._jar.items()})

    view = pm.new_view()
    view.resize(900, 600)
    view.show()
    view.load(QUrl("https://www.douyin.com/"))

    def read_back():
        def cb(res):
            s = res or ""
            print("页面 document.cookie 片段 =", repr(s)[:300])
            print("探针 Cookie 是否随启动注入进浏览器:",
                  "是 ✅" if PROBE in s else "否 ❌（会被页面当成未登录）")
            app.quit()
        view.page().runJavaScript("document.cookie", 0, cb)

    QTimer.singleShot(15000, read_back)
    QTimer.singleShot(30000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
