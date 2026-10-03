@echo off
rem B29-bigdata-spark one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
rem -u (unbuffered) keeps stdout/stderr interleaving stable enough for log diffing.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

where java >nul 2>nul
if errorlevel 1 echo [!] java not found in PATH - Spark needs a JRE/JDK (17+).
if errorlevel 1 exit /b 1

python -c "import pyspark; print('[env] pyspark', pyspark.__version__)"
if errorlevel 1 echo [!] pyspark not installed. Run: pip install pyspark
if errorlevel 1 exit /b 1

echo [1/3] unit tests (25: ledger / parity vs pure Python / Spark SQL / skew correctness / showcase)
python -u -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/3] demo (six sections; section 6 prints measured timings, so two runs differ there only)
python -u demo.py
if errorlevel 1 exit /b 1

echo.
echo [3/3] showcase page is fresh (web/showcase.html == recompute)
python tools\showcase.py --check
if errorlevel 1 exit /b 1

echo.
echo Done. Note the PYSPARK_PYTHON pitfall: sparklab/session.py sets it to the full interpreter path
echo (this machine's python3 is a Microsoft Store stub - Spark workers cannot start with it).
endlocal
exit /b 0
