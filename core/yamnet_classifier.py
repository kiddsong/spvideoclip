import os
import csv
import numpy as np
import librosa
from typing import List, Dict, Any, Optional

class YAMNetClassifier:
    """
    基于 Google AudioSet 预训练 YAMNet 深度神经网络的拍打/抽打声音事件分类器。

    重点检测类别（Target Slap & Impact Features）：
      - 461: Slap, smack (肉体拍打/掌掴/脆击)
      - 466: Whip (皮鞭抽打/破空甩动声)
      - 352: Slam (重击撞击包络)
      - 462: Click (短促冲击爆裂音)

    纯干扰排查类别（Interference Categories，若只有这些声音而无任何拍打迹象，则一票否决剔除）：
      - 纯人声/呼喊: 0 (Speech), 6 (Shout), 9 (Yell), 10 (Children shouting), 11 (Screaming), 13 (Laughter), 19 (Crying, sobbing), 33 (Groan), 34 (Grunt)
      - 环境机械碰撞: 348 (Door), 351 (Sliding door), 353 (Knock), 58 (Clapping), 62 (Applause)
      - 脚步与地面: 48 (Walk, footsteps)
    """

    def __init__(self, model_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if model_path is None:
            model_path = os.path.join(base_dir, "models", "yamnet.onnx")
        self.class_map_path = os.path.join(base_dir, "models", "yamnet_class_map.csv")
        self.model_path = model_path
        self.session = None
        self.classes = {}

        # 核心拍打特征类别
        self.target_indices = {
            461: "Slap, smack",
            466: "Whip"
        }

        # 强干扰误报类别（无拍打伴随时直接剔除）
        self.pure_interference_indices = {
            0, 1, 5, 6, 9, 10, 11, 13, 14, 15, 19, 23, 33, 34, 65, # 人声/尖叫/哭泣/喘息
            48,                                                   # 脚步/地面声
            348, 351, 353,                                        # 关门/敲门声
            58, 62                                                # 单纯拍手/鼓掌
        }

        self._load_classes()
        self._init_session()

    def _load_classes(self):
        if os.path.exists(self.class_map_path):
            try:
                with open(self.class_map_path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader)
                    for row in reader:
                        self.classes[int(row[0])] = row[2]
            except Exception:
                pass

    def _init_session(self):
        if os.path.exists(self.model_path):
            try:
                import onnxruntime as ort
                self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
            except Exception as e:
                print("加载 YAMNet 模型失败:", e)
                self.session = None

    def is_available(self) -> bool:
        return self.session is not None

    def evaluate_clip(self, y_16k: np.ndarray) -> Dict[str, Any]:
        """
        对输入的 16kHz 音频切片进行 YAMNet 深度语义推断。
        返回：
          - target_score: 拍打/抽打（Slap / Whip）的综合置信分 (0.0 ~ 1.0)
          - is_pure_noise: 是否为纯粹的尖叫/哭喊/敲门/脚步等无拍打噪音 (True 表示应舍弃)
          - top1_label: Top-1 预测标签
        """
        if not self.is_available() or len(y_16k) < 1600:
            return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "unknown"}

        waveform = np.asarray(y_16k, dtype=np.float32)
        max_val = np.max(np.abs(waveform))
        if max_val > 0:
            waveform = waveform / max_val

        try:
            input_name = self.session.get_inputs()[0].name
            outputs = self.session.run(None, {input_name: waveform})
            scores = outputs[0] # [num_frames, 521]

            if len(scores) == 0:
                return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "unknown"}

            max_scores_per_class = np.max(scores, axis=0)

            # 1. 核心目标：Slap (461) 与 Whip (466)
            slap_score = float(max_scores_per_class[461]) if 461 < len(max_scores_per_class) else 0.0
            whip_score = float(max_scores_per_class[466]) if 466 < len(max_scores_per_class) else 0.0
            target_score = max(slap_score, whip_score)

            # 2. 统计强干扰类别得分
            top1_idx = int(np.argmax(max_scores_per_class))
            top1_label = self.classes.get(top1_idx, f"Class {top1_idx}")
            top1_score = float(max_scores_per_class[top1_idx])

            # 检查是否有非拍打噪音极高而拍打分极低的情况
            # 规则：如果 Top-1 是纯人声(哭叫/言语)或关门/脚步，且 target_score 极低(<0.05)，则标记为纯噪音
            is_pure_noise = False
            if top1_idx in self.pure_interference_indices and target_score < 0.04:
                is_pure_noise = True

            # 额外排查纯鼓掌/拍手 (Clapping 58, Applause 62)
            clap_score = float(max_scores_per_class[58]) if 58 < len(max_scores_per_class) else 0.0
            if clap_score > 0.35 and target_score < 0.06:
                is_pure_noise = True

            return {
                "target_score": round(target_score, 3),
                "slap_score": round(slap_score, 3),
                "whip_score": round(whip_score, 3),
                "is_pure_noise": is_pure_noise,
                "top1_label": top1_label,
                "top1_score": round(top1_score, 3)
            }
        except Exception as e:
            return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "error", "error": str(e)}
