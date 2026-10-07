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
        showOk(box, [el("b", "", "已上传：" + r.data.name + " — "), a,
                     el("span", "note", "  " + note)]);
        $("file-input").value = "";
        $("file-pass").value = "";
      })
      .catch(function () { showErr(box, "网络错误，请重试。"); });
  });

  // ------------------------------------------------ 统计
  function refreshStats() {
    getJSON("/api/stats").then(function (r) {
      var box = $("stats");
      box.textContent = "";
      var s = r.data.stats || {};
      var table = el("table", "grid");
      [["链接总数", s.links], ["命中总数", s.total_hits]].forEach(function (row) {
        var tr = el("tr");
        tr.appendChild(el("td", "", row[0]));
        tr.appendChild(el("td", "", String(row[1])));
        table.appendChild(tr);
      });
      box.appendChild(table);
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
