"""把一段时间的原始记录合并成一页「摘要」。这是唯一会交给 AI 的东西。

原理（全部是确定性代码）：
1. 每条 window 事件持续到下一条事件为止，算出时长。
2. 同一个软件连续使用的片段合并成一个「时间段」，记下其中停留最久的几个标题。
3. 短于 MIN_SEGMENT_SECONDS 的碎片不单独列出，只计入统计。
4. away/back 之间算作离开电脑。
5. 其他来源各走各的时间线（决定 0011）：正在播放（media）、浏览器扩展看过的网页和搜索词（web）、最近打开的文件（file）。
   它们不打断窗口的时长计算。
6. 电脑睡眠 / 关机（决定 0012）：away(reason=sleep|shutdown) 到对应的 back 之间算离开，这段里残留的窗口记录作废；
   醒来不到 1 分钟又睡了（假醒），合并成一段。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from awy import clock, rawlog

MIN_SEGMENT_SECONDS = 60
MAX_TITLES_PER_SEGMENT = 3
MAX_TITLE_LEN = 60
STATE_TYPES = {"window", "away", "back", "paused", "resumed"}   # 窗口时间线只看这些
MEDIA_MIN_SECONDS = 30
WEB_MIN_SECONDS = 20
MAX_LIST = 20
POWER_REASONS = ("sleep", "shutdown")   # 电脑睡眠、关机
FAKE_WAKE_SECONDS = 60
STATE_LOOKBACK = timedelta(hours=36)    # 算某段时间开头的状态时往前多看多久（睡眠可能从前一天开始）


@dataclass
class Segment:
    start: datetime
    end: datetime
    app: str
    titles: dict[str, float] = field(default_factory=dict)  # 标题 -> 秒

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def _fmt_dur(sec: float) -> str:
    m = int(round(sec / 60))
    if m < 60:
        return f"{m} 分"
    h, m = divmod(m, 60)
    return f"{h} 小时 {m} 分" if m else f"{h} 小时"


def _short(t: str) -> str:
    t = t.strip()
    return t if len(t) <= MAX_TITLE_LEN else t[: MAX_TITLE_LEN - 1] + "…"


def _power_clean(timeline: list[tuple[datetime, dict[str, Any]]]
                 ) -> tuple[list[tuple[datetime, dict[str, Any]]], list[tuple[datetime, datetime, str]]]:
    """找出「电脑睡眠 / 关机」时间段（合并假醒），去掉段内残留的记录。返回 (整理后的时间线, [(开始, 结束, 原因)])。"""
    periods: list[list[Any]] = []
    for i, (t0, ev) in enumerate(timeline):
        if ev.get("type") != "away" or ev.get("reason") not in POWER_REASONS:
            continue
        back = next((t for t, e in timeline[i + 1:] if e.get("type") == "back" and e.get("reason") == ev["reason"]), None)
        if back is None or back <= t0:
            continue
        if periods and (t0 - periods[-1][1]).total_seconds() < FAKE_WAKE_SECONDS:
            periods[-1][1] = max(periods[-1][1], back)
        else:
            periods.append([t0, back, ev["reason"]])
    if not periods:
        return timeline, []
    keep = [(t, 0, e) for t, e in timeline
            if not any(a <= t < b for a, b, _ in periods)
            and not (e.get("reason") in POWER_REASONS and e.get("type") in ("away", "back"))]
    for a, b, why in periods:
        keep.append((a, 0, {"type": "away", "reason": why}))
        keep.append((b, -1, {"type": "back", "reason": why}))   # 同一时刻：先「醒来」再记窗口
    keep.sort(key=lambda x: (x[0], x[1]))
    return [(t, e) for t, _, e in keep], [(a, b, why) for a, b, why in periods]


def _timeline(events: list[dict[str, Any]], start: datetime,
              initial: dict[str, Any] | None) -> list[tuple[datetime, dict[str, Any]]]:
    tl: list[tuple[datetime, dict[str, Any]]] = []
    if initial is not None:
        tl.append((start, initial))
    for ev in events:
        if ev.get("type") in STATE_TYPES:
            tl.append((datetime.fromisoformat(ev["ts"]), ev))
    tl.sort(key=lambda x: x[0])
    return tl


def power_periods(events: list[dict[str, Any]], start: datetime, end: datetime,
                  initial: dict[str, Any] | None = None) -> list[tuple[datetime, datetime, str]]:
    """[start, end] 里的电脑睡眠 / 关机时间段（裁到这个范围内）。"""
    _, periods = _power_clean(_timeline(events, start, initial))
    return [(max(a, start), min(b, end), why) for a, b, why in periods if b > start and a < end]


def build_segments(events: list[dict[str, Any]], start: datetime, end: datetime,
                   initial: dict[str, Any] | None = None) -> tuple[list[Segment], float]:
    """返回 (使用片段列表, 离开电脑的总秒数)。initial 是 start 之前最后一条事件，用来确定开头的状态。
    events 里也可以带 start 之前的事件（会被裁掉），这样跨过 start 的睡眠也能认出来。"""
    timeline, _ = _power_clean(_timeline(events, start, initial))

    segments: list[Segment] = []
    away_seconds = 0.0
    for i, (t0, ev) in enumerate(timeline):
        t1 = timeline[i + 1][0] if i + 1 < len(timeline) else end
        t0, t1 = max(t0, start), min(t1, end)
        if t1 <= t0:
            continue
        dur = (t1 - t0).total_seconds()
        kind = ev.get("type")
        if kind in ("away", "paused"):
            away_seconds += dur
            continue
        if kind != "window":
            # back / resumed：状态延续到下一条 window，之间的时间不归属任何软件
            continue
        app = ev.get("app") or "未知"
        title = _short(ev.get("title") or "")
        if segments and segments[-1].app == app and (t0 - segments[-1].end) <= timedelta(seconds=5):
            seg = segments[-1]
            seg.end = t1
        else:
            seg = Segment(start=t0, end=t1, app=app)
            segments.append(seg)
        if title:
            seg.titles[title] = seg.titles.get(title, 0.0) + dur
    return segments, away_seconds


def _spans(events: list[dict[str, Any]], kind: str, start: datetime, end: datetime,
           initial: dict[str, Any] | None) -> list[tuple[datetime, datetime, dict[str, Any]]]:
    """某一类事件的时间线：每条持续到下一条同类事件（或 end）。返回 [(开始, 结束, 事件)]。"""
    tl = [(start, initial)] if initial is not None and initial.get("type") == kind else []
    tl += [(datetime.fromisoformat(e["ts"]), e) for e in events if e.get("type") == kind]
    out = []
    for i, (t0, ev) in enumerate(tl):
        t1 = tl[i + 1][0] if i + 1 < len(tl) else end
        t0, t1 = max(t0, start), min(t1, end)
        if t1 > t0:
            out.append((t0, t1, ev))
    return out


def _media_lines(events, start, end, initial) -> list[str]:
    """正在播放：合并连续的同一首歌 / 同一个视频。"""
    items: list[list[Any]] = []   # [开始, 结束, app, 标题, 歌手]
    for t0, t1, ev in _spans(events, "media", start, end, initial):
        if ev.get("state") != "playing":
            continue
        key = (ev.get("app", ""), ev.get("title", ""), ev.get("artist", ""))
        if items and tuple(items[-1][2:]) == key and (t0 - items[-1][1]) <= timedelta(seconds=10):
            items[-1][1] = t1
        else:
            items.append([t0, t1, *key])
    items = [x for x in items if (x[1] - x[0]).total_seconds() >= MEDIA_MIN_SECONDS]
    if not items:
        return []
    if len(items) > MAX_LIST:   # 太多就按标题汇总时长
        agg: dict[tuple, float] = defaultdict(float)
        for x in items:
            agg[tuple(x[2:])] += (x[1] - x[0]).total_seconds()
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:MAX_LIST]
        return [f"- {app}：{_short(title)}" + (f" - {artist}" if artist else "") + f"（共 {_fmt_dur(sec)}）"
                for (app, title, artist), sec in top]
    return [f"- {clock.to_local(a):%H:%M}–{clock.to_local(b):%H:%M} {app}：{_short(title)}"
            + (f" - {artist}" if artist else "") + f"（{_fmt_dur((b - a).total_seconds())}）"
            for a, b, app, title, artist in items]


def _web_lines(events, start, end, initial) -> tuple[list[str], list[str]]:
    """浏览器扩展：看过的网页（按停留时长）和搜索词。"""
    per_page: dict[tuple[str, str], float] = defaultdict(float)
    searches: list[str] = []
    seen_q: set[str] = set()
    for t0, t1, ev in _spans(events, "web", start, end, initial):
        if not ev.get("domain"):
            continue   # 浏览器不在前面 / 看的是 http 页面：不算
        per_page[(ev["domain"], _short(ev.get("title") or ""))] += (t1 - t0).total_seconds()
        q = (ev.get("search") or "").strip()
        if q and q.lower() not in seen_q:
            seen_q.add(q.lower())
            searches.append(f"- {clock.to_local(t0):%H:%M} 「{_short(q)}」（{ev['domain']}）")
    pages = [f"- {domain}" + (f" · {title}" if title else "") + f"（{_fmt_dur(sec)}）"
             for (domain, title), sec in sorted(per_page.items(), key=lambda kv: -kv[1]) if sec >= WEB_MIN_SECONDS]
    return pages[:MAX_LIST], searches[:MAX_LIST]


def _file_lines(events) -> list[str]:
    seen: dict[str, datetime] = {}
    for e in events:
        if e.get("type") == "file" and e.get("name") and e["name"] not in seen:
            seen[e["name"]] = datetime.fromisoformat(e["ts"])
    return [f"- {clock.to_local(t):%H:%M} {name}" for name, t in list(seen.items())[:MAX_LIST]]


def render(events: list[dict[str, Any]], start: datetime, end: datetime,
           initial: dict[str, Any] | None = None, initial_media: dict[str, Any] | None = None,
           initial_web: dict[str, Any] | None = None) -> str:
    segments, away = build_segments(events, start, end, initial)
    total_active = sum(s.seconds for s in segments)
    per_app: dict[str, float] = defaultdict(float)
    for s in segments:
        per_app[s.app] += s.seconds

    head = f"# 电脑活动摘要 {start:%Y-%m-%d %H:%M} – {end:%H:%M}"
    if start.date() != end.date():
        head = f"# 电脑活动摘要 {start:%Y-%m-%d %H:%M} – {end:%Y-%m-%d %H:%M}"
    lines = [head, ""]
    extra = _power_section(events, start, end, initial) + _extra_sections(events, start, end, initial_media, initial_web)
    if not segments:
        lines.append("- 这段时间没有电脑使用记录" + ("（离开或暂停采集 " + _fmt_dur(away) + "）" if away else "") + "。")
        return "\n".join(lines + extra) + "\n"

    slept = _power_seconds(events, start, end, initial)
    lines.append(f"- 在电脑前约 {_fmt_dur(total_active)}；离开或暂停约 {_fmt_dur(away)}"
                 + (f"（其中电脑睡眠 / 关机约 {_fmt_dur(slept)}）" if slept >= 60 else "") + "。")
    lines += ["", "## 按时间", ""]
    for s in segments:
        if s.seconds < MIN_SEGMENT_SECONDS:
            continue
        tops = sorted(s.titles.items(), key=lambda kv: -kv[1])[:MAX_TITLES_PER_SEGMENT]
        detail = "；".join(t for t, _ in tops)
        lines.append(f"- {clock.to_local(s.start):%H:%M}–{clock.to_local(s.end):%H:%M} {s.app}（{_fmt_dur(s.seconds)}）" + (f"：{detail}" if detail else ""))
    lines += ["", "## 按软件统计", ""]
    for app, sec in sorted(per_app.items(), key=lambda kv: -kv[1])[:10]:
        if sec >= MIN_SEGMENT_SECONDS:
            lines.append(f"- {app}：{_fmt_dur(sec)}")
    return "\n".join(lines + extra) + "\n"


POWER_NAMES = {"sleep": "电脑睡眠", "shutdown": "关机"}


def _power_seconds(events, start, end, initial) -> float:
    return sum((b - a).total_seconds() for a, b, _ in power_periods(events, start, end, initial))


def _power_section(events, start, end, initial) -> list[str]:
    items = [(a, b, why) for a, b, why in power_periods(events, start, end, initial) if (b - a).total_seconds() >= 60]
    if not items:
        return []
    return ["", "## 电脑睡眠 / 关机（这段时间没在用电脑）", ""] + [
        f"- {clock.to_local(a):%H:%M}–{clock.to_local(b):%H:%M} {POWER_NAMES[why]}（{_fmt_dur((b - a).total_seconds())}）"
        for a, b, why in items]


def _extra_sections(events, start, end, initial_media, initial_web) -> list[str]:
    out: list[str] = []
    media = _media_lines(events, start, end, initial_media)
    if media:
        out += ["", "## 在听 / 在看（包括后台播放）", ""] + media
    pages, searches = _web_lines(events, start, end, initial_web)
    if pages:
        out += ["", "## 看过的网页（浏览器扩展，按停留时长）", ""] + pages
    if searches:
        out += ["", "## 搜索过", ""] + searches
    files = _file_lines(events)
    if files:
        out += ["", "## 打开过的文件", ""] + files
    return out


def state_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """算 [start, end) 的窗口时间线要用的事件：多带上 start 之前一段（跨过 start 的睡眠、开头的状态）。"""
    return [e for e in rawlog.read_range(start - STATE_LOOKBACK, start) if e.get("type") in STATE_TYPES]


def summarize_range(start: datetime, end: datetime) -> str:
    events = state_events(start, end) + rawlog.read_range(start, end)
    return render(events, start, end, None,
                  rawlog.last_event_before(start, types={"media"}), rawlog.last_event_before(start, types={"web"}))


# ---- 手机（决定 0014）-------------------------------------------------------------
# 手机回家连上 Wi-Fi 才上传，数据常常「迟到」。所以手机摘要不按记录时间切，而是按「这次整理之前新收到的」来写：
# 使用片段只写新收到的；健康数据写那一天到目前为止收到的全部（手表晚同步时，步数会变多，以最新的为准）。

PHONE_MIN_SESSION = 120      # 按时间列出的手机使用片段至少 2 分钟
PHONE_MERGE_GAP = 120        # 同一个 App 间隔 2 分钟以内算同一段
PHONE_MAX_LINES = 30
WEEKDAYS = "一二三四五六日"


def phone_day(ev: dict[str, Any]) -> Any:
    """这条手机记录算哪一天：睡眠算醒来那天，其他按开始时间。"""
    t = ev["end"] if ev.get("type") == "phone_sleep" else ev["ts"]
    return clock.to_local(datetime.fromisoformat(t)).date()


def _phone_latest(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一条记录（同一个小时 / 同一次睡眠……）收到过好几次时，只留最后收到的。"""
    from awy.phone import event_key
    latest: dict[str, dict[str, Any]] = {}
    for ev in sorted(events, key=lambda e: e.get("rx", "")):
        latest[event_key(ev)] = ev
    return sorted(latest.values(), key=lambda e: e["ts"])


def _phone_usage_lines(apps: list[dict[str, Any]], screens: list[dict[str, Any]]) -> list[str]:
    out = ["", "### 手机使用", ""]
    if screens:
        on = sum((datetime.fromisoformat(s["end"]) - datetime.fromisoformat(s["ts"])).total_seconds() for s in screens)
        out.append(f"- 亮屏约 {_fmt_dur(on)}（{len(screens)} 次）")
    merged: list[list[Any]] = []   # [开始, 结束, 名字]
    for a in sorted(apps, key=lambda e: e["ts"]):
        t0, t1 = datetime.fromisoformat(a["ts"]), datetime.fromisoformat(a["end"])
        if merged and merged[-1][2] == a["app"] and (t0 - merged[-1][1]).total_seconds() <= PHONE_MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], t1)
        else:
            merged.append([t0, t1, a["app"]])
    per_app: dict[str, float] = defaultdict(float)
    for a in apps:
        per_app[a["app"]] += (datetime.fromisoformat(a["end"]) - datetime.fromisoformat(a["ts"])).total_seconds()
    long = [m for m in merged if (m[1] - m[0]).total_seconds() >= PHONE_MIN_SESSION]
    if long:
        out.append("- 按时间：")
        for t0, t1, name in long[:PHONE_MAX_LINES]:
            out.append(f"  - {clock.to_local(t0):%H:%M}–{clock.to_local(t1):%H:%M} {name}（{_fmt_dur((t1 - t0).total_seconds())}）")
        rest = len(merged) - min(len(long), PHONE_MAX_LINES)
        if rest > 0:
            out.append(f"  - 另外还有 {rest} 段较短或较零碎的使用")
    top = [(n, s) for n, s in sorted(per_app.items(), key=lambda kv: -kv[1]) if s >= 60][:10]
    if top:
        out.append("- 按应用：" + "；".join(f"{n} {_fmt_dur(s)}" for n, s in top))
    return out


def _phone_health_lines(events: list[dict[str, Any]]) -> list[str]:
    out = ["", "### 健康（截至目前收到的）", ""]
    hours = [e for e in events if e["type"] == "phone_health"]
    steps = [(e, e["steps"]) for e in hours if e.get("steps")]
    if steps:
        peak, n = max(steps, key=lambda x: x[1])
        h = clock.to_local(datetime.fromisoformat(peak["ts"]))
        out.append(f"- 步数：共 {sum(s for _, s in steps)} 步；最多的一小时是 {h:%H}:00–{(h + timedelta(hours=1)):%H}:00（{n} 步）")
    hr = [e for e in hours if e.get("hr_avg")]
    if hr:
        avg = round(sum(e["hr_avg"] for e in hr) / len(hr))
        lo = min(hr, key=lambda e: e.get("hr_min", e["hr_avg"]))
        hi = max(hr, key=lambda e: e.get("hr_max", e["hr_avg"]))
        at = lambda e: f"{clock.to_local(datetime.fromisoformat(e['ts'])):%H} 点左右"   # noqa: E731
        out.append(f"- 心率：各小时平均约 {avg} 次/分；最低 {lo.get('hr_min', lo['hr_avg'])}（{at(lo)}），"
                   f"最高 {hi.get('hr_max', hi['hr_avg'])}（{at(hi)}）")
    for s in (e for e in events if e["type"] == "phone_sleep"):
        t0, t1 = datetime.fromisoformat(s["ts"]), datetime.fromisoformat(s["end"])
        parts = [f"{name} {_fmt_dur(s.get(k, 0) * 60)}" for k, name in
                 (("deep", "深睡"), ("light", "浅睡"), ("rem", "快速眼动"), ("awake", "清醒")) if s.get(k)]
        out.append(f"- 睡眠：{clock.to_local(t0):%m-%d %H:%M} – {clock.to_local(t1):%H:%M}，共 {_fmt_dur((t1 - t0).total_seconds())}"
                   + (f"（{'、'.join(parts)}）" if parts else "") + (f"，记录来自{s['by']}" if s.get("by") else ""))
    return out if len(out) > 3 else []


def render_phone(new: list[dict[str, Any]], known: list[dict[str, Any]], start: datetime, end: datetime) -> str:
    """new：这次新收到的手机记录（rx 在 [start, end)）；known：涉及到的那几天收到过的全部手机记录。没有新的返回 ""。"""
    if not new:
        return ""
    lines = [f"# 手机活动摘要（{start:%m-%d %H:%M} – {end:%m-%d %H:%M} 收到的）", "",
             "- 来自手机端 AwyRead。手机回家连上 Wi-Fi 才会传，所以可能有前几天的内容；时间是事情实际发生的时间。"]
    for day in sorted({phone_day(e) for e in new}):
        today_new = [e for e in new if phone_day(e) == day]
        apps = [e for e in today_new if e["type"] == "phone_app"]
        screens = [e for e in today_new if e["type"] == "phone_screen"]
        body: list[str] = []
        if apps or screens:
            body += _phone_usage_lines(apps, screens)
        if any(e["type"] in ("phone_health", "phone_sleep") for e in today_new):
            body += _phone_health_lines(_phone_latest([e for e in known if phone_day(e) == day]))
        if body:
            lines += ["", f"## {day.month}月{day.day}日（周{WEEKDAYS[day.weekday()]}）"] + body
    return "\n".join(lines) + "\n"
