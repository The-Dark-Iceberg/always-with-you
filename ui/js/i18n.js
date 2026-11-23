/* 多语言（界面这一侧）。中文是原文；其他语言的翻译在 ui/i18n/<代码>.json（和后台共用同一份）。
   用法：
     T("保存")                       -> 当前语言的文字
     T("现在由 {name} 回答", {name: "DeepSeek"})
     HTML 里写死的文字：<span data-i18n="陪着你">陪着你</span>
                       title / aria-label 用 data-i18n-title / data-i18n-aria
   加一种语言：在 LANGS 里加一行，再放一个 ui/i18n/<代码>.json，后台 src/awy/i18n.py 的 LANGS 也加一行。 */
(function () {
  "use strict";
  var LANGS = [
    { code: "zh", name: "简体中文", locale: "zh-CN" },
    { code: "en", name: "English", locale: "en-US" }
  ];
  var lang = "zh", dict = {};

  function known(code) { return LANGS.some(function (l) { return l.code === code; }); }

  function T(s, vars) {
    var out = (lang !== "zh" && dict[s]) || s;
    if (vars) out = out.replace(/\{(\w+)\}/g, function (m, k) { return Object.prototype.hasOwnProperty.call(vars, k) ? vars[k] : m; });
    return out;
  }

  function load(code) {
    if (!known(code)) code = "zh";
    if (code === "zh") { lang = "zh"; dict = {}; return Promise.resolve(); }
    return fetch("i18n/" + code + ".json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { lang = code; dict = d; })
      .catch(function () { lang = "zh"; dict = {}; });
  }

  // 把 HTML 里写死的文字换成当前语言（原文放在 data-i18n* 属性里，来回切换不会丢）
  function apply(root) {
    root = root || document;
    root.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = T(el.getAttribute("data-i18n")); });
    root.querySelectorAll("[data-i18n-title]").forEach(function (el) { el.title = T(el.getAttribute("data-i18n-title")); });
    root.querySelectorAll("[data-i18n-aria]").forEach(function (el) { el.setAttribute("aria-label", T(el.getAttribute("data-i18n-aria"))); });
    document.documentElement.lang = locale();
    document.title = T("一个时刻陪着你的AI");
  }

  function locale() { return LANGS.filter(function (l) { return l.code === lang; })[0].locale; }

  // 静态预览（没有后台）时的默认语言：跟浏览器
  function guess() { return /^zh/i.test(navigator.language || "") ? "zh" : "en"; }

  window.T = T;
  window.I18N = {
    LANGS: LANGS, T: T, load: load, apply: apply, guess: guess, known: known,
    get lang() { return lang; },
    get locale() { return locale(); }
  };
})();
