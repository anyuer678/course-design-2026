"""scripts/sync_assets.py —— 把 webkit/ 共享资产同步到各产品的 web/assets/。

用法：
    python scripts/sync_assets.py            # 同步（覆盖产品侧副本）
    python scripts/sync_assets.py --check    # 只核验新鲜度（不一致退出 1，供体检/CI 用）

共享资产清单（PRODUCTS.md §四 的 webkit/ 共享目录落地）：
    webkit/kb.css -> <产品>/web/assets/kb.css
产品清单与 studio（含 courselab）保持一致；新增产品在这里加一行即可。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = [("webkit/kb.css", "{product}/web/assets/kb.css")]
PRODUCTS = ["linkbox", "simlab", "datascope", "cachekv",
            "sensorhub", "courselab", "studio"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="webkit 共享资产同步（--check 只核验）")
    ap.add_argument("--check", action="store_true", help="只核验新鲜度，不写盘")
    args = ap.parse_args(argv[1:])

    stale, copied = [], 0
    for src_rel, dst_tpl in ASSETS:
        src = ROOT / src_rel
        for product in PRODUCTS:
            dst = ROOT / dst_tpl.format(product=product)
            if not src.is_file():
                print(f"[缺] 源文件不存在：{src_rel}")
                return 1
            same = dst.is_file() and dst.read_bytes() == src.read_bytes()
            if same:
                continue
            if args.check:
                stale.append(dst.relative_to(ROOT).as_posix())
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                copied += 1
                print(f"[同步] {dst.relative_to(ROOT).as_posix()}")

    if args.check:
        if stale:
            print("共享资产过期（跑 python scripts/sync_assets.py 同步）：")
            for s in stale:
                print("  [过期]", s)
            return 1
        print(f"共享资产新鲜：{len(ASSETS) * len(PRODUCTS)} 份副本全部与 webkit/ 一致")
        return 0
    print(f"完成：同步 {copied} 份、其余已一致（共 {len(ASSETS) * len(PRODUCTS)} 份）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
