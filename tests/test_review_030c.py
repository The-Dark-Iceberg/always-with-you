"""0.3.0 第三轮复查（ChatGPT）的 5 条：换回失败后接着用、下次换回覆盖新记录；换回漏掉大聊天文件；
关掉聊天整理时的时间差和普通便条；U+2028 之类的字符把聊天拆碎；打码后名字反复重名。全部在临时数据目录里跑。"""

import json
import sqlite3
import zipfile
from datetime import timedelta

import pytest

from awy import clock, library, paths
from awy.memory.store import MemoryStore
from tests.test_review_030b import _archive, _chat_days, _facts, _interrupt_after_db, _library


def _core():
    from awy.core import Core
    return Core()


def _close(core):
    core.stop()
    core.store.close()


# ---- 1 换回失败后接着用了一阵，下次换回前先另存 ---------------------------------------------
def test_failed_startup_restore_then_retry_keeps_what_was_recorded_meanwhile(tmp_path, monkeypatch):
    name = _archive(tmp_path, 1, "2026-11-20")
    _library(5, "2026-11-19")
    _interrupt_after_db(name, copy_chats=False)

    real = library.restore_archive
    monkeypatch.setattr(library, "restore_archive", lambda n: (_ for _ in ()).throw(OSError("文件被占用")))
    core = _core()                                        # 第一次启动：换回失败，接着用当前（换了一半）的库
    try:
        assert any("没有成功" in m for m in core.startup_notices)
        core.store.add_fact("换回失败后新记下的事", actor="test", category="event", speaker="user")
    finally:
        _close(core)
    (paths.chats_dir() / "2026-11-21.jsonl").write_text(
        json.dumps({"ts": "2026-11-21T09:00:00+08:00", "role": "me", "text": "这段时间的聊天"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    p = json.loads((paths.data_dir() / library.PENDING_FILE).read_text(encoding="utf-8"))
    assert p["stage"] == "swapping" and p["retry"] is True

    monkeypatch.setattr(library, "restore_archive", real)
    before = {a["name"] for a in library.list_archives()}
    core = _core()                                        # 第二次启动：换回成功
    try:
        assert len(core.store.current_facts()) == 5 and _chat_days() == {"2026-11-19"}
        assert any("另存" in m for m in core.startup_notices)
    finally:
        _close(core)
    saved = ({a["name"] for a in library.list_archives()} - before).pop()
    with zipfile.ZipFile(paths.archives_dir() / saved) as z:   # 换回之前那段时间的东西都在另存的包里
        assert "这段时间的聊天" in z.read("聊天记录/2026-11-21.jsonl").decode("utf-8")
        z.extract("memory.db", tmp_path / "saved")
    con = sqlite3.connect(tmp_path / "saved" / "memory.db")
    assert con.execute("SELECT count(*) FROM facts WHERE text='换回失败后新记下的事'").fetchone()[0] == 1
    con.close()


# ---- 2 换回自动备份：聊天文件不限大小、原样换回、少了就报错 ----------------------------------
def test_restore_keeps_big_chat_files_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "MAX_CHAT_BYTES", 10)   # 让普通聊天文件都算「太大」
    name = _archive(tmp_path, 1, None)
    _library(5, "2026-11-19")
    original = (paths.chats_dir() / "2026-11-19.jsonl").read_bytes()
    _interrupt_after_db(name, copy_chats=False)
    assert library.recover_interrupted_enable()
    assert (paths.chats_dir() / "2026-11-19.jsonl").read_bytes() == original


def test_restore_refuses_backup_missing_chat_days(tmp_path):
    _library(2, "2026-11-19")
    backup = library.backup_current()
    broken = paths.archives_dir() / "broken-backup.zip"
    with zipfile.ZipFile(paths.archives_dir() / backup.name) as zin, zipfile.ZipFile(broken, "w") as zout:
        for i in zin.infolist():
            if not i.filename.startswith("聊天记录/"):
                zout.writestr(i, zin.read(i))           # 清单写着 1 天，聊天文件却没了
    with pytest.raises(library.LibraryError):
        library.restore_archive(broken.name)
    assert _chat_days() == {"2026-11-19"}                 # 没动当前的聊天


# ---- 3 关掉聊天整理：时间差、普通便条 --------------------------------------------------------
def test_organizer_never_sees_chat_while_switch_is_off(store):
    from awy.ops import WriteOps
    store.add_episode("chat", "[11-21 10:00] 用户：一句悄悄话", None, None)
    store.add_episode("pc_summary", "- 在写代码", None, None)
    store.add_inbox("note", "用户好像很累\n（用户原话：今天加班到十点，悄悄话）", "chat")
    store.add_inbox("remember", "用户下周三考试\n（用户原话：记住我下周三考试）", "chat")
    on = {"v": True}
    ops = WriteOps(store, "test", chat_allowed=lambda: on["v"])
    assert "悄悄话" in ops.list_pending()
    on["v"] = False                                       # 整理到一半用户关掉：下一次列出来就没有了
    text = ops.list_pending()
    assert "悄悄话" not in text and "在写代码" in text and "下周三考试" in text


def test_switch_turned_off_while_chat_episode_is_being_made(store):
    from awy import pipeline
    from awy.config import TERMS_VERSION, Settings
    from awy.pipeline import Scheduler
    s = Settings()
    s.accepted_terms, s.organizer = TERMS_VERSION, "none"
    real = pipeline.make_chat_episode

    def racing(st, now, settings):
        st.add_episode("chat", "[10:00] 用户：开关关掉前读到的话", None, None)   # 已经读完聊天、正要存……
        settings.chat_in_memory = False                                        # ……这时用户关掉了开关
        pipeline.skip_pending_chat(st)                                          # 设置页那边的清理先跑完了
        return st.add_episode("chat", "[10:01] 用户：清理之后才存进去的话", None, None)
    pipeline.make_chat_episode = racing
    try:
        Scheduler(store, lambda: s).run_now()
    finally:
        pipeline.make_chat_episode = real
    assert not [e for e in store.pending_episodes() if e["source"] == "chat"]


def test_plain_notes_are_refused_when_chat_is_off_but_remember_still_works(store):
    from awy import pipeline
    from awy.config import Settings
    from awy.ops import ReadOps
    s = Settings()
    ops = ReadOps(store, s)
    ops.user_said = "今天加班到十点，好累"
    ops.leave_note("note", "用户最近加班多")              # 开着：照常收
    s.chat_in_memory = False
    assert "没有记下" in ops.leave_note("note", "用户很累")
    assert "没有记下" in ops.leave_note("remember", "用户很累")   # 没说「记住」→ 降成普通便条 → 不收
    ops.user_said = "记住我下周三考试"
    assert "收件箱" in ops.leave_note("remember", "用户下周三考试")
    assert pipeline.skip_pending_chat(store) == 1         # 开着时留的那张普通便条也跳过
    left = store.pending_inbox()
    assert [n["kind"] for n in left] == ["remember"] and "记住我下周三考试" in left[0]["content"]


# ---- 4 U+2028 这类字符 ----------------------------------------------------------------------
def test_line_separator_characters_do_not_split_chat_records(tmp_path):
    from awy import chat
    text = "从网页复制的一段 第二行 第三段\x85完"
    chat.append_history("me", text, "deepseek")
    raw = chat._chat_file(clock.today()).read_text(encoding="utf-8")
    assert " " not in raw and len(raw.splitlines()) == 1     # 写文件时转义掉，别的工具也不会拆错
    # 旧版本写下的文件里是原样的 U+2028：也要能读
    legacy = json.dumps({"ts": clock.now_iso(), "role": "ai", "text": "旧 记录"}, ensure_ascii=False)
    with chat._chat_file(clock.today()).open("a", encoding="utf-8") as f:
        f.write(legacy + "\n")
    assert [r["text"] for r in chat.load_page()["items"]] == [text, "旧 记录"]
    assert [r["text"] for r in chat.load_history()] == [text, "旧 记录"]
    now = clock.now()
    assert len(chat.load_range(now - timedelta(hours=1), now + timedelta(minutes=1))) == 2
    MemoryStore(paths.memory_db()).close()
    dest = tmp_path / "out.zip"
    library.build_zip(dest, paths.memory_db())
    with zipfile.ZipFile(dest) as z:
        lines = z.read(f"聊天记录/{clock.today().isoformat()}.jsonl").decode("utf-8").splitlines()
    assert [json.loads(x)["text"] for x in lines] == [text, "旧 记录"]


# ---- 5 打码后名字反复重名 --------------------------------------------------------------------
def test_export_survives_repeated_name_collisions(tmp_path):
    s = MemoryStore(paths.memory_db())
    first = s.upsert_entity("王老师 13812345678", kind="person", actor="test")
    s.upsert_entity("王老师 [已隐藏]", kind="person", actor="test")
    s.upsert_entity(f"王老师 [已隐藏] #{first}", kind="person", actor="test")
    s.close()
    dest = tmp_path / "out.zip"
    library.build_zip(dest, paths.memory_db())            # 以前：第二次撞名直接报错，整个导出失败
    with zipfile.ZipFile(dest) as z:
        z.extract("memory.db", tmp_path / "x")
    con = sqlite3.connect(tmp_path / "x" / "memory.db")
    names = [r[0] for r in con.execute("SELECT name FROM entities ORDER BY id")]
    con.close()
    assert len(names) == 3 == len(set(names)) and not any("13812345678" in n for n in names)
