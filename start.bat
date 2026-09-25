@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
set "result=%ERRORLEVEL%"

if not "%result%"=="0" (
    echo.
    echo Zapret2 WebControl stopped with an error. See the message above.
    pause
)

exit /b %result%
