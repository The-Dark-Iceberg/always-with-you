"""界面用的本机接口：提供 ui/ 里的页面文件，以及页面要的数据（/api/...）。

安全：
- 只监听 127.0.0.1，端口每次启动随机。
- 每个 /api 请求必须带 X-AWY-Token（钥匙每次启动随机生成，只交给我们自己的窗口）。
- 检查 Host 头必须是 127.0.0.1:<端口>，防「DNS 重绑定」把恶意网页伪装成本机地址。
- 带 Origin 头时必须是我们自己的地址，防别的网页跨站调用。
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from awy import __version__, clock, config, export, i18n, library, paths, rawlog, summarize, updater, vault
from awy import chat as _chat
from awy.chat import ChatService, detect_brains, load_page
from awy.i18n import t
from awy.memory import rank
from awy.privacy import MASK

# 下面几个是「按当前语言」的显示名：每次调用时现取，切换语言后立刻生效
_cat = export.category_name


def _act(a: str) -> str:
    return {"add_fact": t("新增"), "invalidate_fact": t("标记失效"), "reinforce_fact": t("加强"),
            "set_persona": t("更新画像"), "add_entity": t("登记"), "mark_processed": t("整理完成"),
            "undo": t("撤销")}.get(a, a)


def _who(w: str) -> str:
    return {"deepseek": "DeepSeek", "mcp-organizer": t("整理入口"), "chat": t("陪伴聊天"), "user": t("你")}.get(w, w)


def _app_name(a: str) -> str:
    """采集时存下的几个固定中文名，显示时翻译。"""
    return {"[隐私窗口]": t("[隐私窗口]"), "未知": t("未知")}.get(a, a)


PREF_IMAGES = {"avatar": 400_000, "wallpaper": 6_000_000}   # 允许的最大字节数（已在页面里压缩过）
# 界面偏好（存在 prefs/prefs.json）。只存「不是默认」的值，默认值就删掉这一项。
PREF_FREE = {"veil", "side"}   # 旧有的：聊天壁纸遮罩、侧边栏收起
PREF_CHOICES = {
    "tlorder": {"desc"},                # 首页时间线：从晚到早
    "skin": {"glass"},                  # 主题：液态玻璃（默认铅笔手绘），决定 0013
    "glassbg": {"wall"},                # 玻璃背景：自己的壁纸（默认紫白气泡）
    "glassmode": {"light", "dark"},     # 玻璃明暗（默认跟随系统）
    "motion": {"full", "off"},          # 动效（默认收敛）
}
PREF_PERCENT = {"glassveil"}            # 玻璃浓淡 0~100
SETTING_KEYS = {"organizer", "organize_times", "blocked_apps", "blocked_keywords", "raw_retention_days",
                "autostart", "chat_brain", "collect_enabled", "language", "antigravity_model",
                "timezone", "chat_in_memory", "chat_brain"}


def _fmt_min(sec: float) -> str:
    m = int(round(sec / 60))
    return t("{h} 时 {m} 分", h=m // 60, m=f"{m % 60:02d}") if m >= 60 else t("{m} 分", m=m)


class WebApi:
    def __init__(self, core: Any, token: str, port: int) -> None:
        self.core = core
        self.token = token
        self.port = port
        self.chat = ChatService(core.read_ops, core.settings)
        self.on_show: Any = None  # 第二个实例启动时调用，让窗口出现
        self.on_quit: Any = None  # 开始安装更新后、或托盘菜单点「退出」时调用，让程序退出（桌面版才有）
        self.on_menu_hide: Any = None  # 托盘菜单点完某一项后收起（桌面版才有）
        self.pick_folder: Any = None   # 弹出「选择文件夹」对话框，返回路径或 None（桌面版才有）
        self.pick_zip: Any = None      # 弹出「选择压缩包」对话框，返回路径或 None（桌面版才有）
        self.on_restart: Any = None    # 换记忆库 / 搬家后重启程序（桌面版才有）
        self.lib_job: dict[str, Any] = {"state": "idle"}
        self._move_dest: Path | None = None
        self.update_job: dict[str, Any] = {"state": "idle"}
        self.model_job: dict[str, Any] = {"state": "idle"}   # 模型下载进度
        routes = [
            Route("/api/status", self.status),
            Route("/api/today", self.today),
            Route("/api/memory", self.memory),
            Route("/api/log", self.audit),
            Route("/api/log/{aid:int}/undo", self.undo, methods=["POST"]),
            Route("/api/settings", self.settings, methods=["GET", "POST"]),
            Route("/api/brains", self.brains),
            Route("/api/timezones", self.timezones),
            Route("/api/install/{brain}", self.install, methods=["POST"]),
            Route("/api/organize", self.organize, methods=["POST"]),
            Route("/api/model", self.model_status),
            Route("/api/model/download", self.model_download, methods=["POST"]),
            Route("/api/chat", self.chat_send, methods=["POST"]),
            Route("/api/chat/history", self.chat_history),
            Route("/api/chat/warmup", self.chat_warmup, methods=["POST"]),
            Route("/api/prefs", self.prefs_get),
            Route("/api/prefs/{name}", self.prefs_set, methods=["POST", "DELETE"]),
            Route("/api/show", self.show, methods=["POST"]),
            Route("/api/export/{kind}", self.export_txt, methods=["POST"]),
            Route("/api/quit", self.quit, methods=["POST"]),
            Route("/api/browser/status", self.browser_status),
            Route("/api/browser/install", self.browser_install, methods=["POST"]),
            Route("/api/phone", self.phone_status),
            Route("/api/phone/enable", self.phone_enable, methods=["POST"]),
            Route("/api/phone/pair", self.phone_pair, methods=["POST", "DELETE"]),
            Route("/api/phone/unpair", self.phone_unpair, methods=["POST"]),
            Route("/api/menu/hide", self.menu_hide, methods=["POST"]),
            Route("/api/terms/accept", self.terms_accept, methods=["POST"]),
            Route("/api/onboarded", self.onboarded, methods=["POST"]),
            Route("/api/library", self.library_info),
            Route("/api/library/open", self.library_open, methods=["POST"]),
            Route("/api/library/export", self.library_export, methods=["POST"]),
            Route("/api/library/import", self.library_import, methods=["POST"]),
            Route("/api/library/enable", self.library_enable, methods=["POST"]),
            Route("/api/library/archives/open", self.library_archives_open, methods=["POST"]),
            Route("/api/library/move/pick", self.library_move_pick, methods=["POST"]),
            Route("/api/library/move", self.library_move, methods=["POST"]),
            Route("/api/library/job", self.library_job),
            Route("/api/update/check", self.update_check),
            Route("/api/update/install", self.update_install, methods=["POST"]),
            Route("/api/update/status", self.update_status),
            Route("/", self.index),
            Mount("/", StaticFiles(directory=str(paths.ui_dir())), name="ui"),
        ]
        self.app = _Guard(Starlette(routes=routes), token, port)

    # ---- 页面 ----
    async def index(self, request: Request) -> Response:
        return FileResponse(paths.ui_dir() / "index.html", headers={"Cache-Control": "no-store"})

    # ---- 状态 ----
    async def status(self, request: Request) -> Response:
        s = self.core.settings
        st = self.core.status()
        return JSONResponse({**st, "chatBrain": s.chat_brain, "organizeBrain": _organizer_to_brain(s.organizer),
                             "nextOrganize": _next_slot(s.organize_times), "version": __version__,
                             "today": clock.today().isoformat(), "timezone": clock.zone_name(),
                             "now": clock.now().strftime("%H:%M"),
                             "language": i18n.lang(), "languageSetting": s.language,
                             "termsAccepted": self.core.terms_accepted, "onboarded": s.onboarded,
                             "languages": [{"code": k, "name": v} for k, v in i18n.LANGS.items()]})

    # ---- 今天 ----
    async def today(self, request: Request) -> Response:
        now = clock.now()
        start = datetime.combine(now.date(), dtime.min, tzinfo=now.tzinfo)
        events = summarize.state_events(start, now) + rawlog.read_range(start, now)
        segs, away = summarize.build_segments(events, start, now)
        active = sum(s.seconds for s in segs)
        per_app: dict[str, float] = {}
        for s in segs:
            per_app[s.app] = per_app.get(s.app, 0) + s.seconds
        timeline = []
        for s in segs:
            if s.seconds < summarize.MIN_SEGMENT_SECONDS:
                continue
            tops = [t for t, _ in sorted(s.titles.items(), key=lambda kv: -kv[1])[:3]]
            timeline.append({"at": s.start.timestamp(), "when": f"{clock.to_local(s.start):%H:%M}–{clock.to_local(s.end):%H:%M}", "app": _app_name(s.app), "t": " · ".join(tops).replace(MASK, t("[已隐藏]")),
                             "dur": _fmt_min(s.seconds)})
        for a, b, why in summarize.power_periods(events, start, now):   # 电脑睡眠 / 关机也列进时间线
            if (b - a).total_seconds() >= summarize.MIN_SEGMENT_SECONDS:
                timeline.append({"at": a.timestamp(), "when": f"{clock.to_local(a):%H:%M}–{clock.to_local(b):%H:%M}",
                                 "app": "", "t": t("电脑睡眠") if why == "sleep" else t("关机"), "away": True, "power": why,
                                 "dur": _fmt_min((b - a).total_seconds())})
        timeline.sort(key=lambda x: x["at"])
        added_today = sum(1 for f in self.core.store.current_facts() if f["created_at"][:10] == now.date().isoformat())
        hour = now.hour
        hi = (t("早上好") if 5 <= hour < 11 else t("中午好") if hour < 13 else t("下午好") if hour < 18
              else t("晚上好") if hour < 23 else t("夜深了"))
        top = max(per_app.items(), key=lambda kv: kv[1])[0] if per_app else None
        greet = (t("{hi}。今天你在电脑前待了 {dur}，用得最多的是 {app}。", hi=hi, dur=_fmt_min(active),
                   app=_app_name(top or "")) if active >= 60 else t("{hi}。今天还没怎么用电脑。", hi=hi))
        apps = [{"name": _app_name(a), "min": int(round(sec / 60))}
                for a, sec in sorted(per_app.items(), key=lambda kv: -kv[1])[:8] if sec >= 60]
        return JSONResponse({"greeting": greet, "stats": [
            {"num": _fmt_min(active), "lab": t("在电脑前")}, {"num": _fmt_min(away), "lab": t("离开 / 休息")},
            {"num": t("{n} 条", n=added_today), "lab": t("今天新记住的事")}], "timeline": timeline, "apps": apps})

    # ---- 记忆 ----
    async def memory(self, request: Request) -> Response:
        store = self.core.store
        q = request.query_params.get("q", "").strip()
        hist = request.query_params.get("history") == "1"
        if q:
            facts = [h.fact for h in rank.search(store, q, 30, include_history=hist, record_recall=False)]
        else:
            facts = list(reversed(store.current_facts()))[:300]
        p = store.persona()
        return JSONResponse({
            "persona": [ln for ln in p["content"].splitlines() if ln.strip()] if p else [],
            "personaMeta": t("第 {v} 版 · {time} 由 {who} 更新", v=p["id"], time=p["created_at"][5:16].replace("T", " "),
                             who=_who(p["source"]))
            if p else t("还没有核心画像，会在每天最后一次整理时慢慢形成。"),
            "facts": [{"id": f["id"], "text": f["text"], "cat": _cat(f["category"]), "catKey": f["category"], "src": export.speaker_name(f.get("speaker")),
                       "srcKey": f.get("speaker") or "pc",
                       "imp": 1 if f["importance"] < 0.4 else 2 if f["importance"] < 0.7 else 3,
                       "when": f["valid_at"][5:10], "confirmed": bool(f["confirmed"]),
                       "gone": (t("{day} 不再成立：{why}", day=f["invalid_at"][5:10], why=f["invalid_reason"] or "")
                                if f["invalid_at"] else None)}
                      for f in facts],
        })

    # ---- 写入日志 ----
    async def audit(self, request: Request) -> Response:
        out = []
        for a in self.core.store.audit_log(300):
            d = json.loads(a["detail"])
            what = d.get("text") or d.get("reason") or d.get("name") or d.get("note") or a["target"]
            out.append({"id": a["id"], "t": a["at"][11:19], "day": a["at"][:10], "who": _who(a["actor"]),
                        "act": _act(a["action"]), "actKey": a["action"], "what": what, "undone": bool(a["undone_at"]),
                        "undoable": a["action"] in ("add_fact", "invalidate_fact", "reinforce_fact", "set_persona")})
        return JSONResponse(out)

    async def undo(self, request: Request) -> Response:
        try:
            msg = self.core.store.undo(request.path_params["aid"])
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"message": msg})

    # ---- 设置 ----
    async def settings(self, request: Request) -> Response:
        s = self.core.settings
        if request.method == "POST":
            body = await request.json()
            changes = {k: v for k, v in body.items() if k in SETTING_KEYS}
            if "organize_brain" in body:
                changes["organizer"] = {"deepseek": "deepseek", "claude": "claude_cli"}.get(body["organize_brain"], "none")
            if "chat_brain" in changes and changes["chat_brain"] not in ("deepseek", "antigravity"):
                return JSONResponse({"error": t("这个 AI 暂时还不能用来聊天")}, status_code=400)
            if "antigravity_model" in changes and not re.fullmatch(r"[A-Za-z0-9._\-]{1,64}", str(changes["antigravity_model"])):
                return JSONResponse({"error": t("不认识这个模型")}, status_code=400)
            if "timezone" in changes and not clock.is_valid(str(changes["timezone"])):
                return JSONResponse({"error": t("不认识这个地区")}, status_code=400)
            if "language" in changes and changes["language"] not in ("", *i18n.LANGS):
                return JSONResponse({"error": t("不支持这种语言")}, status_code=400)
            if "raw_retention_days" in changes and not config.is_valid_retention(changes["raw_retention_days"]):
                return JSONResponse({"error": t("原始记录保留天数要在 {a} 到 {b} 之间", a=config.RETENTION_MIN,
                                                b=config.RETENTION_MAX)}, status_code=400)
            if "chat_in_memory" in changes and not isinstance(changes["chat_in_memory"], bool):
                return JSONResponse({"error": t("设置的值不对")}, status_code=400)
            if "organize_times" in changes:
                if not changes["organize_times"]:
                    return JSONResponse({"error": t("至少要留一个整理时间")}, status_code=400)
                for tm in changes["organize_times"]:
                    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", tm):
                        return JSONResponse({"error": t("整理时间「{v}」格式不对，应为 时:分", v=tm)}, status_code=400)
            key = (body.get("deepseek_api_key") or "").strip()
            if key:
                changes["deepseek_api_key_protected"] = vault.protect(key)
            self.core.update_settings(**changes)
        return JSONResponse({
            "organizer": s.organizer, "organize_times": s.organize_times, "blocked_apps": s.blocked_apps,
            "blocked_keywords": s.blocked_keywords, "raw_retention_days": s.raw_retention_days,
            "autostart": s.autostart, "chat_brain": s.chat_brain, "collect_enabled": s.collect_enabled,
            "language": s.language, "timezone": s.timezone, "chat_in_memory": s.chat_in_memory,
            "keySaved": bool(s.deepseek_api_key_protected),
            "model": self._model_text(), "modelInstalled": self.core.model_installed(),
            "modelEnabled": self.core.store.embedder is not None,
        })

    async def timezones(self, request: Request) -> Response:
        """可选的地区列表，每个带当前的 UTC 偏移（如 +08:00），设置页的下拉提示用。"""
        from datetime import datetime, timezone as _tz
        from zoneinfo import ZoneInfo
        now = datetime.now(_tz.utc)
        cc = clock.zone_countries()
        return JSONResponse([{"id": z, "offset": now.astimezone(ZoneInfo(z)).strftime("%z"), "cc": cc.get(z, "")}
                             for z in clock.zones()])

    async def brains(self, request: Request) -> Response:
        return JSONResponse(detect_brains(self.core.settings))

    async def install(self, request: Request) -> Response:
        """一键安装：只认程序里写死的几个名字，命令也是写死的。"""
        brain = request.path_params["brain"]
        if brain not in _chat.INSTALLERS:
            return JSONResponse({"error": t("不认识这个名字")}, status_code=400)
        try:
            _chat.open_install_window(brain)
        except OSError as e:
            return JSONResponse({"error": t("打不开 PowerShell：{e}", e=e)}, status_code=500)
        return JSONResponse({"ok": True, "message": t("已经打开 PowerShell 窗口，按里面的提示操作就行")})

    async def organize(self, request: Request) -> Response:
        threading.Thread(target=self.core.scheduler.run_now, kwargs={"final_of_day": False}, daemon=True).start()
        return JSONResponse({"message": t("开始整理……")})

    # ---- 向量模型：下载 → 校验 → 启用（给已有记忆建索引）----
    def _model_text(self) -> str:
        if self.core.store.embedder is not None:
            return t("已启用")
        return t("已下载，还没启用") if self.core.model_installed() else t("还没下载")

    async def model_status(self, request: Request) -> Response:
        return JSONResponse({"text": self._model_text(), "installed": self.core.model_installed(),
                             "enabled": self.core.store.embedder is not None, "job": self.model_job})

    async def model_download(self, request: Request) -> Response:
        if self.model_job.get("state") in ("downloading", "indexing"):
            return JSONResponse({"message": t("已经在进行中")})
        job = self.model_job = {"state": "downloading", "file": "", "done": 0, "total": 0}

        def on_dl(name: str, done: int, total: int) -> None:
            job.update(file=name, done=done, total=total)

        def on_idx(done: int, total: int) -> None:
            job.update(state="indexing", done=done, total=total)

        def work() -> None:
            try:
                if not self.core.model_installed():
                    from awy import paths as _p
                    from awy.memory import embed
                    embed.download(_p.models_dir(), on_dl)
                job["state"] = "indexing"
                msg = self.core.enable_embedder(on_idx)
                job.update(state="done", message=msg)
            except Exception as e:  # 网络断了、校验失败等：告诉页面，已下载的部分保留，下次接着下
                job.update(state="error", message=f"{type(e).__name__}: {e}")
        threading.Thread(target=work, name="model-download", daemon=True).start()
        return JSONResponse({"message": t("开始下载")})

    # ---- 聊天 ----
    async def chat_send(self, request: Request) -> Response:
        body = await request.json()
        text = str(body.get("text", ""))[:4000]

        def gen():  # 一行一个 JSON 事件，页面边收边显示
            for ev in self.chat.send(text):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        return StreamingResponse(gen(), media_type="application/x-ndjson")

    async def chat_warmup(self, request: Request) -> Response:
        self.chat.warmup()
        return JSONResponse({"ok": True})

    async def chat_history(self, request: Request) -> Response:
        before = request.query_params.get("before") or None
        if before and not re.fullmatch(r"\d{4}-\d{2}-\d{2}:\d{1,7}", before):
            return JSONResponse({"error": "bad cursor"}, status_code=400)
        try:
            limit = max(1, min(int(request.query_params.get("limit", "30")), 100))
        except ValueError:
            limit = 30
        return JSONResponse(load_page(before, limit))

    # ---- 头像、壁纸等偏好 ----
    async def prefs_get(self, request: Request) -> Response:
        out: dict[str, Any] = {}
        for name in PREF_IMAGES:
            f = paths.prefs_dir() / f"{name}.jpg"
            if f.exists():
                out[name] = "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode("ascii")
        meta = paths.prefs_dir() / "prefs.json"
        if meta.exists():
            out.update(json.loads(meta.read_text(encoding="utf-8")))
        return JSONResponse(out)

    async def prefs_set(self, request: Request) -> Response:
        name = request.path_params["name"]
        if name in PREF_IMAGES:
            f = paths.prefs_dir() / f"{name}.jpg"
            if request.method == "DELETE":
                f.unlink(missing_ok=True)
                return JSONResponse({"ok": True})
            body = await request.json()
            m = re.fullmatch(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", str(body.get("data", "")))
            if not m:
                return JSONResponse({"error": t("只接受 JPEG 图片")}, status_code=400)
            try:
                raw = base64.b64decode(m.group(1), validate=True)
            except binascii.Error:
                return JSONResponse({"error": t("图片数据损坏")}, status_code=400)
            if len(raw) > PREF_IMAGES[name] or not raw.startswith(b"\xff\xd8"):
                return JSONResponse({"error": t("图片太大或格式不对")}, status_code=400)
            f.write_bytes(raw)
            return JSONResponse({"ok": True})
        if name in PREF_FREE or name in PREF_CHOICES or name in PREF_PERCENT:
            meta = paths.prefs_dir() / "prefs.json"
            data = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            if request.method == "DELETE":
                data.pop(name, None)
            else:
                value = (await request.json()).get("value")
                if name in PREF_CHOICES and value not in PREF_CHOICES[name]:
                    return JSONResponse({"error": t("未知的偏好")}, status_code=400)
                if name in PREF_PERCENT:
                    if isinstance(value, bool):   # 先查：int(True) 会变成 1
                        return JSONResponse({"error": t("未知的偏好")}, status_code=400)
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        return JSONResponse({"error": t("未知的偏好")}, status_code=400)
                    if not 0 <= value <= 100:
                        return JSONResponse({"error": t("未知的偏好")}, status_code=400)
                data[name] = value
            meta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return JSONResponse({"ok": True})
        return JSONResponse({"error": t("未知的偏好")}, status_code=404)

    # ---- 检查更新（只在用户点按钮时联网）----
    async def update_check(self, request: Request) -> Response:
        try:
            info = await run_in_threadpool(updater.check, self.core.settings.update_repo)
        except updater.UpdateError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        self._update_info = info
        return JSONResponse({k: v for k, v in info.items() if k not in ("asset", "sha256")})

    async def update_install(self, request: Request) -> Response:
        info = getattr(self, "_update_info", None)
        if not info or not info.get("newer"):
            return JSONResponse({"error": t("请先点「检查更新」")}, status_code=400)
        if self.update_job.get("state") in ("downloading", "installing"):
            return JSONResponse({"message": t("已经在进行中")})
        job = self.update_job = {"state": "downloading", "done": 0, "total": info.get("size", 0)}

        def work() -> None:
            try:
                exe = updater.download(info, lambda d, tot: job.update(done=d, total=tot))
                job["state"] = "installing"
                updater.run_installer(exe)
                if self.on_quit:   # 安装包需要替换程序文件，先让出来；装好后它会把程序重新打开
                    threading.Timer(1.5, self.on_quit).start()
            except updater.UpdateError as e:
                job.update(state="error", message=str(e))
            except Exception as e:
                job.update(state="error", message=f"{type(e).__name__}: {e}")
        threading.Thread(target=work, name="update", daemon=True).start()
        return JSONResponse({"message": t("开始下载")})

    async def update_status(self, request: Request) -> Response:
        return JSONResponse(self.update_job)

    # ---- 导出 TXT（存到「文档\AlwaysWithYou 导出」，并在资源管理器里选中它）----
    async def export_txt(self, request: Request) -> Response:
        kind = request.path_params["kind"]
        if kind == "memory":
            text = export.memory_text(self.core.store)
        elif kind == "log":
            text = export.log_text(self.core.store, _act, _who)
        else:
            return JSONResponse({"error": t("不认识这个名字")}, status_code=400)
        f = export.save(kind, text)
        try:
            export.reveal(f)
        except OSError:
            pass
        return JSONResponse({"path": str(f), "message": t("已导出到：{path}", path=str(f))})

    # ---- 浏览器扩展：随安装包带，用户确认后复制到自选文件夹（决定 0011）----
    async def browser_status(self, request: Request) -> Response:
        import time as _time
        seen = self.core.browser.last_seen
        return JSONResponse({"connected": bool(seen) and _time.time() - seen < 180,
                             "minutesAgo": int((_time.time() - seen) // 60) if seen else None,
                             "error": self.core.browser_server.error})

    async def browser_install(self, request: Request) -> Response:
        import shutil
        src = paths.extension_dir()
        if not (src / "manifest.json").exists():
            return JSONResponse({"error": t("找不到程序自带的浏览器扩展")}, status_code=500)
        if self.pick_folder:
            folder = await run_in_threadpool(self.pick_folder)
            if not folder:
                return JSONResponse({"cancelled": True})
        else:   # 没有桌面窗口（开发时的网页模式）：放到「文档」里
            folder = str(export.export_dir().parent)
        dest = Path(folder) / "AlwaysWithYou-browser-extension"
        try:
            dest.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
        except OSError as e:
            return JSONResponse({"error": t("复制失败：{e}", e=e)}, status_code=500)
        try:
            export.reveal(dest / "manifest.json")
        except OSError:
            pass
        return JSONResponse({"path": str(dest)})

    # ---- 手机（决定 0014）----
    async def phone_status(self, request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(self.core.phone_status))

    async def phone_enable(self, request: Request) -> Response:
        body = await request.json()
        await run_in_threadpool(self.core.set_phone_enabled, bool(body.get("enabled")))
        return JSONResponse(await run_in_threadpool(self.core.phone_status))

    async def phone_pair(self, request: Request) -> Response:
        """POST：生成新的配对码（10 分钟有效）；DELETE：作废当前的配对码。"""
        if request.method == "DELETE":
            self.core.phone.cancel_pairing()
        elif not self.core.settings.phone_enabled:
            return JSONResponse({"error": t("先打开「接收手机数据」")}, status_code=400)
        else:
            await run_in_threadpool(self.core.phone.start_pairing)
        return JSONResponse(await run_in_threadpool(self.core.phone_status))

    async def phone_unpair(self, request: Request) -> Response:
        body = await request.json()
        if not self.core.phone.remove_device(str(body.get("id", ""))):
            return JSONResponse({"error": t("没有这台手机")}, status_code=404)
        return JSONResponse(await run_in_threadpool(self.core.phone_status))

    # ---- 第一次打开：风险确认 → 引导（决定 0012）----
    async def terms_accept(self, request: Request) -> Response:
        await run_in_threadpool(self.core.accept_terms)
        return JSONResponse({"ok": True})

    async def onboarded(self, request: Request) -> Response:
        body = await request.json()
        self.core.update_settings(onboarded=bool(body.get("done", True)))
        return JSONResponse({"ok": True})

    # ---- 记忆库：位置、导出、存档、搬家（决定 0012）----
    async def library_info(self, request: Request) -> Response:
        return JSONResponse({"path": str(paths.data_dir()), "canMove": paths.can_move(),
                             "readme": library._names()["readme"], "archives": library.list_archives(),
                             "job": self.lib_job})

    async def library_open(self, request: Request) -> Response:
        """打开数据文件夹，并选中「记忆库说明.md」。"""
        try:
            f = library.write_folder_readme()
            export.reveal(f)
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"ok": True})

    async def library_export(self, request: Request) -> Response:
        dest = export.export_dir() / f"{library._names()['export']}-{clock.now():%Y%m%d-%H%M%S}.zip"
        try:
            m = await run_in_threadpool(lambda: library.build_zip(dest, self.core.store))
        except (OSError, library.LibraryError) as e:
            return JSONResponse({"error": t("导出失败：{e}", e=e)}, status_code=500)
        try:
            export.reveal(dest)
        except OSError:
            pass
        return JSONResponse({"path": str(dest), "facts": m["facts"], "chats": m["chats"],
                             "message": t("已导出到：{path}", path=str(dest))})

    async def library_import(self, request: Request) -> Response:
        if not self.pick_zip:
            return JSONResponse({"error": t("只有桌面版能选择文件")}, status_code=400)
        f = await run_in_threadpool(self.pick_zip)
        if not f:
            return JSONResponse({"cancelled": True})
        try:
            r = await run_in_threadpool(library.import_archive, Path(f))
        except library.LibraryError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except OSError as e:
            return JSONResponse({"error": t("复制失败：{e}", e=e)}, status_code=500)
        return JSONResponse({**r, "archives": library.list_archives()})

    async def library_archives_open(self, request: Request) -> Response:
        d = paths.archives_dir()
        try:
            zips = sorted(d.glob("*.zip"))
            if zips:
                export.reveal(zips[0])
            else:
                export.open_folder(d)
        except OSError:
            pass
        return JSONResponse({"ok": True})

    async def library_enable(self, request: Request) -> Response:
        name = str((await request.json()).get("name", ""))
        try:
            await run_in_threadpool(lambda: library.validate(library.archive_path(name)))
        except library.LibraryError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return self._maintenance(t("正在启用选中的记忆库"), lambda progress: library.enable_archive(name, progress))

    async def library_move_pick(self, request: Request) -> Response:
        if not self.pick_folder:
            return JSONResponse({"error": t("只有桌面版能选择文件夹")}, status_code=400)
        folder = await run_in_threadpool(self.pick_folder)
        if not folder:
            return JSONResponse({"cancelled": True})
        try:
            dest = await run_in_threadpool(library.plan_move, Path(folder))
        except library.LibraryError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        self._move_dest = dest
        return JSONResponse({"dest": str(dest), "from": str(paths.data_dir())})

    async def library_move(self, request: Request) -> Response:
        dest = self._move_dest
        if dest is None:
            return JSONResponse({"error": t("请先选择新位置")}, status_code=400)
        self._move_dest = None
        return self._maintenance(t("正在把记忆库搬到新位置"), lambda progress: library.move_data(dest, progress))

    async def library_job(self, request: Request) -> Response:
        return JSONResponse(self.lib_job)

    def _maintenance(self, title: str, work: Any) -> Response:
        """换记忆库 / 搬家：先停下采集、聊天和记忆库，做完（或失败）后重启程序。"""
        if self.lib_job.get("state") == "running":
            return JSONResponse({"error": t("已经在进行中")}, status_code=409)
        job = self.lib_job = {"state": "running", "title": title, "stage": "", "done": 0, "total": 0}

        def progress(stage: str, done: int, total: int) -> None:
            job.update(stage=stage, done=done, total=total)

        def run() -> None:
            import gc
            from awy.core import close_logging
            try:
                self.chat.close()
                self.core.stop()
                self.core.store.embedder = None   # 放开向量模型文件
                gc.collect()
                close_logging()
                work(progress)
                job.update(state="restarting")
            except library.LibraryError as e:
                job.update(state="error", message=str(e))
            except Exception as e:
                job.update(state="error", message=f"{type(e).__name__}: {e}")
            if self.on_restart:   # 不管成没成功都要重启：各部分已经停了
                threading.Timer(2.5, self.on_restart).start()
            else:
                job["manual"] = True
        threading.Thread(target=run, name="library-job", daemon=True).start()
        return JSONResponse({"ok": True})

    async def quit(self, request: Request) -> Response:
        if self.on_quit:
            threading.Timer(0.2, self.on_quit).start()   # 先把回复发出去再退出
        return JSONResponse({"ok": True})

    async def menu_hide(self, request: Request) -> Response:
        if self.on_menu_hide:
            self.on_menu_hide()
        return JSONResponse({"ok": True})

    async def show(self, request: Request) -> Response:
        if self.on_show:
            self.on_show()
        return JSONResponse({"ok": True})


class _Guard:
    """ASGI 中间件：钥匙、Host、Origin 三道检查（只针对 /api）。"""

    def __init__(self, app: Any, token: str, port: int) -> None:
        self.app = app
        self.token = token.encode()
        self.hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}
        self.origins = {f"http://127.0.0.1:{port}".encode(), f"http://localhost:{port}".encode()}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"host") not in self.hosts:
                return await _deny(send, 403, "bad host")
            origin = headers.get(b"origin")
            if origin and origin not in self.origins:
                return await _deny(send, 403, "cross-origin")
            if scope["path"].startswith("/api/") and not hmac.compare_digest(headers.get(b"x-awy-token", b""), self.token):
                return await _deny(send, 401, "bad token")
        await self.app(scope, receive, send)


async def _deny(send: Any, status: int, msg: str) -> None:
    body = json.dumps({"error": msg}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _organizer_to_brain(org: str) -> str:
    return {"deepseek": "deepseek", "claude_cli": "claude"}.get(org, "none")


def _next_slot(times: list[str]) -> str:
    now = clock.now().strftime("%H:%M")
    later = sorted(t for t in times if t > now)
    return later[0] if later else (sorted(times)[0] if times else "—")
