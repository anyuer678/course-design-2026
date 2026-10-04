@echo off
rem Remove the CourseLab logon scheduled task created by install_autostart.bat.
setlocal
set TASKNAME=CourseLab
schtasks /delete /tn "%TASKNAME%" /f
if errorlevel 1 (
    echo [!] no task named "%TASKNAME%" (or access denied). Nothing to remove.
    exit /b 1
)
echo Task "%TASKNAME%" removed.
endlocal
exit /b 0
