"""datascope/run.py —— CLI：画像与清洗。

    python datascope/run.py profile 数据.csv
    python datascope/run.py clean 数据.csv --recipe 配方.json --out 清洗后.csv --report 报告.json

配方是有序步骤数组（见 README），报告即账本（每步计数对账）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import datascope                                    # noqa: E402
from datascope.clean import RecipeError             # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DataScope：CSV 画像与清洗（报告即账本）")
    sub = ap.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="列画像（类型/缺失/去重/最值）")
    p_profile.add_argument("csv", help="CSV 文件路径")

    p_clean = sub.add_parser("clean", help="按配方清洗")
    p_clean.add_argument("csv", help="CSV 文件路径")
    p_clean.add_argument("--recipe", required=True, help="配方 JSON（有序步骤数组）")
    p_clean.add_argument("--out", required=True, help="清洗后 CSV 输出路径")
    p_clean.add_argument("--report", help="报告 JSON 输出路径（缺省打到 stdout）")

    p_mine = sub.add_parser("mine", help="挖掘（B26 真引擎：Apriori/K-means）")
    p_mine.add_argument("csv", help="CSV 文件路径")
    p_mine.add_argument("--task", required=True, choices=("apriori", "kmeans"))
    p_mine.add_argument("--params", default="{}", help="挖掘参数（JSON 对象）")

    args = ap.parse_args(argv)
    try:
        table = datascope.parse_csv(args.csv)
    except ValueError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2

    if args.command == "profile":
        print(json.dumps(datascope.profile(table), ensure_ascii=False, indent=2))
        return 0

    if args.command == "mine":
        from datascope.mining import apriori_from_rows, kmeans_from_rows
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"[!] --params 不是合法 JSON：{exc.msg}", file=sys.stderr)
            return 2
        try:
            if args.task == "apriori":
                result = apriori_from_rows(table, **params)
            else:
                result = kmeans_from_rows(table, **params)
        except (ValueError, TypeError) as exc:
            print(f"[!] {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[!] 配方读不了：{exc}", file=sys.stderr)
        return 2

    try:
        cleaned, report = datascope.apply_recipe(table, recipe)
    except RecipeError as exc:
        print(f"[!] 配方不合法：{exc}", file=sys.stderr)
        return 2

    cleaned.to_csv(args.out)
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写出 {args.out}（{len(cleaned)} 行）与 {args.report}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"已写出 {args.out}（{len(cleaned)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
