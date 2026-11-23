"""浏览器扩展的接收端（决定 0011）。

扩展（browser-extension/）把「当前在看的网页」发到本机 127.0.0.1:<browser_port>/browser/page。这里负责：
- 只认我们自己的扩展：请求的 Origin 必须是 chrome-extension://<固定 ID>（manifest 里的 key 决定了 ID）。
  网页伪造不了 Origin，所以别的网站没法往这里塞数据。
- 只记 https；去掉网址里的全部参数和 # 后面的部分；参数里的搜索词先提取出来再去掉。
- 标题过打码；标题或域名命中「不记录的关键词」的，只记成「[隐私网页]」。
- 只在变化时写一条原始记录 {"type": "web", "url", "domain", "title", "search"?}；浏览器不在前面时写 {"type": "web", "state": "off"}。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from awy import privacy, rawlog
from awy.config import Settings

log = logging.getLogger(__name__)

EXTENSION_ID = "doibcaigkbpobgfglncikhllpfdnghdc"   # 由 browser-extension/manifest.json 的 key 算出来，改 key 要同步改这里
ALLOWED_ORIGINS = {f"chrome-extension://{EXTENSION_ID}", f"extension://{EXTENSION_ID}"}
MAX_BODY = 8192

# 常见搜索：域名（结尾匹配）→ 参数名。路径限定的写在 path 里。
SEARCH_PARAMS: list[tuple[str, str | None, tuple[str, ...]]] = [
    ("google.", "/search", ("q",)),
    ("bing.com", "/search", ("q",)),
    ("baidu.com", "/s", ("wd", "word")),
    ("duckduckgo.com", None, ("q",)),
    ("sogou.com", "/web", ("query",)),
    ("so.com", "/s", ("q",)),
    ("search.bilibili.com", None, ("keyword",)),
    ("zhihu.com", "/search", ("q",)),
    ("youtube.com", "/results", ("search_query",)),
    ("douban.com", "/search", ("q", "search_text")),
    ("github.com", "/search", ("q",)),
    ("xiaohongshu.com", "/search_result", ("keyword",)),
    ("weibo.com", None, ("q",)),
    ("s.weibo.com", None, ("q",)),
]


def clean(url: str, title: str, blocked_keywords: list[str]) -> dict[str, str] | None:
    """把扩展发来的网址整理成要记的内容。不该记（不是 https、格式不对）返回 None。"""
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return None
    if u.scheme != "https" or not u.hostname:
        return None
    host = u.hostname.lower()
    domain = host[4:] if host.startswith("www.") else host
    title = (title or "").strip()
    if privacy.is_blocked("", f"{domain} {title}", [], blocked_keywords):
        return {"domain": "[隐私网页]", "url": "", "title": ""}
    search = ""
    params = parse_qs(u.query, keep_blank_values=False)
    for suffix, path, keys in SEARCH_PARAMS:
        if suffix.endswith("."):   # google. → google.com / google.co.uk / www.google.com.hk
            hit = re.search(r"(^|\.)" + re.escape(suffix) + r"[a-z]{2,3}(\.[a-z]{2})?$", host) is not None
        else:
            hit = host == suffix or host.endswith("." + suffix)
        if hit and (path is None or u.path.startswith(path)):
            for k in keys:
                if params.get(k):
                    search = unquote(params[k][0]).strip()[:200]
                    break
        if search:
            break
    port = f":{u.port}" if u.port and u.port != 443 else ""
    clean_url = f"https://{host}{port}{u.path or '/'}"      # 参数和 # 后面的全部去掉
    out = {"domain": domain, "url": privacy.mask(clean_url), "title": privacy.mask(title)[:300]}
    if search:
        out["search"] = privacy.mask(search)
    return out


class BrowserBridge:
    """接收扩展的数据。last_seen：最近一次收到的时间（设置页显示「已连接」用）。"""

    def __init__(self, get_settings: Callable[[], Settings], sink: Callable[[dict], None] = rawlog.append) -> None:
        self._get_settings = get_settings
        self._sink = sink
        self.last_seen = 0.0
        self._last: tuple | None = None
        self.app = Starlette(routes=[Route("/browser/page", self.page, methods=["POST"]),
                                     Route("/browser/ping", self.ping)])

    def _origin_ok(self, request: Request) -> bool:
        return request.headers.get("origin", "") in ALLOWED_ORIGINS

    async def ping(self, request: Request) -> Response:
        if not self._origin_ok(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"ok": True})

    async def page(self, request: Request) -> Response:
        if not self._origin_ok(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return JSONResponse({"error": "too large"}, status_code=413)
        try:
            data: dict[str, Any] = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"error": "bad json"}, status_code=400)
        self.last_seen = time.time()
        s = self._get_settings()
        if not s.collect_enabled:
            return JSONResponse({"ok": True, "recorded": False})
        info = None if data.get("off") else clean(str(data.get("url", "")), str(data.get("title", "")), s.blocked_keywords)
        ev = {"type": "web", **info} if info else {"type": "web", "state": "off"}
        key = tuple(sorted(ev.items()))
        if key == self._last:
            return JSONResponse({"ok": True, "recorded": False})
        self._last = key
        try:
            self._sink({"ts": rawlog.now_iso(), "src": "browser", **ev})
        except OSError:
            log.exception("写原始记录失败")
        return JSONResponse({"ok": True, "recorded": True})
