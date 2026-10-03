@echo off
rem B12-algo-arena one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads batch files by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >nul 2>nul || (echo [!] python not found in PATH. Install Python 3.10+ first. & exit /b 1)

echo [1/3] unit tests (66: five paradigms vs brute force, plus showcase page)
python -m unittest discover -s tests || exit /b 1

echo.
echo [2/3] demo (DP table and traceback - three greedy variants - N-queens - Dijkstra snapshots - timing)
python demo.py || exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check || exit /b 1

echo.
echo Done. Full timing run: python experiments.py (about 45 s)
endlocal
exit /b 0
