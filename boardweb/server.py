"""boardweb/server.py —— 画板 Web 版（用户 2026-10-07："画板要内嵌网页、要图形
工具/微调/贴图"；2026-10-11 加协同：/ws/board 实时广播笔画）。

API：
    GET  /                       画板页（HTML5 Canvas；静态资产在 /static）
    GET  /api/doc                读当前文档 {version, shapes}
    PUT  /api/doc                保存文档（原子写 + 轮转备份 keep=10）
    POST /api/img?name=          上传贴图（原始字节 ≤8MiB，png/jpg/jpeg/gif/webp）
    GET  /img/<file>             读贴图（文件名白名单，防穿越）
    GET  /api/backups            备份清单（文件名 + 时间）
    WS   /ws/board               协同通道：add/clear 增量广播，undo/删除/微调等
                                 结构性变更走全量 sync；服务端不回显发送方；
                                 peers 计数进出都推。单线程事件循环，hub 免锁。
只绑回环。存储：data/doc.json + data/backups/ + data/img/。
协同与持久化的边界：实时层只管"别人画的我看得见"，落盘仍是各端自动保存
（last-save-wins + version 单调），不引入 OT/CRDT——课设口径的如实简化。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

from webframe import HttpFail, MicroApp, MicroServer, Response  # noqa: E402

WEB_ROOT = ROOT / "web"
DEFAULT_PORT = 8025                # 8023 桌面版探活 / 8024 courselab
DATA_DIR = ROOT / "data"
DOC_PATH = DATA_DIR / "doc.json"
BACKUPS_DIR = DATA_DIR / "backups"
IMG_DIR = DATA_DIR / "img"
DOC_MAX_BYTES = 4 * 1024 * 1024    # 文档上限 4MiB
IMG_MAX_BYTES = 8 * 1024 * 1024    # 贴图上限 8MiB
KEEP_BACKUPS = 10
IMG_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
           "gif": "image/gif", "webp": "image/webp"}
_FILE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(png|jpg|jpeg|gif|webp)$")


def _save_doc_atomic(text: str) -> None:
    """文档原子写 + 轮转备份（本产品的备份承诺：保存即留底，keep=10）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if DOC_PATH.is_file():
        # 秒级时戳在同秒连存会同名互覆（测试实抓）——掺随机尾缀保证一份不丢
        stamp = (time.strftime("%Y%m%d-%H%M%S")
                 + "-" + os.urandom(2).hex())
        (BACKUPS_DIR / f"doc-{stamp}.json").write_text(
            DOC_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        backups = sorted(BACKUPS_DIR.glob("doc-*.json"))
        for old in backups[:max(0, len(backups) - KEEP_BACKUPS)]:
            old.unlink()
    tmp = DOC_PATH.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, DOC_PATH)


def build_app(data_dir: Path | None = None) -> MicroApp:
    global DOC_PATH, BACKUPS_DIR, IMG_DIR
    if data_dir is not None:
        data_dir = Path(data_dir)
        DOC_PATH = data_dir / "doc.json"
        BACKUPS_DIR = data_dir / "backups"
        IMG_DIR = data_dir / "img"
    app = MicroApp()

    @app.get("/")
    def index(ctx):
        return Response((WEB_ROOT / "index.html").read_bytes(),
                        content_type="text/html; charset=utf-8")

    app.static("/static", WEB_ROOT)

    @app.get("/api/doc")
    def doc_get(ctx):
        if not DOC_PATH.is_file():
            return ctx.json({"version": 0, "shapes": []})
        try:
            doc = json.loads(DOC_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise HttpFail(500, "文档损坏——可从 /api/backups 列出的备份恢复")
        return ctx.json(doc)

    @app.put("/api/doc")
    def doc_put(ctx):
        raw = ctx.request.body or b""
        if len(raw) > DOC_MAX_BYTES:
            raise HttpFail(413, f"文档超过 {DOC_MAX_BYTES // 1048576}MiB 上限")
        try:
            doc = json.loads(raw.decode("utf-8"))
            shapes = doc["shapes"]
            if not isinstance(shapes, list):
                raise KeyError("shapes")
        except (ValueError, KeyError, UnicodeDecodeError):
            raise HttpFail(400, "文档须为含 shapes 数组的 JSON")
        version = int(doc.get("version", 0)) + 1
        doc["version"] = version
        doc["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_doc_atomic(json.dumps(doc, ensure_ascii=False))
        return ctx.json({"ok": True, "version": version,
                         "saved_at": doc["saved_at"]})

    @app.get("/api/backups")
    def backups(ctx):
        names = sorted((p.name for p in BACKUPS_DIR.glob("doc-*.json")),
                       reverse=True) if BACKUPS_DIR.is_dir() else []
        return ctx.json({"backups": names, "keep": KEEP_BACKUPS})

    @app.post("/api/img")
    def img_upload(ctx):
        name = (ctx.query.get("name") or "paste.png").strip()
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
        if ext not in IMG_EXT:
            raise HttpFail(400, "只支持 png/jpg/jpeg/gif/webp 贴图")
        raw = ctx.request.body or b""
        if not raw:
            raise HttpFail(400, "贴图内容为空")
        if len(raw) > IMG_MAX_BYTES:
            raise HttpFail(413, f"贴图超过 {IMG_MAX_BYTES // 1048576}MiB 上限")
        img_id = base64.b64encode(os.urandom(9)).decode("ascii").replace("/", "x").replace("+", "y")
        fname = f"img-{img_id}.{ext}"
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        (IMG_DIR / fname).write_bytes(raw)
        return ctx.json({"ok": True, "id": img_id, "file": fname,
                         "url": f"/img/{fname}", "bytes": len(raw)}, status=201)

    @app.get("/img/<file>")
    def img_get(ctx):
        fname = ctx.params["file"]
        if not _FILE_RE.match(fname):
            raise HttpFail(404, "not found")
        path = (IMG_DIR / fname).resolve()
        if not path.is_file() or IMG_DIR.resolve() not in path.parents:
            raise HttpFail(404, "not found")
        return Response(path.read_bytes(), content_type=IMG_EXT[path.suffix[1:]],
                        headers=[("Cache-Control", "max-age=86400")])

    # ------------------------------------------------ 协同白板（/ws/board）
    # hub = 本 app 实例的活跃会话集。netlab 事件循环单线程跑全部 WS 回调，
    # 集合增删与广播天然串行，不需要锁。
    peers: set = set()

    def broadcast(text: str, skip=None) -> None:
        for s in list(peers):
            if s is skip or s.closing:
                continue
            s.send(text)

    def peers_msg() -> str:
        return json.dumps({"type": "peers", "peers": len(peers)},
                          ensure_ascii=False)

    @app.ws("/ws/board")
    def ws_board(session):
        peers.add(session)
        session.send(json.dumps({"type": "hello", "peers": len(peers)},
                                ensure_ascii=False))
        broadcast(peers_msg(), skip=session)

        def on_message(text):
            try:
                msg = json.loads(text)
                kind = msg["type"]
            except (ValueError, KeyError, TypeError):
                session.send('{"type":"error","error":"消息须为含 type 的 JSON"}')
                return
            if kind == "add":
                shape = msg.get("shape")
                if not isinstance(shape, dict):
                    session.send('{"type":"error","error":"add 须带 shape 对象"}')
                    return
                broadcast(json.dumps({"type": "add", "shape": shape},
                                     ensure_ascii=False), skip=session)
            elif kind == "clear":
                broadcast('{"type":"clear"}', skip=session)
            elif kind == "sync":
                shapes = msg.get("shapes")
                if not isinstance(shapes, list):
                    session.send('{"type":"error","error":"sync 须带 shapes 数组"}')
                    return
                payload = json.dumps({"type": "sync", "shapes": shapes},
                                     ensure_ascii=False)
                # 单帧上限 64KiB（netlab），留余量；超限如实报错，保存通道不受影响
                if len(payload.encode("utf-8")) > 56 * 1024:
                    session.send('{"type":"error",'
                                 '"error":"画板内容过大，协同同步失败（保存不受影响）"}')
                    return
                broadcast(payload, skip=session)
            elif kind == "ping":
                session.send('{"type":"pong"}')
            else:
                session.send(json.dumps(
                    {"type": "error", "error": f"未知类型 {kind!r}"},
                    ensure_ascii=False))

        def on_close():
            peers.discard(session)
            broadcast(peers_msg())

        session.on_message = on_message
        session.on_close = on_close

    return app


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="画板 Web 版（只绑回环）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = MicroServer(build_app(), host=args.host, port=args.port)
    port = server.start()
    print(f"画板 Web 版已启动：http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见")
    return 0


if __name__ == "__main__":
    import threading
    raise SystemExit(main())
