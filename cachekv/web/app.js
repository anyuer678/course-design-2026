/* CacheKV 控制台（UI 2.1，生产控制台形态）：
   侧边栏导航 / 搜索过滤 / 排序 / 键详情抽屉 / Toast / 读取趋势曲线 / uptime。
   判定全在服务端；本文件只做调用与渲染。 */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function show(data) { $("out").textContent = JSON.stringify(data, null, 2); }

  // ---------------- Toast（替代 alert / 状态写脸）
  function toast(msg, kind) {
    var t = el("div", "toast " + (kind || "ok"), msg);
    $("toast-wrap").appendChild(t);
    setTimeout(function () { t.classList.add("out"); }, 2400);
    setTimeout(function () { t.remove(); }, 2800);
  }

  // ---------------- 工具
  function fmtTTL(sec) {
    if (sec === null || sec === undefined) return "永久";
    if (sec < 0) return "过期中";
    sec = Math.floor(sec);                              // 进位用 floor：不出现 "1m60s"
    if (sec < 60) return sec + "s";
    if (sec < 3600) {
      return Math.floor(sec / 60) + "m" + String(sec % 60).padStart(2, "0") + "s";
    }
    return Math.floor(sec / 3600) + "h" +
      String(Math.floor((sec % 3600) / 60)).padStart(2, "0") + "m";
  }
  function fmtBytes(n) { return n < 1024 ? n + " B" : (n / 1024).toFixed(1) + " KB"; }
  function fmtUptime(sec) {
    if (sec === null || sec === undefined) return "—";
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return h ? ("已运行 " + h + "h " + m + "m") : ("已运行 " + Math.max(1, Math.floor(sec / 60)) + "m");
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast("已复制到剪贴板"); })
        .catch(function () { fallbackCopy(text); });
    } else {
      fallbackCopy(text);
    }
  }
  function fallbackCopy(text) {
    var ta = el("textarea"); ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    toast(ok ? "已复制到剪贴板" : "复制失败——请手动选择文本", ok ? "ok" : "err");
  }

  // ---------------- 主题（仅浅色，保留结构以便未来扩展）
  // ---------------- 状态
  var STATE = { overview: null, filter: "all", sort: "ttl", search: "" };
  var SERIES = [];                                    // 读取趋势采样
  var LAST_HITS = null, LAST_MISSES = null;

  // ---------------- ECharts 资产（2026-10-11 渲染层升级）
  // 本地化 echarts.min.js（webkit/ 同步进 assets，不走 CDN，页面保持离线可开）；
  // 资产缺失时 getChart 返回 null，调用方降级成文字，绝不抛错瘫痪整页。
  var _charts = {};
  function getChart(id) {
    if (!window.echarts) return null;
    var node = $(id);
    if (!node) return null;
    if (!_charts[id]) {
      _charts[id] = window.echarts.init(node);
      if (!_charts._resized) {
        _charts._resized = true;
        window.addEventListener("resize", function () {
          Object.keys(_charts).forEach(function (k) {
            if (_charts[k] && _charts[k].resize) _charts[k].resize();
          });
        });
      }
    }
    return _charts[id];
  }

  // ---------------- 键过滤 / 排序 / 分页
  function visibleKeys() {
    var keys = (STATE.overview && STATE.overview.keys) || [];
    var q = STATE.search.toLowerCase();
    return keys.filter(function (k) {
      if (STATE.filter === "ttl" && k.ttl === null) return false;
      if (STATE.filter === "forever" && k.ttl !== null) return false;
      if (q && k.key.toLowerCase().indexOf(q) < 0) return false;
      return true;
    }).sort(function (a, b) {
      if (STATE.sort === "size") return b.size - a.size;
      if (STATE.sort === "key") return a.key < b.key ? -1 : 1;
      var at = a.ttl === null ? Infinity : a.ttl, bt = b.ttl === null ? Infinity : b.ttl;
      return at - bt;
    });
  }
  var PAGE_SIZE = 12, page = 1;

  // ---------------- 抽屉
  function openDrawer(key) {
    fetch("/api/kv/" + encodeURIComponent(key)).then(function (r) {
      return r.text().then(function (t) { return { status: r.status, t: t }; });
    }).then(function (r) {
      var rec = null;
      (STATE.overview.keys || []).forEach(function (k) { if (k.key === key) rec = k; });
      $("drawer-key").textContent = key;
      $("drawer-value").textContent = r.status === 200 ? r.t
        : ("（读取失败 HTTP " + r.status + "：键可能刚过期）");
      var meta = $("drawer-meta");
      meta.textContent = "";
      [[ "大小", rec ? fmtBytes(rec.size) : "—" ],
       ["剩余 TTL", rec ? fmtTTL(rec.ttl) : "—"],
       ["过期时刻", rec && rec.expires_at ? new Date(rec.expires_at * 1000).toLocaleString() : "永不"]]
        .forEach(function (p) {
          meta.appendChild(el("dt", null, p[0]));
          meta.appendChild(el("dd", null, p[1]));
        });
      $("drawer-del").onclick = function () { doDel(key); closeDrawer(); };
      $("drawer-copy").onclick = function () { copyText(r.status === 200 ? r.t : ""); };
      document.body.classList.add("drawer-open");
    });
  }
  function closeDrawer() { document.body.classList.remove("drawer-open"); }
  $("drawer-mask").addEventListener("click", closeDrawer);
  $("drawer-close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeDrawer();
  });

  // ---------------- 趋势曲线（客户端采样；2026-10-11 换 ECharts 渲染）
  function drawSpark() {
    var c = getChart("sparkline");
    $("spark-note").textContent = (window.echarts
      ? "蓝=命中增量（面积）  红=未命中增量（每 2s 采样，纵轴自动缩放，悬浮可读数）"
      : "ECharts 未加载——趋势曲线已降级。");
    if (!c) return;
    if (SERIES.length < 2) { c.clear(); return; }
    var xs = SERIES.map(function (p) {
      return new Date(p.t).toLocaleTimeString("zh-CN", { hour12: false });
    });
    c.setOption({
      animation: false,                               // 2s 轮询刷新，关动画防闪烁
      grid: { left: 44, right: 16, top: 24, bottom: 26 },
      tooltip: { trigger: "axis" },
      legend: { data: ["命中/2s", "未命中/2s"], top: 0, textStyle: { fontSize: 11 } },
      xAxis: { type: "category", data: xs, axisLabel: { fontSize: 10 } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 10 } },
      series: [
        { name: "命中/2s", type: "line", smooth: true, showSymbol: false,
          data: SERIES.map(function (p) { return p.dHits; }),
          lineStyle: { width: 2, color: "#2563eb" },
          areaStyle: { color: "rgba(37,99,235,.10)" } },
        { name: "未命中/2s", type: "line", smooth: true, showSymbol: false,
          data: SERIES.map(function (p) { return p.dMiss; }),
          lineStyle: { width: 2, color: "#f43f5e", type: "dashed" } }
      ]
    });
  }

  // ---------------- 总览刷新（2s）
  function refresh() {
    fetch("/api/overview").then(function (r) { return r.json(); }).then(function (d) {
      STATE.overview = d;
      var s = d.stats || {};
      var keys = d.keys || [];
      $("t-keys").textContent = String(s.keys);
      $("t-keys-sub").textContent = keys.length
        ? "最短 TTL " + fmtTTL((keys[0] || {}).ttl) : "空库";
      $("t-hits").textContent = String(s.hits);
      $("t-misses").textContent = String(s.misses);
      $("t-sets").textContent = String(s.sets);
      $("t-snaps").textContent = String(s.snapshots_saved);
      $("t-snaps-sub").textContent = (d.snapshot && d.snapshot.dirty) ? "有待写入" : "已持久化";
      $("nav-key-cnt").textContent = String(s.keys);

      var rate = s.hit_rate;
      var pct = (rate === null || rate === undefined) ? null : Math.round(rate * 100);
      var g = getChart("donut");
      if (g) {
        g.setOption({
          animation: false,
          series: [{
            type: "gauge", startAngle: 210, endAngle: -30, min: 0, max: 100,
            radius: "95%", center: ["50%", "58%"],
            progress: { show: true, width: 12, itemStyle: { color: "#2563eb" } },
            axisLine: { lineStyle: { width: 12, color: [[1, "#e5e7eb"]] } },
            axisTick: { show: false }, splitLine: { show: false },
            axisLabel: { show: false }, pointer: { show: false }, anchor: { show: false },
            detail: {
              valueAnimation: false, fontSize: 22, fontWeight: 750,
              offsetCenter: [0, "-8%"], formatter: pct === null ? "—" : "{value}%"
            },
            data: [{ value: pct === null ? 0 : pct }]
          }]
        });
      }
      $("donut-note").textContent = (s.gets || 0) === 0
        ? "读取为 0。注入演示数据或执行 GET 后开始记账。"
        : "共 " + s.gets + " 次读取：" + s.hits + " 命中 / " + s.misses + " 未命中。";

      var snap = d.snapshot || {};
      $("snap-path").textContent = snap.path || "（未配置）";
      $("snap-state").textContent = "";
      $("snap-state").appendChild(el("span", "pill " + (snap.dirty ? "warn" : "ok"),
        snap.dirty ? "有待写入" : "已持久化"));
      $("snap-bytes").textContent = (s.snapshot_bytes || 0) + " B";

      $("foot-uptime").textContent = fmtUptime(d.uptime_sec);
      $("foot-state").className = "badge-dot";
      $("foot-state").textContent = "运行中";
      STATE.offline_toasted = false;
      $("live-dot").className = "dot";
      $("hero-live") && ($("hero-live").textContent = "● 服务在线");

      // K2：TTL 分布条（服务器权威数据；倒计时只在两次刷新之间本地推算）
      renderTtlDist(keys);

      // 趋势采样
      if (LAST_HITS !== null) {
        SERIES.push({ t: Date.now(),
                      dHits: Math.max(0, s.hits - LAST_HITS),
                      dMiss: Math.max(0, s.misses - LAST_MISSES) });
        if (SERIES.length > 90) SERIES.shift();
        drawSpark();
      }
      LAST_HITS = s.hits; LAST_MISSES = s.misses;

      renderKeys();
    }).catch(function () {
      $("live-dot").className = "dot off";
      $("foot-state").className = "badge-dot err";
      $("foot-state").textContent = "失联";
      if (!STATE.offline_toasted) {
        STATE.offline_toasted = true;
        toast("服务失联——每 2s 自动重试", "err");
      }
    });
  }

  // ---------------- 键空间表
  // K2 TTL 剩余可视化（2026-10-07 引入，2026-10-11 换 ECharts 堆叠条）：
  // 服务器权威数据；倒计时只在两次刷新之间本地推算（expires_at 本地推算）
  function renderTtlDist(keys) {
    var box = $("ttl-dist");
    if (!box) return;                                  // 安全绑定：缺元素只降级
    var soon = 0, short = 0, long = 0, forever = 0;
    keys.forEach(function (k) {
      if (k.ttl === null || k.ttl === undefined) forever += 1;
      else if (k.ttl < 60) soon += 1;
      else if (k.ttl < 300) short += 1;
      else long += 1;
    });
    var total = keys.length;
    box.hidden = total === 0;
    var c = getChart("ttl-dist-bar");
    if (!c) return;
    if (!total) { c.clear(); return; }
    c.setOption({
      animation: false,
      grid: { left: 8, right: 8, top: 24, bottom: 4, containLabel: false },
      tooltip: { trigger: "axis", axisPointer: { type: "none" } },
      legend: { top: 0, textStyle: { fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
      xAxis: { type: "value", show: false },
      yAxis: { type: "category", data: [""], show: false },
      series: [
        { name: "即将过期 <1m", type: "bar", stack: "ttl", barWidth: 14,
          itemStyle: { color: "#f43f5e" }, data: [soon] },
        { name: "5 分钟内", type: "bar", stack: "ttl",
          itemStyle: { color: "#f59e0b" }, data: [short] },
        { name: "更长", type: "bar", stack: "ttl",
          itemStyle: { color: "#2563eb" }, data: [long] },
        { name: "永久", type: "bar", stack: "ttl",
          itemStyle: { color: "#8b5cf6" }, data: [forever] }
      ]
    });
  }
  function tickCountdown() {
    var keys = (STATE.overview && STATE.overview.keys) || [];
    var live = keys.some(function (k) { return k.expires_at; });
    if (!live) return;                                 // 全是永久键就不必重画
    var now = Date.now() / 1000;
    keys.forEach(function (k) {
      if (k.expires_at) k.ttl = k.expires_at - now;    // 负数=刚过期，下轮刷新会被服务端摘除
    });
    renderKeys();
  }
  function renderKeys() {
    var keys = visibleKeys();
    var rows = $("key-rows");
    rows.textContent = "";
    var total = keys.length;
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > pages) page = pages;
    var slice = keys.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    $("ks-count").textContent = (STATE.overview.stats.keys) + " 存活 / 显示 " + total;
    $("empty-hint").hidden = total > 0;
    $("page-note").textContent = total > PAGE_SIZE
      ? ("第 " + page + " / " + pages + " 页（每页 " + PAGE_SIZE + " 条）") : "";

    slice.forEach(function (k) {
      var tr = el("tr");
      tr.addEventListener("click", function () { openDrawer(k.key); });
      tr.appendChild(el("td", "", "")).appendChild(el("span", "kbd", k.key));
      tr.appendChild(el("td", "time", fmtBytes(k.size)));
      var ttl = el("td");
      ttl.appendChild(el("span",
        "pill " + (k.ttl === null ? "violet" : (k.ttl < 60 ? "err" : (k.ttl < 300 ? "warn" : "info"))),
        fmtTTL(k.ttl)));
      tr.appendChild(ttl);
      var ops = el("td");
      var del = el("button", "btn btn-danger btn-xs", "删除");
      del.addEventListener("click", function (ev) { ev.stopPropagation(); doDel(k.key); });
      ops.appendChild(del);
      tr.appendChild(ops);
      rows.appendChild(tr);
    });

    if (pages > 1) {
      var pager = el("tr");
      var ptd = el("td", "note", "");
      ptd.colSpan = 4;
      if (page > 1) {
        var prev = el("button", "btn btn-ghost btn-xs", "上一页");
        prev.addEventListener("click", function (ev) { ev.stopPropagation(); page--; renderKeys(); });
        ptd.appendChild(prev); ptd.appendChild(document.createTextNode(" "));
      }
      ptd.appendChild(el("span", "time", " 第 " + page + " / " + pages + " 页 "));
      if (page < pages) {
        var next = el("button", "btn btn-ghost btn-xs", "下一页");
        next.addEventListener("click", function (ev) { ev.stopPropagation(); page++; renderKeys(); });
        ptd.appendChild(next);
      }
      pager.appendChild(ptd);
      rows.appendChild(pager);
    }
  }

  // ---------------- 命令行
  function needKey() {
    var key = $("key").value;
    if (!key) { toast("键名不能为空", "err"); return null; }
    return key;
  }
  function doPut() {
    var key = needKey();
    if (!key) return;
    var qs = $("ttl").value ? ("?ttl=" + encodeURIComponent($("ttl").value)) : "";
    fetch("/api/kv/" + encodeURIComponent(key) + qs, {
      method: "PUT", headers: { "Content-Type": "text/plain" },
      body: $("value").value
    }).then(function (r) {
      return r.text().then(function (t) {
        show({ op: "SET", key: key, status: r.status });
        toast(r.status === 201 || r.status === 200 ? "SET " + key : "SET 失败（" + r.status + "）",
              r.status < 400 ? "ok" : "err");
        refresh();
      });
    });
  }
  function doGet(key) {
    key = key || needKey();
    if (!key) return;
    fetch("/api/kv/" + encodeURIComponent(key)).then(function (r) {
      return r.text().then(function (t) {
        show({ op: "GET", key: key, status: r.status, value: r.status === 200 ? t : undefined });
        toast(r.status === 200 ? "GET " + key + " 命中" : "GET " + key + " 未命中（" + r.status + "）",
              r.status === 200 ? "ok" : "err");
        refresh();
      });
    });
  }
  function doDel(key) {
    key = key || needKey();
    if (!key) return;
    fetch("/api/kv/" + encodeURIComponent(key), { method: "DELETE" })
      .then(function (r) {
        show({ op: "DEL", key: key, status: r.status });
        toast(r.status === 204 ? "DEL " + key : "DEL 未命中（" + r.status + "）",
              r.status === 204 ? "ok" : "err");
        refresh();
      });
  }
  function doSave() {
    fetch("/api/save", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) { show({ op: "SAVE", saved_keys: d.saved }); toast("快照已写入（" + d.saved + " 键）"); refresh(); });
  }
  function doDemo() {
    fetch("/api/demo", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        show({ op: "DEMO", seeded_keys: d.seeded, hits: d.hits, misses: d.misses });
        toast("已注入 " + d.seeded + " 个演示键（命中 " + d.hits + " / 未命中 " + d.misses + "）");
        refresh();
      });
  }

  // 生产级防线：绑定缺失元素不抛错——单个 id 失配只降级该功能，绝不瘫痪整页
  function on(id, fn) {
    var node = $(id);
    if (node) node.addEventListener("click", fn);
    else if (window.console) console.warn("[cachekv] 缺少元素 #" + id + "（该入口已降级）");
  }
  on("btn-put", doPut);
  on("btn-get", function () { doGet(); });
  on("btn-del", function () { doDel(); });
  on("btn-demo", doDemo);   // 旧布局的 btn-save 快照入口已并入侧边栏 nav-save
  on("nav-demo", doDemo);
  on("nav-save", doSave);
  // ---------------- K1 键空间导入（导出走 /api/export 直链，无需 JS）
  var imp = $("import-file");
  if (imp) imp.addEventListener("change", function () {
    var f = imp.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () {
      fetch("/api/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: reader.result
      }).then(function (r) {
        return r.json().then(function (d) { return { status: r.status, d: d }; });
      }).then(function (r) {
        if (r.status !== 200) { toast((r.d && r.d.error) || "导入失败", "err"); return; }
        toast("已导入 " + r.d.imported + " 键（跳过 " + r.d.skipped + "）");
        refresh();
      });
    };
    reader.readAsText(f);
    imp.value = "";
  });
  on("drawer-mask", closeDrawer);
  on("drawer-close", closeDrawer);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeDrawer();
  });
  $("search").addEventListener("input", function () {
    STATE.search = this.value.trim(); page = 1; renderKeys();
  });
  document.querySelectorAll(".chip[data-filter]").forEach(function (c) {
    c.addEventListener("click", function () {
      document.querySelectorAll(".chip[data-filter]").forEach(function (x) {
        x.classList.remove("active");
      });
      c.classList.add("active");
      STATE.filter = c.dataset.filter; page = 1; renderKeys();
    });
  });
  $("sort").addEventListener("change", function () { STATE.sort = this.value; renderKeys(); });

  // 侧边导航高亮
  document.querySelectorAll(".side-link[data-nav]").forEach(function (a) {
    a.addEventListener("click", function () {
      document.querySelectorAll(".side-link").forEach(function (x) { x.classList.remove("active"); });
      a.classList.add("active");
      $("crumb-page").textContent = a.textContent.replace(/\d+$/, "").trim();
    });
  });

  refresh();
  setInterval(refresh, 2000);
  setInterval(tickCountdown, 1000);   // K2：秒级倒计时（每秒由 expires_at 本地推算）
})();
