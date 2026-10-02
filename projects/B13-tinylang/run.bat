@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会把提示解析成乱码
chcp 65001 >nul
rem B13-tinylang 一键脚本：逐层自测 + 两条执行路径对拍 + 样例程序 + 流水线演示
setlocal
cd /d %~dp0
rem Python 默认按本地代码页写标准输出，重定向时中文和 ∞ 会编码失败
set PYTHONUTF8=1
where python >nul 2>nul || (echo [!] 找不到 python，请先安装 Python 3.10+ & exit /b 1)

echo [1/3] 自测：词法/语法/语义/代码生成/VM 逐层，再跑 300 个随机程序对拍...
python tests\test_tinylang.py || exit /b 1
python tests\test_against_reference.py || exit /b 1

echo.
echo [2/3] 样例程序：六个正常样例 + 三个故意写错的样例（退出码必须如预期）...
for %%f in (gcd collatz sum_of_squares types_and_print short_circuit scope_shadow) do (
    python tiny.py programs\%%f.tiny || exit /b 1
)

call :expect_exit error_syntax 2
if errorlevel 1 exit /b 1
call :expect_exit error_types 2
if errorlevel 1 exit /b 1
call :expect_exit error_runtime 1
if errorlevel 1 exit /b 1

echo.
echo [3/3] 演示：全链逐阶段 → 语义选择 → 错误定位 → 两路径对拍 → 样例
echo.
python demo.py || exit /b 1

echo.
echo 全部完成。单独看某个阶段：python tiny.py programs\gcd.tiny --asm
goto :eof

:expect_exit
rem 参数 1：样例名（不含 .tiny）；参数 2：期望退出码。编译/运行错误必须传非 0，否则等于报错被吞了
python tiny.py programs\%1.tiny >nul 2>&1
if "%ERRORLEVEL%"=="%2" (
    echo   %1.tiny 退出码 %ERRORLEVEL%（符合预期）
    exit /b 0
)
echo   [!] %1.tiny 期望退出码 %2，实际 %ERRORLEVEL%
exit /b 1
