"""Batch-169 feature tests.

Methods under test:
  - LogicValidator.multi_hop_count(ontology, src, max_hops)
  - OntologyOptimizer.score_above_percentile(p)
  - OntologyGenerator.entities_with_properties(result)
  - OntologyPipeline.score_histogram(bins)
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


def _make_entity(eid, props=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, properties=props or {})


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _ont(rels):
    return {"entities": [], "relationships": rels}


# ---------------------------------------------------------------------------
# LogicValidator.multi_hop_count
# ---------------------------------------------------------------------------

class TestMultiHopCount:
    def test_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.multi_hop_count(_ont([]), "a", max_hops=2) == 0

    def test_direct_neighbor_one_hop(self):
        v = _make_validator()
        rels = [{"source": "a", "target": "b", "type": "r"}]
        assert v.multi_hop_count(_ont(rels), "a", max_hops=1) == 1

    def test_two_hops(self):
        v = _make_validator()
        rels = [
            {"source": "a", "target": "b", "type": "r"},
            {"source": "b", "target": "c", "type": "r"},
        ]
        assert v.multi_hop_count(_ont(rels), "a", max_hops=2) == 2

    def test_max_hops_limit(self):
        v = _make_validator()
        rels = [
            {"source": "a", "target": "b", "type": "r"},
            {"source": "b", "target": "c", "type": "r"},
        ]
        # max_hops=1 should only reach b, not c
        assert v.multi_hop_count(_ont(rels), "a", max_hops=1) == 1

    def test_no_outgoing_edges(self):
        v = _make_validator()
        rels = [{"source": "b", "target": "a", "type": "r"}]
        assert v.multi_hop_count(_ont(rels), "a", max_hops=3) == 0


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_above_percentile
# ---------------------------------------------------------------------------

class TestScoreAbovePercentile:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_above_percentile(75) == 0

    def test_all_same_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_above_percentile(75) == 0

    def test_top_quarter(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        result = o.score_above_percentile(75)
        assert result >= 1

    def test_returns_integer(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert isinstance(o.score_above_percentile(50), int)


# ---------------------------------------------------------------------------
# OntologyGenerator.entities_with_properties
# ---------------------------------------------------------------------------

class TestEntitiesWithProperties:
    def test_empty_result(self):
        gen = _make_generator()
        assert gen.entities_with_properties(_make_result([])) == []

    def test_no_properties(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.entities_with_properties(_make_result(entities)) == []

    def test_some_with_properties(self):
        gen = _make_generator()
        entities = [
            _make_entity("e1", {"role": "hero"}),
            _make_entity("e2"),
            _make_entity("e3", {"color": "red"}),
        ]
        result = gen.entities_with_properties(_make_result(entities))
        assert len(result) == 2
        ids = [e.id for e in result]
        assert "e1" in ids
        assert "e3" in ids


# ---------------------------------------------------------------------------
# OntologyPipeline.score_histogram
# ---------------------------------------------------------------------------

class TestScoreHistogram:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.score_histogram() == {}

    def test_all_keys_present(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        hist = p.score_histogram(bins=5)
        assert len(hist) == 5

    def test_counts_sum_to_run_count(self):
        p = _make_pipeline()
        for v in [0.1, 0.3, 0.7, 0.9]:
            _push_run(p, v)
        hist = p.score_histogram(bins=5)
        assert sum(hist.values()) == 4

    def test_single_bin(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6]:
            _push_run(p, v)
        hist = p.score_histogram(bins=1)
        assert sum(hist.values()) == 3
