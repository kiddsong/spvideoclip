import os
import uuid
import json
import time
import shutil
from typing import Dict, Any, Optional, Callable
from core.audio_extractor import AudioExtractor, SUPPORTED_EXTENSIONS
from core.impact_detector import ImpactDetector
from core.video_cutter import VideoCutter

class VideoPipeline:
    """整合视频上传、音频特征识别、时间戳提取与视频生成全流程控制器，全面支持古老与现代格式"""

    def __init__(self, base_storage_dir: str, export_dir: str = r"D:\videocliout"):
        self.base_dir = base_storage_dir
        self.upload_dir = os.path.join(base_storage_dir, "uploads")
        self.audio_dir = os.path.join(base_storage_dir, "audio")
        self.output_dir = os.path.join(base_storage_dir, "outputs")
        self.export_dir = export_dir

        for d in [self.upload_dir, self.audio_dir, self.output_dir, self.export_dir]:
            os.makedirs(d, exist_ok=True)

        self.audio_extractor = AudioExtractor(sample_rate=22050)
        self.detector = ImpactDetector(sample_rate=22050)
        self.cutter = VideoCutter()

        # 记录各文件的转码进度与状态
        self.transcode_progress: Dict[str, Dict[str, Any]] = {}

    def _resolve_video_path(self, video_identifier: str) -> str:
        """解析视频路径：支持绝对路径（直接读取）和 uploads 内部相对路径"""
        if os.path.isabs(video_identifier) and os.path.exists(video_identifier):
            return video_identifier
        path_in_uploads = os.path.join(self.upload_dir, video_identifier)
        if os.path.exists(path_in_uploads):
            return path_in_uploads
        raise FileNotFoundError(f"视频文件不存在: {video_identifier}")

    def prepare_video_playback(self, video_identifier: str) -> Dict[str, Any]:
        """
        极速元数据探测（毫秒级响应）：
        支持本地绝对路径直接播放，无需文件拷贝；
        若是 H5 原生播放格式，直接提供视频源；
        若是非原生格式，启动后台轻量转码供浏览器播放。
        """
        video_path = self._resolve_video_path(video_identifier)
        video_info = self.audio_extractor.get_video_info(video_path)
        is_native = self.audio_extractor.is_browser_native(video_path, video_info)

        # 构造播放 URL
        import urllib.parse
        if os.path.isabs(video_identifier):
            # 本地直接引用的绝对路径
            encoded_path = urllib.parse.quote(video_path)
            playback_url = f"/api/media/direct?path={encoded_path}"
        else:
            playback_url = f"/api/media/uploads/{video_identifier}"

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        preview_filename = f"preview_{base_name}.mp4"
        preview_path = os.path.join(self.upload_dir, preview_filename)

        # 检查是否已存在可用的预览文件
        if os.path.exists(preview_path) and os.path.getsize(preview_path) > 0:
            playback_url = f"/api/media/uploads/{preview_filename}"
            self.transcode_progress[preview_filename] = {
                "progress": 1.0,
                "message": "H5 预览流已就绪",
                "ready": True
            }
        elif is_native:
            # 浏览器原生兼容格式，优先使用 direct 流
            if os.path.isabs(video_identifier):
                encoded_path = urllib.parse.quote(video_path)
                playback_url = f"/api/media/direct?path={encoded_path}"
            else:
                playback_url = f"/api/media/uploads/{video_identifier}"
        else:
            # 非浏览器原生格式 (wmv, rmvb, avi, mkv, h265 等)：
            # 必须后台异步生成专供网页播放的轻量预览流并实时追踪进度
            self.transcode_progress[preview_filename] = {
                "progress": 0.01,
                "message": "正在启动转码转换...",
                "ready": False
            }

            import threading
            def async_convert():
                try:
                    def on_progress(ratio, msg):
                        self.transcode_progress[preview_filename] = {
                            "progress": round(ratio, 2),
                            "message": msg,
                            "ready": False
                        }
                    self.audio_extractor.convert_to_web_preview(
                        input_path=video_path,
                        output_mp4_path=preview_path,
                        total_duration=video_info.get("duration", 0.0),
                        progress_callback=on_progress
                    )
                    self.transcode_progress[preview_filename] = {
                        "progress": 1.0,
                        "message": "H5 预览转换完成！",
                        "ready": True
                    }
                except Exception as e:
                    self.transcode_progress[preview_filename] = {
                        "progress": 0.0,
                        "message": f"转码异常: {str(e)}",
                        "ready": False
                    }
            threading.Thread(target=async_convert, daemon=True).start()

            # 当预览流还没就绪时，先尝试直读（若部分支持），同时前端会自动轮询预览流
            if os.path.isabs(video_identifier):
                encoded_path = urllib.parse.quote(video_path)
                playback_url = f"/api/media/direct?path={encoded_path}"
            else:
                playback_url = f"/api/media/uploads/{video_identifier}"

        return {
            "video_info": video_info,
            "playback_url": playback_url,
            "is_converted": not is_native,
            "preview_filename": preview_filename if not is_native else None
        }

    def process_detection(
        self,
        video_filename: str,
        sensitivity: float = 1.0,
        pre_seconds: float = 1.2,
        post_seconds: float = 1.2,
        min_interval_sec: float = 1.0,
        enable_ai: bool = True,
        progress_cb: Optional[Callable[[float, str], None]] = None
    ) -> Dict[str, Any]:
        """第一阶段：分析视频音频并识别拍打时间戳 (支持 Google YAMNet 深度学习精滤)"""
        video_path = self._resolve_video_path(video_filename)

        if progress_cb: progress_cb(0.1, "正在解析视频元数据...")
        video_info = self.audio_extractor.get_video_info(video_path)

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        # 音频存储使用安全前缀名，避免同名冲突
        import hashlib
        path_hash = hashlib.md5(video_path.encode('utf-8')).hexdigest()[:8]
        wav_filename = f"{path_hash}_{base_name}.wav"
        wav_path = os.path.join(self.audio_dir, wav_filename)

        if progress_cb: progress_cb(0.3, "正在提取音频流 (支持各类新旧格式)...")
        if not os.path.exists(wav_path):
            self.audio_extractor.extract_audio(video_path, wav_path)

        msg = "正在进行声学瞬态分析与 Google YAMNet AI 深度语义识别..." if enable_ai else "正在进行皮肤拍打声学分析与重叠去重..."
        if progress_cb: progress_cb(0.6, msg)
        events = self.detector.detect_impacts(
            wav_path,
            sensitivity=sensitivity,
            min_interval_sec=min_interval_sec,
            enable_ai=enable_ai
        )

        intervals = self.detector.generate_cut_intervals(
            events=events,
            video_duration=video_info["duration"],
            pre_seconds=pre_seconds,
            post_seconds=post_seconds
        )

        if progress_cb: progress_cb(1.0, "分析完成！")

        return {
            "video_filename": video_filename,
            "audio_filename": wav_filename,
            "video_info": video_info,
            "events": events,
            "intervals": intervals,
            "stats": {
                "detected_count": len(events),
                "merged_clip_count": len(intervals),
                "total_clip_duration": round(sum(e - s for s, e in intervals), 2)
            }
        }

    def process_render(
        self,
        video_filename: str,
        intervals: list,
        original_name: Optional[str] = None,
        progress_cb: Optional[Callable[[float, str], None]] = None
    ) -> Dict[str, Any]:
        """第二阶段：根据区间列表截取并拼接生成统一的标准 H.264 MP4 成片"""
        video_path = self._resolve_video_path(video_filename)

        # 获取原文件的主文件名
        if original_name:
            base_name = os.path.splitext(original_name)[0]
        else:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            if "_" in base_name and len(base_name.split("_")[0]) == 10:
                base_name = base_name.split("_", 1)[1]

        # 命名格式规范：Merge_原文件名.mp4
        output_filename = f"Merge_{base_name}.mp4"
        output_path = os.path.join(self.output_dir, output_filename)

        def cutter_cb(curr, total, msg):
            if progress_cb:
                ratio = 0.1 + 0.85 * (curr / max(1, total))
                progress_cb(round(ratio, 2), msg)

        self.cutter.cut_and_concat(
            input_video=video_path,
            intervals=intervals,
            output_video=output_path,
            progress_callback=cutter_cb
        )

        output_info = self.audio_extractor.get_video_info(output_path)

        # 自动复制/导出到目标目录 D:\videocliout
        export_file_path = os.path.join(self.export_dir, output_filename)
        try:
            shutil.copy2(output_path, export_file_path)
            export_saved = True
        except Exception as e:
            export_saved = False
            export_file_path = f"保存失败: {str(e)}"

        if progress_cb: progress_cb(1.0, f"成片已生成并自动保存至 {self.export_dir}！")

        return {
            "output_filename": output_filename,
            "duration": output_info["duration"],
            "size_bytes": output_info["size_bytes"],
            "export_dir": self.export_dir,
            "export_file_path": export_file_path,
            "export_saved": export_saved
        }
