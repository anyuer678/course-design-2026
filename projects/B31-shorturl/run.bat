@echo off
rem B31-shorturl one-click entry. Pure ASCII body (see PLAN section 6):
rem cmd re-reads the batch file by byte offset, so multi-byte text can make it
rem resume in the middle of a line and try to execute a Chinese fragment.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set B31_PORT=8000

where python >nul 2>nul || (echo [!] python not found & exit /b 1)

echo [1/5] Environment check
python --version
python -c "import b31, netlab, sqlite3, sys; print('      Python', sys.version.split()[0], '| SQLite', sqlite3.sqlite_version); print('      Reusing netlab from B11:', b31.B11_DIR)" || exit /b 1

echo.
echo [2/5] Test suite (unittest, no third-party deps)
python -m unittest discover -s tests || exit /b 1

echo.
echo [3/5] Demo: short codes, URL gate, raw response bytes, status, keep-alive, shadow model
python demo.py || exit /b 1

echo.
echo [4/5] Showcase freshness (web/showcase.html vs recomputed, byte-exact)
python tools\showcase.py --check || exit /b 1

if /i "%~1"=="no-server" (
    echo.
    echo [5/5] Skipped server start per no-server flag. To try the page by hand: run.bat
    echo.
    echo All done. Tests and demo build their databases in temp dirs; no new files in the project.
    exit /b 0
)

echo.
echo [5/5] Starting short-url server: http://127.0.0.1/%B31_PORT%/
echo       Open the address above in a browser, then try in order:
echo       1 paste a long URL and click the button -- you get a short link with hits=0
echo       2 click that short link -- browser jumps to the target; back and refresh: hits=1
echo       3 alias-only, or a javascript: URL -- the page must show an error, not crash
echo       4 create the same alias again -- it must report already taken
echo       5 press Ctrl+C to stop the server
echo       Look and feel can only be judged by you; I will not tick that box for you.
python -m b31.server --port %B31_PORT%

echo.
echo Server exited. Saved data lives in data/shorturl.sqlite.
endlocal
