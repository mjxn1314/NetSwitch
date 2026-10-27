@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges, please click "Yes" in the UAC window...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
set "PYEXE=D:\Program Files\Python314\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
"%PYEXE%" "%~dp0ip_address_changer.py"
if %errorlevel% neq 0 (
    echo.
    echo ============================================
    echo Program exited with an error. See message above.
    echo Press any key to close this window.
    pause >nul
)