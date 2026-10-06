"""datascope/dataset.py —— 数据表：CSV 解析、列画像、导出。

表示：Table = 列名列表 + 行字典列表（值一律字符串，清洗层负责类型转换——
CSV 本来就只有文本，假装它有类型是后续一切坑的来源）。
画像（profile）推断每列的类型与缺失情况，是清洗配方的前置依据。
"""
from __future__ import annotations

import csv
from pathlib import Path


class Table:
    def __init__(self, columns: list[str], rows: list[dict]):
        self.columns = list(columns)
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def column(self, name: str) -> list[str]:
        if name not in self.columns:
            raise KeyError(f"列 {name!r} 不存在，可用：{self.columns}")
        return [row.get(name, "") for row in self.rows]

    def to_csv(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            self.to_csv_stream(f)
        return path

    def to_csv_stream(self, f) -> None:
        """写到已打开的文本文件对象（服务端字符串导出复用）。"""
        writer = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(self.rows)


def parse_csv_text(text: str) -> Table:
    """解析 CSV 文本（服务端 API 用）：口径与 parse_csv 一致。"""
    import io
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise ValueError("CSV 是空的（没有表头）")
    columns = [name.strip() for name in reader.fieldnames]
    if any(not name for name in columns):
        raise ValueError("表头有空列名")
    rows = []
    for raw in reader:
        if all((v or "").strip() == "" for v in raw.values()):
            continue
        row = {}
        for key in columns:
            raw_key = next((k for k in raw if k and k.strip() == key), None)
            row[key] = (raw[raw_key] or "") if raw_key is not None else ""
        rows.append(row)
    return Table(columns, rows)


def parse_csv(path: str | Path) -> Table:
    """读 CSV 文件：首行为表头；空行跳过；值保持字符串；BOM 兼容。"""
    return parse_csv_text(Path(path).read_text(encoding="utf-8-sig"))


def profile(table: Table) -> dict:
    """列画像：推断类型（int/float/text）、缺失数、去重数、数值列的 min/max。

    类型判定口径：全列（非缺失值）都能当 int 读 → int；都能当 float → float；
    否则 text。空串算缺失，不参与类型判定。bool 不许冒充 int（B23/B31 教训）。
    """
    out = {}
    for name in table.columns:
        values = table.column(name)
        missing = sum(1 for v in values if v.strip() == "")
        present = [v for v in values if v.strip() != ""]
        distinct = len(set(present))
        kind = "text"
        lo = hi = None
        if present:
            try:
                nums = [int(v) for v in present]
                kind, lo, hi = "int", min(nums), max(nums)
            except ValueError:
                try:
                    nums = [float(v) for v in present]
                    kind, lo, hi = "float", min(nums), max(nums)
                except ValueError:
                    pass
        out[name] = {"type": kind, "missing": missing, "distinct": distinct,
                     "min": lo, "max": hi}
    return out
