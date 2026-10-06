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
  function loadSchema(experiment) {
    currentExperiment = experiment;
    return fetch("/api/params/" + encodeURIComponent(experiment))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentSchema = data.schema;
        buildForm(data.schema);
        msg("");
      });
  }

  function buildForm(schema) {
    var box = $("params-form");
    box.textContent = "";
    Object.keys(schema).forEach(function (field) {
      var spec = schema[field];
      var row = el("div", "prow");
      row.appendChild(el("label", "plabel", spec.label || field));
      var value = spec.default;
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
    var table = el("table", "grid");
    var head = el("tr");
    head.appendChild(el("th", "", "顶点"));
    head.appendChild(el("th", "", "当前估计距离"));
    head.appendChild(el("th", "", "状态"));
    table.appendChild(head);
    dist.forEach(function (d, v) {
      var tr = el("tr");
      tr.appendChild(el("td", "", "v" + v));
      tr.appendChild(el("td", "", d === null ? "∞" : String(d)));
      var stateText = settled.indexOf(v) >= 0 ? "已确定" : "待定";
      if (v === current) stateText = "★ 本轮确定";
      var cls = v === current ? "cur" : (settled.indexOf(v) >= 0 ? "settled" : "");
      tr.appendChild(el("td", cls, stateText));
      table.appendChild(tr);
    });
    stage.appendChild(table);
  }

  function renderKnapsack(stage, frame) {
    var rows = frame.state.rows || [];
    var weights = record.params.weights || [];
    var table = el("table", "grid");
    var head = el("tr");
    head.appendChild(el("th", "", "物品 \\ 容量"));
    var capacity = rows.length ? rows[0].length - 1 : 0;
    for (var w = 0; w <= capacity; w++) head.appendChild(el("th", "", String(w)));
    table.appendChild(head);
    rows.forEach(function (row, i) {
      var tr = el("tr");
      tr.appendChild(el("th", "", i === 0 ? "（无）" : "第" + (i - 1) + "件 w" + weights[i - 1]));
      row.forEach(function (value) { tr.appendChild(el("td", "", String(value))); });
      if (i === frame.state.item + 1) tr.className = "cur";
      table.appendChild(tr);
    });
    stage.appendChild(table);
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

  // 初始化：填实验下拉 → 载第一个的表单 → 自动重算一次（页面一打开就有东西看）
  fetch("/api/records").then(function (r) { return r.json(); }).then(function (data) {
    var exp = $("experiment-list");
    exp.textContent = "";
    (data.experiments || []).forEach(function (name) {
      var opt = el("option", "", name); opt.value = name;
      exp.appendChild(opt);
    });
    refreshRecords();
    if (data.experiments && data.experiments.length) {
      currentExperiment = data.experiments[0];
      loadSchema(currentExperiment).then(rerun);
    }
  });
})();
