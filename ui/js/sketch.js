/*
 * 来源：用户个人网页 html-个人/js/sketch.js（用户本人的作品）。
 * 本项目里的改动：入场动画的逐个延迟封顶（一页框很多时不用等太久）；新增了一批界面图标。
 *
 * 手绘铅笔描边。
 *
 * 用法：给任何元素加 data-sketch，它就会被画上一圈铅笔框。
 *   data-sketch            方框（默认）
 *   data-sketch="circle"   圆圈
 *   data-sketch="underline" 下划线
 *   data-sketch-tone="soft" 颜色淡一些
 * 图标：<span class="ico" data-icon="person"></span>
 *
 * 线条每次打开页面都会重新「画」一遍，所以每次看都略有不同；
 * 鼠标移到可点的框上时，会轻轻重描一次。
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var PAD = 8;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var canHover = window.matchMedia("(hover: hover)");

  /* ---------- 铅笔滤镜：线条轻微抖动 + 石墨颗粒 ---------- */
  function ensureDefs() {
    if (document.getElementById("sk-defs")) return;
    var holder = document.createElementNS(NS, "svg");
    holder.setAttribute("id", "sk-defs");
    holder.setAttribute("aria-hidden", "true");
    holder.setAttribute("width", "0");
    holder.setAttribute("height", "0");
    holder.style.position = "absolute";
    holder.innerHTML =
      '<filter id="sk-pencil" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="3" result="warp"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="warp" scale="1.8" xChannelSelector="R" yChannelSelector="G" result="wobble"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="1" seed="8" result="grain"/>' +
      '<feColorMatrix in="grain" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.6 1.55" result="mask"/>' +
      '<feComposite in="wobble" in2="mask" operator="in"/>' +
      "</filter>";
    document.body.insertBefore(holder, document.body.firstChild);
  }

  /* ---------- 随机数（可复现） ---------- */
  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function jit(r, amt) { return (r() - 0.5) * 2 * amt; }
  function n(v) { return Math.round(v * 10) / 10; }

  /* ---------- 形状 ---------- */
  // 一笔略带弧度、两头稍微出头的直线
  function stroke(x1, y1, x2, y2, r, amp) {
    var dx = x2 - x1, dy = y2 - y1;
    var len = Math.hypot(dx, dy) || 1;
    var ux = dx / len, uy = dy / len, nx = -uy, ny = ux;
    var o1 = r() * Math.min(5, len * 0.03);
    var o2 = r() * Math.min(6, len * 0.04);
    var sx = x1 - ux * o1, sy = y1 - uy * o1;
    var ex = x2 + ux * o2, ey = y2 + uy * o2;
    var bend = Math.min(amp, len * 0.025 + 0.6);
    var c1 = jit(r, bend), c2 = jit(r, bend);
    var ddx = ex - sx, ddy = ey - sy;
    return "M" + n(sx) + " " + n(sy) +
      "C" + n(sx + ddx * 0.33 + nx * c1) + " " + n(sy + ddy * 0.33 + ny * c1) +
      " " + n(sx + ddx * 0.66 + nx * c2) + " " + n(sy + ddy * 0.66 + ny * c2) +
      " " + n(ex) + " " + n(ey);
  }

  function box(w, h, r) {
    var k = 1.4;
    var c = [
      [PAD + jit(r, k), PAD + jit(r, k)],
      [PAD + w + jit(r, k), PAD + jit(r, k)],
      [PAD + w + jit(r, k), PAD + h + jit(r, k)],
      [PAD + jit(r, k), PAD + h + jit(r, k)]
    ];
    var d = "";
    for (var i = 0; i < 4; i++) {
      var a = c[i], b = c[(i + 1) % 4];
      d += stroke(a[0], a[1], b[0], b[1], r, 2.2);
    }
    return d;
  }

  function circle(w, h, r) {
    var cx = PAD + w / 2, cy = PAD + h / 2, rx = w / 2, ry = h / 2;
    var count = 12;
    var a0 = r() * Math.PI * 2;
    var sweep = Math.PI * 2 + 0.35 + r() * 0.3;   // 多画一点，首尾交叠
    var drift = (r() < 0.5 ? -1 : 1) * 0.045;
    var pts = [];
    for (var i = 0; i <= count; i++) {
      var t = a0 + (sweep * i) / count;
      var k = 1 + jit(r, 0.025) + drift * (i / count);
      pts.push([cx + Math.cos(t) * rx * k, cy + Math.sin(t) * ry * k]);
    }
    var d = "M" + n(pts[0][0]) + " " + n(pts[0][1]);
    for (var j = 0; j < pts.length - 1; j++) {
      var p0 = pts[j - 1] || pts[j], p1 = pts[j], p2 = pts[j + 1], p3 = pts[j + 2] || p2;
      d += "C" + n(p1[0] + (p2[0] - p0[0]) / 6) + " " + n(p1[1] + (p2[1] - p0[1]) / 6) +
        " " + n(p2[0] - (p3[0] - p1[0]) / 6) + " " + n(p2[1] - (p3[1] - p1[1]) / 6) +
        " " + n(p2[0]) + " " + n(p2[1]);
    }
    return d;
  }

  function underline(w, h, r) {
    var y = PAD + h + 2;
    var d = "M" + n(PAD - 3) + " " + n(y + jit(r, 1)) +
      "C" + n(PAD + w * 0.3) + " " + n(y + jit(r, 3)) +
      " " + n(PAD + w * 0.7) + " " + n(y + jit(r, 3)) +
      " " + n(PAD + w + 4) + " " + n(y - 1 + jit(r, 1.5));
    d += "M" + n(PAD + w * 0.9) + " " + n(y + 5) +
      "C" + n(PAD + w * 0.62) + " " + n(y + 3 + jit(r, 2.5)) +
      " " + n(PAD + w * 0.36) + " " + n(y + 6 + jit(r, 2.5)) +
      " " + n(PAD + w * 0.14) + " " + n(y + 4.5);
    return d;
  }

  var SHAPES = { box: box, circle: circle, underline: underline };

  /* ---------- 画到元素上 ---------- */
  function draw(el, animate) {
    var w = el.offsetWidth, h = el.offsetHeight;
    if (!w || !h) return;
    var st = el._sk;
    st.w = w; st.h = h;
    var kind = el.getAttribute("data-sketch") || "box";
    var shape = SHAPES[kind] || box;
    var extra = kind === "underline" ? 14 : 0;
    var W = w + PAD * 2, H = h + PAD * 2 + extra;

    if (!st.svg) {
      st.svg = document.createElementNS(NS, "svg");
      st.svg.setAttribute("class", "sk-svg");
      st.svg.setAttribute("aria-hidden", "true");
      st.svg.setAttribute("focusable", "false");
      el.insertBefore(st.svg, el.firstChild);
    }
    var svg = st.svg;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.style.left = -PAD + "px";
    svg.style.top = -PAD + "px";

    var d1 = shape(w, h, rng(st.seed));
    var d2 = shape(w, h, rng(st.seed * 7 + 13));
    svg.innerHTML =
      '<g filter="url(#sk-pencil)">' +
      '<rect width="' + W + '" height="' + H + '" fill="none"/>' +
      '<path class="p1" d="' + d1 + '"/>' +
      '<path class="p2" d="' + d2 + '"/>' +
      "</g>";

    if (animate && !reduce.matches) drawIn(svg, st.delay || 0);
  }

  // 像铅笔一样一笔一笔画出来
  function drawIn(svg, delay) {
    var paths = svg.querySelectorAll("path");
    for (var i = 0; i < paths.length; i++) {
      var p = paths[i];
      if (!p.animate || !p.getTotalLength) return;
      var len = p.getTotalLength();
      p.style.strokeDasharray = len + " " + len;
      var anim = p.animate(
        [{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
        { duration: 900 + len * 0.35, delay: delay + i * 140, easing: "cubic-bezier(.45,.1,.25,1)", fill: "backwards" }
      );
      anim.onfinish = (function (path) { return function () { path.style.strokeDasharray = ""; }; })(p);
    }
  }

  var ro = "ResizeObserver" in window
    ? new ResizeObserver(function (entries) {
        entries.forEach(function (e) {
          var el = e.target, st = el._sk;
          if (st && (el.offsetWidth !== st.w || el.offsetHeight !== st.h)) draw(el, false);
        });
      })
    : null;

  function setup(el, index) {
    if (el._sk) return;
    el._sk = {
      seed: (Math.random() * 1e9) | 0,
      delay: el.hasAttribute("data-sketch-delay") ? +el.getAttribute("data-sketch-delay") : Math.min(index, 10) * 70
    };
    draw(el, true);
    if (ro) ro.observe(el);

    var interactive = el.matches("a, button, [data-sketch-hover]");
    if (interactive) {
      el.addEventListener("pointerenter", function () {
        if (!canHover.matches || reduce.matches) return;
        el._sk.seed = (el._sk.seed * 1.37 + 9973) | 0;   // 换一笔，轻轻重描
        draw(el, false);
      });
    }
  }

  /* ---------- 手绘图标（48×48） ---------- */
  var ICONS = {
    folder: [
      "M7.8 14.6c0-1.8 1-2.9 2.8-2.9h8.6l3.6 4.1h14.6c1.8 0 2.9 1.1 2.9 2.9v16.9c0 1.8-1.1 2.9-2.9 2.9H10.7c-1.8 0-2.9-1.1-2.9-2.9V14.6",
      "M8.2 20.6c10.6-.4 21.2-.3 31.9.1"
    ],
    close: [
      "M14.2 14.4c6.3 6.2 12.8 12.6 19.4 19.3",
      "M33.8 14.1c-6.4 6.5-12.9 13-19.6 19.5"
    ],
    person: [
      "M24.6 9.2c4.3.2 7.4 3.6 7.2 7.8-.2 4.3-3.6 7.4-7.9 7.2-4.2-.2-7.3-3.7-7.1-7.9.3-4.1 3.6-7.2 7.6-7.1",
      "M9.8 40.6c.6-7.4 6.4-12.6 14.2-12.7 7.9-.1 13.6 5.1 14.4 12.5"
    ],
    pencil: [
      "M11.2 37.4 32.8 15.6c1.6-1.6 3.6-1.5 5.1 0l.5.5c1.5 1.6 1.4 3.6-.1 5.1L16.8 42.9l-7.4 1.6 1.8-7.1",
      "M29.6 18.8l5.9 5.8",
      "M11.4 37.4l5.3 5.4"
    ],
    "arrow-left": [
      "M38.5 24.6c-9.6-.6-19.3-.4-28.4.2",
      "M19 15.4c-3.4 3.1-6.4 6.2-9.2 9.4 3 3 6.2 6.1 9.6 9.1"
    ],
    "arrow-right": [
      "M9.5 24.2c9.6.5 19.2.3 28.3-.3",
      "M29.2 15c3.4 3.2 6.4 6.3 9.3 9.4-3 3-6.2 6.1-9.6 9.2"
    ],
    link: [
      "M21 13.5h-8.2c-1.7 0-2.8 1.1-2.8 2.8v19.1c0 1.7 1.1 2.8 2.8 2.8h19.3c1.7 0 2.8-1.1 2.8-2.8v-8",
      "M27.4 9.6l11.1.2-.1 11",
      "M38.2 9.9 22.8 25.2"
    ],
    download: [
      "M24.2 9.5c-.2 8.3-.1 16.4.1 23.6",
      "M15.6 25.2c2.9 2.8 5.7 5.6 8.6 8.6 2.8-3 5.6-5.8 8.4-8.7",
      "M10.2 39.4c9.3-.5 18.6-.4 27.8.2"
    ],
    box: [
      "M8.4 17.6 24.2 10.4l15.6 7.3L24 24.9 8.4 17.6",
      "M8.4 17.9v16.4L24 41.6l15.8-7.4V17.8",
      "M24 25v16.4",
      "M8.4 17.6 4.6 23l15.6 7.3 3.8-5.2",
      "M39.8 17.8l3.7 5.3-15.7 7.2-3.8-5.3"
    ],
    /* ---- 以下为本项目新增 ---- */
    // 窗口（托盘菜单「打开主界面」）
    window: [
      "M8.3 11.2c10.5-.4 21-.3 31.4.1.3 8.7.3 17.3 0 25.9-10.5.4-21 .3-31.5 0-.3-8.7-.3-17.4.1-26",
      "M8.6 17.6c10.3-.2 20.6-.2 30.9.1",
      "M12.4 14.3h.4", "M15.9 14.4h.4"
    ],
    // 电源（托盘菜单「退出」）
    power: [
      "M16.6 13.4c-4.2 2.6-7 7.2-6.9 12.4.2 7.8 6.6 14 14.4 13.9 7.7-.1 13.9-6.5 13.8-14.2-.1-5.1-2.8-9.6-6.9-12.1",
      "M24.2 7.8c-.1 5.6-.1 11 .1 16.4"
    ],
    // 网状地球（语言）：歪一点的外圈 + 中轴 + 两条经线弧 + 赤道 + 两条纬线
    globe: [
      "M24.3 7.6c9.2-.1 16.6 7.4 16.4 16.6-.2 9.1-7.6 16.3-16.6 16.2C15 40.3 7.6 32.8 7.7 23.8 7.8 14.8 15.1 7.7 24.6 7.9",
      "M24.1 7.8c-5.2 4.3-7.8 10-7.7 16.3.1 6.3 2.8 11.9 7.9 16.3",
      "M24.4 7.9c5 4.5 7.6 10.1 7.5 16.4-.1 6.2-2.7 11.7-7.8 16",
      "M24.2 7.9c-.2 10.9-.1 21.7.1 32.4",
      "M7.9 24.2c10.9-.3 21.8-.2 32.6.1",
      "M10.6 15.8c8.9 1.6 17.9 1.6 26.9-.2",
      "M10.5 32.4c9-1.7 18-1.7 27 .1"
    ],
    sun: [
      "M24.3 16.8c4.2.1 7.3 3.3 7.1 7.4-.2 4.1-3.5 7.1-7.6 7-4-.2-7-3.5-6.8-7.5.2-3.9 3.4-6.9 7.3-6.9",
      "M24 6.5v4.6", "M24.2 37.2v4.4", "M6.6 24.2h4.5", "M37.1 23.9h4.4",
      "M11.6 11.8l3.2 3.1", "M33.2 33.4l3.1 3", "M36.4 11.5l-3.1 3.2", "M14.9 33.1l-3.2 3.2"
    ],
    chat: [
      "M10.2 12.4c8.9-.9 18.6-.8 27.4.1 1.6.2 2.6 1.3 2.6 2.9l-.2 13.8c0 1.6-1.1 2.7-2.7 2.8-6.1.3-11.9.3-17.6.1l-7.6 6.4.9-6.6c-1-.1-1.9-.2-2.9-.3-1.6-.2-2.5-1.3-2.5-2.9l.1-13.5c0-1.6 1-2.7 2.5-2.8",
      "M16.3 19.6c5.4-.2 10.6-.2 15.6.1", "M16.5 25.4c3.6-.1 7.1-.1 10.3.1"
    ],
    book: [
      "M24 13.2c-4.6-2.6-9.7-3.4-15.4-2.8l.3 25.4c5.6-.6 10.6.2 15.2 2.9",
      "M24 13.2c4.7-2.7 9.8-3.4 15.4-2.7l-.2 25.3c-5.6-.5-10.6.3-15.2 3",
      "M24 13.4v25.1"
    ],
    clock: [
      "M24.5 9.4c8.2.3 14.5 6.9 14.2 14.9-.3 8.2-7 14.4-15.1 14.1-8-.3-14.2-7.1-13.9-15 .3-8 6.9-14.2 14.8-14",
      "M24.2 15.6l-.1 9 6.2 4.1"
    ],
    plug: [
      "M17.4 9.6l.2 8", "M30.5 9.4l-.1 8.2",
      "M12.2 17.6c7.8-.4 15.7-.4 23.6.1l-.6 7.4c-.6 5.6-5 9.1-11 9-5.8-.1-10.2-3.6-10.9-9.1l-1.1-7.4",
      "M24 34.2l.1 5.4c0 1.6 1.1 2.6 2.7 2.6h4.6"
    ],
    gear: [
      "M24.2 18.6c3 .1 5.4 2.6 5.3 5.6-.1 3-2.6 5.4-5.7 5.2-2.9-.1-5.2-2.6-5.1-5.6.1-2.9 2.5-5.3 5.5-5.2",
      "M21.6 8.6l4.9-.1.9 4.6 3.4 1.5 3.9-2.7 3.5 3.5-2.7 3.9 1.5 3.4 4.6.9v4.9l-4.6.9-1.5 3.4 2.7 3.9-3.5 3.5-3.9-2.7-3.4 1.5-.9 4.6h-4.9l-.9-4.6-3.4-1.5-3.9 2.7-3.5-3.5 2.7-3.9-1.5-3.4-4.6-.9.1-4.9 4.6-.9 1.4-3.4-2.7-3.9 3.5-3.5 3.9 2.7 3.4-1.5.9-4.6"
    ],
    search: [
      "M20.6 10.4c5.6.2 10 4.8 9.8 10.3-.2 5.6-4.8 9.9-10.4 9.7-5.5-.2-9.8-4.9-9.6-10.4.2-5.5 4.7-9.7 10.2-9.6",
      "M28.4 28.7l9.6 9.7"
    ],
    check: ["M10.6 25.4c3.2 2.8 6 5.8 8.6 9 5.3-8.3 11.4-15.7 18.4-22.2"],
    undo: [
      "M17.8 13.6c-3.6 3-6.6 5.9-9.2 8.9 3.2 2.7 6.4 5.6 9.5 8.6",
      "M9 22.6c8.6-.4 15.6-.3 21 .3 5.8.7 9.4 4.4 9.1 9.7-.3 5-4 8-9.4 8.3"
    ],
    send: ["M8.6 22.8 39.8 9.4 30.2 39.6l-7.8-11.4L8.6 22.8", "M22.4 28.2 39.6 9.6"],
    pause: ["M18.2 12.6l.2 23", "M29.6 12.4l-.1 23.2"],
    play: ["M15.4 11.2c7.9 4.1 15.4 8.4 22.4 13-7 4.5-14.4 8.9-22.3 13.3l-.1-26.3"],
    spark: [
      "M24.1 8.6c1.1 6.6 3.6 9.6 10.6 11.1-6.9 1.4-9.5 4.4-10.6 11.2-1.2-6.8-3.8-9.8-10.7-11.2 6.9-1.5 9.6-4.5 10.7-11.1",
      "M36.6 30.2c.4 2.6 1.4 3.6 4.1 4.2-2.7.5-3.7 1.6-4.1 4.2-.5-2.6-1.5-3.7-4.2-4.2 2.7-.6 3.7-1.6 4.2-4.2"
    ],
    palette: [
      "M24.2 8.8c-8.9-.1-15.8 6.7-15.8 15.3 0 8.5 6.7 15.4 14.8 15.4 1.9 0 2.9-1.1 2.9-2.6 0-1.7-1.3-2.3-1.3-3.9 0-1.8 1.4-3 3.2-3h3.7c4.4 0 7.9-3.4 7.9-7.7-.1-7.6-6.6-13.4-15.4-13.5",
      "M16.2 22.4c.1-1.1 1.9-1.1 2 0 0 1.2-2 1.2-2 0",
      "M21.4 15.8c.1-1.1 1.9-1.1 2 0 0 1.2-2 1.2-2 0",
      "M29.2 16.4c.1-1.1 1.9-1.1 2 0 0 1.2-2 1.2-2 0"
    ],
    heart: ["M24 39.4c-8.3-5.8-14.3-11.4-14.6-18.2-.2-5 3.3-8.6 7.6-8.6 3.2 0 5.6 1.9 7 4.6 1.4-2.8 3.9-4.7 7.1-4.6 4.4.1 7.7 3.8 7.4 8.8-.4 6.8-6.4 12.3-14.5 18"],
    "side-close": [
      "M9.6 10.4c9.6-.4 19.3-.3 28.8.2l-.3 27.2c-9.6.4-19.2.4-28.7 0l.2-27.4",
      "M19.2 10.8l-.2 26.8",
      "M31.4 19.2c-2.2 1.6-4.2 3.2-5.9 4.9 1.8 1.6 3.8 3.3 5.9 4.9"
    ],
    "side-open": [
      "M9.6 10.4c9.6-.4 19.3-.3 28.8.2l-.3 27.2c-9.6.4-19.2.4-28.7 0l.2-27.4",
      "M19.2 10.8l-.2 26.8",
      "M26.2 19.2c2.2 1.6 4.2 3.2 5.9 4.9-1.8 1.6-3.8 3.3-5.9 4.9"
    ],
    image: [
      "M8.8 11.2c10.1-.5 20.3-.4 30.4.2l-.3 25.6c-10.1.5-20.2.4-30.2-.1l.1-25.7",
      "M9.4 31.6c4.1-4.4 7.9-8.2 11.3-11.4 3.1 3.3 6.2 6.9 9.2 10.6 2.1-2 4-3.8 6-5.4 1.2 1.2 2.4 2.5 3.4 3.8",
      "M31.6 15.8c1.5.1 2.6 1.3 2.5 2.8-.1 1.4-1.3 2.5-2.7 2.4-1.5-.1-2.5-1.3-2.4-2.8.1-1.4 1.2-2.4 2.6-2.4"
    ],
    lock: [
      "M13.4 22.4c7.2-.3 14.4-.3 21.4.1l-.3 16.8c-7 .4-14 .4-21 0l-.1-16.9",
      "M17.6 22.2v-5.4c.1-4 2.8-6.8 6.6-6.8 3.7.1 6.3 2.9 6.3 6.9l-.1 5.3"
    ]
  };

  function icon(name) {
    var p = ICONS[name];
    if (!p) return "";
    var a = "", b = "";
    for (var i = 0; i < p.length; i++) {
      a += '<path class="p1" d="' + p[i] + '"/>';
      b += '<path class="p2" d="' + p[i] + '"/>';
    }
    return '<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">' +
      '<g filter="url(#sk-pencil)"><rect x="-4" y="-4" width="56" height="56" fill="none"/>' +
      a + '<g transform="translate(.8 .6)">' + b + "</g></g></svg>";
  }

  function renderIcons(root) {
    var list = root.querySelectorAll("[data-icon]");
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (!el.firstChild) el.innerHTML = icon(el.getAttribute("data-icon"));
    }
  }

  /* ---------- 入口 ---------- */
  function init(root) {
    root = root || document;
    ensureDefs();
    renderIcons(root);
    // 液态玻璃主题（决定 0013）不画铅笔框；换回铅笔主题时界面会重画一遍，那时再画
    if (document.documentElement.getAttribute("data-skin") === "glass") return;

    // 等字体就位再画框，免得框画好后字体一换又变形；最多等 1.2 秒
    var fontsReady = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
    var timeout = new Promise(function (res) { setTimeout(res, 1200); });
    Promise.race([fontsReady, timeout]).then(function () {
      var els = root.querySelectorAll("[data-sketch]");
      for (var i = 0; i < els.length; i++) setup(els[i], i);
    });
  }

  window.Sketch = { init: init, icon: icon };
})();
