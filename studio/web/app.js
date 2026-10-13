/* Studio 门户脚本：只做渲染与调用，判定全在服务端。 */
(function () {
  "use strict";
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

  // ------------------------------------------------ 认证
  function renderAuth(envelopeActive) {
    $("auth-guest").hidden = !!user;
    $("auth-user").hidden = !user;
    // hidden 属性压不过内联 display:flex——display 一并切换
    // （2026-10-07 走查：登录后表单曾与"已登录"并排显示）
    $("auth-guest").style.display = user ? "none" : "flex";
    $("auth-user").style.display = user ? "flex" : "none";
    // 正规认证卡（轮四十三）：未登录显示登录+注册并排卡，登录后收起
    $("auth-hero").hidden = !!user;
    $("envelope-hint").hidden = !!user || !envelopeActive;
    if (user) {
      $("whoami").textContent = user + " · " + (ROLE_LABEL[role] || role || "?");
      $("btn-users").hidden = role !== "owner";
      $("users-card").hidden = role !== "owner" ? true : $("users-card").hidden;
    }
  }

  function authMsg(text) { $("auth-msg").textContent = text || ""; }

  // ------------------------------------------------ Toast（轮四十五：alert 退役）
  function toast(text, type) {
    var box = $("toast-box"), node = document.createElement("div");
    node.className = "toast " + (type || "");
    node.textContent = text;
    box.appendChild(node);
    requestAnimationFrame(function () { node.classList.add("in"); });
    setTimeout(function () {
      node.classList.remove("in");
      setTimeout(function () { node.remove(); }, 300);
    }, 3200);
  }

  function login() {
    var btn = $("btn-login");
    var msg = $("login-msg");
    btn.disabled = true; btn.textContent = "登录中…"; msg.textContent = "";
    postJSON("/api/login", { username: $("login-user").value.trim(),
                             password: $("login-pass").value })
      .then(function (r) {
        if (r.status === 200) {
          user = r.data.user; role = r.data.role;
          $("login-pass").value = "";
          renderAuth();
          refresh();
        } else {
          msg.textContent = r.data.error || "登录失败";
        }
      })
      .finally(function () { btn.disabled = false; btn.textContent = "登录"; });
  }

  function logout() {
    var btn = $("btn-logout");
    btn.disabled = true; btn.textContent = "登出中…";
    postJSON("/api/logout").then(function () {
      user = null; role = null;
      $("users-card").hidden = true;      // 面板跟登录态走，登出即收
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
  ["login-user", "login-pass"].forEach(function (id) {
    $(id).addEventListener("keydown", function (e) { if (e.key === "Enter") login(); });
  });
  // 注册卡：任一栏 Enter 即提交（轮四十五交互补全）
  ["reg-name", "reg-pass", "reg-pass2", "reg-invite"].forEach(function (id) {
    $(id).addEventListener("keydown", function (e) {
      if (e.key === "Enter") $("btn-register").click();
    });
  });
  $("btn-logout").addEventListener("click", logout);
  $("btn-passwd").addEventListener("click", changePassword);

  // ------------------------------------------------ 成员管理（RBAC，owner 专属）
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
  $("btn-users").addEventListener("click", function () {
    var card = $("users-card");
    card.hidden = false;
    loadUsers();
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  });
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

  // ------------------------------------------------ 自助注册（轮四十二）
  $("btn-register").addEventListener("click", function () {
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
    var btn = this;
    btn.disabled = true; btn.textContent = "注册中…"; msg.textContent = "";
    postJSON("/api/register", { name: name, password: pw, invite: invite || null })
      .then(function (r) {
        if (r.status === 201) {
          user = r.data.user; role = r.data.role;
          $("reg-pass").value = ""; $("reg-pass2").value = ""; $("reg-invite").value = "";
          renderAuth();
          msg.textContent = "注册成功，已登录为 " + (ROLE_LABEL[role] || role) + "。";
          refresh();
        } else {
          msg.textContent = r.data.error || "注册失败";
        }
      })
      .finally(function () { btn.disabled = false; btn.textContent = "注册并登录"; });
  });

  // ------------------------------------------------ 邀请码（owner 专属）
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
  var _usersObserver = new MutationObserver(function () {
    if (!$("users-card").hidden) loadInvites();
  });
  _usersObserver.observe($("users-card"), { attributes: true, attributeFilter: ["hidden"] });

  // ------------------------------------------------ 我的分层与权限（轮四十四）
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
        var canOperate = role === "owner" || role === "operator";
        if (busy[p.id]) {
          row.appendChild(el("span", "note", busy[p.id]));
        } else if (!user) {
          // 未登录：按钮照画，act() 会提示先登录（登录态由服务端裁决）
          if (p.online) {
            var stop0 = el("button", "btn ghost", "停止");
            stop0.addEventListener("click", function () { act(p.id, "stop"); });
            row.appendChild(stop0);
          } else {
            var start0 = el("button", "btn", "启动");
            start0.addEventListener("click", function () { act(p.id, "start"); });
            row.appendChild(start0);
          }
        } else if (!canOperate) {
          row.appendChild(el("span", "note", "观察者只读"));
        } else if (p.online) {
          if (p.kind === "desktop") {
            // 桌面窗口应用：端口是探活行协议口，不是 HTTP——导航过去只会报
            // ERR_INVALID_HTTP_RESPONSE（2026-10-07 实测），所以不给"打开产品"。
            // 轮四十一：门户启动为后台服务（不弹 Swing 窗口），画图走 BoardWeb。
            row.appendChild(el("span", "badge", "桌面应用 · 后台运行，画图走 BoardWeb"));
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
        refresh();
      })
      .catch(function () { delete busy[id]; refresh(); });
  }

  // ------------------------------------------------ 探活历史（2026-10-12 监控大盘时序维度）
  // /api/history 返回位掩码压缩采样（按 products 顺序），前端解位画状态页式
  // 色条：每产品一行，绿=在线红=掉线。采样在服务端后台线程，本文件只渲染。
  var UPTIME = null;
  function renderUptime() {
    var UP_COLOR = "#10b981", DOWN_COLOR = "#f43f5e";
    fetch("/api/history").then(function (r) { return r.json(); }).then(function (h) {
      var box = $("uptime-strip");
      if (!box) return;
      if (!window.echarts || !h.samples || h.samples.length < 2) {
        if (UPTIME) { UPTIME.clear(); }
        return;                                        // 采样不足两条画不出段，等下轮
      }
      var names = {};
      (last || []).forEach(function (p) { names[p.id] = p.name; });
      var pids = h.products || [];
      var rows = pids.map(function (pid) { return names[pid] || pid; });
      if (!UPTIME) UPTIME = echarts.init(box);
      var segments = [];
      var samples = h.samples;
      // 相邻同状态合并：6h×10 产品最多 2 万采样点，不合并每 3s 重画 2 万矩形；
      // 合并后每行只有状态翻转那么几段，这也是状态页条的真实画法。
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
      renderPerms();
      render(last);
      renderUptime();
      refreshAudit();
    });
  }

  // ---------------- 状态实时推送（2026-10-12，GAP P0 升级动作）
  // 优先走 /ws/status（服务器变化才推，首包即快照）；断线自动回退 3s 轮询，
  // 5s 后重连。侧栏 foot-state 徽标显示当前模式。登录态不在推送里——
  // 初始 refresh() 与登录动作后各自拉一次（cookie 会话，变化极低频）。
  var WS = null, WS_OK = false;
  function setModeBadge() {
    var b = $("ws-state");
    if (!b) return;
    b.textContent = WS_OK ? "● 实时推送（WebSocket）" : "○ 轮询模式（3s）";
  }
  function applyStatus(products) {
    last = products || [];
    render(last);
    renderUptime();
    refreshAudit();
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

  // ------------------------------------------------ 操作审计（M2，登录后可见）
  var OUTCOME_CLS = { ok: "pill ok", refused: "pill warn",
                      failed: "pill err", timeout: "pill err" };

  // 监控大盘（2026-10-11 ECharts 化）：审计账本两图——各产品启停堆叠 + 结果分布环。
  // 数据全来自 /api/audit，前端只做聚合；未登录/无事件时整块隐藏。
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
    if (!dash) return;
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
      if (!rows) return;
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

  refresh();
  connectStatus();
  setInterval(function () {
    if (!WS_OK) refresh();               // WS 在线时轮询休眠，断线自动接管
  }, 3000);

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
