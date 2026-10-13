@echo off
rem Studio P0 one-click: tests + demo (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
set PYTHONUTF8=1
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] Running test suite (26 tests: auth + matrix + uptime monitor + ws status push + lifecycles)...
python -m pytest tests -q
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo [2/2] Running four-part demo...
python demo.py
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo All green. To use the portal: python server.py --port 8017
echo login: owner, initial password in studio\data\password.txt
pause
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%