@echo off
rem scripts/start_all.bat - double-click entry: start the portal (8017) and
rem pull up all 8 managed products through it. Pair with stop_all.bat.
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1
python scripts\start_all.py
set EC=%ERRORLEVEL%
pause
endlocal & exit /b %EC%
