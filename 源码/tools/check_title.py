# -*- coding: utf-8 -*-
"""读取真实窗口标题（Windows API），确认程序名显示为「抖音视频下载器 v1.2.0」。

Qt 的 windowTitle() 只反映我们设置的值，不等于用户看到的标题栏，
所以这里直接从操作系统读。
"""
import ctypes
import os
import sys
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer                                   # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from app.config import APP_TITLE, APP_VERSION                       # noqa: E402

user32 = ctypes.windll.user32

CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def all_titles():
    out = []

    def _cb(hwnd, _lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.strip():
                out.append(buf.value)
        return True

    user32.EnumWindows(CB(_cb), 0)
    return out


def main():
    app = QApplication(sys.argv[:1])
    from app.main_window import MainWindow
    w = MainWindow()
    w.show()

    def check():
        titles = all_titles()
        hits = [t for t in titles if "抖音" in t]
        print("窗口标题(windowTitle()):", repr(w.windowTitle()), flush=True)
        print("操作系统实际标题栏:", flush=True)
        for t in hits:
            print("   ", repr(t), flush=True)
        expect = f"{APP_TITLE}  v{APP_VERSION}"
        if any(t.strip() == expect.strip() for t in hits):
            print("结论：标题正确 ✅", flush=True)
        else:
            print("结论：标题与预期不一致，预期 %r" % expect, flush=True)
        app.quit()

    QTimer.singleShot(2500, check)
    app.exec()


if __name__ == "__main__":
    main()
