"""决定 0011：时区、说话人权重、聊天参与整理、正在播放、最近文件、浏览器扩展。全部不联网、不碰真实数据。"""

import base64
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from awy import clock


@pytest.fixture(autouse=True)
def reset_clock():
    yield
    clock.set_zone("")


# ---- 时区 ----------------------------------------------------------------------------
def test_clock_zone_changes_local_time():
    assert clock.set_zone("Asia/Shanghai") and clock.zone_name() == "Asia/Shanghai"
    sh = clock.now()
    assert clock.set_zone("Europe/London")
    ld = clock.now()
    assert sh.utcoffset() != ld.utcoffset() and abs((sh - ld).total_seconds()) < 5   # 同一时刻，不同地区的钟
    assert not clock.set_zone("Mars/Olympus") and clock.zone_name() == ""            # 不认识的退回跟随电脑
    assert "Europe/London" in clock.zones() and not any(z.startswith("Etc/") for z in clock.zones())
    utc_noon = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    clock.set_zone("Europe/London")
    assert clock.to_local(utc_noon).hour == 13                                       # 夏令时自动处理


def test_rawlog_reads_across_zone_change(data_dir):
    """换过时区后，同一时刻的记录可能落在相邻日期的文件里，读的时候要找得到。"""
    from awy import rawlog
    clock.set_zone("Asia/Shanghai")
    ev_time = datetime(2026, 11, 20, 1, 30, tzinfo=clock.now().tzinfo)               # 上海 11-20 01:30 = 伦敦 11-19 17:30
    rawlog.append({"ts": ev_time.isoformat(), "src": "pc", "type": "window", "app": "a.exe", "title": ""})
    clock.set_zone("Europe/London")
    tz = clock.now().tzinfo
    got = rawlog.read_range(datetime(2026, 11, 19, 17, 0, tzinfo=tz), datetime(2026, 11, 19, 18, 0, tzinfo=tz))
    assert len(got) == 1


# ---- 说话人权重 ------------------------------------------------------------------------
def test_old_database_is_upgraded(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'event',
        importance REAL NOT NULL DEFAULT 0.5, confirmed INTEGER NOT NULL DEFAULT 0, subject_id INTEGER,
        valid_at TEXT NOT NULL, invalid_at TEXT, invalid_reason TEXT, created_at TEXT NOT NULL, retracted_at TEXT,
        episode_id INTEGER, inbox_id INTEGER, source TEXT NOT NULL, recall_count INTEGER NOT NULL DEFAULT 0,
        last_recalled_at TEXT, reinforce_count INTEGER NOT NULL DEFAULT 0, embedding BLOB, embed_model TEXT);
      INSERT INTO facts(text, valid_at, created_at, source, reinforce_count, confirmed)
        VALUES('用户喜欢猫', '2026-11-01T10:00:00+08:00', '2026-11-01T10:00:00+08:00', 'deepseek', 3, 0),
              ('用户对花生过敏', '2026-11-01T10:00:00+08:00', '2026-11-01T10:00:00+08:00', 'deepseek', 0, 1);
    """)
    con.commit()
    con.close()
    from awy.memory.store import MemoryStore
    s = MemoryStore(db)
    a, b = s.get_fact(1), s.get_fact(2)
    assert a["reinforce_count"] == 6 and a["speaker"] == "pc" and a["confidence"] == pytest.approx(0.6)   # 旧公式 ×2，排序不变
    assert b["speaker"] == "note" and b["confidence"] == 1.0
    s.close()
    s = MemoryStore(db)   # 再打开一次不会再乘 2
    assert s.get_fact(1)["reinforce_count"] == 6
    s.close()


def test_speaker_confidence_and_ranking(store):
    from awy.memory import rank
    u = store.add_fact("用户最近压力很大", actor="t", category="state", importance=0.5, speaker="user")
    a = store.add_fact("用户最近压力很大（AI 猜的）", actor="t", category="state", importance=0.5, speaker="assistant")
    fu, fa = store.get_fact(u), store.get_fact(a)
    assert fu["confidence"] == 0.9 and fa["confidence"] == 0.4
    now = datetime.now().astimezone()
    assert rank.base_score(fu, now) > rank.base_score(fa, now)
    assert "AI 推测" in rank.describe(fa) and "用户说的" in rank.describe(fu)
    sh = store.add_fact("和 AI 讨论了复习计划", actor="t", category="event", speaker="shared")
    assert store.get_fact(sh)["category"] == "shared" and store.get_fact(sh)["confidence"] == 1.0
    n = store.add_fact("用户对花生过敏", actor="t", category="health", confirmed=True)
    assert store.get_fact(n)["speaker"] == "note"


def test_reinforce_by_speaker_and_undo(store):
    fid = store.add_fact("用户喜欢猫", actor="t", category="preference", speaker="assistant")
    assert store.reinforce_fact(fid, actor="t", speaker="assistant") == 0           # AI 复述不加分，什么都不改
    f = store.get_fact(fid)
    assert f["reinforce_count"] == 0 and f["confidence"] == 0.4
    assert store.reinforce_fact(fid, actor="t", speaker="user") == 2                # 用户亲口说了：+2，可信度升上去
    f = store.get_fact(fid)
    assert f["reinforce_count"] == 2 and f["confidence"] == 0.9 and f["speaker"] == "user"
    last = store.audit_log(1)[0]
    store.undo(last["id"])
    f = store.get_fact(fid)
    assert f["reinforce_count"] == 0 and f["confidence"] == 0.4 and f["speaker"] == "assistant"


def test_lower_speaker_cannot_overturn_higher(store):
    from awy.ops import WriteOps
    ops = WriteOps(store, "t")
    fid = store.add_fact("用户住在 A 宿舍", actor="t", category="state", speaker="user")
    msg = ops.invalidate_fact(fid, reason="AI 觉得搬家了", speaker="assistant")
    assert "没有推翻" in msg and store.get_fact(fid)["invalid_at"] is None
    assert "不再成立" in ops.invalidate_fact(fid, reason="用户说搬到 B 了", speaker="user")
    assert store.get_fact(fid)["invalid_at"]
    pc = store.add_fact("用户常用 VS Code", actor="t", category="habit", speaker="pc")
    assert "不再成立" in ops.invalidate_fact(pc, reason="用户说换编辑器了", speaker="user")
    assert "speaker 必须是" in ops.add_fact("x", category="event", importance=0.5, speaker="god")
    assert "没有加强" in ops.reinforce_fact(pc, speaker="assistant")


# ---- 聊天参与整理 ---------------------------------------------------------------------
def test_chat_becomes_an_episode(store, data_dir):
    from awy import chat, pipeline
    from awy.config import Settings
    now = clock.now()
    for i, (role, text) in enumerate([("me", "今天考完线代了，好累"), ("ai", "辛苦啦！那周末打算休息一下吗？"), ("me", "对，想去看电影")]):
        rec = {"ts": (now - timedelta(minutes=30 - i)).isoformat(timespec="seconds"), "role": role, "text": text, "brain": "deepseek"}
        with chat._chat_file(clock.today()).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    s = Settings()
    eid = pipeline.make_chat_episode(store, now, s)
    ep = next(e for e in store.pending_episodes() if e["id"] == eid)
    assert ep["source"] == "chat" and "用户：今天考完线代了" in ep["content"] and "AI：辛苦啦" in ep["content"]
    assert pipeline.make_chat_episode(store, now + timedelta(minutes=1), s) is None      # 没有新聊天就不再生成
    s.chat_in_memory = False
    assert pipeline.make_chat_episode(store, now + timedelta(hours=1), s) is None


def test_chat_episode_budget_keeps_user_words():
    from awy import chat
    now = clock.now()
    recs = []
    for i in range(60):
        recs.append({"ts": (now + timedelta(seconds=i)).isoformat(), "role": "me", "text": f"用户第{i}句" + "嗯" * 100})
        recs.append({"ts": (now + timedelta(seconds=i, milliseconds=1)).isoformat(), "role": "ai", "text": "长回复" * 400})
    text = chat.render_chat_episode(recs, now, now + timedelta(minutes=5))
    assert len(text) <= chat.CHAT_EPISODE_BUDGET + 200
    assert "用户第59句" in text                     # 最近的用户的话一定保留


# ---- 正在播放 / 最近文件 / 摘要 --------------------------------------------------------
def test_media_collector_only_records_changes():
    from awy.collect_more import MediaCollector
    from awy.config import Settings
    got, now_playing = [], [{"app": "cloudmusic.exe", "title": "晴天", "artist": "周杰伦", "playing": True}]
    s = Settings()
    c = MediaCollector(lambda: s, read=lambda: now_playing, sink=got.append)
    c.tick()
    c.tick()
    assert len(got) == 1 and got[0]["app"] == "cloudmusic" and got[0]["title"] == "晴天" and got[0]["state"] == "playing"
    now_playing[0] = {**now_playing[0], "playing": False}
    c.tick()
    assert got[-1]["state"] == "stopped"
    now_playing[0] = {"app": "MSEdge", "title": "密码 Abc@12345 的视频", "artist": "", "playing": True}
    c.tick()
    assert "Abc@12345" not in got[-1]["title"]       # 不走黑名单，但密码照样打码


def test_recent_files_collector(tmp_path):
    from awy.collect_more import RecentFilesCollector
    from awy.config import Settings
    recent = tmp_path / "Recent"
    recent.mkdir()
    since = time.time() - 5
    old = recent / "旧文件.docx.lnk"
    old.write_text("x")
    os.utime(old, (since - 100, since - 100))
    for name in ("期末复习.pdf.lnk", "某个文件夹.lnk", "网银密码.xlsx.lnk", "notepad.exe.lnk"):
        (recent / name).write_text("x")
    got = []
    c = RecentFilesCollector(lambda: Settings(), folder=lambda: recent, sink=got.append, since=since)
    c.tick()
    assert [e["name"] for e in got] == ["期末复习.pdf"]   # 旧的、文件夹、含隐私关键词的、程序快捷方式都不记


def test_summary_has_new_sections_and_window_time_is_not_cut():
    from awy import summarize
    t0 = datetime(2026, 11, 20, 14, 0, tzinfo=timezone(timedelta(hours=8)))
    ev = lambda m, **kw: {"ts": (t0 + timedelta(minutes=m)).isoformat(), **kw}   # noqa: E731
    events = [
        ev(0, type="window", app="Code.exe", title="memory.py"),
        ev(1, type="media", state="playing", app="cloudmusic", title="晴天", artist="周杰伦"),
        ev(5, type="web", domain="bilibili.com", url="https://bilibili.com/video/x", title="线代教程"),
        ev(6, type="file", name="期末复习.pdf"),
        ev(8, type="web", domain="google.com", url="https://google.com/search", title="搜索", search="特征值 怎么求"),
        ev(9, type="web", state="off"),
        ev(20, type="media", state="stopped"),
    ]
    clock.set_zone("Asia/Shanghai")
    text = summarize.render(events, t0, t0 + timedelta(minutes=30))
    assert "Code.exe（30 分）" in text                       # 中间夹着别的事件，窗口时长照样是 30 分钟
    assert "晴天 - 周杰伦" in text and "bilibili.com · 线代教程" in text
    assert "「特征值 怎么求」" in text and "期末复习.pdf" in text


# ---- 浏览器扩展 ------------------------------------------------------------------------
def test_url_cleaning_rules():
    from awy.browser import clean
    assert clean("http://example.com/a?x=1", "t", []) is None                  # http 一点都不记
    assert clean("chrome://settings", "t", []) is None
    r = clean("https://www.bilibili.com/video/BV1tDs66oEQa?spm_id=xx&token=SECRET#t=30", "某视频", [])
    assert r["url"] == "https://www.bilibili.com/video/BV1tDs66oEQa" and r["domain"] == "bilibili.com"
    assert "SECRET" not in json.dumps(r)
    assert clean("https://www.google.com/search?q=%E7%BA%BF%E4%BB%A3&sca=1", "线代 - Google", [])["search"] == "线代"
    assert clean("https://www.baidu.com/s?wd=期末复习", "百度", [])["search"] == "期末复习"
    assert clean("https://search.bilibili.com/all?keyword=考研数学", "B站", [])["search"] == "考研数学"
    assert clean("https://www.google.com.hk/search?q=abc", "", [])["search"] == "abc"
    assert "search" not in clean("https://notgoogle.example/search?q=abc", "", [])
    assert clean("https://bank.example.com/x", "招商银行网银", ["网银"])["domain"] == "[隐私网页]"


def test_bridge_accepts_only_our_extension(data_dir):
    from starlette.testclient import TestClient

    from awy import browser
    from awy.config import Settings
    got = []
    s = Settings()
    br = browser.BrowserBridge(lambda: s, sink=got.append)
    c = TestClient(br.app, base_url="http://127.0.0.1:47823")
    body = json.dumps({"url": "https://github.com/x?y=1", "title": "x"})
    assert c.post("/browser/page", content=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/browser/page", content=body).status_code == 403                 # 没有 Origin 也不行
    ok = {"Origin": f"chrome-extension://{browser.EXTENSION_ID}", "Content-Type": "text/plain"}
    assert c.post("/browser/page", content=body, headers=ok).json()["recorded"] is True
    assert c.post("/browser/page", content=body, headers=ok).json()["recorded"] is False    # 一样的不重复记
    c.post("/browser/page", content=json.dumps({"off": True}), headers=ok)
    assert [e.get("domain", e.get("state")) for e in got] == ["github.com", "off"] and br.last_seen
    s.collect_enabled = False
    c.post("/browser/page", content=body, headers=ok)
    assert len(got) == 2
    assert c.post("/browser/page", content="x" * 10000, headers=ok).status_code == 413


def test_extension_files_match_app():
    """扩展的固定 ID、端口要和程序里写的一致，否则扩展发的数据会被拒收。"""
    from awy import browser, paths
    from awy.config import Settings
    d = paths.extension_dir()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    h = hashlib.sha256(base64.b64decode(m["key"])).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(ch, 16)) for ch in h) == browser.EXTENSION_ID
    port = Settings().browser_port
    assert m["host_permissions"] == [f"http://127.0.0.1:{port}/*"]
    assert f"127.0.0.1:{port}/browser/page" in (d / "background.js").read_text(encoding="utf-8")
    assert m["incognito"] == "not_allowed" and set(m["permissions"]) == {"tabs", "alarms"}
    assert len(m["description"]) <= 132


def test_api_timezone_and_extension_install(monkeypatch, tmp_path):
    import awy.core as core_mod
    monkeypatch.setattr(core_mod.ServerThread, "start", lambda self: None)
    from starlette.testclient import TestClient

    from awy.core import Core
    from awy.webapi import WebApi
    core = Core()
    api = WebApi(core, "k", 48996)
    c = TestClient(api.app, base_url="http://127.0.0.1:48996")
    c.headers.update({"X-AWY-Token": "k"})
    try:
        assert c.post("/api/settings", json={"timezone": "Mars/Olympus"}).status_code == 400
        c.post("/api/settings", json={"timezone": "Europe/London"})
        assert c.get("/api/status").json()["timezone"] == "Europe/London" and clock.zone_name() == "Europe/London"
        assert any(z["id"] == "Asia/Shanghai" and z["offset"] == "+0800" for z in c.get("/api/timezones").json())
        api.pick_folder = lambda: None
        assert c.post("/api/browser/install").json() == {"cancelled": True}
        monkeypatch.setattr("awy.export.reveal", lambda f: None)
        api.pick_folder = lambda: str(tmp_path)
        r = c.post("/api/browser/install").json()
        assert (tmp_path / "AlwaysWithYou-browser-extension" / "manifest.json").exists() and r["path"]
        assert c.get("/api/browser/status").json()["connected"] is False
    finally:
        core.store.close()
