/* LinkBox 产品页脚本：只做表单与渲染，业务判定全部在服务端。 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function showErr(box, text) {
    box.textContent = text;
    box.classList.add("err");
    box.hidden = false;
  }
  function showOk(box, nodes) {
    box.textContent = "";
    nodes.forEach(function (n) { box.appendChild(n); });
    box.classList.remove("err");
    box.hidden = false;
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    });
  }
  function getJSON(url) {
    return fetch(url).then(function (resp) {
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    });
  }

  // ------------------------------------------------ 短链
  function refreshLinks() {
    getJSON("/api/links").then(function (r) {
      var list = $("link-list");
      list.textContent = "";
      (r.data.links || []).slice(0, 10).forEach(function (item) {
        var li = el("li");
        var left = el("span");
        var a = el("a", "", "/" + item.code);
        a.href = "/" + item.code;
        left.appendChild(a);
        left.appendChild(el("span", "note", "  → " + item.target));
        li.appendChild(left);
        li.appendChild(el("span", "note", item.hits + " 次"));
        // L3 删除管理（2026-10-07）：逐行删除入口，确认后调 DELETE /api/links/<code>
        var del = el("button", "btn-del", "删除");
        del.type = "button";
        del.addEventListener("click", function () {
          if (!window.confirm("删除短链 /" + item.code + "？删除后链接即刻失效。")) return;
          fetch("/api/links/" + encodeURIComponent(item.code), { method: "DELETE" })
            .then(function (resp) {
              if (resp.status === 204) { refreshLinks(); return; }
              return resp.json().then(function (data) {
                showErr($("link-result"), data.error || ("删除失败 " + resp.status));
              });
            })
            .catch(function () { showErr($("link-result"), "网络错误，请重试。"); });
        });
        li.appendChild(del);
        list.appendChild(li);
      });
      if (!list.children.length) list.appendChild(el("li", "note", "（还没有链接）"));
    });
  }

  $("link-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var box = $("link-result");
    post("/api/links", {
      url: $("link-url").value,
      alias: $("link-alias").value || null
    }).then(function (r) {
      if (!r.ok) { showErr(box, r.data.error || ("失败 " + r.status)); return; }
      var a = el("a", "", r.data.short_url);
      a.href = r.data.short_url;
      showOk(box, [el("b", "", "短链已创建："), a,
                   el("span", "note", "  目标 " + r.data.target)]);
      refreshLinks();
    });
  });

  // ------------------------------------------------ 暂存
  $("stash-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var box = $("stash-result");
    var body = {
      content: $("stash-content").value,
      ttl_hours: Number($("stash-ttl").value)
    };
    var pass = $("stash-pass").value;
    if (pass) body.passcode = pass;
    post("/api/stash", body).then(function (r) {
      if (!r.ok) { showErr(box, r.data.error || ("失败 " + r.status)); return; }
      var a = el("a", "", location.origin + r.data.url);
      a.href = r.data.url;
      var note = r.data.protected ? "  已设口令，打开需先输入" : "  到期即清除，凭链接查看";
      showOk(box, [el("b", "", "已暂存："), a, el("span", "note", note)]);
      $("stash-content").value = "";
      $("stash-pass").value = "";
    });
  });

  // ------------------------------------------------ 文件互传（轮八）
  $("file-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var box = $("file-result");
    var file = $("file-input").files[0];
    if (!file) { showErr(box, "先选一个文件。"); return; }
    var params = new URLSearchParams();
    params.set("name", file.name);
    params.set("ttl_hours", $("file-ttl").value);
    var pass = $("file-pass").value;
    if (pass) params.set("passcode", pass);
    box.textContent = "上传中…";
    box.hidden = false;
    fetch("/api/files?" + params.toString(), { method: "POST", body: file })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, status: resp.status, data: data };
        });
      })
      .then(function (r) {
        if (!r.ok) { showErr(box, r.data.error || ("失败 " + r.status)); return; }
        var a = el("a", "", location.origin + r.data.url);
        a.href = r.data.url;
        var size = r.data.size > 1048576
          ? (r.data.size / 1048576).toFixed(1) + " MB"
          : Math.max(1, Math.round(r.data.size / 1024)) + " KB";
        var note = (r.data.protected ? "已设口令，扫码后先输口令；" : "") +
          size + " · 扫码即下载，到期自动清除";
        var qrDl = el("a", "", "下载二维码");
        qrDl.href = r.data.url + "/qr.svg?download=1";     // L1 二维码下载
        qrDl.download = "qr-file-" + r.data.code + ".svg";
        showOk(box, [el("b", "", "已上传：" + r.data.name + " — "), a,
                     qrDl, el("span", "note", "  " + note)]);
        $("file-input").value = "";
        $("file-pass").value = "";
      })
      .catch(function () { showErr(box, "网络错误，请重试。"); });
  });

  // ------------------------------------------------ 统计（2026-10-11 ECharts 化）
  // 左：Top 短链命中横向条形；右：暂存/文件在存库存环图。数字与排行同源
  // /api/stats（stats + top + inventory），B31 引擎现算，本文件只做渲染。
  var STAT_CHARTS = {};
  function statChart(id) {
    if (!window.echarts) return null;
    if (!STAT_CHARTS[id]) STAT_CHARTS[id] = echarts.init($(id));
    return STAT_CHARTS[id];
  }
  function refreshStats() {
    getJSON("/api/stats").then(function (r) {
      var box = $("stats");
      box.textContent = "";
      var s = r.data.stats || {};
      var top = r.data.top || [];
      var inv = r.data.inventory || {};

      var barCard = el("div", "statchart");
      barCard.id = "stats-top";
      box.appendChild(barCard);

      var pieCard = el("div", "statchart");
      pieCard.id = "stats-inv";
      box.appendChild(pieCard);

      var bar = statChart("stats-top");
      if (bar) {
        var rows = top.map(function (item) {
          return { name: "/" + item.code, target: item.target, hits: item.hits };
        });
        bar.setOption({
          title: { text: "短链命中排行 Top " + rows.length,
                   left: 10, top: 6, textStyle: { fontSize: 13 } },
          grid: { left: 76, right: 40, top: 40, bottom: 24 },
          tooltip: {
            trigger: "item",
            formatter: function (p) {
              return p.name + " → " + p.data.target + "<br>命中 <b>" +
                p.value + "</b> 次";
            }
          },
          xAxis: { type: "value", minInterval: 1 },
          yAxis: {
            type: "category", inverse: true,
            data: rows.map(function (x) { return x.name; }),
            axisLabel: { fontSize: 11 }
          },
          series: [{
            type: "bar", barMaxWidth: 18,
            itemStyle: { color: "#2563eb", borderRadius: [0, 6, 6, 0] },
            label: { show: true, position: "right", fontSize: 11 },
            data: rows.map(function (x) {
              return { name: x.name, value: x.hits, target: x.target };
            })
          }]
        });
        if (!rows.length) {
          bar.setOption({ title: { text: "还没有短链——先去「短链」页创建一个。",
                                   left: 10, top: 6, textStyle: { fontSize: 13 } } });
        }
      }

      var pie = statChart("stats-inv");
      if (pie) {
        pie.setOption({
          title: { text: "在存库存", left: 10, top: 6, textStyle: { fontSize: 13 } },
          tooltip: { trigger: "item", formatter: "{b}：{c} 条（{d}%）" },
          legend: { bottom: 6, icon: "circle" },
          series: [{
            type: "pie", radius: ["42%", "68%"], center: ["50%", "52%"],
            label: { show: true, formatter: "{b} {c}", color: "#334155" },
            itemStyle: { borderRadius: 6, borderColor: "#fff", borderWidth: 2 },
            data: [
              { name: "短链", value: s.links || 0, itemStyle: { color: "#2563eb" } },
              { name: "文本暂存", value: inv.stashes || 0, itemStyle: { color: "#0d9488" } },
              { name: "文件", value: inv.files || 0, itemStyle: { color: "#f59e0b" } }
            ].filter(function (d) { return d.value > 0; })   // 0 值切片只剩图例，标签不悬空
          }]
        });
      }

      var note = el("p", "note", "短链 " + (s.links || 0) + " 条 · 命中累计 " +
        (s.total_hits || 0) + " 次 · 单链最高 " + (s.best_hits || 0) + " 次。");
      box.appendChild(note);
    });
  }

  // ------------------------------------------------ 选项卡（侧边栏导航 + hash 深链接）
  function activateTab(name) {
    var tab = document.querySelector('.tab[data-tab="' + name + '"]');
    if (!tab) { return false; }
    document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
    document.querySelectorAll(".tabpage").forEach(function (p) { p.hidden = true; });
    tab.classList.add("active");
    var page = $("tab-" + name);
    page.hidden = false;
    var crumb = document.getElementById("crumb-page");
    if (crumb) crumb.textContent = tab.textContent.trim();
    if (name === "links") refreshLinks();
    if (name === "stats") refreshStats();
    return true;
  }
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      activateTab(tab.dataset.tab);
    });
  });
  // hash 深链接（2026-10-07 走查：直开 /#stash 曾停在短链视图）
  function locFromHash() {
    var name = (location.hash || "").replace("#", "");
    if (!activateTab(name)) { activateTab("links"); }
  }
  window.addEventListener("hashchange", locFromHash);
  locFromHash();
})();
