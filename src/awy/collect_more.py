"""更多采集来源（决定 0011）：正在播放、最近打开的文件。都不用无障碍、不截图、不碰键盘。

- 正在播放：Windows 系统媒体接口（SMTC，就是音量浮窗里显示歌名的那个）。后台放歌、网页里放视频都能拿到标题。
  用户决定：听歌看视频不算隐私，不走「不记录的软件」黑名单，只过密码类打码（privacy.mask）。
  注意：无痕窗口里放的视频也会被记到（接口分不出来），使用说明里有提醒。
- 最近打开的文件：Windows「最近使用」文件夹（%APPDATA%\\Microsoft\\Windows\\Recent）里的快捷方式名。
  只记文件名，不读文件内容；文件名含「不记录的关键词」的整条不记，其余过打码。

两个都只在「变化时」写一条原始记录，暂停记录时不采。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from awy import privacy, rawlog
from awy.config import Settings

log = logging.getLogger(__name__)

# SMTC 的播放状态：0 关闭 1 打开 2 切换中 3 停止 4 播放 5 暂停
_PLAYING = 4
_logged_ok = False


def read_now_playing() -> list[dict]:
    """读系统里所有媒体会话：[{app, title, artist, playing}]。出错返回空列表。"""
    global _logged_ok
    if sys.platform != "win32":
        return []
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError:
        if not _logged_ok:
            log.warning("「正在播放」接口加载失败（winrt 没打包进来？），这项采集不工作", exc_info=True)
            _logged_ok = True
        return []

    async def read() -> list[dict]:
        mgr = await Manager.request_async()
        out = []
        for s in mgr.get_sessions():
            try:
                p = await s.try_get_media_properties_async()
                info = s.get_playback_info()
                out.append({"app": str(s.source_app_user_model_id or ""), "title": str(p.title or ""),
                            "artist": str(p.artist or ""), "playing": int(info.playback_status) == _PLAYING})
            except Exception:
                continue
        return out
    try:
        out = asyncio.run(read())
    except Exception:
        log.debug("读正在播放失败", exc_info=True)
        return []
    if not _logged_ok:   # 第一次读成功时记一行，方便确认打包后这项采集能用
        log.info("「正在播放」接口可用（当前 %d 个媒体会话）", len(out))
        _logged_ok = True
    return out


def _app_name(app_id: str) -> str:
    """SMTC 给的是程序标识（如 MSEdge、cloudmusic.exe），去掉 .exe 和路径。"""
    name = app_id.replace("\\", "/").split("/")[-1].split("!")[0]
    return name[:-4] if name.lower().endswith(".exe") else name


class _Poller:
    """后台线程，每隔 interval 秒调一次 tick()。"""
    interval = 5.0
    name = "poller"

    def __init__(self, get_settings: Callable[[], Settings], sink: Callable[[dict], None] = rawlog.append) -> None:
        self._get_settings = get_settings
        self._sink = sink
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> dict | None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _emit(self, ev: dict) -> dict:
        ev = {"ts": rawlog.now_iso(), **ev}
        try:
            self._sink(ev)
        except OSError:
            log.exception("写原始记录失败")
        return ev

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("%s 出错", self.name)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


class MediaCollector(_Poller):
    """正在播放：只在「换歌 / 开始 / 停止」时写一条 {"type": "media", "state": "playing"|"stopped", ...}。"""
    interval = 5.0
    name = "media-collector"

    def __init__(self, get_settings: Callable[[], Settings], read: Callable[[], list[dict]] = read_now_playing,
                 sink: Callable[[dict], None] = rawlog.append) -> None:
        super().__init__(get_settings, sink)
        self._read = read
        self._last: tuple[str, str, str] | None = None

    def tick(self) -> dict | None:
        if not self._get_settings().collect_enabled:
            if self._last is not None:
                self._last = None
                return self._emit({"src": "media", "type": "media", "state": "stopped"})
            return None
        playing = [x for x in self._read() if x.get("playing") and (x.get("title") or "").strip()]
        if not playing:
            if self._last is not None:
                self._last = None
                return self._emit({"src": "media", "type": "media", "state": "stopped"})
            return None
        x = playing[0]
        key = (_app_name(x["app"]), privacy.mask(x["title"].strip()), privacy.mask((x.get("artist") or "").strip()))
        if key == self._last:
            return None
        self._last = key
        return self._emit({"src": "media", "type": "media", "state": "playing",
                           "app": key[0], "title": key[1], "artist": key[2]})


def recent_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"


class RecentFilesCollector(_Poller):
    """最近打开的文件：每分钟看一次「最近使用」文件夹里新出现 / 刚更新的快捷方式。只记文件名。"""
    interval = 60.0
    name = "recent-files"

    def __init__(self, get_settings: Callable[[], Settings], folder: Callable[[], Path] = recent_dir,
                 sink: Callable[[dict], None] = rawlog.append, since: float | None = None) -> None:
        super().__init__(get_settings, sink)
        self._folder = folder
        self._since = time.time() if since is None else since   # 只记程序启动之后打开的，不翻旧账
        self._seen: dict[str, float] = {}

    def tick(self) -> list[dict]:
        s = self._get_settings()
        out: list[dict] = []
        folder = self._folder()
        if not s.collect_enabled or not folder.exists():
            self._since = time.time()
            return out
        newest = self._since
        for f in folder.glob("*.lnk"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime <= self._since:
                continue
            newest = max(newest, mtime)
            name = f.stem                      # 「报告.docx.lnk」→「报告.docx」
            if "." not in name.strip(".") or name.lower().endswith((".exe", ".lnk")):
                continue                       # 没有扩展名的多半是文件夹；程序快捷方式不算「文件」
            if privacy.is_blocked("", name, [], s.blocked_keywords):
                continue
            if time.time() - self._seen.get(name, 0) < 600:   # 10 分钟内重复打开同一个文件只记一次
                continue
            self._seen[name] = time.time()
            out.append(self._emit({"src": "files", "type": "file", "name": privacy.mask(name)}))
        self._since = newest
        return out
