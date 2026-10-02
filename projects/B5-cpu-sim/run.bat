@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会解析错乱/乱码
chcp 65001 >nul
rem B5-cpu-sim 一键脚本：自测 + 流水线时空图演示
setlocal
cd /d %~dp0
where g++ >nul 2>nul
if errorlevel 1 (
    echo [!] 在 PATH 中找不到 g++，请先运行 setup\add-mingw-path.ps1。
    exit /b 1
)
if not exist build mkdir build
echo [1/2] 编译 + 自测...
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude tests\test_cpu.cpp -o build\tests.exe || exit /b 1
build\tests.exe || exit /b 1
echo.
echo [2/2] 流水线时空图演示...
g++ -std=c++17 -O2 -Wall -Wextra -static -Iinclude src\main.cpp -o build\cpu-sim.exe || exit /b 1
build\cpu-sim.exe --chart programs\bubble.asm
endlocal
