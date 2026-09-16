# -*- coding: utf-8 -*-
"""从抖音主页 / 任意页面抓取视频列表。

核心思路：抖音主页的作品列表是「虚拟列表」，DOM 里始终只保留约 20 个节点，
边滚边清，所以纯 DOM 抓取永远只能拿到 20 多个。
本模块在页面脚本执行前注入 XHR / fetch 钩子，直接捕获 aweme/post 接口的
JSON 响应并累积，可完整拿到全部作品；DOM 提取仅作为兜底。
"""
import json
import os
from typing import List, Dict

from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEngineScript

from .webengine import make_view

# ---------------------------------------------------------------- 注入钩子
# 在 DocumentCreation 阶段执行（早于页面自身脚本），patched XHR / fetch 后
# 所有接口响应都会先经过 handle() 抽取 aweme_list。
HOOK_JS = r"""
(function(){
  if (window.__dyHooked) return;
  window.__dyHooked = 1;
  window.__dyPosts = {};
  window.__dyOrder = [];
  window.__dyMeta = {has_more: 1, cursor: 0, calls: 0, last: 0, total: 0,
                     err: 0, end_votes: 0};

  function authorKey(a){
    var au = a.author || (a.aweme_info && a.aweme_info.author) || {};
    return String(au.sec_uid || au.uid || '');
  }

  // 只收「目标主播」的作品：一旦从主页作品接口确定了作者，
  // 其它作者一律丢弃。抖音视频页会顺带加载推荐位（related/recommend/feed），
  // 不过滤的话列表里就会混进别的主播的视频。
  // 目标主播：优先从当前 URL 的 /user/<sec_uid> 直接确定。
  // 这比「等第一个接口响应再锁作者」可靠得多——一旦页面先加载了别人的内容
  // （推荐位 / 预取 / 相邻推荐），作者就会被锁错，本主播的作品会被大面积丢弃，
  // 表现就是「630 个只采到一两百个」。
  window.__dyTarget = '';
  function targetAuthor(){
    if (window.__dyTarget) return window.__dyTarget;
    try {
      var um = String(location.href || '').match(/\/user\/([A-Za-z0-9_\-]{20,})/);
      if (um) window.__dyTarget = um[1];
    } catch(e){}
    return window.__dyTarget || '';
  }

  function addList(list, lock){
    if (!list || !list.length) return 0;
    var n = 0;
    for (var i = 0; i < list.length; i++){
      var a = list[i];
      if (!a) continue;
      var id = a.aweme_id || (a.aweme_info && a.aweme_info.aweme_id)
               || (a.common && a.common.aweme_id);
      if (!id) continue;
      var ak = authorKey(a);
      var want = targetAuthor() || window.__dyAuthor;
      if (lock && !want && ak) window.__dyAuthor = ak;
      if (want && ak && ak !== want) continue;
      if (!window.__dyPosts[id]){
        window.__dyPosts[id] = a;
        window.__dyOrder.push(id);
        n++;
      }
    }
    return n;
  }

  var BLOCK_API = /related|recommend|\/feed|search|suggest|hot\/|comment\/list|user\/profile|mix\/list|collection/i;

  function handle(url, txt){
    if (!txt || typeof txt !== 'string') return 0;
    if (txt.length < 20 || txt.length > 8000000) return 0;
    if (txt.charAt(0) !== '{') return 0;
    var u = String(url || '');
    if (BLOCK_API.test(u)) return 0;
    var o = null;
    try { o = JSON.parse(txt); } catch(e){ return 0; }
    if (!o || typeof o !== 'object') return 0;

    var isPostApi = /aweme\/post/i.test(u);
    var n = 0;
    if (o.aweme_list) n += addList(o.aweme_list, isPostApi);
    if (o.data && o.data.aweme_list) n += addList(o.data.aweme_list, isPostApi);
    if (o.awemeList) n += addList(o.awemeList, isPostApi);
    if (o.data && o.data.awemeList) n += addList(o.data.awemeList, isPostApi);

    if (n > 0 || isPostApi){
      var m = window.__dyMeta;
      var hm = (typeof o.has_more !== 'undefined') ? o.has_more
             : (o.data && typeof o.data.has_more !== 'undefined') ? o.data.has_more : null;
      var mc = (typeof o.max_cursor !== 'undefined') ? o.max_cursor
             : (o.data && typeof o.data.max_cursor !== 'undefined') ? o.data.max_cursor : null;
      // ⚠️ 抖音在「被限流 / 出小错」时同样会回一个 JSON：status_code != 0、
      // 没有 aweme_list，而且 has_more 也常常是 0。老代码无条件采信 has_more，
      // 于是采集会在半途「被骗停」——这正是「主页显示 630 个作品、只采到
      // 165 个」的元凶。现在只有「真的返回了作品且 status_code 正常」的响应
      // 才有资格改写 has_more / cursor。
      var sc = (typeof o.status_code !== 'undefined') ? o.status_code
             : (o.data && typeof o.data.status_code !== 'undefined')
               ? o.data.status_code : 0;
      var bad = (sc !== 0);
      if (n > 0){
        m.calls += 1;
        m.last = n;
        m.total = window.__dyOrder.length;
        if (!bad && hm !== null && typeof hm !== 'undefined') m.has_more = hm ? 1 : 0;
        if (mc !== null && typeof mc !== 'undefined') m.cursor = mc;
      }
      if (bad) m.err = (m.err || 0) + 1;
      // 「空页 + has_more=0」才算真正的结尾，且要连续确认，避免一次偶然的
      // 空响应就把整轮采集截断。
      if (isPostApi && !bad && n === 0 && hm === 0){
        m.end_votes = (m.end_votes || 0) + 1;
      } else if (n > 0){
        m.end_votes = 0;
      }
    }
    return n;
  }

  function readResp(x){
    try {
      if (x.responseType && x.responseType !== '' && x.responseType !== 'text'){
        try { return JSON.stringify(x.response); } catch(e){ return ''; }
      }
      return x.responseText;
    } catch(e){ return ''; }
  }

  // ---- XMLHttpRequest ----
  try {
    var XO = window.XMLHttpRequest;
    if (XO && XO.prototype && !XO.prototype.__dyPatched){
      XO.prototype.__dyPatched = 1;
      var P = XO.prototype;
      var origOpen = P.open;
      P.open = function(){
        try { this.__dyUrl = String(arguments[1] || ''); } catch(e){}
        try {
          var self = this;
          if (!self.__dyBound){
            self.__dyBound = 1;
            self.addEventListener('load', function(){
              try { handle(self.__dyUrl, readResp(self)); } catch(e){}
            });
          }
        } catch(e){}
        return origOpen.apply(this, arguments);
      };
    }
  } catch(e){}

  // ---- fetch ----
  try {
    if (window.fetch && !window.fetch.__dyPatched){
      var of = window.fetch;
      var nf = function(){
        var u = '';
        try {
          var a0 = arguments[0];
          u = (a0 && typeof a0 === 'object' && a0.url) ? String(a0.url) : String(a0 || '');
        } catch(e){}
        var p;
        try { p = of.apply(window, arguments); }
        catch(e){ return of.apply(window, arguments); }
        try {
          p.then(function(r){
            try { r.clone().text().then(function(t){ handle(u, t); }); } catch(e){}
            return r;
          });
        } catch(e){}
        return p;
      };
      nf.__dyPatched = 1;
      window.fetch = nf;
    }
  } catch(e){}
})()
"""


def install_hooks(profile):
    """把钩子脚本装进 Profile，所有页面自动生效"""
    try:
        scripts = profile.scripts()
        for s in scripts.toList():
            if s.name() == "dy_hook":
                return
    except Exception:
        return
    sc = QWebEngineScript()
    sc.setName("dy_hook")
    sc.setSourceCode(HOOK_JS)
    sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    sc.setRunsOnSubFrames(True)
    sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    profile.scripts().insert(sc)


# ---------------------------------------------------------------- 滚动
SCROLL_JS = r"""
(function(){
  var ih = window.innerHeight || 800;
  // 快速路径：从作品列表容器向上找真正的滚动祖先，
  // 免去遍历全页几千个元素的开销。
  var el = null;
  try {
    var seed = document.querySelector('ul[data-e2e="scroll-list"]')
            || document.querySelector('[data-e2e="user-post-list"]')
            || document.querySelector('#slidelist');
    var p = seed;
    while (p && p !== document.body && p !== document.documentElement){
      if (p.scrollHeight > p.clientHeight + 80){ el = p; break; }
      p = p.parentElement;
    }
  } catch(e){}

  if (el){
    var before = el.scrollTop;
    el.scrollTop = Math.min(el.scrollHeight,
                           el.scrollTop + Math.floor(el.clientHeight * 0.9));
    // 已经到底（滚不动了）时向上回弹一点再到底，用来「顶」出懒加载；
    // 有些虚拟列表的 IntersectionObserver 需要一次真实位移才会继续取数。
    if (el.scrollTop === before && el.scrollHeight > el.clientHeight + 80){
      el.scrollTop = Math.max(0, before - 160);
    }
    try { el.dispatchEvent(new Event('scroll', {bubbles: true})); } catch(e){}
  } else {
    window.scrollBy(0, Math.max(600, Math.floor(ih * 1.2)));
    var els = document.querySelectorAll('div,ul,section');
    var best = null, bestDelta = 0;
    for (var i = 0; i < els.length; i++){
      var e = els[i];
      if (e.scrollHeight > e.clientHeight + 150){
        var d = e.scrollHeight - e.clientHeight - e.scrollTop;
        if (d > bestDelta){ best = e; bestDelta = d; }
      }
    }
    if (best) best.scrollTop = Math.min(best.scrollHeight,
                                        best.scrollTop + best.clientHeight);
  }

  var m = (window.__dyMeta || {});

  // ---- 读取网页上显示的「作品 N」总数，用于校准采集是否完整 ----
  function parseCnt(s){
    s = String(s || '').replace(/[,\s]/g, '');
    var mm = s.match(/(\d+(?:\.\d+)?)(万|亿)?/);
    if (!mm) return 0;
    var v = parseFloat(mm[1]);
    if (mm[2] === '万') v *= 10000;
    else if (mm[2] === '亿') v *= 100000000;
    v = Math.round(v);
    return (v > 0 && v < 20000000) ? v : 0;
  }
  function readExpected(){
    // a) 最可靠：抖音自带的 data-e2e 标记
    try {
      var e = document.querySelector('[data-e2e="user-post-count"]');
      if (e){ var v0 = parseCnt(e.textContent); if (v0) return v0; }
    } catch(err){}
    // b) 退一步：按文档顺序找第一个「作品 + 数字」的小元素
    //    （主播自己的 tab 在最上面，先命中即对；不取最大值，
    //     以免误收推荐卡片里的其它数字）
    try {
      var all = document.querySelectorAll('div,span,p,a,li,em,i,dt,dd');
      for (var i = 0; i < all.length; i++){
        var el = all[i];
        if (el.children && el.children.length > 3) continue;
        var t = (el.textContent || '').trim();
        if (!t || t.length > 18) continue;
        if (t.indexOf('作品') !== 0) continue;
        var v = parseCnt(t.replace(/作品/g, ''));
        if (v) return v;
      }
    } catch(err){}
    return 0;
  }
  if (!window.__dyExpected){ window.__dyExpected = readExpected(); }

  return JSON.stringify({
    h: document.body ? document.body.scrollHeight : 0,
    y: Math.round((el ? el.scrollTop : 0) || window.scrollY || 0),
    ih: ih,
    n: document.querySelectorAll('a[href*="/video/"]').length,
    total: (window.__dyOrder ? window.__dyOrder.length : -1),
    calls: m.calls || 0,
    has_more: (typeof m.has_more === 'undefined') ? -1 : m.has_more,
    cursor: m.cursor || 0,
    exp: window.__dyExpected || 0,
    err: m.err || 0,
    end_votes: m.end_votes || 0
  });
})()
"""

# ---------------------------------------------------------------- 提取
EXTRACT_JS = r"""
(function(){
  function pick(a){
    var v = a.video || {};
    var pa = v.play_addr || {};
    var da = v.download_addr || {};
    var brs = v.bit_rate || [];
    var bit = [];
    for (var i = 0; i < brs.length; i++){
      var b = brs[i] || {};
      var bpa = b.play_addr || {};
      bit.push({q: b.quality_type || b.gear_name || 0,
                br: b.bitrate || 0,
                urls: (bpa.url_list || []).slice(0, 3)});
    }
    // 标题优先级：desc 往往是最完整的文案；但部分作品 desc 为空、
    // 文案却躺在别的字段里（预览标题 / 画面文字 / SEO 标题 / 话题标签），
    // 所以逐级回退，尽量避免出现「无标题」。
    var title = a.desc || a.item_title || a.preview_title || a.caption || '';
    if (!title && a.seo_info && a.seo_info.title) title = a.seo_info.title;
    if (!title){
      var tx = a.text_extra || [];
      var tags = [];
      for (var t = 0; t < tx.length && tags.length < 6; t++){
        var tg = tx[t] || {};
        var nm = tg.hashtag_name || tg.text || '';
        if (nm) tags.push(String(nm).charAt(0) === '#' ? nm : ('#' + nm));
      }
      if (tags.length) title = tags.join(' ');
    }
    if (!title && a.chapter_abstract) title = a.chapter_abstract;
    // 长视频的章节标题也是真实文案（如「文明社会与非文明社会的区」）
    if (!title && a.chapter_list && a.chapter_list.length){
      var c0 = a.chapter_list[0] || {};
      title = c0.desc || c0.desc_for_search || '';
    }
    var au = a.author || {};
    return {
      id: String(a.aweme_id || ''),
      title: String(title || '').slice(0, 300),
      // 分集作品（合集/短剧）的辅助信息，供无文案时命名使用
      mix: (a.mix_info && a.mix_info.mix_name) ? String(a.mix_info.mix_name) : '',
      mix_id: (a.mix_info && a.mix_info.mix_id) ? String(a.mix_info.mix_id) : '',
      dur: v.duration ? Math.round(v.duration) / 1000 : 0,
      ct: a.create_time || 0,
      au: String(au.sec_uid || au.uid || ''),
      nick: String(au.nickname || ''),
      urls: (pa.url_list || []).slice(0, 4),
      dl: (da.url_list || []).slice(0, 4),
      bit: bit,
      w: v.width || 0, h: v.height || 0
    };
  }

  var api = [];
  try {
    var ord = window.__dyOrder || [];
    for (var i = 0; i < ord.length; i++){
      var a = window.__dyPosts[ord[i]];
      if (!a) continue;
      var o = pick(a);
      if (o.id) api.push(o);
    }
  } catch(e){}

  // DOM 兜底
  function collect(root){
    var out = [], seen = {};
    if (!root) return out;
    var nodes = root.querySelectorAll('a[href]');
    for (var i = 0; i < nodes.length; i++){
      var a = nodes[i];
      var h = a.getAttribute('href') || '';
      var m = h.match(/\/video\/(\d{14,25})/);
      if (!m) continue;
      var id = m[1];
      if (seen[id]) continue;
      var t = '';
      var img = a.querySelector('img');
      if (img) t = img.getAttribute('alt') || '';
      if (!t) t = a.getAttribute('title') || '';
      if (!t) t = (a.textContent || '').trim();
      seen[id] = 1;
      out.push({id: id, title: (t || '').slice(0, 300), dur: 0, ct: 0,
                urls: [], dl: [], bit: [], w: 0, h: 0});
    }
    return out;
  }

  // DOM 兜底：只认主页专属容器，避免把侧栏/推荐位一并收进来
  var doms = [];
  function add(name, root){ if (root){ var it = collect(root); if (it.length) doms.push({name: name, items: it}); } }
  add('scroll-list', document.querySelector('ul[data-e2e="scroll-list"]'));
  add('user-post-list', document.querySelector('[data-e2e="user-post-list"]'));
  add('slidelist', document.querySelector('#slidelist'));
  add('post-container', document.querySelector('[data-e2e="user-post-item-list"]'));

  return JSON.stringify({
    api: api,
    doms: doms,
    author: window.__dyTarget || window.__dyAuthor || '',
    meta: window.__dyMeta || {},
    expected: window.__dyExpected || 0,
    count: document.querySelectorAll('a[href*="/video/"]').length,
    height: document.body ? document.body.scrollHeight : 0
  });
})()
"""


class ScrapeController(QObject):
    """驱动可见浏览器滚动抓取（隐藏页面不会触发懒加载）"""

    sigProgress = Signal(str)
    sigFinished = Signal(object)   # list[dict]
    sigError = Signal(str)

    MAX_SCROLL = 500          # 最多滚动次数（每次约 1 屏）
    NO_NEW_LIMIT = 30         # 连续多少次没新增才放弃（约 30 秒）
    END_CONFIRM = 2           # 「空页 + has_more=0」需连续确认几次才算结束

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.host = None
        self._steps = 0
        self._last_total = -1
        self._last_cursor = -1
        self._no_new = 0
        self._busy = False
        self._expected = 0        # 网页上显示的作品总数（校准用）
        self._reloaded = False    # 钩子没命中时是否重载过（只试一次）

    @property
    def busy(self):
        return self._busy

    def start(self, url: str, host=None):
        if self._busy:
            return
        self._busy = True
        self._steps = 0
        self._last_total = -1
        self._last_cursor = -1
        self._no_new = 0
        self._expected = 0
        self._reloaded = False
        self.url = url
        self.host = host

        self.view = make_view(host)
        if host is not None:
            try:
                from PySide6.QtWidgets import QVBoxLayout
                lay = host.layout()
                if lay is None:
                    lay = QVBoxLayout(host)
                    lay.setContentsMargins(0, 0, 0, 0)
                    host.setLayout(lay)
                lay.addWidget(self.view)
                self.view.show()
            except Exception:
                pass
        else:
            self.view.resize(1280, 900)
        self.view.loadFinished.connect(self._on_loaded)
        self.sigProgress.emit("正在打开页面…")
        self.view.load(QUrl(url))

    # ------------------------------------------------------------ 流程
    def _on_loaded(self, ok):
        if not ok:
            self._fail("页面加载失败，请检查网络或链接是否正确")
            return
        self.sigProgress.emit("页面已加载，开始滚动采集…")
        QTimer.singleShot(3000, self._scroll_step)

    def _scroll_step(self):
        if not self.view:
            return
        self._steps += 1
        try:
            self.view.page().runJavaScript(SCROLL_JS, 0, self._on_scrolled)
        except Exception as e:
            self._fail(f"页面通信失败：{e}")

    def _on_scrolled(self, raw):
        try:
            d = json.loads(raw)
        except Exception:
            d = {}
        n = int(d.get("n", -1))
        total = int(d.get("total", -1))
        calls = int(d.get("calls", 0))
        has_more = int(d.get("has_more", -1))
        cursor = int(d.get("cursor", 0))
        exp = int(d.get("exp", 0) or 0)
        err = int(d.get("err", 0) or 0)
        ends = int(d.get("end_votes", 0) or 0)
        if exp > 0:
            self._expected = exp

        # 以「接口累计条数」为准；接口不可用时回落到 DOM 节点数
        metric = total if total >= 0 else n

        if self._expected > 0:
            msg = (f"滚动采集第 {self._steps} 次，已采集 "
                   f"{metric} / 共 {self._expected} 个…")
        else:
            msg = f"滚动采集第 {self._steps} 次，已发现 {max(total, n)} 个视频…"
        if os.environ.get("DY_DEBUG"):
            msg += (f" [dom={n} api={total} calls={calls} more={has_more} "
                    f"cur={cursor} exp={exp} err={err} end={ends} "
                    f"h={d.get('h')} y={d.get('y')}]")
        self.sigProgress.emit(msg)

        grew = metric > self._last_total or cursor != self._last_cursor
        if grew:
            self._no_new = 0
        else:
            self._no_new += 1
        self._last_total = metric
        self._last_cursor = cursor

        # 到齐了（或差 3% 以内且确实不再增长）就收工
        reached = False
        if self._expected > 0:
            if metric >= self._expected:
                reached = True
            elif metric >= self._expected * 0.97 and self._no_new >= 3:
                reached = True

        # 收工判定。关键点：**已知网页总数且还差得多时，绝不相信
        # 「has_more=0」**——被限流时接口正是这么回的，顺着它停就又是一次
        # 钩子没生效时的自救：接口一次都没抓到、网页又明确显示了作品总数，
        # 说明这次页面加载有问题（钩子没挂上 / 走了异常渲染路径）。
        # 此时硬滚下去只能靠 DOM 兜底，630 个作品最多只能拿到 400 多个。
        # 重新加载一次页面往往就好了——但只重试一次，避免卡在死循环里。
        if (self._expected > 0 and calls == 0 and self._steps >= 12
                and not self._reloaded):
            self._reloaded = True
            self.sigProgress.emit("接口未响应，正在重新加载页面重试…")
            self._steps = 0
            self._no_new = 0
            self._last_total = -1
            self._last_cursor = -1
            try:
                self.view.load(QUrl(self.url))
            except Exception:
                pass
            return

        # 「630 只采到 165」。这种情况只在「长时间确实没有新增」时才放弃。
        done = False
        if reached:
            done = True
        elif self._steps >= self.MAX_SCROLL:
            done = True
        elif self._no_new >= self.NO_NEW_LIMIT:
            done = True
        elif self._expected <= 0 or metric >= self._expected * 0.97:
            # 总数未知、或已接近目标：可以采信接口的「没有更多了」
            if ends >= self.END_CONFIRM or (has_more == 0 and self._no_new >= 2):
                done = True

        if done:
            QTimer.singleShot(1200, self._extract)
        else:
            QTimer.singleShot(900, self._scroll_step)

    def _extract(self):
        if not self.view:
            return
        self.sigProgress.emit("正在整理视频清单…")
        self.view.page().runJavaScript(EXTRACT_JS, 0, self._on_extracted)

    def _on_extracted(self, raw):
        try:
            data = json.loads(raw)
        except Exception as e:
            self._fail(f"解析页面失败：{e}")
            return

        items: List[Dict] = data.get("api") or []
        source = "接口捕获"
        if len(items) < 5:
            for s in data.get("doms", []):
                if s.get("items"):
                    items = s["items"]
                    source = "页面解析"
                    break

        if not items:
            self._fail("未在页面中发现视频。请确认已登录并停留在主播主页。")
            return

        # 二次过滤：只保留目标主播的作品，剔除推荐位混入的其它主播
        base = str(data.get("author") or "")
        if not base:
            from collections import Counter
            ks = [str(it.get("au") or "") for it in items]
            ks = [k for k in ks if k]
            if ks:
                base = Counter(ks).most_common(1)[0][0]
        if base:
            before = len(items)
            items = [it for it in items
                     if not it.get("au") or str(it.get("au")) == base]
            dropped = before - len(items)
            if dropped > 0:
                self.sigProgress.emit(f"已剔除 {dropped} 条非本主播的视频")

        # 登录墙识别：未登录时抖音只返回一屏推荐位，页面高度很小
        height = int(data.get("height", 0) or 0)
        if len(items) < 20 and height < 1600:
            self._fail(
                f"只发现 {len(items)} 个视频，页面看起来处于「未登录」状态。\n"
                "请先在「账号登录」页扫码登录抖音，再回来开始采集。")
            return

        # 去重保序
        seen, uniq = set(), []
        for it in items:
            vid = str(it.get("id", ""))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            uniq.append(it)

        exp = self._expected or int(data.get("expected", 0) or 0)
        if exp > 0:
            self.sigProgress.emit(
                f"采集完成：{len(uniq)} 个视频（网页显示共 {exp} 个）")
        else:
            self.sigProgress.emit(f"采集完成：{len(uniq)} 个视频（{source}）")
        self._cleanup()
        self._busy = False
        # 把「网页显示的作品总数」一并带回，让界面能校准 / 提示不完整
        self.sigFinished.emit({"items": uniq, "expected": exp,
                               "url": getattr(self, "url", "")})

    # ------------------------------------------------------------ 收尾
    def _fail(self, msg):
        self._cleanup()
        self._busy = False
        self.sigError.emit(msg)

    def _cleanup(self):
        try:
            if self.view:
                try:
                    self.view.loadFinished.disconnect()
                except Exception:
                    pass
                self.view.stop()
                self.view.setParent(None)
                self.view.deleteLater()
        except Exception:
            pass
        self.view = None
        try:
            if self.host is not None:
                self.host.hide()
                self.host.deleteLater()
        except Exception:
            pass
        self.host = None

    def cancel(self):
        self._busy = False
        self._cleanup()
        self.sigError.emit("已取消采集")
