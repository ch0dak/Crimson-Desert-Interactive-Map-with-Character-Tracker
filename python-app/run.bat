@echo off
cd /d "%~dp0"

:: Self-elevate: relaunch as admin if not already
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process cmd '/c \"%~f0\"' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

echo === CD Map Tracker ===
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

echo Checking dependencies...
pip install -q -r requirements.txt

echo.
echo Starting tracker (requires Administrator)...
echo Press Ctrl+C to stop.
echo.
python main.py
pause
