"""scripts/stop_all.py —— 收摊：经门户停掉全部产品，再停门户，核对端口全关。"""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRODUCTS = ["board", "courselab", "sensorhub", "cachekv",
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
    auth = {"Cookie": headers.get("set-cookie", "").split(";")[0]}
    for pid in PRODUCTS:
        status, _, _ = req(8017, "POST", f"/api/products/{pid}/stop", headers=auth)
        print(f"{'✅' if status == 200 else '❌'} stop {pid}")
    time.sleep(1.5)
    still = [p for p in (8018, 7788, 8019, 8020, 8021, 8022, 8023, 8024)
             if port_open(p)]
    if still:
        print(f"⚠ 仍有端口在线（看门狗/子进程残留）：{still}，10s 后复查")
        time.sleep(10)
        still = [p for p in still if port_open(p)]
    # 停门户
    out = subprocess.run(["taskkill", "/F", "/FI",
                          f"WINDOWTITLE eq CourseLab*"], capture_output=True)
    # 门户是 python 进程：按端口找 PID 停
    import re
    netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    pids = {int(ln.split()[-1]) for ln in netstat.stdout.splitlines()
            if re.search(r":8017\s.*LISTENING", ln)}
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    time.sleep(0.5)
    print("门户已停" if not port_open(8017) else "门户仍在（手动检查）")
    print("端口残留：" + (str(still) if still else "无"))
    return 0 if not still else 1


if __name__ == "__main__":
    raise SystemExit(main())
