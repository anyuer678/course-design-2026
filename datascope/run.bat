@echo off
rem DataScope one-click: double-entry tests (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
set PYTHONUTF8=1
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] pytest entry (31 tests: parse + profile + cleaning + mining + report + server)...
python -m pytest tests -q
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo [2/2] unittest discover entry...
python -m unittest discover -s tests
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo All green. Try: python run.py profile your.csv
pause
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%