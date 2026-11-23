"""桌面外壳：pywebview 窗口（用 Windows 自带的 Edge WebView2 显示 ui/ 页面）+ pystray 托盘图标。

- 关闭窗口 = 缩到托盘；托盘菜单「退出」才真正退出。
- 只允许运行一个：第二次打开时，叫已经在运行的那个显示窗口，然后自己退出。
- 页面通过本机接口（webapi.py）拿数据，钥匙每次启动随机生成，只放在窗口地址里。
"""

from __future__ import annotations

import ctypes
import json
import logging
import secrets
import socket
import sys
import threading

import httpx

from awy import paths
from awy.i18n import t
from awy.core import Core
from awy.mcp_servers import ServerThread
from awy.webapi import WebApi
from awy import traymenu

log = logging.getLogger(__name__)
MUTEX_NAME = "Local\\AlwaysWithYou-single-instance"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _runtime_file():
    return paths.data_dir() / "runtime.json"


def _already_running(wait: float = 0) -> bool:
    """用 Windows 命名互斥量判断是否已经有一个在运行。wait > 0 时最多等这么多秒让旧的退出（重启时用）。"""
    if sys.platform != "win32":
        return False
    import time
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    deadline = time.time() + wait
    while True:
        h = k32.CreateMutexW(None, False, MUTEX_NAME)
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            return False                    # 自己拿到了：句柄留着，一直到程序退出
        k32.CloseHandle(ctypes.c_void_p(h))   # 放开这个句柄，否则旧的退出后互斥量也不会消失
        if time.time() >= deadline:
            return True
        time.sleep(0.5)


def _restart_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--restarted"]
    from pathlib import Path
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else sys.executable), "-m", "awy", "--restarted"]


def _wake_existing() -> None:
    try:
        rt = json.loads(_runtime_file().read_text(encoding="utf-8"))
        httpx.post(f"http://127.0.0.1:{rt['port']}/api/show", headers={"X-AWY-Token": rt["token"]}, timeout=3)
    except Exception:
        log.exception("叫醒已运行的实例失败")


def start_web(core: Core) -> tuple[WebApi, ServerThread, str]:
    """启动界面用的本机接口，返回 (api, 服务线程, 窗口要打开的地址)。"""
    port, token = _free_port(), secrets.token_urlsafe(32)
    api = WebApi(core, token, port)
    server = ServerThread(api.app, port, "web-ui")
    server.start()
    rt = _runtime_file()
    rt.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")
    return api, server, f"http://127.0.0.1:{port}/?t={token}"


def _window_size() -> tuple[int, int, tuple[int, int]]:
    """窗口 1200×800，但不超过屏幕的 90%。返回 (宽, 高, 最小尺寸)。
    注意：本进程不声明 DPI 感知，Windows 会按显示缩放（如 150%）自动放大，所以这里用的是「逻辑像素」，
    不要再乘缩放比例（2026-11-20 实测：GetSystemMetrics 在 150% 缩放的 2560×1600 屏上返回 1707×1067）。"""
    sw, sh = 1920, 1080
    if sys.platform == "win32":
        try:
            sw, sh = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        except (AttributeError, OSError):
            pass
    return min(1200, int(sw * 0.9)), min(800, int(sh * 0.9)), (820, 560)


def _tray_image():
    """托盘图标：ui/img/tray.png（由 packaging/make_icon.py 从角色图裁出脸部）。找不到就用暖色圆 +「陪」字。"""
    from PIL import Image, ImageDraw, ImageFont
    try:
        return Image.open(paths.ui_dir() / "img" / "tray.png").convert("RGBA")
    except OSError:
        pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(232, 130, 90, 255))
    for name in ("simkai.ttf", "msyh.ttc", "simhei.ttf"):
        try:
            font = ImageFont.truetype(name, 38)
            d.text((32, 33), "陪", font=font, fill="white", anchor="mm")
            break
        except OSError:
            continue
    return img


def run_desktop(minimized: bool = False, restarted: bool = False) -> int:
    if _already_running(wait=30 if restarted else 0):
        _wake_existing()
        return 0

    import pystray
    import webview

    core = Core()
    api, web_server, url = start_web(core)
    w, h, min_size = _window_size()
    window = webview.create_window(t("一个时刻陪着你的AI"), url, width=w, height=h, min_size=min_size,
                                   hidden=minimized and core.terms_accepted,   # 还没确认风险说明：开机自启也要弹出来
                                   background_color="#f5f1e8")
    # 托盘右键菜单：一个藏着的小窗口，右键时弹出（见 traymenu.py）
    menu_win = webview.create_window(traymenu.TITLE, url.replace("/?t=", "/menu.html?t=", 1),
                                     width=traymenu.SIZE[0], height=traymenu.SIZE[1], frameless=True, easy_drag=False,
                                     resizable=False, on_top=True, hidden=True, shadow=True, background_color="#f5f1e8")
    tray_menu = traymenu.TrayMenu(menu_win)
    api.on_menu_hide = tray_menu.hide

    def pick_folder() -> str | None:   # 「安装浏览器扩展」时选保存位置
        r = window.create_file_dialog(webview.FileDialog.FOLDER)
        return r[0] if r else None

    api.pick_folder = pick_folder

    def pick_zip() -> str | None:   # 「导入记忆库压缩包」
        r = window.create_file_dialog(webview.FileDialog.OPEN, file_types=(t("记忆库压缩包 (*.zip)"),))
        return r[0] if r else None

    api.pick_zip = pick_zip
    quitting = threading.Event()

    def show() -> None:
        window.show()
        window.restore()

    def on_closing() -> bool:
        if quitting.is_set():
            return True
        window.hide()
        return False  # 不关闭，只是藏起来

    window.events.closing += on_closing

    def on_menu_closing() -> bool:   # 菜单窗口被 Alt+F4 之类关掉时：只收起，不真的关
        if quitting.is_set():
            return True
        tray_menu.hide()
        return False

    menu_win.events.closing += on_menu_closing
    api.on_show = show

    def toggle_collect(icon, item) -> None:
        core.update_settings(collect_enabled=not core.settings.collect_enabled)

    def organize(icon, item) -> None:
        threading.Thread(target=core.scheduler.run_now, daemon=True).start()
        icon.notify(t("开始整理……完成后会提醒你"), t("一个时刻陪着你的AI"))

    def quit_app(icon, item) -> None:
        quitting.set()
        icon.stop()
        try:
            api.chat.close()
            web_server.stop()
            core.stop()
        finally:
            _runtime_file().unlink(missing_ok=True)
            try:
                menu_win.destroy()
            finally:
                window.destroy()

    menu = pystray.Menu(   # 备用：自绘菜单出问题时才会出现
        pystray.MenuItem(lambda item: t("打开主界面"), lambda icon, item: show(), default=True),
        pystray.MenuItem(lambda item: t("暂停记录") if core.settings.collect_enabled else t("继续记录"), toggle_collect),
        pystray.MenuItem(lambda item: t("立即整理一次"), organize),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item: t("退出"), quit_app),
    )
    icon = traymenu.make_icon_class(pystray)("AlwaysWithYou", _tray_image(), t("一个时刻陪着你的AI"), menu)
    icon.on_right = tray_menu.popup   # 右键弹手绘菜单；没准备好时退回下面这个系统菜单
    core.on_message = lambda m: icon.notify(m[:200], t("一个时刻陪着你的AI"))
    api.on_quit = lambda: quit_app(icon, None)   # 开始安装更新后退出，让安装包替换文件

    def restart() -> None:   # 换记忆库 / 搬家之后：开一个新的自己（它会等这个退出），然后退出
        import subprocess
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(_restart_command(), creationflags=flags, close_fds=True)
        quit_app(icon, None)

    api.on_restart = restart
    core.scheduler._on_result = core.on_message
    core.start()
    icon.run_detached()
    for m in core.startup_notices:   # 比如「上次换记忆库没换完，已自动换回」
        try:
            core.on_message(m)
        except Exception:
            log.warning("启动提醒没发出去", exc_info=True)
    webview.start(private_mode=True)
    if not quitting.is_set():  # 窗口被系统强制关闭等情况，也要收尾
        quit_app(icon, None)
    return 0
