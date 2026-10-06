"""linkbox/server.py —— 产品入口：python server.py --port 8018

复用说明：短链应用与服务器来自课程任务 B31（b31.app / b31.server），
本文件只做产品装配——数据目录、暂存仓储、产品应用类。
只绑回环地址：自托管产品，默认不对外网开放。
"""
from __future__ import annotations

import argparse
import threading
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))                       # linkbox 包
sys.path.insert(0, str(ROOT.parent / "projects" / "B31-shorturl"))
sys.path.insert(0, str(ROOT.parent / "projects" / "B11-net-lab"))

from b31.server import ShortUrlServer               # noqa: E402
from b31.store import Store                         # noqa: E402

from linkbox.app import LinkBoxApp                  # noqa: E402
from linkbox.files import MAX_FILE_BYTES, FileStore  # noqa: E402
from linkbox.stash import StashStore                # noqa: E402
from linkbox.sweeper import StashSweeper            # noqa: E402

DATA_DIR = ROOT / "data"
WEB_ROOT = ROOT / "web"


def build_server(*, host: str = "127.0.0.1", port: int = 8018,
                 db_path: str | None = None,
                 stash_path: str | None = None,
                 files_path: str | None = None,
                 sweep_interval: float = 300.0) -> ShortUrlServer:
    DATA_DIR.mkdir(exist_ok=True)
    db = db_path or str(DATA_DIR / "shorturl.sqlite")
    stash_db = stash_path or str(DATA_DIR / "stash.sqlite")
    files_db = files_path or str(DATA_DIR / "files.sqlite")
    store = Store(db)
    stash = StashStore(stash_db)
    files = FileStore(files_db)
    # 文件上传放宽传输层上限（netlab 默认 1 MiB 是为 JSON 设计的）；
    # 应用层仍有 MAX_FILE_BYTES 精确限额与空体 400，传输层只做粗闸。
    app = LinkBoxApp(store, WEB_ROOT, stash=stash, files=files)
    server = ShortUrlServer(app, host=host, port=port,
                            max_body=MAX_FILE_BYTES + 4096)
    server.sweeper = StashSweeper(stash, files, interval=sweep_interval)
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LinkBox 自托管工具站（只绑回环）")
    ap.add_argument("--port", type=int, default=8018)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--memory", action="store_true", help="不落盘，退出即忘")
    args = ap.parse_args(argv)

    server = build_server(host=args.host, port=args.port,
                          db_path=":memory:" if args.memory else None,
                          stash_path=":memory:" if args.memory else None,
                          files_path=":memory:" if args.memory else None)
    port = server.start()
    server.sweeper.start()                          # M3：后台清扫过期暂存
    print(f"LinkBox 已启动： http://127.0.0.1:{port}/   （Ctrl+C 退出）")
    print(f"过期清扫： 每 {server.sweeper.interval:.0f} 秒一轮")
    if not args.memory:
        print(f"数据目录： {DATA_DIR}")
    try:
        threading.Event().wait()        # start() 已把事件循环放到后台线程
    except KeyboardInterrupt:
        print("\n再见")
        server.sweeper.stop()
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
