@echo off
title SPVideoClip
cd /d "%~dp0"

echo [SPVideoClip] Starting environment check and server...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [Error] Python not found in system PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    echo and ensure "Add python.exe to PATH" is checked during installation.
    echo.
    pause
    exit /b 1
)

python run.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] Program exited with error code %errorlevel%.
    pause
)
