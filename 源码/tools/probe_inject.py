# -*- coding: utf-8 -*-
"""验证 CookieStore 注入到底有没有生效。

判断依据不能只看 cookieAdded 信号（Qt 编程式写入不一定发这个信号），
改成：注入一个非 HttpOnly 的探针 Cookie → 打开抖音 → 在页面里读 document.cookie。
同时等 35 秒看它有没有写进 Chromium 的明文 Cookie 库。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QByteArray, QDateTime, QTimer, QUrl   # noqa: E402
from PySide6.QtNetwork import QNetworkCookie                     # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app.config import profile_dir                               # noqa: E402
from app.webengine import ProfileManager                         # noqa: E402

READ_JS = "document.cookie"
PROBE = "probe_inject_check"
VALUE = "VALUE-OK-123"


def db_has_probe():
    p = os.path.join(profile_dir(), "Cookies")
    if not os.path.isfile(p):
        return "无库"
    for uri in ("file:%s?mode=ro&immutable=1", "file:%s?mode=ro"):
        try:
            con = sqlite3.connect(uri % p.replace("\\", "/"), uri=True)
            rows = con.execute("select host_key,name,value from cookies where name=?",
                               (PROBE,)).fetchall()
            con.close()
            return rows
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
    return "读取失败 " + last


def main():
    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()
    store = pm.profile.cookieStore()

    view = pm.new_view()
    view.resize(900, 600)
    view.show()
    view.load(QUrl("https://www.douyin.com/"))

    def inject():
        ck = QNetworkCookie(QByteArray(PROBE.encode()), QByteArray(VALUE.encode()))
        ck.setDomain(".douyin.com")
        ck.setPath("/")
        ck.setSecure(True)
        ck.setExpirationDate(QDateTime.fromSecsSinceEpoch(int(time.time()) + 86400 * 30))
        store.setCookie(ck, QUrl("https://www.douyin.com/"))
        print(">>> 已调用 setCookie（%s=%s）" % (PROBE, VALUE))

    def read_back():
        def cb(res):
            print(">>> 页面 document.cookie =", repr(res)[:600])
            hit = PROBE in (res or "")
            print(">>> 注入是否生效：", "是 ✅" if hit else "否 ❌")
        view.page().runJavaScript(READ_JS, 0, cb)

    def final():
        print(">>> 35 秒后 Chromium 库里的探针行:", db_has_probe())
        print(">>> 内存罐里的探针:", [k[2] for k in pm._jar if k[2] == PROBE])
        app.quit()

    QTimer.singleShot(5000, inject)
    QTimer.singleShot(9000, read_back)
    QTimer.singleShot(38000, final)
    app.exec()


if __name__ == "__main__":
    main()
