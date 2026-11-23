"""原始记录（正本）：raw/YYYY-MM-DD/events.jsonl，每行一个事件，只追加不修改。

事件格式见 docs/DATA_FORMAT.md。写进来的内容必须已经过 privacy 过滤。
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from awy import clock, paths

_lock = threading.Lock()


def now_iso() -> str:
    return clock.now_iso()


def events_file(day: date) -> Path:
    return paths.raw_dir(day) / "events.jsonl"


def append(event: dict[str, Any]) -> None:
    """追加一条事件。event 必须含 ts（ISO 时间，带时区）。"""
    ts = datetime.fromisoformat(event["ts"])
    line = json.dumps(event, ensure_ascii=False)
    with _lock:
        with events_file(ts.date()).open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_day(day: date) -> Iterator[dict[str, Any]]:
    f = paths.data_dir() / "raw" / day.isoformat() / "events.jsonl"
    if not f.exists():
        return
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # 断电时可能写了半行，跳过


def read_range(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """读取 [start, end) 之间的事件，按时间排序。"""
    out: list[dict[str, Any]] = []
    day = start.date() - timedelta(days=1)   # 多看前后一天：换过时区后，同一时刻可能存在相邻日期的文件里
    while day <= end.date() + timedelta(days=1):
        for ev in read_day(day):
            ts = datetime.fromisoformat(ev["ts"])
            if start <= ts < end:
                out.append(ev)
        day += timedelta(days=1)
    out.sort(key=lambda e: e["ts"])
    return out


def last_event_before(t: datetime, lookback_days: int = 2, types: set[str] | None = None) -> dict[str, Any] | None:
    """找 t 之前最近的一条事件（用来知道某个时间段开始时的状态）。types 限定事件类型（不同来源各算各的）。"""
    best = None
    day = t.date() + timedelta(days=1)
    for _ in range(lookback_days + 2):
        for ev in read_day(day):
            ts = datetime.fromisoformat(ev["ts"])
            if ts < t and (types is None or ev.get("type") in types) and (best is None or ev["ts"] > best["ts"]):
                best = ev
        if best:
            return best
        day -= timedelta(days=1)
    return best


def prune(retention_days: int, today: date | None = None) -> list[str]:
    """删除超过保留天数的原始记录文件夹，返回被删的日期。摘要和记忆不受影响。
    天数先整理到 1~3650：0 或负数会把今天的也删掉，太大会算不出日期。"""
    from awy.config import clean_retention
    retention_days = clean_retention(retention_days)
    today = today or clock.today()
    root = paths.data_dir() / "raw"
    removed: list[str] = []
    if not root.exists():
        return removed
    cutoff = today - timedelta(days=retention_days)
    for d in root.iterdir():
        try:
            day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    return removed
