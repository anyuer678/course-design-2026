@echo off
rem scripts/walkthrough_day1.bat - double-click entry: P-acceptance Day-1
rem walkthrough (portal + 8 products, machine-checkable user stories).
rem Evidence markdown lands in p-??/ (dated).
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1
python scripts\walkthrough_day1.py
set EC=%ERRORLEVEL%
pause
endlocal & exit /b %EC%
