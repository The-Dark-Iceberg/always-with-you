"""界面脚本的语法检查：ui/js 里任何一个文件有语法错误，整个界面都会打不开（0.4.1 打包前就差点带上一个）。

用 Node 的 `node --check`（只检查语法，不运行）。电脑上没装 Node 时跳过。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

UI_JS = Path(__file__).resolve().parents[1] / "ui" / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="没装 Node，跳过界面脚本语法检查")
@pytest.mark.parametrize("script", sorted(UI_JS.glob("*.js")), ids=lambda p: p.name)
def test_ui_script_has_no_syntax_error(script):
    r = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
