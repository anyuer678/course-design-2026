@echo off
rem scripts/scan_refs.bat - double-click entry: deliverable reference scan
rem Scans every project's run.bat for missing file references + delivery completeness.
chcp 65001 >nul
setlocal
cd /d %~dp0..
set PYTHONUTF8=1
python scripts\scan_refs.py projects
set EC=%ERRORLEVEL%
pause
endlocal & exit /b %EC%
