import os
import numpy as np
from typing import Dict, Any, List, Optional
import joblib
from sklearn.linear_model import LogisticRegression

class YAMNetTuner:
    """
    负责管理人工反馈样本（1024维深度特征 Embedding）并在本地训练专属微调分类头。
    采用 Logistic Regression 建立专属分类器，毫秒级训练与推断。
    """

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.models_dir = os.path.join(self.base_dir, "models")
        os.makedirs(self.models_dir, exist_ok=True)

        self.samples_file = os.path.join(self.models_dir, "feedback_samples.npz")
        self.head_model_file = os.path.join(self.models_dir, "yamnet_custom_head.joblib")
        self.classifier = None
        self._load_head()

    def _load_head(self):
        if os.path.exists(self.head_model_file):
            try:
                self.classifier = joblib.load(self.head_model_file)
            except Exception as e:
                print("加载本地微调权重失败:", e)
                self.classifier = None

    def get_stats(self) -> Dict[str, Any]:
        """获取当前收集的正负样本数量与模型微调状态"""
        pos_count = 0
        neg_count = 0
        if os.path.exists(self.samples_file):
            try:
                data = np.load(self.samples_file)
                labels = data['labels']
                pos_count = int(np.sum(labels == 1))
                neg_count = int(np.sum(labels == 0))
            except Exception:
                pass

        return {
            "pos_count": pos_count,
            "neg_count": neg_count,
            "total_count": pos_count + neg_count,
            "is_tuned": self.classifier is not None,
            "can_tune": (pos_count >= 2 and neg_count >= 2)
        }

    def record_feedback(self, embeddings: List[np.ndarray], labels: List[int]) -> Dict[str, Any]:
        """
        持久化追加记录用户的人工反馈样本
        embeddings: 1024 维特征向量列表
        labels: 1 表示真实拍打（正样本），0 表示噪音误报（负样本）
        """
        if not embeddings or not labels or len(embeddings) != len(labels):
            return self.get_stats()

        new_X = np.asarray(embeddings, dtype=np.float32)
        new_y = np.asarray(labels, dtype=np.int32)

        if os.path.exists(self.samples_file):
            try:
                old_data = np.load(self.samples_file)
                old_X = old_data['features']
                old_y = old_data['labels']
                all_X = np.vstack([old_X, new_X])
                all_y = np.concatenate([old_y, new_y])
            except Exception:
                all_X = new_X
                all_y = new_y
        else:
            all_X = new_X
            all_y = new_y

        # 去除极度重复的样本，限制最大保留 5000 条
        if len(all_X) > 5000:
            all_X = all_X[-5000:]
            all_y = all_y[-5000:]

        np.savez_compressed(self.samples_file, features=all_X, labels=all_y)
        return self.get_stats()

    def train(self) -> Dict[str, Any]:
        """基于已积累的人工反馈样本，在本地一键训练专属的分类头"""
        if not os.path.exists(self.samples_file):
            raise ValueError("尚未收集到任何人工反馈样本，无法微调")

        data = np.load(self.samples_file)
        X = data['features']
        y = data['labels']

        pos_count = int(np.sum(y == 1))
        neg_count = int(np.sum(y == 0))

        if pos_count < 2 or neg_count < 2:
            raise ValueError(f"样本不均衡或数量不足（当前正样本: {pos_count}, 负样本: {neg_count}），至少各需 2 个样本")

        # 使用带平衡权重的逻辑回归，防止样本倾斜
        clf = LogisticRegression(class_weight='balanced', max_iter=200, C=1.0)
        clf.fit(X, y)

        # 保存权重
        joblib.dump(clf, self.head_model_file)
        self.classifier = clf

        # 评估自身拟合准确率
        acc = float(clf.score(X, y))

        return {
            "status": "success",
            "pos_count": pos_count,
            "neg_count": neg_count,
            "train_accuracy": round(acc, 3),
            "message": f"微调训练完成！基于 {len(y)} 个专属样本优化（准确度: {round(acc*100, 1)}%）"
        }

    def predict_score(self, embedding: np.ndarray) -> Optional[float]:
        """利用微调后的模型对单个 1024 维特征预测其属于拍打的概率 (0.0 ~ 1.0)"""
        if self.classifier is None:
            return None
        try:
            feat = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
            proba = self.classifier.predict_proba(feat)[0][1] # 属于正样本(拍打)的概率
            return float(proba)
        except Exception:
            return None
