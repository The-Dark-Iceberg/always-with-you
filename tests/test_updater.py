"""检查更新：找最新版本、校验码必须对上才安装、只认 GitHub 的下载地址。全部用假的 GitHub，不联网。"""

import hashlib
import json

import httpx
import pytest

from awy import updater

BLOB = b"MZ fake installer bytes" * 100
SHA = hashlib.sha256(BLOB).hexdigest()


def release(tag, *, draft=False, pre=True, digest=True, body="更新说明", url=None):
    ver = tag.lstrip("v")
    name = f"AlwaysWithYou-Setup-{ver}.exe"
    asset = {"name": name, "size": len(BLOB),
             "browser_download_url": url or f"https://github.com/o/r/releases/download/{tag}/{name}"}
    if digest:
        asset["digest"] = "sha256:" + SHA
    return {"tag_name": tag, "draft": draft, "prerelease": pre, "body": body, "published_at": "2026-11-21T08:00:00Z",
            "html_url": f"https://github.com/o/r/releases/tag/{tag}", "assets": [asset]}


def client_for(releases, blob=BLOB, status=200):
    def handler(req):
        if req.url.host == "api.github.com":
            assert req.headers["user-agent"] == updater.USER_AGENT          # 不带任何个人信息
            return httpx.Response(status, json=releases)
        return httpx.Response(200, content=blob, headers={"content-length": str(len(blob))})
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_picks_highest_version_and_skips_drafts(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.2.0")
    info = updater.check("o/r", client_for([release("v0.3.0"), release("v9.9.9", draft=True), release("v0.10.0"),
                                            release("nightly")]))
    assert info["latest"] == "0.10.0" and info["newer"] and info["canInstall"] and info["sha256"] == SHA
    assert info["prerelease"] is True and info["published"] == "2026-11-21"


def test_not_newer_when_same_version(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.2.0")
    assert updater.check("o/r", client_for([release("v0.2.0")]))["newer"] is False
    assert updater.check("o/r", client_for([]))["latest"] is None


def test_repo_missing_gives_friendly_error():
    with pytest.raises(updater.UpdateError, match="o/r"):
        updater.check("o/r", client_for([], status=404))


def test_sha_from_release_notes_when_no_digest(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.1.0")
    info = updater.check("o/r", client_for([release("v0.2.0", digest=False, body=f"修复了一些问题\nSHA256: {SHA}")]))
    assert info["sha256"] == SHA and info["canInstall"]
    info = updater.check("o/r", client_for([release("v0.2.0", digest=False, body="没有校验码")]))
    assert not info["canInstall"]
    with pytest.raises(updater.UpdateError):
        updater.download(info)


def test_download_verifies_checksum(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.1.0")
    info = updater.check("o/r", client_for([release("v0.2.0")]))
    exe = updater.download(info, client=client_for([], blob=BLOB))
    assert exe.read_bytes() == BLOB and exe.name == "AlwaysWithYou-Setup-0.2.0.exe"
    with pytest.raises(updater.UpdateError, match="校验码"):
        updater.download(info, client=client_for([], blob=BLOB + b"tampered"))
    assert not list(exe.parent.glob("*.part"))                       # 对不上的文件已经删掉


def test_rejects_non_github_download(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.1.0")
    info = updater.check("o/r", client_for([release("v0.2.0", url="https://evil.example/x.exe")]))
    assert not info["canInstall"]
    with pytest.raises(updater.UpdateError):
        updater.download(info)


def test_update_api_flow(monkeypatch):
    """接口：检查 → 安装（下载、校验、运行安装包、让程序退出）；不把下载地址和校验码交给页面。"""
    import time

    import awy.core as core_mod
    monkeypatch.setattr(core_mod.ServerThread, "start", lambda self: None)
    from starlette.testclient import TestClient

    from awy.core import Core
    from awy.webapi import WebApi
    monkeypatch.setattr(updater, "__version__", "0.1.0")
    real_check = updater.check
    monkeypatch.setattr(updater, "check", lambda repo: real_check(repo, client_for([release("v0.2.0")])))
    ran, quit_called = [], []
    real_download = updater.download
    monkeypatch.setattr(updater, "download", lambda info, progress=None: real_download(info, progress, client_for([])))
    monkeypatch.setattr(updater, "run_installer", ran.append)
    core = Core()
    api = WebApi(core, "k", 48997)
    api.on_quit = lambda: quit_called.append(1)
    c = TestClient(api.app, base_url="http://127.0.0.1:48997")
    c.headers.update({"X-AWY-Token": "k"})
    try:
        assert c.post("/api/update/install").status_code == 400            # 没检查过不能装
        info = c.get("/api/update/check").json()
        assert info["newer"] and "sha256" not in info and "asset" not in info
        c.post("/api/update/install")
        for _ in range(50):
            if c.get("/api/update/status").json()["state"] in ("installing", "error"):
                break
            time.sleep(0.05)
        assert c.get("/api/update/status").json()["state"] == "installing" and ran
        time.sleep(1.7)
        assert quit_called
    finally:
        core.store.close()
