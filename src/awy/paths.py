"""所有数据目录的唯一来源。

数据默认放在用户目录（%LOCALAPPDATA%\\AlwaysWithYou），不放在安装目录、不放在代码仓库里。
用户可以在设置里把记忆库搬到别的文件夹（决定 0012，见 library.py）：新位置记在默认目录的 location.json 里，
搬走以后默认目录里只留这一个小文件指路。
测试或便携运行时可以用环境变量 AWY_DATA_DIR 指向别的目录（这时不能搬家）。
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from awy import APP_NAME

_moved_to: Path | None = None   # location.json 里记的位置（读一次缓存起来；改了以后由 reload() 刷新）
_loaded = False


def default_dir() -> Path:
    """默认数据目录（也是 location.json 所在的地方）。设了 AWY_DATA_DIR 时就是它。"""
    override = os.environ.get("AWY_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME


def can_move() -> bool:
    return not os.environ.get("AWY_DATA_DIR")


def location_file() -> Path:
    return default_dir() / "location.json"


def read_location() -> dict:
    try:
        data = json.loads(location_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_location(data: dict) -> None:
    f = location_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)
    reload()


def reload() -> None:
    global _loaded
    _loaded = False


def data_dir() -> Path:
    global _moved_to, _loaded
    if not can_move():
        base = default_dir()
    else:
        if not _loaded:
            moved = str(read_location().get("data_dir") or "")
            _moved_to = Path(moved) if moved and Path(moved).is_absolute() and Path(moved).is_dir() else None
            _loaded = True
        base = _moved_to or default_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    return data_dir() / "config.json"


def raw_dir(day: date) -> Path:
    """某一天的原始记录文件夹：raw/YYYY-MM-DD/"""
    p = _sub("raw") / day.isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def summaries_dir(day: date) -> Path:
    p = _sub("summaries") / day.isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def memory_db() -> Path:
    return data_dir() / "memory.db"


def archives_dir() -> Path:
    """记忆存档：导入的记忆库压缩包、启用别的存档前自动备份的压缩包（决定 0012）。"""
    return _sub("archives")


def models_dir() -> Path:
    return _sub("models")


def logs_dir() -> Path:
    return _sub("logs")


def extension_dir() -> Path:
    """浏览器扩展（browser-extension/）：打包后在程序目录里，开发时在项目根目录。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "browser-extension"
    return Path(__file__).resolve().parents[2] / "browser-extension"


def ui_dir() -> Path:
    """界面文件（HTML/CSS/JS）所在位置：打包后在程序目录里，开发时在项目根目录的 ui/。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "ui"
    return Path(__file__).resolve().parents[2] / "ui"


def chats_dir() -> Path:
    return _sub("chats")


def prefs_dir() -> Path:
    """头像、壁纸等界面偏好图片。"""
    return _sub("prefs")


def agent_workdir(name: str) -> Path:
    """调用订阅制 Agent 时给它的私有空文件夹（里面只有陪伴说明，没有用户的任何文件）。"""
    p = _sub("agents") / name
    p.mkdir(parents=True, exist_ok=True)
    return p
