"""simlab/server.py —— SimLab 播放器服务（轮三之二）：跑在自研 webframe 上。

三件事：
    1. 记录库：runs/ 目录下的 simlab-run/v1 记录——列表（元数据）、读取、
       现算落盘（引擎现算 + simlab 校验器先验，自家格式自家把关）；
    2. 播放器页面：帧回放（播放/步进/拖动），三种实验各有渲染器；
    3. 静态资产：/static/*（webframe 的守卫管线）。
只绑回环；记录名白名单 + resolve 双保险，穿越进不了 runs/ 之外的地方。
"""
from __future__ import annotations

import re
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

import simlab                                                 # noqa: E402
from webframe import HttpFail, MicroApp, MicroServer, Response  # noqa: E402

WEB_ROOT = ROOT / "web"
RUNS_DIR = ROOT / "runs"
DEFAULT_PORT = 8019                # 8017 studio / 8018 linkbox / 8020 datascope
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")


def build_app(*, runs_dir: Path | None = None) -> MicroApp:
    runs = Path(runs_dir) if runs_dir else RUNS_DIR

    def _record_path(name: str) -> Path:
        if not _NAME_RE.match(name):
            raise HttpFail(400, f"记录名 {name!r} 不合法（只允许字母数字._-，.json 结尾）")
        path = (runs / name).resolve()
        if not path.is_relative_to(runs.resolve()):
            raise HttpFail(400, "记录名不许走出 runs/ 目录")
        return path

    def ensure_dir() -> None:
        runs.mkdir(parents=True, exist_ok=True)

    app = MicroApp()

    @app.get("/api/records")
    def list_records(ctx):
        ensure_dir()
        items = []
        for path in sorted(runs.glob("*.json")):
            try:
                record = simlab.load(path)
            except simlab.RecordError as exc:     # 坏记录如实标注，不悄悄藏起来
                items.append({"name": path.name, "invalid": True,
                              "error": str(exc)})
                continue
            items.append({"name": path.name, "invalid": False,
                          "experiment": record["experiment"],
                          "title": record["title"],
                          "frames": len(record["frames"]),
                          "created_at": record.get("created_at")})
        return ctx.json({"records": items, "experiments": sorted(simlab.ENGINES)})

    @app.get("/api/records/<name>")
    def read_record(ctx):
        path = _record_path(ctx.params["name"])
        if not path.is_file():
            raise HttpFail(404, f"记录 {ctx.params['name']!r} 不存在")
        try:
            return ctx.json(simlab.load(path))
        except simlab.RecordError as exc:
            raise HttpFail(422, f"记录损坏：{exc}") from None

    @app.post("/api/records")
    def render_record(ctx):
        """现算一份记录并落盘：引擎现算（毫秒级）+ simlab 校验器先验。"""
        body = ctx.json_body({"experiment": (str, True), "params": (dict, True)})
        record = _render_validated(body["experiment"], body["params"])
        ensure_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # 秒级时间戳会同秒碰撞（后写覆盖先写）：掺 2 字节随机后缀
        name = f"{record['experiment']}-{stamp}-{secrets.token_hex(2)}.json"
        save = simlab.save(record, _record_path(name))
        return ctx.json({"name": save.name, **record}, status=201)

    @app.get("/api/params/<experiment>")
    def params_schema(ctx):
        """参数表单描述（类型/默认值/说明）：前端据此生成可调参数表单。"""
        experiment = ctx.params["experiment"]
        if experiment not in simlab.ENGINES:
            raise HttpFail(404, f"未知实验 {experiment!r}，可用：{sorted(simlab.ENGINES)}")
        return ctx.json({"experiment": experiment,
                         "schema": simlab.param_schema(experiment)})

    @app.post("/api/render")
    def render_live(ctx):
        """轮三之三：参数可调实时重算——现算返回记录但**不落盘**（runs/ 零垃圾）。"""
        body = ctx.json_body({"experiment": (str, True), "params": (dict, True)})
        record = _render_validated(body["experiment"], body["params"])
        return ctx.json(record)

    def _render_validated(experiment: str, params: dict) -> dict:
        if experiment not in simlab.ENGINES:
            raise HttpFail(400, f"未知实验 {experiment!r}，"
                                f"可用：{sorted(simlab.ENGINES)}")
        try:
            skeleton = simlab.run_experiment(experiment, params)
        except ValueError as exc:                 # 引擎守卫（负权/越界/形状错）
            raise HttpFail(400, str(exc)) from None
        try:
            return simlab.build(experiment=skeleton["experiment"],
                                title=skeleton["title"],
                                engine=skeleton["engine"],
                                params=skeleton["params"],
                                frames=skeleton["frames"],
                                metrics=skeleton["metrics"],
                                notes=skeleton.get("notes", ""))
        except simlab.RecordError as exc:
            raise HttpFail(500, f"适配器产出了不合法的记录：{exc}") from None

    @app.get("/")
    def index(ctx):
        page = (WEB_ROOT / "index.html").read_bytes()
        return Response(page, content_type="text/html; charset=utf-8")

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 runs_dir: str | Path | None = None) -> MicroServer:
    return MicroServer(build_app(runs_dir=Path(runs_dir) if runs_dir else None),
                       host=host, port=port)


def main(argv=None) -> int:
    import argparse
    import threading
    ap = argparse.ArgumentParser(description="SimLab 播放器（只绑回环）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = build_server(host=args.host, port=args.port)
    port = server.start()
    print(f"SimLab 播放器已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"记录目录： {RUNS_DIR}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见")
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
