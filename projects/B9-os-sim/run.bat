@echo off
rem B9-os-sim one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the C++ programs.
chcp 65001 >nul
setlocal
cd /d %~dp0

where mingw32-make >nul 2>nul
if errorlevel 1 echo [!] mingw32-make not found in PATH (MinGW-w64 ships it as mingw32-make).
if errorlevel 1 exit /b 1

echo [1/4] build tests.exe and os-sim.exe
mingw32-make
if errorlevel 1 exit /b 1

echo.
echo [2/4] self-test: 183 assertions (scheduler / paging / banker / FAT / producer-consumer)
build\tests.exe
if errorlevel 1 exit /b 1

echo.
echo [3/4] demo: textbook numbers for every module
build\os-sim.exe
if errorlevel 1 exit /b 1

echo.
echo [4/4] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Try a single module with: build\os-sim.exe sched
endlocal
exit /b 0
