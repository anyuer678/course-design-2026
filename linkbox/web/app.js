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
    post("/api/stash", {
      content: $("stash-content").value,
      ttl_hours: Number($("stash-ttl").value)
    }).then(function (r) {
      if (!r.ok) { showErr(box, r.data.error || ("失败 " + r.status)); return; }
      var a = el("a", "", location.origin + r.data.url);
      a.href = r.data.url;
      showOk(box, [el("b", "", "已暂存："), a,
                   el("span", "note", "  到期即清除，凭链接查看")]);
      $("stash-content").value = "";
    });
  });

  // ------------------------------------------------ 统计
  function refreshStats() {
    getJSON("/api/stats").then(function (r) {
      var box = $("stats");
      box.textContent = "";
      var table = el("table", "grid");
      [["链接总数", r.data.links], ["命中总数", r.data.hits]].forEach(function (row) {
        var tr = el("tr");
        tr.appendChild(el("td", "", row[0]));
        tr.appendChild(el("td", "", String(row[1])));
        table.appendChild(tr);
      });
      box.appendChild(table);
    });
  }

  // ------------------------------------------------ 选项卡
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
      document.querySelectorAll(".tabpage").forEach(function (p) { p.hidden = true; });
      tab.classList.add("active");
      var page = $("tab-" + tab.dataset.tab);
      page.hidden = false;
      if (tab.dataset.tab === "links") refreshLinks();
      if (tab.dataset.tab === "stats") refreshStats();
    });
  });

  refreshLinks();
})();
