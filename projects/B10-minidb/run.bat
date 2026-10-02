@echo off
rem 源码是 UTF-8，中文 Windows 默认代码页 936 会解析错乱/乱码
chcp 65001 >nul
rem B10-minidb 一键脚本：自测（含与 sqlite3 对拍）+ 全流程演示
setlocal
cd /d %~dp0
set PYTHONUTF8=1
where python >nul 2>nul || (echo [!] 找不到 python，请先安装 Python 3.10+ & exit /b 1)

echo [1/2] 自测：B+树 / 解析 / CRUD / 约束 / 事务 / 恢复 / JOIN + sqlite3 对拍...
python tests\test_minidb.py || exit /b 1

echo.
echo [2/2] 演示：CRUD → 计划器 → 约束与三值逻辑 → JOIN → 事务 → 崩溃恢复
echo.
python demo.py || exit /b 1
endlocal
