import os
import csv
import numpy as np
import librosa
from typing import List, Dict, Any, Optional

class YAMNetClassifier:
    """
    基于 Google AudioSet 预训练 YAMNet 深度神经网络的拍打/抽打声音事件分类器。

    重点关注类别：
      - Class 461: Slap, smack (拍打、肉体脆响)
      - Class 466: Whip (抽打、皮鞭破空及撞击)
    排除类别：
      - Class 58: Clapping (拍手)
      - Class 62: Applause (欢呼鼓掌)
      - Class 353: Knock (敲击/敲门)
    """

    def __init__(self, model_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if model_path is None:
            model_path = os.path.join(base_dir, "models", "yamnet.onnx")
        self.class_map_path = os.path.join(base_dir, "models", "yamnet_class_map.csv")
        self.model_path = model_path
        self.session = None
        self.classes = {}
        self.target_indices = [461, 466] # Slap/smack, Whip
        self.reject_indices = [58, 62, 353] # Clapping, Applause, Knock

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
                # 优先使用 CPUExecutionProvider，轻量无报错
                self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
            except Exception as e:
                print("加载 YAMNet 模型失败:", e)
                self.session = None

    def is_available(self) -> bool:
        return self.session is not None

    def evaluate_clip(self, y_16k: np.ndarray) -> Dict[str, Any]:
        """
        对输入的 16kHz 单声道音频切片进行深度神经网络推理，返回命中概率。
        输入：以拍打点为中心的 0.975s ~ 1.5s 音频段。
        """
        if not self.is_available() or len(y_16k) < 1600:
            return {"score": 0.5, "label": "unknown", "is_match": True}

        # 确保输入数据为 float32 且在 [-1.0, 1.0] 范围内
        waveform = np.asarray(y_16k, dtype=np.float32)
        max_val = np.max(np.abs(waveform))
        if max_val > 0:
            waveform = waveform / max_val

        try:
            input_name = self.session.get_inputs()[0].name
            # 推理得到 [N, 521] 概率矩阵
            outputs = self.session.run(None, {input_name: waveform})
            scores = outputs[0] # [num_frames, 521]

            if len(scores) == 0:
                return {"score": 0.5, "label": "unknown", "is_match": True}

            # 取所有帧中的最大概率作为事件发生标志
            max_scores_per_class = np.max(scores, axis=0)

            # 目标拍打/抽打类别最高分
            slap_score = float(max_scores_per_class[461]) if 461 < len(max_scores_per_class) else 0.0
            whip_score = float(max_scores_per_class[466]) if 466 < len(max_scores_per_class) else 0.0
            target_score = max(slap_score, whip_score)

            # 噪音干扰类别最高分
            clap_score = float(max_scores_per_class[58]) if 58 < len(max_scores_per_class) else 0.0
            knock_score = float(max_scores_per_class[353]) if 353 < len(max_scores_per_class) else 0.0

            # 获取 Top-1 分类标签
            top1_idx = int(np.argmax(max_scores_per_class))
            top1_label = self.classes.get(top1_idx, f"Class {top1_idx}")
            top1_score = float(max_scores_per_class[top1_idx])

            return {
                "target_score": round(target_score, 3),
                "slap_score": round(slap_score, 3),
                "whip_score": round(whip_score, 3),
                "clap_score": round(clap_score, 3),
                "knock_score": round(knock_score, 3),
                "top1_label": top1_label,
                "top1_score": round(top1_score, 3)
            }
        except Exception as e:
            return {"target_score": 0.5, "top1_label": "error", "error": str(e)}
