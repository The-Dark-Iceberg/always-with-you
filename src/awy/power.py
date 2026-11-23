"""电脑睡眠 / 关机的识别（决定 0012）。只用 Windows 自带的东西，笔记本、台式机、各品牌通用。

原理：
1. **间隔检测（主）**：采集线程每 5 秒醒一次。电脑睡眠时所有程序都被冻住（2026-11-21 实测：睡眠期间一条记录都没有），
   所以醒来后发现「上一次到这一次隔了 1 分钟以上」，就说明中间电脑睡着了。
2. **系统日志（校准）**：Windows「系统」日志里记着进入 / 退出睡眠的准确时间，用 wevtutil 读（不需要管理员权限）：
   - Kernel-Power 42（进入睡眠 / 休眠）、506（进入现代待机，Modern Standby）
   - Kernel-Power 107（从睡眠恢复）、507（退出现代待机）、Power-Troubleshooter 1（从低功耗状态恢复）
   - 关机：Kernel-General 13、EventLog 6006、User32 1074、Kernel-Power 109；开机：Kernel-General 12、EventLog 6005
   读不到日志（被策略禁用等）时，就用间隔检测的时间，误差在 5 秒左右。
3. **关机**：程序启动时，如果上一条记录早于这次开机时间，中间就是「关机」。
4. **假醒合并**：睡眠中途短暂亮一下（不到 1 分钟又睡了）算作一直在睡。

不区分合盖还是按电源键，统一叫「电脑睡眠」。
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

GAP_SECONDS = 60          # 两次采集之间隔了这么久，就认为电脑睡过
FAKE_WAKE_SECONDS = 60    # 醒来不到这么久又睡了：算一直在睡
SLEEP_ENTER = {("Kernel-Power", 42), ("Kernel-Power", 506)}
SLEEP_EXIT = {("Kernel-Power", 107), ("Kernel-Power", 507), ("Power-Troubleshooter", 1)}
SHUTDOWN = {("Kernel-General", 13), ("EventLog", 6006), ("User32", 1074), ("Kernel-Power", 109)}
BOOT = {("Kernel-General", 12), ("EventLog", 6005)}
_ALL = SLEEP_ENTER | SLEEP_EXIT | SHUTDOWN | BOOT
_PROVIDERS = sorted({p for p, _ in _ALL})


def _xpath(start: datetime, end: datetime) -> str:
    prov = " or ".join(f"@Name='{'Microsoft-Windows-' if p not in ('EventLog', 'User32') else ''}{p}'" for p in _PROVIDERS)
    ids = " or ".join(f"EventID={i}" for i in sorted({i for _, i in _ALL}))
    f = "%Y-%m-%dT%H:%M:%S.000Z"
    s, e = start.astimezone(timezone.utc).strftime(f), end.astimezone(timezone.utc).strftime(f)
    return (f"*[System[Provider[{prov}] and ({ids}) and "
            f"TimeCreated[@SystemTime>='{s}' and @SystemTime<='{e}']]]")


def parse_events(xml: str) -> list[tuple[datetime, str, int]]:
    """wevtutil 的 XML 输出 → [(时间, 提供者短名, 事件号)]，按时间排序。"""
    out = []
    for ev in re.findall(r"<Event .*?</Event>", xml, re.S):
        p = re.search(r"Provider Name='([^']+)'", ev)
        i = re.search(r"<EventID[^>]*>(\d+)<", ev)
        tm = re.search(r"SystemTime='([^']+)'", ev)
        rec = re.search(r"<EventRecordID>(\d+)<", ev)
        if not (p and i and tm):
            continue
        prov = p.group(1).removeprefix("Microsoft-Windows-")
        key = (prov, int(i.group(1)))
        if key not in _ALL:
            continue
        raw = tm.group(1).rstrip("Z")
        raw = raw[:26] if "." in raw else raw   # 小数点后最多 6 位
        try:
            when = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append((when, int(rec.group(1)) if rec else 0, prov, key[1]))
    out.sort(key=lambda x: (x[0], x[1]))
    return [(w, p, i) for w, _, p, i in out]


def read_events(start: datetime, end: datetime) -> list[tuple[datetime, str, int]]:
    """读系统日志里 [start, end] 之间的电源事件。读不到返回空列表（调用方退回用间隔时间）。"""
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run(["wevtutil", "qe", "System", "/q:" + _xpath(start, end), "/f:xml", "/c:500"],
                           capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        log.info("读系统日志失败，用间隔时间代替", exc_info=True)
        return []
    if r.returncode != 0:
        log.info("读系统日志失败（返回码 %s），用间隔时间代替", r.returncode)
        return []
    return parse_events(r.stdout.decode("utf-8", "replace"))


def sleep_periods(events: list[tuple[datetime, str, int]]) -> list[tuple[datetime, datetime]]:
    """从系统日志事件里配出「睡着 → 醒来」的时间段，并把不到 1 分钟的假醒合并掉。"""
    periods: list[list[datetime]] = []
    start: datetime | None = None
    for when, prov, eid in events:
        key = (prov, eid)
        if key in SLEEP_ENTER:
            if start is None:
                start = when
        elif key in SLEEP_EXIT and start is not None:
            if periods and (start - periods[-1][1]).total_seconds() < FAKE_WAKE_SECONDS:
                periods[-1][1] = when
            else:
                periods.append([start, when])
            start = None
    return [(a, b) for a, b in periods]


def refine_gap(last_tick: datetime, now: datetime,
               events: list[tuple[datetime, str, int]]) -> tuple[datetime, datetime]:
    """采集发现 last_tick → now 之间断了。用系统日志把开始 / 结束校准到准确时刻。

    - 开始：last_tick 前 10 分钟内有「进入睡眠」且之后没有醒来，就用它（屏幕先黑、程序过几秒才被冻住）。
    - 结束：间隔里最后一次「醒来」的时间。
    找不到就用 last_tick / now。"""
    start, end = last_tick, now
    entering: datetime | None = None
    for when, prov, eid in events:
        key = (prov, eid)
        if when > last_tick:
            break
        if key in SLEEP_ENTER and when >= last_tick - timedelta(minutes=10):
            entering = entering or when
        elif key in SLEEP_EXIT:
            entering = None
    if entering is not None:
        start = entering
    exits = [w for w, p, i in events if (p, i) in SLEEP_EXIT and last_tick <= w <= now]
    if exits:
        end = exits[-1]
    return min(start, last_tick), max(end, start)


def last_shutdown(events: list[tuple[datetime, str, int]], after: datetime, boot: datetime) -> datetime | None:
    """after 和开机时间之间，最后一次「关机」的时间。"""
    found = [w for w, p, i in events if (p, i) in SHUTDOWN and after <= w <= boot]
    return found[-1] if found else None


def boot_time() -> datetime:
    import psutil
    return datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
