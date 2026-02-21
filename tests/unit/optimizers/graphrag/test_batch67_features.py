"""Batch-67 feature tests.

Covers:
- OntologyMediator.get_action_summary()
- OntologyMediator.preview_recommendations()
- OntologyPipeline.from_dict()
- OntologyGenerator.deduplicate_entities()
- OntologyCritic.calibrate_thresholds()
"""

import pytest
from typing import List

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(domain: str = "test") -> OntologyGenerationContext:
    return OntologyGenerationContext(data_source="t", data_type="text", domain=domain)


def _critic() -> OntologyCritic:
    return OntologyCritic(use_llm=False)


def _mediator() -> OntologyMediator:
    gen = OntologyGenerator()
    crit = _critic()
    return OntologyMediator(generator=gen, critic=crit, max_rounds=2)


def _make_score(c=0.7, cons=0.8, cl=0.6, g=0.7, da=0.8) -> CriticScore:
    return CriticScore(
        completeness=c,
        consistency=cons,
        clarity=cl,
        granularity=g,
        relationship_coherence=da,
        domain_alignment=da,
        recommendations=["Add more entities", "Improve clarity"],
    )


def _make_entity(eid="e1", text="Alice", etype="Person") -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=0.9)


def _make_result(*entities, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities),
        relationships=list(rels or []),
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# OntologyMediator.get_action_summary
# ---------------------------------------------------------------------------

class TestGetActionSummary:
    def test_returns_list(self):
        med = _mediator()
        assert isinstance(med.get_action_summary(), list)

    def test_empty_when_no_actions(self):
        med = _mediator()
        assert med.get_action_summary() == []

    def test_sorted_by_count_desc(self):
        med = _mediator()
        med._action_counts["add_entities"] = 3
        med._action_counts["improve_clarity"] = 7
        med._action_counts["remove_duplicates"] = 1
        summary = med.get_action_summary()
        counts = [item["count"] for item in summary]
        assert counts == sorted(counts, reverse=True)

    def test_rank_starts_at_one(self):
        med = _mediator()
        med._action_counts["a"] = 2
        summary = med.get_action_summary()
        assert summary[0]["rank"] == 1

    def test_top_n_limits(self):
        med = _mediator()
        for i in range(10):
            med._action_counts[f"action_{i}"] = i + 1
        summary = med.get_action_summary(top_n=3)
        assert len(summary) == 3

    def test_all_keys_present(self):
        med = _mediator()
        med._action_counts["x"] = 1
        item = med.get_action_summary()[0]
        assert "action" in item and "count" in item and "rank" in item


# ---------------------------------------------------------------------------
# OntologyMediator.preview_recommendations
# ---------------------------------------------------------------------------

class TestPreviewRecommendations:
    def test_returns_list(self):
        med = _mediator()
        result = med.preview_recommendations({}, _make_score(), _ctx())
        assert isinstance(result, list)

    def test_does_not_modify_action_counts(self):
        med = _mediator()
        before = dict(med._action_counts)
        med.preview_recommendations({}, _make_score(), _ctx())
        assert med._action_counts == before

    def test_does_not_modify_undo_stack(self):
        med = _mediator()
        before_len = len(med._undo_stack)
        med.preview_recommendations({}, _make_score(), _ctx())
        assert len(med._undo_stack) == before_len

    def test_returns_score_recommendations(self):
        med = _mediator()
        score = _make_score()
        result = med.preview_recommendations({}, score, _ctx())
        assert result == list(score.recommendations)

    def test_empty_recommendations(self):
        med = _mediator()
        score = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5, granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        result = med.preview_recommendations({}, score, _ctx())
        assert result == []


# ---------------------------------------------------------------------------
# OntologyPipeline.from_dict
# ---------------------------------------------------------------------------

class TestPipelineFromDict:
    def test_round_trip_domain(self):
        p = OntologyPipeline(domain="legal")
        p2 = OntologyPipeline.from_dict(p.as_dict())
        assert p2.domain == "legal"

    def test_round_trip_max_rounds(self):
        p = OntologyPipeline(domain="x", max_rounds=7)
        p2 = OntologyPipeline.from_dict(p.as_dict())
        assert p2._mediator.max_rounds == 7

    def test_returns_pipeline_instance(self):
        d = {"domain": "finance", "use_llm": False, "max_rounds": 2}
        p = OntologyPipeline.from_dict(d)
        assert isinstance(p, OntologyPipeline)

    def test_defaults_for_missing_keys(self):
        p = OntologyPipeline.from_dict({})
        assert isinstance(p, OntologyPipeline)
        assert p.domain == "general"

    def test_classmethod_call(self):
        p = OntologyPipeline.from_dict({"domain": "test"})
        assert p.domain == "test"


# ---------------------------------------------------------------------------
# OntologyGenerator.deduplicate_entities
# ---------------------------------------------------------------------------

class TestDeduplicateEntities:
    def test_no_duplicates_unchanged(self):
        gen = OntologyGenerator()
        result = _make_result(_make_entity("e1", "Alice"), _make_entity("e2", "Bob"))
        deduped = gen.deduplicate_entities(result)
        assert len(deduped.entities) == 2

    def test_removes_exact_text_dup(self):
        gen = OntologyGenerator()
        result = _make_result(
            _make_entity("e1", "Alice"),
            _make_entity("e2", "Alice"),  # duplicate text
        )
        deduped = gen.deduplicate_entities(result)
        assert len(deduped.entities) == 1

    def test_case_insensitive_dedup(self):
        gen = OntologyGenerator()
        result = _make_result(
            _make_entity("e1", "alice"),
            _make_entity("e2", "Alice"),
        )
        deduped = gen.deduplicate_entities(result)
        assert len(deduped.entities) == 1

    def test_keeps_highest_confidence(self):
        gen = OntologyGenerator()
        e_low = Entity(id="e1", type="Person", text="Alice", confidence=0.3)
        e_high = Entity(id="e2", type="Person", text="alice", confidence=0.9)
        result = _make_result(e_low, e_high)
        deduped = gen.deduplicate_entities(result)
        assert deduped.entities[0].confidence == 0.9

    def test_rels_remapped_after_dedup(self):
        gen = OntologyGenerator()
        e1 = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        e2 = Entity(id="e2", type="Person", text="alice", confidence=0.5)  # dup, lower conf
        e3 = _make_entity("e3", "Bob")
        rel = Relationship(id="r1", source_id="e2", target_id="e3", type="knows")
        result = _make_result(e1, e2, e3, rels=[rel])
        deduped = gen.deduplicate_entities(result)
        # e2 removed; rel remapped to e1->e3
        assert any(r.source_id == "e1" for r in deduped.relationships)

    def test_metadata_dedup_count(self):
        gen = OntologyGenerator()
        result = _make_result(_make_entity("e1", "Alice"), _make_entity("e2", "alice"))
        deduped = gen.deduplicate_entities(result)
        assert deduped.metadata.get("deduplication_count") == 1
        gen = OntologyGenerator()
        result = _make_result(
            _make_entity("same_id", "Alice"),
            _make_entity("same_id", "Bob"),  # same id, different text
        )
        deduped = gen.deduplicate_entities(result, key="id")
        assert len(deduped.entities) == 1

    def test_invalid_key_raises(self):
        gen = OntologyGenerator()
        with pytest.raises(ValueError):
            gen.deduplicate_entities(_make_result(_make_entity()), key="confidence")

    def test_empty_result(self):
        gen = OntologyGenerator()
        deduped = gen.deduplicate_entities(_make_result())
        assert deduped.entities == []


# ---------------------------------------------------------------------------
# OntologyCritic.calibrate_thresholds
# ---------------------------------------------------------------------------

class TestCalibrateThresholds:
    def _scores(self, values):
        return [CriticScore(
            completeness=v, consistency=v, clarity=v, granularity=v,
            relationship_coherence=v, domain_alignment=v
        ) for v in values]

    def test_returns_dict(self):
        result = _critic().calibrate_thresholds(self._scores([0.5, 0.7, 0.9]))
        assert isinstance(result, dict)

    def test_all_dims_present(self):
        result = _critic().calibrate_thresholds(self._scores([0.5, 0.7]))
        expected_keys = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert set(result.keys()) == expected_keys

    def test_stored_on_instance(self):
        critic = _critic()
        critic.calibrate_thresholds(self._scores([0.4, 0.6, 0.8]))
        assert hasattr(critic, "_calibrated_thresholds")
        assert isinstance(critic._calibrated_thresholds, dict)

    def test_100th_percentile_is_max(self):
        scores = self._scores([0.3, 0.6, 0.9])
        result = _critic().calibrate_thresholds(scores, percentile=100.0)
        assert abs(result["completeness"] - 0.9) < 1e-6

    def test_empty_scores_raises(self):
        with pytest.raises(ValueError):
            _critic().calibrate_thresholds([])

    def test_invalid_percentile_raises(self):
        with pytest.raises(ValueError):
            _critic().calibrate_thresholds(self._scores([0.5]), percentile=0)

    def test_thresholds_in_range(self):
        result = _critic().calibrate_thresholds(self._scores([0.2, 0.5, 0.8, 1.0]))
        for v in result.values():
            assert 0.0 <= v <= 1.0
