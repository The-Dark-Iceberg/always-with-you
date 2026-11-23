# AGENTS.md —— 给所有接手本项目的 AI 的总入口

> Claude Code 读 `CLAUDE.md`、Gemini CLI 读 `GEMINI.md`，它们都只是指向本文件。**以本文件为准。**

## 这是什么

「一个时刻陪着你的AI」（Always With You，简称 awy）：一个 Windows 桌面程序，在用户自己的电脑上
采集生活痕迹 → 过滤隐私 → 生成摘要 → 定时交给 AI 整理成记忆 → 通过 MCP 让 AI 在「陪伴聊天」时了解用户。

用户（项目所有者）**不是计算机专业**，用中文沟通。和他说话要通俗、少术语、先讲结论；
做任何会扩大权限、增加依赖、发送数据到外部的改动前，先讲清风险并征得同意。

## 开工前必读（按顺序）

1. `docs/HANDOFF.md` —— 上一位做到哪了、下一步做什么。**最重要。**
2. `docs/VISION.md` —— 要做什么、明确不做什么。
3. `docs/ARCHITECTURE.md` —— 模块怎么分工、数据怎么流动。
4. 要改记忆相关代码时：`docs/MEMORY_ALGORITHMS.md`、`docs/DATA_FORMAT.md`。
5. 要碰权限、网络、数据时：`docs/SECURITY.md`。
6. 想推翻已有设计前：先看 `docs/decisions/`，那里写了当初为什么这么选。

## 铁律

1. **个人数据永不进仓库。** 真实数据在 `%LOCALAPPDATA%\AlwaysWithYou\`，不在项目目录里。不要提交 config.json、*.db、raw/、summaries/、模型文件、任何密钥。
2. **读写分开。** 只读入口（陪伴聊天用）不能有任何修改记忆的工具；只有整理入口能写。新增工具时先想清楚放哪边。
3. **没有真正的删除。** 记忆只能「标记失效」或「撤回」，所有写入记进 audit 表，可撤销。
4. **原始记录先过滤再落盘。** 任何新的采集来源，都必须先经过 `privacy.py` 的黑名单和打码。
5. **AI 只看摘要。** 交给大模型的只有摘要和记忆，不发原始记录。
6. **不加不必要的依赖。** 每加一个第三方库都是一个可能被「下毒」的入口。加之前说明理由，用 `uv add` 锁定版本。
7. **改代码同步改文档。** 改了行为就更新对应 docs；每次工作结束更新 `docs/HANDOFF.md`。
8. **测试必须通过** 才能提交。
9. **给人看的文字都要能翻译。** 后台写 `t("中文")`（awy/i18n.py），界面写 `T("中文")`（ui/js/i18n.js），然后在 `ui/i18n/en.json` 里加英文；`tests/test_i18n.py` 会抓漏翻。写给 AI 的提示词不用翻译。

## 常用命令（在项目根目录执行）

```bash
uv sync                          # 安装依赖（第一次或依赖变化后）
uv run pytest -q                 # 跑全部测试（约 3 秒，不碰真实数据）
uv run python -m awy             # 启动桌面程序（会使用真实数据目录！）
uv run python -m awy serve-ui    # 不开窗口，只起后台 + 界面接口，打印带钥匙的地址，用浏览器调试
uv run python -m http.server 8765 --bind 127.0.0.1 --directory ui   # 只看界面（假数据）
uv run python -m awy serve       # 无界面运行
uv run python -m awy summary     # 打印今天的电脑活动摘要
uv run python -m awy context     # 打印陪伴模式下 AI 看到的上下文
powershell -File packaging\build.ps1   # 打包 exe 和安装包，见 packaging/README.md
```

想在不影响真实数据的情况下试运行：先设置环境变量 `AWY_DATA_DIR` 和 `AWY_COMPANION_DIR` 指向临时目录。

## 目录地图

```
ui/                界面（HTML/CSS/JS，铅笔手绘风格，字体在 ui/fonts）。没有后台时用 mock-data.js 假数据预览
src/awy/
  __main__.py      入口（桌面程序 / 命令行子命令）
  core.py          把各部件组装起来；开机自启
  desktop.py       桌面外壳：pywebview 窗口 + pystray 托盘 + 只允许运行一个
  webapi.py        界面用的本机接口 /api/...（只听本机 + 每次启动随机钥匙 + 检查 Host/Origin）
  chat.py          「陪我聊聊」：DeepSeek API，或用 ACP 调用 Antigravity（agy acp），临时给只读记忆库
  config.py        设置（默认值都在这里）
  paths.py         所有数据路径的唯一来源
  vault.py         用 Windows DPAPI 加密保存密钥
  collect_pc.py    电脑采集：前台窗口、空闲时间
  privacy.py       黑名单 + 打码（落盘前）
  rawlog.py        原始记录 raw/YYYY-MM-DD/events.jsonl
  summarize.py     原始记录 → 摘要（交给 AI 的唯一东西）
  pipeline.py      定时：生成摘要 → 存 episode → 叫整理者
  ops.py           所有记忆工具的唯一实现（ReadOps / WriteOps）及给 DeepSeek 的工具说明
  mcp_servers.py   两个 MCP 服务 + 钥匙校验
  phone.py         手机端 AwyRead 的接收入口：找电脑、配对、解密上传（唯一听局域网的，默认关着，决定 0014）
  memory/
    store.py       SQLite 记忆库（唯一写 SQL 的地方）
    rank.py        检索打分（RRF、衰减、MMR……）
    context.py     「前稳后动」上下文拼装
    embed.py       bge-m3 向量模型（ONNX）下载与推理
    text.py        jieba 中文分词
  organize/
    rules.md       整理规则（给整理 AI 的说明书）
    deepseek.py    用 DeepSeek API 整理
    claude_cli.py  用 Claude Code 无界面模式整理（实验）
tests/             pytest 测试
android/           手机端 AwyRead（Kotlin，不用 Gradle、零第三方库），怎么打包见 android/README.md
packaging/         PyInstaller 与 Inno Setup 打包脚本
docs/              说明书
```

## 约定

- 文档、注释、界面文字用中文；代码里的名字（变量、函数、文件）用英文。
- Python 3.13，用 uv 管理环境。不要用 pip 直接往系统 Python 里装东西。
- 提交信息用中文，一句话说清做了什么。
- 不确定用户想要什么时，问，不要猜。
