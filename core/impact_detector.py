import numpy as np
import librosa
from scipy.signal import find_peaks
from typing import List, Dict, Any, Tuple, Optional
from core.yamnet_classifier import YAMNetClassifier

class ImpactDetector:
    """
    肉体拍打/抽打（Slap / Flesh Impact / Whip）双轨声学+AI深度识别检测引擎。

    核心双轨机理：
    1. 第一轨：Librosa 毫秒级瞬态冲激检测（Onset Strength + RMS + 频谱质心过滤 + NMS非极大值抑制去重）。
    2. 第二轨：Google YAMNet 深度神经网络语义过滤。精准识别 Class 461 (Slap, smack) 与 Class 466 (Whip)，
       剔除咳嗽、脚步、击掌、敲门等非拍打干扰。
    """

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self.yamnet = YAMNetClassifier()

    def detect_impacts(
        self,
        audio_path: str,
        sensitivity: float = 0.15,     # 灵敏度 0.01 ~ 1.0 (越大约敏感)
        min_interval_sec: float = 1.5,  # 两次独立有效拍打之间的最小安全间隔 (默认 1.5 秒，排除余震抖动与二次触发)
        min_rms_db: float = -35.0,      # 绝对底噪截断 (dB)
        enable_ai: bool = True          # 是否开启 Google YAMNet 深度语义过滤
    ) -> List[Dict[str, Any]]:
        """
        核心检测函数：结合声学瞬态与 Google YAMNet 深度学习分类器返回高质量时间戳列表
        """
        # 1. 加载音频 (22050Hz 用于瞬态高分辨率分析)
        y, sr = librosa.load(audio_path, sr=self.sample_rate, mono=True)
        if len(y) == 0:
            return []

        hop_length = 256
        n_fft = 1024

        # 2. 计算频谱与瞬态能量包络 (Onset Strength)
        D = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

        # 关注人体拍打高能量频带 (200Hz ~ 5500Hz)
        impact_band_idx = (freqs >= 200) & (freqs <= 5500)
        D_band = D[impact_band_idx, :]

        onset_env = librosa.onset.onset_strength(
            S=librosa.amplitude_to_db(D_band, ref=np.max),
            sr=sr,
            hop_length=hop_length,
            aggregate=np.median
        )

        # 短时 RMS 能量 (dB)
        rms = librosa.feature.rms(y=y, frame_length=512, hop_length=hop_length)[0]
        rms_db = librosa.amplitude_to_db(rms, ref=np.max)

        # 频谱质心 (Spectral Centroid)
        cent = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length)[0]

        # 3. 动态自适应阈值计算
        onset_std = float(np.std(onset_env))
        onset_mean = float(np.mean(onset_env))
        max_rms = float(np.max(rms_db)) if len(rms_db) > 0 else 0.0

        # sensitivity (0.01 ~ 1.0) 映射到 onset_threshold
        k = 1.8 - (sensitivity * 1.5)
        onset_threshold = max(0.1, onset_mean + k * onset_std)

        # 动态能量门限
        allowed_db_drop = 10.0 + (sensitivity * 30.0)
        dynamic_energy_thresh = max(min_rms_db, max_rms - allowed_db_drop)

        # 4. 寻峰检测 (Peak Picking)
        candidate_min_dist = max(1, int(0.1 * sr / hop_length))
        peaks, properties = find_peaks(
            onset_env,
            height=onset_threshold,
            distance=candidate_min_dist,
            prominence=onset_std * 0.25
        )

        raw_candidates = []
        duration = len(y) / sr

        for p in peaks:
            timestamp = float(p * hop_length / sr)
            if timestamp > duration:
                continue

            frame_rms = float(rms_db[min(p, len(rms_db) - 1)])
            frame_cent = float(cent[min(p, len(cent) - 1)])

            # 过滤1: 能量门限（排除极微弱背景噪音）
            if frame_rms < dynamic_energy_thresh:
                continue

            # 过滤2: 频谱质心（排除极低频嗡嗡声 < 200Hz 和超高频纯哨音 > 6500Hz）
            if frame_cent < 200 or frame_cent > 6500:
                continue

            # 过滤3: 衰减验证（肉体拍打脉冲 50ms 内显著衰减）
            decay_frames = int(0.05 * sr / hop_length) # 约 50ms
            if p + decay_frames < len(onset_env):
                post_onset = onset_env[p + decay_frames]
                peak_onset = onset_env[p]
                if post_onset / (peak_onset + 1e-6) > 0.92:
                    continue

            # 计算基础声学置信度
            onset_val = float(onset_env[p])
            conf_onset = min(1.0, max(0.0, (onset_val - onset_threshold) / (onset_std * 1.5 + 1e-6)))
            conf_rms = min(1.0, max(0.0, (frame_rms - dynamic_energy_thresh) / (allowed_db_drop + 1e-6)))
            confidence = float(np.clip(0.5 * conf_onset + 0.5 * conf_rms + 0.35, 0.2, 0.99))

            raw_candidates.append({
                "time": round(timestamp, 3),
                "peak_frame": p,
                "onset_val": onset_val,
                "confidence": round(confidence, 2),
                "rms_db": round(frame_rms, 1),
                "spectral_centroid": round(frame_cent, 1)
            })

        # 5. 非极大值抑制（NMS）去除 1.5 秒内的拖尾余震与二次触发
        cluster_events = []
        raw_candidates.sort(key=lambda x: x["time"])

        i = 0
        while i < len(raw_candidates):
            cluster = [raw_candidates[i]]
            j = i + 1
            while j < len(raw_candidates) and (raw_candidates[j]["time"] - cluster[0]["time"]) < min_interval_sec:
                cluster.append(raw_candidates[j])
                j += 1

            best_event = max(cluster, key=lambda x: (x["confidence"], x["onset_val"], x["rms_db"]))
            cluster_events.append(best_event)
            i = j

        # 6. 第二轨：Google YAMNet 深度语义分类验证与置信度重加权
        # 如果模型可用且用户开启了 AI 精滤，对每一个冲击点截取 1 秒切片送入神经网络预测
        final_events = []

        if enable_ai and self.yamnet.is_available() and len(cluster_events) > 0:
            # YAMNet 需要 16kHz 采样率输入，进行一次统一的重采样
            y_16k = librosa.resample(y, orig_sr=sr, target_sr=16000)
            sr_yamnet = 16000

            for ev in cluster_events:
                t = ev["time"]
                # 截取前后约 0.5s（共约 1.0s），包含完整的拍打瞬间与瞬态包络
                start_sample = max(0, int((t - 0.45) * sr_yamnet))
                end_sample = min(len(y_16k), int((t + 0.55) * sr_yamnet))
                clip_16k = y_16k[start_sample:end_sample]

                ai_res = self.yamnet.evaluate_clip(clip_16k)
                target_score = ai_res.get("target_score", 0.0) # Slap/Whip 命中分
                is_pure_noise = ai_res.get("is_pure_noise", False)

                # 智能初筛过滤：
                # 1. 如果经 YAMNet 判定为纯人声/尖叫/哭喊/敲门/脚步/掌声，且完全无 Slap/Whip 拍打特征，则一票否决剔除！
                if is_pure_noise:
                    continue

                # 2. 如果存在拍打特征（哪怕是拍打 + 人声/呻吟/叫声/背景音乐混合），均予以坚定保留！
                # 融合 AI 预测分值：若 AI 命中 Slap/Whip，将大幅提升其置信度
                blended_confidence = float(np.clip(ev["confidence"] * 0.5 + target_score * 0.5 + 0.1, 0.2, 0.99))

                # 保存用于人工反馈学习的特征索引（转为可序列化的 list）
                embedding_data = ai_res.get("embedding")
                embedding_list = [round(float(v), 5) for v in embedding_data] if embedding_data is not None else None

                final_events.append({
                    "time": ev["time"],
                    "confidence": round(blended_confidence, 2),
                    "ai_score": round(target_score, 2),
                    "custom_score": ai_res.get("custom_score"),
                    "ai_label": ai_res.get("top1_label", ""),
                    "rms_db": ev["rms_db"],
                    "spectral_centroid": ev["spectral_centroid"],
                    "embedding": embedding_list
                })
        else:
            # 纯声学模式
            for ev in cluster_events:
                final_events.append({
                    "time": ev["time"],
                    "confidence": ev["confidence"],
                    "ai_score": None,
                    "custom_score": None,
                    "rms_db": ev["rms_db"],
                    "spectral_centroid": ev["spectral_centroid"],
                    "embedding": None
                })

        return final_events

    @staticmethod
    def generate_cut_intervals(
        events: List[Dict[str, Any]],
        video_duration: float,
        pre_seconds: float = 1.0,
        post_seconds: float = 1.0,
        min_gap_merge: float = 0.5
    ) -> List[Tuple[float, float]]:
        """
        根据检测到的拍打时间戳生成剪辑时间区间 [-pre_seconds, +post_seconds]，并自动合并重叠区间。
        """
        if not events:
            return []

        raw_intervals = []
        for ev in events:
            t = ev["time"]
            start = max(0.0, t - pre_seconds)
            end = min(video_duration, t + post_seconds)
            raw_intervals.append((start, end))

        # 按起始时间排序
        raw_intervals.sort(key=lambda x: x[0])

        merged_intervals = []
        for interval in raw_intervals:
            if not merged_intervals:
                merged_intervals.append(interval)
            else:
                prev_start, prev_end = merged_intervals[-1]
                curr_start, curr_end = interval

                if curr_start <= prev_end + min_gap_merge:
                    new_end = max(prev_end, curr_end)
                    merged_intervals[-1] = (prev_start, round(new_end, 3))
                else:
                    merged_intervals.append((round(curr_start, 3), round(curr_end, 3)))

        return [(round(s, 3), round(e, 3)) for s, e in merged_intervals]
