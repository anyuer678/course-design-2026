@echo off
rem B1-cpp-ministl one-click entry. Body is pure ASCII on purpose (PLAN section 6):
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

echo [1/3] build and run the self-test (boundaries + RAII + todo round-trip + vs-std cross-check)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_ministl.cpp -o build\tests.exe
if errorlevel 1 exit /b 1
build\tests.exe
if errorlevel 1 exit /b 1

echo.
echo [2/3] build and run the 5-section demo (containers / todo app / cross-check summary)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src\main.cpp -o build\ministl-demo.exe
if errorlevel 1 exit /b 1
build\ministl-demo.exe
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Edit include\mini\string.hpp and re-run: the self-test is built to catch regressions.
endlocal
exit /b 0
