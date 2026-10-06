"""cachekv/server.py —— CacheKV 服务（轮五之一）：跑在自研 webframe 上。

API（键与值都是文本；TTL 用查询串）：
    PUT    /api/kv/<key>?ttl=秒    写入（体为值；ttl 可选）→ 201/200
    GET    /api/kv/<key>           读取（未命中/已过期 → 404）
    DELETE /api/kv/<key>           删除（删了 204；本来没有 404）
    GET    /api/keys               存活键列表
    GET    /api/stats              统计（命中/未命中/键数/快照数）
    POST   /api/save               手动快照
    GET    /                       统计页（自刷新）
只绑回环。快照：启动载入 + 定时（脏了才写）+ 停止时保存。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

from webframe import HttpFail, MicroApp, MicroServer, Response  # noqa: E402

from cachekv import CacheKV, SnapshotSaver                     # noqa: E402

WEB_ROOT = ROOT / "web"
DATA_DIR = ROOT / "data"
DEFAULT_PORT = 8021               # 8017 studio / 8018 linkbox / 8019 simlab / 8020 datascope
_KEY_RE_MAX = 200                 # 键长度上限
_STARTED_AT = None                # 进程启动时刻（/api/overview 提供 uptime，轮九）


class CacheKVServer(MicroServer):
    """停机时刷快照：主动保存是产品的承诺，不能指望用户先按保存。"""

    def stop(self) -> None:
        saver = getattr(self, "saver", None)
        if saver is not None:
            saver.stop()
        engine = getattr(self, "engine", None)
        if engine is not None and engine.snapshot_path is not None:
            try:
                engine.save()
            except Exception:
                pass                        # 停机路径不许被快照异常卡住
        super().stop()


def build_app(engine: CacheKV) -> MicroApp:
    app = MicroApp()

    def key_of(ctx) -> bytes:
        name = ctx.params["key"]
        if not name or len(name) > _KEY_RE_MAX:
            raise HttpFail(400, f"键长度须在 1..{_KEY_RE_MAX}")
        return name.encode("utf-8")

    @app.put("/api/kv/<key>")
    def put_value(ctx):
        key = key_of(ctx)
        ttl = ctx.query.get("ttl")
        engine.cmd_set(key, ctx.request.body)
        if ttl is not None:
            try:
                seconds = int(ttl)
            except ValueError:
                raise HttpFail(400, "ttl 要写成整数秒") from None
            if seconds <= 0:
                raise HttpFail(400, "ttl 必须是正整数秒")
            if engine.cmd_expire(key, seconds) != 1:
                raise HttpFail(404, "键在设置过期前消失了")
        return ctx.text("OK", status=201 if ctx.request.body else 200)

    @app.get("/api/kv/<key>")
    def get_value(ctx):
        key = key_of(ctx)
        value = engine.cmd_get(key)
        if value is None:
            raise HttpFail(404, f"键 {ctx.params['key']!r} 不存在或已过期")
        return Response(value, content_type="text/plain; charset=utf-8",
                        headers=[("Cache-Control", "no-store")])

    @app.delete("/api/kv/<key>")
    def delete_value(ctx):
        key = key_of(ctx)
        removed = engine.cmd_del([key])
        if not removed:
            raise HttpFail(404, f"键 {ctx.params['key']!r} 不存在")
        return Response(b"", status=204, content_type=None)

    @app.get("/api/keys")
    def keys(ctx):
        return ctx.json({"keys": [key.decode("utf-8", "replace")
                                  for key, _, _ in engine.export_state()
                                  if not engine._check_expired(key)]})

    @app.get("/api/overview")
    def overview(ctx):
        """仪表盘聚合口（轮九）：存活键明细（大小/TTL）+ 统计 + 快照状态 + 运行时长，一次拉全。
        键明细与 TTL 由引擎 overview() 现算（用引擎自己的时钟）。"""
        import time
        payload = engine.overview()
        payload["snapshot"] = {"path": str(engine.snapshot_path)
                               if engine.snapshot_path else None,
                               "dirty": engine.dirty}
        payload["started_at"] = _STARTED_AT
        payload["uptime_sec"] = round(time.time() - _STARTED_AT, 1) if _STARTED_AT else None
        return ctx.json(payload)

    @app.post("/api/demo")
    def demo(ctx):
        """一键注入演示数据（轮九）：12 个键（混合 TTL）+ 制造命中/未命中账，
        让统计页打开就是"有数据、有图表、可演示"的状态。幂等：重复注入即覆盖。"""
        seeds = [
            ("app:theme", "dark", None),
            ("app:lang", "zh-CN", None),
            ("session:u1", "alice|127.0.0.1|2026-10-05T12:00", 1800),
            ("session:u2", "bob|192.168.1.7|2026-10-05T12:05", 3600),
            ("session:u3", "carol|10.0.0.9|2026-10-05T12:10", 600),
            ("cache:page:home", "<html>…渲染好的首页片段（3KB 模拟）…</html>", 300),
            ("cache:page:course", "<html>…课程列表片段…</html>", 120),
            ("cache:api:rank", '{"top":[{"pid":"B11","n":42},{"pid":"B31","n":35}]}', 60),
            ("config:max_labs", "2", None),
            ("config:session_hours", "12", None),
            ("queue:task:1001", "pending|stu_a|B11-net-lab#0", 900),
            ("note:todo", "给论文补第 5 章的压测对照表", None),
        ]
        for key, value, ttl in seeds:
            engine.cmd_set(key.encode("utf-8"), value.encode("utf-8"))
            if ttl is not None and engine.cmd_expire(key.encode("utf-8"), ttl) != 1:
                raise HttpFail(500, f"演示键 {key!r} 设置 TTL 失败")
        hits = misses = 0
        for key, _, _ in list(engine.export_state())[:8]:
            if engine.cmd_get(key) is not None:
                hits += 1
        for miss in ("demo:miss:a", "demo:miss:b", "demo:miss:c", "demo:miss:d"):
            if engine.cmd_get(miss.encode("utf-8")) is None:
                misses += 1
        return ctx.json({"seeded": len(seeds), "hits": hits, "misses": misses})

    @app.get("/api/stats")
    def stats(ctx):
        return ctx.json({"stats": engine.stats_view(),
                         "snapshot": str(engine.snapshot_path) if engine.snapshot_path else None,
                         "dirty": engine.dirty})

    @app.post("/api/save")
    def save_now(ctx):
        count = engine.save()
        return ctx.json({"saved": count})

    @app.get("/")
    def index(ctx):
        page = (WEB_ROOT / "index.html").read_bytes()
        return Response(page, content_type="text/html; charset=utf-8")

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = 8021,
                 data_dir: str | Path | None = None,
                 snapshot_interval: float = 60.0) -> tuple[CacheKVServer, CacheKV, SnapshotSaver]:
    global _STARTED_AT
    import time
    _STARTED_AT = time.time()
    data = Path(data_dir) if data_dir else DATA_DIR
    data.mkdir(parents=True, exist_ok=True)
    engine = CacheKV(snapshot_path=data / "snapshot.bin")
    loaded = engine.load()
    server = CacheKVServer(build_app(engine), host=host, port=port)
    saver = SnapshotSaver(engine, interval=snapshot_interval)
    server.engine = engine
    server.saver = saver
    server.loaded_keys = loaded
    return server, engine, saver


def main(argv=None) -> int:
    import argparse
    import threading
    ap = argparse.ArgumentParser(description="CacheKV 自托管键值缓存（只绑回环）")
    ap.add_argument("--port", type=int, default=8021)
    args = ap.parse_args(argv)
    server, engine, saver = build_server(port=args.port)
    port = server.start()
    saver.start()
    print(f"CacheKV 已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"快照： 启动载入 {server.loaded_keys} 键，每 {saver.interval:.0f}s 脏了才写 → "
          f"{engine.snapshot_path}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见（停止前保存快照）")
        saver.stop()
        engine.save()
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
