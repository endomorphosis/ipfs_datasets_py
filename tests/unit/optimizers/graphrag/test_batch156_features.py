"""Batch-156 feature tests.

Methods under test:
  - OntologyOptimizer.score_below_threshold(threshold)
  - OntologyLearningAdapter.feedback_trend_direction()
  - OntologyGenerator.entity_avg_confidence(result)
  - OntologyCritic.dimension_delta_summary(before, after)
"""
import pytest
from unittest.mock import MagicMock


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="Test", text=eid, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_below_threshold
# ---------------------------------------------------------------------------

class TestScoreBelowThreshold:
    @pytest.mark.parametrize(
        "scores,threshold,expected",
        [
            ([], 0.5, []),
            ([0.7, 0.8, 0.9], 0.5, []),
            ([0.2, 0.6, 0.8], 0.5, [0.2]),
            ([0.5], 0.5, []),
        ],
    )
    def test_score_below_threshold_scenarios(self, scores, threshold, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        result = o.score_below_threshold(threshold=threshold)
        assert [entry.average_score for entry in result] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_trend_direction
# ---------------------------------------------------------------------------

class TestFeedbackTrendDirection:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], "stable"),
            ([0.5], "stable"),
            ([0.2, 0.3, 0.7, 0.8], "improving"),
            ([0.8, 0.9, 0.2, 0.3], "declining"),
            ([0.5, 0.5, 0.5, 0.5], "stable"),
        ],
    )
    def test_feedback_trend_direction_scenarios(self, scores, expected):
        a = _make_adapter()
        for v in scores:
            _push_feedback(a, v)
        assert a.feedback_trend_direction() == expected

    def test_returns_string(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.6)
        assert isinstance(a.feedback_trend_direction(), str)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_avg_confidence
# ---------------------------------------------------------------------------

class TestEntityAvgConfidence:
    @pytest.mark.parametrize(
        "confidences,predicate",
        [
            ([], lambda avg: avg == pytest.approx(0.0)),
            ([0.8], lambda avg: avg == pytest.approx(0.8)),
            ([0.2, 0.4, 0.6], lambda avg: avg == pytest.approx(0.4)),
            ([0.0, 0.1, 0.2, 0.3, 0.4], lambda avg: 0.0 <= avg <= 1.0),
        ],
    )
    def test_entity_avg_confidence_scenarios(self, confidences, predicate):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=v) for i, v in enumerate(confidences)]
        result = _make_result(entities)
        assert predicate(gen.entity_avg_confidence(result))


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_delta_summary
# ---------------------------------------------------------------------------

class TestDimensionDeltaSummary:
    @pytest.mark.parametrize(
        "before,after,predicate",
        [
            (_make_score(), _make_score(), lambda summary: len(summary) == 6),
            (_make_score(), _make_score(), lambda summary: all(v == pytest.approx(0.0) for v in summary.values())),
            (
                _make_score(completeness=0.3),
                _make_score(completeness=0.7),
                lambda summary: summary["completeness"] == pytest.approx(0.4),
            ),
            (
                _make_score(clarity=0.9),
                _make_score(clarity=0.4),
                lambda summary: summary["clarity"] == pytest.approx(-0.5),
            ),
        ],
    )
    def test_dimension_delta_summary_scenarios(self, before, after, predicate):
        critic = _make_critic()
        assert predicate(critic.dimension_delta_summary(before, after))
