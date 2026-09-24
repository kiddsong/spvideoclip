import os
import subprocess
import json
from typing import Tuple, Dict, Any

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
    """负责通过 FFmpeg 探测视频、提取高品质分析音频，以及为古老视频格式生成 H5 兼容预览流"""

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
        # 仅当格式为 mp4 且视频编码为 h264/avc1，音频为 aac/mp3 时，大部分现代浏览器才能无缝原生播放
        if ext == ".mp4" and info.get("v_codec") in ["h264", "avc1"]:
            return True
        if ext == ".webm" and info.get("v_codec") in ["vp8", "vp9", "av1"]:
            return True
        return False

    def convert_to_web_preview(self, input_path: str, output_mp4_path: str) -> str:
        """
        将古老格式（rm, rmvb, wmv, mpg, vob 等）或不兼容编码转为 H5 友好且适合随时 Seek 的 Web MP4
        采用超快速度 ultrafast 预设，确保上传后极速完成
        """
        os.makedirs(os.path.dirname(output_mp4_path), exist_ok=True)
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
            output_mp4_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"转码 Web 兼容预览流失败: {res.stderr}")
        return output_mp4_path

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
