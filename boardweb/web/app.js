/* boardweb/web/app.js —— 画板 Web 版（用户 2026-10-07 四项诉求的落地面：
   图形工具 / 选择微调 / 贴图粘贴 / 内嵌网页）。判定与持久化在服务端，本文件只做
   Canvas 渲染与交互。 */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }

  var canvas = $("board"), ctx = canvas.getContext("2d");
  var W = canvas.width, H = canvas.height;
  var tool = "pen", color = $("color").value, width = Number($("width").value);
  var shapes = [];                 // 文档对象数组（唯一出处，JSON 可序列化）
  var selected = -1;               // 选中的 shape 下标
  var drawing = null;              // 进行中的 shape
  var dragOff = null;              // 移动中的偏移 {dx,dy}
  var undoStack = [], redoStack = [];
  var dirty = false, saveTimer = null;
  var imgCache = {};               // url -> HTMLImageElement

  function status(text) { $("save-state").textContent = text; }
  function markDirty() {
    dirty = true;
    status("改动未保存…");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 1000);
  }
  function pushUndo() {
    undoStack.push(JSON.stringify(shapes));
    if (undoStack.length > 50) undoStack.shift();
    redoStack.length = 0;
  }
  function setShapes(arr) { shapes = arr; selected = -1; render(); markDirty(); }

  // ------------------------------------------------ 渲染
  function drawShape(s) {
    ctx.strokeStyle = s.color; ctx.fillStyle = s.color; ctx.lineWidth = s.width;
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (s.type === "pen") {
      ctx.beginPath();
      s.pts.forEach(function (p, i) { i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); });
      ctx.stroke();
    } else if (s.type === "line") {
      ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
    } else if (s.type === "rect") {
      ctx.strokeRect(s.x, s.y, s.w, s.h);
    } else if (s.type === "ellipse") {
      ctx.beginPath();
      ctx.ellipse(s.x + s.w / 2, s.y + s.h / 2, Math.abs(s.w / 2), Math.abs(s.h / 2), 0, 0, 7);
      ctx.stroke();
    } else if (s.type === "image") {
      var im = imgCache[s.img];
      if (im && im.complete) ctx.drawImage(im, s.x, s.y, s.w, s.h);
    }
  }
  function bbox(s) {
    if (s.type === "pen") {
      var xs = s.pts.map(function (p) { return p[0]; });
      var ys = s.pts.map(function (p) { return p[1]; });
      return { x: Math.min.apply(null, xs), y: Math.min.apply(null, ys),
               w: Math.max.apply(null, xs) - Math.min.apply(null, xs),
               h: Math.max.apply(null, ys) - Math.min.apply(null, ys) };
    }
    if (s.type === "line") return { x: Math.min(s.x1, s.x2), y: Math.min(s.y1, s.y2),
                                    w: Math.abs(s.x2 - s.x1), h: Math.abs(s.y2 - s.y1) };
    return { x: s.x, y: s.y, w: s.w, h: s.h };
  }
  function render() {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
    shapes.forEach(drawShape);
    if (drawing) drawShape(drawing);
    if (selected >= 0 && selected < shapes.length) {
      var b = bbox(shapes[selected]);
      ctx.strokeStyle = "#2563eb"; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
      ctx.strokeRect(b.x - 5, b.y - 5, b.w + 10, b.h + 10);
      ctx.setLineDash([]);
      fillProps(shapes[selected]);
    } else { disableProps(); }
  }

  // ------------------------------------------------ 属性面板（微调）
  var propIds = ["p-x", "p-y", "p-w", "p-h", "p-color", "p-width"];
  function disableProps() {
    propIds.forEach(function (id) { $(id).disabled = true; });
    ["p-x", "p-y", "p-w", "p-h"].forEach(function (id) { $(id).value = ""; });
  }
  function fillProps(s) {
    var b = bbox(s);
    $("p-x").value = Math.round(b.x); $("p-y").value = Math.round(b.y);
    $("p-w").value = Math.round(b.w); $("p-h").value = Math.round(b.h);
    propIds.forEach(function (id) { $(id).disabled = false; });
    $("p-color").value = s.color; $("p-width").value = s.width;
  }
  function applyProps() {
    if (selected < 0) return;
    var s = shapes[selected], b = bbox(s);
    pushUndo();
    if (s.type === "pen" || s.type === "image" || s.type === "rect" || s.type === "ellipse") {
      moveShape(s, Number($("p-x").value) - b.x, Number($("p-y").value) - b.y);
    }
    if (s.type === "rect" || s.type === "ellipse" || s.type === "image") {
      s.w = Math.max(1, Number($("p-w").value)); s.h = Math.max(1, Number($("p-h").value));
    }
    s.color = $("p-color").value; s.width = Number($("p-width").value) || s.width;
    render(); markDirty();
  }
  function moveShape(s, dx, dy) {
    if (s.type === "pen") s.pts.forEach(function (p) { p[0] += dx; p[1] += dy; });
    else if (s.type === "line") { s.x1 += dx; s.y1 += dy; s.x2 += dx; s.y2 += dy; }
    else { s.x += dx; s.y += dy; }
  }
  propIds.forEach(function (id) {
    $(id).addEventListener("change", applyProps);
  });

  // ------------------------------------------------ 命中测试（自上而下取最上层）
  function hit(x, y) {
    for (var i = shapes.length - 1; i >= 0; i--) {
      var s = shapes[i], b = bbox(s);
      if (s.type === "line") {
        var dx = s.x2 - s.x1, dy = s.y2 - s.y1, len2 = dx * dx + dy * dy || 1;
        var t = Math.max(0, Math.min(1, ((x - s.x1) * dx + (y - s.y1) * dy) / len2));
        var px = s.x1 + t * dx, py = s.y1 + t * dy;
        if ((x - px) * (x - px) + (y - py) * (y - py) < 36) return i;
      } else if (x >= b.x - 4 && x <= b.x + b.w + 4 && y >= b.y - 4 && y <= b.y + b.h + 4) {
        return i;
      }
    }
    return -1;
  }

  // ------------------------------------------------ 指针交互
  function pos(ev) {
    var r = canvas.getBoundingClientRect();
    return [Math.round(ev.clientX - r.left), Math.round(ev.clientY - r.top)];
  }
  canvas.addEventListener("pointerdown", function (ev) {
    if (ev.button !== 0) return;
    canvas.setPointerCapture(ev.pointerId);
    var p = pos(ev);
    if (tool === "select") {
      selected = hit(p[0], p[1]);
      if (selected >= 0) {
        var b = bbox(shapes[selected]);
        dragOff = { dx: p[0] - b.x, dy: p[1] - b.y, last: p.slice() };
        pushUndo();
      }
      render(); return;
    }
    pushUndo();
    if (tool === "pen") drawing = { type: "pen", pts: [p], color: color, width: width };
    else drawing = { type: tool, x1: p[0], y1: p[1], x2: p[0], y2: p[1],
                     x: p[0], y: p[1], w: 0, h: 0, color: color, width: width };
  });
  canvas.addEventListener("pointermove", function (ev) {
    var p = pos(ev);
    if (drawing) {
      if (drawing.type === "pen") drawing.pts.push(p);
      else { drawing.x2 = p[0]; drawing.y2 = p[1];
             drawing.x = Math.min(drawing.x1, p[0]); drawing.y = Math.min(drawing.y1, p[1]);
             drawing.w = Math.abs(p[0] - drawing.x1); drawing.h = Math.abs(p[1] - drawing.y1); }
      render(); return;
    }
    if (tool === "select" && selected >= 0 && dragOff) {
      moveSel(p[0] - dragOff.last[0], p[1] - dragOff.last[1]);
      dragOff.last = p;
    }
  });
  canvas.addEventListener("pointerup", function () {
    if (drawing) {
      var keep = drawing.type !== "pen" || drawing.pts.length > 1;
      shapes.push(drawing);
      selected = keep ? shapes.length - 1 : -1;
      drawing = null;
      if (!keep) undoStack.pop();
      render(); markDirty();
    }
    dragOff = null;
  });
  function moveSel(dx, dy) {
    if (selected < 0) return;
    moveShape(shapes[selected], dx, dy);
    render(); markDirty();
  }
  function deleteSel() {
    if (selected < 0) return;
    pushUndo();
    shapes.splice(selected, 1);
    selected = -1; render(); markDirty();
  }
  document.addEventListener("keydown", function (ev) {
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if (ev.ctrlKey && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(); return; }
    if (ev.ctrlKey && ev.key.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
    if (ev.key === "Delete" || ev.key === "Backspace") { deleteSel(); return; }
    var step = ev.shiftKey ? 10 : 1, d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
      ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
    if (d && selected >= 0) { ev.preventDefault(); moveSel(d[0], d[1]); }
  });

  // ------------------------------------------------ 撤销 / 重做 / 清空
  function undo() {
    if (!undoStack.length) return;
    redoStack.push(JSON.stringify(shapes));
    shapes = JSON.parse(undoStack.pop());
    selected = -1; render(); markDirty();
  }
  function redo() {
    if (!redoStack.length) return;
    undoStack.push(JSON.stringify(shapes));
    shapes = JSON.parse(redoStack.pop());
    selected = -1; render(); markDirty();
  }
  $("btn-undo").addEventListener("click", undo);
  $("btn-redo").addEventListener("click", redo);
  $("btn-clear").addEventListener("click", function () {
    if (!shapes.length || !window.confirm("清空整块画板？（可撤销）")) return;
    pushUndo(); shapes = []; selected = -1; render(); markDirty();
  });

  // ------------------------------------------------ 工具切换
  document.querySelectorAll(".tool").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll(".tool").forEach(function (t) { t.classList.remove("active"); });
      b.classList.add("active");
      tool = b.dataset.tool;
      canvas.className = tool === "select" ? "tool-select" : "";
    });
  });
  $("color").addEventListener("input", function () { color = this.value; });
  $("width").addEventListener("change", function () { width = Number(this.value); });

  // ------------------------------------------------ 贴图（文件 + Ctrl+V 粘贴）
  function uploadImage(blob, name) {
    status("贴图上传中…");
    fetch("/api/img?name=" + encodeURIComponent(name), { method: "POST", body: blob })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
      .then(function (r) {
        if (r.status !== 201) { status("贴图失败：" + (r.d.error || r.status)); return; }
        var url = r.d.url, im = new Image();
        im.onload = function () {
          pushUndo();
          var s = { type: "image", img: url,
                    x: Math.round((W - im.width) / 2), y: Math.round((H - im.height) / 2),
                    w: im.width, h: im.height, color: "#000", width: 1 };
          shapes.push(s); selected = shapes.length - 1;
          render(); markDirty();
          status("贴图已插入");
        };
        im.src = url;
      });
  }
  $("btn-img").addEventListener("click", function () { $("img-file").click(); });
  $("img-file").addEventListener("change", function () {
    if (this.files[0]) uploadImage(this.files[0], this.files[0].name);
    this.value = "";
  });
  document.addEventListener("paste", function (ev) {
    var items = (ev.clipboardData || {}).items || [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image/") === 0) {
        ev.preventDefault();
        uploadImage(items[i].getAsFile(), "paste." + items[i].type.split("/")[1]);
        return;
      }
    }
  });

  // ------------------------------------------------ 保存 / 加载 / 导出
  function saveNow() {
    if (!dirty) return;
    fetch("/api/doc", { method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shapes: shapes }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        dirty = false;
        status("已保存 " + (d.saved_at || "").slice(11) + "（v" + d.version + "）");
      })
      .catch(function () { status("保存失败——重试中"); saveTimer = setTimeout(saveNow, 2000); });
  }
  window.addEventListener("beforeunload", function (ev) {
    if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
  });

  function preloadImages(list, done) {
    var left = 0;
    list.forEach(function (s) {
      if (s.type === "image" && !imgCache[s.img]) {
        left++;
        var im = new Image();
        im.onload = im.onerror = function () { if (--left === 0) done(); };
        imgCache[s.img] = im; im.src = s.img;
      }
    });
    if (!left) done();
  }
  function boot() {
    fetch("/api/doc").then(function (r) { return r.json(); }).then(function (d) {
      shapes = d.shapes || [];
      preloadImages(shapes, function () { render(); });
      status("已加载（v" + (d.version || 0) + "）");
    });
  }

  $("btn-export").addEventListener("click", function () {
    var a = document.createElement("a");
    a.download = "board-" + new Date().toISOString().slice(0, 10) + ".png";
    a.href = canvas.toDataURL("image/png");
    a.click();
  });

  disableProps();
  boot();
})();
