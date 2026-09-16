# -*- coding: utf-8 -*-
"""验证「已登录 / 未登录」徽标：用应用真实配置目录跑一遍浏览器页的判定逻辑。

期望（当前账号处于未登录状态）：
  * 只有游客 Cookie（passport_csrf_token 之类）时，cookie 判定必须是 False
  * 页面 DOM 判定应为 guest
  * 最终徽标 = 未登录
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QUrl                       # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from app.ui_browser import LOGIN_PROBE_JS                     # noqa: E402
from app.webengine import ProfileManager                      # noqa: E402


def main():
    app = QApplication(sys.argv[:1])
    pm = ProfileManager.instance()

    print("环境: %s" % ("打包 EXE" if getattr(sys, "frozen", False) else "源码运行"))
    print("cookie 判定 logged_in =", pm.logged_in, "(当前未登录，应为 False)")
    print("识别到的会话 Cookie =",
          {k: v[:10] for k, v in pm._session.items()} or "无")
    print("内存罐条数 =", len(pm._jar))

    view = pm.new_view()
    view.resize(1180, 760)
    view.show()
    view.load(QUrl("https://www.douyin.com/"))

    def probed(res):
        dom = res if isinstance(res, str) else "unknown"
        print("DOM 判定 =", dom)
        cookie_ok = pm.logged_in
        if dom == "guest":
            ok, note = False, "抖音页面当前显示为未登录"
        elif cookie_ok:
            ok, note = True, "本机已保存抖音登录信息"
        else:
            ok, note = False, "尚未登录抖音"
        print("最终徽标 =", "已登录" if ok else "未登录", "|", note)
        print("结论:", "✅ 一致" if (not ok and not cookie_ok) else "⚠️ 请检查")
        app.quit()

    def grab():
        view.page().runJavaScript(LOGIN_PROBE_JS, 0, probed)

    QTimer.singleShot(15000, grab)
    QTimer.singleShot(30000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
