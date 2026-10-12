"""check_fresh_boot.py —— 新鲜空数据目录起服冒烟：容器空卷 / 新克隆等价验证。

背景（2026-10-12 轮二十四）：compose 命名卷首挂是**空目录**，本地测试全部
跑在"数据目录已有历史文件"的状态上——"全新环境能不能起服"从未验证过。
本检查对 8 个产品各做一次：
  1. staged 布局：产品目录拷贝到临时区（剔除 data/logs/runs/backup/
     __pycache__/config.json），再建空 data 目录——等价于容器空卷首挂；
     webframe/projects/showcase/g2 用 junction 共享（只读依赖，零拷贝）；
  2. 真启动：python server.py --host 127.0.0.1 --port <随机空闲端口>；
  3. 探活：15s 内 / 必须给出任意 HTTP 响应（2xx-4xx 都算"活着"，
     403/302 是正常业务响应）；超时或进程先退 = 红；
  4. 清理：terminate + 删临时区。
已验证过 mkdir(exist_ok) 只是"写了自建"，这里证明它真的够用。
无 Docker 引擎也能跑（与 check_docker_layout 同为 compose 实测的替身哨兵）。
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ["studio", "linkbox", "simlab", "datascope",
            "cachekv", "sensorhub", "courselab", "boardweb"]
# 拷贝产品目录时剔除（等价 .dockerignore 的运行数据口径 + 容器凭据口径）
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "data", "logs",
                              "runs", "backup", "config.json", "*.sqlite", "*.sqlite3")
SHARE = ["webframe", "projects", "showcase", "g2"]   # 只读依赖：junction 共享
BOOT_TIMEOUT = 15.0
PROBE_TIMEOUT = 3.0


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url: str) -> int | None:
    # 系统代理 7890 常开（见 MEMORY）：显式无代理 opener，否则假红/假绿
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=PROBE_TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:      # 4xx/5xx 也是"服务器活着"
        return e.code
    except OSError:
        return None


def make_junction(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def stage_product(product: str, stage_root: Path) -> Path:
    """staged 布局：/app 风格目录树 + 全新空数据目录。返回产品 staged 目录。"""
    stage_root.mkdir(parents=True, exist_ok=True)
    app = stage_root / "app"
    app.mkdir(exist_ok=True)
    for share in SHARE:                      # 只读依赖 junction（幂等）
        link = app / share
        if not link.exists():
            make_junction(link, ROOT / share)
    dst = app / product
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / product, dst, ignore=SKIP)
    # 空数据目录（compose 命名卷首挂的真实形态）
    for sub in ("data", "logs"):
        (dst / sub).mkdir(exist_ok=True)
    return dst


def boot_and_probe(product: str, pdir: Path) -> tuple[bool, str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(pdir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    deadline = time.monotonic() + BOOT_TIMEOUT
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False, f"启动后立即退出（码 {proc.returncode}）"
            code = get(f"http://127.0.0.1:{port}/")
            if code is not None and code < 500:
                return True, f"HTTP {code}（端口 {port}）"
            time.sleep(0.25)
        return False, f"{BOOT_TIMEOUT:.0f}s 未探活"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        time.sleep(0.2)                      # 让端口释放，避免下一产品撞车


def main() -> int:
    # 系统临时目录：不在仓库里堆 staging；收尾清理只做 best-effort——
    # 工作区大批量删除会撞 safe-delete 守卫（实测 940 文件 > 50/turn 阈值，
    # 2026-10-12 在 check_all 里把 8/8 全 PASS 的一轮打成红），残留交给系统清理
    tmp = Path(tempfile.mkdtemp(prefix="kc-freshboot-"))
    violations = []
    for product in PRODUCTS:
        t0 = time.time()
        try:
            pdir = stage_product(product, tmp)
            ok, detail = boot_and_probe(product, pdir)
        except Exception as err:             # staging 本身炸也要红得有名有姓
            ok, detail = False, f"staging 异常：{err!r}"
        dt = time.time() - t0
        print(f"[{'PASS' if ok else 'FAIL'}] 新鲜空数据起服：{product}（{detail}，{dt:.1f}s）")
        if not ok:
            violations.append(f"{product}: {detail}")
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass                                 # 守卫拦截就留着，系统临时目录自会清理
    if violations:
        print(f"新鲜起服冒烟：{len(violations)} 处失败")
        return 1
    print(f"新鲜起服冒烟：{len(PRODUCTS)} 个产品全部在空数据目录上起服并响应")
    return 0


if __name__ == "__main__":
    sys.exit(main())
