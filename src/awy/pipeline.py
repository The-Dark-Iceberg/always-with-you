"""定时流程：生成摘要 → 存为 episode → 叫整理者整理。

默认每天 10:00 / 14:00 / 19:00 / 23:30 各一次（设置里可改）。
电脑关机或睡眠错过的时间点，下次启动后会补跑一次（只补最近一次，不会连跑好几次）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from typing import Callable

from awy import clock, i18n, paths, rawlog, summarize, vault
from awy.i18n import t
from awy.config import TERMS_VERSION, Settings
from awy.memory.store import MemoryStore
from awy.ops import WriteOps
from awy.organize import claude_cli, deepseek
from awy.organize.deepseek import RunResult

log = logging.getLogger(__name__)
SOURCE_PC = "pc_summary"
SOURCE_CHAT = "chat"
CHAT_FIRST_RUN_LOOKBACK = timedelta(hours=24)
FIRST_RUN_LOOKBACK = timedelta(hours=12)


def _parse_times(items: list[str]) -> list[time]:
    out = []
    for s in items:
        try:
            h, m = s.strip().split(":")
            out.append(time(int(h), int(m)))
        except ValueError:
            continue
    return sorted(out)


def last_slot_before(now: datetime, slots: list[time]) -> datetime | None:
    """now 之前（含）最近的一个整理时间点。"""
    for day_offset in (0, 1):
        d = now.date() - timedelta(days=day_offset)
        for t in reversed(slots):
            cand = datetime.combine(d, t, tzinfo=now.tzinfo)
            if cand <= now:
                return cand
    return None


def is_last_slot_of_day(at: datetime, slots: list[time]) -> bool:
    return bool(slots) and at.time() >= slots[-1]


def make_summary_episode(store: MemoryStore, now: datetime) -> int | None:
    """把「上次摘要结束」到 now 之间的电脑活动生成一份摘要，存成 episode。"""
    last_end = store.latest_episode_end(SOURCE_PC)
    start = datetime.fromisoformat(last_end) if last_end else now - FIRST_RUN_LOOKBACK
    if now - start < timedelta(minutes=5):
        return None
    text = summarize.summarize_range(start, now)
    (paths.summaries_dir(now.date()) / f"{now:%H%M}.md").write_text(text, encoding="utf-8")
    return store.add_episode(SOURCE_PC, text, start.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"))


SOURCE_PHONE = "phone_summary"
PHONE_FIRST_RUN_LOOKBACK = timedelta(days=3)


def make_phone_episode(store: MemoryStore, now: datetime) -> int | None:
    """把「上次整理之后新收到的手机数据」写成一份摘要，存成 episode（决定 0014）。
    period_start / period_end 是「收到的时间」范围，不是数据发生的时间：手机回家才上传，数据常常迟到。"""
    from awy.phone import PhoneState
    last_end = store.latest_episode_end(SOURCE_PHONE)
    start = datetime.fromisoformat(last_end) if last_end else now - PHONE_FIRST_RUN_LOOKBACK
    if start >= now:
        return None
    days = PhoneState().days_received(start, now)
    if not days:
        return None
    known = [e for d in days for e in rawlog.read_day(d) if e.get("src") == "phone" and e.get("type", "").startswith("phone_")]
    new = [e for e in known if (rx := _parse_iso(e.get("rx", ""))) and start <= rx < now]
    text = summarize.render_phone(new, known, start, now)
    if not text:
        return None
    (paths.summaries_dir(now.date()) / f"{now:%H%M}-phone.md").write_text(text, encoding="utf-8")
    # 精确到微秒（和 rx 一样）：只精确到秒的话，同一秒里收到的会在下次被再写一遍
    return store.add_episode(SOURCE_PHONE, text, start.isoformat(), now.isoformat())


def _parse_iso(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None
    return d if d and d.tzinfo else None


def skip_pending_chat(store: MemoryStore) -> int:
    """把还没整理的聊天 episode 和聊天 AI 留的普通便条标成「跳过」：关掉「聊天内容参与整理」后，它们不再交给整理 AI。
    用户亲口说的「记住」「纠正」便条照常整理。返回跳过了几项。"""
    from awy.ops import is_chat_item
    eps = [e["id"] for e in store.pending_episodes() if is_chat_item(e)]
    notes = [n["id"] for n in store.pending_inbox() if is_chat_item(n)]
    if eps or notes:
        store.mark_processed(eps, notes, "chat-off", "聊天不参与整理：跳过")
    return len(eps) + len(notes)


def make_chat_episode(store: MemoryStore, now: datetime, settings: Settings) -> int | None:
    """把「上次整理到的聊天」到 now 之间的聊天（用户和 AI 双方）存成一份 episode，和电脑活动一起整理（决定 0011）。"""
    if not settings.chat_in_memory:
        skip_pending_chat(store)   # 关掉之前排队、还没整理的聊天也不交给整理 AI
        return None
    from awy import chat
    last_end = store.latest_episode_end(SOURCE_CHAT)
    start = datetime.fromisoformat(last_end) if last_end else now - CHAT_FIRST_RUN_LOOKBACK
    since = _parse_iso(settings.chat_in_memory_since)
    if since and since > start:
        start = since              # 开关关着的那段时间的聊天不补读
    if start >= now:
        return None
    text = chat.render_chat_episode(chat.load_range(start, now), start, now)
    if not text:
        return None
    return store.add_episode(SOURCE_CHAT, text, start.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"))


def organize(store: MemoryStore, settings: Settings, *, final_of_day: bool) -> RunResult:
    if not store.pending_episodes() and not store.pending_inbox():
        return RunResult(True, t("没有待整理的内容"))
    task = ("现在开始整理。" + ("这是今天最后一次整理，请在最后按第 8 步考虑是否更新核心画像。"
                              if final_of_day else "这不是今天最后一次整理，不要更新核心画像。")
            + f" 现在时间：{clock.now().isoformat(timespec='minutes')}。"
            + f"事实、人物/项目简介和核心画像都用「{i18n.memory_language()}」写。")
    if settings.organizer == "deepseek":
        try:
            key = vault.unprotect(settings.deepseek_api_key_protected)
        except (OSError, ValueError) as e:
            return RunResult(False, t("读取 API Key 失败：{e}", e=e))
        return deepseek.run(WriteOps(store, "deepseek", chat_allowed=lambda: settings.chat_in_memory), api_key=key, base_url=settings.deepseek_base_url,
                            model=settings.deepseek_model, task=task, max_steps=settings.organizer_max_steps)
    if settings.organizer == "claude_cli":
        return claude_cli.run(settings, paths.data_dir(), task)
    return RunResult(False, t("未设置整理方式（设置里选择 DeepSeek 或 Claude Code）"))


class Scheduler:
    """后台线程，每 30 秒看一次是否到了整理时间。"""

    def __init__(self, store: MemoryStore, get_settings: Callable[[], Settings],
                 on_result: Callable[[str], None] | None = None) -> None:
        self.store = store
        self._get_settings = get_settings
        self._on_result = on_result or (lambda msg: None)
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._done_slot: datetime | None = None
        self._pruned_day = None   # 原始记录每天清理一次，和整理无关（整理时间清空了也照样清理）
        self.last_message = t("还没有整理过")
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_now(self, final_of_day: bool = False) -> str:
        """立即生成摘要并整理（界面上的按钮调用；在调用方线程里执行）。"""
        if self._get_settings().accepted_terms != TERMS_VERSION:
            # 还没确认风险说明：不管从哪里点的（托盘、界面按钮、定时），都不把任何内容交给 AI
            msg = t("还没确认风险说明，先不整理")
            self.last_message = msg
            self._on_result(msg)
            return msg
        if not self._busy.acquire(blocking=False):
            return t("正在整理中，请稍后")
        try:
            s = self._get_settings()
            now = clock.now()
            make_summary_episode(self.store, now)
            try:
                make_chat_episode(self.store, now, s)
            except Exception:   # 聊天这部分出问题不耽误电脑活动的整理
                log.exception("整理聊天记录出错，这次只整理电脑活动")
            try:
                make_phone_episode(self.store, now)
            except Exception:   # 手机这部分出问题也不耽误别的
                log.exception("整理手机数据出错，这次跳过手机")
            if not s.chat_in_memory:
                skip_pending_chat(self.store)   # 生成聊天的同时用户关掉了开关：刚生成的那份也不交出去
            res = organize(self.store, s, final_of_day=final_of_day)
            rawlog.prune(s.raw_retention_days)
            msg = (t("{time} 整理完成：{summary}", time=f"{now:%m-%d %H:%M}", summary=res.summary) if res.ok
                   else t("{time} 整理失败：{summary}", time=f"{now:%m-%d %H:%M}", summary=res.summary))
            if res.prompt_tokens:
                msg += t("（用量：输入 {inp} / 输出 {out} tokens）", inp=res.prompt_tokens, out=res.completion_tokens)
        except Exception as e:
            log.exception("整理出错")
            msg = t("整理出错：{e}", e=e)
        finally:
            self._busy.release()
        self.last_message = msg
        self._on_result(msg)
        return msg

    def prune_daily(self) -> list[str]:
        """按「原始记录保留天数」清理过期的原始记录，每天最多一次。"""
        today = clock.today()
        if self._pruned_day == today:
            return []
        self._pruned_day = today
        try:
            return rawlog.prune(self._get_settings().raw_retention_days)
        except Exception:   # 不管什么错都只记日志：不能让整个调度线程退出（那样定时整理也停了）
            log.exception("清理原始记录失败")
            return []

    def _run(self) -> None:
        self.prune_daily()
        while not self._stop.wait(30):
            try:
                self.prune_daily()
            except Exception:
                log.exception("每日清理出错")
            try:
                s = self._get_settings()
                slots = _parse_times(s.organize_times)
                now = clock.now()
                slot = last_slot_before(now, slots)
                if slot is None or slot == self._done_slot:
                    continue
                last_end = self.store.latest_episode_end(SOURCE_PC)
                if last_end and datetime.fromisoformat(last_end) >= slot:
                    self._done_slot = slot  # 这个时间点已经处理过（比如手动点过）
                    continue
                self._done_slot = slot
                self.run_now(final_of_day=is_last_slot_of_day(slot, slots))
            except Exception:
                log.exception("调度出错")
