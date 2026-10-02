"""mqttlite/svgplot.py —— 手写 SVG 折线图（曲线页零依赖，写进 build/）

课程要点：物联网的"最后一公里"往往是一张给人看的曲线。不引图表库，
直接生成自包含 SVG：坐标映射（值域→画布）、折线点列、异常标记、图例——
和 B28 的仪表盘同一条纪律：**SVG 是我们拼出来的字符串，形状由数据决定**。
"""
from __future__ import annotations

from pathlib import Path

PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf"]


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def line_chart(out_path: str | Path, series: dict[str, list[tuple[float, float]]],
               anomalies: list[tuple[float, float, str]] | None = None,
               title: str = "", y_label: str = "", width: int = 900, height: int = 420,
               padding: int = 60) -> int:
    """series: {设备名: [(x, y), ...]}；anomalies: [(x, y, 标签)]。返回写入字节数。"""
    all_pts = [pt for pts in series.values() for pt in pts]
    if not all_pts:
        raise ValueError("没有数据点，画不了图")
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if y1 == y0:
        y1 = y0 + 1.0
    y0, y1 = y0 - (y1 - y0) * 0.05, y1 + (y1 - y0) * 0.05

    def sx(x: float) -> float:
        return padding + (x - x0) / (x1 - x0 or 1) * (width - 2 * padding)

    def sy(y: float) -> float:
        return height - padding - (y - y0) / (y1 - y0) * (height - 2 * padding)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{width/2}" y="26" text-anchor="middle" font-size="18" '
        f'font-family="sans-serif">{_esc(title)}</text>',
    ]
    # 坐标轴
    parts.append(f'<line x1="{padding}" y1="{height-padding}" x2="{width-padding}" '
                 f'y2="{height-padding}" stroke="#333"/>')
    parts.append(f'<line x1="{padding}" y1="{padding}" x2="{padding}" '
                 f'y2="{height-padding}" stroke="#333"/>')
    # y 轴刻度（4 档，值直接标出来）
    for i in range(5):
        value = y0 + (y1 - y0) * i / 4
        py = sy(value)
        parts.append(f'<line x1="{padding}" y1="{py:.1f}" x2="{width-padding}" y2="{py:.1f}" '
                     f'stroke="#eeeeee"/>')
        parts.append(f'<text x="{padding-6}" y="{py+4:.1f}" text-anchor="end" font-size="11" '
                     f'font-family="sans-serif">{value:.1f}</text>')
    # 折线
    for index, (label, pts) in enumerate(series.items()):
        color = PALETTE[index % len(PALETTE)]
        point_str = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in pts)
        parts.append(f'<polyline points="{point_str}" fill="none" stroke="{color}" '
                     f'stroke-width="1.6"/>')
        lx = padding + 12 + index * 150
        parts.append(f'<line x1="{lx}" y1="44" x2="{lx+22}" y2="44" stroke="{color}" '
                     f'stroke-width="3"/>')
        parts.append(f'<text x="{lx+28}" y="48" font-size="12" '
                     f'font-family="sans-serif">{_esc(label)}</text>')
    # 异常标记
    for x, y, label in anomalies or []:
        parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="none" '
                     f'stroke="#d62728" stroke-width="1.6"><title>{_esc(label)}</title></circle>')
    # x 轴两端标签（seq 范围）与 y 轴名
    parts.append(f'<text x="{padding}" y="{height-padding+18}" font-size="11" '
                 f'font-family="sans-serif">{x0:.0f}</text>')
    parts.append(f'<text x="{width-padding}" y="{height-padding+18}" text-anchor="end" '
                 f'font-size="11" font-family="sans-serif">{x1:.0f}</text>')
    parts.append(f'<text x="14" y="{padding}" font-size="12" '
                 f'font-family="sans-serif">{_esc(y_label)}</text>')
    parts.append("</svg>")

    out_path = Path(out_path)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return out_path.stat().st_size
