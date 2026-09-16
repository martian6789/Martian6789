# -*- coding: utf-8 -*-
"""端到端流程测试：真实走一遍「开始 → 暂停 → 继续 → 完成」。

覆盖页面层的文件名规划、状态机、断点续传与收尾统计。
用法：test_flow.py [条数]
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QTimer                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox             # noqa: E402

# 把会阻塞的弹窗换成空操作，否则无人点击会卡死
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
SAVE = os.path.join(tempfile.gettempdir(), "dytest_flow")

START = time.time()
STATE = {"paused": False, "parts_at_pause": 0, "resumed": False}


def log(m):
    print("[%6.1fs] %s" % (time.time() - START, m), flush=True)


def parts_in(d):
    try:
        return [f for f in os.listdir(d) if ".part" in f]
    except Exception:
        return []


def main():
    from app.ui_download import DownloadPage, STATUS_DONE, COL_STATUS

    app = QApplication(sys.argv[:1])
    if os.path.isdir(SAVE):
        for f in os.listdir(SAVE):
            try:
                os.remove(os.path.join(SAVE, f))
            except Exception:
                pass
    os.makedirs(SAVE, exist_ok=True)

    # 挑几条短一点的，跑得快
    with open(os.path.join(ROOT, "tools", "scrape_items.json"),
              encoding="utf-8") as f:
        data = json.load(f)
    data = sorted(data, key=lambda x: x.get("dur") or 0)
    items = [it for it in data if (it.get("dur") or 0) > 8][:N]

    page = DownloadPage()
    page.editDir.setText(SAVE)
    page.chkSkip.setChecked(True)
    page.add_items(items)

    checked = len(page.selected_rows())
    log("列表 %d 条，默认勾选 %d 条（应相等）" % (len(page.items), checked))
    assert checked == len(page.items), "默认勾选数量不对"

    # 勾选框行为：点一下应当翻转（注意 Qt.Checked 的枚举值是 2，
    # 这里必须比对 Qt.CheckState 枚举，比 1 会永远不相等）
    from PySide6.QtCore import Qt as _Qt
    before = page.table.item(0, 0).checkState()
    page._on_cell_clicked(0, 0)             # 点第 1 行 → 取消勾选
    mid = page.table.item(0, 0).checkState()
    log("点击第 1 行后翻转 = %s（%s → %s）"
        % (before == _Qt.Checked and mid == _Qt.Unchecked, before, mid))
    page._on_cell_clicked(0, 0)             # 再点一次 → 恢复勾选
    log("再点一次恢复勾选 = %s"
        % (page.table.item(0, 0).checkState() == _Qt.Checked))

    # 时长列有值
    durs = [page.table.item(r, 3).text() for r in range(min(3, len(page.items)))]
    log("时长列前 3 行 = %s" % durs)

    page.select_all()
    page.start_download()
    log("已开始下载，phase=%s，并发=%d/%d"
        % (page._phase, page.dm.max_workers, page.resolver.concurrency))

    def do_pause():
        if page._phase != "running":
            log("此刻不在运行（phase=%s），跳过暂停" % page._phase)
            STATE["paused"] = True
            return
        page.pause_download()
        STATE["paused"] = True
        STATE["parts_at_pause"] = len(parts_in(SAVE))
        log("已暂停 phase=%s，磁盘上的临时文件 %d 个：%s"
            % (page._phase, STATE["parts_at_pause"], parts_in(SAVE)))

    def do_check_pause():
        log("暂停保持中：phase=%s，待完成 %d" % (page._phase, len(page.pending)))
        log("此时未完成的文件数 = %d" % len(parts_in(SAVE)))
        # 最后一条应还是「已暂停」
        st = [page.table.item(r, 4).text() for r in range(len(page.items))]
        log("状态快照 = %s" % st)

    def do_resume():
        page.resume_download()
        STATE["resumed"] = True
        log("已继续，phase=%s" % page._phase)

    def watch():
        if page._phase in ("running", "waiting"):
            return
        if not STATE["resumed"]:
            return
        log("=== 结束 ===")
        log("phase=%s 成功=%d 失败=%d 跳过=%d"
            % (page._phase, page.done_count, page.fail_count, page.skip_count))
        st = [page.table.item(r, 4).text() for r in range(len(page.items))]
        log("最终状态 = %s" % st)
        left = parts_in(SAVE)
        log("残留临时文件 = %s" % left)
        finals = sorted(f for f in os.listdir(SAVE) if f.endswith(".mp4"))
        log("成品文件 %d 个：" % len(finals))
        for f in finals:
            log("    %-40s %10d 字节" % (f[:40], os.path.getsize(os.path.join(SAVE, f))))
        ok = (page.fail_count == 0 and not left
              and len(finals) == len(page.items))
        log("结论：全部完成且无残留临时文件 = %s" % ("是 ✅" if ok else "否 ❌"))
        app.quit()

    QTimer.singleShot(9000, do_pause)
    QTimer.singleShot(12000, do_check_pause)
    QTimer.singleShot(13500, do_resume)
    poll = QTimer()
    poll.timeout.connect(watch)
    poll.start(600)
    QTimer.singleShot(280000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
