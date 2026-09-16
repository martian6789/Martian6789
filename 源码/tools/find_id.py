# -*- coding: utf-8 -*-
"""在 QtWebEngine 配置目录里搜索主播 sec_user_id 与昵称，用于定位用户实际抓取的账号。"""
import collections
import os
import re

PROFILE = r"C:\Users\Administrator\AppData\Local\DouyinDownloader\WebProfile"

pat_id = re.compile(rb"MS4wLjABAAAA[A-Za-z0-9_\-]{20,60}")
pat_nick = re.compile("南山空同".encode("utf-8"))


def main():
    found = collections.Counter()
    for root, dirs, files in os.walk(PROFILE):
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) > 40 * 1024 * 1024:
                    continue
                data = open(p, "rb").read()
            except Exception:
                continue
            for m in pat_id.findall(data):
                found[("id", m.decode("ascii", "ignore"))] += 1
            if pat_nick.search(data):
                found[("nick", os.path.relpath(p, PROFILE))] += 1
    if not found:
        print("未找到任何 sec_user_id / 昵称")
    for (kind, val), n in found.most_common(30):
        print(f"{n:6d}  {kind}  {val}")


if __name__ == "__main__":
    main()
