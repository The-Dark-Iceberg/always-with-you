"""中文分词，给 SQLite 全文搜索用。

SQLite 自带的全文搜索按空格切词，中文没有空格，所以先用 jieba 切好再存。
"""

from __future__ import annotations

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    out = []
    for w in jieba.cut_for_search(text or ""):
        w = _PUNCT.sub("", w).lower()
        if w:
            out.append(w)
    return out


def tokenize(text: str) -> str:
    return " ".join(tokens(text))


def fts_query(text: str) -> str:
    """把用户问题变成 FTS5 查询：任意一个词命中即可（OR），词用双引号包起来防止语法错误。"""
    words = list(dict.fromkeys(tokens(text)))
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words)
