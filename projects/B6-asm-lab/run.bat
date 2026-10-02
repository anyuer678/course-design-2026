@echo off
rem B6-asm-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
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
if not exist build\asm mkdir build\asm

echo [1/3] assemble the four .s files + ABI probe, build and run the self-test
gcc -c asm\reverse.s -o build\asm\reverse.o
if errorlevel 1 exit /b 1
gcc -c asm\fib.s -o build\asm\fib.o
if errorlevel 1 exit /b 1
gcc -c asm\sort.s -o build\asm\sort.o
if errorlevel 1 exit /b 1
gcc -c asm\stackframe.s -o build\asm\stackframe.o
if errorlevel 1 exit /b 1
gcc -c tests\abi_probe.s -o build\asm\abi_probe.o
if errorlevel 1 exit /b 1
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_asm.cpp build\asm\reverse.o build\asm\fib.o build\asm\sort.o build\asm\stackframe.o build\asm\abi_probe.o -o build\tests.exe
if errorlevel 1 exit /b 1
build\tests.exe
if errorlevel 1 exit /b 1

echo.
echo [2/3] build and run the demo (five sections, numbers computed live)
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src\main.cpp build\asm\reverse.o build\asm\fib.o build\asm\sort.o build\asm\stackframe.o build\asm\abi_probe.o -o build\asm-lab.exe
if errorlevel 1 exit /b 1
build\asm-lab.exe
if errorlevel 1 exit /b 1

echo.
echo [3/3] disassembly structure check (registers and stack frames, via objdump)
python tools\disasm_check.py
if errorlevel 1 exit /b 1

echo.
echo Done. Read the README pitfalls section - the 32-bit long trap is in there.
endlocal
exit /b 0
