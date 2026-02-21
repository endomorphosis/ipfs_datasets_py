"""Batch-161 feature tests.

Methods under test:
  - LogicValidator.max_in_degree(ontology)
  - LogicValidator.max_out_degree(ontology)
  - OntologyOptimizer.score_streak(direction)
  - OntologyOptimizer.recent_best_score(n)
"""
import pytest
from unittest.mock import MagicMock


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _ontology(entities, relationships):
    return {"entities": entities, "relationships": relationships}


# ---------------------------------------------------------------------------
# LogicValidator.max_in_degree
# ---------------------------------------------------------------------------

class TestMaxInDegree:
    def test_empty_entities_returns_none(self):
        v = _make_validator()
        assert v.max_in_degree({"entities": [], "relationships": []}) is None

    def test_no_relationships(self):
        v = _make_validator()
        ont = _ontology([{"id": "e1"}, {"id": "e2"}], [])
        result = v.max_in_degree(ont)
        assert result is not None
        assert result["count"] == 0

    def test_single_relationship(self):
        v = _make_validator()
        ont = _ontology(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "type": "rel"}],
        )
        result = v.max_in_degree(ont)
        assert result["entity"] == "b"
        assert result["count"] == 1

    def test_hub_entity(self):
        v = _make_validator()
        ont = _ontology(
            [{"id": "hub"}, {"id": "x"}, {"id": "y"}, {"id": "z"}],
            [
                {"source": "x", "target": "hub", "type": "rel"},
                {"source": "y", "target": "hub", "type": "rel"},
                {"source": "z", "target": "hub", "type": "rel"},
            ],
        )
        result = v.max_in_degree(ont)
        assert result["entity"] == "hub"
        assert result["count"] == 3


# ---------------------------------------------------------------------------
# LogicValidator.max_out_degree
# ---------------------------------------------------------------------------

class TestMaxOutDegree:
    def test_empty_entities_returns_none(self):
        v = _make_validator()
        assert v.max_out_degree({"entities": [], "relationships": []}) is None

    def test_no_relationships(self):
        v = _make_validator()
        ont = _ontology([{"id": "e1"}, {"id": "e2"}], [])
        result = v.max_out_degree(ont)
        assert result is not None
        assert result["count"] == 0

    def test_single_relationship(self):
        v = _make_validator()
        ont = _ontology(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "type": "rel"}],
        )
        result = v.max_out_degree(ont)
        assert result["entity"] == "a"
        assert result["count"] == 1

    def test_hub_entity(self):
        v = _make_validator()
        ont = _ontology(
            [{"id": "hub"}, {"id": "x"}, {"id": "y"}],
            [
                {"source": "hub", "target": "x", "type": "rel"},
                {"source": "hub", "target": "y", "type": "rel"},
            ],
        )
        result = v.max_out_degree(ont)
        assert result["entity"] == "hub"
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_streak
# ---------------------------------------------------------------------------

class TestScoreStreak:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_streak("up") == 0

    def test_single_entry_streak_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_streak("up") == 1

    def test_up_streak(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.score_streak("up") == 4

    def test_down_streak(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.score_streak("down") == 3

    def test_broken_streak(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.3, 0.4]:  # last two are up, then broken
            _push_opt(o, v)
        assert o.score_streak("up") == 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.recent_best_score
# ---------------------------------------------------------------------------

class TestRecentBestScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.recent_best_score() == pytest.approx(0.0)

    def test_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.recent_best_score(5) == pytest.approx(0.7)

    def test_limits_to_n(self):
        o = _make_optimizer()
        for v in [0.9, 0.1, 0.2]:
            _push_opt(o, v)
        # last 2 are [0.1, 0.2]; best is 0.2
        assert o.recent_best_score(2) == pytest.approx(0.2)

    def test_uses_max(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.recent_best_score(3) == pytest.approx(0.7)
