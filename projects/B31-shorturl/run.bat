@echo off
rem B31-shorturl one-click entry. Keep every line before the first echo ASCII-only:
rem cmd re-reads the batch file by byte offset, so multi-byte text in this preamble
rem can make it resume in the middle of a line and try to execute a Chinese fragment.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set B31_PORT=8000

where python >nul 2>nul || (echo [!] python not found & exit /b 1)

echo [1/4] 环境检查
python --version
python -c "import b31, netlab, sqlite3, sys; print('      Python', sys.version.split()[0], '| SQLite', sqlite3.sqlite_version); print('      复用 B11 的 netlab：', b31.B11_DIR)" || exit /b 1

echo.
echo [2/4] 运行测试（unittest，无第三方依赖）
python -m unittest discover -s tests || exit /b 1

echo.
echo [3/4] 演示：短码生成、URL 关卡、原始响应字节、状态码、keep-alive、影子模型
python demo.py || exit /b 1

if /i "%~1"=="no-server" (
    echo.
    echo [4/4] 已按 no-server 跳过启动服务。要人工验证页面，直接跑：run.bat
    echo.
    echo 全部完成。测试与演示都在临时目录里建数据库，项目目录没有留下新文件。
    exit /b 0
)

echo.
echo [4/4] 启动短链服务：http://127.0.0.1/%B31_PORT%/
echo       请在浏览器里打开上面这个地址，依次试：
echo       1 在输入框里贴一个长地址，点“生成短链” —— 页面显示短链与命中数 0
echo       2 点那条短链 —— 浏览器跳到目标地址，回来刷新列表命中数加一
echo       3 只填别名不填地址，或者填 javascript 开头的地址 —— 页面应给出中文报错而不是崩溃
echo       4 用同一个别名再建一次 —— 应显示“已被占用”
echo       5 按 Ctrl+C 结束服务
echo       页面效果、样式和手感只能由你看，这一项我不替你勾。
python -m b31.server --port %B31_PORT%

echo.
echo 服务已退出。保存过的数据在 data 目录里的 shorturl.sqlite。
endlocal
