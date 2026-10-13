"""boardweb/tests/test_boardweb.py —— 画板 Web 版服务端自测（2026-10-07）。

口径：文档原子写 + 轮转备份 keep=10；贴图扩展名白名单 + 8MiB 上限 +
路径白名单防穿越；页面与静态资产可达。全部隔离目录，不碰 data/。
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
for p in (str(ROOT), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from boardweb.server import build_app  # noqa: E402

# 公开的 1x1 透明 PNG（基准常量，非手写字节）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class TestBoardWeb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="boardweb-test-")
        self.app = build_app(data_dir=Path(self.tmp))

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path.split("?")[0],
                      query=[tuple(p.split("=", 1)) if "=" in p else (p, "")
                             for p in path.split("?")[1].split("&")] if "?" in path else [],
                      keep_alive=False, content_length=len(body))
        return self.app.handle(req)

    def test_doc_roundtrip_and_version(self):
        status, _, body = self.handle("GET", "/api/doc")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["shapes"], [])
        shapes = [{"type": "rect", "x": 1, "y": 2, "w": 3, "h": 4,
                   "color": "#171717", "width": 4}]
        status, _, body = self.handle(
            "PUT", "/api/doc", json.dumps({"shapes": shapes}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["version"], 1)
        status, _, body = self.handle("GET", "/api/doc")
        self.assertEqual(json.loads(body)["shapes"], shapes)

    def test_doc_graphic_library_roundtrip(self):
        """轮三十七图形库：arrow/triangle/diamond/text/sticky 五类新形状
        逐字段持久化往返（服务端不校验 shape 内部结构——前端契约，测试钉形状）。"""
        shapes = [
            {"type": "arrow", "x1": 10, "y1": 10, "x2": 90, "y2": 60,
             "color": "#171717", "width": 4},
            {"type": "triangle", "x": 5, "y": 5, "w": 40, "h": 30,
             "color": "#f00", "width": 2},
            {"type": "diamond", "x": 120, "y": 8, "w": 60, "h": 36,
             "color": "#2563eb", "width": 2},
            {"type": "text", "x": 200, "y": 15, "text": "标注：Raft 复制",
             "w": 96, "h": 24, "color": "#171717", "width": 18},
            {"type": "sticky", "x": 30, "y": 200, "text": "待办：补图",
             "w": 160, "h": 100, "color": "#171717", "width": 14},
        ]
        status, _, body = self.handle(
            "PUT", "/api/doc", json.dumps({"shapes": shapes}).encode(),
            [("Content-Type", "application/json")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["version"], 1)
        status, _, body = self.handle("GET", "/api/doc")
        self.assertEqual(json.loads(body)["shapes"], shapes)   # 逐字段一致
        self.assertEqual({s["type"] for s in json.loads(body)["shapes"]},
                         {"arrow", "triangle", "diamond", "text", "sticky"})

    def test_doc_bad_body_400(self):
        status, _, _ = self.handle("PUT", "/api/doc", b"not json",
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 400)
        status, _, _ = self.handle("PUT", "/api/doc",
                                   json.dumps({"no": "shapes"}).encode(),
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 400)

    def test_backup_rotation_keep10(self):
        for i in range(13):
            self.handle("PUT", "/api/doc",
                        json.dumps({"shapes": [{"i": i}]}).encode(),
                        [("Content-Type", "application/json")])
        status, _, body = self.handle("GET", "/api/backups")
        data = json.loads(body)
        self.assertEqual(data["keep"], 10)
        self.assertEqual(len(data["backups"]), 10)   # 轮转：只留最近 10 份

    def test_img_upload_and_fetch(self):
        png = {"name": "paste.png"}
        status, _, body = self.handle(
            "POST", "/api/img?name=" + png["name"], PNG_1PX,
            [("Content-Type", "application/octet-stream")])
        self.assertEqual(status, 201)
        url = json.loads(body)["url"]
        status, _, got = self.handle("GET", url)
        self.assertEqual(status, 200)
        self.assertEqual(got, PNG_1PX)

    def test_img_rejects_bad_ext_and_oversize(self):
        status, _, _ = self.handle("POST", "/api/img?name=x.exe", b"MZ")
        self.assertEqual(status, 400)
        status, _, _ = self.handle("POST", "/api/img?name=big.png", b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(status, 413)

    def test_img_path_traversal_blocked(self):
        status, _, _ = self.handle("GET", "/img/..%2f..%2fdoc.json")
        self.assertIn(status, (400, 404))
        status, _, _ = self.handle("GET", "/img/ghost.png")
        self.assertEqual(status, 404)

    def test_doc_too_big_413(self):
        big = json.dumps({"shapes": [{"pad": "x" * 1024}] * 5000}).encode()
        status, _, _ = self.handle("PUT", "/api/doc", big,
                                   [("Content-Type", "application/json")])
        self.assertEqual(status, 413)

    def test_index_page(self):
        status, _, body = self.handle("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"board", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
