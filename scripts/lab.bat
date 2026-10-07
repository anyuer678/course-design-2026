@echo off
rem showcase lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from Python files.
rem Usage (argument order does not matter):
rem   lab.bat             start the hub on 127.0.0.1:7788 and open the index page
rem   lab.bat no-open     start the hub only (no browser)
rem   lab.bat lan         bind 0.0.0.0 so LAN devices can browse the static pages
rem                       (control APIs stay loopback-only; remote callers get 403)
rem   lab.bat selftest    run the lab self-test (starts B31, sends a real request, stops it)
rem If a hub is already running, lab.bat reuses it and just reopens the page
rem (exit 0, not an error).
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

set LANFLAG=
set OPENFLAG=--open
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="selftest" goto :selftest
if /i "%~1"=="lan" set LANFLAG=--lan
if /i "%~1"=="no-open" set OPENFLAG=
shift
goto :parse

:selftest
python showcase\lab.py --selftest
set EC=%ERRORLEVEL%
pause
exit /b %EC%

:parsed
echo [1/2] checks passed: python in PATH, catalog and pages ready to serve
echo [2/2] lab hub on http://127.0.0.1:7788/   (Ctrl+C stops it; child processes are cleaned up)
if defined LANFLAG echo [!] LAN mode: static pages bound to 0.0.0.0; control APIs stay loopback-only (remote GET/POST get 403).
python showcase\lab.py %LANFLAG% %OPENFLAG% || (echo [!] lab exited with an error ^(port 7788 busy? see the message above^) & pause & exit /b 1)
echo.
echo Lab stopped. All child processes were cleaned up.
pause
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%
exit /b 0
