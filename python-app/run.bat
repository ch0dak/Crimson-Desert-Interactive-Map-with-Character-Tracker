@echo off
cd /d "%~dp0"
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
