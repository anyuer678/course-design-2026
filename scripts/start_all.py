"""scripts/start_all.py —— 真实使用周的启动器：起门户并经门户拉起全部九产品。

用法：python start_all.py
等价于用户在门户页面里逐个点"启动"（真实子进程链），跑完打印每产品在线状态。
配对脚本：stop_all.py。
"""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRODUCTS = ["linkbox", "simlab", "datascope",
            "cachekv", "sensorhub", "courselab", "board", "boardweb"]


def req(port: int, method: str, path: str, body=None, headers=None, timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(method, path, body=body, headers=dict(headers or {}))
    resp = conn.getresponse()
    data = resp.read()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, data, hdrs


def main() -> int:
    busy = [p for p in (8017,) if _port_open(p)]
    if busy:
        print("门户已在运行（:8017）——直接使用即可；如需重启先跑 stop_all.py")
        return 0
    studio = subprocess.Popen([sys.executable, str(REPO / "studio" / "server.py"),
                               "--port", "8017"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if _port_open(8017):
            break
        time.sleep(0.2)
    if not _port_open(8017):
        # 探活失败不许裸栈 + 不许把半启动的门户留在机上（2026-10-07 审查收口）
        studio.terminate()
        print("门户 10s 未就绪——已回收进程；可手动 python studio/server.py --port 8017 看报错")
        return 1
    pw_lines = [ln.strip() for ln in (REPO / "studio" / "data" / "password.txt")
                .read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    status, body, headers = req(8017, "POST", "/api/login",
                                json.dumps({"username": "owner",
                                            "password": pw_lines[-1]}).encode(),
                                [("Content-Type", "application/json")])
    if status != 200:
        studio.terminate()
        print(f"登录失败：HTTP {status}——已回收门户进程")
        return 1
    auth = {"Cookie": headers.get("set-cookie", "").split(";")[0],
            "Content-Type": "application/json"}
    fails = []
    for pid in PRODUCTS:
        status, body, _ = req(8017, "POST", f"/api/products/{pid}/start",
                              headers=auth)
        online = status == 200 and json.loads(body).get("online") is True
        print(f"{'✅' if online else '❌'} {pid}")
        if not online:
            fails.append(pid)
    print(("全部在线，浏览器打开 http://127.0.0.1:8017/ 管理与导航"
           if not fails else f"启动失败：{fails}"))
    return 0 if not fails else 1


def _port_open(port: int) -> bool:
    import socket
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
