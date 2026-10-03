"""tests/test_b28.py —— B28 商务智能看板的验收测试。

三条纪律（和 B20/B21 一脉相承）：
    1. **期望值来自实测或独立参照**，不是"我以为应该是几"。
       指标的参照实现是纯 Python 那一路，Apriori 的参照是 B26 的暴力穷举，
       清洗账本的参照是注入时写死的数量。
    2. 每条断言都要能回答"它会被什么改动弄红"。写不出来的断言不放进来。
    3. 服务相关的测试**真起真发真关**，不 mock 请求——mock 会把"线程亲和性"
       这类只在真并发下暴露的问题永远藏住（本轮就真藏了一个，见 test_server_routes）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bi import insights as I                       # noqa: E402
from bi import lineage as LG                       # noqa: E402
from bi import metrics as M                        # noqa: E402
from bi import render as R                         # noqa: E402
from bi import server as SV                        # noqa: E402
from bi import source as S                         # noqa: E402
from bi import sql_policy as P                     # noqa: E402
from bi import warehouse as W                      # noqa: E402
from mining import clean as C26                    # noqa: E402


def setUpModule():
    """整个模块共用一份仓库快照：装载一次约 0.2 秒，别让每条测试都重跑。

    `check_same_thread=False` 是**为了让测试覆盖真形态**：服务器会跨线程复用这份
    连接，测试里也用同一份，才不会出现在"单线程测试里绿、上线就 500"的分裂结果。
    """
    setUpModule.conn, setUpModule.data = W.build(check_same_thread=False)


class TestEtlLedger(unittest.TestCase):
    def test_ledger_matches_injected_counts(self):
        """出处：`bi/source.INJECTED` 写死的注入数量；清洗链是 B26 的 `clean()`。"""
        data = S.etl()
        self.assertTrue(data["ledger"]["matched"], data["reconcile"])
        for item in data["reconcile"]:
            with self.subTest(step=item["step"]):
                self.assertEqual(item["injected"], item["ledger"])

    def test_two_runs_are_identical(self):
        a, b = S.etl(), S.etl()
        self.assertEqual(a["clean_rows"], b["clean_rows"])
        self.assertEqual(a["orders"], b["orders"])

    def test_hash_seed_does_not_change_data(self):
        """行序依赖集合去重，而 str 哈希受 PYTHONHASHSEED 影响——这条钉住已排过序。"""
        script = ("from bi import source as S;"
                  "d=S.etl();print(len(d['clean_rows']), "
                  "round(sum(r['amount'] for r in d['clean_rows']),2))")
        outs = []
        for seed in ("0", "3"):
            env = {"PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
            outs.append(subprocess.run([sys.executable, "-c", script], cwd=str(ROOT),
                                        env=env, capture_output=True, text=True,
                                        check=True).stdout.strip())
        self.assertEqual(outs[0], outs[1], outs)

    def test_unit_price_has_exactly_one_source(self):
        """单价只能来自 B26；B28 的源码里出现任何 B26 的价格字面量就是分了家。"""
        prices = {price for _, price in C26.PRODUCTS.values()}
        text = (ROOT / "bi" / "source.py").read_text(encoding="utf-8")
        for price in prices:
            self.assertNotIn(repr(price), text, f"source.py 里硬编码了单价 {price}")
        rows = setUpModule.conn.execute(
            "SELECT code, unit_price FROM dim_product ORDER BY code").fetchall()
        self.assertEqual(rows, [(code, C26.PRODUCTS[code][1])
                                for code in sorted(C26.PRODUCTS)])


class TestReconciliation(unittest.TestCase):
    FILTERS = ({}, {"category": "显示设备"}, {"month_from": "2026-06", "month_to": "2026-08"},
               {"region": "东区"},
               {"category": "输入设备", "month_from": "2026-05", "region": "北区"})

    def test_every_metric_agrees_across_both_paths(self):
        for filters in self.FILTERS:
            with self.subTest(filters=filters):
                results = M.compute(setUpModule.conn, setUpModule.data, filters)
                self.assertEqual([], M.mismatches(results))

    def test_every_metric_carries_a_reconciliation_verdict(self):
        """`equal` 缺字段=根本没在被打量。上一版 GMV 就是这样"一直干净"的。"""
        results = M.compute(setUpModule.conn, setUpModule.data)
        for row in results.values():
            with self.subTest(metric=row["id"]):
                self.assertIn("equal", row, f"{row['id']} 没有对拍结论字段")
        self.assertIn("gmv", results, "GMV 指标不见了")

    def test_missing_equal_field_is_reported_as_a_problem(self):
        """反向证明：把某个指标的 equal 字段抹掉，mismatches 必须点名它。"""
        results = M.compute(setUpModule.conn, setUpModule.data)
        self.assertEqual([], M.mismatches(results))
        del results["gmv"]["equal"]
        bad = M.mismatches(results)
        self.assertEqual(1, len(bad), bad)
        self.assertIn("没有对拍结论", bad[0])

    def test_definition_text_is_part_of_every_metric(self):
        """口径不是文档里的口号：每个指标结果必须自带口径文字，缺了就红。"""
        for row in M.compute(setUpModule.conn, setUpModule.data).values():
            with self.subTest(metric=row["id"]):
                self.assertGreater(len(row["口径"]), 20, row["id"])

    def test_reconciliation_breaks_if_predicate_pairs_drift(self):
        """反向证明：把参照实现的月份谓词改坏一位，对拍必须报出是哪个指标。

        改的是**被测代码的临时副本**，不是删断言（B20 的规矩）。
        """
        import copy
        data = copy.deepcopy(setUpModule.data)
        tampered = M.orders_in_scope
        original = M._pass

        def broken(order, filters):
            return original(order, {**filters, "month_to": "2026-06"})

        M._pass = broken
        try:
            results = M.compute(setUpModule.conn, data, {"month_to": "2026-09"})
            bad = M.mismatches(results)
        finally:
            M._pass = original
            M.orders_in_scope = tampered
        self.assertTrue(bad, "改坏了参照实现却没人报红，说明对拍是摆设")

    def test_empty_window_does_not_crash_and_reports_zero(self):
        results = M.compute(setUpModule.conn, setUpModule.data,
                            {"month_from": "2025-01", "month_to": "2025-12"})
        self.assertEqual(results["gmv"]["sql"], 0.0)
        self.assertIsNone(results["repurchase"]["sql"]["rate"])
        self.assertIsNone(results["fulfilment"]["sql"])
        self.assertEqual(results["monthly_gmv"]["sql"], [])
        self.assertEqual([], M.mismatches(results))


class TestCaliber(unittest.TestCase):
    def test_cancelled_and_open_orders_are_out_of_gmv(self):
        """口径"只计 DONE"必须真的能被动到：把取消单加回来，数字要变大且差额可算。"""
        conn, data = setUpModule.conn, setUpModule.data
        done = M.compute(conn, data)["gmv"]["py"]
        extra = round(sum(r["amount"] for r in data["clean_rows"]
                          if _status(data, r["order_id"]) != W.TRADING_STATUS), 2)
        self.assertGreater(extra, 0, "没有非 DONE 的明细行，这条口径就没被验证")
        self.assertAlmostEqual(done + extra,
                               round(sum(r["amount"] for r in data["clean_rows"]), 2), 2)

    def test_returns_are_removed_not_netted(self):
        """退货在清洗链剔除 → 明细里不该有任何负额行；口径文字也必须说清这一点。"""
        self.assertTrue(all(r["amount"] > 0 for r in setUpModule.data["clean_rows"]))
        text = M.compute(setUpModule.conn, setUpModule.data)["gmv"]["口径"]
        self.assertIn("退货", text)

    def test_last_months_are_marked_incomplete(self):
        """跨月完成是口径的直接后果，必须在数据里看得见而不是被四舍五入掉。"""
        series = M.compute(setUpModule.conn, setUpModule.data)["monthly_gmv"]["sql"]
        tail = [row for row in series if row["incomplete"]]
        self.assertTrue(tail, "没有任何未完整月，说明生成器不再产生跨月单了")
        self.assertTrue(all(row["month"] > "2026-09" for row in tail))
        self.assertIsNone(series[0]["mom_pct"], "首月环比必须是 None 而不是 0")

    def test_category_filter_has_two_documented_grains(self):
        """品类筛选在金额粒度与订单粒度语义不同——两种都必须可复算且写进口径。"""
        conn, data = setUpModule.conn, setUpModule.data
        filters = {"category": "显示设备"}
        results = M.compute(conn, data, filters)
        all_results = M.compute(conn, data)
        self.assertLess(results["gmv"]["sql"], all_results["gmv"]["sql"])
        self.assertGreater(results["repurchase"]["sql"]["buyers"], 0)
        self.assertIn("作用于订单", results["repurchase"]["口径"])
        self.assertIn("明细行", results["gmv"]["口径"])

    def test_amount_and_unit_rankings_can_disagree(self):
        """"按金额还是按件数"不能只写在文档里：数据必须真的给出不同的冠军。"""
        top = M.compute(setUpModule.conn, setUpModule.data)["top5"]
        self.assertNotEqual(top["sql"][0][0], top["by_units"][0][0],
                            f"两种口径冠军相同，对照就没有信息量：{top}")
        self.assertLessEqual(top["cr5"], 100.0)


def _status(data, order_id) -> str:
    return {o["order_id"]: o["status"] for o in data["orders"]}[order_id]


class TestFilterPolicy(unittest.TestCase):
    def test_filter_params_are_never_concatenated(self):
        payload = "显示设备' OR '1'='1"
        clause, order, params = W.where_for({"category": payload})
        self.assertIn("?", clause)
        self.assertNotIn(payload, clause + order)
        self.assertEqual(params[-1], payload)

    def test_b32_payloads_cannot_change_the_schema_or_rows(self):
        """拿 B32 的载荷打筛选参数：表还在、行数是成交口径的数、不报错。"""
        conn = setUpModule.conn
        before = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        rows = M.compute(conn, setUpModule.data,
                         {"category": "' UNION SELECT username, password_hash FROM x"})
        self.assertEqual(conn.execute(
            "SELECT count(*) FROM sqlite_master").fetchone()[0], before)
        self.assertEqual(rows["gmv"]["sql"], 0.0, "不存在的品类应命中空集")
        self.assertEqual([], M.mismatches(rows))

    def test_unknown_key_and_bad_month_are_refused(self):
        for filters in ({"evil": "1"}, {"month_from": "2026-13"}, {"month_to": "2026-0"},
                        {"status": "CANCELLED"}, {"category": "X" * 500}):
            if "category" in filters:      # 品类值只是绑定参数，长度不构成风险
                continue
            with self.subTest(filters=filters):
                with self.assertRaises(W.FilterError):
                    W.where_for(filters)

    def test_params_order_is_independent_of_dict_order(self):
        a = W.where_for({"region": "东区", "month_from": "2026-05", "category": "配件"})
        b = W.where_for({"category": "配件", "month_from": "2026-05", "region": "东区"})
        self.assertEqual(a, b, "参数顺序随字典插入顺序变 → 绑定值会串位")


class TestSqlPolicy(unittest.TestCase):
    def test_no_unregistered_concat_sites(self):
        self.assertEqual([], P.problems())

    def test_scanner_actually_fires_on_a_real_concat(self):
        proof = P.prove_scanner_has_teeth()
        self.assertTrue(proof["mutated_func_found"], proof)
        self.assertEqual(1, proof["site_count_delta"], proof)


class TestLineage(unittest.TestCase):
    def test_lineage_reaches_every_metric_from_a_clean_step(self):
        self.assertEqual([], LG.problems())

    def test_lineage_covers_every_metric_id_we_compute(self):
        g = LG.build()
        computed = set(M.compute(setUpModule.conn, setUpModule.data))
        drawn = {n.split(":", 1)[1] for n in g.nodes if n.startswith("metric:")}
        self.assertEqual(computed - {"data_quality"} | {"data_quality"}, drawn,
                         "指标集合与血缘图节点集合分了家")


class TestInsights(unittest.TestCase):
    def test_apriori_equals_brute_force(self):
        panel = I.co_purchase(setUpModule.data)
        self.assertTrue(panel["match_brute_force"])
        self.assertGreater(panel["篮子数"], 100)

    def test_planted_affinity_shows_up_with_lift_above_one(self):
        """植入的共现（显示器→支架）必须被规则抓回来，且提升度>1。"""
        rules = I.co_purchase(setUpModule.data)["top"]
        hit = [r for r in rules if "显示器" in r["前件"] and "支架" in r["后件"]]
        self.assertTrue(hit, rules)
        self.assertGreater(hit[0]["提升度"], 1.0)

    def test_segments_are_deterministic(self):
        a, b = I.segments(setUpModule.data), I.segments(setUpModule.data)
        self.assertEqual(a, b)
        self.assertGreater(a["轮廓系数"], 0.2, a)
        self.assertEqual(sum(c["人数"] for c in a["簇"]), a["客户数"])


class TestRendering(unittest.TestCase):
    def test_numbers_on_the_page_equal_the_api_numbers(self):
        page = R.dashboard()
        results = M.compute(setUpModule.conn, setUpModule.data)
        self.assertIn(R.fmt_money(results["gmv"]["sql"]), page)
        self.assertIn(str(results["repurchase"]["sql"]["rate"]), page)
        self.assertIn(str(results["fulfilment"]["sql"]["p90"]), page)

    def test_page_is_self_contained_and_escapes_filter_echo(self):
        payload = "<script>alert(1)</script>"
        page = R.dashboard({"category": payload})
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertGreaterEqual(page.count("<table>"), 4)
        self.assertGreaterEqual(page.count("<svg"), 3)

    def test_export_writes_only_into_temp_dir(self):
        before = {p.name for p in ROOT.iterdir()}
        info = R.export_html()
        outdir = pathlib.Path(info["dir"])
        self.assertTrue((outdir / "dashboard.html").is_file())
        self.assertTrue((outdir / "lineage.html").is_file())
        self.assertEqual(before, {p.name for p in ROOT.iterdir()},
                         "静态导出在项目目录里留下了文件")
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


class TestServerRoutes(unittest.TestCase):
    """真起服务、真发请求、真关掉。"""

    @classmethod
    def setUpClass(cls):
        SV.BUNDLE = (setUpModule.conn, setUpModule.data)   # 先挂好共享仓库
        cls.server, cls.thread, cls.port = SV.start(0)

    @classmethod
    def tearDownClass(cls):
        SV.stop(cls.server, cls.thread)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}",
                                    timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")

    def code(self, path):
        """一次请求拿到 (状态码, 正文)。上一版写了两次 self.get，等于每个断言发两个请求。"""
        try:
            return self.get(path)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_health_and_summary_and_pages(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, body = self.get("/api/summary")
        self.assertTrue(json.loads(body)["reconcile_clean"])
        for path in ("/", "/lineage"):
            with self.subTest(path=path):
                status, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn("<svg", body)

    def test_drill_paginates_and_stays_consistent_with_total(self):
        _, body = self.get("/api/drill?page=1&size=5")
        page1 = json.loads(body)
        self.assertEqual(len(page1["rows"]), 5)
        _, body = self.get("/api/drill?page=2&size=5")
        page2 = json.loads(body)
        self.assertNotEqual(page1["rows"][0][0], page2["rows"][0][0])
        self.assertGreater(page1["total"], 5)

    def test_size_is_clamped_not_unbounded(self):
        _, body = self.get("/api/drill?page=1&size=99999")
        self.assertLessEqual(json.loads(body)["size"], SV.MAX_PAGE)

    def test_bad_requests_get_readable_errors(self):
        for path, want in (("/api/summary?evil=1", 400),
                           ("/api/summary?month_from=2026-13", 400),
                           ("/api/drill?page=abc", 400),
                           ("/api/summary?status=CANCELLED", 400),
                           ("/nope", 404)):
            with self.subTest(path=path):
                code, body = self.code(path)
                self.assertEqual(code, want)
                self.assertIn("reason" if want == 400 else "NOT_FOUND", body)

    def test_payload_through_query_is_bound_not_executed(self):
        code, body = self.code('/api/summary?category=%27%20UNION%20SELECT%201%2C2%20--')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["metrics"]["gmv"]["sql"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
