/*
 * 液态玻璃主题（决定 0013）。铅笔手绘主题时这里什么都不做。
 *
 * 三种玻璃：
 *   大块磨砂（侧边栏、内容区）和小块液态玻璃（按钮、标签、输入框、开关、侧边栏选中块）：
 *     每块玻璃里放一份「背景的副本」（气泡或壁纸，按它在窗口里的位置对齐），再用 SVG 滤镜把边缘往里弯、模糊。
 *     这样不管嵌在几层里面，折射的都是壁纸本身，而且比「透过去看背后」省。
 *   浮在上面的（弹窗、菜单、提示条、主题面板）：用 backdrop-filter 透过去看底下的界面。
 *   卡片、聊天气泡：只有一层淡淡的玻璃色和亮边，让下面的大块磨砂透上来。
 *
 * 互动：鼠标高光、长按拉伸（松手回弹）、侧边栏选中块可以按住拖动、开关小圆点按住变透镜可以拖。
 * 动效分「完整 / 收敛 / 关闭」；系统开了「减少动态效果」时一律关闭。
 *
 * 对外：window.Glass.set({ skin, bg, mode, veil, motion, wall })
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var NS = "http://www.w3.org/2000/svg";
  var reduceMQ = window.matchMedia("(prefers-reduced-motion: reduce)");
  var st = { skin: "pencil", bg: "bubbles", mode: "auto", veil: 0.5, motion: "calm", wall: null };
  function on() { return st.skin === "glass"; }
  function motion() { return reduceMQ.matches ? "off" : st.motion; }

  /* ---------- 弹簧：所有回弹、流过去都用它 ---------- */
  function Spring(value, opts) {
    opts = opts || {};
    this.x = value; this.v = 0; this.t = value;
    this.k = opts.k || 340; this.zeta = opts.zeta || 0.72;
    this.on = opts.on || function () {};
    this.done = opts.done || null;
    this.running = false;
    this._step = this.step.bind(this);
  }
  Spring.prototype.to = function (t, zeta) {
    this.t = t;
    if (zeta) this.zeta = zeta;
    if (motion() === "off") { this.jump(t); return; }
    if (!this.running) { this.running = true; this.last = performance.now(); requestAnimationFrame(this._step); }
  };
  Spring.prototype.jump = function (t) {
    this.x = this.t = t; this.v = 0; this.running = false; this.on(t, 0);
    if (this.done) this.done();
  };
  Spring.prototype.step = function (now) {
    if (!this.running) return;
    var dt = Math.min(0.034, (now - this.last) / 1000), c = 2 * Math.sqrt(this.k) * this.zeta;
    this.last = now;
    for (var i = 0; i < 4; i++) {
      var h = dt / 4, a = -this.k * (this.x - this.t) - c * this.v;
      this.v += a * h; this.x += this.v * h;
    }
    if (Math.abs(this.x - this.t) < 0.02 && Math.abs(this.v) < 0.5) { this.jump(this.t); return; }
    this.on(this.x, this.v);
    keepAlive(50);
    requestAnimationFrame(this._step);
  };

  /* ---------- 滤镜仓库 ---------- */
  var defs = null, mapCache = {}, filterCache = {}, filterCount = 0;
  function ensureDefs() {
    if (defs) return defs;
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("aria-hidden", "true"); svg.setAttribute("width", "0"); svg.setAttribute("height", "0");
    svg.style.position = "absolute";
    defs = document.createElementNS(NS, "defs");
    svg.appendChild(defs);
    document.body.appendChild(svg);
    return defs;
  }
  // 位移图：圆角矩形（在 margin 处开始）的边上一圈往里弯，越靠边弯得越多；红=左右，绿=上下，128=不动
  function displacementMap(W, H, m, r, bezel, power) {
    var key = [W, H, m, r, bezel, power].join(",");
    if (mapCache[key]) return mapCache[key];
    if (Object.keys(mapCache).length > 120) mapCache = {};   // 用过的滤镜已经带着图了，缓存只是省得重算，满了就清
    var s = Math.min(0.5, 360 / Math.max(W, H)), cw = Math.max(2, Math.round(W * s)), ch = Math.max(2, Math.round(H * s));
    var c = document.createElement("canvas"); c.width = cw; c.height = ch;
    var ctx = c.getContext("2d"), img = ctx.createImageData(cw, ch), d = img.data;
    var w = W - 2 * m, h = H - 2 * m, hw = w / 2, hh = h / 2, rr = Math.min(r, hw, hh);
    for (var j = 0; j < ch; j++) {
      for (var i = 0; i < cw; i++) {
        var x = (i + 0.5) / s - m - hw, y = (j + 0.5) / s - m - hh;
        var qx = Math.abs(x) - (hw - rr), qy = Math.abs(y) - (hh - rr);
        var ox = Math.max(qx, 0), oy = Math.max(qy, 0);
        var inside = -(Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0) - rr);
        var k = (j * cw + i) * 4, dx = 0, dy = 0;
        if (inside >= 0 && inside < bezel) {
          var nx = 0, ny = 0;
          if (qx > 0 && qy > 0) { var l = Math.hypot(ox, oy) || 1; nx = ox / l; ny = oy / l; }
          else if (qx > qy) nx = 1; else ny = 1;
          nx *= x < 0 ? -1 : 1; ny *= y < 0 ? -1 : 1;
          var t = 1 - inside / bezel, mm = Math.pow(t, power);
          dx = -nx * mm; dy = -ny * mm;
        }
        d[k] = 128 + dx * 127; d[k + 1] = 128 + dy * 127; d[k + 2] = 128; d[k + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return (mapCache[key] = c.toDataURL());
  }
  // kind：sheet 大块磨砂 / ctl 小块液态玻璃 / float 浮层（backdrop）/ lens 透镜（backdrop，带一点彩边）
  function params(kind, w, h) {
    var v = st.veil, mn = Math.min(w, h);
    if (kind === "sheet") return { blur: 3 + 10 * v, bezel: Math.min(30, mn * 0.3), power: 2, scale: 30, sat: 1.45 };
    if (kind === "ctl") return { blur: 1.2 + 3.5 * v, bezel: Math.min(16, mn * 0.42), power: 1.8, scale: Math.min(16, mn * 0.42) * 1.5, sat: 1.6 };
    if (kind === "float") return { blur: 10 + 10 * v, bezel: Math.min(28, mn * 0.3), power: 2, scale: 30, sat: 1.5 };
    return { blur: 0.4, bezel: mn * 0.36, power: 2.4, scale: mn * 0.5, sat: 1.4, chroma: true };   // lens
  }
  function filterId(kind, w, h, r, m) {
    w = Math.round(w); h = Math.round(h); r = Math.round(r); m = Math.round(m || 0);
    var key = kind + "|" + w + "x" + h + "|" + r + "|" + m + "|" + st.veil.toFixed(2);
    if (filterCache[key]) return filterCache[key];
    var p = params(kind, w, h), W = w + 2 * m, H = h + 2 * m;
    var id = "glf" + (++filterCount);
    var map = displacementMap(W, H, m, r, Math.max(2, p.bezel), p.power);
    var f = document.createElementNS(NS, "filter");
    f.setAttribute("id", id);
    f.setAttribute("x", "0"); f.setAttribute("y", "0"); f.setAttribute("width", W); f.setAttribute("height", H);
    f.setAttribute("filterUnits", "userSpaceOnUse");
    f.setAttribute("color-interpolation-filters", "sRGB");
    var html = '<feGaussianBlur in="SourceGraphic" stdDeviation="' + p.blur.toFixed(1) + '" result="b"/>' +
      '<feImage href="' + map + '" x="0" y="0" width="' + W + '" height="' + H + '" preserveAspectRatio="none" result="m"/>';
    if (p.chroma) {
      html += ["1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0", "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0", "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0"]
        .map(function (mx, i) {
          return '<feDisplacementMap in="b" in2="m" scale="' + (p.scale * (1 + i * 0.03)).toFixed(1) + '" xChannelSelector="R" yChannelSelector="G" result="d' + i + '"/>' +
            '<feColorMatrix in="d' + i + '" type="matrix" values="' + mx + '" result="c' + i + '"/>';
        }).join("") +
        '<feBlend in="c0" in2="c1" mode="screen" result="c01"/><feBlend in="c01" in2="c2" mode="screen" result="rgb"/>' +
        '<feColorMatrix in="rgb" type="saturate" values="' + p.sat + '"/>';
    } else {
      html += '<feDisplacementMap in="b" in2="m" scale="' + p.scale.toFixed(1) + '" xChannelSelector="R" yChannelSelector="G" result="d"/>' +
        '<feColorMatrix in="d" type="saturate" values="' + p.sat + '"/>';
    }
    f.innerHTML = html;
    ensureDefs().appendChild(f);
    filterCache[key] = id;
    return id;
  }
  function clearFilters() {
    filterCache = {};
    if (defs) defs.innerHTML = "";
  }
  function radiusOf(el) { return parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0; }

  /* ---------- 背景：紫白色超大气泡（堆在角落、只露一部分，非常缓慢地漂移）/ 自己的壁纸 ---------- */
  // 圆心和半径用「窗口长边的百分之几」表示，ax/ay 漂移幅度，p 周期（秒）
  var BUBBLES = [
    { cx: [1, -4], cy: [0, -7], r: 30, ax: 1.6, ay: 1.2, p: 74, f: 0.1 },    // 右上
    { cx: [1, 4], cy: [0, 20], r: 19, ax: 1.2, ay: 1.8, p: 91, f: 1.7 },
    { cx: [1, -30], cy: [0, -12], r: 15, ax: 2.0, ay: 1.0, p: 63, f: 3.1 },
    { cx: [0, -3], cy: [1, 3], r: 34, ax: 1.4, ay: 1.4, p: 86, f: 0.9 },     // 左下
    { cx: [0, 27], cy: [1, 11], r: 18, ax: 1.8, ay: 1.2, p: 69, f: 2.4 },
    { cx: [0, -10], cy: [1, -30], r: 14, ax: 1.2, ay: 2.0, p: 102, f: 4.2 },
    { cx: [1, 3], cy: [1, 4], r: 12, ax: 1.4, ay: 1.4, p: 80, f: 5.3 }       // 右下（小）
  ];
  var BUB_HTML = '<span class="gb-bub">' + BUBBLES.map(function () { return "<i></i>"; }).join("") + "</span>";
  var bgEl = null, wallUrl = null, wallSize = null, driftTimer = 0, t0 = performance.now();
  function ensureBg() {
    if (bgEl) return;
    bgEl = document.createElement("div");
    bgEl.id = "glass-bg"; bgEl.setAttribute("aria-hidden", "true");
    bgEl.innerHTML = BUB_HTML + '<span class="gb-wall"></span>';
    document.body.insertBefore(bgEl, document.body.firstChild);
    var css = BUBBLES.map(function (b, i) {
      var n = i + 1;
      return ".gb-bub>i:nth-child(" + n + "){width:var(--gb" + n + "-s);height:var(--gb" + n + "-s);" +
        "transform:translate(calc(var(--gb" + n + "-x) - var(--ox,0px) + var(--gm,0px)),calc(var(--gb" + n + "-y) - var(--oy,0px) + var(--gm,0px)))}";
    }).join("\n");
    var style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
  }
  function placeBubbles() {
    var W = window.innerWidth, H = window.innerHeight, u = Math.max(W, H) / 100;
    var t = (performance.now() - t0) / 1000, still = motion() === "off";
    BUBBLES.forEach(function (b, i) {
      var n = i + 1, r = b.r * u;
      var dx = still ? 0 : b.ax * u * Math.sin(2 * Math.PI * t / b.p + b.f);
      var dy = still ? 0 : b.ay * u * Math.cos(2 * Math.PI * t / (b.p * 1.3) + b.f);
      var cx = b.cx[0] * W + b.cx[1] * u + dx, cy = b.cy[0] * H + b.cy[1] * u + dy;
      root.style.setProperty("--gb" + n + "-x", (cx - r).toFixed(1) + "px");
      root.style.setProperty("--gb" + n + "-y", (cy - r).toFixed(1) + "px");
      root.style.setProperty("--gb" + n + "-s", (2 * r).toFixed(1) + "px");
    });
  }
  function drift() {
    clearInterval(driftTimer); driftTimer = 0;
    placeBubbles();
    if (on() && root.getAttribute("data-glass-bg") !== "wall" && motion() !== "off") {
      driftTimer = setInterval(function () { if (!document.hidden) placeBubbles(); }, 100);   // 很慢的漂移，每秒 10 次足够顺
    }
  }
  function placeWall() {
    if (!wallSize) return;
    var W = window.innerWidth, H = window.innerHeight, s = Math.max(W / wallSize[0], H / wallSize[1]);
    var w = wallSize[0] * s, h = wallSize[1] * s;
    root.style.setProperty("--gw-size", w.toFixed(1) + "px " + h.toFixed(1) + "px");
    root.style.setProperty("--gw-x", ((W - w) / 2).toFixed(1) + "px");
    root.style.setProperty("--gw-y", ((H - h) / 2).toFixed(1) + "px");
  }
  function setWall(dataUrl) {
    if (dataUrl === st.wall && wallUrl) return Promise.resolve(true);
    st.wall = dataUrl;
    if (wallUrl) { URL.revokeObjectURL(wallUrl); wallUrl = null; }
    wallSize = null;
    root.style.removeProperty("--gw-img");
    if (!dataUrl) return Promise.resolve(false);
    return fetch(dataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
      wallUrl = URL.createObjectURL(blob);   // 用短的 blob 地址，免得几 MB 的字符串到处复制
      return new Promise(function (res) {
        var im = new Image();
        im.onload = function () {
          wallSize = [im.naturalWidth || 1, im.naturalHeight || 1];
          root.style.setProperty("--gw-img", 'url("' + wallUrl + '")');
          placeWall(); res(true);
        };
        im.onerror = function () { res(false); };
        im.src = wallUrl;
      });
    }).catch(function () { return false; });
  }

  /* ---------- 哪些东西做成玻璃 ---------- */
  var SHEET = ".side, .main";
  var CTL = ".btn, .chip.filter, .input-wrap, .switch .track, .gl-navpill";
  var FLOAT = ".ask, .first-card, .lang-menu, .toast, .theme-panel";
  var PLATE = ".card, .msg, .chip, .bar, .save-note";
  var tracked = [], floats = [];

  function enhance(el, kind) {
    var g = el._gl;
    if (g && g.bg.parentNode === el) {
      if (!g.tracked) { tracked.push(el); g.tracked = true; g.w = 0; }
      return;
    }
    if (!g) {
      var bg = document.createElement("span"), src = document.createElement("span"), rim = document.createElement("span");
      bg.className = "gl-bg"; bg.setAttribute("aria-hidden", "true");
      src.className = "gl-src"; src.innerHTML = BUB_HTML + '<span class="gb-wall"></span>';
      rim.className = "gl-rim";
      bg.appendChild(src); bg.appendChild(rim);
      g = el._gl = { bg: bg, src: src, kind: kind, x: NaN, y: NaN, w: 0, h: 0, fid: "", tracked: false };
    }
    if (!g.tracked) { tracked.push(el); g.tracked = true; g.w = 0; }
    el.insertBefore(g.bg, el.firstChild);
    el.classList.add("gl-on", "gl-" + kind);
  }
  function scan(rootEl) {
    if (!on()) return;
    var base = rootEl && rootEl.querySelectorAll ? rootEl : document;
    var list, i;
    list = base.querySelectorAll(SHEET);
    for (i = 0; i < list.length; i++) enhance(list[i], "sheet");
    list = base.querySelectorAll(CTL);
    for (i = 0; i < list.length; i++) {
      if (!list[i].closest(".sk-svg")) enhance(list[i], "ctl");
    }
    list = base.querySelectorAll(FLOAT);
    for (i = 0; i < list.length; i++) {
      var f = list[i];
      f.classList.add("gl-float");
      if (floats.indexOf(f) < 0) { floats.push(f); floatRO.observe(f); }
    }
    list = base.querySelectorAll(PLATE);
    for (i = 0; i < list.length; i++) {
      if (!list[i].classList.contains("gl-float") && !list[i].classList.contains("gl-on")) list[i].classList.add("gl-plate");
    }
    ensurePill();
    keepAlive(1600);   // 新出来的东西有入场动画，这段时间跟着对齐
  }
  function unenhanceAll() {
    document.querySelectorAll(".gl-on").forEach(function (el) {
      if (el._gl) { el._gl.bg.remove(); el._gl = null; }
      el.classList.remove("gl-on", "gl-sheet", "gl-ctl");
      el.style.translate = el.style.scale = "";
    });
    tracked = [];
    floats.forEach(function (f) { f.classList.remove("gl-float"); f.style.backdropFilter = ""; floatRO.unobserve(f); });
    floats = [];
    document.querySelectorAll(".gl-plate").forEach(function (el) { el.classList.remove("gl-plate"); });
    document.querySelectorAll(".gl-navpill").forEach(function (p) { p.remove(); });
    clearFilters();
  }

  // 浮层：大小变了就换一张合身的折射滤镜
  var floatRO = new ResizeObserver(function (entries) {
    entries.forEach(function (e) { fitFloat(e.target); });
  });
  function fitFloat(f) {
    if (!on() || !f.isConnected) return;
    var w = f.offsetWidth, h = f.offsetHeight;
    if (!w || !h) return;
    var id = filterId("float", w, h, radiusOf(f), 0);
    f.style.backdropFilter = "url(#" + id + ")";
  }

  /* ---------- 每一帧：把每块玻璃里的背景副本对齐到它在窗口里的位置 ---------- */
  var aliveUntil = 0, rafOn = false;
  function keepAlive(ms) {
    if (!on()) return;
    aliveUntil = Math.max(aliveUntil, performance.now() + ms);
    if (!rafOn) { rafOn = true; requestAnimationFrame(frame); }
  }
  function frame() {
    if (!on()) { rafOn = false; return; }
    align();
    if (performance.now() < aliveUntil) requestAnimationFrame(frame);
    else rafOn = false;
  }
  function align() {
    var keep = [];
    for (var i = 0; i < tracked.length; i++) {
      var el = tracked[i], g = el._gl;
      if (!g) continue;
      if (!el.isConnected) { g.tracked = false; continue; }   // 已经不在页面上了：不再跟踪（重新出现时会重新加上）
      keep.push(el);
      if (g.bg.parentNode !== el) continue;
      var w = el.offsetWidth, h = el.offsetHeight;
      if (!w || !h) continue;
      if (w !== g.w || h !== g.h) {
        var p = params(g.kind, w, h), m = Math.ceil(p.blur * 2.2) + 2;
        g.w = w; g.h = h; g.m = m;
        g.src.style.setProperty("--gm", m + "px");
        g.src.style.left = g.src.style.top = -m + "px";
        g.src.style.width = (w + 2 * m) + "px"; g.src.style.height = (h + 2 * m) + "px";
        g.fid = filterId(g.kind, w, h, radiusOf(el), m);
        g.src.style.filter = "url(#" + g.fid + ")";
      }
      var r = el.getBoundingClientRect();
      if (Math.abs(r.left - g.x) > 0.25 || Math.abs(r.top - g.y) > 0.25) {
        g.x = r.left; g.y = r.top;
        g.src.style.setProperty("--ox", r.left.toFixed(1) + "px");
        g.src.style.setProperty("--oy", r.top.toFixed(1) + "px");
      }
    }
    tracked = keep;
  }

  /* ---------- 鼠标高光 ---------- */
  document.addEventListener("pointermove", function (e) {
    if (!on() || !e.target.closest) return;
    var t = e.target.closest(".gl-on, .gl-plate, .gl-float"), n = 0;
    while (t && n++ < 4) {
      var r = t.getBoundingClientRect();
      t.style.setProperty("--mx", (e.clientX - r.left).toFixed(0) + "px");
      t.style.setProperty("--my", (e.clientY - r.top).toFixed(0) + "px");
      t = t.parentElement && t.parentElement.closest(".gl-on, .gl-plate, .gl-float");
    }
  }, { passive: true });

  /* ---------- 点击被「拉伸 / 拖动」吃掉：松手后那一下 click 不算 ---------- */
  var swallowUntil = 0, swallowEl = null;
  function swallowNextClick(el) { swallowEl = el; swallowUntil = performance.now() + 500; }
  document.addEventListener("click", function (e) {
    if (swallowEl && performance.now() < swallowUntil && swallowEl.contains(e.target)) {
      e.preventDefault(); e.stopPropagation(); swallowEl = null;
    }
  }, true);

  /* ---------- 长按拉伸：按住 0.3 秒后往外拉，东西被拉长一点，松手弹回来 ---------- */
  var STRETCH = ".btn, .card, .chip, .side";
  var NO_STRETCH = ".msgs, .gl-float, input, textarea, select, .input-wrap, .switch, .nav, .lang-pick, .side-toggle, .brand, a, .theme-panel";
  var press = null;
  document.addEventListener("pointerdown", function (e) {
    if (!on() || e.button !== 0 || motion() === "off" || press) return;
    var t = e.target.closest && e.target.closest(STRETCH);
    if (!t || e.target.closest(NO_STRETCH)) return;
    press = { el: t, x: e.clientX, y: e.clientY, id: e.pointerId, armed: false, s: 0 };
    press.timer = setTimeout(function () {
      if (!press) return;
      press.armed = true;
      try { t.setPointerCapture(press.id); } catch (err) { /* 指针已经松开 */ }
      document.body.classList.add("gl-noselect");
      var sel = window.getSelection && window.getSelection(); if (sel) sel.removeAllRanges();
      t.classList.add("gl-armed");
    }, 300);
  });
  document.addEventListener("pointermove", function (e) {
    if (!press || e.pointerId !== press.id) return;
    var dx = e.clientX - press.x, dy = e.clientY - press.y, dist = Math.hypot(dx, dy);
    if (!press.armed) { if (dist > 6) endPress(false); return; }
    var max = motion() === "full" ? 0.14 : 0.08;
    var s = max * (1 - Math.exp(-dist / 170)), pull = 1 - Math.exp(-dist / 220);
    var ux = dist ? dx / dist : 0, uy = dist ? dy / dist : 0, ax = Math.abs(ux), ay = Math.abs(uy);
    press.s = s; press.ux = ux; press.uy = uy; press.pull = pull;
    applyStretch(press.el, ux * pull * 16, uy * pull * 16, 1 + s * ax - s * 0.45 * ay, 1 + s * ay - s * 0.45 * ax);
    keepAlive(80);
  });
  function applyStretch(el, tx, ty, sx, sy) {
    el.style.translate = tx.toFixed(2) + "px " + ty.toFixed(2) + "px";
    el.style.scale = sx.toFixed(4) + " " + sy.toFixed(4);
  }
  function endPress(released) {
    if (!press) return;
    var p = press; press = null;
    clearTimeout(p.timer);
    document.body.classList.remove("gl-noselect");
    p.el.classList.remove("gl-armed");
    if (!p.armed) return;
    swallowNextClick(p.el);
    if (!p.s) { p.el.style.translate = p.el.style.scale = ""; return; }
    // 从拉开的样子弹回原样：用一个从 1 到 0 的弹簧（会稍微越过 0 一点，就是「啵」的那一下）
    var ax = Math.abs(p.ux), ay = Math.abs(p.uy), s = p.s, pull = p.pull;
    var sp = new Spring(1, {
      k: 420, zeta: motion() === "full" ? 0.42 : 0.58,
      on: function (q) {
        applyStretch(p.el, p.ux * pull * 16 * q, p.uy * pull * 16 * q, 1 + (s * ax - s * 0.45 * ay) * q, 1 + (s * ay - s * 0.45 * ax) * q);
      },
      done: function () { p.el.style.translate = p.el.style.scale = ""; }
    });
    sp.to(0);
  }
  document.addEventListener("pointerup", function (e) { if (press && e.pointerId === press.id) endPress(true); });
  document.addEventListener("pointercancel", function (e) { if (press && e.pointerId === press.id) endPress(false); });

  /* ---------- 侧边栏：选中块是一块会流过去的玻璃，可以按住上下拖 ---------- */
  var pill = null, pillY = null, pillSpring = null, navDrag = null;
  function ensurePill() {
    var nav = document.getElementById("nav");
    if (!nav) return;
    var cur = nav.querySelector("a.on");
    if (!pill || pill.parentNode !== nav) {
      if (!pill) {
        pill = document.createElement("span");
        pill.className = "gl-navpill"; pill.setAttribute("aria-hidden", "true");
        pillSpring = new Spring(0, { k: 330, zeta: 0.74, on: function (y, v) {
          var s = Math.min(Math.abs(v) / 2600, 0.24);
          pill.style.transform = "translateY(" + y.toFixed(1) + "px) scale(" + (1 - s * 0.3).toFixed(3) + "," + (1 + s).toFixed(3) + ")";
        } });
      }
      nav.insertBefore(pill, nav.firstChild);
      enhance(pill, "ctl");
      if (pillY != null) pillSpring.jump(pillY);
    }
    if (!cur) { pill.style.opacity = "0"; return; }
    pill.style.opacity = "";
    pill.style.height = cur.offsetHeight + "px";
    var y = cur.offsetTop;
    if (navDrag && navDrag.moving) return;
    if (pillY == null) pillSpring.jump(y); else if (pillSpring.t !== y) pillSpring.to(y);
    pillY = y;
  }
  document.addEventListener("pointerdown", function (e) {
    if (!on() || e.button !== 0 || !pill) return;
    var a = e.target.closest && e.target.closest("#nav a");
    if (!a) return;
    navDrag = { y0: e.clientY, py0: pillSpring.x, id: e.pointerId, moving: false, nav: a.parentNode };
  });
  document.addEventListener("pointermove", function (e) {
    if (!navDrag || e.pointerId !== navDrag.id) return;
    var dy = e.clientY - navDrag.y0;
    if (!navDrag.moving) {
      if (Math.abs(dy) < 6) return;
      navDrag.moving = true;
      try { navDrag.nav.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
      document.body.classList.add("gl-noselect");
      liftPill(true);
    }
    var links = navDrag.nav.querySelectorAll("a"), min = links[0].offsetTop, max = links[links.length - 1].offsetTop;
    var y = navDrag.py0 + dy, over = y < min ? y - min : y > max ? y - max : 0;
    pillSpring.to(Math.max(min, Math.min(max, y)) + over * 0.25, 0.9);   // 拖出头了有一点阻力
    keepAlive(80);
  });
  function endNavDrag(e) {
    if (!navDrag || (e && e.pointerId !== navDrag.id)) return;
    var d = navDrag; navDrag = null;
    document.body.classList.remove("gl-noselect");
    if (!d.moving) return;
    // 按手指拖到的位置（弹簧的目标）找最近的一项；弹簧本身可能还没追上手指
    var links = [].slice.call(d.nav.querySelectorAll("a")), y = pillSpring.t, best = links[0];
    links.forEach(function (a) { if (Math.abs(a.offsetTop - y) < Math.abs(best.offsetTop - y)) best = a; });
    pillSpring.to(best.offsetTop, 0.62);
    pillY = best.offsetTop;
    setTimeout(function () { liftPill(false); }, 160);
    if (best.getAttribute("href") !== (location.hash || "#today")) best.click();   // 走正常的换页（有没保存的修改会先问）
    swallowNextClick(d.nav);   // 放在上面那次 click 之后：只吃掉松手时浏览器自己补的那一下
  }
  document.addEventListener("pointerup", endNavDrag);
  document.addEventListener("pointercancel", endNavDrag);
  function liftPill(up) {
    if (!pill) return;
    pill.classList.toggle("lifted", up);
    if (up) {
      var id = filterId("lens", pill.offsetWidth, pill.offsetHeight, radiusOf(pill), 0);
      pill.style.backdropFilter = "url(#" + id + ")";
    } else {
      pill.style.backdropFilter = "";
    }
  }

  /* ---------- 开关：按住时小圆点变成透镜，可以拖过去 ---------- */
  var swDrag = null;
  document.addEventListener("pointerdown", function (e) {
    if (!on() || e.button !== 0) return;
    var sw = e.target.closest && e.target.closest(".switch");
    if (!sw) return;
    var track = sw.querySelector(".track"), knob = sw.querySelector(".knob"), input = sw.querySelector("input");
    if (!track || !knob || !input) return;
    var tr = track.getBoundingClientRect();
    swDrag = { sw: sw, track: track, knob: knob, input: input, id: e.pointerId, x0: e.clientX, moving: false,
      min: 3, max: tr.width - knob.offsetWidth - 3, left: tr.left };
    sw.classList.add("gl-press");
    var id = filterId("lens", knob.offsetWidth, knob.offsetHeight, knob.offsetWidth / 2, 0);
    knob.style.backdropFilter = "url(#" + id + ")";
  });
  document.addEventListener("pointermove", function (e) {
    if (!swDrag || e.pointerId !== swDrag.id) return;
    var d = swDrag;
    if (!d.moving && Math.abs(e.clientX - d.x0) < 5) return;
    if (!d.moving) { d.moving = true; try { d.sw.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ } }
    var x = Math.max(d.min, Math.min(d.max, e.clientX - d.left - d.knob.offsetWidth / 2));
    d.knob.style.transition = "none";
    d.knob.style.transform = "translateX(" + (x - d.min).toFixed(1) + "px) scale(1.3)";
    d.x = x;
  });
  function endSwitch(e) {
    if (!swDrag || (e && e.pointerId !== swDrag.id)) return;
    var d = swDrag; swDrag = null;
    d.sw.classList.remove("gl-press");
    d.knob.style.backdropFilter = "";
    d.knob.style.transition = ""; d.knob.style.transform = "";
    if (!d.moving) return;                      // 只是点了一下：交给正常的点击去切换
    var want = d.x > (d.min + d.max) / 2;
    swallowNextClick(d.sw);
    if (d.input.checked !== want) {
      d.input.checked = want;
      d.input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  document.addEventListener("pointerup", endSwitch);
  document.addEventListener("pointercancel", endSwitch);

  /* ---------- 页面变化、滚动、窗口大小 ---------- */
  var mo = new MutationObserver(function (records) {
    if (!on()) return;
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      for (var j = 0; j < r.addedNodes.length; j++) {
        var n = r.addedNodes[j];
        if (n.nodeType !== 1 || n.classList.contains("gl-bg") || n.classList.contains("gl-navpill")) continue;
        scan(n.parentNode || document);
        break;
      }
    }
    // 自己（比如 .main）的内容被整个换掉时，副本也被删了：补回去
    tracked.forEach(function (el) { if (el._gl && el.isConnected && el._gl.bg.parentNode !== el) el.insertBefore(el._gl.bg, el.firstChild); });
    ensurePill();
  });
  document.addEventListener("scroll", function () { keepAlive(250); }, { capture: true, passive: true });
  document.addEventListener("transitionrun", function () { keepAlive(700); }, true);
  document.addEventListener("animationstart", function () { keepAlive(900); }, true);
  window.addEventListener("resize", function () {
    if (!on()) return;
    placeBubbles(); placeWall();
    tracked.forEach(function (el) { if (el._gl) el._gl.w = 0; });   // 大小可能变了：下一帧重新量
    floats.forEach(fitFloat);
    ensurePill();
    keepAlive(400);
  });
  if (reduceMQ.addEventListener) reduceMQ.addEventListener("change", function () { if (on()) drift(); });

  /* ---------- 对外 ---------- */
  function set(cfg) {
    var was = on(), veilChanged = cfg.veil != null && Math.abs(cfg.veil - st.veil) > 0.001;
    ["skin", "bg", "mode", "veil", "motion"].forEach(function (k) { if (cfg[k] != null) st[k] = cfg[k]; });
    var wallDone = cfg.wall !== undefined ? setWall(cfg.wall) : Promise.resolve(!!wallUrl);
    if (!on()) {
      root.removeAttribute("data-skin"); root.removeAttribute("data-glass-mode"); root.removeAttribute("data-glass-bg");
      clearInterval(driftTimer); driftTimer = 0;
      if (was) { mo.disconnect(); unenhanceAll(); }
      return wallDone;
    }
    ensureBg();
    root.setAttribute("data-skin", "glass");
    if (st.mode === "light" || st.mode === "dark") root.setAttribute("data-glass-mode", st.mode); else root.removeAttribute("data-glass-mode");
    root.style.setProperty("--gl-veil", st.veil.toFixed(2));
    root.setAttribute("data-motion", motion());
    if (veilChanged) { clearFilters(); tracked.forEach(function (el) { if (el._gl) el._gl.w = 0; }); floats.forEach(fitFloat); }
    return wallDone.then(function (hasWall) {
      root.setAttribute("data-glass-bg", st.bg === "wall" && hasWall ? "wall" : "bubbles");
      drift(); placeWall();
      if (!was) mo.observe(document.body, { childList: true, subtree: true });
      scan(document);
      return hasWall;
    });
  }

  window.Glass = { set: set, isOn: on, refresh: function (el) { scan(el || document); } };
})();
