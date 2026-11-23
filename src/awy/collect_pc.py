"""电脑端采集：每隔几秒问一次 Windows「最前面的窗口是哪个」和「用户多久没操作了」。

只读取：窗口标题、进程名、空闲秒数。
不读取：按了哪些键、屏幕内容、剪贴板、文件内容。
只有状态变化时才写一条记录（换窗口、离开、回来、锁屏），不是每 5 秒写一行。

电脑睡眠 / 关机（决定 0012，原理见 power.py）：
- 两次采集之间隔了 1 分钟以上 = 电脑睡过：补写 away(reason=sleep)（时间往回补到睡着的那一刻）和 back(reason=sleep)。
- 程序启动时，上一条记录早于开机时间 = 中间关过机：补写 away(reason=shutdown) 和 back(reason=shutdown)。
- 程序正常退出时写 away(reason=app_exit)，退出期间不算在用电脑。
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import psutil

from awy import clock, power, privacy, rawlog
from awy.config import Settings

log = logging.getLogger(__name__)

LOCK_APPS = {"lockapp.exe", "logonui.exe"}
STATE_TYPES = {"window", "away", "back", "paused", "resumed"}


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0


def foreground() -> tuple[str, str]:
    """返回 (进程名, 窗口标题)。拿不到时返回空字符串。"""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name()
    except (psutil.Error, ValueError):
        app = ""
    return app, buf.value


@dataclass
class _State:
    app: str = ""
    title: str = ""
    away: bool = False


class PcCollector:
    """后台线程。start() 开始，stop() 结束。暂停由 settings.collect_enabled 控制。"""

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        probe: Callable[[], tuple[str, str]] = foreground,
        idle: Callable[[], float] = idle_seconds,
        sink: Callable[[dict], None] = rawlog.append,
        power_watch: bool = False,
        wallclock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        read_power: Callable[[datetime, datetime], list] = power.read_events,
        boot: Callable[[], datetime] = power.boot_time,
        last_state: Callable[[datetime], dict | None] | None = None,
    ) -> None:
        self._get_settings = get_settings
        self._power_watch = power_watch     # 测试里默认关掉，程序里由 core 打开
        self._wall = wallclock
        self._read_power = read_power
        self._boot = boot
        self._last_state = last_state or (lambda t: rawlog.last_event_before(t, types=STATE_TYPES))
        self._last_tick: datetime | None = None
        self._probe = probe
        self._idle = idle
        self._sink = sink
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = _State()
        self.paused_written = False

    # ---- 电脑睡眠 / 关机 ---------------------------------------------------------
    def _power_check(self, s: Settings) -> None:
        now = self._wall()
        last, self._last_tick = self._last_tick, now
        if not self._power_watch or not s.collect_enabled:
            return
        try:
            if last is None:
                self._startup_check(now)
            elif (now - last).total_seconds() > power.GAP_SECONDS:
                self._gap(last, now)
        except Exception:   # 识别失败不影响正常采集
            log.exception("识别睡眠 / 关机出错")

    def _gap(self, last: datetime, now: datetime) -> None:
        events = self._read_power(last - timedelta(minutes=15), now + timedelta(seconds=5))
        start, end = power.refine_gap(last, now, events)
        if (end - start).total_seconds() < power.GAP_SECONDS:
            return
        self._emit_at(start, {"type": "away", "reason": "sleep"})
        self._emit_at(end, {"type": "back", "reason": "sleep"})
        self._state = _State()   # 醒来后重新记当前窗口
        log.info("电脑睡眠：%s → %s", start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))

    def _startup_check(self, now: datetime) -> None:
        """程序刚启动：上一条记录早于这次开机 = 中间关过机。"""
        last = self._last_state(clock.now())
        if not last:
            return
        last_ts = datetime.fromisoformat(last["ts"])
        boot = self._boot()
        if last_ts >= boot:
            if last.get("type") == "window":   # 程序上次没正常退出（崩溃等）：之后那段不能算在用这个软件
                self._emit_at(last_ts + timedelta(seconds=1), {"type": "away", "reason": "app_exit"})
            return
        events = self._read_power(last_ts, boot + timedelta(minutes=1))
        off = power.last_shutdown(events, last_ts, boot) or last_ts
        self._emit_at(max(off, last_ts), {"type": "away", "reason": "shutdown"})
        self._emit_at(boot, {"type": "back", "reason": "shutdown"})
        log.info("关机：%s → 开机 %s", off.isoformat(timespec="seconds"), boot.isoformat(timespec="seconds"))

    def _emit_at(self, when: datetime, ev: dict) -> dict:
        return self._emit({**ev, "ts": clock.to_local(when).isoformat(timespec="seconds")})

    # ---- 单步逻辑（测试直接调用）-----------------------------------------
    def tick(self) -> dict | None:
        s = self._get_settings()
        self._power_check(s)
        if not s.collect_enabled:
            if not self.paused_written:
                self.paused_written = True
                self._state = _State()
                return self._emit({"type": "paused"})
            return None
        if self.paused_written:
            self.paused_written = False
            self._emit({"type": "resumed"})

        app, title = self._probe()
        idle = self._idle()

        if app.lower() in LOCK_APPS:
            if not self._state.away:
                self._state = _State(away=True)
                return self._emit({"type": "away", "reason": "locked"})
            return None

        if idle >= s.idle_threshold_seconds:
            if not self._state.away:
                self._state = _State(away=True)
                return self._emit({"type": "away", "reason": "idle", "idle_seconds": int(idle)})
            return None

        if self._state.away:
            self._state = _State()
            self._emit({"type": "back"})

        if privacy.is_blocked(app, title, s.blocked_apps, s.blocked_keywords):
            app, title = "[隐私窗口]", ""
        else:
            title = privacy.mask(title)

        if (app, title) != (self._state.app, self._state.title):
            self._state = _State(app=app, title=title)
            return self._emit({"type": "window", "app": app, "title": title})
        return None

    def _emit(self, ev: dict) -> dict:
        ev = {"ts": rawlog.now_iso(), "src": "pc", **ev}   # ev 里自带 ts 时用它的（往回补的睡眠 / 关机）
        try:
            self._sink(ev)
        except OSError:
            log.exception("写原始记录失败")
        return ev

    # ---- 线程 ----------------------------------------------------------------
    def start(self) -> None:
        if sys.platform != "win32":
            log.warning("非 Windows 系统，电脑采集不启动")
            return
        self._thread = threading.Thread(target=self._run, name="pc-collector", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # 采集失败不能拖垮整个程序
                log.exception("采集出错")
            self._stop.wait(max(1, self._get_settings().poll_seconds))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._power_watch and self._thread and self._get_settings().collect_enabled and not self._state.away:
            self._emit({"type": "away", "reason": "app_exit"})   # 退出期间不算在用电脑
