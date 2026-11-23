"""时间：程序里所有「现在几点」「今天是哪天」都从这里取（决定 0011）。

设置里的「我所在的地区」（settings.timezone）：
- 空字符串 = 跟随电脑的时区。
- 填 IANA 时区名（如 Europe/London）= 按这个地区算。原理：电脑时钟里的 UTC 时间不管电脑时区设成什么都是准的，
  拿它换算成所选地区的时间（夏令时由 tzdata 自动处理）。不联网查位置。

为什么要这个：留学生常见「电脑是国内时间、人在英国」，记忆里的「凌晨 2 点还在写代码」要按人实际生活的时间算。
Windows 版 Python 不带时区数据库，靠 tzdata 包（已打包进安装包）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

_zone: tzinfo | None = None   # None = 跟随电脑
_name = ""


def set_zone(name: str) -> bool:
    """设置所在地区。名字不认识就退回「跟随电脑」，返回 False。"""
    global _zone, _name
    name = (name or "").strip()
    if not name:
        _zone, _name = None, ""
        return True
    try:
        _zone, _name = ZoneInfo(name), name
        return True
    except (ZoneInfoNotFoundError, ValueError):
        _zone, _name = None, ""
        return False


def zone_name() -> str:
    """当前生效的时区名；跟随电脑时返回空字符串。"""
    return _name


def now() -> datetime:
    """带时区的「现在」。"""
    n = datetime.now(timezone.utc)
    return n.astimezone(_zone) if _zone is not None else n.astimezone()


def today() -> date:
    return now().date()


def to_local(dt: datetime) -> datetime:
    """把记录里的时间（可能是以前别的时区存的）换成当前地区的时间，用于显示和摘要。"""
    return dt.astimezone(_zone) if _zone is not None else dt.astimezone()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


@lru_cache(maxsize=1)
def zones() -> list[str]:
    """可以选的地区（IANA 名）。去掉历史遗留和 Etc/ 这类不像地名的。"""
    skip = ("Etc/", "SystemV/", "US/", "posix/", "right/", "Canada/", "Mexico/", "Brazil/", "Chile/")
    names = {z for z in available_timezones() if "/" in z and not z.startswith(skip)}
    std = set(zone_countries())
    if std:   # 只留 zone.tab 里的正式名字（去掉 America/Buenos_Aires 这类旧别名，免得同一个城市出现两次）
        names &= std
    return sorted(names)


@lru_cache(maxsize=1)
def zone_countries() -> dict[str, str]:
    """时区 → 国家 / 地区代码（来自 tzdata 自带的 zone.tab），设置页用来显示「英国 · 伦敦」这样的名字。"""
    out: dict[str, str] = {}
    try:
        from importlib.resources import files
        text = files("tzdata").joinpath("zoneinfo", "zone.tab").read_text(encoding="utf-8")
    except (ImportError, OSError, ValueError):
        return out
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            out[parts[2]] = parts[0]
    return out


def is_valid(name: str) -> bool:
    return not name or name in available_timezones()
