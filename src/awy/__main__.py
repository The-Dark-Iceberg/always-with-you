"""程序入口。

  AlwaysWithYou.exe                 打开桌面程序（托盘常驻）
  AlwaysWithYou.exe --minimized     启动后只在托盘，不弹窗口（开机自启用）

开发与维护用的命令（在项目目录下 `uv run python -m awy <命令>`）：
  serve            无界面运行（采集 + MCP + 定时整理），Ctrl+C 退出
  summary          打印今天到现在的电脑活动摘要（不写入记忆库）
  organize-now     立即生成摘要并整理一次
  context          打印陪伴模式下 AI 看到的上下文
  download-model   下载并校验 bge-m3 向量模型（约 2.3GB）
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, time as dtime


def main(argv: list[str] | None = None) -> int:
    # 无控制台的 exe 里 sys.stdout/stderr 是 None，有些库往里写东西会崩溃
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    p = argparse.ArgumentParser(prog="awy", description="一个时刻陪着你的AI")
    p.add_argument("command", nargs="?", default="gui",
                   choices=["gui", "serve", "serve-ui", "summary", "organize-now", "context", "download-model"])
    p.add_argument("--minimized", action="store_true", help="启动时只显示托盘图标")
    p.add_argument("--restarted", action="store_true", help="换记忆库 / 搬家后自动重启（等旧的退出）")
    a = p.parse_args(argv)

    if a.command == "gui":
        from awy.desktop import run_desktop
        return run_desktop(minimized=a.minimized, restarted=a.restarted)

    if a.command == "serve-ui":
        # 开发用：不开窗口，只启动后台和界面接口，打印地址，用浏览器打开调试
        import time as _t

        from awy.core import Core
        from awy.desktop import start_web
        core = Core(on_message=print)
        core.start()
        _, server, url = start_web(core)
        print("界面地址（含一次性钥匙）：", url, flush=True)
        try:
            while True:
                _t.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            core.stop()
        return 0

    if a.command == "summary":
        from awy import summarize
        from awy import clock
        now = clock.now()
        print(summarize.summarize_range(datetime.combine(now.date(), dtime.min, tzinfo=now.tzinfo), now))
        return 0

    if a.command == "download-model":
        from awy import paths
        from awy.memory import embed

        def prog(name: str, done: int, total: int) -> None:
            print(f"\r{name}: {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", flush=True)
        embed.download(paths.models_dir(), prog)
        print("\n下载完成，校验通过")
        return 0

    from awy.core import Core
    core = Core(on_message=print)
    if a.command == "context":
        from awy.ops import ReadOps
        print(ReadOps(core.store, core.settings).get_user_context())
        return 0
    if a.command == "organize-now":
        print(core.scheduler.run_now(final_of_day=False))
        return 0
    if a.command == "serve":
        core.start()
        print(f"运行中：只读入口 127.0.0.1:{core.settings.read_port}，整理入口 127.0.0.1:{core.settings.write_port}。Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            core.stop()
        return 0
    return 1


def guarded_main() -> int:
    """打包后的程序没有控制台：出错时把详细信息写进 logs/crash.log，并弹窗提示，方便排查。"""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        import traceback

        from awy import paths
        detail = traceback.format_exc()
        log_file = paths.logs_dir() / "crash.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"\n==== {datetime.now().isoformat()} ====\n{detail}")
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"程序出错退出了。详细信息已保存到：\n{log_file}\n\n{detail[-600:]}",
                                             "一个时刻陪着你的AI", 0x10)
        raise


if __name__ == "__main__":
    sys.exit(guarded_main())
