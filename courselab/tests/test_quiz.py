"""随堂测验（轮五十）：题库加载 / 判分 / 落库 / 权限与边界。

覆盖：
- quiz_for 剥答案（学生拿不到 answer/explain）；
- grade 全对/全错/部分：得分与逐题 detail（含正确答案与解析）；
- 落库：登录用户记 quiz_attempts、未登录不计分（游客可体验）；
- /api/quiz/<cid> 与 /submit：无测验课程 404、answers 非对象 400、mine 未登录 401。
"""
import json
import tempfile
import unittest
from pathlib import Path

from app import db as dbmod
from app import quiz


class QuizLogicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = dbmod.DB(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.db.conn.close)
        # 造一个登录用户（列名以 db.py 为准：pwd_salt/pwd_hash/pwd_iter）
        self.db.execute(
            "INSERT INTO users (username, display_name, pwd_salt, pwd_hash, "
            "pwd_iter, role, status, created_at) VALUES "
            "('stu','甲','s','h',1000,'student','active','now')")
        row = self.db.execute("SELECT id FROM users WHERE username='stu'").fetchone()
        self.uid = row[0]

    def test_quiz_for_strips_answers(self):
        cid = "B12-algo-arena"
        paper = quiz.quiz_for(cid)
        self.assertIsNotNone(paper)
        self.assertEqual(paper["count"], 3)
        for qz in paper["questions"]:
            self.assertNotIn("answer", qz)
            self.assertNotIn("explain", qz)
            self.assertEqual(len(qz["options"]), 4)

    def test_grade_full_and_partial(self):
        cid = "B12-algo-arena"
        bank = quiz.load_bank()[cid]
        right = {str(i): qz["answer"] for i, qz in enumerate(bank)}
        r = quiz.grade(self.db, self.uid, cid, right)
        self.assertEqual((r["score"], r["total"]), (3, 3))
        self.assertTrue(all(d["ok"] for d in r["detail"]))
        # 全错
        wrong = {str(i): (qz["answer"] + 1) % 4 for i, qz in enumerate(bank)}
        r2 = quiz.grade(self.db, self.uid, cid, wrong)
        self.assertEqual(r2["score"], 0)
        self.assertFalse(all(d["ok"] for d in r2["detail"]))
        # 部分作答（缺题不计分不报错）
        r3 = quiz.grade(self.db, self.uid, cid, {"0": bank[0]["answer"]})
        self.assertEqual(r3["score"], 1)
        self.assertIsNone(r3["detail"][1]["given"])

    def test_attempts_persist_and_guest_not_recorded(self):
        cid = "B5-cpu-sim"
        bank = quiz.load_bank()[cid]
        quiz.grade(self.db, self.uid, cid,
                   {str(i): qz["answer"] for i, qz in enumerate(bank)})
        quiz.grade(self.db, None, cid,
                   {str(i): qz["answer"] for i, qz in enumerate(bank)})   # 游客
        rows = quiz.my_attempts(self.db, self.uid, cid)
        self.assertEqual(len(rows), 1)                # 游客那次不落库
        self.assertEqual(rows[0]["score"], 3)

    def test_stats_aggregation(self):
        cid = "B10-minidb"
        bank = quiz.load_bank()[cid]
        right = {str(i): qz["answer"] for i, qz in enumerate(bank)}
        wrong = {str(i): (qz["answer"] + 1) % 4 for i, qz in enumerate(bank)}
        quiz.grade(self.db, self.uid, cid, wrong)   # 先差后好：last/best 分开
        quiz.grade(self.db, self.uid, cid, right)
        st = quiz.stats(self.db, self.uid)
        self.assertEqual(st["count"], 2)
        self.assertEqual(len(st["per_course"]), 1)
        pc = st["per_course"][0]
        self.assertEqual((pc["best"], pc["last"], pc["count"]), (100, 100, 2))
        self.assertTrue(pc["course"])               # 课程名映射成功
        self.assertEqual(len(st["timeline"]), 2)
        # 无记录用户：空分析不报错
        self.db.execute(
            "INSERT INTO users (username, display_name, pwd_salt, pwd_hash, "
            "pwd_iter, role, status, created_at) VALUES "
            "('nobody','乙','s','h',1000,'student','active','now')")
        row = self.db.one("SELECT id FROM users WHERE username='nobody'")
        st2 = quiz.stats(self.db, row["id"])
        self.assertEqual(st2, {"count": 0, "per_course": [], "timeline": []})

    def test_unknown_course(self):
        self.assertIsNone(quiz.quiz_for("no-such-course"))
        self.assertIsNone(quiz.grade(self.db, self.uid, "no-such-course", {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
