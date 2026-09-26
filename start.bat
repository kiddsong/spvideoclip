@echo off
chcp 65001 >nul
title SPVideoClip 智能剪辑系统
cd /d "%~dp0"

echo =====================================================================
echo  SPVideoClip 智能音频识别与定点剪辑合并系统 (v2.5.0)
echo  正在检查启动环境...
echo =====================================================================

:: 1. 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [错误] 未在系统环境变量中检测到 Python！
    echo 请安装 Python 3.10 或更高版本，并在安装时务必勾选 "Add python.exe to PATH"。
    echo 官方下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 2. 检查 FFmpeg 环境
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [提示] 系统未检测到 FFmpeg 编解码器！
    echo 正在尝试通过 Windows 官方包管理器 (winget) 为您自动安装...
    winget install --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        echo [注意] 自动安装失败，请手动下载安装 FFmpeg 并加入系统环境变量 PATH:
        echo 下载地址: https://www.gyan.dev/ffmpeg/builds/
        echo.
        pause
    ) else (
        echo [成功] FFmpeg 安装完成！
    )
)

:: 3. 运行主程序 (主程序内部自带模块级自愈与一键镜像加速安装)
python run.py

if %errorlevel% neq 0 (
    echo.
    echo 程序运行已结束或异常退出。
    pause
)
