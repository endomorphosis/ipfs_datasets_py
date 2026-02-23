"""Unit tests for Batch 215 GraphRAG enhancements.

Tests for:
1. OntologyOptimizer.score_trend_slope() enhanced docstring (manual verification - covered by Batch 214)
2. OntologyLearningAdapter.feedback_autocorrelation(lag)
3. Performance profiling of OntologyCritic.evaluate_ontology()
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ========================================================================
# Tests for OntologyLearningAdapter.feedback_autocorrelation
# ========================================================================


class TestOntologyLearningAdapterFeedbackAutocorrelation:
    """Test feedback_autocorrelation method."""

    def test_autocorrelation_empty_feedback(self):
        """Should return 0.0 when no feedback exists."""
        adapter = OntologyLearningAdapter()
        acf = adapter.feedback_autocorrelation(lag=1)
        assert acf == 0.0

    def test_autocorrelation_too_few_records(self):
        """Should return 0.0 when records <= lag."""
        adapter = OntologyLearningAdapter()
        adapter.apply_feedback(final_score=0.5, actions=["generate"])
        # Only 1 record, lag=1 requires at least 2
        acf = adapter.feedback_autocorrelation(lag=1)
        assert acf == 0.0

    def test_autocorrelation_exactly_lag_plus_one(self):
        """Should compute when records == lag + 1."""
        adapter = OntologyLearningAdapter()
        adapter.apply_feedback(final_score=0.5, actions=["generate"])
        adapter.apply_feedback(final_score=0.7, actions=["refine"])
        # 2 records, lag=1: should compute
        acf = adapter.feedback_autocorrelation(lag=1)
        assert isinstance(acf, float)
        assert -1.0 <= acf <= 1.0

    def test_autocorrelation_constant_series_zero_variance(self):
        """Should return 0.0 when feedback has zero variance."""
        adapter = OntologyLearningAdapter()
        for _ in range(5):
            adapter.apply_feedback(final_score=0.6, actions=["generate"])
        acf = adapter.feedback_autocorrelation(lag=1)
        assert acf == 0.0

    def test_autocorrelation_perfect_positive_correlation(self):
        """Should return near 1.0 for strongly autocorrelated series."""
        adapter = OntologyLearningAdapter()
        # Slowly increasing series: strongly autocorrelated
        for i in range(10):
            adapter.apply_feedback(final_score=0.5 + i * 0.01, actions=["generate"])
        acf = adapter.feedback_autocorrelation(lag=1)
        assert acf > 0.6  # Strong positive autocorrelation

    def test_autocorrelation_negative_correlation(self):
        """Should return negative value for alternating series."""
        adapter = OntologyLearningAdapter()
        # Alternating high-low pattern
        for i in range(10):
            score = 0.8 if i % 2 == 0 else 0.4
            adapter.apply_feedback(final_score=score, actions=["generate"])
        acf = adapter.feedback_autocorrelation(lag=1)
        assert acf < 0  # Negative autocorrelation

    def test_autocorrelation_lag_2_cyclic_pattern(self):
        """Should detect cyclic pattern with lag=2."""
        adapter = OntologyLearningAdapter()
        # Pattern repeats every 2 steps: [0.5, 0.7, 0.5, 0.7, ...]
        for i in range(10):
            score = 0.5 if i % 2 == 0 else 0.7
            adapter.apply_feedback(final_score=score, actions=["generate"])
        # Lag-2 should show high positive correlation
        acf2 = adapter.feedback_autocorrelation(lag=2)
        assert acf2 > 0.7

    def test_autocorrelation_returns_float(self):
        """Should always return float type."""
        adapter = OntologyLearningAdapter()
        adapter.apply_feedback(final_score=0.5, actions=["generate"])
        adapter.apply_feedback(final_score=0.6, actions=["refine"])
        adapter.apply_feedback(final_score=0.55, actions=["generate"])
        acf = adapter.feedback_autocorrelation(lag=1)
        assert isinstance(acf, float)

    def test_autocorrelation_bounded_output(self):
        """Should always return value in [-1, 1]."""
        adapter = OntologyLearningAdapter()
        # Random-ish scores
        scores = [0.5, 0.7, 0.4, 0.8, 0.6, 0.9, 0.3, 0.75, 0.55, 0.65]
        for s in scores:
            adapter.apply_feedback(final_score=s, actions=["generate"])
        for lag in [1, 2, 3]:
            acf = adapter.feedback_autocorrelation(lag=lag)
            assert -1.0 <= acf <= 1.0

    def test_autocorrelation_lag_validation(self):
        """Should handle edge cases for lag parameter."""
        adapter = OntologyLearningAdapter()
        for i in range(5):
            adapter.apply_feedback(final_score=0.5 + i * 0.1, actions=["generate"])
        # Lag must be >= 1 (implicit in implementation)
        # Lag=5 with 5 records should return 0.0 (need > lag records)
        acf = adapter.feedback_autocorrelation(lag=5)
        assert acf == 0.0

    def test_autocorrelation_mathematical_property(self):
        """Should satisfy: acf(0) would be 1.0 if implemented."""
        adapter = OntologyLearningAdapter()
        for i in range(10):
            adapter.apply_feedback(final_score=0.5 + i * 0.05, actions=["generate"])
        # For any non-constant series, lag=1 should have absolute value < 1
        acf1 = adapter.feedback_autocorrelation(lag=1)
        assert abs(acf1) < 1.0

    def test_autocorrelation_with_diverse_actions(self):
        """Should compute autocorrelation regardless of action types."""
        adapter = OntologyLearningAdapter()
        actions_list = [
            ["generate"],
            ["refine"],
            ["merge_entities"],
            ["split_entity"],
            ["add_relationship"],
        ]
        for i, actions in enumerate(actions_list * 2):  # 10 feedback records
            adapter.apply_feedback(
                final_score=0.5 + (i % 3) * 0.1, actions=actions
            )
        acf = adapter.feedback_autocorrelation(lag=1)
        assert isinstance(acf, float)
        assert -1.0 <= acf <= 1.0

    def test_autocorrelation_realistic_improvement_pattern(self):
        """Should detect positive autocorrelation in gradual improvement."""
        adapter = OntologyLearningAdapter()
        # Simulate ontology improvement over refinement cycles
        base_score = 0.4
        for cycle in range(15):
            # Gradual improvement with noise
            score = min(0.95, base_score + cycle * 0.03 + (cycle % 3) * 0.01)
            adapter.apply_feedback(
                final_score=score,
                actions=["refine"] if cycle > 0 else ["generate"],
            )
        # Should show strong positive autocorrelation (scores increase gradually)
        acf1 = adapter.feedback_autocorrelation(lag=1)
        assert acf1 > 0.75


# ========================================================================
# Tests for Performance Profiling (validate infrastructure)
# ========================================================================


class TestEvaluateOntologyTiming:
    """Test that evaluate_ontology tracking is working."""

    def test_timing_metadata_present_in_score(self):
        """Should include timing_ms in metadata after evaluation."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

        # Clear shared cache to ensure fresh evaluation
        OntologyCritic.clear_shared_cache()
        
        critic = OntologyCritic(use_llm=False)
        ontology = {
            "entities": [
                {"id": "e1", "text": "Entity1", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Entity2", "type": "Org", "confidence": 0.8},
            ],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "works_at",
                    "confidence": 0.85,
                }
            ],
        }

        class Context:
            domain = "legal"
            strategy = "test"

        score = critic.evaluate_ontology(ontology, Context())
        # timing_ms should be present in metadata
        assert "timing_ms" in score.metadata

    def test_timing_is_numeric(self):
        """Should have numeric timing_ms value."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

        # Clear shared cache
        OntologyCritic.clear_shared_cache()
        
        critic = OntologyCritic(use_llm=False)
        ontology = {
            "entities": [
                {"id": "e1", "text": "Test", "type": "Concept", "confidence": 0.9}
            ],
            "relationships": [],
        }

        class Context:
            domain = "general"

        score = critic.evaluate_ontology(ontology, Context())
        timing = score.metadata.get("timing_ms")
        assert isinstance(timing, (int, float))

    def test_timing_is_positive(self):
        """Should have positive timing_ms value."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

        # Clear shared cache
        OntologyCritic.clear_shared_cache()
        
        critic = OntologyCritic(use_llm=False)
        ontology = {
            "entities": [
                {"id": "e1", "text": "Entity", "type": "Thing", "confidence": 0.7}
            ],
            "relationships": [],
        }

        class Context:
            domain = "test"

        score = critic.evaluate_ontology(ontology, Context())
        timing = score.metadata.get("timing_ms")
        assert timing > 0
