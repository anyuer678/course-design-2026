"""tests/test_radar.py —— B39 自测：记录检查器（正/负例）+ CRDT 最小复现的性质与收敛

纪律：检查器的每条规则都要有一条"改坏必须报红"的对照；CRDT 的三条性质
（交换/结合/幂等）与置换收敛都是**逐场景断言**，赢家用独立求 max 当参照。
"""
from __future__ import annotations

import pathlib
import random
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "repro"))

import check_record                                                       # noqa: E402
from crdt_lww import LWWRegister, Timestamp, VectorClock, apply_ops       # noqa: E402

REPO_ROOT = ROOT.parents[1]                                               # B39 → projects/ → 仓库根
EXAMPLE = ROOT / "docs" / "records" / "example-crdt.md"


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b39-{name}-"))
    if str(base.resolve()).lower().startswith(str(REPO_ROOT.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


class MutationMixin(unittest.TestCase):
    """把示例记录改坏一处 → 写进临时目录 → 检查器必须报出预期问题。"""

    def mutated(self, old: str, new: str) -> pathlib.Path:
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn(old, text, msg=f"示例记录里应包含：{old[:40]!r}")
        tmp = make_tmp("mut")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "mutated.md"
        path.write_text(text.replace(old, new), encoding="utf-8")
        return path

    def problems_for(self, old: str, new: str) -> list[str]:
        return check_record.check_record(self.mutated(old, new), REPO_ROOT)


class TestRecordChecker(MutationMixin):
    def test_example_record_passes(self):
        self.assertEqual(check_record.check_record(EXAMPLE, REPO_ROOT), [])

    def test_missing_section_turns_red(self):
        problems = self.problems_for("## 局限与适用边界", "## 其他")
        self.assertTrue(any("缺少必需小节" in p and "局限与适用边界" in p for p in problems), problems)

    def test_bad_evidence_path_turns_red(self):
        problems = self.problems_for("repro/crdt_lww.py`", "repro/NOPE.py`")
        self.assertTrue(any("证据路径在仓库里不存在" in p for p in problems), problems)

    def test_fake_commit_turns_red(self):
        problems = self.problems_for("@f0bb729", "@deadbeef0")
        self.assertTrue(any("证据提交在 git 里不存在" in p for p in problems), problems)

    def test_sample_without_honesty_marker_turns_red(self):
        problems = self.problems_for("示例（非真实来源）", "示例")
        self.assertTrue(any("非真实来源" in p for p in problems), problems)

    def test_bad_date_turns_red(self):
        problems = self.problems_for("日期：2026-10-02", "日期：2026/10/02")
        self.assertTrue(any("YYYY-MM-DD" in p for p in problems), problems)

    def test_evidence_without_pointers_turns_red(self):
        problems = self.problems_for("`", "")       # 去掉全部反引号：指针随之消失
        self.assertTrue(any("没有任何可核验指针" in p for p in problems), problems)

    def test_missing_meta_field_turns_red(self):
        problems = self.problems_for("- 记录人：课程设计仓库（B39 示例）", "- 备注：无")
        self.assertTrue(any("记录人" in p for p in problems), problems)


class TestCrdtLww(unittest.TestCase):
    def test_set_and_merge_basic(self):
        reg = LWWRegister("a")
        self.assertIsNone(reg.value)
        reg.set("x")
        self.assertEqual((reg.value, reg.ts), ("x", Timestamp(1, "a")))
        later = LWWRegister("a")
        later.set("y")
        later.set("z")                                        # 计数器 2
        reg.merge_in(later)
        self.assertEqual(reg.value, "z")

    def test_tie_break_by_replica(self):
        """记录里点名的手算场景：并列计数器按副本号取大。"""
        reg_a = LWWRegister("a")
        reg_a.set("x")                                        # (1, "a")
        reg_b = LWWRegister("b")
        reg_b.set("y")                                        # (1, "b")
        self.assertEqual(LWWRegister.merged([reg_a, reg_b]).value, "y")
        self.assertEqual(LWWRegister.merged([reg_b, reg_a]).value, "y")   # 顺序无关

    def test_commutativity(self):
        rng = random.Random(1)
        for _ in range(50):
            regs = []
            for replica in ("a", "b", "c"):
                reg = LWWRegister(replica)
                for _ in range(rng.randint(0, 3)):
                    reg.set(rng.choice(["p", "q", "r"]))
                regs.append(reg)
            ab = LWWRegister.merged(list(regs))
            ba = LWWRegister.merged(list(reversed(regs)))
            self.assertEqual((ab.value, ab.ts), (ba.value, ba.ts))

    def test_associativity(self):
        rng = random.Random(2)
        for _ in range(50):
            made = []
            for replica in ("a", "b", "c", "d"):
                reg = LWWRegister(replica)
                for _ in range(rng.randint(0, 4)):
                    reg.set(rng.randint(0, 100))
                made.append(reg)
            left = LWWRegister.merged([LWWRegister.merged(made[:2]), made[2], made[3]])
            right = LWWRegister.merged([made[0], LWWRegister.merged(made[1:3]), made[3]])
            self.assertEqual((left.value, left.ts), (right.value, right.ts))

    def test_idempotence(self):
        reg = LWWRegister("a")
        reg.set("x")
        other = LWWRegister("b")
        other.set("y")
        merged = LWWRegister.merged([reg, other])
        merged.merge_in(other)                                # 重传/回声：不变
        merged.merge_in(other)
        self.assertEqual((merged.value, merged.ts), ("y", Timestamp(1, "b")))

    def test_convergence_permutations(self):
        """随机置换 100 组：任何合并顺序都应得到同一 (值, 时间戳)。"""
        rng = random.Random(3)
        regs = []
        for replica in ("a", "b", "c", "d", "e"):
            reg = LWWRegister(replica)
            for _ in range(rng.randint(1, 4)):
                reg.set(f"{replica}-{rng.randint(0, 99)}")
            regs.append(reg)
        expected = max(regs, key=lambda r: (r.ts.counter, r.ts.replica))
        for _ in range(100):
            order = list(range(len(regs)))
            rng.shuffle(order)
            out = LWWRegister.merged([regs[i] for i in order])
            self.assertEqual((out.value, out.ts), (expected.value, expected.ts))

    def test_partition_heal_scenario(self):
        """分区各写、愈合合并：赢家与独立手算的 max 一致。"""
        reg_a, reg_c = LWWRegister("a"), LWWRegister("c")
        reg_a.set("x")                                        # (1, "a")
        reg_c.set("z")                                        # (1, "c")
        reg_b = LWWRegister("b")
        for _ in range(3):                                    # b 写得晚：计数器 3
            reg_b.set("y")
        out = LWWRegister.merged([reg_a, reg_c, reg_b])
        best = max([reg_a, reg_c, reg_b], key=lambda r: (r.ts.counter, r.ts.replica))
        self.assertEqual((out.value, out.ts), (best.value, best.ts))
        self.assertEqual(out.value, "y")

    def test_same_ts_conflict_raises(self):
        """协议违规（同一副本同一计数两个值）必须当场报错而不是静默取一个。"""
        one = LWWRegister("a")
        one.set("x")
        two = LWWRegister("a")
        two.set("y")                                          # 同为 (1, "a")，值却不同
        with self.assertRaises(ValueError):
            LWWRegister.merged([one, two])

    def test_apply_ops_monotonic(self):
        reg = LWWRegister("a")
        apply_ops(reg, ["p", "q", "r"])
        self.assertEqual(reg.ts, Timestamp(3, "a"))
        self.assertEqual(reg.clock.get("a"), 3)

    def test_vector_clock_merge_is_join(self):
        left, right = VectorClock(), VectorClock()
        left.tick("a")
        left.tick("a")
        right.tick("a")
        right.tick("b")
        left.merge(right)
        self.assertEqual(left.progress, {"a": 2, "b": 1})
        left.merge(right)                                     # 幂等
        self.assertEqual(left.progress, {"a": 2, "b": 1})


if __name__ == "__main__":
    unittest.main()
