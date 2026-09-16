# -*- coding: utf-8 -*-
"""生成应用图标（纯标准库，输出 PNG 编码的 ICO）"""
import os
import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def encode_png(w: int, h: int, pixels) -> bytes:
    """pixels: list of rows, each row list of (r,g,b,a)"""
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))
    comp = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", comp) + _chunk(b"IEND", b""))


def lerp(a, b, t):
    return int(round(a + (b - a) * t))


def render(size: int):
    """绘制：圆角渐变方块 + 白色下载箭头"""
    c1 = (255, 92, 122)     # 顶部亮色
    c2 = (254, 44, 85)      # 品牌红
    bg_alpha = 255
    R = size * 0.22         # 圆角半径

    cx = cy = size / 2.0
    # 箭头参数
    stem_w = size * 0.13
    stem_top = size * 0.27
    stem_bottom = size * 0.56
    head_w = size * 0.34
    head_top = size * 0.47
    head_tip = size * 0.74
    tray_t = size * 0.075
    tray_w = size * 0.42
    tray_y = size * 0.805

    rows = []
    for y in range(size):
        row = []
        fy = y + 0.5
        for x in range(size):
            fx = x + 0.5
            # 圆角遮罩
            dx = max(0.0, max(R - fx, fx - (size - R)))
            dy = max(0.0, max(R - fy, fy - (size - R)))
            if dx * dx + dy * dy > R * R:
                row.append((0, 0, 0, 0))
                continue
            t = fy / size
            r, g, b = lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)
            a = bg_alpha

            white = False
            # 竖杆
            if abs(fx - cx) <= stem_w / 2 and stem_top <= fy <= stem_bottom:
                white = True
            # 三角箭头
            if head_top <= fy <= head_tip:
                half = (head_w / 2.0) * (1.0 - (fy - head_top) / (head_tip - head_top))
                if abs(fx - cx) <= half:
                    white = True
            # 托盘
            if tray_y <= fy <= tray_y + tray_t and abs(fx - cx) <= tray_w / 2:
                white = True

            if white:
                r = g = b = 255
            row.append((r, g, b, a))
        rows.append(row)
    return rows


def build_ico(sizes=(16, 32, 48, 64, 128, 256)) -> bytes:
    images = []
    for s in sizes:
        png = encode_png(s, s, render(s))
        images.append((s, png))
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for s, png in images:
        entries += struct.pack("<BBBBHHII",
                               s if s < 256 else 0,
                               s if s < 256 else 0,
                               0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out += entries
    for _, png in images:
        out += png
    return bytes(out)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    os.makedirs(os.path.join(root, "app"), exist_ok=True)
    for target in (os.path.join(root, "app.ico"),
                   os.path.join(root, "app", "app.ico")):
        with open(target, "wb") as f:
            f.write(build_ico())
        print("wrote", target, os.path.getsize(target), "bytes")
