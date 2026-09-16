# -*- coding: utf-8 -*-
"""截取「批量下载」页（含时长列、暂停/继续按钮）与设置页，输出到 tools/shots/。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer, Qt                        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from app.config import APP_TITLE, APP_VERSION                # noqa: E402
from app.main_window import MainWindow                       # noqa: E402
from app.ui_download import (STATUS_DONE, STATUS_FAIL, STATUS_PAUSE,  # noqa: E402
                            STATUS_SKIP, STATUS_DOWNLOAD, COL_STATUS,
                            COL_SIZE, COL_PROG)

OUT = os.path.join(ROOT, "tools", "shots")
os.makedirs(OUT, exist_ok=True)


def main():
    app = QApplication(sys.argv[:1])
    w = MainWindow()
    w.resize(1180, 780)
    w.show()

    page = w.pageDownload
    try:
        with open(os.path.join(ROOT, "tools", "scrape_items.json"),
                  encoding="utf-8") as f:
            data = json.load(f)[:14]
    except Exception:
        data = []
    if data:
        page.add_items(data)

    # 摆几种状态，方便一眼看到效果
    demo = [
        (0, STATUS_DONE, "122.4 MB", "100%"),
        (1, STATUS_DONE, "51.7 MB", "100%"),
        (2, STATUS_DOWNLOAD, "18.3 MB", "37%"),
        (3, STATUS_DONE, "118.7 MB", "100%"),
        (4, STATUS_PAUSE, "9.4 MB", "12%"),
        (5, STATUS_FAIL, "未能获取视频地址（可能已删除、私密…）", ""),
        (6, STATUS_SKIP, "已存在", ""),
    ]
    for r, st, sz, pg in demo:
        if r < page.table.rowCount():
            page._set(r, COL_STATUS, st)
            page._set(r, COL_SIZE, sz)
            page._set(r, COL_PROG, pg)
    page.pending = set(range(7, 14))
    page._total = 14
    page._phase = "paused"
    page.btnPause.setText("继续")
    page.btnPause.setEnabled(True)
    page.btnStop.setEnabled(True)
    page.btnStart.setEnabled(False)
    page.lblStat.setText("已暂停，还有 7 个没下完。点「继续」会从断点接着下。")
    page._failed_rows = [5]
    page._update_buttons()
    page._update_bar()

    def shot_download():
        w.nav.setCurrentRow(0)
        print("时长列示例:", [page.table.item(r, 3).text() for r in range(4)])
        print("表头:", [page.table.horizontalHeaderItem(c).text()
                       for c in range(page.table.columnCount())])
        print("按钮:", page.btnStart.text(), "/", page.btnPause.text(), "/",
              page.btnStop.text(), "/", page.btnRetry.text())
        p = os.path.join(OUT, "download_page.png")
        w.grab().save(p)
        print("已保存", p)

    def to_settings():
        w.nav.setCurrentRow(2)

    def shot_settings():
        p = os.path.join(OUT, "settings_page.png")
        w.grab().save(p)
        print("已保存", p)
        print("页脚:", f"{APP_TITLE} v{APP_VERSION}")
        print("窗口标题:", w.windowTitle())

    QTimer.singleShot(9000, shot_download)
    QTimer.singleShot(11000, to_settings)
    QTimer.singleShot(13000, shot_settings)
    QTimer.singleShot(14500, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
