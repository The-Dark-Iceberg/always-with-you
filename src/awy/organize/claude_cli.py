"""用订阅制的 Claude Code（命令行无界面模式）执行整理。

状态：实验性，作者机器上还没装 claude 命令行，未实测。命令行参数以 Claude Code 官方文档为准，
如有变化只需改 build_command()。

原理：生成一个只包含「整理入口」的 MCP 配置文件，用 `claude -p` 启动，
并且只允许它使用记忆库的整理工具（不能执行命令、不能改文件）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from awy.config import Settings
from awy.i18n import t
from awy.organize import rules_text
from awy.organize.deepseek import RunResult

SERVER_NAME = "awy-organizer"


def find_claude() -> str | None:
    return shutil.which("claude")


def write_mcp_config(settings: Settings, path: Path) -> Path:
    cfg = {"mcpServers": {SERVER_NAME: {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.write_port}/mcp",
        "headers": {"Authorization": f"Bearer {settings.write_token}"},
    }}}
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_command(exe: str, mcp_config: Path, task: str) -> list[str]:
    prompt = rules_text() + "\n\n---\n\n" + task
    return [exe, "-p", prompt,
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--allowedTools", f"mcp__{SERVER_NAME}",
            "--output-format", "text"]


def run(settings: Settings, workdir: Path, task: str, timeout: int = 1800) -> RunResult:
    exe = find_claude()
    if not exe:
        return RunResult(False, t("没有找到 claude 命令行（Claude Code），请先安装或改用 DeepSeek 整理"))
    cfg = write_mcp_config(settings, workdir / "organizer-mcp.json")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        p = subprocess.run(build_command(exe, cfg, task), cwd=workdir, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        return RunResult(False, t("Claude Code 超过 {n} 秒没有完成，已停止", n=timeout))
    finally:
        cfg.unlink(missing_ok=True)  # 钥匙不留在磁盘上
    if p.returncode != 0:
        return RunResult(False, t("Claude Code 出错（{code}）：{detail}", code=p.returncode, detail=(p.stderr or p.stdout)[-500:]))
    return RunResult(True, (p.stdout or "").strip()[-1000:] or t("整理完成"))
