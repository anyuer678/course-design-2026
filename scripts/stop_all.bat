@echo off
rem scripts/stop_all.bat - double-click entry: stop all 8 products through the
rem portal, then stop the portal itself and verify every port is closed.
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1
python scripts\stop_all.py
set EC=%ERRORLEVEL%
pause
endlocal & exit /b %EC%
