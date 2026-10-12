@echo off
rem BoardWeb one-click: tests + server smoke (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
set PYTHONUTF8=1
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] Running test suite (13 tests: doc/backup/img/safety + ws board)...
python -m pytest tests -q
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo All green. Try: python server.py --port 8025
pause
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%
