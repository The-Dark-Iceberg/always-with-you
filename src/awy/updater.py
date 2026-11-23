"""检查更新：只在用户点「检查更新」时，去公开的发布仓库（GitHub Releases）看有没有新版本。

流程：
1. check()：读发布仓库的 releases 列表，找版本号最大的那个，和本机版本比较。
2. 用户在界面上点「是」后，download()：下载安装包，边下边算 SHA-256，和 GitHub 给的校验码对比，对不上就删掉、不安装。
3. run_installer()：静默运行新安装包（覆盖安装，记忆和设置都保留），程序自己退出；装好后安装包会把程序重新打开。

安全（见 docs/SECURITY.md）：
- 只访问写死的发布仓库；请求里不带任何个人信息（User-Agent 是固定的程序名）。
- 只认名字是 AlwaysWithYou-Setup-<版本>.exe 的附件；下载地址必须是 GitHub 的域名；大小有上限。
- 必须有校验码（GitHub 自动给的 digest，或发布说明里的 SHA256 行）且对得上才安装。没有校验码的版本只提示去网页下载。
- 校验码能防下载过程中被篡改或损坏，防不了发布仓库本身被盗号（这个只能靠保护好 GitHub 账号，以后可加代码签名）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from awy import __version__, paths

log = logging.getLogger(__name__)

RELEASES_REPO = "The-Dark-Iceberg/always-with-you"   # 源码仓库公开后，安装包直接发在它的 Releases 里（决定 0010 补充）
API = "https://api.github.com/repos/{repo}/releases?per_page=20"
USER_AGENT = "AlwaysWithYou-updater"
ALLOWED_HOSTS = {"github.com", "api.github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"}
MAX_SIZE = 300 * 1024 * 1024
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA_LINE = re.compile(r"SHA-?256[^0-9a-fA-F]{0,20}([0-9a-fA-F]{64})", re.IGNORECASE)


class UpdateError(Exception):
    """给用户看的错误（文字已经是当前语言）。"""


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = _TAG.match(v.strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def _host_ok(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and (u.hostname or "") in ALLOWED_HOSTS


def check(repo: str = RELEASES_REPO, client: httpx.Client | None = None) -> dict:
    """返回 {current, latest, newer, prerelease, notes, published, page, size, canInstall, asset, sha256}。"""
    from awy.i18n import t
    own = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=True)
    try:
        r = client.get(API.format(repo=repo), headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    except httpx.HTTPError as e:
        raise UpdateError(t("连不上 GitHub：{e}", e=type(e).__name__)) from e
    finally:
        if own:
            client.close()
    if r.status_code == 404:
        raise UpdateError(t("还没有找到发布仓库（{repo}）", repo=repo))
    if r.status_code != 200:
        raise UpdateError(t("GitHub 返回错误 {code}", code=r.status_code))
    best, best_v = None, None
    for rel in r.json():
        v = parse_version(str(rel.get("tag_name", "")))
        if rel.get("draft") or v is None:
            continue
        if best_v is None or v > best_v:
            best, best_v = rel, v
    current = parse_version(__version__) or (0, 0, 0)
    if best is None:
        return {"current": __version__, "latest": None, "newer": False}
    latest = ".".join(map(str, best_v))
    want = f"AlwaysWithYou-Setup-{latest}.exe"
    asset = next((a for a in best.get("assets") or [] if a.get("name") == want), None)
    sha = None
    if asset and str(asset.get("digest", "")).startswith("sha256:"):
        sha = asset["digest"].split(":", 1)[1].lower()
    if not sha:
        m = _SHA_LINE.search(best.get("body") or "")
        sha = m.group(1).lower() if m else None
    return {
        "current": __version__, "latest": latest, "newer": best_v > current,
        "prerelease": bool(best.get("prerelease")), "notes": (best.get("body") or "")[:4000],
        "published": (best.get("published_at") or "")[:10], "page": best.get("html_url", ""),
        "size": asset.get("size", 0) if asset else 0,
        "canInstall": bool(asset and sha and _host_ok(asset.get("browser_download_url", ""))),
        "asset": asset.get("browser_download_url") if asset else None, "sha256": sha,
    }


def download(info: dict, progress: Callable[[int, int], None] | None = None,
             client: httpx.Client | None = None) -> Path:
    """下载并校验。成功返回安装包路径；校验不对就删掉并报错。"""
    from awy.i18n import t
    url, sha = info.get("asset"), info.get("sha256")
    if not url or not sha or not _host_ok(url):
        raise UpdateError(t("这个版本没有可校验的安装包，为了安全不自动安装，请到发布页面手动下载"))
    folder = paths.data_dir() / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / f"AlwaysWithYou-Setup-{info['latest']}.exe"
    part = final.with_suffix(".part")
    h = hashlib.sha256()
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True)
    try:
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as r:
            if not _host_ok(str(r.url)):
                raise UpdateError(t("下载地址不是 GitHub，已停止"))
            if r.status_code != 200:
                raise UpdateError(t("下载失败（{code}）", code=r.status_code))
            total = int(r.headers.get("content-length") or info.get("size") or 0)
            if total > MAX_SIZE:
                raise UpdateError(t("安装包大得不正常，已停止"))
            done = 0
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    done += len(chunk)
                    if done > MAX_SIZE:
                        raise UpdateError(t("安装包大得不正常，已停止"))
                    h.update(chunk)
                    f.write(chunk)
                    if progress:
                        progress(done, total)
    except httpx.HTTPError as e:
        part.unlink(missing_ok=True)
        raise UpdateError(t("下载中断：{e}", e=type(e).__name__)) from e
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    finally:
        if own:
            client.close()
    if h.hexdigest() != sha:
        part.unlink(missing_ok=True)
        raise UpdateError(t("安装包校验码对不上，可能下载出错或被篡改，已删除，没有安装"))
    final.unlink(missing_ok=True)
    part.rename(final)
    return final


def run_installer(exe: Path) -> None:
    """静默覆盖安装（/SILENT 会显示进度条，但不问问题）。记忆和设置不受影响：覆盖安装不会运行卸载程序。
    安装包装完会自动重新打开本程序（installer.iss 里 Check: WizardSilent 那一行）。"""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, cwd=str(exe.parent), close_fds=True,
                     env={k: v for k, v in os.environ.items() if not k.startswith("AWY_")})
