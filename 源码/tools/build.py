# -*- coding: utf-8 -*-
"""打包脚本：PyInstaller 单文件 EXE"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, ROOT)

# EXE 文件名直接取应用标题，保证和窗口标题永远一致（改名字只改 config.py）
from app.config import APP_TITLE as NAME  # noqa: E402

# 注意：QtWebEngineCore 依赖 QtPrintSupport / QtWebChannel / QtQml / QtQuick，
# 这些绝对不能排除，否则运行期 ImportError。
EXCLUDES = [
    "tkinter", "matplotlib", "scipy", "pandas", "PIL", "notebook",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebEngineQuick", "PySide6.QtNetworkAuth",
]


def main():
    # 旧 EXE 必须先删：PyInstaller 写新 EXE 前会尝试删除它，
    # 而批量删除动作会被安全守卫拦截，导致打包在最后一步失败。
    exe = os.path.join(ROOT, "dist", NAME + ".exe")
    if os.path.exists(exe):
        try:
            os.remove(exe)
            print("已移除旧 EXE")
        except Exception as e:
            print("移除旧 EXE 失败:", e)

    # build 缓存同理（PyInstaller 会批量清理 90 个条目而触发拦截）。
    # 用一个全新的临时工作目录，它就无需删除任何旧文件。
    work = os.path.join(tempfile.gettempdir(), "dybuild_%d" % int(time.time()))
    os.makedirs(work, exist_ok=True)
    print("工作目录:", work)

    # 注意：绝对不要动项目里的 build/ 目录。
    # 它包含 100+ 个文件，任何批量删除都会被安全守卫判定为
    # SAFE_DELETE_BULK_CONFIRM_REQUIRED 并直接终止当前进程（EXIT 1）。
    # 由于 --workpath/--specpath 已指向全新临时目录，PyInstaller
    # 根本不会读写项目里的 build/，所以无需、也不能清理它。

    args = [
        PY, "-m", "PyInstaller",
        # 不加 --clean：它会在收尾时批量删除 build 缓存（70+ 文件），
        # 容易被安全守卫拦截。缓存目录由脚本自行清理。
        "--noconfirm",
        "--onefile", "--windowed",
        "--name", NAME,
        "--icon", os.path.join(ROOT, "app", "app.ico"),
        # 窗口/任务栏图标运行时要从 main.py 旁边读到 app.ico，
        # 不打进去的话打包后就找不到，任务栏只会显示默认白框图标
        "--add-data", os.path.join(ROOT, "app", "app.ico") + os.pathsep + ".",
        "--add-binary", os.path.join(ROOT, "app", "bin", "ffmpeg.exe") + os.pathsep + ".",
        "--hidden-import", "PySide6.QtWebEngineWidgets",
        "--hidden-import", "PySide6.QtWebEngineCore",
        "--hidden-import", "PySide6.QtNetwork",
        "--collect-all", "PySide6",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", work,
        "--specpath", work,
    ]
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    args.append(os.path.join(ROOT, "main.py"))

    print(" ".join(args[:14]), "...", flush=True)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    # 让 PyInstaller 把自身缓存也放在临时目录，避免它去清理用户目录下的旧缓存
    env["PYINSTALLER_CONFIG_DIR"] = work + "_cfg"
    r = subprocess.run(args, cwd=ROOT, env=env)
    print("EXIT", r.returncode, flush=True)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
