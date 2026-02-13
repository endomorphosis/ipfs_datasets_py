"""
ML-based confidence scoring for FOL conversion.

Uses gradient boosting (XGBoost/LightGBM fallback) to predict
conversion quality based on extracted features.

Features:
- Feature engineering from text and formulas
- Gradient boosting classifier
- Model training and evaluation
- Fallback to heuristic scoring
"""

import logging
import pickle
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import ML libraries
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    logger.warning("XGBoost not available. Install with: pip install xgboost")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    logger.warning("LightGBM not available. Install with: pip install lightgbm")


@dataclass
class MLConfidenceConfig:
    """Configuration for ML confidence scorer."""
    model_path: Optional[Path] = None
    use_xgboost: bool = True  # Prefer XGBoost over LightGBM
    n_estimators: int = 100
    max_depth: int = 6
    learning_rate: float = 0.1
    fallback_to_heuristic: bool = True


class FeatureExtractor:
    """Extract features for ML confidence prediction."""
    
    @staticmethod
    def extract_features(
        sentence: str,
        fol_formula: str,
        predicates: Dict[str, List[str]],
        quantifiers: List[str],
        operators: List[str],
    ) -> np.ndarray:
        """
        Extract feature vector for ML model.
        
        Args:
            sentence: Original natural language sentence
            fol_formula: Generated FOL formula
            predicates: Extracted predicates dictionary
            quantifiers: List of quantifiers
            operators: List of logical operators
            
        Returns:
            Feature vector as numpy array
        """
        features = []
        
        # Text features
        features.append(len(sentence))  # 0: Sentence length
        features.append(len(sentence.split()))  # 1: Word count
        features.append(sentence.count(','))  # 2: Comma count
        features.append(sentence.count('.'))  # 3: Period count
        
        # Formula features
        features.append(len(fol_formula))  # 4: Formula length
        features.append(fol_formula.count('('))  # 5: Parenthesis depth
        features.append(fol_formula.count('∀') + fol_formula.count('∃'))  # 6: Quantifier count
        
        # Predicate features
        total_predicates = sum(len(v) for v in predicates.values())
        features.append(total_predicates)  # 7: Total predicates
        features.append(len(predicates.get('nouns', [])))  # 8: Noun predicates
        features.append(len(predicates.get('verbs', [])))  # 9: Verb predicates
        features.append(len(predicates.get('adjectives', [])))  # 10: Adjective predicates
        
        # Logical structure features
        features.append(len(quantifiers))  # 11: Quantifier count
        features.append(len(operators))  # 12: Operator count
        features.append(quantifiers.count('∀'))  # 13: Universal quantifiers
        features.append(quantifiers.count('∃'))  # 14: Existential quantifiers
        
        # Operator distribution
        features.append(operators.count('∧'))  # 15: AND operators
        features.append(operators.count('∨'))  # 16: OR operators
        features.append(operators.count('→'))  # 17: IMPLIES operators
        features.append(operators.count('¬'))  # 18: NOT operators
        
        # Complexity indicators
        features.append(len(fol_formula) / max(len(sentence), 1))  # 19: Formula/sentence ratio
        features.append(total_predicates / max(len(sentence.split()), 1))  # 20: Predicates per word
        
        # Logical indicator keywords
        keywords = ['all', 'some', 'if', 'then', 'and', 'or', 'not', 'every', 'each']
        features.append(sum(sentence.lower().count(kw) for kw in keywords))  # 21: Keyword count
        
        return np.array(features, dtype=np.float32)


class MLConfidenceScorer:
    """ML-based confidence scoring for FOL conversion."""
    
    def __init__(self, config: Optional[MLConfidenceConfig] = None):
        """
        Initialize ML confidence scorer.
        
        Args:
            config: Configuration for the scorer
        """
        self.config = config or MLConfidenceConfig()
        self.model = None
        self.feature_extractor = FeatureExtractor()
        self._is_trained = False
        
        # Load model if path provided
        if self.config.model_path and self.config.model_path.exists():
            self.load_model(self.config.model_path)
    
    def extract_features(
        self,
        sentence: str,
        fol_formula: str,
        predicates: Dict[str, List[str]],
        quantifiers: List[str],
        operators: List[str],
    ) -> np.ndarray:
        """Extract features for prediction."""
        return self.feature_extractor.extract_features(
            sentence, fol_formula, predicates, quantifiers, operators
        )
    
    def predict_confidence(
        self,
        sentence: str,
        fol_formula: str,
        predicates: Dict[str, List[str]],
        quantifiers: List[str],
        operators: List[str],
    ) -> float:
        """
        Predict confidence score for FOL conversion.
        
        Args:
            sentence: Original sentence
            fol_formula: Generated formula
            predicates: Extracted predicates
            quantifiers: Quantifiers list
            operators: Operators list
            
        Returns:
            Confidence score between 0 and 1
        """
        # If model not trained, use heuristic fallback
        if not self._is_trained:
            if self.config.fallback_to_heuristic:
                return self._heuristic_confidence(
                    sentence, fol_formula, predicates, quantifiers, operators
                )
            else:
                logger.warning("Model not trained and fallback disabled")
                return 0.5
        
        try:
            features = self.extract_features(
                sentence, fol_formula, predicates, quantifiers, operators
            )
            features = features.reshape(1, -1)  # Add batch dimension
            
            if XGBOOST_AVAILABLE and self.config.use_xgboost:
                pred = self.model.predict_proba(features)[0, 1]
            elif LIGHTGBM_AVAILABLE:
                pred = self.model.predict(features)[0]
            else:
                # Fallback
                return self._heuristic_confidence(
                    sentence, fol_formula, predicates, quantifiers, operators
                )
            
            return float(np.clip(pred, 0.0, 1.0))
        
        except Exception as e:
            logger.error(f"ML prediction failed: {e}")
            if self.config.fallback_to_heuristic:
                return self._heuristic_confidence(
                    sentence, fol_formula, predicates, quantifiers, operators
                )
            return 0.5
    
    def _heuristic_confidence(
        self,
        sentence: str,
        fol_formula: str,
        predicates: Dict[str, List[str]],
        quantifiers: List[str],
        operators: List[str],
    ) -> float:
        """
        Heuristic-based confidence scoring (fallback).
        
        Returns:
            Confidence score between 0 and 1
        """
        score = 0.0
        
        # Base score for having any predicates
        total_predicates = sum(len(v) for v in predicates.values())
        if total_predicates > 0:
            score += 0.3
        
        # Bonus for logical structure
        if len(quantifiers) > 0:
            score += 0.2
        if len(operators) > 0:
            score += 0.2
        
        # Bonus for keyword indicators
        keywords = ['all', 'some', 'if', 'then', 'and', 'or', 'not']
        keyword_count = sum(sentence.lower().count(kw) for kw in keywords)
        score += min(0.2, keyword_count * 0.05)
        
        # Penalty for very short or very long formulas
        if len(fol_formula) < 5:
            score -= 0.2
        if len(fol_formula) > 200:
            score -= 0.1
        
        return max(0.0, min(1.0, score))
    
    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        validation_split: float = 0.2,
        task_type: str = "regression",
    ) -> Dict[str, float]:
        """
        Train ML model on labeled data.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target labels (n_samples,) - continuous [0, 1] for regression or binary {0, 1} for classification
            validation_split: Fraction for validation set
            task_type: Either "regression" (continuous) or "classification" (binary)
            
        Returns:
            Training metrics dictionary
        """
        if not XGBOOST_AVAILABLE and not LIGHTGBM_AVAILABLE:
            raise RuntimeError(
                "Neither XGBoost nor LightGBM available. "
                "Install with: pip install xgboost lightgbm"
            )
        
        # Validate task_type
        if task_type not in ["regression", "classification"]:
            raise ValueError(f"task_type must be 'regression' or 'classification', got {task_type}")
        
        # Split data
        n_train = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:n_train], X[n_train:]
        y_train, y_val = y[:n_train], y[n_train:]
        
        logger.info(f"Training {task_type} model on {len(X_train)} samples, validating on {len(X_val)}")
        
        if self.config.use_xgboost and XGBOOST_AVAILABLE:
            # XGBoost training
            if task_type == "classification":
                self.model = xgb.XGBClassifier(
                    n_estimators=self.config.n_estimators,
                    max_depth=self.config.max_depth,
                    learning_rate=self.config.learning_rate,
                    objective='binary:logistic',
                    eval_metric='logloss',
                )
            else:  # regression
                self.model = xgb.XGBRegressor(
                    n_estimators=self.config.n_estimators,
                    max_depth=self.config.max_depth,
                    learning_rate=self.config.learning_rate,
                    objective='reg:squarederror',
                    eval_metric='rmse',
                )
            
            self.model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )
            
            if task_type == "classification":
                train_score = self.model.score(X_train, y_train)
                val_score = self.model.score(X_val, y_val)
            else:  # regression - use R^2 score
                train_pred = self.model.predict(X_train)
                val_pred = self.model.predict(X_val)
                train_score = 1 - np.mean((train_pred - y_train) ** 2) / np.var(y_train)
                val_score = 1 - np.mean((val_pred - y_val) ** 2) / np.var(y_val)
            
        elif LIGHTGBM_AVAILABLE:
            # LightGBM training
            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            
            if task_type == "classification":
                params = {
                    'objective': 'binary',
                    'metric': 'binary_logloss',
                    'num_leaves': 2 ** self.config.max_depth,
                    'learning_rate': self.config.learning_rate,
                    'verbose': -1,
                }
            else:  # regression
                params = {
                    'objective': 'regression',
                    'metric': 'rmse',
                    'num_leaves': 2 ** self.config.max_depth,
                    'learning_rate': self.config.learning_rate,
                    'verbose': -1,
                }
            
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=self.config.n_estimators,
                valid_sets=[val_data],
                callbacks=[lgb.early_stopping(10)],
            )
            
            train_pred = self.model.predict(X_train)
            val_pred = self.model.predict(X_val)
            
            if task_type == "classification":
                train_score = np.mean((train_pred > 0.5) == y_train)
                val_score = np.mean((val_pred > 0.5) == y_val)
            else:  # regression - use R^2 score
                train_score = 1 - np.mean((train_pred - y_train) ** 2) / np.var(y_train)
                val_score = 1 - np.mean((val_pred - y_val) ** 2) / np.var(y_val)
        
        self._is_trained = True
        
        metrics = {
            'train_accuracy': float(train_score),
            'val_accuracy': float(val_score),
            'n_train': len(X_train),
            'n_val': len(X_val),
        }
        
        logger.info(
            f"Training complete: train_acc={train_score:.3f}, "
            f"val_acc={val_score:.3f}"
        )
        
        return metrics
    
    def save_model(self, path: Path) -> None:
        """Save trained model to file."""
        if not self._is_trained:
            raise RuntimeError("Model not trained yet")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'config': self.config,
                'is_trained': self._is_trained,
            }, f)
        
        logger.info(f"Model saved to {path}")
    
    def load_model(self, path: Path) -> None:
        """Load trained model from file."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        
        self.model = data['model']
        self.config = data['config']
        self._is_trained = data['is_trained']
        
        logger.info(f"Model loaded from {path}")
    
    def get_feature_importance(self) -> Optional[Dict[str, float]]:
        """
        Get feature importance scores.
        
        Returns:
            Dictionary mapping feature names to importance scores
        """
        if not self._is_trained:
            return None
        
        feature_names = [
            'sentence_length', 'word_count', 'comma_count', 'period_count',
            'formula_length', 'parenthesis_depth', 'quantifier_count_formula',
            'total_predicates', 'noun_predicates', 'verb_predicates', 'adj_predicates',
            'quantifier_count', 'operator_count', 'universal_quantifiers', 'existential_quantifiers',
            'and_operators', 'or_operators', 'implies_operators', 'not_operators',
            'formula_sentence_ratio', 'predicates_per_word', 'keyword_count',
        ]
        
        try:
            if hasattr(self.model, 'feature_importances_'):
                importances = self.model.feature_importances_
            elif hasattr(self.model, 'feature_importance'):
                importances = self.model.feature_importance()
            else:
                return None
            
            return dict(zip(feature_names, importances))
        
        except Exception as e:
            logger.error(f"Failed to get feature importance: {e}")
            return None


__all__ = [
    "MLConfidenceConfig",
    "FeatureExtractor",
    "MLConfidenceScorer",
]
