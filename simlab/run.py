"""simlab/run.py —— CLI：跑一次实验，出一条校验过的运行记录。

    python simlab/run.py <实验名> --params '<JSON>' [--out 路径] [--list]

记录先过自家校验器再落盘（自家格式自家先验）；确定性由引擎保证
（同参数两次运行，剔除 created_at 后逐字节一致——tests 钉住）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simlab                                    # noqa: E402
from simlab.record import RecordError            # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SimLab：真实引擎 → 统一运行记录")
    ap.add_argument("experiment", nargs="?", help="实验名，如 b12-dijkstra")
    ap.add_argument("--params", default="{}", help="实验参数（JSON 对象）")
    ap.add_argument("--params-file", help="实验参数 JSON 文件（长参数用，优先于 --params）")
    ap.add_argument("--out", help="记录输出路径（缺省打到 stdout）")
    ap.add_argument("--list", action="store_true", help="列出可用实验")
    args = ap.parse_args(argv)

    if args.list or not args.experiment:
        names = sorted(simlab.ENGINES)
        print("可用实验：" + ("、".join(names) if names else "（无）"))
        return 0 if args.list else 2

    if args.params_file:
        try:
            params = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[!] --params-file 读不了：{exc}", file=sys.stderr)
            return 2
    else:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"[!] --params 不是合法 JSON：{exc.msg}", file=sys.stderr)
            return 2

    try:
        skeleton = simlab.run_experiment(args.experiment, params)
    except ValueError as exc:                    # 引擎守卫 + 未知实验名
        print(f"[!] {exc}", file=sys.stderr)
        return 2

    try:
        record = simlab.build(experiment=skeleton["experiment"],
                              title=skeleton["title"],
                              engine=skeleton["engine"],
                              params=skeleton["params"],
                              frames=skeleton["frames"],
                              metrics=skeleton["metrics"],
                              notes=skeleton.get("notes", ""))
    except RecordError as exc:
        print(f"[!] 适配器产出了不合法的记录：{exc}", file=sys.stderr)
        return 1

    if args.out:
        path = simlab.save(record, args.out)
        print(f"已写出 {path}：{len(record['frames'])} 帧，"
              f"指标 {sorted(record['metrics'])}")
    else:
        print(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
