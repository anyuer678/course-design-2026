/* DataScope 控制台（UI 2.1）：数据源 → 列画像 → 清洗配方 → 挖掘与 SVG 报告。
   判定全在服务端；本文件只做调用与渲染。
   挖掘参数与返回形状对齐 datascope/mining.py：apriori 需要 group_col/item_col，
   kmeans 需要 columns（数值列）；规则字段为 ante/cons。 */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function toast(msg, kind) {
    var t = el("div", "toast " + (kind || "ok"), msg);
    $("toast-wrap").appendChild(t);
    setTimeout(function () { t.classList.add("out"); }, 4200);   // 2026-10-07 走查：2.6s 易错过
    setTimeout(function () { t.remove(); }, 4600);
  }
  function on(id, fn) {
    var node = $(id);
    if (node) node.addEventListener("click", fn);
    else if (window.console) console.warn("[datascope] 缺少元素 #" + id);
  }

  var STATE = { csv: null, rows: 0, columns: [], numeric: [], recipe: [],
                cleanedCsv: null, reportUrl: null };
  var OPS_NEED_COL = { to_number: 1, drop_empty_rows: 1, fill_missing: 1, drop_column: 1 };
  var OP_LABEL = { drop_duplicates: "去重行", trim: "去首尾空格", to_number: "转数值",
                   drop_empty_rows: "删空行", fill_missing: "填充缺失", drop_column: "删列" };

  // ---------------- 侧边导航高亮
  document.querySelectorAll(".side-link[data-nav]").forEach(function (a) {
    a.addEventListener("click", function () {
      document.querySelectorAll(".side-link[data-nav]").forEach(function (x) {
        x.classList.remove("active");
      });
      a.classList.add("active");
      $("crumb-page").textContent = a.textContent.replace(/^[①②③④]\s*/, "").trim();
    });
  });

  // ---------------- 数据源
  function loadCsv(text, label) {
    if (!text || !text.trim()) { toast("CSV 为空", "err"); return; }
    fetch("/api/profile", {
      method: "POST", headers: { "Content-Type": "text/csv" }, body: text
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      if (r.status !== 200) { toast((r.d && r.d.error) || "解析失败", "err"); return; }
      STATE.csv = text;
      STATE.rows = r.d.rows;
      STATE.columns = Object.keys(r.d.profile);
      STATE.numeric = STATE.columns.filter(function (c) {
        return r.d.profile[c].type !== "text";
      });
      $("source-state").textContent = "已载入：" + (label || "粘贴内容") +
        "（" + r.d.rows + " 行 × " + STATE.columns.length + " 列）";
      $("foot-state").textContent = "已载入 " + r.d.rows + " 行";
      $("foot-state").className = "badge-dot";
      $("profile-state").textContent = r.d.rows + " 行";
      renderProfile(r.d.profile);
      fillColSelect(Object.keys(r.d.profile));
      fillMiningSelects(r.d.profile);
      toast("数据已载入（" + r.d.rows + " 行）");
    }).catch(function () { toast("网络错误", "err"); });
  }

  function renderProfile(profile) {
    var rows = $("profile-rows");
    rows.textContent = "";
    Object.keys(profile).forEach(function (name) {
      var p = profile[name];
      var tr = el("tr");
      tr.appendChild(el("td", "", "")).appendChild(el("span", "kbd", name));
      var kind = el("td");
      kind.appendChild(el("span", "pill " + (p.type === "text" ? "" : "info"), p.type));
      tr.appendChild(kind);
      var miss = el("td");
      miss.appendChild(el("span", "pill " + (p.missing ? "warn" : "ok"), String(p.missing)));
      tr.appendChild(miss);
      tr.appendChild(el("td", "time", String(p.distinct)));
      tr.appendChild(el("td", "time", p.min === null ? "—" : String(p.min)));
      tr.appendChild(el("td", "time", p.max === null ? "—" : String(p.max)));
      rows.appendChild(tr);
    });
  }

  function fillColSelect(columns) {
    var sel = $("op-col");
    sel.textContent = "";
    columns.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c; o.textContent = c;
      sel.appendChild(o);
    });
  }
  function fillMiningSelects(profile) {
    var cols = Object.keys(profile);
    [["ap-group"], ["ap-item"]].forEach(function (ids) {
      var sel = $(ids[0]);
      sel.textContent = "";
      cols.forEach(function (c) {
        var o = document.createElement("option");
        o.value = c; o.textContent = c;
        sel.appendChild(o);
      });
    });
    // 聚篮列默认第一列，商品列默认第二列（若无则同列）
    if (cols.length > 1) $("ap-item").value = cols[1];
    var km = $("km-cols");
    km.textContent = "";
    STATE.numeric.forEach(function (c) {
      var label = el("label", "chip", c);
      var box = document.createElement("input");
      box.type = "checkbox"; box.value = c; box.style.marginRight = ".3rem";
      if (STATE.numeric.indexOf(c) >= 0 && c !== "订单号") box.checked = true;
      label.insertBefore(box, label.firstChild);
      km.appendChild(label);
    });
    if (!STATE.numeric.length) km.appendChild(el("span", "note", "（无数值列）"));
  }

  $("file").addEventListener("change", function () {
    var f = this.files[0];
    if (!f) return;
    var reader = new FileReader();
    reader.onload = function () { loadCsv(String(reader.result), f.name); };
    reader.readAsText(f, "utf-8");
  });
  on("btn-load", function () { loadCsv($("csv-text").value, "粘贴内容"); });
  function loadSample() {
    fetch("/api/sample").then(function (r) { return r.text(); })
      .then(function (t) {
        $("csv-text").value = t;
        loadCsv(t, "内置示例（含重复/缺失/空格脏）");
      });
  }
  on("btn-sample", loadSample);
  on("btn-sample-card", loadSample);
  on("nav-sample", loadSample);

  // ---------------- 配方构建
  function syncOpUi() {
    var op = $("op").value;
    var needCol = !!OPS_NEED_COL[op];
    $("op-col").style.display = needCol ? "" : "none";
    $("op-param").style.display = op === "fill_missing" ? "" : "none";
    $("op-hint").textContent = needCol
      ? "「" + OP_LABEL[op] + "」需要选列" + (op === "to_number" ? "（坏值转空）" : "")
      : "「" + OP_LABEL[op] + "」作用于整表";
  }
  $("op").addEventListener("change", syncOpUi);
  syncOpUi();

  on("btn-add-step", function () {
    if (!STATE.csv) { toast("先加载数据", "err"); return; }
    var op = $("op").value;
    var step = { op: op };
    if (OPS_NEED_COL[op]) {
      var col = $("op-col").value;
      if (!col) { toast("该操作需要选列", "err"); return; }
      step.column = col;
    }
    if (op === "to_number") step.on_error = "blank";
    if (op === "fill_missing") step.strategy = $("op-param").value;
    STATE.recipe.push(step);
    renderRecipe();
  });

  function renderRecipe() {
    var box = $("recipe-chips");
    box.textContent = "";
    if (!STATE.recipe.length) {
      box.appendChild(el("span", "note", "配方为空——加入步骤后执行清洗"));
      return;
    }
    STATE.recipe.forEach(function (step, i) {
      var chip = el("span", "chip active",
        (i + 1) + ". " + OP_LABEL[step.op] + (step.column ? "：" + step.column : "") + "  ✕");
      chip.title = "点击移除这一步";
      chip.addEventListener("click", function () {
        STATE.recipe.splice(i, 1); renderRecipe();
      });
      box.appendChild(chip);
    });
  }

  // ---------------- D1 配方保存/重放（2026-10-07 功能增强）
  function refreshRecipes() {
    fetch("/api/recipes").then(function (r) { return r.json(); }).then(function (d) {
      var sel = $("recipes-select");
      if (!sel) return;
      sel.textContent = "";
      var blank = el("option", null, "— 已存配方 —");
      blank.value = "";
      sel.appendChild(blank);
      (d.recipes || []).forEach(function (n) {
        var op = el("option", null, n);
        op.value = n;
        sel.appendChild(op);
      });
    });
  }
  on("btn-recipe-save", function () {
    if (!STATE.recipe.length) { toast("配方为空——先加入步骤", "err"); return; }
    var inp = $("recipe-name");
    var name = (inp && inp.value ? inp.value : "").trim();
    if (!name) { toast("先在配方名输入框里起个名字", "err"); return; }
    fetch("/api/recipes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, steps: STATE.recipe })
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      if (r.status !== 201) { toast((r.d && r.d.error) || "保存失败", "err"); return; }
      toast("配方已保存：" + r.d.name);
      refreshRecipes();
    });
  });
  on("btn-recipe-load", function () {
    var sel = $("recipes-select");
    var name = sel ? sel.value : "";
    if (!name) { toast("先选一个配方", "err"); return; }
    fetch("/api/recipes/" + encodeURIComponent(name))
      .then(function (r) {
        return r.json().then(function (d) { return { status: r.status, d: d }; });
      })
      .then(function (r) {
        if (r.status !== 200) { toast((r.d && r.d.error) || "读取失败", "err"); return; }
        STATE.recipe = r.d.steps || [];
        renderRecipe();
        toast("配方已应用（" + STATE.recipe.length + " 步）");
      });
  });
  refreshRecipes();

  // ---------------- 清洗
  on("btn-clean", function () {
    if (!STATE.csv) { toast("先加载数据", "err"); return; }
    if (!STATE.recipe.length) { toast("配方为空——先加入步骤", "err"); return; }
    fetch("/api/clean", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv: STATE.csv, recipe: STATE.recipe })
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      if (r.status !== 200) { toast((r.d && r.d.error) || "清洗失败", "err"); return; }
      STATE.cleanedCsv = r.d.csv;
      var rep = r.d.report || {};
      var ledger = rep.steps || [];
      $("ct-before").textContent = String(rep.rows_before !== undefined
        ? rep.rows_before : STATE.rows);
      $("ct-after").textContent = String(r.d.rows_after);
      $("ct-steps").textContent = String(ledger.length);
      $("clean-tiles").hidden = false;
      var out = $("clean-out");
      out.hidden = false;
      var lines = r.d.csv.split("\n");
      var ledgerText = ledger.map(function (e) {
        return "  第" + e.step + "步 " + e.op +
          "：" + e.rows_before + " → " + e.rows_after + " 行" +
          (e.counts && Object.keys(e.counts).length
            ? "（" + JSON.stringify(e.counts) + "）" : "");
      }).join("\n");
      out.textContent = "清洗账本（逐步可追溯）：\n" + ledgerText +
        "\n\n清洗后预览（前 " + Math.min(15, lines.length) + " 行）：\n" +
        lines.slice(0, 15).join("\n");
      $("btn-download-csv").disabled = false;
      toast("清洗完成：" + (rep.rows_before !== undefined ? rep.rows_before : STATE.rows)
        + " 行 → " + r.d.rows_after + " 行");
    }).catch(function () { toast("网络错误", "err"); });
  });
  on("btn-download-csv", function () {
    if (!STATE.cleanedCsv) return;
    var blob = new Blob([STATE.cleanedCsv], { type: "text/csv" });
    var a = el("a"); a.href = URL.createObjectURL(blob);
    a.download = "datascope-cleaned.csv";
    a.click(); URL.revokeObjectURL(a.href);
    toast("CSV 已下载");
  });

  // ---------------- 挖掘参数（对齐 mining.py 形状）
  function miningParams() {
    var task = $("task").value;
    if (task === "apriori") {
      var group = $("ap-group").value, item = $("ap-item").value;
      if (!group || !item) { toast("先加载数据以选择聚篮/商品列", "err"); return null; }
      if (group === item) { toast("聚篮列与商品列不能相同", "err"); return null; }
      return { task: "apriori", params: {
        group_col: group, item_col: item,
        min_support: Number($("ap-support").value || 0.3) || 0.3,
        min_confidence: Number($("ap-conf").value || 0.6) || 0.6 } };
    }
    var cols = Array.prototype.map.call(
      document.querySelectorAll("#km-cols input:checked"), function (b) { return b.value; });
    if (!cols.length) { toast("K-means 至少选一列数值特征", "err"); return null; }
    return { task: "kmeans", params: { columns: cols,
      k: Number($("km-k").value || 3) || 3 } };
  }
  function syncTaskUi() {
    var task = $("task").value;
    $("apriori-params").style.display = task === "apriori" ? "" : "none";
    $("kmeans-params").style.display = task === "kmeans" ? "" : "none";
  }
  $("task").addEventListener("change", syncTaskUi);
  syncTaskUi();

  function renderApriori(d) {
    var box = $("mine-out");
    box.textContent = "";
    box.appendChild(el("p", "note", d.notes || ""));
    box.appendChild(el("p", "note",
      "事务数 " + (d.stats && d.stats.n) + " · 频繁项集 " + (d.itemsets || []).length + " 组"));
    var t = el("table", "kb");
    var head = el("tr");
    ["关联规则", "支持度", "置信度", "提升度"].forEach(function (h) {
      head.appendChild(el("th", null, h));
    });
    t.appendChild(head);
    (d.rules || []).slice(0, 15).forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("td", "", "")).appendChild(el("span", "kbd",
        r.ante.join(" + ") + " → " + r.cons.join(" + ")));
      tr.appendChild(el("td", "time", String(r.support)));
      tr.appendChild(el("td", "time", String(r.confidence)));
      tr.appendChild(el("td", "time", String(r.lift)));
      t.appendChild(tr);
    });
    box.appendChild(t);
    if (!(d.rules || []).length) {
      box.appendChild(el("p", "note", "该支持度/置信度下没有规则——调低参数再试。"));
    }
  }
  function renderKmeans(d) {
    var box = $("mine-out");
    box.textContent = "";
    var m = d.metrics || {};
    var tiles = el("div", "tiles");
    [["迭代次数", m.iterations, "c-blue"], ["惯性 SSE", m.inertia, "c-amber"],
     ["轮廓系数", m.silhouette, "c-green"], ["空簇事件", m.empty_cluster_events, "c-rose"]]
      .forEach(function (p) {
        var tile = el("div", "tile " + p[2]);
        tile.appendChild(el("div", "t-label", p[0]));
        tile.appendChild(el("div", "t-value time", String(p[1])));
        tiles.appendChild(tile);
      });
    box.appendChild(tiles);
    var sizes = {};
    (d.labels || []).forEach(function (l) { sizes[l] = (sizes[l] || 0) + 1; });
    var t = el("table", "kb");
    var head = el("tr");
    ["簇", "样本数", "质心（" + (d.centroids ? d.centroids[0].length : 0) + " 维）"]
      .forEach(function (h) { head.appendChild(el("th", null, h)); });
    t.appendChild(head);
    (d.centroids || []).forEach(function (c, i) {
      var tr = el("tr");
      tr.appendChild(el("td", "", "")).appendChild(el("span", "pill info", "簇 " + i));
      tr.appendChild(el("td", "time", String(sizes[i] || 0)));
      tr.appendChild(el("td", "", "")).appendChild(el("span", "kbd",
        c.map(function (x) { return String(x); }).join(", ")));
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  on("btn-mine", function () {
    if (!STATE.cleanedCsv) { toast("先执行清洗（挖掘基于清洗后数据）", "err"); return; }
    var spec = miningParams();
    if (!spec) return;
    var box = $("mine-out");
    box.textContent = "";
    box.appendChild(el("p", "note", "挖掘中…"));
    fetch("/api/mine", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv: STATE.cleanedCsv, task: spec.task, params: spec.params })
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (r) {
      if (r.status !== 200) {
        box.textContent = "";
        box.appendChild(el("div", "msg err", (r.d && r.d.error) || "挖掘失败"));
        toast("挖掘失败", "err");
        return;
      }
      if (r.d.task === "apriori") renderApriori(r.d); else renderKmeans(r.d);
      toast("挖掘完成");
    }).catch(function () { toast("网络错误", "err"); });
  });

  on("btn-report", function () {
    if (!STATE.cleanedCsv) { toast("先执行清洗", "err"); return; }
    var spec = miningParams();
    var btn = $("btn-report");
    btn.disabled = true;
    fetch("/api/report", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv: STATE.csv, recipe: STATE.recipe,
                             mining: spec ? { task: spec.task, params: spec.params } : null })
    }).then(function (r) {
      return r.text().then(function (t) { return { status: r.status, t: t }; });
    }).then(function (r) {
      btn.disabled = false;
      if (r.status !== 200) { toast("报告生成失败（" + r.status + "）", "err"); return; }
      if (STATE.reportUrl) URL.revokeObjectURL(STATE.reportUrl);
      STATE.reportUrl = URL.createObjectURL(new Blob([r.t], { type: "image/svg+xml" }));
      var box = $("mine-out");
      box.textContent = "";
      var img = el("img");
      img.src = STATE.reportUrl;
      img.alt = "清洗与挖掘 SVG 报告";
      img.style.cssText = "width:100%;border:1px solid var(--line);border-radius:12px";
      box.appendChild(img);
      $("btn-download-svg").disabled = false;
      toast("SVG 报告已生成");
    }).catch(function () { btn.disabled = false; toast("网络错误", "err"); });
  });
  on("btn-download-svg", function () {
    if (!STATE.reportUrl) return;
    var a = el("a"); a.href = STATE.reportUrl; a.download = "datascope-report.svg";
    a.click();
    toast("报告已下载");
  });
})();
