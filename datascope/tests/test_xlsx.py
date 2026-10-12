"""datascope/xlsx.py 自测：内存组装 xlsx（zip+XML 手写 fixture，不落二进制文件），
覆盖 字符串池/富文本/inlineStr/布尔/数字取整、多表取第一、稀疏单元格、
全空行跳过、坏输入四类（非 zip / 缺部件 / 空表 / 空表头）、zip 炸弹三道闸、
API /api/import/xlsx 全链路（webframe 直调）。
"""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import datascope
from datascope.xlsx import (MAX_CELLS, MAX_COLS, MAX_ROWS,  # noqa: F401
                            _col_index, parse_xlsx_bytes)


def build_xlsx(grid, *, extra_parts=None, skip=()):
    """grid: 行列表，每行 [值, ...]；str → sharedStrings，数值/bool 原生。
    返回 xlsx 字节。skip 可丢掉部件模拟坏文件。"""
    shared, s_idx = [], {}

    def sid(text):
        if text not in s_idx:
            s_idx[text] = len(shared)
            shared.append(text)
        return s_idx[text]

    def cell_xml(ref, value):
        """Python 值 → 一个 <c>：str 走字符串池、bool 走 t="b"、数值走缺省 n。"""
        if value is None:
            return ""
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
        if isinstance(value, str):
            return f'<c r="{ref}" t="s"><v>{sid(value)}</v></c>'
        return f'<c r="{ref}"><v>{value}</v></c>'

    def ref(r, c):
        letters = ""
        n = c + 1
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(ord("A") + rem) + letters
        return f"{letters}{r + 1}"

    rows_xml = []
    for r, row in enumerate(grid):
        cells = "".join(cell_xml(ref(r, c), v) for c, v in enumerate(row))
        rows_xml.append(f'<row r="{r + 1}">{cells}</row>')
    sheet = (f'<?xml version="1.0"?>'
             f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>')
    ss = ('<?xml version="1.0"?>'
          '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          f'count="{len(shared)}" uniqueCount="{len(shared)}">'
          + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
    parts = {
        "xl/workbook.xml":
            '<?xml version="1.0"?><workbook '
            'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="数据" sheetId="1" r:id="rId1"/>'
            '<sheet name="另一张" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels":
            '<?xml version="1.0"?><Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet2.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/sharedStrings.xml": ss,
    }
    parts.update(extra_parts or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in parts.items():
            if name not in skip:
                zf.writestr(name, data)
    return buf.getvalue()


GRID = [
    ["商品", "数量", "金额", "有货"],
    ["键盘", 2, 199.9, True],
    ["鼠标", 1, 59, False],
    [None, None, None, None],          # 全空行：应跳过
    ["数据线", 3, 19.9, True],
]


class TestColIndex(unittest.TestCase):
    def test_letters(self):
        for letters, want in [("A", 0), ("Z", 25), ("AA", 26),
                              ("AZ", 51), ("BA", 52)]:
            self.assertEqual(_col_index(letters), want, letters)


class TestParseXlsx(unittest.TestCase):
    def test_roundtrip_types(self):
        table = parse_xlsx_bytes(build_xlsx(GRID))
        self.assertEqual(table.columns, ["商品", "数量", "金额", "有货"])
        self.assertEqual(len(table), 3)                        # 全空行被跳过
        self.assertEqual(table.rows[0],
                         {"商品": "键盘", "数量": "2", "金额": "199.9", "有货": "TRUE"})
        self.assertEqual(table.rows[1]["金额"], "59")          # 整数不带 .0
        self.assertEqual(table.rows[1]["有货"], "FALSE")
        # 出口同 CSV：画像直接可用
        p = datascope.profile(table)
        self.assertEqual(p["数量"]["type"], "int")
        self.assertEqual(p["金额"]["type"], "float")

    def test_first_sheet_only(self):
        """workbook 声明两张，读的必须是第一张（rId1 → sheet1.xml）。"""
        second = ('<?xml version="1.0"?><worksheet '
                  'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>不该被读</t></is>'
                  '</c></row></sheetData></worksheet>')
        table = parse_xlsx_bytes(build_xlsx(GRID, extra_parts={
            "xl/worksheets/sheet2.xml": second}))
        self.assertEqual(table.columns[0], "商品")

    def test_inline_string_cell(self):
        """字符串池缺失时 inlineStr 也要能读（WPS 导出常见）；富文本 runs 拼接。"""
        sheet = ('<?xml version="1.0"?><worksheet '
                 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>名称</t></is></c>'
                 '</row><row r="2"><c r="A1" t="inlineStr"><is><t>富文本甲'
                 '<r><t>乙</t></r></t></is></c></row></sheetData></worksheet>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml",
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<sheets><sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            zf.writestr("xl/worksheets/sheet1.xml", sheet)
        table = parse_xlsx_bytes(buf.getvalue())
        self.assertEqual(table.columns, ["名称"])
        # 富文本 <is> 里混排的 runs 取后代 <t> 拼接（fixture 故意写成嵌套）
        self.assertEqual(table.rows[0]["名称"].replace("\n", ""), "富文本甲乙")

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):                  # 不是 zip
            parse_xlsx_bytes(b"plain csv,text\n1,2\n")
        with self.assertRaises(ValueError):                  # 缺 workbook
            parse_xlsx_bytes(build_xlsx(GRID, skip=("xl/workbook.xml",)))
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as zf:
            zf.writestr("xl/workbook.xml",
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<sheets/></workbook>')
        with self.assertRaises(ValueError):                  # 没有工作表
            parse_xlsx_bytes(empty.getvalue())
        # 表头有空列名：表头行 A1="a"、C1="c"（B1 缺格）→ 中间列是空名，拒收
        sparse = ('<?xml version="1.0"?><worksheet '
                  'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>a</t></is></c>'
                  '<c r="C1" t="inlineStr"><is><t>c</t></is></c></row>'
                  '<row r="2"><c r="A1"><v>1</v></c></row></sheetData></worksheet>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml",
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<sheets><sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            zf.writestr("xl/worksheets/sheet1.xml", sparse)
        with self.assertRaises(ValueError):
            parse_xlsx_bytes(buf.getvalue())

    def test_zip_bomb_guards(self):
        wide = [["c%d" % i for i in range(300)]] + [[1] * 300]
        with self.assertRaises(ValueError):                  # 列数闸
            parse_xlsx_bytes(build_xlsx(wide), max_cols=256)
        many = [["h"], *[[i] for i in range(50)]]            # 行数闸（注入上限覆盖默认值）
        with self.assertRaises(ValueError):
            parse_xlsx_bytes(build_xlsx(many), max_rows=10)
        # 单元格总数闸：一行 300 格 × max_cells 边界
        with self.assertRaises(ValueError):
            parse_xlsx_bytes(build_xlsx(wide), max_cols=1000, max_cells=100)


class TestImportApi(unittest.TestCase):
    """POST /api/import/xlsx：字节 → CSV 文本（webframe 直调，与 TestReportDataApi 同法）。"""

    def setUp(self):
        from datascope.server import build_app
        self.app = build_app()

    def handle(self, method, path, body=b"", headers=None):
        from netlab.http1 import Request
        req = Request(method=method, target=path, version="1.1",
                      headers=[(k.lower(), v) for k, v in list(headers or [])],
                      body=body, path=path.split("?")[0],
                      query=[tuple(p.split("=", 1)) if "=" in p else (p, "")
                             for p in path.split("?")[1].split("&")] if "?" in path else [],
                      keep_alive=False, content_length=len(body))
        return self.app.handle(req)

    def test_import_roundtrip(self):
        status, _, body = self.handle(
            "POST", "/api/import/xlsx", body=build_xlsx(GRID),
            headers=[("Content-Type",
                      "application/vnd.openxmlformats-officedocument"
                      ".spreadsheetml.sheet")])
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["columns"], ["商品", "数量", "金额", "有货"])
        self.assertEqual(data["rows"], 3)
        self.assertIn("键盘,2,199.9,TRUE", data["csv"])
        # 转出的 CSV 能直接走既有画像端点——全链路闭环
        status, _, body = self.handle(
            "POST", "/api/profile", body=data["csv"].encode("utf-8"),
            headers=[("Content-Type", "text/csv")])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["rows"], 3)

    def test_import_rejects_garbage(self):
        status, _, body = self.handle(
            "POST", "/api/import/xlsx", body=b"not a zip",
            headers=[("Content-Type", "application/octet-stream")])
        self.assertEqual(status, 400)
        self.assertIn("zip", json.loads(body)["error"])
        status, _, body = self.handle(
            "POST", "/api/import/xlsx", body=b"",
            headers=[("Content-Type", "application/octet-stream")])
        self.assertEqual(status, 400)
        status, _, body = self.handle(
            "POST", "/api/import/xlsx", body=b"x",
            headers=[("Content-Type", "text/html")])
        self.assertEqual(status, 415)


if __name__ == "__main__":
    unittest.main(verbosity=2)
