@echo off
rem B11-net-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/3] unit tests (102: 76 netlab + 16 stdlib comparison + 10 showcase page)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] demo: request journey / CRUD / keep-alive / boundary rejections / UDP / GBN sweep
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Run one module alone: python -m unittest tests.test_netlab -v
endlocal
exit /b 0
