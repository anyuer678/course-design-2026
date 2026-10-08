/* Studio 门户脚本：只做渲染与调用，判定全在服务端。 */
(function () {
  "use strict";
  var busy = {};
  var user = null;
  var last = [];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function $(id) { return document.getElementById(id); }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    });
  }

  // ------------------------------------------------ 认证
  function renderAuth() {
    $("auth-guest").hidden = !!user;
    $("auth-user").hidden = !user;
    // hidden 属性压不过内联 display:flex——display 一并切换
    // （2026-10-07 走查：登录后表单曾与"已登录"并排显示）
    $("auth-guest").style.display = user ? "none" : "flex";
    $("auth-user").style.display = user ? "flex" : "none";
    if (user) $("whoami").textContent = "已登录：" + user;
  }

  function authMsg(text) { $("auth-msg").textContent = text || ""; }

  function login() {
    var btn = $("btn-login");
    btn.disabled = true; btn.textContent = "登录中…"; authMsg("");
    postJSON("/api/login", { username: "owner", password: $("login-pass").value })
      .then(function (r) {
        if (r.status === 200) {
          user = r.data.user;
          $("login-pass").value = "";
          renderAuth();
          refresh();
        } else {
          authMsg(r.data.error || "登录失败");
        }
      })
      .finally(function () { btn.disabled = false; btn.textContent = "登录"; });
  }

  function logout() {
    var btn = $("btn-logout");
    btn.disabled = true; btn.textContent = "登出中…";
    postJSON("/api/logout").then(function () {
      user = null;
      renderAuth();
      authMsg("已登出");
      refresh();
    }).finally(function () { btn.disabled = false; btn.textContent = "登出"; });
  }

  function changePassword() {
    var btn = $("btn-passwd");
    btn.disabled = true; btn.textContent = "提交中…";
    postJSON("/api/password", { old: $("old-pass").value, new: $("new-pass").value })
      .then(function (r) {
        var msg = $("passwd-msg");
        if (r.status === 200) {
          msg.textContent = "口令已改（新口令立即生效）。";
          $("old-pass").value = "";
          $("new-pass").value = "";
        } else {
          msg.textContent = r.data.error || "改口令失败";
        }
      })
      .finally(function () { btn.disabled = false; btn.textContent = "改口令"; });
  }

  $("btn-login").addEventListener("click", login);
  $("login-pass").addEventListener("keydown", function (e) {
    if (e.key === "Enter") login();
  });
  $("btn-logout").addEventListener("click", logout);
  $("btn-passwd").addEventListener("click", changePassword);

  // ------------------------------------------------ 产品卡片
  function render(list) {
    var box = $("cards");
    box.textContent = "";
    list.forEach(function (p) {
      var card = el("div", "card" + (p.online ? " online" : ""));
      var head = el("div", "head");
      head.appendChild(el("b", "", p.name));
      var dot = el("span", "dot" + (p.online ? " on" : ""));
      dot.title = p.online ? "在线" : "离线";
      head.appendChild(dot);
      card.appendChild(head);
      card.appendChild(el("p", "note", p.tagline));
      if (p.managed) {
        var row = el("div", "row");
        if (busy[p.id]) {
          row.appendChild(el("span", "note", busy[p.id]));
        } else if (p.online) {
          if (p.kind === "desktop") {
            // 桌面窗口应用：端口是探活行协议口，不是 HTTP——导航过去只会报
            // ERR_INVALID_HTTP_RESPONSE（2026-10-07 实测），所以不给"打开产品"。
            row.appendChild(el("span", "badge", "桌面应用 · 门户启动即开画图窗口"));
          } else {
            var open = el("a", "btn", "打开产品");
            open.href = "http://127.0.0.1:" + p.port + "/";
            if (p.id === "lab") open.href += "showcase/index.html";
            open.target = "_blank";
            row.appendChild(open);
          }
          var stop = el("button", "btn ghost", "停止");
          stop.addEventListener("click", function () { act(p.id, "stop"); });
          row.appendChild(stop);
        } else {
          var start = el("button", "btn", "启动");
          start.addEventListener("click", function () { act(p.id, "start"); });
          row.appendChild(start);
        }
        if (p.pid) row.appendChild(el("span", "note", "PID " + p.pid));
        card.appendChild(row);
      } else if (p.id === "studio") {
        card.appendChild(el("span", "badge", "门户本体（无需启停）"));
      } else {
        card.appendChild(el("span", "badge", "已规划"));
      }
      box.appendChild(card);
    });
  }

  function act(id, action) {
    if (!user) { alert("管理动作需要先登录（右上角）"); return; }
    busy[id] = action === "start" ? "启动中…" : "停止中…";
    render(last);
    fetch("/api/products/" + id + "/" + action, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        delete busy[id];
        if (data.error) alert(data.error);
        refresh();
      })
      .catch(function () { delete busy[id]; refresh(); });
  }

  function refresh() {
    fetch("/api/products").then(function (r) { return r.json(); }).then(function (data) {
      last = data.products || [];
      user = (data.portal && data.portal.user) || null;
      renderAuth();
      render(last);
      refreshAudit();
    });
  }

  // ------------------------------------------------ 操作审计（M2，登录后可见）
  var OUTCOME_CLS = { ok: "pill ok", refused: "pill warn",
                      failed: "pill err", timeout: "pill err" };
  function refreshAudit() {
    if (!user) return;                       // 未登录：保持占位行，不发请求（401 噪音）
    fetch("/api/audit?limit=50").then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      var rows = $("audit-rows");
      if (!rows) return;
      rows.textContent = "";
      if (r.status !== 200) {
        rows.appendChild(el("tr")).appendChild(
          el("td", "note", "审计读取失败（HTTP " + r.status + "）"));
        return;
      }
      var events = r.d.events || [];
      if (!events.length) {
        rows.appendChild(el("tr")).appendChild(
          el("td", "note", "还没有启停动作——启动或停止一个产品后这里开始记账。"));
        return;
      }
      events.forEach(function (e) {
        var tr = el("tr");
        var t = new Date((e.ts || 0) * 1000);
        tr.appendChild(el("td", "time",
          isNaN(t) ? "—" : t.toLocaleString("zh-CN", { hour12: false })));
        tr.appendChild(el("td", "", e.action === "start" ? "启动" : "停止"));
        tr.appendChild(el("td", "", el("span", "kbd", e.pid).textContent));
        tr.appendChild(el("td", "", "")).appendChild(
          el("span", OUTCOME_CLS[e.outcome] || "pill", e.outcome));
        tr.appendChild(el("td", "note", e.detail || ""));
        rows.appendChild(tr);
      });
    });
  }

  refresh();
  setInterval(refresh, 3000);

  // ------------------------------------------------ 侧栏导航（高亮跟随 + hash 定位）
  function activateNav(key) {
    document.querySelectorAll(".side-link").forEach(function (a) {
      var on = a.getAttribute("data-nav") === key;
      a.classList.toggle("active", on);
      if (on) $("crumb-page").textContent = a.textContent.trim();
    });
  }
  document.querySelectorAll(".side-link").forEach(function (a) {
    a.addEventListener("click", function () {
      activateNav(a.getAttribute("data-nav"));
    });
  });
  function locFromHash() {
    if (location.hash === "#account") {
      activateNav("account");
      var t = $("account");
      if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (location.hash === "#audit") {
      activateNav("audit");
      var a = $("audit");
      if (a) a.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      activateNav("cards");
    }
  }
  window.addEventListener("hashchange", locFromHash);
  locFromHash();
})();
