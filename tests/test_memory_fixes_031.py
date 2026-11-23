"""对照《它是怎么记住你的》核对时发现的 3 个问题（0.3.1）：
1 聊天时附上的记忆每句都算「被想起」，强度很快全封顶；2 DeepSeek 系统提示里时间在记忆前面，命中不了提示词缓存；
3 用「一起聊过」加强一条「用户说的」事实，标签被改成【一起聊过】。
另外补上说明书里几条之前没有直接测试的规则：名次合并、可信度系数、强度、推翻等级。"""

from datetime import timedelta

import pytest

from awy import clock
from awy.memory import context, rank


# ---- 1 附上的记忆一天只算一次「被想起」 ----------------------------------------------------
def test_chat_context_counts_recall_once_per_day(store):
    ids = [store.add_fact(f"用户第{i}个长期习惯", actor="t", category="habit", importance=0.8, speaker="user") for i in range(5)]
    for _ in range(12):                      # DeepSeek：每发一句话就拼一次记忆
        context.build_context(store)
    counts = {f["id"]: f["recall_count"] for f in store.current_facts()}
    assert all(counts[i] == 1 for i in ids), counts
    assert rank.strength(store.get_fact(ids[0])) == pytest.approx(1.05)   # 不会聊几句就封顶 1.5


def test_real_search_still_counts_every_time(store):
    fid = store.add_fact("用户喜欢跑步", actor="t", category="habit", speaker="user")
    for _ in range(3):
        rank.search(store, "跑步", 5)
    assert store.get_fact(fid)["recall_count"] == 3


def test_context_counts_again_on_a_new_day(store):
    fid = store.add_fact("用户喜欢猫", actor="t", category="preference", importance=0.8, speaker="user")
    yesterday = (clock.now() - timedelta(days=1)).isoformat(timespec="seconds")
    store._db.execute("UPDATE facts SET recall_count=4, last_recalled_at=? WHERE id=?", (yesterday, fid))
    store._db.commit()
    context.build_context(store)
    context.build_context(store)
    assert store.get_fact(fid)["recall_count"] == 5


# ---- 2 DeepSeek 系统提示：会变的时间放最后 ---------------------------------------------------
def test_deepseek_prompt_puts_time_after_memory(store, monkeypatch):
    from datetime import datetime
    from awy import chat
    from awy.config import Settings
    from awy.ops import ReadOps
    store.add_fact("用户喜欢猫", actor="t", category="preference", importance=0.8, speaker="user")
    ops = ReadOps(store, Settings())
    tz = clock.now().tzinfo
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 21, 10, 1, tzinfo=tz))
    a = chat.deepseek_system_prompt(ops)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 11, 21, 10, 2, tzinfo=tz))
    b = chat.deepseek_system_prompt(ops)
    assert a.index("现在时间") > a.index("一、核心画像与长期特点") > a.index("你是谁")
    # 过了一分钟，前面一字不差的部分要盖住陪伴说明和整个稳定区（这样才能命中提示词缓存）
    same = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
    assert same > a.index("用户喜欢猫")


# ---- 3 「一起聊过」不改掉说话人 ------------------------------------------------------------
def test_shared_reinforce_keeps_user_label(store):
    fid = store.add_fact("用户喜欢吃辣", actor="t", category="preference", speaker="user")
    assert store.reinforce_fact(fid, actor="t", speaker="shared") == 1     # 加分照加
    f = store.get_fact(fid)
    assert f["speaker"] == "user" and f["confidence"] == pytest.approx(0.9)
    assert "【用户说的】" in rank.describe(f)


def test_shared_reinforce_on_shared_fact_and_other_upgrades_still_work(store):
    s = store.add_fact("和 AI 一起定了复习计划", actor="t", category="shared", speaker="shared")
    assert store.reinforce_fact(s, actor="t", speaker="shared") == 1
    assert store.get_fact(s)["speaker"] == "shared"
    a = store.add_fact("用户最近压力很大", actor="t", category="state", speaker="assistant")
    store.reinforce_fact(a, actor="t", speaker="user")                   # AI 猜的被用户亲口说了：照样升级
    f = store.get_fact(a)
    assert f["speaker"] == "user" and f["confidence"] == pytest.approx(0.9)


# ---- 说明书里其他规则：之前没有直接测试的 -----------------------------------------------------
def test_rrf_ranks_by_position_and_normalises():
    r = rank.rrf([[1, 2, 3], [1, 3]])
    assert max(r, key=r.get) == 1 and r[1] == pytest.approx(1.0)
    assert r[3] > r[2]                                  # 两路都有的排在只有一路的前面
    assert rank.rrf([]) == {}


@pytest.mark.parametrize("conf,want", [(1.0, 1.0), (0.9, 0.96), (0.6, 0.84), (0.4, 0.76)])
def test_credibility_factor(conf, want):
    assert rank.credibility({"confidence": conf}) == pytest.approx(want)


def test_strength_caps_at_one_point_five():
    assert rank.strength({}) == 1.0
    assert rank.strength({"recall_count": 3, "reinforce_count": 4}) == pytest.approx(1.35)
    assert rank.strength({"recall_count": 50}) == pytest.approx(1.5)


@pytest.mark.parametrize("old,evidence,allowed", [
    ("user", "assistant", False), ("user", "pc", False), ("note", "user", False),
    ("pc", "user", True), ("assistant", "pc", True), ("user", "shared", True), ("user", "note", True),
])
def test_overturn_levels(store, old, evidence, allowed):
    fid = store.add_fact("用户住在 A 宿舍", actor="t", category="state", speaker=old)
    if allowed:
        store.invalidate_fact(fid, actor="t", speaker=evidence)
        assert store.get_fact(fid)["invalid_at"]
    else:
        with pytest.raises(PermissionError):
            store.invalidate_fact(fid, actor="t", speaker=evidence)
        assert not store.get_fact(fid)["invalid_at"]
