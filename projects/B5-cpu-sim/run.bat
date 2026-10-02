@echo off
rem B5-cpu-sim one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the C++ programs.
chcp 65001 >/dev/null
setlocal
cd /d %~dp0

where g++ >/dev/null 2>/dev/null
if errorlevel 1 echo [!] g++ not found in PATH. Run setup\add-mingw-path.ps1 first.
if errorlevel 1 exit /b 1

if not exist build mkdir build

echo [1/3] build and run the self-test (ISA / assembler / single-cycle / pipeline vs single-cycle)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_cpu.cpp -o build\tests.exe
if errorlevel 1 exit /b 1
build\tests.exe
if errorlevel 1 exit /b 1

echo.
echo [2/3] build the simulator and run the bubble-sort demo on both models
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src\main.cpp -o build\cpu-sim.exe
if errorlevel 1 exit /b 1
build\cpu-sim.exe programs\bubble.asm
if errorlevel 1 exit /b 1

echo.
echo [3/3] pipeline space-time chart (S = stall, F = flush)
build\cpu-sim.exe --chart programs\bubble.asm
if errorlevel 1 exit /b 1

echo.
echo Done. Try your own program: build\cpu-sim.exe --chart programs\loop.asm
endlocal
exit /b 0
