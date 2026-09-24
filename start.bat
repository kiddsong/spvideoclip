@echo off
title VideoClip
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

echo [1/2] Checking dependencies...
pip install -r requirements.txt -q

echo.
echo [2/2] Starting server...
echo URL: http://127.0.0.1:8000
echo.

python run.py

pause
