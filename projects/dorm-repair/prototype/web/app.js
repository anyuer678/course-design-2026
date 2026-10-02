/* B16 原型前端。
 *
 * 三条纪律：
 *  1. 不用 innerHTML（只用 textContent / createElement）：工单描述是用户写的字符串，
 *     当标记解析就是存储型 XSS 的入口。
 *  2. 不自己推业务规则：按钮来自服务端返回的 attemptable / required_inputs，
 *     而那份数据来自 B15 的模型。规则改了，这里不用跟着改。
 *  3. 四种界面状态都得有明确呈现：正常、加载、空、错误。
 *     空状态还要说清"是没有还是没加载出来"，否则报错会被看成没数据。
 */
const state = { role: "STUDENT", actor: "stu-1", meta: null, orders: [], detail: null, pending: null };

const $ = (id) => document.getElementById(id);
const list = (path, params) => {
  const q = new URLSearchParams({ role: state.role, actor: state.actor, ...(params || {}) });
  return request(`${path}?${q}`);
};

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (err) {
    throw new Error(`服务端返回的不是 JSON（HTTP ${response.status}）`);
  }
  if (!response.ok) {
    const error = new Error((payload && payload.error) || `HTTP ${response.status}`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function post(url, body) {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function say(id, text, kind) {
  const node = $(id);
  node.textContent = text || "";
  node.dataset.state = kind || "";
}

function setBusy(on, where, text) {
  const node = $(where);
  node.textContent = on ? text : (text || "");
  if (node.hidden !== undefined) node.hidden = false;
  document.body.dataset.busy = on ? "1" : "0";
}

/* ---------------------------------------------------------------- 初始化 */

async function boot() {
  setBusy(true, "load-state", "正在读取元数据…");
  try {
    state.meta = await request("/api/meta");
  } catch (err) {
    showError("error-state", `原型起不来：${err.message}`);
    setBusy(false, "load-state", "");
    return;
  }
  fill("category", state.meta.categories, "请选择分类");
  fill("priority", Object.keys(state.meta.priorities).map((p) => ({
    value: p, label: `${p}（${state.meta.priorities[p]} 小时内响应）`,
  })), "请选择紧急程度");
  fill("f-state", state.meta.states, "全部");
  fill("f-category", state.meta.categories, "全部");
  syncActors();
  setBusy(false, "load-state", "");
  await loadOrders();
}

function fill(id, values, placeholder) {
  const select = $(id);
  select.replaceChildren();
  if (placeholder) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
  }
  for (const item of values) {
    const option = document.createElement("option");
    const entry = typeof item === "string" ? { value: item, label: item } : item;
    option.value = entry.value;
    option.textContent = entry.label;
    select.appendChild(option);
  }
}

function syncActors() {
  fill("actor", state.meta.roles[state.role]);
  state.actor = state.meta.roles[state.role][0];
  $("actor").value = state.actor;
  say("identity-state", `当前以 ${state.role} 身份查看：${state.actor}`);
}

/* ---------------------------------------------------------------- 列表与四种状态 */

function showError(id, text) {
  const node = $(id);
  node.textContent = text;
  node.hidden = !text;
}

async function loadOrders(filters) {
  setBusy(true, "load-state", "正在加载工单…");
  showError("error-state", "");
  $("empty").hidden = true;
  $("orders").hidden = true;
  let data;
  try {
    data = await list("/api/orders", filters || currentFilters());
  } catch (err) {
    setBusy(false, "load-state", "");
    $("orders").hidden = true;
    showError("error-state", `加载失败：${err.message}　这不是"没有工单"，是请求没成功。`);
    return;
  }
  state.orders = data.orders;
  setBusy(false, "load-state", `${data.count} 张工单可见 · 原型时钟 ${new Date(data.now * 1000).toLocaleTimeString()}`);
  $("empty").hidden = !data.empty;
  $("orders").hidden = data.empty;
  renderRows();
}

function currentFilters() {
  const out = {};
  if ($("f-state").value) out.state = $("f-state").value;
  if ($("f-category").value) out.category = $("f-category").value;
  if ($("f-room").value.trim()) out.room = $("f-room").value.trim();
  if ($("f-overdue").checked) out.overdue = "1";
  return out;
}

function renderRows() {
  const tbody = document.querySelector("#orders tbody");
  tbody.replaceChildren();
  for (const order of state.orders) {
    const row = document.createElement("tr");
    row.append(
      cell(order.id), cell(order.room), cell(order.category),
      cell(`${order.priority} / ${order.sla_hours}h`),
      cell(order.state, order.overdue ? "badge overdue" : "badge"),
      cell(order.sla_due_at ? new Date(order.sla_due_at * 1000).toLocaleString() : "未提交"),
      cell(order.description),
    );
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = "打开";
    open.addEventListener("click", () => openDetail(order.id));
    const linkCell = document.createElement("td");
    linkCell.append(open);
    row.append(linkCell);
    tbody.append(row);
  }
}

function cell(text, className) {
  const td = document.createElement("td");
  const node = className ? document.createElement("span") : td;
  node.textContent = text;
  if (className) {
    node.className = className;
    td.append(node);
  }
  return td;
}

/* ---------------------------------------------------------------- 详情与动作 */

async function openDetail(id) {
  $("detail").hidden = false;
  $("detail-h").textContent = `工单详情 · ${id}`;
  say("detail-status", "正在读取…");
  let order;
  try {
    order = await list(`/api/orders/${id}`);
  } catch (err) {
    say("detail-status", `读不到：${err.message}`, "bad");
    return;
  }
  state.detail = order;
  renderDetail();
  $("detail-h").focus();
}

function renderDetail() {
  const order = state.detail;
  const dl = $("detail-fields");
  dl.replaceChildren();
  const rows = [
    ["编号", order.id], ["状态", order.state], ["宿舍", order.room],
    ["分类", order.category], ["紧急程度", `${order.priority}（${order.sla_hours} 小时）`],
    ["描述", order.description], ["联系方式", order.contact],
    ["报修人", order.reporter], ["当前维修员", order.assignee || "（无）"],
    ["提交时刻", order.submitted_at ? new Date(order.submitted_at * 1000).toLocaleString() : "未提交"],
    ["时限到期", order.sla_due_at ? new Date(order.sla_due_at * 1000).toLocaleString() : "—"],
    ["是否逾期", order.overdue ? "已逾期" : "未逾期"],
  ];
  for (const [key, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = key;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  }
  renderActions();
  const ol = $("detail-history");
  ol.replaceChildren();
  for (const change of order.history) {
    const li = document.createElement("li");
    li.textContent = `${new Date(change.at * 1000).toLocaleTimeString()}　` +
      `${change.from} → ${change.to}　${change.action}　by ${change.role}/${change.actor}` +
      (change.reason ? `　理由：${change.reason}` : "");
    ol.append(li);
  }
  if (!order.history.length) {
    const li = document.createElement("li");
    li.textContent = "还没有处理记录。";
    ol.append(li);
  }
  say("detail-status", "");
}

function renderActions() {
  const box = $("detail-actions");
  box.replaceChildren();
  const names = {
    submit: "提交报修", assign: "派单", reassign: "改派", return_pool: "退回公共池",
    accept: "接单", decline: "拒单", resolve: "标记完工", confirm: "验收通过",
    reject_check: "验收不通过", force_close: "强制关闭", cancel: "取消工单", escalate: "升级退回",
  };
  for (const action of state.detail.attemptable) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = names[action] || action;
    button.dataset.action = action;
    const need = state.detail.required_inputs[action] || [];
    if (need.length) button.setAttribute("aria-describedby", "action-hint");
    button.addEventListener("click", () => prepareAction(action, need));
    box.append(button);
  }
  if (!state.detail.attemptable.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = state.detail.state === "CLOSED" || state.detail.state === "CANCELLED"
      ? "这张单已经是终态，任何人都不能再对它操作（BR-02）。"
      : `以当前身份（${state.role} / ${state.actor}）没有可执行的动作。这不是故障：权限矩阵就是这么规定的。`;
    box.append(p);
  }
}

function prepareAction(action, need) {
  state.pending = action;
  for (const key of ["reason", "note", "assignee"]) {
    $(`${key}-label`).hidden = !need.includes(key);
    $(key).value = "";
  }
  $("action-hint").textContent = need.length
    ? `「${action}」需要先填写：${need.join("、")}（BR-05 / 第 3 节前置条件）`
    : `即将执行「${action}」。这一步会写进处理记录，确认后才提交。`;
  $("action-form").hidden = false;
  say("detail-status", `待确认：${action}`);
  const first = need.length ? $(need[0]) : $("reason");
  if (first && first.closest("label") && !first.closest("label").hidden) first.focus();
  else $("action-form").querySelector("button[type=submit]").focus();
}

async function submitAction(action, extra) {
  const body = { action, ...extra };
  say("detail-status", `正在执行 ${action}…`);
  try {
    state.detail = await list(`/api/orders/${state.detail.id}/act`, body);
  } catch (err) {
    // 服务端拒绝就照实显示，不粉饰成"操作成功"
    say("detail-status", `被拒绝：${err.message}${err.payload && err.payload.code ? `（${err.payload.code}）` : ""}`, "bad");
    if (err.payload && err.payload.attemptable) {
      state.detail.attemptable = err.payload.attemptable;
      renderActions();
    }
    return;
  }
  $("action-form").hidden = true;
  say("detail-status", `已执行 ${action}`, "good");
  renderDetail();
  await loadOrders();
}

/* ---------------------------------------------------------------- 建单与就地报错 */

function clearFieldErrors() {
  for (const name of ["room", "category", "priority", "description", "contact"]) {
    const node = $(`${name}-err`);
    node.textContent = "";
    node.hidden = true;
    $(name).setAttribute("aria-invalid", "false");
  }
  showError("create-summary", "");
}

function renderFieldErrors(fields) {
  for (const item of fields) {
    const node = $(`${item.field}-err`);
    if (!node) continue;
    node.textContent = item.reason;
    node.hidden = false;
    $(item.field).setAttribute("aria-invalid", "true");
  }
  const summary = $("create-summary");
  summary.textContent = `有 ${fields.length} 处需要修改，已一次性列出（FR-03）：` +
    fields.map((f) => `${f.field}`).join("、");
  summary.hidden = false;
  const first = $(fields[0].field);
  if (first) first.focus();
}

/* ---------------------------------------------------------------- 事件绑定 */

$("identity-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.role = $("role").value;
  state.actor = $("actor").value;
  say("identity-state", `当前以 ${state.role} 身份查看：${state.actor}`);
  loadOrders();
});

$("role").addEventListener("change", () => {
  syncActors();
});

$("filter-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadOrders();
});

$("reset").addEventListener("click", () => {
  $("filter-form").reset();
  loadOrders();
});

$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFieldErrors();
  const action = event.submitter ? event.submitter.value : "draft";
  const body = {
    room: $("room").value,
    category: $("category").value,
    priority: $("priority").value,
    description: $("description").value,
    contact: $("contact").value,
    role: state.role,
    actor: state.actor,
    action,
  };
  say("create-status", "提交中…", "busy");
  let created;
  try {
    created = await post("/api/orders", body);
  } catch (err) {
    const payload = err.payload || {};
    if (payload.code === "INVALID_FIELDS") {
      say("create-status", "未提交：字段有问题，见下方逐项说明", "bad");
      renderFieldErrors(payload.fields || []);
    } else {
      say("create-status", `未提交：${err.message}`, "bad");
    }
    return;
  }
  say("create-status", `已${action === "submit" ? "提交" : "存为草稿"}：${created.id}（${created.state}）`, "good");
  $("create-form").reset();
  await loadOrders();
  openDetail(created.id);
});

$("action-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitAction(state.pending, {
    reason: $("reason").value, note: $("note").value, assignee: $("assignee").value,
    role: state.role, actor: state.actor,
  });
});

$("cancel-action").addEventListener("click", () => {
  $("action-form").hidden = true;
  say("detail-status", "已取消本次操作，工单没有变化");
});

$("close-detail").addEventListener("click", () => {
  $("detail").hidden = true;
  state.detail = null;
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("detail").hidden) {
    $("detail").hidden = true;
    state.detail = null;
  }
});

boot();
