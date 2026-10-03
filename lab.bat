@echo off
rem showcase lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from Python files.
rem Usage:
rem   lab.bat             start the hub on 127.0.0.1:7788 and open the index page
rem   lab.bat no-open     start the hub only (no browser)
rem   lab.bat selftest    run the lab self-test (starts B31, sends a real request, stops it)
rem   lab.bat lan         bind 0.0.0.0 so LAN devices can browse the static pages
rem                       (control APIs stay loopback-only; remote callers get 403)
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

if /i "%~1"=="selftest" (
    python showcase\lab.py --selftest || exit /b 1
    exit /b 0
)

set EXTRA=
set OPENARG=%~1
if /i "%~1"=="lan" (
    set EXTRA=--lan
    set OPENARG=%~2
)

echo [1/2] checks passed: python in PATH, catalog and pages ready to serve
if /i "%OPENARG%"=="no-open" goto :serve
echo       opening http://127.0.0.1:7788/showcase/index.html in about 2 seconds
start "" /b python -c "import time,webbrowser; time.sleep(2); webbrowser.open('http://127.0.0.1:7788/showcase/index.html')"

:serve
echo [2/2] lab hub starting on http://127.0.0.1:7788/   (Ctrl+C stops it; child processes are cleaned up)
if defined EXTRA echo [!] LAN mode: static pages bound to 0.0.0.0; control APIs stay loopback-only (remote GET/POST get 403).
python showcase\lab.py %EXTRA% || (echo [!] lab exited with an error ^(port 7788 busy? see the message above^) & exit /b 1)
echo.
echo Lab stopped. All child processes were cleaned up.
endlocal
exit /b 0
