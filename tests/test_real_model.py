"""用真实 bge-m3 模型检验「按意思搜索」的效果。电脑上没下载模型时自动跳过。

改 rank.py 里的门槛（VECTOR_ABS_MIN / VECTOR_REL_GAP / DUP_SIM_*）后必须跑这个测试。
"""

import os
from pathlib import Path

import pytest

from awy.memory import embed, rank
from awy.memory.store import MemoryStore

REAL_MODELS = Path(os.environ.get("LOCALAPPDATA", "")) / "AlwaysWithYou" / "models"
pytestmark = pytest.mark.skipif(not embed.is_installed(REAL_MODELS), reason="没有下载 bge-m3 模型")

FACTS = ["用户今天早上去操场晨练了", "用户晚上去跑步五公里", "用户喜欢吃麻辣火锅", "用户在写 Python 记忆库项目",
         "用户最近熬夜到很晚", "用户睡眠不足，白天很困", "用户和室友小王关系很好", "用户对花生过敏",
         "用户下周有期中考试"]


@pytest.fixture(scope="module")
def real_store(tmp_path_factory):
    s = MemoryStore(tmp_path_factory.mktemp("real") / "m.db", embedder=embed.Bge3Embedder(REAL_MODELS))
    for f in FACTS:
        s.add_fact(f, actor="test")
    yield s
    s.close()


def _top(store, q, k=2):
    return {h.fact["text"] for h in rank.search(store, q, k, record_recall=False)}


def test_vectors_are_normalized(real_store):
    v = real_store.embedder.encode(["你好", "今天天气不错"])
    assert v.shape == (2, 1024)
    assert abs(float((v[0] ** 2).sum()) - 1) < 1e-3


def test_semantic_search_finds_related_without_shared_words(real_store):
    assert _top(real_store, "运动") == {"用户今天早上去操场晨练了", "用户晚上去跑步五公里"}
    assert _top(real_store, "最近睡得怎么样") == {"用户最近熬夜到很晚", "用户睡眠不足，白天很困"}
    assert "用户和室友小王关系很好" in _top(real_store, "朋友", 1)
    assert "用户喜欢吃麻辣火锅" in _top(real_store, "吃的", 1)


def test_near_duplicate_is_suppressed(real_store):
    real_store.add_fact("用户正在编写 Python 的记忆库项目", actor="test")
    hits = [h.fact["text"] for h in rank.search(real_store, "记忆库项目", 2, record_recall=False)]
    assert not ({"用户在写 Python 记忆库项目", "用户正在编写 Python 的记忆库项目"} <= set(hits))
