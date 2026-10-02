@echo off
rem B13-tinylang one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/4] unit tests (lexer/parser/semantics/codegen/vm/call-frames + 300 random programs)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/4] sample programs and the four error samples
python -c "import pathlib, subprocess, sys; names = ['gcd', 'collatz', 'sum_of_squares', 'types_and_print', 'short_circuit', 'scope_shadow', 'fib', 'hanoi', 'ackermann', 'binomial']; bad = [n for n in names if subprocess.run([sys.executable, 'tiny.py', 'programs/' + n + '.tiny']).returncode]; sys.exit(1 if bad else 0)"
if errorlevel 1 exit /b 1
python check_exits.py
if errorlevel 1 exit /b 1

echo.
echo [3/4] stress: 300 random programs + recursion cross-check, both engines byte for byte
python tests\test_against_reference.py
if errorlevel 1 exit /b 1
python tests\test_recursion.py
if errorlevel 1 exit /b 1

echo.
echo [4/4] demo (whole chain stage by stage, seven sections)
python demo.py
if errorlevel 1 exit /b 1

echo.
echo Done. Next hand-run step: python tiny.py programs\gcd.tiny --asm
endlocal
exit /b 0
