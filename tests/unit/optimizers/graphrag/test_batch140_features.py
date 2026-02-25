"""Batch-140 feature tests.

Methods under test:
  - OntologyLearningAdapter.domain_coverage()
  - OntologyLearningAdapter.volatility()
  - OntologyGenerator.confidence_std(result)
  - OntologyGenerator.entity_type_distribution(result)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _fr(score, domain=None):
    r = MagicMock()
    r.final_score = score
    if domain is not None:
        r.domain = domain
    else:
        # No domain attr → will use _default
        del r.domain
    return r


def _push_adapter(a, score, domain=None):
    a._feedback.append(_fr(score, domain))


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_result(*entries):
    """entries = (entity_type, confidence) tuples"""
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, EntityExtractionResult
    entities = [
        Entity(id=f"e{i}", type=t, text=f"e{i}", properties={}, confidence=c)
        for i, (t, c) in enumerate(entries)
    ]
    return EntityExtractionResult(entities=entities, relationships=[], confidence=0.5, metadata={}, errors=[])


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.domain_coverage
# ---------------------------------------------------------------------------

class TestDomainCoverage:
    @pytest.mark.parametrize(
        "records,expected",
        [
            ([], 0.0),
            ([(0.8, None), (0.7, None)], 1.0),
            ([(0.2, None)], 0.0),
            ([(0.8, "A"), (0.2, "B")], 0.5),
            ([(0.8, "A"), (0.9, "B")], 1.0),
        ],
    )
    def test_domain_coverage_scenarios(self, records, expected):
        a = _make_adapter()
        for score, domain in records:
            _push_adapter(a, score, domain=domain)
        assert a.domain_coverage() == pytest.approx(expected)

    def test_returns_float(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert isinstance(a.domain_coverage(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.volatility
# ---------------------------------------------------------------------------

class TestVolatility:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.5], 0.0),
            ([0.7, 0.7, 0.7, 0.7], 0.0),
            ([0.0, 1.0, 0.0, 1.0], 1.0),
        ],
    )
    def test_volatility_scenarios(self, scores, expected):
        a = _make_adapter()
        for v in scores:
            _push_adapter(a, v)
        assert a.volatility() == pytest.approx(expected)

    def test_returns_non_negative(self):
        a = _make_adapter()
        _push_adapter(a, 0.3)
        _push_adapter(a, 0.7)
        assert a.volatility() >= 0.0


# ---------------------------------------------------------------------------
# OntologyGenerator.confidence_std
# ---------------------------------------------------------------------------

class TestConfidenceStd:
    @pytest.mark.parametrize(
        "entries,expected",
        [
            ([], 0.0),
            ([("T", 0.7)], 0.0),
            # std = 0.5
            ([("T", 0.0), ("T", 1.0)], 0.5),
            ([("T", 0.6), ("T", 0.6), ("T", 0.6)], 0.0),
        ],
    )
    def test_confidence_std_scenarios(self, entries, expected):
        g = _make_generator()
        r = _make_result(*entries)
        assert g.confidence_std(r) == pytest.approx(expected)

    def test_returns_float(self):
        g = _make_generator()
        r = _make_result(("T", 0.4), ("T", 0.6))
        assert isinstance(g.confidence_std(r), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_type_distribution
# ---------------------------------------------------------------------------

class TestEntityTypeDistribution:
    @pytest.mark.parametrize(
        "entries,expected",
        [
            ([], {}),
            ([("Person", 0.8), ("Person", 0.7)], {"Person": 1.0}),
            ([("Person", 0.8), ("Org", 0.7)], {"Person": 0.5, "Org": 0.5}),
        ],
    )
    def test_entity_type_distribution_scenarios(self, entries, expected):
        g = _make_generator()
        r = _make_result(*entries)
        dist = g.entity_type_distribution(r)
        for key, value in expected.items():
            assert dist[key] == pytest.approx(value)
        assert set(dist.keys()) == set(expected.keys())

    def test_fractions_sum_to_one(self):
        g = _make_generator()
        r = _make_result(("A", 0.8), ("B", 0.7), ("C", 0.6))
        dist = g.entity_type_distribution(r)
        assert sum(dist.values()) == pytest.approx(1.0)

    def test_returns_dict(self):
        g = _make_generator()
        r = _make_result(("X", 0.5))
        assert isinstance(g.entity_type_distribution(r), dict)
