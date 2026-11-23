"""检索打分。算法说明见 docs/MEMORY_ALGORITHMS.md。

最终得分 = 相关度 × 时间权重 × 重要度系数 × 强度系数 × 确认加成
- 相关度：关键词搜索和向量搜索两路结果按名次融合（RRF，借鉴 Graphiti）。
- 时间权重：用户设计的 5 档按天衰减；性格/偏好/习惯/关系/健康这类长期事实不衰减到 0.8 以下。
- 重要度系数：0.5 + 0.5 × importance（Generative Agents 的「重要性」）。
- 强度系数：被回忆、被重复提到的次数越多越强（MemoryBank 的遗忘曲线思想）。
- 确认加成：用户亲口确认/纠正过的 ×1.2。
- 可信度系数：0.6 + 0.4 × 可信度（说话人权重，决定 0011：用户说的 0.9、AI 猜的 0.4……）。
最后用 MMR 去掉意思重复的结果（借鉴 Graphiti）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from awy import clock
from awy.memory import text as T
from awy.memory.store import MemoryStore

# 5 档按天衰减：(不超过多少天, 权重)
DECAY_TIERS: list[tuple[float, float]] = [(1, 1.0), (3, 0.8), (7, 0.5), (30, 0.2)]
OLD_WEIGHT = 0.05
DURABLE_CATEGORIES = {"trait", "preference", "habit", "relation", "health"}
DURABLE_FLOOR = 0.8
RRF_K = 60
# bge-m3 实测（2026-11-20）：相关内容相似度约 0.57~0.75，无关内容也有 0.45~0.56，
# 所以用「相对门槛」：只要和最相关那条差距不超过 VECTOR_REL_GAP、且不低于 VECTOR_ABS_MIN 的结果。
VECTOR_ABS_MIN = 0.5
VECTOR_REL_GAP = 0.07
# 只有「几乎同一句话」才算重复：实测换个说法的同义句约 0.99，相关但不同的事（晨练/跑步）约 0.70。
DUP_SIM_VECTOR = 0.9
DUP_SIM_TOKENS = 0.6


def age_days(fact: dict, now: datetime) -> float:
    return max(0.0, (now - datetime.fromisoformat(fact["valid_at"])).total_seconds() / 86400)


def tier_weight(days: float) -> float:
    for limit, w in DECAY_TIERS:
        if days <= limit:
            return w
    return OLD_WEIGHT


def time_weight(fact: dict, now: datetime) -> float:
    w = tier_weight(age_days(fact, now))
    if fact["category"] in DURABLE_CATEGORIES or fact["importance"] >= 0.8 or fact["confirmed"]:
        w = max(w, DURABLE_FLOOR)
    return w


def strength(fact: dict) -> float:
    """reinforce_count 存的是「加强分」：用户再提 +2，电脑活动 / 认同 / 聊过 +1，AI 复述 +0（见 store.SPEAKERS）。"""
    n = int(fact.get("recall_count", 0)) + int(fact.get("reinforce_count", 0))
    return 1.0 + 0.05 * min(n, 10)


def credibility(fact: dict) -> float:
    """可信度系数 0.6~1.0：AI 猜的最多打六折，不会完全看不到。"""
    c = fact.get("confidence")
    return 0.6 + 0.4 * (0.6 if c is None else float(c))


def base_score(fact: dict, now: datetime) -> float:
    s = time_weight(fact, now) * (0.5 + 0.5 * fact["importance"]) * strength(fact) * credibility(fact)
    return s * (1.2 if fact["confirmed"] else 1.0)


def rrf(rank_lists: list[list[int]]) -> dict[int, float]:
    """名次融合：每一路里排第 r 名得 1/(K+r)，加起来，再归一化到 0~1。"""
    scores: dict[int, float] = {}
    for lst in rank_lists:
        for r, fid in enumerate(lst, start=1):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (RRF_K + r)
    if not scores:
        return scores
    top = len(rank_lists) / (RRF_K + 1)
    return {k: v / top for k, v in scores.items()}


def is_duplicate(a: dict, b: dict, vecs: dict[int, np.ndarray]) -> bool:
    """两条事实是否「几乎是同一句话」。相关但不同的事（晨练/跑步）不算。"""
    va, vb = vecs.get(a["id"]), vecs.get(b["id"])
    if va is not None and vb is not None:
        return float(np.dot(va, vb)) >= DUP_SIM_VECTOR
    ta, tb = set(T.tokens(a["text"])), set(T.tokens(b["text"]))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= DUP_SIM_TOKENS


def mmr(items: list[tuple[dict, float]], k: int, vecs: dict[int, np.ndarray]) -> list[tuple[dict, float]]:
    """按得分从高到低挑，跳过和已选结果重复的（MMR 思想的简化版：实测线性扣分压不住真正的重复句）。"""
    chosen: list[tuple[dict, float]] = []
    for f, s in sorted(items, key=lambda x: -x[1]):
        if len(chosen) >= k:
            break
        if not any(is_duplicate(f, c, vecs) for c, _ in chosen):
            chosen.append((f, s))
    return chosen


@dataclass
class Hit:
    fact: dict
    score: float


def search(store: MemoryStore, query: str, k: int = 8, *, include_history: bool = False,
           now: datetime | None = None, record_recall: bool = True) -> list[Hit]:
    now = now or clock.now()
    lists: list[list[int]] = []
    lists.append([fid for fid, _ in store.fts_search(query, 50, include_inactive=include_history)])

    vecs: dict[int, np.ndarray] = {}
    if store.embedder is not None:
        ids, mat = store.embeddings(include_inactive=include_history)
        if mat is not None:
            try:
                q = np.asarray(store.embedder.encode([query])[0], dtype=np.float32)
                sims = mat @ q
                order = np.argsort(-sims)[:50]
                cutoff = max(VECTOR_ABS_MIN, float(sims[order[0]]) - VECTOR_REL_GAP)
                lists.append([ids[i] for i in order if sims[i] >= cutoff])
                vecs = {ids[i]: mat[i] for i in order}
            except Exception:
                pass

    rel = rrf(lists)
    facts = store.facts_by_ids(list(rel))
    scored = [(f, rel[fid] * base_score(f, now)) for fid, f in facts.items()
              if f["retracted_at"] is None and (include_history or f["invalid_at"] is None)]
    scored.sort(key=lambda x: -x[1])
    picked = mmr(scored[: k * 3], k, vecs)
    if record_recall:
        store.note_recalled([f["id"] for f, _ in picked])
    return [Hit(f, s) for f, s in picked]


def describe(fact: dict[str, Any]) -> str:
    """把一条事实写成给 AI 看的一行。"""
    when = fact["valid_at"][:10]
    tail = ""
    if fact.get("invalid_at"):
        tail = f"（到 {fact['invalid_at'][:10]} 不再成立）"
    sp = fact.get("speaker")
    flag = ("【用户确认】" if fact.get("confirmed") else "【用户说的】" if sp in ("user", "user_agreed")
            else "【一起聊过】" if sp == "shared" else "【AI 推测，未经确认】" if sp == "assistant" else "")
    return f"- [#{fact['id']}] {flag}{fact['text']}（{when}，{fact['category']}）{tail}"
