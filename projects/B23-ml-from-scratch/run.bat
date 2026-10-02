@echo off
rem B23-ml-from-scratch one-click: tests + demo (body kept pure ASCII on purpose,
rem see PLAN section 6 for the cmd byte-offset / codepage pitfalls)
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] Running test suite (33 tests, gradient check included)...
python tests\test_ml.py
if errorlevel 1 exit /b 1

echo.
echo [2/2] Running five-part demo...
python demo.py
if errorlevel 1 exit /b 1

echo.
echo All green. See README.md for the knowledge map and exercises.
endlocal
