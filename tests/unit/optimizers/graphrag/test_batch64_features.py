"""Batch 64: EntityExtractionResult.merge, OntologyMediator.reset_state,
OntologyOptimizer.reset_history + session_count, ExtractionConfig.diff,
OntologyGenerator.generate_synthetic_ontology.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    return OntologyGenerationContext(data_source="test", data_type="text", domain="test")


def _score(**kwargs):
    defaults = dict(
        completeness=0.7, consistency=0.7, clarity=0.6, granularity=0.5,
        domain_alignment=0.4, recommendations=["Add more entity properties"],
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_mediator():
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic, max_rounds=3)


def _make_result(entities=None, relationships=None, confidence=0.8):
    ents = entities or [Entity(id="e1", type="Person", text="Alice")]
    rels = relationships or []
    return EntityExtractionResult(entities=ents, relationships=rels, confidence=confidence)


def _make_report(score=0.7, n_sessions=0):
    return OptimizationReport(
        average_score=score, trend="stable", improvement_rate=0.0,
        recommendations=[], best_ontology=None, worst_ontology=None,
        metadata={"num_sessions": n_sessions},
    )


# ---------------------------------------------------------------------------
# EntityExtractionResult.merge
# ---------------------------------------------------------------------------

class TestEntityExtractionResultMerge:
    def test_returns_new_instance(self):
        a = _make_result([Entity(id="e1", type="T", text="Alice")])
        b = _make_result([Entity(id="e2", type="T", text="Bob")])
        merged = a.merge(b)
        assert merged is not a and merged is not b

    def test_non_overlapping_entities_all_present(self):
        a = _make_result([Entity(id="e1", type="T", text="Alice")])
        b = _make_result([Entity(id="e2", type="T", text="Bob")])
        merged = a.merge(b)
        texts = {e.text for e in merged.entities}
        assert "Alice" in texts and "Bob" in texts

    def test_duplicate_entity_not_doubled(self):
        a = _make_result([Entity(id="e1", type="T", text="Alice")])
        b = _make_result([Entity(id="e2", type="T", text="alice")])  # same normalised
        merged = a.merge(b)
        alice_count = sum(1 for e in merged.entities if e.text.lower() == "alice")
        assert alice_count == 1

    def test_relationships_from_other_included(self):
        a = _make_result([Entity(id="e1", type="T", text="Alice")])
        b = _make_result(
            entities=[Entity(id="e2", type="T", text="Bob"), Entity(id="e3", type="T", text="Carol")],
            relationships=[Relationship(id="r1", source_id="e2", target_id="e3", type="knows")],
        )
        merged = a.merge(b)
        assert any(r.id == "r1" for r in merged.relationships)

    def test_confidence_is_average(self):
        a = _make_result(confidence=0.6)
        b = _make_result([Entity(id="e2", type="T", text="Bob")], confidence=0.8)
        merged = a.merge(b)
        assert merged.confidence == pytest.approx(0.7)

    def test_errors_combined(self):
        a = EntityExtractionResult(entities=[], relationships=[], confidence=0.5, errors=["err1"])
        b = EntityExtractionResult(entities=[], relationships=[], confidence=0.5, errors=["err2"])
        merged = a.merge(b)
        assert "err1" in merged.errors and "err2" in merged.errors

    def test_empty_merge(self):
        a = _make_result([Entity(id="e1", type="T", text="Alice")])
        b = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        merged = a.merge(b)
        assert len(merged.entities) == 1

    def test_merge_preserves_metadata(self):
        a = EntityExtractionResult(entities=[], relationships=[], confidence=0.5, metadata={"k": "v"})
        b = EntityExtractionResult(entities=[], relationships=[], confidence=0.5, metadata={"m": "n"})
        merged = a.merge(b)
        assert merged.metadata.get("k") == "v"
        assert merged.metadata.get("m") == "n"


# ---------------------------------------------------------------------------
# OntologyMediator.reset_state
# ---------------------------------------------------------------------------

class TestMediatorResetState:
    def test_resets_action_counts(self):
        mediator = _make_mediator()
        mediator.refine_ontology({"entities": [], "relationships": []}, _score(), _ctx())
        mediator.reset_state()
        assert mediator.get_action_stats() == {}

    def test_resets_undo_stack(self):
        mediator = _make_mediator()
        mediator.refine_ontology({"entities": [], "relationships": []}, _score(), _ctx())
        mediator.reset_state()
        with pytest.raises(IndexError):
            mediator.undo_last_action()

    def test_resets_recommendation_counts(self):
        mediator = _make_mediator()
        mediator.refine_ontology(
            {"entities": [], "relationships": []},
            _score(recommendations=["Add properties"]),
            _ctx(),
        )
        mediator.reset_state()
        assert mediator.get_recommendation_stats() == {}

    def test_reset_on_fresh_mediator_is_no_op(self):
        mediator = _make_mediator()
        mediator.reset_state()  # should not raise
        assert mediator.get_action_stats() == {}

    def test_returns_none(self):
        mediator = _make_mediator()
        result = mediator.reset_state()
        assert result is None


# ---------------------------------------------------------------------------
# OntologyOptimizer.reset_history + session_count
# ---------------------------------------------------------------------------

class TestOptimizerResetHistory:
    def test_returns_count_of_removed_entries(self):
        opt = OntologyOptimizer()
        opt._history.extend([_make_report(), _make_report(), _make_report()])
        assert opt.reset_history() == 3

    def test_history_is_empty_after_reset(self):
        opt = OntologyOptimizer()
        opt._history.extend([_make_report(0.7), _make_report(0.8)])
        opt.reset_history()
        assert opt._history == []

    def test_reset_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.reset_history() == 0

    def test_reset_allows_fresh_analysis(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5))
        opt.reset_history()
        assert opt.score_trend_summary() == "insufficient_data"


class TestSessionCount:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.session_count() == 0

    def test_sums_num_sessions_from_metadata(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(n_sessions=3))
        opt._history.append(_make_report(n_sessions=5))
        assert opt.session_count() == 8

    def test_missing_metadata_treated_as_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(OptimizationReport(
            average_score=0.7, trend="stable", improvement_rate=0.0, recommendations=[]
        ))
        assert opt.session_count() == 0


# ---------------------------------------------------------------------------
# ExtractionConfig.diff
# ---------------------------------------------------------------------------

class TestExtractionConfigDiff:
    def test_identical_configs_return_empty(self):
        cfg = ExtractionConfig()
        assert cfg.diff(cfg) == {}

    def test_single_field_diff(self):
        cfg1 = ExtractionConfig(confidence_threshold=0.5)
        cfg2 = ExtractionConfig(confidence_threshold=0.9)
        diff = cfg1.diff(cfg2)
        assert "confidence_threshold" in diff
        assert diff["confidence_threshold"]["self"] == pytest.approx(0.5)
        assert diff["confidence_threshold"]["other"] == pytest.approx(0.9)

    def test_multiple_fields_diff(self):
        cfg1 = ExtractionConfig(confidence_threshold=0.5, max_entities=10)
        cfg2 = ExtractionConfig(confidence_threshold=0.9, max_entities=50)
        diff = cfg1.diff(cfg2)
        assert "confidence_threshold" in diff
        assert "max_entities" in diff

    def test_unchanged_fields_not_in_diff(self):
        cfg1 = ExtractionConfig(confidence_threshold=0.5)
        cfg2 = ExtractionConfig(confidence_threshold=0.9)
        diff = cfg1.diff(cfg2)
        assert "max_entities" not in diff

    def test_returns_dict(self):
        assert isinstance(ExtractionConfig().diff(ExtractionConfig()), dict)


# ---------------------------------------------------------------------------
# OntologyGenerator.generate_synthetic_ontology
# ---------------------------------------------------------------------------

class TestGenerateSyntheticOntology:
    @pytest.fixture
    def gen(self):
        return OntologyGenerator()

    def test_returns_dict(self, gen):
        assert isinstance(gen.generate_synthetic_ontology("legal"), dict)

    def test_has_required_keys(self, gen):
        ont = gen.generate_synthetic_ontology("legal")
        for key in ("entities", "relationships", "metadata", "domain"):
            assert key in ont

    def test_entity_count_matches_n_entities(self, gen):
        ont = gen.generate_synthetic_ontology("medical", n_entities=4)
        assert len(ont["entities"]) == 4

    def test_domain_preserved(self, gen):
        ont = gen.generate_synthetic_ontology("finance")
        assert ont["domain"] == "finance"

    def test_entities_have_ids(self, gen):
        ont = gen.generate_synthetic_ontology("legal", n_entities=3)
        for e in ont["entities"]:
            assert "id" in e and e["id"]

    def test_unknown_domain_uses_general_types(self, gen):
        ont = gen.generate_synthetic_ontology("unknown_domain", n_entities=2)
        assert len(ont["entities"]) == 2

    def test_single_entity_no_relationships(self, gen):
        ont = gen.generate_synthetic_ontology("legal", n_entities=1)
        assert len(ont["entities"]) == 1
        assert len(ont["relationships"]) == 0

    def test_metadata_marks_synthetic(self, gen):
        ont = gen.generate_synthetic_ontology("medical")
        assert ont["metadata"].get("synthetic") is True
