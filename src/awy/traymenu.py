"""托盘右键菜单：用一个无边框的小网页窗口（ui/menu.html）代替 Windows 自带的灰色菜单，和主界面一样是手绘风格。

- 右键托盘图标 → 窗口出现在鼠标旁边（右下角对着鼠标，超出屏幕就往里挪）。
- 点了某一项、按 Esc、或者点到别的地方（它不再是最前面的窗口）→ 自动收起。
- 不出现在任务栏和 Alt+Tab 里（WS_EX_TOOLWINDOW）。
- 万一这个窗口没准备好（比如还在加载），就退回 Windows 自带菜单，保证右键总有反应。

坐标：本进程不声明 DPI 感知，所有 Win32 坐标都是同一套「逻辑像素」，不用自己换算（见 desktop._window_size 的说明）。
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Any

log = logging.getLogger(__name__)

TITLE = "AWY-tray-menu"          # ui/menu.html 的 <title> 也是这个，靠它找到窗口
SIZE = (240, 292)                # 逻辑像素，和 menu.html 的内容高度对应

_HWND_TOPMOST = -1
_SWP_NOSIZE, _SWP_NOACTIVATE, _SWP_SHOWWINDOW = 0x0001, 0x0010, 0x0040
_GWL_EXSTYLE, _WS_EX_TOOLWINDOW, _WS_EX_APPWINDOW = -20, 0x00000080, 0x00040000
_GA_ROOT = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class TrayMenu:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.hwnd = 0
        self.visible = False
        self._styled = False
        self._u32 = ctypes.windll.user32
        self._u32.GetForegroundWindow.restype = wintypes.HWND
        self._u32.GetAncestor.restype = wintypes.HWND
        self._u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self._u32.FindWindowW.restype = wintypes.HWND
        self._u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        self._u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, wintypes.UINT]

    def _find(self) -> int:
        if not self.hwnd:
            self.hwnd = self._u32.FindWindowW(None, TITLE) or 0
        return self.hwnd

    def popup(self) -> bool:
        """在鼠标位置弹出。返回 False 表示没准备好（调用方改用 Windows 自带菜单）。"""
        u32 = self._u32
        hwnd = self._find()
        if not hwnd:
            return False
        if not self._styled:   # 不进任务栏 / Alt+Tab
            ex = u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            u32.SetWindowLongW(hwnd, _GWL_EXSTYLE, (ex | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW)
            self._styled = True
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        rc = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(rc))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        fit = self._measure()
        if fit:   # 按页面内容实际需要的大小来（高 DPI 屏上 pywebview 给的窗口会偏小，英文也比中文长）
            w, h = fit
            u32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, w, h, _SWP_NOACTIVATE | 0x0002)   # 0x0002 = SWP_NOMOVE
        mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
        u32.GetMonitorInfoW(u32.MonitorFromPoint(pt, 2), ctypes.byref(mi))
        work = mi.rcWork
        x = max(work.left, min(pt.x - w, work.right - w))
        y = max(work.top, min(pt.y - h, work.bottom - h))
        u32.SetWindowPos(hwnd, _HWND_TOPMOST, x, y, 0, 0, _SWP_NOSIZE | _SWP_NOACTIVATE)   # 先挪好再显示，不闪
        self.window.show()
        u32.SetWindowPos(hwnd, _HWND_TOPMOST, x, y, 0, 0, _SWP_NOSIZE | _SWP_SHOWWINDOW)
        u32.SetForegroundWindow(hwnd)
        self.visible = True
        threading.Thread(target=self._refresh, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()
        return True

    def _measure(self) -> tuple[int, int] | None:
        """问页面：内容要多大（CSS 像素 × 缩放比例 = 屏幕像素）。窗口藏着时也能量。"""
        try:
            r = self.window.evaluate_js(
                "(function(){var m=document.getElementById('tray-menu');if(!m)return null;"
                "var b=m.getBoundingClientRect();return [Math.ceil(Math.max(innerWidth,b.width)),"
                "Math.ceil(b.height),devicePixelRatio||1];})()")
        except Exception:
            log.debug("量托盘菜单大小失败", exc_info=True)
            return None
        if not r or len(r) != 3 or not r[1]:
            return None
        cw, ch, dpr = r
        return int(round(cw * dpr)), int(round(ch * dpr))

    def _refresh(self) -> None:
        try:
            self.window.evaluate_js("window.awyMenuOpen && window.awyMenuOpen()")
        except Exception:
            log.debug("刷新托盘菜单状态失败", exc_info=True)

    def _watch(self) -> None:
        """点到别处（菜单不再是最前面的窗口）就收起。刚弹出时给 0.4 秒让焦点切过来。"""
        time.sleep(0.4)
        while self.visible:
            fg = self._u32.GetForegroundWindow()
            if fg and self._u32.GetAncestor(fg, _GA_ROOT) != self.hwnd:
                self.hide()
                return
            time.sleep(0.15)

    def hide(self) -> None:
        if self.visible:
            self.visible = False
            try:
                self.window.hide()
            except Exception:
                log.debug("收起托盘菜单失败", exc_info=True)


def make_icon_class(pystray_mod: Any) -> type:
    """pystray 的 Windows 图标类：右键时先问 on_right()，它处理了就不弹 Windows 自带菜单。"""
    from pystray._util import win32   # pystray 内部模块，版本锁在 uv.lock 里

    class Icon(pystray_mod.Icon):  # type: ignore[misc, valid-type]
        on_right: Any = None

        def _on_notify(self, wparam, lparam):  # noqa: ANN001
            if lparam == win32.WM_RBUTTONUP and self.on_right:
                win32.SetForegroundWindow(self._hwnd)   # 拿到前台权限，才能把菜单窗口放到最前
                try:
                    if self.on_right():
                        return None
                except Exception:
                    log.exception("自绘托盘菜单出错，改用系统菜单")
            return super()._on_notify(wparam, lparam)

    return Icon
