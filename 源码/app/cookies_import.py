# -*- coding: utf-8 -*-
"""从本机 Chrome / Edge 导入抖音登录 Cookie，以及手动粘贴导入。

两种加密格式：
* ``v10`` / ``v11`` —— 当前用户 DPAPI 加密，可以直接解密；
* ``v20`` —— Chrome / Edge 127+ 的「应用绑定加密」，密钥由系统提权服务
  持有，普通进程无法解密。遇到这种只能改用扫码登录或手动粘贴。

只读浏览器数据库的**临时副本**，绝不修改浏览器自身数据。
"""
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import sqlite3
import tempfile
from typing import List, Dict, Tuple, Optional

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtNetwork import QNetworkCookie


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt = ctypes.windll.crypt32
_crypt.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB), ctypes.POINTER(ctypes.c_wchar_p),
    ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_ulong, ctypes.POINTER(DATA_BLOB)]
_crypt.CryptUnprotectData.restype = ctypes.c_bool
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def dpapi_decrypt(blob: bytes) -> bytes:
    """用当前用户的 DPAPI 主密钥解密。

    注意第三个参数是「可选熵」，必须传 NULL；早期版本误传了输出结构，
    导致解密恒定失败。
    """
    if not blob:
        return b""
    in_buf = ctypes.create_string_buffer(blob, len(blob))
    indata = DATA_BLOB(len(blob), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    outdata = DATA_BLOB()
    ok = _crypt.CryptUnprotectData(
        ctypes.byref(indata), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(outdata))
    if not ok:
        raise OSError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(outdata.pbData, outdata.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outdata.pbData)


def _browser_roots() -> List[Tuple[str, str]]:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    cands = [
        ("Google Chrome", os.path.join(local, "Google", "Chrome", "User Data")),
        ("Microsoft Edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
        ("Chrome (Beta)", os.path.join(local, "Google", "Chrome Beta", "User Data")),
        ("Chromium", os.path.join(local, "Chromium", "User Data")),
    ]
    return [(n, p) for n, p in cands if os.path.isdir(p)]


def _profiles(root: str) -> List[Tuple[str, str]]:
    """列出 (profile 名, Cookies 数据库路径)"""
    out = []
    for s in ["Default"] + [f"Profile {i}" for i in range(1, 8)]:
        for rel in (os.path.join(s, "Network", "Cookies"),
                    os.path.join(s, "Cookies")):
            p = os.path.join(root, rel)
            if os.path.isfile(p):
                out.append((s, p))
                break
    return out


def _abe_key(root: str) -> Optional[bytes]:
    """尝试获取应用绑定密钥（Chrome/Edge 127+）。

    绝大多数情况下系统会拒绝普通进程，返回 None；
    保留此逻辑以便在旧系统上仍有机会解出 v20。
    """
    ls = os.path.join(root, "Local State")
    if not os.path.isfile(ls):
        return None
    try:
        with open(ls, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        enc = (data.get("os_crypt") or {}).get("app_bound_encrypted_key")
        if not enc:
            return None
        raw = base64.b64decode(enc)
        if raw[:4] != b"APPB":
            return None
        return dpapi_decrypt(raw[4:])
    except Exception:
        return None


def scan_browsers() -> List[Dict]:
    """扫描浏览器，统计抖音 Cookie 的可读性（只读副本，不修改原库）"""
    out = []
    for name, root in _browser_roots():
        for prof, db in _profiles(root):
            info = {"browser": name, "profile": prof, "total": 0,
                    "v10": 0, "v20": 0, "plain": 0, "readable": 0}
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                shutil.copy2(db, tmp)
                con = sqlite3.connect("file:%s?mode=ro" % tmp.replace("\\", "/"),
                                      uri=True)
                cur = con.cursor()
                cur.execute(
                    "SELECT host_key, name, value, encrypted_value FROM cookies "
                    "WHERE host_key LIKE '%douyin%'")
                for host, cname, value, enc in cur.fetchall():
                    info["total"] += 1
                    if value:
                        info["plain"] += 1
                        continue
                    pre = bytes(enc)[:3] if enc else b""
                    if pre in (b"v10", b"v11"):
                        info["v10"] += 1
                    elif pre == b"v20":
                        info["v20"] += 1
                con.close()
            except Exception:
                pass
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            out.append(info)
    return out


def read_douyin_cookies() -> List[Dict]:
    """返回可解密的抖音登录 Cookie 列表"""
    out: List[Dict] = []
    seen = set()
    for name, root in _browser_roots():
        for prof, db in _profiles(root):
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                shutil.copy2(db, tmp)
                con = sqlite3.connect("file:%s?mode=ro" % tmp.replace("\\", "/"),
                                      uri=True)
                cur = con.cursor()
                cur.execute(
                    "SELECT name, value, encrypted_value, host_key, path "
                    "FROM cookies WHERE host_key LIKE '%douyin%' "
                    "OR host_key LIKE '%iesdouyin%' OR host_key LIKE '%snssdk%'")
                for cname, value, enc, host, path in cur.fetchall():
                    val = value
                    if not val and enc:
                        raw = bytes(enc)
                        pre = raw[:3]
                        if pre in (b"v10", b"v11"):
                            try:
                                val = dpapi_decrypt(raw[3:]).decode(
                                    "utf-8", "ignore")
                            except Exception:
                                val = ""
                        else:
                            val = ""        # v20 无法离线解密
                    if not val:
                        continue
                    key = (host, path, cname)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"browser": f"{name} / {prof}", "name": cname,
                                "value": val, "domain": host,
                                "path": path or "/"})
                con.close()
            except Exception:
                pass
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
    return out


# ---------------------------------------------------------------- 手动导入
PAIR_RE = re.compile(r"([^=;\s]+)\s*=\s*([^;]*)")


def parse_cookie_string(text: str) -> List[Dict]:
    """解析手动粘贴的 Cookie。

    支持三种写法：
      1) ``name=value; name2=value2``（浏览器 F12 里复制的一整行）
      2) 每行一个 ``name=value``
      3) JSON 数组 ``[{"name":..,"value":..,"domain":..}]``
    未给出域时默认 ``.douyin.com``。
    """
    text = (text or "").strip()
    if not text:
        return []

    items: List[Dict] = []
    # 1) JSON
    if text[0] in "[{":
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            for it in data or []:
                if not isinstance(it, dict):
                    continue
                n = it.get("name") or it.get("Name")
                v = it.get("value") or it.get("Value")
                if not n or v is None:
                    continue
                items.append({
                    "name": str(n), "value": str(v),
                    "domain": it.get("domain") or ".douyin.com",
                    "path": it.get("path") or "/",
                })
            if items:
                return items
        except Exception:
            pass

    # 2) name=value 拼接
    for m in PAIR_RE.finditer(text):
        n, v = m.group(1).strip(), m.group(2).strip()
        if not n or n.lower() in ("path", "domain", "expires", "max-age",
                                 "samesite", "secure", "httponly"):
            continue
        if v.startswith('"') and v.endswith('"') and len(v) > 1:
            v = v[1:-1]
        items.append({"name": n, "value": v,
                      "domain": ".douyin.com", "path": "/"})

    # 去重（同名取最后一个）
    dedup: Dict[str, Dict] = {}
    for it in items:
        dedup[it["name"]] = it
    return list(dedup.values())


def cookies_to_qt(items: List[Dict]) -> List[QNetworkCookie]:
    res = []
    for c in items:
        try:
            ck = QNetworkCookie(QByteArray(str(c["name"]).encode("utf-8")),
                                QByteArray(str(c["value"]).encode("utf-8")))
            ck.setDomain(c.get("domain") or ".douyin.com")
            ck.setPath(c.get("path") or "/")
            ck.setSecure(True)
            res.append(ck)
        except Exception:
            continue
    return res


def import_to_profile(items: List[Dict], profile) -> int:
    """写入 WebEngine Profile 的 CookieStore，返回成功条数"""
    n = 0
    try:
        store = profile.cookieStore()
        for ck in cookies_to_qt(items):
            try:
                store.setCookie(ck, QUrl("https://www.douyin.com/"))
                n += 1
            except Exception:
                pass
    except Exception:
        return 0
    return n


# 只有「登录后才会有」的 Cookie 才算登录标志。
# passport_csrf_token / uid_tt / odin_tt 这些游客也有，不能作为判据，
# 否则会出现「没登录却提示已导入登录态」。
LOGIN_MARKERS = {"sessionid", "sessionid_ss", "sid_tt"}


def has_login(items: List[Dict]) -> bool:
    names = {str(c.get("name", "")) for c in items}
    return bool(names & LOGIN_MARKERS)
