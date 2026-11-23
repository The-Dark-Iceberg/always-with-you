"""用 DeepSeek API（OpenAI 兼容格式）执行整理。

原理：把整理规则作为系统提示词，把写入工具交给模型；模型决定调用哪个工具，
本程序执行后把结果返回给模型，循环直到它不再调用工具，或者达到步数上限（防止失控花钱）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import httpx

from awy.i18n import t
from awy.ops import WRITE_TOOL_SCHEMAS, WriteOps, call_write_tool
from awy.organize import rules_text

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    ok: bool
    summary: str
    steps: int = 0
    tool_calls: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def run(ops: WriteOps, *, api_key: str, base_url: str, model: str, task: str, max_steps: int = 60,
        client: httpx.Client | None = None) -> RunResult:
    if not api_key:
        return RunResult(False, t("没有设置 DeepSeek API Key"))
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(120.0))
    messages: list[dict] = [
        {"role": "system", "content": rules_text()},
        {"role": "user", "content": task},
    ]
    res = RunResult(False, "")
    try:
        for step in range(1, max_steps + 1):
            r = client.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages, "tools": WRITE_TOOL_SCHEMAS, "temperature": 0.2},
            )
            if r.status_code != 200:
                res.summary = f"DeepSeek 返回错误 {r.status_code}：{r.text[:300]}"
                return res
            data = r.json()
            usage = data.get("usage") or {}
            res.prompt_tokens += int(usage.get("prompt_tokens", 0))
            res.completion_tokens += int(usage.get("completion_tokens", 0))
            msg = data["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            res.steps = step
            if not calls:
                res.ok = True
                res.summary = (msg.get("content") or "").strip() or "整理完成"
                return res
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                name = c["function"]["name"]
                out = call_write_tool(ops, name, c["function"].get("arguments") or "{}")
                res.tool_calls.append(name)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        res.summary = f"达到步数上限（{max_steps}），已停止；已完成的写入都保留，可在写入日志里查看"
        return res
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
        res.summary = f"整理出错：{type(e).__name__}: {e}"
        return res
    finally:
        if own:
            client.close()
