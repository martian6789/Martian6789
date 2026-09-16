# -*- coding: utf-8 -*-
"""设置页面"""
import os
import subprocess

from PySide6.QtCore import QSettings, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QGroupBox, QFormLayout, QMessageBox, QTextBrowser, QFileDialog)

from .config import (app_data_dir, profile_dir, default_save_dir, APP_TITLE,
                     APP_VERSION, DEFAULT_CONCURRENCY)
from .webengine import ProfileManager

HELP = """
<h3 style="margin-top:0">三步开始</h3>
<ol style="line-height:1.8">
<li><b>登录</b>：浏览器页右上角扫码（登录态存在本机，下次免扫）。</li>
<li><b>采集</b>：打开主播主页 → 点「抓取当前页面全部视频」；
或直接把主页链接粘到下载页 →「一键下载该主播全部视频」。</li>
<li><b>下载</b>：勾选要下的视频，选目录与画质，点「开始下载」。</li>
</ol>

<h3>几个要点</h3>
<ul style="line-height:1.8">
<li>暂停会保留已下载部分，点「继续」断点续传；「停止」则丢弃半成品。</li>
<li>下完前文件带 <code>.part.mp4</code> 后缀，属正常，完成后自动改名。</li>
<li>并发默认 %d（解析/下载都是），并发越高越容易触发平台风控；
反复失败就调回 1~2。</li>
<li>采集数量以主页显示的作品数为准，少几个属正常（含已删除/私密作品）。</li>
</ul>

<h3>常见问题</h3>
<ul style="line-height:1.8">
<li><b>提示下载失败 / 需要人工验证？</b> 点「去验证」在浏览器里拖一次滑块，
回来点「继续」即可。</li>
<li><b>拿不到视频地址？</b> 多为解析太密被限流，把并发调小，
等一会儿点「重试失败的项」。</li>
<li><b>数量偏少？</b> 先确认已登录，再点一次采集即可补齐（不会重复添加）。</li>
<li><b>文件名不对？</b> 优先用视频文案；作者没写文案时用「日期+时长」
或「合集名 第N集」兜底。</li>
<li><b>文件很小打不开？</b> 下载后会校验时长，不合格会自动重试；
持续失败多为磁盘空间不足。</li>
</ul>

<p style="color:#6B7280">下载内容仅供个人学习收藏，请尊重作者版权。</p>
""" % DEFAULT_CONCURRENCY



class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("DouyinDownloader", "DouyinDownloader")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        t = QLabel("设置")
        t.setObjectName("sectionTitle")
        root.addWidget(t)

        g = QGroupBox("常规")
        f = QFormLayout(g)
        f.setSpacing(10)

        row = QHBoxLayout()
        self.editDir = QLineEdit(self.settings.value("save_dir", default_save_dir()))
        b1 = QPushButton("浏览…")
        b1.clicked.connect(self.choose_dir)
        row.addWidget(self.editDir, 1)
        row.addWidget(b1)
        f.addRow("默认保存目录", row)

        self.spin = QSpinBox()
        self.spin.setRange(1, 10)
        self.spin.setValue(int(self.settings.value("concurrency", 10)))
        self.spin.setFixedWidth(80)
        self.spin.setToolTip("同时进行的下载任务数，越大越快，但更占带宽")
        self.spin.valueChanged.connect(
            lambda v: self.settings.setValue("concurrency", v))
        f.addRow("同时下载数量", self.spin)

        self.spinR = QSpinBox()
        self.spinR.setRange(1, 10)
        self.spinR.setValue(int(self.settings.value("resolve_concurrency", DEFAULT_CONCURRENCY)))
        self.spinR.setFixedWidth(80)
        self.spinR.setToolTip("同时解析几个视频的直链，越大越快。"
                              "8 以上建议机器内存 8GB 起")
        self.spinR.valueChanged.connect(
            lambda v: self.settings.setValue("resolve_concurrency", v))
        f.addRow("同时解析数量", self.spinR)

        tip2 = QLabel("解析负责拿直链、下载负责存文件，两者同时进行。"
                      "机器卡顿可适当调小。")
        tip2.setObjectName("hint")
        tip2.setWordWrap(True)
        f.addRow("", tip2)

        root.addWidget(g)

        g2 = QGroupBox("账号")
        v2 = QVBoxLayout(g2)
        row2 = QHBoxLayout()
        self.btnClearCookie = QPushButton("退出登录（清除本机登录信息）")
        self.btnClearCookie.setObjectName("danger")
        self.btnClearCookie.clicked.connect(self.clear_cookie)
        self.btnData = QPushButton("打开数据目录")
        self.btnData.clicked.connect(self.open_data)
        row2.addWidget(self.btnClearCookie)
        row2.addWidget(self.btnData)
        row2.addStretch(1)
        v2.addLayout(row2)
        lbl = QLabel("登录信息与配置保存在：%s\n"
                     "（其中 session.json 是本机登录信息的备份，"
                     "删除它等同于退出登录）" % profile_dir())
        lbl.setObjectName("hint")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v2.addWidget(lbl)
        root.addWidget(g2)

        g3 = QGroupBox("使用帮助")
        v3 = QVBoxLayout(g3)
        tb = QTextBrowser()
        tb.setHtml(HELP)
        tb.setOpenExternalLinks(True)
        v3.addWidget(tb)
        root.addWidget(g3, 1)

        foot = QLabel(f"{APP_TITLE} v{APP_VERSION}")
        foot.setObjectName("hint")
        root.addWidget(foot)

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认保存目录", self.editDir.text())
        if d:
            self.editDir.setText(d)
            self.settings.setValue("save_dir", d)

    def clear_cookie(self):
        r = QMessageBox.question(self, "确认", "将清除已保存的登录状态，需要重新扫码登录。继续？")
        if r != QMessageBox.Yes:
            return
        ProfileManager.instance().clear_cookies()
        QMessageBox.information(self, "完成", "已清除登录 Cookie。")

    def open_data(self):
        d = app_data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))
