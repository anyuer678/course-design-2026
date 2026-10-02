@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会把提示解析成乱码
chcp 65001 >nul
rem B12-algo-arena 一键脚本：自测（穷举与暴力对拍）+ 演示（含 quick 档规模计时）
setlocal
cd /d %~dp0
rem Python 默认按本地代码页写标准输出，重定向时中文和 ∞ 会编码失败
set PYTHONUTF8=1
where python >nul 2>nul || (echo [!] 找不到 python，请先安装 Python 3.10+ & exit /b 1)

echo [1/2] 自测：分治 / DP / 贪心 / 回溯 / 图 / 计时工具，逐一与暴力与参照实现对拍...
python tests\test_algo.py || exit /b 1

echo.
echo [2/2] 演示：DP 表与方案还原 → 三种贪心的对照 → N 皇后解数表 → Dijkstra 每轮快照 → 规模计时
echo.
python demo.py || exit /b 1

echo.
echo 全部完成。完整计时档：python experiments.py（约 45 秒）
endlocal
