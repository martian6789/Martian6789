# -*- coding: utf-8 -*-
"""共享的 WebEngine Profile（持久化 Cookie）与请求拦截器

关于登录态持久化，这里做了两层保险：

1. **自建会话文件** ``session.json``
   Chromium 写 Cookie 是「攒批提交」的（默认约 30 秒一次），程序被直接关闭时
   最后一次写入常常丢失——实测用户登录后再次打开软件又变回未登录，就是这个原因。
   所以我们自己在每次 Cookie 变化后立刻落盘一份，启动时再注入回 CookieStore。
2. **QtWebEngine 的明文 Cookie 库**
   Qt 的 Cookie 库是明文 SQLite，可以离线读取，用作启动时的初始种子。
   若上面那份文件里记着「已登出」，则跳过种子，避免旧 Cookie 复活。
"""
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time

from PySide6.QtCore import QObject, Signal, QTimer, QUrl, QByteArray, QDateTime
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import (QWebEngineProfile, QWebEnginePage,
                                     QWebEngineSettings,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .config import (UA, profile_dir, app_data_dir, SESSION_COOKIES)

_HOME = "https://www.douyin.com/"
# 1601-01-01 到 1970-01-01 的秒数（Chromium 的时间戳起点）
_CHROME_EPOCH = 11644473600

# 浏览器内部会用到的协议，不能拦
_ALLOWED_SCHEMES = {"http", "https", "about", "data", "blob", "filesystem",
                    "chrome-error", "view-source", "ws", "wss"}


class SafeWebEnginePage(QWebEnginePage):
    """拦掉自定义协议，避免弹出「获取打开此 xxx 链接的应用」。

    抖音的登录弹窗里带 ``bitbrowser://``（指纹浏览器）这类唤起本机软件的
    链接。QtWebEngine 遇到未知协议会转交给操作系统，Windows 就会弹出
    「你的电脑没有可打开此链接的应用」——非常干扰用户。这里直接拦下。
    """

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        try:
            scheme = (url.scheme() or "").lower()
        except Exception:
            scheme = ""
        if scheme and scheme not in _ALLOWED_SCHEMES:
            if scheme in ("mailto", "tel"):
                try:
                    from PySide6.QtGui import QDesktopServices
                    QDesktopServices.openUrl(url)
                except Exception:
                    pass
            return False
        try:
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        except Exception:
            return False

    def createWindow(self, _wtype):
        # 页面里的 target=_blank 一律原地忽略，不弹新窗口
        return None



def _s(v) -> str:
    """QByteArray / str / None 一律转成 str（不同 PySide6 版本返回值不一致）"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return bytes(v).decode("utf-8", "ignore")
    except Exception:
        return str(v)


def _chrome_ts(v) -> int:
    """Chromium 的微秒时间戳 → Unix 秒（0 表示会话级 Cookie）"""
    try:
        v = int(v or 0)
    except Exception:
        return 0
    if v <= 0:
        return 0
    return int(v / 1000000) - _CHROME_EPOCH


def _cookie_ts(cookie) -> int:
    """QNetworkCookie 的有效期 → Unix 秒（0 表示会话级 Cookie）"""
    try:
        if cookie.isSessionCookie():
            return 0
        return int(cookie.expirationDate().toSecsSinceEpoch())
    except Exception:
        return 0


def _url_for(domain: str) -> QUrl:
    d = (domain or "").lstrip(".") or "www.douyin.com"
    return QUrl("https://%s/" % d)


class StreamInterceptor(QWebEngineUrlRequestInterceptor):
    """捕获所有网络请求 URL，交给当前的 sink 处理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink = None
        self._lock = threading.Lock()

    def set_sink(self, fn):
        with self._lock:
            self._sink = fn

    def clear_sink(self):
        with self._lock:
            self._sink = None

    def interceptRequest(self, info):
        try:
            url = info.requestUrl().toString()
        except Exception:
            return
        with self._lock:
            sink = self._sink
        if sink is None:
            return
        try:
            sink(url)
        except Exception:
            pass


class ProfileManager(QObject):
    """单例：持久化 Cookie 的浏览器 Profile + 全局请求拦截器"""

    _instance = None

    cookiesChanged = Signal()
    loggedOut = Signal()

    @classmethod
    def instance(cls) -> "ProfileManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        if ProfileManager._instance is not None:
            raise RuntimeError("use ProfileManager.instance()")
        ProfileManager._instance = self

        # 内存中的 Cookie 罐：(domain, path, name) -> {value, expires}
        self._jar = {}
        self._jar_lock = threading.Lock()
        self._logged_out = False
        self.cookie_dict = {}
        self._session = {}          # 会话 Cookie 名 -> 过期时间（0=会话级）
        # 本进程内「明确删掉过」的 key：磁盘同步不许把它们复活
        self._forgotten = set()
        self._disk_sig = None       # (mtime, size) 缓存，避免反复读同一个库

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self._save_session)

        self.interceptor = StreamInterceptor(self)
        self.profile = QWebEngineProfile("douyin_profile", QApplication.instance())
        self.profile.setPersistentStoragePath(profile_dir())
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.setHttpUserAgent(UA)
        self.profile.setUrlRequestInterceptor(self.interceptor)

        st = self.profile.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        # 未知协议（bitbrowser:// 等）一律拒绝，不要交给 Windows 处理
        try:
            pol = getattr(QWebEngineSettings.WebAttribute, "UnknownUrlSchemePolicy")
            disallow = getattr(
                QWebEngineSettings, "UnknownUrlSchemePolicy").DisallowUnknownUrlSchemes
            st.setAttribute(pol, disallow)
        except Exception:
            pass

        store = self.profile.cookieStore()
        store.cookieAdded.connect(self._on_cookie)
        try:
            store.cookieRemoved.connect(self._on_cookie_removed)
        except Exception:
            pass

        # 1) 先读自己的会话文件（最关键的一层）
        self._restore_session()
        # 2) 读明文库补全（例如用户没走过我们的保存流程时）
        if not self._logged_out:
            try:
                store.loadAllCookies()
            except Exception:
                pass
            QTimer.singleShot(0, self._load_cookies_from_disk)

        # 3) 运行期持续以明文库为准（登录后几秒内自愈，不依赖 cookieAdded）
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(4000)
        self._sync_timer.timeout.connect(self._periodic_sync)
        self._sync_timer.start()

        # 注入接口捕获钩子（必须在任何页面创建之前）
        try:
            from .scraper import install_hooks
            install_hooks(self.profile)
        except Exception:
            pass

    # ------------------------------------------------------------ 会话文件
    @staticmethod
    def session_path() -> str:
        return os.path.join(app_data_dir(), "session.json")

    def _restore_session(self):
        """启动时把上次保存的 Cookie 注入回 CookieStore"""
        path = self.session_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if data.get("logged_out"):
            # 用户主动登出过：清干净，别让旧 Cookie 复活
            self._logged_out = True
            try:
                self.profile.cookieStore().deleteAllCookies()
            except Exception:
                pass
            return

        items = data.get("cookies") or []
        n = 0
        now = int(time.time())
        for c in items:
            try:
                name = str(c.get("name") or "")
                if not name:
                    continue
                exp = int(c.get("expires") or 0)
                # 已过期的不恢复：注入后会被 Chromium 立刻删掉，白白触发一轮
                # cookieRemoved，还可能把内存罐里的登录态搞乱。
                if exp and exp <= now:
                    continue
                domain = str(c.get("domain") or ".douyin.com")
                path_ = str(c.get("path") or "/")
                self._remember(domain, path_, name, str(c.get("value") or ""), exp)
                n += 1
            except Exception:
                continue
        if n:
            self._inject_jar()
            if self._session:
                self.cookiesChanged.emit()

    def _inject_jar(self):
        """把内存 Cookie 罐写回 Qt 的 CookieStore"""
        store = self.profile.cookieStore()
        with self._jar_lock:
            items = list(self._jar.items())
        for (domain, path_, name), meta in items:
            try:
                ck = QNetworkCookie(QByteArray(name.encode("utf-8")),
                                    QByteArray(str(meta.get("value", "")).encode("utf-8")))
                ck.setDomain(domain)
                ck.setPath(path_)
                ck.setSecure(True)
                exp = int(meta.get("expires") or 0)
                if exp > 0:
                    ck.setExpirationDate(QDateTime.fromSecsSinceEpoch(exp))
                store.setCookie(ck, _url_for(domain))
            except Exception:
                continue

    def _save_session(self):
        """把内存 Cookie 罐立刻落盘（幂等，随时可调用）"""
        path = self.session_path()
        try:
            with self._jar_lock:
                items = [{"name": k[2], "value": v.get("value", ""),
                          "domain": k[0], "path": k[1],
                          "expires": int(v.get("expires") or 0)}
                         for k, v in self._jar.items()]
            data = {"version": 1, "saved_at": int(time.time()),
                    "logged_out": bool(self._logged_out), "cookies": items}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass

    # ------------------------------------------------------------ 内存罐
    def _remember(self, domain, path_, name, value, expires):
        key = (domain or "", path_ or "/", name)
        with self._jar_lock:
            self._jar[key] = {"value": value, "expires": int(expires or 0)}
            self._forgotten.discard(key)
        if name:
            self.cookie_dict[name] = value
            if name in SESSION_COOKIES:
                self._session[name] = int(expires or 0)
                self._logged_out = False

    def _forget(self, domain, path_, name, tombstone: bool = False):
        """从内存罐移除一条 Cookie。

        ``tombstone=True`` 才会写进 ``_forgotten``（永久不再从磁盘恢复）。
        **只有主动登出才该用 True**——早期版本让 ``cookieRemoved`` 也写墓碑，
        结果：会话文件里若残留一个已过期的 sessionid，Qt 注入后立刻被
        Chromium 删掉 → 触发 ``cookieRemoved`` → 记下墓碑 → 明文库里
        **有效**的 sessionid 从此再也同步不进内存罐，界面永远「未登录」。
        明文库才是权威，普通的删除信号不该留下永久墓碑。
        """
        key = (domain or "", path_ or "/", name)
        with self._jar_lock:
            self._jar.pop(key, None)
            if tombstone:
                self._forgotten.add(key)
        self.cookie_dict.pop(name, None)
        if name in SESSION_COOKIES:
            self._session.pop(name, None)

    def _schedule_save(self):
        if not self._save_timer.isActive():
            self._save_timer.start()

    # ------------------------------------------------------------ 信号
    def _on_cookie(self, cookie):
        try:
            name = _s(cookie.name())
            value = _s(cookie.value())
            domain = _s(cookie.domain())
            path_ = _s(cookie.path()) or "/"
        except Exception:
            return
        if not name:
            return
        had = name in self._session
        self._remember(domain, path_, name, value, _cookie_ts(cookie))
        self._schedule_save()
        if name in SESSION_COOKIES and not had:
            self.cookiesChanged.emit()

    def _on_cookie_removed(self, cookie):
        try:
            self._forget(_s(cookie.domain()), _s(cookie.path()), _s(cookie.name()))
        except Exception:
            return
        self._schedule_save()
        self.cookiesChanged.emit()

    def _load_cookies_from_disk(self) -> int:
        """从 QtWebEngine 的明文 Cookies 库补全 Cookie 罐，返回新增条数

        注意几个坑：
        * 该库常被 Chromium 独占，直接复制可能报 WinError 32 → 先复制，
          失败则改用 ``immutable=1`` 只读打开原库；
        * ``setCookie`` 这类编程式写入**不会**触发 ``cookieAdded``，
          所以这里读到的必须合并进内存罐，不能只依赖信号；
        * 这个方法会被**反复调用**（启动时 + 定时轮询），因为本环境下
          ``cookieAdded`` 并不可靠——实测页面已经登录（明文库里躺着
          sessionid）、信号却一次都没发出，于是内存罐里没有 sessionid，
          界面就一直显示「未登录」。既然明文库读得到，就以它为准。
        """
        if self._logged_out:
            return 0
        path = os.path.join(profile_dir(), "Cookies")
        if not os.path.isfile(path):
            return 0
        try:
            st = os.stat(path)
            sig = (int(st.st_mtime), int(st.st_size))
        except Exception:
            sig = None
        if sig is not None and sig == self._disk_sig:
            return 0                      # 库没变过，不用重复读
        self._disk_sig = sig

        rows = None
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            shutil.copy2(path, tmp)
            con = sqlite3.connect("file:%s?mode=ro" % tmp.replace("\\", "/"),
                                  uri=True)
            rows = con.execute(
                "SELECT host_key, name, value, path, expires_utc, has_expires "
                "FROM cookies").fetchall()
            con.close()
        except Exception:
            rows = None
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        if rows is None:
            try:
                uri = "file:%s?mode=ro&immutable=1" % path.replace("\\", "/")
                con = sqlite3.connect(uri, uri=True)
                rows = con.execute(
                    "SELECT host_key, name, value, path, expires_utc, has_expires "
                    "FROM cookies").fetchall()
                con.close()
            except Exception:
                return 0

        added = 0
        for host, name, value, cpath, exp, has_exp in rows or []:
            name, value = str(name or ""), str(value or "")
            if not name or not value:
                continue
            ts = _chrome_ts(exp) if has_exp else 0
            with self._jar_lock:
                key = (str(host or ""), str(cpath or "/"), name)
                if key in self._jar or key in self._forgotten:
                    continue            # 会话文件更新 / 本次已明确删掉，不覆盖
            self._remember(host, cpath, name, value, ts)
            added += 1
        if added:
            self._schedule_save()
            if self._session:
                self.cookiesChanged.emit()
        return added

    def _periodic_sync(self):
        """定时把明文库里的新 Cookie 并进内存罐

        为什么需要：登录是**在没有页面跳转**的弹窗里完成的，而本环境下
        ``cookieAdded`` 未必会发出来，于是「已经登录了，界面还显示未登录」。
        轮询明文库（库变了才读，开销极小）能保证登录后几秒内自愈。
        """
        if self._logged_out:
            return
        try:
            self._load_cookies_from_disk()
        except Exception:
            pass

    def import_cookies(self, items, default_ttl: int = 180 * 24 * 3600) -> int:
        """导入外部 Cookie（浏览器导入 / 手动粘贴）。

        必须同时写进 CookieStore 和内存罐：``setCookie`` 不会发
        ``cookieAdded``，只写 CookieStore 的话内存罐永远不知道登录过了，
        下次启动也存不进会话文件——这正是「每次打开都要重新登录」的成因之一。
        """
        from .config import SESSION_COOKIES as _NAMES
        store = self.profile.cookieStore()
        now = int(time.time())
        n = 0
        got_session = False
        for c in items or []:
            try:
                name = str(c.get("name") or "")
                value = str(c.get("value") or "")
                if not name:
                    continue
                domain = str(c.get("domain") or ".douyin.com")
                path_ = str(c.get("path") or "/")
                exp = int(c.get("expires") or 0) or (now + default_ttl)
                ck = QNetworkCookie(QByteArray(name.encode("utf-8")),
                                    QByteArray(value.encode("utf-8")))
                ck.setDomain(domain)
                ck.setPath(path_)
                ck.setSecure(True)
                ck.setExpirationDate(QDateTime.fromSecsSinceEpoch(exp))
                store.setCookie(ck, _url_for(domain))
                self._remember(domain, path_, name, value, exp)
                if name in _NAMES:
                    got_session = True
                n += 1
            except Exception:
                continue
        if got_session:
            self._logged_out = False
        self._save_session()
        self.cookiesChanged.emit()
        return n

    # ------------------------------------------------------------ 对外接口
    @property
    def logged_in(self) -> bool:
        """严格判定：必须有真正的会话 Cookie 且未过期。

        注意 ``passport_csrf_token`` / ``uid_tt`` 这类 Cookie 未登录的游客也会
        有，早期版本把它们当登录标志，导致「没登录却显示已登录」。
        """
        now = time.time()
        for name, exp in list(self._session.items()):
            if exp and exp <= now:
                continue
            if self.cookie_dict.get(name):
                return True
        return False

    def cookie_header(self) -> str:
        """拼成 ``a=1; b=2`` 形式，便于 requests 复用登录态"""
        return "; ".join("%s=%s" % (k, v) for k, v in self.cookie_dict.items())

    def clear_cookies(self):
        """清除登录信息（内存 + CookieStore + 会话文件）"""
        self._logged_out = True
        self._session.clear()
        self.cookie_dict.clear()
        with self._jar_lock:
            self._jar.clear()
            self._forgotten.clear()
        self._disk_sig = None
        try:
            self.profile.cookieStore().deleteAllCookies()
        except Exception:
            pass
        self._save_session()          # 立刻写盘，记下「已登出」
        self.cookiesChanged.emit()
        self.loggedOut.emit()

    def new_view(self, parent=None) -> QWebEngineView:
        """创建一个使用该 Profile 的浏览器视图（带协议白名单）"""
        view = QWebEngineView(parent)
        view.page()          # 触发一次默认页创建，避免 Qt 内部状态不一致
        p = SafeWebEnginePage(self.profile, view)
        view.setPage(p)
        return view


def make_view(parent=None, offscreen: bool = False) -> QWebEngineView:
    """创建后台解析用的视图。

    offscreen=True 时用 ``WA_DontShowOnScreen`` + ``show()`` 把视图标记成
    「对 Qt 可见、但不在屏幕上开窗口」。这一步很关键：Chromium 对不可见的
    页面会节流 requestAnimationFrame 与渲染，抖音的播放器因此要 14 秒以上
    才真正开始拉流；标记为可见后通常 2~4 秒就能拿到直链。
    """
    view = ProfileManager.instance().new_view(parent)
    if offscreen:
        try:
            from PySide6.QtCore import Qt as _Qt
            view.setAttribute(_Qt.WA_DontShowOnScreen, True)
            view.show()
        except Exception:
            pass
    return view

