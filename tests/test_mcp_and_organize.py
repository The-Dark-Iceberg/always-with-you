import json

import anyio
import httpx

from awy.config import Settings
from awy.mcp_servers import asgi_app, build_read_server, build_write_server
from awy.ops import ReadOps, WriteOps
from awy.organize import deepseek


def _tools(server):
    from mcp.client.client import Client

    async def go():
        async with Client(server) as c:
            return [t.name for t in (await c.list_tools()).tools]
    return anyio.run(go)


def _call(server, name, args):
    from mcp.client.client import Client

    async def go():
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return "".join(getattr(x, "text", "") for x in r.content)
    return anyio.run(go)


def test_read_server_cannot_write(store):
    read = build_read_server(ReadOps(store, Settings()))
    names = set(_tools(read))
    assert names == {"get_user_context", "search_memory", "recall_period", "leave_note"}
    write = build_write_server(WriteOps(store, "t"))
    assert {"add_fact", "invalidate_fact", "update_persona"} <= set(_tools(write))


def test_read_tools_work(store):
    store.add_fact("用户喜欢吃火锅", actor="t", category="preference", importance=0.8)
    read = build_read_server(ReadOps(store, Settings()))
    assert "火锅" in _call(read, "get_user_context", {})
    assert "火锅" in _call(read, "search_memory", {"query": "火锅"})
    assert "收件箱" in _call(read, "leave_note", {"kind": "remember", "content": "用户说他对花生过敏"})
    assert store.pending_inbox()[0]["source"] == "chat"
    assert "kind 只能是" in _call(read, "leave_note", {"kind": "delete", "content": "x"})


def test_http_requires_token_and_rejects_origin(store):
    app = asgi_app(build_read_server(ReadOps(store, Settings())), "secret-token")

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            r1 = await c.post("/mcp", json=body)
            r2 = await c.post("/mcp", json=body, headers={"Authorization": "Bearer wrong"})
            r3 = await c.post("/mcp", json=body, headers={"Authorization": "Bearer secret-token",
                                                         "Origin": "https://evil.example"})
            return r1.status_code, r2.status_code, r3.status_code
    assert anyio.run(go) == (401, 401, 403)


def _scripted_deepseek(script):
    """假的 DeepSeek：按顺序返回预先写好的回复，并记录收到的请求。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        step = script[len(seen) - 1]
        if isinstance(step, str):
            msg = {"role": "assistant", "content": step}
        else:
            msg = {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                for i, (n, a) in enumerate(step)]}
        return httpx.Response(200, json={"choices": [{"message": msg}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_deepseek_organizer_loop(store):
    ep = store.add_episode("pc_summary", "# 摘要\n- 10:00–12:00 Code.exe：memory.py", None, None)
    note = store.add_inbox("remember", "用户说他对花生过敏", "chat")
    client, seen = _scripted_deepseek([
        [("list_pending", {})],
        [("find_similar_facts", {"text": "用户对花生过敏"})],
        [("add_fact", {"text": "用户对花生过敏", "category": "health", "importance": 0.9,
                       "inbox_id": note, "confirmed": True}),
         ("add_fact", {"text": "用户在开发记忆库项目", "category": "state", "importance": 0.5,
                       "episode_id": ep})],
        [("mark_processed", {"episode_ids": [ep], "inbox_ids": [note]})],
        "新增 2 条。",
    ])
    res = deepseek.run(WriteOps(store, "deepseek"), api_key="k", base_url="https://x", model="m",
                       task="整理", client=client)
    assert res.ok and res.summary == "新增 2 条。" and res.prompt_tokens == 500
    assert {f["text"] for f in store.current_facts()} == {"用户对花生过敏", "用户在开发记忆库项目"}
    assert store.pending_episodes() == [] and store.pending_inbox() == []
    assert seen[0]["messages"][0]["role"] == "system" and "整理规则" in seen[0]["messages"][0]["content"]
    assert all(a["actor"] == "deepseek" for a in store.audit_log())


def test_deepseek_bad_tool_args_reported_back(store):
    client, seen = _scripted_deepseek([[("add_fact", {"text": "x", "category": "bogus", "importance": 1})], "好"])
    deepseek.run(WriteOps(store, "deepseek"), api_key="k", base_url="https://x", model="m", task="t", client=client)
    assert "category 必须是" in seen[1]["messages"][-1]["content"]


def test_deepseek_step_limit(store):
    client, _ = _scripted_deepseek([[("list_pending", {})]] * 5)
    res = deepseek.run(WriteOps(store, "d"), api_key="k", base_url="https://x", model="m", task="t",
                       max_steps=3, client=client)
    assert not res.ok and "步数上限" in res.summary
