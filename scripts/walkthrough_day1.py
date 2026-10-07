"""scripts/walkthrough_day1.py —— P-验收 Day-1 预演：门户真启停八产品 + 机器可走查的用户故事。

这不是 P-验收的替代品（真实使用 ≥1 周仍由用户执行），而是它的 Day-1 冒烟预演：
用真实端口（8017-8024）把门户与八个产品按用户实际路径拉起，把清单里"机器可走查"
的故事真跑一遍并落一份证据文档；观感类故事（窗口/图表/移动端）如实留给用户。
产物：p-验收/day1-预演-<日期>.md。
"""
from __future__ import annotations

import atexit
import http.client
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool, str]] = []


def step(story: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((story, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {story}" + (f" —— {detail}" if detail else ""))


def req(port: int, method: str, path: str, body: bytes | None = None,
        headers: list | None = None, timeout: float = 10):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(method, path, body=body,
                 headers=dict(headers or {}))
    resp = conn.getresponse()
    data = resp.read()
    resp_headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, data, resp_headers


def wait_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    stamp = time.strftime("%Y-%m-%d")
    # 0) 前置：端口必须空闲
    busy = [p for p in range(8017, 8025) if wait_port(p, 0.2)]
    if busy:
        print(f"[!] 端口已被占用：{busy}（先停掉已有实例再预演）")
        return 1

    # 1) 启动 Studio 门户（真实用户路径）
    studio = subprocess.Popen([sys.executable, str(REPO / "studio" / "server.py"),
                               "--port", "8017"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    step("门户启动（studio/server.py :8017）", wait_port(8017))

    pw_lines = [ln.strip() for ln in (REPO / "studio" / "data" / "password.txt")
                .read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    password = pw_lines[-1]          # 文件带 # 说明头，口令是最后一个非注释行
    status, body, headers = req(8017, "POST", "/api/login",
                                json.dumps({"username": "owner",
                                            "password": password}).encode(),
                                [("Content-Type", "application/json")])
    cookie = headers.get("set-cookie", "").split(";")[0]
    step("门户登录（owner）", status == 200 and cookie.startswith("wf_session="),
         f"HTTP {status}")
    if status != 200:
        studio.terminate()
        return 1
    auth = [("Cookie", cookie), ("Content-Type", "application/json")]

    # 2) 门户一键启停八个产品
    products = ["linkbox", "lab", "simlab", "datascope", "cachekv",
                "sensorhub", "courselab", "board"]
    ports = {"linkbox": 8018, "lab": 7788, "simlab": 8019, "datascope": 8020,
             "cachekv": 8021, "sensorhub": 8022, "courselab": 8024, "board": 8023}
    # 收摊兜底（2026-10-07 审查收口）：此前中途异常会把门户+已启动的产品全留
    # 在机上——正是"残留进程"事故的成因模式。atexit 兜底做幂等收摊；
    # 正常路径收完摊置 done，兜底不再动作。
    _cleaned = {"done": False}

    def _emergency_cleanup():
        if _cleaned["done"]:
            return
        _cleaned["done"] = True
        print("[!] 预演未正常收摊——兜底清理八产品与门户")
        for pid in reversed(products):
            try:
                req(8017, "POST", f"/api/products/{pid}/stop", headers=auth)
            except Exception:
                pass
        try:
            studio.terminate()
        except Exception:
            pass

    atexit.register(_emergency_cleanup)
    for pid in products:
        status, body, _ = req(8017, "POST", f"/api/products/{pid}/start",
                              headers=auth)
        online = status == 200 and json.loads(body).get("online") is True
        step(f"门户启动 {pid}（:{ports[pid]}）", online, f"HTTP {status}")

    # 3) 机器可走查的用户故事（PRODUCTS §六）
    # LinkBox：短链 → 跳转； stash → 取回
    status, body, _ = req(8018, "POST", "/api/links",
                          json.dumps({"url": "https://github.com/"}).encode(),
                          [("Content-Type", "application/json")])
    code = json.loads(body).get("code", "") if status == 201 else ""
    status2, _, headers2 = req(8018, "GET", f"/l/{code}")
    step("LinkBox：建短链并真实跳转", status == 201 and status2 == 302
         and headers2.get("location") == "https://github.com/",
         f"201 → 302 → {headers2.get('location')}")
    status, body, _ = req(8018, "POST", "/api/stash",
                          json.dumps({"content": "预演存一段文本"}).encode(),
                          [("Content-Type", "application/json")])
    stash_code = json.loads(body).get("code", "") if status in (200, 201) else ""
    status2, body2, _ = req(8018, "GET", f"/api/stash/{stash_code}")
    ok = status2 == 200 and "预演存一段文本" in body2.decode("utf-8", "replace")
    step("LinkBox：存文本并取回", ok, f"HTTP {status} → {status2}")

    # 实验台：/ 302 到控制台首页
    status, _, headers = req(7788, "GET", "/")
    target = headers.get("location", "")
    status2, body2, _ = req(7788, "GET", target) if target.startswith("/") and status == 302 \
        else (0, b"", {})
    step("实验台：控制台页面可开（/ → 控制台）",
         status == 302 and status2 == 200 and len(body2) > 300,
         f"302 → {target} → HTTP {status2}")

    # SimLab：记录清单 + 单条详情
    status, body, _ = req(8019, "GET", "/api/records")
    names = json.loads(body).get("records", []) if status == 200 else []
    ok = status == 200 and len(names) > 0
    detail = f"{len(names)} 条记录"
    if ok:
        first = names[0]
        name = first.get("name") or first.get("id") or ""
        status2, _, _ = req(8019, "GET", f"/api/records/{name}")
        ok = status2 == 200
        detail += f"；首条详情 HTTP {status2}"
    step("SimLab：回放记录清单与详情", ok, detail)

    # DataScope：CSV 画像
    csv = "order,item,qty\n1,apple,2\n1,pear,3\n2,apple,1\n"
    status, body, _ = req(8020, "POST", "/api/profile", csv.encode(),
                          [("Content-Type", "text/csv")])
    step("DataScope：CSV 画像", status == 200 and b'"rows"' in body and b'"profile"' in body,
         f"HTTP {status}")

    # CacheKV：TTL 键 → 读 → 统计
    status, _, _ = req(8021, "PUT", "/api/kv/pv-demo?ttl=120", b"survives")
    status2, body2, _ = req(8021, "GET", "/api/kv/pv-demo")
    status3, body3, _ = req(8021, "GET", "/api/stats")
    stats = json.loads(body3).get("stats", {})
    step("CacheKV：TTL 键读写 + 统计账", status in (200, 201)
         and status2 == 200 and body2 == b"survives" and stats.get("hits", 0) >= 1,
         f"hits={stats.get('hits')}")

    # SensorHub：拍一拍 → 曲线 → 告警
    req(8022, "POST", "/api/tick")
    status, body, _ = req(8022, "GET", "/api/series?device=dev-01")
    status2, body2, _ = req(8022, "GET", "/api/chart?device=dev-01")
    ok = status == 200 and status2 == 200 and body2.lstrip().startswith(b"<svg")
    step("SensorHub：推拍 + 曲线 SVG", ok, f"series {status} / chart {status2}")

    # CourseLab：健康 + 课程目录
    status, body, _ = req(8024, "GET", "/health")
    ok = status == 200 and b"courselab" in body
    status2, body2, _ = req(8024, "GET", "/api/courses")
    courses = len(json.loads(body2).get("courses", [])) if status2 == 200 else 0
    step("CourseLab：健康检查 + 课程目录", ok and courses == 33,
         f"health {status}，课程 {courses} 门")

    # Board：探活口活账
    with socket.create_connection(("127.0.0.1", 8023), timeout=3) as sock:
        reply = sock.recv(4096).decode("utf-8", "replace").strip()
    step("Board：探活口回报活账", reply.startswith("BOARD 8023 OK"), reply)

    # 4) 门户逐个停止（board 有 ≤8s 看门狗滞后，轮询确认）
    for pid in reversed(products):
        req(8017, "POST", f"/api/products/{pid}/stop", headers=auth)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not wait_port(8023, 0.3):
            break
        time.sleep(0.3)
    else:
        print("[!] board :8023 在 10s 后仍可连（看门狗未收干净）")
    step("门户逐个停止八产品（board 看门狗跟进）", not wait_port(8023, 0.3))

    studio.terminate()
    studio.wait(timeout=5)
    step("门户停止", not wait_port(8017, 0.5))
    _cleaned["done"] = True               # 已正常收摊，atexit 兜底不再动作

    # 5) 证据文档
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    lines = [
        f"# P-验收 Day-1 预演（{stamp}）",
        "",
        "> 机器可走查部分的冒烟预演，**不替代**真实使用 ≥1 周（PRODUCTS §六）。",
        "> 全部经真实端口（8017-8024）与门户真实启停路径执行；观感类故事留给用户。",
        "",
        f"| 结果 | 故事 | 明细 |",
        "|---|---|---|",
    ]
    lines += [f"| {'✅' if ok else '❌'} | {story} | {detail} |" for story, ok, detail in RESULTS]
    lines += [
        "",
        f"**合计：{passed}/{len(RESULTS)} 通过。**",
        "",
        "## 留给用户的人工故事（机器做不了）",
        "",
        "- LinkBox 二维码用手机扫；SimLab 播放观感与参数手感；DataScope SVG 报告观感；",
        "- SensorHub 曲线实时观感（调快节拍）；Board 真窗口完整人工清单（B14 同款）；",
        "- CourseLab 三角色真实教学流（注册审批/布置任务/看板）。",
    ]
    out = REPO / "p-验收" / f"day1-预演-{stamp}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n证据文档：{out}（{passed}/{len(RESULTS)} 通过）")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
