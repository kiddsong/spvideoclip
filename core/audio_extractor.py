import os
import subprocess
import json
from typing import Tuple, Dict, Any, Callable, Optional

SUPPORTED_EXTENSIONS = {
    # 现代标准格式
    ".mp4", ".mov", ".mkv", ".webm", ".m4v",
    # 古老/传统/VCD/DVD 格式
    ".mpg", ".mpeg", ".mpe", ".m2v", ".vob", ".dat",
    # 微软 Windows Media
    ".wmv", ".asf",
    # RealNetworks RealMedia
    ".rm", ".rmvb",
    # 早期 AVI / DivX / XviD
    ".avi", ".divx", ".xvid",
    # Flash 视频
    ".flv", ".f4v",
    # 早期手机格式
    ".3gp", ".3g2",
    # 广播/摄像机高清流
    ".ts", ".mts", ".m2ts"
}

class AudioExtractor:
    """负责通过 FFmpeg 探测视频、提取高品质分析音频，以及为古老视频格式生成带精准进度的 H5 预览流"""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """使用 ffprobe 获取视频时长、分辨率、视频音频编码等元信息"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_type,codec_name",
            "-of", "json",
            video_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            data = json.loads(result.stdout)
            duration = float(data.get("format", {}).get("duration", 0.0))

            width = 0
            height = 0
            v_codec = ""
            a_codec = ""

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and not v_codec:
                    width = int(stream.get("width", 0))
                    height = int(stream.get("height", 0))
                    v_codec = stream.get("codec_name", "").lower()
                elif stream.get("codec_type") == "audio" and not a_codec:
                    a_codec = stream.get("codec_name", "").lower()

            return {
                "duration": duration,
                "width": width,
                "height": height,
                "v_codec": v_codec,
                "a_codec": a_codec,
                "size_bytes": int(data.get("format", {}).get("size", 0))
            }
        except Exception as e:
            raise RuntimeError(f"获取视频元数据失败: {str(e)}")

    def is_browser_native(self, video_path: str, info: Dict[str, Any]) -> bool:
        """判断视频是否能被 Chrome/Edge/Firefox 的 H5 <video> 标签原生直接流畅播放"""
        ext = os.path.splitext(video_path)[1].lower()
        if ext == ".mp4" and info.get("v_codec") in ["h264", "avc1"]:
            return True
        if ext == ".webm" and info.get("v_codec") in ["vp8", "vp9", "av1"]:
            return True
        return False

    def convert_to_web_preview(
        self,
        input_path: str,
        output_mp4_path: str,
        total_duration: float = 0.0,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        将古老格式或不兼容编码转为 H5 友好 Web MP4，并实时解析 FFmpeg 管道向外部推送百分比进度
        """
        os.makedirs(os.path.dirname(output_mp4_path), exist_ok=True)
        temp_output = output_mp4_path + ".tmp.mp4"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            temp_output
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms=") and total_duration > 0:
                    try:
                        ms = int(line.split("=")[1])
                        current_sec = ms / 1_000_000.0
                        ratio = min(0.99, max(0.01, current_sec / total_duration))
                        percent = int(ratio * 100)
                        if progress_callback:
                            progress_callback(ratio, f"正在转换 H5 预览画面: {percent}% ({current_sec:.1f}s / {total_duration:.1f}s)")
                    except Exception:
                        pass
                elif line.startswith("progress=end"):
                    if progress_callback:
                        progress_callback(1.0, "H5 预览流转码完成！")

            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg 转码异常退出，退出码: {proc.returncode}")

            if os.path.exists(temp_output):
                if os.path.exists(output_mp4_path):
                    os.remove(output_mp4_path)
                os.rename(temp_output, output_mp4_path)

            return output_mp4_path

        finally:
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass

    def extract_audio(self, video_path: str, output_wav_path: str) -> str:
        """从视频（无论新旧格式）提取单声道分析用高保真 WAV"""
        os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", str(self.sample_rate),
            "-f", "wav",
            output_wav_path
        ]

        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) == 0:
                raise RuntimeError("音频导出文件为空或生成失败")
            return output_wav_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg 音频提取失败: {e.stderr}")
