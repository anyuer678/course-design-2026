@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会把提示解析成乱码
chcp 65001 >nul
rem B11-net-lab 一键脚本：自测（含与标准库对拍）+ 全流程演示
setlocal
cd /d %~dp0
rem Python 默认按本地代码页写标准输出，重定向时中文演示会崩
set PYTHONUTF8=1
where python >nul 2>nul || (echo [!] 找不到 python，请先安装 Python 3.10+ & exit /b 1)

echo [1/2] 自测：HTTP 解析边界、服务器与多路复用、资源回收、UDP 与 GBN、stdlib 对拍...
python tests\test_netlab.py || exit /b 1
python tests\test_against_stdlib.py || exit /b 1

echo.
echo [2/2] 演示：一条请求的旅程 → CRUD → keep-alive 与并发 → 越界拒绝 → UDP → GBN 丢包实验
echo.
python demo.py || exit /b 1

echo.
echo 全部完成。想单独看某个模块：python -m unittest tests.test_netlab -v
endlocal
