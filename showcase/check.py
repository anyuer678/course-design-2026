"""showcase/check.py —— 展示层工程的仓库级校验器（口径：showcase/SPEC.md）。

做四件事，任何一件红都会指名道姓：

1. **manifest 自洽**：id 唯一、批次齐全、`done` 项必须有 page/generator 且文件存在；
2. **每个已交付页面的静态体检**（`lint_page_text`）：编码/标题/必备锚点/`data-showcase`/
   生成物标记/零外链/无危险 DOM 写法/内联脚本过 `node --check`（没装 node 记 skipped）；
3. **逐项目新鲜度**：对每个 `done` 项目跑子进程 `python tools/showcase.py --check`
   （重算比对；页面过期、数据分叉都在那边红）；
4. **总入口**：`index.html` 与 manifest 现算一致、页内链接目标都存在。

用法：

```
python showcase/check.py               # 全部校验
python showcase/check.py --write-index # 重生成 showcase/index.html
```
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / "manifest.json"
INDEX = Path(__file__).resolve().parent / "index.html"

#: 全文允许出现的唯一外部地址形态：W3C 命名空间串（它是标识符，不是网络请求）。
URL_EXCEPTIONS = ("http://www.w3.org/", "https://www.w3.org/")
ANCHORS = ("facts", "demo", "repro")
PROVENANCE = "tools/showcase.py --write"


# ------------------------------------------------------------------ manifest

def load(path: Path | None = None) -> dict:
    return json.loads((path or MANIFEST).read_text(encoding="utf-8"))


def manifest_problems(manifest: dict, root: Path) -> list:
    out = []
    projects = manifest.get("projects", [])
    ids = [p["id"] for p in projects]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        out.append(f"manifest id 重复：{dupes}")
    batches = manifest.get("batch_names", {})
    for p in projects:
        if str(p.get("batch")) not in batches:
            out.append(f"{p['id']} 的批次 {p.get('batch')} 不在 batch_names 里")
        if p.get("status") not in ("done", "todo"):
            out.append(f"{p['id']} 的 status 只能是 done/todo，收到 {p.get('status')!r}")
        if p.get("status") == "done":
            if not p.get("page"):
                out.append(f"{p['id']} 标了 done 却没有 page")
            elif not (root / p["page"]).is_file():
                out.append(f"{p['id']} 的页面不存在：{p['page']}")
            if not p.get("generator"):
                out.append(f"{p['id']} 标了 done 却没有 generator")
            elif not (root / "projects" / p["id"] / p["generator"]).is_file():
                out.append(f"{p['id']} 的生成器不存在：{p['generator']}")
    return out


# ------------------------------------------------------------------ 页面体检

def _external_refs(text: str) -> list:
    out = []
    for m in re.finditer(r'(?:src|href)\s*=\s*["\']([^"\']*)["\']', text):
        value = m.group(1).strip()
        if not value or value.startswith("#"):
            continue
        if "://" in value or value.startswith("//") or value.startswith(("mailto:", "javascript:")):
            out.append(f"属性外链：{value[:70]}")
    for m in re.finditer(r"url\(\s*[\"']?([^)\"']+)", text):
        value = m.group(1).strip()
        if value.startswith(("http:", "https:", "//")):
            out.append(f"CSS 外链：{value[:70]}")
    for m in re.finditer(r"https?://[^\s\"'<>)]+", text):
        if not m.group(0).startswith(URL_EXCEPTIONS):
            out.append(f"页内出现外部地址：{m.group(0)[:70]}")
    return out


def _node_check(scripts: list) -> tuple:
    """内联脚本过 node --check。返回 (problems, notes)。"""
    if not scripts:
        return [], []
    if not shutil.which("node"):
        return [], ["node 不在 PATH：内联脚本语法检查 skipped"]
    joined = "\n;\n".join(scripts)
    with tempfile.TemporaryDirectory(prefix="showcase-node-") as tmp:
        path = Path(tmp) / "inline.js"
        path.write_text(joined, encoding="utf-8")
        proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        return [f"内联脚本没过 node --check：{(proc.stderr or '').strip().splitlines()[-1][:100]}"], []
    return [], [f"内联脚本 node --check 通过（{len(scripts)} 段）"]


def lint_page_text(text: str, pid: str) -> tuple:
    """页面静态体检。返回 (problems, notes)。纯函数，测试直接喂文本。"""
    problems = []
    if not text.startswith("<!DOCTYPE html>"):
        problems.append("不是以 <!DOCTYPE html> 开头")
    if 'lang="zh-CN"' not in text:
        problems.append('缺少 lang="zh-CN"')
    if '<meta charset="utf-8">' not in text:
        problems.append("缺少 <meta charset=\"utf-8\">")
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    if not title or not title.group(1).strip():
        problems.append("缺少非空的 <title>")
    if f'data-showcase="{pid}"' not in text:
        problems.append(f'缺少 data-showcase="{pid}"（与 manifest 对不上？）')
    for anchor in ANCHORS:
        if f'id="{anchor}"' not in text:
            problems.append(f"缺少必备锚点 id=\"{anchor}\"")
    if PROVENANCE not in text:
        problems.append(f"页脚缺少生成物标记「{PROVENANCE}」")
    problems.extend(_external_refs(text))
    for pattern in (r"\.\s*innerHTML\s*=", r"\.\s*outerHTML\s*=",
                    r"document\s*\.\s*write", r"insertAdjacentHTML"):
        if re.search(pattern, text):
            problems.append(f"危险 DOM 写法：{pattern}")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S)
    node_problems, notes = _node_check(scripts)
    problems.extend(node_problems)
    return problems, notes


# ------------------------------------------------------------------ 总入口

INDEX_JS = """\
(function(){
  "use strict";
  var q = document.getElementById("q");
  var cnt = document.getElementById("count");
  var chipBox = document.getElementById("chips");
  var items = Array.prototype.slice.call(document.querySelectorAll("li[data-id]"));
  var sections = Array.prototype.slice.call(document.querySelectorAll("section[data-batch]"));
  var cur = "all";

  function visible(it){
    var okB = cur === "all" || it.dataset.batch === cur;
    var kw = q.value.trim().toLowerCase();
    var okQ = !kw || (it.dataset.id + " " + it.dataset.course).toLowerCase().indexOf(kw) >= 0;
    return okB && okQ;
  }
  function apply(){
    var shown = 0;
    items.forEach(function(it){
      var vis = visible(it);
      it.style.display = vis ? "" : "none";
      if (vis) shown++;
    });
    sections.forEach(function(sec){
      var any = items.some(function(it){
        return it.dataset.batch === sec.dataset.batch && it.style.display !== "none";
      });
      sec.style.display = any ? "" : "none";
    });
    cnt.textContent = "显示 " + shown + " / " + items.length;
  }
  function chip(label, val){
    var b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (val === cur ? " active" : "");
    b.textContent = label;
    b.addEventListener("click", function(){
      cur = val;
      Array.prototype.forEach.call(chipBox.children, function(c){
        c.className = "chip" + (c === b ? " active" : "");
      });
      apply();
    });
    chipBox.appendChild(b);
  }
  chip("全部（" + items.length + "）", "all");
  sections.forEach(function(sec){
    var n = items.filter(function(it){ return it.dataset.batch === sec.dataset.batch; }).length;
    chip("批次 " + sec.dataset.batch + "（" + n + "）", sec.dataset.batch);
  });
  q.addEventListener("input", apply);
  document.addEventListener("keydown", function(e){
    if (e.key === "/" && document.activeElement !== q){
      e.preventDefault();
      q.focus();
    } else if (e.key === "Escape"){
      q.value = "";
      apply();
      q.blur();
    } else if (e.key === "Enter" && document.activeElement === q){
      var first = items.filter(visible)[0];
      var a = first && first.querySelector("a");
      if (a) a.click();
    }
  });
  apply();
})();"""


def render_index(manifest: dict) -> str:
    projects = manifest["projects"]
    batches = manifest["batch_names"]
    done = [p for p in projects if p["status"] == "done"]
    lines = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>课设作品集 · 33 个项目</title>",
        "<style>",
        ":root{--ink:#16181d;--muted:#5f6773;--line:#d5d9e0;--card:#fff;--bg:#f7f8fa;--ok:#14603a;--todo:#8a5a00}",
        "*{box-sizing:border-box}body{margin:0;padding:2rem 1.2rem 4rem;background:var(--bg);color:var(--ink);"
        'font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}',
        "main{max-width:62rem;margin:0 auto}h1{font-size:1.6rem;margin:.2rem 0}h2{font-size:1.05rem;margin:1.6rem 0 .4rem}"
        "h2 .n{color:var(--muted);font-weight:400;font-size:.9rem}",
        "p.note{color:var(--muted);font-size:.88rem}ul{list-style:none;padding:0;margin:.2rem 0}"
        "li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.6rem .9rem;margin:.45rem 0;"
        "display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap;transition:border-color .12s,box-shadow .12s}"
        "li:hover{border-color:#1d4ed8;box-shadow:0 2px 8px rgba(29,78,216,.14)}",
        "a{color:#1d4ed8;text-decoration:none;font-weight:600}a:hover{text-decoration:underline}",
        ".course{color:var(--muted);font-size:.85rem}.note2{color:var(--muted);font-size:.85rem}",
        ".badge{font-size:.78rem;padding:.05rem .5rem;border-radius:999px;border:1px solid var(--line)}"
        ".badge.ok{color:var(--ok);border-color:var(--ok)}.badge.todo{color:var(--todo)}",
        ".tools{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:.8rem 0 .2rem}"
        ".tools input{flex:1;min-width:16rem;font:inherit;font-size:.95rem;padding:.45rem .8rem;"
        "border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink)}"
        ".tools input:focus{outline:2px solid #1d4ed8;outline-offset:1px}",
        ".chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .6rem}"
        ".chip{font:inherit;font-size:.85rem;padding:.22rem .7rem;border:1px solid var(--line);"
        "border-radius:999px;background:#fff;cursor:pointer;color:var(--ink)}"
        ".chip:hover{border-color:#1d4ed8}.chip.active{background:#1d4ed8;border-color:#1d4ed8;color:#fff}",
        ".cnt{color:var(--muted);font-size:.85rem;white-space:nowrap}",
        "footer{color:var(--muted);font-size:.85rem;margin-top:2.5rem}",
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>课设作品集</h1>",
        f'<p class="note">{len(projects)} 个项目 · 已交付展示页 <strong>{len(done)}</strong> 个（每页双击即看、零网络依赖；'
        "页面为生成物，检验器与批次表见 <code>showcase/SPEC.md</code>）。</p>",
        '<div class="tools">'
        '<input id="q" type="search" autocomplete="off" '
        'placeholder="搜索：项目编号 / 课程 / 关键词（按 / 聚焦，Esc 清空，回车打开第一条）">'
        '<span id="count" class="cnt"></span></div>',
        '<div class="chips" id="chips"></div>',
    ]
    for batch in sorted(batches, key=int):
        members = [p for p in projects if str(p["batch"]) == batch]
        if not members:
            continue
        lines.append(f'<section data-batch="{batch}">')
        lines.append(f'<h2>批次 {batch} · {html.escape(batches[batch])} '
                     f'<span class="n">{len(members)} 项</span></h2>')
        lines.append("<ul>")
        for p in members:
            title = html.escape(p["title"])
            course = html.escape(p["course"])
            attrs = (f'data-id="{html.escape(p["id"], quote=True)}" '
                     f'data-batch="{batch}" '
                     f'data-course="{html.escape(p["course"] + " " + p["title"], quote=True)}"')
            if p["status"] == "done":
                href = html.escape("../" + p["page"])
                lines.append(f'<li {attrs}><a href="{href}">{p["id"]}</a>'
                             f'<span class="course">{course} · {title}</span>'
                             f'<span class="badge ok">已交付</span></li>')
            else:
                note = f' · {html.escape(p["note"])}' if p.get("note") else ""
                lines.append(f'<li {attrs}><span>{p["id"]}</span>'
                             f'<span class="course">{course} · {title}{note}</span>'
                             f'<span class="badge todo">待补</span></li>')
        lines.append("</ul>")
        lines.append("</section>")
    lines += [
        "<footer>",
        "<p>页面里的数字来自各项目真实产物的现算；观感与顺手程度归你实跑验收。</p>",
        "<p><strong>实时控制真实后端</strong>：仓库根跑 <code>python showcase/lab.py</code> 后，"
        "从 http://127.0.0.1:7788/showcase/index.html 打开（或刷新任一页），右下角会出现实验台面板："
        "可启动/停止各项目的真实服务（B11/B31/B38/B35/B28/dorm 六个已注册）、发送真实请求、"
        "实时看服务与 demo/测试的输出。实验台没启动时页面仍是原来的静态自包含页。</p>",
        "<p>重生成本页：<code>python showcase/check.py --write-index</code>（清单在 "
        "<code>showcase/manifest.json</code>）。</p>",
        "</footer>",
        "</main>",
        f"<script>{INDEX_JS}</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(lines)


def index_problems(manifest: dict, index_text: str, root: Path) -> list:
    out = []
    if index_text != render_index(manifest):
        out.append("showcase/index.html 与 manifest 现算不一致（过期或手改过）："
                   "跑 python showcase/check.py --write-index")
    for m in re.finditer(r'(?:src|href)\s*=\s*["\']([^"\']*)["\']', index_text):
        value = m.group(1).strip()
        if value.startswith("#") or not value:
            continue
        if "://" in value or value.startswith("//"):
            continue
        target = (INDEX.parent / value).resolve()
        if not target.exists():
            out.append(f"总入口链接不存在：{value}")
    return out


# ------------------------------------------------------------------ 全量校验

def project_check(root: Path, entry: dict) -> tuple:
    """子进程跑项目自己的生成器 --check。返回 (problems, notes)。"""
    project_dir = root / "projects" / entry["id"]
    generator = project_dir / entry["generator"]
    try:
        proc = subprocess.run([sys.executable, str(generator), "--check"],
                              cwd=str(project_dir), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        return [f"{entry['id']} 的生成器 --check 超时（300 秒）"], []
    tail = [line for line in (proc.stdout or "").strip().splitlines() if line][-3:]
    if proc.returncode != 0:
        detail = " / ".join(tail) or (proc.stderr or "").strip().splitlines()[-1:]
        return [f"{entry['id']} 的生成器 --check 失败：{detail}"], []
    return [], tail


def check(root: Path | None = None) -> tuple:
    root = root or ROOT
    manifest = load()
    problems = manifest_problems(manifest, root)
    notes = []
    for entry in manifest["projects"]:
        if entry["status"] != "done":
            continue
        page = root / entry["page"]
        if not page.is_file():
            continue          # manifest_problems 已经报了
        text = page.read_text(encoding="utf-8")
        page_problems, page_notes = lint_page_text(text, entry["id"])
        problems.extend(f"{entry['id']}：{p}" for p in page_problems)
        notes.extend(f"{entry['id']}：{n}" for n in page_notes)
        sub_problems, sub_notes = project_check(root, entry)
        problems.extend(sub_problems)
        notes.extend(f"{entry['id']}：{n}" for n in sub_notes)
    if INDEX.is_file():
        problems.extend(index_problems(manifest, INDEX.read_text(encoding="utf-8"), root))
    else:
        problems.append("showcase/index.html 不存在：跑 python showcase/check.py --write-index")
    return problems, notes


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="展示层工程仓库级校验（口径：showcase/SPEC.md）")
    ap.add_argument("--write-index", action="store_true", help="重生成 showcase/index.html")
    args = ap.parse_args(argv[1:])
    if args.write_index:
        manifest = load()
        INDEX.write_text(render_index(manifest), encoding="utf-8", newline="\n")
        done = sum(1 for p in manifest["projects"] if p["status"] == "done")
        total = len(manifest["projects"])
        print(f"已写出 showcase/index.html：{total} 个项目（已交付 {done}）；"
              f"改过 manifest.json 后重跑；校验用 python showcase/check.py")
        return 0
    problems, notes = check()
    for note in notes:
        print(f"[note] {note}")
    if problems:
        print(f"展示层校验发现 {len(problems)} 处问题：")
        for p in problems:
            print("  -", p)
        return 1
    manifest = load()
    done = sum(1 for p in manifest["projects"] if p["status"] == "done")
    print(f"展示层校验通过：{len(manifest['projects'])} 个项目里已交付 {done} 个页面，"
          f"结构/自包含/逐项目新鲜度/总入口全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
