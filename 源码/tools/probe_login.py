# -*- coding: utf-8 -*-
"""登录态诊断：在临时沙箱里复刻一次启动流程，看 Cookie 罐到底拿到了什么。

用法：
    python -u tools/probe_login.py

要点：必须在 import app.config **之前**把 LOCALAPPDATA 指向临时目录，
这样既不影响用户真实配置，又能真实复现「启动 → 读 session.json →
读 Cookies 明文库」这条链路。
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REAL = os.path.join(os.environ.get("LOCALAPPDATA", ""), "DouyinDownloader")
SANDBOX = tempfile.mkdtemp(prefix="dylogin_")
DST = os.path.join(SANDBOX, "DouyinDownloader")
os.makedirs(DST, exist_ok=True)

# 只复制判定登录态需要的东西，避免把几百 MB 的缓存一起搬过来
for item in ("session.json",):
    src = os.path.join(REAL, item)
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(DST, item))

wp_src = os.path.join(REAL, "WebProfile")
wp_dst = os.path.join(DST, "WebProfile")
os.makedirs(wp_dst, exist_ok=True)
for item in ("Cookies", "Cookies-journal", "Local Storage", "WebStorage",
             "Session Storage", "user_prefs.json"):
    s = os.path.join(wp_src, item)
    d = os.path.join(wp_dst, item)
    try:
        if os.path.isdir(s):
            shutil.copytree(s, d)
        elif os.path.isfile(s):
            shutil.copy2(s, d)
    except Exception as e:
        print("复制 %s 失败: %s" % (item, e), flush=True)

os.environ["LOCALAPPDATA"] = SANDBOX
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

import app.config as cfg                                           # noqa: E402
from app.webengine import ProfileManager                           # noqa: E402


def main():
    print("沙箱:", SANDBOX, flush=True)
    print("app_data_dir:", cfg.app_data_dir(), flush=True)
    print("SESSION_COOKIES:", cfg.SESSION_COOKIES, flush=True)
    print()

    # session.json 里有什么
    sp = ProfileManager.session_path()
    if os.path.isfile(sp):
        d = json.load(open(sp, encoding="utf-8"))
        names = [c["name"] for c in (d.get("cookies") or [])]
        print("session.json: logged_out=%s 条数=%d" % (
            d.get("logged_out"), len(names)), flush=True)
        print("  含会话类:", [n for n in names
                              if n in cfg.SESSION_COOKIES] or "无", flush=True)
    else:
        print("session.json 不存在", flush=True)
    print()

    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()

    fired = []
    orig = pm._on_cookie

    def spy(cookie):
        try:
            nm = bytes(cookie.name()).decode("utf-8", "ignore") \
                if not isinstance(cookie.name(), str) else cookie.name()
        except Exception:
            nm = "?"
        fired.append(nm)
        return orig(cookie)

    pm._on_cookie = spy
    pm.profile.cookieStore().cookieAdded.disconnect()
    pm.profile.cookieStore().cookieAdded.connect(spy)

    def report():
        print("启动后 ——", flush=True)
        print("  logged_in =", pm.logged_in, flush=True)
        print("  内存罐条目 =", len(pm._jar), flush=True)
        print("  会话类在罐里 =", [n for n in pm._session
                                   if pm.cookie_dict.get(n)] or "无", flush=True)
        doms = {}
        for (dom, p, nm) in pm._jar:
            doms.setdefault(dom, []).append(nm)
        for dom, names in sorted(doms.items()):
            print("   [%s] %d 条" % (dom, len(names)), flush=True)
        print("  cookieAdded 触发次数 =", len(fired), flush=True)
        # 直接读一遍明文库，看能读到几条会话 Cookie
        raw = []
        try:
            import sqlite3
            con = sqlite3.connect(
                "file:%s?mode=ro&immutable=1"
                % os.path.join(cfg.profile_dir(), "Cookies").replace("\\", "/"),
                uri=True)
            raw = [r[0] for r in con.execute(
                "SELECT name FROM cookies WHERE name IN "
                "('sessionid','sessionid_ss','sid_tt')").fetchall()]
            con.close()
        except Exception as e:
            print("  直接读库失败:", e, flush=True)
        print("  明文库里的会话类 =", raw or "无", flush=True)
        print()
        print("结论:", "登录态正常" if pm.logged_in else "❌ 登录态丢失", flush=True)
        app.quit()

    QTimer.singleShot(3000, report)
    app.exec()


if __name__ == "__main__":
    main()
