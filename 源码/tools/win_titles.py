# -*- coding: utf-8 -*-
"""列出当前所有可见窗口标题中带「抖音」的（用于验证打包后 EXE 的真实标题栏）。

不依赖 Qt，只调 Win32 API，所以可以对着已经跑起来的 EXE 直接查。
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def titles():
    out = []

    def _cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value.strip()
            if t and "抖音" in t:
                out.append(t)
        return True

    user32.EnumWindows(CB(_cb), 0)
    return out


if __name__ == "__main__":
    hits = titles()
    if not hits:
        print("（没找到带「抖音」的可见窗口）")
    for t in hits:
        print(repr(t))
