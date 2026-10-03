@echo off
rem B8-mini-shell one-click entry (Windows side). Body is pure ASCII on purpose
rem (PLAN section 6). This shell needs fork/exec/pipes, so the real work runs in
rem WSL Ubuntu-24.04 via run.sh; this wrapper only locates WSL and checks results.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
chcp 65001 >nul
setlocal
set WSL_UTF8=1
set PYTHONUTF8=1
cd /d %~dp0

where wsl >nul 2>nul
if errorlevel 1 echo [!] wsl.exe not found. Install WSL2 with Ubuntu-24.04 first.
if errorlevel 1 exit /b 1

echo [1/3] WSL side: compile + dual-entry self-test + six-section demo (via run.sh)
wsl -d Ubuntu-24.04 -e bash -c "./run.sh"
if errorlevel 1 exit /b 1

echo.
echo [2/3] showcase page is fresh (web/showcase.html == recompute; recompute runs through WSL)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page tests (freshness / tamper / data pins; Windows-side entry)
python tests\showcase_check.py
if errorlevel 1 exit /b 1

echo.
echo Done (ran inside WSL Ubuntu-24.04). Interactive: open WSL in this folder and run ./build/msh
endlocal
exit /b 0
