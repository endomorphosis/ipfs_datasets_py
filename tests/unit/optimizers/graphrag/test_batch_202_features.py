"""
Unit tests for Batch 202 implementations.

Tests cover:
- OntologyOptimizer.score_geometric_mean()
- OntologyOptimizer.score_harmonic_mean()
- OntologyLearningAdapter.feedback_geometric_mean()
- OntologyLearningAdapter.feedback_harmonic_mean()
- OntologyGenerator.relationship_confidence_avg()
- LogicValidator.avg_path_length()
- LogicValidator.node_density()
"""
from __future__ import annotations

import math
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report(score: float = 0.5) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


def _adapter_with_scores(scores: list[float]) -> OntologyLearningAdapter:
    adapter = OntologyLearningAdapter(domain="test")
    for s in scores:
        adapter.apply_feedback(final_score=s, actions=[])
    return adapter


def _make_result(
    rels: list[Relationship] | None = None,
    entities: list[Entity] | None = None,
) -> EntityExtractionResult:
    if entities is None:
        entities = [Entity(id="e1", text="Alice", type="Person")]
    if rels is None:
        rels = []
    return EntityExtractionResult(entities=entities, relationships=rels, confidence=0.8)


def _make_ontology(n_entities: int = 3, n_rels: int = 2) -> dict:
    entities = [{"id": f"e{i}"} for i in range(n_entities)]
    rels = []
    for i in range(n_rels):
        src = f"e{i % n_entities}"
        tgt = f"e{(i + 1) % n_entities}"
        rels.append({
            "id": f"r{i}",
            "source_id": src,
            "target_id": tgt,
            "subject_id": src,
            "object_id": tgt,
        })
    return {"entities": entities, "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_geometric_mean
# ---------------------------------------------------------------------------

class TestScoreGeometricMean:
    def test_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.score_geometric_mean() == 0.0

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.64))
        assert opt.score_geometric_mean() == pytest.approx(0.64)

    def test_two_entries(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.25))
        opt._history.append(_report(1.0))
        # geometric mean of 0.25 and 1.0 = sqrt(0.25) = 0.5
        assert opt.score_geometric_mean() == pytest.approx(0.5)

    def test_uniform_scores(self):
        opt = OntologyOptimizer()
        for _ in range(4):
            opt._history.append(_report(0.8))
        assert opt.score_geometric_mean() == pytest.approx(0.8)

    def test_zero_score_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.0))
        opt._history.append(_report(0.9))
        assert opt.score_geometric_mean() == 0.0

    def test_geometric_mean_le_arithmetic_mean(self):
        """AM-GM inequality: geometric <= arithmetic for positive values."""
        opt = OntologyOptimizer()
        scores = [0.3, 0.5, 0.8, 0.9]
        for s in scores:
            opt._history.append(_report(s))
        arith = sum(scores) / len(scores)
        assert opt.score_geometric_mean() <= arith + 1e-9

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.7))
        result = opt.score_geometric_mean()
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_harmonic_mean
# ---------------------------------------------------------------------------

class TestScoreHarmonicMean:
    def test_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.score_harmonic_mean() == 0.0

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        assert opt.score_harmonic_mean() == pytest.approx(0.5)

    def test_two_entries(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.5))
        opt._history.append(_report(1.0))
        # HM = 2 / (1/0.5 + 1/1.0) = 2 / (2+1) = 2/3
        assert opt.score_harmonic_mean() == pytest.approx(2 / 3)

    def test_uniform_scores(self):
        opt = OntologyOptimizer()
        for _ in range(3):
            opt._history.append(_report(0.6))
        assert opt.score_harmonic_mean() == pytest.approx(0.6)

    def test_zero_score_returns_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.0))
        opt._history.append(_report(0.8))
        assert opt.score_harmonic_mean() == 0.0

    def test_harmonic_le_geometric_le_arithmetic(self):
        """Classic mean inequality: HM <= GM <= AM."""
        opt = OntologyOptimizer()
        scores = [0.4, 0.6, 0.8]
        for s in scores:
            opt._history.append(_report(s))
        hm = opt.score_harmonic_mean()
        gm = opt.score_geometric_mean()
        am = sum(scores) / len(scores)
        assert hm <= gm + 1e-9
        assert gm <= am + 1e-9

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.append(_report(0.9))
        assert isinstance(opt.score_harmonic_mean(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_geometric_mean
# ---------------------------------------------------------------------------

class TestFeedbackGeometricMean:
    def test_no_feedback(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_geometric_mean() == 0.0

    def test_single_feedback(self):
        adapter = _adapter_with_scores([0.49])
        assert adapter.feedback_geometric_mean() == pytest.approx(0.49)

    def test_two_values(self):
        adapter = _adapter_with_scores([0.25, 1.0])
        # sqrt(0.25 * 1.0) = 0.5
        assert adapter.feedback_geometric_mean() == pytest.approx(0.5)

    def test_uniform_values(self):
        adapter = _adapter_with_scores([0.7, 0.7, 0.7])
        assert adapter.feedback_geometric_mean() == pytest.approx(0.7)

    def test_zero_returns_zero(self):
        adapter = _adapter_with_scores([0.0, 0.8])
        assert adapter.feedback_geometric_mean() == 0.0

    def test_returns_float(self):
        adapter = _adapter_with_scores([0.6])
        assert isinstance(adapter.feedback_geometric_mean(), float)

    def test_consistent_with_pow(self):
        scores = [0.2, 0.4, 0.8]
        adapter = _adapter_with_scores(scores)
        expected = (0.2 * 0.4 * 0.8) ** (1 / 3)
        assert adapter.feedback_geometric_mean() == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_harmonic_mean
# ---------------------------------------------------------------------------

class TestFeedbackHarmonicMean:
    def test_no_feedback(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_harmonic_mean() == 0.0

    def test_single_feedback(self):
        adapter = _adapter_with_scores([0.5])
        assert adapter.feedback_harmonic_mean() == pytest.approx(0.5)

    def test_two_values(self):
        adapter = _adapter_with_scores([0.5, 1.0])
        # HM = 2 / (2 + 1) = 2/3
        assert adapter.feedback_harmonic_mean() == pytest.approx(2 / 3)

    def test_uniform_values(self):
        adapter = _adapter_with_scores([0.8, 0.8, 0.8])
        assert adapter.feedback_harmonic_mean() == pytest.approx(0.8)

    def test_zero_returns_zero(self):
        adapter = _adapter_with_scores([0.0, 0.5])
        assert adapter.feedback_harmonic_mean() == 0.0

    def test_hm_le_gm(self):
        """Harmonic mean <= geometric mean for positive values."""
        adapter = _adapter_with_scores([0.3, 0.5, 0.7])
        assert adapter.feedback_harmonic_mean() <= adapter.feedback_geometric_mean() + 1e-9

    def test_returns_float(self):
        adapter = _adapter_with_scores([0.4])
        assert isinstance(adapter.feedback_harmonic_mean(), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_confidence_avg
# ---------------------------------------------------------------------------

class TestRelationshipConfidenceAvg:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_no_relationships(self):
        result = _make_result(rels=[])
        assert self.gen.relationship_confidence_avg(result) == 0.0

    def test_single_relationship(self):
        rels = [Relationship(id="r1", source_id="e1", target_id="e2",
                             type="knows", confidence=0.75)]
        result = _make_result(rels=rels)
        assert self.gen.relationship_confidence_avg(result) == pytest.approx(0.75)

    def test_multiple_relationships(self):
        rels = [
            Relationship(id="r1", source_id="e1", target_id="e2",
                         type="knows", confidence=0.6),
            Relationship(id="r2", source_id="e2", target_id="e3",
                         type="works_at", confidence=0.8),
        ]
        result = _make_result(rels=rels)
        assert self.gen.relationship_confidence_avg(result) == pytest.approx(0.7)

    def test_uniform_confidence(self):
        rels = [
            Relationship(id=f"r{i}", source_id="e1", target_id="e2",
                         type="t", confidence=0.9)
            for i in range(5)
        ]
        result = _make_result(rels=rels)
        assert self.gen.relationship_confidence_avg(result) == pytest.approx(0.9)

    def test_matches_confidence_mean(self):
        """relationship_confidence_avg must equal relationship_confidence_mean."""
        rels = [
            Relationship(id="r1", source_id="e1", target_id="e2",
                         type="t", confidence=0.55),
        ]
        result = _make_result(rels=rels)
        assert (self.gen.relationship_confidence_avg(result)
                == self.gen.relationship_confidence_mean(result))

    def test_returns_float(self):
        rels = [Relationship(id="r1", source_id="e1", target_id="e2",
                             type="t", confidence=0.5)]
        result = _make_result(rels=rels)
        assert isinstance(self.gen.relationship_confidence_avg(result), float)


# ---------------------------------------------------------------------------
# LogicValidator.avg_path_length
# ---------------------------------------------------------------------------

class TestAvgPathLength:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology(self):
        assert self.validator.avg_path_length({}) == 0.0

    def test_no_entities(self):
        assert self.validator.avg_path_length({"entities": [], "relationships": []}) == 0.0

    def test_single_entity(self):
        ont = {"entities": [{"id": "e1"}], "relationships": []}
        assert self.validator.avg_path_length(ont) == 0.0

    def test_direct_connection(self):
        ont = _make_ontology(n_entities=2, n_rels=1)
        result = self.validator.avg_path_length(ont)
        assert result >= 0.0  # Should be a non-negative value

    def test_matches_average_path_length(self):
        """avg_path_length must be identical to average_path_length."""
        ont = _make_ontology(n_entities=4, n_rels=3)
        assert (self.validator.avg_path_length(ont)
                == self.validator.average_path_length(ont))

    def test_disconnected_graph(self):
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [],  # no connections
        }
        result = self.validator.avg_path_length(ont)
        assert result == 0.0

    def test_returns_float(self):
        ont = _make_ontology(n_entities=3, n_rels=2)
        assert isinstance(self.validator.avg_path_length(ont), float)


# ---------------------------------------------------------------------------
# LogicValidator.node_density
# ---------------------------------------------------------------------------

class TestNodeDensity:
    def setup_method(self):
        self.validator = LogicValidator()

    def test_empty_ontology(self):
        assert self.validator.node_density({}) == 0.0

    def test_single_node(self):
        ont = {"entities": [{"id": "e1"}], "relationships": []}
        assert self.validator.node_density(ont) == 0.0

    def test_two_nodes_no_edges(self):
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}], "relationships": []}
        assert self.validator.node_density(ont) == 0.0

    def test_two_nodes_one_edge(self):
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e2"}],
        }
        # max_edges = 2 * 1 = 2; density = 1/2 = 0.5
        assert self.validator.node_density(ont) == pytest.approx(0.5)

    def test_complete_directed_graph(self):
        # 3 nodes, 6 edges → density 1.0
        nodes = [{"id": f"e{i}"} for i in range(3)]
        rels = [
            {"id": f"r{i}{j}", "source_id": f"e{i}", "target_id": f"e{j}"}
            for i in range(3)
            for j in range(3)
            if i != j
        ]
        ont = {"entities": nodes, "relationships": rels}
        assert self.validator.node_density(ont) == pytest.approx(1.0)

    def test_none_ontology(self):
        assert self.validator.node_density(None) == 0.0

    def test_density_in_range(self):
        ont = _make_ontology(n_entities=5, n_rels=4)
        d = self.validator.node_density(ont)
        assert 0.0 <= d <= 1.0

    def test_returns_float(self):
        ont = _make_ontology(n_entities=3, n_rels=2)
        assert isinstance(self.validator.node_density(ont), float)

    def test_more_edges_higher_density(self):
        base = {"entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]}
        sparse = {**base, "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e2"}]}
        dense = {
            **base,
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e2", "target_id": "e3"},
                {"id": "r3", "source_id": "e1", "target_id": "e3"},
            ],
        }
        assert self.validator.node_density(sparse) < self.validator.node_density(dense)
