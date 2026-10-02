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

echo [1/3] Full test suite via unittest discovery (45 tests: 33 core + 12 sklearn compare)...
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] Direct entries (core file + sklearn compare file)...
python tests\test_ml.py
if errorlevel 1 exit /b 1
python tests\test_sklearn_compare.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] Six-part demo (core five parts are stdlib-only; part six needs scikit-learn)...
python demo.py
if errorlevel 1 exit /b 1

echo.
echo All green. See README.md for the knowledge map, install scope and exercises.
endlocal
