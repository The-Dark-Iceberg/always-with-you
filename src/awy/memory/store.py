"""记忆库的存取。只有这里直接写 SQL。

核心概念（详见 docs/DATA_FORMAT.md 与 docs/MEMORY_ALGORITHMS.md）：
- fact（事实）：一句关于用户的话，带两个「世界时间」：valid_at（从何时成立）、
  invalid_at（从何时不再成立）。借鉴自 Graphiti 的双时间模型。
- retracted_at：这条记录被撤回（写错了），和「不再成立」是两回事。
- 当前事实 = invalid_at 为空 且 retracted_at 为空。
- 所有写操作都记进 audit（写入日志），可以撤销。没有真正的删除。
- episode（原始摘要）：整理时的输入，作为事实的证据。
- inbox（收件箱）：聊天时 AI 留下的便条，只能由整理任务处理。
- persona（核心画像）：上下文最前面的稳定部分。
- speaker / confidence（说话人与可信度，决定 0011）：这条事实是谁说的、有多可信。
  用户自己说的比 AI 说的可信；AI 复述不算加强；等级低的说话人推翻不了等级高的。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from awy import clock
from awy.i18n import t
from awy.memory import text as T

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'other',      -- person/place/project/thing/other
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aliases(
  alias TEXT PRIMARY KEY,                  -- 小写
  entity_id INTEGER NOT NULL REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS episodes(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,                    -- pc_summary / phone / manual ...
  period_start TEXT, period_end TEXT,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  processed_at TEXT, processed_by TEXT
);

CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'event',  -- trait/preference/habit/relation/state/event/plan/health
  importance REAL NOT NULL DEFAULT 0.5,    -- 0~1
  confirmed INTEGER NOT NULL DEFAULT 0,    -- 用户亲口确认/纠正过
  subject_id INTEGER REFERENCES entities(id),
  valid_at TEXT NOT NULL,
  invalid_at TEXT,
  invalid_reason TEXT,
  created_at TEXT NOT NULL,
  retracted_at TEXT,
  episode_id INTEGER REFERENCES episodes(id),
  inbox_id INTEGER,
  source TEXT NOT NULL,                    -- 哪个整理者写的
  recall_count INTEGER NOT NULL DEFAULT 0,
  last_recalled_at TEXT,
  reinforce_count INTEGER NOT NULL DEFAULT 0, -- 加强分（用户再提 +2，电脑活动/认同/聊过 +1，AI 复述 +0）
  speaker TEXT NOT NULL DEFAULT 'pc',      -- note/user/user_agreed/shared/pc/assistant，见 SPEAKERS
  confidence REAL NOT NULL DEFAULT 0.6,    -- 可信度 0~1
  embedding BLOB,
  embed_model TEXT
);
CREATE INDEX IF NOT EXISTS facts_current ON facts(invalid_at, retracted_at);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(tokens);

CREATE TABLE IF NOT EXISTS persona(
  id INTEGER PRIMARY KEY,
  content TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS inbox(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                      -- remember / correct / note
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  processed_at TEXT, result TEXT
);

CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT NOT NULL,                    -- fact:12 / persona:3 / entity:5 ...
  detail TEXT NOT NULL DEFAULT '{}',
  undone_at TEXT
);
"""

CATEGORIES = {"trait", "preference", "habit", "relation", "state", "event", "plan", "health", "shared"}

# 说话人：(可信度, 等级, 再次提到时的加强分)。等级低的不能推翻等级高的。见决定 0011、docs/MEMORY_ALGORITHMS.md
SPEAKERS: dict[str, tuple[float, int, int]] = {
    "note": (1.0, 3, 2),         # 用户说「记住……」/「你记错了……」
    "user": (0.9, 2, 2),         # 用户自己说的
    "user_agreed": (0.8, 2, 1),  # AI 说的，用户表示认同
    "shared": (1.0, 2, 1),       # 「一起聊过的事」：确实聊过，所以可信度 1.0
    "pc": (0.6, 1, 1),           # 从电脑活动推测
    "assistant": (0.4, 0, 0),    # AI 说的，用户没接话（AI 复述记忆不算加强）
}
INBOX_KINDS = {"remember", "correct", "note"}


def now_iso() -> str:
    return clock.now_iso()


class MemoryStore:
    """线程安全：所有操作串行执行（个人数据量小，够用）。"""

    def __init__(self, path: Path | str, embedder: Any = None) -> None:
        self.path = str(path)
        self.embedder = embedder  # 有 encode(list[str]) -> np.ndarray 和 name 属性；可以为 None
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        self._db.commit()

    def _migrate(self) -> None:
        """旧版记忆库升级。只加列、改数字，不删任何东西。"""
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(facts)")}
        if "speaker" not in cols:   # 1 → 2：说话人与可信度
            self._db.execute("ALTER TABLE facts ADD COLUMN speaker TEXT NOT NULL DEFAULT 'pc'")
            self._db.execute("ALTER TABLE facts ADD COLUMN confidence REAL NOT NULL DEFAULT 0.6")
            self._db.execute("UPDATE facts SET speaker='note', confidence=1.0 WHERE confirmed=1")
            # 旧版强度公式是「2 × 加强次数」，现在直接存加强分，所以乘 2，排序结果不变
            self._db.execute("UPDATE facts SET reinforce_count = reinforce_count * 2")
            self._db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', '2')")
            self._db.execute("INSERT OR REPLACE INTO meta VALUES('reinforce_points_migrated', '1')")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- 工具 ----------------------------------------------------------------
    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _audit(self, actor: str, action: str, target: str, detail: dict) -> int:
        cur = self._db.execute(
            "INSERT INTO audit(at, actor, action, target, detail) VALUES(?,?,?,?,?)",
            (now_iso(), actor, action, target, json.dumps(detail, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def _embed(self, texts: list[str]) -> list[bytes | None]:
        if not self.embedder or not texts:
            return [None] * len(texts)
        try:
            vecs = self.embedder.encode(texts)
        except Exception:
            return [None] * len(texts)
        return [np.asarray(v, dtype=np.float32).tobytes() for v in vecs]

    # ---- 实体 ----------------------------------------------------------------
    def resolve_entity(self, name: str) -> sqlite3.Row | None:
        n = name.strip()
        rows = self._q("SELECT * FROM entities WHERE name=?", (n,))
        if rows:
            return rows[0]
        rows = self._q("SELECT e.* FROM aliases a JOIN entities e ON e.id=a.entity_id WHERE a.alias=?", (n.lower(),))
        return rows[0] if rows else None

    def upsert_entity(self, name: str, kind: str = "other", aliases: list[str] | None = None,
                      note: str = "", actor: str = "system") -> int:
        with self._lock:
            ent = self.resolve_entity(name)
            if ent is None:
                cur = self._db.execute(
                    "INSERT INTO entities(name, kind, note, created_at) VALUES(?,?,?,?)",
                    (name.strip(), kind, note, now_iso()),
                )
                eid = int(cur.lastrowid)
                self._audit(actor, "add_entity", f"entity:{eid}", {"name": name, "kind": kind})
            else:
                eid = int(ent["id"])
                if note and note != ent["note"]:
                    self._db.execute("UPDATE entities SET note=? WHERE id=?", (note, eid))
            for a in aliases or []:
                a = a.strip().lower()
                if a:
                    self._db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (a, eid))
            self._db.commit()
            return eid

    def list_entities(self) -> list[dict]:
        rows = self._q("SELECT * FROM entities ORDER BY id")
        out = []
        for r in rows:
            al = [x["alias"] for x in self._q("SELECT alias FROM aliases WHERE entity_id=?", (r["id"],))]
            out.append({**dict(r), "aliases": al})
        return out

    # ---- 原始摘要（episode）-----------------------------------------------------
    def add_episode(self, source: str, content: str, period_start: str | None = None,
                    period_end: str | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO episodes(source, period_start, period_end, content, created_at) VALUES(?,?,?,?,?)",
                (source, period_start, period_end, content, now_iso()),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def pending_episodes(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM episodes WHERE processed_at IS NULL ORDER BY id")]

    def episodes_between(self, start_iso: str, end_iso: str) -> list[dict]:
        return [dict(r) for r in self._q(
            "SELECT * FROM episodes WHERE period_end > ? AND period_start < ? ORDER BY period_start",
            (start_iso, end_iso))]

    def latest_episode_end(self, source: str) -> str | None:
        r = self._q("SELECT MAX(period_end) AS m FROM episodes WHERE source=?", (source,))
        return r[0]["m"] if r else None

    # ---- 收件箱 ----------------------------------------------------------------
    def add_inbox(self, kind: str, content: str, source: str) -> int:
        if kind not in INBOX_KINDS:
            raise ValueError(f"kind 必须是 {sorted(INBOX_KINDS)} 之一")
        content = content.strip()
        if not content:
            raise ValueError("内容不能为空")
        if len(content) > 2000:
            raise ValueError("便条太长（最多 2000 字）")
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO inbox(kind, content, source, created_at) VALUES(?,?,?,?)",
                (kind, content, source, now_iso()),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def pending_inbox(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM inbox WHERE processed_at IS NULL ORDER BY id")]

    def mark_processed(self, episode_ids: list[int], inbox_ids: list[int], actor: str, note: str = "") -> None:
        t = now_iso()
        with self._lock:
            for i in episode_ids:
                self._db.execute("UPDATE episodes SET processed_at=?, processed_by=? WHERE id=? AND processed_at IS NULL",
                                 (t, actor, i))
            for i in inbox_ids:
                self._db.execute("UPDATE inbox SET processed_at=?, result=? WHERE id=? AND processed_at IS NULL",
                                 (t, note, i))
            self._audit(actor, "mark_processed", "batch", {"episodes": episode_ids, "inbox": inbox_ids, "note": note})
            self._db.commit()

    # ---- 事实 ----------------------------------------------------------------
    def add_fact(self, text: str, *, actor: str, category: str = "event", importance: float = 0.5,
                 valid_at: str | None = None, subject: str | None = None, episode_id: int | None = None,
                 inbox_id: int | None = None, confirmed: bool = False, speaker: str | None = None) -> int:
        text = text.strip()
        if not text:
            raise ValueError("事实内容不能为空")
        if category not in CATEGORIES:
            category = "event"
        speaker = speaker if speaker in SPEAKERS else ("note" if confirmed else "pc")
        if speaker == "shared" or category == "shared":   # 「一起聊过的事」两者总是一起出现
            speaker, category = "shared", "shared"
        if speaker == "note":
            confirmed = True
        confidence = SPEAKERS[speaker][0]
        importance = float(min(1.0, max(0.0, importance)))
        valid_at = valid_at or now_iso()
        datetime.fromisoformat(valid_at)  # 格式校验
        with self._lock:
            sid = self.upsert_entity(subject, actor=actor) if subject else None
            (emb,) = self._embed([text])
            cur = self._db.execute(
                """INSERT INTO facts(text, category, importance, confirmed, subject_id, valid_at, created_at,
                   episode_id, inbox_id, source, speaker, confidence, embedding, embed_model)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (text, category, importance, int(confirmed), sid, valid_at, now_iso(), episode_id, inbox_id,
                 actor, speaker, confidence, emb, getattr(self.embedder, "name", None) if emb else None),
            )
            fid = int(cur.lastrowid)
            self._db.execute("INSERT INTO facts_fts(rowid, tokens) VALUES(?,?)", (fid, T.tokenize(text)))
            self._audit(actor, "add_fact", f"fact:{fid}", {"text": text, "category": category, "speaker": speaker,
                                                            "importance": importance, "valid_at": valid_at})
            self._db.commit()
            return fid

    def get_fact(self, fid: int) -> dict | None:
        rows = self._q("SELECT * FROM facts WHERE id=?", (fid,))
        return _fact_dict(rows[0]) if rows else None

    def invalidate_fact(self, fid: int, *, actor: str, invalid_at: str | None = None, reason: str = "",
                        speaker: str = "note") -> None:
        """把事实标记为不再成立。speaker 是「推翻它的证据是谁说的」：等级低的推翻不了等级高的（AI 推翻不了用户说的）。"""
        invalid_at = invalid_at or now_iso()
        datetime.fromisoformat(invalid_at)
        with self._lock:
            f = self.get_fact(fid)
            if f is None:
                raise ValueError(f"没有编号为 {fid} 的事实")
            if f["invalid_at"]:
                return
            mine = SPEAKERS.get(speaker, SPEAKERS["pc"])[1]
            theirs = SPEAKERS.get(f.get("speaker") or "pc", SPEAKERS["pc"])[1]
            if mine < theirs:
                raise PermissionError(f"fact_id={fid} 是「{f.get('speaker')}」说的，可信度更高；"
                                      f"「{speaker}」的证据不能推翻它。只有用户自己的话才能推翻。")
            self._db.execute("UPDATE facts SET invalid_at=?, invalid_reason=? WHERE id=?", (invalid_at, reason, fid))
            self._audit(actor, "invalidate_fact", f"fact:{fid}", {"invalid_at": invalid_at, "reason": reason,
                                                                   "speaker": speaker})
            self._db.commit()

    def reinforce_fact(self, fid: int, *, actor: str, speaker: str = "pc") -> int:
        """同一事实再次出现：不新增，只加强。返回加了几分（AI 复述是 0，什么都不改）。
        证据更可信时，这条事实的说话人和可信度升上去（AI 猜的被用户亲口说了 → 变成「用户说的」）。
        例外：「一起聊过」只加分、不改说话人——它说的是「聊过这件事」，不是「这件事是谁说的」；
        要是让它换掉，用户亲口说的「喜欢吃辣」会被标成【一起聊过】。"""
        conf, _, points = SPEAKERS.get(speaker, SPEAKERS["pc"])
        with self._lock:
            f = self.get_fact(fid)
            if f is None:
                raise ValueError(f"没有编号为 {fid} 的事实")
            old_conf = float(f.get("confidence") or 0.6)
            new_conf = old_conf if speaker == "shared" and f.get("speaker") != "shared" else max(old_conf, conf)
            if points == 0 and new_conf == old_conf:
                return 0
            upgrade = new_conf > old_conf
            self._db.execute("UPDATE facts SET reinforce_count=reinforce_count+?, confidence=?"
                             + (", speaker=?" if upgrade else "") + " WHERE id=?",
                             (points, new_conf, speaker, fid) if upgrade else (points, new_conf, fid))
            self._audit(actor, "reinforce_fact", f"fact:{fid}", {
                "points": points, "speaker": speaker, "old_confidence": old_conf, "old_speaker": f.get("speaker"),
                "text": f["text"]})
            self._db.commit()
            return points

    def note_recalled(self, fids: list[int], *, once_per_day: bool = False) -> None:
        """被想起一次就记一次（遗忘曲线里的「回忆加强」）。不进写入日志。
        once_per_day=True：今天已经记过的不再加（聊天时附上的整段记忆用它：每发一句都附，
        要是每次都加，聊十来句所有记忆的强度就全封顶了，「越常被想起越牢」也就没有区分度了）。"""
        if not fids:
            return
        t = now_iso()
        sql = "UPDATE facts SET recall_count=recall_count+1, last_recalled_at=? WHERE id=?"
        if once_per_day:
            sql += " AND (last_recalled_at IS NULL OR substr(last_recalled_at, 1, 10) < ?)"
        with self._lock:
            self._db.executemany(sql, [(t, i, t[:10]) if once_per_day else (t, i) for i in fids])
            self._db.commit()

    def current_facts(self) -> list[dict]:
        return [_fact_dict(r) for r in self._q(
            "SELECT * FROM facts WHERE invalid_at IS NULL AND retracted_at IS NULL ORDER BY id")]

    def ended_facts(self) -> list[dict]:
        """后来不再成立的事实（被标记失效，但没有被撤回），导出时单独列出。"""
        return [_fact_dict(r) for r in self._q(
            "SELECT * FROM facts WHERE invalid_at IS NOT NULL AND retracted_at IS NULL ORDER BY invalid_at")]

    def facts_valid_during(self, start_iso: str, end_iso: str) -> list[dict]:
        """某段时间内成立过的事实（包括后来失效的），用于回顾历史。"""
        return [_fact_dict(r) for r in self._q(
            """SELECT * FROM facts WHERE retracted_at IS NULL AND valid_at < ?
               AND (invalid_at IS NULL OR invalid_at > ?) ORDER BY valid_at""", (end_iso, start_iso))]

    def fts_search(self, query: str, limit: int = 50, include_inactive: bool = False) -> list[tuple[int, float]]:
        """关键词搜索，返回 [(fact_id, bm25 分数)]，分数越小越相关。"""
        q = T.fts_query(query)
        if not q:
            return []
        cond = "" if include_inactive else "AND f.invalid_at IS NULL AND f.retracted_at IS NULL"
        rows = self._q(
            f"""SELECT f.id, bm25(facts_fts) AS s FROM facts_fts JOIN facts f ON f.id=facts_fts.rowid
                WHERE facts_fts MATCH ? AND f.retracted_at IS NULL {cond} ORDER BY s LIMIT ?""",
            (q, limit))
        return [(int(r["id"]), float(r["s"])) for r in rows]

    def facts_by_ids(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {int(r["id"]): _fact_dict(r) for r in self._q(f"SELECT * FROM facts WHERE id IN ({marks})", tuple(ids))}

    def embeddings(self, include_inactive: bool = False) -> tuple[list[int], np.ndarray | None]:
        model = getattr(self.embedder, "name", None)
        if not model:
            return [], None
        cond = "" if include_inactive else "AND invalid_at IS NULL"
        rows = self._q(f"SELECT id, embedding FROM facts WHERE retracted_at IS NULL {cond} "
                       "AND embedding IS NOT NULL AND embed_model=?", (model,))
        if not rows:
            return [], None
        ids = [int(r["id"]) for r in rows]
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        return ids, mat

    def missing_embeddings(self) -> int:
        """当前事实里还没有向量的条数。"""
        return int(self._q("SELECT COUNT(*) FROM facts WHERE invalid_at IS NULL AND retracted_at IS NULL "
                           "AND embedding IS NULL")[0][0])

    def reembed_all(self, progress: Any = None) -> int:
        """换模型或第一次装好模型后，给所有事实重新算向量。"""
        rows = self._q("SELECT id, text FROM facts WHERE retracted_at IS NULL")
        done = 0
        for i in range(0, len(rows), 16):
            batch = rows[i:i + 16]
            embs = self._embed([r["text"] for r in batch])
            with self._lock:
                for r, e in zip(batch, embs):
                    self._db.execute("UPDATE facts SET embedding=?, embed_model=? WHERE id=?",
                                     (e, getattr(self.embedder, "name", None) if e else None, r["id"]))
                self._db.commit()
            done += len(batch)
            if progress:
                progress(done, len(rows))
        return done

    # ---- 核心画像 --------------------------------------------------------------
    def persona(self) -> dict | None:
        rows = self._q("SELECT * FROM persona WHERE active=1 ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def set_persona(self, content: str, *, actor: str, reason: str = "") -> int:
        content = content.strip()
        if not content:
            raise ValueError("画像内容不能为空")
        with self._lock:
            old = self.persona()
            self._db.execute("UPDATE persona SET active=0 WHERE active=1")
            cur = self._db.execute(
                "INSERT INTO persona(content, reason, source, created_at) VALUES(?,?,?,?)",
                (content, reason, actor, now_iso()))
            pid = int(cur.lastrowid)
            self._audit(actor, "set_persona", f"persona:{pid}",
                        {"previous": old["id"] if old else None, "reason": reason})
            self._db.commit()
            return pid

    # ---- 写入日志与撤销 ----------------------------------------------------------
    def audit_log(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]

    def undo(self, audit_id: int, actor: str = "user") -> str:
        """撤销一条写入。返回说明文字。"""
        with self._lock:
            rows = self._q("SELECT * FROM audit WHERE id=?", (audit_id,))
            if not rows:
                raise ValueError(t("没有这条日志"))
            a = rows[0]
            if a["undone_at"]:
                return t("这条已经撤销过了")
            kind, _, tid = a["target"].partition(":")
            detail = json.loads(a["detail"])
            action = a["action"]
            if action == "add_fact":
                self._db.execute("UPDATE facts SET retracted_at=? WHERE id=?", (now_iso(), int(tid)))
                msg = t("已撤回事实 #{id}", id=tid)
            elif action == "invalidate_fact":
                self._db.execute("UPDATE facts SET invalid_at=NULL, invalid_reason=NULL WHERE id=?", (int(tid),))
                msg = t("事实 #{id} 恢复为仍然成立", id=tid)
            elif action == "reinforce_fact":
                pts = int(detail.get("points", 2))   # 旧版没记分数的，迁移时已按 ×2 换算
                self._db.execute("UPDATE facts SET reinforce_count=MAX(0, reinforce_count-?) WHERE id=?", (pts, int(tid)))
                if "old_confidence" in detail:
                    self._db.execute("UPDATE facts SET confidence=?, speaker=COALESCE(?, speaker) WHERE id=?",
                                     (detail["old_confidence"], detail.get("old_speaker"), int(tid)))
                msg = t("取消对事实 #{id} 的一次加强", id=tid)
            elif action == "set_persona":
                self._db.execute("UPDATE persona SET active=0 WHERE id=?", (int(tid),))
                prev = detail.get("previous")
                if prev:
                    self._db.execute("UPDATE persona SET active=1 WHERE id=?", (prev,))
                msg = t("画像已恢复到上一版") if prev else t("画像已清空")
            else:
                return t("「{action}」类型的操作不支持撤销", action=action)
            self._db.execute("UPDATE audit SET undone_at=? WHERE id=?", (now_iso(), audit_id))
            self._audit(actor, "undo", f"audit:{audit_id}", {"undid": action, "target": a["target"]})
            self._db.commit()
            return msg

    # ---- 统计 ----------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        def one(sql: str) -> int:
            return int(self._q(sql)[0][0])
        return {
            "current_facts": one("SELECT COUNT(*) FROM facts WHERE invalid_at IS NULL AND retracted_at IS NULL"),
            "all_facts": one("SELECT COUNT(*) FROM facts"),
            "entities": one("SELECT COUNT(*) FROM entities"),
            "pending_episodes": one("SELECT COUNT(*) FROM episodes WHERE processed_at IS NULL"),
            "pending_inbox": one("SELECT COUNT(*) FROM inbox WHERE processed_at IS NULL"),
            "embedded": one("SELECT COUNT(*) FROM facts WHERE embedding IS NOT NULL"),
        }


def _fact_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("embedding", None)
    return d
