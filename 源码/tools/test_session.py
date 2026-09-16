# -*- coding: utf-8 -*-
"""验证登录态持久化：即使 Chromium 自己的 Cookie 库丢了，登录也要能保住。

三个阶段各跑一个独立进程（模拟真实「关掉再打开」）：

  save     写入一个测试会话并落盘
  restore  把 Chromium 的 Cookies 库搬走，看登录态是否还在
  logout   标记登出后重启，看完能不能复活

用法：python tools/test_session.py <save|restore|logout|check_guest>
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 关键：把 LOCALAPPDATA 指到临时沙箱，避免把测试 Cookie 写进用户真实配置目录。
# 必须在 import app.config 之前设置。
_SANDBOX = os.environ.get("DY_TEST_SANDBOX") or os.path.join(
    tempfile.gettempdir(), "dytest_profile")
os.environ["LOCALAPPDATA"] = _SANDBOX
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.config import profile_dir                           # noqa: E402
from app.webengine import ProfileManager                     # noqa: E402

DB = os.path.join(profile_dir(), "Cookies")
DB_BAK = DB + ".testbak"
SESSION = ProfileManager.session_path()
FUTURE = int(time.time()) + 90 * 24 * 3600


def _cleanup():
    for p in (SESSION, SESSION + ".tmp", DB_BAK):
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def phase_save(app, pm):
    _cleanup()
    print("phase=save")
    accepted = []

    def on_added(c):
        n = c.name()
        n = n if isinstance(n, str) else bytes(n).decode("utf-8", "ignore")
        if n in ("sessionid", "sessionid_ss"):
            accepted.append(n)

    pm.profile.cookieStore().cookieAdded.connect(on_added)

    # 游客 Cookie（未登录也有）——不许被当成登录标志
    pm._remember(".douyin.com", "/", "passport_csrf_token", "guest-only", FUTURE)
    pm._remember(".douyin.com", "/", "uid_tt", "guest-uid", FUTURE)
    pm._inject_jar()
    print("  只有游客 Cookie 时 logged_in =", pm.logged_in, "(应为 False)")

    # 真正的会话 Cookie
    pm._remember(".douyin.com", "/", "sessionid", "TEST-SESSION-ABC", FUTURE)
    pm._remember(".douyin.com", "/", "sessionid_ss", "TEST-SS-ABC", FUTURE)
    pm._inject_jar()
    print("  注入 sessionid 后 logged_in =", pm.logged_in, "(应为 True)")

    QTimer.singleShot(1500, lambda: finish(app, pm, accepted))


def phase_restore(app, pm):
    print("phase=restore")
    print("  session.json 存在 =", os.path.isfile(SESSION))
    print("  Chromium 的 Cookies 库是否存在 =", os.path.isfile(DB), "(被搬走才是关键场景)")
    print("  logged_in =", pm.logged_in, "(应为 True —— 靠我们自己的备份恢复)")
    print("  内存罐里的会话 Cookie =",
          {k[2]: v["value"][:14] for k, v in pm._jar.items()
           if k[2] in ("sessionid", "sessionid_ss")})
    finish(app, pm)


def phase_logout(app, pm):
    print("phase=logout")
    pm.clear_cookies()
    print("  登出后 logged_in =", pm.logged_in, "(应为 False)")
    with open(SESSION, "r", encoding="utf-8") as f:
        d = json.load(f)
    print("  session.json logged_out =", d.get("logged_out"), "(应为 True)")
    finish(app, pm)


def phase_check_guest(app, pm):
    print("phase=check_guest")
    print("  登出后重启，logged_in =", pm.logged_in, "(应为 False，旧 Cookie 不许复活)")
    finish(app, pm)


def finish(app, pm, accepted=None):
    if accepted is not None:
        print("  CookieStore 是否接收了注入的会话 Cookie =", sorted(set(accepted)))
    pm._save_session()
    # 让 Qt 有机会把 Cookie 写进自己的库，顺便验证落盘
    QTimer.singleShot(2000, app.quit)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "save"
    print("沙箱配置目录 =", _SANDBOX)

    if phase == "save":
        _cleanup()
    elif phase == "restore":
        # 模拟「Chromium 没把 Cookie 写下来」：把它的库藏起来
        if os.path.isfile(DB) and not os.path.isfile(DB_BAK):
            shutil.move(DB, DB_BAK)
            print("  已把 Chromium 的 Cookies 库移开：", DB_BAK)
        if os.path.isfile(DB_BAK) and not os.path.isfile(DB):
            pass
    elif phase == "check_guest":
        # 把库还回去：库里有旧 Cookie，但我们已登出，必须以登出为准
        if os.path.isfile(DB_BAK):
            if os.path.isfile(DB):
                os.remove(DB)
            shutil.move(DB_BAK, DB)
            print("  已把旧的 Cookies 库还回原位（模拟旧 Cookie 残留）")

    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()
    {"save": phase_save, "restore": phase_restore,
     "logout": phase_logout, "check_guest": phase_check_guest}[phase](app, pm)
    app.exec()


if __name__ == "__main__":
    main()
