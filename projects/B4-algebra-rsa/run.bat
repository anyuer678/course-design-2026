@echo off
rem B4-algebra-rsa one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
rem Null device is >nul - the bash-style >/dev/null would create C:\dev\null here.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/2] unit tests (43: egcd / modpow / phi / crt / primes / RSA / groups / sets)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/2] demo (six sections, numbers computed live)
python demo.py
if errorlevel 1 exit /b 1

echo.
echo Done. See README.md for scope, red lines and G2 exercises.
endlocal
exit /b 0
