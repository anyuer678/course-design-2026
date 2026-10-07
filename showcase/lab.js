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
  var pid = (document.body && document.body.dataset) ? document.body.dataset.showcase : "";
  var isIndex = !!(document.body && document.body.dataset && document.body.dataset.labIndex);
  if (!isIndex && !(slot && pid)) return;  // 既不是项目页也不是总入口：完全安静
  // 就地控制台只在"本源就是实验台"（:7788）或 file://（Hub 固定 7788）时激活；
  // 页面被其他 http 来源内嵌（如课程平台 /repo/）时保持静态启动说明——
  // 那里没有 /lab/api/* 路由，发探测请求只会留下 404 噪音（2026-10-07 终扫）。
  var HUB = (location.protocol === "http:")
    ? (location.port === "7788" ? "" : null)
    : "http:\/\/127.0.0.1:7788";

  function api(path, post) {
    if (HUB === null) return Promise.reject(new Error("非实验台来源：控制台不可用"));
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
      "#lab-slot .lab-status{color:var(--kb-text-2,#475569);font-size:13px;margin:2px 0 6px}",
      "#lab-slot .lab-hint{color:var(--kb-text-2,#475569);font-size:13px;margin:8px 0 3px}",
      "#lab-slot .lab-row{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}",
      "#lab-slot button{font:inherit;font-size:13px;padding:4px 12px;border:1px solid var(--kb-border,#e2e8f0);",
      "border-radius:999px;background:#fff;color:var(--kb-text-1,#0f172a);cursor:pointer;",
      "transition:border-color .2s ease,color .2s ease}",
      "#lab-slot button:hover{border-color:var(--kb-primary,#3b82f6);color:var(--kb-primary,#3b82f6)}",
      "#lab-slot button:disabled{opacity:.45;cursor:default}",
      "#lab-slot textarea{width:100%;box-sizing:border-box;min-height:64px;",
      "border:1px solid var(--kb-border,#e2e8f0);border-radius:8px;padding:6px;",
      "font:12px/1.5 ui-monospace,Consolas,monospace;resize:vertical}",
      "#lab-slot textarea:focus{outline:2px solid #bfdbfe;border-color:var(--kb-primary,#3b82f6)}",
      "#lab-slot pre{background:#0f172a;color:#e2e8f0;border:1px solid #1e293b;",
      "border-radius:10px;padding:10px 12px;margin:4px 0;",
      "max-height:240px;overflow:auto;font:13px/1.55 ui-monospace,Consolas,monospace;",
      "white-space:pre-wrap;word-break:break-word}",
      "[data-lab-index] .lab-ctl{display:inline-flex;gap:6px;align-items:center;margin-left:auto;flex-wrap:wrap}",
      "[data-lab-index] .lab-dot{font-size:12px;color:#94a3b8}",
      "[data-lab-index] .lab-dot.on{color:#16a34a}",
      "[data-lab-index] .lab-mini{font:inherit;font-size:12px;padding:2px 9px;",
      "border:1px solid var(--kb-border,#e2e8f0);border-radius:999px;background:#fff;",
      "color:var(--kb-text-2,#475569);cursor:pointer;transition:all .2s ease}",
      "[data-lab-index] .lab-mini:hover{border-color:var(--kb-primary,#3b82f6);color:var(--kb-primary,#3b82f6)}",
      "[data-lab-index] .lab-mini:disabled{opacity:.45;cursor:default}",
      "[data-lab-index] .lab-mini.on{background:var(--kb-primary,#3b82f6);",
      "border-color:var(--kb-primary,#3b82f6);color:#fff}",
      "[data-lab-index] .lab-err{color:#b91c1c;font-size:12px}",
      "[data-lab-index] .lab-log{flex-basis:100%;width:100%;background:#0f172a;color:#e2e8f0;",
      "border-radius:8px;padding:8px 10px;margin:6px 0 2px;max-height:200px;overflow:auto;",
      "font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}",
      "[data-lab-index] a.lab-open{font:inherit;font-size:12px;padding:2px 9px;",
      "border:1px solid var(--kb-border,#e2e8f0);border-radius:999px;background:#fff;",
      "color:var(--kb-primary,#3b82f6);cursor:pointer;text-decoration:none;transition:all .2s ease}",
      "[data-lab-index] a.lab-open:hover{border-color:var(--kb-primary,#3b82f6)}",
      "#lab-slot a.lab-open{display:inline-flex;font:inherit;font-size:13px;padding:4px 12px;",
      "border:1px solid var(--kb-border,#e2e8f0);border-radius:999px;background:#fff;",
      "color:var(--kb-primary,#3b82f6);cursor:pointer;text-decoration:none;",
      "transition:border-color .2s ease,color .2s ease}",
      "#lab-slot a.lab-open:hover{border-color:var(--kb-primary,#3b82f6)}",
    ].join("");
    document.head.appendChild(s);
  }

  // ------------------------------------------------ 总入口「项目群控制台」模式
  function indexConsole() {
    var hint = document.getElementById("hub-hint");
    var openLogPid = null, logTimer = null, logFrom = 0, logPre = null;
    var current = [];          // 最近一次 overview 的项目列表（全部停止用）
    var stopAll = null;

    // 提示横幅：静态文字先包进 .hub-txt（之后只改它，保住追加的「全部停止」按钮）
    if (hint && !hint.querySelector(".hub-txt")) {
      var t0 = el("span", "hub-txt");
      while (hint.firstChild) t0.appendChild(hint.firstChild);
      hint.appendChild(t0);
    }
    if (hint) {
      stopAll = el("button", "lab-mini", "全部停止");
      stopAll.style.display = "none";
      stopAll.title = "停掉所有由本实验台启动的服务与长任务";
      stopAll.addEventListener("click", function () {
        var running = current.filter(function (p) { return p.state && p.state.running; });
        if (!running.length) return;
        if (!window.confirm("停止所有在跑的进程（服务与长任务）？")) return;
        stopAll.disabled = true;
        (function next(i) {
          if (i >= running.length) { refresh(); return; }
          api("/lab/api/stop", { project: running[i].project })
            .then(function () { next(i + 1); })
            .catch(function () { next(i + 1); });
        })(0);
      });
      hint.appendChild(document.createTextNode(" "));
      hint.appendChild(stopAll);
    }

    function setHint(cls, text) {
      if (!hint) return;
      hint.className = "hub" + (cls ? (" " + cls) : "");
      var t = hint.querySelector(".hub-txt");
      if (t) t.textContent = text;
    }

    function rowOf(project) {
      return document.querySelector('li[data-id="' + project + '"]');
    }

    function shortLabel(id, label) {
      if (id === "serve_start") return "启动";
      if (id === "serve_stop") return "停止";
      if (id === "stop_run") return "停止";
      if (id === "demo") return "演示";
      if (id === "tests") return "测试";
      if (id === "run") return "运行";
      return label;
    }

    function flash(entry, text) {
      var li = rowOf(entry.project);
      var box = li && li.querySelector(".lab-ctl");
      if (!box) return;
      var old = box.querySelector(".lab-err");
      if (old) old.remove();
      var p = el("span", "lab-err", text);
      box.appendChild(p);
      setTimeout(function () { if (p.parentNode) p.remove(); }, 6000);
    }

    function fire(entry, action, btn) {
      btn.disabled = true;
      var req;
      if (action.id === "serve_start") req = api("/lab/api/start", { project: entry.project });
      else if (action.id === "serve_stop" || action.id === "stop_run") req = api("/lab/api/stop", { project: entry.project });
      else req = api("/lab/api/run", { project: entry.project, kind: action.id });
      req.then(function (r) {
        if (!r.ok) flash(entry, "失败：" + (r.error || "?") + (r.tail ? "（输出尾部见日志）" : ""));
        return refresh();
      }).catch(function (e) { flash(entry, "失败：" + e); })
        .then(function () { btn.disabled = false; });
    }

    function closeLog() {
      if (logTimer) { clearInterval(logTimer); logTimer = null; }
      if (logPre && logPre.parentNode) logPre.parentNode.removeChild(logPre);
      logPre = null;
      openLogPid = null;
      Array.prototype.forEach.call(document.querySelectorAll(".lab-mini.on"),
        function (b) { b.classList.remove("on"); });
    }

    function toggleLog(entry, btn) {
      var li = rowOf(entry.project);
      if (!li) return;
      if (openLogPid === entry.project) { closeLog(); return; }
      closeLog();
      openLogPid = entry.project;
      logFrom = 0;
      logPre = el("pre", "lab-log", "（暂无输出）");
      li.appendChild(logPre);
      btn.classList.add("on");
      function pull() {
        api("/lab/api/log?project=" + encodeURIComponent(entry.project) + "&from=" + logFrom)
          .then(function (r) {
            if (!r.ok) return;
            (r.lines || []).forEach(function (ln) {
              var atBottom = logPre.scrollTop + logPre.clientHeight >= logPre.scrollHeight - 8;
              logPre.textContent = (logPre.textContent === "（暂无输出）" ? "" : logPre.textContent) + ln + "\n";
              if (atBottom) logPre.scrollTop = logPre.scrollHeight;
            });
            logFrom = r.from;
          }).catch(function () {});
      }
      pull();
      logTimer = setInterval(pull, 1500);
    }

    function fillRow(entry) {
      var li = rowOf(entry.project);
      if (!li) return;
      if (!(entry.actions || []).length) return;   // 没接动作的项目（如 B8 走 WSL）：保持静态行
      var box = li.querySelector(".lab-ctl");
      if (!box) {
        box = el("span", "lab-ctl");
        li.appendChild(box);
      }
      var dot = box.querySelector(".lab-dot");
      if (!dot) {
        dot = el("span", "lab-dot");
        box.appendChild(dot);
      }
      var running = !!(entry.state && entry.state.running);
      var up = running && entry.state.up ? " · " + Math.round(entry.state.up) + "s" : "";
      dot.textContent = running
        ? ("● " + (entry.state.port ? (":" + entry.state.port) : "运行中") + up)
        : "○";
      dot.title = running
        ? ("运行中 pid=" + entry.state.pid + "（" + entry.state.up + "s" +
           (entry.state.kind ? "，" + entry.state.kind : "") + "）")
        : "未运行";
      dot.className = "lab-dot" + (running ? " on" : "");
      var op = box.querySelector(".lab-open");
      if (op) op.style.display = running ? "" : "none";
      if (box.dataset.built === "1") return;    // 按钮只建一次，轮询只刷新状态点
      box.dataset.built = "1";
      (entry.actions || []).forEach(function (a) {
        var b = el("button", "lab-mini", shortLabel(a.id, a.label));
        b.addEventListener("click", function () { fire(entry, a, b); });
        box.appendChild(b);
      });
      if (entry.ui && entry.port) {
        // 服务自己的浏览器页面（B11 路线帮助 / B31 前端 / B28 看板 / dorm 原型）
        var open = document.createElement("a");
        open.className = "lab-open";
        open.textContent = "打开";
        open.href = "http://127.0.0.1:" + entry.port + "/";
        open.target = "_blank";
        open.rel = "noopener";
        open.title = "在新标签页打开 http://127.0.0.1:" + entry.port + "/";
        open.style.display = running ? "" : "none";
        box.appendChild(open);
      }
      var lg = el("button", "lab-mini", "日志");
      lg.addEventListener("click", function () { toggleLog(entry, lg); });
      box.appendChild(lg);
    }

    function refresh() {
      return api("/lab/api/overview").then(function (r) {
        if (!r.ok) {
          setHint("warn", "控制仅限本机：" + (r.error || "该来源不可用") +
            "——局域网访客可以继续浏览全部页面。");
          if (stopAll) stopAll.style.display = "none";
          return;
        }
        var projects = r.projects || [];
        current = projects;
        projects.forEach(fillRow);
        var svc = [], tasks = 0;
        projects.forEach(function (p) {
          var st = p.state || {};
          if (!st.running) return;
          if (st.port) svc.push(p.project.split("-")[0] + ":" + st.port);
          else tasks += 1;
        });
        var live = svc.length + tasks;
        if (stopAll) {
          stopAll.style.display = live ? "" : "none";
          stopAll.disabled = false;
          stopAll.textContent = "全部停止" + (live ? "（" + live + "）" : "");
        }
        setHint("ok", "实验台已连接——共 " + projects.length + " 项" +
          (live
            ? "；正在运行：" + (svc.length ? "服务 " + svc.join("、") : "") +
              (svc.length && tasks ? "，" : "") + (tasks ? "长任务×" + tasks : "")
            : "，当前没有运行中的进程") +
          "。每行可 启动/停止 服务、跑 演示/测试/运行、看日志；B11/B31/B28/dorm 的服务运行时可点「打开」进它自己的页面。");
      }).catch(function () {
        setHint("", "实时控制台已断开——重新启动 lab.bat 后刷新本页即可恢复。");
        if (stopAll) stopAll.style.display = "none";
      });
    }

    ensureStyle();
    refresh();
    var timer = setInterval(refresh, 3000);
    window.addEventListener("beforeunload", function () { clearInterval(timer); });
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
        else if (a.id === "serve_stop" || a.id === "stop_run") req = api("/lab/api/stop", { project: pid });
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

    // ---- 「打开」按钮：ui 服务运行时指向它自己的浏览器页面
    var openLink = null;
    if (info.ui && info.port) {
      openLink = document.createElement("a");
      openLink.className = "lab-open";
      openLink.textContent = "打开服务页面（:" + info.port + "）";
      openLink.href = "http://127.0.0.1:" + info.port + "/";
      openLink.target = "_blank";
      openLink.rel = "noopener";
      openLink.style.display = "none";
      var openRow = el("div", "lab-row");
      openRow.appendChild(openLink);
      slot.appendChild(openRow);
    }

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
          if (openLink) openLink.style.display = st.running ? "" : "none";
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

  if (isIndex) {
    indexConsole();
  } else {
    api("/lab/api/info?project=" + encodeURIComponent(pid))
      .then(function (info) {
        if (info && info.ok) consoleUI(info);
        // 实验台没跑：保留 #lab-slot 里的静态启动说明，不动它
      })
      .catch(function () { /* 同上：静态说明保持原样 */ });
  }
})();
