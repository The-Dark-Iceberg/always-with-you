/*
 * 动态背景：纸上几道淡淡的铅笔弧线，像等高线一样非常缓慢地起伏。
 *
 * - 每秒最多画 30 帧，切到别的标签页时自动暂停，几乎不耗电。
 * - 系统开了「减少动态效果」时只画一张静止的。
 * - 想调整：改下面 CONFIG 里的数字。
 */
(function () {
  "use strict";

  var CONFIG = {
    linesDesktop: 9,     // 电脑上的线条数
    linesPhone: 6,       // 手机上的线条数
    speed: 1,            // 起伏速度，0.5 更慢，2 更快
    strength: 1,         // 线条深浅，0.6 更淡，1.4 更深
    fps: 30
  };

  var canvas = document.createElement("canvas");
  canvas.id = "paper-bg";
  canvas.setAttribute("aria-hidden", "true");
  document.body.insertBefore(canvas, document.body.firstChild);
  var ctx = canvas.getContext("2d");
  if (!ctx) return;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var dark = window.matchMedia("(prefers-color-scheme: dark)");

  var W = 0, H = 0, lines = [], ink = "42,41,38", raf = 0, last = 0;
  var start = performance.now();

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function readInk() {
    var v = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim();
    var m = /^#?([0-9a-f]{6})$/i.exec(v);
    if (m) {
      var x = parseInt(m[1], 16);
      ink = (x >> 16 & 255) + "," + (x >> 8 & 255) + "," + (x & 255);
    }
  }

  function build() {
    var r = rng(20261119);               // 固定种子：窗口大小变化时线条不会乱跳
    var count = W < 640 ? CONFIG.linesPhone : CONFIG.linesDesktop;
    var dir = function () { return r() < 0.5 ? -1 : 1; };
    lines = [];
    for (var i = 0; i < count; i++) {
      var full = r() < 0.45;
      lines.push({
        base: (0.07 + 0.86 * (i + 0.5) / count + (r() - 0.5) * 0.05),
        amp: 14 + r() * 26,
        k1: 0.0016 + r() * 0.002,
        k2: 0.004 + r() * 0.004,
        p1: r() * Math.PI * 2,
        p2: r() * Math.PI * 2,
        s1: (0.00006 + r() * 0.00005) * dir(),
        s2: (0.00004 + r() * 0.00004) * dir(),
        tilt: (r() - 0.5) * 0.08,
        x0: full ? -0.05 : r() * 0.3 - 0.05,
        x1: full ? 1.05 : 0.65 + r() * 0.4,
        alpha: 0.08 + r() * 0.07,
        gap: 1 + r() * 1.6
      });
    }
  }

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth || window.innerWidth;
    H = canvas.clientHeight || window.innerHeight;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    build();
  }

  function trace(L, t, x0, x1, dy) {
    var baseY = L.base * H;
    ctx.beginPath();
    for (var x = x0; x <= x1; x += 6) {
      var y = baseY + dy +
        L.tilt * (x - W / 2) +
        L.amp * Math.sin(L.k1 * x + L.p1 + t * L.s1 * CONFIG.speed) +
        L.amp * 0.45 * Math.sin(L.k2 * x + L.p2 + t * L.s2 * CONFIG.speed) +
        1.1 * Math.sin(x * 0.09 + L.p2);         // 手的细微抖动
      if (x === x0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
  }

  function frame(t) {
    ctx.clearRect(0, 0, W, H);
    var k = (dark.matches ? 0.85 : 1) * CONFIG.strength;
    for (var i = 0; i < lines.length; i++) {
      var L = lines[i];
      var x0 = L.x0 * W, x1 = L.x1 * W;
      var a = L.alpha * k;

      // 两头淡出，像铅笔起笔收笔
      var g = ctx.createLinearGradient(x0, 0, x1, 0);
      g.addColorStop(0, "rgba(" + ink + ",0)");
      g.addColorStop(0.15, "rgba(" + ink + "," + a + ")");
      g.addColorStop(0.85, "rgba(" + ink + "," + a + ")");
      g.addColorStop(1, "rgba(" + ink + ",0)");
      ctx.strokeStyle = g;

      ctx.lineWidth = 1;
      trace(L, t, x0, x1, 0);
      ctx.stroke();

      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 0.7;
      trace(L, t, x0, x1, L.gap);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }

  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (now - last < 1000 / CONFIG.fps) return;
    if (document.documentElement.getAttribute("data-skin") === "glass") return;   // 液态玻璃主题时纸张背景藏起来了，不用画
    last = now;
    frame(now - start);
  }

  function play() {
    cancelAnimationFrame(raf);
    raf = 0;
    if (reduce.matches || document.hidden) {
      frame(0);
      return;
    }
    raf = requestAnimationFrame(loop);
  }

  var resizeTimer = 0;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { resize(); frame(performance.now() - start); }, 120);
  });
  document.addEventListener("visibilitychange", play);
  function onScheme() { readInk(); frame(performance.now() - start); }
  if (dark.addEventListener) dark.addEventListener("change", onScheme);
  if (reduce.addEventListener) reduce.addEventListener("change", play);

  readInk();
  resize();
  play();
})();
