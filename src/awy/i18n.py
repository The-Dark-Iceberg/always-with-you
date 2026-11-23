"""多语言：中文是原文，其他语言各一个翻译文件 ui/i18n/<代码>.json（界面和后台共用同一份）。

用法：
    from awy.i18n import t
    t("已保存")                      -> 当前语言下的文字
    t("向量模型已启用，已为 {n} 条记忆建立索引", n=3)  -> 带变量（翻译里用同样的 {n}）

规则（给后来维护的人 / AI）：
- 只翻译「给人看的」文字：界面、提示、托盘、通知。写给 AI 看的提示词、工具说明不翻译（AI 都看得懂中文）。
- 翻译文件的键就是中文原文。没翻译到的会直接显示中文，不会出错。
- tests/test_i18n.py 会检查：代码里每个 t(中文) / T(中文) 在每个翻译文件里都有，变量名也一致。
- 加一种语言：复制 ui/i18n/en.json 改名（如 ja.json）并翻译，再在 LANGS 和 ui/js/i18n.js 里各加一行。
"""

from __future__ import annotations

import json
import logging
import sys

from awy import paths

log = logging.getLogger(__name__)

LANGS = {"zh": "简体中文", "en": "English"}
SOURCE = "zh"

_lang = SOURCE
_cache: dict[str, dict[str, str]] = {}


def system_lang() -> str:
    """Windows 界面语言是中文就用中文，否则用英文。"""
    if sys.platform == "win32":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (lid & 0x3FF) == 0x04 else "en"
        except (OSError, AttributeError):
            pass
    return SOURCE


def resolve(setting: str) -> str:
    """设置里的值：空字符串表示「跟随系统」。"""
    return setting if setting in LANGS else system_lang()


def set_lang(code: str) -> None:
    global _lang
    _lang = code if code in LANGS else SOURCE


def lang() -> str:
    return _lang


def _dict(code: str) -> dict[str, str]:
    if code not in _cache:
        f = paths.ui_dir() / "i18n" / f"{code}.json"
        try:
            _cache[code] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("读不了翻译文件 %s，改用中文", f)
            _cache[code] = {}
    return _cache[code]


def t(text: str, **kw: object) -> str:
    out = text if _lang == SOURCE else _dict(_lang).get(text, text)
    if kw:
        try:
            out = out.format(**kw)
        except (KeyError, IndexError, ValueError):
            out = text.format(**kw)
    return out


def memory_language() -> str:
    """整理记忆时，事实和画像用哪种语言写（写给 AI 的说明）。"""
    return {"zh": "中文", "en": "English"}.get(_lang, "中文")
