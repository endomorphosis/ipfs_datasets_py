"""
Integration tests for ML confidence scoring.

Tests ML confidence scorer functionality end-to-end.
"""

import pytest
import numpy as np
from pathlib import Path
from ipfs_datasets_py.logic.ml_confidence import (
    MLConfidenceScorer,
    MLConfidenceConfig,
    FeatureExtractor,
)


class TestMLConfidenceScorerIntegration:
    """Integration tests for ML confidence scorer."""

    def test_feature_extraction(self):
        """
        GIVEN: Sentence and formula
        WHEN: Extracting features
        THEN: Should produce 22-dimensional vector
        """
        extractor = FeatureExtractor()
        
        features = extractor.extract_features(
            sentence="All humans are mortal",
            fol_formula="∀x(Human(x) → Mortal(x))",
            predicates={"nouns": ["humans"], "verbs": ["are"]},
            quantifiers=["∀"],
            operators=["→"]
        )
        
        assert isinstance(features, np.ndarray)
        assert features.shape == (22,)
        assert features.dtype == np.float32

    def test_heuristic_fallback(self):
        """
        GIVEN: Untrained scorer
        WHEN: Predicting confidence
        THEN: Should use heuristic scoring
        """
        config = MLConfidenceConfig(fallback_to_heuristic=True)
        scorer = MLConfidenceScorer(config)
        
        confidence = scorer.predict_confidence(
            sentence="All humans are mortal",
            fol_formula="∀x(Human(x) → Mortal(x))",
            predicates={"nouns": ["humans"], "verbs": ["are"]},
            quantifiers=["∀"],
            operators=["→"]
        )
        
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.3  # Should have reasonable heuristic score

    def test_heuristic_scoring_quality(self):
        """
        GIVEN: Different quality conversions
        WHEN: Using heuristic scoring
        THEN: Better conversions should score higher
        """
        scorer = MLConfidenceScorer(
            MLConfidenceConfig(fallback_to_heuristic=True)
        )
        
        # Good conversion
        good_confidence = scorer.predict_confidence(
            sentence="All humans are mortal",
            fol_formula="∀x(Human(x) → Mortal(x))",
            predicates={"nouns": ["humans"], "verbs": ["are"]},
            quantifiers=["∀"],
            operators=["→"]
        )
        
        # Poor conversion
        poor_confidence = scorer.predict_confidence(
            sentence="Complex ambiguous sentence",
            fol_formula="P",  # Too simple
            predicates={},
            quantifiers=[],
            operators=[]
        )
        
        assert good_confidence > poor_confidence

    def test_training_with_synthetic_data(self):
        """
        GIVEN: Synthetic training data
        WHEN: Training model
        THEN: Should train successfully
        """
        try:
            import xgboost
            XGBOOST_AVAILABLE = True
        except ImportError:
            XGBOOST_AVAILABLE = False
        
        if not XGBOOST_AVAILABLE:
            pytest.skip("XGBoost not available")
        
        scorer = MLConfidenceScorer()
        
        # Generate synthetic training data
        np.random.seed(42)
        X = np.random.rand(100, 22).astype(np.float32)
        y = (X[:, 0] + X[:, 7] > 1.0).astype(int)  # Simple rule
        
        metrics = scorer.train(X, y, validation_split=0.2)
        
        assert 'train_accuracy' in metrics
        assert 'val_accuracy' in metrics
        assert metrics['train_accuracy'] > 0.5
        assert metrics['val_accuracy'] > 0.5

    def test_prediction_after_training(self):
        """
        GIVEN: Trained model
        WHEN: Making predictions
        THEN: Should predict confidence scores
        """
        try:
            import xgboost
            XGBOOST_AVAILABLE = True
        except ImportError:
            XGBOOST_AVAILABLE = False
        
        if not XGBOOST_AVAILABLE:
            pytest.skip("XGBoost not available")
        
        scorer = MLConfidenceScorer()
        
        # Train with synthetic data
        np.random.seed(42)
        X = np.random.rand(100, 22).astype(np.float32)
        y = np.random.rand(100)  # Random confidence scores [0, 1]
        
        scorer.train(X, y, validation_split=0.2, task_type="regression")
        
        # Predict
        confidence = scorer.predict_confidence(
            sentence="All humans are mortal",
            fol_formula="∀x(Human(x) → Mortal(x))",
            predicates={"nouns": ["humans"]},
            quantifiers=["∀"],
            operators=["→"]
        )
        
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    def test_model_persistence(self, tmp_path):
        """
        GIVEN: Trained model
        WHEN: Saving and loading
        THEN: Should persist state correctly
        """
        try:
            import xgboost
            XGBOOST_AVAILABLE = True
        except ImportError:
            XGBOOST_AVAILABLE = False
        
        if not XGBOOST_AVAILABLE:
            pytest.skip("XGBoost not available")
        
        scorer1 = MLConfidenceScorer()
        
        # Train
        np.random.seed(42)
        X = np.random.rand(50, 22).astype(np.float32)
        y = np.random.rand(50)
        scorer1.train(X, y, validation_split=0.2)
        
        # Save
        model_path = tmp_path / "model.pkl"
        scorer1.save_model(model_path)
        
        # Load into new scorer
        scorer2 = MLConfidenceScorer()
        scorer2.load_model(model_path)
        
        # Both should give same predictions
        confidence1 = scorer1.predict_confidence(
            "Test", "P(x)", {}, [], []
        )
        confidence2 = scorer2.predict_confidence(
            "Test", "P(x)", {}, [], []
        )
        
        assert abs(confidence1 - confidence2) < 0.01


class TestFeatureExtractorIntegration:
    """Integration tests for feature extraction."""

    def test_comprehensive_feature_extraction(self):
        """
        GIVEN: Complex sentence and formula
        WHEN: Extracting all features
        THEN: Should capture all aspects
        """
        extractor = FeatureExtractor()
        
        features = extractor.extract_features(
            sentence="If all humans are mortal and Socrates is a human, then Socrates is mortal",
            fol_formula="∀x(Human(x) → Mortal(x)) ∧ Human(Socrates) → Mortal(Socrates)",
            predicates={
                "nouns": ["humans", "Socrates"],
                "verbs": ["are", "is"],
                "adjectives": ["mortal"]
            },
            quantifiers=["∀"],
            operators=["→", "∧"]
        )
        
        # Check all 22 features are extracted
        assert len(features) == 22
        
        # Sentence features
        assert features[0] > 50  # Sentence length
        assert features[1] > 10  # Word count
        
        # Formula features
        assert features[4] > 50  # Formula length
        assert features[6] > 0   # Quantifiers in formula
        
        # Predicate features
        assert features[7] > 0   # Total predicates
        assert features[8] > 0   # Noun predicates

    def test_edge_case_empty_inputs(self):
        """
        GIVEN: Empty or minimal inputs
        WHEN: Extracting features
        THEN: Should handle gracefully
        """
        extractor = FeatureExtractor()
        
        features = extractor.extract_features(
            sentence="",
            fol_formula="",
            predicates={},
            quantifiers=[],
            operators=[]
        )
        
        assert len(features) == 22
        assert all(f >= 0 for f in features)  # All non-negative

    def test_feature_ranges(self):
        """
        GIVEN: Various inputs
        WHEN: Extracting features
        THEN: Should produce reasonable ranges
        """
        extractor = FeatureExtractor()
        
        features = extractor.extract_features(
            sentence="Simple sentence",
            fol_formula="P(x)",
            predicates={"nouns": ["sentence"]},
            quantifiers=[],
            operators=[]
        )
        
        # All features should be finite and non-negative
        assert all(np.isfinite(f) for f in features)
        assert all(f >= 0 for f in features)


class TestMLConfidenceEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_dependencies_fallback(self):
        """
        GIVEN: XGBoost/LightGBM not available
        WHEN: Creating scorer with fallback enabled
        THEN: Should work with heuristic
        """
        config = MLConfidenceConfig(fallback_to_heuristic=True)
        scorer = MLConfidenceScorer(config)
        
        # Should work even without ML libraries
        confidence = scorer.predict_confidence(
            "Test", "P(x)", {}, [], []
        )
        
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    def test_extreme_input_lengths(self):
        """
        GIVEN: Very long or very short inputs
        WHEN: Extracting features and predicting
        THEN: Should handle without error
        """
        scorer = MLConfidenceScorer(
            MLConfidenceConfig(fallback_to_heuristic=True)
        )
        
        # Very short
        conf1 = scorer.predict_confidence("A", "P", {}, [], [])
        assert 0.0 <= conf1 <= 1.0
        
        # Very long
        long_sentence = "word " * 1000
        long_formula = "P(x) ∧ " * 100
        conf2 = scorer.predict_confidence(
            long_sentence,
            long_formula,
            {"nouns": ["word"] * 100},
            ["∀"] * 50,
            ["∧"] * 100
        )
        assert 0.0 <= conf2 <= 1.0

    def test_unicode_handling(self):
        """
        GIVEN: Unicode characters in input
        WHEN: Extracting features
        THEN: Should handle properly
        """
        scorer = MLConfidenceScorer(
            MLConfidenceConfig(fallback_to_heuristic=True)
        )
        
        confidence = scorer.predict_confidence(
            sentence="Café résumé naïve",
            fol_formula="∀x(P(x) → Q(x))",
            predicates={"nouns": ["Café"]},
            quantifiers=["∀"],
            operators=["→"]
        )
        
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0


class TestMLConfidencePerformance:
    """Performance tests for ML confidence scoring."""

    def test_prediction_speed(self):
        """
        GIVEN: Trained model
        WHEN: Making predictions
        THEN: Should be fast (<10ms)
        """
        import time
        
        scorer = MLConfidenceScorer(
            MLConfidenceConfig(fallback_to_heuristic=True)
        )
        
        # Time 100 predictions
        times = []
        for _ in range(100):
            start = time.time()
            scorer.predict_confidence(
                "All humans are mortal",
                "∀x(Human(x) → Mortal(x))",
                {"nouns": ["humans"]},
                ["∀"],
                ["→"]
            )
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times)
        assert avg_time < 0.01  # <10ms average


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
