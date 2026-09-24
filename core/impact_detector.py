import numpy as np
import librosa
from scipy.signal import find_peaks
from typing import List, Dict, Any, Tuple

class ImpactDetector:
    """
    肉体拍打/抽打（Slap / Flesh Impact / Whip）声学特征检测引擎。

    核心声学机理：
    1. 极短陡峭的瞬态冲激：短时能量与频谱通量在极短时间内爆发。
    2. 肉体碰撞阻尼：衰减迅速，不具备金属撞击的持续高频泛音。
    3. 频谱能量分布：集中在 200Hz ~ 5500Hz 范围内。
    4. 抑制拖尾与重叠二次触发：单次拍打会产生余震/反弹或房间混响，必须通过动态防抖与 NMS 非极大值抑制彻底去重。
    """

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def detect_impacts(
        self,
        audio_path: str,
        sensitivity: float = 0.15,     # 默认灵敏度 0.15 (严苛过滤)
        min_interval_sec: float = 1.5,  # 两次独立有效拍打之间的最小安全间隔 (默认 1.5 秒，彻底排除余震抖动与二次触发)
        min_rms_db: float = -35.0       # 绝对底噪截断 (dB)
    ) -> List[Dict[str, Any]]:
        """
        核心检测函数：返回识别到的拍击时间戳列表及相关声学特征分值
        """
        # 1. 加载音频
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
        # 当 sensitivity 接近 0.01 时，要求峰值高出均值 1.8 倍标准差以上，只保留极清晰爆发的强冲击
        k = 1.8 - (sensitivity * 1.5)
        onset_threshold = max(0.1, onset_mean + k * onset_std)

        # 动态能量门限：
        # sensitivity 越低，能量门限越严苛（比如只允许主峰下浮 10dB~15dB，微弱声全滤除）
        allowed_db_drop = 10.0 + (sensitivity * 30.0)
        dynamic_energy_thresh = max(min_rms_db, max_rms - allowed_db_drop)

        # 4. 寻峰检测 (Peak Picking)
        # 先以较小帧距提取所有潜在候选脉冲
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

            # 过滤3: 衰减验证（肉体拍打脉冲 50ms 内显著衰减，区别于乐器长音或持续尖叫）
            decay_frames = int(0.05 * sr / hop_length) # 约 50ms
            if p + decay_frames < len(onset_env):
                post_onset = onset_env[p + decay_frames]
                peak_onset = onset_env[p]
                if post_onset / (peak_onset + 1e-6) > 0.92:
                    continue

            # 计算置信度与能量强度得分
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

        # 5. 非极大值抑制（NMS）与防微小滞后重叠去重
        # 如果两次检测时间差 < min_interval_sec（例如 0.6 秒以内的多次击发或反弹抖动），
        # 视作同一拍打事件的振铃/残余能量，严格只保留 onset_val（瞬态爆发力）最高的主峰！
        filtered_events = []
        # 按时间排序
        raw_candidates.sort(key=lambda x: x["time"])

        i = 0
        while i < len(raw_candidates):
            cluster = [raw_candidates[i]]
            j = i + 1
            while j < len(raw_candidates) and (raw_candidates[j]["time"] - cluster[0]["time"]) < min_interval_sec:
                cluster.append(raw_candidates[j])
                j += 1

            # 在该密集聚集窗内，选取冲击最强、能量最大的脉冲
            best_event = max(cluster, key=lambda x: (x["confidence"], x["onset_val"], x["rms_db"]))
            filtered_events.append({
                "time": best_event["time"],
                "confidence": best_event["confidence"],
                "rms_db": best_event["rms_db"],
                "spectral_centroid": best_event["spectral_centroid"]
            })
            i = j

        return filtered_events

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

                # 如果当前区间的开始时间 <= 上一个区间的结束时间 + 允许融合的间隙
                if curr_start <= prev_end + min_gap_merge:
                    new_end = max(prev_end, curr_end)
                    merged_intervals[-1] = (prev_start, round(new_end, 3))
                else:
                    merged_intervals.append((round(curr_start, 3), round(curr_end, 3)))

        return [(round(s, 3), round(e, 3)) for s, e in merged_intervals]
