# -*- coding: utf-8 -*-
"""用真实 ProfileManager + 应用钩子抓取，然后 dump 原始 aweme 对象。

目标：为 desc 为空的条目找出可替代的标题字段。
"""
import json
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer                            # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.scraper import SCROLL_JS                            # noqa: E402
from app.webengine import make_view                          # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

DUMP = r"""
(function(){
  var out = [];
  var ord = window.__dyOrder || [];
  for (var i = 0; i < ord.length; i++){
    var a = window.__dyPosts[ord[i]];
    if (!a) continue;
    var v = a.video || {};
    var te = [];
    var tx = a.text_extra || [];
    for (var j = 0; j < tx.length; j++) te.push(tx[j].hashtag_name || tx[j].text || '');
    out.push({
      i: i, id: String(a.aweme_id || ''),
      desc: (a.desc === undefined) ? null : a.desc,
      item_title: (a.item_title === undefined) ? null : a.item_title,
      preview_title: (a.preview_title === undefined) ? null : a.preview_title,
      caption: (a.caption === undefined) ? null : a.caption,
      seo_title: a.seo_info ? a.seo_info.title : null,
      te: te,
      is_top: a.is_top || 0,
      aweme_type: a.aweme_type,
      imgs: (a.images || []).length,
      ct: a.create_time || 0,
      dur: v.duration || 0,
      keys: Object.keys(a)
    });
  }
  return JSON.stringify({n: out.length, meta: window.__dyMeta || {}, items: out});
})()
"""


def main():
    app = QApplication(sys.argv)
    host = QWidget()
    host.resize(1280, 900)
    host.show()

    view = make_view(host)
    view.resize(1280, 900)
    view.show()

    st = {"steps": 0, "last": -1, "no_new": 0, "calls": -1}

    def dump():
        def on_dump(raw):
            try:
                d = json.loads(raw)
            except Exception as e:
                print("parse err", e, repr(raw)[:200]); app.quit(); return
            items = d.get("items") or []
            print("\n==== 原始条目 n = %d ====" % len(items), flush=True)
            empty = [it for it in items if not (it.get("desc") or "").strip()]
            print("desc 为空: %d" % len(empty), flush=True)
            for it in empty:
                print("  id=%s ct=%s dur=%s top=%s type=%s imgs=%s"
                      % (it["id"], it["ct"], it["dur"], it["is_top"],
                         it["aweme_type"], it["imgs"]), flush=True)
                print("     desc=%r" % (it["desc"],), flush=True)
                print("     item_title=%r preview=%r caption=%r"
                      % (it["item_title"], it["preview_title"], it["caption"]), flush=True)
                print("     seo=%r te=%s" % (it["seo_title"], it["te"]), flush=True)
                print("     keys=%s" % (it["keys"],), flush=True)
            keys = set()
            for it in items:
                keys.update(it.get("keys") or [])
            print("\n全部字段(%d): %s" % (len(keys), sorted(keys)), flush=True)
            with open(os.path.join(ROOT, "tools", "raw_items.json"), "w",
                      encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            print("已写入 tools/raw_items.json", flush=True)
            app.quit()

        view.page().runJavaScript(DUMP, 0, on_dump)

    def step():
        st["steps"] += 1

        def on_scrolled(raw):
            try:
                s = json.loads(raw)
            except Exception:
                s = {}
            total = int(s.get("total", -1))
            calls = int(s.get("calls", 0))
            more = int(s.get("has_more", -1))
            print("step %d captured=%d calls=%d has_more=%d" %
                  (st["steps"], total, calls, more), flush=True)
            grew = total > st["last"] or calls != st["calls"]
            st["no_new"] = 0 if grew else st["no_new"] + 1
            st["last"], st["calls"] = total, calls
            done = (more == 0) or st["steps"] >= 120 or st["no_new"] >= 12
            if done:
                print("滚动结束，导出原始数据…", flush=True)
                QTimer.singleShot(2500, dump)
            else:
                QTimer.singleShot(900, step)

        view.page().runJavaScript(SCROLL_JS, 0, on_scrolled)

    def on_load(ok):
        print("loadFinished =", ok, flush=True)
        QTimer.singleShot(4000, step)

    view.loadFinished.connect(on_load)
    view.load(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl(URL))
    QTimer.singleShot(600000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
