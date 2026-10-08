/* SensorHub 监测台：只做调用与展示，判定与对账全在服务端。 */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fillSelect(sel, names, keep) {
    var old = keep ? sel.value : null;
    sel.textContent = "";
    names.forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name; opt.textContent = name;
      sel.appendChild(opt);
    });
    if (old && names.indexOf(old) >= 0) sel.value = old;
  }

  function num(v) { return (typeof v === "number") ? v : "—"; }
  function toast(msg, kind) {
    var t = el("div", "toast " + (kind || "ok"), msg);
    $("toast-wrap").appendChild(t);
    setTimeout(function () { t.classList.add("out"); }, 2400);
    setTimeout(function () { t.remove(); }, 2800);
  }

  function refresh() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      $("live-dot").className = "dot";
      $("foot-state").className = "badge-dot";
      $("foot-state").textContent = "运行中 · " + (s.broker.clients || 0) + " 客户端";
      if (!s.running) {
        $("stats").textContent = "";
        $("stats").appendChild(el("div", "empty", "引擎未启动——检查 server 进程。"));
        return;
      }
      var rec = s.recorder || {};
      var alertSum = s.alerts || {};
      var rows = rec.rows || 0;
      var tiles = [["入库行数", rows, "c-blue"], ["broker 客户端", s.broker.clients, "c-violet"],
        ["已发布报文", s.broker.stats.publishes_in, "c-cyan"],
        ["拍数", s.ticks, "c-blue"], ["告警总数", alertSum.total || 0, "c-rose"],
        ["解析失败", rec.parse_errors || 0, "c-amber"]];
      var box = $("stats");
      box.textContent = "";
      tiles.forEach(function (p) {
        var tile = el("div", "tile " + p[2]);
        tile.appendChild(el("div", "t-label", p[0]));
        tile.appendChild(el("div", "t-value time", String(p[1])));
        box.appendChild(tile);
      });
      var ruleText = Object.keys(s.rules || {}).map(function (name) {
        return name + " > " + s.rules[name];
      }).join("，");
      $("rules").textContent = "当前规则：" + ruleText + "（严格大于才算告警）"
        + (alertSum.unacked ? "，未确认 " + alertSum.unacked + " 条" : "");
      $("nav-alert-cnt").textContent = String(alertSum.total || 0);
      // S1：规则编辑器的占位符跟随当前阈值
      var ruleInput = $("rule-value");
      if (ruleInput && !ruleInput.value && s.rules) {
        ruleInput.placeholder = "当前 " + (s.rules[$("rule-name").value] || "—");
      }

      // 对账表：设备账本 vs 入库实收
      var tbody = $("ledger").querySelector("tbody");
      tbody.textContent = "";
      Object.keys(s.sims || {}).sort().forEach(function (dev) {
        var sim = s.sims[dev], led = sim.ledger || {};
        var gaps = (rec.gaps || {})[dev];
        var tr = el("tr");
        [dev, num(sim.sent), num(led.spike), num(led.freeze), num(led.dropout),
         num((rec.by_device || {})[dev] || 0), num(gaps === undefined ? "—" : gaps)]
          .forEach(function (v, i) {
            var td = el("td", "", String(v));
            if (i === 5 && rows > 0 && v !== num(sim.sent)) td.className = "warn";
            tr.appendChild(td);
          });
        tbody.appendChild(tr);
      });

      // 告警明细单独拉取（见下方 /api/alerts）
    }).then(function () {
      return fetch("/api/alerts?limit=20").then(function (r) { return r.json(); });
    }).then(function (data) {
      var atbody = $("alerttable").querySelector("tbody");
      atbody.textContent = "";
      (data.alerts || []).forEach(function (a) {
        var tr = el("tr");
        var t = new Date(a.raised_at * 1000);
        var stamp = isNaN(t) ? "—" :
          t.toLocaleTimeString("zh-CN", { hour12: false });
        [stamp, a.device, a.seq, a.rule, a.metric, a.value, a.threshold]
          .forEach(function (v, i) {
            var td = el("td", "", String(v));
            if (i === 0 || i === 5) td.className = "warn";
            tr.appendChild(td);
          });
        // S2 告警确认（2026-10-07）：已确认出绿标，未确认给确认按钮
        var op = el("td");
        if (a.acked_at) {
          op.appendChild(el("span", "pill ok", "已确认"));
        } else {
          var btn = el("button", "btn btn-ghost btn-xs", "确认");
          btn.addEventListener("click", function () {
            fetch("/api/alerts/ack", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ device: a.device, seq: a.seq, rule: a.rule })
            }).then(function (r) {
              return r.json().then(function (d) { return { ok: r.ok, d: d }; });
            }).then(function (r) {
              if (!r.ok) { toast(r.d.error || "确认失败", "err"); return; }
              toast("已确认：" + a.device + " #" + a.seq + " " + a.rule);
              refresh();
            });
          });
          op.appendChild(btn);
        }
        tr.appendChild(op);
        atbody.appendChild(tr);
      });
      if (!(data.alerts || []).length) {
        atbody.appendChild(el("tr")).appendChild(
          el("td", "note", "（还没有告警——可以点「注入越限样本」试一次）"));
      }
    });
  }

  $("btn-tick").addEventListener("click", function () {
    fetch("/api/tick", { method: "POST" }).then(function () { toast("已推一拍"); refresh(); });
  });
  $("btn-inject").addEventListener("click", function () {
    var dev = $("device").value || "dev-01";
    var seq = Math.floor(Math.random() * 1e9);   // 只为演示注入唯一 seq
    fetch("/api/inject", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: dev, seq: seq, temp: 120, vib: 4.8 })
    }).then(function () { return fetch("/api/tick", { method: "POST" }); })
      .then(function () {
        toast("已注入越限样本（temp=120）");
        $("metric").value = "temp";
        showChart();
        refresh();
      });
  });
  function showChart() {
    var dev = $("device").value;
    if (!dev) return;
    var metric = $("metric").value;
    var img = $("chart");
    img.src = "/api/chart?device=" + encodeURIComponent(dev) +
      "&metric=" + encodeURIComponent(metric) + "&t=" + Date.now();
    img.hidden = false;
    var note = dev + " · " + metric + "（温度曲线叠加设备自报异常点）";
    img.alt = note;                                  // 走查 2026-10-07：绘出后 alt 别再停在空态文案
    $("chartnote").textContent = note;
  }
  $("btn-chart").addEventListener("click", showChart);

  // S1 规则编辑器（2026-10-07）：改阈值 → POST /api/rules → 立即生效并落盘
  $("btn-rule").addEventListener("click", function () {
    var rule = $("rule-name").value;
    var raw = $("rule-value").value;
    if (raw === "") { toast("先填新阈值", "err"); return; }
    fetch("/api/rules", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule: rule, threshold: Number(raw) })
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (r) {
      if (!r.ok) { toast(r.d.error || "更新失败", "err"); return; }
      toast("阈值已更新：" + rule + " > " + r.d.rules[rule]);
      $("rule-value").value = "";
      refresh();
    });
  });
  $("rule-name").addEventListener("change", function () {
    $("rule-value").value = "";
  });

  // 设备名单从 status 里拿（注入设备也会出现在库里）
  fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
    fillSelect($("device"), s.devices || [], false);
  });

  refresh();
  setInterval(function () {
    if (!$("auto").checked) return;
    refresh();
    // 曲线已展示时随自刷新重绘（走查 2026-10-07：此前画一次就定格）
    var img = $("chart");
    if (!img.hidden && img.src.indexOf("/api/chart") >= 0) {
      img.src = img.src.replace(/&t=\d+/, "&t=" + Date.now());
    }
  }, 2000);
})();
