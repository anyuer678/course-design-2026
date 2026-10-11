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

  // 2026-10-11 ECharts 化：阈值线数据源（refresh 每次 /api/status 顺带缓存）
  var RULES = {};
  var lastQuery = null;                                // {device, metric}
  var chart = null;
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
      RULES = s.rules || {};
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
    // 2026-10-11：seq 交给服务端 next_seq 分配（max+1）——random*1e9 造出的
    // 离群 seq 会把曲线 X 轴拉到亿级（10-07 与 10-11 两回实测教训）
    fetch("/api/inject", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device: dev, temp: 120, vib: 4.8 })
    }).then(function () { return fetch("/api/tick", { method: "POST" }); })
      .then(function () {
        toast("已注入越限样本（temp=120）");
        $("metric").value = "temp";
        showChart();
        refresh();
      });
  });
  // ---- 曲线（2026-10-11 ECharts 化：客户端渲染，数据 /api/series 现取）----
  // 阈值线取服务端规则（严格大于才告警）；温度曲线叠加 B35 自报异常红点。
  // /api/chart 的服务端 SVG 保留为备援，页面不再依赖 <img>。
  function getChart() {
    if (!window.echarts) return null;                  // 资产缺失只降级，不抛错
    if (!chart) {
      chart = window.echarts.init($("chart"));
      window.addEventListener("resize", function () { chart && chart.resize(); });
    }
    return chart;
  }
  var RULE_KEY = { temp: "temp_max", vib: "vib_max" };

  // ---------------- WebSocket 实时曲线（轮十八，2026-10-11）
  // 优先走 /ws/live（手写 RFC 6455 服务器推送，1s 增量）；断线自动退回
  // 2s HTTP 轮询，恢复后自动重连——两种来源共用同一份渲染数据 CUR。
  var WS = null, WS_OK = false, WS_RETRY = null;
  var CUR = null;                                     // {device, metric, pts, anoms}

  function setBadge() {
    $("live-badge").textContent = WS_OK ? "● 实时推送（WebSocket）" : "○ 轮询模式（2s）";
  }
  function connectWS() {
    if (WS) { try { WS.close(); } catch (e) {} }
    try {
      WS = new WebSocket("ws://" + location.host + "/ws/live");
    } catch (e) { WS_OK = false; setBadge(); return; }
    WS.onopen = function () {
      WS_OK = true; setBadge();
      if (lastQuery) subscribe(lastQuery.device, lastQuery.metric);
    };
    WS.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "snapshot") {
        CUR = { device: m.device, metric: m.metric,
                pts: m.points || [], anoms: m.anomalies || [] };
        $("chart").hidden = false;
        drawChart();
      } else if (m.type === "append" && CUR &&
                 m.device === CUR.device && m.metric === CUR.metric) {
        CUR.pts = CUR.pts.concat(m.points || []).slice(-500);
        (m.anomalies || []).forEach(function (a) { CUR.anoms.push(a); });
        drawChart();
      }
    };
    WS.onclose = function () {
      WS_OK = false; setBadge();
      if (WS_RETRY) clearTimeout(WS_RETRY);
      WS_RETRY = setTimeout(connectWS, 3000);          // 断线重连，期间轮询兜底
    };
    WS.onerror = function () { try { WS.close(); } catch (e) {} };
  }
  function subscribe(device, metric) {
    if (WS && WS.readyState === 1) {
      WS.send(JSON.stringify({ device: device, metric: metric }));
      return true;
    }
    return false;
  }

  function drawChart() {
    if (!CUR || !CUR.pts.length) {
      var c0 = getChart();
      if (c0) c0.clear();
      return;
    }
    var c = getChart();
    if (!c) { $("chartnote").textContent = "ECharts 未加载（assets 缺失）"; return; }
    var pts = CUR.pts, anoms = CUR.anoms;
    var series = [{
      name: CUR.metric, type: "line", smooth: true, showSymbol: false,
      data: pts.map(function (p) { return [p[0], p[1]]; }),
      lineStyle: { width: 2, color: "#2563eb" },
      areaStyle: { color: "rgba(37,99,235,.10)" }
    }];
    var thr = RULES[RULE_KEY[CUR.metric]];
    if (typeof thr === "number") {
      series[0].markLine = {
        silent: true, symbol: "none",
        lineStyle: { color: "#f43f5e", type: "dashed", width: 1.5 },
        label: { formatter: "阈值 " + thr, position: "insideEndTop" },
        data: [{ yAxis: thr }]
      };
    }
    var yMin = typeof thr === "number"
      ? function (v) {
          return Math.floor(Math.min(v.min, thr) - (v.max - v.min) * 0.05);
        }
      : null;
    if (anoms.length) {
      series.push({
        name: "自报异常", type: "scatter", symbolSize: 9,
        itemStyle: { color: "#f43f5e" },
        data: anoms.map(function (a) { return [a.seq, a.temp]; }),
        tooltip: {
          formatter: function (p) {
            var a = anoms[p.dataIndex] || {};
            return "seq " + p.value[0] + " · " + p.value[1] +
              (a.label ? "（" + a.label + "）" : "");
          }
        }
      });
    }
    c.setOption({
      animation: false,                               // 1s 增量推进，关动画防闪烁
      grid: { left: 48, right: 24, top: 32, bottom: 36 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "value", name: "seq", min: "dataMin", max: "dataMax" },
      yAxis: { type: "value", scale: true, name: CUR.metric, min: yMin },
      series: series
    });
    c.resize();                                       // 容器尺寸曾变过则自救
    $("chartnote").textContent = CUR.device + " · " + CUR.metric +
      (CUR.metric === "temp" ? "（温度曲线叠加设备自报异常点）" : "") +
      " · 近 " + pts.length + " 点" +
      (WS_OK ? " · 实时推送中" : " · 轮询刷新");
  }

  function showChart() {
    var dev = $("device").value;
    if (!dev) return;
    lastQuery = { device: dev, metric: $("metric").value };
    // 先显示容器再 init（教训入账 2026-10-11：隐藏时 echarts.init 拿不到宽度，
    // canvas 只有 100px——console 零错误但视觉压扁，必须目检才能抓到）
    $("chart").hidden = false;
    getChart();
    if (subscribe(dev, lastQuery.metric)) return;     // WS 在线：订阅后等快照
    renderChart();                                    // 离线：HTTP 兜底
  }
  function renderChart() {
    if (!lastQuery) return;
    var dev = lastQuery.device, metric = lastQuery.metric;
    fetch("/api/series?device=" + encodeURIComponent(dev) +
          "&metric=" + encodeURIComponent(metric) + "&limit=500")
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (r) {
        if (!r.ok) { $("chartnote").textContent = (r.d && r.d.error) || "曲线加载失败"; return; }
        CUR = { device: dev, metric: metric,
                pts: r.d.points || [], anoms: r.d.anomalies || [] };
        if (!CUR.pts.length) {
          var c = getChart();
          if (c) c.clear();
          $("chartnote").textContent = "设备 " + dev + " 暂无 " + metric +
            " 数据——推一拍或注入样本后自动出现。";
          return;
        }
        drawChart();
      });
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
  setBadge();
  connectWS();
  setInterval(function () {
    if (!$("auto").checked) return;
    refresh();
    // 曲线已展示时随自刷新重绘（走查 2026-10-07 的行为保留：画一次就定格是缺陷）。
    // WS 实时推送在线时图表由 onmessage 增量驱动，HTTP 轮询只管面板。
    if (!WS_OK && lastQuery && !$("chart").hidden) renderChart();
  }, 2000);
})();
