# -*- coding: utf-8 -*-
"""验证命名逻辑：读入抓取结果，模拟界面层的分集编号 + 兜底命名。

输出用户最终会在列表/文件名里看到的名字。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.config import fallback_title, safe_filename   # noqa: E402
from app.ui_download import DownloadPage               # noqa: E402

SRC = os.path.join(ROOT, "tools", "scrape_items.json")


def assign_episodes(items):
    """直接调用界面层真实方法：DownloadPage._assign_episodes"""
    holder = type("H", (), {})()
    holder.items = items
    DownloadPage._assign_episodes(holder)


def title_of(it):
    """直接调用界面层真实方法：DownloadPage.title_of"""
    return DownloadPage.title_of(None, it)


class _Chk:
    def __init__(self, v):
        self.v = v

    def isChecked(self):
        return self.v


def build_filename(it, with_id=False):
    """直接调用界面层真实方法：DownloadPage.build_filename"""
    holder = type("H", (), {})()
    holder.chkIdName = _Chk(with_id)
    return DownloadPage.build_filename(holder, it.get("title") or "",
                                       it["id"], it)


def main():
    items = json.load(open(SRC, encoding="utf-8"))
    for it in items:
        it.setdefault("ep", 0)
    assign_episodes(items)

    print("总条目: %d" % len(items))
    empty = [it for it in items if not (it.get("title") or "").strip()]
    print("原始无文案: %d" % len(empty))

    still = []
    print("\n---- 无文案条目的新名字 ----")
    for it in empty:
        name = title_of(it)
        if not name:
            still.append(it)
            name = "<仍为空>"
        print("  %-20s -> %s" % (it["id"], name))

    print("\n仍无法命名的条目: %d" % len(still))
    for it in still:
        print("   ", it["id"])

    # 文件名安全性抽检（走真实 build_filename）
    bad = []
    for it in items:
        fn = build_filename(it)
        if not fn or len(fn) > 100:
            bad.append((it["id"], fn))
    print("\n文件名异常(过长/变空): %d" % len(bad))
    for b in bad[:10]:
        print("   ", b)

    print("\n---- 实际文件名样例（无文案）----")
    for it in empty[:8]:
        print("   ", build_filename(it))
    print("---- 实际文件名样例（附加视频ID）----")
    for it in empty[:3]:
        print("   ", build_filename(it, with_id=True))

    mixt = [it for it in items if it.get("mix")]
    print("\n带合集信息的条目: %d" % len(mixt))
    for it in mixt[:10]:
        print("   %s mix=%r mix_id=%r ep=%s title=%r"
              % (it["id"], it.get("mix"), it.get("mix_id"), it.get("ep"),
                 (it.get("title") or "")[:40]))


if __name__ == "__main__":
    main()
