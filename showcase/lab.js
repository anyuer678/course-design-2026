/* showcase/lab.js —— 展示页右下角"实时实验台"控制台（由 lab.py 提供）。
 *
 * 设计要点：
 * - 页面自己仍可双击静态看；本文件只在"实验台在跑"时有存在感：拉不到就只留一个小提示；
 * - 只用 DOM API 构建界面（不用 innerHTML），零依赖、无框架；
 * - 与 lab.py 的 API 一一对应：/lab/api/info、/start、/stop、/run、/log、/sock；
 * - 请求框里的 \r \n \t \\ \xNN 转义与 lab.py 的 unescape_bytes() 同一条规则。
 */
(function () {
  "use strict";
  var pid = (document.body && document.body.dataset) ? document.body.dataset.showcase : "";
  if (!pid) return;
  var HUB = (location.protocol === "http:") ? "" : "http:\/\/127.0.0.1:7788";

  function api(path, post) {
    var opt = { method: post ? "POST" : "GET" };
    if (post) {
      opt.headers = { "Content-Type": "application/json" };
      opt.body = JSON.stringify(post);
    }
    return fetch(HUB + path, opt).then(function (r) { return r.json(); });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function ensureStyle() {
    if (document.getElementById("lab-style")) return;
    var s = document.createElement("style");
    s.id = "lab-style";
    s.textContent = [
      "#lab-dock{position:fixed;right:14px;bottom:14px;width:400px;max-width:92vw;background:#0f1115;color:#e6e9ef;",
      "border:1px solid #3a3f4b;border-radius:10px;font:13px/1.6 ui-monospace,Consolas,monospace;z-index:9999;",
      "box-shadow:0 6px 24px rgba(0,0,0,.35)}",
      "#lab-dock .lab-head{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;",
      "background:#171a21;border-bottom:1px solid #3a3f4b;cursor:pointer;user-select:none}",
      "#lab-dock .lab-head b{font-size:13px;color:#9ec1ff}",
      "#lab-dock .lab-body{padding:8px 10px;max-height:62vh;overflow:auto}",
      "#lab-dock .lab-row{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}",
      "#lab-dock button{font:inherit;font-size:12px;padding:3px 10px;border:1px solid #4a5164;border-radius:6px;",
      "background:#1c2230;color:#dbe4ff;cursor:pointer}",
      "#lab-dock button:hover{border-color:#9ec1ff}",
      "#lab-dock button:disabled{opacity:.45;cursor:default}",
      "#lab-dock .lab-status{color:#8fb3e0;margin:2px 0}",
      "#lab-dock .lab-hint{color:#98a2b3;font-size:12px;margin:4px 0}",
      "#lab-dock textarea{width:100%;min-height:64px;background:#0a0c10;color:#d8e2f2;border:1px solid #3a3f4b;",
      "border-radius:6px;font:12px/1.5 ui-monospace,Consolas,monospace;padding:6px;resize:vertical}",
      "#lab-dock pre{background:#0a0c10;border:1px solid #2c3140;border-radius:6px;padding:6px;margin:4px 0;",
      "max-height:200px;overflow:auto;white-space:pre-wrap;word-break:break-word;color:#cfe0c8}",
      "#lab-dock .lab-badge{position:fixed;right:14px;bottom:14px;background:#1c2230;color:#9ec1ff;",
      "border:1px solid #4a5164;border-radius:8px;font:12px ui-monospace,Consolas,monospace;padding:5px 10px;",
      "cursor:pointer;z-index:9999}",
    ].join("");
    document.head.appendChild(s);
  }

  function absent() {
    // 实验台没在跑：角落里留一个可展开、可关闭的小提示；不打扰静态浏览
    ensureStyle();
    if (sessionStorage.getItem("lab-dismissed") === "1") return;
    var badge = el("div", "lab-badge", "实验台未启动");
    badge.title = "点这里看怎么开";
    badge.addEventListener("click", function () {
      var box = el("div", "");
      box.id = "lab-dock";
      box.appendChild(el("div", "lab-head", "实时实验台（未启动）"));
      var body = el("div", "lab-body");
      body.appendChild(el("div", "lab-hint",
        "本页是静态生成物，要让页面能真正控制后端（启停真实服务、发真实请求、看实时日志）："));
      body.appendChild(el("pre", "", "cd 仓库根\npython showcase\\lab.py\n# 然后浏览器打开 http://127.0.0.1:7788/showcase/index.html 或刷新本页"));
      var row = el("div", "lab-row");
      var x = el("button", "", "知道了，本次不再提示");
      x.addEventListener("click", function () {
        sessionStorage.setItem("lab-dismissed", "1");
        box.remove();
      });
      row.appendChild(x);
      body.appendChild(row);
      box.appendChild(body);
      badge.remove();
      document.body.appendChild(box);
    });
    document.body.appendChild(badge);
  }

  function dock(info) {
    if (!info || !info.ok) return absent();
    ensureStyle();
    var state = info.state || {};
    var pollTimer = null;
    var logFrom = 0;
    var wasRunning = !!state.running;

    var box = el("div", "");
    box.id = "lab-dock";
    var head = el("div", "lab-head");
    head.appendChild(el("b", "", "实时实验台 · " + pid));
    var toggle = el("span", "", "收起");
    head.appendChild(toggle);
    box.appendChild(head);
    var body = el("div", "lab-body");
    box.appendChild(body);
    head.addEventListener("click", function () {
      var hidden = body.style.display === "none";
      body.style.display = hidden ? "" : "none";
      toggle.textContent = hidden ? "收起" : "展开";
    });

    var status = el("div", "lab-status", "…");
    body.appendChild(status);
    if (info.hint) body.appendChild(el("div", "lab-hint", info.hint));

    // ---- 动作按钮
    var acts = info.actions || [];
    if (!acts.length) {
      body.appendChild(el("div", "lab-hint",
        "本项目未接实验台动作（演示/测试入口见本页页尾与 README）。"));
    }
    var row = el("div", "lab-row");
    acts.forEach(function (a) {
      var b = el("button", "", a.label);
      b.addEventListener("click", function () {
        b.disabled = true;
        var req;
        if (a.id === "serve_start") req = api("/lab/api/start", { project: pid });
        else if (a.id === "serve_stop") req = api("/lab/api/stop", { project: pid });
        else req = api("/lab/api/run", { project: pid, kind: a.id });
        req.then(function (r) {
          if (!r.ok) appendLog("[实验台] " + (r.error || "失败") + (r.tail ? "\n" + r.tail : ""));
          refresh();
        }).catch(function (e) { appendLog("[实验台] " + e); })
          .then(function () { b.disabled = false; });
      });
      row.appendChild(b);
    });
    body.appendChild(row);

    // ---- 请求发送区（只对注册了常驻服务的项目显示）
    var input = null;
    if (info.sample) {
      body.appendChild(el("div", "lab-hint", "把下面这段原样发给真实服务（\\r \\n \\t \\xNN 会转义成字节）："));
      input = document.createElement("textarea");
      input.value = info.sample;
      body.appendChild(input);
      var sendRow = el("div", "lab-row");
      var send = el("button", "", "发送真实请求");
      var resp = el("pre", "", "（响应将显示在这里）");
      send.addEventListener("click", function () {
        send.disabled = true;
        api("/lab/api/sock", { project: pid, bytes: toBytes(input.value) }).then(function (r) {
          if (!r.ok) { resp.textContent = "发送失败：" + (r.error || "?"); return; }
          var head = "发出 " + r.sent + " B，收到 " + r.got + " B（" + r.ms + " ms）\n";
          var hex = r.hex.length > 400 ? r.hex.slice(0, 400) + " …" : r.hex;
          resp.textContent = head + "---- 文本（utf-8, 替换非法字节）----\n" + r.text +
            "\n---- 字节 ----\n" + hex;
        }).catch(function (e) { resp.textContent = "发送失败：" + e; })
          .then(function () { send.disabled = false; });
      });
      sendRow.appendChild(send);
      body.appendChild(sendRow);
      body.appendChild(resp);
    }

    // ---- 实时日志
    body.appendChild(el("div", "lab-hint", "实时日志（服务或 demo/测试进程的 stdout+stderr）："));
    var log = el("pre", "", "（暂无输出）");
    body.appendChild(log);
    function appendLog(text) {
      var atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
      log.textContent = (log.textContent === "（暂无输出）" ? "" : log.textContent) + text + "\n";
      if (atBottom) log.scrollTop = log.scrollHeight;
    }
    function refresh() {
      return api("/lab/api/log?project=" + encodeURIComponent(pid) + "&from=" + logFrom)
        .then(function (r) {
          if (!r.ok) return;
          (r.lines || []).forEach(function (ln) { appendLog(ln); });
          logFrom = r.from;
          var st = r.state || {};
          status.textContent = "服务：" + (st.running
            ? ("运行中 pid=" + st.pid + (st.port ? (":" + st.port) : "") + "（" + st.up + "s，" + st.kind + "）")
            : "未运行") + "　·　实验台：" + (HUB ? "127.0.0.1:7788" : "同源");
          if (wasRunning && !st.running) appendLog("[实验台] 进程已退出");
          wasRunning = !!st.running;
        }).catch(function () { status.textContent = "服务：状态查询失败（实验台还在吗？）"; });
    }
    refresh();
    pollTimer = setInterval(refresh, 1500);
    window.addEventListener("beforeunload", function () { clearInterval(pollTimer); });

    document.body.appendChild(box);
  }

  function toBytes(text) {
    // 与 lab.py unescape_bytes() 同一规则：\r \n \t \\ \xNN + 其余按 utf-8
    var out = [], i = 0;
    while (i < text.length) {
      var c = text.charAt(i);
      if (c === "\\" && i + 1 < text.length) {
        var n = text.charAt(i + 1);
        if (n === "r") { out.push(13); i += 2; continue; }
        if (n === "n") { out.push(10); i += 2; continue; }
        if (n === "t") { out.push(9); i += 2; continue; }
        if (n === "\\") { out.push(92); i += 2; continue; }
        if (n === "x" && i + 4 <= text.length) {
          var h = parseInt(text.substr(i + 2, 2), 16);
          if (!isNaN(h)) { out.push(h); i += 4; continue; }
        }
      }
      var code = text.charCodeAt(i);
      if (code < 128) { out.push(code); } else {
        encodeURIComponent(c).split("%").slice(1).forEach(function (p) {
          out.push(parseInt(p, 16));
        });
      }
      i += 1;
    }
    return out;
  }

  api("/lab/api/info?project=" + encodeURIComponent(pid))
    .then(dock)
    .catch(function () { absent(); });
})();
