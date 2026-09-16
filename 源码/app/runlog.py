# -*- coding: utf-8 -*-
"""运行日志：写到 <数据目录>/logs/run-YYYY-MM-DD.log

为什么要有：批量下载一旦出问题（解析连续失败、下载校验不过），只看界面上的
一句话很难定位。把「哪一条、什么原因、页面当时长什么样」记下来，事后才有据可查。
放在数据目录里，设置页的「打开数据目录」就能直接找到。
"""
import os
import threading
import time

from .config import app_data_dir

_lock = threading.Lock()
_MAX_BYTES = 4 * 1024 * 1024      # 单日文件超过 4MB 就重开一份


def log_dir() -> str:
    d = os.path.join(app_data_dir(), "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return app_data_dir()
    return d


def log_path() -> str:
    return os.path.join(log_dir(), "run-%s.log" % time.strftime("%Y-%m-%d"))


def log(tag: str, msg: str):
    """追加一行日志。任何异常都吞掉——日志绝不能反过来搞崩主流程。"""
    try:
        line = "[%s] [%s] %s\n" % (time.strftime("%H:%M:%S"), tag, msg)
    except Exception:
        return
    try:
        with _lock:
            p = log_path()
            if os.path.isfile(p) and os.path.getsize(p) > _MAX_BYTES:
                try:
                    os.remove(p)
                except Exception:
                    pass
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
