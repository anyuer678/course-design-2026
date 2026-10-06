@echo off
rem Board one-click: compile + engine selfcheck + double-entry tests (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)
where javac >nul 2>nul
if errorlevel 1 (
    echo [!] javac not found in PATH. Install JDK 17 or newer first.
    exit /b 1
)

echo [1/3] compile engine (B14 paint) + product (board), release 17...
python compile_support.py
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo [2/3] pytest entry (11 tests: engine selfcheck 7054 + backup + daemon + launcher)...
python -m pytest tests -q
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo [3/3] unittest discover entry...
python -m unittest discover -s tests
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo All green. Open the paint window with: python launch.py --window
echo Managed daemon mode for Studio portal: python launch.py --port 8023
pause
endlocal
