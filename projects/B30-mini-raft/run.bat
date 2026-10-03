@echo off
rem B30-mini-raft one-click: tests + demo (pure ASCII body, see PLAN section 6)
rem The project is a single-process event-driven Raft SIMULATION plus a real-socket
rem mini-RPC. It is not a multi-process cluster; README states the red line.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/4] Unit tests via unittest discovery...
python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

echo.
echo [2/4] Unit tests via direct entry (catches import-order mistakes)...
python tests\test_b30.py
if errorlevel 1 exit /b 1

echo.
echo [3/4] Eight-part demo (all numbers computed at runtime)...
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [4/4] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo All green. See README.md for the knowledge map, limits and exercises.
endlocal
