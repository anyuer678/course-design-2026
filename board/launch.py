"""board/launch.py —— 产品启动器（Studio 门户管理 board 的入口）。

职责只有两件：
    1. 确保编译产物新鲜（ensure_classes，脏了就 javac）；
    2. 拉起 `board.BackupDaemon`（守护 + 探活口；--window 可加开 B14 真窗口），
       并把 --parent-pid 指给启动器——Studio 停止 = 终止本进程，java 子进程的
       看门狗一秒内确认父进程不在、自觉退出，**不留孤儿进程、不留半开探活口**。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_support import ensure_classes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="board 画板产品启动器（被 Studio 管理）")
    ap.add_argument("--port", type=int, default=8023,
                    help="探活口端口（0 = 自动分配）")
    ap.add_argument("--window", action="store_true",
                    help="加开 B14 画板真窗口（headless 环境会明确拒绝）")
    ap.add_argument("--interval", type=float, default=2000,
                    help="目录守护轮询毫秒数")
    ap.add_argument("--keep", type=int, default=20, help="每桶保留备份数")
    args = ap.parse_args(argv)

    classes, _ = ensure_classes()
    data_dir = Path(__file__).resolve().parent / "data"
    board_args = ["--port", str(args.port), "--interval", str(args.interval),
                  "--keep", str(args.keep)]
    if args.window:
        board_args.append("--window")
    # 轮九 UI 专项：Nimbus 外观由引擎 App.java 显式 setLookAndFeel（产品矩阵观感统一），
    # launch.py 不再经 JVM 属性注入（显式调用优先级更高，属性已移除）。
    cmd = ["java", f"-Dpaint.data={data_dir}",
           "-cp", str(classes),
           "board.BackupDaemon"] + board_args
    if not args.window:
        # 只有 Studio 托管的服务形态才带看门狗；--window 是用户本机开窗，独立活
        cmd += ["--parent-pid", str(os.getpid())]
    try:
        proc = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent),
                              check=False)
    except KeyboardInterrupt:
        return 0
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
