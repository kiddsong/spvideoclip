import os
import sys
import shutil
import subprocess
import webbrowser
import importlib

REQUIRED_MODULES = [
    ("fastapi", "fastapi>=0.100.0"),
    ("uvicorn", "uvicorn>=0.22.0"),
    ("multipart", "python-multipart>=0.0.6"),
    ("numpy", "numpy>=1.23.0"),
    ("scipy", "scipy>=1.10.0"),
    ("librosa", "librosa>=0.10.0"),
    ("onnxruntime", "onnxruntime>=1.15.0"),
    ("sklearn", "scikit-learn>=1.2.0"),
    ("joblib", "joblib>=1.2.0"),
    ("tqdm", "tqdm>=4.65.0"),
    ("aiofiles", "aiofiles>=23.1.0"),
    ("jinja2", "jinja2>=3.1.0"),
]

def check_and_install_python_dependencies():
    """检查 Python 运行依赖，若缺失则自动执行 pip 安装"""
    missing = []
    for mod_name, pkg_spec in REQUIRED_MODULES:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pkg_spec)

    if missing:
        print("\n" + "=" * 65)
        print(" [环境检测] 检测到缺少必要的 Python 依赖组件，正在自动为您安装...")
        print(f" 待安装组件: {', '.join(missing)}")
        print("=" * 65 + "\n")

        requirements_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        cmd = [sys.executable, "-m", "pip", "install", "-r", requirements_file]

        try:
            # 优先尝试国内清华镜像源加速，若失败则走默认源
            install_cmd = cmd + ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            res = subprocess.run(install_cmd)
            if res.returncode != 0:
                print(" 正在尝试使用官方源重新安装...")
                subprocess.run(cmd, check=True)
            print("\n [环境检测] Python 依赖组件安装成功！\n")
        except Exception as e:
            print(f"\n [错误] 自动安装依赖失败: {e}")
            print(" 请尝试手动运行: pip install -r requirements.txt")
            input("\n 按回车键退出...")
            sys.exit(1)
    else:
        print(" [环境检测] Python 基础运行依赖检测正常。")

def check_and_guide_ffmpeg():
    """检查系统全局 FFmpeg / FFprobe 是否就绪"""
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None

    if not (ffmpeg_ok and ffprobe_ok):
        print("\n" + "!" * 65)
        print(" [核心组件缺失提示] 系统未检测到 FFmpeg 或 FFprobe！")
        print(" 本系统的音频提取、瞬态采样与音视频精准合并深度依赖 FFmpeg。")
        print("-" * 65)
        if sys.platform == "win32":
            print(" Windows 快速安装指引:")
            print(" 1. 使用 winget 一键安装（打开 PowerShell 运行）:")
            print("    winget install Gyan.FFmpeg")
            print(" 2. 或手动下载:")
            print("    前往 https://www.gyan.dev/ffmpeg/builds/ 下载 essentials 构建包")
            print("    解压并将 bin 目录路径添加至系统环境变量 Path 中。")
        elif sys.platform == "darwin":
            print(" macOS 安装指引: brew install ffmpeg")
        else:
            print(" Linux 安装指引: sudo apt update && sudo apt install ffmpeg")
        print("!" * 65 + "\n")
        input(" 请安装配置完成后按回车键继续...")
        # 再次检查
        if shutil.which("ffmpeg") is None:
            print(" 仍然未找到 ffmpeg，程序即将退出。")
            sys.exit(1)
    else:
        print(" [环境检测] FFmpeg 多媒体编解码组件检测正常。")

def main():
    print("=" * 65)
    print(" SPVideoClip 智能音频识别与定点剪辑合并系统 (v2.5.0)")
    print(" 正在进行运行环境与系统依赖自动检测...")
    print("=" * 65)

    check_and_install_python_dependencies()
    check_and_guide_ffmpeg()

    print("\n" + "=" * 65)
    print(" 环境检测完毕，系统正常启动中...")
    print(" 本地控制台地址: http://127.0.0.1:8000")
    print("=" * 65 + "\n")

    # 自动在默认浏览器中打开页面
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    import uvicorn
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)

if __name__ == "__main__":
    main()
