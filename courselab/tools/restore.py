"""恢复工具：把备份复制回 --db（先校验来源、给现存库留 .before-restore 底）。

用法：
    python tools/restore.py --from backup/app-YYYYmmdd-HHMMSS.db
    python tools/restore.py --from X --db Y
说明：恢复前请先停服（进程可能缓存了连接）；恢复后建议复跑一次 server.py --selftest。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _verify(path: Path):
    conn = sqlite3.connect(str(path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    finally:
        conn.close()
    return integrity, users, tables


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="CourseLab 恢复（复制 + 校验）")
    ap.add_argument("--from", dest="src", required=True, help="备份文件路径")
    ap.add_argument("--db", default=str(ROOT / "data" / "app.db"), help="目标数据库路径")
    args = ap.parse_args(argv[1:])

    src = Path(args.src)
    dest = Path(args.db)
    if not src.is_file():
        print(f"[!] 找不到备份文件：{src}")
        return 1
    integrity, users, tables = _verify(src)
    if integrity != "ok":
        print(f"[!] 备份文件自检失败（integrity={integrity}），拒绝恢复")
        return 1
    print(f"备份文件校验：users={users} tables={tables} integrity={integrity}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        bak = dest.parent / f"{dest.name}.before-restore-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(dest, bak)
        print(f"  现有库已留底：{bak}")
    shutil.copy2(src, dest)

    integrity2, users2, _ = _verify(dest)
    print(f"恢复完成：{src} -> {dest}（users={users2} integrity={integrity2}）")
    if integrity2 != "ok":
        print("[!] 恢复后的库自检失败——请用留底文件回滚")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
