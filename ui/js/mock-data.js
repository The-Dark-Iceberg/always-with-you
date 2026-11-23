/* 原型用的假数据。接后台时，这些内容改由本机接口提供（字段名尽量和后台一致）。 */
window.MOCK = {
  status: { version: "0.2.0", collecting: true, readServer: true, writeServer: true, embedder: true,
            chatBrain: "antigravity", organizeBrain: "deepseek",
            nextOrganize: "23:30", lastOrganize: "19:00 整理完成：新增 3 条，加强 1 条" },
  today: {
    greeting: "晚上好。今天你在电脑前待了 6 小时 20 分，大部分时间在写记忆库项目；下午刷了一会儿 B 站，然后又回来了。",
    stats: [
      { num: "6 时 20 分", lab: "在电脑前" },
      { num: "1 时 05 分", lab: "离开 / 休息" },
      { num: "3 条", lab: "今天新记住的事" }
    ],
    timeline: [
      { when: "09:12–10:48", app: "Code.exe", t: "store.py · rank.py · always-with-you", dur: "1 时 36 分" },
      { when: "10:48–11:06", app: "chrome.exe", t: "SQLite FTS5 文档 · bge-m3 模型卡", dur: "18 分" },
      { when: "11:06–12:20", app: "Code.exe", t: "test_memory.py · context.py", dur: "1 时 14 分" },
      { when: "12:20–13:25", away: true, t: "离开电脑", dur: "1 时 05 分" },
      { when: "13:25–13:52", app: "msedge.exe", t: "哔哩哔哩 · 开源｜我花了 4 个多月，让 AI 知道我每天过得怎么样", dur: "27 分" },
      { when: "13:52–16:10", app: "Claude.exe", t: "一个时刻陪着你的AI", dur: "2 时 18 分" },
      { when: "16:10–16:35", app: "[隐私窗口]", t: "", dur: "25 分" }
    ],
    apps: [
      { name: "Code.exe", min: 170 }, { name: "Claude.exe", min: 138 }, { name: "msedge.exe", min: 27 },
      { name: "[隐私窗口]", min: 25 }, { name: "chrome.exe", min: 18 }
    ]
  },
  chat: [
    { who: "ai", tool: "读取了你的记忆（核心画像 · 近期 · 今天）",
      text: "晚上好。今天写了一整天的记忆库，连午饭都是一点多才去吃的吧？\n下午那会儿看到你去 B 站看了 Kinship 的视频——是又想到什么新点子了吗？" },
    { who: "me", text: "嗯，在想界面能不能做成铅笔画的感觉，跟我的个人网页一样。" },
    { who: "ai", tool: "搜索记忆：「个人网页」",
      text: "我记得你的个人网页是纸张底色加霞鹜文楷，线条会像铅笔一样一笔一笔画出来。用在这里挺合适的——这个程序本来就是安安静静陪着你的，不需要太亮眼。" },
    { who: "me", text: "对，记住：我喜欢这种手绘铅笔的风格。" },
    { who: "ai", tool: "留了一张便条（记住）",
      text: "好，记下了。下次整理的时候会写进记忆里。" }
  ],
  persona: [
    "白天忙正事，晚上喜欢折腾自己的小项目，愿意花时间把一件事弄明白。",
    "说话直接，喜欢先听结论；讨厌被糊弄，在意安全和隐私。",
    "最近的主线：做一个能长期陪着自己、真正懂自己的本地 AI。",
    "喜欢安静、手绘、纸张质感的东西。"
  ],
  personaMeta: "第 3 版 · 11 月 20 日 23:30 由 DeepSeek 整理时更新",
  facts: [
    { id: 41, text: "用户喜欢手绘铅笔风格的界面", cat: "偏好", imp: 3, when: "11-20", confirmed: true },
    { id: 40, text: "用户在开发一个本地记忆库项目，叫「一个时刻陪着你的AI」", cat: "状态", imp: 3, when: "11-19" },
    { id: 39, text: "用户非常在意数据安全，不愿意给软件无障碍权限", cat: "性格", imp: 3, when: "11-19", confirmed: true },
    { id: 38, text: "用户今天中午一点多才去吃午饭", cat: "事件", imp: 1, when: "11-20" },
    { id: 37, text: "用户最近几天都熬夜到凌晨两点以后", cat: "状态", imp: 2, when: "11-18" },
    { id: 36, text: "用户戴手表记录睡眠和心率", cat: "其他", imp: 1, when: "11-19" },
    { id: 35, text: "用户周末常去图书馆看书", cat: "其他", imp: 1, when: "11-19" },
    { id: 22, text: "用户打算先学习、再做项目", cat: "计划", imp: 2, when: "11-02", gone: "11-19 被新事实取代" }
  ],
  log: [
    { t: "19:00:41", who: "DeepSeek", act: "新增", what: "用户喜欢手绘铅笔风格的界面" },
    { t: "19:00:39", who: "DeepSeek", act: "加强", what: "用户在开发一个本地记忆库项目" },
    { t: "19:00:36", who: "DeepSeek", act: "标记失效", what: "用户打算先学习、再做项目（被新事实取代）" },
    { t: "19:00:30", who: "DeepSeek", act: "新增", what: "用户今天中午一点多才去吃午饭" },
    { t: "14:00:12", who: "DeepSeek", act: "新增", what: "用户最近几天都熬夜到凌晨两点以后", undone: true },
    { t: "13:58:02", who: "陪伴聊天", act: "便条", what: "用户说：记住我喜欢手绘铅笔风格" }
  ],
  /* 「由谁来回答」：我们的程序去调用它们（订阅制的走官方命令行），不改它们自己的配置 */
  brains: [
    { id: "deepseek", name: "DeepSeek API", logo: "D", kind: "按用量付费",
      state: "ok", stateText: "已填写 Key", desc: "最快、最便宜。分享给别人时，对方也最容易用上。",
      canChat: true, canOrganize: true },
    { id: "antigravity", name: "Google Antigravity", logo: "G", kind: "订阅额度（Gemini Pro）",
      state: "ok", stateText: "已安装 · 已登录", desc: "通过 agy 命令行。每次对话时临时给它读记忆的权限，你自己打开 Antigravity 时它看不到记忆。",
      models: [{ id: "gemini-3.8-flash-low", name: "Gemini 3.8 Flash (Low)" }, { id: "gemini-3.8-flash-high", name: "Gemini 3.8 Flash (High)" }, { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6 (Thinking)" }], model: "gemini-3.8-flash-low", canChat: true, canOrganize: true },
    { id: "claude", name: "Claude", logo: "C", kind: "订阅额度",
      state: "ok", stateText: "检测到 Claude 桌面版自带的命令行", desc: "通过 Claude Code 命令行。第一次用前要在里面登录一次。",
      canChat: true, canOrganize: true },
    { id: "codex", name: "ChatGPT / Codex", logo: "O", kind: "订阅额度",
      state: "off", stateText: "没找到命令行", desc: "桌面版里的命令行被系统保护起来了，需要另外装官方的 Codex 命令行，再用 ChatGPT 账号登录。",
      models: [], canChat: false, canOrganize: false,
      install: { title: "Codex 命令行", cmd: "npm install -g @openai/codex", login: "用你的 ChatGPT 账号登录一次" } },
    { id: "dsh", name: "DeepSeek Harness", logo: "H", kind: "看你的 dsh 设置",
      state: "warn", stateText: "已安装 · 接法待确认", desc: "它自带一个本地接口，具体怎么接还在研究。",
      models: [], canChat: false, canOrganize: false }
  ],
  chatWallpaper: null,
  settings: {
    organizer: "deepseek", times: "10:00、14:00、19:00、23:30", keySaved: false, keepDays: 30,
    blockedApps: "KeePass.exe\nKeePassXC.exe\n1Password.exe\nBitwarden.exe\nAliPay.exe",
    blockedWords: "密码\n网银\n银行\n支付宝\n微信支付\n无痕\nInPrivate",
    autostart: true, model: "已下载（2.3 GB），已启用"
  },
  library: {
    path: "C:\Users\你\AppData\Local\AlwaysWithYou", canMove: true, readme: "记忆库说明.md",
    archives: [
      { name: "自动备份-20261120-213000.zip", kind: "backup", exportedAt: "2026-11-20 21:30", facts: 128, chats: true, size: 5300000, ok: true },
      { name: "记忆库-旧电脑.zip", kind: "export", exportedAt: "2026-10-02 09:12", facts: 64, chats: false, size: 2100000, ok: true }
    ]
  },
  phone: {
    enabled: true, running: true, error: null, port: 47824, addresses: ["192.168.1.5"],
    pairing: { code: "7K3Q-9XMD-2PLF", expiresIn: 540 },
    devices: [{ id: "a1b2c3d4e5f60718", name: "我的手机", pairedAt: "2026-11-22T20:10:00+08:00", lastSeen: "2026-11-22T21:05:12+08:00" }]
  },
  zones: [
    { id: "Asia/Shanghai", offset: "+0800", cc: "CN" }, { id: "Europe/London", offset: "+0000", cc: "GB" },
    { id: "America/New_York", offset: "-0500", cc: "US" }, { id: "Asia/Tokyo", offset: "+0900", cc: "JP" }
  ]
};
