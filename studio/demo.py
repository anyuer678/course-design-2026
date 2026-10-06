"""Studio 四段演示：门户自启 → 目录/状态 → 认证（登录/改口令回滚）→ 退出。

门户起在临时端口、凭据用临时目录（不碰真实的 studio/data/）；LinkBox/实验台
只做探活演示，不真启停（真启停链路由 tests 覆盖）。断言失败计入退出码。
"""
import http.client
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
for p in (str(REPO), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from studio.server import build_server                   # noqa: E402

FAILS = []


def check(cond, msg):
    print(f"    {'OK' if cond else 'XX'} {msg}")
    if not cond:
        FAILS.append(msg)


def talk(method, path, body=None, headers=None):
    """每步一条新连接：验的是状态码与语义，不绑 keep-alive 行为。"""
    conn = http.client.HTTPConnection("127.0.0.1", PORT[0])
    conn.request(method, path, body=body,
                 headers=dict(headers or {}))
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, resp.getheaders(), payload


PORT = [0]


def main() -> int:
    print("Studio 演示：门户自身跑在 webframe 微框架上")
    with tempfile.TemporaryDirectory() as td:
        server, manager, auth = build_server(port=0, linkbox_port=18018,
                                             lab_port=17888,
                                             linkbox_memory=True,
                                             data_dir=td)
        PORT[0] = server.start()
        try:
            print(f"\n=== 第一段：门户自证（127.0.0.1:{PORT[0]}）===")
            status, _, body = talk("GET", "/")
            check(status == 200 and b"Studio" in body,
                  "门户首页可达（webframe 静态管线）")

            print("\n=== 第二段：产品目录（矩阵照抄 PRODUCTS.md + 实验台并入）===")
            status, _, body = talk("GET", "/api/products")
            data = json.loads(body)
            ids = [p["id"] for p in data["products"]]
            check(status == 200 and ids[:3] == ["studio", "linkbox", "lab"],
                  f"目录 {len(ids)} 项，实验台在列")
            check(data["portal"]["framework"] == "webframe",
                  "状态面板声明框架来源")

            print("\n=== 第三段：状态探测（诚实口径：在线 = 端口连得上）===")
            status, _, body = talk("GET", "/api/products/linkbox/status")
            data = json.loads(body)
            check(status == 200 and data["online"] is False,
                  "LinkBox 未启动 → 如实报离线")

            print("\n=== 第四段：认证（管理动作的门）===")
            status, _, _ = talk("POST", "/api/products/linkbox/start")
            check(status == 401, "未登录启停 → 401（目录可看，开关不给摸）")
            status, headers, _ = talk(
                "POST", "/api/login",
                json.dumps({"username": "owner",
                            "password": auth.password}).encode(),
                [("Content-Type", "application/json")])
            cookie = dict(headers).get("Set-Cookie", "").split(";")[0]
            check(status == 200 and cookie.startswith("wf_session="),
                  "登录拿到签名会话 cookie")
            status, _, body = talk("GET", "/api/me",
                                   headers={"Cookie": cookie})
            check(json.loads(body)["user"] == "owner", "会话识别出 owner")
            # 演示收尾不留真启停（真链路在 tests）：把 LinkBox 保持离线原样
        finally:
            server.stop()

    print()
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败")
        return 1
    print("四段演示全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
