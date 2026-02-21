"""Batch-160 feature tests.

Methods under test:
  - OntologyCritic.dimension_ratio(score)
  - OntologyCritic.all_dimensions_below(score, threshold)
  - OntologyLearningAdapter.feedback_range()
  - OntologyPipeline.run_score_at(idx)
"""
import pytest
from unittest.mock import MagicMock


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


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_ratio
# ---------------------------------------------------------------------------

class TestDimensionRatio:
    def test_equal_scores_equal_ratios(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        ratios = critic.dimension_ratio(score)
        vals = list(ratios.values())
        assert all(abs(v - vals[0]) < 1e-9 for v in vals)

    def test_ratios_sum_to_one(self):
        critic = _make_critic()
        score = _make_score(completeness=0.8, clarity=0.2)
        ratios = critic.dimension_ratio(score)
        assert sum(ratios.values()) == pytest.approx(1.0)

    def test_zero_total_equal_distribution(self):
        critic = _make_critic()
        score = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        ratios = critic.dimension_ratio(score)
        assert sum(ratios.values()) == pytest.approx(1.0)

    def test_keys_match_dimensions(self):
        critic = _make_critic()
        score = _make_score()
        ratios = critic.dimension_ratio(score)
        assert set(ratios.keys()) == set(critic._DIMENSIONS)


# ---------------------------------------------------------------------------
# OntologyCritic.all_dimensions_below
# ---------------------------------------------------------------------------

class TestAllDimensionsBelow:
    def test_all_below_returns_true(self):
        critic = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.2, clarity=0.3,
                            granularity=0.0, relationship_coherence=0.1, domain_alignment=0.2)
        assert critic.all_dimensions_below(score, threshold=0.4) is True

    def test_one_above_returns_false(self):
        critic = _make_critic()
        score = _make_score(completeness=0.9)
        assert critic.all_dimensions_below(score, threshold=0.5) is False

    def test_equal_to_threshold_returns_false(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        assert critic.all_dimensions_below(score, threshold=0.5) is False

    def test_custom_low_threshold(self):
        critic = _make_critic()
        score = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.all_dimensions_below(score, threshold=0.1) is True


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_range
# ---------------------------------------------------------------------------

class TestFeedbackRange:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_range() == pytest.approx(0.0)

    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_range() == pytest.approx(0.0)

    def test_two_records(self):
        a = _make_adapter()
        _push_feedback(a, 0.2)
        _push_feedback(a, 0.8)
        assert a.feedback_range() == pytest.approx(0.6)

    def test_multiple_records(self):
        a = _make_adapter()
        for v in [0.1, 0.5, 0.9, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_range() == pytest.approx(0.8)

    def test_all_same_returns_zero(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_range() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_at
# ---------------------------------------------------------------------------

class TestRunScoreAt:
    def test_first_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.run_score_at(0) == pytest.approx(0.7)

    def test_negative_index(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        _push_run(p, 0.8)
        assert p.run_score_at(-1) == pytest.approx(0.8)

    def test_out_of_range_raises(self):
        p = _make_pipeline()
        with pytest.raises(IndexError):
            p.run_score_at(0)

    def test_multiple_runs(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_at(1) == pytest.approx(0.5)
