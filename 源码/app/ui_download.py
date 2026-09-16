# -*- coding: utf-8 -*-
"""批量下载页面"""
import os
import re
from typing import List, Dict

from PySide6.QtCore import Qt, Signal, QSettings, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QComboBox, QCheckBox, QProgressBar, QFileDialog, QMessageBox,
    QGroupBox, QSizePolicy)

from .config import (safe_filename, fmt_size, fmt_dur, default_save_dir,
                     fallback_title, DEFAULT_CONCURRENCY)
from .scraper import ScrapeController
from .resolver import ResolveController
from .downloader import DownloadManager, DownloadTask, free_bytes
from . import runlog

COL_CHECK, COL_IDX, COL_TITLE, COL_DUR, COL_STATUS, COL_SIZE, COL_PROG = range(7)

STATUS_WAIT = "等待中"
STATUS_RESOLVE = "解析中"
STATUS_DOWNLOAD = "下载中"
STATUS_DONE = "已完成"
STATUS_FAIL = "失败"
STATUS_SKIP = "已跳过"
STATUS_PAUSE = "已暂停"


class ScrapeWindow(QWidget):
    """采集时显示的可见浏览器窗口（隐藏页面不会触发懒加载）"""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("正在采集视频列表")
        self.resize(1120, 780)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QLabel("正在自动滚动采集该主播的全部视频，请不要关闭此窗口…"
                     "（直接关闭即中止采集）")
        top.setStyleSheet(
            "background:#17191F;color:#E5E7EB;padding:0 12px;font-size:12px;")
        # 关键：QLabel 默认的垂直尺寸策略是 Preferred，放进布局后会「吃掉」
        # 多余空间——于是顶部出现一大片黑色空条（截图里上半屏全黑就是这个
        # 原因，而不是网页没渲染）。固定成一行高度即可。
        top.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        top.setFixedHeight(32)
        top.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(top)
        self.lblTop = top
        # 让这条窄标签顺便当进度条用（已采集 X / 共 Y）
        try:
            controller.sigProgress.connect(self._on_prog)
        except Exception:
            pass

    def _on_prog(self, msg):
        self.lblTop.setText(f"{msg}　（请勿关闭本窗口，关闭即中止采集）")

    def closeEvent(self, e):
        try:
            self.controller.cancel()
        except Exception:
            pass
        super().closeEvent(e)


class DownloadPage(QWidget):
    sigOpenBrowser = Signal()
    sigStatus = Signal(str)
    sigSolveCaptcha = Signal(str)   # 携带一条视频地址，让浏览器页打开它过验证

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("DouyinDownloader", "DouyinDownloader")
        self.items: List[Dict] = []
        self._task_refs: list = []
        self._auto_start = False
        self.pending = set()
        self.done_count = 0
        self.fail_count = 0
        self.skip_count = 0
        self._failed_rows: List[int] = []
        self._total = 0
        self._phase = "idle"          # idle / running / paused
        self._scraping = False
        self._save_dir = ""
        self._resume_rows: List[int] = []
        self._payloads: Dict[int, dict] = {}     # row -> 解析结果（继续时复用）
        self._auto_retried = False

        self.scraper = ScrapeController(self)
        self.scraper.sigProgress.connect(self._on_scrape_progress)
        self.scraper.sigFinished.connect(self._on_scrape_finished)
        self.scraper.sigError.connect(self._on_scrape_error)

        self.resolver = ResolveController(self)
        self.resolver.sigResolved.connect(self._on_resolved)
        self.resolver.sigFailed.connect(self._on_resolve_failed)
        self.resolver.sigProgress.connect(self._on_resolve_progress)
        self.resolver.sigAllDone.connect(self._maybe_finish)
        self.resolver.sigStalled.connect(self._on_stalled)
        self.resolver.sigCaptcha.connect(self._on_captcha)

        conc = self._int_setting("concurrency", DEFAULT_CONCURRENCY)
        self.dm = DownloadManager(self, conc)
        self.resolver.set_concurrency(
            self._int_setting("resolve_concurrency", DEFAULT_CONCURRENCY))

        self._build_ui()

    def _int_setting(self, key: str, default: int) -> int:
        # v1.2.0 起把默认并发从 10 降到 5：实测 10 路同时加载播放页会被抖音
        # 限流，反而出现「前几个成功、后面整批失败」。老版本存过的 10 一次性
        # 迁移到 5，免得升级后还是老样子。
        if not self.settings.value("conc_migrated_v12", False, type=bool):
            self.settings.setValue("concurrency", 5)
            self.settings.setValue("resolve_concurrency", 5)
            self.settings.setValue("conc_migrated_v12", True)
        # v1.3.1 起默认并发再降到 1：并发 5 依然频繁触发风控验证码中间页，
        # 一旦触发整批解析全挂，速度反而归零。同样只迁移一次，之后用户
        # 自己改过的值不会再被动。
        if not self.settings.value("conc_migrated_v13", False, type=bool):
            self.settings.setValue("concurrency", DEFAULT_CONCURRENCY)
            self.settings.setValue("resolve_concurrency", DEFAULT_CONCURRENCY)
            self.settings.setValue("conc_migrated_v13", True)
        try:
            return int(self.settings.value(key, default))
        except Exception:
            return default

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        title = QLabel("批量下载")
        title.setObjectName("sectionTitle")
        root.addWidget(title)

        # ---- 抓取区 ----
        g = QGroupBox("视频来源")
        v = QVBoxLayout(g)
        v.setSpacing(9)

        row1 = QHBoxLayout()
        self.editUrl = QLineEdit()
        self.editUrl.setPlaceholderText("粘贴主播主页链接，例如 https://www.douyin.com/user/MS4wLjABAAAA...")
        self.editUrl.returnPressed.connect(self.one_click)
        self.btnOneClick = QPushButton("一键下载该主播全部视频")
        self.btnOneClick.setObjectName("primary")
        self.btnOneClick.setFixedHeight(34)
        self.btnOneClick.setCursor(Qt.PointingHandCursor)
        self.btnOneClick.setToolTip("自动抓取该主播主页的全部视频，并以最高画质下载")
        self.btnOneClick.clicked.connect(self.one_click)
        self.btnFetch = QPushButton("仅抓取列表")
        self.btnFetch.setToolTip("只把视频加入列表，不立即下载")
        self.btnFetch.setCursor(Qt.PointingHandCursor)
        self.btnFetch.clicked.connect(lambda: self.fetch_from_url(False))
        row1.addWidget(self.editUrl, 1)
        row1.addWidget(self.btnOneClick)
        row1.addWidget(self.btnFetch)
        v.addLayout(row1)

        row1b = QHBoxLayout()
        hint = QLabel("提示：先在【浏览器】页扫码登录抖音，再打开主播主页，然后回来点「抓取浏览器当前页」")
        hint.setObjectName("hint")
        self.btnFetchBrowser = QPushButton("抓取浏览器当前页")
        self.btnFetchBrowser.setCursor(Qt.PointingHandCursor)
        self.btnFetchBrowser.clicked.connect(lambda: self.sigOpenBrowser.emit())
        row1b.addWidget(hint, 1)
        row1b.addWidget(self.btnFetchBrowser)
        v.addLayout(row1b)

        row1c = QHBoxLayout()
        self.btnImport = QPushButton("导入视频链接")
        self.btnImport.setToolTip("粘贴若干视频链接或纯 ID，每行一个")
        self.btnImport.clicked.connect(self.import_links)
        self.btnClear = QPushButton("清空列表")
        self.btnClear.clicked.connect(self.clear_list)
        self.lblCount = QLabel("共 0 个视频")
        self.lblCount.setObjectName("hint")
        row1c.addWidget(self.btnImport)
        row1c.addWidget(self.btnClear)
        row1c.addStretch(1)
        row1c.addWidget(self.lblCount)
        v.addLayout(row1c)

        root.addWidget(g)

        # ---- 列表 ----
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["", "#", "标题", "时长", "状态", "大小", "进度"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        hh.setSectionResizeMode(COL_IDX, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_DUR, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_PROG, QHeaderView.ResizeToContents)
        # 勾选框列给足宽度，鼠标更容易点中
        self.table.setColumnWidth(COL_CHECK, 64)
        self.table.setColumnWidth(COL_PROG, 70)
        # 「全选」放在勾选列的正上方（表头上），几百条列表时不必去下面找按钮。
        # QHeaderView 是个 QWidget，允许挂子控件，只要自己跟随表头几何变化定位。
        self.chkAll = QCheckBox("全选", hh)
        self.chkAll.setCursor(Qt.PointingHandCursor)
        self.chkAll.setToolTip("勾选 / 取消勾选列表里的全部视频")
        self.chkAll.toggled.connect(self._on_check_all)
        self._place_check_all()
        hh.geometriesChanged.connect(self._place_check_all)
        self.table.horizontalScrollBar().valueChanged.connect(
            self._place_check_all)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self.table, 1)

        # ---- 设置区 ----
        g2 = QGroupBox("下载设置")
        v2 = QVBoxLayout(g2)
        v2.setSpacing(9)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("保存到"))
        self.editDir = QLineEdit(self.settings.value("save_dir", default_save_dir()))
        btnDir = QPushButton("浏览…")
        btnDir.clicked.connect(self.choose_dir)
        self.btnOpenDir = QPushButton("打开")
        self.btnOpenDir.setObjectName("ghost")
        self.btnOpenDir.clicked.connect(self.open_dir)
        row2.addWidget(self.editDir, 1)
        row2.addWidget(btnDir)
        row2.addWidget(self.btnOpenDir)
        v2.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("画质"))
        self.comboQ = QComboBox()
        self.comboQ.addItems(["最高画质（推荐）", "较高画质", "标准画质"])
        self.comboQ.setCurrentIndex(int(self.settings.value("quality", 0)))
        self.comboQ.setFixedWidth(150)
        row3.addWidget(self.comboQ)

        row3.addSpacing(16)
        self.chkSkip = QCheckBox("跳过已存在的文件")
        self.chkSkip.setChecked(True)
        row3.addWidget(self.chkSkip)
        self.chkIdName = QCheckBox("文件名附加视频ID")
        self.chkIdName.setChecked(self.settings.value("name_with_id", "0") == "1")
        self.chkIdName.setToolTip("勾选后文件名会带上视频 ID，方便与抖音一一对应")
        row3.addWidget(self.chkIdName)
        row3.addStretch(1)

        self.btnSelectAll = QPushButton("全选")
        self.btnSelectAll.clicked.connect(self.select_all)
        self.btnInvert = QPushButton("反选")
        self.btnInvert.clicked.connect(self.invert_selection)
        row3.addWidget(self.btnSelectAll)
        row3.addWidget(self.btnInvert)
        v2.addLayout(row3)

        root.addWidget(g2)

        # ---- 操作区 ----
        row4 = QHBoxLayout()
        self.btnStart = QPushButton("开始下载")
        self.btnStart.setObjectName("primary")
        self.btnStart.setFixedHeight(36)
        self.btnStart.setMinimumWidth(130)
        self.btnStart.setCursor(Qt.PointingHandCursor)
        self.btnStart.clicked.connect(self.start_download)

        self.btnPause = QPushButton("暂停")
        self.btnPause.setFixedHeight(36)
        self.btnPause.setMinimumWidth(90)
        self.btnPause.setEnabled(False)
        self.btnPause.setToolTip("暂停后已下载的部分会保留，点「继续」可从断点接着下")
        self.btnPause.clicked.connect(self.pause_download)

        self.btnStop = QPushButton("停止")
        self.btnStop.setFixedHeight(36)
        self.btnStop.setEnabled(False)
        self.btnStop.setToolTip("停止本次任务，并丢弃未下完的临时文件")
        self.btnStop.clicked.connect(self.stop_download)

        self.btnRetry = QPushButton("重试失败的项")
        self.btnRetry.setFixedHeight(36)
        self.btnRetry.setEnabled(False)
        self.btnRetry.setToolTip("只重新下载列表中失败的视频")
        self.btnRetry.clicked.connect(lambda: self.retry_failed())

        self.btnVerify = QPushButton("去验证")
        self.btnVerify.setFixedHeight(36)
        self.btnVerify.setCursor(Qt.PointingHandCursor)
        self.btnVerify.setToolTip(
            "打开浏览器页手动完成抖音的滑动验证码。\n"
            "提示「下载失败 / 需要人工验证」时点它，过完验证回来点「继续」即可。")
        self.btnVerify.clicked.connect(self._go_verify)

        self.bar = QProgressBar()
        self.bar.setFixedHeight(10)
        self.bar.setValue(0)
        self.lblStat = QLabel("就绪")
        self.lblStat.setObjectName("hint")
        row4.addWidget(self.btnStart)
        row4.addWidget(self.btnPause)
        row4.addWidget(self.btnStop)
        row4.addWidget(self.btnRetry)
        row4.addWidget(self.btnVerify)
        row4.addWidget(self.bar, 1)
        row4.addWidget(self.lblStat)
        root.addLayout(row4)

    # ---------------- 按钮可用状态 ----------------
    def _update_buttons(self):
        running = self._phase == "running"
        busy = self._phase in ("running", "paused", "waiting")
        can_edit = (not busy) and (not self._scraping)
        self.btnStart.setEnabled(can_edit)
        self.btnStop.setEnabled(busy)
        self.btnPause.setEnabled(running or self._phase == "paused")
        self.btnPause.setText("继续" if self._phase == "paused" else "暂停")
        self.btnFetch.setEnabled(can_edit)
        self.btnFetchBrowser.setEnabled(can_edit)
        self.btnImport.setEnabled(can_edit)
        self.btnClear.setEnabled(can_edit)
        self.btnRetry.setEnabled(can_edit and bool(self._failed_rows))

    def _busy(self, on: bool, msg: str = ""):
        """采集期间禁用操作"""
        self._scraping = on
        self._update_buttons()
        if msg:
            self.lblStat.setText(msg)
            self.sigStatus.emit(msg)

    # ---------------- 抓取 ----------------
    def fetch_from_url(self, with_url=True):
        url = self.editUrl.text().strip() if with_url else ""
        if with_url and not url:
            QMessageBox.information(self, "提示", "请先粘贴主播主页链接")
            return
        if url and not url.startswith("http"):
            url = "https://" + url
            self.editUrl.setText(url)
        self._busy(True, "正在采集视频列表…")
        win = ScrapeWindow(self.scraper)
        win.show()
        self.scraper.start(url or self.editUrl.text().strip(), host=win)

    def one_click(self):
        """一键：抓取主播全部视频 → 自动全选（不自动下载，由用户点开始）"""
        if self._phase != "idle":
            QMessageBox.information(self, "提示", "任务进行中，请先停止")
            return
        if not self.editUrl.text().strip():
            QMessageBox.information(self, "提示", "请先粘贴主播主页链接")
            return
        self._auto_start = True
        self.fetch_from_url()

    def fetch_url(self, url: str, auto_start: bool = True):
        self._auto_start = auto_start
        self._busy(True, "正在采集视频列表…")
        self.scraper.start(url)

    def _on_scrape_progress(self, msg):
        self.lblStat.setText(msg)
        self.sigStatus.emit(msg)

    def _on_scrape_error(self, msg):
        self._busy(False)
        self.lblStat.setText(msg)
        if msg != "已取消采集":
            QMessageBox.warning(self, "采集失败", msg)

    def _on_scrape_finished(self, payload):
        self._busy(False)
        # 采集器现在会把「网页上显示的作品总数」一并带回，用作校准：
        # 只采到一半时能明确提示，而不是悄悄少一半。
        if isinstance(payload, dict):
            items = payload.get("items") or []
            expected = int(payload.get("expected") or 0)
        else:                       # 兼容旧调用
            items, expected = payload or [], 0
        added = self.add_items(items)
        got = len(items)

        incomplete = bool(expected) and got < expected
        if incomplete:
            self.lblStat.setText(
                f"采集完成：{got} / 共 {expected} 个（可能不完整，可再点一次采集）")
        else:
            self.lblStat.setText(f"采集完成，新增 {added} 个视频")
        self.sigStatus.emit(self.lblStat.text())

        # 「一键」只帮你把列表抓回来并全选；下不下载、什么时候下载由用户
        # 自己点「开始下载」——早期版本会立刻自动开跑，用户想先核对一下
        # 列表/保存目录都来不及。
        if self._auto_start:
            self._auto_start = False
            self.select_all()
            if incomplete:
                QMessageBox.information(
                    self, "采集可能不完整",
                    f"网页显示该主播共有 {expected} 个作品，本次采集到 {got} 个。\n"
                    "可再点一次「采集」补齐（已采集到的不会重复添加）。\n\n"
                    "确认无误后点「开始下载」。")
            else:
                self.lblStat.setText(
                    f"已采集并全选 {got} 个视频，点「开始下载」开始")
                self.sigStatus.emit(self.lblStat.text())
            return
        if added == 0:
            QMessageBox.information(self, "提示", "没有发现新的视频（可能已全部在列表中）")
            return
        if incomplete:
            QMessageBox.information(
                self, "采集可能不完整",
                f"网页显示该主播共有 {expected} 个作品，本次只采集到 {got} 个。\n\n"
                "通常是抖音对「翻页太快」做了限流。可以再点一次「采集」，"
                "已采集到的不会重复添加，会接着把剩下的补上。")

    def import_links(self):
        text, ok = self._multi_input()
        if not ok or not text.strip():
            return
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = (re.search(r"/video/(\d{14,25})", line)
                 or re.fullmatch(r"(\d{14,25})", line))
            if m:
                items.append({"id": m.group(1), "title": ""})
        if not items:
            QMessageBox.information(self, "提示", "未识别到视频链接或 ID")
            return
        added = self.add_items(items)
        self.lblStat.setText(f"导入 {added} 个视频")

    def _multi_input(self):
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle("导入视频链接")
        d.resize(560, 380)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("每行一个视频链接或视频 ID："))
        te = QTextEdit()
        te.setPlaceholderText("https://www.douyin.com/video/1234567890123456789")
        lay.addWidget(te, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("确定")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec():
            return te.toPlainText(), True
        return "", False

    # ---------------- 列表管理 ----------------
    def add_items(self, items: List[Dict]) -> int:
        exist = {it["id"] for it in self.items}
        added = 0
        for it in items:
            vid = str(it.get("id", "")).strip()
            if not vid or vid in exist:
                continue
            exist.add(vid)
            try:
                dur = float(it.get("dur") or 0)
            except Exception:
                dur = 0.0
            self.items.append({
                "id": vid,
                "title": (it.get("title") or "").strip(),
                "dur": dur,
                "ct": float(it.get("ct") or 0),
                "mix": str(it.get("mix") or ""),
                "mix_id": str(it.get("mix_id") or ""),
                "ep": 0,
            })
            added += 1
        if added:
            self._assign_episodes()
            self._rebuild_table()
        return added

    def _assign_episodes(self):
        """给属于同一合集/短剧的作品编号。

        抖音的列表接口只给合集名、不给集数，但集数在合集内是按发布时间
        递增的，所以按作品 ID（时间有序）排序即可得到「第几集」。
        """
        groups = {}
        for it in self.items:
            key = it.get("mix_id") or it.get("mix") or ""
            if key:
                groups.setdefault(key, []).append(it)
        for arr in groups.values():
            if len(arr) < 2:
                continue
            arr.sort(key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 0)
            for i, it in enumerate(arr, 1):
                it["ep"] = i

    def title_of(self, it: Dict) -> str:
        """列表显示 / 文件名用的标题：优先真实文案，其次元数据兜底。"""
        t = (it.get("title") or "").strip()
        if t:
            return t
        return fallback_title(it.get("ct"), it.get("dur"),
                              it.get("mix"), it.get("ep"))

    def _rebuild_table(self):
        # 全量重建（状态重置）
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            # 注意：这里刻意不加 Qt.ItemIsUserCheckable。
            # 加了之后 Qt 会在点击勾选框时自己切换一次，而 cellClicked 里
            # 我又切一次，两次叠加就等于没反应——这正是「点很多次才勾上」
            # 的原因。改为完全由我们的点击处理逻辑负责。
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setData(Qt.CheckStateRole, Qt.Checked)
            chk.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, COL_CHECK, chk)

            idx = QTableWidgetItem(str(r + 1))
            idx.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, COL_IDX, idx)

            title = self.title_of(it) or f"视频 {it['id']}"
            titem = QTableWidgetItem(title)
            titem.setToolTip(title)
            self.table.setItem(r, COL_TITLE, titem)

            sec = float(it.get("dur") or 0)
            ditem = QTableWidgetItem(fmt_dur(sec) if sec > 0 else "—")
            ditem.setTextAlignment(Qt.AlignCenter)
            if sec > 0:
                ditem.setToolTip(f"{sec:.1f} 秒")
            self.table.setItem(r, COL_DUR, ditem)

            self.table.setItem(r, COL_STATUS, QTableWidgetItem(STATUS_WAIT))
            self.table.setItem(r, COL_SIZE, QTableWidgetItem(""))
            self.table.setItem(r, COL_PROG, QTableWidgetItem(""))
        self.lblCount.setText(f"共 {len(self.items)} 个视频")
        self._place_check_all()
        self._refresh_check_all()
        self._update_bar()

    def selected_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it and it.checkState() == Qt.Checked:
                rows.append(r)
        return rows

    def _place_check_all(self):
        """把「全选」控件贴到勾选列的表头格子上（跟随缩放 / 横向滚动）。"""
        try:
            hh = self.table.horizontalHeader()
            x = hh.sectionViewportPosition(COL_CHECK) + 4
            y = max(0, (hh.height() - 22) // 2)
            self.chkAll.setGeometry(x, y, 58, 22)
        except Exception:
            pass

    def _on_check_all(self, on: bool):
        st = Qt.Checked if on else Qt.Unchecked
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it:
                it.setCheckState(st)

    def _refresh_check_all(self):
        """手动勾选某几行后，让表头的「全选」反映真实状态（全选/半选/未选）。"""
        total = self.table.rowCount()
        on = 0
        for r in range(total):
            it = self.table.item(r, COL_CHECK)
            if it and it.checkState() == Qt.Checked:
                on += 1
        if total and on == total:
            state = Qt.Checked
        elif on:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Unchecked
        try:
            self.chkAll.blockSignals(True)
            self.chkAll.setTristate(state == Qt.PartiallyChecked)
            self.chkAll.setCheckState(state)
            self.chkAll.blockSignals(False)
        except Exception:
            pass

    def _go_verify(self):
        """手动打开浏览器页做滑动验证码（触发风控时用户可主动来点）。"""
        vid = ""
        for r in sorted(self.pending):
            if 0 <= r < len(self.items):
                vid = self.items[r]["id"]
                break
        if not vid and self.items:
            vid = self.items[0]["id"]
        self.sigSolveCaptcha.emit(
            f"https://www.douyin.com/video/{vid}" if vid
            else "https://www.douyin.com/")
        self.lblStat.setText("已打开浏览器，请拖动滑块完成验证")

    def _toggle_row(self, r):
        it = self.table.item(r, COL_CHECK)
        if not it:
            return
        on = it.checkState() == Qt.Checked
        it.setCheckState(Qt.Unchecked if on else Qt.Checked)
        self._refresh_check_all()

    def select_all(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it:
                it.setCheckState(Qt.Checked)
        self._refresh_check_all()

    def invert_selection(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it:
                it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked
                                 else Qt.Checked)
        self._refresh_check_all()

    def clear_list(self):
        if self._phase != "idle":
            QMessageBox.information(self, "提示", "下载进行中，请先停止")
            return
        self.items.clear()
        self._failed_rows.clear()
        self._payloads.clear()
        self.table.setRowCount(0)
        self.lblCount.setText("共 0 个视频")
        self._update_bar()
        self._update_buttons()

    def _on_cell_clicked(self, r, c):
        # 点整行任意位置都能勾选/取消——勾选框本身只有 15px，很难点中。
        self._toggle_row(r)

    def _set(self, row, col, text):
        it = self.table.item(row, col)
        if it is None:
            it = QTableWidgetItem()
            self.table.setItem(row, col, it)
        it.setText(text)

    # ---------------- 文件名规划 ----------------
    def build_filename(self, title: str, vid: str, item: Dict = None) -> str:
        base = safe_filename(title) if title else ""
        if not base and item:
            # 没有文案时用元数据兜底（合集集数 / 发布日期 / 时长）
            base = safe_filename(fallback_title(item.get("ct"), item.get("dur"),
                                                item.get("mix"), item.get("ep")))
        if not base:
            base = f"抖音视频_{vid}"
        if self.chkIdName.isChecked():
            base = f"{base}_{vid}"
        return base + ".mp4"

    def _fname(self, row: int) -> str:
        it = self.items[row]
        return it.get("fname") or self.build_filename(
            it.get("title"), it["id"], it)

    def _plan_names(self, rows, save_dir, reuse=True):
        """给每一行确定一个稳定的文件名。

        两个要点：
        1. 同名的 ``.part.mp4`` 存在说明上次是「暂停」而不是失败——必须沿用
           同一个文件名，否则续传找不到断点，等于白下。
        2. 其余情况遇到已存在的文件或同批冲突就依次退让序号，绝不覆盖。
        """
        used = set()
        plan = {}
        for r in rows:
            it = self.items[r]
            cand = (it.get("fname") if reuse else "") or \
                self.build_filename(it.get("title"), it["id"], it)
            stem, ext = os.path.splitext(cand)
            part = os.path.join(save_dir, stem + ".part" + ext)
            full = os.path.join(save_dir, cand)
            if (os.path.exists(part) and not os.path.exists(full)
                    and cand.lower() not in used):
                name = cand                      # 续传：沿用原名
            else:
                name = cand
                n = 1
                while (name.lower() in used
                       or os.path.exists(os.path.join(save_dir, name))):
                    n += 1
                    name = "%s (%d)%s" % (stem, n, ext)
            used.add(name.lower())
            plan[r] = name
        for r, nm in plan.items():
            self.items[r]["fname"] = nm
        return plan

    # ---------------- 下载 ----------------
    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self.editDir.text() or default_save_dir())
        if d:
            self.editDir.setText(d)
            self.settings.setValue("save_dir", d)

    def open_dir(self):
        d = self.editDir.text().strip()
        if d and os.path.isdir(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def start_download(self, _retry=False):
        if self._phase == "paused":
            self.resume_download()
            return
        if self._phase != "idle":
            return
        rows = self.selected_rows()
        if _retry:
            for r in rows:
                if r in self._failed_rows:
                    self._failed_rows.remove(r)
        else:
            self._failed_rows = []
        if not rows:
            QMessageBox.information(self, "提示", "请先勾选要下载的视频")
            return
        save_dir = self.editDir.text().strip()
        if not save_dir:
            QMessageBox.information(self, "提示", "请选择保存目录")
            return
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法创建保存目录：{e}")
            return

        free = free_bytes(save_dir)
        if 0 <= free < 500 * 1024 * 1024:
            r = QMessageBox.warning(
                self, "磁盘空间不足",
                f"保存目录所在磁盘仅剩 {fmt_size(free)}。\n\n"
                "继续下载很可能写出无法播放的损坏文件。\n"
                "建议先清理磁盘，或点「浏览…」把保存目录换到其它分区"
                "（如 D:\\ 或 E:\\）。\n\n是否仍要继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return

        self.settings.setValue("save_dir", save_dir)
        self.settings.setValue("quality", self.comboQ.currentIndex())
        self.settings.setValue("name_with_id",
                               "1" if self.chkIdName.isChecked() else "0")

        # 全新一轮：清掉上一轮的文件名缓存（标题/画质可能已变）
        for r in rows:
            self.items[r].pop("fname", None)
        self._payloads.clear()
        self.done_count = self.fail_count = self.skip_count = 0
        self._total = len(rows)
        self._auto_retried = False

        # 先按「自然文件名」判重跳过，再给真正要下的行排唯一名字
        todo = list(rows)
        if self.chkSkip.isChecked():
            keep = []
            for r in todo:
                it = self.items[r]
                nm = self.build_filename(it.get("title"), it["id"], it)
                if os.path.exists(os.path.join(save_dir, nm)):
                    self._set(r, COL_STATUS, STATUS_SKIP)
                    self._set(r, COL_SIZE, "已存在")
                    self.skip_count += 1
                else:
                    keep.append(r)
            todo = keep
            if not todo:
                self.lblStat.setText("所选视频都已存在，无需下载")
                self._update_bar()
                return

        self._plan_names(todo, save_dir, reuse=False)
        self._begin(todo, save_dir)

    def _begin(self, rows, save_dir):
        """提交一批行：已有解析结果的直接下，其余的交给解析器。"""
        self._save_dir = save_dir
        self._phase = "running"
        self.pending = set(rows)
        self._task_refs.clear()
        self.dm.set_max_workers(
            self._int_setting("concurrency", DEFAULT_CONCURRENCY))
        self.resolver.set_concurrency(
            self._int_setting("resolve_concurrency", DEFAULT_CONCURRENCY))
        self.dm.reset_control()
        self._update_buttons()

        queued = []
        for r in sorted(rows):
            pay = self._payloads.get(r)
            if pay:
                self._set(r, COL_STATUS, "准备下载…")
                self._submit_download(r, pay)
            else:
                self._set(r, COL_STATUS, STATUS_WAIT)
                self._set(r, COL_PROG, "")
                queued.append((r, self.items[r]["id"],
                               self.items[r].get("title", ""),
                               self.items[r].get("dur", 0)))
        if queued:
            self.resolver.start(queued, self.comboQ.currentIndex())
            self.lblStat.setText(
                f"开始解析（并发 {self.resolver.concurrency}）…")
        else:
            self.lblStat.setText("继续下载…")
        self.sigStatus.emit(self.lblStat.text())
        self._update_bar()

    def pause_download(self):
        """暂停/继续：暂停保留 .part 文件，继续时用 HTTP Range 断点续传。"""
        if self._phase == "paused":
            self.resume_download()
            return
        if self._phase != "running":
            return
        self._resume_rows = sorted(self.pending)
        self.resolver.pause()
        self.dm.request_pause()
        self._phase = "paused"
        for r in self._resume_rows:
            self._set(r, COL_STATUS, STATUS_PAUSE)
            self._set(r, COL_PROG, "")
        self.lblStat.setText(
            f"已暂停，还有 {len(self._resume_rows)} 个没下完。"
            "点「继续」会从断点接着下。")
        self.sigStatus.emit(self.lblStat.text())
        self._update_buttons()

    def resume_download(self):
        if self._phase != "paused":
            return
        rows = [r for r in self._resume_rows if 0 <= r < len(self.items)
                and r in self.pending]
        if not rows:
            self._phase = "idle"
            self._update_buttons()
            return
        for r in rows:
            self._set(r, COL_STATUS, STATUS_WAIT)
        self.dm.resume()
        # 沿用原文件名，才能命中上次留下的 .part 继续下
        self._plan_names(rows, self._save_dir, reuse=True)
        self._begin(rows, self._save_dir)

    def stop_download(self):
        self.resolver.stop()
        self.dm.request_cancel()
        self.pending.clear()
        self._phase = "idle"
        self._resume_rows = []
        self._payloads.clear()
        self.lblStat.setText("已停止")
        self._update_buttons()

    # ---------------- 回调 ----------------
    def _on_resolve_progress(self, row, msg):
        self._set(row, COL_STATUS, msg)

    def _on_resolve_failed(self, row, msg):
        self._set(row, COL_STATUS, STATUS_FAIL)
        self._set(row, COL_SIZE, msg[:60])
        self.pending.discard(row)
        self._payloads.pop(row, None)
        self.fail_count += 1
        if row not in self._failed_rows:
            self._failed_rows.append(row)
        self._update_bar()
        self._maybe_finish()

    def _on_resolved(self, row, payload):
        self._payloads[row] = payload
        self._set(row, COL_STATUS, "准备下载…")
        self._submit_download(row, payload)

    def _submit_download(self, row, payload):
        name = self._fname(row)
        task = DownloadTask(row, payload, self._save_dir, name,
                            self.dm.cancel, self.dm.pause)
        task.signals.sigProgress.connect(self._on_task_progress)
        task.signals.sigDone.connect(self._on_task_done)
        task.signals.sigError.connect(self._on_task_error)
        task.signals.sigLog.connect(self._on_resolve_progress)
        self._task_refs.append(task)   # 保持引用，避免被回收后信号丢失
        self.dm.submit(task)

    def _on_task_progress(self, row, pct, size):
        self._set(row, COL_PROG, f"{pct}%")
        self._set(row, COL_SIZE, fmt_size(size))

    def _on_task_done(self, row, path, size):
        self._set(row, COL_STATUS, STATUS_DONE)
        self._set(row, COL_SIZE, fmt_size(size))
        self._set(row, COL_PROG, "100%")
        self.pending.discard(row)
        self._payloads.pop(row, None)
        if row in self._failed_rows:
            self._failed_rows.remove(row)
        self.done_count += 1
        self._update_bar()
        self._maybe_finish()

    def _on_stalled(self, n: int):
        """连续多条拿不到视频流 → 判定为系统性问题，停下来给出可操作建议。

        早期版本会让几百条挨个超时失败，用户只看到一屏红字，却不知道该
        重新登录还是等一会。这里直接中止排队，并把「最可能的原因 + 怎么做」
        摆出来；已排进去的那几条不打断，让它们自然收尾。
        """
        self.resolver.stop()
        self.lblStat.setText(f"已中止：连续 {n} 条解析失败")
        self._phase = "idle"
        self._update_buttons()
        QMessageBox.warning(
            self, "解析连续失败，已中止",
            f"已经连续 {n} 条视频拿不到播放地址，很可能不是单个视频的问题。\n\n"
            "常见原因与处理：\n"
            "· 登录态失效 —— 去【浏览器】页看右上角是否显示「已登录」，\n"
            "   若不是请重新扫码登录；\n"
            "· 触发了抖音的人机验证 —— 去【浏览器】页打开任意一个视频，\n"
            "   手动完成一次滑动验证，再回来重试；\n"
            "· 短时间内请求太密集被限流 —— 把【设置】里的并发数保持 1~2，\n"
            "   过几分钟再试。\n\n"
            "已经失败的那几条可以点「重试失败的项」单独补跑。\n"
            "详细原因已写入运行日志（设置页可打开数据目录下的 logs 文件夹）。")

    def _on_captcha(self):
        """检测到人机验证：立即暂停并把用户引去完成验证。

        不再让队列在验证墙后面一条条白等超时——那正是「开头几条/一大批
        失败」却看不出原因的场景。暂停（而不是停止），完成验证回来点
        「继续」就能接着跑，已解析好的直链也还在。
        """
        runlog.log("captcha", "解析过程检测到人机验证，已自动暂停")
        if self._phase == "running":
            self.pause_download()
        self.lblStat.setText("检测到人机验证，已暂停")
        # 找一条还没解析成功的视频，让浏览器页直接打开它——验证码就在
        # 那个页面上，用户滑动一次即可，不用自己再去输入地址。
        vid = ""
        for r in sorted(self.pending):
            if 0 <= r < len(self.items):
                vid = self.items[r]["id"]
                break
        btn = QMessageBox(QMessageBox.Warning, "需要人工验证",
                          "抖音要求完成一次人机验证（拖动滑块），"
                          "下载已自动暂停。\n\n"
                          "点「立即去完成验证」会自动打开验证页面，"
                          "拖动滑块完成后回到本页点「继续」，"
                          "会从断点接着下载。")
        bGo = btn.addButton("立即去完成验证", QMessageBox.AcceptRole)
        btn.addButton("知道了", QMessageBox.RejectRole)
        btn.exec_()
        if btn.clickedButton() is bGo:
            self.sigSolveCaptcha.emit(
                f"https://www.douyin.com/video/{vid}" if vid
                else "https://www.douyin.com/")

    def _on_task_error(self, row, msg):
        self._set(row, COL_STATUS, STATUS_FAIL)
        self._set(row, COL_SIZE, msg[:60])
        self.pending.discard(row)
        self.fail_count += 1
        if row not in self._failed_rows:
            self._failed_rows.append(row)
        # 直链带时效，过期后同一个 URL 重试多少次都没用——丢掉缓存，
        # 这样「重试失败的项」会重新解析而不是拿旧地址撞墙。
        low = msg or ""
        if any(k in low for k in ("403", "404", "过期", "不存在", "未获取")):
            self._payloads.pop(row, None)
        self._update_bar()
        self._maybe_finish()

    def retry_failed(self):
        """只重新下载失败的项"""
        if self._phase != "idle":
            QMessageBox.information(self, "提示", "任务进行中，请先停止")
            return
        rows = [r for r in self._failed_rows if 0 <= r < len(self.items)]
        if not rows:
            QMessageBox.information(self, "提示", "当前没有失败的视频")
            return
        self._select_only(rows)
        self.start_download(True)

    def _select_only(self, rows):
        keep = set(rows)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it:
                it.setCheckState(Qt.Checked if r in keep else Qt.Unchecked)

    def _maybe_finish(self):
        if self._phase != "running":
            return
        if self.resolver.running or self.pending:
            return
        if not (self.done_count or self.fail_count or self.skip_count):
            return
        # 解析失败几乎都是「同一时间请求太密被平台限流」，隔几秒再来一次
        # 基本都能过。所以这里自动补一轮，让用户一次点「开始下载」就跑完，
        # 而不是自己去发现哪些失败、再手动点重试。
        if self._failed_rows and not self._auto_retried:
            self._auto_retried = True
            rows = [r for r in self._failed_rows if 0 <= r < len(self.items)]
            self._failed_rows = []
            self.fail_count = max(0, self.fail_count - len(rows))
            for r in rows:
                self._payloads.pop(r, None)
                self._set(r, COL_STATUS, "稍后自动重试…")
                self._set(r, COL_SIZE, "")
            if rows:
                self._phase = "waiting"
                self.lblStat.setText(
                    f"有 {len(rows)} 个没成功，3 秒后自动重试一轮…")
                self.sigStatus.emit(self.lblStat.text())
                self._update_buttons()
                QTimer.singleShot(3000, lambda: self._auto_retry(rows))
                return
        self._phase = "idle"
        self._payloads.clear()
        self._resume_rows = []
        self.lblStat.setText(
            f"完成：成功 {self.done_count}　失败 {self.fail_count}　"
            f"跳过 {self.skip_count}")
        self.sigStatus.emit(self.lblStat.text())
        self._update_buttons()
        tip = ("\n\n失败项已保留勾选，可点「重试失败的项」再试一次。"
               if self._failed_rows else "")
        QMessageBox.information(
            self, "下载结束",
            f"成功 {self.done_count} 个\n失败 {self.fail_count} 个\n"
            f"跳过 {self.skip_count} 个{tip}")

    def _auto_retry(self, rows):
        """自动补一轮：只重跑失败的那些，其余结果保持不变。"""
        if self._phase != "waiting":
            return
        rows = [r for r in rows if 0 <= r < len(self.items)]
        if not rows:
            self._phase = "running"
            self._maybe_finish()
            return
        self._auto_retried = True
        self._plan_names(rows, self._save_dir, reuse=True)
        self._begin(rows, self._save_dir)


    def _update_bar(self):
        if self._total <= 0:
            self.bar.setValue(0)
            return
        done = self._total - len(self.pending)
        self.bar.setValue(int(max(0, min(100, done * 100.0 / self._total))))

