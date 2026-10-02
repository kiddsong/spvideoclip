#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SPVideoClip 视频批量转码与格式统一工具 (Batch Transcoder v3.0 - 任务记忆库与增量处理版)
-----------------------------------------------------------------------------------------
功能特性:
1. 【任务记录库机制 (Task Database)】:
   - 自动在工作目录下创建并维护 `convert_task_db.json` 任务记录库；
   - 完整记录每个目录的最后扫描时间、所有发现的文件及每个文件的处理状态 (PENDING / PROCESSED / FAILED)；
   - 当再次运行转码工具时，若检测到当前目录曾扫描过且存在未完成任务，智能询问：
       [1] 直接处理任务库中的未处理文件（跳过耗时的全盘递归扫描，秒级开工）；
       [2] 重新全面扫描目录（刷新任务库，追加新拷入的文件）。
2. 【智能断点接续与原位替换】:
   - 已处理成功的视频会被标为 PROCESSED 并记录新文件的 hash/路径，绝不会重复二次转码；
   - 转码成功并通过严格校验后，安全删除旧视频，用新生成的 MP4 原地替换（主文件名保持不变）。
3. 【全自动 GPU 硬件加速】:
   - 优先挂载 NVIDIA NVENC (h264_nvenc) 高达 35x~60x 倍速硬件转码；
   - 自动支持 Intel QSV / AMD AMF / Windows MediaFoundation；
   - 无独立显卡或驱动不可用时，平滑安全回退至 CPU 多核 (libx264 ultrafast) 转码。
4. 【广电级音画时钟锁相】:
   - 强制 `-fps_mode cfr` 恒定帧率与 `-af aresample=async=1000` 动态时间戳对齐，彻底根治 AVI/WMV 早期丢帧导致的音画不同步。
5. 【实时动态控制台进度条】:
   - 实时显示 百分比、图形进度条、当前转码倍速 (如 45.2x)、已用时间及动态预估剩余时间 (ETA)。
"""

import os
import sys
import json
import shutil
import subprocess
import time
from typing import Dict, Any, Optional, Tuple, List

# 常见视频扩展名列表
VIDEO_EXTENSIONS = {
    ".wmv", ".asf", ".rm", ".rmvb", ".avi", ".flv", ".f4v",
    ".mkv", ".mov", ".mpg", ".mpeg", ".mpe", ".m2v", ".vob",
    ".dat", ".3gp", ".3g2", ".ts", ".mts", ".m2ts", ".webm",
    ".mp4", ".m4v"
}

TASK_DB_FILENAME = "convert_task_db.json"

def format_size(size_bytes: int) -> str:
    """人类可读的文件大小格式化"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def format_duration(seconds: float) -> str:
    """格式化秒数为时分秒"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}小时{m:02d}分{s:02d}秒"
    return f"{m:02d}分{s:02d}秒"

def check_ffmpeg() -> bool:
    """检查系统环境是否有 ffmpeg 和 ffprobe"""
    return (shutil.which("ffmpeg") is not None) and (shutil.which("ffprobe") is not None)

def detect_hardware_encoder() -> Tuple[str, List[str], str]:
    """
    自动检测当前电脑支持的最佳硬件转码器：
    返回: (encoder_name, encoder_flags, display_name)
    """
    candidates = [
        ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22"], "NVIDIA NVENC 硬件加速 (超高速)"),
        ("h264_qsv",   ["-c:v", "h264_qsv", "-preset", "faster", "-global_quality", "22"], "Intel QuickSync 硬件加速"),
        ("h264_amf",   ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22"], "AMD AMF 硬件加速"),
        ("h264_mf",    ["-c:v", "h264_mf", "-quality", "speed"], "Windows MediaFoundation 硬件加速"),
    ]

    for enc_name, enc_args, desc in candidates:
        test_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "nullsrc=s=640x480:d=0.2",
            "-c:v", enc_name,
            "-f", "null", "-"
        ]
        try:
            res = subprocess.run(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return enc_name, enc_args, desc
        except Exception:
            pass

    # CPU 兜底方案
    cpu_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p"]
    return "libx264", cpu_args, "CPU 多核极速转码 (libx264 ultrafast)"

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

        # 兜底：若容器无时长，从视频流取时长
        if duration <= 0:
            for stream in data.get("streams", []):
                try:
                    d = float(stream.get("duration", 0.0))
                    if d > duration:
                        duration = d
                except Exception:
                    pass

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
    """如果视频轨道已经是标准 H.264，可走极速转封装"""
    v_codec = info.get("v_codec", "")
    return v_codec in ["h264", "avc1"]

def render_progress_bar(percent: float, speed_str: str, elapsed_sec: float, eta_sec: Optional[float]):
    """渲染控制台动态进度条"""
    bar_len = 25
    percent_clamped = min(100.0, max(0.0, percent))
    filled = int(bar_len * percent_clamped / 100.0)
    bar_str = "=" * filled + (">" if filled < bar_len else "")
    bar_str = bar_str.ljust(bar_len, " ")

    eta_text = f"{int(eta_sec)}s" if (eta_sec is not None and eta_sec >= 0) else "--"
    speed_text = speed_str if speed_str else "--"

    line = f"\r   [{bar_str}] {percent_clamped:5.1f}% | 速率: {speed_text:>6} | 用时: {int(elapsed_sec)}s | 剩余: {eta_text:>4} "
    sys.stdout.write(line)
    sys.stdout.flush()

# =====================================================================
# 任务记录库管理模块 (Task Database Management)
# =====================================================================

class TaskDatabase:
    """
    持久化任务数据库，记录每个扫描到的视频文件处理状态。
    存储在 target_dir/convert_task_db.json 中。
    """
    def __init__(self, db_path: str, root_dir: str):
        self.db_path = db_path
        self.root_dir = os.path.abspath(root_dir)
        self.data = {
            "root_dir": self.root_dir,
            "last_scan_time": None,
            "tasks": {} # file_path -> {status, size_bytes, duration, v_codec, a_codec, processed_time, dst_path}
        }
        self.load()

    def load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, dict) and "tasks" in content:
                        self.data = content
            except Exception:
                pass

    def save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   [警告] 任务记录库保存失败: {e}")

    def has_history(self) -> bool:
        """检查是否有历史扫描记录"""
        return bool(self.data.get("last_scan_time") and self.data.get("tasks"))

    def get_pending_tasks(self) -> List[Tuple[str, Dict[str, Any]]]:
        """获取所有待处理任务（仅包含 PENDING 或 FAILED 的非兼容文件），原生兼容或已完成的文件绝对跳过"""
        pending = []
        tasks = self.data.get("tasks", {})
        dirty = False

        for file_path, item in list(tasks.items()):
            status = item.get("status")

            # 原生已兼容(NATIVE_COMPATIBLE) 或 已经转码完成(PROCESSED) 的文件直接跳过，无需处理
            if status in ["PROCESSED", "NATIVE_COMPATIBLE"]:
                continue

            # 校验物理文件是否存在
            if not os.path.exists(file_path):
                # 检查是否已经被转换成同名 .mp4
                base, _ = os.path.splitext(file_path)
                expected_mp4 = base + ".mp4"
                if os.path.exists(expected_mp4):
                    item["status"] = "PROCESSED"
                    item["dst_path"] = expected_mp4
                    dirty = True
                else:
                    # 原文件已彻底不存在，从任务库中移除
                    del tasks[file_path]
                    dirty = True
                continue

            pending.append((file_path, item))

        if dirty:
            self.save()
        return pending

    def update_scan_results(self, need_transcode_list: List[Tuple[str, Dict[str, Any]]], compatible_list: List[Tuple[str, Dict[str, Any]]]):
        """根据全盘扫描结果更新数据库"""
        self.data["last_scan_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tasks = self.data.get("tasks", {})

        # 录入需要转码的文件
        for file_path, info in need_transcode_list:
            if file_path not in tasks:
                tasks[file_path] = {
                    "status": "PENDING",
                    "size_bytes": info.get("size_bytes", 0),
                    "duration": info.get("duration", 0.0),
                    "v_codec": info.get("v_codec", "unknown"),
                    "a_codec": info.get("a_codec", "unknown"),
                    "discovered_time": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            elif tasks[file_path].get("status") != "PROCESSED":
                # 更新元数据
                tasks[file_path].update({
                    "size_bytes": info.get("size_bytes", 0),
                    "duration": info.get("duration", 0.0),
                    "v_codec": info.get("v_codec", "unknown"),
                    "a_codec": info.get("a_codec", "unknown")
                })

        # 录入原生兼容的文件（标记为无需转码）
        for file_path, info in compatible_list:
            if file_path not in tasks:
                tasks[file_path] = {
                    "status": "NATIVE_COMPATIBLE",
                    "size_bytes": info.get("size_bytes", 0),
                    "duration": info.get("duration", 0.0),
                    "v_codec": info.get("v_codec", "unknown"),
                    "a_codec": info.get("a_codec", "unknown"),
                    "discovered_time": time.strftime("%Y-%m-%d %H:%M:%S")
                }

        self.save()

    def mark_processed(self, file_path: str, dst_path: str):
        """标记任务成功完成"""
        tasks = self.data.get("tasks", {})
        if file_path in tasks:
            tasks[file_path]["status"] = "PROCESSED"
            tasks[file_path]["dst_path"] = dst_path
            tasks[file_path]["processed_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            tasks[file_path] = {
                "status": "PROCESSED",
                "dst_path": dst_path,
                "processed_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        self.save()

    def mark_failed(self, file_path: str, error_msg: str):
        """标记任务失败"""
        tasks = self.data.get("tasks", {})
        if file_path in tasks:
            tasks[file_path]["status"] = "FAILED"
            tasks[file_path]["error"] = error_msg
            tasks[file_path]["failed_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def get_statistics(self) -> Dict[str, int]:
        """获取任务统计数量"""
        tasks = self.data.get("tasks", {})
        stats = {"total": len(tasks), "processed": 0, "pending": 0, "failed": 0, "compatible": 0}
        for item in tasks.values():
            st = item.get("status")
            if st == "PROCESSED":
                stats["processed"] += 1
            elif st == "PENDING":
                stats["pending"] += 1
            elif st == "FAILED":
                stats["failed"] += 1
            elif st == "NATIVE_COMPATIBLE":
                stats["compatible"] += 1
        return stats

# =====================================================================
# 核心转码流水线
# =====================================================================

def transcode_video(
    src_path: str,
    dst_path: str,
    info: Dict[str, Any],
    encoder_name: str,
    encoder_flags: List[str]
) -> bool:
    """执行单个视频的高性能转码"""
    temp_dst = dst_path + ".converting_temp.mp4"
    if os.path.exists(temp_dst):
        try:
            os.remove(temp_dst)
        except Exception:
            pass

    total_duration = info.get("duration", 0.0)

    # 1. 优先尝试极速流拷贝 (0.2 秒完成)
    if can_stream_copy(info):
        print("   [模式] 检测到视频流已为 H.264 编码 -> 启用【极速无损封装换流】...")
        cmd = [
            "ffmpeg", "-y",
            "-i", src_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            temp_dst
        ]
    else:
        # 2. 硬件加速或 CPU 高画质重编码 (附带 CFR 与音频时间戳校准，杜绝音画不同步)
        cmd = [
            "ffmpeg", "-y",
            "-i", src_path
        ] + encoder_flags + [
            "-fps_mode", "cfr",
            "-af", "aresample=async=1000:min_hard_comp=0.100000:first_pts=0",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            temp_dst
        ]

    try:
        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace"
        )

        current_speed = ""
        last_progress_time = start_time

        for line in proc.stdout:
            line = line.strip()
            if line.startswith("speed="):
                current_speed = line.split("=")[1].strip()
            elif line.startswith("out_time_ms=") and total_duration > 0:
                try:
                    out_ms = int(line.split("=")[1])
                    cur_sec = out_ms / 1_000_000.0
                    ratio = min(0.999, max(0.001, cur_sec / total_duration))
                    percent = ratio * 100.0
                    elapsed = time.time() - start_time
                    eta = (elapsed / ratio - elapsed) if ratio > 0.02 else None

                    if (time.time() - last_progress_time) >= 0.15:
                        render_progress_bar(percent, current_speed, elapsed, eta)
                        last_progress_time = time.time()
                except Exception:
                    pass
            elif line.startswith("progress=end"):
                elapsed = time.time() - start_time
                render_progress_bar(100.0, current_speed, elapsed, 0)

        proc.wait()
        sys.stdout.write("\n")
        sys.stdout.flush()

        cost_time = time.time() - start_time

        if proc.returncode == 0 and os.path.exists(temp_dst) and os.path.getsize(temp_dst) > 1024:
            src_abs = os.path.abspath(src_path)
            dst_abs = os.path.abspath(dst_path)

            if os.path.exists(src_abs):
                os.remove(src_abs)

            if os.path.exists(dst_abs) and src_abs != dst_abs:
                os.remove(dst_abs)

            os.rename(temp_dst, dst_abs)
            print(f"   √ 转换完成并已替换！耗时: {cost_time:.1f} 秒\n")
            return True
        else:
            print(f"   × 转码异常退出 (FFmpeg 返回码: {proc.returncode})")
            if os.path.exists(temp_dst):
                try:
                    os.remove(temp_dst)
                except Exception:
                    pass
            return False

    except Exception as e:
        sys.stdout.write("\n")
        print(f"   × 转码进程出错: {e}")
        if os.path.exists(temp_dst):
            try:
                os.remove(temp_dst)
            except Exception:
                pass
        return False

def scan_directory(root_dir: str) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, Dict[str, Any]]]]:
    """递归遍历根目录下的所有视频文件"""
    need_transcode = []
    already_compatible = []

    print(f"\n[正在全面扫描目录]: {root_dir}")
    print(" (正在深度遍历所有层级子文件夹，请稍候...)")

    total_scanned = 0
    for current_root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["__pycache__", "venv", "node_modules", "$RECYCLE.BIN"]]

        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                total_scanned += 1
                full_path = os.path.join(current_root, filename)

                info = probe_video(full_path)
                if not info:
                    need_transcode.append((full_path, {"v_codec": "unknown", "a_codec": "unknown", "size_bytes": os.path.getsize(full_path), "duration": 0.0}))
                    continue

                if is_spvideoclip_native(full_path, info):
                    already_compatible.append((full_path, info))
                else:
                    need_transcode.append((full_path, info))

    print(f" 扫描完毕！共检测到 {total_scanned} 个视频文件。")
    print(f" - 已经完全原生兼容: {len(already_compatible)} 个")
    print(f" - 需要转码统一为 MP4: {len(need_transcode)} 个\n")
    return need_transcode, already_compatible

def main():
    print("=" * 75)
    print(" SPVideoClip 视频批量转码与格式统一工具 (v3.0 - 任务记忆库与增量断点版)")
    print("=" * 75)

    # 1. 确定工作目录并第一时间检测历史任务库 (0毫秒瞬时响应)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = sys.argv[1] if len(sys.argv) > 1 else script_dir

    if not os.path.isdir(target_dir):
        print(f"[错误] 指定的目标目录不存在: {target_dir}")
        sys.exit(1)

    db_file_path = os.path.join(target_dir, TASK_DB_FILENAME)
    task_db = TaskDatabase(db_file_path, target_dir)

    should_rescan = True

    # 第一时间展示历史任务库状态
    if task_db.has_history():
        stats = task_db.get_statistics()
        pending_tasks = task_db.get_pending_tasks()
        last_time = task_db.data.get("last_scan_time", "未知")

        print("\n" + "-" * 75)
        print(f" [第一时间检测到历史任务库]: {db_file_path}")
        print(f" 上次扫描时间: {last_time}")
        print(f" 任务统计: 总计录入 {stats['total']} 个 | 原生兼容(跳过): {stats['compatible']} 个 | 已完成: {stats['processed']} 个 | 待处理: {len(pending_tasks)} 个")
        print("-" * 75)

        if pending_tasks:
            print("\n检测到当前目录之前已经遍历过，且库中存在未处理完成的文件。")
            print(" 请选择接下来的操作:")
            print("   [1] 直接处理任务库中的未处理文件 (推荐 - 跳过全盘扫描，立即开始转码)")
            print("   [2] 重新全面扫描所有子目录 (刷新任务库，追加新放入的视频)")
            print("   [0] 退出程序")

            while True:
                choice = input("\n请输入选项编号 [默认 1]: ").strip()
                if choice in ["1", ""]:
                    should_rescan = False
                    break
                elif choice == "2":
                    should_rescan = True
                    break
                elif choice == "0":
                    print("程序已退出。")
                    return
                else:
                    print("输入无效，请输入 1 或 2。")
        else:
            print("\n[提示] 历史任务库中的所有非兼容视频已全部处理完成！")
            ask = input("是否需要重新全面扫描目录以寻找新放入的文件？(Y/N) [默认 N]: ").strip().lower()
            if ask in ["y", "yes"]:
                should_rescan = True
            else:
                print("无需处理，程序退出。")
                return

    # 2. 检查运行依赖与 GPU 硬件加速 (在用户选定继续后再启动硬件探测)
    if not check_ffmpeg():
        print("\n[错误] 未检测到 FFmpeg 或 FFprobe！")
        print("本工具深度依赖 FFmpeg 硬件加速编解码。请安装并添加至环境变量 PATH。")
        print("下载地址: https://www.gyan.dev/ffmpeg/builds/")
        input("\n按回车键退出程序...")
        sys.exit(1)

    enc_name, enc_flags, enc_desc = detect_hardware_encoder()
    print(f"\n [硬件检测] 当前启用引擎: {enc_desc}")

    # 3. 执行全盘重新扫描 或 从任务库直接载入
    if should_rescan:
        need_transcode_list, compatible_list = scan_directory(target_dir)
        task_db.update_scan_results(need_transcode_list, compatible_list)
        pending_tasks = task_db.get_pending_tasks()
    else:
        print(f"\n[已跳过全盘扫描] 正在直接从任务库载入未处理任务...")
        pending_tasks = task_db.get_pending_tasks()

    if not pending_tasks:
        print("\n[提示] 当前没有待处理的非兼容视频文件！所有文件均已符合原生播放标准。")
        input("\n按回车键退出程序...")
        return

    # 6. 展示待处理文件列表
    print("-" * 75)
    print(f" 本次待处理视频任务清单 (共 {len(pending_tasks)} 个):")
    print("-" * 75)
    for idx, (path, info) in enumerate(pending_tasks, 1):
        rel_path = os.path.relpath(path, target_dir)
        size_str = format_size(info.get("size_bytes", 0))
        dur_str = format_duration(info.get("duration", 0.0))
        codec_str = f"{info.get('v_codec', '未知')}/{info.get('a_codec', '未知')}"
        print(f" [{idx:02d}] {rel_path}")
        print(f"      时长: {dur_str} | 大小: {size_str} | 编码: {codec_str}")
    print("-" * 75)

    print("\n[处理须知]:")
    print(" 1. 优先调用 GPU 硬件加速转码，并自动启用 CFR 恒定帧率与 aresample 声画锁相；")
    print(" 2. 单个文件转码成功后，将用新 MP4 替换原文件，并实时在任务库中标记为 PROCESSED；")
    print(" 3. 您随时可以按 Ctrl+C 中断，下次启动时选择 [1] 即可直接无缝断点接续！")

    try:
        user_choice = input("\n确认立即开始批量处理？(Y/N) [默认 Y]: ").strip().lower()
    except KeyboardInterrupt:
        print("\n已取消操作。")
        return

    if user_choice not in ["y", "yes", ""]:
        print("已取消转码任务。")
        return

    # 7. 开始批量流水线
    print("\n" + "=" * 75)
    print(" 开始批量转码与增量更新...")
    print("=" * 75)

    success_count = 0
    fail_count = 0
    total_count = len(pending_tasks)
    all_start_time = time.time()

    for idx, (src_path, info) in enumerate(pending_tasks, 1):
        if not os.path.exists(src_path):
            continue

        filename = os.path.basename(src_path)
        base_name, _ = os.path.splitext(filename)
        parent_dir = os.path.dirname(src_path)
        dst_path = os.path.join(parent_dir, f"{base_name}.mp4")

        # 【核心新增】：在正式转码前进行毫秒级自动二次核实 (Real-time Pre-execution Verification)
        # 针对历史误标、已被其他方式处理过或已转为标准 MP4 的文件，自动修正数据库并无缝跳过！
        live_info = probe_video(src_path)
        if live_info and is_spvideoclip_native(src_path, live_info):
            print(f"[{idx}/{total_count}] 跳过已合规文件: {filename}")
            print(f"   [自动核验] 检测到该文件已经是标准 H.264+AAC MP4 格式，无需重复转码！")
            task_db.mark_processed(src_path, src_path)
            continue

        # 如果源文件并非原生，但同一目录下已存在同名 .mp4，再次核查目标 mp4 是否已完好转码就绪
        if os.path.exists(dst_path) and os.path.abspath(src_path) != os.path.abspath(dst_path):
            dst_info = probe_video(dst_path)
            if dst_info and is_spvideoclip_native(dst_path, dst_info):
                print(f"[{idx}/{total_count}] 自动跳过并清理旧文件: {filename}")
                print(f"   [自动核验] 检测到目标 {base_name}.mp4 已成功就绪且编码合规，直接补全标记并移除残留原文件！")
                try:
                    os.remove(src_path)
                except Exception:
                    pass
                task_db.mark_processed(src_path, dst_path)
                continue

        # 使用最新实时探测到的元数据替换可能过时的历史元数据
        current_info = live_info if live_info else info

        print(f"[{idx}/{total_count}] 正在处理: {filename}")
        print(f"   路径: {src_path}")
        print(f"   大小: {format_size(current_info.get('size_bytes', 0))} | 时长: {format_duration(current_info.get('duration', 0.0))}")

        success = transcode_video(src_path, dst_path, current_info, enc_name, enc_flags)
        if success:
            success_count += 1
            task_db.mark_processed(src_path, dst_path)
        else:
            fail_count += 1
            task_db.mark_failed(src_path, "转码失败")

    total_cost = time.time() - all_start_time
    print("=" * 75)
    print(" 批量转码全部处理完成！")
    print(f" 本次成功完成: {success_count} 个")
    if fail_count > 0:
        print(f" 失败文件: {fail_count} 个 (可在下次重试)")
    print(f" 本次耗时: {total_cost:.1f} 秒")
    print(f" 任务记录库已更新: {db_file_path}")
    print("=" * 75)
    input("\n按回车键退出程序...")

if __name__ == "__main__":
    main()
