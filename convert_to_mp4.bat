@echo off
title SPVideoClip Batch Video Converter
cd /d "%~dp0"

:: 极速启动 Python 主程序，所有环境检查与任务库检测在主程序中秒级呈现
python convert_to_mp4.py

if %errorlevel% neq 0 (
    echo.
    echo [Error] Process exited with error code %errorlevel%.
    pause
)
