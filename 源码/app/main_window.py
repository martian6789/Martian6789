# -*- coding: utf-8 -*-
"""主窗口"""
import os
import sys

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QIcon, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLabel,
    QStackedWidget, QStatusBar, QMessageBox, QListWidgetItem)

from .config import APP_TITLE, APP_VERSION
from .style import QSS
from .ui_download import DownloadPage
from .ui_browser import BrowserPage
from .ui_settings import SettingsPage
from .webengine import ProfileManager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self.resize(1180, 780)
        self.setMinimumSize(1020, 660)

        central = QWidget()
        central.setObjectName("content")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 侧边栏 ----
        side = QWidget()
        side.setObjectName("sidebar")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        ttl = QLabel(APP_TITLE)
        ttl.setObjectName("appTitle")
        sub = QLabel(f"v{APP_VERSION}   ·   最高画质")
        sub.setObjectName("appSub")
        ttl.setToolTip(f"{APP_TITLE}  v{APP_VERSION}")
        sl.addWidget(ttl)
        sl.addWidget(sub)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setSpacing(2)
        for name in ("批量下载", "浏览器 · 登录", "设置"):
            it = QListWidgetItem("   " + name)
            it.setSizeHint(QSize(0, 46))
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self.switch_page)
        sl.addWidget(self.nav, 1)

        foot = QLabel("登录状态：")
        foot.setObjectName("navFooter")
        self.lblLogin = QLabel("检测中…")
        self.lblLogin.setObjectName("navFooter")
        sl.addWidget(foot)
        sl.addWidget(self.lblLogin)
        sl.addSpacing(10)

        lay.addWidget(side)

        # ---- 内容区 ----
        self.stack = QStackedWidget()
        self.pageDownload = DownloadPage()
        self.pageBrowser = BrowserPage()
        self.pageSettings = SettingsPage()
        self.stack.addWidget(self.pageDownload)
        self.stack.addWidget(self.pageBrowser)
        self.stack.addWidget(self.pageSettings)
        lay.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        sb = QStatusBar()
        sb.setStyleSheet("")
        self.setStatusBar(sb)
        self.sbLabel = QLabel("就绪")
        sb.addWidget(self.sbLabel)

        # ---- 信号连接 ----
        self.pageDownload.sigStatus.connect(self.sbLabel.setText)
        self.pageDownload.sigOpenBrowser.connect(self._goto_browser_and_fetch)
        self.pageDownload.sigSolveCaptcha.connect(self._goto_browser_for_captcha)
        self.pageBrowser.sigScrape.connect(self._scrape_from_browser)
        ProfileManager.instance().cookiesChanged.connect(self._refresh_login)
        # 浏览器页的综合登录结论（页面 DOM 优先）直接驱动侧边栏文字
        self.pageBrowser.sigLoginState.connect(self._on_login_state)

        self.nav.setCurrentRow(0)
        self._refresh_login()

    def switch_page(self, i):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)

    def _goto_browser_and_fetch(self):
        self.nav.setCurrentRow(1)
        url = self.pageBrowser.view.url().toString()
        if url and "douyin.com" in url and "/user/" in url:
            self._scrape_from_browser(url)
        else:
            self.sbLabel.setText("请在浏览器中打开主播主页，然后点「抓取当前页面全部视频」")
            QMessageBox.information(
                self, "提示",
                "请在浏览器中打开要下载的主播主页（网址含 /user/），\n"
                "然后点底部的「抓取当前页面全部视频」按钮。")

    def _scrape_from_browser(self, url: str):
        if not url or "douyin.com" not in url:
            QMessageBox.information(self, "提示", "当前页面不是抖音页面")
            return
        self.nav.setCurrentRow(0)
        self.pageDownload.fetch_url(url)

    def _goto_browser_for_captcha(self, url: str):
        """切到浏览器页并直接打开触发验证的视频页，让用户滑动过验证。

        浏览器页与解析视图共用同一个 Profile，Cookie 与风控状态互通，
        在这里过完验证，解析那边立刻就能继续拿流。
        """
        self.nav.setCurrentRow(1)
        try:
            self.pageBrowser.view.load(QUrl(url or "https://www.douyin.com/"))
        except Exception:
            pass
        self.sbLabel.setText("请在浏览器中拖动滑块完成验证，然后回「批量下载」点「继续」")

    def _refresh_login(self):
        ok = ProfileManager.instance().logged_in
        self.lblLogin.setText("已登录" if ok else "未登录")
        color = "#0F9D58" if ok else "#6B7280"
        self.lblLogin.setStyleSheet(f"color:{color}; font-size:11px; padding:0 18px 4px 18px;")

    def _on_login_state(self, ok: bool, note: str):
        """浏览器页综合了「页面 DOM + Cookie」的结论——以它为准。

        早期这里只看 pm.logged_in，页面明明已登录（有头像），
        侧边栏却一直显示「未登录」，用户以为登录没成功。
        """
        self.lblLogin.setText("已登录" if ok else "未登录")
        self.lblLogin.setToolTip(note)
        color = "#0F9D58" if ok else "#6B7280"
        self.lblLogin.setStyleSheet(f"color:{color}; font-size:11px; padding:0 18px 4px 18px;")

    def closeEvent(self, e):
        try:
            self.pageDownload.stop_download()
        except Exception:
            pass
        # 解析用的视图池是常驻的（销毁后重建会拿不到视频流），退出时释放掉
        try:
            self.pageDownload.resolver.shutdown()
        except Exception:
            pass
        # 退出前把本次登录态落盘。Chromium 自己是攒批写 Cookie 的，
        # 不主动保存的话，登录后很快关闭软件会丢掉会话。
        try:
            ProfileManager.instance()._save_session()
        except Exception:
            pass
        super().closeEvent(e)
