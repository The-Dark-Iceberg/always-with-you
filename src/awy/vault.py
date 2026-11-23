"""用 Windows 自带的 DPAPI 加密保存密钥（如 DeepSeek API Key）。

加密结果只有「同一台电脑上的同一个 Windows 账号」能解开；配置文件被拷走也读不出原文。
非 Windows 系统（只用于开发测试）退化为明文并打上前缀，方便识别。
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

_PLAIN_PREFIX = "plain:"
_DPAPI_PREFIX = "dpapi:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _Blob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def protect(text: str) -> str:
    if not text:
        return ""
    if sys.platform != "win32":
        return _PLAIN_PREFIX + text
    src = _to_blob(text.encode("utf-8"))
    dst = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(src), "AlwaysWithYou", None, None, None, 0, ctypes.byref(dst)
    )
    if not ok:
        raise OSError("DPAPI 加密失败")
    return _DPAPI_PREFIX + base64.b64encode(_from_blob(dst)).decode("ascii")


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith(_PLAIN_PREFIX):
        return stored[len(_PLAIN_PREFIX):]
    if not stored.startswith(_DPAPI_PREFIX):
        raise ValueError("无法识别的密钥格式")
    raw = base64.b64decode(stored[len(_DPAPI_PREFIX):])
    src = _to_blob(raw)
    dst = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)
    )
    if not ok:
        raise OSError("DPAPI 解密失败（可能换了电脑或 Windows 账号）")
    return _from_blob(dst).decode("utf-8")
