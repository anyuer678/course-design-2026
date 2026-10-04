"""在线实验（F5 + F14 队列部分）：固定命令表 + 进程管理 + SSE 日志 + 并发限额 + 审计。

安全边界（与 showcase/lab.py 同款纪律，客户端只能选 id，带不了命令/参数/路径）：
- 命令表 TASKS/SERVES 在服务端写死（命令与课设仓库 lab.py 的注册表同款）；
- 并发限额（默认 2）；每项目同时只允许一个进程；超时（600s）与手动停止都走"整树杀"；
- 日志先进内存环（供 SSE 回放），落库只存首尾摘要（审计用：lrun 表）。
"""
from __future__ import annotations

import atexit
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from app.db import now_str

PY = sys.executable
MAX_CONCURRENT = 2
TASK_TIMEOUT = 600.0
LOG_RING = 4000
SERVE_READY_TIMEOUT = 8.0


class LabsError(Exception):
    def __init__(self, code: str, message: str, http: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ------------------------------------------------------------------ 固定命令表

def _task(demo: bool, tests: bool, bat=None) -> dict:
    out = {}
    if demo:
        out["demo"] = {"label": "运行 demo.py", "argv": [PY, "demo.py"]}
    if tests:
        out["tests"] = {"label": "跑测试套件", "argv": [PY, "-m", "unittest", "discover", "-s", "tests"]}
    if bat is not None:
        out["run"] = {"label": "运行 run.bat", "argv": ["cmd", "/c", "run.bat"] + bat}
    return out


_DEMO_TESTS = [
    "B3-logic-lab", "B4-algebra-rsa", "B10-minidb", "B11-net-lab", "B12-algo-arena",
    "B13-tinylang", "B23-ml-from-scratch", "B24-cv-scanner", "B25-nlp-lab",
    "B26-datamining", "B27-course-kg", "B28-bi-dashboard", "B29-bigdata-spark",
    "B30-mini-raft", "B31-shorturl", "B32-sec-lab", "B33-viz-algo", "B34-path-planner",
    "B35-iot-mqtt", "B37-industry-ai", "B38-mini-redis", "B39-tech-radar",
    "B40-career-map", "B41-thesis-seeds", "dorm-repair",
]
_BATS = {
    "B1-cpp-ministl": [], "B2-datastruct-lab": [], "B5-cpu-sim": [], "B6-asm-lab": [],
    "B7-mini-make": [], "B9-os-sim": [], "B14-java-paint": ["no-gui"],
}
# B8-mini-shell 要在 WSL 里跑：不在此列（同 lab.py 口径）。

TASKS: dict = {}
for _pid in _DEMO_TESTS:
    TASKS[_pid] = _task(demo=True, tests=True)
for _pid, _extra in _BATS.items():
    TASKS[_pid] = _task(demo=False, tests=False, bat=_extra)

SERVES = {
    "B11-net-lab": {
        "argv": [PY, "-c",
                 ("from netlab.server import Server; s = Server(port=8311); s.start(); "
                  "print('netlab 已启动 127.0.0.1:%d' % s.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8311, "ui": True,
    },
    "B31-shorturl": {
        "argv": [PY, "-m", "b31.server", "--port", "8312", "--memory"],
        "port": 8312, "ui": True,
    },
    "B38-mini-redis": {
        "argv": [PY, "-c",
                 ("from redislite.server import Server; s = Server(port=8313).start(); "
                  "print('redis 子集已启动 127.0.0.1:%d' % s.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8313, "ui": False,
    },
    "B35-iot-mqtt": {
        "argv": [PY, "-c",
                 ("from mqttlite.broker import Broker; b = Broker(port=8314).start(); "
                  "print('mqtt broker 已启动 127.0.0.1:%d' % b.port, flush=True); "
                  "import time; time.sleep(10**8)")],
        "port": 8314, "ui": False,
    },
    "B28-bi-dashboard": {"argv": [PY, "-m", "bi.server", "--port", "8315"], "port": 8315, "ui": True},
    "dorm-repair": {"argv": [PY, "-m", "prototype.server", "--port", "8316"], "port": 8316, "ui": True},
}


def describe(pid: str) -> dict:
    """某项目可做的实验动作（页面按钮的数据源）。"""
    acts = []
    for key, spec in TASKS.get(pid, {}).items():
        acts.append({"id": key, "label": spec["label"]})
    serve = SERVES.get(pid)
    if serve:
        acts.append({"id": "serve_start", "label": f"启动真实服务（:{serve['port']}）"})
    return {"actions": acts, "port": serve["port"] if serve else None,
            "ui": bool(serve["ui"]) if serve else False}


# ------------------------------------------------------------------ 进程管理

def _kill_tree(proc) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # cmd /c run.bat 的子进程会活下来继续跑：必须整树杀（lab.py 同款教训）
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class Labs:
    def __init__(self, repo: Path, db) -> None:
        self.repo = Path(repo)
        self.db = db
        self._lk = threading.Lock()
        self._runs: dict = {}
        atexit.register(self.shutdown)
        threading.Thread(target=self._monitor, daemon=True).start()

    # -------------------------------------------------- 查询
    def _running(self) -> list:
        out = []
        for meta in self._runs.values():
            proc = meta["proc"]
            if proc is not None and proc.poll() is None:
                out.append(meta)
        return out

    def active(self) -> dict:
        with self._lk:
            running = self._running()
        items = [{
            "run_id": m["id"], "pid": m["pid"], "action": m["action"], "kind": m["kind"],
            "user_id": m["user_id"],
            "started": time.strftime("%H:%M:%S", time.localtime(m["started"])),
            "seconds": round(time.time() - m["started"], 1),
            "port": m["port"],
        } for m in running]
        return {"ok": True, "running": items, "limit": MAX_CONCURRENT}

    def mine(self, user_id: int) -> list:
        rows = self.db.all(
            "SELECT id, pid, action, kind, started_at, finished_at, exit_code"
            " FROM lab_runs WHERE user_id = ? ORDER BY started_at DESC LIMIT 20", (user_id,))
        return [dict(r) for r in rows]

    def status(self, run_id: str):
        meta = self._runs.get(run_id)
        if meta is None:
            return None
        proc = meta["proc"]
        running = proc is not None and proc.poll() is None
        return {
            "run_id": run_id, "pid": meta["pid"], "action": meta["action"],
            "kind": meta["kind"], "user_id": meta["user_id"], "running": running,
            "seconds": round((meta["end"] or time.time()) - meta["started"], 1),
            "exit": meta["exit"], "port": meta["port"],
        }

    # -------------------------------------------------- 启停
    def start(self, user: dict, pid: str, action: str) -> dict:
        spec = TASKS.get(pid, {}).get(action)
        kind = "task"
        port = None
        if spec is None:
            serve = SERVES.get(pid)
            if action == "serve_start" and serve:
                spec = {"label": "启动真实服务", "argv": serve["argv"]}
                kind, port = "serve", serve["port"]
            else:
                raise LabsError("NO_ACTION", "本项目未注册该动作")
        with self._lk:
            if len(self._running()) >= MAX_CONCURRENT:
                raise LabsError("LIMIT", f"并发上限（{MAX_CONCURRENT} 个）已满，稍后再试", 429)
            if any(m["pid"] == pid and m["proc"].poll() is None for m in self._runs.values()):
                raise LabsError("BUSY", "该项目已有进程在跑", 409)
            run_id = secrets.token_hex(6)
            env = dict(os.environ, PYTHONUTF8="1")
            cwd = self.repo / "projects" / pid
            assert cwd.is_dir(), cwd
            proc = subprocess.Popen(spec["argv"], cwd=str(cwd), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            meta = {"id": run_id, "user_id": user["id"], "pid": pid, "action": action,
                    "kind": kind, "proc": proc, "started": time.time(), "end": None,
                    "exit": None, "port": port, "buf": deque(maxlen=LOG_RING)}
            self._runs[run_id] = meta
            self.db.execute(
                "INSERT INTO lab_runs(id, user_id, pid, action, kind, started_at)"
                " VALUES(?,?,?,?,?,?)",
                (run_id, user["id"], pid, action, kind, now_str()))
            meta["buf"].append(f"$ [{pid}] {spec['label']}（run {run_id}）")
            threading.Thread(target=self._pump, args=(meta,), daemon=True).start()
        if kind == "serve":
            self._wait_port(meta)
        return {"ok": True, "run_id": run_id, "port": port}

    def _pump(self, meta: dict) -> None:
        try:
            for line in iter(meta["proc"].stdout.readline, ""):
                meta["buf"].append(line.rstrip("\n"))
        finally:
            exit_code = meta["proc"].wait()
            meta["exit"] = exit_code
            meta["end"] = time.time()
            tail = "\n".join(list(meta["buf"])[-12:])
            self.db.execute(
                "UPDATE lab_runs SET finished_at=?, exit_code=?, log_tail=? WHERE id=?",
                (now_str(), exit_code, tail, meta["id"]))

    def _wait_port(self, meta: dict) -> None:
        deadline = time.time() + SERVE_READY_TIMEOUT
        while time.time() < deadline:
            if meta["proc"].poll() is not None:
                raise LabsError("SERVE_FAILED", "服务进程提前退出，看日志尾部",
                                500)
            try:
                with socket.create_connection(("127.0.0.1", meta["port"]), timeout=0.3):
                    return
            except OSError:
                time.sleep(0.15)
        self._kill(meta)
        raise LabsError("SERVE_TIMEOUT", f"服务 {SERVE_READY_TIMEOUT:.0f} 秒内未就绪", 504)

    def _kill(self, meta: dict) -> None:
        _kill_tree(meta["proc"])
        meta["buf"].append("[平台] 已停止")

    def stop(self, run_id: str) -> dict:
        meta = self._runs.get(run_id)
        if meta is None:
            raise LabsError("NO_RUN", "没有这个运行记录", 404)
        if meta["proc"].poll() is not None:
            return {"ok": True, "already": True}
        self._kill(meta)
        return {"ok": True}

    def stream(self, run_id: str):
        """SSE：先回放缓冲，再跟实时，直到进程结束。产出 (event, data)。"""
        meta = self._runs.get(run_id)
        if meta is None:
            yield ("done", {"error": "run 不存在或平台重启过", "exit": None})
            return
        idx = 0
        while True:
            buf = meta["buf"]
            while idx < len(buf):
                yield ("log", buf[idx])
                idx += 1
            if meta["end"] is not None:
                yield ("done", {
                    "exit": meta["exit"],
                    "seconds": round(meta["end"] - meta["started"], 1),
                    "pid": meta["pid"], "action": meta["action"], "port": meta["port"],
                })
                return
            time.sleep(0.25)

    def _monitor(self) -> None:
        while True:
            time.sleep(1.0)
            for meta in list(self._runs.values()):
                if meta["proc"] is not None and meta["proc"].poll() is None:
                    if time.time() - meta["started"] > TASK_TIMEOUT:
                        meta["buf"].append(f"[平台] 超时终止（>{TASK_TIMEOUT:.0f}s）")
                        self._kill(meta)

    def shutdown(self) -> None:
        for meta in list(self._runs.values()):
            if meta["proc"] is not None and meta["proc"].poll() is None:
                _kill_tree(meta["proc"])
