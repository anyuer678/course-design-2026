"""datascope —— P4 数据工作台的地基（PRODUCTS.md §五 轮四之一）：CSV 导入 + 画像 + 清洗管线。

立场（零件库原则 + B26 的账本纪律）：
    - **报告即账本**（B26 clean.py 的核心思想继承）：每个清洗步骤的计数
      都是"动过多少行/格"的账，报表不是文案；
    - 通用 CSV 清洗层是 DataScope 自己的产品代码（B26 的清洗链是销售专用
      教学件，硬编码商品表，不适合作通用引擎——如实区分，不硬凑复用）；
    - 挖掘引擎（mining.py）**import B26 真实实现**：Apriori/K-means 零重写；
    - 轮四（三）出 SVG 报告；本轮交付：解析、画像、清洗步骤库、挖掘适配、服务。
"""
from __future__ import annotations

import sys
from pathlib import Path

_B26 = Path(__file__).resolve().parents[1] / "projects" / "B26-datamining"
if str(_B26) not in sys.path:
    sys.path.insert(0, str(_B26))

from .dataset import Table, parse_csv, parse_csv_text, profile  # noqa: E402,F401
from .clean import RecipeError, apply_recipe         # noqa: E402,F401
from .xlsx import parse_xlsx_bytes                   # noqa: E402,F401

__all__ = ["Table", "parse_csv", "parse_csv_text", "profile",
           "apply_recipe", "RecipeError", "parse_xlsx_bytes"]
