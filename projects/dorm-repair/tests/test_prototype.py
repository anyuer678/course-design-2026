"""B16 原型的契约测试（headless，全部可自动跑）。

这一层的价值在于：**界面观感我不能替你验，但界面的承诺可以验。**
所以这里断言的都是"原型有没有遵守 B15 的模型"：可见范围、可用动作、必填输入、
错误一次报全、被拒绝时状态不变、静态文件的目录包含、前端有没有用不安全写法。
"看着顺不顺眼、点起来对不对"仍然只能你来走查（清单在 docs/07-walkthrough.md）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# prototype.server 必须最先导入：它负责把 B11 的 netlab 挂进 sys.path（不复制第二套 HTTP）
from prototype.server import IDENTITIES, PrototypeServer, read_static  # noqa: E402
from netlab.client import Connection                    # noqa: E402
from spec import workorder as W                         # noqa: E402

WEB = ROOT / "prototype" / "web"


def q(role, actor):
    return f"role={role}&actor={actor}"


class ProtoCase(unittest.TestCase):
    def setUp(self):
        self.server = PrototypeServer(port=0)
        self.port = self.server.start()
        self.addCleanup(self.tearDown_server)

    def tearDown_server(self):
        self.server.stop()

    def get(self, conn, path):
        response = conn.request("GET", path)
        return response.status, (json.loads(response.text()) if response.header("content-type",
                                                                                 ) or "" else {})

    def json_of(self, response):
        return json.loads(response.text())


class TestPagesAndAccessibilityContract(ProtoCase):
    def test_index_is_served_with_a11y_contracts(self):
        with Connection(port=self.port) as c:
            page = c.request("GET", "/").text()
        for marker in ('lang="zh-CN"', '<meta charset="utf-8">', 'class="skip"',
                       'role="status"', 'aria-live="polite"', 'role="alert"',
                       '<caption', 'scope="col"', '<main>', '<header', '<footer'):
            with self.subTest(marker=marker):
                self.assertIn(marker, page)

    def test_every_form_control_has_a_label(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\sid="([\w-]+)"', page))
        self.assertIn("room", ids)
        for field_id in ids - {"f-overdue"}:        # 复选框的 label 把 input 包在里面
            self.assertIn(f'for="{field_id}"', page, f"{field_id} 没有关联的 label")

    def test_describedby_targets_exist(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for target in set(re.findall(r'aria-describedby="([\w-]+)"', page)):
            self.assertIn(f'id="{target}"', page, f"aria-describedby 指向不存在的 {target}")

    def test_error_and_empty_states_exist_in_markup(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for element in ('id="empty"', 'id="error-state"', 'id="load-state"',
                        'id="create-summary"', '-err"'):
            with self.subTest(element=element):
                self.assertIn(element, page)

    def test_static_assets_content_types(self):
        with Connection(port=self.port) as c:
            self.assertEqual(c.request("GET", "/app.js").header("content-type"),
                             "text/javascript; charset=utf-8")
            self.assertEqual(c.request("GET", "/style.css").header("content-type"),
                             "text/css; charset=utf-8")
            self.assertEqual(c.request("GET", "/favicon.svg").header("content-type"),
                             "image/svg+xml")

    def test_static_reader_refuses_paths_outside_web_root(self):
        """绕过协议层直接从函数进：目录包含检查必须自己站得住。"""
        for name in ["../server.py", "..\\server.py", "web/../../spec/workorder.py",
                     str(ROOT / "spec" / "workorder.py"), "/etc/passwd",
                     "C:\\Windows\\win.ini", "index.html\\..\\server.py"]:
            with self.subTest(name=name):
                self.assertIsNone(read_static(name))
        self.assertTrue(read_static("index.html").startswith(b"<!DOCTYPE html>"))
        # 绝对路径本身不是问题，落在 web 目录里才给读：检查的是解析后的位置
        self.assertIsNotNone(read_static(str(WEB / "index.html")))


class TestFrontendSource(unittest.TestCase):
    JS_GLOBALS = {"document", "fetch", "JSON", "Date", "Number", "Array", "Object", "Set",
                  "Map", "Promise", "Error", "Boolean", "String", "console", "navigator",
                  "encodeURIComponent", "decodeURIComponent", "URLSearchParams", "setTimeout",
                  "alert", "parseInt", "parseFloat", "isNaN"}
    JS_KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "typeof", "function",
                   "await", "async", "new", "do", "else", "in", "of"}

    def test_every_called_helper_is_defined(self):
        """`node --check` 只管语法：函数名写错（我这边真写过 `busy` 却调 `setBusy`）
        它照样通过，浏览器里才炸。这里做一次便宜的名称解析，把这类错误提前抓住。"""
        text = (WEB / "app.js").read_text(encoding="utf-8")
        defined = set(re.findall(r"function\s+([\w$]+)", text))
        defined |= set(re.findall(r"(?:const|let|var)\s+([\w$]+)\s*=", text))
        called = set(re.findall(r"(?<![\w.$])([a-z][\w$]*)\s*\(", text))
        missing = sorted(called - defined - self.JS_GLOBALS - self.JS_KEYWORDS)
        self.assertEqual(missing, [], f"这些名字被当函数调用但没有定义：{missing}")

    def test_table_header_matches_rendered_columns(self):
        """列数对不上是常见的前端缺陷：读屏器会念错位置，视觉上也会串列。"""
        page = (WEB / "index.html").read_text(encoding="utf-8")
        script = (WEB / "app.js").read_text(encoding="utf-8")
        header = len(re.findall(r'<th scope="col">', page))
        body = script.split("function renderRows(")[1].split("\n}\n")[0]
        built = len(re.findall(r"cell\(", body))
        self.assertEqual(header, built + 1, "表头列数应等于每行生成的单元格数，外加操作那一列")

    def test_markup_has_no_invalid_closings(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for bad in ("</input>", "</br>", "</img>", "<input></input>"):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, page)

    def test_no_unsafe_dom_writes(self):
        patterns = [r"\.\s*innerHTML\s*[+]?=", r"\.\s*outerHTML\s*[+]?=",
                    r"document\s*\.\s*write(?:ln)?\s*\(", r"insertAdjacentHTML\s*\("]
        text = (WEB / "app.js").read_text(encoding="utf-8")
        for pattern in patterns:
            self.assertIsNone(re.search(pattern, text),
                              f"app.js 出现了 {pattern}：用户写的描述会被当标记解析")

    def test_uses_textcontent_for_user_data(self):
        text = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("textContent", text)
        self.assertIn("createElement", text)
        self.assertIn("replaceChildren", text)     # 重渲染前先清空，避免旧行残留

    def test_app_js_is_syntactically_valid(self):
        if not shutil.which("node"):
            self.skipTest("本机没有 node，跳过语法检查")
        proc = subprocess.run(["node", "--check", str(WEB / "app.js")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_business_rules_duplicated_in_js(self):
        """前端不许自带状态机：动作、必填项、可见性都得读服务端的结论。

        抓到 `submit`/`confirm` 这类动作名是可以的（要显示中文按钮名），
        但不允许出现"如果状态是 X 且角色是 Y 才显示"这种条件判断。
        """
        text = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("state ===", text.replace("state.detail.state ===", ""),
                         "前端在按状态自己推规则了？")
        self.assertNotIn("role ===", text, "前端在按角色自己推权限了？")
        self.assertIn("attemptable", text)
        self.assertIn("required_inputs", text)


class TestApiContract(ProtoCase):
    def test_meta_comes_from_the_model_not_a_copy(self):
        with Connection(port=self.port) as c:
            meta = self.json_of(c.request("GET", "/api/meta"))
        self.assertEqual(meta["states"], [s.value for s in W.State])
        self.assertEqual(meta["terminal"], [s.value for s in W.TERMINAL])
        self.assertEqual(meta["priorities"], {p.value: W.SLA_HOURS[p] for p in W.Priority})
        self.assertEqual(meta["visibility"], {str(r): v for r, v in W.ROLE_VISIBILITY.items()})

    def test_list_matches_the_visibility_matrix(self):
        expected = {
            ("STUDENT", "stu-1"): {"R001", "R002", "R005"},
            ("STUDENT", "stu-2"): {"R003", "R004", "R006"},
            ("WORKER", "w-1"): {"R001", "R002", "R003"},
            # w-2 现在看得见 R005（他完工、学生已确认的关闭单）。出处：AQ-12 于 2026-10-01
            # 裁决为 OWN_OR_POOL_OR_RESOLVED。这一格是原型**自己长出来的**——列表读
            # spec.visible_to()，前端一行没改；而 R005 依然没有任何可点动作（attemptable 表在下面）。
            ("WORKER", "w-2"): {"R003", "R005", "R006"},
            ("ADMIN", "adm-1"): {"R001", "R002", "R003", "R004", "R005", "R006"},
        }
        with Connection(port=self.port) as c:
            for (role, actor), ids in expected.items():
                data = self.json_of(c.request("GET", f"/api/orders?{q(role, actor)}"))
                with self.subTest(role=role, actor=actor):
                    self.assertEqual({o["id"] for o in data["orders"]}, ids)
                    self.assertEqual(data["count"], len(ids))
                    self.assertEqual(data["empty"], not ids)

    def test_workers_never_see_drafts(self):
        with Connection(port=self.port) as c:
            for actor in IDENTITIES["WORKER"]:
                data = self.json_of(c.request("GET", f"/api/orders?{q('WORKER', actor)}"))
                with self.subTest(actor=actor):
                    self.assertEqual([o["id"] for o in data["orders"] if o["state"] == "DRAFT"], [])

    def test_overdue_orders_sort_first(self):
        with Connection(port=self.port) as c:
            data = self.json_of(c.request("GET", f"/api/orders?{q('ADMIN', 'adm-1')}"))
        overdue = [o["id"] for o in data["orders"] if o["overdue"]]
        self.assertEqual(overdue, ["R003"], "种子里只该有 R003 逾期（URGENT 已过 5 小时）")
        self.assertEqual(data["orders"][0]["id"], "R003", "逾期排最前，管理员一进页面就先看到它")

    def test_detail_reports_attemptable_and_required_inputs_from_the_model(self):
        with Connection(port=self.port) as c:
            for role, actor, oid, expected in [
                    ("STUDENT", "stu-1", "R001", {"confirm", "reject_check"}),
                    ("ADMIN", "adm-1", "R001", {"force_close"}),
                    ("WORKER", "w-1", "R001", set()),        # 已完工，维修员这一侧没动作了
                    ("STUDENT", "stu-2", "R004", {"submit", "cancel"}),
                    ("ADMIN", "adm-1", "R005", set()),        # 终态：任何角色都空
            ]:
                data = self.json_of(c.request("GET", f"/api/orders/{oid}?{q(role, actor)}"))
                with self.subTest(role=role, oid=oid):
                    self.assertEqual(set(data["attemptable"]), expected)
                    for action in data["attemptable"]:
                        self.assertEqual(data["required_inputs"][action],
                                         list(W.required_inputs(W.Action(action))))

    def test_history_is_renderable_and_append_only(self):
        with Connection(port=self.port) as c:
            data = self.json_of(c.request("GET", f"/api/orders/R001?{q('ADMIN', 'adm-1')}"))
        steps = [(h["from"], h["to"], h["action"]) for h in data["history"]]
        self.assertEqual(steps, [("DRAFT", "SUBMITTED", "submit"),
                                 ("SUBMITTED", "ASSIGNED", "assign"),
                                 ("ASSIGNED", "IN_PROGRESS", "accept"),
                                 ("IN_PROGRESS", "RESOLVED", "resolve")])
        self.assertTrue(all(h["role"] and h["actor"] for h in data["history"]))

    def test_create_lists_every_field_problem_and_creates_nothing(self):
        with Connection(port=self.port) as c:
            before = self.json_of(c.request("GET", f"/api/orders?{q('ADMIN', 'adm-1')}"))["count"]
            bad = c.request("POST", f"/api/orders?{q('STUDENT', 'stu-1')}",
                            body=json.dumps({"room": "101", "category": "WIFI",
                                             "priority": "SOMEDAY", "description": "   ",
                                             "contact": "123"}).encode(),
                            headers=[("Content-Type", "application/json")])
            after = self.json_of(c.request("GET", f"/api/orders?{q('ADMIN', 'adm-1')}"))["count"]
        self.assertEqual(bad.status, 400)
        payload = self.json_of(bad)
        self.assertEqual(payload["code"], "INVALID_FIELDS")
        self.assertEqual([f["code"] for f in payload["fields"]],
                         ["ROOM_FORMAT", "CATEGORY_UNKNOWN", "PRIORITY_UNKNOWN",
                          "DESCRIPTION_LENGTH", "CONTACT_FORMAT"])
        self.assertEqual(before, after, "校验失败不该留下半张工单")

    def test_full_chain_through_the_api(self):
        with Connection(port=self.port) as c:
            created = c.request("POST", f"/api/orders?{q('STUDENT', 'stu-1')}",
                                body=json.dumps({"room": "D04-417", "category": "FURNITURE",
                                                 "priority": "NORMAL", "description": "椅子腿裂了",
                                                 "contact": "13711112222"}).encode(),
                                headers=[("Content-Type", "application/json")])
            self.assertEqual(created.status, 201)
            oid = self.json_of(created)["id"]
            self.assertEqual(self.json_of(created)["state"], "DRAFT")
            self.assertIn("submit", self.json_of(created)["attemptable"])

            def act(action, role, actor, **extra):
                body = json.dumps({"action": action, **extra}).encode()
                response = c.request("POST", f"/api/orders/{oid}/act?{q(role, actor)}",
                                     body=body, headers=[("Content-Type", "application/json")])
                return response.status, self.json_of(response)

            status, view = act("submit", "STUDENT", "stu-1")
            self.assertEqual((status, view["state"]), (200, "SUBMITTED"))
            self.assertIsNotNone(view["submitted_at"])
            self.assertEqual(view["sla_due_at"], view["submitted_at"] + 24 * 3600,
                             "时限来自模型的 SLA 表，不是前端写的")
            status, view = act("assign", "ADMIN", "adm-1", assignee="w-1")
            self.assertEqual((status, view["state"], view["assignee"]), (200, "ASSIGNED", "w-1"))
            status, view = act("accept", "WORKER", "w-1")
            self.assertEqual((status, view["state"]), (200, "IN_PROGRESS"))
            status, view = act("resolve", "WORKER", "w-1", note="换新椅子")
            self.assertEqual((status, view["state"]), (200, "RESOLVED"))
            status, view = act("confirm", "STUDENT", "stu-1")
            self.assertEqual((status, view["state"], view["assignee"]), (200, "CLOSED", ""))
            self.assertEqual(view["attemptable"], [], "终态不该还剩按钮")
            self.assertEqual(len(view["history"]), 5)

    def test_server_refuses_actions_the_role_cannot_take(self):
        """> NFR-02：前端不给按钮只是便利，越权必须被服务端拒绝。"""
        with Connection(port=self.port) as c:
            before = self.json_of(c.request("GET", f"/api/orders/R003?{q('ADMIN', 'adm-1')}"))
            refused = c.request("POST", f"/api/orders/R003/act?{q('STUDENT', 'stu-2')}",
                                body=json.dumps({"action": "resolve", "note": "我说了算"}).encode(),
                                headers=[("Content-Type", "application/json")])
            after = self.json_of(c.request("GET", f"/api/orders/R003?{q('ADMIN', 'adm-1')}"))
        self.assertEqual(refused.status, 400)
        self.assertIn(self.json_of(refused)["code"], ("NO_SUCH_TRANSITION", "ROLE_NOT_ALLOWED"))
        self.assertEqual(before["state"], after["state"], "被拒绝的操作不能改到工单")
        self.assertEqual(before["history"], after["history"])

    def test_missing_required_input_is_rejected_with_a_stable_code(self):
        # R006 是 ASSIGNED，return_pool 的前置条件里带 reason（第 3 节 TR-04）
        with Connection(port=self.port) as c:
            response = c.request("POST", f"/api/orders/R006/act?{q('ADMIN', 'adm-1')}",
                                 body=json.dumps({"action": "return_pool"}).encode(),
                                 headers=[("Content-Type", "application/json")])
        self.assertEqual(response.status, 400)
        self.assertEqual(self.json_of(response)["code"], "REASON_REQUIRED")

    def test_identity_is_validated_server_side(self):
        for bad in ["role=HACKER&actor=adm-1", "role=ADMIN&actor=stu-1",
                    "role=STUDENT&actor=", ""]:
            with self.subTest(bad=bad), Connection(port=self.port) as c:
                response = c.request("GET", f"/api/orders?{bad}")
                self.assertEqual(response.status, 400)
                self.assertIn("error", self.json_of(response))

    def test_unknown_order_is_404_not_500(self):
        with Connection(port=self.port) as c:
            response = c.request("GET", f"/api/orders/R999?{q('ADMIN', 'adm-1')}")
        self.assertEqual(response.status, 404)

    def test_students_cannot_open_others_orders(self):
        with Connection(port=self.port) as c:
            response = c.request("GET", f"/api/orders/R003?{q('STUDENT', 'stu-1')}")
        self.assertEqual(response.status, 404, "看不见就是看不见，不透露它存在")

    def test_filters_narrow_without_escaping_visibility(self):
        with Connection(port=self.port) as c:
            mine = self.json_of(c.request("GET", f"/api/orders?{q('STUDENT', 'stu-1')}&state=SUBMITTED"))
            alls = self.json_of(c.request("GET", f"/api/orders?{q('ADMIN', 'adm-1')}&state=SUBMITTED"))
        self.assertEqual([o["id"] for o in mine["orders"]], [])
        self.assertTrue(mine["empty"], "筛选后为空要走空状态，不是留着上一次的行")
        self.assertGreater(len(alls["orders"]), 0)

    def test_blank_state_marker_survives_a_re_render(self):
        """空状态必须说清"是没有"而不是"没加载出来"——这条在 markup 里用文案承诺。"""
        page = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn("是没有，还是没加载出来", page)

    def test_frontend_maps_field_errors_to_each_field(self):
        """AC-05 的可自动部分：错误要落到"对应字段旁边"，不是只弹一句总提示。

        这里验的是接线的存在与形状（每个字段都有 `<id>-err` 落点、`aria-invalid` 被翻转、
        汇总里带条数、焦点送到第一个出错字段）。它在不在浏览器里真的显示出来，
        由 docs/07-walkthrough.md 的第 3 步人工确认。
        """
        script = (WEB / "app.js").read_text(encoding="utf-8")
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for field in ("room", "category", "priority", "description", "contact"):
            self.assertIn(f'id="{field}-err"', page, f"{field} 没有就地错误落点")
        self.assertIn("${item.field}-err", script, "没有把服务端返回的字段错误写到对应落点")
        self.assertIn('setAttribute("aria-invalid", "true")', script)
        self.assertIn("aria-invalid", script)
        self.assertRegex(script, r"有 \$\{fields\.length\} 处", "汇总应当告诉用户有几处要改")
        self.assertRegex(script, r"first\.focus|first\)\.focus", "焦点要送到第一个出错字段")

    def test_walkthrough_checklist_covers_every_story(self):
        """走查清单不是装饰：每个用户故事都得有人在浏览器里替它走一遍。"""
        walkthrough = (ROOT / "docs" / "07-walkthrough.md").read_text(encoding="utf-8")
        stories = (ROOT / "docs" / "04-user-stories.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"^###\s+(US-\d{2})", stories, re.M))
        self.assertEqual(len(listed), 13, "故事数量变了要同步走查清单")
        missing = sorted(u for u in listed if u not in walkthrough)
        self.assertEqual(missing, [], "这些故事没有对应的走查条目")
        for marker in ("未验证", "AQ-02", "AQ-03"):
            self.assertIn(marker, walkthrough, f"走查清单缺少 {marker} 相关内容")


if __name__ == "__main__":
    unittest.main()
