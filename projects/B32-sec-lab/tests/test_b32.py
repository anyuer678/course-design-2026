"""tests/test_b32.py —— B32 信息安全导论实验的验收测试。

四类靶件（SQL 注入 / HTML 注入 / 口令存储 / 路径穿越）+ 一个静态扫描器，
每组都遵守本仓库三条纪律：

1. **期望值来自实测或参照实现**，不是我以为。文案里出现的数字都是先跑出来的，
   参照要么是标准库（`html.escape`、`urllib.parse`、`pathlib`），
   要么是另一条独立实现（纯 Python 谓词、暴力解码）。
2. **每条断言都能回答"被什么改动弄红"**。写不出来的就不放进来；
   三处专门用临时副本改坏被测代码，证明判定不是装饰（不许改测试断言）。
3. **红要红在该红的原因上**：拒绝类断言都匹配 reason 里的关键词，
   不是只看"抛了异常"。

运行：`python -m unittest discover -s tests` 或 `python tests\\test_b32.py`（双入口同数）。
"""
from __future__ import annotations

import html
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECTS_DIR = ROOT.parent                                  # = projects/
WORKSPACE_ROOT = PROJECTS_DIR.parent                        # = 仓库根（课设/）
sys.path.insert(0, str(ROOT))

from sec32 import audit as A                          # noqa: E402
from sec32 import creds as C                          # noqa: E402
from sec32 import sqli as Q                           # noqa: E402
from sec32 import traversal as T                      # noqa: E402
from sec32 import xss as X                            # noqa: E402


def inside_repo(path) -> bool:
    """这个路径落在仓库里面吗？"""
    try:
        pathlib.Path(path).resolve().relative_to(WORKSPACE_ROOT.resolve())
    except ValueError:
        return False
    return True


_PROBE_ROOTS: set[pathlib.Path] = set()


def make_probe_root(name: str) -> pathlib.Path:
    """反向证明用的临时副本：**只能建在仓库之外**，并且只有它自己能被删。

    这条函数是 2026-10-02 两次误删事故的直接后果。当时写的是
    `work = parents[2] / "_probe_b32_xss"`（= `projects/_probe_b32_xss`），
    而清理写成 `shutil.rmtree(work.parent)` —— `work.parent` 正是 `projects/`，
    于是整个 projects 目录被删了两遍（第二遍是因为我把带着这个 bug 的测试
    恢复出来之后没审计就直接跑了）。
    现在的规矩：**只删本函数亲手建、且登记在案的那一个目录**；
    "在仓库外"与"是我建的"两件事都由代码断言，不靠人记住。
    """
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b32-probe-{name}-"))
    if inside_repo(base):
        raise RuntimeError(f"临时副本必须建在仓库之外，实际得到 {base}")
    _PROBE_ROOTS.add(base.resolve())
    return base


def destroy_probe_root(base) -> None:
    resolved = pathlib.Path(base).resolve()
    if inside_repo(resolved):
        raise RuntimeError(f"拒绝删除仓库内的路径 {resolved}")
    if resolved not in _PROBE_ROOTS:
        raise RuntimeError(f"拒绝删除不是 make_probe_root 建立的目录 {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)
    _PROBE_ROOTS.discard(resolved)


def load_mutated(module_name: str, file_path):
    """从临时副本加载改坏的模块（标准写法：spec → module_from_spec → exec_module）。"""
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSqlInjection(unittest.TestCase):
    def setUp(self):
        self.conn = Q.fresh_db()

    def test_legitimate_login_works_on_both_paths(self):
        """安全修复的验收包含功能不回归：正常口令在两侧都必须登进去。"""
        vuln = Q.login_concat(self.conn, "admin", "sha256$TOP_SECRET")
        safe = Q.login_bound(self.conn, "admin", "sha256$TOP_SECRET")
        self.assertTrue(vuln["logged_in"] and safe["logged_in"])
        self.assertEqual(vuln["role"], "admin")
        self.assertEqual(safe["role"], "admin")

    def test_comment_payload_bypasses_concat_but_not_binding(self):
        payload, pwd = Q.PAYLOAD_COMMENT, "随便填"
        vuln, safe = Q.login_concat(self.conn, payload, pwd), \
            Q.login_bound(self.conn, payload, pwd)
        self.assertTrue(vuln["logged_in"], vuln["sql"])
        self.assertEqual(vuln["role"], "admin", "注释截断了密码检查 ⇒ 不需要口令")
        self.assertFalse(safe["logged_in"])
        self.assertEqual(safe["rows"], [])

    def test_always_true_payload_needs_a_comment_to_close(self):
        """恒真条件本身要配合注释收尾才成立；少了那个 `--` 就只剩字符串比较。"""
        with_comment = Q.login_concat(self.conn, Q.PAYLOAD_OR_TRUE, "x")
        self.assertTrue(with_comment["logged_in"])
        self.assertEqual(len(with_comment["rows"]), 2, with_comment["rows"])

    def test_famous_payload_fails_here_because_of_precedence(self):
        """课本那条 `' OR '1'='1` 在本谓词里**不成立**（AND 优先于 OR）。

        这条测试反过来钉住一件事：不许把"注入=万能钥匙"当结论写进文档。
        """
        for fn in (Q.login_concat, Q.login_bound):
            out = fn(self.conn, Q.PAYLOAD_PRECEDENCE, "x")
            with self.subTest(fn=fn.__name__):
                self.assertFalse(out["logged_in"], out["sql"])

    def test_union_extracts_credentials_only_from_concat(self):
        vuln = Q.search_concat(self.conn, Q.PAYLOAD_UNION)
        safe = Q.search_bound(self.conn, Q.PAYLOAD_UNION)
        self.assertEqual(len(vuln["rows"]), 2, vuln["sql"])
        self.assertIn("sha256$TOP_SECRET", str(vuln["rows"]))
        self.assertEqual(safe["rows"], [])

    def test_union_requires_matching_column_count(self):
        """列数不对就报 OperationalError ⇒ 载荷能否成立取决于语法，不是"危险字符"。"""
        out = Q.search_concat(self.conn, Q.PAYLOAD_UNION_BAD_ARITY)
        self.assertEqual(out["rows"], [])
        self.assertIn("UNION", out["error"])
        self.assertIn("number", out["error"])

    def test_quote_doubling_blocks_payloads_but_cannot_save_identifiers(self):
        """翻倍转义挡住了这三条载荷（实测），但标识符位置它救不了 —— 见 ORDER BY 那条。"""
        for payload in (Q.PAYLOAD_COMMENT, Q.PAYLOAD_OR_TRUE, Q.PAYLOAD_PRECEDENCE):
            out = Q.login_quote_doubled(self.conn, payload, "x")
            with self.subTest(payload=payload):
                self.assertFalse(out["logged_in"], out["sql"])

    def test_binding_an_identifier_is_a_silent_no_op(self):
        """ORDER BY 用占位符绑列名：不报错，但排序变成按常量排 ⇒ 与不排序同序。

        比报错更危险的是这种"静默无效"，所以断言两边都必须看到：
        绑参结果 == 无排序结果 != 真按 phone 排的结果。
        """
        real = [r[0] for r in Q.order_concat(self.conn, "phone")["rows"]]
        bound = [r[0] for r in Q.order_bound(self.conn, "phone")["rows"]]
        natural = [r[0] for r in Q.order_concat(self.conn, "id")["rows"]]
        self.assertNotEqual(real, natural, "种子数据里 phone 顺序应与 id 顺序不同")
        self.assertEqual(bound, natural)

    def test_boolean_channel_in_order_by_is_measurable(self):
        """推断通道：CASE WHEN 真/假给出两种不同顺序，这就是"能传出 1 比特"的证据。"""
        true = [r[0] for r in Q.order_concat(self.conn, Q.PAYLOAD_BOOL_TRUE)["rows"]]
        false = [r[0] for r in Q.order_concat(self.conn, Q.PAYLOAD_BOOL_FALSE)["rows"]]
        self.assertNotEqual(true, false, (true, false))
        blocked = Q.order_whitelist(self.conn, Q.PAYLOAD_BOOL_TRUE)
        self.assertEqual(blocked["error"], "COLUMN_NOT_ALLOWED")
        self.assertEqual(blocked["rows"], [])

    def test_whitelist_keeps_legitimate_sorting_identical(self):
        concat = Q.order_concat(self.conn, "phone")["rows"]
        safe = Q.order_whitelist(self.conn, "PHONE", "ASC")["rows"]
        self.assertEqual(concat, safe, "白名单不该改变合法输入的结果")
        self.assertEqual(Q.order_whitelist(self.conn, "id", "sideways")["error"],
                         "DIRECTION_NOT_ALLOWED")

    def test_second_order_injection_leaks_only_on_read(self):
        """写入是绑定的（载荷原样进库），读取时再拼一次才爆炸 —— sink 才是危险点。"""
        Q.note_add(self.conn, Q.PAYLOAD_SECOND_ORDER, "note-body")
        concat = Q.note_digest_concat(self.conn)
        self.assertEqual([r["rows"] for r in concat], [[("sha256$TOP_SECRET",)]])
        bound = Q.note_report_bound(self.conn, Q.PAYLOAD_SECOND_ORDER)
        self.assertEqual(bound["rows"], [("note-body",)], "绑定读取只会拿到正文")

    def test_stacked_statements_depend_on_the_executing_api(self):
        """同一段叠句载荷：execute() 拒绝第二条，executescript() 照做（实测能力差异）。"""
        out = Q.stacked_outcome(Q.fresh_db(), Q.PAYLOAD_STACKED)
        self.assertEqual(out["execute"], "ProgrammingError")
        self.assertEqual(out["executescript"], "no-error")
        self.assertEqual(out["tables_dropped"], 1, out)

    def test_like_metacharacters_widen_matches_without_being_injection(self):
        """`%` 不是注入，但会超出预期：loose 全命中、strict（转义元字符）零命中。"""
        out = Q.like_search_bound(self.conn, "%")
        self.assertEqual(len(out["loose"]["rows"]), 3, out["loose"])
        self.assertEqual(out["strict"]["rows"], [])
        self.assertEqual(out["widened"], 3)
        self.assertIsNone(out["strict"]["error"], "ESCAPE 子句必须被 SQLite 接受")


class TestXssEscaping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = X.payload_table()

    def test_every_payload_is_flagged_in_vuln_and_clean_in_safe(self):
        self.assertEqual(len(X.PAYLOADS), len(self.rows))
        for row in self.rows:
            with self.subTest(payload=row["label"]):
                self.assertTrue(row["vuln_evidence"], row["payload"])
                self.assertEqual(row["safe_evidence"], [], row["vuln_evidence"])

    def test_safe_output_matches_reference_escape(self):
        """参照实现就是标准库：文本节点必须逐字等于 html.escape(payload, quote=True)。"""
        for label, payload in X.PAYLOADS.items():
            page = X.render_safe(payload)
            with self.subTest(payload=label):
                self.assertEqual(X.text_node(page), html.escape(payload, quote=True))

    def test_roundtrip_escapes_without_destroying_data(self):
        for row in self.rows:
            with self.subTest(payload=row["label"]):
                self.assertTrue(row["safe_roundtrip"])

    def test_ampersand_omission_is_caught_as_entity_redecode(self):
        """只换 `< >` 不换 `&` 的后果：实体解一次就变回标记。"""
        row = next(r for r in self.rows if r["label"] == "假转义（二次解码）")
        self.assertEqual(len(row["vuln_evidence"]), 1, row["vuln_evidence"])
        self.assertIn("实体解一次", row["vuln_evidence"][0])

    def test_backslash_swallows_the_js_delimiter_only_in_vuln(self):
        payload = X.PAYLOADS["吞定界符的反斜杠"]
        self.assertTrue(X.js_literal_hijacked(X.render_vuln(payload), payload))
        self.assertFalse(X.js_literal_hijacked(X.render_safe(payload), payload))

    def test_closing_script_tag_is_neutralised_by_json_escaping(self):
        payload = X.PAYLOADS["提前闭合脚本块"]
        self.assertGreater(X.render_vuln(payload).count("</script"), 1)
        self.assertEqual(X.render_safe(payload).count("</script"), 1)

    def test_javascript_scheme_is_replaced_not_escaped(self):
        page = X.render_safe(X.PAYLOADS["javascript 协议"])
        href = page.split('<a href="', 1)[1].split('"', 1)[0]
        self.assertEqual(href, "#blocked")
        vuln = X.render_vuln(X.PAYLOADS["javascript 协议"])
        self.assertTrue(vuln.split('<a href="', 1)[1].startswith("javascript:"))

    def test_http_layer_shows_the_same_verdict_as_the_pure_function(self):
        """真起真发真关：状态码、Content-Type、字节与纯函数层判定必须一致。"""
        payload = X.PAYLOADS["脚本标签"]
        both = X.serve_both(payload)
        for mode in ("vuln", "safe"):
            row = both[mode]
            with self.subTest(mode=mode):
                self.assertEqual(row["status"], 200)
                self.assertTrue(row["is_html"])
                self.assertEqual(row["headers"]["x-content-type-options"], "nosniff")
                expected = X.evidence(
                    X.render_vuln(payload) if mode == "vuln" else X.render_safe(payload),
                    payload)
                self.assertEqual(row["evidence"], expected)
        self.assertTrue(both["vuln"]["evidence"])
        self.assertEqual(both["safe"]["evidence"], [])
        self.assertIn("&lt;script&gt;", both["safe"]["body"])
        self.assertNotEqual(both["vuln"]["port"], both["safe"]["port"])

    def test_evidence_rule_is_not_a_placeholder(self):
        """反向证明：把修复版的文本转义改坏，判定必须立刻出现信号。

        改的是临时副本里的**被测代码**，不是测试断言（B20 的规矩）。
        """
        work = make_probe_root("xss")
        try:
            shutil.copytree(ROOT / "sec32", work / "sec32")
            target = work / "sec32" / "xss.py"
            text = target.read_text(encoding="utf-8")
            mutated = text.replace("    return html.escape(name, quote=True)",
                                   "    return html.escape(name, quote=False)")
            self.assertNotEqual(mutated, text, "锚点没命中，这条证明就是空的")
            target.write_text(mutated, encoding="utf-8")   # 不写回去，加载的就还是原始模块
            module = load_mutated("mutated_xss", target)
            payload = X.PAYLOADS["属性逃逸"]
            self.assertTrue(X.evidence(module.render_safe(payload), payload),
                            "去掉 quote=True 后判定毫无反应")
        finally:
            destroy_probe_root(work)


class TestCredentials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cost = C.cost_table()          # 现算一次约 2 秒，全类共用

    def test_plaintext_is_recoverable(self):
        record = C.store_plain("hunter2")
        self.assertEqual(C.recover_plain(record), "hunter2")
        self.assertEqual(record["stored"], "hunter2")

    def test_unsalted_digest_collides_across_users(self):
        effect = C.salt_effect("hunter2")
        self.assertTrue(effect["md5_same"], "无盐同口令必然同摘要（彩虹表与横向比较的前提）")
        self.assertFalse(effect["pbkdf2_same"])
        self.assertTrue(effect["salt_differs"])
        self.assertTrue(effect["verify_a"])
        self.assertFalse(effect["verify_b_wrong"])

    def test_pbkdf2_verifies_and_rejects_tampering(self):
        record = C.store_pbkdf2("hunter2", iters=2_000)
        self.assertTrue(C.verify_pbkdf2(record, "hunter2"))
        self.assertFalse(C.verify_pbkdf2(record, "hunter3"))
        tampered = {**record, "salt": bytes.fromhex(record["salt"]).hex()}
        tampered = {**record, "iters": 1}
        self.assertFalse(C.verify_pbkdf2(tampered, "hunter2"), "改迭代次数就该验不过")

    def test_cost_table_is_monotone_in_iterations(self):
        ladder = self.cost["pbkdf2_ladder"]
        rates = [ladder[k] for k in sorted(ladder)]
        self.assertTrue(all(a > b for a, b in zip(rates, rates[1:])), rates)
        ratio = rates[0] / rates[-1]
        self.assertGreater(ratio, 50, f"迭代 100 倍而吞吐只降 {ratio:.1f} 倍，成本模型可疑")

    def test_slowdown_is_stated_in_orders_of_magnitude_only(self):
        """口径：这条断言只要求"数量级"级别的差距，不假装测出 GPU 上的数字。"""
        self.assertGreater(self.cost["slowdown_vs_md5"], 1e4)
        fast, slow = self.cost["md5_per_sec"], self.cost["pbkdf2_default_per_sec"]
        self.assertLess(C.dictionary_hours(10 ** 6, fast),
                        C.dictionary_hours(10 ** 6, slow))

    def test_random_tokens_are_reproducible_and_secrets_are_not(self):
        ent = C.token_entropy()
        self.assertTrue(ent["random_reproducible"], "已知种子必须能复现 random 的令牌")
        self.assertFalse(ent["secrets_reproducible"])
        self.assertTrue(ent["secrets_unique"])
        self.assertGreater(ent["secrets_bits_per_token"], ent["random_bits_per_token"])

    def test_default_iterations_are_not_quietly_lowered(self):
        """这条是"防止有人为了跑得快把参数改掉"的钉子；改就要连口径一起改。"""
        self.assertGreaterEqual(C.DEFAULT_ITERS, 10_000)
        self.assertGreaterEqual(C.SALT_BYTES, 16)
        with self.assertRaises(ValueError):
            C.hash_rate("md4")

    def test_rate_measurement_is_reproducible_in_order_of_magnitude(self):
        again = C.hash_rate("pbkdf2", C.DEFAULT_ITERS)
        ratio = again / self.cost["pbkdf2_default_per_sec"]
        self.assertTrue(0.4 < ratio < 2.5, (ratio, again))


class TestPathTraversal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = T.make_tree()
        cls.rows = T.build_case_rows(cls.tree)
        cls.by_name = {r["name"]: r for r in cls.rows if "skipped" not in r}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tree["base"], ignore_errors=True)

    def test_guarded_handler_never_escapes(self):
        escaped = [r["name"] for r in self.rows if "skipped" not in r
                   and r["guarded"]["verdict"] == "ESCAPED"]
        self.assertEqual(escaped, [], escaped)

    def test_the_crude_join_escapes_repeatedly(self):
        escaped = [r["name"] for r in self.rows if "skipped" not in r
                   and r["join"]["verdict"] == "ESCAPED"]
        self.assertGreaterEqual(len(escaped), 5, escaped)

    def test_prefix_check_fails_specifically_on_the_sibling_directory(self):
        """`static_evil` 以 `static` 开头：startswith 通过，is_relative_to 拦住。

        这一条是整组的核心证据——真实代码里最常见的错法。
        """
        row = self.by_name["兄弟目录绝对路径（前缀检查的靶）"]
        self.assertEqual(row["prefix"]["verdict"], "ESCAPED", row["prefix"])
        self.assertEqual(row["guarded"]["verdict"], "REJECTED", row["guarded"])
        root, sibling = str(self.tree["root"].resolve()), str(self.tree["sibling_root"])
        self.assertTrue(sibling.startswith(root), "前缀检查之所以被骗，是因为它真的是前缀")
        self.assertFalse(self.tree["sibling_root"].resolve().is_relative_to(
            self.tree["root"].resolve()))

    def test_refusal_reasons_are_distinguishable(self):
        """红要红在该红的原因上：每条载荷都必须落到不同的那条规则。"""
        expected = {
            "相对穿越": "..",
            "百分号编码的点": "..",
            "双重编码": "双重编码",
            "绝对路径（指向 root 外）": "绝对路径",
            "NUL 截断": "NUL",
            "尾点（Windows 会忽略）": "尾点",
        }
        for name, keyword in expected.items():
            with self.subTest(case=name):
                row = self.by_name[name]
                self.assertEqual(row["guarded"]["verdict"], "REJECTED", row["guarded"])
                self.assertIn(keyword, row["guarded"]["detail"], row["guarded"]["detail"])

    def test_legitimate_access_is_not_blocked(self):
        for name in ("正常文件", "正常子目录", "大小写变形"):
            with self.subTest(case=name):
                row = self.by_name[name]
                self.assertEqual(row["guarded"]["verdict"], "SERVED_INSIDE", row["guarded"])
                self.assertIn(T.INSIDE_SENTINEL, row["guarded"]["detail"])

    def test_blacklist_and_encoding_only_matter_if_someone_decodes(self):
        """`%2e%2e` 在**没有解码那一步**的实现里只是打不开的文件名（ERROR），不是越界。

        编码绕过永远依附于"某一层确实解过码"——课本常省掉这半句。
        """
        row = self.by_name["百分号编码的点"]
        self.assertEqual(row["blacklist"]["verdict"], "ERROR", row["blacklist"])
        self.assertEqual(row["guarded"]["verdict"], "REJECTED")

    def test_stdlib_reference_behaviour_is_recorded_not_assumed(self):
        ref = T.stdlib_reference()
        self.assertEqual(ref["unquote_2e2e2f"], "../")
        self.assertEqual(ref["unquote_double_252e"], "%2e%2e%2f")
        self.assertEqual(ref["unquote_twice_252e"], "../", "解两次才变成 ../")
        self.assertNotIn("/", ref["unquote_overlong_c0af"], "本机实测过长编码不产生斜杠")
        self.assertEqual(ref["unquote_fullwidth_solidus"], repr("／"))
        self.assertTrue(ref["is_relative_to_case_flip"],
                        "WindowsPath 的比较大小写无关 ⇒ 大小写变换打不穿判定")
        self.assertEqual(ref["plus_in_unquote"], "a+b",
                         "unquote 不把 + 当空格；那是 unquote_plus 的语义")

    def test_symlink_escape_is_caught_or_declared_not_skipped(self):
        row = next(r for r in self.rows if r["name"] == "软链越界")
        if "skipped" in row:
            self.skipTest(row["skipped"])
        self.assertEqual(row["join"]["verdict"], "ESCAPED", row["join"])
        self.assertEqual(row["guarded"]["verdict"], "REJECTED", row["guarded"])

    def test_resolve_check_is_the_only_thing_stopping_a_symlink_escape(self):
        """拆掉 resolve 归属判定，软链载荷必须立刻越界；不拆则拦住。

        上一版这条探针挑错了载荷：`../outside.txt` 在段规则之外还会被
        `_reject_win_normalization`（`..` 以点结尾）拦下，所以只拆 resolve 也测不出来——
        那是我的探针写错，不是被测代码没问题。软链路径不含 `..`，
        **只有** resolve 判定能拦它，正好用来单独量这一层。
        """
        if self.tree["symlink"] is None:
            self.skipTest("本机建不出目录软链（权限或文件系统限制），这一层没法单独量")
        work = make_probe_root("path")
        try:
            shutil.copytree(ROOT / "sec32", work / "sec32")
            target = work / "sec32" / "traversal.py"
            original = target.read_text(encoding="utf-8")
            no_resolve = original.replace(
                "    if not target.is_relative_to(root.resolve()):", "    if False:")
            self.assertNotEqual(no_resolve, original, "锚点没命中，这条证明就是空的")
            payload = "linkdir/outside.txt"
            for label, source, want in (("原样", original, "REJECTED"),
                                        ("只拆 resolve 判定", no_resolve, "ESCAPED")):
                with self.subTest(stage=label):
                    target.write_text(source, encoding="utf-8")
                    module = load_mutated(f"mut_trav_{abs(hash(label))}", target)
                    tree = module.make_tree()
                    try:
                        if tree["symlink"] is None:
                            self.skipTest("副本所在文件系统不支持软链")
                        verdict = module.classify(module.serve_guarded, tree["root"],
                                                  payload)
                        self.assertEqual(verdict["verdict"], want, (label, verdict))
                    finally:
                        shutil.rmtree(tree["base"], ignore_errors=True)
        finally:
            destroy_probe_root(work)


class TestProbeSandboxIsSafe(unittest.TestCase):
    """这一组是事故本身换来的：守卫代码自己也必须被测，否则它只是安慰剂。"""

    def test_probe_root_is_never_inside_the_repo(self):
        work = make_probe_root("guard")
        try:
            self.assertFalse(inside_repo(work), work)
            self.assertTrue(str(work).startswith(str(tempfile.gettempdir())))
        finally:
            destroy_probe_root(work)

    def test_destroy_refuses_an_in_repo_path(self):
        """反向证明：指着仓库里说"删掉它"，守卫必须拒绝，而且目录必须还在。"""
        decoy = PROJECTS_DIR / "_b32_guard_should_survive"
        decoy.mkdir(exist_ok=True)
        try:
            with self.assertRaises(RuntimeError):
                destroy_probe_root(decoy)
            self.assertTrue(decoy.is_dir(), "守卫没能保住仓库内的目录")
        finally:
            decoy.rmdir()

    def test_destroy_refuses_a_path_it_did_not_create(self):
        outside = pathlib.Path(tempfile.gettempdir()) / "definitely-not-mine-b32"
        outside.mkdir(exist_ok=True)
        nested = make_probe_root("nested")     # 只有走 make_probe_root 的才允许被删
        try:
            with self.assertRaises(RuntimeError):
                destroy_probe_root(outside)    # 临时目录里但不是我建的那一个
            self.assertTrue(outside.is_dir())
        finally:
            outside.rmdir()
            destroy_probe_root(nested)


class TestAuditScanner(unittest.TestCase):
    def test_registry_and_scan_agree_both_ways(self):
        self.assertEqual(A.problems(), [])

    def test_scanner_finds_the_concat_sites_in_sqli(self):
        found = {(site["func"]) for site in A.scan_package().get("sqli.py", [])}
        self.assertIn("login_concat", found)
        self.assertIn("search_concat", found)
        self.assertIn("order_whitelist", found, "白名单版也是拼接点，只是定性不同")
        self.assertGreaterEqual(len(found), 6, found)

    def test_wrappers_must_be_registered_or_sites_go_invisible(self):
        """本项目的 SQL 走 `_rows/_outcome` 包装。把它们从 sink 集合里摘掉，
        扫出来的点数必须大幅下降——这就是"静态检查最常见的失效方式"的实物证据。"""
        full = len(A.scan_package().get("sqli.py", []))
        saved_name = A.NAME_SINKS
        A.NAME_SINKS = ()
        try:
            reduced = len(A.scan_package().get("sqli.py", []))
        finally:
            A.NAME_SINKS = saved_name
        self.assertLess(reduced, full, (reduced, full))
        A.NAME_SINKS = saved_name
        self.assertEqual(len(A.scan_package().get("sqli.py", [])), full)

    def test_unregistered_site_makes_problems_red(self):
        """登记表与扫描结果任一方漂移都要红：这里改登记表，看它点名。"""
        saved = dict(A.JUDGED)
        try:
            A.JUDGED.pop(("sqli.py", "order_whitelist"))
            problems = A.problems()
        finally:
            A.JUDGED.update(saved)
        self.assertTrue(any("order_whitelist" in p for p in problems), problems)

    def test_registry_entry_for_a_renamed_function_is_stale(self):
        saved = dict(A.JUDGED)
        try:
            A.JUDGED[("sqli.py", "no_such_function")] = ("危险", "假条目")
            problems = A.problems()
        finally:
            A.JUDGED.pop(("sqli.py", "no_such_function"))
            A.JUDGED.update(saved)
        self.assertTrue(any("no_such_function" in p for p in problems), problems)

    def test_summary_is_computed_from_the_four_groups(self):
        s = A.summary()
        self.assertEqual(s["xss"]["payloads"], len(X.PAYLOADS))
        self.assertEqual(s["xss"]["safe_flagged"], 0)
        self.assertEqual(s["traversal"]["by_handler"]["guarded"]["escaped"], 0)
        self.assertGreater(s["creds"]["slowdown_vs_md5"], 1e4)
        self.assertEqual(s["audit_problems"], [])
        self.assertEqual(s["sqli"]["login_leaks_fixed"], 1,
                         "只有正常口令那一条应该登录成功")

    def test_two_runs_of_summary_agree_where_no_time_is_involved(self):
        """确定性：除成本表（含实测耗时）外，其它组必须逐字相同。"""
        first, second = A.summary(), A.summary()
        for key in ("xss", "traversal", "sqli", "sql_sites", "audit_problems"):
            with self.subTest(key=key):
                self.assertEqual(first[key], second[key])


class TestNoLeftovers(unittest.TestCase):
    def test_probe_copies_leave_nothing_behind(self):
        """反向验证用的临时副本必须清理干净，否则仓库里就多出一份会烂掉的代码。"""
        projects = ROOT.parent
        leftovers = sorted(p.name for p in projects.glob("_probe_b32_*"))
        self.assertEqual(leftovers, [])
        stale = sorted(p.name for p in ROOT.glob("_probe_b32_*"))
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
