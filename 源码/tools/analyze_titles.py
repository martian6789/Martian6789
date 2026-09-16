# -*- coding: utf-8 -*-
"""离线分析 tools/union_dump.json：统计 32 条无文案作品的可用文本字段。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "union_dump.json")


def txt(v):
    if isinstance(v, str):
        return v.strip()
    return ""


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    api = d.get("api") or []
    empty = [it for it in api if not (it.get("desc") or "").strip()]
    print("总条目 %d，其中 desc 为空 %d" % (len(api), len(empty)))

    fields = ["item_title", "preview_title", "caption", "seo_title", "video_text",
              "chapter_abstract", "share_title", "share_desc", "music_title"]
    print("\n各字段在「空 desc」集合中的非空数量：")
    for f in fields:
        n = sum(1 for it in empty if txt(it.get(f)))
        print("   %-18s %d / %d" % (f, n, len(empty)))

    n_ch = sum(1 for it in empty if it.get("chapter_list"))
    print("\nchapter_list 非空: %d / %d" % (n_ch, len(empty)))
    n_mix = sum(1 for it in empty if it.get("mix_info"))
    print("mix_info 非空: %d / %d" % (n_mix, len(empty)))
    n_ser = sum(1 for it in empty
                if it.get("series_basic_info") and isinstance(it["series_basic_info"], dict)
                and it["series_basic_info"])
    print("series_basic_info 非空: %d / %d" % (n_ser, len(empty)))

    print("\n---- 32 条逐条明细 ----")
    for it in empty:
        ch = it.get("chapter_list") or []
        chdesc = ""
        if ch and isinstance(ch, list) and isinstance(ch[0], dict):
            chdesc = txt(ch[0].get("desc")) or txt(ch[0].get("desc_for_search"))
        import time as _t
        try:
            dt = _t.strftime("%Y-%m-%d", _t.localtime(it.get("ct") or 0))
        except Exception:
            dt = "?"
        print("  %s  时长%-7.1fs  %s  chapter=%r  mix=%s"
              % (it["id"], (it.get("dur") or 0) / 1000.0, dt,
                 chdesc[:40], bool(it.get("mix_info"))))

    # 章节文本分布：有多少条能拿到章节标题
    got = 0
    for it in empty:
        ch = it.get("chapter_list") or []
        if ch and isinstance(ch, list) and isinstance(ch[0], dict) and (
                txt(ch[0].get("desc")) or txt(ch[0].get("desc_for_search"))):
            got += 1
    print("\n可用章节标题的条目: %d / %d" % (got, len(empty)))


if __name__ == "__main__":
    main()
