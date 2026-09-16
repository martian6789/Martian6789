# -*- coding: utf-8 -*-
"""生成「源码交接包」

把可继续开发的干净源码 + 变更日志 + 参考文档整理成一个 zip，
方便交给别的 AI 工具或在另一个 WorkBuddy 账号下继续维护。
排除内容：__pycache__、build/、dist/、调试日志 txt、抓取数据 json、截图等。
"""
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import _desktop_dir, APP_TITLE, APP_VERSION

EXCLUDE_DIRS = {"__pycache__", "build", "dist", "output", "shots",
                "NVIDIA Corporation", ".workbuddy"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".json", ".spec", ".log"}
# 这些是调试期产生的日志/输出，不属于源码
EXCLUDE_NAMES = {
    "all_log.txt", "api_urls_log.txt", "build_log.txt", "detail_log.txt",
    "exe_exit.txt", "exe_run.txt", "f_hidden.txt", "f_shown.txt",
    "fast_hidden.txt", "fast_shown.txt", "flow_log.txt", "frames_log.txt",
    "hook_log.txt", "inject_log.txt", "login_log.txt", "login2_log.txt",
    "post_log.txt", "probe_log.txt", "raw_log.txt", "resolve_log.txt",
    "resolve_log2.txt", "resume_log.txt", "resume_log2.txt", "sc_log.txt",
    "sc_log2.txt", "scrape_log.txt", "scrape_log2.txt", "scrape_log3.txt",
    "scrape_log4.txt", "union_log.txt", "union_log2.txt", "union_log3.txt",
    "urls_log.txt",
}


def _ignore(_dir, names):
    out = []
    for n in names:
        p = os.path.join(_dir, n)
        if os.path.isdir(p) and n in EXCLUDE_DIRS:
            out.append(n)
        elif os.path.isfile(p):
            if n in EXCLUDE_NAMES or os.path.splitext(n)[1] in EXCLUDE_SUFFIX:
                if not (n.endswith(".spec") or n.endswith(".json")):
                    out.append(n)
    return out


def build_package(root: str, memory_dir: str, skill_md: str = "") -> str:
    """返回生成的 zip 路径"""
    base = os.path.join(_desktop_dir(), f"{APP_TITLE}-源码交接包")
    # 只重建三个内容子目录，保留用户可能已放在包里的说明文档
    for sub in ("源码", "变更日志", "参考文档"):
        d = os.path.join(base, sub)
        if os.path.isdir(d):
            shutil.rmtree(d)
    src = os.path.join(base, "源码")
    os.makedirs(src, exist_ok=True)

    # ---- 源码：只留 app/、main.py、app.ico、tools 下的 .py ----
    shutil.copytree(os.path.join(root, "app"),
                    os.path.join(src, "app"), ignore=_ignore)
    for f in ("main.py", "app.ico"):
        p = os.path.join(root, f)
        if os.path.exists(p):
            shutil.copy2(p, src)
    tsrc = os.path.join(root, "tools")
    tdst = os.path.join(src, "tools")
    os.makedirs(tdst, exist_ok=True)
    for n in sorted(os.listdir(tsrc)):
        if n.endswith(".py"):
            shutil.copy2(os.path.join(tsrc, n), os.path.join(tdst, n))

    # ---- 变更日志（每版改动原因都记在这里）----
    logs = os.path.join(base, "变更日志")
    os.makedirs(logs, exist_ok=True)
    if os.path.isdir(memory_dir):
        for n in sorted(os.listdir(memory_dir)):
            if n.endswith(".md"):
                shutil.copy2(os.path.join(memory_dir, n), os.path.join(logs, n))

    # ---- 参考：采集/下载的工作流经验 ----
    if skill_md and os.path.exists(skill_md):
        ref = os.path.join(base, "参考文档")
        os.makedirs(ref, exist_ok=True)
        shutil.copy2(skill_md, os.path.join(ref, "抖音下载技能文档.md"))

    zip_path = base + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for d, _, fs in os.walk(base):
            for f in fs:
                p = os.path.join(d, f)
                z.write(p, os.path.relpath(p, os.path.dirname(base)))
    return zip_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mem = os.path.join(os.path.dirname(here), ".workbuddy", "memory")
    skill = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                         "douyin-video-download", "SKILL.md")
    print("PKG:", build_package(here, mem, skill))
    print("VERSION:", APP_TITLE, APP_VERSION)
