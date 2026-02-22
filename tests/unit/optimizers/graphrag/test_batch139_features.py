"""Batch-139 feature tests.

Methods under test:
  - LogicValidator.in_degree(ontology, entity_id)
  - LogicValidator.out_degree(ontology, entity_id)
  - LogicValidator.top_k_entities_by_degree(ontology, k)
  - OntologyCritic.bucket_scores(scores, buckets)
  - OntologyCritic.median_score(scores)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _ont_rels(*pairs):
    rels = [{"source_id": s, "target_id": t} for s, t in pairs]
    return {"relationships": rels}


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _cs(overall):
    s = MagicMock()
    s.overall = overall
    return s


# ---------------------------------------------------------------------------
# LogicValidator.in_degree
# ---------------------------------------------------------------------------

class TestInDegree:
    def test_no_relationships(self):
        v = _make_validator()
        assert v.in_degree({}, "A") == 0

    def test_entity_is_target(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("C", "B"))
        assert v.in_degree(ont, "B") == 2

    def test_entity_is_source_only(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"))
        assert v.in_degree(ont, "A") == 0

    def test_unknown_entity(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"))
        assert v.in_degree(ont, "Z") == 0


# ---------------------------------------------------------------------------
# LogicValidator.out_degree
# ---------------------------------------------------------------------------

class TestOutDegree:
    def test_no_relationships(self):
        v = _make_validator()
        assert v.out_degree({}, "A") == 0

    def test_entity_is_source(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("A", "C"))
        assert v.out_degree(ont, "A") == 2

    def test_entity_is_target_only(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"))
        assert v.out_degree(ont, "B") == 0

    def test_unknown_entity(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"))
        assert v.out_degree(ont, "Z") == 0


# ---------------------------------------------------------------------------
# LogicValidator.top_k_entities_by_degree
# ---------------------------------------------------------------------------

class TestTopKEntitiesByDegree:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.top_k_entities_by_degree({}) == []

    def test_highest_degree_first(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("A", "C"), ("A", "D"), ("B", "E"))
        top = v.top_k_entities_by_degree(ont, k=1)
        assert top[0] == "A"

    def test_k_limits_result(self):
        v = _make_validator()
        ont = _ont_rels(("A", "B"), ("C", "D"), ("E", "F"))
        result = v.top_k_entities_by_degree(ont, k=2)
        assert len(result) <= 2

    def test_returns_list(self):
        v = _make_validator()
        ont = _ont_rels(("X", "Y"))
        assert isinstance(v.top_k_entities_by_degree(ont, k=3), list)


# ---------------------------------------------------------------------------
# OntologyCritic.bucket_scores
# ---------------------------------------------------------------------------

class TestBucketScores:
    def test_empty_all_zero(self):
        c = _make_critic()
        result = c.bucket_scores([], buckets=4)
        assert all(v == 0 for v in result.values())

    def test_bucket_count(self):
        c = _make_critic()
        result = c.bucket_scores([_cs(0.5)], buckets=5)
        assert len(result) == 5

    def test_total_equals_input(self):
        c = _make_critic()
        scores = [_cs(v) for v in [0.1, 0.3, 0.6, 0.9]]
        result = c.bucket_scores(scores, buckets=4)
        assert sum(result.values()) == 4

    def test_score_one_in_last_bucket(self):
        c = _make_critic()
        result = c.bucket_scores([_cs(1.0)], buckets=2)
        # last bucket should be "0.50-1.00"
        last = list(result.keys())[-1]
        assert result[last] >= 1


# ---------------------------------------------------------------------------
# OntologyCritic.median_score
# ---------------------------------------------------------------------------

class TestMedianScore:
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.median_score([]) == pytest.approx(0.0)

    def test_single(self):
        c = _make_critic()
        assert c.median_score([_cs(0.7)]) == pytest.approx(0.7)

    def test_odd_count(self):
        c = _make_critic()
        scores = [_cs(0.2), _cs(0.6), _cs(0.9)]
        assert c.median_score(scores) == pytest.approx(0.6)

    def test_even_count(self):
        c = _make_critic()
        scores = [_cs(0.2), _cs(0.4), _cs(0.6), _cs(0.8)]
        assert c.median_score(scores) == pytest.approx(0.5)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.median_score([_cs(0.5)]), float)
