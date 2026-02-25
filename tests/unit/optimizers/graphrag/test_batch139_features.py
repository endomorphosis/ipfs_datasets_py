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
    @pytest.mark.parametrize(
        "ontology,entity_id,expected",
        [
            ({}, "A", 0),
            (_ont_rels(("A", "B"), ("C", "B")), "B", 2),
            (_ont_rels(("A", "B")), "A", 0),
            (_ont_rels(("A", "B")), "Z", 0),
        ],
    )
    def test_in_degree_scenarios(self, ontology, entity_id, expected):
        v = _make_validator()
        assert v.in_degree(ontology, entity_id) == expected


# ---------------------------------------------------------------------------
# LogicValidator.out_degree
# ---------------------------------------------------------------------------

class TestOutDegree:
    @pytest.mark.parametrize(
        "ontology,entity_id,expected",
        [
            ({}, "A", 0),
            (_ont_rels(("A", "B"), ("A", "C")), "A", 2),
            (_ont_rels(("A", "B")), "B", 0),
            (_ont_rels(("A", "B")), "Z", 0),
        ],
    )
    def test_out_degree_scenarios(self, ontology, entity_id, expected):
        v = _make_validator()
        assert v.out_degree(ontology, entity_id) == expected


# ---------------------------------------------------------------------------
# LogicValidator.top_k_entities_by_degree
# ---------------------------------------------------------------------------

class TestTopKEntitiesByDegree:
    @pytest.mark.parametrize(
        "ontology,k,expected_prefix,max_len",
        [
            ({}, 3, [], 0),
            (_ont_rels(("A", "B"), ("A", "C"), ("A", "D"), ("B", "E")), 1, ["A"], 1),
            (_ont_rels(("A", "B"), ("C", "D"), ("E", "F")), 2, None, 2),
        ],
    )
    def test_top_k_entities_by_degree_scenarios(self, ontology, k, expected_prefix, max_len):
        v = _make_validator()
        result = v.top_k_entities_by_degree(ontology, k=k)
        assert isinstance(result, list)
        assert len(result) <= max_len
        if expected_prefix:
            assert result[0] == expected_prefix[0]


# ---------------------------------------------------------------------------
# OntologyCritic.bucket_scores
# ---------------------------------------------------------------------------

class TestBucketScores:
    @pytest.mark.parametrize(
        "values,buckets,expected_len,expected_total",
        [
            ([], 4, 4, 0),
            ([0.5], 5, 5, 1),
            ([0.1, 0.3, 0.6, 0.9], 4, 4, 4),
        ],
    )
    def test_bucket_scores_scenarios(self, values, buckets, expected_len, expected_total):
        c = _make_critic()
        scores = [_cs(v) for v in values]
        result = c.bucket_scores(scores, buckets=buckets)
        assert len(result) == expected_len
        assert sum(result.values()) == expected_total

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
    @pytest.mark.parametrize(
        "values,expected",
        [
            ([], 0.0),
            ([0.7], 0.7),
            ([0.2, 0.6, 0.9], 0.6),
            ([0.2, 0.4, 0.6, 0.8], 0.5),
        ],
    )
    def test_median_score_scenarios(self, values, expected):
        c = _make_critic()
        scores = [_cs(v) for v in values]
        assert c.median_score(scores) == pytest.approx(expected)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.median_score([_cs(0.5)]), float)
