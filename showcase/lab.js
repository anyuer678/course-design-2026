/* showcase/lab.js —— 展示页内「实时实验台」分节的控制台（由 lab.py 提供）。
 *
 * 设计要点：
 * - 实验台是每页的一个正式分节（#lab-slot）：页面双击静态看时，它显示启动说明；
 *   实验台在跑时，本文件把该分节**就地**升级为控制台（启停真实服务、发原始请求、看实时日志）；
 * - 只用 DOM API 构建界面（不用 innerHTML），零依赖、无框架；
 * - 与 lab.py 的 API 一一对应：/lab/api/info、/start、/stop、/run、/log、/sock；
 * - 请求框里的 \r \n \t \\ \xNN 转义与 lab.py 的 unescape_bytes() 同一条规则。
 */
(function () {
  "use strict";
  var slot = document.getElementById("lab-slot");
  if (!slot) return;                       // 页面上没有实验台分节：完全安静
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
      "#lab-slot .lab-status{color:#5f6773;font-size:13px;margin:2px 0 6px}",
      "#lab-slot .lab-hint{color:#5f6773;font-size:13px;margin:8px 0 3px}",
      "#lab-slot .lab-row{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}",
      "#lab-slot button{font:inherit;font-size:13px;padding:4px 12px;border:1px solid #d5d9e0;",
      "border-radius:999px;background:#fff;color:#1c2330;cursor:pointer}",
      "#lab-slot button:hover{border-color:#1d4ed8}",
      "#lab-slot button:disabled{opacity:.45;cursor:default}",
      "#lab-slot textarea{width:100%;box-sizing:border-box;min-height:64px;border:1px solid #d5d9e0;",
      "border-radius:8px;padding:6px;font:12px/1.5 ui-monospace,Consolas,monospace;resize:vertical}",
      "#lab-slot pre{background:#0f1115;color:#e6e9ef;border-radius:8px;padding:10px 12px;margin:4px 0;",
      "max-height:240px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;",
      "white-space:pre-wrap;word-break:break-word}",
    ].join("");
    document.head.appendChild(s);
  }

  function consoleUI(info) {
    ensureStyle();
    var state = info.state || {};
    var logFrom = 0;
    var wasRunning = !!state.running;
    slot.textContent = "";

    var status = el("div", "lab-status", "正在连接实验台…");
    slot.appendChild(status);
    if (info.hint) slot.appendChild(el("div", "lab-hint", info.hint));

    var log = null;
    function appendLog(text) {
      if (!log) return;
      var atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
      log.textContent = (log.textContent === "（暂无输出）" ? "" : log.textContent) + text + "\n";
      if (atBottom) log.scrollTop = log.scrollHeight;
    }

    // ---- 动作按钮（启停服务 / 跑 demo / 跑测试）
    var acts = info.actions || [];
    if (!acts.length) {
      slot.appendChild(el("div", "lab-hint",
        "本项目未接实验台动作（演示与测试入口见上方「怎么自己跑」）。"));
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
    slot.appendChild(row);

    // ---- 请求发送区（只对注册了常驻服务的项目显示）
    var resp = null;
    if (info.sample) {
      slot.appendChild(el("div", "lab-hint",
        "把下面这段原样发给真实服务（\\r \\n \\t \\xNN 转义成字节）："));
      var input = document.createElement("textarea");
      input.value = info.sample;
      slot.appendChild(input);
      var sendRow = el("div", "lab-row");
      var send = el("button", "", "发送真实请求");
      resp = el("pre", "", "（响应将显示在这里）");
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
      slot.appendChild(sendRow);
      slot.appendChild(resp);
    }

    // ---- 实时日志
    slot.appendChild(el("div", "lab-hint", "实时日志（服务或 demo/测试进程的 stdout+stderr）："));
    log = el("pre", "", "（暂无输出）");
    slot.appendChild(log);

    function refresh() {
      return api("/lab/api/log?project=" + encodeURIComponent(pid) + "&from=" + logFrom)
        .then(function (r) {
          if (!r.ok) return;
          (r.lines || []).forEach(function (ln) { appendLog(ln); });
          logFrom = r.from;
          var st = r.state || {};
          status.textContent = "实验台已连接（" + (HUB ? "127.0.0.1:7788" : "同源") + "）　·　服务：" +
            (st.running
              ? ("运行中 pid=" + st.pid + (st.port ? (":" + st.port) : "") + "（" + st.up + "s，" + st.kind + "）")
              : "未运行");
          if (wasRunning && !st.running) appendLog("[实验台] 进程已退出");
          wasRunning = !!st.running;
        }).catch(function () {
          status.textContent = "实验台连接已断开（服务状态未知；重新启动 lab.bat 后刷新本页）";
        });
    }
    refresh();
    var pollTimer = setInterval(refresh, 1500);
    window.addEventListener("beforeunload", function () { clearInterval(pollTimer); });
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
    .then(function (info) {
      if (info && info.ok) consoleUI(info);
      // 实验台没跑：保留 #lab-slot 里的静态启动说明，不动它
    })
    .catch(function () { /* 同上：静态说明保持原样 */ });
})();
