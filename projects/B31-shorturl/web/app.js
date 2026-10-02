/* B31 前端：原生 DOM，不引框架，也完全不用 innerHTML。
 *
 * 短链服务显示的是"用户提交的字符串"，这是存储型 XSS 的经典入口。
 * 只用 textContent 写文本、只用 createElement 建节点，浏览器就不会把
 * 用户数据当标记解析——不靠转义函数，也就不靠人记得调用它。
 *
 * 前端校验只是为了少跑一趟网络，不是防线：服务端会再校验一次（b31/urls.py）。
 */
const form = document.getElementById("create-form");
const urlInput = document.getElementById("url");
const aliasInput = document.getElementById("alias");
const statusLine = document.getElementById("form-status");
const resultBox = document.getElementById("result");
const shortLink = document.getElementById("short-link");
const resultTarget = document.getElementById("result-target");
const copyButton = document.getElementById("copy");
const refreshButton = document.getElementById("refresh");
const tbody = document.querySelector("#links tbody");
const totals = document.getElementById("totals");
const emptyLine = document.getElementById("empty");

function setStatus(text, kind) {
  statusLine.textContent = text;
  statusLine.dataset.state = kind || "";
}

async function jsonOrNull(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`服务端返回的不是 JSON（HTTP ${response.status}）`);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("目标地址不能为空。", "bad");
    urlInput.focus();
    return;
  }
  const payload = { url };
  const alias = aliasInput.value.trim();
  if (alias) payload.alias = alias;

  setStatus("提交中…", "busy");
  let response;
  try {
    response = await fetch("/api/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    setStatus("请求发不出去，服务可能已经退出。", "bad");
    return;
  }
  let data;
  try {
    data = await jsonOrNull(response);
  } catch (err) {
    setStatus(err.message, "bad");
    return;
  }
  if (!response.ok) {
    setStatus(`HTTP ${response.status}：${(data && data.error) || "创建失败"}`, "bad");
    resultBox.hidden = true;
    return;
  }
  showResult(data);
  setStatus(`已创建，命中数会从 0 开始。`, "good");
  await loadLinks();
});

function showResult(data) {
  // short_url 由服务端的 Host 头部拼出来：只接受 http(s) 开头，别的形态一律不当链接用
  if (typeof data.short_url === "string" && /^https?:\/\//i.test(data.short_url)) {
    shortLink.href = data.short_url;
  } else {
    shortLink.removeAttribute("href");
  }
  shortLink.textContent = data.short_url;
  resultTarget.textContent = data.target;
  resultBox.hidden = false;
}

copyButton.addEventListener("click", async () => {
  const text = shortLink.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    setStatus("已复制到剪贴板。", "good");
  } catch (err) {
    setStatus("浏览器不允许直接复制，请手动选中链接。", "bad");
  }
});

refreshButton.addEventListener("click", () => loadLinks());

async function loadLinks() {
  let response;
  try {
    response = await fetch("/api/links?limit=20");
  } catch (err) {
    setStatus("读不到列表：服务可能已退出。", "bad");
    return;
  }
  if (!response.ok) {
    setStatus(`读列表失败：HTTP ${response.status}`, "bad");
    return;
  }
  const data = await response.json();
  renderRows(data.links);
  totals.textContent = `共 ${data.stats.links} 条 · 累计命中 ${data.stats.total_hits}`;
}

function renderRows(links) {
  tbody.replaceChildren();
  emptyLine.hidden = links.length > 0;
  for (const link of links) {
    const row = document.createElement("tr");
    const codeCell = document.createElement("td");
    const anchor = document.createElement("a");
    anchor.href = `/l/${encodeURIComponent(link.code)}`;
    anchor.target = "_blank";
    anchor.rel = "noopener";
    anchor.textContent = link.code;
    codeCell.appendChild(anchor);
    row.appendChild(codeCell);
    row.appendChild(cell(link.target));
    row.appendChild(cell(String(link.hits)));
    row.appendChild(cell(new Date(link.created_at * 1000).toLocaleString()));
    tbody.appendChild(row);
  }
}

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

loadLinks();
