# -*- coding: utf-8 -*-
"""全局配置与路径工具"""
import os
import re
import sys
import time

# APP_NAME 同时是「数据目录名」与注册表键名，改名会让用户已保存的登录态
# 和设置全部丢失，所以它保持稳定；界面/标题/EXE 用 APP_TITLE。
APP_NAME = "DouyinDownloader"
APP_TITLE = "抖音批量下载器"
APP_VERSION = "1.3.2"

# 默认并发。实测并发越高越容易触发抖音风控（验证码中间页），一旦触发
# 整批解析全部失败，速度反而归零，所以默认取最稳妥的 1。
DEFAULT_CONCURRENCY = 1

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 真正的登录态 Cookie。只有这几个是「登录后才会有」的。
# 千万不要把 passport_csrf_token / uid_tt / odin_tt / login_status 也算进来：
# 未登录的游客同样会拿到它们，会导致界面误报「已登录」。
SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt")

# 兼容旧引用
LOGIN_COOKIES = set(SESSION_COOKIES) | {"sid_guard"}


def app_data_dir() -> str:
    """应用数据目录（保存 Cookie / 配置）"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = os.path.join(base, APP_NAME)
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        p = os.path.join(os.path.expanduser("~"), APP_NAME)
        os.makedirs(p, exist_ok=True)
    return p


def profile_dir() -> str:
    d = os.path.join(app_data_dir(), "WebProfile")
    os.makedirs(d, exist_ok=True)
    return d


def _desktop_dir() -> str:
    """取「用户真正看到的桌面」。

    不能直接用 ~/Desktop：桌面被 OneDrive 重定向时，真正的桌面在
    OneDrive 目录下，下载到 ~/Desktop 用户根本找不到文件。
    顺序：SHGetFolderPath（系统认可、自动处理重定向）→ 注册表
    User Shell Folders → ~/Desktop 兜底。
    """
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x10
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
            d = buf.value
            if d and os.path.isdir(d):
                return d
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion"
                r"\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Desktop")
            d = os.path.expandvars(v)
            if d and os.path.isdir(d):
                return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def default_save_dir() -> str:
    d = os.path.join(_desktop_dir(), "抖音视频")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return _desktop_dir()
    return d


def ffmpeg_path() -> str:
    """ffmpeg 可执行文件路径（支持 PyInstaller 打包）"""
    if getattr(sys, "frozen", False):
        cand = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.exists(cand):
            return cand
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "bin", "ffmpeg.exe"),
              os.path.join(here, "ffmpeg.exe")):
        if os.path.exists(c):
            return c
    return "ffmpeg"


ILLEGAL_CHARS = r'[\\/:*?"<>|\r\n\t]'


def safe_filename(name: str, maxlen: int = 90, keep_dot: bool = True) -> str:
    """清理成合法 Windows 文件名"""
    name = re.sub(ILLEGAL_CHARS, " ", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ") if keep_dot else name
    if len(name) > maxlen:
        name = name[:maxlen].rstrip()
    return name or "未命名视频"


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def fmt_dur(sec: float) -> str:
    sec = int(sec or 0)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def fmt_date(ts) -> str:
    """时间戳 → YYYY-MM-DD，非法值返回空串"""
    try:
        ts = float(ts or 0)
    except Exception:
        return ""
    if ts <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except Exception:
        return ""


def fmt_dur_cn(dur) -> str:
    """秒 → 「4分02秒」/「57秒」"""
    try:
        sec = int(float(dur or 0))
    except Exception:
        sec = 0
    if sec <= 0:
        return ""
    m, s = divmod(sec, 60)
    return f"{m}分{s:02d}秒" if m else f"{s}秒"


def fallback_title(ct=0, dur=0, mix: str = "", ep: int = 0) -> str:
    """给「没有文案」的作品生成一个有意义的名字。

    抖音上确实存在作者没写文案的作品：实测某主播 626 条里有 32 条，
    desc / item_title / preview_title / caption / seo / text_extra
    全为空（详情页也确认为空），此时干巴巴地显示「视频 + 数字ID」毫无信息量。
    这里改用真实元数据兜底：
      1. 属于某个合集/短剧 → 「合集名 第N集」（N 由同合集内按发布时间排序得出）
      2. 否则 → 「2024-04-20 6分43秒」
    两者都拿不到才返回空串，由调用方退回「抖音视频_<id>」。
    """
    mix = (mix or "").strip()
    if mix and ep:
        return f"{mix} 第{ep}集"
    parts = []
    d = fmt_date(ct)
    if d:
        parts.append(d)
    dc = fmt_dur_cn(dur)
    if dc:
        parts.append(dc)
    return " ".join(parts)
