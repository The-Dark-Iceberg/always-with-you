/* Always With You · 记录助手（Chrome / Edge 扩展，决定 0011）

   只做一件事：告诉本机的「一个时刻陪着你的AI」你现在在看哪个网页。
   - 只看「当前窗口、当前标签页」的网址和标题；浏览器不在最前面时报告「没在看」。
   - 只报 https:// 开头的网页；http（不加密）、浏览器自己的页面、本地文件一律不报。
   - 不读网页内容、不读输入框、不读 Cookie；不在无痕窗口里运行（manifest 里 incognito: not_allowed）。
   - 只发给本机 127.0.0.1:47823；程序没开就什么也不发，也不存。
   - 网址参数（? 后面的部分）由本机程序去掉，搜索词在去掉之前提取出来（见 src/awy/browser.py）。
*/
const ENDPOINT = "http://127.0.0.1:47823/browser/page";
let lastSent = "";

async function currentPage() {
  let win = null;
  try { win = await chrome.windows.getLastFocused(); } catch (e) { return { off: true }; }
  if (!win || !win.focused || win.incognito) return { off: true };
  const [tab] = await chrome.tabs.query({ active: true, windowId: win.id });
  if (!tab || tab.incognito || !tab.url || !tab.url.startsWith("https://")) return { off: true };
  return { url: tab.url, title: tab.title || "" };
}

async function report(force) {
  let body;
  try { body = JSON.stringify(await currentPage()); } catch (e) { return; }
  if (!force && body === lastSent) return;
  try {
    // text/plain 是「简单请求」，不会触发跨域预检；程序那边按 JSON 解析
    await fetch(ENDPOINT, { method: "POST", headers: { "Content-Type": "text/plain" }, body });
    lastSent = body;
  } catch (e) {
    lastSent = "";   // 程序没开：什么也不存，下次再说
  }
}

chrome.tabs.onActivated.addListener(() => report(false));
chrome.tabs.onUpdated.addListener((id, info) => { if (info.status === "complete" || info.title) report(false); });
chrome.windows.onFocusChanged.addListener(() => report(false));
// 每分钟重报一次当前状态：程序重启过也能接上（程序那边会去重）
chrome.alarms.create("awy-tick", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(() => report(true));
chrome.runtime.onStartup.addListener(() => report(true));
chrome.runtime.onInstalled.addListener(() => report(true));
