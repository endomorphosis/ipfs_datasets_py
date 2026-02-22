"""Batch-159 feature tests.

Methods under test:
  - OntologyOptimizer.history_iqr()
  - OntologyOptimizer.top_n_history(n)
  - OntologyPipeline.all_runs_above(threshold)
  - OntologyGenerator.entity_type_ratio(result)
"""
import pytest
from unittest.mock import MagicMock


def _make_entity(eid, etype="Person"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=[],
        confidence=1.0,
        metadata={},
        errors=[],
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_iqr
# ---------------------------------------------------------------------------

class TestHistoryIqr:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_iqr() == pytest.approx(0.0)

    def test_too_few_entries_returns_zero(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_iqr() == pytest.approx(0.0)

    def test_four_entries(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.7, 0.9]:
            _push_opt(o, v)
        iqr = o.history_iqr()
        assert iqr >= 0.0

    def test_constant_values_iqr_zero(self):
        o = _make_optimizer()
        for _ in range(8):
            _push_opt(o, 0.5)
        assert o.history_iqr() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyOptimizer.top_n_history
# ---------------------------------------------------------------------------

class TestTopNHistory:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.top_n_history(3) == []

    def test_returns_at_most_n(self):
        o = _make_optimizer()
        for v in [0.1, 0.4, 0.7, 0.9]:
            _push_opt(o, v)
        result = o.top_n_history(2)
        assert len(result) == 2

    def test_sorted_descending(self):
        o = _make_optimizer()
        for v in [0.1, 0.8, 0.5, 0.3]:
            _push_opt(o, v)
        result = o.top_n_history(4)
        scores = [e.average_score for e in result]
        assert scores == sorted(scores, reverse=True)

    def test_best_is_first(self):
        o = _make_optimizer()
        for v in [0.2, 0.9, 0.4]:
            _push_opt(o, v)
        assert o.top_n_history(1)[0].average_score == pytest.approx(0.9)

    def test_fewer_than_n_available(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        result = o.top_n_history(5)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# OntologyPipeline.all_runs_above
# ---------------------------------------------------------------------------

class TestAllRunsAbove:
    def test_empty_returns_false(self):
        p = _make_pipeline()
        assert p.all_runs_above(0.5) is False

    def test_all_above_returns_true(self):
        p = _make_pipeline()
        for v in [0.6, 0.7, 0.8]:
            _push_run(p, v)
        assert p.all_runs_above(0.5) is True

    def test_one_below_returns_false(self):
        p = _make_pipeline()
        _push_run(p, 0.9)
        _push_run(p, 0.3)
        assert p.all_runs_above(0.5) is False

    def test_equal_to_threshold_returns_false(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.all_runs_above(0.5) is False


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_type_ratio
# ---------------------------------------------------------------------------

class TestEntityTypeRatio:
    def test_empty_result(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.entity_type_ratio(result) == {}

    def test_single_type(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "Person"), _make_entity("e2", "Person")]
        result = _make_result(entities)
        ratios = gen.entity_type_ratio(result)
        assert ratios == pytest.approx({"Person": 1.0})

    def test_two_types_even(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "Person"), _make_entity("e2", "Org")]
        result = _make_result(entities)
        ratios = gen.entity_type_ratio(result)
        assert ratios == pytest.approx({"Person": 0.5, "Org": 0.5})

    def test_ratios_sum_to_one(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", "A"),
            _make_entity("e2", "B"),
            _make_entity("e3", "C"),
            _make_entity("e4", "A"),
        ]
        result = _make_result(entities)
        ratios = gen.entity_type_ratio(result)
        assert sum(ratios.values()) == pytest.approx(1.0)
