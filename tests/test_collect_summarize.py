from datetime import date, datetime, timedelta

from awy import rawlog, summarize
from awy.collect_pc import PcCollector
from awy.config import Settings


def test_collector_emits_only_on_change():
    s = Settings(blocked_apps=["KeePass.exe"], blocked_keywords=["网银"])
    state = {"fg": ("Code.exe", "a.py"), "idle": 0.0}
    got = []
    c = PcCollector(lambda: s, probe=lambda: state["fg"], idle=lambda: state["idle"], sink=got.append)
    c.tick(); c.tick()
    assert [e["type"] for e in got] == ["window"]
    state["fg"] = ("KeePass.exe", "我的密码库")
    c.tick()
    assert got[-1]["app"] == "[隐私窗口]" and got[-1]["title"] == ""
    state["fg"] = ("chrome.exe", "登录 13812345678")
    c.tick()
    assert "13812345678" not in got[-1]["title"]
    state["idle"] = 999
    c.tick(); c.tick()
    assert got[-1]["type"] == "away" and sum(e["type"] == "away" for e in got) == 1
    state["idle"] = 0
    c.tick()
    assert [e["type"] for e in got[-2:]] == ["back", "window"]
    s.collect_enabled = False
    c.tick(); c.tick()
    assert got[-1]["type"] == "paused" and sum(e["type"] == "paused" for e in got) == 1


def _ev(t, **kw):
    return {"ts": t.isoformat(), "src": "pc", **kw}


def test_summary_merges_and_counts():
    t0 = datetime(2026, 11, 20, 10, 0).astimezone()
    evs = [
        _ev(t0, type="window", app="Code.exe", title="a.py"),
        _ev(t0 + timedelta(minutes=20), type="window", app="Code.exe", title="b.py"),
        _ev(t0 + timedelta(minutes=30), type="window", app="chrome.exe", title="B站"),
        _ev(t0 + timedelta(minutes=30, seconds=20), type="window", app="Code.exe", title="b.py"),
        _ev(t0 + timedelta(minutes=50), type="away", reason="idle"),
        _ev(t0 + timedelta(minutes=80), type="back"),
        _ev(t0 + timedelta(minutes=80), type="window", app="chrome.exe", title="文档"),
    ]
    for e in evs:
        rawlog.append(e)
    text = summarize.summarize_range(t0, t0 + timedelta(minutes=90))
    assert "10:00–10:30 Code.exe（30 分）：a.py；b.py" in text
    assert "离开或暂停约 30 分" in text
    assert "chrome.exe：10 分" in text      # 20 秒的碎片只计入统计
    assert "Code.exe：50 分" in text


def test_summary_empty_range():
    t0 = datetime(2026, 11, 20, 10, 0).astimezone()
    assert "没有电脑使用记录" in summarize.summarize_range(t0, t0 + timedelta(hours=1))


def test_prune_keeps_recent():
    rawlog.append({"ts": datetime(2026, 1, 1, 12).astimezone().isoformat(), "type": "x"})
    rawlog.append({"ts": datetime(2026, 11, 19, 12).astimezone().isoformat(), "type": "x"})
    assert rawlog.prune(30, today=date(2026, 11, 20)) == ["2026-01-01"]
