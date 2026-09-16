# -*- coding: utf-8 -*-
"""联合诊断：API 条目（含补充字段） + 卡片 DOM 文本 + 数量差集。

用于：
1. 为 desc 为空的条目寻找可替代标题（video_text / 卡片文本 / 章节摘要等）
2. 找出 API 未返回、但页面存在的视频（数量 626 vs 630）
"""
import json
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer, QUrl                      # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.scraper import SCROLL_JS                            # noqa: E402
from app.webengine import make_view                          # noqa: E402

SEC = "MS4wLjABAAAAL94fkQsx9uTmamu_-5NGUQBXJBMcPhTEqwWudXkitv0"
URL = "https://www.douyin.com/user/" + SEC

DUMP = r"""
(function(){
  var api = [];
  var ord = window.__dyOrder || [];
  for (var i = 0; i < ord.length; i++){
    var a = window.__dyPosts[ord[i]];
    if (!a) continue;
    var v = a.video || {};
    var si = a.share_info || {};
    var st = a.status || {};
    var mu = a.music || {};
    var ch = a.chapter_list || a.chapter_data || null;
    var m = {id: String(a.aweme_id || ''),
             desc: (a.desc === undefined) ? null : a.desc,
             item_title: (a.item_title === undefined) ? null : a.item_title,
             preview_title: (a.preview_title === undefined) ? null : a.preview_title,
             caption: (a.caption === undefined) ? null : a.caption,
             seo_title: a.seo_info ? a.seo_info.title : null,
             video_text: a.video_text,
             suggest_words: a.suggest_words,
             chapter_abstract: a.chapter_abstract,
             chapter_data: ch,
             share_title: si.share_title,
             share_desc: si.share_desc,
             music_title: mu.title,
             mix_info: a.mix_info,
             series_basic_info: a.series_basic_info,
             chapter_list: a.chapter_list,
             chapter_data: a.chapter_data,
             anchor_info: a.anchor_info,
             is_multi_content: a.is_multi_content,
             is_25_story: a.is_25_story,
             is_story: a.is_story,
             long_video: a.long_video,
             shoot_way: a.shoot_way,
             media_type: a.media_type,
             aweme_type: a.aweme_type,
             is_top: a.is_top || 0,
             imgs: (a.images || []).length,
             ct: a.create_time || 0,
             dur: v.duration || 0,
             ratio: st.video_status || null,
             keys: Object.keys(a)};
    api.push(m);
  }

  // 卡片 DOM（作品列表容器内的 li）
  function cards(sel){
    var out = [];
    var ns = document.querySelectorAll(sel);
    for (var i = 0; i < ns.length; i++){
      var c = ns[i];
      var a = c.querySelector('a[href*="/video/"]') ||
              (c.tagName === 'A' ? c : null);
      var id = '';
      if (a){
        var m = (a.getAttribute('href') || '').match(/\/video\/(\d{10,25})/);
        if (m) id = m[1];
      }
      var img = c.querySelector('img');
      out.push({id: id,
                alt: img ? (img.getAttribute('alt') || '') : '',
                txt: (c.innerText || '').trim().slice(0, 120)});
    }
    return out;
  }

  var dom = cards('ul[data-e2e="scroll-list"] li');
  var dom2 = cards('[data-e2e="user-post-list"] li');
  var links = [];
  var ls = document.querySelectorAll('a[href*="/video/"]');
  for (var k = 0; k < ls.length; k++){
    var mm = (ls[k].getAttribute('href') || '').match(/\/video\/(\d{10,25})/);
    if (mm) links.push(mm[1]);
  }

  var pageTxt = '';
  try { pageTxt = document.body.innerText.slice(0, 300); } catch(e){}

  return JSON.stringify({
    meta: window.__dyMeta || {},
    api: api, domScroll: dom, domPost: dom2, allLinks: links, pageTxt: pageTxt
  });
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

    def analyse(raw):
        try:
            d = json.loads(raw)
        except Exception as e:
            print("parse err", e, repr(raw)[:200]); app.quit(); return

        with open(os.path.join(ROOT, "tools", "union_dump.json"), "w",
                  encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("\n已写入 tools/union_dump.json", flush=True)

        def cut(v, n=90):
            s = repr(v)
            return s if len(s) <= n else s[:n] + "...(%d)" % len(s)

        api = d.get("api") or []
        print("\n======== 汇总 ========", flush=True)
        print("meta:", json.dumps(d.get("meta"), ensure_ascii=False), flush=True)
        print("API 条目: %d" % len(api), flush=True)
        print("DOM scroll li: %d / post li: %d / 页面 video 链接去重: %d"
              % (len(d.get("domScroll") or []), len(d.get("domPost") or []),
                 len(set(d.get("allLinks") or []))), flush=True)

        empty = [it for it in api if not (it.get("desc") or "").strip()]
        print("\nAPI 中 desc 为空: %d" % len(empty), flush=True)
        for it in empty[:8]:
            print("  id=%s dur=%s ct=%s" % (it["id"], it["dur"], it["ct"]), flush=True)
            print("     video_text=%s" % cut(it.get("video_text")), flush=True)
            print("     chapter_abstract=%s" % cut(it.get("chapter_abstract")), flush=True)
            print("     share_title=%s" % cut(it.get("share_title")), flush=True)
            print("     share_desc=%s" % cut(it.get("share_desc")), flush=True)
            print("     music_title=%s shoot_way=%s media_type=%s"
                  % (cut(it.get("music_title"), 40), cut(it.get("shoot_way"), 20),
                     it.get("media_type")), flush=True)
            print("     mix_info=%s" % cut(it.get("mix_info"), 200), flush=True)
            print("     series_basic_info=%s" % cut(it.get("series_basic_info"), 200), flush=True)
            print("     chapter_list=%s" % cut(it.get("chapter_list"), 150), flush=True)
            print("     chapter_data=%s" % cut(it.get("chapter_data"), 150), flush=True)
            print("     anchor_info=%s is_multi=%s is_story=%s is_25=%s long=%s"
                  % (cut(it.get("anchor_info"), 60), it.get("is_multi_content"),
                     it.get("is_story"), it.get("is_25_story"), cut(it.get("long_video"), 30)),
                  flush=True)
            print("     suggest=%s" % cut(it.get("suggest_words"), 80), flush=True)

        # 字段非空率统计（在空 desc 集合内）
        print("\n---- 空 desc 条目里各候选字段的非空数量 ----", flush=True)
        cands = ["item_title", "preview_title", "caption", "seo_title", "video_text",
                 "chapter_abstract", "share_title", "share_desc", "music_title"]
        for c in cands:
            n = 0
            for it in empty:
                v = it.get(c)
                if isinstance(v, str):
                    if v.strip():
                        n += 1
                elif v:
                    n += 1
            print("   %-18s %d / %d" % (c, n, len(empty)), flush=True)

        domi = {}
        for c in (d.get("domScroll") or []) + (d.get("domPost") or []):
            if c.get("id"):
                domi[c["id"]] = c
        print("\n---- 空标题条目在卡片 DOM 中的文本 ----", flush=True)
        for it in empty[:10]:
            c = domi.get(it["id"])
            print("  %s %s" % (it["id"],
                               ("alt=%s txt=%s" % (cut(c.get("alt"), 50),
                                                   cut(c.get("txt"), 70))
                                if c else "<DOM 中不存在>")), flush=True)

        api_ids = set(it["id"] for it in api)
        link_ids = set(d.get("allLinks") or [])
        missing = sorted(link_ids - api_ids)
        print("\nDOM 有、API 没有的 id: %d" % len(missing), flush=True)
        for mid in missing[:40]:
            c = domi.get(mid) or {}
            print("  %s alt=%s txt=%s" % (mid, cut(c.get("alt"), 40),
                                          cut(c.get("txt"), 60)), flush=True)
        app.quit()

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
                print("滚动结束，导出…", flush=True)
                QTimer.singleShot(3000, lambda: view.page().runJavaScript(DUMP, 0, analyse))
            else:
                QTimer.singleShot(900, step)

        view.page().runJavaScript(SCROLL_JS, 0, on_scrolled)

    def on_load(ok):
        print("loadFinished =", ok, flush=True)
        QTimer.singleShot(4000, step)

    view.loadFinished.connect(on_load)
    view.load(QUrl(URL))
    QTimer.singleShot(600000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
