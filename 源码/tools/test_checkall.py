# -*- coding: utf-8 -*-
"""离屏验证：表头「全选」勾选框的定位与联动"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.ui_download import DownloadPage, COL_CHECK

app = QApplication(sys.argv)
p = DownloadPage()
p.items = [{"id": "1", "title": "a", "dur": 10, "ct": 0, "mix": "", "mix_id": "", "ep": 0}
           for _ in range(5)]
p._rebuild_table()
p.show()
app.processEvents()

print("CHKALL_GEO:", p.chkAll.geometry().getRect())
print("STATE_AFTER_BUILD:", p.chkAll.checkState(), "expect Checked(2)")
n = sum(1 for r in range(p.table.rowCount())
        if p.table.item(r, COL_CHECK).checkState() == Qt.Checked)
print("ROWS_CHECKED:", n)

p._toggle_row(0)
p._toggle_row(1)
print("STATE_AFTER_TOGGLE_2:", p.chkAll.checkState(), "expect Partially(1)")

p.chkAll.setCheckState(Qt.Checked)   # 手动触发全选
p._on_check_all(True)
n = sum(1 for r in range(p.table.rowCount())
        if p.table.item(r, COL_CHECK).checkState() == Qt.Checked)
print("ROWS_AFTER_CHECKALL:", n)
print("STATE_AFTER_CHECKALL:", p.chkAll.checkState(), "expect Checked(2)")
p.chkAll.setCheckState(Qt.Unchecked)
p._on_check_all(False)
n = sum(1 for r in range(p.table.rowCount())
        if p.table.item(r, COL_CHECK).checkState() == Qt.Checked)
print("ROWS_AFTER_UNCHECK:", n)
print("BTN_VERIFY:", p.btnVerify.text())
