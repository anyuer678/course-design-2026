/* SimLab 控制台（UI 2.1）：schema 驱动参数表单 + 帧回放 + 回放库管理。
   帧内容全部来自服务端现算的引擎产出，前端零加工。 */
(function () {
  "use strict";
  var record = null, t = 0, timer = null;
  var currentExperiment = null, currentSchema = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function msg(text) { $("form-msg").textContent = text || ""; }
  function toast(text, kind) {
    var t = el("div", "toast " + (kind || "ok"), text);
    $("toast-wrap").appendChild(t);
    setTimeout(function () { t.classList.add("out"); }, 2600);
    setTimeout(function () { t.remove(); }, 3000);
  }
  function on(id, fn) {
    var node = $(id);
    if (node) node.addEventListener("click", fn);
    else if (window.console) console.warn("[simlab] 缺少元素 #" + id);
  }

  // ------------------------------------------------ 数据获取
  function fmtWhen(v) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    return isNaN(n) ? String(v)
      : new Date(n < 1e12 ? n * 1000 : n).toLocaleString();
  }
  function refreshRecords() {
    fetch("/api/records").then(function (r) { return r.json(); }).then(function (data) {
      var rows = $("record-rows");
      rows.textContent = "";
      var items = data.records || [];
      $("lib-count").textContent = items.length + " 份";
      $("nav-rec-cnt").textContent = String(items.length);
      $("lib-empty").hidden = items.length > 0;
      if (!items.length) {
        var tr0 = el("tr");
        var td0 = el("td", "note", "（空）");
        td0.colSpan = 5;
        tr0.appendChild(td0);
        rows.appendChild(tr0);
        return;
      }
      items.forEach(function (item) {
        var tr = el("tr");
        tr.addEventListener("click", function () { loadRecord(item.name); });
        var nameTd = el("td");
        nameTd.appendChild(el("span", "kbd", item.name));
        if (item.invalid) {
          nameTd.appendChild(el("span", "pill err", "损坏"));
          tr.appendChild(nameTd);
          tr.appendChild(el("td", "note", item.error || ""));
          tr.appendChild(el("td", "note", "—"));
          tr.appendChild(el("td", "note", "—"));
          var fix = el("td");
          var del = el("button", "btn btn-danger btn-xs", "删除文件");
          del.addEventListener("click", function (ev) {
            ev.stopPropagation();
            toast("删除请直接删 runs/" + item.name + " 文件（保留只读记录库的克制）", "err");
          });
          fix.appendChild(del);
          tr.appendChild(fix);
          rows.appendChild(tr);
          return;
        }
        tr.appendChild(nameTd);
        tr.appendChild(el("td", "", "")).appendChild(el("span", "pill info", item.experiment));
        tr.appendChild(el("td", "time", String(item.frames)));
        tr.appendChild(el("td", "time", fmtWhen(item.created_at)));
        var ops = el("td");
        var load = el("button", "btn btn-ghost btn-xs", "载入");
        load.addEventListener("click", function (ev) {
          ev.stopPropagation(); loadRecord(item.name);
        });
        ops.appendChild(load);
        tr.appendChild(ops);
        rows.appendChild(tr);
      });
    }).catch(function () { $("live-dot").className = "dot off"; });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    });
  }

  // ------------------------------------------------ 参数表单（schema 驱动）
  function loadSchema(experiment, preset) {
    currentExperiment = experiment;
    return fetch("/api/params/" + encodeURIComponent(experiment))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentSchema = data.schema;
        buildForm(data.schema, preset);
        msg("");
      });
  }

  function buildForm(schema, preset) {
    var box = $("params-form");
    box.textContent = "";
    Object.keys(schema).forEach(function (field) {
      var spec = schema[field];
      var row = el("div", "prow");
      row.appendChild(el("label", "plabel", spec.label || field));
      // M1 分享链接（2026-10-07）：URL hash 里带来的参数值优先于 schema 默认值
      var value = (preset && Object.prototype.hasOwnProperty.call(preset, field))
        ? preset[field] : spec.default;
      if (spec.type === "bool") {
        var cb = el("input", "inp");
        cb.type = "checkbox"; cb.checked = !!value; cb.dataset.field = field;
        cb.dataset.kind = "bool";
        row.appendChild(cb);
      } else if (spec.type === "enum") {
        var sel = el("select", "inp");
        (spec.options || []).forEach(function (option) {
          var o = el("option", "", option); o.value = option;
          if (option === value) o.selected = true;
          sel.appendChild(o);
        });
        sel.dataset.field = field; sel.dataset.kind = "enum";
        row.appendChild(sel);
      } else if (spec.type === "int") {
        var num = el("input", "inp");
        num.type = "number"; num.value = value;
        if (spec.min !== undefined) num.min = String(spec.min);
        num.dataset.field = field; num.dataset.kind = "int";
        row.appendChild(num);
      } else {
        var ta = el("textarea", "inp wide");
        ta.rows = 2;
        ta.value = JSON.stringify(value);
        ta.dataset.field = field; ta.dataset.kind = "json";
        row.appendChild(ta);
      }
      box.appendChild(row);
    });
  }

  function collectParams() {
    var params = {};
    var inputs = $("params-form").querySelectorAll("[data-field]");
    for (var i = 0; i < inputs.length; i++) {
      var node = inputs[i];
      var field = node.dataset.field, kind = node.dataset.kind;
      if (kind === "bool") params[field] = node.checked;
      else if (kind === "enum") params[field] = node.value;
      else if (kind === "int") params[field] = Number(node.value);
      else params[field] = JSON.parse(node.value);
    }
    return params;
  }

  function rerun() {
    var params;
    try { params = collectParams(); }
    catch (exc) { msg("参数 JSON 解析失败：" + exc.message); toast("参数 JSON 解析失败", "err"); return; }
    msg("现算中…");
    postJSON("/api/render", { experiment: currentExperiment, params: params })
      .then(function (r) {
        if (r.status !== 200) { msg(""); toast(r.data.error || "重算失败", "err"); return; }
        msg("已现算 " + r.data.frames.length + " 帧（未落盘）");
        setRecord(r.data);
      });
  }

  function saveRun() {
    var params;
    try { params = collectParams(); }
    catch (exc) { msg("参数 JSON 解析失败：" + exc.message); toast("参数 JSON 解析失败", "err"); return; }
    postJSON("/api/records", { experiment: currentExperiment, params: params })
      .then(function (r) {
        if (r.status !== 201) { toast(r.data.error || "保存失败", "err"); return; }
        msg("已存为 " + r.data.name);
        toast("已保存 " + r.data.name);
        refreshRecords();
        setRecord(r.data);
      });
  }

  // ------------------------------------------------ 演示回放库：每个引擎按默认参数各现算一份
  function buildDemoLibrary() {
    var btn = $("btn-demo-lib");
    btn.disabled = true;
    fetch("/api/records").then(function (r) { return r.json(); }).then(function (data) {
      var experiments = data.experiments || [];
      if (!experiments.length) { toast("没有可用实验", "err"); btn.disabled = false; return; }
      var done = 0, failed = 0;
      experiments.forEach(function (exp) {
        fetch("/api/params/" + encodeURIComponent(exp))
          .then(function (r) { return r.json(); })
          .then(function (schema) {
            var params = {};
            Object.keys(schema.schema || {}).forEach(function (field) {
              params[field] = schema.schema[field].default;
            });
            return postJSON("/api/records", { experiment: exp, params: params });
          })
          .then(function (r) {
            done += 1;
            if (r.status !== 201) failed += 1;
            if (done === experiments.length) {
              toast(failed ? ("回放库生成完成，" + failed + " 份失败")
                           : ("回放库已生成：" + done + " 份记录（每引擎一份）"));
              btn.disabled = false;
              refreshRecords();
            }
          });
      });
    });
  }
  on("btn-demo-lib", buildDemoLibrary);
  on("nav-demo-lib", buildDemoLibrary);

  // ------------------------------------------------ 播放器状态
  function setRecord(rec) {
    record = rec;
    t = 0;
    $("player").hidden = false;
    $("rec-title").textContent = rec.title;
    $("rec-meta").textContent = rec.experiment + " · " + rec.frames.length + " 帧 · "
      + rec.engine + (rec.notes ? " · " + rec.notes : "");
    $("slider").max = String(rec.frames.length - 1);
    $("slider").value = "0";
    stop();
    draw();
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; $("btn-play").textContent = "▶ 播放"; }
  }

  function togglePlay() {
    if (!record) return;
    if (timer) { stop(); return; }
    if (t >= record.frames.length - 1) t = 0;
    $("btn-play").textContent = "⏸ 暂停";
    timer = setInterval(function () {
      if (t >= record.frames.length - 1) { stop(); return; }
      t += 1; draw();
    }, 450);
  }

  function goto(frame) {
    if (!record) return;
    stop();
    t = Math.max(0, Math.min(frame, record.frames.length - 1));
    draw();
  }

  // ------------------------------------------------ 渲染分发
  var RENDERERS = { "b12-dijkstra": renderDijkstra,
                    "b12-knapsack": renderKnapsack,
                    "b34-astar": renderAstar };

  // ECharts 助手（2026-10-11 回放图表化）：实例跟随 stage 逐帧重建——
  // stage.textContent="" 会移除旧容器，实例必须跟着 dispose，否则泄漏。
  // 回放每 450ms 一帧，动画关掉保证帧与帧干净切换。
  var CHART = null;
  function chartIn(stage, height) {
    if (CHART) { CHART.dispose(); CHART = null; }
    if (!window.echarts) return null;
    var box = el("div");
    box.style.cssText = "width:100%;height:" + (height || 260) + "px";
    stage.appendChild(box);
    CHART = window.echarts.init(box);
    return CHART;
  }
  window.addEventListener("resize", function () { if (CHART) CHART.resize(); });

  function draw() {
    if (!record) return;
    var frame = record.frames[t];
    var stage = $("stage");
    stage.textContent = "";
    var renderer = RENDERERS[record.experiment];
    if (renderer) renderer(stage, frame, t);
    else stage.appendChild(el("pre", "code", JSON.stringify(frame.state, null, 2)));
    $("frame-caption").textContent = frame.caption;
    $("pos").textContent = "第 " + (t + 1) + " / " + record.frames.length + " 帧";
    $("slider").value = String(t);
  }

  function renderDijkstra(stage, frame) {
    var dist = frame.state.dist || [];
    var settled = frame.state.settled || [];
    var current = frame.state.current;
    var c = chartIn(stage, 280);
    if (!c) { stage.appendChild(el("p", "note", "ECharts 未加载（assets 缺失）")); return; }
    var labels = dist.map(function (_, v) { return "v" + v; });
    var maxDist = 0;
    dist.forEach(function (d) { if (d !== null) maxDist = Math.max(maxDist, d); });
    var data = dist.map(function (d, v) {
      if (d === null) {
        return { value: 0, itemStyle: { color: "transparent" },
                 label: { show: true, position: "top", formatter: "∞",
                          color: "#94a3b8", fontSize: 13 } };
      }
      var color = v === current ? "#f59e0b"
        : (settled.indexOf(v) >= 0 ? "#2563eb" : "#94a3b8");
      return { value: d, itemStyle: { color: color, borderRadius: [4, 4, 0, 0] } };
    });
    c.setOption({
      animation: false,
      grid: { left: 48, right: 24, top: 40, bottom: 36 },
      tooltip: { trigger: "axis",
        formatter: function (ps) {
          var p = ps[0];
          var d = dist[ps[0].dataIndex];
          var state = ps[0].dataIndex === current ? "★ 本轮确定"
            : (settled.indexOf(ps[0].dataIndex) >= 0 ? "已确定" : "待定");
          return p.name + "　" + state + "<br/>距离：" + (d === null ? "∞" : d);
        } },
      xAxis: { type: "category", data: labels },
      yAxis: { type: "value", minInterval: 1, name: "距离" },
      series: [{ type: "bar", data: data, barMaxWidth: 46,
                 label: { show: true, position: "top", fontSize: 12 } }]
    });
    stage.appendChild(el("p", "note",
      "蓝=已确定 · 橙=本轮确定 · 灰=待定（∞ 为尚不可达）——距离随播放逐步收敛。"));
  }

  function renderKnapsack(stage, frame) {
    // 末帧只有 chosen/best 没有 rows（引擎口径）——向前找最近带表的帧，
    // 让最后一画面停留在"完整 DP 表 + 选中结论"上，而不是一张空图。
    var state = frame.state;
    if (!state.rows) {
      for (var i = t; i >= 0; i--) {
        if (record.frames[i].state.rows) { state = record.frames[i].state; break; }
      }
    }
    var rows = state.rows || [];
    var weights = record.params.weights || [];
    var capacity = rows.length ? rows[0].length - 1 : 0;
    var c = chartIn(stage, 300);
    if (!c) { stage.appendChild(el("p", "note", "ECharts 未加载（assets 缺失）")); return; }
    var yLabels = rows.map(function (_, i) {
      return i === 0 ? "（无）" : "第" + (i - 1) + "件 w" + weights[i - 1];
    });
    var data = [];
    var maxV = 0;
    rows.forEach(function (row, i) {
      row.forEach(function (value, w) {
        data.push([w, i, value]);
        if (value > maxV) maxV = value;
      });
    });
    var option = {
      animation: false,
      grid: { left: 90, right: 90, top: 36, bottom: 44 },
      tooltip: { formatter: function (ps) {
        return ps.value[0] === 0 ? "不放任何物品" :
          "容量 " + ps.value[0] + " · 前 " + ps.value[1] + " 件 · 最优价值 " + ps.value[2];
      } },
      xAxis: { type: "category", name: "容量", data:
        Array.from({ length: capacity + 1 }, function (_, w) { return String(w); }) },
      yAxis: { type: "category", data: yLabels, inverse: true },
      visualMap: { min: 0, max: Math.max(maxV, 1), calculable: false, orient: "vertical",
        right: 8, top: "center", itemHeight: 120,
        inRange: { color: ["#eff6ff", "#93c5fd", "#2563eb"] },
        text: ["最优价值", "0"], textStyle: { fontSize: 11 } },
      series: [{ type: "heatmap", data: data, label: { show: true, fontSize: 11 } }]
    };
    if (typeof state.item === "number" && state.item >= 0) {
      option.series[0].markArea = { silent: true, itemStyle: { color: "rgba(244,63,94,.10)" },
        data: [[{ yAxis: state.item + 1 }, { yAxis: state.item + 1 }]] };
      option.tooltip.formatter = function (ps) {
        return "容量 " + ps.value[0] + " · 前 " + ps.value[1] + " 件 · 最优价值 " + ps.value[2];
      };
    }
    c.setOption(option);
    if (frame.state.chosen) {
      stage.appendChild(el("p", "note", "选中物品：" + frame.state.chosen.join("、")
        + "，最优价值 " + frame.state.best));
    }
  }

  function renderAstar(stage, frame) {
    var state = frame.state;
    var params = record.params;
    var cell = 26;
    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", params.width * cell);
    svg.setAttribute("height", params.height * cell);
    svg.setAttribute("class", "maze");
    var walls = {};
    (params.walls || []).forEach(function (c) { walls[c[0] + "," + c[1]] = true; });
    var expandedSet = {};
    (state.expanded || []).forEach(function (c, i) { expandedSet[c[0] + "," + c[1]] = i; });
    var pathSet = {};
    var last = t === record.frames.length - 1;
    if (last && record.metrics.path) {
      record.metrics.path.forEach(function (c) { pathSet[c[0] + "," + c[1]] = true; });
    }
    for (var y = 0; y < params.height; y++) {
      for (var x = 0; x < params.width; x++) {
        var key = x + "," + y;
        var rect = document.createElementNS(svgNS, "rect");
        rect.setAttribute("x", x * cell); rect.setAttribute("y", y * cell);
        rect.setAttribute("width", cell - 1); rect.setAttribute("height", cell - 1);
        var cls = "cell";
        if (walls[key]) cls += " wall";
        else if (expandedSet[key] !== undefined) cls += " expanded";
        if (pathSet[key]) cls += " path";
        if (key === params.start.join(",")) cls += " start";
        if (key === params.goal.join(",")) cls += " goal";
        if (state.current && key === state.current[0] + "," + state.current[1]) cls += " current";
        rect.setAttribute("class", cls);
        svg.appendChild(rect);
      }
    }
    stage.appendChild(svg);
    if (last && record.metrics.found) {
      stage.appendChild(el("p", "note", "到达目标：代价 " + record.metrics.cost
        + "，共展开 " + record.metrics.expanded_count + " 格（路径已描绿）"));
    }
  }

  // ------------------------------------------------ 控制条与导航
  on("btn-render", rerun);
  on("btn-save", saveRun);
  // M1 分享链接（2026-10-07）：把当前实验+参数编进 URL hash，打开即回放
  on("btn-share", function () {
    var params;
    try { params = collectParams(); }
    catch (exc) { toast("参数 JSON 解析失败，无法分享", "err"); return; }
    var url = location.origin + "/#exp=" + encodeURIComponent(currentExperiment) +
      "&params=" + encodeURIComponent(JSON.stringify(params));
    function done() { toast("分享链接已复制，打开即回放本次参数"); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, function () {
        window.prompt("复制下面的分享链接：", url);       // 剪贴板不可用就亮出原文
      });
    } else {
      window.prompt("复制下面的分享链接：", url);
    }
  });
  $("btn-load-legacy") && null;
  on("btn-play", togglePlay);
  on("btn-first", function () { goto(0); });
  on("btn-prev", function () { goto(t - 1); });
  on("btn-next", function () { goto(t + 1); });
  on("btn-last", function () { goto(record ? record.frames.length - 1 : 0); });
  $("slider").addEventListener("input", function () { goto(Number(this.value)); });
  $("experiment-list").addEventListener("change", function () {
    loadSchema(this.value);
  });
  document.querySelectorAll(".side-link[data-nav]").forEach(function (a) {
    a.addEventListener("click", function () {
      document.querySelectorAll(".side-link[data-nav]").forEach(function (x) {
        x.classList.remove("active");
      });
      a.classList.add("active");
      $("crumb-page").textContent = a.textContent.replace(/^[①②]\s*/, "").replace(/\d+$/, "").trim();
    });
  });

  function loadRecord(name) {
    fetch("/api/records/" + encodeURIComponent(name)).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (r) {
      if (r.status !== 200) { toast(r.data.error || "载入失败", "err"); return; }
      setRecord(r.data);
      toast("已载入 " + name);
    });
  }

  // 初始化：填实验下拉 → 载第一个的表单 → 自动重算一次（页面一打开就有东西看）。
  // M1：若 URL hash 带 #exp=…&params=…（分享链接），优先按它复原实验与参数。
  function parseShareHash() {
    var hash = (location.hash || "").replace(/^#/, "");
    if (!hash) return null;
    var kv = {};
    hash.split("&").forEach(function (pair) {
      var eq = pair.indexOf("=");
      if (eq > 0) kv[pair.slice(0, eq)] = decodeURIComponent(pair.slice(eq + 1));
    });
    if (!kv.exp) return null;
    var preset = null;
    if (kv.params) {
      try { preset = JSON.parse(kv.params); }
      catch (exc) { return null; }                    // 坏参数当没有，走默认初始化
      if (!preset || typeof preset !== "object" || Array.isArray(preset)) return null;
    }
    return { exp: kv.exp, preset: preset };
  }
  fetch("/api/records").then(function (r) { return r.json(); }).then(function (data) {
    var exp = $("experiment-list");
    exp.textContent = "";
    (data.experiments || []).forEach(function (name) {
      var opt = el("option", "", name); opt.value = name;
      exp.appendChild(opt);
    });
    refreshRecords();
    var shared = parseShareHash();
    if (shared && (data.experiments || []).indexOf(shared.exp) >= 0) {
      exp.value = shared.exp;                         // 下拉跟着分享链接走
      loadSchema(shared.exp, shared.preset).then(rerun);
      return;
    }
    if (data.experiments && data.experiments.length) {
      currentExperiment = data.experiments[0];
      loadSchema(currentExperiment).then(rerun);
    }
  });
})();
