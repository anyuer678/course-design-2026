"""kg/viz.py —— 零依赖可视化：手写 SVG 分层布局 + 自包含交互 HTML

课程要点（可视化技术提前试水）：
    - 分层布局 = 按拓扑层级（最长路径深度）排 x，同层按批次/编号排 y；
      边画成折线（正交连线），跨层可读。
    - 交互 = 选中节点高亮其全部（含间接）先修——用内嵌 JSON 的传递闭包
      数据在浏览器里现场着色，不需要任何图表库。
    - 自包含：单 HTML 文件内嵌全部数据与脚本，无 CDN、无外部请求。
"""
from __future__ import annotations

import json
import math

from .graph import KnowledgeGraph

NODE_W, NODE_H, GAP_X, GAP_Y = 168, 44, 60, 26


def _layers(g: KnowledgeGraph) -> dict[str, int]:
    """层号 = 从任意源点出发的最长路径深度（保证边总是从浅层指向深层）。"""
    layer: dict[str, int] = {}
    order = g.topological_order()
    for t in order:
        preds = [layer[e["src"]] for e in g.edges
                 if e["dst"] == t and e["src"] in layer]
        layer[t] = (max(preds) + 1) if preds else 0
    return layer


def render_html(g: KnowledgeGraph, title: str = "课程先修知识图谱",
                source_note: str = "数据来源：data/courses.csv 与 data/prereqs.csv（PLAN §3 依赖表转写）。"
                                   "本页为自包含文件：{n} 个任务节点、{m} 条关系边。") -> str:
    layers = _layers(g)
    by_layer: dict[int, list[str]] = {}
    for t, lv in layers.items():
        by_layer.setdefault(lv, []).append(t)

    positions: dict[str, tuple[float, float]] = {}
    max_h = 0
    for lv in sorted(by_layer):
        members = sorted(by_layer[lv],
                         key=lambda t: (g.nodes[t]["batch"], t))
        for k, t in enumerate(members):
            x = 40 + lv * (NODE_W + GAP_X)
            y = 40 + k * (NODE_H + GAP_Y)
            positions[t] = (x, y)
        max_h = max(max_h, 40 + len(members) * (NODE_H + GAP_Y))
    width = 40 + (max(layers.values()) + 1) * (NODE_W + GAP_X)
    height = max_h + 80

    # 闭包数据：点一个节点，JS 高亮它的全部（含间接）先修与解锁后继
    closure = {t: {"anc": sorted(g.ancestors(t)), "des": sorted(g.descendants(t))}
               for t in g.nodes}

    svg_edges = []
    for e in g.edges:
        x1, y1 = positions[e["src"]]
        x2, y2 = positions[e["dst"]]
        x1 += NODE_W
        y1 += NODE_H / 2
        x2 -= 8
        y2 += NODE_H / 2
        mid = (x1 + x2) / 2
        color = {"先修": "#b3261e", "概念支撑": "#7c4dff",
                 "迭代阶段": "#2e6fdb"}.get(e["kind"], "#888")
        svg_edges.append(
            f'<path class="edge" data-src="{e["src"]}" data-dst="{e["dst"]}" '
            f'd="M {x1:.0f} {y1:.0f} C {mid:.0f} {y1:.0f}, {mid:.0f} {y2:.0f}, '
            f'{x2:.0f} {y2:.0f}" stroke="{color}" fill="none" '
            f'marker-end="url(#arrow-{color.lstrip("#")})" />')

    svg_nodes = []
    for t, (x, y) in sorted(positions.items()):
        info = g.nodes[t]
        label = info["courses"].replace("&", "&amp;").replace("<", "&lt;")
        short = label.split("+")[0].strip()
        svg_nodes.append(
            f'<g class="node" data-id="{t}" transform="translate({x:.0f},{y:.0f})" '
            f'role="button" tabindex="0">'
            f'<rect width="{NODE_W}" height="{NODE_H}" rx="8" />'
            f'<text class="tid" x="10" y="18">{t} · 批次{info["batch"]}</text>'
            f'<text class="tname" x="10" y="34">{short[:18]}</text>'
            f'<title>{t}：{label}</title></g>')

    legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{k}</span>'
        for k, c in [("先修", "#b3261e"), ("概念支撑", "#7c4dff"),
                     ("迭代阶段", "#2e6fdb")])

    arrow_defs = "".join(
        f'<marker id="arrow-{c.lstrip("#")}" viewBox="0 0 10 10" refX="9" '
        f'refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
        for c in ("#b3261e", "#7c4dff", "#2e6fdb"))

    data_json = json.dumps(closure, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 16px; background:#fafafa; }}
h1 {{ font-size: 20px; }}
.legend {{ margin: 8px 0 12px; font-size: 13px; color:#444; }}
.lg i {{ display:inline-block; width:22px; height:4px; margin: 0 4px 2px 12px; }}
svg {{ background: #fff; border: 1px solid #ddd; }}
.node rect {{ fill: #eef3ff; stroke: #4a6fa5; stroke-width: 1.2; cursor: pointer; }}
.node:hover rect {{ fill: #ffe9a8; }}
.node text {{ font-size: 12px; fill: #222; pointer-events: none; }}
.edge {{ opacity: .55; }}
.dim {{ opacity: .08; }}
.hl {{ opacity: 1; stroke-width: 2.5; }}
.hint {{ color:#666; font-size: 13px; }}
</style></head><body>
<h1>{title}</h1>
<div class="legend">{legend}<span class="hint">　点击节点：红色高亮其全部先修（含间接），蓝色高亮解锁的后继</span></div>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs>{arrow_defs}</defs>
{''.join(svg_edges)}
{''.join(svg_nodes)}
</svg>
<script>
const CLOSURE = {data_json};
document.querySelectorAll('.node').forEach(node => {{
  node.addEventListener('click', () => {{
    const id = node.dataset.id;
    const anc = new Set(CLOSURE[id].anc);
    const des = new Set(CLOSURE[id].des);
    document.querySelectorAll('.edge').forEach(p => {{
      const s = p.dataset.src, d = p.dataset.dst;
      p.classList.remove('hl', 'dim');
      if (s === id || anc.has(s)) {{ if (des.has(d) || d === id) {{ p.classList.add('hl'); }} else {{ p.classList.add('hl'); }} }}
      else {{ p.classList.add('dim'); }}
    }});
    document.querySelectorAll('.node').forEach(n => {{
      const t = n.dataset.id;
      n.style.opacity = (t === id || anc.has(t) || des.has(t)) ? '1' : '.25';
    }});
  }});
}});
</script>
<p class="hint">{source_note.format(n=len(g.nodes), m=len(g.edges))}</p>
</body></html>"""
