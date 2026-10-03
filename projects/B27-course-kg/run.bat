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

echo [1/3] test suite (21: 14 core + 7 showcase; discover)...
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] Running four-part demo (HTML goes to a temp dir)...
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo All green. See README.md for the knowledge map and exercises.
endlocal
