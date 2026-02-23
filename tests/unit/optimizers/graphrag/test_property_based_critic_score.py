"""Property-based tests for CriticScore helpers."""

from hypothesis import given, settings, strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, DIMENSION_WEIGHTS
from tests.unit.optimizers.graphrag.strategies import valid_critic_score


class TestCriticScorePropertyBased:
    @settings(max_examples=100)
    @given(score=valid_critic_score())
    def test_overall_matches_weighted_sum(self, score: CriticScore):
        expected = (
            DIMENSION_WEIGHTS["completeness"] * score.completeness
            + DIMENSION_WEIGHTS["consistency"] * score.consistency
            + DIMENSION_WEIGHTS["clarity"] * score.clarity
            + DIMENSION_WEIGHTS["granularity"] * score.granularity
            + DIMENSION_WEIGHTS["relationship_coherence"] * score.relationship_coherence
            + DIMENSION_WEIGHTS["domain_alignment"] * score.domain_alignment
        )
        assert score.overall == expected

    @settings(max_examples=50)
    @given(score=valid_critic_score())
    def test_to_dict_round_trip_preserves_dimensions(self, score: CriticScore):
        restored = CriticScore.from_dict(score.to_dict())
        assert restored.completeness == score.completeness
        assert restored.consistency == score.consistency
        assert restored.clarity == score.clarity
        assert restored.granularity == score.granularity
        assert restored.relationship_coherence == score.relationship_coherence
        assert restored.domain_alignment == score.domain_alignment

    @settings(max_examples=50)
    @given(score=valid_critic_score())
    def test_to_list_order_and_length(self, score: CriticScore):
        values = score.to_list()
        assert len(values) == 6
        assert values == [
            score.completeness,
            score.consistency,
            score.clarity,
            score.granularity,
            score.relationship_coherence,
            score.domain_alignment,
        ]


class TestCriticScorePassingProperty:
    @settings(max_examples=50)
    @given(score=valid_critic_score(), threshold=st.floats(min_value=0.0, max_value=1.0))
    def test_is_passing_consistent(self, score: CriticScore, threshold: float):
        assert score.is_passing(threshold) == (score.overall >= threshold)
