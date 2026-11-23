# PyInstaller 打包配置。用 packaging/build.ps1 调用，不要直接运行。
# 打成「文件夹」形式（onedir）：启动快，也比单文件 exe 更不容易被杀毒软件误报。
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH + "/.."

datas = [(ROOT + "/ui", "ui")]                             # 界面（HTML/CSS/JS/字体）
datas += [(ROOT + "/browser-extension", "browser-extension")]  # 浏览器扩展（「安装浏览器扩展」时复制出去）
datas += collect_data_files("jieba")                      # 分词词典
datas += collect_data_files("awy", includes=["**/*.md"])  # organize/rules.md
datas += collect_data_files("webview")                    # pywebview 自带的 JS
datas += collect_data_files("tzdata")                     # 时区数据库（Windows 版 Python 不带，决定 0011）
hidden = collect_submodules("uvicorn") + collect_submodules(
    "mcp", filter=lambda n: not n.startswith("mcp.cli"))  # mcp.cli 需要 typer，我们用不到
hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "pystray._win32"]
hidden += collect_submodules("winrt") + collect_submodules("tzdata")   # 正在播放（SMTC）、时区

excludes = ["tkinter", "matplotlib", "IPython", "pytest", "PySide6", "shiboken6", "PyQt5", "PyQt6"]

a = Analysis(
    [ROOT + "/packaging/entry.py"],
    pathex=[ROOT + "/src"],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)

# 去掉用不到的大文件：jieba 的 paddle 模型和关键词提取词典
_drop = ("jieba/lac_small", "jieba\\lac_small", "jieba/analyse", "jieba\\analyse")
a.binaries = [b for b in a.binaries if not any(d in b[0] for d in _drop)]
a.datas = [d for d in a.datas if not any(x in d[0] for x in _drop)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AlwaysWithYou",
    console=False,
    icon=ROOT + "/packaging/output/app.ico",
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AlwaysWithYou")
