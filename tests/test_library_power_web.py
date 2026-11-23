"""决定 0012：记忆库导出 / 存档 / 搬家、电脑睡眠与关机、「记住」便条核对、联网放行。"""

import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from awy import library, paths, power
from awy.memory.store import MemoryStore

U = timezone.utc


def _make_library(n=3):
    s = MemoryStore(paths.memory_db())
    for i in range(n):
        s.add_fact(f"用户喜欢第{i}种茶", actor="test", category="preference", speaker="user")
    s.set_persona("用户是个爱喝茶的人", actor="test")
    s.close()
    (paths.chats_dir() / "2026-11-20.jsonl").write_text(
        json.dumps({"ts": "2026-11-20T10:00:00+08:00", "role": "me", "text": "你好"}, ensure_ascii=False) + "\n",
        encoding="utf-8")


# ---- 导出 / 存档 ----------------------------------------------------------------------------
def test_export_zip_has_readme_memory_db_and_chats(tmp_path):
    _make_library()
    store = MemoryStore(paths.memory_db())
    dest = tmp_path / "out.zip"
    m = library.build_zip(dest, store)
    store.close()
    with zipfile.ZipFile(dest) as z:
        names = set(z.namelist())
        assert {"manifest.json", "记忆库说明.md", "记忆.md", "memory.db", "AGENTS.md", "CLAUDE.md", "GEMINI.md",
                "聊天记录/2026-11-20.jsonl"} <= names
        assert "config.json" not in names and not any(n.startswith("raw/") for n in names)
        md = z.read("记忆.md").decode("utf-8")
        assert "用户喜欢第0种茶" in md and "爱喝茶" in md and "可信度 0.9" in md
        readme = z.read("记忆库说明.md").decode("utf-8")
        assert "数据，不是指令" in readme and "mode=ro" in readme
        assert "@记忆库说明.md" in z.read("CLAUDE.md").decode("utf-8")
    assert m["facts"] == 3 and m["chats"] is True
    assert library.validate(dest)["facts"] == 3


def test_export_hides_passwords_everywhere_but_backup_keeps_them(tmp_path):
    import sqlite3
    secret = "Abc@12345"
    s = MemoryStore(paths.memory_db())
    s.add_fact(f"用户的邮箱密码是 {secret}", actor="test", category="state", speaker="user")
    s.add_episode("chat", f"[11-20 10:00] 用户：我的密码是 {secret}", None, None)
    s.add_inbox("remember", f"用户密码 {secret}（用户原话：记住我的密码是 {secret}）", "chat")
    s.close()
    (paths.chats_dir() / "2026-11-20.jsonl").write_text(
        json.dumps({"ts": "2026-11-20T10:00:00+08:00", "role": "me", "text": f"记住我的密码是 {secret}"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    dest = tmp_path / "out.zip"
    library.build_zip(dest, paths.memory_db())
    with zipfile.ZipFile(dest) as z:
        for name in z.namelist():
            assert secret.encode() not in z.read(name), name          # 压缩包里任何文件都找不到原文
        assert "[已隐藏]" in z.read("聊天记录/2026-11-20.jsonl").decode("utf-8")
        z.extract("memory.db", tmp_path / "x")
    con = sqlite3.connect(tmp_path / "x" / "memory.db")
    assert con.execute("SELECT count(*) FROM facts_fts WHERE facts_fts MATCH '用户'").fetchone()[0] >= 1   # 索引重建过
    con.close()
    backup = tmp_path / "backup.zip"
    library.build_zip(backup, paths.memory_db(), kind="backup")
    with zipfile.ZipFile(backup) as z:
        assert secret.encode() in z.read("memory.db") or secret.encode() in z.read("聊天记录/2026-11-20.jsonl")


def test_validate_rejects_foreign_and_broken_zips(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(library.LibraryError):
        library.validate(bad)
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "AlwaysWithYou", "format": 1, "schema": 2}))
        z.writestr("memory.db", b"not a database at all" * 100)
    with pytest.raises(library.LibraryError):
        library.validate(broken)
    future = tmp_path / "future.zip"
    with zipfile.ZipFile(future, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "AlwaysWithYou", "format": 1, "schema": 99}))
        z.writestr("memory.db", b"")
    with pytest.raises(library.LibraryError):
        library.validate(future)


def test_import_then_enable_backs_up_current(tmp_path):
    # 另一份记忆库（只有 1 条）打成压缩包
    _make_library(1)
    other = tmp_path / "other.zip"
    library.build_zip(other, paths.memory_db())
    (paths.chats_dir() / "2026-11-20.jsonl").unlink()
    # 当前记忆库换成 5 条
    paths.memory_db().unlink()
    _make_library(5)
    r = library.import_archive(other)
    assert r["facts"] == 1 and (paths.archives_dir() / r["name"]).exists()
    with pytest.raises(library.LibraryError):
        library.archive_path("../config.json")
    backup = library.enable_archive(r["name"])
    s = MemoryStore(paths.memory_db())
    assert len(s.current_facts()) == 1
    s.close()
    names = [a["name"] for a in library.list_archives()]
    assert backup in names and r["name"] in names
    assert library.validate(paths.archives_dir() / backup)["facts"] == 5
    # 存档里的聊天记录也一起换过来
    assert (paths.chats_dir() / "2026-11-20.jsonl").exists()


# ---- 搬家 ----------------------------------------------------------------------------------
@pytest.fixture
def movable(tmp_path, monkeypatch):
    default = tmp_path / "default"
    default.mkdir()
    monkeypatch.setattr(paths, "can_move", lambda: True)
    monkeypatch.setattr(paths, "default_dir", lambda: default)
    paths.reload()
    yield default
    paths.reload()


def test_move_copies_verifies_and_only_deletes_our_own_files(movable, tmp_path):
    _make_library()
    (paths.data_dir() / "raw" / "2026-11-20").mkdir(parents=True)
    (paths.data_dir() / "raw" / "2026-11-20" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    marker_outside = tmp_path / "别的东西.txt"   # 标记文件：在旧位置外面，绝不能被删
    marker_outside.write_text("keep", encoding="utf-8")
    target_parent = tmp_path / "D盘"
    target_parent.mkdir()
    (target_parent / "用户自己的文件.txt").write_text("keep", encoding="utf-8")   # 不空 → 建子文件夹

    dest = library.plan_move(target_parent)
    assert dest == target_parent / "AlwaysWithYou"
    library.move_data(dest)

    assert paths.data_dir() == dest.resolve()
    assert (dest / "memory.db").exists() and (dest / "raw" / "2026-11-20" / "events.jsonl").exists()
    assert (dest / "chats" / "2026-11-20.jsonl").exists()
    left = {p.name for p in movable.iterdir()}
    assert left == {"location.json", "location.txt"}   # 默认位置只留指路文件
    assert (movable / "location.txt").read_text(encoding="utf-8-sig") == str(dest.resolve())
    assert marker_outside.read_text(encoding="utf-8") == "keep"
    assert (target_parent / "用户自己的文件.txt").read_text(encoding="utf-8") == "keep"
    s = MemoryStore(paths.memory_db())
    assert len(s.current_facts()) == 3
    s.close()

    # 再搬回默认位置
    back = library.plan_move(movable)
    library.move_data(back)
    assert paths.data_dir() == movable
    assert (movable / "memory.db").exists() and not (movable / "location.txt").exists()
    assert not dest.exists()                      # 搬空了的旧文件夹删掉
    assert (target_parent / "用户自己的文件.txt").exists()


def test_move_always_uses_a_folder_named_alwayswithyou(movable, tmp_path):
    _make_library()
    empty = tmp_path / "空盘"
    empty.mkdir()
    assert library.plan_move(empty) == empty / "AlwaysWithYou"     # 选了空文件夹也建子文件夹
    named = tmp_path / "x" / "AlwaysWithYou"
    named.mkdir(parents=True)
    assert library.plan_move(named) == named


def test_move_refuses_bad_targets(movable, tmp_path):
    _make_library()
    with pytest.raises(library.LibraryError):
        library.plan_move(paths.data_dir() / "chats")          # 搬进自己里面
    with pytest.raises(library.LibraryError):
        library.plan_move(tmp_path / "不存在")
    busy = tmp_path / "busy"
    (busy / "AlwaysWithYou").mkdir(parents=True)
    (busy / "AlwaysWithYou" / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(library.LibraryError):
        library.plan_move(busy)


def test_folder_readme_follows_language(data_dir):
    from awy import i18n
    f = library.write_folder_readme()
    assert f.name == "记忆库说明.md" and "config.json" in f.read_text(encoding="utf-8")
    i18n.set_lang("en")
    try:
        f2 = library.write_folder_readme()
        assert f2.name == "MEMORY-README.md" and not f.exists()
    finally:
        i18n.set_lang("zh")


# ---- 电脑睡眠 / 关机 -----------------------------------------------------------------------
def _t(h, m, s=0):
    return datetime(2026, 11, 21, h, m, s, tzinfo=U)


def test_sleep_periods_merge_fake_wakes():
    ev = [(_t(1, 0), "Kernel-Power", 506), (_t(2, 0), "Kernel-Power", 507),
          (_t(2, 0, 30), "Kernel-Power", 506), (_t(3, 0), "Kernel-Power", 507),   # 醒了 30 秒：假醒
          (_t(4, 0), "Kernel-Power", 42), (_t(5, 0), "Kernel-Power", 107)]
    assert power.sleep_periods(ev) == [(_t(1, 0), _t(3, 0)), (_t(4, 0), _t(5, 0))]


def test_refine_gap_uses_event_log_times():
    ev = [(_t(8, 50, 30), "Kernel-Power", 506), (_t(10, 40, 4), "Kernel-Power", 507)]
    assert power.refine_gap(_t(8, 50, 36), _t(10, 40, 9), ev) == (_t(8, 50, 30), _t(10, 40, 4))
    assert power.refine_gap(_t(8, 50, 36), _t(10, 40, 9), []) == (_t(8, 50, 36), _t(10, 40, 9))


def test_parse_wevtutil_xml():
    xml = ("<Event xmlns='x'><System><Provider Name='Microsoft-Windows-Kernel-Power' Guid='{1}'/>"
           "<EventID>506</EventID><TimeCreated SystemTime='2026-11-21T08:50:36.5424450Z'/>"
           "<EventRecordID>7</EventRecordID></System></Event>"
           "<Event xmlns='x'><System><Provider Name='Microsoft-Windows-Kernel-General'/><EventID>1</EventID>"
           "<TimeCreated SystemTime='2026-11-21T08:51:00.0Z'/></System></Event>")
    out = power.parse_events(xml)
    assert out == [(datetime(2026, 11, 21, 8, 50, 36, 542445, tzinfo=U), "Kernel-Power", 506)]


def test_collector_writes_sleep_and_shutdown():
    from awy.collect_pc import PcCollector
    from awy.config import Settings
    s = Settings()
    got: list[dict] = []
    wall = {"now": _t(9, 0)}
    c = PcCollector(lambda: s, probe=lambda: ("code.exe", "a.py"), idle=lambda: 0, sink=got.append,
                    power_watch=True, wallclock=lambda: wall["now"],
                    read_power=lambda a, b: [(_t(9, 0, 3), "Kernel-Power", 506), (_t(11, 0), "Kernel-Power", 507)],
                    boot=lambda: _t(8, 0),
                    last_state=lambda t: {"ts": _t(7, 0).isoformat(), "type": "window", "app": "x"})
    c.tick()   # 启动：上一条记录 7:00 早于开机 8:00 → 关机
    assert [(e["type"], e.get("reason")) for e in got[:2]] == [("away", "shutdown"), ("back", "shutdown")]
    got.clear()
    wall["now"] = _t(9, 0, 5)
    c.tick()
    assert got == []           # 正常间隔，同一窗口不重复写
    wall["now"] = _t(11, 0, 6)
    c.tick()                    # 隔了 2 小时 → 睡眠，时间按系统日志校准
    kinds = [(e["type"], e.get("reason")) for e in got]
    assert kinds[:2] == [("away", "sleep"), ("back", "sleep")] and kinds[2][0] == "window"
    assert datetime.fromisoformat(got[0]["ts"]) == _t(9, 0, 3).replace(microsecond=0)
    assert datetime.fromisoformat(got[1]["ts"]) == _t(11, 0)


def test_summary_counts_sleep_as_away_and_drops_stale_windows():
    from awy import summarize
    iso = lambda d: d.isoformat()   # noqa: E731
    events = [{"ts": iso(_t(9, 0)), "type": "window", "app": "code.exe", "title": "a"},
              {"ts": iso(_t(9, 10)), "type": "away", "reason": "sleep"},
              {"ts": iso(_t(9, 10, 2)), "type": "window", "app": "explorer.exe", "title": ""},   # 屏幕黑前的残留
              {"ts": iso(_t(10, 0)), "type": "back", "reason": "sleep"},
              {"ts": iso(_t(10, 0, 20)), "type": "away", "reason": "sleep"},                    # 假醒 20 秒
              {"ts": iso(_t(11, 0)), "type": "back", "reason": "sleep"},
              {"ts": iso(_t(11, 0, 1)), "type": "window", "app": "code.exe", "title": "a"}]
    segs, away = summarize.build_segments(events, _t(9, 0), _t(11, 30))
    assert away == 110 * 60
    assert {sg.app for sg in segs} == {"code.exe"}
    assert summarize.power_periods(events, _t(9, 0), _t(11, 30)) == [(_t(9, 10), _t(11, 0), "sleep")]
    text = summarize.render(events, _t(9, 0), _t(11, 30))
    assert "电脑睡眠" in text and "1 小时 50 分" in text


# ---- 「记住」便条核对 ----------------------------------------------------------------------
def test_remember_note_must_come_from_user(store):
    from awy.config import Settings
    from awy.ops import ReadOps
    ops = ReadOps(store, Settings())
    ops.user_said = "今天好累啊"
    msg = ops.leave_note("remember", "用户今天很累")
    assert "普通便条" in msg and store.pending_inbox()[-1]["kind"] == "note"
    assert "用户原话：今天好累啊" in store.pending_inbox()[-1]["content"]
    ops.user_said = "记住，我下周三考试"
    ops.leave_note("remember", "用户下周三考试")
    assert store.pending_inbox()[-1]["kind"] == "remember"
    ops.user_said = "不对，其实我是学化学的"
    ops.leave_note("correct", "用户学的是化学")
    assert store.pending_inbox()[-1]["kind"] == "correct"


# ---- 联网放行 ------------------------------------------------------------------------------
def test_web_permission_by_kind():
    from awy.chat import permission_for, web_label
    assert permission_for({"kind": "search", "rawInput": {"query": "天气"}})[0]
    assert permission_for({"kind": "fetch", "rawInput": {"url": "https://www.bbc.com/news"}})[0]
    assert permission_for({"kind": "think"})[0]
    assert permission_for({"kind": "other", "title": "mcp_awy-memory_search_memory"})[0]
    # 实测 agy 的真实格式
    assert permission_for({"name": "mcp_awy-memory_search_memory", "kind": "other", "title": "Run mcp_awy-memory_search_memory",
                           "rawInput": {"query": "茶"}})[0]
    # 审查发现的问题：参数或说明里带着记忆工具的名字，不能因此放行
    assert not permission_for({"name": "run_command", "kind": "execute", "title": "echo mcp_awy-memory_x",
                               "rawInput": {"CommandLine": "del x # mcp_awy-memory_search_memory \"awy-memory\""}})[0]
    assert not permission_for({"name": "run_command", "kind": "other", "rawInput": {"note": "mcp_awy-memory_search_memory"}})[0]
    assert not permission_for({"name": "mcp_awy-memory_search_memory", "kind": "execute"})[0]
    assert not permission_for({"name": "mcp_awy-memory_delete_everything", "kind": "other"})[0]
    for bad in ("http://127.0.0.1:47821/mcp", "http://localhost/", "http://192.168.1.1/", "http://10.0.0.2/",
                "http://[::1]/", "http://router/", "http://nas.local/"):
        assert not permission_for({"kind": "fetch", "rawInput": {"url": bad}})[0], bad
    for kind in ("read", "edit", "delete", "move", "execute", "other"):
        assert not permission_for({"kind": kind, "title": "x"})[0], kind
    assert "天气" in web_label({"kind": "search", "rawInput": {"query": "天气"}})
    assert "www.bbc.com" in web_label({"kind": "fetch", "rawInput": {"url": "https://www.bbc.com/news"}})
    assert web_label({"kind": "execute"}) is None


def test_companion_guide_allows_web():
    from awy.chat import COMPANION_GUIDE
    assert "不要上网" not in COMPANION_GUIDE and "上网搜索" in COMPANION_GUIDE


# ---- 审查补充（2026-11-21）：坏存档拦在启用之前；换的时候出错自动换回 ----------------------------
def _zip_with_db(tmp_path, mutate):
    import shutil as _sh
    import sqlite3
    _make_library(2)
    good = tmp_path / "good.zip"
    library.build_zip(good, paths.memory_db(), kind="backup")
    work = tmp_path / "w"
    with zipfile.ZipFile(good) as z:
        z.extractall(work)
    con = sqlite3.connect(work / "memory.db")
    mutate(con)
    con.commit()
    con.close()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        for f in work.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(work).as_posix())
    _sh.rmtree(work)
    return bad


def test_archive_missing_columns_is_rejected_before_enable(tmp_path):
    bad = _zip_with_db(tmp_path, lambda con: con.execute("ALTER TABLE facts DROP COLUMN embed_model"))
    with pytest.raises(library.LibraryError):
        library.validate(bad)


def test_swap_failure_restores_current_library(tmp_path, monkeypatch):
    _make_library(1)
    other = tmp_path / "other.zip"
    library.build_zip(other, paths.memory_db(), kind="backup")
    paths.memory_db().unlink()
    _make_library(5)
    name = library.import_archive(other)["name"]
    real = library._swap_in
    calls = {"n": 0}

    def flaky(db, chats, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            real(db, [])               # 记忆库已经换了一半……
            raise OSError("磁盘满了")   # ……然后写聊天时出错
        return real(db, chats, **kw)
    monkeypatch.setattr(library, "_swap_in", flaky)
    with pytest.raises(library.LibraryError):
        library.enable_archive(name)
    s = MemoryStore(paths.memory_db())
    assert len(s.current_facts()) == 5          # 已经换回原来的
    s.close()
    assert not (paths.data_dir() / library.PENDING_FILE).exists()


def test_startup_recovers_when_enabled_library_cannot_open(tmp_path):
    _make_library(3)
    backup = library.backup_current()
    (paths.data_dir() / library.PENDING_FILE).write_text(json.dumps({"backup": backup.name}), encoding="utf-8")
    paths.memory_db().write_bytes(b"this is not sqlite" * 50)    # 模拟换上来的库打不开
    for suffix in ("-wal", "-shm"):
        (paths.data_dir() / f"memory.db{suffix}").unlink(missing_ok=True)
    assert library.recover_failed_enable() == backup.name
    s = MemoryStore(paths.memory_db())
    assert len(s.current_facts()) == 3
    s.close()


def test_no_organizing_before_terms_accepted(store):
    from awy.config import TERMS_VERSION, Settings
    from awy.pipeline import Scheduler
    s = Settings()
    got = []
    sch = Scheduler(store, lambda: s, got.append)
    assert "风险说明" in sch.run_now()       # 托盘「立即整理一次」也走这里
    assert store.pending_episodes() == []    # 没生成任何要交给 AI 的东西
    s.accepted_terms = TERMS_VERSION
    s.organizer = "none"
    assert "风险说明" not in sch.run_now()


def test_raw_records_pruned_even_without_organize_times(store, data_dir):
    from datetime import date
    from awy import clock
    from awy.config import Settings
    from awy.pipeline import Scheduler
    old = paths.data_dir() / "raw" / (clock.today().replace(year=clock.today().year - 1)).isoformat()
    old.mkdir(parents=True)
    (old / "events.jsonl").write_text("{}\n", encoding="utf-8")
    s = Settings()
    s.organize_times = []
    sch = Scheduler(store, lambda: s)
    assert old.name in sch.prune_daily()
    assert not old.exists()
    assert sch.prune_daily() == []           # 同一天不重复


def test_settings_reject_empty_organize_times():
    from starlette.testclient import TestClient
    from awy.core import Core
    from awy.webapi import WebApi
    core = Core()
    try:
        api = WebApi(core, "tok", 50123)
        c = TestClient(api.app, base_url="http://127.0.0.1:50123")
        r = c.post("/api/settings", json={"organize_times": []}, headers={"X-AWY-Token": "tok"})
        assert r.status_code == 400 and core.settings.organize_times
    finally:
        core.stop()
