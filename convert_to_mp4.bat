@echo off
title SPVideoClip Batch Video Converter
cd /d "%~dp0"

echo [SPVideoClip] Checking environment...
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

ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [Error] FFmpeg not found in system PATH.
    echo Please install FFmpeg from https://www.gyan.dev/ffmpeg/builds/
    echo and add the bin folder to your system PATH.
    echo.
    pause
    exit /b 1
)

python convert_to_mp4.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] Process exited with error code %errorlevel%.
    pause
)
