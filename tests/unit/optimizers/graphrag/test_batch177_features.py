"""Batch-177 feature tests.

Methods under test:
  - LogicValidator.in_degree_distribution(ontology)
  - LogicValidator.out_degree_distribution(ontology)
  - OntologyPipeline.run_score_ewma(alpha)
  - OntologyPipeline.run_score_percentile(p)
  - OntologyMediator.feedback_count_by_action(action)
  - OntologyMediator.action_success_rate(action)
"""
import pytest
from unittest.mock import MagicMock


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic(use_llm=False))


# ── LogicValidator.in_degree_distribution ─────────────────────────────────────

class TestInDegreeDistribution:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.in_degree_distribution(_FakeOntology([])) == {}

    def test_single_rel(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        d = v.in_degree_distribution(_FakeOntology(rels))
        assert d.get("b", 0) == 1

    def test_multiple_incoming(self):
        v = _make_validator()
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        d = v.in_degree_distribution(_FakeOntology(rels))
        assert d["c"] == 2

    def test_source_only_has_zero_in_degree(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        d = v.in_degree_distribution(_FakeOntology(rels))
        assert d.get("a", 0) == 0


# ── LogicValidator.out_degree_distribution ────────────────────────────────────

class TestOutDegreeDistribution:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.out_degree_distribution(_FakeOntology([])) == {}

    def test_single_rel(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        d = v.out_degree_distribution(_FakeOntology(rels))
        assert d.get("a", 0) == 1

    def test_multiple_outgoing(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("a", "c")]
        d = v.out_degree_distribution(_FakeOntology(rels))
        assert d["a"] == 2

    def test_target_only_has_zero_out_degree(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        d = v.out_degree_distribution(_FakeOntology(rels))
        assert d.get("b", 0) == 0


# ── OntologyPipeline.run_score_ewma ──────────────────────────────────────────

class TestRunScoreEWMA:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.run_score_ewma() == []

    def test_single_returns_same(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.run_score_ewma() == pytest.approx([0.6])

    def test_alpha_one_returns_scores(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        result = p.run_score_ewma(alpha=1.0)
        assert result == pytest.approx([0.2, 0.5, 0.8])

    def test_length_matches_runs(self):
        p = _make_pipeline()
        for v in [0.3, 0.6, 0.9]:
            _push_run(p, v)
        assert len(p.run_score_ewma()) == 3


# ── OntologyPipeline.run_score_percentile ────────────────────────────────────

class TestRunScorePercentile:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_percentile() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_percentile() == pytest.approx(0.0)

    def test_50th_is_median(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        assert p.run_score_percentile(50.0) == pytest.approx(0.5)

    def test_0th_is_min(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        assert p.run_score_percentile(0.0) == pytest.approx(0.2)

    def test_100th_is_max(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        assert p.run_score_percentile(100.0) == pytest.approx(0.8)


# ── OntologyMediator.feedback_count_by_action ────────────────────────────────

class TestFeedbackCountByAction:
    def test_unknown_action_returns_zero(self):
        m = _make_mediator()
        assert m.feedback_count_by_action("merge") == 0

    def test_recorded_action_returns_count(self):
        m = _make_mediator()
        m._action_counts["merge"] = 5
        assert m.feedback_count_by_action("merge") == 5


# ── OntologyMediator.action_success_rate ─────────────────────────────────────

class TestActionSuccessRate:
    def test_unknown_action_returns_zero(self):
        m = _make_mediator()
        assert m.action_success_rate("merge") == pytest.approx(0.0)

    def test_returns_float(self):
        m = _make_mediator()
        assert isinstance(m.action_success_rate("x"), float)
