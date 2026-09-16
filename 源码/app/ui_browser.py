# -*- coding: utf-8 -*-
"""内置浏览器页面（扫码登录 / 浏览主播主页 / 导入登录态 / 登出）"""
from PySide6.QtCore import Signal, QUrl, Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QMessageBox, QDialog, QPlainTextEdit, QDialogButtonBox)
from PySide6.QtGui import QDesktopServices

from .webengine import ProfileManager

HOME = "https://www.douyin.com/"
LOGIN_URL = "https://www.douyin.com/user/self?from_tab_name=main"

# 判定抖音页面当前是不是「未登录」状态。
# 顺序很重要：先做**廉价**判据（头像，一次 querySelector），没有头像才做
# 昂贵的「遍历 DOM 找可见文案」，且昂贵那步最多 10 秒跑一次。
# 这个探针会被定时调用（登录是在不跳转的弹窗里完成的，只在 loadFinished
# 探一次会漏掉「扫码后状态没更新」的情况）。
LOGIN_PROBE_JS = r"""
(function () {
  try {
    var h = location.host || '';
    if (h.indexOf('douyin.com') < 0 && h.indexOf('iesdouyin') < 0) return 'unknown';

    // 1) 登录后才有头像；有且可见就可以直接判定
    var av = document.querySelector(
      'img[src*="aweme-avatar"], [data-e2e="user-avatar"], [class*="avatar"] img');
    if (av) {
      var r0 = av.getBoundingClientRect();
      if (r0.width > 0 && r0.height > 0) return 'user';
    }

    // 2) 昂贵的判据（遍历 + 逐个量尺寸）——限流，最多 10 秒一次
    var now = Date.now();
    if (window.__dyProbeAt && now - window.__dyProbeAt < 10000) return 'unknown';
    window.__dyProbeAt = now;

    function visibleExact(t) {
      var all = document.querySelectorAll('body *');
      for (var i = 0; i < all.length; i++) {
        var e = all[i];
        if (e.children.length === 0 && (e.textContent || '').trim() === t) {
          var r = e.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) return true;
        }
      }
      return false;
    }

    var body = document.body ? (document.body.innerText || '') : '';
    if (body.indexOf('扫码登录') >= 0 && visibleExact('扫码登录')) return 'guest';
    if (body.indexOf('登录后即可观看') >= 0) return 'guest';
    if (body.indexOf('登录后即可查看') >= 0) return 'guest';
    return 'unknown';
  } catch (e) { return 'unknown'; }
})();
"""


class ImportDialog(QDialog):
    """导入 / 恢复登录态：自动读取 → 扫码 → 手动粘贴，三条路都给出"""

    def __init__(self, pm, parent=None):
        super().__init__(parent)
        self.pm = pm
        self.imported = False
        self.setWindowTitle("导入登录态")
        self.resize(620, 560)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        t = QLabel("方式一：从本机浏览器自动导入")
        t.setStyleSheet("font-weight:600;")
        root.addWidget(t)

        d1 = QLabel(
            "读取本机 Chrome / Edge 里已登录的抖音 Cookie。\n"
            "只读取数据库副本，不会修改浏览器数据。\n"
            "注意：Chrome / Edge 127 之后启用了「应用绑定加密」，"
            "多数情况下软件无法离线读取，此时请用方式二或方式三。")
        d1.setWordWrap(True)
        d1.setObjectName("hint")
        root.addWidget(d1)

        row = QHBoxLayout()
        self.btnAuto = QPushButton("尝试自动导入")
        self.btnAuto.setObjectName("primary")
        self.btnAuto.clicked.connect(self.auto_import)
        self.btnScan = QPushButton("去扫码登录（最可靠）")
        self.btnScan.clicked.connect(self._go_scan)
        row.addWidget(self.btnAuto)
        row.addWidget(self.btnScan)
        row.addStretch(1)
        root.addLayout(row)

        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#E5E7EB;")
        root.addWidget(line)

        t2 = QLabel("方式二：手动粘贴 Cookie")
        t2.setStyleSheet("font-weight:600;")
        root.addWidget(t2)

        d2 = QLabel(
            "在已登录抖音的浏览器里按 F12 → Application → Cookies → "
            "https://www.douyin.com，把以 sessionid 开头的几个值复制出来，"
            "按 <code>名字=值; 名字=值</code> 的形式粘贴到下面。\n"
            "必须包含 sessionid，最好再带上 sessionid_ss、sid_tt、uid_tt、"
            "passport_csrf_token。")
        d2.setWordWrap(True)
        d2.setObjectName("hint")
        d2.setTextFormat(Qt.RichText)
        root.addWidget(d2)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(
            "sessionid=xxxx; sessionid_ss=yyyy; sid_tt=zzzz; uid_tt=...; "
            "passport_csrf_token=...")
        root.addWidget(self.edit, 1)

        row2 = QHBoxLayout()
        self.btnManual = QPushButton("导入粘贴内容")
        self.btnManual.clicked.connect(self.manual_import)
        self.lblTip = QLabel("")
        self.lblTip.setObjectName("hint")
        self.lblTip.setWordWrap(True)
        row2.addWidget(self.btnManual)
        row2.addWidget(self.lblTip, 1)
        root.addLayout(row2)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("关闭")
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ---------------- 自动导入 ----------------
    def auto_import(self):
        from .cookies_import import (read_douyin_cookies, has_login, scan_browsers)
        self.btnAuto.setEnabled(False)
        try:
            items = read_douyin_cookies()
        finally:
            self.btnAuto.setEnabled(True)

        if items:
            n = self.pm.import_cookies(items)
            if has_login(items):
                self._ok(f"已导入 {n} 条 Cookie，检测到登录态。")
            else:
                self.lblTip.setText(
                    f"已导入 {n} 条 Cookie，但没找到登录标识（sessionid）。")
            return

        stats = scan_browsers()
        self.lblTip.setText(self._explain(stats))

    def _explain(self, stats) -> str:
        lines = []
        for s in stats:
            if s["total"] == 0:
                continue
            readable = s["v10"] + s["plain"]
            lines.append(f"· {s['browser']} / {s['profile']}：抖音 Cookie "
                         f"{s['total']} 条（新版加密 {s['v20']} 条 / 可读 "
                         f"{readable} 条）")
        if not lines:
            return ("没有在本机 Chrome / Edge 中发现抖音 Cookie。"
                    "请先在系统浏览器里登录抖音，或直接用扫码登录。")
        return ("找到了 Cookie，但都是新版加密格式，软件无法离线读取：\n"
                + "\n".join(lines)
                + "\n请用「去扫码登录」，或按方式二手动粘贴。")

    def _go_scan(self):
        self._ok("已打开抖音首页，请点击右上角「登录」用抖音 App 扫码。",
                 scanned=True)

    # ---------------- 手动导入 ----------------
    def manual_import(self):
        from .cookies_import import parse_cookie_string, has_login
        items = parse_cookie_string(self.edit.toPlainText())
        if not items:
            self.lblTip.setText("没有解析出有效的 Cookie，请检查粘贴内容。")
            return
        n = self.pm.import_cookies(items)
        if has_login(items):
            self._ok(f"已导入 {n} 条 Cookie，检测到登录态。")
        else:
            self.lblTip.setText(
                f"已导入 {n} 条 Cookie，但缺少 sessionid，可能仍是未登录状态。")

    # ---------------- 收尾 ----------------
    def _ok(self, msg, scanned=False):
        self.imported = True
        self.lblTip.setText(msg)
        QMessageBox.information(self, "完成", msg)
        self.accept()


class BrowserPage(QWidget):
    sigScrape = Signal(str)      # 请求抓取当前 URL
    sigStatus = Signal(str)
    # 综合了页面 DOM 与 Cookie 的最终登录结论（ok, note）。
    # 侧边栏的「登录状态」直接用它——不能只看 pm.logged_in，
    # 否则会出现「页面明明已登录、侧边栏却显示未登录」的分裂。
    sigLoginState = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm = ProfileManager.instance()
        self._dom_state = "unknown"     # guest / user / unknown
        self._resynced = False
        self._build_ui()
        self.pm.cookiesChanged.connect(self._refresh_login)
        self.pm.loggedOut.connect(self._on_logged_out)
        self._refresh_login()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("浏览器 · 登录与找主播")
        t.setObjectName("sectionTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.lblLogin = QLabel("未登录")
        self.lblLogin.setStyleSheet(
            "color:#9CA3AF; background:#F3F4F6; border-radius:10px; padding:4px 12px;")
        head.addWidget(self.lblLogin)
        self.btnImport = QPushButton("导入 / 恢复登录态")
        self.btnImport.setObjectName("iconBtn")
        self.btnImport.setToolTip(
            "从本机浏览器导入已登录的 Cookie，或手动粘贴 Cookie，或去扫码登录")
        self.btnImport.clicked.connect(self._import_cookies)
        head.addWidget(self.btnImport)
        self.btnLogout = QPushButton("登出")
        self.btnLogout.setObjectName("iconBtn")
        self.btnLogout.setToolTip("清除本机保存的登录信息，返回未登录状态")
        self.btnLogout.clicked.connect(self.logout)
        head.addWidget(self.btnLogout)
        root.addLayout(head)

        bar = QHBoxLayout()
        self.btnBack = QPushButton("←")
        self.btnBack.setObjectName("iconBtn")
        self.btnBack.setToolTip("后退")
        self.btnFwd = QPushButton("→")
        self.btnFwd.setObjectName("iconBtn")
        self.btnFwd.setToolTip("前进")
        self.btnReload = QPushButton("刷新")
        self.btnReload.setObjectName("iconBtn")
        self.editUrl = QLineEdit()
        self.editUrl.setPlaceholderText("输入网址后回车")
        self.editUrl.returnPressed.connect(self.navigate)
        self.btnGo = QPushButton("打开")
        self.btnGo.clicked.connect(self.navigate)
        self.btnHome = QPushButton("抖音首页")
        self.btnHome.clicked.connect(lambda: self.view.load(QUrl(HOME)))
        bar.addWidget(self.btnBack)
        bar.addWidget(self.btnFwd)
        bar.addWidget(self.btnReload)
        bar.addWidget(self.editUrl, 1)
        bar.addWidget(self.btnGo)
        bar.addWidget(self.btnHome)
        root.addLayout(bar)

        self.view = self.pm.new_view(self)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.urlChanged.connect(self._on_url)
        self.view.loadFinished.connect(self._on_loaded)
        root.addWidget(self.view, 1)

        foot = QHBoxLayout()
        self.lblFoot = QLabel(
            "内置浏览器只用于登录与选视频（它不带视频解码器，页面里的视频会提示"
            "「不支持格式」，属正常现象，不影响下载）；看视频请点「在系统浏览器打开」。")
        self.lblFoot.setObjectName("hint")
        self.btnScrape = QPushButton("抓取当前页面全部视频")
        self.btnScrape.setObjectName("primary")
        self.btnScrape.setCursor(Qt.PointingHandCursor)
        self.btnScrape.clicked.connect(lambda: self.sigScrape.emit(self.view.url().toString()))
        self.btnOpenExt = QPushButton("在系统浏览器打开")
        self.btnOpenExt.clicked.connect(
            lambda: QDesktopServices.openUrl(self.view.url()))
        foot.addWidget(self.lblFoot, 1)
        foot.addWidget(self.btnOpenExt)
        foot.addWidget(self.btnScrape)
        root.addLayout(foot)

        self.btnBack.clicked.connect(self.view.back)
        self.btnFwd.clicked.connect(self.view.forward)
        self.btnReload.clicked.connect(self.view.reload)

        self.view.load(QUrl(HOME))

    # ------------------------------------------------------------ 登录态
    def navigate(self):
        u = self.editUrl.text().strip()
        if not u:
            return
        if not u.startswith("http"):
            u = "https://" + u
        self.view.load(QUrl(u))

    def _on_url(self, url):
        try:
            s = url.toString() if hasattr(url, "toString") else str(url)
        except Exception:
            return
        if s and s != self.editUrl.text():
            self.editUrl.setText(s)

    def _on_loaded(self, ok):
        self._on_url(self.view.url())
        if not ok:
            return
        # 页面加载完成后，用页面自身的真实状态校正徽标
        try:
            self.view.page().runJavaScript(LOGIN_PROBE_JS, 0, self._on_dom_state)
        except Exception:
            pass

    def _on_dom_state(self, res):
        state = "unknown"
        if isinstance(res, str) and res in ("guest", "user", "unknown"):
            state = res
        self._dom_state = state
        # 已保存登录信息、页面却是游客态 → 大概率是 Cookie 没赶上首次加载，补一次
        if state == "guest" and self.pm.logged_in and not self._resynced:
            self._resynced = True
            try:
                self.pm._inject_jar()
            except Exception:
                pass
            QTimer.singleShot(600, self.view.reload)
        self._refresh_login()

    def _refresh_login(self):
        cookie_ok = self.pm.logged_in
        dom = self._dom_state
        if dom == "guest":
            ok, note = False, "抖音页面当前显示为未登录"
        elif dom == "user":
            # 页面自己都显示登录了，就以页面为准——本环境下 Cookie 信号
            # 并不可靠，只认 Cookie 会导致「明明登录了却显示未登录」。
            ok, note = True, "已确认登录（页面显示为已登录）"
        elif cookie_ok:
            ok, note = True, "本机已保存抖音登录信息"
        else:
            ok, note = False, "尚未登录抖音"
        self.lblLogin.setText("已登录" if ok else "未登录")
        self.lblLogin.setToolTip(note)
        self.lblLogin.setStyleSheet(
            "color:#0F9D58; background:#E7F6EE; border-radius:10px; padding:4px 12px;"
            if ok else
            "color:#9CA3AF; background:#F3F4F6; border-radius:10px; padding:4px 12px;")
        self.sigLoginState.emit(ok, note)

    def _import_cookies(self):
        dlg = ImportDialog(self.pm, self)
        dlg.exec()
        if dlg.imported:
            self._dom_state = "unknown"
            QTimer.singleShot(1200, self._after_import)

    def _after_import(self):
        # 导入时已同步写进 CookieStore 与内存罐，这里只需要刷新界面并重载页面
        self._refresh_login()
        try:
            self.view.reload()
        except Exception:
            pass

    def logout(self):
        """退出登录：清空 Cookie（含本机保存的会话文件），回到未登录状态"""
        if not self.pm.logged_in:
            QMessageBox.information(self, "提示", "当前已经是未登录状态。")
            return
        r = QMessageBox.question(
            self, "退出登录",
            "将清除本机保存的抖音登录信息，下次需要重新扫码登录。\n继续？")
        if r != QMessageBox.Yes:
            return
        self.pm.clear_cookies()       # 会触发 _on_logged_out

    def _on_logged_out(self):
        """不论从哪个页面发起登出，浏览器页都同步回未登录状态"""
        self._dom_state = "unknown"
        self._resynced = True
        self._refresh_login()
        QTimer.singleShot(400, lambda: self.view.load(QUrl(HOME)))
        QTimer.singleShot(2500, self._after_logout_probe)

    def _after_logout_probe(self):
        try:
            self.view.page().runJavaScript(LOGIN_PROBE_JS, 0, self._on_dom_state)
        except Exception:
            pass

    def open_login(self):
        """弹出登录入口：加载抖音首页并提示"""
        self.view.load(QUrl(HOME))
        QMessageBox.information(
            self, "登录抖音",
            "已在下方浏览器中打开抖音首页。\n\n"
            "请点击页面右上角的「登录」按钮，用抖音 App 扫码完成登录。\n"
            "登录成功后状态会变为「已登录」，登录信息会保存在本机，"
            "下次打开无需再扫。")
