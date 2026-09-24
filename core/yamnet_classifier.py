import os
import csv
import numpy as np
import librosa
from typing import List, Dict, Any, Optional
from core.yamnet_tuner import YAMNetTuner

class YAMNetClassifier:
    """
    基于 Google AudioSet 预训练 YAMNet 深度神经网络的拍打/抽打声音事件分类器，
    并挂载本地专属 RLHF 人工反馈微调头（YAMNetTuner）。
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

        # 强干扰误报类别（无拍打伴运行时直接剔除）
        self.pure_interference_indices = {
            0, 1, 5, 6, 9, 10, 11, 13, 14, 15, 19, 23, 33, 34, 65, # 人声/尖叫/哭泣/喘息
            48,                                                   # 脚步/地面声
            348, 351, 353,                                        # 关门/敲门声
            58, 62                                                # 单纯拍手/鼓掌
        }

        self.tuner = YAMNetTuner()
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
        对输入的 16kHz 音频切片进行 YAMNet 深度语义推断，并由本地微调模型联合修正。
        返回：
          - target_score: 融合了 Google 原始分与本地微调权重的综合判定分
          - embedding: 1024 维特征向量（供人工反馈学习）
          - is_pure_noise: 是否为纯噪音（应舍弃）
        """
        if not self.is_available() or len(y_16k) < 1600:
            return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "unknown", "embedding": None}

        waveform = np.asarray(y_16k, dtype=np.float32)
        max_val = np.max(np.abs(waveform))
        if max_val > 0:
            waveform = waveform / max_val

        try:
            input_name = self.session.get_inputs()[0].name
            outputs = self.session.run(None, {input_name: waveform})
            scores = outputs[0]      # [num_frames, 521]
            embeddings = outputs[1]  # [num_frames, 1024]

            if len(scores) == 0:
                return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "unknown", "embedding": None}

            max_scores_per_class = np.max(scores, axis=0)
            # 取整段切片中能量最强帧的 1024 维 Embedding，用于本地微调特征库
            mean_embedding = np.mean(embeddings, axis=0) # [1024]

            # 1. Google 原始分类分值
            slap_score = float(max_scores_per_class[461]) if 461 < len(max_scores_per_class) else 0.0
            whip_score = float(max_scores_per_class[466]) if 466 < len(max_scores_per_class) else 0.0
            raw_target_score = max(slap_score, whip_score)

            # 2. 本地微调模型预测分（如果用户已经微调过）
            custom_score = self.tuner.predict_score(mean_embedding)

            # 3. 融合分计算：若已有本地微调模型，赋予本地模型 60% 决策权，大幅纠偏 Google 通用模型的偏差！
            if custom_score is not None:
                final_target_score = round(0.4 * raw_target_score + 0.6 * custom_score, 3)
            else:
                final_target_score = round(raw_target_score, 3)

            # 4. 统计强干扰类别得分
            top1_idx = int(np.argmax(max_scores_per_class))
            top1_label = self.classes.get(top1_idx, f"Class {top1_idx}")
            top1_score = float(max_scores_per_class[top1_idx])

            is_pure_noise = False
            # 只有当本地模型和原始模型均判定不是拍打时，才触发一票否决
            if top1_idx in self.pure_interference_indices and final_target_score < 0.05:
                is_pure_noise = True

            clap_score = float(max_scores_per_class[58]) if 58 < len(max_scores_per_class) else 0.0
            if clap_score > 0.35 and final_target_score < 0.06:
                is_pure_noise = True

            return {
                "target_score": final_target_score,
                "raw_target_score": round(raw_target_score, 3),
                "custom_score": round(custom_score, 3) if custom_score is not None else None,
                "embedding": mean_embedding,
                "is_pure_noise": is_pure_noise,
                "top1_label": top1_label,
                "top1_score": round(top1_score, 3)
            }
        except Exception as e:
            return {"target_score": 0.5, "is_pure_noise": False, "top1_label": "error", "error": str(e), "embedding": None}
