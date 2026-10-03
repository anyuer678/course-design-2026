"""Batch ⑤: wire the showcase step into B8/B11/B32 run.bat (ASCII + CRLF)."""
from pathlib import Path

BASE = Path(r"C:\Users\30816\Desktop\课设\projects")


def write_crlf(path: Path, text: str) -> None:
    assert all(ord(c) < 128 for c in text), f"{path.name}: non-ascii introduced"
    path.write_bytes(text.replace("\n", "\r\n").encode("ascii"))
    print(f"{path.parent.name}/{path.name}: written, {len(text)} chars")


def patch(project: str, pairs) -> None:
    path = BASE / project / "run.bat"
    raw = path.read_bytes().decode("ascii")
    assert raw.count("\n") == raw.count("\r\n") == raw.count("\r"), f"{project}: line endings"
    text = raw.replace("\r\n", "\n")
    for old, new in pairs:
        assert text.count(old) == 1, f"{project}: pattern not unique/found: {old[:60]!r}"
        text = text.replace(old, new)
    write_crlf(path, text)


# ---------------------------------------------------------------- B11 (full rewrite)
b11 = """@echo off
rem B11-net-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\\dev\\null here.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/3] unit tests (101: 75 netlab + 16 stdlib comparison + 10 showcase page)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] demo: request journey / CRUD / keep-alive / boundary rejections / UDP / GBN sweep
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Run one module alone: python -m unittest tests.test_netlab -v
endlocal
exit /b 0
"""
write_crlf(BASE / "B11-net-lab" / "run.bat", b11)

# ---------------------------------------------------------------- B32 (renumber + add step)
patch("B32-sec-lab", [
    ("echo [1/4] unit tests (50 assertions over four labs plus the static scanner)",
     "echo [1/5] unit tests (60: 50 core + 10 showcase page tests)"),
    ("echo [2/4] same suite through the direct file entry (dual entry, same count expected)",
     "echo [2/5] core suite through the direct file entry (50; discover above = 50 + 10)"),
    ("echo [3/4] policy checks", "echo [3/5] policy checks"),
    ("echo [4/4] demo: six sections, numbers computed live",
     "echo [4/5] demo: six sections, numbers computed live"),
    ("python demo.py\nif errorlevel 1 exit /b 1\n\necho.\necho Done. Everything ran in memory and temp dirs; nothing new was left here.",
     "python demo.py\nif errorlevel 1 exit /b 1\n\n"
     "echo.\necho [5/5] showcase page is fresh (web/showcase.html == recompute)\n"
     "python tools\\showcase.py --check\nif errorlevel 1 exit /b 1\n\n"
     "echo.\necho Done. Everything ran in memory and temp dirs; nothing new was left here."),
])

# ---------------------------------------------------------------- B8 (split WSL step + add two showcase steps)
patch("B8-mini-shell", [
    ("set WSL_UTF8=1\ncd /d %~dp0",
     "set WSL_UTF8=1\nset PYTHONUTF8=1\ncd /d %~dp0"),
    ("wsl -d Ubuntu-24.04 -e bash -c \"./run.sh\"\nif errorlevel 1 exit /b 1\n\necho.\necho Done (ran inside WSL Ubuntu-24.04). Interactive: open WSL in this folder and run ./build/msh",
     "echo [1/3] WSL side: compile + dual-entry self-test + six-section demo (via run.sh)\n"
     "wsl -d Ubuntu-24.04 -e bash -c \"./run.sh\"\nif errorlevel 1 exit /b 1\n\n"
     "echo.\necho [2/3] showcase page is fresh (web/showcase.html == recompute; recompute runs through WSL)\n"
     "python tools\\showcase.py --check\nif errorlevel 1 exit /b 1\n\n"
     "echo.\necho [3/3] showcase page tests (freshness / tamper / data pins; Windows-side entry)\n"
     "python tests\\showcase_check.py\nif errorlevel 1 exit /b 1\n\n"
     "echo.\necho Done (ran inside WSL Ubuntu-24.04). Interactive: open WSL in this folder and run ./build/msh"),
])
print("all run.bat patches applied")
