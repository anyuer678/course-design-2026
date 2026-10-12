"""Studio 门户自测：矩阵对齐 / 认证 / 启停鉴权 / 七产品真启停链路。

可独立推导的性质：
    - 管理动作（启停）未登录 → 401；登录是会话签名 cookie（webframe 能力）；
    - 登录错误统一"用户名或口令不对"（不给猜测者喂哪个字段错了）；
    - 改口令：未登录 401、旧口令错 400、新口令过短 400、成功后旧口令立即失效；
    - 密钥/口令落盘：重新打开 Auth，密钥与口令不变（重启不掉会话）；
    - 在线 = TCP 探活；不是门户启动的进程不许 stop（409）；
    - 实验台（showcase lab）并入为 managed product：真启停真探活。
"""
import http.client
import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.auth import USERNAME, Auth
from studio.manager import AlreadyOnline
from studio.server import build_app, build_manager

def _free_port(start: int) -> int:
    """从 start 起找第一个可绑定的空闲端口（2026-10-06 起：17788 撞上 IDE 内部
    监听端口导致 409 的教训——测试端口必须运行时探测，不能写死）。"""
    port = start
    for _ in range(64):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise RuntimeError(f"{start} 起找不到空闲端口")


LINKBOX_PORT = _free_port(18098)
LAB_PORT = _free_port(17788)
SIMLAB_PORT = _free_port(18018)
DATASCOPE_PORT = _free_port(18028)
CACHEKV_PORT = _free_port(18038)
SENSORHUB_PORT = _free_port(18049)
BOARD_PORT = _free_port(18059)
COURSELAB_PORT = _free_port(18069)


class PortalCase(unittest.TestCase):
    """直接驱动 app.handle；启停真子进程用例单独标注。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.auth = Auth(cls._tmp.name)
        cls.manager = build_manager(linkbox_port=LINKBOX_PORT,
                                    lab_port=LAB_PORT, simlab_port=SIMLAB_PORT,
                                    datascope_port=DATASCOPE_PORT,
                                    cachekv_port=CACHEKV_PORT,
                                    sensorhub_port=SENSORHUB_PORT,
                                    board_port=BOARD_PORT,
                                    courselab_port=COURSELAB_PORT,
                                    linkbox_memory=True)
        cls.app = build_app(cls.manager, cls.auth)
        # 生产里 build_server 会挂探活采样器；app 级测试挂一个不起线程的
        # 空采样器，让 /api/history 与生产同构（products 有内容、samples 可为空）
        from studio.monitor import UptimeMonitor
        cls.manager.uptime = UptimeMonitor(cls.manager)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path, query=[], keep_alive=False,
                      content_length=len(body))
        return self.app.handle(req)

    def login(self):
        raw = json.dumps({"username": USERNAME,
                          "password": self.auth.password}).encode()
        status, headers, body = self.handle(
            "POST", "/api/login", raw,
            [("Content-Type", "application/json")])
        assert status == 200, body
        cookie = None
        for k, v in headers:
            if k == "Set-Cookie" and v.startswith("wf_session="):
                cookie = v.split(";")[0]
        assert cookie, headers
        return cookie

    def authed(self, method, path, cookie, body=b""):
        return self.handle(method, path, body,
                           [("Cookie", cookie)] +
                           ([("Content-Type", "application/json")] if body else []))

    # ------------------------------------------------ 认证
    def test_auth_flow(self):
        status, _, body = self.handle("GET", "/api/me")
        self.assertEqual(json.loads(body)["user"], None)     # 未登录
        # 错口令：统一话术，401
        raw = json.dumps({"username": USERNAME, "password": "wrong"}).encode()
        status, _, body = self.handle("POST", "/api/login", raw,
                                      [("Content-Type", "application/json")])
        self.assertEqual(status, 401)
        self.assertIn("用户名或口令", body.decode("utf-8"))
        # 对口令 → 会话
        cookie = self.login()
        status, _, body = self.handle(
            "GET", "/api/me", headers=[("Cookie", cookie)])
        self.assertEqual(json.loads(body)["user"], USERNAME)
        # 登出 → 服务器强制回写空会话 cookie（浏览器会拿它替换旧 cookie）
        status, headers, _ = self.handle("POST", "/api/logout",
                                         headers=[("Cookie", cookie)])
        self.assertEqual(status, 200)
        new_cookie = None
        for k, v in headers:
            if k == "Set-Cookie" and v.startswith("wf_session="):
                new_cookie = v.split(";")[0]
        self.assertIsNotNone(new_cookie, "logout 必须回写空会话覆盖旧凭据")
        status, _, body = self.handle(
            "GET", "/api/me", headers=[("Cookie", new_cookie)])
        self.assertEqual(json.loads(body)["user"], None)

    def test_password_change(self):
        cookie = self.login()
        # 未登录改口令 → 401
        raw = json.dumps({"old": self.auth.password, "new": "new-password-1"}).encode()
        status, _, _ = self.handle("POST", "/api/password", raw,
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 401)
        # 旧口令错 → 400；新口令过短 → 400
        status, _, _ = self.authed("POST", "/api/password", cookie,
                                   json.dumps({"old": "bad", "new": "x"}).encode())
        self.assertEqual(status, 400)
        old = self.auth.password
        status, _, _ = self.authed("POST", "/api/password", cookie,
                                   json.dumps({"old": old, "new": "short"}).encode())
        self.assertEqual(status, 400)
        # 成功 → 旧口令登录立即失效，新口令可用
        status, _, _ = self.authed("POST", "/api/password", cookie,
                                   json.dumps({"old": old,
                                               "new": "new-password-1"}).encode())
        self.assertEqual(status, 200)
        wrong = json.dumps({"username": USERNAME, "password": old}).encode()
        status, _, _ = self.handle("POST", "/api/login", wrong,
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 401)
        right = json.dumps({"username": USERNAME,
                            "password": "new-password-1"}).encode()
        status, _, _ = self.handle("POST", "/api/login", right,
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.auth.set_password(old)          # 还原，免得影响同类其他用例
        # 世代机制：改口令前的旧会话（gen 已过期）做管理动作 → 401 重新登录
        status, _, body = self.authed("POST", "/api/products/linkbox/start",
                                      cookie)
        self.assertEqual(status, 401)
        self.assertIn("重新登录", body.decode("utf-8"))

    def test_credentials_persist_across_restart(self):
        """密钥与口令落盘：重新打开 Auth，两者都不变（重启不掉会话/口令）。"""
        again = Auth(self._tmp.name)
        self.assertEqual(again.secret, self.auth.secret)
        self.assertEqual(again.password, self.auth.password)

    # ------------------------------------------------ 目录与状态
    def test_listing_matches_product_matrix(self):
        status, _, body = self.handle("GET", "/api/products")
        self.assertEqual(status, 200)
        data = json.loads(body)
        ids = [p["id"] for p in data["products"]]
        # PRODUCTS.md §二矩阵：门户 + 九个 managed（boardweb 2026-10-07 加入）——矩阵全兑现
        self.assertEqual(ids, ["studio", "linkbox", "lab", "simlab", "datascope",
                               "cachekv", "sensorhub", "courselab", "board", "boardweb"])
        by_id = {p["id"]: p for p in data["products"]}
        for managed in ("linkbox", "lab", "simlab", "datascope", "cachekv",
                        "sensorhub", "courselab", "board", "boardweb"):
            self.assertTrue(by_id[managed]["managed"], msg=managed)
        self.assertTrue(all(p["managed"] for p in data["products"] if p["id"] != "studio"),
                        "矩阵已无 planned 产品：门户自身除外，任何残留 planned 都是登记错误")
        # kind 字段：浏览器产品一律 web；board 是桌面窗口应用（8023 是探活行协议口
        # 而非 HTTP，门户曾给它的卡片渲染"打开产品"导致 ERR_INVALID_HTTP_RESPONSE）
        self.assertTrue(all(p["kind"] == "web" for p in data["products"]
                            if p["id"] != "board"), "浏览器产品缺 kind=web")
        self.assertEqual(by_id["board"]["kind"], "desktop")

    def test_board_is_desktop_kind(self):
        status, _, body = self.handle("GET", "/api/products/board/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["kind"], "desktop")

    def test_status_and_unknown_product(self):
        status, _, body = self.handle("GET", "/api/products/linkbox/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["port"], LINKBOX_PORT)
        status, _, _ = self.handle("GET", "/api/products/nope/status")
        self.assertEqual(status, 404)

    def test_history_api_over_app(self):
        status, _, body = self.handle("GET", "/api/history")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("linkbox", data["products"])
        self.assertIsInstance(data["samples"], list)   # 未登录也可读（只读公开）

    def test_courselab_lifecycle(self):
        """CourseLab 并入：第八个 managed 产品（并行会话交付 M0-M11 后的收官接入）。
        原「已规划 start 400」用例随 planned 清零退场——该 API 分支保留给未来登记。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/courselab/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/courselab/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/courselab/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_index_and_static_served(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Studio".encode(), body)
        status, headers, body = self.handle("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/javascript; charset=utf-8")

    # ------------------------------------------------ 启停鉴权 + 真启停链路
    def test_start_stop_requires_login(self):
        status, _, body = self.handle("POST", "/api/products/linkbox/start")
        self.assertEqual(status, 401)        # 未登录：目录可看，开关不给你摸
        self.assertIn("登录", body.decode("utf-8"))

    def test_start_stop_linkbox_lifecycle(self):
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/linkbox/start", cookie)
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["online"], "启动后探活必须在线")
        self.assertIsNotNone(data["pid"])
        status, _, _ = self.authed("POST", "/api/products/linkbox/start", cookie)
        self.assertEqual(status, 409)
        status, _, body = self.authed("POST", "/api/products/linkbox/stop", cookie)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/linkbox/stop", cookie)
        self.assertEqual(status, 200)        # 幂等

    def test_stop_online_but_not_ours_409(self):
        """在线但没有门户的进程句柄：不许 stop（可能不是门户启的）。"""
        cookie = self.login()
        self.authed("POST", "/api/products/linkbox/start", cookie)
        orphan = self.manager.procs.pop("linkbox")   # 假装门户忘了它
        try:
            status, _, body = self.authed("POST", "/api/products/linkbox/stop",
                                          cookie)
            self.assertEqual(status, 409)
            self.assertIn("不是本门户", body.decode("utf-8"))
        finally:
            orphan.terminate()                        # 测试自清理：句柄还在手里
            orphan.wait(timeout=5)
        self.assertFalse(self.manager.probe(LINKBOX_PORT))

    def test_lab_lifecycle(self):
        """实验台并入：真起 showcase/lab.py 子进程 → 探活 → 停止。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/lab/start", cookie)
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertTrue(data["online"], "lab 启动后必须在线（端口探活）")
        status, _, _ = self.authed("POST", "/api/products/lab/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/lab/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_simlab_lifecycle(self):
        """SimLab 播放器并入：managed 模式泛化到第三个产品。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/simlab/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/simlab/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/simlab/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_datascope_lifecycle(self):
        """DataScope 并入：managed 模式泛化到第四个产品。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/datascope/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/datascope/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/datascope/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_cachekv_lifecycle(self):
        """CacheKV 并入：managed 模式泛化到第五个产品。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/cachekv/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/cachekv/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/cachekv/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_sensorhub_lifecycle(self):
        """SensorHub 并入：managed 模式泛化到第六个产品。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/sensorhub/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/sensorhub/stop", cookie)
        self.assertEqual(status, 200)
        status, _, body = self.authed("GET", "/api/products/sensorhub/status", cookie)
        self.assertFalse(json.loads(body)["online"])

    def test_board_lifecycle(self):
        """画板并入：第七个 managed 产品。契约差异（如实声明）：stop 终止的是
        launch.py 启动器，java 守护靠父进程看门狗秒级跟进退出——所以离线断言
        带 8s 截止时间轮询（这也顺带验证看门狗真的把进程收干净了）。"""
        cookie = self.login()
        status, _, body = self.authed("POST", "/api/products/board/start", cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["online"])
        status, _, _ = self.authed("POST", "/api/products/board/stop", cookie)
        self.assertEqual(status, 200)
        deadline = time.time() + 8
        body = b'{"online": true}'
        while time.time() < deadline:
            status, _, body = self.authed("GET", "/api/products/board/status", cookie)
            if not json.loads(body)["online"]:
                break
            time.sleep(0.2)
        else:
            self.fail("board stop 后 8s 探活仍在线（看门狗没收干净）")
        status, _, body = self.authed("POST", "/api/products/board/stop", cookie)
        self.assertFalse(json.loads(body)["online"])

    # ------------------------------------------------ M2 操作审计（2026-10-07）
    def test_audit_api_gate_and_empty(self):
        """M2：审计读取要登录（401）；本用例的 manager 没挂账本 → 空账也 200。"""
        status, _, _ = self.handle("GET", "/api/audit")
        self.assertEqual(status, 401)
        cookie = self.login()
        status, _, body = self.authed("GET", "/api/audit", cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"events": []})


class TestAudit(unittest.TestCase):
    """M2 操作审计：启停（含拒绝）如实入账、幂等空操作不记、落盘重启仍在。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port(18198)
        cls.manager = build_manager(linkbox_port=cls.port,
                                    lab_port=_free_port(18188),
                                    simlab_port=_free_port(18218),
                                    datascope_port=_free_port(18228),
                                    cachekv_port=_free_port(18238),
                                    sensorhub_port=_free_port(18249),
                                    board_port=_free_port(18259),
                                    courselab_port=_free_port(18269),
                                    boardweb_port=_free_port(18279),
                                    linkbox_memory=True,
                                    audit_path=Path(cls._tmp.name) / "audit.sqlite3")

    @classmethod
    def tearDownClass(cls):
        if cls.manager.audit is not None:
            cls.manager.audit.close()            # Windows：连接不关，临时目录删不掉
        cls._tmp.cleanup()

    def test_lifecycle_writes_audit(self):
        m = self.manager
        with self.assertRaises(ValueError):
            m.start("studio")                        # 已规划 → refused
        with self.assertRaises(AlreadyOnline):
            m.procs["linkbox"] = object()            # 伪造句柄 → refused
            m.start("linkbox")
        del m.procs["linkbox"]
        self.assertEqual(m.audit.count(), 2)
        m.start("linkbox")                           # 真启动 → ok
        m.stop("linkbox")                            # 真停止 → ok
        m.stop("linkbox")                            # 幂等空操作 → 不记账
        m.start("linkbox")                           # 再启动 → ok
        m.stop("linkbox")
        events = m.audit.tail(50)
        actions = [(e["action"], e["pid"], e["outcome"]) for e in events]
        self.assertIn(("start", "linkbox", "ok"), actions)
        self.assertIn(("stop", "linkbox", "ok"), actions)
        self.assertIn(("start", "studio", "refused"), actions)
        self.assertEqual(actions.count(("stop", "linkbox", "ok")), 2)
        # 幂等空操作没入账：stop 事件恰好 2 次（每次真停各 1）
        self.assertEqual([e["action"] for e in events].count("stop"), 2)
        # 落盘：换个 AuditLog 实例（模拟重启后）账还在
        from studio.audit import AuditLog
        reopened = AuditLog(Path(self._tmp.name) / "audit.sqlite3")
        self.assertGreaterEqual(reopened.count(), 6)
        reopened.close()

    def test_audit_connection_follows_using_thread(self):
        """跨线程回归（2026-10-08 浏览器走查抓出）：构造在主线程、使用在别的线程
        （webframe 事件循环形态）——惰性连接跟首用线程走，不再 ProgrammingError。"""
        import threading
        from studio.audit import AuditLog
        path = Path(self._tmp.name) / "threaded.sqlite3"
        log = AuditLog(path)                       # 主线程只构造，不触发连接
        box = {}

        def worker():
            try:
                log.record("start", "linkbox", "ok", "来自事件循环线程")
                box["rows"] = log.tail(10)
            except Exception as exc:               # 旧实现在这里抛 ProgrammingError
                box["error"] = exc

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        self.assertNotIn("error", box, f"跨线程使用失败：{box.get('error')}")
        self.assertEqual(box["rows"][0]["outcome"], "ok")
        self.assertEqual(log.count(), 1)           # 同一连接再从构造线程读（惰性后单归属）
        log.close()


class TestUptimeMonitor(unittest.TestCase):
    """探活历史采样器：可注入时钟 + 公开 sample_once（测试不 sleep）。"""

    def _manager(self):
        m = build_manager(linkbox_port=LINKBOX_PORT, lab_port=LAB_PORT,
                          simlab_port=SIMLAB_PORT, datascope_port=DATASCOPE_PORT,
                          cachekv_port=CACHEKV_PORT, sensorhub_port=SENSORHUB_PORT,
                          board_port=BOARD_PORT, courselab_port=COURSELAB_PORT,
                          linkbox_memory=True)
        return m

    def test_samples_probe_and_encode_bitmask(self):
        from studio.monitor import UptimeMonitor
        t = [1000.0]
        m = self._manager()
        mon = UptimeMonitor(m, clock=lambda: t[0])
        # lab 端口起一个真 HTTP 监听 → 在线；linkbox 端口空着 → 离线
        srv = socket.socket()
        srv.bind(("127.0.0.1", LAB_PORT))
        srv.listen(1)
        try:
            mon.sample_once()
            t[0] += 10.0
            srv.close()                       # 第二轮 lab 掉线
            mon.sample_once()
        finally:
            srv.close()
        h = mon.history()
        self.assertEqual(h["interval"], 10.0)
        self.assertEqual(len(h["samples"]), 2)
        self.assertNotIn("studio", h["products"])      # 本体不采样
        lab_i = h["products"].index("lab")
        link_i = h["products"].index("linkbox")
        s1, s2 = h["samples"]
        self.assertEqual((s1[1] >> lab_i) & 1, 1)      # 第一轮 lab 在线
        self.assertEqual((s1[1] >> link_i) & 1, 0)     # linkbox 空端口离线
        self.assertEqual((s2[1] >> lab_i) & 1, 0)      # 第二轮 lab 掉线
        self.assertEqual(s1[0], 1000.0)                # 注入时钟生效

    def test_ring_buffer_trims_to_capacity(self):
        from studio.monitor import UptimeMonitor
        t = [0.0]
        m = self._manager()
        mon = UptimeMonitor(m, max_samples=5, clock=lambda: t[0])
        for _ in range(8):
            mon.sample_once()
            t[0] += 10.0
        h = mon.history()
        self.assertEqual(len(h["samples"]), 5)         # 只留最近 5 条
        self.assertEqual(h["samples"][0][0], 30.0)     # 0/10/20 被裁掉
        self.assertEqual(h["samples"][-1][0], 70.0)


class TestOverRealSocket(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.auth = Auth(cls._tmp.name)
        cls.manager = build_manager(linkbox_port=18099, lab_port=17789,
                                    simlab_port=18019, datascope_port=18029,
                                    cachekv_port=18039, sensorhub_port=18048,
                                    board_port=18058, courselab_port=18068,
                                    linkbox_memory=True)
        from webframe import MicroServer
        cls.server = MicroServer(build_app(cls.manager, cls.auth), port=0)
        cls.port = cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls._tmp.cleanup()

    def test_products_and_me_over_socket(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/products")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read())
        self.assertIn("lab", [p["id"] for p in data["products"]])
        self.assertIsNone(data["portal"]["user"])    # 未登录
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"Studio", resp.read())
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
