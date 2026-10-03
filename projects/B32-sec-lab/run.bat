@echo off
rem B32-sec-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/5] unit tests (60: 50 core + 10 showcase page tests)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/5] core suite through the direct file entry (50; discover above = 50 + 10)
python tests\test_b32.py
if errorlevel 1 exit /b 1

echo.
echo [3/5] policy checks: SQL concat sites, registry both ways, scanner visibility
python -c "from sec32 import audit as A; s = A.summary(); print('      unregistered / stale registry entries:', s['audit_problems'] or 'none'); print('      concat sites found:', s['sql_sites']); print('      xss:', s['xss']); print('      traversal guarded escapes:', s['traversal']['by_handler']['guarded']['escaped'])"
if errorlevel 1 exit /b 1

echo.
echo [4/5] demo: six sections, numbers computed live
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [5/5] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Everything ran in memory and temp dirs; nothing new was left here.
endlocal
exit /b 0
