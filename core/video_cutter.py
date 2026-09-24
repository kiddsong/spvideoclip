import os
import subprocess
import tempfile
from typing import List, Tuple, Callable, Optional

class VideoCutter:
    """
    负责视频高精度片段截取与拼接，支持精准重编码截取，保证拼接片段音视频完美对齐、不卡顿。
    """

    def __init__(self, crf: int = 18, preset: str = "fast"):
        self.crf = crf
        self.preset = preset

    def cut_and_concat(
        self,
        input_video: str,
        intervals: List[Tuple[float, float]],
        output_video: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> str:
        """
        截取指定的所有时间区间并无缝合并为新视频。
        """
        if not intervals:
            raise ValueError("没有可用于剪辑的时间片段区间")

        os.makedirs(os.path.dirname(output_video), exist_ok=True)
        clip_files = []
        temp_dir = tempfile.mkdtemp(prefix="videocli_clips_")

        try:
            total = len(intervals)
            # 1. 逐个切取片段 (精确到毫秒，避免关键帧错位)
            for idx, (start_sec, end_sec) in enumerate(intervals):
                clip_path = os.path.join(temp_dir, f"clip_{idx:04d}.mp4")
                duration = round(end_sec - start_sec, 3)

                if progress_callback:
                    progress_callback(idx + 1, total, f"正在裁剪片段 {idx+1}/{total} [{start_sec}s - {end_sec}s]")

                # 采用精确seek与重编码，保证拼接时时间基与音频一致
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss", str(start_sec),
                    "-t", str(duration),
                    "-i", input_video,
                    "-c:v", "libx264",
                    "-preset", self.preset,
                    "-crf", str(self.crf),
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-avoid_negative_ts", "1",
                    "-reset_timestamps", "1",
                    clip_path
                ]

                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    raise RuntimeError(f"裁剪片段 {idx+1} 失败: {res.stderr}")

                clip_files.append(clip_path)

            # 2. 生成 concat 列表文件
            concat_txt = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_txt, "w", encoding="utf-8") as f:
                for p in clip_files:
                    # Windows 路径转为 ffmpeg 兼容的正斜杠格式
                    safe_p = p.replace("\\", "/")
                    f.write(f"file '{safe_p}'\n")

            if progress_callback:
                progress_callback(total, total, "正在合并生成最终视频...")

            # 3. 使用 concat demuxer 极速合并
            concat_cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_txt,
                "-c", "copy",
                "-movflags", "+faststart",  # 优化H5网页流式直接播放
                output_video
            ]

            res_concat = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res_concat.returncode != 0:
                raise RuntimeError(f"拼接视频失败: {res_concat.stderr}")

            return output_video

        finally:
            # 清理临时切片文件
            try:
                for cf in clip_files:
                    if os.path.exists(cf):
                        os.remove(cf)
                concat_path = os.path.join(temp_dir, "concat_list.txt")
                if os.path.exists(concat_path):
                    os.remove(concat_path)
                os.rmdir(temp_dir)
            except Exception:
                pass
