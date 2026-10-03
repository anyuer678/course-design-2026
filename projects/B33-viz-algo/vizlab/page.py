"""vizlab/page.py —— 生成自包含 HTML 动画页：操作记录 → 可播放/暂停/单步的画面

课程要点（可视化技术）：
    - 动画的本质是**状态机 + 渲染函数**：每一帧 = 对"操作记录"的一个下标；播放/暂停/单步
      都只是在移动这个下标——没有"再算一遍算法"，只有"重放已记录的操作"；
    - 页面的数据（TRACES）**直接内嵌**进 HTML：单文件、双击即开、不依赖服务器
      （fetch 在 file:// 下受限，内嵌绕开整类问题——B27 同款做法）；
    - DOM 一律用 createElement/textContent 建，不用 innerHTML 拼串：
      内嵌数据虽然可信，但"不把数据当代码"要成为肌肉记忆；
    - 零框架：布局 flex、动画定时器 setInterval、图是 SVG 圆与线——够用即克制。
"""
from __future__ import annotations

import json
from pathlib import Path

_TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B33 算法可视化 —— 堆排序 / 图遍历（操作记录回放）</title>
<style>
  body { font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif;
         margin: 0; background: #f5f6f8; color: #222; }
  h1 { font-size: 20px; margin: 14px 18px 4px; }
  .sub { margin: 0 18px 10px; color: #666; font-size: 13px; }
  .wrap { display: flex; flex-wrap: wrap; gap: 14px; padding: 0 18px 20px; }
  .card { background: #fff; border: 1px solid #e2e5ea; border-radius: 10px;
          padding: 12px 14px; flex: 1 1 480px; min-width: 460px; }
  .card h2 { font-size: 15px; margin: 2px 0 10px; }
  .bars { display: flex; align-items: flex-end; gap: 4px; height: 180px;
          padding: 6px; background: #fafbfc; border-radius: 8px; }
  .bar { flex: 1; background: #1f77b4; border-radius: 3px 3px 0 0;
         transition: height .12s ease; position: relative; }
  .bar.sorted { background: #2ca02c; }
  .bar.root { background: #ff9f1c; }
  .bar.swap { background: #d62728; }
  .bar span { position: absolute; top: -18px; width: 100%; text-align: center;
              font-size: 11px; color: #444; }
  .controls { margin-top: 10px; display: flex; align-items: center; gap: 8px;
              flex-wrap: wrap; font-size: 13px; }
  button { padding: 4px 10px; border: 1px solid #cfd6df; background: #fff;
           border-radius: 6px; cursor: pointer; font-size: 13px; }
  button:hover { background: #eef3f9; }
  button.active { background: #e8f1fb; border-color: #8ab6e8; }
  .status { color: #555; min-width: 150px; }
  svg { background: #fafbfc; border-radius: 8px; width: 100%; height: auto; }
  .node circle { stroke: #fff; stroke-width: 2; }
  .node text { font-size: 13px; text-anchor: middle; dominant-baseline: central;
               fill: #fff; pointer-events: none; }
  .edge { stroke: #cdd4dd; stroke-width: 2; }
  .edge.tree { stroke: #8ab6e8; stroke-width: 3; }
  .legend { font-size: 12px; color: #666; margin-top: 6px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
              margin: 0 4px 0 10px; vertical-align: -1px; }
</style>
</head>
<body>
<h1>B33 算法可视化 —— 操作记录回放</h1>
<p class="sub">数据来源：B2-datastruct-lab 的只读 trace 观察口导出的 JSON（内嵌于本页）。
播放 / 暂停 / 单步 / 上一步 都只是在移动"记录下标"，页面不重算算法。</p>
<div class="wrap">
  <div class="card">
    <h2>堆排序（min-heap：建堆 + 逐个取顶）</h2>
    <div id="sort-bars" class="bars"></div>
    <div class="controls">
      <button id="sort-prev">上一步</button>
      <button id="sort-play">播放</button>
      <button id="sort-next">下一步</button>
      <span id="sort-status" class="status"></span>
      <label>速度 <select id="sort-speed">
        <option value="1000">0.5×</option>
        <option value="500" selected>1×</option>
        <option value="250">2×</option>
        <option value="120">4×</option>
      </select></label>
    </div>
    <p class="legend"><i style="background:#2ca02c"></i>已排序前缀
      <i style="background:#1f77b4"></i>堆区
      <i style="background:#ff9f1c"></i>堆顶（当前最小值）
      <i style="background:#d62728"></i>本步交换的两格</p>
  </div>
  <div class="card">
    <h2>图遍历（同一张图：BFS / DFS 切换）</h2>
    <div class="controls">
      <label><input type="radio" name="algo" value="bfs" checked> BFS（队列 = 逐层扩散）</label>
      <label><input type="radio" name="algo" value="dfs"> DFS（栈 = 一条路走到黑）</label>
    </div>
    <svg id="graph" viewBox="0 0 540 360" aria-label="图遍历动画"></svg>
    <div class="controls">
      <button id="graph-prev">上一步</button>
      <button id="graph-play">播放</button>
      <button id="graph-next">下一步</button>
      <span id="graph-status" class="status"></span>
      <label>速度 <select id="graph-speed">
        <option value="1000">0.5×</option>
        <option value="500" selected>1×</option>
        <option value="250">2×</option>
        <option value="120">4×</option>
      </select></label>
    </div>
    <p class="legend"><i style="background:#2ca02c"></i>已访问
      <i style="background:#d62728"></i>当前访问
      <i style="background:#ff9f1c"></i>前沿（队列/栈中）
      <i style="background:#cdd4dd"></i>未触达的边/结点</p>
  </div>
</div>
<script>
const TRACES = __TRACES__;
"""

_TEMPLATE_TAIL = """
// ---------------------------------------------------------------- 通用迷你动画器
function makeAnimator(total, delayFn, render) {
  let index = 0;
  let timer = null;
  function clamp() { index = Math.max(0, Math.min(total - 1, index)); }
  function draw() { render(index); }
  return {
    next() { clamp(); if (index < total - 1) index += 1; draw(); },
    prev() { clamp(); if (index > 0) index -= 1; draw(); },
    play(btn) {
      if (timer) { clearInterval(timer); timer = null; btn.textContent = "播放"; return; }
      btn.textContent = "暂停";
      timer = setInterval(() => {
        if (index >= total - 1) { clearInterval(timer); timer = null; btn.textContent = "播放"; return; }
        index += 1; draw();
      }, delayFn());
    },
    stop(btn) { if (timer) { clearInterval(timer); timer = null; btn.textContent = "播放"; } },
    setSpeed() { if (timer) { clearInterval(timer); timer = null;
      return true; } return false; },
    draw, get index() { return index; }
  };
}

// ---------------------------------------------------------------- 排序面板
(function () {
  const trace = TRACES.sort;
  const n = trace.input.length;
  const maxV = Math.max.apply(null, trace.input);
  const container = document.getElementById("sort-bars");
  const bars = [];
  for (let i = 0; i < n; i += 1) {
    const bar = document.createElement("div");
    bar.className = "bar";
    const label = document.createElement("span");
    label.textContent = String(trace.input[i]);
    bar.appendChild(label);
    container.appendChild(bar);
    bars.push(bar);
  }
  const status = document.getElementById("sort-status");
  const speed = document.getElementById("sort-speed");
  const playBtn = document.getElementById("sort-play");

  function render(index) {
    const step = trace.steps[index];
    const state = step.state;
    const out = step.out;
    const swapA = step.op === "swap" ? out + step.a : -1;
    const swapB = step.op === "swap" ? out + step.b : -1;
    for (let i = 0; i < n; i += 1) {
      const bar = bars[i];
      const value = i < state.length ? state[i] : 0;
      bar.style.height = Math.round(8 + (value / maxV) * 150) + "px";
      bar.className = "bar";
      bar.firstChild.textContent = value > 0 ? String(value) : "";
      if (i < out) bar.className = "bar sorted";
      else if (i === swapA || i === swapB) bar.className = "bar swap";
      else if (i === out && i < state.length) bar.className = "bar root";
    }
    const opText = { build: "建堆完成", swap: "交换 (" + step.a + ", " + step.b + ")",
                     pop: "取出 " + state[out - 1] }[step.op] || step.op;
    status.textContent = "第 " + (index + 1) + "/" + trace.steps.length + " 步：" + opText;
  }
  const anim = makeAnimator(trace.steps.length, () => Number(speed.value), render);
  playBtn.addEventListener("click", () => anim.play(playBtn));
  document.getElementById("sort-next").addEventListener("click", () => { anim.stop(playBtn); anim.next(); });
  document.getElementById("sort-prev").addEventListener("click", () => { anim.stop(playBtn); anim.prev(); });
  speed.addEventListener("change", () => { if (anim.setSpeed()) anim.play(playBtn); });
  anim.draw();
}());

// ---------------------------------------------------------------- 图面板
(function () {
  const svg = document.getElementById("graph");
  const status = document.getElementById("graph-status");
  const speed = document.getElementById("graph-speed");
  const playBtn = document.getElementById("graph-play");
  const NS = "http://www.w3.org/2000/svg";
  let algo = "bfs";
  let anim = null;

  function layout(trace) {
    const R = 130, CX = 270, CY = 180;
    const pos = [];
    for (let i = 0; i < trace.nodes; i += 1) {
      const angle = -Math.PI / 2 + (2 * Math.PI * i) / trace.nodes;
      pos.push([CX + R * Math.cos(angle), CY + R * Math.sin(angle)]);
    }
    return pos;
  }

  function build(trace) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const pos = layout(trace);
    const edgeEls = [];
    for (const pair of trace.edges) {
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", pos[pair[0]][0]); line.setAttribute("y1", pos[pair[0]][1]);
      line.setAttribute("x2", pos[pair[1]][0]); line.setAttribute("y2", pos[pair[1]][1]);
      line.setAttribute("class", "edge");
      svg.appendChild(line);
      edgeEls.push(line);
    }
    const nodeEls = [];
    for (let i = 0; i < trace.nodes; i += 1) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "node");
      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("cx", pos[i][0]); circle.setAttribute("cy", pos[i][1]);
      circle.setAttribute("r", 18); circle.setAttribute("fill", "#1f77b4");
      const text = document.createElementNS(NS, "text");
      text.setAttribute("x", pos[i][0]); text.setAttribute("y", pos[i][1]);
      text.textContent = String(i);
      g.appendChild(circle); g.appendChild(text);
      svg.appendChild(g);
      nodeEls.push(circle);
    }
    function render(index) {
      const step = trace.steps[index];
      const visited = new Set();
      for (let i = 0; i <= index; i += 1) visited.add(trace.steps[i].a);
      const frontier = new Set(step.state);
      for (let i = 0; i < trace.nodes; i += 1) {
        let fill = "#1f77b4";
        if (visited.has(i)) fill = "#2ca02c";
        if (frontier.has(i) && !visited.has(i)) fill = "#ff9f1c";
        if (i === step.a) fill = "#d62728";
        nodeEls[i].setAttribute("fill", fill);
      }
      for (const line of edgeEls) line.setAttribute("class", "edge");
      const distText = algo === "bfs" && step.b >= 0 ? "，距离 " + step.b : "";
      status.textContent = "第 " + (index + 1) + "/" + trace.steps.length +
        " 步：访问 " + step.a + distText + "；前沿 [" + step.state.join(", ") + "]";
    }
    return render;
  }

  function load() {
    const trace = TRACES[algo];
    const render = build(trace);
    anim = makeAnimator(trace.steps.length, () => Number(speed.value), render);
    anim.draw();
  }

  playBtn.addEventListener("click", () => anim.play(playBtn));
  document.getElementById("graph-next").addEventListener("click", () => { anim.stop(playBtn); anim.next(); });
  document.getElementById("graph-prev").addEventListener("click", () => { anim.stop(playBtn); anim.prev(); });
  speed.addEventListener("change", () => { if (anim.setSpeed()) anim.play(playBtn); });
  for (const radio of document.querySelectorAll("input[name=algo]")) {
    radio.addEventListener("change", () => {
      anim.stop(playBtn);
      algo = radio.value;
      load();
    });
  }
  load();
}());
</script>
</body>
</html>
"""


def build_page(traces_dir: str | Path, out_path: str | Path) -> int:
    """把 traces_dir 下的 sort.json / bfs.json / dfs.json 内嵌进单文件 HTML。返回字节数。"""
    traces_dir = Path(traces_dir)
    traces = {name: json.loads((traces_dir / f"{name}.json").read_text(encoding="utf-8"))
              for name in ("sort", "bfs", "dfs")}
    data = json.dumps(traces, ensure_ascii=False, separators=(",", ":"))
    html = _TEMPLATE_HEAD.replace("__TRACES__", data) + _TEMPLATE_TAIL
    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path.stat().st_size
