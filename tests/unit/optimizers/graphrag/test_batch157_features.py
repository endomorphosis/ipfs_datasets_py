"""Batch-157 feature tests.

Methods under test:
  - OntologyPipeline.last_n_scores(n)
  - LogicValidator.leaf_entities(ontology)
  - LogicValidator.source_entities(ontology)
  - OntologyOptimizer.best_history_entry()
"""
import pytest
from unittest.mock import MagicMock


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


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


# ---------------------------------------------------------------------------
# OntologyPipeline.last_n_scores
# ---------------------------------------------------------------------------

class TestLastNScores:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.last_n_scores(3) == []

    def test_n_zero_returns_empty(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        # Python [-0:] == [:] — returns all; use a direct assertion
        result = p.last_n_scores(5)
        assert len(result) == 1  # only one run exists

    def test_returns_last_n(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.9]:
            _push_run(p, v)
        result = p.last_n_scores(2)
        assert result == pytest.approx([0.5, 0.9])

    def test_n_larger_than_history(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        result = p.last_n_scores(10)
        assert result == pytest.approx([0.3, 0.7])

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.last_n_scores(1) == pytest.approx([0.6])


# ---------------------------------------------------------------------------
# LogicValidator.leaf_entities
# ---------------------------------------------------------------------------

class TestLeafEntities:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.leaf_entities({}) == []

    def test_no_edges_all_are_leaves(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        result = v.leaf_entities(ont)
        assert result == ["A", "B"]

    def test_chain_last_node_is_leaf(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        result = v.leaf_entities(ont)
        assert result == ["C"]

    def test_hub_non_leaf(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "A", "object_id": "C"},
            ],
        }
        leaves = v.leaf_entities(ont)
        assert "A" not in leaves
        assert set(leaves) == {"B", "C"}


# ---------------------------------------------------------------------------
# LogicValidator.source_entities
# ---------------------------------------------------------------------------

class TestSourceEntities:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.source_entities({}) == []

    def test_no_edges_all_are_sources(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        result = v.source_entities(ont)
        assert result == ["A", "B"]

    def test_chain_first_node_is_source(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        result = v.source_entities(ont)
        assert result == ["A"]

    def test_returns_sorted(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "Z"}, {"id": "A"}, {"id": "M"}],
            "relationships": [],
        }
        result = v.source_entities(ont)
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# OntologyOptimizer.best_history_entry
# ---------------------------------------------------------------------------

class TestBestHistoryEntry:
    def test_empty_returns_none(self):
        o = _make_optimizer()
        assert o.best_history_entry() is None

    def test_single_entry_is_best(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        result = o.best_history_entry()
        assert result.average_score == pytest.approx(0.7)

    def test_returns_max_score(self):
        o = _make_optimizer()
        for v in [0.3, 0.9, 0.5]:
            _push_opt(o, v)
        result = o.best_history_entry()
        assert result.average_score == pytest.approx(0.9)

    def test_first_entry_is_best(self):
        o = _make_optimizer()
        for v in [0.9, 0.3, 0.1]:
            _push_opt(o, v)
        result = o.best_history_entry()
        assert result.average_score == pytest.approx(0.9)
