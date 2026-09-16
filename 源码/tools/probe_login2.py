# -*- coding: utf-8 -*-
"""诊断二：找出「已登录」最可靠的判定信号（localStorage / 登录弹窗可见性）"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, QUrl                      # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.webengine import ProfileManager                     # noqa: E402

JS = r"""
(function () {
  var out = { href: location.href };
  function ls(k) {
    try {
      var v = localStorage.getItem(k);
      return v === null ? '<null>' : String(v).slice(0, 260);
    } catch (e) { return '<ERR>'; }
  }
  out.user_info = ls('user_info');
  out.user_info_passport_new = ls('user_info_passport_new');
  out.guiding = ls('LoginGuidingStrategy');
  out.sec_uid = ls('web_runtime_security_uid');

  // 登录弹窗是否「真的可见」
  var targets = ['扫码登录', '登录后即可', '验证码登录'];
  out.visible = {};
  targets.forEach(function (t) {
    var hits = [];
    document.querySelectorAll('div,span,p,section').forEach(function (e) {
      if (e.children.length === 0 && (e.innerText || '').trim() === t) {
        var r = e.getBoundingClientRect();
        hits.push({ y: Math.round(r.top), w: Math.round(r.width),
                    h: Math.round(r.height),
                    vis: getComputedStyle(e).visibility,
                    op: getComputedStyle(e).opacity });
      }
    });
    out.visible[t] = hits.slice(0, 4);
  });

  // 顶部导航里的登录按钮（可见、靠右）
  out.topLogin = [];
  document.querySelectorAll('button,div,span,a').forEach(function (e) {
    if (e.children.length === 0 && (e.innerText || '').trim() === '登录') {
      var r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.top < 140) {
        out.topLogin.push({ y: Math.round(r.top), x: Math.round(r.left),
                            w: Math.round(r.width), h: Math.round(r.height) });
      }
    }
  });

  // 头像 / 昵称容器
  var cands = ['.avatar', '[class*="avatar"]', '[data-e2e="user-info"]',
               'img[src*="aweme-avatar"]', '[class*="nickname"]'];
  out.avatarish = {};
  cands.forEach(function (sel) {
    out.avatarish[sel] = document.querySelectorAll(sel).length;
  });
  return JSON.stringify(out);
})();
"""


def main():
    app = QApplication(sys.argv)
    pm = ProfileManager.instance()
    view = pm.new_view()
    view.resize(1180, 780)
    view.show()
    view.load(QUrl("https://www.douyin.com/"))

    def grab():
        view.page().runJavaScript(JS, 0, on_js)

    def on_js(res):
        print("\n===== 关键信号 =====")
        try:
            d = json.loads(res)
        except Exception as e:
            print("解析失败", e, repr(res)[:200])
            app.quit()
            return
        for k in ("href", "user_info", "user_info_passport_new", "guiding",
                  "sec_uid"):
            print("%-24s %s" % (k, d.get(k)))
        print("visible:", json.dumps(d.get("visible"), ensure_ascii=False))
        print("topLogin:", json.dumps(d.get("topLogin"), ensure_ascii=False))
        print("avatarish:", json.dumps(d.get("avatarish"), ensure_ascii=False))
        app.quit()

    QTimer.singleShot(16000, grab)
    QTimer.singleShot(26000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
