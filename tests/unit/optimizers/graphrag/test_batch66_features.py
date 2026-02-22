"""Batch-66 feature tests.

Covers:
- Entity.from_dict() classmethod
- EntityExtractionResult.to_csv()
- OntologyOptimizer.top_n_ontologies(n)
- OntologyOptimizer.score_variance()
- OntologyOptimizer.improvement_rate()
"""

import csv
import io
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(domain: str = "test") -> OntologyGenerationContext:
    return OntologyGenerationContext(data_source="t", data_type="text", domain=domain)


def _make_entity(eid="e1", etype="Person", text="Alice", conf=0.9, span=None):
    return Entity(id=eid, type=etype, text=text, confidence=conf, source_span=span)


def _make_result(*entities):
    return EntityExtractionResult(entities=list(entities), relationships=[], confidence=0.8)


def _optimizer_with_history(scores):
    """Create an OntologyOptimizer whose _history contains fake reports."""
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OptimizationReport

    opt = OntologyOptimizer()

    for i, score in enumerate(scores):
        fake_ont = {"entities": [{"id": f"e{i}", "type": "T", "text": f"E{i}"}], "relationships": []}
        report = OptimizationReport(
            average_score=score,
            trend="stable",
            improvement_rate=0.5,
            best_ontology=fake_ont,
            metadata={"num_sessions": 1},
        )
        opt._history.append(report)
    return opt


# ---------------------------------------------------------------------------
# Entity.from_dict
# ---------------------------------------------------------------------------

class TestEntityFromDict:
    def test_round_trip(self):
        e = _make_entity(span=(0, 5))
        restored = Entity.from_dict(e.to_dict())
        assert restored.id == e.id
        assert restored.type == e.type
        assert restored.text == e.text
        assert abs(restored.confidence - e.confidence) < 1e-9

    def test_span_preserved(self):
        e = _make_entity(span=(3, 10))
        restored = Entity.from_dict(e.to_dict())
        assert restored.source_span == (3, 10)

    def test_no_span(self):
        e = _make_entity()
        restored = Entity.from_dict(e.to_dict())
        assert restored.source_span is None

    def test_properties_preserved(self):
        e = Entity(id="x", type="T", text="foo", properties={"k": "v"})
        restored = Entity.from_dict(e.to_dict())
        assert restored.properties == {"k": "v"}

    def test_missing_required_key_raises(self):
        with pytest.raises(KeyError):
            Entity.from_dict({"type": "T", "text": "foo"})  # missing id

    def test_defaults_applied(self):
        # Only required keys
        e = Entity.from_dict({"id": "y", "type": "X", "text": "bar"})
        assert e.confidence == 1.0
        assert e.source_span is None

    def test_returns_entity_instance(self):
        restored = Entity.from_dict({"id": "z", "type": "Z", "text": "Z"})
        assert isinstance(restored, Entity)


# ---------------------------------------------------------------------------
# EntityExtractionResult.to_csv
# ---------------------------------------------------------------------------

class TestEntityExtractionResultToCsv:
    def test_returns_string(self):
        result = _make_result(_make_entity())
        assert isinstance(result.to_csv(), str)

    def test_has_header(self):
        csv_str = _make_result(_make_entity()).to_csv()
        lines = csv_str.splitlines()
        assert lines[0] == "id,type,text,confidence,source_span_start,source_span_end"

    def test_correct_row_count(self):
        result = _make_result(_make_entity("e1"), _make_entity("e2", text="Bob"))
        lines = _make_result(_make_entity("e1"), _make_entity("e2", text="Bob")).to_csv().splitlines()
        assert len(lines) == 3  # header + 2 entity rows

    def test_entity_values_in_row(self):
        e = _make_entity(eid="e99", etype="Org", text="ACME", conf=0.75)
        csv_str = _make_result(e).to_csv()
        reader = list(csv.reader(io.StringIO(csv_str)))
        row = reader[1]
        assert row[0] == "e99"
        assert row[1] == "Org"
        assert row[2] == "ACME"
        assert abs(float(row[3]) - 0.75) < 1e-6

    def test_span_present(self):
        e = _make_entity(span=(5, 10))
        csv_str = _make_result(e).to_csv()
        reader = list(csv.reader(io.StringIO(csv_str)))
        row = reader[1]
        assert row[4] == "5"
        assert row[5] == "10"

    def test_span_absent_empty_cols(self):
        e = _make_entity()
        csv_str = _make_result(e).to_csv()
        reader = list(csv.reader(io.StringIO(csv_str)))
        row = reader[1]
        assert row[4] == ""
        assert row[5] == ""

    def test_empty_result(self):
        csv_str = _make_result().to_csv()
        lines = csv_str.splitlines()
        assert len(lines) == 1  # only header


# ---------------------------------------------------------------------------
# OntologyOptimizer.top_n_ontologies
# ---------------------------------------------------------------------------

class TestTopNOntologies:
    def test_returns_list(self):
        opt = _optimizer_with_history([0.5, 0.8, 0.6])
        result = opt.top_n_ontologies(2)
        assert isinstance(result, list)

    def test_respects_n(self):
        opt = _optimizer_with_history([0.5, 0.8, 0.6])
        assert len(opt.top_n_ontologies(2)) <= 2

    def test_sorted_by_score_desc(self):
        opt = _optimizer_with_history([0.5, 0.9, 0.7])
        top = opt.top_n_ontologies(3)
        # First entry should be from the 0.9 batch
        assert top[0]["entities"][0]["id"] == "e1"  # index 1 = score 0.9

    def test_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.top_n_ontologies(5) == []

    def test_invalid_n_raises(self):
        opt = _optimizer_with_history([0.5])
        with pytest.raises(ValueError):
            opt.top_n_ontologies(0)

    def test_n_larger_than_history(self):
        opt = _optimizer_with_history([0.5, 0.6])
        result = opt.top_n_ontologies(100)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_variance
# ---------------------------------------------------------------------------

class TestScoreVariance:
    def test_returns_float(self):
        opt = _optimizer_with_history([0.5, 0.7, 0.9])
        assert isinstance(opt.score_variance(), float)

    def test_zero_for_single_entry(self):
        opt = _optimizer_with_history([0.7])
        assert opt.score_variance() == 0.0

    def test_zero_for_empty(self):
        opt = OntologyOptimizer()
        assert opt.score_variance() == 0.0

    def test_known_variance(self):
        # scores [0.0, 1.0]: mean=0.5, var = (0.25 + 0.25)/2 = 0.25
        opt = _optimizer_with_history([0.0, 1.0])
        assert abs(opt.score_variance() - 0.25) < 1e-9

    def test_non_negative(self):
        opt = _optimizer_with_history([0.3, 0.6, 0.9, 0.4])
        assert opt.score_variance() >= 0.0

    def test_identical_scores_zero_variance(self):
        opt = _optimizer_with_history([0.7, 0.7, 0.7])
        assert abs(opt.score_variance()) < 1e-9


# ---------------------------------------------------------------------------
# OntologyOptimizer.improvement_rate
# ---------------------------------------------------------------------------

class TestImprovementRate:
    def test_returns_float(self):
        opt = _optimizer_with_history([0.4, 0.6, 0.8])
        assert isinstance(opt.improvement_rate(), float)

    def test_all_improving(self):
        opt = _optimizer_with_history([0.3, 0.5, 0.7, 0.9])
        assert opt.improvement_rate() == 1.0

    def test_all_declining(self):
        opt = _optimizer_with_history([0.9, 0.7, 0.5, 0.3])
        assert opt.improvement_rate() == 0.0

    def test_half_improving(self):
        opt = _optimizer_with_history([0.5, 0.7, 0.5, 0.7])
        # pairs: (0.5,0.7)=improve, (0.7,0.5)=decline, (0.5,0.7)=improve -> 2/3
        assert abs(opt.improvement_rate() - 2 / 3) < 1e-9

    def test_single_entry_zero(self):
        opt = _optimizer_with_history([0.5])
        assert opt.improvement_rate() == 0.0

    def test_in_range(self):
        opt = _optimizer_with_history([0.3, 0.6, 0.4, 0.8, 0.5])
        rate = opt.improvement_rate()
        assert 0.0 <= rate <= 1.0
