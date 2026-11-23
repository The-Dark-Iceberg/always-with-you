/* 界面：按地址栏 # 后面的名字切换页面。
   数据来自 api.js：由程序打开时是真实数据，静态预览时是 mock-data.js 的假数据。
   所有给人看的文字都写成 T(中文原文)，翻译在 ui/i18n/<语言>.json（见 i18n.js）。 */
(function () {
  "use strict";
  var M = window.MOCK, A = window.AWY, LIVE = A.live, I = window.I18N, T = window.T;
  var app = document.getElementById("app");
  // 液态玻璃主题（决定 0013）：还有一些小毛病，用户决定先不放出来（2026-11-21）。
  // 代码都留着（css/glass.css、js/glass.js、主题面板）；改成 true 就会在侧边栏「设置」下面出现「主题」入口。
  var GLASS_ENABLED = false;

  function pages() {
    return [
      { id: "today", name: T("今天"), icon: "sun" },
      { id: "chat", name: T("陪我聊聊"), icon: "chat" },
      { id: "memory", name: T("记忆"), icon: "book" },
      { id: "log", name: T("写入日志"), icon: "clock" },
      { id: "brain", name: T("由谁来回答"), icon: "spark" },
      { id: "settings", name: T("设置"), icon: "gear" }
    ];
  }

  /* ---------- 小工具 ---------- */
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function ico(name) { return '<span class="ico" data-icon="' + name + '"></span>'; }
  function head(title, sub, right) {
    return '<header class="page-head"><div><h1 data-sketch="underline" data-sketch-tone="soft">' + title + "</h1>" +
      (sub ? '<p class="sub">' + sub + "</p>" : "") + "</div>" + (right || "") + "</header>";
  }
  function toast(msg) {
    var t = document.getElementById("toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }
  function sw(id, checked, label, track) {
    return '<label class="switch"><input type="checkbox" id="' + id + '"' + (checked ? " checked" : "") + (track ? " data-save" : "") + '>' +
      '<span class="track" data-sketch data-sketch-tone="soft"><span class="knob"></span></span>' +
      (label ? "<span>" + label + "</span>" : "") + "</label>";
  }
  function fail(e) { toast(e && e.message ? e.message : T("出错了")); }
  // 对话框：buttons = [{key, label, primary}]，返回 Promise，得到被点按钮的 key；按 Esc 或点外面得到 null。
  // 正文里也可以放带 data-ans="..." 的按钮（比如存档列表里每一项的「启用」）。
  function choose(title, bodyHtml, buttons, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var mask = document.createElement("div");
      mask.className = "ask-mask";
      mask.innerHTML = '<div class="card ask' + (opts.wide ? " wide" : "") + '" role="dialog" aria-modal="true" aria-labelledby="ask-t" data-sketch>' +
        '<h2 id="ask-t">' + esc(title) + "</h2>" + bodyHtml + '<div class="ask-btns">' + buttons.map(function (b) {
          return '<button class="btn ' + (b.primary ? "primary" : "quiet") + '" data-sketch' + (b.primary ? "" : ' data-sketch-tone="soft"') +
            ' data-ans="' + esc(b.key) + '">' + esc(b.label) + "</button>";
        }).join("") + "</div></div>";
      document.body.appendChild(mask);
      window.Sketch && Sketch.init(mask);
      var first = mask.querySelector(".ask-btns .btn.primary");
      if (first) first.focus();
      function done(v) { document.removeEventListener("keydown", onKey); mask.remove(); resolve(v); }
      function onKey(e) { if (e.key === "Escape") done(null); }
      document.addEventListener("keydown", onKey);
      mask.addEventListener("click", function (e) {
        var a = e.target.closest("[data-ans]");
        if (a) done(a.getAttribute("data-ans"));
        else if (e.target === mask) done(null);
      });
    });
  }
  // 「是 / 否」确认框：点「是」得到 true。
  function ask(title, bodyHtml) {
    return choose(title, bodyHtml, [{ key: "no", label: T("否") }, { key: "yes", label: T("是"), primary: true }])
      .then(function (k) { return k === "yes"; });
  }

  /* ---------- 没保存的修改（决定 0012）：不自动保存；有改动时「保存」按钮一直高亮，想离开时提醒 ---------- */
  var dirty = { root: null, snap: "", save: null };
  function formValues(root) {
    var o = {};
    root.querySelectorAll("[data-save]").forEach(function (el) { o[el.id] = el.type === "checkbox" ? el.checked : el.value; });
    return JSON.stringify(o);
  }
  function trackForm(root, saveFn) { dirty.root = root; dirty.save = saveFn; dirty.snap = root ? formValues(root) : ""; updateDirty(); }
  function isDirty() { return !!(dirty.root && document.body.contains(dirty.root) && formValues(dirty.root) !== dirty.snap); }
  function updateDirty() {
    var d = isDirty();
    document.querySelectorAll(".save-btn").forEach(function (b) { b.classList.toggle("dirty", d); });
    document.querySelectorAll(".save-note").forEach(function (n) { n.hidden = !d; });
  }
  // 要离开（换页、切语言、翻引导的下一步）之前调用：有没保存的修改就问一句。得到 true 才继续。
  function leaveOk() {
    if (!isDirty()) return Promise.resolve(true);
    return choose(T("有修改还没保存"), "<p>" + T("刚才改的设置还没保存。不保存就离开，这些修改会丢掉。") + "</p>",
      [{ key: "stay", label: T("留在这里") }, { key: "drop", label: T("不保存") }, { key: "save", label: T("保存"), primary: true }])
      .then(function (k) {
        if (k === "drop") { dirty.root = null; return true; }
        if (k === "save" && dirty.save) return dirty.save().then(function () { return true; }, function (e) { fail(e); return false; });
        return false;
      });
  }
  function lines(v) { return v.split("\n").map(function (x) { return x.trim(); }).filter(Boolean); }

  // 一键安装：确认后让后台打开 PowerShell 窗口；之后每 5 秒看一次装好没有，装好了自动刷新页面
  var installWatch = null;
  function startInstall(id) {
    data.brains().then(function (list) {
      var b = list.filter(function (x) { return x.id === id; })[0];
      if (!b || !b.install) { go(); return; }
      var it = b.install;
      return ask(T("安装 {name}？", { name: it.title }),
        "<p>" + T("会打开一个 PowerShell 窗口，从官方网站下载并运行安装程序。运行的命令是：") + "</p>" +
        "<p><code>" + esc(it.cmd) + "</code></p>" +
        "<p>" + T("装好后它会自动启动一次，请按提示{login}。登录完关掉那个窗口，回到这里就能用了。", { login: esc(it.login) }) + "</p>"
      ).then(function (ok) {
        if (!ok) return;
        if (!LIVE) { toast(T("（预览演示）这里会打开 PowerShell 窗口")); return; }
        return A.post("/api/install/" + id).then(function (r) {
          toast(r.message);
          clearInterval(installWatch);
          var tries = 0;
          installWatch = setInterval(function () {
            if (++tries > 180 || (location.hash || "#today") !== "#brain") { clearInterval(installWatch); return; }
            data.brains().then(function (l) {
              var nb = l.filter(function (x) { return x.id === id; })[0];
              if (nb && !nb.install) { clearInterval(installWatch); toast(T("{name} 装好了", { name: it.title })); go(); }
            });
          }, 5000);
        });
      });
    }).catch(fail);
  }
  // AI 的回复里常有 **加粗**、`代码`：先整体转义（防止注入），再把这两种标记换成样式
  function rich(s) {
    return esc(s).replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
  }

  /* ---------- 偏好（头像、壁纸、侧边栏）：程序里存数据目录，预览时存浏览器 ---------- */
  var prefs = {
    cache: {},
    load: function () {
      if (LIVE) return A.get("/api/prefs").then(function (p) { prefs.cache = p; }).catch(function () {});
      ["avatar", "wallpaper", "veil", "side", "lang", "tlorder", "skin", "glassbg", "glassmode", "glassveil", "motion"].forEach(function (k) {
        try { var v = localStorage.getItem("awy." + k); if (v != null) prefs.cache[k] = v; } catch (e) {}
      });
      return Promise.resolve();
    },
    get: function (k) { return prefs.cache[k] == null ? null : prefs.cache[k]; },
    set: function (k, v) {
      if (v == null) delete prefs.cache[k]; else prefs.cache[k] = v;
      if (LIVE) {
        if (v == null) return A.del("/api/prefs/" + k);
        return A.post("/api/prefs/" + k, (k === "avatar" || k === "wallpaper") ? { data: v } : { value: v });
      }
      try { if (v == null) localStorage.removeItem("awy." + k); else localStorage.setItem("awy." + k, v); return Promise.resolve(); }
      catch (e) { return Promise.reject(new Error(T("存不下"))); }
    }
  };

  /* ---------- 取数据（真实接口 / 假数据） ---------- */
  var data = {
    status: function () { return LIVE ? A.get("/api/status") : Promise.resolve(M.status); },
    today: function () { return LIVE ? A.get("/api/today") : Promise.resolve(M.today); },
    // 聊天记录分页：一次 30 条；before 是当前最上面那条的 id，往上滑时再要更早的一页
    chat: function (before) {
      if (!LIVE) return Promise.resolve({ more: false, items: before ? [] : M.chat.map(function (m, i) {
        return { id: "mock:" + i, role: m.who, text: m.text, tools: m.tool ? [m.tool] : [] }; }) });
      return A.get("/api/chat/history" + (before ? "?before=" + encodeURIComponent(before) : ""));
    },
    memory: function (q, hist) {
      if (!LIVE) return Promise.resolve({ persona: M.persona, personaMeta: M.personaMeta, facts: M.facts });
      return A.get("/api/memory?q=" + encodeURIComponent(q || "") + (hist ? "&history=1" : ""));
    },
    log: function () { return LIVE ? A.get("/api/log") : Promise.resolve(M.log.map(function (l, i) { return Object.assign({ id: i, undoable: !l.undone }, l); })); },
    brains: function () { return LIVE ? A.get("/api/brains") : Promise.resolve(M.brains); },
    library: function () { return LIVE ? A.get("/api/library") : Promise.resolve(M.library); },
    settings: function () {
      if (LIVE) return A.get("/api/settings");
      var s = M.settings;
      return Promise.resolve({ organize_times: s.times.split("、"), blocked_apps: s.blockedApps.split("\n"),
        blocked_keywords: s.blockedWords.split("\n"), raw_retention_days: s.keepDays, autostart: s.autostart,
        keySaved: s.keySaved, model: s.model, organizer: "deepseek", language: prefs.get("lang") || "" });
    }
  };
  var STATUS = M.status;   // 边栏和各页共用的状态，进入每页时刷新

  /* ---------- 各页面：render.xxx(数据) 返回 HTML ---------- */
  var render = {}, loaders = {};

  loaders.today = function () { return data.today(); };
  // 「今天」时间线的顺序：默认从早到晚；选了从晚到早会记住（偏好 tlorder = "desc"）
  var todayTimeline = [];
  function tlDesc() { return prefs.get("tlorder") === "desc"; }
  function tlOrderLabel() { return (tlDesc() ? "↓ " + T("从晚到早") : "↑ " + T("从早到晚")); }
  function timelineRows(list) {
    if (!list.length) return '<li class="away"><span class="when">—</span><span class="what muted">' + T("今天还没有记录") + "</span><span></span></li>";
    var rows = tlDesc() ? list.slice().reverse() : list;
    return rows.map(function (r, i) {
      return '<li class="' + (r.away ? "away " : "") + 'enter" style="--i:' + (i + 3) + '"><span class="when">' + esc(r.when) +
        '</span><span class="what">' + (r.away ? '<span class="muted">' + esc(r.t) + "</span>" :
          "<b>" + esc(r.app) + "</b>" + (r.t ? ' <span class="t">· ' + esc(r.t) + "</span>" : "")) +
        '</span><span class="dur">' + esc(r.dur) + "</span></li>";
    }).join("");
  }
  function toggleTimelineOrder() {
    prefs.set("tlorder", tlDesc() ? null : "desc").catch(fail);
    var list = document.getElementById("tl-list"), lab = document.getElementById("tl-order-lab");
    if (list) list.innerHTML = timelineRows(todayTimeline);
    if (lab) lab.textContent = tlOrderLabel();
  }
  render.today = function (t) {
    var h = head(T("今天"), new Date(todayStr() + "T12:00:00").toLocaleDateString(I.locale, { month: "long", day: "numeric", weekday: "long" }) +
      (STATUS.timezone ? ' <span class="small">· ' + esc(STATUS.timezone) + " " + esc(STATUS.now || "") + "</span>" : ""),
      '<button class="btn primary" data-sketch data-act="organize">' + ico("spark") + T("现在整理一次") + "</button>");
    h += '<p class="hello enter" style="--i:0">' + esc(t.greeting) + "</p>";
    h += '<div class="grid-3 section">';
    t.stats.forEach(function (s, i) {
      h += '<div class="card stat enter" style="--i:' + (i + 1) + '" data-sketch><div class="num">' + esc(s.num) +
        '</div><div class="lab">' + esc(s.lab) + "</div></div>";
    });
    h += '</div><div class="grid-2 section" style="grid-template-columns: 3fr 2fr">';
    todayTimeline = t.timeline;
    h += '<section><h2 class="tl-head">' + T("时间线") + ' <span class="small">' + T("只在本机，不会原样发给 AI") + "</span>" +
      '<button class="chip filter tl-order" data-sketch data-sketch-tone="soft" data-act="tl-order" title="' + esc(T("点一下换个顺序")) + '">' +
      '<span id="tl-order-lab">' + tlOrderLabel() + "</span></button>" +
      '</h2><ul class="timeline" id="tl-list">' + timelineRows(t.timeline) + "</ul></section>";
    var max = Math.max.apply(null, t.apps.map(function (a) { return a.min; }).concat([1]));
    h += "<section><h2>" + T("按软件") + '</h2><div class="apps">';
    if (!t.apps.length) h += '<p class="small">' + T("还没有数据") + "</p>";
    t.apps.forEach(function (a) {
      h += '<div class="row"><span>' + esc(a.name) + '</span><span class="bar" data-sketch data-sketch-tone="soft"><i style="width:calc(' +
        (a.min / max * 100) + '% - 6px)"></i></span><span class="n">' + T("{h}时{m}分", { h: Math.floor(a.min / 60), m: a.min % 60 }) + "</span></div>";
    });
    return h + "</div></section></div>";
  };

  loaders.chat = function () { return Promise.all([data.chat(), data.brains()]); };
  render.chat = function (d) {
    var history = d[0].items, brains = d[1];
    chatPage.more = d[0].more; chatPage.cursor = history.length ? history[0].id : null; chatPage.loading = false;
    var who = brains.filter(function (b) { return b.id === STATUS.chatBrain; })[0];
    var right = '<div class="head-tools"><span class="small">' +
      T("现在由 {name} 回答", { name: '<a href="#brain">' + esc(who ? who.name : T("未选择")) + "</a>" }) + "</span>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="wall-panel" aria-expanded="false">' + ico("image") + T("壁纸") + "</button>" +
      '<div class="wall-panel card" id="wall-panel" data-sketch hidden>' +
      "<h3>" + T("聊天壁纸") + '</h3><p class="small">' + T("选一张自己喜欢的图片。图片只存在这台电脑上。") + "</p>" +
      '<label class="btn primary" data-sketch>' + ico("image") + T("选择图片") + '<input type="file" id="wall-file" accept="image/*" hidden></label>' +
      '<label class="range"><span>' + T("图片更明显") + '</span><input type="range" id="wall-veil" min="0" max="90" step="5"><span>' + T("字更清楚") + "</span></label>" +
      '<button class="btn quiet" data-act="wall-reset">' + ico("undo") + T("恢复默认") + "</button></div></div>";
    var h = '<div class="chat">' + head(T("陪我聊聊"), T("这里的 AI 会先看一眼你的记忆再说话；你说「记住……」它就会记下来。"), right);
    h += '<div class="msgs-wrap" id="msgs-wrap"><div class="chat-wall" id="chat-wall"></div><div class="msgs" id="msgs">';
    h += moreHint();
    if (!history.length) h += '<p class="small" style="text-align:center;margin-top:30px">' + T("还没有聊过天。说点什么吧。") + "</p>";
    h += msgList(history, true);
    h += '</div></div><div class="compose"><span class="input-wrap" data-sketch><textarea class="textarea" id="say" rows="1" placeholder="' +
      esc(T("想说点什么……（Enter 发送，Shift+Enter 换行）")) + '"></textarea></span>' +
      '<button class="btn primary" data-sketch data-act="send" id="send-btn">' + ico("send") + T("发送") + "</button></div></div>";
    return h;
  };
  /* 聊天记录很长时：只画最近 30 条，滑到顶部再自动加载更早的一页，滚动位置保持不动 */
  var chatPage = { more: false, cursor: null, loading: false };
  function moreHint() {
    return '<div class="more-hint small" id="more-hint"' + (chatPage.more ? "" : " hidden") + ">" + T("往上滑，加载更早的聊天") + "</div>";
  }
  // 「今天」以后台为准：设置里选了别的地区时，和电脑的日期可能不一样
  function todayStr() {
    if (STATUS && STATUS.today) return STATUS.today;
    var n = new Date();
    return n.getFullYear() + "-" + String(n.getMonth() + 1).padStart(2, "0") + "-" + String(n.getDate()).padStart(2, "0");
  }
  function dayOf(m) { return (m.ts || "").slice(0, 10); }
  function dayLabel(day) {
    if (!day) return "";
    var d = new Date(day + "T00:00:00"), today = new Date(todayStr() + "T00:00:00");
    var diff = Math.round((today - d) / 86400000);
    if (diff === 0) return T("今天");
    if (diff === 1) return T("昨天");
    return d.toLocaleDateString(I.locale, { month: "long", day: "numeric", weekday: "short" });
  }
  function divider(day) { return '<div class="day-sep" data-day="' + esc(day) + '"><span>' + esc(dayLabel(day)) + "</span></div>"; }
  // 一串消息（从旧到新），每换一天插一条日期分隔线
  function msgList(items, animate) {
    var h = "", last = null;
    items.forEach(function (m, i) {
      var day = dayOf(m);
      if (day && day !== last) { h += divider(day); last = day; }
      h += msg(m, animate ? i : 0, !animate);
    });
    return h;
  }
  function loadOlder() {
    var box = document.getElementById("msgs");
    if (!box || !chatPage.more || chatPage.loading || !chatPage.cursor) return;
    chatPage.loading = true;
    var hint = document.getElementById("more-hint");
    hint.textContent = T("正在加载……");
    data.chat(chatPage.cursor).then(function (page) {
      chatPage.loading = false;
      chatPage.more = page.more;
      hint.textContent = T("往上滑，加载更早的聊天");
      hint.hidden = !page.more;
      if (!page.items.length) return;
      chatPage.cursor = page.items[0].id;
      var oldH = box.scrollHeight, oldTop = box.scrollTop;
      var tmp = document.createElement("div");
      tmp.innerHTML = msgList(page.items, false);
      var next = hint.nextSibling;
      // 新加载的最后一天和原来最上面的是同一天：去掉原来那条重复的日期线
      var lastDay = dayOf(page.items[page.items.length - 1]);
      if (next && next.classList && next.classList.contains("day-sep") && next.getAttribute("data-day") === lastDay) next.remove();
      next = hint.nextSibling;
      while (tmp.firstChild) box.insertBefore(tmp.firstChild, next);
      Sketch.init(box);
      box.scrollTop = box.scrollHeight - oldH + oldTop;   // 内容加在上面，眼前看到的位置不跳
    }).catch(function (e) { chatPage.loading = false; hint.textContent = (e && e.message) || T("出错了"); });
  }
  function msg(m, i, still) {
    var ai = m.role !== "me";
    return '<div class="msg ' + (ai ? "ai" : "me") + (still ? "" : " enter") + '" style="--i:' + Math.min(i || 0, 8) + '" data-sketch' + (ai ? "" : ' data-sketch-tone="soft"') + ">" +
      '<div class="who">' + (ai ? T("陪着你") : T("我")) + "</div>" +
      ((m.tools || []).map(function (t) { return '<div class="tool">' + ico("book") + esc(t) + "</div>"; }).join("")) +
      '<div class="body">' + (ai ? rich(m.text) : esc(m.text).replace(/\n/g, "<br>")) + "</div></div>";
  }

  // 分类小标签：[全部 12] [偏好 5] ……，点了只看这一类
  function chips(group, counts, order, names, cur) {
    var total = 0; Object.keys(counts).forEach(function (k) { total += counts[k]; });
    var keys = order.filter(function (k) { return counts[k]; }).concat(Object.keys(counts).filter(function (k) { return order.indexOf(k) < 0; }));
    return '<div class="filter-row" role="group">' + [""].concat(keys).map(function (k) {
      var on = (cur || "") === k;
      return '<button class="chip filter' + (on ? " on" : "") + '" data-sketch' + (on ? ' data-sketch-tone="accent"' : ' data-sketch-tone="soft"') +
        ' data-act="filter" data-group="' + group + '" data-id="' + esc(k) + '" aria-pressed="' + on + '">' +
        esc(k ? names[k] || k : T("全部")) + ' <span class="n">' + (k ? counts[k] : total) + "</span></button>";
    }).join("") + "</div>";
  }
  function exportBtn(kind) {
    return '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="export" data-id="' + kind + '">' + ico("download") + T("导出 TXT") + "</button>";
  }
  var CAT_ORDER = ["trait", "preference", "habit", "relation", "health", "plan", "state", "event", "shared"];
  function factItem(f, i) {
    return '<li class="fact' + (f.gone ? " gone" : "") + ' enter" style="--i:' + Math.min(i + 1, 10) + '"><span class="txt">' +
      (f.confirmed ? '<span class="ok">' + ico("check") + "</span>" : "") + esc(f.text) +
      '</span><span class="tags"><span class="chip" data-sketch data-sketch-tone="soft">' + esc(f.cat) +
      '</span><span class="imp" title="' + esc(T("重要程度")) + '">' + "●●●".slice(0, f.imp) + "○○○".slice(f.imp) + "</span>" +
      (f.src ? '<span class="src src-' + esc(f.srcKey || "") + '" title="' + esc(T("这条记忆是谁说的")) + '">' + esc(f.src) + "</span>" : "") +
      "<span>" + esc(f.when) + "</span></span>" +
      (f.gone ? '<span class="small" style="grid-column:1/-1">' + esc(f.gone) + "</span>" : "") + "</li>";
  }

  var memState = { q: "", hist: false, cat: "" };
  loaders.memory = function () { return data.memory(memState.q, memState.hist); };
  render.memory = function (d) {
    var h = head(T("记忆"), T("AI 对你的了解。写错了的可以到「写入日志」里撤回，被推翻的旧事实会划掉保留。"), exportBtn("memory"));
    h += '<section class="card persona lined enter" style="--i:0" data-sketch><h2 style="margin-bottom:8px">' + T("核心画像") + "</h2>";
    if (!d.persona.length) h += '<p class="muted">' + T("还没有核心画像。") + "</p>";
    d.persona.forEach(function (p) { h += "<p>" + esc(p) + "</p>"; });
    h += '<p class="small meta">' + esc(d.personaMeta) + "</p></section>";
    h += '<section class="section"><div class="toolbar"><span class="input-wrap" data-sketch>' + ico("search") +
      '<input class="input" id="mem-q" placeholder="' + esc(T("按意思搜索，比如：最近睡得怎么样")) + '" value="' + esc(memState.q) + '"></span>' +
      sw("hist", memState.hist, T("也看已经不成立的")) + "</div>";
    var counts = {}, names = {};
    d.facts.forEach(function (f) { var k = f.catKey || f.cat; counts[k] = (counts[k] || 0) + 1; names[k] = f.cat; });
    if (memState.cat && !counts[memState.cat]) memState.cat = "";
    if (d.facts.length) h += chips("cat", counts, CAT_ORDER, names, memState.cat);
    var shown = d.facts.filter(function (f) { return !memState.cat || (f.catKey || f.cat) === memState.cat; });
    if (!shown.length) h += '<ul class="facts"><li class="fact"><span class="txt muted">' + (memState.q ? T("没有找到相关的记忆") : T("记忆库还是空的，整理几次以后这里会慢慢多起来")) + "</span></li></ul>";
    else if (memState.q || memState.cat) h += '<ul class="facts">' + shown.map(factItem).join("") + "</ul>";   // 搜索结果按相关度排，不分组
    else {
      // 「全部」时按大分类分组显示
      var keys = CAT_ORDER.filter(function (k) { return counts[k]; }).concat(Object.keys(counts).filter(function (k) { return CAT_ORDER.indexOf(k) < 0; }));
      keys.forEach(function (k) {
        var items = shown.filter(function (f) { return (f.catKey || f.cat) === k; });
        h += '<h3 class="group-head">' + esc(names[k]) + ' <span class="small">' + items.length + "</span></h3>" +
          '<ul class="facts">' + items.map(factItem).join("") + "</ul>";
      });
    }
    return h + "</section>";
  };

  var logState = { act: "" };
  var ACT_ORDER = ["add_fact", "invalidate_fact", "reinforce_fact", "set_persona", "add_entity", "mark_processed", "undo"];
  loaders.log = function () { return data.log(); };
  render.log = function (list) {
    var h = head(T("写入日志"), T("每一次对记忆的改动都在这里。点「撤销」可以撤回，不会真的删除。"), exportBtn("log"));
    var counts = {}, names = {};
    list.forEach(function (l) { var k = l.actKey || l.act; counts[k] = (counts[k] || 0) + 1; names[k] = l.act; });
    if (logState.act && !counts[logState.act]) logState.act = "";
    if (list.length) h += chips("act", counts, ACT_ORDER, names, logState.act);
    var shown = list.filter(function (l) { return !logState.act || (l.actKey || l.act) === logState.act; });
    h += '<ul class="log">';
    if (!shown.length) h += '<li><span class="small" style="grid-column:1/-1">' + T("还没有任何写入") + "</span></li>";
    var day = null;
    shown.forEach(function (l, i) {
      if (l.day && l.day !== day) { day = l.day; h += '<li class="log-day">' + divider(day) + "</li>"; }   // 按天分组
      h += '<li class="' + (l.undone ? "undone " : "") + 'enter" style="--i:' + Math.min(i, 10) + '"><span class="t">' + esc(l.t) +
        '</span><span class="who">' + esc(l.who) + '</span><span class="what"><span class="act">' + esc(l.act) + "</span>" + esc(l.what) +
        "</span>" + (l.undone ? '<span class="small">' + T("已撤销") + "</span>" : l.undoable ?
          '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="undo" data-id="' + l.id + '">' + ico("undo") + T("撤销") + "</button>" : "<span></span>") + "</li>";
    });
    return h + "</ul>";
  };

  loaders.brain = function () { return data.brains(); };
  render.brain = function (brains) {
    function nameOf(id) { var b = brains.filter(function (x) { return x.id === id; })[0]; return b ? b.name : T("未选择"); }
    var h = head(T("由谁来回答"), T("聊天在这里进行，背后的「大脑」由你选。你自己打开这些软件时，它们照常工作、看不到你的记忆。"));
    h += '<div class="grid-2 enter" style="--i:0">' +
      '<section class="card pick" data-sketch data-sketch-tone="accent">' + ico("chat") + '<div><div class="small">' + T("陪我聊聊") + "</div><h2>" + esc(nameOf(STATUS.chatBrain)) + "</h2></div></section>" +
      '<section class="card pick" data-sketch data-sketch-tone="accent">' + ico("spark") + '<div><div class="small">' + T("整理记忆") + "</div><h2>" + esc(nameOf(STATUS.organizeBrain)) + "</h2></div></section></div>";
    h += '<div class="tools section">';
    brains.forEach(function (b, i) {
      var dot = b.state === "ok" ? "" : b.state === "warn" ? " warn" : " off";
      var tags = (STATUS.chatBrain === b.id ? '<span class="chip" data-sketch data-sketch-tone="accent">' + T("聊天用它") + "</span>" : "") +
        (STATUS.organizeBrain === b.id ? '<span class="chip" data-sketch data-sketch-tone="accent">' + T("整理用它") + "</span>" : "");
      var acts = "";
      if (b.canChat && STATUS.chatBrain !== b.id) acts += '<button class="btn primary" data-sketch data-act="use-chat" data-id="' + b.id + '">' + ico("chat") + T("聊天用它") + "</button>";
      if (b.canOrganize && STATUS.organizeBrain !== b.id) acts += '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="use-org" data-id="' + b.id + '">' + ico("spark") + T("整理用它") + "</button>";
      if (b.install) acts += '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="install" data-id="' + b.id + '">' + ico("download") + T("一键安装") + "</button>";
      if (!acts && !tags) acts = '<span class="small">' + T("暂时不能用") + "</span>";
      h += '<div class="card tool-card enter" style="--i:' + (i + 1) + '" data-sketch' + (b.state === "off" ? ' data-sketch-tone="soft"' : "") + ">" +
        '<div class="head"><span class="logo" data-sketch="circle" data-sketch-tone="soft">' + esc(b.logo) + "</span><div><h3>" + esc(b.name) +
        '</h3><div class="small">' + esc(b.kind) + '</div></div><span class="state"><span class="dot' + dot + '"></span>' + esc(b.stateText) + "</span></div>" +
        '<p class="muted">' + esc(b.desc) + "</p>" + (tags ? '<div class="tags-row">' + tags + "</div>" : "") +
        (b.models && b.models.length ? '<label class="model-pick"><span class="small">' + T("模型档位") + "</span>" +
          '<span class="input-wrap" data-sketch data-sketch-tone="soft"><select class="input" id="agy-model">' +
          b.models.map(function (m) { return '<option value="' + esc(m.id) + '"' + (m.id === b.model ? " selected" : "") + ">" + esc(m.name) + "</option>"; }).join("") +
          '</select></span><span class="small">' + T("聊天用 Low 最快；High 会先深度思考，一句话可能要几分钟。") + "</span></label>" : "") +
        '<div class="actions">' + acts + "</div></div>";
    });
    h += "</div>";
    return h + '<p class="small section">' + T("订阅制的 AI 会用你自己的账号和额度。把这个软件分享给别人时，对方需要用自己的账号登录自己的工具。") + "</p>";
  };

  loaders.settings = function () {
    return Promise.all([data.settings(), data.library()]).then(function (r) { r[0].library = r[1]; return r[0]; });
  };
  render.settings = function (s) {
    var h = head(T("设置"), T("改完点最下面的「保存」。"));
    function field(label, ctrl, hint, i) {
      return '<div class="field enter" style="--i:' + i + '"><label>' + label + "</label>" + ctrl + (hint ? '<p class="hint">' + hint + "</p>" : "") + "</div>";
    }
    function wrap(inner, style) { return '<span class="input-wrap" data-sketch data-sketch-tone="soft"' + (style ? ' style="' + style + '"' : "") + ">" + inner + "</span>"; }
    var sep = I.lang === "zh" ? "、" : ", ";
    h += '<section class="card" data-sketch><h2 style="margin-bottom:4px">' + T("整理记忆") + "</h2>";
    h += field("DeepSeek API Key", wrap('<input class="input" id="set-key" type="password" autocomplete="off" data-save placeholder="' + esc(s.keySaved ? T("已保存（加密）") : "sk-……") + '">'),
      T("只保存在这台电脑上，用 Windows 自带的加密功能锁住。聊天和整理都可以用它。"), 0);
    h += field(T("整理时间"), wrap('<input class="input" id="set-times" data-save value="' + esc(s.organize_times.join(sep)) + '">'), T("用顿号分开。电脑关着错过的，开机后会补一次。"), 1);
    h += field(T("我所在的地区"), tzPicker("set-tz", s.timezone),
      T("一般选「跟随电脑」。电脑时区和你实际生活的地方不一样时（比如人在英国、电脑是北京时间），可以搜城市或国家，选你所在的地方。整理时间、「今天」和记忆里的时间都按它算。"), 1);
    h += field(T("聊天内容参与整理"), sw("set-chatmem", s.chat_in_memory !== false, T("你和 AI 的聊天会和电脑活动一起整理进记忆"), true),
      T("整理时，这段时间的聊天原话（双方，太长的会截短）会交给整理记忆的 AI。你说的话最可信；AI 的话只用来记「聊过什么」，或者在你认同时才算数。"), 1);
    h += '</section><section class="card section" data-sketch><h2 style="margin-bottom:4px">' + T("隐私") + "</h2>";
    h += field(T("不记录的软件"), wrap('<textarea class="textarea" id="set-apps" data-save>' + esc(s.blocked_apps.join("\n")) + "</textarea>"), T("一行一个进程名。这些软件只会记成「隐私窗口」。"), 2);
    h += field(T("标题含这些词时不记"), wrap('<textarea class="textarea" id="set-words" data-save>' + esc(s.blocked_keywords.join("\n")) + "</textarea>"), "", 3);
    h += field(T("原始记录保留"), wrap('<input class="input" id="set-keep" data-save type="number" min="1" max="3650" value="' + esc(s.raw_retention_days) + '">', "max-width:160px"), T("天。到期自动删除，整理出来的记忆会一直保留。"), 4);
    h += '</section><section class="card section" data-sketch><h2 style="margin-bottom:4px">' + T("其他") + "</h2>";
    h += field(ico("globe") + " " + T("语言") + (I.lang === "zh" ? "" : " · 语言") + (I.lang === "en" ? "" : " · Language"), langButtons(s.language), T("切换后立刻生效，不用保存。"), 5);
    h += field(T("头像"), '<div class="avatar-row"><span class="avatar-preview" data-sketch="circle" data-sketch-tone="soft">' + avatarInner() + "</span>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="avatar-pick">' + ico("image") + T("更换") + "</button>" +
      '<button class="btn quiet" data-act="avatar-reset">' + ico("undo") + T("恢复默认") + "</button></div>", T("显示在左上角的圆圈里。也可以直接点左上角的圆圈来换。"), 6);
    h += field(T("按意思搜索的模型"), modelBox(s),
      T("bge-m3（约 2.3GB），只在本机运行。不下载也能用，只是只能按关键词搜索。下载中途断了，再点一次会接着下。"), 7);
    h += field(T("浏览器扩展"), '<div><div class="avatar-row"><span id="ext-status" class="small"></span>' +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="ext-install">' + ico("download") + T("安装浏览器扩展") + "</button></div>" +
      '<div class="small ext-note" id="ext-note"></div></div>',
      T("让它知道你在看哪个网页：只记 https 网页的网址（去掉参数）、域名、标题和搜索词，不读网页内容。支持 Edge 和 Chrome。"), 8);
    h += field(T("开机自动启动"), sw("set-auto", s.autostart, T("只在右下角托盘里"), true), "", 8);
    h += field(T("使用引导"), '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="guide-open">' + ico("arrow-right") + T("重新打开引导") + "</button>",
      T("第一次打开时那几步设置说明。"), 9);
    h += '</section><div class="save-bar section"><button class="btn primary save-btn" data-sketch data-act="save">' + ico("check") + T("保存") +
      '</button><span class="save-note" hidden>' + ico("arrow-left") + T("有修改还没保存，记得点「保存」") + "</span></div>";
    var lib = s.library || {};
    h += '<section class="card section" data-sketch><h2 style="margin-bottom:4px">' + T("记忆库") + "</h2>";
    // 路径和按钮包成一块：不然按钮那一行会被排进左边的标签列（只有 180px 宽）
    h += field(T("位置"), '<div><div class="lib-path"><code>' + esc(lib.path || "—") + "</code></div>" +
      '<div class="avatar-row"><button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lib-open">' + ico("folder") + T("打开文件夹") + "</button>" +
      (lib.canMove === false ? "" : '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lib-move">' + ico("arrow-right") + T("更改位置…") + "</button>") + "</div></div>",
      T("你的记忆、聊天记录和设置都在这个文件夹里。最外层有一份「{f}」，是写给 AI 看的：每个文件是什么、怎么读。", { f: esc(lib.readme || "记忆库说明.md") }), 10);
    h += field(T("导出记忆库"), '<div class="avatar-row">' +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lib-export">' + ico("download") + T("导出压缩包") + "</button></div>",
      T("压缩包里有说明、整理好的「记忆.md」、完整的记忆库和全部聊天记录（单独一个文件夹）。导出时密码、密钥、手机号、证件号这类内容会换成「[已隐藏]」。在别的电脑上解压，把文件夹拖给任意 Agent，它读了说明就能接着了解你。不含 API Key 和原始窗口记录。压缩包没有密码，请自己保管好。"), 11);
    h += field(T("记忆存档"), '<div class="avatar-row"><button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lib-archives">' + ico("box") + T("打开记忆存档") + "</button>" +
      '<span class="small">' + T("{n} 个压缩包", { n: (lib.archives || []).length }) + "</span></div>",
      T("导入的记忆库压缩包和自动备份都放在这里。选一个点「启用」就换成那份记忆；换之前，当前的记忆会自动备份成压缩包放进来，随时能换回去。"), 12);
    h += "</section>";
    // 手机（决定 0014）：内容由 phoneBox() 画，状态单独去取（打开、配对都是立刻生效，不走「保存」）
    h += '<section class="card section" data-sketch><h2 style="margin-bottom:4px">' + T("手机") + '</h2><div id="phone-box">' +
      phoneBox(LIVE ? null : M.phone) + "</div></section>";
    h += '<section class="card section" data-sketch><h2 style="margin-bottom:4px">' + T("关于与更新") + "</h2>";
    h += field(T("当前版本"), '<div><div class="avatar-row"><span>' + esc(STATUS.version || "—") + "</span>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="update-check" id="update-btn">' + ico("download") + T("检查更新") + "</button></div>" +
      '<div class="bar" id="update-bar" data-sketch data-sketch-tone="soft" hidden><i style="width:0"></i></div><p class="small" id="update-note"></p></div>',
      T("只在你点这个按钮时联网，去 GitHub 上的发布仓库看有没有新版本。更新时记忆和设置都会保留。"), 9);
    h += "</section>";
    return h;
  };
  function modelBox(s) {
    var btn = s.modelEnabled ? "" : '<button class="btn primary" data-sketch data-act="model-dl" id="model-btn" data-installed="' + (s.modelInstalled ? 1 : 0) + '">' + ico("download") +
      "<span>" + (s.modelInstalled ? T("启用模型") : T("下载并启用")) + "</span></button>";
    return '<div class="model-box"><div class="avatar-row"><span id="model-text">' + esc(s.model) + "</span>" + btn + "</div>" +
      '<div class="bar" id="model-bar" data-sketch data-sketch-tone="soft" hidden><i style="width:0"></i></div><p class="small" id="model-note"></p></div>';
  }
  // 「我所在的地区」：上面一个搜索框，下面是选项（名字按界面语言显示，如「英国 · 伦敦」）
  function tzPicker(id, cur) {
    function wrap(inner) { return '<span class="input-wrap" data-sketch data-sketch-tone="soft">' + inner + "</span>"; }
    return '<div class="tz-pick">' + wrap('<input class="input" id="' + id + '-q" autocomplete="off" placeholder="' + esc(T("搜索城市或国家，如 伦敦 / 英国 / London")) + '">') +
      wrap('<select class="input" id="' + id + '" data-save><option value="">' + esc(T("跟随电脑")) + "</option>" +
        (cur ? '<option value="' + esc(cur) + '" selected>' + esc(cur) + "</option>" : "") + "</select>") + "</div>";
  }
  // 语言按钮：跟随系统 + 每种语言（语言名用它自己的文字写，看不懂当前语言的人也能找到自己的）
  function langButtons(setting) {
    var opts = [{ code: "", name: T("跟随系统") }].concat(I.LANGS);
    return '<div class="lang-row">' + opts.map(function (l) {
      var on = (setting || "") === l.code;
      return '<button class="btn ' + (on ? "primary" : "quiet") + '" data-sketch' + (on ? "" : ' data-sketch-tone="soft"') +
        ' data-act="set-lang" data-id="' + l.code + '" aria-pressed="' + on + '">' + esc(l.name) + "</button>";
    }).join("") + "</div>";
  }

  /* ---------- 边栏 ---------- */
  function renderNav(cur) {
    var nav = document.getElementById("nav"), h = "";
    pages().forEach(function (p) {
      h += '<a href="#' + p.id + '" title="' + esc(p.name) + '" class="' + (p.id === cur ? "on" : "") + '">' + ico(p.icon) + '<span class="label">' + p.name + "</span></a>";
    });
    // 「设置」下面：主题（铅笔手绘 / 液态玻璃，决定 0013）。液态玻璃暂时关闭时不显示这个入口
    if (GLASS_ENABLED) {
      var tpOpen = !!document.getElementById("theme-panel");
      h += '<span class="nav-sep" aria-hidden="true"></span><button type="button" class="nav-theme" data-act="theme-panel" aria-haspopup="dialog" aria-expanded="' + tpOpen +
        '" title="' + esc(T("主题")) + '">' + ico("palette") + '<span class="label">' + T("主题") + "</span></button>";
    }
    nav.innerHTML = h;
    var s = STATUS, on = s.collecting !== false;
    var curLang = I.LANGS.filter(function (l) { return l.code === I.lang; })[0];
    document.getElementById("side-foot").innerHTML =
      '<div class="status-line" title="' + (on ? T("正在记录") : T("已暂停记录")) + '"><span class="dot' + (on ? "" : " off") + '"></span><span class="label">' + (on ? T("正在记录") : T("已暂停记录")) + "</span></div>" +
      '<div class="small label">' + T("下次整理 {time}", { time: esc(s.nextOrganize || "—") }) + "</div>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="pause">' + ico(on ? "pause" : "play") + '<span class="label">' + (on ? T("暂停记录") : T("继续记录")) + "</span></button>" +
      '<div class="lang-pick"><button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lang-menu" aria-haspopup="true" aria-expanded="false" title="语言 / Language" aria-label="语言 / Language">' +
      ico("globe") + '<span class="label">' + esc(curLang.name) + "</span></button>" +
      '<div class="lang-menu card" id="lang-menu" data-sketch hidden>' + I.LANGS.map(function (l) {
        return '<button class="lang-item' + (l.code === I.lang ? " on" : "") + '" data-act="set-lang" data-id="' + l.code + '">' + esc(l.name) + "</button>";
      }).join("") + "</div></div>";
    window.Sketch && Sketch.init(document.querySelector(".side"));
  }

  var seq = 0, shownPage = null;
  function go() {
    var id = (location.hash || "#today").slice(1);
    if (!render[id]) id = "today";
    var my = ++seq;
    Promise.all([data.status(), loaders[id]()]).then(function (r) {
      if (my !== seq) return;           // 用户已经点到别的页了
      STATUS = r[0];
      dirty.root = null;
      app.innerHTML = render[id](r[1]);
      if (shownPage !== id) { app.scrollTop = 0; shownPage = id; }   // 液态玻璃主题里内容区自己滚动：换页回到顶上
      app.classList.toggle("is-chat", id === "chat");   // 聊天页铺满窗口高度，输入框贴底
      renderNav(id);
      window.Sketch && Sketch.init(app);
      var msgs = document.getElementById("msgs");
      if (msgs) {
        applyWallpaper(); msgs.scrollTop = msgs.scrollHeight;
        msgs.addEventListener("scroll", function () { if (msgs.scrollTop < 80) loadOlder(); }, { passive: true });
        if (LIVE) A.post("/api/chat/warmup").catch(function () {});
      }
      if (id === "settings") { trackForm(app, saveSettings); fillZones("set-tz"); }
      if (id === "settings" && LIVE) { pollModel(); extStatus(); phoneRefresh(); }   // 下载进行中时，回到设置页能接着看到进度
    }).catch(function (e) {
      app.innerHTML = head(T("出错了"), esc(e.message || e)) + '<button class="btn primary" data-sketch data-act="retry">' + ico("undo") + T("再试一次") + "</button>";
      Sketch.init(app);
    });
  }

  /* ---------- 浏览器扩展 ---------- */
  function extStatus() {
    var el = document.getElementById("ext-status");
    if (!el) return;
    A.get("/api/browser/status").then(function (st) {
      el.textContent = st.connected ? T("已连接") : st.minutesAgo != null ? T("{n} 分钟前收到过数据", { n: st.minutesAgo }) : T("还没连上（没装，或浏览器没开）");
    }).catch(function () {});
  }
  function installExt(btn) {
    ask(T("安装浏览器扩展？"),
      "<p>" + T("会把程序自带的扩展复制到你选的文件夹，然后你自己在浏览器里装上。它只记：") + "</p><ul>" +
      "<li>" + T("https 网页的网址（去掉 ? 后面的全部参数）、域名、标题，以及搜索词") + "</li>" +
      "<li>" + T("http（不加密）网页、无痕窗口一律不记；不读网页内容和输入框") + "</li>" +
      "<li>" + T("数据只发给本机这个程序") + "</li></ul>"
    ).then(function (ok) {
      if (!ok) return;
      if (!LIVE) { toast(T("（预览演示）这里会让你选文件夹并复制扩展")); return; }
      btn.disabled = true;
      A.post("/api/browser/install").then(function (r) {
        btn.disabled = false;
        if (r.cancelled) return;
        var note = document.getElementById("ext-note");
        note.innerHTML = "<p>" + T("已保存到：") + " <code>" + esc(r.path) + "</code></p><ol>" +
          "<li>" + T("Edge 地址栏输入 edge://extensions（Chrome 是 chrome://extensions）") + "</li>" +
          "<li>" + T("打开「开发人员模式」") + "</li>" +
          "<li>" + T("点「加载解压缩的扩展」，选上面这个文件夹") + "</li></ol>" +
          "<p>" + T("装好后这个文件夹不要删除，删了浏览器里的扩展就没了。") + "</p>";
      }, function (e) { btn.disabled = false; fail(e); });
    });
  }

  /* ---------- 手机（决定 0014）---------- */
  function phoneField(label, ctrl, hint) {
    return '<div class="field"><label>' + label + "</label>" + ctrl + (hint ? '<p class="hint">' + hint + "</p>" : "") + "</div>";
  }
  function phoneBox(st) {
    if (!st) return '<p class="small">' + T("正在读取…") + "</p>";
    var on = !!st.enabled, h = "";
    var state = !on ? T("已关闭") : st.error ? T("没能打开") : st.running ? T("已打开，等手机来连") : T("正在打开…");
    h += phoneField(T("接收手机数据"), '<div><div class="avatar-row"><span class="dot' + (on && st.running ? "" : on ? " warn" : " off") + '"></span><span>' + state + "</span>" +
      '<button class="btn ' + (on ? "quiet" : "primary") + '" data-sketch' + (on ? ' data-sketch-tone="soft"' : "") + ' data-act="phone-toggle">' +
      ico(on ? "pause" : "play") + (on ? T("关闭") : T("打开")) + "</button></div>" +
      (st.error ? '<p class="small" style="color:var(--warm)">' + esc(st.error) + "</p>" : "") + "</div>",
      T("手机上装好 AwyRead 并配对后，它会在你和电脑连同一个 Wi-Fi 时，把应用使用时长、步数、心率、睡眠加密传过来，和电脑活动一起整理成记忆。打开后，这台电脑会在家里的局域网上等手机来连（其他设备没有配对钥匙，传不进来）。第一次打开时 Windows 可能会问是否允许它访问网络，请选「专用网络」并允许。"));
    if (!on) return h;
    var addrs = (st.addresses || []).map(function (a) { return "<code>" + esc(a) + "</code>"; }).join(" ");
    h += phoneField(T("这台电脑的地址"), "<div>" + (addrs || '<span class="small">' + T("没查到（电脑可能没连网）") + "</span>") + "</div>",
      T("手机找不到电脑时，把这个地址填到手机 AwyRead 的「电脑地址」里。只显示真实的 Wi-Fi / 有线网卡，VPN、组网工具、虚拟机的网卡不用来配对。") + "<br>" +
      T("填了地址还是连不上：公司、学校这类 Wi-Fi 常常不让连在上面的设备互相连接，这时在家里的 Wi-Fi 下配对和传输；或者让手机连这台电脑开的「移动热点」。"));
    var pair;
    if (st.pairing) {
      pair = '<div><div class="pair-code" data-sketch>' + esc(st.pairing.code) + "</div>" +
        '<p class="small">' + T("在手机 AwyRead 的「电脑」里填这个配对码。{m} 分钟内有效，只能用一次。", { m: Math.max(1, Math.ceil(st.pairing.expiresIn / 60)) }) + "</p>" +
        '<div class="avatar-row"><button class="btn primary" data-sketch data-act="phone-copy" data-code="' + esc(st.pairing.code) + '">' + ico("check") + T("复制配对码") + "</button>" +
        '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="phone-pair-cancel">' + ico("undo") + T("不配对了") + "</button></div></div>";
    } else {
      pair = '<div class="avatar-row"><button class="btn primary" data-sketch data-act="phone-pair">' + ico("arrow-right") + T("配对新手机") + "</button></div>";
    }
    h += phoneField(T("配对"), pair, T("配对码只用来让手机和电脑互相认出对方，不会在网络上传。"));
    var devs = st.devices || [];
    h += phoneField(T("已配对的手机"), devs.length ? '<div class="phone-list">' + devs.map(function (d) {
      var seen = d.lastSeen ? T("上次收到：{t}", { t: esc(d.lastSeen.slice(5, 16).replace("T", " ")) }) : T("还没收到过数据");
      return '<div class="avatar-row"><span>' + esc(d.name || T("手机")) + '</span><span class="small">' + seen + "</span>" +
        '<button class="btn danger" data-act="phone-unpair" data-id="' + esc(d.id) + '">' + T("取消配对") + "</button></div>";
    }).join("") + "</div>" : '<span class="small">' + T("还没有") + "</span>", "");
    return h;
  }
  var phoneTimer = null;
  function phoneShow(st) {
    var box = document.getElementById("phone-box");
    if (!box) return;
    var before = box._devs, now = (st.devices || []).length;
    phoneShow.last = st;
    box.innerHTML = phoneBox(st);
    box._devs = now;
    Sketch.init(box);
    if (before != null && now > before) toast(T("新手机配对好了"));
    clearTimeout(phoneTimer);
    // 显示配对码时每 3 秒看一次：手机配对成功后自动刷新；配对码过期了也会自动消失
    if (st.pairing || (st.enabled && !st.running && !st.error)) phoneTimer = setTimeout(phoneRefresh, 3000);
  }
  function phoneRefresh() {
    if (!document.getElementById("phone-box")) return;
    A.get("/api/phone").then(phoneShow, function () {});
  }
  // 复制到剪贴板：先用浏览器的剪贴板接口，不行（桌面窗口里有时不给）就退回老办法
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { return copyFallback(text); });
    }
    return copyFallback(text);
  }
  function copyFallback(text) {
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) resolve(); else reject(new Error("copy"));
    });
  }
  function phoneAct(act, b) {
    if (act === "phone-copy" && !LIVE) { copyText(b.getAttribute("data-code") || "").then(function () { toast(T("已复制配对码")); }); return; }
    if (!LIVE) { toast(T("（预览演示）这里会打开接收、生成配对码或取消配对")); return; }
    if (act === "phone-toggle") {
      var on = !!(phoneShow.last && phoneShow.last.enabled);
      b.disabled = true;
      A.post("/api/phone/enable", { enabled: !on }).then(phoneShow, function (e) { b.disabled = false; fail(e); });
    }
    if (act === "phone-copy") copyText(b.getAttribute("data-code") || "").then(function () { toast(T("已复制配对码")); }, function () { toast(T("复制失败，请照着输入")); });
    if (act === "phone-pair") A.post("/api/phone/pair").then(phoneShow, fail);
    if (act === "phone-pair-cancel") A.del("/api/phone/pair").then(phoneShow, fail);
    if (act === "phone-unpair") {
      ask(T("取消这台手机的配对？"), "<p>" + T("取消后它传来的数据电脑不再收。已经收到的数据和整理出的记忆不受影响。以后想用，在手机上重新配对就行。") + "</p>")
        .then(function (ok) { if (ok) A.post("/api/phone/unpair", { id: b.getAttribute("data-id") }).then(phoneShow, fail); });
    }
  }

  var zoneCache = null;
  // 地区名按界面语言：国家 / 地区名用浏览器自带的 Intl.DisplayNames，城市中文名见 zones-zh.js（没有的用英文）
  function zoneLabel(z) {
    var city = z.id.split("/").pop().replace(/_/g, " "), region = "";
    if (I.lang === "zh" && window.ZONE_ZH && ZONE_ZH[z.id]) city = ZONE_ZH[z.id];
    try { if (z.cc && window.Intl && Intl.DisplayNames) region = new Intl.DisplayNames([I.locale || I.lang], { type: "region" }).of(z.cc) || ""; } catch (e) {}
    var off = "UTC" + z.offset.slice(0, 3) + ":" + z.offset.slice(3);
    return (region && region !== city ? region + " · " : "") + city + (I.lang === "zh" ? "（" + off + "）" : " (" + off + ")");
  }
  function fillZones(id) {
    var sel = document.getElementById(id), q = document.getElementById(id + "-q");
    if (!sel) return;
    (zoneCache ? Promise.resolve(zoneCache) : LIVE ? A.get("/api/timezones") : Promise.resolve(M.zones || [])).then(function (list) {
      zoneCache = list;
      var cur = sel.value;
      var items = list.map(function (z) { return { id: z.id, label: zoneLabel(z) }; });
      if (cur && !items.some(function (x) { return x.id === cur; })) items.push({ id: cur, label: cur });
      items.sort(function (a, b) { return a.label.localeCompare(b.label, I.locale || I.lang); });
      function draw() {
        var k = (q ? q.value : "").trim().toLowerCase(), now = sel.value;
        var shown = items.filter(function (x) { return !k || x.id === now || x.label.toLowerCase().indexOf(k) >= 0 || x.id.toLowerCase().indexOf(k) >= 0; });
        sel.innerHTML = '<option value="">' + esc(T("跟随电脑")) + "</option>" + shown.map(function (x) {
          return '<option value="' + esc(x.id) + '"' + (x.id === now ? " selected" : "") + ">" + esc(x.label) + "</option>"; }).join("");
        sel.size = k ? Math.max(2, Math.min(8, shown.length + 1)) : 1;   // 搜索时直接展开成列表，点一下就选上
      }
      draw();
      if (q) q.addEventListener("input", draw);
    }).catch(function () {});
  }

  /* ---------- 语言 ---------- */
  // 程序里：存进设置（后台的提示、托盘、AI 整理用的语言也跟着变）；预览时：存浏览器
  function setLanguage(code) {
    leaveOk().then(function (ok) { if (ok) doSetLanguage(code); });
  }
  function doSetLanguage(code) {
    var save = LIVE ? A.post("/api/settings", { language: code }).then(function () { return data.status(); })
      : prefs.set("lang", code || null).then(function () { return { language: code || I.guess() }; });
    save.then(function (st) { return I.load(st.language); }).then(function () {
      I.apply();
      setSide(shell.classList.contains("collapsed"), false);
      go();
      if (guide.el) renderGuide();
    }).catch(fail);
  }

  /* ---------- 侧边栏收起 ---------- */
  var shell = document.querySelector(".shell");
  function setSide(collapsed, save) {
    shell.classList.toggle("collapsed", collapsed);
    var b = document.getElementById("side-toggle");
    var label = collapsed ? T("展开侧边栏") : T("收起侧边栏");
    b.setAttribute("aria-label", label); b.title = label;
    b.innerHTML = ico(collapsed ? "side-open" : "side-close");
    window.Sketch && Sketch.init(b);
    if (save) prefs.set("side", collapsed ? "collapsed" : null);
  }
  document.getElementById("side-toggle").addEventListener("click", function () { setSide(!shell.classList.contains("collapsed"), true); });

  /* ---------- 图片：缩小后存 ---------- */
  function shrink(file, square, maxSide, done) {
    if (!file || !/^image\//.test(file.type)) { toast(T("请选择一张图片")); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var im = new Image();
      im.onload = function () {
        var c = document.createElement("canvas"), g = c.getContext("2d");
        if (square) {
          var side = Math.min(im.width, im.height);
          c.width = c.height = maxSide;
          g.drawImage(im, (im.width - side) / 2, (im.height - side) / 2, side, side, 0, 0, maxSide, maxSide);
        } else {
          var k = Math.min(1, maxSide / Math.max(im.width, im.height));
          c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
          g.drawImage(im, 0, 0, c.width, c.height);
        }
        done(c.toDataURL("image/jpeg", square ? 0.9 : 0.85));
      };
      im.onerror = function () { toast(T("这张图片打不开")); };
      im.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  /* ---------- 头像 ---------- */
  function avatarInner() {
    var img = prefs.get("avatar");
    return img ? '<img src="' + esc(img) + '" alt="' + esc(T("我的头像")) + '">' : ico("heart");
  }
  function applyAvatar() {
    document.getElementById("avatar-slot").innerHTML = avatarInner();
    var prev = document.querySelector(".avatar-preview");
    if (prev) { var svg = prev.querySelector(".sk-svg"); prev.innerHTML = avatarInner(); if (svg) prev.insertBefore(svg, prev.firstChild); }
    window.Sketch && Sketch.init(document.querySelector(".brand"));
  }
  document.getElementById("avatar-btn").addEventListener("click", function () { document.getElementById("avatar-file").click(); });
  document.getElementById("avatar-file").addEventListener("change", function (e) {
    shrink(e.target.files[0], true, 256, function (url) {
      prefs.set("avatar", url).then(function () { applyAvatar(); toast(T("头像换好了")); }, fail);
    });
    e.target.value = "";
  });

  /* ---------- 聊天壁纸 ---------- */
  var DEFAULT_VEIL = 55;
  function applyWallpaper() {
    var wall = document.getElementById("chat-wall"), wrap = document.getElementById("msgs-wrap");
    if (!wall) return;
    var img = prefs.get("wallpaper"), veil = +(prefs.get("veil") || DEFAULT_VEIL);
    wall.style.backgroundImage = img ? 'url("' + img + '")' : "";
    wall.style.setProperty("--veil", veil / 100);
    wrap.classList.toggle("has-wall", !!img);
    var slider = document.getElementById("wall-veil");
    if (slider) slider.value = String(veil);
  }

  /* ---------- 主题：铅笔手绘 / 液态玻璃（决定 0013） ---------- */
  // 偏好里只存「不是默认」的值：skin=glass、glassbg=wall、glassmode=light|dark、motion=full|off、glassveil=0~100
  function glassCfg() {
    var veil = parseInt(prefs.get("glassveil"), 10);
    return {
      skin: GLASS_ENABLED && prefs.get("skin") === "glass" ? "glass" : "pencil",   // 关闭时：以前选过玻璃也按铅笔显示
      bg: prefs.get("glassbg") === "wall" ? "wall" : "bubbles",
      mode: prefs.get("glassmode") === "light" || prefs.get("glassmode") === "dark" ? prefs.get("glassmode") : "auto",
      motion: prefs.get("motion") === "full" || prefs.get("motion") === "off" ? prefs.get("motion") : "calm",
      veil: (isNaN(veil) ? 50 : Math.max(0, Math.min(100, veil))) / 100,
      wall: prefs.get("wallpaper") || null
    };
  }
  function applySkin() { return window.Glass ? Glass.set(glassCfg()) : Promise.resolve(false); }

  function themePanelHtml() {
    var c = glassCfg();
    function opt(k, v, label) {
      var on = (k === "skin" ? c.skin : k === "glassbg" ? c.bg : k === "glassmode" ? c.mode : c.motion) === v;
      return '<button type="button" class="btn ' + (on ? "primary" : "quiet") + '" data-sketch' + (on ? "" : ' data-sketch-tone="soft"') +
        ' data-act="theme-set" data-k="' + k + '" data-v="' + v + '" aria-pressed="' + on + '">' + esc(label) + "</button>";
    }
    var h = "<h3>" + T("主题") + "</h3>" +
      '<div><div class="tp-lab">' + T("风格") + '</div><div class="tp-row">' + opt("skin", "pencil", T("铅笔手绘")) + opt("skin", "glass", T("液态玻璃")) + "</div></div>";
    if (c.skin !== "glass") return h + '<p class="tp-note">' + T("铅笔手绘是原来的样子。换成液态玻璃后，可以选背景、明暗和动效。") + "</p>";
    return h +
      '<div><div class="tp-lab">' + T("背景") + '</div><div class="tp-row">' + opt("glassbg", "bubbles", T("紫白气泡")) + opt("glassbg", "wall", T("我的壁纸")) +
      '<button type="button" class="btn quiet" data-sketch data-sketch-tone="soft" data-act="glass-wall-pick">' + ico("image") + T("选择图片…") + "</button></div>" +
      '<p class="tp-note">' + T("壁纸铺满整个窗口，按钮和卡片的边缘会折射它。图片只存在这台电脑上，和聊天壁纸是同一张。") + "</p></div>" +
      '<div><div class="tp-lab">' + T("明暗") + '</div><div class="tp-row">' + opt("glassmode", "auto", T("跟随系统")) + opt("glassmode", "light", T("偏亮")) + opt("glassmode", "dark", T("偏暗")) + "</div></div>" +
      '<div><div class="tp-lab">' + T("玻璃浓淡") + '</div><label class="range"><span>' + T("更透") + '</span><input type="range" id="glass-veil" min="0" max="100" step="5" value="' +
      Math.round(c.veil * 100) + '"><span>' + T("字更清楚") + "</span></label></div>" +
      '<div><div class="tp-lab">' + T("动效") + '</div><div class="tp-row">' + opt("motion", "full", T("完整")) + opt("motion", "calm", T("收敛")) + opt("motion", "off", T("关闭")) + "</div>" +
      '<p class="tp-note">' + T("长按按钮或卡片往外拉，松手会弹回来；侧边栏选中的那一块可以按住上下拖。") + "</p></div>";
  }
  function themePanel() { return document.getElementById("theme-panel"); }
  function placeThemePanel() {
    var p = themePanel(), b = document.querySelector('[data-act="theme-panel"]');
    if (!p || !b) return;
    var r = b.getBoundingClientRect(), side = document.querySelector(".side").getBoundingClientRect();
    p.style.left = Math.min(side.right + 12, window.innerWidth - p.offsetWidth - 12) + "px";
    p.style.top = Math.max(12, Math.min(r.top - 24, window.innerHeight - p.offsetHeight - 12)) + "px";
  }
  function renderThemePanel() {
    var p = themePanel();
    if (!p) return;
    p.innerHTML = themePanelHtml();
    window.Sketch && Sketch.init(p);
    placeThemePanel();
  }
  function openThemePanel(open) {
    var p = themePanel(), b = document.querySelector('[data-act="theme-panel"]');
    if (!open) { if (p) p.remove(); if (b) b.setAttribute("aria-expanded", "false"); return; }
    if (!p) {
      p = document.createElement("div");
      p.id = "theme-panel"; p.className = "card theme-panel"; p.setAttribute("role", "dialog");
      p.setAttribute("aria-label", T("主题")); p.setAttribute("data-sketch", "");
      document.body.appendChild(p);
    }
    renderThemePanel();
    if (b) b.setAttribute("aria-expanded", "true");
  }
  function setThemePref(k, v) {
    var stored = { skin: v === "glass" ? "glass" : null, glassbg: v === "wall" ? "wall" : null,
      glassmode: v === "light" || v === "dark" ? v : null, motion: v === "full" || v === "off" ? v : null }[k];
    if (k === "glassbg" && v === "wall" && !prefs.get("wallpaper")) { glassWallInput().click(); return; }   // 还没有壁纸：先选一张
    var wasGlass = glassCfg().skin === "glass";
    prefs.set(k, stored).then(applySkin).then(function () {
      var isGlass = glassCfg().skin === "glass";
      if (wasGlass !== isGlass) { go(); window.Sketch && Sketch.init(document); }   // 换风格：整页重画
      renderThemePanel();
    }).catch(fail);
  }
  function glassWallInput() {
    var inp = document.getElementById("glass-wall-file");
    if (!inp) {
      inp = document.createElement("input");
      inp.type = "file"; inp.accept = "image/*"; inp.id = "glass-wall-file"; inp.hidden = true;
      document.body.appendChild(inp);
    }
    return inp;
  }
  document.addEventListener("pointerdown", function (e) {
    var p = themePanel();
    if (p && !p.contains(e.target) && !e.target.closest('[data-act="theme-panel"]')) openThemePanel(false);
  });
  window.addEventListener("resize", placeThemePanel);

  /* ---------- 聊天 ---------- */
  var sending = false;
  function send() {
    var box = document.getElementById("say"), text = box && box.value.trim();
    if (!text || sending) return;
    var msgs = document.getElementById("msgs");
    var today = todayStr();
    var seps = msgs.querySelectorAll(".day-sep");
    if (!seps.length || seps[seps.length - 1].getAttribute("data-day") !== today) msgs.insertAdjacentHTML("beforeend", divider(today));
    msgs.insertAdjacentHTML("beforeend", msg({ role: "me", text: text }));
    box.value = "";
    var holder = document.createElement("div");
    holder.innerHTML = msg({ role: "ai", text: "" });
    var bubble = holder.firstChild, body = bubble.querySelector(".body"), thinking = T("正在想……");
    body.innerHTML = '<span class="small waiting">' + thinking + "</span>";
    var started = Date.now(), gotText = false;
    var timer = setInterval(function () {   // 等得久时让人知道它还在干活
      var w = body.querySelector(".waiting");
      if (!w || gotText) { clearInterval(timer); return; }
      w.textContent = T("正在想…… 已等 {n} 秒", { n: Math.round((Date.now() - started) / 1000) });
    }, 1000);
    msgs.appendChild(bubble);
    Sketch.init(msgs); msgs.scrollTop = msgs.scrollHeight;
    if (!LIVE) {
      setTimeout(function () { body.textContent = T("（这是静态预览：由程序打开时，这里会是 AI 的真实回复。）"); }, 600);
      return;
    }
    sending = true; document.getElementById("send-btn").disabled = true;
    var answer = "";
    A.chat(text, function (ev) {
      if (ev.type === "tool") body.insertAdjacentHTML("beforebegin", '<div class="tool">' + ico("book") + esc(ev.text) + "</div>");
      if (ev.type === "delta") { gotText = true; answer += ev.text; body.innerHTML = rich(answer); }
      if (ev.type === "error") { gotText = true; body.innerHTML = '<span style="color:var(--warm)">' + esc(ev.text) + "</span>"; }
      Sketch.init(bubble); msgs.scrollTop = msgs.scrollHeight;
    }).catch(function (e) {
      body.innerHTML = '<span style="color:var(--warm)">' + esc(e.message) + "</span>";
    }).then(function () {
      sending = false; clearInterval(timer); var b = document.getElementById("send-btn"); if (b) b.disabled = false;
      if (!answer && body.querySelector(".waiting")) body.innerHTML = '<span class="small">' + T("（没有收到回复）") + "</span>";
      var secs = Math.round((Date.now() - started) / 1000);
      if (answer && secs >= 5) body.insertAdjacentHTML("afterend", '<div class="small took">' + T("用时 {n} 秒", { n: secs }) + "</div>");
    });
  }

  /* ---------- 向量模型下载 ---------- */
  var modelArmed = false, modelTimer = 0;
  function startModel(btn) {
    if (!LIVE) { toast(T("预览模式不会真的下载")); return; }
    var label = btn.querySelector("span:last-child");
    if (!modelArmed && btn.getAttribute("data-installed") !== "1") {   // 第一次点：先提醒大小，防止误点
      modelArmed = true;
      label.textContent = T("确定下载约 2.3GB？再点一次");
      setTimeout(function () { modelArmed = false; var b = document.getElementById("model-btn"); if (b) b.querySelector("span:last-child").textContent = T("下载并启用"); }, 6000);
      return;
    }
    modelArmed = false; btn.disabled = true;
    A.post("/api/model/download").then(pollModel, fail);
  }
  function pollModel() {
    clearTimeout(modelTimer);
    A.get("/api/model").then(function (m) {
      var bar = document.getElementById("model-bar"), note = document.getElementById("model-note"),
        text = document.getElementById("model-text"), j = m.job;
      if (!bar) return;                       // 已经离开设置页，停止查询
      text.textContent = m.text;
      if (j.state === "downloading" || j.state === "indexing") {
        bar.hidden = false; Sketch.init(bar.parentNode);
        var pct = j.total ? Math.min(100, j.done / j.total * 100) : 0;
        bar.querySelector("i").style.width = "calc(" + pct.toFixed(1) + "% - 6px)";
        note.textContent = j.state === "downloading"
          ? T("正在下载 {file}：{done} / {total} MB", { file: j.file || "", done: (j.done / 1048576).toFixed(0), total: (j.total / 1048576).toFixed(0) })
          : T("下载完成、校验通过，正在给已有的记忆建索引：{done} / {total}", { done: j.done, total: j.total });
        modelTimer = setTimeout(pollModel, 1000);
      } else if (j.state === "done") {
        bar.hidden = true; note.textContent = j.message || T("完成"); toast(T("模型已启用"));
        var b = document.getElementById("model-btn"); if (b) b.remove();
      } else if (j.state === "error") {
        bar.hidden = true; note.textContent = T("没成功：{msg}（再点一次会接着下）", { msg: j.message });
        var b2 = document.getElementById("model-btn"); if (b2) b2.disabled = false;
      }
    }).catch(function () { modelTimer = setTimeout(pollModel, 2000); });
  }

  /* ---------- 检查更新 ---------- */
  function checkUpdate(btn) {
    var note = document.getElementById("update-note");
    if (!LIVE) { toast(T("预览模式不会联网检查")); return; }
    btn.disabled = true; note.textContent = T("正在检查……");
    A.get("/api/update/check").then(function (u) {
      btn.disabled = false;
      if (!u.latest || !u.newer) { note.textContent = T("已经是最新版本（{v}）", { v: u.current }); return; }
      note.textContent = T("发现新版本 {v}", { v: u.latest });
      var notes = esc(u.notes || T("（没有写更新说明）")).replace(/\r?\n/g, "<br>");
      var size = u.size ? T("大小约 {n} MB", { n: Math.round(u.size / 1048576) }) : "";
      var body = "<p>" + T("当前 {cur} → 新版本 {v}", { cur: esc(u.current), v: esc(u.latest) }) +
        (u.prerelease ? ' <span class="chip" data-sketch data-sketch-tone="soft">' + T("测试版") + "</span>" : "") +
        (u.published ? ' <span class="small">' + esc(u.published) + "</span>" : "") + "</p>" +
        '<div class="update-notes">' + notes + "</div>" +
        (u.canInstall
          ? "<p>" + T("现在更新吗？程序会先下载并核对校验码，然后自动关闭、安装、再重新打开；记忆和设置都会保留。") + (size ? "（" + size + "）" : "") + "</p>"
          : "<p>" + T("这个版本没有可校验的安装包，为了安全不自动安装。点「是」打开发布页面，手动下载。") + "</p>");
      return ask(T("发现新版本 {v}", { v: u.latest }), body).then(function (ok) {
        if (!ok) return;
        if (!u.canInstall) { if (u.page) window.open(u.page, "_blank"); return; }
        btn.disabled = true;
        return A.post("/api/update/install").then(function () { pollUpdate(); });
      });
    }).catch(function (e) { btn.disabled = false; note.textContent = e.message || T("出错了"); });
  }
  function pollUpdate() {
    A.get("/api/update/status").then(function (j) {
      var bar = document.getElementById("update-bar"), note = document.getElementById("update-note"), btn = document.getElementById("update-btn");
      if (!bar) return;
      if (j.state === "downloading") {
        bar.hidden = false; Sketch.init(bar.parentNode);
        var pct = j.total ? Math.min(100, j.done / j.total * 100) : 0;
        bar.querySelector("i").style.width = "calc(" + pct.toFixed(1) + "% - 6px)";
        note.textContent = T("正在下载新版本：{done} / {total} MB", { done: (j.done / 1048576).toFixed(0), total: (j.total / 1048576).toFixed(0) });
        setTimeout(pollUpdate, 800);
      } else if (j.state === "installing") {
        bar.hidden = true; note.textContent = T("校验通过，正在安装。程序马上会自动关闭，装好后会重新打开。");
      } else if (j.state === "error") {
        bar.hidden = true; note.textContent = T("没成功：{msg}", { msg: j.message }); if (btn) btn.disabled = false;
      }
    }).catch(function () { /* 程序已经关掉去安装了 */ });
  }

  /* ---------- 交互 ---------- */
  function saveSettings() {
    var times = document.getElementById("set-times").value.split(/[、,，\s]+/).filter(Boolean);
    var body = {
      organize_times: times,
      blocked_apps: document.getElementById("set-apps").value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean),
      blocked_keywords: document.getElementById("set-words").value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean),
      raw_retention_days: Math.min(3650, Math.max(1, parseInt(document.getElementById("set-keep").value, 10) || 30)),
      autostart: document.getElementById("set-auto").checked,
      timezone: document.getElementById("set-tz").value,
      chat_in_memory: document.getElementById("set-chatmem").checked
    };
    var key = document.getElementById("set-key").value.trim();
    if (key) body.deepseek_api_key = key;
    if (!LIVE) { toast(T("已保存（预览模式不会真的保存）")); trackForm(app, saveSettings); return Promise.resolve(); }
    return A.post("/api/settings", body).then(function () { toast(T("已保存")); dirty.root = null; go(); });
  }

  function closeLangMenu() {
    var m = document.getElementById("lang-menu"), b = document.querySelector('[data-act="lang-menu"]');
    if (m && !m.hidden) { m.hidden = true; if (b) b.setAttribute("aria-expanded", "false"); }
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-act]");
    if (!b || b.getAttribute("data-act") !== "lang-menu") closeLangMenu();
    if (!b) return;
    var act = b.getAttribute("data-act"), id = b.getAttribute("data-id");
    if (act === "retry") go();
    if (act === "tl-order") toggleTimelineOrder();
    if (act === "theme-panel") openThemePanel(!themePanel());
    if (act === "theme-set") setThemePref(b.getAttribute("data-k"), b.getAttribute("data-v"));
    if (act === "glass-wall-pick") glassWallInput().click();
    if (act === "organize") {
      if (!LIVE) { toast(T("开始整理……（预览演示）")); return; }
      A.post("/api/organize").then(function (r) { toast(r.message + " " + T("完成后托盘会提醒你")); }, fail);
    }
    if (act === "undo") {
      if (!LIVE) { toast(T("已撤销（预览演示）")); return; }
      A.post("/api/log/" + id + "/undo").then(function (r) { toast(r.message); go(); }, fail);
    }
    if (act === "save") saveSettings().catch(fail);
    if (act === "g-save") guideSave().catch(fail);
    if (act === "guide-open") openGuide(0);
    if (act === "g-phone-on") {
      if (!LIVE) { toast(T("（预览演示）这里会打开接收手机数据")); return; }
      A.post("/api/phone/enable", { enabled: true }).then(function () {
        toast(T("已打开。之后在「设置 → 手机」里点「配对新手机」，把配对码填到手机上"));
      }, fail);
    }
    if (act === "g-next" || act === "g-prev" || act === "g-skip") {
      leaveOk().then(function (ok) {
        if (!ok) return;
        if (act === "g-skip" || (act === "g-next" && guide.step === GUIDE_STEPS - 1)) return closeGuide(true);
        guide.step += act === "g-next" ? 1 : -1;
        renderGuide();
      });
    }
    if (act === "lib-open") { if (LIVE) A.post("/api/library/open").catch(fail); else toast(T("（预览演示）这里会打开记忆库文件夹")); }
    if (act === "lib-move") moveLibrary();
    if (act === "lib-archives") openArchives();
    if (act === "lib-export") {
      ask(T("导出记忆库？"), "<p>" + T("压缩包会连同你和 AI 的全部聊天记录一起导出。") + "</p><ul>" +
        "<li>" + T("密码、密钥、手机号、证件号、银行卡这类内容会换成「[已隐藏]」，但规则不是万能的，别的隐私（比如聊到的人名、地址）会原样保留。") + "</li>" +
        "<li>" + T("压缩包没有密码，拿到它的人能看到关于你的全部记忆。请自己保管好，不要随便发给别人。") + "</li></ul>"
      ).then(function (ok) {
        if (!ok) return;
        if (!LIVE) { toast(T("（预览演示）这里会导出压缩包并打开所在文件夹")); return; }
        b.disabled = true;
        A.post("/api/library/export", {})
          .then(function (r) { b.disabled = false; toast(r.message); }, function (e) { b.disabled = false; fail(e); });
      });
    }
    if (act === "model-dl") startModel(b);
    if (act === "pause") {
      var on = STATUS.collecting !== false;
      if (!LIVE) { STATUS.collecting = !on; renderNav((location.hash || "#today").slice(1)); toast(on ? T("已暂停记录") : T("继续记录")); return; }
      A.post("/api/settings", { collect_enabled: !on }).then(function () { toast(on ? T("已暂停记录") : T("继续记录")); go(); }, fail);
    }
    if (act === "use-chat" || act === "use-org") {
      var body = act === "use-chat" ? { chat_brain: id } : { organize_brain: id };
      if (!LIVE) { if (act === "use-chat") STATUS.chatBrain = id; else STATUS.organizeBrain = id; go(); return; }
      A.post("/api/settings", body).then(function () { toast(act === "use-chat" ? T("以后聊天由它来回答") : T("以后整理记忆由它来做")); go(); }, fail);
    }
    if (act === "install") startInstall(id);
    if (act === "update-check") checkUpdate(b);
    if (act === "ext-install") installExt(b);
    if (act && act.indexOf("phone-") === 0) phoneAct(act, b);
    if (act === "filter") {
      if (b.getAttribute("data-group") === "cat") memState.cat = id || ""; else logState.act = id || "";
      go();
    }
    if (act === "export") {
      if (!LIVE) { toast(T("（预览演示）这里会导出 TXT 并打开所在文件夹")); return; }
      b.disabled = true;
      A.post("/api/export/" + id).then(function (r) { b.disabled = false; toast(r.message); }, function (e) { b.disabled = false; fail(e); });
    }
    if (act === "lang-menu") {
      var menu = document.getElementById("lang-menu"), open = menu.hidden;
      menu.hidden = !open; b.setAttribute("aria-expanded", String(open));
      if (open) { Sketch.init(menu); var first = menu.querySelector(".lang-item"); if (first) first.focus(); }
    }
    if (act === "set-lang") setLanguage(id || "");
    if (act === "avatar-pick") document.getElementById("avatar-file").click();
    if (act === "avatar-reset") prefs.set("avatar", null).then(function () { applyAvatar(); toast(T("已恢复默认")); }, fail);
    if (act === "wall-panel") {
      var panel = document.getElementById("wall-panel"), opened = panel.hasAttribute("hidden");
      if (opened) { panel.removeAttribute("hidden"); Sketch.init(panel); } else panel.setAttribute("hidden", "");
      b.setAttribute("aria-expanded", String(opened));
    }
    if (act === "wall-reset") Promise.all([prefs.set("wallpaper", null), prefs.set("veil", null)]).then(function () { applyWallpaper(); applySkin(); toast(T("已恢复默认")); }, fail);
    if (act === "send") send();
  });
  document.addEventListener("change", function (e) {
    if (e.target.id === "wall-file") {
      shrink(e.target.files[0], false, 2560, function (url) {
        prefs.set("wallpaper", url).then(function () { applyWallpaper(); applySkin(); toast(T("壁纸换好了")); }, fail);
      });
      e.target.value = "";
    }
    if (e.target.id === "glass-wall-file") {   // 液态玻璃主题：选壁纸后铺满整个窗口
      shrink(e.target.files[0], false, 2560, function (url) {
        prefs.set("wallpaper", url).then(function () { return prefs.set("glassbg", "wall"); }).then(applySkin).then(function () {
          applyWallpaper(); renderThemePanel(); toast(T("壁纸换好了"));
        }).catch(fail);
      });
      e.target.value = "";
    }
    if (e.target.id === "hist") { memState.hist = e.target.checked; go(); }
    if (e.target.id === "agy-model") {
      if (!LIVE) { toast(T("已切换模型档位")); return; }
      A.post("/api/settings", { antigravity_model: e.target.value }).then(function () { toast(T("已切换模型档位")); }, fail);
    }
  });
  document.addEventListener("change", updateDirty);
  document.addEventListener("click", function (e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a || !isDirty()) return;
    e.preventDefault(); e.stopPropagation();
    leaveOk().then(function (ok) { if (ok) { dirty.root = null; location.hash = a.getAttribute("href"); } });
  }, true);
  var veilTimer = 0, glassVeilTimer = {};
  document.addEventListener("input", function (e) {
    updateDirty();
    if (e.target.id === "wall-veil") {
      prefs.cache.veil = e.target.value; applyWallpaper();
      clearTimeout(veilTimer); veilTimer = setTimeout(function () { prefs.set("veil", e.target.value); }, 400);
    }
    if (e.target.id === "glass-veil") {   // 玻璃浓淡：拖动时先看效果，停下来再存
      var gv = e.target.value;
      prefs.cache.glassveil = gv;
      clearTimeout(glassVeilTimer.apply); glassVeilTimer.apply = setTimeout(applySkin, 90);
      clearTimeout(glassVeilTimer.save); glassVeilTimer.save = setTimeout(function () { prefs.set("glassveil", gv).catch(fail); }, 500);
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeLangMenu(); openThemePanel(false); }
    if (e.target.id === "say" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    if (e.target.id === "mem-q" && e.key === "Enter") { memState.q = e.target.value.trim(); go(); }
  });

  /* ---------- 第一次打开：先确认风险，再看引导（决定 0012） ---------- */
  function termsItems() {
    return [
      T("它会一直记录你在电脑上做什么：窗口标题和软件名，离开、锁屏和电脑睡眠的时间，正在播放的歌和视频，最近打开的文件名；装了浏览器扩展的话，还有看过的网页和搜索词。隐私过滤（密码、银行等关键词和「不记录的软件」）会尽量拦住敏感内容，但做不到 100%。"),
      T("如果你在「设置 → 手机」里打开接收并配对了手机端 AwyRead，还会收到手机上的数据：每个 App 用了多久、亮屏时间，以及步数、心率、睡眠这类健康数据。打开期间，这台电脑会在你所在的局域网（同一个 Wi-Fi）上等手机来连；没有配对钥匙的设备传不进来。这项默认关着。"),
      T("整理记忆和聊天时，这些内容会发给你选的 AI 服务（比如 DeepSeek、Google Antigravity），由它们按各自的隐私政策处理。"),
      T("聊天时 AI 可能会上网搜索，搜索词里可能带着你问的问题。"),
      T("所有数据只存在你自己的电脑上，没有云端备份：请自己保管、自己备份。用这台电脑的其他人也可能看到这些数据。"),
      T("因使用本软件造成的任何直接或间接损失（包括但不限于隐私泄露、数据丢失），与项目作者本人无关，作者不承担责任。")
    ];
  }
  function showTerms() {
    var mask = document.createElement("div");
    mask.className = "first-mask";
    mask.innerHTML = '<div class="card first-card terms" role="dialog" aria-modal="true" aria-labelledby="terms-t" data-sketch>' +
      '<h2 id="terms-t">' + T("使用前，请先了解这些风险") + "</h2>" +
      '<p class="muted">' + T("在你点「我了解风险并接受使用」之前，它不会记录任何东西。") + '</p><ol class="terms-list">' +
      termsItems().map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ol>" +
      '<div class="ask-btns"><button class="btn quiet" data-sketch data-sketch-tone="soft" data-ans="quit">' + ico("close") + T("退出软件") + "</button>" +
      '<button class="btn primary" data-sketch data-ans="ok">' + ico("check") + T("我了解风险并接受使用") + "</button></div></div>";
    document.body.appendChild(mask);
    window.Sketch && Sketch.init(mask);
    mask.addEventListener("click", function (e) {
      var a = e.target.closest("[data-ans]");
      if (!a) return;
      if (a.getAttribute("data-ans") === "quit") {
        if (!LIVE) { toast(T("（预览演示）这里会退出软件")); return; }
        mask.querySelector(".terms").innerHTML = "<h2>" + T("正在退出……") + '</h2><p class="muted">' + T("下次打开时还会先看到这一页。") + "</p>";
        A.post("/api/quit").catch(function () {});
        return;
      }
      (LIVE ? A.post("/api/terms/accept") : Promise.resolve()).then(function () {
        mask.remove();
        return data.status().then(function (st) { STATUS = st; if (st.onboarded === false || !LIVE) openGuide(0); });
      }).catch(fail);
    });
  }

  var guide = { step: 0, el: null, s: null, brains: [], lib: null };
  var GUIDE_STEPS = 7;
  function openGuide(step) {
    leaveOk().then(function (ok) {
      if (!ok) return;
      dirty.root = null;
      if ((location.hash || "#today") !== "#today") location.hash = "#today";   // 底下换成「今天」，免得和引导里的控件重名
      return Promise.all([data.settings(), data.brains(), data.library()]).then(function (r) {
        guide.s = r[0]; guide.brains = r[1]; guide.lib = r[2]; guide.step = step || 0;
        if (!guide.el) { guide.el = document.createElement("div"); guide.el.className = "first-mask"; document.body.appendChild(guide.el); }
        renderGuide();
      });
    }).catch(fail);
  }
  function closeGuide(done) {
    if (guide.el) { guide.el.remove(); guide.el = null; }
    dirty.root = null;
    if (done && LIVE) A.post("/api/onboarded", { done: true }).catch(function () {});
    go();
  }
  // 有要填的步骤最下面都有这一行：箭头指着「保存设置」，提醒一定要点
  function gSaveRow() {
    return '<div class="g-save-row"><span class="g-arrow">' + T("填完一定要点「保存设置」，不然不会生效") + ico("arrow-right") + "</span>" +
      '<button class="btn primary save-btn" data-sketch data-act="g-save">' + ico("check") + T("保存设置") + "</button></div>";
  }
  function guideBody(i) {
    var s = guide.s;
    function wrap(inner) { return '<span class="input-wrap" data-sketch data-sketch-tone="soft">' + inner + "</span>"; }
    function list(items) { return "<ul>" + items.map(function (x) { return "<li>" + x + "</li>"; }).join("") + "</ul>"; }
    if (i === 0) return { t: T("欢迎！"), b: "<p>" + T("我会一直陪着你：记下你在电脑和手机上做了什么，定时整理成记忆，聊天时像老朋友一样懂你。") + "</p><p>" +
      T("接下来几步帮你把它设置好，大概两三分钟。不想看的话，点左下角「跳过所有」；以后在「设置」里还能重新打开。") + "</p>" +
      '<h3 class="g-h">' + ico("globe") + T("先选语言") + " · Language</h3>" + langButtons(s.language) +
      '<p class="small">' + T("切换后立刻生效，不用保存。") + "</p>" };
    if (i === 1) return { t: T("我所在的地区"), b: "<p>" + T("整理时间、「今天」和记忆里的时间都按这里算。一般选「跟随电脑」就行；电脑时区和你实际生活的地方不一样时（比如人在英国、电脑还是北京时间），搜一下你所在的城市或国家，选上它。") + "</p>" +
      tzPicker("g-tz", s.timezone) + gSaveRow() };
    if (i === 2) return { t: T("记什么，不记什么"), b: '<div class="grid-2 g-two"><div><h3 class="g-h">' + ico("check") + T("会记下") + "</h3>" +
      list([T("最前面的窗口标题和软件名"), T("离开、锁屏、电脑睡眠和关机的时间"), T("正在播放的歌和视频（包括后台播放）"), T("最近打开的文件名（不读内容）"),
        T("你和 AI 的聊天"), T("装了浏览器扩展的话：看过的 https 网页和搜索词"),
        T("配对了手机的话：每个 App 用了多久、亮屏时间、步数、心率、睡眠")]) +
      '</div><div><h3 class="g-h">' + ico("lock") + T("不会记") + "</h3>" +
      list([T("按了哪些键、输入了什么"), T("屏幕截图、声音、摄像头"), T("文件内容、剪贴板"), T("你在哪里（不看 Wi-Fi 和定位）"), T("无痕窗口和 http 网页")]) + "</div></div>" +
      "<p>" + T("下面两项可以按需要再加：用这些软件时只记成「隐私窗口」；窗口标题里有这些词时整条不记。") + "</p>" +
      '<div class="grid-2"><label class="g-lab">' + T("不记录的软件（一行一个进程名）") + wrap('<textarea class="textarea" id="g-apps" data-save>' + esc(s.blocked_apps.join("\n")) + "</textarea>") + "</label>" +
      '<label class="g-lab">' + T("标题含这些词时不记") + wrap('<textarea class="textarea" id="g-words" data-save>' + esc(s.blocked_keywords.join("\n")) + "</textarea>") + "</label></div>" + gSaveRow() };
    if (i === 3) {
      var agy = guide.brains.filter(function (b) { return b.id === "antigravity"; })[0];
      return { t: T("由谁来回答"), b: "<p>" + T("聊天和整理记忆都要用到 AI。先选一个陪你聊天：") + "</p>" +
        '<label class="g-lab">' + T("聊天由谁来回答") + wrap('<select class="input" id="g-brain" data-save>' +
          [["deepseek", "DeepSeek"], ["antigravity", "Google Antigravity"]].map(function (o) {
            return '<option value="' + o[0] + '"' + (STATUS.chatBrain === o[0] ? " selected" : "") + ">" + o[1] + "</option>"; }).join("") + "</select>") + "</label>" +
        '<label class="g-lab">DeepSeek API Key' + wrap('<input class="input" id="g-key" type="password" autocomplete="off" data-save placeholder="' +
          esc(s.keySaved ? T("已保存（加密）") : "sk-……") + '">') + "</label>" +
        '<p class="small">' + T("整理记忆用 DeepSeek，需要这个 Key（在 platform.deepseek.com 申请）。只保存在这台电脑上，用 Windows 自带的加密功能锁住。") + "</p>" +
        (agy && agy.install ? '<p><button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="install" data-id="antigravity">' + ico("download") + T("一键安装 Google Antigravity") + "</button></p>"
          : agy ? '<p class="small">Google Antigravity：' + esc(agy.stateText) + "</p>" : "") +
        '<p class="small">' + T("聊天时 AI 可以直接上网搜索、看网页上的最新消息，不用每次问你；它不能读写你的文件，也不能运行命令。") + "</p>" + gSaveRow() };
    }
    if (i === 4) return { t: T("可选功能"), b: "<p>" + T("这几项都可以以后再弄。") + "</p>" +
      '<div class="g-opt"><h3 class="g-h">' + T("按意思搜索的模型") + "</h3>" + modelBox(s) +
      '<p class="small">' + T("bge-m3（约 2.3GB），只在本机运行。不下载也能用，只是只能按关键词搜索。") + "</p></div>" +
      '<div class="g-opt"><h3 class="g-h">' + T("浏览器扩展") + '</h3><div class="avatar-row"><span id="ext-status" class="small"></span>' +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="ext-install">' + ico("download") + T("安装浏览器扩展") + "</button></div>" +
      '<div class="small ext-note" id="ext-note"></div></div>' +
      '<div class="g-opt"><h3 class="g-h">' + T("手机") + "</h3>" +
      '<p class="small">' + T("手机上装了 AwyRead 的话，它会在和电脑连同一个 Wi-Fi 时，把应用使用时长、步数、心率、睡眠加密传过来，一起整理成记忆。默认关着，不用的话跳过就行。") + "</p>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="g-phone-on">' + ico("play") + T("打开接收手机数据") + "</button></div>" +
      '<div class="g-opt"><h3 class="g-h">' + T("开机自动启动") + "</h3>" + sw("g-auto", s.autostart, T("只在右下角托盘里"), true) + "</div>" + gSaveRow() };
    if (i === 5) {
      var lib = guide.lib || {};
      return { t: T("你的记忆库"), b: "<p>" + T("记下的一切都在这个文件夹里，只在你的电脑上：") + "</p>" +
        '<div class="lib-path"><code>' + esc(lib.path || "—") + "</code></div>" +
        '<p><button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="lib-open">' + ico("folder") + T("打开文件夹") + "</button></p>" +
        list([T("文件夹最外层有一份「{f}」，是写给 AI 看的说明。", { f: esc(lib.readme || "记忆库说明.md") }),
          T("C 盘空间紧张的话，可以在「设置 → 记忆库」里把它搬到别的盘。"),
          T("「导出记忆库」会生成一个压缩包（连同聊天记录，密码之类的会换成「[已隐藏]」）。在别的电脑上解压，把文件夹拖给任意 Agent，它读了说明就能接着了解你。"),
          T("「记忆存档」里可以导入别处导出的压缩包，点「启用」就换过去；换之前会自动备份当前的记忆，随时能换回来。"),
          T("没有云端备份，记得偶尔导出一份存好。")]) };
    }
    return { t: T("都设置好了"), b: "<p>" + T("现在它会开始陪着你。点左边的「陪我聊聊」就能和它说话。") + "</p>" +
      '<div class="avatar-row"><span class="avatar-preview" data-sketch="circle" data-sketch-tone="soft">' + avatarInner() + "</span>" +
      '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="avatar-pick">' + ico("image") + T("换一个头像（可选）") + "</button></div>" +
      list([T("以后改设置，改完都要点「保存」。"), T("想再看一遍这个引导：「设置 → 其他 → 重新打开引导」。")]) };
  }
  function renderGuide() {
    var i = guide.step, st = guideBody(i), last = i === GUIDE_STEPS - 1, dots = "";
    for (var k = 0; k < GUIDE_STEPS; k++) dots += '<i class="' + (k === i ? "on" : k < i ? "done" : "") + '"></i>';
    guide.el.innerHTML = '<div class="card first-card guide" role="dialog" aria-modal="true" aria-labelledby="g-t" data-sketch>' +
      '<div class="g-top"><span class="small">' + T("第 {n} 步，共 {m} 步", { n: i + 1, m: GUIDE_STEPS }) + '</span><span class="g-dots">' + dots + "</span></div>" +
      '<h2 id="g-t">' + esc(st.t) + '</h2><div class="g-body" id="g-body">' + st.b + "</div>" +
      '<div class="g-foot">' + (last ? "<span></span>" : '<button class="btn quiet" data-act="g-skip">' + T("跳过所有") + "</button>") +
      '<span class="g-nav">' + (i > 0 ? '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-act="g-prev">' + ico("arrow-left") + T("上一步") + "</button>" : "") +
      '<button class="btn primary" data-sketch data-act="g-next">' + (last ? T("开始使用") : T("下一步")) + ico(last ? "check" : "arrow-right") + "</button></span></div></div>";
    window.Sketch && Sketch.init(guide.el);
    var body = document.getElementById("g-body");
    trackForm(body.querySelector("[data-save]") ? body : null, guideSave);
    if (i === 1) fillZones("g-tz");
    if (i === 4 && LIVE) { pollModel(); extStatus(); }
  }
  function guideSave() {
    var body = {}, g = function (id) { return document.getElementById(id); };
    if (g("g-tz")) body.timezone = g("g-tz").value;
    if (g("g-apps")) body.blocked_apps = lines(g("g-apps").value);
    if (g("g-words")) body.blocked_keywords = lines(g("g-words").value);
    if (g("g-brain")) body.chat_brain = g("g-brain").value;
    if (g("g-key") && g("g-key").value.trim()) body.deepseek_api_key = g("g-key").value.trim();
    if (g("g-auto")) body.autostart = g("g-auto").checked;
    return (LIVE ? A.post("/api/settings", body) : Promise.resolve()).then(function () {
      toast(LIVE ? T("已保存") : T("已保存（预览模式不会真的保存）"));
      if (LIVE) return Promise.all([data.settings(), data.status()]).then(function (r) { guide.s = r[0]; STATUS = r[1]; });
    }).then(function () {
      if (g("g-key") && g("g-key").value) { g("g-key").value = ""; g("g-key").placeholder = T("已保存（加密）"); }
      trackForm(document.getElementById("g-body"), guideSave);
    });
  }

  /* ---------- 记忆库：存档、搬家（决定 0012） ---------- */
  // 换记忆库 / 搬家的进度。做完（或失败）后程序会自动重启，这个窗口会关掉，新的会自己打开。
  function libJob(title) {
    var mask = document.createElement("div");
    mask.className = "first-mask";
    mask.innerHTML = '<div class="card first-card job" data-sketch><h2>' + esc(title) + '</h2><p class="muted" id="job-stage">' + T("正在停下记录……") + "</p>" +
      '<div class="bar" data-sketch data-sketch-tone="soft"><i id="job-bar" style="width:0"></i></div>' +
      '<p class="small" id="job-note">' + T("请不要关掉这个窗口。做完后程序会自动重新打开。") + "</p></div>";
    document.body.appendChild(mask);
    window.Sketch && Sketch.init(mask);
    var timer = setInterval(function () {
      A.get("/api/library/job").then(function (j) {
        var st = document.getElementById("job-stage"), bar = document.getElementById("job-bar"), note = document.getElementById("job-note");
        if (j.stage) st.textContent = j.stage;
        if (j.total) bar.style.width = Math.min(100, Math.round(j.done / j.total * 100)) + "%";
        if (j.state === "restarting") { st.textContent = T("完成，正在重新打开……"); bar.style.width = "100%"; }
        if (j.state === "error") { st.textContent = T("没成功：{msg}", { msg: j.message }); note.textContent = T("原来的数据没有动。程序会自动重新打开。"); }
        if (j.manual) { clearInterval(timer); note.textContent = T("请手动重新打开程序。"); }
      }).catch(function () { clearInterval(timer); });   // 连不上了：程序已经退出去重启了
    }, 700);
  }
  function openArchives() {
    data.library().then(function (lib) {
      var items = lib.archives || [];
      function kind(k) { return k === "backup" ? T("自动备份") : T("导出的记忆库"); }
      var body = '<p class="small">' + T("点「启用」换成那一份记忆，程序会自动重启；换之前，当前的记忆会自动备份成压缩包放进这里。两份记忆不会合并。") + "</p>" +
        (items.length ? '<ul class="arch-list">' + items.map(function (a) {
          return "<li><div><b>" + esc(a.name) + '</b><div class="small">' + (a.ok ? esc(kind(a.kind)) + " · " + esc(a.exportedAt) + " · " +
            T("{n} 条记忆", { n: Number(a.facts) || 0 }) + (a.chats ? " · " + T("含聊天记录") : "") : T("这个压缩包读不出来")) +
            " · " + (a.size / 1048576).toFixed(1) + " MB</div></div>" +
            (a.ok ? '<button class="btn quiet" data-sketch data-sketch-tone="soft" data-ans="enable:' + esc(a.name) + '">' + ico("check") + T("启用") + "</button>" : "<span></span>") + "</li>";
        }).join("") + "</ul>" : '<p class="muted">' + T("还没有存档。可以导入别的电脑上导出的记忆库压缩包。") + "</p>");
      return choose(T("记忆存档"), body, [{ key: "folder", label: T("打开存档文件夹") }, { key: "import", label: T("导入压缩包…") },
        { key: "close", label: T("关闭"), primary: true }], { wide: true });
    }).then(function (k) {
      if (!k || k === "close") return;
      if (!LIVE) { toast(T("（预览演示）这里会真的操作记忆存档")); return; }
      if (k === "folder") return A.post("/api/library/archives/open");
      if (k === "import") {
        return A.post("/api/library/import").then(function (r) {
          if (!r.cancelled) toast(T("已导入：{name}（{n} 条记忆）", { name: r.name, n: r.facts }));
          openArchives();
        }, function (e) { fail(e); openArchives(); });
      }
      if (k.indexOf("enable:") === 0) {
        var name = k.slice(7);
        return ask(T("启用这份记忆？"), "<p><code>" + esc(name) + "</code></p><p>" +
          T("当前的记忆会先自动备份成压缩包放进记忆存档，然后换成这一份。程序会自动重启。") + "</p>").then(function (yes) {
          if (!yes) return openArchives();
          return A.post("/api/library/enable", { name: name }).then(function () { libJob(T("正在启用选中的记忆")); });
        });
      }
    }).catch(fail);
  }
  function moveLibrary() {
    if (!LIVE) { toast(T("（预览演示）这里会让你选一个新文件夹")); return; }
    leaveOk().then(function (ok) {
      if (!ok) return;
      return A.post("/api/library/move/pick").then(function (r) {
        if (r.cancelled) return;
        return ask(T("把记忆库搬到这里？"), "<p>" + T("从：") + " <code>" + esc(r.from) + "</code></p><p>" + T("到：") + " <code>" + esc(r.dest) + "</code></p><p>" +
          T("程序会先暂停记录，复制所有文件并逐个核对，核对无误后才删掉旧位置的文件，然后自动重启。下载过向量模型的话有 2GB 多，可能要一两分钟。") + "</p>").then(function (yes) {
          if (!yes) return;
          return A.post("/api/library/move").then(function () { libJob(T("正在把记忆库搬到新位置")); });
        });
      });
    }).catch(fail);
  }

  window.addEventListener("hashchange", go);
  // 启动：先读偏好和语言，翻译好再画页面（避免先闪一下中文）
  prefs.load().then(function () {
    if (LIVE) return data.status().then(function (st) { return st.language; }, function () { return "zh"; });
    return prefs.get("lang") || I.guess();
  }).then(I.load).then(function () {
    I.apply();
    applySkin();   // 主题先定下来（同步换上），再画页面
    setSide(prefs.get("side") === "collapsed", false);
    applyAvatar();
    go();
    // 第一次打开：先风险确认，再引导。预览时在地址后面加 #first 可以看这两页。
    if (LIVE) data.status().then(function (st) { if (st.termsAccepted === false) showTerms(); else if (st.onboarded === false) openGuide(0); }).catch(function () {});
    else if (location.hash === "#first") showTerms();
  });
})();
