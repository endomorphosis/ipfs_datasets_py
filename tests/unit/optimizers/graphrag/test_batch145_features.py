"""Batch-145 feature tests.

Methods under test:
  - OntologyCritic.dimension_covariance(scores, dim_a, dim_b)
  - LogicValidator.unreachable_entities(ontology, source)
  - OntologyLearningAdapter.feedback_zscore(value)
"""
import pytest


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_covariance
# ---------------------------------------------------------------------------

def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


class TestDimensionCovariance:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        self.critic = OntologyCritic(use_llm=False)

    def test_empty_returns_zero(self):
        assert self.critic.dimension_covariance([], "completeness", "clarity") == pytest.approx(0.0)

    def test_single_score_returns_zero(self):
        s = _make_score()
        assert self.critic.dimension_covariance([s], "completeness", "clarity") == pytest.approx(0.0)

    def test_perfect_positive_covariance(self):
        # both dimensions move together
        s1 = _make_score(completeness=0.2, consistency=0.2)
        s2 = _make_score(completeness=0.8, consistency=0.8)
        cov = self.critic.dimension_covariance([s1, s2], "completeness", "consistency")
        assert cov > 0

    def test_negative_covariance(self):
        s1 = _make_score(completeness=0.2, consistency=0.8)
        s2 = _make_score(completeness=0.8, consistency=0.2)
        cov = self.critic.dimension_covariance([s1, s2], "completeness", "consistency")
        assert cov < 0

    def test_zero_variance_returns_zero(self):
        s1 = _make_score(completeness=0.5, consistency=0.5)
        s2 = _make_score(completeness=0.5, consistency=0.7)
        # completeness has zero variance → covariance is 0
        cov = self.critic.dimension_covariance([s1, s2], "completeness", "consistency")
        assert cov == pytest.approx(0.0)

    def test_invalid_dim_raises(self):
        s = _make_score()
        with pytest.raises(AttributeError):
            self.critic.dimension_covariance([s, s], "completeness", "nonexistent_dim")


# ---------------------------------------------------------------------------
# LogicValidator.unreachable_entities
# ---------------------------------------------------------------------------

def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


class TestUnreachableEntities:
    def test_empty_ontology_returns_empty(self):
        v = _make_validator()
        result = v.unreachable_entities({}, "A")
        assert result == []

    def test_all_reachable_returns_empty(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "A", "object_id": "C"},
            ],
        }
        result = v.unreachable_entities(ont, "A")
        assert result == []

    def test_isolated_entity_is_unreachable(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
            ],
        }
        result = v.unreachable_entities(ont, "A")
        assert "C" in result

    def test_source_not_in_result(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [],
        }
        result = v.unreachable_entities(ont, "A")
        assert "A" not in result

    def test_directed_unreachable(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "B", "object_id": "A"},  # B→A, not A→B
            ],
        }
        # From A, cannot reach B or C
        result = v.unreachable_entities(ont, "A")
        assert "B" in result
        assert "C" in result

    def test_returns_sorted_list(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "Z"}, {"id": "M"}, {"id": "A"}],
            "relationships": [],
        }
        result = v.unreachable_entities(ont, "X")  # source not in entities
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_zscore
# ---------------------------------------------------------------------------

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


class TestFeedbackZscore:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_zscore(0.5) == pytest.approx(0.0)

    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_zscore(0.5) == pytest.approx(0.0)

    def test_zero_std_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        _push_feedback(a, 0.5)
        assert a.feedback_zscore(0.5) == pytest.approx(0.0)

    def test_mean_value_returns_zero(self):
        a = _make_adapter()
        for v in [0.0, 1.0]:
            _push_feedback(a, v)
        assert a.feedback_zscore(0.5) == pytest.approx(0.0)

    def test_above_mean_positive(self):
        a = _make_adapter()
        for v in [0.0, 0.5, 1.0]:
            _push_feedback(a, v)
        assert a.feedback_zscore(0.9) > 0.0

    def test_below_mean_negative(self):
        a = _make_adapter()
        for v in [0.0, 0.5, 1.0]:
            _push_feedback(a, v)
        assert a.feedback_zscore(0.1) < 0.0
