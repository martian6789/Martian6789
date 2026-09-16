# -*- coding: utf-8 -*-
"""验证「已登录却显示未登录」是否修好。

用法：
    python tools/verify_login_badge.py [等待秒数]

用真实 profile 跑，检查三件事：
1. 明文库里到底有没有 sessionid（用户是否真的登录过）
2. ProfileManager.logged_in 在轮询后是否变成 True（webengine.py 的修复）
3. BrowserPage 的徽标文字是否是「已登录」（ui_browser.py 的修复）

注意：会占用 WebProfile 锁，不要和其它 Qt 探针同时跑。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-dev-shm-usage")

WAIT = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0

from PySide6.QtCore import QTimer                          # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow    # noqa: E402

from app.config import app_data_dir, profile_dir, SESSION_COOKIES  # noqa: E402
from app.webengine import ProfileManager                   # noqa: E402

print("=" * 66)
print("1) 明文库里是否有登录 Cookie")
print("=" * 66)
sqlite3 = __import__("sqlite3")
import shutil
import tempfile

p = os.path.join(profile_dir(), "Cookies")
print("   Cookies 库:", p, "存在:", os.path.isfile(p))
disk_session = []
if os.path.isfile(p):
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(p, tmp)
        con = sqlite3.connect("file:%s?mode=ro" % tmp.replace("\\", "/"), uri=True)
        rows = con.execute("SELECT name, length(value), is_httponly "
                           "FROM cookies").fetchall()
        con.close()
    except Exception as e:
        print("   读取失败:", e)
        rows = []
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    for name, ln, ho in rows:
        if name in SESSION_COOKIES:
            disk_session.append((name, ln))
    print("   总计 %d 条 Cookie" % len(rows))
    print("   明文库里的会话类 Cookie:", disk_session or "（无）")

print()
print("=" * 66)
print("2) ProfileManager 内存罐（轮询同步后）")
print("=" * 66)

app = QApplication(sys.argv)
app.setApplicationName("DouyinProbe")
pm = ProfileManager.instance()

print("   启动瞬间 logged_in =", pm.logged_in)
print("   轮询间隔 4s，等待 %.0fs …" % WAIT)

win = QMainWindow()
win.setWindowTitle("登录态验证")
win.resize(900, 640)

from app.ui_browser import BrowserPage        # noqa: E402
page = BrowserPage(win)
win.setCentralWidget(page)
win.show()

T0 = time.time()


def snapshot():
    print("   [%.0fs] logged_in=%s  session=%s  jar=%d  dict=%d"
          % (time.time() - T0, pm.logged_in,
             sorted(pm._session.keys()), len(pm._jar), len(pm.cookie_dict)))


def report():
    print()
    print("=" * 66)
    print("结论")
    print("=" * 66)
    print("   明文库会话 Cookie :", disk_session or "（无）")
    print("   内存罐 session    :", sorted(pm._session.keys()) or "（无）")
    print("   pm.logged_in      :", pm.logged_in)
    badge = page.lblLogin.text()
    print("   界面徽标          :", badge)
    print("   徽标提示          :", page.lblLogin.toolTip())
    print("   页面 DOM 状态     :", page._dom_state)

    ok_disk = bool(disk_session)
    ok_mem = pm.logged_in
    ok_badge = (badge == "已登录")
    print()
    print("   明文库有登录态      :", "✅" if ok_disk else "❌")
    print("   内存罐同步到登录态  :", "✅" if ok_mem else "❌")
    print("   徽标显示已登录      :", "✅" if ok_badge else "❌")
    if ok_disk and not ok_mem:
        print("\n   ⚠️ 明文库有、内存罐没有 → webengine 的轮询同步仍然没生效")
    if ok_badge:
        print("\n   结论：修复生效 ✅")
    else:
        print("\n   结论：仍然显示未登录 ❌")
    app.quit()


for i in range(1, int(WAIT // 4) + 1):
    QTimer.singleShot(i * 4000, snapshot)
QTimer.singleShot(int(WAIT * 1000), report)
QTimer.singleShot(int(WAIT * 1000) + 15000, app.quit)
app.exec()
