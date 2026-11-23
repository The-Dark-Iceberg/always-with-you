import json
from datetime import datetime, time, timedelta

from awy import config, vault
from awy.pipeline import is_last_slot_of_day, last_slot_before, make_summary_episode


def test_last_slot():
    slots = [time(10), time(14), time(19), time(23, 30)]
    now = datetime(2026, 11, 20, 15, 0).astimezone()
    assert last_slot_before(now, slots).time() == time(14)
    early = datetime(2026, 11, 20, 8, 0).astimezone()
    s = last_slot_before(early, slots)
    assert s.date().day == 19 and s.time() == time(23, 30) and is_last_slot_of_day(s, slots)


def test_summary_episode_chain(store):
    now = datetime(2026, 11, 20, 14, 0).astimezone()
    first = make_summary_episode(store, now)
    assert first is not None
    assert make_summary_episode(store, now + timedelta(minutes=2)) is None   # 太短不生成
    second = make_summary_episode(store, now + timedelta(hours=5))
    eps = store.pending_episodes()
    assert [e["id"] for e in eps] == [first, second]
    assert eps[1]["period_start"] == eps[0]["period_end"]                    # 首尾相接，不重不漏


def test_config_roundtrip_and_tokens(tmp_path):
    p = tmp_path / "c.json"
    s = config.load(p)
    assert s.read_token and s.write_token and s.read_token != s.write_token
    s.organize_times = ["09:00"]
    config.save(s, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["unknown_field"] = 1
    p.write_text(json.dumps(data), encoding="utf-8")
    s2 = config.load(p)
    assert s2.organize_times == ["09:00"] and s2.read_token == s.read_token


def test_vault_roundtrip():
    enc = vault.protect("sk-test-123")
    assert "sk-test-123" not in enc
    assert vault.unprotect(enc) == "sk-test-123"
    assert vault.protect("") == "" and vault.unprotect("") == ""

