"""备份工具：SQLite `VACUUM INTO` 时间戳副本 + 完整性校验（标准库，停服/在线皆可跑）。

用法：
    python tools/backup.py                     # 备份 data/app.db 到 backup/
    python tools/backup.py --db X --out Y      # 指定来源与去向
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="CourseLab 备份（VACUUM INTO + 校验）")
    ap.add_argument("--db", default=str(ROOT / "data" / "app.db"))
    ap.add_argument("--out", default=str(ROOT / "backup"))
    args = ap.parse_args(argv[1:])

    src = Path(args.db)
    if not src.is_file():
        print(f"[!] 找不到数据库：{src}（先启动过一次平台，或检查 --db）")
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"app-{time.strftime('%Y%m%d-%H%M%S')}.db"

    conn = sqlite3.connect(str(src))
    try:
        conn.execute("VACUUM INTO ?", (str(dest),))
    finally:
        conn.close()

    chk = sqlite3.connect(str(dest))
    try:
        users = chk.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        labs_count = chk.execute("SELECT COUNT(*) FROM lab_runs").fetchone()[0]
        records = chk.execute("SELECT COUNT(*) FROM task_records").fetchone()[0]
        integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        chk.close()
    print(f"备份完成：{dest}")
    print(f"  校验：users={users} lab_runs={labs_count} task_records={records} "
          f"integrity={integrity} 大小={dest.stat().st_size}B")
    return 0 if integrity == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
