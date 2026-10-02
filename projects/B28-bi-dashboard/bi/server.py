"""bi/server.py —— 可筛选的仪表盘服务：标准库 `http.server`，只绑 127.0.0.1。

为什么这一层值得单独写：BI 的"可筛选"就是把用户输入送到 SQL 面前，
本项目的全部纪律（B32 的第一组）都在这几行里落地：
    · 筛选键必须命中 `warehouse.FILTER_FIELDS` 白名单，未知键**直接 400**，不静默忽略；
    · 值一律 `?` 绑定；页面上回显筛选值时过 `html.escape`；
    · 分页参数是整数，非法就拒（`int()` 失败不降级成字符串拼接）。

路由（都在同一个内存库上，每次请求现算，不缓存——缓存会造出"两个不同的今日数"）：
    /            看板 HTML（支持 ?month_from=&month_to=&category=&region=）
    /api/summary 同一份指标与洞察的 JSON 形态（口径文字也在里面）
    /api/drill   明细下钻：当前筛选命中的订单行，带 LIMIT/OFFSET
    /lineage     指标血缘图（B27 的分层 SVG 页面）
    /health      装载摘要，给 run.bat 自检用

浏览器观感不在我的验收范围（本机策略禁止自动化驱动浏览器），
README 里作为"需要你实跑的一步"列出，我不代勾。
"""
from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from bi import insights as I
from bi import lineage as L
from bi import metrics as M
from bi import render as R
from bi import warehouse as W

MAX_PAGE = 200
BUNDLE: tuple | None = None


def bundle() -> tuple:
    """一个进程一份仓库：请求之间共享同一份清洗结果，保证数字不会漂。

    实测踩过的坑（现在由 `warehouse.build` 的参数承接）：`ThreadingHTTPServer`
    每个请求换一条线程，默认 `check_same_thread=True` 的连接在第二条请求上就抛
    ProgrammingError——**第一次 /health 成功、第二次就 500**，这种"首请求必好"的
    缺陷最容易在只发一个请求的自测里溜过去。
    """
    global BUNDLE
    if BUNDLE is None:
        BUNDLE = W.build(check_same_thread=False)
    return BUNDLE


# 允许的筛选键：与 warehouse 的三张白名单表同源，不另列一份清单（会漂移）。
QUERY_KEYS = tuple(sorted({key for group in (W.ITEM_FIELDS, W.ORDER_FIELDS,
                                             W.CUSTOMER_FIELDS)
                           for key, _ in group} | {"status"}))


def filters_from_query(raw: str) -> dict:
    """从 query string 取筛选，**未知键直接拒**。

    第一版只挑已知键、把别的键静默丢掉，于是 `?evil=1` 返回 200。
    那算不上漏洞（它没进 SQL），但对使用者是伤害：条件写错了却看到一张
    "按你的条件算出来的" 看板。拒绝的成本是一句 400，误信的成本没人估得出。
    """
    parsed = parse_qs(raw, keep_blank_values=True)
    unknown = sorted(set(parsed) - set(QUERY_KEYS) - {"page", "size"})
    if unknown:
        raise W.FilterError(f"未知查询参数 {unknown}；可用的是 {list(QUERY_KEYS)}"
                            "（分页另有 page/size）")
    filters: dict[str, str] = {}
    for key in QUERY_KEYS:
        if key in parsed:
            filters[key] = unquote(parsed[key][-1])
    W.where_for(filters)              # 只是校验，返回值在这里用不上
    return filters


def summary(filters: dict) -> dict:
    conn, data = bundle()
    results = M.compute(conn, data, filters)
    panels = I.panels(data, filters)
    return {"filters": filters,
            "reconcile_clean": not M.mismatches(results),
            "mismatches": M.mismatches(results),
            "metrics": {key: {k: v for k, v in row.items() if k != "名称"}
                        for key, row in results.items()},
            "insights": panels,
            "loading": {"ledger": data["ledger"], "seed": data["seed"]}}


def drill(filters: dict, page: int = 1, size: int = 50) -> dict:
    """明细下钻：当前筛选下**具体是哪些单**。口径与汇总必须同源，否则下钻就对不上账。"""
    conn, data = bundle()
    size = max(1, min(size, MAX_PAGE))
    page = max(1, page)
    template = ("SELECT o.order_id, o.customer_id, c.region, o.created_at, "
                "o.completed_at, o.status, p.name, i.qty, i.amount "
                + M.ITEM_FROM + " ORDER BY o.order_id ASC LIMIT ? OFFSET ?")
    rows = W.run(conn, template, filters, [size, (page - 1) * size])
    total = W.run(conn, "SELECT count(*) " + M.ITEM_FROM, filters)[0][0]
    return {"filters": filters, "page": page, "size": size, "total": total,
            "rows": [[*(str(v) for v in row)] for row in rows]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_name = "B28-bi-dashboard"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False,
                                      default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):                        # noqa: N802  stdlib 约定的方法名
        try:
            self._route()
        except Exception as exc:                     # noqa: BLE001 兜底成 500，不吐 traceback
            # 实测踩过：/health 里引用了一个已改名的常量，异常直接冒到 socketserver，
            # 客户端只看到 502 且 stderr 一片 traceback。服务层的兜底应该给**可读的 500**。
            self._json({"error": "INTERNAL", "reason": f"{type(exc).__name__}: {exc}"}, 500)

    def _route(self) -> None:
        parts = urlsplit(self.path)
        path, query = parts.path, parts.query
        try:
            filters = filters_from_query(query)
        except W.FilterError as exc:
            self._json({"error": "BAD_FILTER", "reason": exc.reason}, 400)
            return
        if path == "/":
            self._send(200, R.dashboard(filters, bundle=bundle()).encode("utf-8"),
                       "text/html; charset=utf-8")
        elif path == "/api/summary":
            self._json(summary(filters))
        elif path == "/api/drill":
            try:
                page = int(query and parse_qs(query).get("page", ["1"])[-1] or 1)
                size = int(query and parse_qs(query).get("size", ["50"])[-1] or 50)
            except ValueError:
                self._json({"error": "BAD_PAGE",
                            "reason": "page/size 必须是整数"}, 400)
                return
            self._json(drill(filters, page, size))
        elif path == "/lineage":
            self._send(200, L.render().encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/health":
            conn, data = bundle()
            self._json({"ok": True, "loaded": data["loaded"],
                        "lineage_problems": L.problems(),
                        "filters": sorted(W.FILTER_KEYS),
                        "status_constant": W.TRADING_STATUS})
        else:
            self._json({"error": "NOT_FOUND", "path": html.escape(path)}, 404)

    def log_message(self, *args):                      # 静音 stderr
        pass


def start(port: int = 0) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def stop(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="B28 仪表盘服务（只绑 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    server, thread, port = start(args.port)
    print(f"B28 仪表盘已启动：http://127.0.0.1:{port}/  （Ctrl+C 结束）")
    print("这一步是给你在浏览器里看的：筛选、下钻、血缘图的观感只能由你判断，我不代勾。")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop(server, thread)
        print("服务已关闭，内存库随之释放（没有落盘文件）。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
