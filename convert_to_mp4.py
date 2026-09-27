#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SPVideoClip 视频批量转码与格式统一工具 (Batch Transcoder)
--------------------------------------------------------------
功能说明:
1. 自动递归遍历当前脚本所在文件夹及所有子文件夹（递归至最深层）。
2. 使用 ffprobe 智能检测每个视频的真实编码格式。
3. 自动筛选出无法被 SPVideoClip (浏览器 H5) 直接原生播放的视频格式：
   - 非 MP4 容器格式 (如 .wmv, .asf, .rm, .rmvb, .avi, .flv, .mkv, .mpg, .vob, .ts 等)
   - 虽为 .mp4/.m4v 但视频编码不是 H.264 (如 H.265/HEVC, MPEG-4, XviD, VP9 等)
   - 音频非 AAC/MP3 兼容格式
4. 采用 FFmpeg 高画质（CRF 19 + H.264 + AAC + faststart）转码为完美兼容的 MP4。
5. 智能支持快速转封装（若视频已是 H.264，仅容器格式老旧，直接秒速 -c copy 换封装）。
6. 安全机制：转码 100% 成功确认后才删除原文件，用新 MP4 替换（保持主文件名不变），确保数据绝对安全。
"""

import os
import sys
import json
import shutil
import subprocess
import time
from typing import Dict, Any, Optional, Tuple

# 常见视频扩展名列表
VIDEO_EXTENSIONS = {
    ".wmv", ".asf", ".rm", ".rmvb", ".avi", ".flv", ".f4v",
    ".mkv", ".mov", ".mpg", ".mpeg", ".mpe", ".m2v", ".vob",
    ".dat", ".3gp", ".3g2", ".ts", ".mts", ".m2ts", ".webm",
    ".mp4", ".m4v"
}

def format_size(size_bytes: int) -> str:
    """人类可读的文件大小格式化"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def format_duration(seconds: float) -> str:
    """格式化时长为分秒"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}小时{m:02d}分{s:02d}秒"
    return f"{m:02d}分{s:02d}秒"

def check_ffmpeg() -> bool:
    """检查系统环境是否有 ffmpeg 和 ffprobe"""
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    return ffmpeg_ok and ffprobe_ok

def probe_video(file_path: str) -> Optional[Dict[str, Any]]:
    """使用 ffprobe 探测视频详细元数据"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height",
        "-of", "json",
        file_path
    ]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None

        data = json.loads(res.stdout)
        format_info = data.get("format", {})
        duration = float(format_info.get("duration", 0.0))
        size_bytes = int(format_info.get("size", os.path.getsize(file_path)))

        v_codec = ""
        a_codec = ""
        width = 0
        height = 0

        for stream in data.get("streams", []):
            stype = stream.get("codec_type")
            if stype == "video" and not v_codec:
                v_codec = stream.get("codec_name", "").lower()
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
            elif stype == "audio" and not a_codec:
                a_codec = stream.get("codec_name", "").lower()

        return {
            "v_codec": v_codec,
            "a_codec": a_codec,
            "duration": duration,
            "size_bytes": size_bytes,
            "width": width,
            "height": height
        }
    except Exception:
        return None

def is_spvideoclip_native(file_path: str, info: Dict[str, Any]) -> bool:
    """
    判断该视频是否能被 SPVideoClip (现代浏览器) 原生流畅播放。
    标准：容器为 MP4/M4V 且 视频编码为 H.264 (avc1) 且 音频编码为 AAC/MP3。
    """
    ext = os.path.splitext(file_path)[1].lower()
    v_codec = info.get("v_codec", "")
    a_codec = info.get("a_codec", "")

    if ext in [".mp4", ".m4v"]:
        if v_codec in ["h264", "avc1"] and a_codec in ["aac", "mp3", ""]:
            return True
    return False

def can_stream_copy(info: Dict[str, Any]) -> bool:
    """如果视频轨道已经是标准 H.264，可走极速转封装，节省大量时间"""
    v_codec = info.get("v_codec", "")
    return v_codec in ["h264", "avc1"]

def transcode_video(src_path: str, dst_path: str, info: Dict[str, Any]) -> bool:
    """
    执行视频转码，优先根据编码特征选择极速换封装或高画质重编码
    """
    temp_dst = dst_path + ".converting_temp.mp4"
    if os.path.exists(temp_dst):
        try:
            os.remove(temp_dst)
        except Exception:
            pass

    # 1. 如果视频本身就是 H.264 编码，只需将音频转为 AAC 并换封装为 MP4 (只需几秒)
    if can_stream_copy(info):
        print("  -> 检测到视频轨道已为 H.264 编码，启用【极速转封装模式】(画质零损失，秒级完成)...")
        cmd = [
            "ffmpeg", "-y",
            "-i", src_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            temp_dst
        ]
    else:
        # 2. 老旧编码（WMV, RM, MPEG, XviD, H.265等），走高质量 H.264 重编码
        # CRF=19 接近无损的高保真画质，preset=fast 保证良好速度
        print(f"  -> 检测到非原生视频编码 ({info.get('v_codec') or '未知'})，启用【高质量 H.264 原画重编码】...")
        cmd = [
            "ffmpeg", "-y",
            "-i", src_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-movflags", "+faststart",
            temp_dst
        ]

    try:
        start_time = time.time()
        # 启动转码进程
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        _, stderr_text = proc.communicate()

        cost_time = time.time() - start_time

        # 检查是否成功
        if proc.returncode == 0 and os.path.exists(temp_dst) and os.path.getsize(temp_dst) > 1024:
            # 安全替换：
            # 若源文件扩展名不是 .mp4，先删除原文件，再重命名 temp -> dst_path
            # 若源文件本身是 .mp4（重编码同名替换），先删除原文件再重命名
            src_abs = os.path.abspath(src_path)
            dst_abs = os.path.abspath(dst_path)

            if os.path.exists(src_abs):
                os.remove(src_abs)

            if os.path.exists(dst_abs) and src_abs != dst_abs:
                os.remove(dst_abs)

            os.rename(temp_dst, dst_abs)
            print(f"  √ 转换成功！耗时: {cost_time:.1f} 秒")
            return True
        else:
            print(f"  × 转码失败 (FFmpeg 退出码: {proc.returncode})")
            if stderr_text:
                for line in stderr_text.splitlines()[-5:]:
                    print(f"    [FFmpeg] {line}")
            if os.path.exists(temp_dst):
                try:
                    os.remove(temp_dst)
                except Exception:
                    pass
            return False

    except Exception as e:
        print(f"  × 执行转码时发生异常: {e}")
        if os.path.exists(temp_dst):
            try:
                os.remove(temp_dst)
            except Exception:
                pass
        return False

def scan_directory(root_dir: str) -> Tuple[list, list]:
    """递归遍历根目录下的所有视频文件"""
    need_transcode = []
    already_compatible = []

    print(f"\n[1/3] 正在深度扫描目录: {root_dir}")
    print("      (包含所有层级的子文件夹，请稍候...)")

    total_scanned = 0
    for current_root, dirs, files in os.walk(root_dir):
        # 忽略临时文件夹和隐藏文件夹
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["__pycache__", "venv", "node_modules"]]

        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                total_scanned += 1
                full_path = os.path.join(current_root, filename)

                info = probe_video(full_path)
                if not info:
                    # 探测失败的文件列入需修复/转码队列
                    need_transcode.append((full_path, {"v_codec": "unknown", "a_codec": "unknown", "size_bytes": os.path.getsize(full_path)}))
                    continue

                if is_spvideoclip_native(full_path, info):
                    already_compatible.append((full_path, info))
                else:
                    need_transcode.append((full_path, info))

    print(f"      扫描完毕！共检测到 {total_scanned} 个视频文件。")
    print(f"      - 已经完全兼容原生播放: {len(already_compatible)} 个 (无需处理)")
    print(f"      - 需转码统一为标准 MP4: {len(need_transcode)} 个")
    return need_transcode, already_compatible

def main():
    print("=" * 70)
    print(" SPVideoClip 视频格式统一工具 —— 递归批量转码为标准 H.264 MP4")
    print("=" * 70)

    # 1. 检查运行环境
    if not check_ffmpeg():
        print("\n[错误] 系统未检测到 FFmpeg 或 FFprobe！")
        print("本转码工具深度依赖 FFmpeg。请确保已安装 FFmpeg 并已添加至系统环境变量 PATH。")
        print("下载地址: https://www.gyan.dev/ffmpeg/builds/")
        input("\n按回车键退出程序...")
        sys.exit(1)

    # 2. 确定扫描工作目录（默认当前脚本所在目录）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = sys.argv[1] if len(sys.argv) > 1 else script_dir

    if not os.path.isdir(target_dir):
        print(f"[错误] 指定的目标目录不存在: {target_dir}")
        sys.exit(1)

    # 3. 递归扫描
    need_transcode, already_compatible = scan_directory(target_dir)

    if not need_transcode:
        print("\n[提示] 没有发现需要转码的视频文件！所有视频均已满足 SPVideoClip 原生播放标准。")
        input("\n按回车键退出...")
        return

    # 4. 列出需要转码的清单
    print("\n[2/3] 待处理的视频文件列表:")
    print("-" * 70)
    for idx, (path, info) in enumerate(need_transcode, 1):
        rel_path = os.path.relpath(path, target_dir)
        size_str = format_size(info.get("size_bytes", 0))
        codec_str = f"编码: {info.get('v_codec', '未知')}/{info.get('a_codec', '未知')}"
        print(f" [{idx:02d}] {rel_path} ({size_str}) -> {codec_str}")
    print("-" * 70)

    print("\n[重要说明]:")
    print(" 1. 转码完成后，将用生成的标准 H.264+AAC MP4 替换原文件（主文件名不变）；")
    print(" 2. 原始非兼容格式文件将在成功转码后被安全删除；")
    print(" 3. 转码成功后的 MP4 可以在 SPVideoClip 控制台秒开直接播放，无需任何等待。")

    # 确认是否继续
    try:
        user_choice = input("\n确认立即开始批量处理？(输入 Y 开始，输入 N 取消) [Y/N]: ").strip().lower()
    except KeyboardInterrupt:
        print("\n已取消操作。")
        return

    if user_choice not in ["y", "yes", ""]:
        print("已取消转码任务。")
        return

    # 5. 开始批量转码流水线
    print("\n[3/3] 开始批量转码与替换...")
    print("=" * 70)

    success_count = 0
    fail_count = 0
    total_count = len(need_transcode)
    all_start_time = time.time()

    for idx, (src_path, info) in enumerate(need_transcode, 1):
        filename = os.path.basename(src_path)
        base_name, old_ext = os.path.splitext(filename)
        parent_dir = os.path.dirname(src_path)
        dst_path = os.path.join(parent_dir, f"{base_name}.mp4")

        print(f"\n[{idx}/{total_count}] 正在处理: {filename}")
        print(f"  位置: {src_path}")
        print(f"  原大小: {format_size(info.get('size_bytes', 0))}")

        success = transcode_video(src_path, dst_path, info)
        if success:
            success_count += 1
            if os.path.exists(dst_path):
                new_size = os.path.getsize(dst_path)
                print(f"  新文件: {os.path.basename(dst_path)} ({format_size(new_size)})")
        else:
            fail_count += 1

    total_cost = time.time() - all_start_time
    print("\n" + "=" * 70)
    print(" 批量转码全部处理完成！")
    print(f" 总任务数: {total_count} 个")
    print(f" 成功转码替换: {success_count} 个")
    if fail_count > 0:
        print(f" 失败数量: {fail_count} 个 (原文件完好保留)")
    print(f" 总计耗时: {total_cost:.1f} 秒")
    print("=" * 70)
    input("\n按回车键退出程序...")

if __name__ == "__main__":
    main()
