"""datascope/server.py —— DataScope 工作台服务（轮四之二）：跑在自研 webframe 上。

API：
    POST /api/profile   （text/csv 体）          → 列画像
    POST /api/clean     {csv, recipe}            → 清洗后 CSV + 账本报告
    POST /api/mine      {csv, task, params}      → B26 真引擎挖掘（Apriori/K-means）
    GET  /                                       → 简单工作台页（轮四（三）再做精致报告）
只绑回环。CSV 以文本进出——保持"CSV 只有文本"的本相，类型转换显式做。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO),):
    if p not in sys.path:
        sys.path.insert(0, p)

import datascope                                             # noqa: E402
from webframe import HttpFail, MicroApp, MicroServer, Response  # noqa: E402

from datascope.mining import apriori_from_rows, kmeans_from_rows  # noqa: E402

WEB_ROOT = ROOT / "web"
DEFAULT_PORT = 8020                # 8017 studio / 8018 linkbox / 8019 simlab
RECIPES_DIR = ROOT / "data" / "recipes"   # D1 清洗配方落盘（JSON，原子写）
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")

# 内置演示数据（轮九）：一份故意带脏的订单 CSV——重复行 / 数量缺失 / 金额含空格 /
# 备注列待删，任何一条基础配方都能在它上面演示出"清洗前 vs 清洗后"的差异。
SAMPLE_CSV = """订单号,商品,数量,金额,备注
1001,键盘,2,199.90,
1002,鼠标,1,59.50,促销
1003,键盘,2,199.90,
1004,显示器,1, 899.00 ,
1005,鼠标,1,59.50,促销
1006,鼠标,1,59.50,促销
1007,键盘, ,249.00,
1008,显示器,1,,换货
1009,数据线,3,19.90,
1010,键盘,2,199.90,
1011,鼠标,2,,促销
1012,显示器,1,899.00,
1013,数据线,5,19.90,清仓
1014,键盘,1, 249.00 ,
"""


def build_app(recipes_dir: Path | None = None) -> MicroApp:
    app = MicroApp()
    rdir = Path(recipes_dir) if recipes_dir else RECIPES_DIR

    def _recipe_path(name: str) -> Path:
        if not _NAME_RE.match(name or ""):
            raise HttpFail(400, "配方名只允许字母数字与 _-（1..40 字符）")
        return rdir / (name + ".json")

    # ---------------- D1 清洗配方：保存 / 列表 / 读取 / 删除（JSON 原子写）
    @app.get("/api/recipes")
    def recipes_list(ctx):
        names = sorted(p.stem for p in rdir.glob("*.json")) if rdir.is_dir() else []
        return ctx.json({"recipes": names})

    @app.post("/api/recipes")
    def recipes_save(ctx):
        payload = ctx.json_body({"name": (str, True), "steps": (list, True)})
        path = _recipe_path(payload["name"].strip())
        steps = payload["steps"]
        if not steps or len(steps) > 50:
            raise HttpFail(400, "steps 须为 1..50 条")
        for st in steps:
            if not isinstance(st, dict) or not isinstance(st.get("op"), str):
                raise HttpFail(400, "每个步骤须为含 op 的对象")
        rdir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"name": path.stem, "steps": steps},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)                 # 原子落盘（B10 的经验）
        return ctx.json({"ok": True, "name": path.stem, "steps": steps}, status=201)

    @app.get("/api/recipes/<name>")
    def recipes_get(ctx):
        path = _recipe_path(ctx.params["name"])
        if not path.is_file():
            raise HttpFail(404, "没有这个配方")
        return ctx.json(json.loads(path.read_text(encoding="utf-8")))

    @app.delete("/api/recipes/<name>")
    def recipes_delete(ctx):
        path = _recipe_path(ctx.params["name"])
        if not path.is_file():
            raise HttpFail(404, "没有这个配方")
        path.unlink()
        return ctx.json({"ok": True})

    def _csv_of(ctx, payload: dict | None = None) -> datascope.Table:
        try:
            if payload is not None:
                text = payload.get("csv")
                if not isinstance(text, str) or not text.strip():
                    raise HttpFail(400, "csv 字段缺失或为空")
            else:
                ctype = ctx.request.header("content-type")
                if ctype is not None and not ctype.startswith("text/csv") \
                        and not ctype.startswith("text/plain"):
                    raise HttpFail(415, "体要用 text/csv 或 text/plain")
                text = ctx.request.body.decode("utf-8")
            return datascope.parse_csv_text(text)
        except UnicodeDecodeError:
            raise HttpFail(400, "CSV 不是 UTF-8") from None
        except ValueError as exc:
            raise HttpFail(400, str(exc)) from None

    @app.post("/api/profile")
    def profile(ctx):
        table = _csv_of(ctx)
        return ctx.json({"rows": len(table),
                         "profile": datascope.profile(table)})

    @app.post("/api/clean")
    def clean(ctx):
        payload = ctx.json_body({"csv": (str, True), "recipe": (list, True)})
        table = _csv_of(ctx, payload)
        try:
            cleaned, report = datascope.apply_recipe(table, payload["recipe"])
        except datascope.RecipeError as exc:
            raise HttpFail(400, str(exc)) from None
        import io
        buffer = io.StringIO()
        cleaned.to_csv_stream(buffer)
        return ctx.json({"rows_after": len(cleaned), "report": report,
                         "csv": buffer.getvalue()})

    @app.post("/api/mine")
    def mine(ctx):
        payload = ctx.json_body({"csv": (str, True), "task": (str, True),
                                 "params": (dict, False)})
        table = _csv_of(ctx, payload)
        task = payload["task"]
        params = payload.get("params") or {}
        try:
            if task == "apriori":
                return ctx.json(apriori_from_rows(table, **params))
            if task == "kmeans":
                return ctx.json(kmeans_from_rows(table, **params))
        except TypeError as exc:
            raise HttpFail(400, f"参数不认识：{exc}") from None
        except ValueError as exc:             # 引擎/适配层守卫（坏值、空列、k 太大）
            raise HttpFail(400, str(exc)) from None
        raise HttpFail(400, f"task 只能是 apriori/kmeans，收到 {task!r}")

    @app.post("/api/report")
    def report(ctx):
        """清洗（必选）+ 挖掘（可选）→ 自包含 SVG 报告（轮四之三）。"""
        payload = ctx.json_body({"csv": (str, True), "recipe": (list, True),
                                 "mining": (dict, False)})
        table = _csv_of(ctx, payload)
        try:
            cleaned, clean_report = datascope.apply_recipe(table, payload["recipe"])
        except datascope.RecipeError as exc:
            raise HttpFail(400, str(exc)) from None
        mining = None
        if payload.get("mining"):
            task = payload["mining"].get("task")
            params = payload["mining"].get("params") or {}
            try:
                if task == "apriori":
                    mining = apriori_from_rows(cleaned, **params)
                elif task == "kmeans":
                    mining = kmeans_from_rows(cleaned, **params)
                else:
                    raise HttpFail(400, f"mining.task 只能是 apriori/kmeans，收到 {task!r}")
            except (ValueError, TypeError) as exc:
                raise HttpFail(400, str(exc)) from None
        from datascope.report import render_report
        svg = render_report(clean_report, mining)
        return Response(svg.encode("utf-8"),
                        content_type="image/svg+xml",
                        headers=[("Cache-Control", "no-store")])

    @app.get("/api/sample")
    def sample(ctx):
        """内置演示 CSV（轮九）：故意带重复/缺失/空格脏，供一键体验画像与清洗。"""
        return Response(SAMPLE_CSV.encode("utf-8"),
                        content_type="text/csv; charset=utf-8",
                        headers=[("Cache-Control", "no-store")])

    @app.get("/")
    def index(ctx):
        page = (WEB_ROOT / "index.html").read_bytes()
        return Response(page, content_type="text/html; charset=utf-8")

    app.static("/static", WEB_ROOT)
    return app


def build_server(*, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> MicroServer:
    return MicroServer(build_app(), host=host, port=port)


def main(argv=None) -> int:
    import argparse
    import threading
    ap = argparse.ArgumentParser(description="DataScope 工作台（只绑回环）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = build_server(port=args.port)
    port = server.start()
    print(f"DataScope 工作台已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print("挖掘引擎 = B26 Apriori/K-means（原项目 import，未重写）")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n再见")
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
