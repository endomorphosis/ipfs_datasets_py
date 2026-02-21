"""Batch 105: confidence bands, strict pass, stddev/median, validator density."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer


def _entity(eid: str, conf: float) -> Entity:
    return Entity(id=eid, text=eid, type="PERSON", confidence=conf)


def _score(v: float) -> CriticScore:
    return CriticScore(
        completeness=v,
        consistency=v,
        clarity=v,
        granularity=v,
        domain_alignment=v,
    )


class _Entry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


class TestGroupEntitiesByConfidenceBand:
    def test_empty_result(self):
        gen = OntologyGenerator()
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.0, metadata={})
        out = gen.group_entities_by_confidence_band(result, [0.5])
        assert sum(len(v) for v in out.values()) == 0

    def test_empty_bands_returns_all_bucket(self):
        gen = OntologyGenerator()
        result = EntityExtractionResult(entities=[_entity("a", 0.7)], relationships=[], confidence=0.0, metadata={})
        out = gen.group_entities_by_confidence_band(result, [])
        assert list(out.keys()) == ["all"]
        assert len(out["all"]) == 1

    def test_buckets_assignment(self):
        gen = OntologyGenerator()
        result = EntityExtractionResult(
            entities=[_entity("a", 0.2), _entity("b", 0.5), _entity("c", 0.95)],
            relationships=[],
            confidence=0.0,
            metadata={},
        )
        out = gen.group_entities_by_confidence_band(result, [0.4, 0.9])
        assert len(out["<0.4"]) == 1
        assert len(out["[0.4,0.9)"]) == 1
        assert len(out[">=0.9"]) == 1

    def test_unsorted_bands_supported(self):
        gen = OntologyGenerator()
        result = EntityExtractionResult(entities=[_entity("a", 0.5)], relationships=[], confidence=0.0, metadata={})
        out = gen.group_entities_by_confidence_band(result, [0.9, 0.4])
        assert len(out["[0.4,0.9)"]) == 1


class TestAllPass:
    def test_empty_true(self):
        assert OntologyCritic().all_pass([]) is True

    def test_strict_above_threshold(self):
        critic = OntologyCritic()
        assert critic.all_pass([_score(0.7), _score(0.8)], threshold=0.6) is True

    def test_equal_threshold_fails(self):
        critic = OntologyCritic()
        assert critic.all_pass([_score(0.6)], threshold=0.6) is False

    def test_below_threshold_fails(self):
        critic = OntologyCritic()
        assert critic.all_pass([_score(0.9), _score(0.5)], threshold=0.6) is False


class TestFeedbackStddev:
    def test_empty_zero(self):
        assert OntologyLearningAdapter().feedback_stddev() == pytest.approx(0.0)

    def test_single_zero(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.4)
        assert a.feedback_stddev() == pytest.approx(0.0)

    def test_nonzero(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.0)
        a.apply_feedback(1.0)
        assert a.feedback_stddev() == pytest.approx(0.5)

    def test_float_type(self):
        assert isinstance(OntologyLearningAdapter().feedback_stddev(), float)


class TestScoreMedian:
    def test_empty_zero(self):
        assert OntologyOptimizer().score_median() == pytest.approx(0.0)

    def test_odd_median(self):
        o = OntologyOptimizer()
        o._history.extend([_Entry(0.1), _Entry(0.9), _Entry(0.6)])
        assert o.score_median() == pytest.approx(0.6)

    def test_even_median(self):
        o = OntologyOptimizer()
        o._history.extend([_Entry(0.1), _Entry(0.3), _Entry(0.9), _Entry(1.0)])
        assert o.score_median() == pytest.approx(0.6)

    def test_float_type(self):
        assert isinstance(OntologyOptimizer().score_median(), float)


class TestValidatorRelationshipDensity:
    def test_no_entities_zero(self):
        v = LogicValidator()
        assert v.relationship_density({"entities": [], "relationships": [{"id": "r1"}]}) == pytest.approx(0.0)

    def test_simple_ratio(self):
        v = LogicValidator()
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}], "relationships": [{"id": "r1"}]}
        assert v.relationship_density(ont) == pytest.approx(0.5)

    def test_edges_nodes_supported(self):
        v = LogicValidator()
        ont = {"nodes": [{"id": "n1"}], "edges": [{"id": "x"}, {"id": "y"}]}
        assert v.relationship_density(ont) == pytest.approx(2.0)

    def test_float_type(self):
        assert isinstance(LogicValidator().relationship_density({}), float)
