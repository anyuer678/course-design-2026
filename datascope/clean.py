"""datascope/clean.py —— 清洗步骤库 + 配方执行器：每一步都是一笔账（B26 纪律）。

配方（recipe）= 有序步骤列表：[{"op": "drop_duplicates"}, {"op": "fill_missing",
"column": "amount", "strategy": "mean"}, ...]。
账本（report.steps）记录每步的 rows_before/rows_after 与改动计数——
"每一步到底删了什么"不许糊过去（B26 clean.py 的核心思想）。

已知边界：值一律字符串进出（类型转换用 to_number 步骤显式做）。
"""
from __future__ import annotations

from .dataset import Table, profile


class RecipeError(ValueError):
    """配方不合法（未知操作/缺参数/列不存在），problems 一次报全。"""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def _require(table: Table, op: str, params: dict, fields: tuple) -> None:
    for field in fields:
        if field not in params:
            raise RecipeError([f"{op} 缺少参数 {field!r}"])
    for field, value in params.items():
        if field == "column" and value not in table.columns:
            raise RecipeError([f"{op}：列 {value!r} 不存在，可用：{table.columns}"])


def _empty(value: str) -> bool:
    return value.strip() == ""


# ---------------------------------------------------------------- 步骤实现
def _drop_duplicates(table: Table, params: dict) -> tuple[Table, dict]:
    seen = set()
    rows = []
    for row in table.rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return Table(table.columns, rows), {"duplicates_removed": len(table) - len(rows)}


def _drop_empty_rows(table: Table, params: dict) -> tuple[Table, dict]:
    column = params.get("column")
    _require(table, "drop_empty_rows", params, ())
    if column is not None:
        kept = [r for r in table.rows if not _empty(r.get(column, ""))]
    else:
        kept = [r for r in table.rows
                if not any(_empty(v) for v in r.values())]
    return Table(table.columns, kept), {"empty_rows_removed": len(table) - len(kept)}


def _fill_missing(table: Table, params: dict) -> tuple[Table, dict]:
    _require(table, "fill_missing", params, ("column", "strategy"))
    column, strategy = params["column"], params["strategy"]
    values = [v for v in table.column(column) if not _empty(v)]
    if strategy == "mean":
        try:
            fill_value = str(round(sum(float(v) for v in values) / len(values), 4))
        except ValueError:
            raise RecipeError(
                [f"fill_missing：列 {column!r} 不是数值列，mean 只对数值列有意义"]) from None
    elif strategy == "mode":
        fill_value = max(set(values), key=values.count) if values else ""
    elif strategy == "value":
        if "value" not in params:
            raise RecipeError(["fill_missing：strategy=value 需要 value 参数"])
        fill_value = str(params["value"])
    else:
        raise RecipeError([f"fill_missing：strategy 只能是 mean/mode/value，"
                           f"收到 {strategy!r}"])
    rows = [{**r, column: (fill_value if _empty(r.get(column, "")) else r.get(column, ""))}
            for r in table.rows]
    filled = sum(1 for a, b in zip(table.rows, rows) if a.get(column) != b.get(column))
    return Table(table.columns, rows), {"cells_filled": filled, "fill_value": fill_value}


def _trim(table: Table, params: dict) -> tuple[Table, dict]:
    column = params.get("column")
    _require(table, "trim", params, ())
    targets = [column] if column else table.columns
    rows = []
    for row in table.rows:
        new_row = dict(row)
        for name in targets:
            if name in new_row:
                new_row[name] = new_row[name].strip()
        rows.append(new_row)
    changed = sum(1 for a, b in zip(table.rows, rows) if a != b)
    return Table(table.columns, rows), {"rows_trimmed": changed}


def _drop_column(table: Table, params: dict) -> tuple[Table, dict]:
    _require(table, "drop_column", params, ("column",))
    column = params["column"]
    columns = [c for c in table.columns if c != column]
    rows = [{k: v for k, v in row.items() if k != column} for row in table.rows]
    return Table(columns, rows), {"column_dropped": column}


def _to_number(table: Table, params: dict) -> tuple[Table, dict]:
    _require(table, "to_number", params, ("column",))
    column = params["column"]
    on_error = params.get("on_error", "fail")
    if on_error not in ("fail", "blank"):
        raise RecipeError([f"to_number：on_error 只能是 fail/blank，收到 {on_error!r}"])
    problems, converted_rows = [], []
    converted = blanked = 0
    for index, row in enumerate(table.rows):
        value = row.get(column, "")
        new_row = dict(row)
        if _empty(value):
            new_row[column] = ""
        else:
            try:
                new_row[column] = str(float(value)) if any(
                    c in value for c in ".eE") else str(int(value))
                converted += 1
            except ValueError:
                if on_error == "fail":
                    problems.append(
                        f"to_number：第 {index + 1} 行（数据行）的 {column}={value!r} 不是数字")
                else:
                    new_row[column] = ""
                    blanked += 1
        converted_rows.append(new_row)
    if problems:
        raise RecipeError(problems)
    changed = sum(1 for a, b in zip(table.rows, converted_rows)
                  if a.get(column) != b.get(column))
    return Table(table.columns, converted_rows), {
        "cells_converted": converted, "cells_blanked": blanked,
        "cells_changed": changed}


STEPS = {
    "drop_duplicates": _drop_duplicates,
    "drop_empty_rows": _drop_empty_rows,
    "fill_missing": _fill_missing,
    "trim": _trim,
    "drop_column": _drop_column,
    "to_number": _to_number,
}


def apply_recipe(table: Table, recipe: list) -> tuple[Table, dict]:
    """按序执行配方，返回 (清洗后的表, 报告)。报告含前后画像与逐步账本。"""
    if not isinstance(recipe, list) or not recipe:
        raise RecipeError(["recipe 必须是非空步骤数组"])
    problems = [f"第 {i + 1} 步 {step.get('op')!r} 不是对象" for i, step in
                enumerate(recipe) if not isinstance(step, dict)]
    known_steps = [(i, step) for i, step in enumerate(recipe)
                   if isinstance(step, dict) and step.get("op") in STEPS]
    unknown = [f"第 {i + 1} 步 op={step.get('op')!r} 未知，可用：{sorted(STEPS)}"
               for i, step in enumerate(recipe)
               if isinstance(step, dict) and step.get("op") not in STEPS]
    # 已知步骤的参数错误也预检：列名对着当前表头核（一次报全，不挤牙膏）
    for i, step in known_steps:
        op = step["op"]
        params = {k: v for k, v in step.items() if k != "op"}
        for field in ("column",):
            if field in params and isinstance(params[field], str) \
                    and params[field] not in table.columns:
                problems.append(f"第 {i + 1} 步 {op}：列 {params[field]!r} 不存在，"
                                f"可用：{table.columns}")
    if problems or unknown:
        raise RecipeError(problems + unknown)

    current = table
    steps_ledger = []
    for index, step in enumerate(recipe):
        op, params = step["op"], {k: v for k, v in step.items() if k != "op"}
        before = len(current)
        current, counts = STEPS[op](current, params)
        steps_ledger.append({
            "step": index + 1, "op": op, "params": params,
            "rows_before": before, "rows_after": len(current),
            "counts": counts,
        })
    report = {
        "rows_before": len(table),
        "rows_after": len(current),
        "profile_before": profile(table),
        "profile_after": profile(current),
        "steps": steps_ledger,
    }
    return current, report
