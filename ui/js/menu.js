/* 托盘右键菜单（menu.html）。窗口由 desktop.py 在鼠标位置弹出；点了某一项或按 Esc 就收起。
   点到菜单外面时的收起由 desktop.py 负责（它会发现菜单不再是最前面的窗口）。 */
(function () {
  "use strict";
  var A = window.AWY, I = window.I18N, T = window.T, collecting = true;

  function hide() { return A.post("/api/menu/hide").catch(function () {}); }

  function refresh() {
    var get = A.live ? A.get("/api/status") : Promise.resolve({ language: I.guess(), collecting: true, nextOrganize: "23:30" });   // 静态预览用假状态
    return get.then(function (s) {
      return I.load(s.language).then(function () {
        I.apply();
        document.title = "AWY-tray-menu";               // desktop.py 靠这个标题找到窗口，不能被翻译掉
        collecting = s.collecting !== false;
        document.getElementById("tm-dot").className = "dot" + (collecting ? "" : " off");
        document.getElementById("tm-status").textContent = collecting ? T("正在记录") : T("已暂停记录");
        document.getElementById("tm-next").textContent = T("下次整理 {time}", { time: s.nextOrganize || "—" });
        document.getElementById("tm-pause").textContent = collecting ? T("暂停记录") : T("继续记录");
        var ico = document.getElementById("tm-pause-ico");
        ico.setAttribute("data-icon", collecting ? "pause" : "play"); ico.innerHTML = "";
        Sketch.init(document.body);
      });
    }).catch(function () {});
  }
  window.awyMenuOpen = refresh;   // desktop.py 每次弹出菜单时调用

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-cmd]");
    if (!b) return;
    var cmd = b.getAttribute("data-cmd");
    hide().then(function () {
      if (cmd === "show") return A.post("/api/show");
      if (cmd === "pause") return A.post("/api/settings", { collect_enabled: !collecting });
      if (cmd === "organize") return A.post("/api/organize");
      if (cmd === "quit") return A.post("/api/quit");
    }).catch(function () {});
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") hide();
    var items = Array.prototype.slice.call(document.querySelectorAll(".tm-item")), i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { items[(i + 1) % items.length].focus(); e.preventDefault(); }
    if (e.key === "ArrowUp") { items[(i - 1 + items.length) % items.length].focus(); e.preventDefault(); }
  });
  refresh();
})();
