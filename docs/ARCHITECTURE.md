# 架构

## 数据流

```
【采集】collect_pc.py：每 5 秒看一次前台窗口和空闲时间，状态变化才记一条
   │  经过 privacy.py：黑名单 → [隐私窗口]；标题打码
   ▼
【正本】rawlog.py：%LOCALAPPDATA%\AlwaysWithYou\raw\YYYY-MM-DD\events.jsonl（默认保留 30 天）
   │
   ▼  pipeline.Scheduler：每天 10:00 / 14:00 / 19:00 / 23:30（可改；错过的开机后补一次）
【摘要】summarize.py：零碎记录 → 时间段 + 统计 → 一页 Markdown
   │  同时存一份到 summaries\YYYY-MM-DD\HHMM.md
   ▼
【待整理】memory.db 的 episodes 表（processed_at 为空）
   │                                         ┌── 陪伴聊天时 AI 留的便条（inbox 表）
   ▼                                         ▼
【整理】organize/：DeepSeek API（工具调用循环）或 Claude Code（无界面模式 + 整理入口 MCP）
   │  按 organize/rules.md：抽取事实 → 先查相似 → 重复则加强 / 矛盾则旧的标失效 / 新的就新增
   ▼
【记忆库】memory/store.py：facts（双时间）、entities+aliases、persona（核心画像）、audit（写入日志）
   │
   ▼
【读取】只读入口 MCP（127.0.0.1:47821）→ 陪伴文件夹里的 Claude Code / Gemini CLI / Codex
        get_user_context：「前稳后动」拼装（memory/context.py）
        search_memory：关键词 + 向量 → RRF → 衰减×重要度×强度 → MMR（memory/rank.py）
```

## 界面与聊天（决定 0006 已被网页界面 + pywebview 取代，0004 已被 0008 取代）

```
AlwaysWithYou.exe
 ├─ pywebview 窗口（Windows 自带 Edge WebView2）── 打开 http://127.0.0.1:<随机端口>/?t=<随机钥匙>
 │     └─ ui/（HTML/CSS/JS）── fetch /api/...（带 X-AWY-Token）
 ├─ webapi.py（uvicorn 线程）── 今天 / 记忆 / 写入日志 / 设置 / 由谁来回答 / 聊天（逐行流式返回）/ 头像壁纸
 ├─ pystray 托盘
 └─ chat.py
      ├─ DeepSeek：本进程直接调 API，工具 = ReadOps（只读 + 便条）
      └─ Antigravity：子进程 `agy acp`；session/new 时传入只读 MCP（127.0.0.1:47821 + 只读钥匙）；
         Agent 的每次工具调用都要本程序同意：只放行 mcp_awy-memory_*，其余（读写文件、命令等）一律拒绝
```

- 聊天记录：数据目录 `chats/YYYY-MM-DD.jsonl`。头像、壁纸：`prefs/`。
- 订阅制 Agent 的工作目录：`agents/<名字>/`（空文件夹，只有陪伴说明 AGENTS.md / GEMINI.md）。
- `runtime.json`：当前界面接口的端口和钥匙，供「第二次打开」叫醒已运行的窗口；退出时删除。

## 进程与线程

一个进程（AlwaysWithYou.exe），里面：
- 主线程：Qt 界面与托盘（ui.py）。
- `pc-collector` 线程：采集。
- `mcp-read`、`mcp-write` 线程：各跑一个 uvicorn（只监听 127.0.0.1）。
- `scheduler` 线程：每 30 秒检查是否到了整理时间。
- 临时线程：整理、下载模型、重建向量索引（界面通过 Qt 信号拿结果）。

记忆库 `MemoryStore` 内部用一把锁串行化所有操作（个人数据量小，足够）。

## 两个 MCP 入口

| | 只读入口 | 整理入口 |
|---|---|---|
| 端口 | 47821 | 47822 |
| 钥匙 | `read_token` | `write_token` |
| 谁用 | 陪伴文件夹里的 Agent | 定时整理任务（Claude Code 方式时） |
| 工具 | get_user_context、search_memory、recall_period、leave_note | list_pending、get_persona、find_similar_facts、add_fact、invalidate_fact、reinforce_fact、upsert_entity、update_persona、mark_processed |

DeepSeek 方式整理时不走 HTTP，直接在进程内调用同一个 `WriteOps`（ops.py），所以两种方式规则完全一致。

## 工作模式 vs 陪伴模式

聊天只在本程序的「陪我聊聊」里进行（决定 0008）。本程序**不修改任何别家软件的配置**，也不再生成「陪伴文件夹」；
用户自己打开 Antigravity / Claude Code / Codex 时，它们照常工作、看不到记忆。

## 数据目录（%LOCALAPPDATA%\AlwaysWithYou）

```
config.json        设置（API Key 已 DPAPI 加密）
memory.db          记忆库
raw/YYYY-MM-DD/    原始记录
summaries/YYYY-MM-DD/HHMM.md   每次整理用的摘要
models/bge-m3/     向量模型（可选）
phone/             手机接收入口的状态：批次号、去重索引、收到记录（决定 0014）
logs/app.log       运行日志
```

卸载时会询问是否删除这个目录（默认保留）。

## 0.3.0 新增的模块（决定 0012）

- `power.py`：电脑睡眠 / 关机识别（读系统日志 wevtutil、校准间隔、配对睡眠段）。采集线程 collect_pc.PcCollector 调用它。
- `library.py`：记忆库说明文件、导出压缩包、记忆存档（导入 / 启用）、搬家。会停下各部分的操作由 webapi._maintenance 负责，
  做完后 desktop.restart 开一个新的自己（带 --restarted，等旧的退出）再退出。
- `paths.py`：数据目录可以被 location.json 指到别处。
- 界面：`ui/js/app.js` 里的 showTerms（风险确认）、openGuide / renderGuide（引导）、trackForm / leaveOk（没保存提醒）、
  openArchives / moveLibrary / libJob（记忆库）；`ui/js/zones-zh.js`（时区城市中文名）。

## 手机（决定 0014）

```
手机 AwyRead（android/）                         电脑
  UsageReader / HealthExport                       phone.Discovery   UDP 47824：回答「谁是 AlwaysWithYou」
     ↓ 每小时（SyncJob）或打开 App                  phone.PhoneBridge TCP 47824（0.0.0.0，设置里打开才启动）
  Sync：去重 → queue.jsonl                           /phone/hello  /phone/pair  /phone/upload
     ↓ 连着 Wi-Fi 且已配对                              ↓ 解密 → clean_event（检查 + 隐私）→ 去重
  PcLink：AES-GCM 加密一批（≤400 条）  ──────→        rawlog（src=phone，带 rx）+ phone/batches.jsonl
                                       ←── 加密的「收到了」  ↓ 整理时
                                                    pipeline.make_phone_episode → summarize.render_phone
                                                    → episode（source=phone_summary）→ 整理 AI
```

- 开关：`Core.set_phone_enabled` / `_start_phone` / `_stop_phone`；状态 `Core.phone_status`；界面接口 `/api/phone*`（webapi.py），
  设置页的「手机」卡片（app.js 的 phoneBox / phoneAct）。
- `mcp_servers.ServerThread` 多了 `host` 参数，只有手机入口传 `0.0.0.0`，其他都还是 127.0.0.1。
