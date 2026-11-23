"""0.3.0 复查（ChatGPT 第二轮）的 5 条：存档换到一半退出、关掉聊天整理后仍发聊天、导出漏打码名字和别名、
异常聊天文件、保留天数乱填。外加首页时间线顺序的偏好。全部在临时数据目录里跑，不碰真实数据。"""

import json
import sqlite3
import zipfile
from datetime import timedelta

import pytest

from awy import clock, library, paths
from awy.memory.store import MemoryStore

TOKEN = "tok"


def _facts() -> int:
    s = MemoryStore(paths.memory_db())
    try:
        return len(s.current_facts())
    finally:
        s.close()


def _library(n: int, chat_day: str | None) -> None:
    """当前记忆库换成 n 条事实；chat_day 不为空时只留这一天的聊天文件。"""
    for f in [paths.memory_db(), *(paths.data_dir() / f"memory.db{x}" for x in ("-wal", "-shm"))]:
        f.unlink(missing_ok=True)
    for f in paths.chats_dir().glob("*.jsonl"):
        f.unlink()
    s = MemoryStore(paths.memory_db())
    for i in range(n):
        s.add_fact(f"用户喜欢第{i}种茶", actor="test", category="preference", speaker="user")
    s.close()
    if chat_day:
        (paths.chats_dir() / f"{chat_day}.jsonl").write_text(
            json.dumps({"ts": f"{chat_day}T10:00:00+08:00", "role": "me", "text": f"{chat_day} 的聊天"},
                       ensure_ascii=False) + "\n", encoding="utf-8")


def _archive(tmp_path, n: int, chat_day: str | None) -> str:
    """做一个 n 条事实的存档放进「记忆存档」，返回存档名。"""
    _library(n, chat_day)
    z = tmp_path / f"lib{n}.zip"
    library.build_zip(z, paths.memory_db(), kind="backup")
    return library.import_archive(z)["name"]


def _chat_days() -> set[str]:
    return {f.stem for f in paths.chats_dir().glob("*.jsonl")}


def _interrupt_after_db(name: str, *, copy_chats: bool) -> str:
    """模拟「启用存档」换到一半程序退出：备份 → 标记 swapping → 记忆库换好了 → 聊天删掉了（copy_chats 时也复制完了），然后断电。"""
    backup = library.backup_current()
    library._write_pending(paths.data_dir() / library.PENDING_FILE, backup.name, name, "swapping")
    stage = paths.data_dir() / "stage-test"
    db, chats, _ = library._stage(library.archive_path(name), stage)
    library._swap_in(db, chats if copy_chats else [])
    if not copy_chats:
        for f in paths.chats_dir().glob("*.jsonl"):
            f.unlink()       # 旧聊天删掉了，新聊天还没复制进来
    return backup.name


# ---- 1 启用存档换到一半退出 ------------------------------------------------------------------
def test_startup_restores_when_switch_was_interrupted_even_if_new_db_opens(tmp_path):
    name = _archive(tmp_path, 1, "2026-11-20")
    _library(5, "2026-11-19")
    _interrupt_after_db(name, copy_chats=False)
    assert _facts() == 1 and _chat_days() == set()        # 新库能打开，聊天却没了：以前会就这么用下去
    from awy.core import Core
    core = Core()
    try:
        assert len(core.store.current_facts()) == 5      # 换回了原来的记忆库……
        assert _chat_days() == {"2026-11-19"}            # ……和原来的聊天
        assert core.startup_notices and "自动换回" in core.startup_notices[0]
    finally:
        core.stop()
        core.store.close()
    assert not (paths.data_dir() / library.PENDING_FILE).exists()


def test_restore_puts_back_exact_chats_even_if_backup_had_none(tmp_path):
    name = _archive(tmp_path, 1, "2026-11-20")
    _library(5, None)                                     # 原来没有聊天
    _interrupt_after_db(name, copy_chats=True)            # 存档的聊天都复制完了，只差改标记
    assert _chat_days() == {"2026-11-20"}
    assert library.recover_interrupted_enable()
    assert _facts() == 5 and _chat_days() == set()        # 不留下存档的聊天


def test_finished_switch_is_not_undone_on_startup(tmp_path):
    name = _archive(tmp_path, 1, "2026-11-20")
    _library(5, "2026-11-19")
    library.enable_archive(name)
    p = json.loads((paths.data_dir() / library.PENDING_FILE).read_text(encoding="utf-8"))
    assert p["stage"] == "swapped"
    assert library.recover_interrupted_enable() is None
    assert _facts() == 1 and _chat_days() == {"2026-11-20"}
    assert library.enable_finished() == 0
    assert not (paths.data_dir() / library.PENDING_FILE).exists()


def test_old_pending_without_stage_keeps_old_behaviour(tmp_path):
    """旧版本写的标记（没有 stage）：库能打开就不动它（升级前刚启用成功、还没重启的情况）。"""
    _library(3, None)
    backup = library.backup_current()
    _library(2, None)
    (paths.data_dir() / library.PENDING_FILE).write_text(json.dumps({"backup": backup.name}), encoding="utf-8")
    assert library.recover_interrupted_enable() is None
    assert _facts() == 2


def test_failed_rollback_says_so_and_keeps_marker(tmp_path, monkeypatch):
    name = _archive(tmp_path, 1, "2026-11-20")
    _library(5, "2026-11-19")

    def broken(db, chats, **kw):
        raise OSError("磁盘坏了")
    monkeypatch.setattr(library, "_swap_in", broken)
    with pytest.raises(library.LibraryError) as e:
        library.enable_archive(name)
    assert "没成功" in str(e.value) and "已经换回" not in str(e.value)
    p = json.loads((paths.data_dir() / library.PENDING_FILE).read_text(encoding="utf-8"))
    assert p["stage"] == "swapping"                       # 下次启动还会再试


# ---- 2 关掉「聊天内容参与整理」 --------------------------------------------------------------
def _chat(ts, text: str, role: str = "me") -> None:
    from awy import chat
    with chat._chat_file(clock.to_local(ts).date()).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts.isoformat(timespec="seconds"), "role": role, "text": text, "brain": "deepseek"},
                           ensure_ascii=False) + "\n")


def test_turning_chat_off_drops_queued_chat_episodes(store):
    from awy import pipeline
    from awy.config import Settings
    from awy.ops import WriteOps
    s = Settings()
    now = clock.now()
    _chat(now - timedelta(minutes=10), "排队中的一句悄悄话")
    assert pipeline.make_chat_episode(store, now, s)      # 整理失败等原因，这份一直在排队
    s.chat_in_memory = False
    assert pipeline.make_chat_episode(store, now + timedelta(minutes=5), s) is None
    assert not [e for e in store.pending_episodes() if e["source"] == "chat"]
    assert "悄悄话" not in WriteOps(store, "test").list_pending()   # 整理 AI 看不到


def test_turning_chat_off_in_settings_skips_queue_immediately():
    from awy import pipeline
    from awy.core import Core
    core = Core()
    try:
        now = clock.now()
        _chat(now - timedelta(minutes=10), "排队中的一句悄悄话")
        assert pipeline.make_chat_episode(core.store, now, core.settings)
        core.update_settings(chat_in_memory=False)
        assert not [e for e in core.store.pending_episodes() if e["source"] == "chat"]
        assert core.settings.chat_in_memory_since == ""
        core.update_settings(chat_in_memory=True)
        assert core.settings.chat_in_memory_since          # 记下重新打开的时间
    finally:
        core.stop()
        core.store.close()


def test_reenabling_chat_does_not_backfill_the_off_period(store):
    from awy import pipeline
    from awy.config import Settings
    s = Settings()
    now = clock.now()
    _chat(now - timedelta(hours=5, minutes=30), "开关打开时说的")
    assert pipeline.make_chat_episode(store, now - timedelta(hours=5), s)
    store.mark_processed([e["id"] for e in store.pending_episodes()], [], "test")
    _chat(now - timedelta(hours=3), "开关关着时说的秘密")
    _chat(now - timedelta(minutes=20), "重新打开后说的")
    s.chat_in_memory_since = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    eid = pipeline.make_chat_episode(store, now, s)
    ep = next(e for e in store.pending_episodes() if e["id"] == eid)
    assert "重新打开后说的" in ep["content"] and "秘密" not in ep["content"]


# ---- 3 导出：人物 / 地点 / 项目的名字和别名 --------------------------------------------------
def test_export_masks_entity_names_and_aliases(tmp_path):
    phone, phone2, key = "13812345678", "13987654321", "sk-abcdef1234567890abcdef12"
    s = MemoryStore(paths.memory_db())
    s.upsert_entity(f"王老师 {phone}", kind="person", aliases=[key, "老王"], actor="test")
    s.upsert_entity(f"王老师 {phone2}", kind="person", actor="test")   # 打码后会和上一个重名
    s.add_fact("用户今天去找王老师", actor="test", category="event", speaker="user", subject=f"王老师 {phone}")
    s.close()
    dest = tmp_path / "out.zip"
    library.build_zip(dest, paths.memory_db())
    with zipfile.ZipFile(dest) as z:
        for n in z.namelist():
            data = z.read(n)
            for secret in (phone, phone2, key):
                assert secret.encode() not in data, (n, secret)
        md = z.read("记忆.md").decode("utf-8")
        assert "王老师 [已隐藏]" in md and "老王" in md
        z.extract("memory.db", tmp_path / "x")
    con = sqlite3.connect(tmp_path / "x" / "memory.db")
    names = [r[0] for r in con.execute("SELECT name FROM entities ORDER BY id")]
    aliases = {r[0] for r in con.execute("SELECT alias FROM aliases")}
    con.close()
    assert len(set(names)) == 2 and all("[已隐藏]" in n for n in names)
    assert "老王" in aliases and not any("[已隐藏]" in a for a in aliases)


# 每个文字列都要归类：要么导出时打码，要么是程序自己填的（时间、类别、编号……）。新加列时这里会报错提醒。
MASKED = {("entities", "name"), ("entities", "note"), ("aliases", "alias"), ("episodes", "content"),
          ("facts", "text"), ("facts", "invalid_reason"), ("persona", "content"), ("persona", "reason"),
          ("inbox", "content"), ("inbox", "result"), ("audit", "detail")}
NOT_FREE_TEXT = {("meta", "key"), ("meta", "value"), ("entities", "kind"), ("entities", "created_at"),
                 ("episodes", "source"), ("episodes", "period_start"), ("episodes", "period_end"),
                 ("episodes", "created_at"), ("episodes", "processed_at"), ("episodes", "processed_by"),
                 ("facts", "category"), ("facts", "valid_at"), ("facts", "invalid_at"), ("facts", "created_at"),
                 ("facts", "retracted_at"), ("facts", "source"), ("facts", "last_recalled_at"), ("facts", "speaker"),
                 ("facts", "embed_model"), ("persona", "source"), ("persona", "created_at"), ("inbox", "kind"),
                 ("inbox", "source"), ("inbox", "created_at"), ("inbox", "processed_at"), ("audit", "at"),
                 ("audit", "actor"), ("audit", "action"), ("audit", "target"), ("audit", "undone_at")}


def test_every_text_column_is_classified_for_export_masking():
    s = MemoryStore(paths.memory_db())
    try:
        cols = {(tb, r[1]) for (tb,) in s._db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'facts_fts%'")
                for r in s._db.execute(f"PRAGMA table_info({tb})") if r[2].upper() == "TEXT"}
    finally:
        s.close()
    assert cols - MASKED - NOT_FREE_TEXT == set(), "新的文字列：决定导出时要不要打码（library.scrub_db），再加进这里"


# ---- 4 存档里的异常聊天文件 ------------------------------------------------------------------
def test_enable_drops_unreadable_chat_lines(tmp_path):
    _library(1, None)
    good = tmp_path / "good.zip"
    library.build_zip(good, paths.memory_db(), kind="backup")
    bad = tmp_path / "bad.zip"
    ok_line = json.dumps({"ts": "2026-11-20T10:00:00+08:00", "role": "me", "text": "正常的一句"}, ensure_ascii=False)
    lines = [ok_line.encode("utf-8"),
             "乱码".encode("gbk") + b'{"ts": 1}',                                         # 编码不对
             b'["not", "a", "record"]',                                                   # 不是一条记录
             json.dumps({"ts": "2026-11-20T10:00:00", "role": "me", "text": "x"}).encode(),  # 时间没有时区
             json.dumps({"ts": "2026-11-20T11:00:00+08:00", "role": "me", "text": 5}).encode()]   # 文字不是字符串
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(bad, "w") as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i))
        zout.writestr("聊天记录/2026-11-20.jsonl", b"\n".join(lines) + b"\n")
    name = library.import_archive(bad)["name"]
    _library(3, None)
    library.enable_archive(name)
    text = (paths.chats_dir() / "2026-11-20.jsonl").read_text(encoding="utf-8")
    assert "正常的一句" in text and len(text.strip().splitlines()) == 1
    assert library.enable_finished() == 4                 # 启动后会提醒「跳过了 4 行」


def test_broken_local_chat_file_does_not_break_chat_page_or_organizing(store):
    from awy import chat, pipeline
    from awy.config import Settings
    now = clock.now()
    f = chat._chat_file(clock.today())
    f.write_bytes("乱码".encode("gbk") + b"\n" + b'["x"]\n' + b'{"ts": 5, "role": "me", "text": "x"}\n')
    _chat(now - timedelta(minutes=5), "这句是好的")
    page = chat.load_page()
    assert [r["text"] for r in page["items"]] == ["这句是好的"]
    assert [r["text"] for r in chat.load_history()] == ["这句是好的"]
    eid = pipeline.make_chat_episode(store, now, Settings())
    assert "这句是好的" in next(e for e in store.pending_episodes() if e["id"] == eid)["content"]


# ---- 5 原始记录保留天数 ----------------------------------------------------------------------
@pytest.fixture
def api():
    from starlette.testclient import TestClient
    from awy.core import Core
    from awy.webapi import WebApi
    core = Core()
    c = TestClient(WebApi(core, TOKEN, 50123).app, base_url="http://127.0.0.1:50123")
    yield core, c
    core.stop()
    core.store.close()


@pytest.mark.parametrize("bad", [0, -1, 3651, 10 ** 9, "30", True, 30.5, None])
def test_settings_reject_bad_retention(api, bad):
    core, c = api
    r = c.post("/api/settings", json={"raw_retention_days": bad}, headers={"X-AWY-Token": TOKEN})
    assert r.status_code == 400 and core.settings.raw_retention_days == 30


def test_settings_accept_max_retention(api):
    core, c = api
    r = c.post("/api/settings", json={"raw_retention_days": 3650}, headers={"X-AWY-Token": TOKEN})
    assert r.status_code == 200 and core.settings.raw_retention_days == 3650


def _raw_day(offset: int):
    d = paths.data_dir() / "raw" / (clock.today() + timedelta(days=offset)).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("{}\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("days", [0, -5, 10 ** 9, "abc", None])
def test_prune_never_deletes_today_or_crashes(days):
    from awy import rawlog
    today, yesterday = _raw_day(0), _raw_day(-1)
    rawlog.prune(days)                                    # 以前：0 / 负数删掉今天的，太大直接报错
    assert today.exists() and yesterday.exists()


def test_scheduler_thread_survives_bad_retention(store):
    from awy.config import Settings
    from awy.pipeline import Scheduler
    today = _raw_day(0)                                   # 有原始记录才会真的去算截止日期
    s = Settings()
    s.raw_retention_days = 10 ** 9                        # 绕过界面直接塞进来
    sch = Scheduler(store, lambda: s)
    assert sch.prune_daily() == []                        # 不抛异常，线程不会退出
    assert today.exists()
    sch._pruned_day = None
    s.raw_retention_days = {"坏": "值"}                   # 什么奇怪的值都不能让它抛出来
    assert sch.prune_daily() == []


def test_config_file_with_bad_retention_is_cleaned(tmp_path):
    from awy import config
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"raw_retention_days": -3}), encoding="utf-8")
    assert config.load(f).raw_retention_days == 1
    f.write_text(json.dumps({"raw_retention_days": "很多"}), encoding="utf-8")
    assert config.load(f).raw_retention_days == 30


# ---- 首页时间线顺序 --------------------------------------------------------------------------
def test_timeline_order_pref_only_accepts_desc(api):
    _, c = api
    h = {"X-AWY-Token": TOKEN}
    assert c.post("/api/prefs/tlorder", json={"value": "<script>"}, headers=h).status_code == 400
    assert c.post("/api/prefs/tlorder", json={"value": "desc"}, headers=h).status_code == 200
    assert c.get("/api/prefs", headers=h).json()["tlorder"] == "desc"
    assert c.delete("/api/prefs/tlorder", headers=h).status_code == 200
    assert "tlorder" not in c.get("/api/prefs", headers=h).json()
