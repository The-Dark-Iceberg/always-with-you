from datetime import datetime, timedelta

import pytest

from awy.memory import context, rank
from tests.conftest import at

NOW = datetime(2026, 11, 20, 20, 0).astimezone()


def test_bitemporal_invalidate_and_undo(store):
    old = store.add_fact("用户住在 3 号宿舍", actor="t", category="state", valid_at=at("2026-09-01T00:00"))
    store.invalidate_fact(old, actor="t", invalid_at=at("2026-11-01T00:00"), reason="搬家")
    new = store.add_fact("用户搬到了 5 号宿舍", actor="t", category="state", valid_at=at("2026-11-01T00:00"))
    assert [f["id"] for f in store.current_facts()] == [new]
    # 回顾 10 月时，旧事实仍然能查到
    assert old in [f["id"] for f in store.facts_valid_during(at("2026-10-01T00:00"), at("2026-10-31T00:00"))]
    # 撤销「标记失效」→ 旧事实恢复
    log = store.audit_log()
    inv = next(a for a in log if a["action"] == "invalidate_fact")
    store.undo(inv["id"])
    assert old in [f["id"] for f in store.current_facts()]
    # 撤销「新增」→ 新事实被撤回（不是删除，记录还在）
    add = next(a for a in log if a["action"] == "add_fact" and a["target"] == f"fact:{new}")
    store.undo(add["id"])
    assert new not in [f["id"] for f in store.current_facts()]
    assert store.get_fact(new)["retracted_at"]
    assert "已经撤销" in store.undo(add["id"])


def test_tier_weights():
    assert [rank.tier_weight(d) for d in (0.5, 2, 5, 20, 90)] == [1.0, 0.8, 0.5, 0.2, 0.05]


def test_durable_facts_do_not_fade(store):
    fid = store.add_fact("用户对花生过敏", actor="t", category="health", importance=0.9,
                         valid_at=at("2025-01-01T00:00"))
    f = store.get_fact(fid)
    assert rank.time_weight(f, NOW) >= rank.DURABLE_FLOOR


def test_search_prefers_recent_and_relevant(store):
    store.add_fact("用户晚上去操场跑步", actor="t", valid_at=(NOW - timedelta(days=60)).isoformat())
    recent = store.add_fact("用户今天去操场跑步了五公里", actor="t", valid_at=(NOW - timedelta(hours=3)).isoformat())
    store.add_fact("用户喜欢吃火锅", actor="t", category="preference", valid_at=(NOW - timedelta(days=2)).isoformat())
    hits = rank.search(store, "跑步", 2, now=NOW)
    assert hits[0].fact["id"] == recent
    assert all("火锅" not in h.fact["text"] for h in hits)
    assert store.get_fact(recent)["recall_count"] == 1     # 被回忆加强


def test_search_hides_invalid_unless_history(store):
    fid = store.add_fact("用户在学日语", actor="t", valid_at=(NOW - timedelta(days=10)).isoformat())
    store.invalidate_fact(fid, actor="t", reason="放弃了")
    assert rank.search(store, "日语", now=NOW) == []
    assert rank.search(store, "日语", include_history=True, now=NOW)[0].fact["id"] == fid


def test_mmr_removes_near_duplicates(store):
    # 假向量模型只按字符计数，判断不了「同义句」；这里用完全相同的句子检验去重逻辑。
    # 同义句的去重效果由 tests/test_real_model.py 用真实模型检验。
    for _ in range(3):
        store.add_fact("用户在写记忆库项目代码", actor="t", valid_at=NOW.isoformat())
    store.add_fact("用户在写记忆库的说明文档", actor="t", valid_at=NOW.isoformat())
    texts = [h.fact["text"] for h in rank.search(store, "记忆库", 2, now=NOW)]
    assert any("说明文档" in t for t in texts)


def test_context_order_and_budget(store):
    store.set_persona("用户是一名大学生，说话直接。", actor="t")
    store.add_fact("用户偏好简洁直接的回答", actor="t", category="preference", importance=0.8,
                   valid_at=(NOW - timedelta(days=100)).isoformat())
    store.add_fact("用户这周在准备期中考试", actor="t", category="state",
                   valid_at=(NOW - timedelta(days=4)).isoformat())
    store.add_fact("用户今天熬夜了", actor="t", category="state", valid_at=(NOW - timedelta(hours=2)).isoformat())
    store.add_episode("pc_summary", "# 电脑活动摘要\n- 在电脑前约 2 小时。",
                      (NOW - timedelta(hours=3)).isoformat(), (NOW - timedelta(hours=1)).isoformat())
    text = context.build_context(store, now=NOW)
    i_persona, i_pref = text.index("大学生"), text.index("简洁直接")
    i_exam, i_today = text.index("期中考试"), text.index("熬夜")
    assert i_persona < i_pref < i_exam < i_today
    assert "在电脑前约 2 小时" in text
    assert text.startswith(context.PREFACE)
    small = context.build_context(store, budget_static=5, budget_recent=5, budget_today=5, now=NOW)
    assert "期中考试" not in small


def test_static_part_is_stable(store):
    store.set_persona("用户是一名大学生。", actor="t")
    store.add_fact("用户偏好简洁", actor="t", category="preference", importance=0.8)
    a = context.build_context(store, now=NOW).split("## 二")[0]
    b = context.build_context(store, now=NOW + timedelta(hours=5)).split("## 二")[0]
    assert a == b   # 稳定区字节不变，才能命中提示词缓存


def test_inbox_validation(store):
    with pytest.raises(ValueError):
        store.add_inbox("delete_all", "x", "chat")
    with pytest.raises(ValueError):
        store.add_inbox("note", "   ", "chat")
    nid = store.add_inbox("remember", "用户说他对花生过敏", "chat")
    assert store.pending_inbox()[0]["id"] == nid


def test_entity_aliases(store):
    eid = store.upsert_entity("王小明", "person", ["小王", "王同学"], actor="t")
    assert store.resolve_entity("小王")["id"] == eid
    assert store.upsert_entity("王同学", actor="t") == eid
