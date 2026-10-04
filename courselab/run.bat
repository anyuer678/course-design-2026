@echo off
rem CourseLab launcher. Body is pure ASCII on purpose (same rule as the repo root lab.bat).
chcp 65001 >/dev/null
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >/dev/null 2>/dev/null
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

if /i "%~1"=="selftest" (
    python server.py --selftest || exit /b 1
    exit /b 0
)

echo [1/2] python in PATH; starting hub on http://127.0.0.1:7900/
start "" /b python -c "import time,webbrowser; time.sleep(1.5); webbrowser.open('http://127.0.0.1:7900/')"
echo [2/2] Ctrl+C stops it.
python server.py || (echo [!] courselab exited with an error ^(port 7900 busy?^) & exit /b 1)
endlocal
exit /b 0
