@echo off
rem B33-viz-algo one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
rem -u keeps stdout unbuffered so two runs can be log-diffed cleanly.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where g++ >nul 2>nul
if errorlevel 1 echo [!] g++ not found in PATH. Install MinGW-w64 GCC and add it to PATH.
if errorlevel 1 exit /b 1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

if not exist ..\B2-datastruct-lab\include\ds\trace.hpp echo [!] B33 needs B2 headers: ..\B2-datastruct-lab\include\ds\trace.hpp
if not exist ..\B2-datastruct-lab\include\ds\trace.hpp exit /b 1
if not exist build\traces mkdir build\traces

echo [1/3] compile the exporter against B2 headers and export sort/bfs/dfs traces
g++ -std=c++17 -O2 -Wall -Wextra -static -I..\B2-datastruct-lab\include tools\export_trace.cpp -o build\export_trace.exe
if errorlevel 1 exit /b 1
build\export_trace.exe build\traces
if errorlevel 1 exit /b 1

echo.
echo [2/3] unit tests (11: trace fidelity vs independent replay / page structure / JS syntax)
python -u -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [3/3] demo (export, replay check, HTML build, node syntax check)
python -u demo.py
if errorlevel 1 exit /b 1

echo.
echo Done. Open build\viz.html in a browser to watch the animations (paused/step/play).
endlocal
exit /b 0
