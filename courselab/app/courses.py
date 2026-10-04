"""课程/项目内容层（现算自仓库，唯一出处）。

- showcase/manifest.json：33 门课程/项目（课程名、项目、批次、状态、展示页）
- g2/cards.json：每门课的"一句话 / 知识点表 / 练习任务 / 踩坑单 / 材料清单"
按 project id 合并；文件 mtime 变了自动重载（仓库改了，平台跟着变）。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # courselab/
REPO = ROOT.parent                              # 课设仓库根
MANIFEST = REPO / "showcase" / "manifest.json"
CARDS = REPO / "g2" / "cards.json"

_cache: dict = {"key": None, "data": None}


def _plain(text: str) -> str:
    """卡片里的 Markdown 强调记号去掉，给页面直显。"""
    return (text or "").replace("**", "").replace("`", "").strip()


def _knowledge_rows(rows) -> list:
    out = []
    for line in rows or []:
        line = (line or "").strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not any(cells):
            continue
        if all(set(c) <= set("-: ") for c in cells):        # 分隔行
            continue
        if cells and cells[0] == "课程知识点":               # 表头
            continue
        out.append(cells)
    return out


def catalog() -> dict:
    key = (MANIFEST.stat().st_mtime, CARDS.stat().st_mtime if CARDS.exists() else 0)
    if _cache["data"] is None or _cache["key"] != key:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cards = {}
        if CARDS.exists():
            for c in json.loads(CARDS.read_text(encoding="utf-8")):
                if c.get("project"):
                    cards[c["project"]] = c
        projects = []
        for p in manifest["projects"]:
            card = cards.get(p["id"], {})
            projects.append({
                "id": p["id"], "course": p["course"], "title": p["title"],
                "batch": str(p["batch"]), "status": p["status"], "page": p.get("page"),
                "summary": _plain(card.get("summary", "")),
                "has_card": bool(card),
            })
        _cache.update(key=key, data={"projects": projects, "cards": cards})
    return _cache["data"]


def course_list() -> dict:
    cat = catalog()
    return {"ok": True, "count": len(cat["projects"]),
            "cards": len(cat["cards"]), "courses": cat["projects"]}


def course_detail(cid: str):
    cat = catalog()
    proj = next((p for p in cat["projects"] if p["id"] == cid), None)
    if proj is None:
        return None
    card = cat["cards"].get(cid, {})
    base = REPO / "projects" / cid
    materials = []
    for m in card.get("materials", []):
        target = base / m
        kind = "dir" if target.is_dir() else ("file" if target.is_file() else "missing")
        materials.append({"path": m, "kind": kind,
                          "url": f"/repo/projects/{cid}/{m}" if kind == "file" else None})
    return {
        **proj,
        "knowledge": _knowledge_rows(card.get("knowledge", [])),
        "tasks": [{"text": _plain(t.get("raw", "")), "from": t.get("from", "")}
                  for t in card.get("tasks", [])],
        "pits": [_plain(x) for x in card.get("pin_list", [])],
        "materials": materials,
    }
