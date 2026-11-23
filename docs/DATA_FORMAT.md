# 数据格式

模块之间靠这些格式对接。改格式 = 改契约，必须同时改代码、测试和本文件，并考虑旧数据怎么兼容。

## 1. 原始记录 raw/YYYY-MM-DD/events.jsonl

每行一个 JSON，只追加。写入前必须已过 `privacy.py`。

| 字段 | 说明 |
|---|---|
| `ts` | ISO 8601 时间，带时区，精确到秒，例如 `2026-11-20T14:03:05+08:00` |
| `src` | 来源：`pc`、`media`、`files`、`browser`、`phone`（手机端 AwyRead，决定 0014） |
| `type` | 见下表 |

| type | 其他字段 | 含义 |
|---|---|---|
| `window` | `app`（进程名）、`title`（已打码的窗口标题） | 前台窗口变了。命中黑名单时 app=`[隐私窗口]`、title 为空 |
| `away` | `reason`：`idle`（`idle_seconds`）/ `locked` / `sleep`（电脑睡眠）/ `shutdown`（关机）/ `app_exit`（程序退出） | 离开电脑。sleep / shutdown 是醒来或开机后**往回补写**的，ts 是睡着 / 关机的时刻（决定 0012） |
| `back` | 可选 `reason`：`sleep` / `shutdown` | 回来了。和同 reason 的 away 配对，中间那段算「电脑睡眠 / 关机」，里面残留的记录作废 |
| `paused` / `resumed` | — | 用户暂停 / 恢复采集 |
| `media` | `state`：`playing`（`app`、`title`、`artist`）或 `stopped` | 系统「正在播放」变了（src=media，决定 0011） |
| `file` | `name`（文件名，已打码） | 最近打开了一个文件（src=files） |
| `web` | `url`（https、去掉全部参数）、`domain`、`title`、可选 `search`；或 `state=off` | 浏览器扩展：当前在看的网页变了；off = 浏览器不在前面或不是 https（src=browser） |

窗口时间线只看 window/away/back/paused/resumed；media、web、file 各走各的时间线，不打断窗口时长。
因为睡眠 / 关机是往回补写的，同一个文件里的行不一定按时间顺序，读的时候按 ts 排序（rawlog.read_range 已经排好）。
醒来不到 1 分钟又睡着（假醒）的两段合并成一段。

时长不单独记录：一条事件持续到下一条事件为止。

**手机（src=phone，决定 0014）** 和上面不一样：每条自带结束时间（`end`），不靠「持续到下一条」；
`ts` 是事情发生的时间（换算成电脑的时区），另外都带 `rx`（电脑收到的时间，精确到微秒）——手机回家才上传，常常晚几小时到几天，
整理时按 rx 找「新收到的」。同一条记录（`type|pkg|ts` 相同）内容变了会再写一行，以 rx 最晚的为准。

| type | 其他字段 | 含义 |
|---|---|---|
| `phone_app` | `app`（App 名，已打码）、`pkg`（包名）、`end` | 一段前台使用（同一 App 间隔 30 秒内已合并，短于 5 秒的不发）。命中黑名单时 app=`[隐私应用]`、pkg 为空 |
| `phone_screen` | `end` | 一段亮屏 |
| `phone_health` | 可选 `steps`、`hr_min`、`hr_avg`、`hr_max` | 一小时的汇总（ts 是这个小时的开始），系统已去重（手机和手表都记步时不重复相加） |
| `phone_sleep` | `end`、`deep`、`light`、`rem`、`awake`（分钟）、`by`（写入记录的 App） | 一次睡眠，算醒来那天 |

电脑另在数据目录的 `phone/` 里记：`state.json`（每台手机最后的批次号、最后联系时间）、`index.json`（写过的记录，去重用）、
`batches.jsonl`（什么时候收到了哪几天的数据，整理时只读这几天）。配对过的手机（编号、名字、DPAPI 加密的钥匙）在 config.json 的 `phone_devices`。

## 2. 摘要（episode 内容）

Markdown。第一行 `# 电脑活动摘要 <开始> – <结束>`，然后是总览行（`- 在电脑前约…`）、`## 按时间`、`## 按软件统计`。
少于 1 分钟的片段不单独列出。每次摘要的开始时间 = 上一次摘要的结束时间（首尾相接，不重不漏）。
总览行里有睡眠时加「（其中电脑睡眠 / 关机约…）」，并有 `## 电脑睡眠 / 关机（这段时间没在用电脑）`。
有数据时追加 `## 在听 / 在看（包括后台播放）`、`## 看过的网页（浏览器扩展，按停留时长）`、`## 搜索过`、`## 打开过的文件`。

手机 episode（source=`phone_summary`，决定 0014）：`# 手机活动摘要（<开始> – <结束> 收到的）`，开始 / 结束是**收到的时间**范围。
按事情发生的日期分 `## M月D日（周X）`，下面 `### 手机使用`（亮屏总时长和次数、按时间列 2 分钟以上的片段（最多 30 段）、按应用统计）
和 `### 健康（截至目前收到的）`（那天全部小时的步数合计和最多的一小时、心率平均 / 最低 / 最高、每次睡眠和各阶段）。
使用片段只写这次新收到的；健康按那天收到过的全部最新数据写（手表晚同步时会变多）。

聊天 episode（source=`chat`）：`# 聊天记录 <开始> – <结束>`，每行 `[MM-DD HH:MM] 用户：…` / `[MM-DD HH:MM] AI：…`。
超过 16000 字时先把 AI 的回复压到 200 字，再只留最近的。

## 3. 记忆库 memory.db（SQLite，schema_version=2）

### facts（事实）
| 字段 | 说明 |
|---|---|
| `text` | 一句完整的中文，第三人称 |
| `category` | trait 性格 / preference 偏好 / habit 习惯 / relation 关系 / health 健康 / plan 计划 / state 状态 / event 事件 / shared 一起聊过的 |
| `importance` | 0~1 |
| `confirmed` | 1 = 用户亲口确认或纠正过 |
| `valid_at` | 世界时间：从何时开始成立 |
| `invalid_at` | 世界时间：从何时不再成立（被新事实推翻）；空 = 仍成立 |
| `invalid_reason` | 为什么不再成立 |
| `retracted_at` | 系统时间：这条记录被撤回（写错了）；撤回的事实永远不参与检索 |
| `episode_id` / `inbox_id` | 证据来源 |
| `source` | 写入者，如 `deepseek`、`mcp-organizer` |
| `recall_count` / `last_recalled_at` | 被检索到的次数（回忆加强） |
| `reinforce_count` | 加强分（v2 起）：用户再提 +2，电脑活动 / 认同 / 聊过 +1，AI 复述 +0。v1 的次数升级时 ×2 |
| `speaker` | 谁说的：note / user / user_agreed / shared / pc / assistant（见 store.SPEAKERS、决定 0011） |
| `confidence` | 可信度 0~1：note 1.0、user 0.9、user_agreed 0.8、shared 1.0、pc 0.6、assistant 0.4 |
| `embedding` / `embed_model` | 向量（float32 字节）及模型名；换模型需重建 |

**当前事实** = `invalid_at IS NULL AND retracted_at IS NULL`。

### 其他表
- `facts_fts`：全文索引，rowid = facts.id，内容是 jieba 分好词、空格分隔的文本。
- `entities` / `aliases`：人、地点、项目及其别名（别名存小写）。
- `episodes`：待整理/已整理的摘要。`processed_at` 为空 = 待整理。
- `inbox`：聊天时留的便条，`kind` ∈ remember / correct / note。
- `persona`：核心画像，多版本，`active=1` 的是当前版本。
- `audit`：写入日志。`action` ∈ add_entity / add_fact / invalidate_fact / reinforce_fact / set_persona / mark_processed / undo；`undone_at` 非空表示已撤销。

## 4. 设置 config.json

字段及默认值以 `src/awy/config.py` 的 `Settings` 为准。未知字段读取时忽略，缺失字段用默认值。
`deepseek_api_key_protected` 是 `dpapi:` 前缀的加密串。`read_token` / `write_token` 首次运行随机生成。
`accepted_terms`：接受过的风险说明版本（等于 config.TERMS_VERSION 才开始记录）；`onboarded`：引导看完或跳过了（决定 0012）。

## 5. 数据文件夹的位置（决定 0012）

- 默认 `%LOCALAPPDATA%\AlwaysWithYou`。用户搬过家时，默认目录里只剩：
  - `location.json`：`{"data_dir": "<新位置的绝对路径>", "previous": "<上一个位置>"}`；`data_dir` 为空 = 默认位置。
  - `location.txt`：带 BOM 的 UTF-8，只有一行新位置路径，给卸载程序读（Inno Setup 不解析 JSON）。
- 新位置的文件夹名永远是 `AlwaysWithYou`。
- 数据文件夹最外层有 `记忆库说明.md`（或 `MEMORY-README.md`），程序启动和切换语言时重写。
- `archives/`：记忆存档（导入的、自动备份的压缩包）。
- `enable-pending.json`：正在启用存档时才有。`{"backup": "<换之前的自动备份名>", "archive": "<启用的存档名>", "stage": "swapping" | "swapped", "dropped_chat_lines": 0}`。
  启动时还是 `swapping` 就用 backup 换回；`swapped` 且新库能打开就删掉它。没有 `stage` 的是旧版本写的，只在库打不开时换回。
  启动时换回失败会加 `"retry": true`（程序接着用当前的库）；下次换回前先把当前的库打包存进 archives/，再换回。
- 聊天文件 `chats/YYYY-MM-DD.jsonl`：每行一条，按 `\n` 分行（不能用 splitlines）。U+2028 / U+2029 / U+0085 写成 `\uXXXX` 转义。
- `prefs/prefs.json`：界面偏好。`veil`（壁纸遮罩）、`side`（侧边栏收起）、`tlorder`（只会是 `"desc"`：首页时间线从晚到早）；
  主题（决定 0013）：`skin`（只会是 `"glass"`）、`glassbg`（`"wall"`）、`glassmode`（`"light"` / `"dark"`）、`motion`（`"full"` / `"off"`）、
  `glassveil`（0~100 的整数）。都只存「不是默认」的值，默认值就没有这一项。头像、壁纸是同目录的 `avatar.jpg`、`wallpaper.jpg`。

## 6. 记忆库压缩包（导出 / 存档，FORMAT = 1）

| 文件 | 说明 |
|---|---|
| `manifest.json` | `app`=AlwaysWithYou、`format`、`kind`（export / backup）、`app_version`、`schema`、`exported_at`、`language`、`facts`、`chats`、`chat_days`、`readme` / `memory_md` / `chats_dir`（下面三项的实际文件名，随导出时的语言） |
| `记忆库说明.md` / `MEMORY-README.md` | 写给 AI 的说明（library.readme_text） |
| `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` | 一样的几行：先读说明（`@说明文件名`，Claude Code / Gemini CLI 会自动引入） |
| `记忆.md` / `memory.md` | 核心画像 + 按分类的全部记忆（时间、重要程度、说话人、可信度）+ 已不再成立的 + 人物（export.memory_markdown） |
| `memory.db` | SQLite 备份 API 拷出的一致副本 |
| `聊天记录/` / `chats/` | 总是带上。`YYYY-MM-DD.jsonl`，和 chats/ 里的格式一样 |

`kind=export` 的压缩包里，所有文字（聊天、记忆、摘要、便条、写入日志）都过了 privacy.mask，manifest 里 `scrubbed=true`；`kind=backup`（启用存档前的自动备份）原样保存。

导入时检查：manifest 的 app、format、schema 不高于当前版本；memory.db 能打开、`PRAGMA integrity_check` 通过、有 facts / meta / persona 表。
只读取上面这些固定名字的成员（聊天文件名必须是日期），不按压缩包里的路径解压，防止路径穿越。
