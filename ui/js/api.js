/* 和后台说话的一层。
   - 由我们的程序打开时，地址里带着钥匙（?t=...），走真实接口 /api/...
   - 直接用静态网页预览时（没有钥匙），走 mock-data.js 里的假数据，方便单独调界面。 */
(function () {
  "use strict";
  var T = window.T;
  var token = new URLSearchParams(location.search).get("t");
  try {
    if (token) sessionStorage.setItem("awy.t", token); else token = sessionStorage.getItem("awy.t");
  } catch (e) { /* 存不了就只用这一次 */ }
  if (location.search) history.replaceState(null, "", location.pathname + location.hash);  // 钥匙不留在地址栏
  var live = !!token;

  function req(method, path, body) {
    return fetch(path, {
      method: method,
      headers: { "X-AWY-Token": token || "", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || T("出错了（{code}）", { code: r.status }));
        return j;
      });
    });
  }

  // 聊天：一行一个 JSON 事件，边收边交给 onEvent
  function chat(text, onEvent) {
    return fetch("/api/chat", {
      method: "POST", headers: { "X-AWY-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    }).then(function (r) {
      if (!r.ok || !r.body) throw new Error(T("发送失败（{code}）", { code: r.status }));
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          buf += dec.decode(res.value, { stream: true });
          var lines = buf.split("\n"); buf = lines.pop();
          lines.forEach(function (ln) { if (ln.trim()) { try { onEvent(JSON.parse(ln)); } catch (e) {} } });
          return pump();
        });
      }
      return pump();
    });
  }

  window.AWY = {
    live: live,
    get: function (p) { return req("GET", p); },
    post: function (p, b) { return req("POST", p, b || {}); },
    del: function (p) { return req("DELETE", p); },
    chat: chat
  };
})();
