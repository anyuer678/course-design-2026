"""扫描每个项目的 run.bat，检查其引用的文件是否真的存在。

运行: python scan_refs.py   （在 projects/ 目录下执行）
这是仓库文化里"引用一个不存在的东西比留空更危险"的一次落实。
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
missing = []
TOOLS = {"g++.exe", "python", "python3", "javac", "java", "node", "mvn",
         "objdump", "gcc", "make", "pip", "wsl.exe"}

for bat in sorted(root.glob("*/run.bat")):
    d = bat.parent
    text = bat.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
    refs = set()
    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("rem") or ls.startswith("::") or not ls:
            continue
        for m in re.finditer(r"[\w./-]+\.(?:py|exe|json|s|cpp|asm|h)\b", line):
            refs.add(m.group(0))
        for m in re.finditer(r"(?:python|py|java|node)\s+([\w./-]+)", line):
            refs.add(m.group(1))
    for ref in sorted(refs):
        ref = ref.lstrip("./")
        if ref.startswith("-") or "." not in ref:
            continue               # 参数(-m/-c)和纯单词(not/make)不是文件引用
        if ref in TOOLS:
            continue
        if not (d / ref).exists() and not (d / "build" / ref).exists():
            missing.append(f"{bat} -> {ref}")

print("缺失引用:" if missing else "全部 run.bat 引用的文件都存在")
for m in missing:
    print(" ", m)

# 第二遍：交付物齐全度。上面那遍只看得見"有 run.bat 的项目"，
# 所以 B30 缺 run.bat/README 时它照样报"全部存在"——这是 2026-10-02 实测出的盲点。
# 判据分两级，都是量出来的（不是我想当然）：
#   硬性 = README.md + run.bat（16 个老项目全部都有，没有例外）
#   软性 = 演示入口与测试入口。各语言形态不同：Python 用 demo.py/tests，
#          C/C++/Java 的演示是 src 里的可执行程序，测试可能在 src 或 tests。
#          所以软性只报"没找到"，让人去看一眼，不冒充"这就是缺陷"。
HARD = ("README.md", "run.bat")
DEMO_HINTS = ("demo.py", "demo", "src", "programs", "msh", "out")
TEST_HINTS = ("tests", "src", "include")

print()
print("交付物齐全度（硬性=README.md+run.bat；软性=演示/测试入口，形态按语言不同）：")
hard_gaps = 0
for d in sorted(x for x in root.iterdir() if x.is_dir() and x.name[0] in "Bb" and x.name[1].isdigit()):
    missing_hard = [n for n in HARD if not (d / n).exists()]
    has_demo = any((d / n).exists() for n in DEMO_HINTS)
    has_test = any((d / n).exists() for n in TEST_HINTS) or bool(list(d.rglob("test_*.py")))         or bool(list(d.rglob("*_test.*")))
    notes = []
    if not has_demo:
        notes.append("没找到演示入口")
    if not has_test:
        notes.append("没找到测试入口")
    if missing_hard or notes:
        hard_gaps += 1
        tag = "缺硬性交付物" if missing_hard else "待人工确认"
        print(f"  [{tag}] {d.name}"
              + (f"：缺 {'、'.join(missing_hard)}" if missing_hard else "")
              + (f"；{'；'.join(notes)}" if notes and not missing_hard else ""))
print("全部项目的硬性交付物齐全" if hard_gaps == 0
      else f"共 {hard_gaps} 个项目需要处理（上面已标明是缺硬性交付物，还是软性入口待人工确认）")

# 第三遍：webkit 共享资产新鲜度（2026-10-05 轮九起）。
# 各产品的 web/assets/kb.css 是 webkit/kb.css 的同步副本——引用了一份过期的
# 共享样式与引用一个不存在的文件同样危险，所以并入本扫描：不一致即列出，
# 同步动作交给 scripts/sync_assets.py（本遍只报不写）。
print()
print("共享资产新鲜度（webkit/ -> 各产品 web/assets/）：")
src = Path(__file__).resolve().parents[1] / "webkit" / "kb.css"
if not src.is_file():
    print("  [缺] webkit/kb.css 不存在（共享样式唯一源丢失）")
    shared_stale = True
else:
    shared_stale = False
    for product in ("linkbox", "simlab", "datascope", "cachekv",
                    "sensorhub", "courselab", "studio"):
        dst = src.parent.parent / product / "web" / "assets" / "kb.css"
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            print(f"  [过期/缺] {dst.relative_to(src.parent.parent)}")
            shared_stale = True
print("全部产品与 webkit/kb.css 一致" if not shared_stale
      else "存在过期副本（跑 python scripts/sync_assets.py 同步）")
