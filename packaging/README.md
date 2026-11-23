# 打包说明

```powershell
# 在项目根目录
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

脚本依次：跑测试 → 生成图标 → PyInstaller 打包到 `dist\AlwaysWithYou\` → 如果装了 Inno Setup 6，生成
`packaging\output\AlwaysWithYou-Setup-<版本>.exe`。

- 没装 Inno Setup 时，`dist\AlwaysWithYou\AlwaysWithYou.exe` 也可以直接双击运行（绿色版），只是没有卸载程序。
- 安装 Inno Setup：`winget install --id JRSoftware.InnoSetup -e --scope user`（作者机器已装，6.7.3，位于 `%LOCALAPPDATA%\Programs\Inno Setup 6`）
- 想把向量模型一起装进安装包：把 `bge-m3` 文件夹（model.onnx、model.onnx_data、tokenizer.json）放到
  `packaging\model\bge-m3\`。安装包会因此大 2GB 左右。不放的话用户在程序「设置」里下载。

## 文件

| 文件 | 作用 |
|---|---|
| `entry.py` | 打包入口（带崩溃日志） |
| `awy.spec` | PyInstaller 配置：收集 jieba 词典、rules.md、uvicorn/mcp 子模块；去掉用不到的大文件 |
| `make_icon.py` | 生成 app.ico |
| `installer.iss` | 安装/卸载脚本：装到用户目录不需管理员；卸载时结束进程、删开机自启、询问是否删数据 |
| `build.ps1` | 一键打包 |
| `ChineseSimplified.isl` | 安装界面的简体中文翻译。Inno Setup 6 官方安装包不自带，取自官方仓库 jrsoftware/issrc 标签 is-6_7_3 的 `Files/Languages/Unofficial/`（译者信息见文件头），已转为 UTF-8 带 BOM |

注意：`build.ps1` 和 `installer.iss` 含中文，必须保存为 **UTF-8 带 BOM**，否则 Windows PowerShell 5.1 / Inno Setup 会乱码。

## 踩过的坑

- **（严重，2026-11-20）静默卸载删掉了用户数据。** 卸载脚本里「是否删除数据」用的是普通 `MsgBox`，在
  `/VERYSILENT /SUPPRESSMSGBOXES` 下被当成「是」。之前的测试没发现，是因为测试时真实数据目录不存在、弹窗根本没出现。
  现已改为：静默卸载一律不删；弹窗用 `SuppressibleMsgBox(..., IDNO)`。**以后改卸载逻辑，必须在真实数据位置放标记文件实测。**

- 无控制台的 exe 里 `sys.stdout` 是 None：uvicorn 默认日志配置会崩溃 → `uvicorn.Config(log_config=None)`，入口处把 stdout/stderr 指向 devnull。
- `collect_submodules("mcp")` 会导入 `mcp.cli`（需要 typer）→ 过滤掉。
- 打包后启动出错时看 `%LOCALAPPDATA%\AlwaysWithYou\logs\crash.log`。
