"""scripts/stop_all.py —— 收摊：经门户停掉全部产品，再停门户，核对端口全关。"""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRODUCTS = ["board", "boardweb", "courselab", "sensorhub", "cachekv",
            "datascope", "simlab", "lab", "linkbox"]


def req(port: int, method: str, path: str, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=body, headers=dict(headers or {}))
    resp = conn.getresponse()
    data = resp.read()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, data, hdrs


def port_open(port: int) -> bool:
    import socket
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.4).close()
        return True
    except OSError:
        return False


def main() -> int:
    if not port_open(8017):
        print("门户未在运行——无需收摊")
        return 0
    pw_lines = [ln.strip() for ln in (REPO / "studio" / "data" / "password.txt")
                .read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    status, _, headers = req(8017, "POST", "/api/login",
                             json.dumps({"username": "owner",
                                         "password": pw_lines[-1]}).encode(),
                             [("Content-Type", "application/json")])
    if status != 200:
        print(f"门户登录失败（HTTP {status}）——不能按 authenticated 路径收摊，中止")
        return 2
    auth = {"Cookie": headers.get("set-cookie", "").split(";")[0]}
    for pid in PRODUCTS:
        status, _, _ = req(8017, "POST", f"/api/products/{pid}/stop", headers=auth)
        print(f"{'✅' if status == 200 else '❌'} stop {pid}")
    time.sleep(1.5)
    still = [p for p in (8018, 7788, 8019, 8020, 8021, 8022, 8023, 8024, 8025)
             if port_open(p)]
    if still:
        print(f"⚠ 仍有端口在线（看门狗/子进程残留）：{still}，10s 后复查")
        time.sleep(10)
        still = [p for p in still if port_open(p)]
    # 停门户：按命令行精确匹配 studio/server.py（2026-10-07 审查收口）。
    # 旧路径一按窗口标题 "CourseLab*" 通配、二按 :8017 LISTENING 猜 PID——
    # 前者可能误杀标题相符的无关窗口，后者字面违反仓库红线"禁按端口号杀"。
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'studio[\\\\/]+server\\.py' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    killed = [int(tok.strip()) for tok in (ps.stdout or "").split()
              if tok.strip().isdigit()]
    for pid in killed:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    if killed:
        print("已停门户进程 PID：" + ", ".join(map(str, killed)))
    time.sleep(0.5)
    print("门户已停" if not port_open(8017) else "门户仍在（手动检查）")
    print("端口残留：" + (str(still) if still else "无"))
    return 0 if not still else 1


if __name__ == "__main__":
    raise SystemExit(main())
