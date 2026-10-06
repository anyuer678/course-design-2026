@echo off
rem repo-wide health check one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from Python files.
rem Usage:
rem   check_all.bat         run the repo-wide health check (7 steps)
rem   check_all.bat deep    also run all 33 showcase test suites (slower)
rem   check_all.bat selftest   prove the checker itself goes red and green
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1
set EXTRA=

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 (echo [!] python not found in PATH. Install Python 3.10+ first. & pause & exit /b 1)

if /i "%~1"=="deep" set EXTRA=--deep
if /i "%~1"=="selftest" set EXTRA=--selftest

python scripts\check_all.py %EXTRA%
set EC=%ERRORLEVEL%
pause
endlocal & exit /b %EC%
