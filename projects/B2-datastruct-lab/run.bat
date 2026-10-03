@echo off
rem B2-datastruct-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the C++ programs.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where g++ >nul 2>nul
if errorlevel 1 echo [!] g++ not found in PATH. Install MinGW-w64 GCC and add it to PATH.
if errorlevel 1 exit /b 1

if not exist build mkdir build

echo [1/4] build and run the self-test (hand-computed edges + vs-std cross-check + menu script)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_ds.cpp -o build\tests.exe
if errorlevel 1 exit /b 1
build\tests.exe
if errorlevel 1 exit /b 1

echo.
echo [2/4] build and run the scripted demo (six sections, numbers computed live)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src\main.cpp -o build\datastruct.exe
if errorlevel 1 exit /b 1
build\datastruct.exe
if errorlevel 1 exit /b 1

echo.
echo [3/4] interactive menu smoke test (instant exit; run build\datastruct.exe --menu for real use)
echo 0 | build\datastruct.exe --menu
if errorlevel 1 exit /b 1

echo.
echo [4/4] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Interactive menu: build\datastruct.exe --menu
endlocal
exit /b 0
