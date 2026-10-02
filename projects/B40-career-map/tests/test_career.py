"""tests/test_career.py —— B40 自测：证据核验器（正/负例）+ JD 映射器口径与缺口

纪律：核验器的每条规则都配一条"改坏必须红"；映射器的中英文匹配口径逐条钉住；
真实数据只钉两件会被「故意更新」打破的事：证据/技能条数与两个"诚实缺口"的集合。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]        # B40-career-map/
sys.path.insert(0, str(ROOT / "tools"))

import check_evidence                                     # noqa: E402
import map_jd                                             # noqa: E402

REPO_ROOT = ROOT.parents[1]                               # B40 → projects/ → 仓库根


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b40-{name}-"))
    if str(base.resolve()).lower().startswith(str(REPO_ROOT.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


def write_json(tmp: pathlib.Path, name: str, obj) -> pathlib.Path:
    path = tmp / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def good_evidence(eid: str = "e1") -> dict:
    return {"id": eid, "claim": "占位声明",
            "pointers": ["PLAN.md"], "anchor": "CRLF 行尾", "commit": "7b699b8"}


def good_skill(sid: str = "s1", evidence=None) -> dict:
    return {"id": sid, "name": sid, "keywords": ["演示"],
            "evidence": ["e1"] if evidence is None else evidence, "practice": "下一步"}


class TestEvidenceChecker(unittest.TestCase):
    def setUp(self):
        self.tmp = make_tmp("ev")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def problems(self, evidence_obj, skills_obj) -> list[str]:
        ev_path = write_json(self.tmp, "ev.json", evidence_obj)
        sk_path = write_json(self.tmp, "sk.json", skills_obj)
        problems = check_evidence.check_evidence_data(ev_path, REPO_ROOT)
        ids = {e["id"] for e in evidence_obj["evidence"]}
        return problems + check_evidence.check_skills_data(sk_path, ids)

    def test_real_index_passes(self):
        ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))
        problems = check_evidence.check_evidence_data(
            ROOT / "data" / "evidence.json", REPO_ROOT)
        self.assertEqual(problems, [], msg=problems)
        problems = check_evidence.check_skills_data(
            ROOT / "data" / "skills.json", {e["id"] for e in ev["evidence"]})
        self.assertEqual(problems, [], msg=problems)

    def test_fake_path_turns_red(self):
        bad = good_evidence()
        bad["pointers"] = ["projects/NOPE/README.md"]
        problems = self.problems({"evidence": [bad]}, {"skills": [good_skill()]})
        self.assertTrue(any("指针路径不存在" in p for p in problems), problems)

    def test_fake_commit_turns_red(self):
        bad = good_evidence()
        bad["commit"] = "deadbeef0"
        problems = self.problems({"evidence": [bad]}, {"skills": [good_skill()]})
        self.assertTrue(any("commit 在 git 里不存在" in p for p in problems), problems)

    def test_bad_anchor_turns_red(self):
        bad = good_evidence()
        bad["anchor"] = "这段字符串绝不可能出现在 PLAN.md 里xq9"
        problems = self.problems({"evidence": [bad]}, {"skills": [good_skill()]})
        self.assertTrue(any("anchor" in p for p in problems), problems)

    def test_empty_pointers_turns_red(self):
        bad = good_evidence()
        bad["pointers"] = []
        problems = self.problems({"evidence": [bad]}, {"skills": [good_skill()]})
        self.assertTrue(any("pointers 为空" in p for p in problems), problems)

    def test_duplicate_id_turns_red(self):
        problems = self.problems(
            {"evidence": [good_evidence("e1"), good_evidence("e1")]},
            {"skills": [good_skill()]})
        self.assertTrue(any("id 重复" in p for p in problems), problems)

    def test_dangling_skill_ref_turns_red(self):
        problems = self.problems({"evidence": [good_evidence()]},
                                 {"skills": [good_skill(evidence=["ghost-id"])]})
        self.assertTrue(any("不存在的证据 id" in p for p in problems), problems)

    def test_dead_evidence_turns_red(self):
        problems = self.problems(
            {"evidence": [good_evidence("e1"), good_evidence("e2")]},
            {"skills": [good_skill()]})
        self.assertTrue(any("没有被任何技能引用" in p and "e2" in p for p in problems), problems)

    def test_gap_skill_allowed(self):
        # 空 evidence 是"缺口"的定义，不是错误（与容器/K8s 同款）
        problems = self.problems({"evidence": [good_evidence()]},
                                 {"skills": [good_skill(), good_skill("s-gap", evidence=[])]})
        self.assertEqual(problems, [], msg=problems)

    def test_missing_practice_turns_red(self):
        bad = good_skill()
        bad["practice"] = ""
        problems = self.problems({"evidence": [good_evidence()]}, {"skills": [bad]})
        self.assertTrue(any("practice 为空" in p for p in problems), problems)


class TestMapJd(unittest.TestCase):
    def test_english_word_boundary(self):
        tokens = map_jd.tokenize("we go fast in gold mines")
        self.assertTrue(map_jd.hit("go", tokens, "we go fast in gold mines"))
        tokens2 = map_jd.tokenize("gold standard only")
        self.assertFalse(map_jd.hit("go", tokens2, "gold standard only"))

    def test_english_phrase_substring(self):
        text = "熟悉 Spring Boot 框架的候选人优先"
        self.assertTrue(map_jd.hit("spring boot", map_jd.tokenize(text), text.lower()))

    def test_chinese_substring(self):
        text = "有微服务架构经验的优先"
        self.assertTrue(map_jd.hit("微服务", map_jd.tokenize(text), text.lower()))
        self.assertFalse(map_jd.hit("容器", map_jd.tokenize(text), text.lower()))

    def test_example_jd_hits_expected_skills(self):
        skills = map_jd.load_skills(ROOT / "data" / "skills.json")
        text = (ROOT / "jd" / "EXAMPLE-合成示例（非真实岗位）.txt").read_text(encoding="utf-8")
        hit_ids = {row["skill"]["id"] for row in map_jd.match_skills(text, skills)}
        for eid in ("networking", "storage-db", "java-enterprise", "python-engineering",
                    "data-ml", "security", "distributed", "testing-quality",
                    "containers", "message-queue"):
            self.assertIn(eid, hit_ids, msg=eid)
        self.assertNotIn("cpp-memory", hit_ids)              # JD 没提 C++
        self.assertNotIn("compilers-asm", hit_ids)

    def test_matrix_deterministic_and_marked(self):
        skills = map_jd.load_skills(ROOT / "data" / "skills.json")
        evidence = map_jd.load_evidence(ROOT / "data" / "evidence.json")
        text = (ROOT / "jd" / "EXAMPLE-合成示例（非真实岗位）.txt").read_text(encoding="utf-8")
        one = map_jd.render_matrix("示例.txt", text, skills, evidence, example=True)
        two = map_jd.render_matrix("示例.txt", text, skills, evidence, example=True)
        self.assertEqual(one, two)
        self.assertIn("示例（非真实岗位）", one)
        self.assertIn("**缺口**", one)                        # 容器/消息队列两条真实缺口
        self.assertIn("不替代真实实习", one)

    def test_gap_row_contains_practice(self):
        skills = [{"id": "s-gap", "name": "缺口语料", "keywords": ["docker"],
                   "evidence": [], "practice": "先写一个最小容器脚本"}]
        out = map_jd.render_matrix("x.txt", "要求熟悉 docker 与 kubernetes",
                                   skills, {}, example=False)
        self.assertIn("**缺口**", out)
        self.assertIn("先写一个最小容器脚本", out)
        self.assertIn("docker", out)

    def test_collect_jds_and_example_flag(self):
        jds = map_jd.collect_jds(ROOT / "jd")
        self.assertEqual(len(jds), 1)
        path, example = jds[0]
        self.assertTrue(example)
        self.assertTrue(path.name.startswith("EXAMPLE"))
        tmp = make_tmp("jd")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(map_jd.collect_jds(tmp), [])         # 空目录：没有 JD 可映射


class TestHonestDesign(unittest.TestCase):
    def test_checker_cli_exits_zero_on_real_data(self):
        self.assertEqual(check_evidence.main(["check", str(ROOT)]), 0)

    def test_counts_and_gap_set_are_pinned(self):
        """条数与"诚实缺口"集合是刻意钉住的：改动数据必须来这里改数字（防止悄悄变化）。"""
        ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))["evidence"]
        skills = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))["skills"]
        self.assertEqual(len(ev), 31)
        self.assertEqual(len(skills), 15)
        gaps = {s["id"] for s in skills if not s["evidence"]}
        self.assertEqual(gaps, {"containers", "message-queue"})

    def test_every_evidence_is_referenced(self):
        ev = json.loads((ROOT / "data" / "evidence.json").read_text(encoding="utf-8"))["evidence"]
        skills = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))["skills"]
        used = {ref for s in skills for ref in s["evidence"]}
        self.assertEqual({e["id"] for e in ev} - used, set())


if __name__ == "__main__":
    unittest.main()
