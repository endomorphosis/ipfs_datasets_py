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
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.domain_coverage() == pytest.approx(0.0)

    def test_single_domain_all_above(self):
        a = _make_adapter()
        _push_adapter(a, 0.8)
        _push_adapter(a, 0.7)
        assert a.domain_coverage() == pytest.approx(1.0)

    def test_single_domain_all_below(self):
        a = _make_adapter()
        _push_adapter(a, 0.2)
        assert a.domain_coverage() == pytest.approx(0.0)

    def test_two_domains_one_covered(self):
        a = _make_adapter()
        _push_adapter(a, 0.8, domain="A")
        _push_adapter(a, 0.2, domain="B")
        cov = a.domain_coverage()
        assert cov == pytest.approx(0.5)

    def test_both_domains_covered(self):
        a = _make_adapter()
        _push_adapter(a, 0.8, domain="A")
        _push_adapter(a, 0.9, domain="B")
        assert a.domain_coverage() == pytest.approx(1.0)

    def test_returns_float(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert isinstance(a.domain_coverage(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.volatility
# ---------------------------------------------------------------------------

class TestVolatility:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.volatility() == pytest.approx(0.0)

    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_adapter(a, 0.5)
        assert a.volatility() == pytest.approx(0.0)

    def test_stable_scores_low_volatility(self):
        a = _make_adapter()
        for _ in range(4):
            _push_adapter(a, 0.7)
        assert a.volatility() == pytest.approx(0.0)

    def test_alternating_scores_high_volatility(self):
        a = _make_adapter()
        for v in [0.0, 1.0, 0.0, 1.0]:
            _push_adapter(a, v)
        assert a.volatility() == pytest.approx(1.0)

    def test_returns_non_negative(self):
        a = _make_adapter()
        _push_adapter(a, 0.3)
        _push_adapter(a, 0.7)
        assert a.volatility() >= 0.0


# ---------------------------------------------------------------------------
# OntologyGenerator.confidence_std
# ---------------------------------------------------------------------------

class TestConfidenceStd:
    def test_empty_result(self):
        g = _make_generator()
        r = _make_result()
        assert g.confidence_std(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result(("T", 0.7))
        assert g.confidence_std(r) == pytest.approx(0.0)

    def test_known_std(self):
        g = _make_generator()
        r = _make_result(("T", 0.0), ("T", 1.0))
        # std = 0.5
        assert g.confidence_std(r) == pytest.approx(0.5)

    def test_identical_scores(self):
        g = _make_generator()
        r = _make_result(("T", 0.6), ("T", 0.6), ("T", 0.6))
        assert g.confidence_std(r) == pytest.approx(0.0)

    def test_returns_float(self):
        g = _make_generator()
        r = _make_result(("T", 0.4), ("T", 0.6))
        assert isinstance(g.confidence_std(r), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_type_distribution
# ---------------------------------------------------------------------------

class TestEntityTypeDistribution:
    def test_empty_result(self):
        g = _make_generator()
        r = _make_result()
        assert g.entity_type_distribution(r) == {}

    def test_single_type(self):
        g = _make_generator()
        r = _make_result(("Person", 0.8), ("Person", 0.7))
        dist = g.entity_type_distribution(r)
        assert dist == {"Person": pytest.approx(1.0)}

    def test_two_types_equal(self):
        g = _make_generator()
        r = _make_result(("Person", 0.8), ("Org", 0.7))
        dist = g.entity_type_distribution(r)
        assert dist["Person"] == pytest.approx(0.5)
        assert dist["Org"] == pytest.approx(0.5)

    def test_fractions_sum_to_one(self):
        g = _make_generator()
        r = _make_result(("A", 0.8), ("B", 0.7), ("C", 0.6))
        dist = g.entity_type_distribution(r)
        assert sum(dist.values()) == pytest.approx(1.0)

    def test_returns_dict(self):
        g = _make_generator()
        r = _make_result(("X", 0.5))
        assert isinstance(g.entity_type_distribution(r), dict)
