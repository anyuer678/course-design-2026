"""tests/showcase_check.py —— B8 展示页生成器自测（口径：showcase/SPEC.md）。

**命名说明（为什么不是 test_showcase.py）**：本项目的主测试在 WSL 里跑
（`python3 -m unittest discover -s tests`），"双入口同数 = 24" 是 run.sh 的硬口径；
`test*.py` 命名的文件会被 WSL 的 discover 抓到（模块级跳过也计入 Ran，实测会破 24 的口径），
所以展示页测试起名 `showcase_check.py`（不在 discover 模式内），只在 Windows 侧直跑：
`python tests\\showcase_check.py`。它与其它项目的 test_showcase.py 职责完全相同。

钉住：页面新鲜度、WSL 采集的解析（双入口同数 24、六段演示、八脚本回放、退出码 {0,1,42,127}）、
路径规范化、改坏必红、页面标记与零外链。每个用例都经一次 WSL 采集（每次约 10 秒，是设计成本）。
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import showcase as sc  # noqa: E402


def quiet_main(argv) -> int:
    with redirect_stdout(io.StringIO()):
        return sc.main(argv)


class TestPageFreshness(unittest.TestCase):
    def test_page_exists_and_fresh(self):
        self.assertTrue(sc.OUT.is_file(), "web/showcase.html 不存在——跑 --write")
        self.assertEqual(quiet_main(["showcase", "--check"]), 0)

    def test_tampered_page_turns_red(self):
        original = sc.OUT
        with tempfile.TemporaryDirectory(prefix="b8-showcase-") as tmp:
            fake = Path(tmp) / "showcase.html"
            fake.write_text("手改过的页面", encoding="utf-8")
            sc.OUT = fake
            try:
                self.assertEqual(quiet_main(["showcase", "--check"]), 1)
            finally:
                sc.OUT = original


class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = sc.collect()

    def test_dual_entry_same_count(self):
        self.assertEqual(self.payload["ran"], (24, 24))

    def test_demo_sections_and_readings(self):
        sections = self.payload["sections"]
        self.assertEqual([s["no"] for s in sections], [1, 2, 3, 4, 5, 6])
        self.assertEqual(sections[0]["title"], "命令执行与退出状态")
        self.assertEqual(self.payload["exit_codes"], {"true": 0, "false": 1, "exit 42": 42})
        self.assertEqual(self.payload["zombies"], 0)

    def test_replay_is_a_live_session(self):
        replay = self.payload["replay"]
        self.assertIn("--- 1) 三段管道", replay)
        self.assertIn("| a", replay)  # 管道输出现场（printf c/b/a | sort | head -2）
        self.assertIn("msh 退出码 127", replay, "错误路径必须真的拿到 127")
        self.assertIn("still alive", replay, "报错后要继续执行")
        self.assertIn("first", replay)
        self.assertIn("second", replay)

    def test_path_normalization(self):
        self.assertNotIn("/mnt/c/", self.payload["demo"])
        self.assertIn("<项目根>", self.payload["demo"])


class TestRenderedPage(unittest.TestCase):
    def test_required_markers(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for marker in ('data-showcase="B8-mini-shell"', 'id="facts"', 'id="demo"',
                       'id="repro"', "tools/showcase.py --write", 'lang="zh-CN"'):
            self.assertIn(marker, text)

    def test_pinned_readings_appear_in_page(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for token in ("24 项双入口同数", "僵尸当面数 = 0", "msh 退出码 127"):
            self.assertIn(token, text)

    def test_no_external_references(self):
        text = sc.OUT.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            self.assertTrue(url.startswith("http://www.w3.org/"),
                            f"页面出现外部地址：{url}")


if __name__ == "__main__":
    unittest.main()
