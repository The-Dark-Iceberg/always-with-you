"""程序核心：把各个部件组装起来。界面（ui.py）和无界面模式（__main__ serve）都用它。

部件：设置 → 记忆库 → 电脑采集线程 → 只读 MCP 服务 → 整理 MCP 服务 → 定时整理线程。
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from awy import clock, config, i18n, library, paths
from awy.i18n import t
from awy.browser import BrowserBridge
from awy.collect_more import MediaCollector, RecentFilesCollector
from awy.collect_pc import PcCollector
from awy.config import Settings
from awy.mcp_servers import ServerThread, asgi_app, build_read_server, build_write_server
from awy.memory import embed
from awy.memory.store import MemoryStore
from awy.ops import ReadOps, WriteOps
from awy.phone import Discovery, PhoneBridge
from awy.pipeline import Scheduler, skip_pending_chat

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "AlwaysWithYou"


def setup_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    h = RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)


def close_logging() -> None:
    """关掉日志文件（搬家、换记忆库前要先放开 logs/ 里的文件）。"""
    root = logging.getLogger()
    for h in [h for h in root.handlers if isinstance(h, RotatingFileHandler)]:
        root.removeHandler(h)
        h.close()


class Core:
    def __init__(self, on_message: Callable[[str], None] | None = None) -> None:
        setup_logging()
        self.on_message = on_message or (lambda m: None)
        self.settings: Settings = config.load()
        i18n.set_lang(i18n.resolve(self.settings.language))
        clock.set_zone(self.settings.timezone)
        self._settings_lock = threading.Lock()
        self._stopped = False
        try:
            library.write_folder_readme()   # 数据文件夹最外层的「记忆库说明.md」（决定 0012）
        except OSError:
            log.warning("写记忆库说明失败", exc_info=True)
        self.startup_notices: list[str] = []   # 启动时发生的、要告诉用户的事（托盘图标出来后再提醒）
        emb = self._make_embedder()
        keep_pending = False
        try:
            # 上次启用存档换到一半就退出了：新库可能能打开、聊天却只换了一部分，一律先换回去（决定 0012 补充二）
            restored = library.recover_interrupted_enable()
            if restored:
                log.error("上次换记忆库没换完，已自动换回备份 %s（另存 %s）", restored["backup"], restored["saved"])
                self.startup_notices.append(t("上次换记忆库时程序中途退出了，已经自动换回原来的记忆库"))
                if restored["saved"]:
                    self.startup_notices.append(t("换回之前，上次之后新记下的内容另存在「记忆存档」里：{name}", name=restored["saved"]))
        except Exception:
            log.exception("上次换记忆库没换完，自动换回也失败了（下次启动再试）")
            keep_pending = True
            self.startup_notices.append(t("上次换记忆库时程序中途退出了，自动换回没有成功，下次启动会再试。原来的记忆库备份在「记忆存档」里"))
        try:
            self.store = MemoryStore(paths.memory_db(), embedder=emb)
        except Exception:
            # 刚换过记忆库、新的打不开：用换之前的自动备份换回去再试一次（决定 0012 补充）
            restored = library.recover_failed_enable()
            if not restored:
                raise
            log.error("换上的记忆库打不开，已自动换回备份 %s", restored)
            self.startup_notices.append(t("换上的记忆库打不开，已经自动换回原来的记忆库"))
            self.store = MemoryStore(paths.memory_db(), embedder=emb)
        if keep_pending:
            # 换回失败：留着标记下次再试；这次接着用当前的库，记一笔，下次换回前先把这段时间的数据另存，不会被覆盖
            library.mark_recovery_failed()
        else:
            dropped = library.enable_finished()
            if dropped:
                self.startup_notices.append(t("换上的记忆库里有 {n} 行聊天记录看不懂，已经跳过", n=dropped))
        self.collector = PcCollector(lambda: self.settings, power_watch=True)
        self.extra_collectors = [MediaCollector(lambda: self.settings), RecentFilesCollector(lambda: self.settings)]
        self.browser = BrowserBridge(lambda: self.settings)
        self.browser_server = ServerThread(self.browser.app, self.settings.browser_port, "browser-bridge")
        self.phone = PhoneBridge(lambda: self.settings, self.update_settings)
        self.phone_server: ServerThread | None = None   # 手机接收入口：用户在设置里打开才启动（决定 0014）
        self.phone_discovery: Discovery | None = None
        self._phone_lock = threading.Lock()
        self.read_ops = ReadOps(self.store, self.settings, "chat")
        self.read_server = ServerThread(
            asgi_app(build_read_server(self.read_ops), self.settings.read_token),
            self.settings.read_port, "mcp-read")
        self.write_server = ServerThread(
            asgi_app(build_write_server(WriteOps(self.store, "mcp-organizer",
                                                   chat_allowed=lambda: self.settings.chat_in_memory)), self.settings.write_token),
            self.settings.write_port, "mcp-write")
        self.scheduler = Scheduler(self.store, lambda: self.settings, self.on_message)

    # ---- 生命周期 --------------------------------------------------------------
    @property
    def terms_accepted(self) -> bool:
        return self.settings.accepted_terms == config.TERMS_VERSION

    def start(self) -> None:
        self.read_server.start()
        self.write_server.start()
        self._embed_missing()
        if self.terms_accepted:
            self._start_recording()
        else:
            log.info("还没确认风险说明，先不记录")

    def _start_recording(self) -> None:
        """采集、浏览器扩展接口、定时整理：确认风险说明之后才开始（决定 0012）。"""
        if getattr(self, "_recording", False):
            return
        self._recording = True
        self.collector.start()
        self.browser_server.start()
        for c in self.extra_collectors:
            c.start()
        self.scheduler.start()
        if self.settings.phone_enabled:
            self._start_phone()

    # ---- 手机接收入口（决定 0014）--------------------------------------------------
    def _start_phone(self) -> None:
        with self._phone_lock:
            if self.phone_server is not None:
                return
            port = self.settings.phone_port
            self.phone_server = ServerThread(self.phone.app, port, "phone-bridge", host="0.0.0.0")
            self.phone_discovery = Discovery(self.phone, port)
            self.phone_server.start()
            self.phone_discovery.start()
            log.info("手机接收入口已打开（端口 %d）", port)

    def _stop_phone(self) -> None:
        with self._phone_lock:
            server, disc = self.phone_server, self.phone_discovery
            self.phone_server = self.phone_discovery = None
        self.phone.cancel_pairing()
        if server:
            server.stop()
        if disc:
            disc.stop()

    def set_phone_enabled(self, enabled: bool) -> None:
        """打开 / 关闭手机接收入口。关掉时配对过的手机还在，下次打开接着用。"""
        self.update_settings(phone_enabled=bool(enabled))
        if enabled and self.terms_accepted and not self._stopped:
            self._start_phone()
        elif not enabled:
            self._stop_phone()

    def phone_status(self) -> dict:
        from awy.phone import lan_addresses
        srv, disc = self.phone_server, self.phone_discovery
        return {"enabled": self.settings.phone_enabled, "running": bool(srv and srv.running),
                "error": (srv.error if srv else None) or (disc.error if disc else None),
                "port": self.settings.phone_port, "addresses": lan_addresses(),
                "devices": self.phone.devices(), "pairing": self.phone.pairing_info()}

    def accept_terms(self) -> None:
        self.update_settings(accepted_terms=config.TERMS_VERSION)
        if not self._stopped:
            self._start_recording()
        # 决定 0008：聊天只在本程序里进行，不再生成「陪伴文件夹」，也不改任何别家软件的配置。
        log.info("程序已启动")

    def stop(self) -> None:
        """可以重复调用（换记忆库 / 搬家时先停一次，退出时还会再调一次）。"""
        if self._stopped:
            return
        self._stopped = True
        self.scheduler.stop()
        self.collector.stop()
        self.browser_server.stop()
        self._stop_phone()
        for c in self.extra_collectors:
            c.stop()
        self.read_server.stop()
        self.write_server.stop()
        self.store.close()
        log.info("程序已退出")

    # ---- 设置 ----------------------------------------------------------------
    def update_settings(self, **changes: object) -> None:
        """原地修改设置并保存（各部件拿的是同一个对象，改完立刻生效）。端口改动需重启程序。"""
        with self._settings_lock:
            was_chat_on = self.settings.chat_in_memory
            known = asdict(self.settings).keys()
            for k, v in changes.items():
                if k in known:
                    setattr(self.settings, k, v)
            if "chat_in_memory" in changes:
                self.settings.chat_in_memory = bool(self.settings.chat_in_memory)
                if self.settings.chat_in_memory and not was_chat_on:
                    self.settings.chat_in_memory_since = clock.now_iso()   # 重新打开：从现在开始算，关着时的聊天不补读
            config.save(self.settings)
        if "chat_in_memory" in changes and not self.settings.chat_in_memory:
            skip_pending_chat(self.store)   # 关掉时，已经排队的聊天也立刻不再交给整理 AI
        if "timezone" in changes:
            clock.set_zone(self.settings.timezone)
        if "language" in changes:
            i18n.set_lang(i18n.resolve(self.settings.language))
            try:
                library.write_folder_readme()
            except OSError:
                pass
        if "autostart" in changes:
            set_autostart(bool(changes["autostart"]))

    # ---- 向量模型 --------------------------------------------------------------
    def _make_embedder(self) -> embed.Bge3Embedder | None:
        if self.settings.embedding_enabled and embed.is_installed(paths.models_dir()):
            return embed.Bge3Embedder(paths.models_dir())
        return None

    def model_installed(self) -> bool:
        return embed.is_installed(paths.models_dir())

    def download_model(self, progress: Callable[[str, int, int], None] | None = None) -> str:
        embed.download(paths.models_dir(), progress)
        return self.enable_embedder()

    def enable_embedder(self, progress: Callable[[int, int], None] | None = None) -> str:
        if not self.model_installed():
            return t("模型还没有下载")
        self.store.embedder = embed.Bge3Embedder(paths.models_dir())
        n = self.store.reembed_all(progress)
        return t("向量模型已启用，已为 {n} 条记忆建立索引", n=n)

    def _embed_missing(self) -> None:
        """有记忆还没有向量（比如刚换成别的电脑导出的记忆库）：后台补上。"""
        if self.store.embedder is None or not self.store.missing_embeddings():
            return

        def work() -> None:
            try:
                n = self.store.reembed_all()
                log.info("已为 %d 条记忆补建向量索引", n)
            except Exception:
                log.exception("补建向量索引失败")
        threading.Thread(target=work, name="embed-missing", daemon=True).start()

    def disable_embedder(self) -> None:
        self.store.embedder = None

    # ---- 状态 ----------------------------------------------------------------
    def status(self) -> dict:
        return {
            "collecting": self.settings.collect_enabled,
            "read_server": self.read_server.running,
            "write_server": self.write_server.running,
            "server_error": self.read_server.error or self.write_server.error,
            "embedder": self.store.embedder is not None,
            "model_installed": self.model_installed(),
            "last_organize": self.scheduler.last_message,
            **self.store.stats(),
        }


# ---- 开机自启（只写当前用户的注册表，不需要管理员权限）----------------------------
def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else sys.executable}" -m awy --minimized'


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass
