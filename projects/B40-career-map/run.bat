@echo off
rem B40-career-map one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
rem -u keeps stdout unbuffered so two runs can be log-diffed cleanly.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/3] unit tests (28: evidence checker positives/negatives, JD matching, honest-design pins)
python -u -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] demo (four sections; everything is file-driven, no timing output)
python -u demo.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Put real JDs into jd\ and run: python tools\map_jd.py --write
endlocal
exit /b 0
