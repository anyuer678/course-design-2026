@echo off
rem B27-course-kg one-click: tests + demo (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] Running test suite (14 tests)...
python tests\test_kg.py
if errorlevel 1 exit /b 1

echo.
echo [2/2] Running four-part demo (HTML goes to a temp dir)...
python demo.py
if errorlevel 1 exit /b 1

echo.
echo All green. See README.md for the knowledge map and exercises.
endlocal
