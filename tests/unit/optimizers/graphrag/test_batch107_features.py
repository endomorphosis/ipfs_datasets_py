"""Batch-107 feature tests.

Methods under test:
  - OntologyOptimizer.trend_string()
  - OntologyOptimizer.entries_above_score(threshold)
  - OntologyOptimizer.running_average(window)
  - OntologyOptimizer.score_quartiles()
  - OntologyOptimizer.score_iqr()
  - LogicValidator.all_entity_ids()
  - LogicValidator.all_relationship_ids()
  - LogicValidator.entity_type_set()
  - LogicValidator.dangling_references()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer

    opt = OntologyOptimizer()
    return opt


class _FakeEntry:
    def __init__(self, score, trend="flat"):
        self.average_score = score
        self.trend = trend
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _make_optimizer_with_history(scores):
    opt = _make_optimizer()
    for s in scores:
        opt._history.append(_FakeEntry(s))
    return opt


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator, ProverConfig

    cfg = ProverConfig()
    return LogicValidator(cfg)


# ---------------------------------------------------------------------------
# OntologyOptimizer.trend_string
# ---------------------------------------------------------------------------

class TestTrendString:
    def test_returns_na_when_empty(self):
        opt = _make_optimizer()
        assert opt.trend_string() == "n/a"

    def test_returns_na_when_single_entry(self):
        opt = _make_optimizer_with_history([0.5])
        assert opt.trend_string() == "n/a"

    def test_improving(self):
        opt = _make_optimizer_with_history([0.1, 0.2, 0.3, 0.4, 0.5])
        assert opt.trend_string() == "improving"

    def test_declining(self):
        opt = _make_optimizer_with_history([0.9, 0.8, 0.7, 0.6, 0.5])
        assert opt.trend_string() == "declining"

    def test_flat(self):
        opt = _make_optimizer_with_history([0.5, 0.5, 0.5, 0.5])
        assert opt.trend_string() == "flat"

    def test_volatile(self):
        opt = _make_optimizer_with_history([0.1, 0.9, 0.1, 0.9, 0.1])
        assert opt.trend_string() == "volatile"

    def test_custom_window(self):
        # Only look at last 2 entries (both rising)
        opt = _make_optimizer_with_history([0.9, 0.1, 0.5, 0.8])
        assert opt.trend_string(window=2) == "improving"

    def test_two_entry_history(self):
        opt = _make_optimizer_with_history([0.3, 0.6])
        assert opt.trend_string() == "improving"


# ---------------------------------------------------------------------------
# OntologyOptimizer.entries_above_score
# ---------------------------------------------------------------------------

class TestEntriesAboveScore:
    def test_empty_history(self):
        opt = _make_optimizer()
        assert opt.entries_above_score(0.5) == []

    def test_all_below(self):
        opt = _make_optimizer_with_history([0.1, 0.2, 0.3])
        assert opt.entries_above_score(0.5) == []

    def test_some_above(self):
        opt = _make_optimizer_with_history([0.4, 0.6, 0.8])
        result = opt.entries_above_score(0.5)
        assert len(result) == 2
        assert all(e.average_score > 0.5 for e in result)

    def test_exact_threshold_excluded(self):
        opt = _make_optimizer_with_history([0.5, 0.6])
        result = opt.entries_above_score(0.5)
        assert len(result) == 1
        assert result[0].average_score == 0.6


# ---------------------------------------------------------------------------
# OntologyOptimizer.running_average
# ---------------------------------------------------------------------------

class TestRunningAverage:
    def test_raises_for_window_zero(self):
        opt = _make_optimizer()
        with pytest.raises(ValueError):
            opt.running_average(0)

    def test_empty_history(self):
        opt = _make_optimizer()
        assert opt.running_average(3) == []

    def test_window_larger_than_history(self):
        opt = _make_optimizer_with_history([0.5, 0.6])
        assert opt.running_average(5) == []

    def test_window_one(self):
        opt = _make_optimizer_with_history([0.2, 0.4, 0.6])
        result = opt.running_average(1)
        assert result == pytest.approx([0.2, 0.4, 0.6])

    def test_window_two(self):
        opt = _make_optimizer_with_history([0.2, 0.4, 0.6])
        result = opt.running_average(2)
        assert result == pytest.approx([0.3, 0.5])

    def test_window_equals_history(self):
        opt = _make_optimizer_with_history([0.2, 0.4, 0.6])
        result = opt.running_average(3)
        assert result == pytest.approx([0.4])


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_quartiles
# ---------------------------------------------------------------------------

class TestScoreQuartiles:
    def test_empty_returns_zeros(self):
        opt = _make_optimizer()
        assert opt.score_quartiles() == (0.0, 0.0, 0.0)

    def test_single_entry(self):
        opt = _make_optimizer_with_history([0.7])
        q1, q2, q3 = opt.score_quartiles()
        assert q1 == pytest.approx(0.7)
        assert q2 == pytest.approx(0.7)
        assert q3 == pytest.approx(0.7)

    def test_four_entries(self):
        opt = _make_optimizer_with_history([0.1, 0.3, 0.7, 0.9])
        q1, q2, q3 = opt.score_quartiles()
        assert q1 < q2 < q3

    def test_quartile_order(self):
        opt = _make_optimizer_with_history([0.2, 0.4, 0.5, 0.6, 0.8])
        q1, q2, q3 = opt.score_quartiles()
        assert q1 <= q2 <= q3

    def test_returns_tuple(self):
        opt = _make_optimizer_with_history([0.3, 0.5, 0.7])
        result = opt.score_quartiles()
        assert isinstance(result, tuple)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_iqr
# ---------------------------------------------------------------------------

class TestScoreIQR:
    def test_empty_returns_zero(self):
        opt = _make_optimizer()
        assert opt.score_iqr() == 0.0

    def test_uniform_scores_iqr_zero(self):
        opt = _make_optimizer_with_history([0.5, 0.5, 0.5, 0.5])
        assert opt.score_iqr() == pytest.approx(0.0)

    def test_wide_spread(self):
        opt = _make_optimizer_with_history([0.0, 0.25, 0.5, 0.75, 1.0])
        iqr = opt.score_iqr()
        assert iqr > 0.0

    def test_iqr_equals_q3_minus_q1(self):
        opt = _make_optimizer_with_history([0.1, 0.3, 0.5, 0.7, 0.9])
        q1, _, q3 = opt.score_quartiles()
        assert opt.score_iqr() == pytest.approx(q3 - q1)


# ---------------------------------------------------------------------------
# LogicValidator.all_entity_ids
# ---------------------------------------------------------------------------

class TestAllEntityIds:
    def test_empty(self):
        v = _make_validator()
        assert v.all_entity_ids({}) == []

    def test_basic(self):
        v = _make_validator()
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}]}
        assert v.all_entity_ids(ont) == ["e1", "e2"]

    def test_ignores_missing_id(self):
        v = _make_validator()
        ont = {"entities": [{"id": "e1"}, {"text": "no id"}]}
        assert v.all_entity_ids(ont) == ["e1"]

    def test_nodes_alias(self):
        v = _make_validator()
        ont = {"nodes": [{"id": "n1"}]}
        assert v.all_entity_ids(ont) == ["n1"]


# ---------------------------------------------------------------------------
# LogicValidator.all_relationship_ids
# ---------------------------------------------------------------------------

class TestAllRelationshipIds:
    def test_empty(self):
        v = _make_validator()
        assert v.all_relationship_ids({}) == []

    def test_basic(self):
        v = _make_validator()
        ont = {"relationships": [{"id": "r1"}, {"id": "r2"}]}
        assert v.all_relationship_ids(ont) == ["r1", "r2"]

    def test_edges_alias(self):
        v = _make_validator()
        ont = {"edges": [{"id": "e1"}]}
        assert v.all_relationship_ids(ont) == ["e1"]


# ---------------------------------------------------------------------------
# LogicValidator.entity_type_set
# ---------------------------------------------------------------------------

class TestEntityTypeSet:
    def test_empty(self):
        v = _make_validator()
        assert v.entity_type_set({}) == set()

    def test_basic(self):
        v = _make_validator()
        ont = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Place"},
                {"id": "e3", "type": "Person"},
            ]
        }
        result = v.entity_type_set(ont)
        assert result == {"Person", "Place"}

    def test_returns_set(self):
        v = _make_validator()
        ont = {"entities": [{"id": "e1", "type": "X"}]}
        assert isinstance(v.entity_type_set(ont), set)


# ---------------------------------------------------------------------------
# LogicValidator.dangling_references
# ---------------------------------------------------------------------------

class TestDanglingReferences:
    def test_no_dangling(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e2"}],
        }
        assert v.dangling_references(ont) == []

    def test_dangling_target(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "missing"}],
        }
        assert v.dangling_references(ont) == ["missing"]

    def test_dangling_source(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e2"}],
            "relationships": [{"id": "r1", "source_id": "ghost", "target_id": "e2"}],
        }
        assert v.dangling_references(ont) == ["ghost"]

    def test_returns_sorted_unique(self):
        v = _make_validator()
        ont = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "z", "target_id": "a"},
                {"id": "r2", "source_id": "z", "target_id": "b"},
            ],
        }
        result = v.dangling_references(ont)
        assert result == sorted(set(result))
        assert "z" in result

    def test_empty_ontology(self):
        v = _make_validator()
        assert v.dangling_references({}) == []
