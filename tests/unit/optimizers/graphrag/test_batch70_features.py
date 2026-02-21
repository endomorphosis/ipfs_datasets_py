"""Batch-70 feature tests.

Covers:
- OntologyOptimizer.score_percentile(p)
- OntologyOptimizer.format_history_table()
- OntologyOptimizer.average_improvement_per_batch()
- EntityExtractionResult.confidence_histogram(bins)
- ExtractionConfig.scale_thresholds(factor)
- OntologyGenerator.tag_entities(result, tags)
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer, OptimizationReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opt(scores):
    opt = OntologyOptimizer()
    for i, s in enumerate(scores):
        opt._history.append(OptimizationReport(
            average_score=s,
            trend="stable",
            improvement_rate=0.5,
            metadata={"num_sessions": 1},
        ))
    return opt


def _entity(eid="e1", text="Alice", conf=0.8) -> Entity:
    return Entity(id=eid, type="Person", text=text, confidence=conf)


def _result(*entities) -> EntityExtractionResult:
    return EntityExtractionResult(entities=list(entities), relationships=[], confidence=0.8)


def _cfg(**kw) -> ExtractionConfig:
    return ExtractionConfig(**kw)


def _gen() -> OntologyGenerator:
    return OntologyGenerator()


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_percentile
# ---------------------------------------------------------------------------

class TestScorePercentile:
    def test_returns_float(self):
        assert isinstance(_opt([0.5, 0.7]).score_percentile(50), float)

    def test_100th_is_max(self):
        opt = _opt([0.3, 0.6, 0.9])
        assert abs(opt.score_percentile(100) - 0.9) < 1e-9

    def test_0th_raises(self):
        with pytest.raises(ValueError):
            _opt([0.5]).score_percentile(0)

    def test_empty_history_raises(self):
        with pytest.raises(ValueError):
            OntologyOptimizer().score_percentile(50)

    def test_median_of_two(self):
        opt = _opt([0.0, 1.0])
        assert abs(opt.score_percentile(50) - 0.5) < 1e-9

    def test_single_entry_all_percentiles_equal(self):
        opt = _opt([0.7])
        assert abs(opt.score_percentile(1) - 0.7) < 1e-9
        assert abs(opt.score_percentile(100) - 0.7) < 1e-9


# ---------------------------------------------------------------------------
# OntologyOptimizer.format_history_table
# ---------------------------------------------------------------------------

class TestFormatHistoryTable:
    def test_returns_string(self):
        assert isinstance(_opt([0.5]).format_history_table(), str)

    def test_empty_history_message(self):
        assert OntologyOptimizer().format_history_table() == "(no history)"

    def test_has_header(self):
        table = _opt([0.5, 0.7]).format_history_table()
        assert "avg_score" in table

    def test_correct_row_count(self):
        table = _opt([0.3, 0.6, 0.9]).format_history_table()
        # header + divider + 3 data rows = 5 lines
        lines = [l for l in table.splitlines() if l.strip()]
        assert len(lines) >= 3

    def test_scores_in_table(self):
        table = _opt([0.1234]).format_history_table()
        assert "0.1234" in table


# ---------------------------------------------------------------------------
# OntologyOptimizer.average_improvement_per_batch
# ---------------------------------------------------------------------------

class TestAverageImprovementPerBatch:
    def test_returns_float(self):
        assert isinstance(_opt([0.4, 0.6]).average_improvement_per_batch(), float)

    def test_zero_for_single_entry(self):
        assert _opt([0.5]).average_improvement_per_batch() == 0.0

    def test_zero_for_empty(self):
        assert OntologyOptimizer().average_improvement_per_batch() == 0.0

    def test_positive_improvement(self):
        # 0.3 -> 0.5 -> 0.7: deltas [0.2, 0.2], mean = 0.2
        assert abs(_opt([0.3, 0.5, 0.7]).average_improvement_per_batch() - 0.2) < 1e-9

    def test_negative_decline(self):
        # 0.9 -> 0.7 -> 0.5: deltas [-0.2, -0.2], mean = -0.2
        assert abs(_opt([0.9, 0.7, 0.5]).average_improvement_per_batch() - (-0.2)) < 1e-9


# ---------------------------------------------------------------------------
# EntityExtractionResult.confidence_histogram
# ---------------------------------------------------------------------------

class TestConfidenceHistogram:
    def test_returns_list(self):
        r = _result(_entity(conf=0.5))
        assert isinstance(r.confidence_histogram(), list)

    def test_length_equals_bins(self):
        r = _result(_entity(conf=0.5))
        assert len(r.confidence_histogram(bins=4)) == 4

    def test_sum_equals_entity_count(self):
        r = _result(_entity("e1", conf=0.2), _entity("e2", conf=0.7), _entity("e3", conf=0.9))
        hist = r.confidence_histogram(bins=5)
        assert sum(hist) == 3

    def test_empty_result(self):
        r = _result()
        hist = r.confidence_histogram(bins=4)
        assert hist == [0, 0, 0, 0]

    def test_invalid_bins_raises(self):
        with pytest.raises(ValueError):
            _result(_entity()).confidence_histogram(bins=0)

    def test_single_bin(self):
        r = _result(_entity(conf=0.3), _entity(conf=0.8))
        hist = r.confidence_histogram(bins=1)
        assert hist == [2]


# ---------------------------------------------------------------------------
# ExtractionConfig.scale_thresholds
# ---------------------------------------------------------------------------

class TestScaleThresholds:
    def test_returns_new_instance(self):
        cfg = _cfg(confidence_threshold=0.5)
        scaled = cfg.scale_thresholds(0.8)
        assert scaled is not cfg

    def test_confidence_threshold_scaled(self):
        cfg = _cfg(confidence_threshold=0.5)
        scaled = cfg.scale_thresholds(0.8)
        assert abs(scaled.confidence_threshold - 0.4) < 1e-9

    def test_clamps_above_one(self):
        cfg = _cfg(confidence_threshold=0.9)
        scaled = cfg.scale_thresholds(2.0)
        assert scaled.confidence_threshold <= 1.0

    def test_clamps_below_zero(self):
        cfg = _cfg(confidence_threshold=0.1)
        scaled = cfg.scale_thresholds(0.0001)
        assert scaled.confidence_threshold >= 0.0

    def test_invalid_factor_raises(self):
        with pytest.raises(ValueError):
            _cfg().scale_thresholds(0)

    def test_negative_factor_raises(self):
        with pytest.raises(ValueError):
            _cfg().scale_thresholds(-1.0)

    def test_other_fields_unchanged(self):
        cfg = _cfg(max_entities=99)
        scaled = cfg.scale_thresholds(0.5)
        assert scaled.max_entities == 99


# ---------------------------------------------------------------------------
# OntologyGenerator.tag_entities
# ---------------------------------------------------------------------------

class TestTagEntities:
    def test_returns_new_result(self):
        r = _result(_entity())
        tagged = _gen().tag_entities(r, {"src": "doc1"})
        assert tagged is not r

    def test_tags_applied_to_all(self):
        r = _result(_entity("e1"), _entity("e2", "Bob"))
        tagged = _gen().tag_entities(r, {"reviewed": True})
        assert all(e.properties.get("reviewed") is True for e in tagged.entities)

    def test_existing_props_overwritten(self):
        e = Entity(id="e1", type="T", text="x", properties={"k": "old"})
        r = _result(e)
        tagged = _gen().tag_entities(r, {"k": "new"})
        assert tagged.entities[0].properties["k"] == "new"

    def test_empty_tags(self):
        e = Entity(id="e1", type="T", text="x", properties={"k": "v"})
        r = _result(e)
        tagged = _gen().tag_entities(r, {})
        assert tagged.entities[0].properties == {"k": "v"}

    def test_original_props_not_mutated(self):
        e = Entity(id="e1", type="T", text="x", properties={})
        r = _result(e)
        _gen().tag_entities(r, {"new_key": "val"})
        assert "new_key" not in e.properties

    def test_relationships_preserved(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        e1, e2 = _entity("e1"), _entity("e2", "Bob")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        r = EntityExtractionResult(entities=[e1, e2], relationships=[rel], confidence=0.8)
        tagged = _gen().tag_entities(r, {"x": 1})
        assert len(tagged.relationships) == 1
