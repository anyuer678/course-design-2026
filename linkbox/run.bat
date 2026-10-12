@echo off
rem LinkBox M1+M2 one-click: tests + demo (pure ASCII body, see PLAN section 6)
chcp 65001 >nul
set PYTHONUTF8=1
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/2] Running test suite (76 tests: product + QR)...
python -m unittest discover -s tests
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo [2/2] Running four-part demo...
python demo.py
if errorlevel 1 (echo [!] step failed & pause & exit /b 1)
echo.
echo All green. To use the product: python server.py --port 8018
echo then open http://127.0.0.1:8018/ in your browser.
pause
set EC=%ERRORLEVEL%
endlocal & exit /b %EC%