"""datascope/xlsx.py —— 最小 xlsx（OOXML SpreadsheetML）读取器，零依赖。

xlsx 本相是一个 zip 容器：xl/workbook.xml 按序列工作表、
xl/_rels/workbook.xml.rels 把 r:id 映到工作表 XML 路径、
xl/sharedStrings.xml 是字符串池、工作表里 <c r="B3" t="s"><v>12</v></c>
用"列字母+行号"寻址、属性 t 决定 <v> 怎么解读。stdlib 的
zipfile + xml.etree 足以读完这一套——不引 openpyxl。

只做"读第一张表 → Table（值一律字符串）"这一件事：与 parse_csv 同一出口，
下游画像/清洗/挖掘管线零改动。故意不做的（都要写进文档而不是装支持）：
- 多表：取 workbook 声明顺序的第一张；
- 日期：Excel 把日期存成"序列号 + 样式"，解出人类可读日期要解析 styles.xml
  的 numFmt 体系——v1 如实给序列号；
- 公式：读缓存值（<v>），不重算。

安全口径（zip 炸弹）：zip 解压后的大小是无界的，一个 42KB 的恶意 xlsx 能
声明上亿行——行数/列数/单元格总数三重上限，超限 ValueError 拒收。
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_ROWS = 100_000          # 数据行上限（表头除外）
MAX_COLS = 256              # 列上限（一张表不该比一张 Excel 老底稿还宽）
MAX_CELLS = 2_000_000       # 单元格总数上限（行×列之外的第三道闸）

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_REF_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def _local(tag: str) -> str:
    """去命名空间：'{ns}row' -> 'row'。"""
    return tag.rsplit("}", 1)[-1]


def _col_index(letters: str) -> int:
    """Excel 列字母 → 0 基序号：A=0、Z=25、AA=26（双射 26 进制）。"""
    n = 0
    for ch in letters:
        if not "A" <= ch <= "Z":
            raise ValueError(f"列字母不认识：{letters!r}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _num_to_str(raw: str) -> str:
    """数字单元格 → 表内字符串：整数值去掉 .0（42 存作 "42" 而非 "42.0"），
    其余保留 Excel 原文（float 重格式化只会引入噪声）。"""
    try:
        value = float(raw)
    except ValueError:
        return raw
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return raw


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """读 sharedStrings.xml：<si> 可以是纯 <t>，也可以是富文本 runs——
    统一取后代所有 <t> 拼接（富文本只关心内容不关心样式）。"""
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root:
        if _local(si.tag) != "si":
            continue
        out.append("".join(t.text or "" for t in si.iter()
                           if _local(t.tag) == "t"))
    return out


def _sheet_paths(zf: zipfile.ZipFile) -> list[str]:
    """workbook.xml 的 sheet 顺序 + rels 映射 → 工作表 part 路径列表。"""
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
    except KeyError as exc:
        raise ValueError("不是有效的 xlsx：缺 xl/workbook.xml") from exc
    rels = {}
    try:
        rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rel_root:
            if _local(rel.tag) == "Relationship":
                rels[rel.get("Id", "")] = rel.get("Target", "")
    except KeyError:
        pass
    paths = []
    for sheet in wb.iter():
        if _local(sheet.tag) != "sheet":
            continue
        rid = sheet.get(f"{_REL_NS}id", "")
        target = rels.get(rid, "")
        if not target:
            raise ValueError(f"工作表 {sheet.get('name', '?')!r} 没有可解析的关系映射")
        target = target.lstrip("/")                 # 绝对 target（/xl/...）与相对统一
        if not target.startswith("xl/"):
            target = "xl/" + target                 # rels 的 Target 相对 xl/ 而言
        paths.append(target)
    if not paths:
        raise ValueError("不是有效的 xlsx：workbook 里没有工作表")
    return paths


def parse_xlsx_bytes(data: bytes, *, max_rows: int = MAX_ROWS,
                     max_cols: int = MAX_COLS,
                     max_cells: int = MAX_CELLS) -> "Table":
    """读 xlsx 字节 → 第一张表 → Table（值一律字符串，口径与 parse_csv 一致）。

    首个非空行是表头；列宽以表头为准（右侧多出的单元格截弃，与 csv.DictReader
    的多余列处理同口径）；数据行右侧缺的列补空串；全空行跳过。
    不是 zip / 缺部件 / 空表 / 超上限 → ValueError（路由层翻译 400）。
    """
    from datascope.dataset import Table               # 底部导入避免环

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("不是 xlsx：文件不是 zip 容器（xlsx 本相是 zip）") from None
    with zf:
        shared = _shared_strings(zf)
        sheet_path = _sheet_paths(zf)[0]
        try:
            sheet = ET.fromstring(zf.read(sheet_path))
        except KeyError as exc:
            raise ValueError(f"不是有效的 xlsx：缺 {sheet_path}") from exc

        rows: list[dict[int, str]] = []
        cell_count = 0
        for row_el in sheet.iter():
            if _local(row_el.tag) != "row":
                continue
            values: dict[int, str] = {}
            for c in row_el:
                if _local(c.tag) != "c":
                    continue
                cell_count += 1
                if cell_count > max_cells:
                    raise ValueError(f"单元格总数超过上限 {max_cells}（疑似 zip 炸弹）")
                ref = c.get("r", "")
                m = _REF_RE.match(ref)
                if m is None:                   # 无 ref 的 cell：spec 允许，按位置数太脆，
                    continue                    # 直接忽略（空单元格本来就等价于缺列）
                idx = _col_index(m.group(1))
                values[idx] = _cell_text(c, shared)
            if values:
                rows.append(values)

        if not rows:
            raise ValueError("工作表是空的（连表头都没有）")

        header_map = rows[0]
        width = max(header_map) + 1
        if width > max_cols:
            raise ValueError(f"列数 {width} 超过上限 {max_cols}")
        columns = [header_map.get(i, "") for i in range(width)]
        if any(not name.strip() for name in columns):
            raise ValueError("表头有空列名（Excel 里删列请连单元格一起删）")

        out_rows = []
        for values in rows[1:]:
            if all(v.strip() == "" for v in values.values()):
                continue                        # 全空行跳过（与 CSV 口径一致）
            if len(out_rows) >= max_rows:
                raise ValueError(f"数据行超过上限 {max_rows}（疑似 zip 炸弹）")
            out_rows.append({name: values.get(i, "").strip()
                             for i, name in enumerate(columns)})
        return Table(columns, out_rows)


def _cell_text(c, shared: list[str]) -> str:
    """按 t 属性解读 <v>/<is>；t 缺省按数字。"""
    t = c.get("t", "n")
    if t == "inlineStr":                        # <c t="inlineStr"><is><t>..</t></is>
        return "".join(el.text or "" for el in c.iter()
                       if _local(el.tag) == "t")
    v = next((el for el in c if _local(el.tag) == "v"), None)
    raw = v.text if v is not None and v.text is not None else ""
    if t == "s":                                # 字符串池下标
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            raise ValueError(f"字符串池下标越界：{raw!r}") from None
    if t == "b":                                # 布尔：0/1 → FALSE/TRUE
        return "TRUE" if raw == "1" else "FALSE"
    if t == "str":                              # 公式缓存字符串
        return raw
    return _num_to_str(raw)                     # n / d / e：数字按数字，其余原文
