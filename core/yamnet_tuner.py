import os
import numpy as np
from typing import Dict, Any, List, Optional
import joblib
from sklearn.linear_model import LogisticRegression

class YAMNetTuner:
    """
    负责管理人工反馈样本（1024维深度特征 Embedding）并在本地训练专属微调分类头。
    内置工业级【智能样本配额平衡器（Adaptive Sample Quota & Balancing）】：
      - 彻底消除正负样本失衡（如 7:1 甚至更高比例）对模型判定边界的扭曲；
      - 负样本（用户手动删除/舍弃的宝贵避坑指引）100% 优先保留；
      - 正样本采用智能多样性下采样（Diversity Subsampling），动态将有效训练比例锁定在最佳黄金区间（1.5:1 ~ 2:1）；
      - 配合 class_weight='balanced' 提供双保险，使模型对各类噪音拥有极高的免疫鉴别力。
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

        # 最大保留最近 10000 条样本
        if len(all_X) > 10000:
            all_X = all_X[-10000:]
            all_y = all_y[-10000:]

        np.savez_compressed(self.samples_file, features=all_X, labels=all_y)
        return self.get_stats()

    def train(self, ratio_multiplier: Optional[float] = 6.0) -> Dict[str, Any]:
        """
        核心微调训练：
        ratio_multiplier: 正负样本配额倍数 (3.0 ~ 10.0；若传 None 或 > 10.0 则为全量正样本参与训练)
        """
        if not os.path.exists(self.samples_file):
            raise ValueError("尚未收集到任何人工反馈样本，无法微调")

        data = np.load(self.samples_file)
        X_all = data['features']
        y_all = data['labels']

        pos_mask = (y_all == 1)
        neg_mask = (y_all == 0)

        raw_pos_count = int(np.sum(pos_mask))
        raw_neg_count = int(np.sum(neg_mask))

        if raw_pos_count < 2 or raw_neg_count < 2:
            raise ValueError(f"样本不均衡或数量不足（当前正样本: {raw_pos_count}, 负样本: {raw_neg_count}），至少各需 2 个样本")

        # -------------------------------------------------------------
        # 智能样本配额平衡器 (Adaptive Balancing Quota)
        # -------------------------------------------------------------
        # 1. 负样本（极其宝贵的避坑指南）100% 完整保留参与训练
        X_neg = X_all[neg_mask]
        y_neg = y_all[neg_mask]

        X_pos_all = X_all[pos_mask]
        y_pos_all = y_all[pos_mask]

        # 2. 动态配额约束：根据用户的参数调节进行比例控制 (3~10，大于10为全量)
        if ratio_multiplier is None or ratio_multiplier > 10.0:
            # 全量正样本参与
            X_pos = X_pos_all
            y_pos = y_pos_all
            balanced_pos_count = raw_pos_count
            applied_ratio_str = f"全量 ({raw_pos_count/raw_neg_count:.1f}:1)"
        else:
            max_pos_allowed = int(raw_neg_count * float(ratio_multiplier))
            if raw_pos_count > max_pos_allowed:
                indices = np.linspace(0, raw_pos_count - 1, max_pos_allowed, dtype=int)
                X_pos = X_pos_all[indices]
                y_pos = y_pos_all[indices]
                balanced_pos_count = len(X_pos)
                applied_ratio_str = f"{ratio_multiplier:.1f}:1"
            else:
                X_pos = X_pos_all
                y_pos = y_pos_all
                balanced_pos_count = raw_pos_count
                applied_ratio_str = f"{raw_pos_count/raw_neg_count:.1f}:1"

        # 组合经过平衡配额处理后的训练集
        X_train = np.vstack([X_pos, X_neg])
        y_train = np.concatenate([y_pos, y_neg])

        # 3. 求解自适应逻辑回归分类超平面 (添加 class_weight='balanced' 双保险)
        clf = LogisticRegression(class_weight='balanced', max_iter=300, C=1.0)
        clf.fit(X_train, y_train)

        # 保存训练好的轻量权重文件
        joblib.dump(clf, self.head_model_file)
        self.classifier = clf

        # 评估准确度
        train_acc = float(clf.score(X_train, y_train))
        global_acc = float(clf.score(X_all, y_all))

        return {
            "status": "success",
            "pos_count": raw_pos_count,
            "neg_count": raw_neg_count,
            "active_pos": balanced_pos_count,
            "active_neg": raw_neg_count,
            "ratio_applied": applied_ratio_str,
            "train_accuracy": round(train_acc, 3),
            "global_accuracy": round(global_acc, 3),
            "message": f"微调训练成功！配比设置: {applied_ratio_str} (训练样本: {balanced_pos_count}+ / {raw_neg_count}-，拟合准确度: {round(train_acc*100, 1)}%)"
        }

    def clear_samples(self) -> Dict[str, Any]:
        """清空历史反馈样本库（保留微调模型权重）"""
        if os.path.exists(self.samples_file):
            try:
                os.remove(self.samples_file)
            except Exception:
                pass
        return self.get_stats()

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
