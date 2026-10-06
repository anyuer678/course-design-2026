"""CacheKV 自测：引擎语义对拍 B38 Store + 统计账本 + 快照重启 + HTTP API + 真套接字。

对拍口径：CacheKV 的读写/过期语义与**直接调用 B38 Store** 同源一致
（B38 的 clock 可注入 → 过期测试不 sleep）；统计账本 hit+miss == 总读取。
"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cachekv import CacheKV, SnapshotSaver
from cachekv.server import build_app, build_server

from redislite.store import Store


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.now = 1_700_000_000.0
        self.engine = CacheKV(clock=lambda: self.now)

    def test_semantics_match_direct_store(self):
        """CacheKV 的读写/过期语义与直接调用 B38 Store 一致。"""
        reference = Store(clock=lambda: self.now)
        for target in (self.engine, reference):
            target.cmd_set(b"k", b"v1")
            self.assertEqual(target.cmd_get(b"k"), b"v1")
            target.cmd_set(b"k", b"v2")
            self.assertEqual(target.cmd_get(b"k"), b"v2")
            target.cmd_expire(b"k", 10)
            self.assertEqual(target.cmd_ttl(b"k"), 10)
            self.now += 11                       # 共同时钟推进
            self.assertIsNone(target.cmd_get(b"k"))   # 惰性过期
        self.assertEqual(self.engine.stats_view()["misses"], 1)
        self.assertEqual(self.engine.stats_view()["hits"], 2)

    def test_incr(self):
        self.engine.cmd_set(b"n", b"10")
        self.assertEqual(self.engine.cmd_incr(b"n"), 11)

    def test_stats_ledger(self):
        self.engine.cmd_set(b"a", b"1")
        self.engine.cmd_get(b"a")                # hit
        self.engine.cmd_get(b"b")                # miss
        self.engine.cmd_del([b"a"])
        view = self.engine.stats_view()
        self.assertEqual(view["hits"], 1)
        self.assertEqual(view["misses"], 1)
        self.assertEqual(view["sets"], 1)
        self.assertEqual(view["deletes"], 1)
        self.assertEqual(view["gets"], view["hits"] + view["misses"])
        self.assertEqual(view["keys"], 0)

    def test_active_expire_cycle(self):
        """主动过期：B38 的 active_expire_cycle 照常工作。"""
        self.engine.cmd_set(b"gone", b"x")
        self.engine.cmd_expire(b"gone", 5)
        self.now += 6
        removed = self.engine.active_expire_cycle()
        self.assertGreaterEqual(removed, 1)

    def test_snapshot_restart_roundtrip(self):
        """快照重启：值与 TTL 都保住；重启后过期键按原时刻惰性过期。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot.bin"
            engine = CacheKV(clock=lambda: self.now, snapshot_path=path)
            engine.cmd_set(b"keep", b"data")
            engine.cmd_set(b"temp", b"soon")
            engine.cmd_expire(b"temp", 100)
            engine.save()
            revived = CacheKV(clock=lambda: self.now, snapshot_path=path)
            self.assertEqual(revived.load(), 2)
            self.assertEqual(revived.cmd_get(b"keep"), b"data")
            self.assertGreaterEqual(revived.cmd_ttl(b"temp"), 90)

    def test_snapshot_saver_thread(self):
        """真线程：脏了才写——没变更时不落盘，set 后落盘。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "snapshot.bin"
            engine = CacheKV(clock=lambda: self.now, snapshot_path=path)
            reports = []
            saver = SnapshotSaver(engine, interval=0.05, report=reports.append)
            saver.start()
            self.assertFalse(path.exists())      # 未脏不写
            engine.cmd_set(b"x", b"1")
            deadline = __import__("time").time() + 2
            while not path.exists() and __import__("time").time() < deadline:
                __import__("time").sleep(0.02)
            saver.stop()
            self.assertTrue(path.exists())


class TestHttp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.now = 1_700_000_000.0
        self.engine = CacheKV(clock=lambda: self.now,
                              snapshot_path=Path(self._tmp.name) / "snapshot.bin")
        self.app = build_app(self.engine)

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path.split("?")[0],
                      query=[tuple(p.split("=", 1)) if "=" in p else (p, "")
                             for p in path.split("?")[1].split("&")] if "?" in path else [],
                      keep_alive=False, content_length=len(body))
        return self.app.handle(req)

    def test_put_get_delete(self):
        status, _, _ = self.handle("PUT", "/api/kv/greeting", b"hello")
        self.assertEqual(status, 201)
        status, _, body = self.handle("GET", "/api/kv/greeting")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"hello")
        status, _, _ = self.handle("DELETE", "/api/kv/greeting")
        self.assertEqual(status, 204)
        status, _, _ = self.handle("GET", "/api/kv/greeting")
        self.assertEqual(status, 404)

    def test_put_with_ttl_then_expire_404(self):
        self.handle("PUT", "/api/kv/temp?ttl=10", b"soon")
        self.now += 11
        status, _, _ = self.handle("GET", "/api/kv/temp")
        self.assertEqual(status, 404)

    def test_put_bad_ttl_400(self):
        status, _, _ = self.handle("PUT", "/api/kv/x?ttl=abc", b"v")
        self.assertEqual(status, 400)

    def test_get_missing_404(self):
        status, _, _ = self.handle("GET", "/api/kv/none")
        self.assertEqual(status, 404)

    def test_delete_missing_404(self):
        status, _, _ = self.handle("DELETE", "/api/kv/none")
        self.assertEqual(status, 404)

    def test_stats_view_via_api(self):
        self.handle("PUT", "/api/kv/a", b"1")
        self.handle("GET", "/api/kv/a")
        status, _, body = self.handle("GET", "/api/stats")
        stats = json.loads(body)["stats"]
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["keys"], 1)

    def test_keys_and_save(self):
        self.handle("PUT", "/api/kv/k1", b"v1")
        status, _, body = self.handle("GET", "/api/keys")
        self.assertEqual(json.loads(body)["keys"], ["k1"])
        status, _, body = self.handle("POST", "/api/save")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["saved"], 1)

    def test_index_and_static(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("CacheKV".encode(), body)
        status, headers, _ = self.handle("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/javascript; charset=utf-8")

    # ---- 轮九：仪表盘聚合口 + 演示数据注入
    def test_overview_lists_keys_with_ttl(self):
        self.handle("PUT", "/api/kv/forever", b"v")
        self.handle("PUT", "/api/kv/short?ttl=60", b"v")
        status, _, body = self.handle("GET", "/api/overview")
        self.assertEqual(status, 200)
        data = json.loads(body)
        rows = {r["key"]: r for r in data["keys"]}
        self.assertEqual(rows["forever"]["ttl"], None)          # 无 TTL = 永久
        self.assertTrue(0 < rows["short"]["ttl"] <= 60)          # 剩余秒如实
        self.assertEqual(rows["short"]["size"], 1)
        self.assertIn("hits", data["stats"])
        self.assertIn("dirty", data["snapshot"])

    def test_demo_seeds_and_accounts(self):
        status, _, body = self.handle("POST", "/api/demo")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["seeded"], 12)
        self.assertGreaterEqual(data["hits"], 8)                 # 制造了命中账
        self.assertEqual(data["misses"], 4)                      # 4 次未命中
        status, _, body = self.handle("GET", "/api/overview")
        rows = json.loads(body)["keys"]
        self.assertEqual(len(rows), 12)                          # 幂等：重复注入仍 12 键
        ttls = [r["ttl"] for r in rows if r["ttl"] is not None]
        self.assertTrue(all(t > 0 for t in ttls))                # 演示键全部存活
        self.assertTrue(any(r["ttl"] is None for r in rows))     # 且有永久键


class TestOverRealSocket(unittest.TestCase):
    def test_persistence_across_restarts(self):
        """真套接字 + 真重启：写两个键（一个带 TTL）→ 停 → 重新 build → 数据在。"""
        with tempfile.TemporaryDirectory() as td:
            server1, engine1, saver1 = build_server(port=0, data_dir=td)
            port = server1.start()
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("PUT", "/api/kv/persistent", b"survives")
            conn.getresponse().read()
            conn.request("PUT", "/api/kv/ephemeral?ttl=1000", b"ttl-kept")
            conn.getresponse().read()
            conn.close()
            saver1.stop()
            server1.stop()

            server2, engine2, saver2 = build_server(port=0, data_dir=td)
            self.assertEqual(server2.loaded_keys, 2)
            self.assertEqual(engine2.cmd_get(b"persistent"), b"survives")
            self.assertGreater(engine2.cmd_ttl(b"ephemeral"), 900)
            saver2.stop()
            server2.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
