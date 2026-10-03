"""planner/viz.py —— 自包含 HTML：搜索展开动画 + 路径高亮（数据内嵌，零框架）

课程要点（可视化技术 / 无人系统的"过程可见"）：
    - 规划算法的输出不止"一条路"，还有**搜索过程**：哪些格子被展开、顺序如何、
      启发式把它们排成了什么形状——动画让"启发式在拉搜索朝哪个方向走"变成肉眼可见；
    - 与 B33 同一条纪律：页面只是"记录下标播放器"，不重算搜索；数据内嵌单文件，
      双击即开；SVG 是拼出来的字符串/元素，零外部依赖。
"""
from __future__ import annotations

import json
from pathlib import Path

_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>B34 路径规划 —— 搜索展开动画</title>
<style>
  body { font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif;
         margin: 0; background: #f5f6f8; color: #222; }
  h1 { font-size: 19px; margin: 14px 18px 2px; }
  .sub { margin: 0 18px 10px; color: #666; font-size: 13px; }
  .card { background: #fff; border: 1px solid #e2e5ea; border-radius: 10px;
          margin: 0 18px 18px; padding: 12px 14px; }
  .controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
              font-size: 13px; margin-top: 8px; }
  button { padding: 4px 10px; border: 1px solid #cfd6df; background: #fff;
           border-radius: 6px; cursor: pointer; font-size: 13px; }
  button:hover { background: #eef3f9; }
  .status { color: #555; min-width: 260px; }
  svg { background: #fafbfc; border-radius: 8px; width: 100%; height: auto; }
  .legend { font-size: 12px; color: #666; margin-top: 6px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
              margin: 0 4px 0 10px; vertical-align: -1px; }
</style>
</head>
<body>
<h1>B34 路径规划 —— 搜索展开动画（A* / Dijkstra 同源）</h1>
<p class="sub">数据内嵌于本页（来自 planner 的搜索结果导出）。播放/单步只是在移动"展开下标"，
页面不重算搜索。绿色为最终路径，冷色渐深表示展开次序，红色是当前展开的格子。</p>
<div class="card">
  <div id="meta" class="sub"></div>
  <svg id="scene" viewBox="0 0 960 560" aria-label="搜索展开动画"></svg>
  <div class="controls">
    <button id="prev">上一步</button>
    <button id="play">播放</button>
    <button id="next">下一步</button>
    <button id="finish">直接看结果</button>
    <span id="status" class="status"></span>
    <label>速度 <select id="speed">
      <option value="400">0.5×</option>
      <option value="200" selected>1×</option>
      <option value="100">2×</option>
      <option value="50">4×</option>
    </select></label>
  </div>
  <p class="legend"><i style="background:#2f3b52"></i>障碍
    <i style="background:#cfe3f7"></i>早期展开
    <i style="background:#2a6fbb"></i>晚期展开
    <i style="background:#d62728"></i>当前展开
    <i style="background:#2ca02c"></i>最终路径
    <i style="background:#ff9f1c"></i>起点/终点</p>
</div>
<script>
const TRACE = __TRACE__;
"""

_TAIL = """
const svg = document.getElementById("scene");
const NS = "http://www.w3.org/2000/svg";
const grid = TRACE.grid;
const cell = Math.min(54, Math.floor(920 / grid.width), Math.floor(520 / grid.height));
const ox = 20, oy = 20;
const meta = document.getElementById("meta");
const status = document.getElementById("status");

meta.textContent = "地图 " + grid.width + "×" + grid.height +
  (grid.diagonal ? "（8 邻域）" : "（4 邻域）") + "；启发式 " + TRACE.meta.heuristic +
  "；展开 " + TRACE.meta.expanded + " 个；路径代价 " + TRACE.meta.cost.toFixed(3) +
  "；路径长 " + TRACE.path.length + " 格（障碍 " + grid.obstacles.length + " 个）";

const obstacleSet = new Set(grid.obstacles.map(p => p[0] + "," + p[1]));
const expandRank = new Map();
TRACE.steps.forEach((cellXY, i) => expandRank.set(cellXY[0] + "," + cellXY[1], i));

function cellRect(x, y, fill, extra) {
  const r = document.createElementNS(NS, "rect");
  r.setAttribute("x", ox + x * cell + 1); r.setAttribute("y", oy + y * cell + 1);
  r.setAttribute("width", cell - 2); r.setAttribute("height", cell - 2);
  r.setAttribute("fill", fill);
  if (extra) r.setAttribute("style", extra);
  return r;
}

function buildScene() {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  for (let y = 0; y < grid.height; y += 1) {
    for (let x = 0; x < grid.width; x += 1) {
      const key = x + "," + y;
      const isObs = obstacleSet.has(key);
      svg.appendChild(cellRect(x, y, isObs ? "#2f3b52" : "#fbfcfd"));
    }
  }
}
buildScene();

function draw(index) {
  buildScene();
  const totalSteps = TRACE.steps.length;
  for (let i = 0; i < Math.min(index + 1, totalSteps); i += 1) {
    const [x, y] = TRACE.steps[i];
    const t = totalSteps <= 1 ? 0 : i / (totalSteps - 1);
    const r = Math.round(207 - t * 165), g = Math.round(227 - t * 116), b = Math.round(247 + t * 0);
    svg.appendChild(cellRect(x, y, "rgb(" + r + "," + g + "," + b + ")"));
    if (i === index) {
      const [cx, cy] = TRACE.steps[index];
      svg.appendChild(cellRect(cx, cy, "#d62728"));
    }
  }
  if (index >= totalSteps - 1 && TRACE.path.length) {
    for (const [x, y] of TRACE.path) svg.appendChild(cellRect(x, y, "#2ca02c", "opacity:0.75"));
  }
  const [sx0, sy0] = TRACE.start, [gx0, gy0] = TRACE.goal;
  svg.appendChild(cellRect(sx0, sy0, "#ff9f1c"));
  svg.appendChild(cellRect(gx0, gy0, "#ff9f1c", "opacity:0.55"));
  const done = index >= totalSteps - 1;
  status.textContent = "展开第 " + Math.min(index + 1, totalSteps) + "/" + totalSteps +
    " 个；当前：" + TRACE.steps[Math.min(index, totalSteps - 1)].join(",") +
    (done ? "；已到终点，绿色为最终路径" : "");
}

const speedSel = document.getElementById("speed");
const playBtn = document.getElementById("play");
let index = 0;
let timer = null;

function stopTimer() { if (timer) { clearInterval(timer); timer = null; playBtn.textContent = "播放"; } }
document.getElementById("next").addEventListener("click", () => {
  stopTimer(); if (index < TRACE.steps.length - 1) index += 1; draw(index);
});
document.getElementById("prev").addEventListener("click", () => {
  stopTimer(); if (index > 0) index -= 1; draw(index);
});
document.getElementById("finish").addEventListener("click", () => {
  stopTimer(); index = TRACE.steps.length - 1; draw(index);
});
playBtn.addEventListener("click", () => {
  if (timer) { stopTimer(); return; }
  playBtn.textContent = "暂停";
  timer = setInterval(() => {
    if (index >= TRACE.steps.length - 1) { stopTimer(); return; }
    index += 1; draw(index);
  }, Number(speedSel.value));
});
speedSel.addEventListener("change", () => { if (timer) { stopTimer(); playBtn.click(); } });
draw(0);
</script>
</body>
</html>
"""


def export_trace(grid, start, goal, result, heuristic_name: str) -> dict:
    """把一次搜索的结果变成可回放的记录（页面数据契约）。"""
    return {
        "grid": {"width": grid.width, "height": grid.height,
                 "diagonal": grid.allow_diagonal,
                 "obstacles": sorted([x, y] for x, y in grid.obstacles)},
        "start": list(start),
        "goal": list(goal),
        "steps": [list(c) for c in result.expanded],
        "path": [list(c) for c in result.path],
        "meta": {"heuristic": heuristic_name, "expanded": result.expanded_count,
                 "cost": float(result.cost) if result.found else -1.0},
    }


def build_page(trace: dict, out_path) -> int:
    data = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    html = _HEAD.replace("__TRACE__", data) + _TAIL
    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path.stat().st_size
