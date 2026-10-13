/* Studio 门户脚本（轮四十六多页面化）：只做渲染与调用，判定全在服务端。
   页面分派：body[data-page] 决定跑哪个 init；共享 bootstrap 拉 portal 数据
   更新登录态与侧栏。所有 $("id") 都在对应页面上才存在——分派保证不踩空。 */
(function () {
  "use strict";
  var PAGE = document.body.getAttribute("data-page") || "";
  var busy = {};
  var user = null;
  var role = null;                   // RBAC：owner / operator / viewer / null 未登录
  var ROLE_LABEL = { owner: "管理员", operator: "操作员", viewer: "观察者" };
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

  // ------------------------------------------------ Toast（轮四十五：alert 退役）
  function toast(text, type) {
    var box = $("toast-box");
    if (!box) return;
    var node = document.createElement("div");
    node.className = "toast " + (type || "");
    node.textContent = text;
    box.appendChild(node);
    requestAnimationFrame(function () { node.classList.add("in"); });
    setTimeout(function () {
      node.classList.remove("in");
      setTimeout(function () { node.remove(); }, 300);
    }, 3200);
  }

  // ------------------------------------------------ 认证状态渲染（全页共享）
  function renderAuth(envelopeActive) {
    var guest = $("auth-guest"), authed = $("auth-user");
    if (guest && authed) {
      guest.hidden = !!user;
      authed.hidden = !user;
      guest.style.display = user ? "none" : "flex";
      authed.style.display = user ? "flex" : "none";
      if (user) $("whoami").textContent = user + " · " + (ROLE_LABEL[role] || role || "?");
    }
    // 侧栏：登录链接只给未登录；成员与邀请只给管理员
    var navLogin = $("nav-login"), navTeam = $("nav-team");
    if (navLogin) navLogin.hidden = !!user;
    if (navTeam) navTeam.hidden = !(user && role === "owner");
    // 页面专属元素按存在性处理
    if ($("envelope-hint") && PAGE === "login")
      $("envelope-hint").hidden = !!user || !envelopeActive;
    if ($("envelope-hint") && PAGE === "account")
      $("envelope-hint").hidden = !envelopeActive || !user;
  }

  function logout() {
    var btn = $("btn-logout");
    if (btn) { btn.disabled = true; btn.textContent = "登出中…"; }
    postJSON("/api/logout").then(function () {
      user = null; role = null;
      renderAuth();
      toast("已登出", "ok");
      setTimeout(function () { location.href = "/"; }, 400);
    });
  }
  if ($("btn-logout")) $("btn-logout").addEventListener("click", logout);

  // ================================================================ login 页
  function initLogin() {
    // tab 切换（生产惯例：登录/注册同页切换）
    function showTab(which) {
      var login = which === "login";
      $("tab-login").classList.toggle("on", login);
      $("tab-register").classList.toggle("on", !login);
      $("pane-login").hidden = !login;
      $("pane-register").hidden = login;
    }
    $("tab-login").addEventListener("click", function () { showTab("login"); });
    $("tab-register").addEventListener("click", function () { showTab("register"); });
    function login() {
      var btn = $("btn-login"), msg = $("login-msg");
      btn.disabled = true; btn.textContent = "登录中…"; msg.textContent = "";
      postJSON("/api/login", { username: $("login-user").value.trim(),
                               password: $("login-pass").value })
        .then(function (r) {
          if (r.status === 200) {
            toast("欢迎回来，" + r.data.user, "ok");
            setTimeout(function () { location.href = "/"; }, 400);
          } else {
            msg.textContent = r.data.error || "登录失败";
          }
        })
        .finally(function () { btn.disabled = false; btn.textContent = "登录"; });
    }
    function register() {
      var name = $("reg-name").value.trim();
      var pw = $("reg-pass").value, pw2 = $("reg-pass2").value;
      var invite = $("reg-invite").value.trim();
      var msg = $("reg-msg");
      // 字段级预校验（与服务端同规则；服务端仍是权威）
      var tips = [];
      if (!/^[A-Za-z0-9_-]{2,20}$/.test(name))
        tips.push("用户名须为 2-20 位字母/数字/下划线/连字符");
      if (pw.length < 8)
        tips.push("口令至少 8 位");
      if (pw !== pw2)
        tips.push("两次输入的口令不一致");
      if (tips.length) { msg.textContent = tips.join("；") + "。"; return; }
      var btn = $("btn-register");
      btn.disabled = true; btn.textContent = "注册中…"; msg.textContent = "";
      postJSON("/api/register", { name: name, password: pw, invite: invite || null })
        .then(function (r) {
          if (r.status === 201) {
            toast("注册成功，已登录为 " + (ROLE_LABEL[r.data.role] || r.data.role), "ok");
            setTimeout(function () { location.href = "/"; }, 500);
          } else {
            msg.textContent = r.data.error || "注册失败";
          }
        })
        .finally(function () { btn.disabled = false; btn.textContent = "注册并登录"; });
    }
    $("btn-login").addEventListener("click", login);
    ["login-user", "login-pass"].forEach(function (id) {
      $(id).addEventListener("keydown", function (e) { if (e.key === "Enter") login(); });
    });
    ["reg-name", "reg-pass", "reg-pass2", "reg-invite"].forEach(function (id) {
      $(id).addEventListener("keydown", function (e) {
        if (e.key === "Enter") register();
      });
    });
    $("btn-register").addEventListener("click", register);
    // 已登录访问认证页 → 直接回矩阵
    if (user) location.href = "/";
  }

  // ================================================================ products 页
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
        var canOperate = role === "owner" || role === "operator";
        // 内嵌控制台对所有人可见（产品本身公开只读）——启停才要权限
        if (p.online && p.kind !== "desktop") {
          var consoleLink = el("a", "btn", "进入控制台");
          consoleLink.href = "/console.html?pid=" + encodeURIComponent(p.id);
          row.appendChild(consoleLink);
        }
        if (busy[p.id]) {
          row.appendChild(el("span", "note", busy[p.id]));
        } else if (!canOperate) {
          row.appendChild(el("span", "note", user ? "观察者只读" : "登录后可启停"));
        } else if (p.online) {
          if (p.kind === "desktop") {
            row.appendChild(el("span", "badge", "桌面应用 · 后台运行，画图走 BoardWeb"));
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
    if (!user) { toast("管理动作需要先登录", "err"); return; }
    if (role !== "owner" && role !== "operator") {
      toast("当前角色（" + (ROLE_LABEL[role] || role) + "）无权启停产品", "err");
      return;
    }
    busy[id] = action === "start" ? "启动中…" : "停止中…";
    render(last);
    fetch("/api/products/" + id + "/" + action, { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        delete busy[id];
        if (data.error) toast(action === "start" ? "启动失败：" + data.error
                                                 : "停止失败：" + data.error, "err");
        else toast((action === "start" ? "已启动：" : "已停止：") + id, "ok");
        refresh();
      })
      .catch(function () { delete busy[id]; refresh(); });
  }

  // ------------------------------------------------ 探活历史（采样在服务端，这里只渲染）
  var UPTIME = null;
  function renderUptime() {
    var UP_COLOR = "#10b981", DOWN_COLOR = "#f43f5e";
    fetch("/api/history").then(function (r) { return r.json(); }).then(function (h) {
      var box = $("uptime-strip");
      if (!box) return;
      if (!window.echarts || !h.samples || h.samples.length < 2) {
        if (UPTIME) { UPTIME.clear(); }
        return;
      }
      var names = {};
      (last || []).forEach(function (p) { names[p.id] = p.name; });
      var pids = h.products || [];
      var rows = pids.map(function (pid) { return names[pid] || pid; });
      if (!UPTIME) UPTIME = echarts.init(box);
      var segments = [];
      var samples = h.samples;
      // 相邻同状态合并：6h×10 产品最多 2 万采样点，不合并每 3s 重画 2 万矩形
      function mk(t0, t1, row, up) {
        return { value: [t0 * 1000, t1 * 1000, row, up ? 1 : 0],
                 itemStyle: { color: up ? UP_COLOR : DOWN_COLOR,
                              opacity: up ? 0.9 : 1 } };
      }
      for (var j = 0; j < pids.length; j++) {
        var segStart = samples[0][0], prevUp = ((samples[0][1] >> j) & 1) === 1;
        for (var i = 1; i < samples.length; i++) {
          var up = ((samples[i][1] >> j) & 1) === 1;
          if (up !== prevUp) {
            segments.push(mk(segStart, samples[i][0], j, prevUp));
            segStart = samples[i][0]; prevUp = up;
          }
        }
        segments.push(mk(segStart, samples[samples.length - 1][0], j, prevUp));
      }
      var spanMin = (samples[samples.length - 1][0] - samples[0][0]) / 60;
      UPTIME.setOption({
        animation: false,
        grid: { left: 130, right: 20, top: 14, bottom: 26 },
        tooltip: {
          formatter: function (p) {
            var v = p.value;
            var st = new Date(v[0]).toLocaleTimeString("zh-CN", { hour12: false });
            var en = new Date(v[1]).toLocaleTimeString("zh-CN", { hour12: false });
            return rows[v[2]] + "<br>" + st + " – " + en +
              "<br>" + (v[3] ? "在线" : "<b>掉线</b>");
          }
        },
        xAxis: { type: "time", axisLabel: { fontSize: 10, hideOverlap: true } },
        yAxis: { type: "category", data: rows, inverse: true,
                 axisLabel: { fontSize: 11 } },
        series: [{
          type: "custom",
          renderItem: function (params, api) {
            var row = api.value(2);
            var start = api.coord([api.value(0), row]);
            var end = api.coord([api.value(1), row]);
            var barH = api.size([0, 1])[1] * 0.62;
            var clipY = Math.max(start[1], end[1]);
            return {
              type: "rect",
              shape: { x: start[0], y: clipY - barH / 2,
                       width: Math.max(end[0] - start[0], 1), height: barH },
              style: api.style()
            };
          },
          encode: { x: [0, 1], y: [2] },
          data: segments
        }]
      });
      var downs = segments.filter(function (s) { return !s.value[3]; }).length;
      $("uptime-note").textContent =
        "近 " + Math.max(1, Math.round(spanMin)) + " 分钟 · " + pids.length +
        " 个产品 · " + samples.length + " 次采样" +
        (downs ? " · 其中 " + downs + " 段掉线（红色）" : " · 全程在线");
    }).catch(function () { /* 服务失联时下一轮 refresh 一并重试 */ });
  }

  function refresh() {
    fetch("/api/products").then(function (r) { return r.json(); }).then(function (data) {
      last = data.products || [];
      user = (data.portal && data.portal.user) || null;
      role = (data.portal && data.portal.role) || null;
      renderAuth(!!(data.portal && data.portal.envelope_active));
      render(last);
      renderUptime();
    });
  }

  // ---------------- 状态实时推送（轮三十六）：变化才推，断线回退 3s 轮询
  var WS = null, WS_OK = false;
  function setModeBadge() {
    var b = $("ws-state");
    if (b) b.textContent = WS_OK ? "● 实时推送（WebSocket）" : "○ 轮询模式（3s）";
  }
  function applyStatus(products) {
    last = products || [];
    render(last);
    renderUptime();
  }
  function connectStatus() {
    try {
      WS = new WebSocket("ws://" + location.host + "/ws/status");
    } catch (e) { setModeBadge(); return; }
    WS.onopen = function () { WS_OK = true; setModeBadge(); };
    WS.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "status") applyStatus(msg.products);
    };
    WS.onclose = WS.onerror = function () {
      WS_OK = false;
      setModeBadge();
      setTimeout(connectStatus, 5000);
    };
  }

  function initProducts() {
    refresh();
    connectStatus();
    setInterval(function () {
      if (!WS_OK) refresh();               // WS 在线时轮询休眠，断线自动接管
    }, 3000);
  }

  // ================================================================ audit 页
  var OUTCOME_CLS = { ok: "pill ok", refused: "pill warn",
                      failed: "pill err", timeout: "pill err" };
  var DASH = { actions: null, outcomes: null };
  var OUTCOME_COLOR = { ok: "#10b981", refused: "#f59e0b",
                        failed: "#f43f5e", timeout: "#a855f7" };
  function dashChart(key) {
    if (!window.echarts) return null;
    if (!DASH[key]) DASH[key] = echarts.init($("dash-" + key));
    return DASH[key];
  }
  window.addEventListener("resize", function () {
    Object.keys(DASH).forEach(function (k) { if (DASH[k]) DASH[k].resize(); });
  });

  function renderDash(events) {
    var dash = $("dash");
    if (!events.length) { dash.hidden = true; return; }
    dash.hidden = false;
    var c1 = dashChart("actions");
    if (c1) {
      var byProduct = {}, order = [];
      events.forEach(function (e) {
        if (!byProduct[e.pid]) { byProduct[e.pid] = { start: 0, stop: 0 }; order.push(e.pid); }
        if (e.action === "start" || e.action === "stop") byProduct[e.pid][e.action] += 1;
      });
      order.sort(function (a, b) {
        return (byProduct[b].start + byProduct[b].stop) -
               (byProduct[a].start + byProduct[a].stop);
      });
      c1.setOption({
        grid: { left: 76, right: 20, top: 42, bottom: 30 },
        tooltip: { trigger: "axis" },
        legend: { top: 6 },
        xAxis: { type: "value", minInterval: 1, name: "次数" },
        yAxis: { type: "category", data: order, inverse: true },
        series: [
          { name: "启动", type: "bar", stack: "total",
            data: order.map(function (p) { return byProduct[p].start; }),
            itemStyle: { color: "#2563eb" }, barMaxWidth: 22 },
          { name: "停止", type: "bar", stack: "total",
            data: order.map(function (p) { return byProduct[p].stop; }),
            itemStyle: { color: "#94a3b8" }, barMaxWidth: 22 }
        ]
      });
    }
    var c2 = dashChart("outcomes");
    if (c2) {
      var byOutcome = {};
      events.forEach(function (e) {
        byOutcome[e.outcome] = (byOutcome[e.outcome] || 0) + 1;
      });
      c2.setOption({
        tooltip: { trigger: "item", formatter: "{b}：{c} 次（{d}%）" },
        legend: { bottom: 4 },
        series: [{ type: "pie", radius: ["42%", "66%"], center: ["50%", "44%"],
          label: { show: true, formatter: "{b} {c}", fontSize: 11 },
          data: Object.keys(byOutcome).map(function (k) {
            return { name: k, value: byOutcome[k],
                     itemStyle: { color: OUTCOME_COLOR[k] || "#94a3b8" } };
          }) }]
      });
    }
  }

  function refreshAudit() {
    if (!user) { $("dash").hidden = true; return; }   // 未登录：不发请求（401 噪音）
    fetch("/api/audit?limit=50").then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      var rows = $("audit-rows");
      rows.textContent = "";
      if (r.status !== 200) {
        $("dash").hidden = true;
        rows.appendChild(el("tr")).appendChild(
          el("td", "note", "审计读取失败（HTTP " + r.status + "）"));
        return;
      }
      var events = r.d.events || [];
      renderDash(events);
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
        tr.appendChild(el("td", "", e.user || "—"));   // RBAC：谁动的
        tr.appendChild(el("td", "note", e.detail || ""));
        rows.appendChild(tr);
      });
    });
  }

  function initAudit() {
    refreshAudit();
    setInterval(refreshAudit, 5000);     // 审计页 5s 轮询（轻量，仅本页开着才跑）
  }

  // ================================================================ team 页
  function usersMsg(text) { $("users-msg").textContent = text || ""; }
  function loadUsers() {
    fetch("/api/users").then(function (r) { return r.json(); }).then(function (d) {
      var rows = $("users-rows");
      rows.textContent = "";
      (d.users || []).forEach(function (u) {
        var tr = el("tr");
        tr.appendChild(el("td", "", u.name));
        var roleCell = tr.appendChild(el("td", "", ""));
        var sel = el("select");
        ["operator", "viewer"].forEach(function (r) {
          var op = el("option", "", r === "operator" ? "operator（可启停）" : "viewer（只读）");
          op.value = r; if (r === u.role) op.selected = true;
          sel.appendChild(op);
        });
        sel.addEventListener("change", function () {
          postJSON("/api/users/" + u.name + "/role", { role: sel.value })
            .then(function (r) {
              if (r.status === 200) { usersMsg(u.name + " → " + sel.value); loadUsers(); }
              else usersMsg(r.data.error || "改角色失败");
            });
        });
        roleCell.appendChild(sel);
        var mgmt = tr.appendChild(el("td", "", ""));
        var reset = el("button", "btn btn-ghost btn-sm", "重置口令");
        reset.addEventListener("click", function () {
          var pw = window.prompt("为 " + u.name + " 设置新口令（至少 8 位）：", "");
          if (pw === null) return;
          postJSON("/api/users/" + u.name + "/reset", { password: pw })
            .then(function (r) {
              usersMsg(r.status === 200 ? u.name + " 口令已重置" : (r.data.error || "重置失败"));
            });
        });
        mgmt.appendChild(reset);
        mgmt.appendChild(document.createTextNode(" "));
        var del = el("button", "btn btn-ghost btn-sm", "删除");
        del.addEventListener("click", function () {
          if (!window.confirm("删除成员 " + u.name + "？")) return;
          fetch("/api/users/" + u.name, { method: "DELETE" })
            .then(function (r) { return r.json().then(function (d2) { return { status: r.status, d: d2 }; }); })
            .then(function (r) {
              if (r.status === 200) { usersMsg(u.name + " 已删除"); loadUsers(); }
              else usersMsg(r.d.error || "删除失败");
            });
        });
        mgmt.appendChild(del);
        rows.appendChild(tr);
      });
      if (!(d.users || []).length) {
        rows.appendChild(el("tr", "note", "")).appendChild(
          el("td", "note", "还没有成员——用下面的表单添加。"));
      }
    });
  }

  function loadInvites() {
    fetch("/api/invites").then(function (r) { return r.json(); }).then(function (d) {
      var rows = $("invite-rows");
      rows.textContent = "";
      (d.invites || []).forEach(function (inv) {
        var tr = el("tr");
        tr.appendChild(el("td", "", el("span", "kbd", inv.code).textContent));
        tr.appendChild(el("td", "", inv.role));
        tr.appendChild(el("td", "note", inv.created));
        var ops = tr.appendChild(el("td", "", ""));
        var del = el("button", "btn btn-ghost btn-sm", "作废");
        del.addEventListener("click", function () {
          fetch("/api/invites/" + encodeURIComponent(inv.code), { method: "DELETE" })
            .then(function () { loadInvites(); });
        });
        ops.appendChild(del);
        rows.appendChild(tr);
      });
      if (!(d.invites || []).length) {
        rows.appendChild(el("tr", "", "")).appendChild(
          el("td", "note", "暂无有效邀请码。"));
      }
    });
  }

  function initTeam() {
    // 非管理员如实显示无权卡（服务端仍是权威，这里只管体验）
    if (role !== "owner") {
      $("users-card").hidden = true;
      $("team-deny").hidden = false;
      return;
    }
    $("users-card").hidden = false;
    loadUsers();
    loadInvites();
    $("btn-add-user").addEventListener("click", function () {
      postJSON("/api/users", {
        name: $("new-user-name").value.trim(),
        password: $("new-user-pass").value,
        role: $("new-user-role").value
      }).then(function (r) {
        if (r.status === 201) {
          usersMsg(r.data.name + " 已添加（" + r.data.role + "）");
          $("new-user-name").value = ""; $("new-user-pass").value = "";
          loadUsers();
        } else {
          usersMsg(r.data.error || "添加失败");
        }
      });
    });
    $("btn-new-invite").addEventListener("click", function () {
      postJSON("/api/invites", { role: $("invite-role").value })
        .then(function (r) {
          if (r.status === 201) {
            $("invite-msg").textContent = "新邀请码：" + r.data.code
              + "（" + r.data.role + "）——复制给要注册的人，用一次即失效。";
            loadInvites();
          } else {
            $("invite-msg").textContent = r.data.error || "生成失败";
          }
        });
    });
  }

  // ================================================================ account 页
  var PERM_DESC = {
    "product.start": "启动产品",
    "product.stop": "停止产品",
    "audit.read": "查看操作审计",
    "users.manage": "成员管理",
    "invites.manage": "邀请码管理",
    "portal.password": "修改门户口令"
  };
  function renderPerms() {
    fetch("/api/me").then(function (r) { return r.json(); }).then(function (d) {
      var me = $("perm-me"), list = $("perm-list");
      list.textContent = "";
      if (!d.user) { me.textContent = "未登录（L0）：仅可浏览产品矩阵与状态。"; return; }
      var labels = { owner: "L3 管理员", operator: "L2 操作员", viewer: "L1 观察者" };
      me.textContent = d.user + "（" + (labels[d.role] || d.role) + "）拥有的权限：";
      (d.permissions || []).forEach(function (p) {
        if (PERM_DESC[p]) list.appendChild(el("span", "pill ok", PERM_DESC[p]));
      });
    }).catch(function () { /* 未登录 401：保持 L0 文案 */ });
  }

  function changePassword() {
    var btn = $("btn-passwd");
    btn.disabled = true; btn.textContent = "提交中…";
    postJSON("/api/password", { old: $("old-pass").value, new: $("new-pass").value })
      .then(function (r) {
        var msg = $("passwd-msg");
        if (r.status === 200) {
          msg.textContent = "口令已改（新口令立即生效），初始口令信封已作废。";
          $("old-pass").value = "";
          $("new-pass").value = "";
        } else {
          msg.textContent = r.data.error || "改口令失败";
        }
      })
      .finally(function () { btn.disabled = false; btn.textContent = "改口令"; });
  }

  function initAccount() {
    renderPerms();
    $("btn-passwd").addEventListener("click", changePassword);
  }

  // ================================================================ console 页
  function initConsole() {
    var pid = new URLSearchParams(location.search).get("pid") || "";
    fetch("/api/products").then(function (r) { return r.json(); }).then(function (d) {
      var p = null;
      (d.products || []).forEach(function (x) { if (x.id === pid) p = x; });
      if (!p) {
        $("console-denied-text").textContent = "没有叫 " + JSON.stringify(pid) + " 的产品。";
        $("console-denied").hidden = false;
        return;
      }
      $("console-title").textContent = p.name;
      if (!p.managed) {
        $("console-denied-text").textContent = p.name + " 是门户本体，无需控制台。";
        $("console-denied").hidden = false;
        return;
      }
      if (p.kind === "desktop") {
        $("console-denied-text").textContent =
          p.name + " 是桌面应用（探活口不是 HTTP），无法内嵌；画图请用 BoardWeb（矩阵页进入控制台）。";
        $("console-denied").hidden = false;
        return;
      }
      if (!p.online) {
        $("console-denied-text").textContent =
          p.name + " 当前离线——回矩阵页启动后再来。";
        $("console-denied").hidden = false;
        return;
      }
      var url = "http://127.0.0.1:" + p.port + "/";
      if (p.id === "lab") url += "showcase/index.html";
      $("console-frame").src = url;
      $("console-frame-box").hidden = false;
      $("console-open").href = url;
      $("console-open").hidden = false;
      $("console-note").textContent = "内嵌自 127.0.0.1:" + p.port +
        "（产品在新窗口打开也一样可用）";
      // 演示条（轮四十七）：有演示端点的产品给一键注入；其余给一句话引导
      var DEMO_HINT = {
        cachekv: "注入 12 个混合 TTL 演示键，统计页立即有账可看",
        sensorhub: "为全部设备注入 8 拍演示读数（含 1 拍离群），曲线立刻有形状"
      };
      var GUIDE = {
        datascope: "数据工作台自带内置演示 CSV（页内「样例数据」即可载入体验画像与清洗）",
        linkbox: "创建一条短链或文本暂存即可开始体验",
        courselab: "用右上角注册的账号登录，课程/实验/任务即刻可见",
        boardweb: "直接在画布上绘制——开两个窗口还能看到多人协同",
        simlab: "回放页自带演示帧，无需额外数据",
        lab: "项目群控制台自带全部演示入口"
      };
      if (DEMO_HINT[pid]) {
        $("demo-note").textContent = "空产品看不出效果？";
        $("btn-demo").addEventListener("click", function () {
          var btn = $("btn-demo");
          btn.disabled = true; btn.textContent = "注入中…";
          postJSON("/api/demo/" + pid).then(function (r) {
            if (r.status === 200) {
              $("demo-msg").textContent = r.data.note || "已注入";
              toast(r.data.note || "演示数据已注入", "ok");
              $("console-frame").src = $("console-frame").src;   // 重载 iframe 看到数据
            } else {
              $("demo-msg").textContent = r.data.error || "注入失败";
            }
          }).finally(function () { btn.disabled = false; btn.textContent = "一键注入演示数据"; });
        });
      } else {
        $("demo-note").textContent = GUIDE[pid] || "";
        $("btn-demo").hidden = true;
      }
      $("demo-bar").hidden = false;
    });
  }

  // ================================================================ 分派
  function bootstrap() {
    // 每页共享：拉 portal 数据更新登录态 → 再进页面初始化
    fetch("/api/products").then(function (r) { return r.json(); }).then(function (data) {
      user = (data.portal && data.portal.user) || null;
      role = (data.portal && data.portal.role) || null;
      renderAuth(!!(data.portal && data.portal.envelope_active));
      dispatch();
    }).catch(function () {
      // 服务失联：至少让页面结构可见
      dispatch();
    });
  }
  function dispatch() {
    if (PAGE === "products") initProducts();
    else if (PAGE === "audit") initAudit();
    else if (PAGE === "team") initTeam();
    else if (PAGE === "account") initAccount();
    else if (PAGE === "login") initLogin();
    else if (PAGE === "console") initConsole();
  }
  bootstrap();
})();
