"""tools/check_record.py —— 主题记录检查器：结构齐不齐 + 证据指针是不是真的

课程要点（技术雷达的自律）：记录最容易被写成"听到过什么"——检查器把"证据"
变成**可机验的指针**：反引号里的仓库路径必须存在，`@提交号` 必须在 git 里存在。
结构上强制五节齐备且有序（问题/原理/证据/局限/复现），来源字段必须诚实
（示例记录必须显式写"非真实来源"）。

用法：
    python tools/check_record.py <记录.md> [仓库根]
退出码 0 = 全部通过；1 = 有问题（逐条打印）。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REQUIRED_SECTIONS = ["问题", "原理", "证据（如何核验）", "局限与适用边界", "最小复现"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HASH_RE = re.compile(r"^@[0-9a-f]{7,40}$")


def _metadata(lines: list[str], start: int) -> dict[str, str]:
    """取 H1 与第一个 H2 之间的 `- 键：值` 行。"""
    meta: dict[str, str] = {}
    for line in lines[start:]:
        if line.startswith("## "):
            break
        m = re.match(r"^-\s*([^：:]+)[：:]\s*(.*)$", line)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
    return meta


def _sections(lines: list[str]) -> dict[str, tuple[int, str]]:
    """标题 → (行号, 该节正文)。按出现顺序，重复标题取首次。"""
    found: dict[str, tuple[int, str]] = {}
    current = None
    start = 0
    buf: list[str] = []
    for idx, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current is not None and current not in found:
                found[current] = (start, "\n".join(buf))
            current = m.group(1)
            start = idx
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None and current not in found:
        found[current] = (start, "\n".join(buf))
    return found


def check_record(path, repo_root) -> list[str]:
    """返回问题列表；空列表 = 通过。"""
    path = pathlib.Path(path)
    repo_root = pathlib.Path(repo_root)
    problems: list[str] = []
    if not path.is_file():
        return [f"记录文件不存在：{path}"]
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines or not lines[0].startswith("# 记录："):
        problems.append("第一行必须是 `# 记录：<主题>`（H1 标题）")
    meta = _metadata(lines, 1)
    for key in ("来源", "日期", "记录人"):
        if not meta.get(key):
            problems.append(f"元信息缺少或为空：{key}")
    if meta.get("日期") and not DATE_RE.match(meta["日期"]):
        problems.append(f"日期格式不是 YYYY-MM-DD：{meta['日期']!r}")
    source = meta.get("来源", "")
    if "示例" in source and "非真实来源" not in source:
        problems.append("来源自称示例，必须显式写「非真实来源」（诚实标注）")

    sections = _sections(lines)
    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        problems.append("缺少必需小节：" + "、".join(missing))
    order = [sections[s][0] for s in REQUIRED_SECTIONS if s in sections]
    if order != sorted(order):
        problems.append("必需小节的顺序不对（应为：问题 → 原理 → 证据 → 局限 → 复现）")

    evidence = sections.get("证据（如何核验）", (0, ""))[1]
    pointers = re.findall(r"`([^`]+)`", evidence)
    paths = [p for p in pointers if "/" in p and " " not in p and not p.startswith("http")]
    commits = [p for p in pointers if HASH_RE.match(p)]
    if not paths and not commits:
        problems.append("证据节没有任何可核验指针（反引号包住的 `路径` 或 `@提交号`）")
    for rel in paths:
        if not (repo_root / rel).exists():
            problems.append(f"证据路径在仓库里不存在：{rel}")
    for token in commits:
        sha = token[1:]
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "cat-file", "-e", f"{sha}^{{commit}}"],
                capture_output=True, text=True)
        except OSError:
            problems.append("找不到 git，无法核验 @提交号 证据（先装 git 再跑检查器）")
            break
        if proc.returncode != 0:
            problems.append(f"证据提交在 git 里不存在：{token}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("用法：python tools/check_record.py <记录.md> [仓库根]")
        return 2
    path = argv[1]
    if len(argv) == 3:
        repo_root = pathlib.Path(argv[2])
    else:
        repo_root = pathlib.Path(__file__).resolve().parents[3]   # tools/ → 项目 → projects/ → 仓库根
    problems = check_record(path, repo_root)
    if not problems:
        print(f"PASS：{path}")
        return 0
    print(f"RED：{path} 有 {len(problems)} 个问题")
    for item in problems:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
