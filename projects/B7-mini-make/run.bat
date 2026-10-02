@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会解析错乱/乱码
chcp 65001 >nul
rem B7-mini-make 一键脚本：自测 + 增量构建演示 + 日志分析演示
setlocal
cd /d %~dp0
rem Python 默认按 GBK 写标准输出，重定向到文件时中文演示会崩
set PYTHONUTF8=1
where python >nul 2>nul || (echo [!] 找不到 python & exit /b 1)

echo [1/3] 自测...
python tests\test_mini_make.py || exit /b 1

echo.
echo [2/3] 增量构建演示（干净起步 → 全量 → up to date → 改源码增量）...
if exist build rmdir /s /q build
python src\mm.py -f demo\Makefile || exit /b 1
python src\mm.py -f demo\Makefile || exit /b 1
echo. >> demo\src\greet.cpp
python src\mm.py -f demo\Makefile || exit /b 1
build\greet.exe || exit /b 1

echo.
echo [3/3] 编译日志分析演示...
python src\logstat.py demo\sample_build.log

echo.
echo 全部完成！试试: python src\mm.py -f demo\Makefile -j 4 clean run
endlocal
