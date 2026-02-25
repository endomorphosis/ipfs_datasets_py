"""Batch 250: OntologyLearningAdapter Comprehensive Test Suite.

Comprehensive testing of the OntologyLearningAdapter for adaptive extraction
threshold refinement based on refinement cycle feedback.

Test Categories:
- Feedback application and recording
- Extraction hint computation via EMA
- Statistics and percentile calculation
- Top actions tracking
- State reset
- Serialization/deserialization (dict and bytes)
- Integration with refinement feedback loops
"""

import pytest
import json
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def adapter():
    """Create a fresh OntologyLearningAdapter."""
    return OntologyLearningAdapter(
        domain="general",
        base_threshold=0.7,
        ema_alpha=0.3,
        min_samples=3,
    )


@pytest.fixture
def legal_adapter():
    """Create an OntologyLearningAdapter for legal domain."""
    return OntologyLearningAdapter(
        domain="legal",
        base_threshold=0.8,
        ema_alpha=0.2,
        min_samples=2,
    )


# ============================================================================
# Feedback Application Tests
# ============================================================================

class TestFeedbackApplication:
    """Test apply_feedback() method."""
    
    def test_apply_feedback_records_score(self, adapter):
        """apply_feedback records the final score."""
        adapter.apply_feedback(final_score=0.85, actions=["action1"])
        
        stats = adapter.get_stats()
        assert stats["sample_count"] == 1
        assert stats["mean_score"] == 0.85
    
    def test_apply_feedback_clamps_scores(self, adapter):
        """apply_feedback clamps scores to [0.0, 1.0]."""
        adapter.apply_feedback(final_score=1.5, actions=[])  # > 1.0
        adapter.apply_feedback(final_score=-0.5, actions=[])  # < 0.0
        
        stats = adapter.get_stats()
        assert stats["sample_count"] == 2
        # Scores should be clamped
        assert all(0.0 <= s <= 1.0 for s in [r.final_score for r in adapter._feedback])
    
    def test_apply_feedback_tracks_actions(self, adapter):
        """apply_feedback tracks action types and their success rates."""
        adapter.apply_feedback(final_score=0.9, actions=["refine", "expand"])
        adapter.apply_feedback(final_score=0.7, actions=["refine"])
        adapter.apply_feedback(final_score=0.8, actions=["expand", "validate"])
        
        stats = adapter.get_stats()
        action_rates = stats["action_success_rates"]
        
        # refine: (0.9 + 0.7) / 2 = 0.8
        assert action_rates["refine"] == pytest.approx(0.8, abs=0.01)
        # expand: (0.9 + 0.8) / 2 = 0.85
        assert action_rates["expand"] == pytest.approx(0.85, abs=0.01)
    
    def test_apply_feedback_with_dict_actions(self, adapter):
        """apply_feedback accepts dict actions with 'action' key."""
        actions = [
            {"action": "extract", "count": 5},
            {"action": "refine", "count": 2},
        ]
        adapter.apply_feedback(final_score=0.85, actions=actions)
        
        stats = adapter.get_stats()
        assert stats["sample_count"] == 1
        assert "extract" in stats["action_success_rates"]
        assert "refine" in stats["action_success_rates"]
    
    def test_apply_feedback_with_confidence(self, adapter):
        """apply_feedback records extraction confidence."""
        adapter.apply_feedback(
            final_score=0.88,
            actions=["refine"],
            confidence_at_extraction=0.75
        )
        
        record = adapter._feedback[0]
        assert record.confidence_at_extraction == 0.75


# ============================================================================
# Extraction Hint Tests
# ============================================================================

class TestExtractionHint:
    """Test get_extraction_hint() method."""
    
    def test_extraction_hint_returns_float(self, adapter):
        """get_extraction_hint returns a float."""
        hint = adapter.get_extraction_hint()
        
        assert isinstance(hint, float)
        assert 0.1 <= hint <= 0.9
    
    def test_extraction_hint_base_threshold_initially(self, adapter):
        """get_extraction_hint returns base threshold with no feedback."""
        hint = adapter.get_extraction_hint()
        
        assert hint == adapter._current_threshold
    
    def test_extraction_hint_adjusts_with_high_success(self, adapter):
        """get_extraction_hint decreases when actions frequently succeed."""
        # Apply highly successful actions (> 0.5)
        for _ in range(5):
            adapter.apply_feedback(final_score=0.95, actions=["refine"])
        
        hint = adapter.get_extraction_hint()
        initial_threshold = adapter._base_threshold
        
        # High success should lower threshold slightly
        assert hint < initial_threshold  # More extraction allowed
    
    def test_extraction_hint_adjusts_with_low_success(self, adapter):
        """get_extraction_hint increases when actions rarely succeed."""
        # Apply poorly successful actions (< 0.5)
        for _ in range(5):
            adapter.apply_feedback(final_score=0.2, actions=["refine"])
        
        hint = adapter.get_extraction_hint()
        initial_threshold = adapter._base_threshold
        
        # Low success should raise threshold
        assert hint > initial_threshold  # Less extraction allowed
    
    def test_extraction_hint_within_bounds(self, adapter):
        """get_extraction_hint always returns value in [0.1, 0.9]."""
        # Apply extreme feedback
        for _ in range(10):
            adapter.apply_feedback(final_score=1.0, actions=["action1"])
        
        hint = adapter.get_extraction_hint()
        assert 0.1 <= hint <= 0.9


# ============================================================================
# Statistics Tests
# ============================================================================

class TestStatistics:
    """Test get_stats() method."""
    
    def test_get_stats_returns_dict(self, adapter):
        """get_stats returns a dictionary."""
        stats = adapter.get_stats()
        
        assert isinstance(stats, dict)
    
    def test_get_stats_has_required_fields(self, adapter):
        """get_stats includes all required fields."""
        adapter.apply_feedback(final_score=0.8, actions=["refine"])
        stats = adapter.get_stats()
        
        required_fields = [
            "domain", "current_threshold", "base_threshold",
            "sample_count", "mean_score", "p50_score", "p90_score",
            "action_success_rates"
        ]
        for field in required_fields:
            assert field in stats
    
    def test_get_stats_mean_score_calculation(self, adapter):
        """get_stats computes mean score correctly."""
        scores = [0.8, 0.9, 0.7]
        for score in scores:
            adapter.apply_feedback(final_score=score, actions=["refine"])
        
        stats = adapter.get_stats()
        expected_mean = sum(scores) / len(scores)
        assert stats["mean_score"] == pytest.approx(expected_mean, abs=0.01)
    
    def test_get_stats_percentiles(self, adapter):
        """get_stats computes percentiles correctly."""
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        for score in scores:
            adapter.apply_feedback(final_score=score, actions=["refine"])
        
        stats = adapter.get_stats()
        
        # p50 should be roughly median (0.5)
        assert 0.4 <= stats["p50_score"] <= 0.6
        # p90 should be high (> 0.7)
        assert stats["p90_score"] >= 0.7


# ============================================================================
# Top Actions Tests
# ============================================================================

class TestTopActions:
    """Test top_actions() method."""
    
    def test_top_actions_returns_list(self, adapter):
        """top_actions returns a list."""
        adapter.apply_feedback(final_score=0.8, actions=["refine"])
        actions = adapter.top_actions()
        
        assert isinstance(actions, list)
    
    def test_top_actions_sorted_by_success(self, adapter):
        """top_actions sorts by mean success (descending)."""
        adapter.apply_feedback(final_score=0.9, actions=["action1"])
        adapter.apply_feedback(final_score=0.7, actions=["action2"])
        adapter.apply_feedback(final_score=0.8, actions=["action1"])
        
        actions = adapter.top_actions()
        
        # action1 has mean (0.9+0.8)/2 = 0.85
        # action2 has mean 0.7
        assert actions[0]["action"] == "action1"
        assert actions[1]["action"] == "action2"
    
    def test_top_actions_respects_limit(self, adapter):
        """top_actions respects the n parameter."""
        for i in range(10):
            adapter.apply_feedback(final_score=0.8, actions=[f"action{i}"])
        
        top_5 = adapter.top_actions(n=5)
        assert len(top_5) == 5
        
        top_3 = adapter.top_actions(n=3)
        assert len(top_3) == 3
    
    def test_top_actions_includes_count_and_success(self, adapter):
        """top_actions includes count and mean_success fields."""
        adapter.apply_feedback(final_score=0.9, actions=["refine", "refine"])
        
        actions = adapter.top_actions(n=10)
        refine_action = next((a for a in actions if a["action"] == "refine"), None)
        
        assert refine_action is not None
        assert "count" in refine_action
        assert "mean_success" in refine_action
        assert refine_action["count"] == 2
        assert refine_action["mean_success"] == pytest.approx(0.9, abs=0.01)


# ============================================================================
# Reset Tests
# ============================================================================

class TestReset:
    """Test reset() method."""
    
    def test_reset_clears_feedback(self, adapter):
        """reset clears all feedback."""
        adapter.apply_feedback(final_score=0.8, actions=["refine"])
        adapter.reset()
        
        stats = adapter.get_stats()
        assert stats["sample_count"] == 0
    
    def test_reset_restores_base_threshold(self, adapter):
        """reset restores base threshold."""
        base = adapter._base_threshold
        adapter.apply_feedback(final_score=0.9, actions=["refine"])
        adapter._current_threshold = 0.5  # Manual change
        
        adapter.reset()
        
        assert adapter._current_threshold == base
    
    def test_reset_useful_for_testing(self, adapter):
        """reset is useful for test isolation."""
        # First cycle
        adapter.apply_feedback(final_score=0.8, actions=["action1"])
        stats1 = adapter.get_stats()
        
        # Reset
        adapter.reset()
        stats2 = adapter.get_stats()
        
        assert stats2["sample_count"] == 0
        assert stats1["sample_count"] > 0


# ============================================================================
# Serialization Tests (Dict Format)
# ============================================================================

class TestToDict:
    """Test to_dict() serialization."""
    
    def test_to_dict_returns_dict(self, adapter):
        """to_dict returns a dictionary."""
        d = adapter.to_dict()
        
        assert isinstance(d, dict)
    
    def test_to_dict_preserves_config(self, adapter):
        """to_dict preserves adapter configuration."""
        d = adapter.to_dict()
        
        assert d["domain"] == adapter.domain
        assert d["base_threshold"] == adapter._base_threshold
        assert d["ema_alpha"] == adapter._ema_alpha
        assert d["min_samples"] == adapter._min_samples
    
    def test_to_dict_preserves_feedback(self, adapter):
        """to_dict preserves all feedback."""
        scores = [0.8, 0.85, 0.9]
        for score in scores:
            adapter.apply_feedback(final_score=score, actions=["refine"])
        
        d = adapter.to_dict()
        
        assert len(d["feedback"]) == 3
        assert [f["final_score"] for f in d["feedback"]] == scores


class TestFromDict:
    """Test from_dict() deserialization."""
    
    def test_from_dict_reconstructs_adapter(self, adapter):
        """from_dict reconstructs adapter from dict."""
        adapter.apply_feedback(final_score=0.85, actions=["refine"])
        d = adapter.to_dict()
        
        reconstructed = OntologyLearningAdapter.from_dict(d)
        
        assert reconstructed.domain == adapter.domain
        assert reconstructed._base_threshold == adapter._base_threshold
        assert reconstructed._current_threshold == adapter._current_threshold
    
    def test_from_dict_preserves_feedback(self, adapter):
        """from_dict restores all feedback."""
        adapter.apply_feedback(final_score=0.8, actions=["action1"])
        adapter.apply_feedback(final_score=0.9, actions=["action2"])
        d = adapter.to_dict()
        
        reconstructed = OntologyLearningAdapter.from_dict(d)
        stats = reconstructed.get_stats()
        
        assert stats["sample_count"] == 2
        assert stats["mean_score"] == pytest.approx(0.85, abs=0.01)
    
    def test_from_dict_round_trip(self, adapter):
        """from_dict enables round-trip serialization."""
        # Apply complex feedback
        for i in range(5):
            adapter.apply_feedback(
                final_score=0.7 + i * 0.05,
                actions=["refine", f"action{i}"],
                confidence_at_extraction=0.75
            )
        
        original_stats = adapter.get_stats()
        d = adapter.to_dict()
        reconstructed = OntologyLearningAdapter.from_dict(d)
        restored_stats = reconstructed.get_stats()
        
        assert original_stats["sample_count"] == restored_stats["sample_count"]
        assert original_stats["mean_score"] == pytest.approx(restored_stats["mean_score"], abs=0.01)


# ============================================================================
# JSON Serialization Tests (Bytes Format)
# ============================================================================

class TestSerialization:
    """Test serialize()/deserialize() methods."""
    
    def test_serialize_returns_bytes(self, adapter):
        """serialize returns bytes."""
        data = adapter.serialize()
        
        assert isinstance(data, bytes)
    
    def test_serialize_is_json(self, adapter):
        """serialize produces valid JSON."""
        adapter.apply_feedback(final_score=0.85, actions=["refine"])
        data = adapter.serialize()
        
        # Should be decodable as JSON
        decoded = json.loads(data.decode("utf-8"))
        assert isinstance(decoded, dict)
    
    def test_deserialize_returns_adapter(self, adapter):
        """deserialize returns OntologyLearningAdapter."""
        adapter.apply_feedback(final_score=0.8, actions=["refine"])
        data = adapter.serialize()
        
        deserialized = OntologyLearningAdapter.deserialize(data)
        
        assert isinstance(deserialized, OntologyLearningAdapter)
    
    def test_serialize_deserialize_round_trip(self, adapter):
        """serialize/deserialize enables lossless round-trip."""
        scores = [0.7, 0.8, 0.9, 0.75, 0.85]
        for score in scores:
            adapter.apply_feedback(final_score=score, actions=["refine", "expand"])
        
        original_stats = adapter.get_stats()
        serialized = adapter.serialize()
        deserialized = OntologyLearningAdapter.deserialize(serialized)
        restored_stats = deserialized.get_stats()
        
        assert original_stats["sample_count"] == restored_stats["sample_count"]
        assert original_stats["mean_score"] == pytest.approx(restored_stats["mean_score"], abs=0.001)
        assert len(deserialized._feedback) == len(adapter._feedback)


# ============================================================================
# Domain-Specific Tests
# ============================================================================

class TestDomainSpecific:
    """Test domain-specific adaptation."""
    
    def test_adapter_respects_domain(self, legal_adapter):
        """Adapter preserves domain information."""
        legal_adapter.apply_feedback(final_score=0.9, actions=["refine"])
        
        stats = legal_adapter.get_stats()
        assert stats["domain"] == "legal"
    
    def test_different_domains_independent(self):
        """Different domain adapters maintain independent state."""
        general = OntologyLearningAdapter(domain="general")
        legal = OntologyLearningAdapter(domain="legal")
        
        general.apply_feedback(final_score=0.9, actions=["refine"])
        legal.apply_feedback(final_score=0.5, actions=["refine"])
        
        general_stats = general.get_stats()
        legal_stats = legal.get_stats()
        
        assert general_stats["mean_score"] == pytest.approx(0.9, abs=0.01)
        assert legal_stats["mean_score"] == pytest.approx(0.5, abs=0.01)


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for realistic workflows."""
    
    def test_adaptation_cycle(self, adapter):
        """Complete adaptation cycle adjusts threshold appropriately."""
        # Initial threshold
        initial_hint = adapter.get_extraction_hint()
        
        # Apply successful refinements
        for _ in range(5):
            adapter.apply_feedback(final_score=0.95, actions=["refine"])
        
        hint_after_success = adapter.get_extraction_hint()
        
        # Hint should be lower (allow more extraction)
        assert hint_after_success < initial_hint + 0.05  # Small margin for EMA
    
    def test_multiple_action_types(self, adapter):
        """Adapter handles multiple action types correctly."""
        actions_applied = [
            (["extract"], 0.9),
            (["refine"], 0.8),
            (["extract", "refine"], 0.85),
            (["validate"], 0.92),
            (["extract", "validate"], 0.88),
        ]
        
        for actions, score in actions_applied:
            adapter.apply_feedback(final_score=score, actions=actions)
        
        top_actions = adapter.top_actions(n=10)
        action_names = {a["action"] for a in top_actions}
        
        assert "extract" in action_names
        assert "refine" in action_names
        assert "validate" in action_names
    
    def test_recovery_from_low_performance(self, adapter):
        """Adapter recovers when performance improves."""
        # Poor initial performance
        for _ in range(3):
            adapter.apply_feedback(final_score=0.3, actions=["refine"])
        
        stats_poor = adapter.get_stats()
        hint_poor = adapter.get_extraction_hint()
        
        # Recovery with good performance
        for _ in range(3):
            adapter.apply_feedback(final_score=0.95, actions=["refine"])
        
        stats_recovery = adapter.get_stats()
        hint_recovery = adapter.get_extraction_hint()
        
        # Should show improvement
        assert stats_recovery["mean_score"] > stats_poor["mean_score"]
        # Hint should be lower (more extraction allowed)
        assert hint_recovery < hint_poor


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
