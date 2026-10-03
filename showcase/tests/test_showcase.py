"""showcase/tests/test_showcase.py —— 展示层校验器的自测。

一条纪律：每个"体检项"都要有一条"改坏必须红"的负面对照；再钉两条真实的——
manifest 现状（33 项、id 唯一）与整树校验通过（含对 B13 生成器的子进程 --check）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "showcase"))

import check as sc  # noqa: E402

GOOD_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>示例 · 展示页</title></head>
<body data-showcase="B13-tinylang">
<section id="facts">数字</section>
<section id="demo">展示</section>
<section id="repro">怎么跑</section>
<footer>生成物：python tools/showcase.py --write</footer>
<script>
const x = 1;
document.title = String(x);
</script>
</body>
</html>
"""


class TestPageLint(unittest.TestCase):
    def test_good_fixture_passes(self):
        problems, notes = sc.lint_page_text(GOOD_PAGE, "B13-tinylang")
        self.assertEqual(problems, [], problems)

    def test_external_script_turns_red(self):
        text = GOOD_PAGE.replace(
            "<footer>", '<script src="https://cdn.example.com/lib.js"></script>\n<footer>')
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertTrue(any("外部" in p for p in problems), problems)

    def test_protocol_relative_url_turns_red(self):
        text = GOOD_PAGE.replace('id="facts">数字', 'id="facts"><img src="//cdn.x/y.png">数字')
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertTrue(any(("外部" in p or "外链" in p) for p in problems), problems)

    def test_w3c_namespace_is_allowed(self):
        text = GOOD_PAGE.replace("const x = 1;", 'const NS = "http://www.w3.org/2000/svg";')
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertEqual(problems, [], problems)

    def test_wrong_project_id_turns_red(self):
        text = GOOD_PAGE.replace('data-showcase="B13-tinylang"', 'data-showcase="B99"')
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertTrue(any("data-showcase" in p for p in problems), problems)

    def test_missing_anchor_turns_red(self):
        for anchor in ("facts", "demo", "repro"):
            text = GOOD_PAGE.replace(f'<section id="{anchor}">', "<section>")
            problems, _ = sc.lint_page_text(text, "B13-tinylang")
            self.assertTrue(any(anchor in p for p in problems), (anchor, problems))

    def test_missing_provenance_turns_red(self):
        text = GOOD_PAGE.replace("python tools/showcase.py --write", "手改的")
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertTrue(any("生成物标记" in p for p in problems), problems)

    def test_innerhtml_turns_red(self):
        text = GOOD_PAGE.replace("document.title = String(x);", "document.body.innerHTML = x;")
        problems, _ = sc.lint_page_text(text, "B13-tinylang")
        self.assertTrue(any("innerHTML" in p for p in problems), problems)

    def test_broken_inline_script_turns_red(self):
        text = GOOD_PAGE.replace("const x = 1;", "const x = ;")
        problems, notes = sc.lint_page_text(text, "B13-tinylang")
        skipped = any("skipped" in n for n in notes)
        if skipped:
            self.skipTest("本机没有 node，按 SPEC 记 skipped")
        self.assertTrue(any("node --check" in p for p in problems), problems)


class TestIndex(unittest.TestCase):
    def manifest(self):
        return {
            "schema": 1,
            "batch_names": {"1": "试点"},
            "projects": [
                {"id": "A-one", "course": "课程一", "title": "项目一", "batch": 1,
                 "status": "done", "page": "projects/A-one/web/showcase.html",
                 "generator": "tools/showcase.py", "note": ""},
                {"id": "B-two", "course": "课程二", "title": "项目二", "batch": 1,
                 "status": "todo", "page": None, "generator": None, "note": "备注"},
            ],
        }

    def test_render_deterministic_and_counts(self):
        text = sc.render_index(self.manifest())
        self.assertEqual(text, sc.render_index(self.manifest()))
        self.assertIn("2 个项目", text)
        self.assertIn("已交付展示页 <strong>1</strong> 个", text)
        self.assertIn('href="../projects/A-one/web/showcase.html"', text)
        self.assertIn("待补", text)

    def test_stale_index_turns_red(self):
        problems = sc.index_problems(self.manifest(), "不一样的文本", ROOT)
        self.assertTrue(any("不一致" in p for p in problems), problems)

    def test_missing_link_target_turns_red(self):
        manifest = json.loads(json.dumps(self.manifest()))
        manifest["projects"][0]["page"] = "showcase/SPEC.md"      # 真实存在
        self.assertEqual(sc.index_problems(manifest, sc.render_index(manifest), ROOT), [])
        manifest["projects"][0]["page"] = "showcase/NOPE.md"      # 目标不存在
        problems = sc.index_problems(manifest, sc.render_index(manifest), ROOT)
        self.assertTrue(any("不存在" in p for p in problems), problems)


class TestManifestAndTree(unittest.TestCase):
    def test_manifest_real_shape(self):
        manifest = sc.load()
        self.assertEqual(len(manifest["projects"]), 33)
        ids = [p["id"] for p in manifest["projects"]]
        self.assertEqual(len(ids), len(set(ids)))
        batches = {p["batch"] for p in manifest["projects"]}
        self.assertEqual(batches, set(range(1, 11)))
        self.assertEqual(sc.manifest_problems(manifest, ROOT), [])

    def test_manifest_missing_page_turns_red(self):
        manifest = sc.load()
        broken = json.loads(json.dumps(manifest))
        for p in broken["projects"]:
            if p["status"] == "done":
                p["page"] = "projects/B13-tinylang/web/nope.html"
        problems = sc.manifest_problems(broken, ROOT)
        self.assertTrue(any("页面不存在" in p for p in problems), problems)

    def test_real_tree_passes(self):
        problems, _notes = sc.check()
        self.assertEqual(problems, [], problems)


if __name__ == "__main__":
    unittest.main()
