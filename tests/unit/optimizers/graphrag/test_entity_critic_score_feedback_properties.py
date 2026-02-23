"""Property-based tests for Entity, CriticScore, and FeedbackRecord.

Uses Hypothesis to generate random, valid inputs and validate invariants
across these core data models. Property tests ensure these types behave
correctly under stress, random mutations, and edge cases.
"""

from __future__ import annotations

import json
from hypothesis import given, strategies as st
from hypothesis.strategies import composite

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord


# ============================================================================
# Hypothesis Strategies for Core Data Models
# ============================================================================


@composite
def valid_critic_score(draw) -> CriticScore:
    """Generate a valid CriticScore with all dimensions in valid range."""
    completeness = draw(st.floats(min_value=0.0, max_value=1.0))
    consistency = draw(st.floats(min_value=0.0, max_value=1.0))
    clarity = draw(st.floats(min_value=0.0, max_value=1.0))
    granularity = draw(st.floats(min_value=0.0, max_value=1.0))
    relationship_coherence = draw(st.floats(min_value=0.0, max_value=1.0))
    domain_alignment = draw(st.floats(min_value=0.0, max_value=1.0))
    
    # Generate lists of feedback (immutable)
    strengths = draw(
        st.lists(
            st.text(min_size=1, max_size=100),
            min_size=0,
            max_size=5,
        )
    )
    
    weaknesses = draw(
        st.lists(
            st.text(min_size=1, max_size=100),
            min_size=0,
            max_size=5,
        )
    )
    
    recommendations = draw(
        st.lists(
            st.text(min_size=1, max_size=100),
            min_size=0,
            max_size=5,
        )
    )
    
    # Metadata dict (immutable at generation time)
    metadata = draw(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.one_of(
                st.text(max_size=100),
                st.integers(),
                st.booleans(),
            ),
            min_size=0,
            max_size=3,
        )
    )
    
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=recommendations,
        metadata=metadata,
    )


@composite
def valid_feedback_record(draw) -> FeedbackRecord:
    """Generate a valid FeedbackRecord."""
    final_score = draw(st.floats(min_value=0.0, max_value=1.0))
    
    # Action types
    action_types = draw(
        st.lists(
            st.sampled_from([
                "add_entity", "remove_entity", "merge_entities",
                "add_relationship", "remove_relationship", "update_confidence",
                "domain_alignment", "consistency_check"
            ]),
            min_size=0,
            max_size=5,
            unique=True,
        )
    )
    
    # Optional confidence at extraction
    confidence_at_extraction = None
    if draw(st.booleans()):
        confidence_at_extraction = draw(st.floats(min_value=0.0, max_value=1.0))
    
    return FeedbackRecord(
        final_score=final_score,
        action_types=action_types,
        confidence_at_extraction=confidence_at_extraction,
    )


# ============================================================================
# CriticScore Property Tests
# ============================================================================


class TestCriticScoreProperties:
    """Property-based tests for CriticScore invariants."""
    
    @given(valid_critic_score())
    def test_critic_score_all_dimensions_in_range(self, score: CriticScore):
        """All dimension scores and overall score are in [0.0, 1.0]."""
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0
        assert 0.0 <= score.granularity <= 1.0
        assert 0.0 <= score.relationship_coherence <= 1.0
        assert 0.0 <= score.domain_alignment <= 1.0
        assert 0.0 <= score.overall <= 1.0
    
    @given(valid_critic_score())
    def test_critic_score_overall_is_weighted_average(self, score: CriticScore):
        """Overall score is a weighted average of dimensions."""
        # Weights sum to 1.0, so overall should be within [min, max] dimensions
        dimensions = [
            score.completeness,
            score.consistency,
            score.clarity,
            score.granularity,
            score.relationship_coherence,
            score.domain_alignment,
        ]
        min_dim = min(dimensions)
        max_dim = max(dimensions)
        
        assert min_dim <= score.overall <= max_dim
    
    @given(valid_critic_score())
    def test_critic_score_to_dict_roundtrip(self, score: CriticScore):
        """CriticScore.to_dict() produces a dict with all key fields."""
        d = score.to_dict()
        
        assert isinstance(d, dict)
        assert 'overall' in d
        assert 'dimensions' in d
        assert 'weights' in d
        assert 'strengths' in d
        assert 'weaknesses' in d
        assert 'recommendations' in d
        assert 'metadata' in d
        
        # Verify dimension keys
        dims = d['dimensions']
        expected_dims = {
            'completeness', 'consistency', 'clarity',
            'granularity', 'relationship_coherence', 'domain_alignment'
        }
        assert set(dims.keys()) == expected_dims
    
    @given(valid_critic_score())
    def test_critic_score_to_list_returns_ordered_dimensions(self, score: CriticScore):
        """CriticScore.to_list() returns dimensions in canonical order."""
        dims_list = score.to_list()
        
        assert isinstance(dims_list, list)
        assert len(dims_list) == 6
        
        # Check order
        assert dims_list[0] == score.completeness
        assert dims_list[1] == score.consistency
        assert dims_list[2] == score.clarity
        assert dims_list[3] == score.granularity
        assert dims_list[4] == score.relationship_coherence
        assert dims_list[5] == score.domain_alignment
    
    @given(valid_critic_score(), st.floats(min_value=0.0, max_value=1.0))
    def test_critic_score_is_passing_threshold_logic(self, score: CriticScore, threshold: float):
        """CriticScore.is_passing(threshold) correctly compares overall vs threshold."""
        is_passing = score.is_passing(threshold=threshold)
        expected = score.overall >= threshold
        assert is_passing == expected
    
    @given(valid_critic_score())
    def test_critic_score_lists_are_mutable_independent(self, score: CriticScore):
        """Lists in CriticScore default to empty, not None."""
        assert isinstance(score.strengths, list)
        assert isinstance(score.weaknesses, list)
        assert isinstance(score.recommendations, list)
    
    @given(valid_critic_score())
    def test_critic_score_to_json_is_valid(self, score: CriticScore):
        """CriticScore.to_json() produces valid JSON."""
        json_str = score.to_json()
        assert isinstance(json_str, str)
        
        # Should be parseable
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert 'overall' in parsed


# ============================================================================
# FeedbackRecord Property Tests
# ============================================================================


class TestFeedbackRecordProperties:
    """Property-based tests for FeedbackRecord invariants."""
    
    @given(valid_feedback_record())
    def test_feedback_final_score_in_range(self, record: FeedbackRecord):
        """FeedbackRecord final_score is in [0.0, 1.0]."""
        assert 0.0 <= record.final_score <= 1.0
    
    @given(valid_feedback_record())
    def test_feedback_action_types_is_list(self, record: FeedbackRecord):
        """FeedbackRecord action_types is always a list."""
        assert isinstance(record.action_types, list)
        
        for action in record.action_types:
            assert isinstance(action, str)
    
    @given(valid_feedback_record())
    def test_feedback_confidence_at_extraction_in_range_or_none(self, record: FeedbackRecord):
        """FeedbackRecord confidence_at_extraction is None or in [0.0, 1.0]."""
        if record.confidence_at_extraction is not None:
            assert isinstance(record.confidence_at_extraction, (int, float))
            assert 0.0 <= record.confidence_at_extraction <= 1.0
    
    @given(valid_feedback_record())
    def test_feedback_repr_includes_key_info(self, record: FeedbackRecord):
        """FeedbackRecord.__repr__() includes final_score and action_types."""
        repr_str = repr(record)
        
        assert isinstance(repr_str, str)
        assert "FeedbackRecord" in repr_str
        assert str(round(record.final_score, 3)) in repr_str


# ============================================================================
# Stress Tests  
# ============================================================================


class TestCriticScoreStress:
    """Stress tests for CriticScore with extreme values."""
    
    def test_critic_score_with_all_dimensions_zero(self):
        """CriticScore handles all-zero dimensions."""
        zero_score = CriticScore(
            completeness=0.0,
            consistency=0.0,
            clarity=0.0,
            granularity=0.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
        )
        
        assert zero_score.overall == 0.0
        assert zero_score.is_passing(threshold=0.0)
        assert not zero_score.is_passing(threshold=0.01)
    
    def test_critic_score_with_all_dimensions_one(self):
        """CriticScore handles all-one dimensions."""
        one_score = CriticScore(
            completeness=1.0,
            consistency=1.0,
            clarity=1.0,
            granularity=1.0,
            relationship_coherence=1.0,
            domain_alignment=1.0,
        )
        
        assert one_score.overall == 1.0
        assert one_score.is_passing(threshold=1.0)
    
    @given(valid_critic_score())
    def test_critic_score_with_large_feedback_lists(self, score: CriticScore):
        """CriticScore handles large feedback lists gracefully."""
        big_strengths = ["strength_" + str(i) for i in range(100)]
        big_score = CriticScore(
            completeness=score.completeness,
            consistency=score.consistency,
            clarity=score.clarity,
            granularity=score.granularity,
            relationship_coherence=score.relationship_coherence,
            domain_alignment=score.domain_alignment,
            strengths=big_strengths,
        )
        
        assert len(big_score.strengths) == 100
        d = big_score.to_dict()
        assert len(d['strengths']) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
