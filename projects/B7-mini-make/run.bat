@echo off
rem B7-mini-make one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem The original script appended a blank line to demo/src/greet.cpp on every run
rem (unbounded growth); this version touches the file's mtime instead.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/3] unit tests (15: parsing / ordering / incremental / building / logstat)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] incremental build demo: clean, full build, up to date, touch source, rebuild
python src\mm.py -f demo\Makefile clean
python src\mm.py -f demo\Makefile
python src\mm.py -f demo\Makefile
python -c "import os, time; os.utime('demo/src/greet.cpp', (time.time(), time.time()))"
python src\mm.py -f demo\Makefile
python src\mm.py -f demo\Makefile run
if errorlevel 1 exit /b 1
python src\mm.py -f demo\Makefile clean

echo.
echo [3/3] build log analysis demo (aggregate by message template)
python src\logstat.py demo\sample_build.log
if errorlevel 1 exit /b 1

echo.
echo Done. Try parallel + goals: python src\mm.py -f demo\Makefile -j 4 run
endlocal
exit /b 0
