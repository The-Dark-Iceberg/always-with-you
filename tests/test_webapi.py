"""界面接口：安全检查（钥匙 / Host / Origin）和各页面的数据。"""

import base64
import json
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from awy import rawlog

PORT = 48999
TOKEN = "test-token"


@pytest.fixture
def api(monkeypatch, tmp_path):
    import awy.core as core_mod
    monkeypatch.setattr(core_mod.ServerThread, "start", lambda self: None)   # 测试里不真的起 MCP 服务
    from awy.core import Core
    from awy.webapi import WebApi
    core = Core()
    w = WebApi(core, TOKEN, PORT)
    client = TestClient(w.app, base_url=f"http://127.0.0.1:{PORT}")
    client.headers.update({"X-AWY-Token": TOKEN})
    yield core, client
    core.store.close()


def test_security_checks(api):
    core, c = api
    assert c.get("/api/status").status_code == 200
    assert c.get("/api/status", headers={"X-AWY-Token": "wrong"}).status_code == 401
    assert c.get("/api/status", headers={"Host": "evil.example:48999"}).status_code == 403          # DNS 重绑定
    assert c.get("/api/status", headers={"Origin": "https://evil.example"}).status_code == 403      # 跨站
    assert c.get("/api/status", headers={"Origin": f"http://127.0.0.1:{PORT}"}).status_code == 200
    r = c.get("/", headers={"X-AWY-Token": ""})            # 页面本身不需要钥匙（里面没有数据）
    assert r.status_code == 200 and "陪着你" in r.text


def test_today_and_memory_and_log(api):
    core, c = api
    now = datetime.now().astimezone()
    rawlog.append({"ts": now.replace(hour=0, minute=5, second=0).isoformat(), "src": "pc", "type": "window",
                   "app": "Code.exe", "title": "a.py"})
    t = c.get("/api/today").json()
    assert t["timeline"][0]["app"] == "Code.exe" and "在电脑前" in t["stats"][0]["lab"]
    fid = core.store.add_fact("用户喜欢猫", actor="deepseek", category="preference", importance=0.8)
    m = c.get("/api/memory").json()
    assert m["facts"][0]["text"] == "用户喜欢猫" and m["facts"][0]["cat"] == "偏好" and m["facts"][0]["imp"] == 3
    log = c.get("/api/log").json()
    entry = next(x for x in log if x["act"] == "新增")
    assert entry["who"] == "DeepSeek" and entry["undoable"]
    assert "撤回" in c.post(f"/api/log/{entry['id']}/undo").json()["message"]
    assert core.store.get_fact(fid)["retracted_at"]


def test_settings_key_is_write_only(api):
    core, c = api
    r = c.post("/api/settings", json={"deepseek_api_key": "sk-fake-1234567890", "organize_times": ["09:00"],
                                      "read_token": "hacked"}).json()
    assert r["keySaved"] is True and "sk-fake" not in json.dumps(r)        # 钥匙只写不读
    assert core.settings.read_token != "hacked"                            # 不允许改的字段被忽略
    assert c.post("/api/settings", json={"organize_times": ["25:99"]}).status_code == 400
    assert c.post("/api/settings", json={"chat_brain": "codex"}).status_code == 400
    c.post("/api/settings", json={"organize_brain": "claude"})
    assert core.settings.organizer == "claude_cli"


def test_prefs_images(api):
    core, c = api
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 100
    data = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
    assert c.post("/api/prefs/avatar", json={"data": data}).json()["ok"]
    assert c.get("/api/prefs").json()["avatar"] == data
    assert c.post("/api/prefs/avatar", json={"data": "data:image/png;base64,AAAA"}).status_code == 400
    assert c.post("/api/prefs/wallpaper", json={"data": "data:image/jpeg;base64," + base64.b64encode(b"notjpeg").decode()}).status_code == 400
    assert c.post("/api/prefs/../../config", json={}).status_code in (404, 405)
    c.post("/api/prefs/veil", json={"value": 40})
    assert c.get("/api/prefs").json()["veil"] == 40
    c.delete("/api/prefs/avatar")
    assert "avatar" not in c.get("/api/prefs").json()


def test_chat_with_fake_deepseek(api, monkeypatch):
    """聊天：假的 DeepSeek 先调用一次读记忆工具，再回答。"""
    core, c = api
    from awy import vault
    core.update_settings(deepseek_api_key_protected=vault.protect("sk-fake"), chat_brain="deepseek")
    core.store.add_fact("用户喜欢番茄炒蛋", actor="t", category="preference", importance=0.8)
    replies = iter([
        {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "get_user_context", "arguments": "{}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "你喜欢番茄炒蛋呀。"}}]},
    ])
    seen = []
    import httpx

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))
    real_client = httpx.Client
    monkeypatch.setattr("awy.chat.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    lines = [json.loads(x) for x in c.post("/api/chat", json={"text": "我喜欢吃什么？"}).text.splitlines()]
    assert [x["type"] for x in lines] == ["tool", "tool", "delta", "done"]   # 程序先读记忆 → 模型又查了一次 → 回答
    assert lines[2]["text"] == "你喜欢番茄炒蛋呀。"
    assert "番茄炒蛋" in seen[0]["messages"][0]["content"]          # 记忆直接放进了系统提示（省一轮来回）
    assert "get_user_context" not in json.dumps(seen[0]["tools"])  # 不再让模型自己去读一遍
    assert "番茄炒蛋" in seen[1]["messages"][-1]["content"]        # 工具结果也照样交给了模型
    hist = c.get("/api/chat/history").json()["items"]
    assert [h["role"] for h in hist[-2:]] == ["me", "ai"]


def test_chat_deepseek_streaming(api, monkeypatch):
    """DeepSeek 流式回复：文字一段一段出来；工具调用分好几段拼起来也能正确执行。"""
    core, c = api
    from awy import vault
    core.update_settings(deepseek_api_key_protected=vault.protect("sk-fake"), chat_brain="deepseek")
    import httpx

    def sse(*chunks):
        body = "".join("data: " + json.dumps({"choices": [{"delta": d}]}, ensure_ascii=False) + "\n\n" for d in chunks)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(body + "data: [DONE]\n\n").encode())
    replies = iter([
        sse({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "search_", "arguments": '{"que'}}]},
            {"tool_calls": [{"index": 0, "function": {"name": "memory", "arguments": 'ry": "猫"}'}}]}),
        sse({"content": "你"}, {"content": "喜欢"}, {"content": "猫。"}),
    ])
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return next(replies)
    real_client = httpx.Client
    monkeypatch.setattr("awy.chat.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    lines = [json.loads(x) for x in c.post("/api/chat", json={"text": "我喜欢什么动物？"}).text.splitlines()]
    assert [x["text"] for x in lines if x["type"] == "delta"] == ["你", "喜欢", "猫。"]
    assert seen[0]["stream"] is True
    call = seen[1]["messages"][-2]["tool_calls"][0]
    assert call["function"] == {"name": "search_memory", "arguments": '{"query": "猫"}'} and call["id"] == "c1"
    assert c.get("/api/chat/history").json()["items"][-1]["text"] == "你喜欢猫。"


def test_model_download_flow(api, monkeypatch):
    """模型下载：用假的下载函数，检查进度能从「下载中」走到「完成」，失败时能报错。"""
    import time
    core, c = api
    from awy.memory import embed
    calls = []

    def fake_download(root, progress):
        for done in (1, 2):
            progress("model.onnx_data", done, 2)
        calls.append(root)
    monkeypatch.setattr(embed, "download", fake_download)
    monkeypatch.setattr(core, "enable_embedder", lambda progress=None: "向量模型已启用，已为 0 条记忆建立索引")
    assert c.get("/api/model").json()["text"] == "还没下载"
    c.post("/api/model/download")
    for _ in range(50):
        job = c.get("/api/model").json()["job"]
        if job["state"] == "done":
            break
        time.sleep(0.05)
    assert job["state"] == "done" and calls

    def broken(root, progress):
        raise ConnectionError("网络断了")
    monkeypatch.setattr(embed, "download", broken)
    c.post("/api/model/download")
    for _ in range(50):
        job = c.get("/api/model").json()["job"]
        if job["state"] == "error":
            break
        time.sleep(0.05)
    assert job["state"] == "error" and "网络断了" in job["message"]


def test_acp_permission_policy():
    from awy.chat import AcpBrain
    assert AcpBrain._is_memory_tool({"title": "Run mcp_awy-memory_get_user_context"})
    assert not AcpBrain._is_memory_tool({"title": "Run shell command: del /s"})
    assert not AcpBrain._is_memory_tool({"title": "Run mcp_comfy-mcp_launch_comfyui"})


def test_one_click_install(api, monkeypatch):
    """一键安装：只认写死的名字；命令来自程序本身，界面传不进命令。"""
    core, c = api
    from awy import chat
    opened = []
    monkeypatch.setattr(chat, "open_install_window", opened.append)
    assert c.post("/api/install/antigravity").json()["ok"] and opened == ["antigravity"]
    assert c.post("/api/install/calc.exe").status_code == 400
    assert c.post("/api/install/antigravity", headers={"X-AWY-Token": "wrong"}).status_code == 401
    assert opened == ["antigravity"]
    script = chat.install_script("antigravity")
    assert "irm https://antigravity.google/cli/install.ps1 | iex" in script and "-NoExit" not in script
    assert "Get-Command npm" in chat.install_script("codex")
    monkeypatch.setattr(chat, "find_agy", lambda: None)
    card = next(b for b in c.get("/api/brains").json() if b["id"] == "antigravity")
    assert card["install"]["cmd"].startswith("irm https://antigravity.google/")


def test_chat_history_pages(api):
    """聊天记录分页：每次给 30 条，往上翻拿更早的，跨天也连得上，没有重复也没有遗漏。"""
    core, c = api
    from awy import paths
    d = paths.chats_dir()
    for day, n in (("2026-11-18", 25), ("2026-11-19", 0), ("2026-11-20", 40)):
        if n:
            (d / f"{day}.jsonl").write_text("".join(json.dumps({"ts": f"{day}T10:00:00+08:00", "role": "me", "text": f"{day}#{i}"},
                                                              ensure_ascii=False) + "\n" for i in range(n)), encoding="utf-8")
    seen, before = [], None
    while True:
        page = c.get("/api/chat/history", params={"before": before} if before else {}).json()
        seen = [m["text"] for m in page["items"]] + seen
        if not page["more"]:
            break
        before = page["items"][0]["id"]
    assert len(seen) == 65 and len(set(seen)) == 65
    assert seen[0] == "2026-11-18#0" and seen[-1] == "2026-11-20#39"
    assert c.get("/api/chat/history", params={"before": "../../x"}).status_code == 400


def test_export_txt(api, monkeypatch, tmp_path):
    """导出 TXT：记忆按大分类、写入日志按天；写到导出文件夹（测试里换成临时目录），不弹资源管理器。"""
    core, c = api
    from awy import export
    out = tmp_path / "exports"
    out.mkdir()
    monkeypatch.setattr(export, "export_dir", lambda: out)
    opened = []
    monkeypatch.setattr(export, "reveal", opened.append)
    core.store.add_fact("用户喜欢猫", actor="deepseek", category="preference", importance=0.8)
    core.store.add_fact("用户性格内向", actor="deepseek", category="trait", importance=0.9)
    fid = core.store.add_fact("用户住在 A 宿舍", actor="deepseek", category="state", importance=0.5)
    core.store.invalidate_fact(fid, actor="deepseek", reason="搬到了 B 宿舍")
    r = c.post("/api/export/memory").json()
    text = (out / r["path"].split("\\")[-1].split("/")[-1]).read_text(encoding="utf-8-sig")
    assert text.index("性格") < text.index("偏好") and "用户喜欢猫" in text
    assert "已经不再成立" in text and "搬到了 B 宿舍" in text and opened
    r = c.post("/api/export/log").json()
    log = open(r["path"], encoding="utf-8-sig").read()
    assert "新增" in log and "用户喜欢猫" in log
    assert c.post("/api/export/../../etc").status_code in (400, 404, 405)
    assert c.post("/api/export/secrets").status_code == 400
    m = c.get("/api/memory").json()["facts"]
    assert {f["catKey"] for f in m} == {"preference", "trait"}
    assert c.get("/api/log").json()[0]["actKey"]
