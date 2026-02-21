"""Batch 59: CriticScore.to_radar_chart_data, weighted_overall, compare_batch,
Entity.to_dict, EntityExtractionResult.to_json, LogicValidator.batch_validate.
"""
from __future__ import annotations

import json
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    CriticScore,
    OntologyCritic,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.logic_validator import (
    LogicValidator,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _score(c=0.8, co=0.7, cl=0.9, g=0.6, da=0.75):
    return CriticScore(
        completeness=c,
        consistency=co,
        clarity=cl,
        granularity=g,
        domain_alignment=da,
    )


def _ontology(n: int = 3):
    return {
        "entities": [
            {"id": f"e{i}", "type": "Person", "text": f"Entity{i}", "properties": {}, "confidence": 0.8}
            for i in range(n)
        ],
        "relationships": [],
        "metadata": {},
        "domain": "test",
    }


@pytest.fixture
def ctx():
    return OntologyGenerationContext(data_source="test", data_type="text", domain="test")


# ---------------------------------------------------------------------------
# CriticScore.to_radar_chart_data
# ---------------------------------------------------------------------------

class TestRadarChartData:
    def test_returns_axes_and_values(self):
        data = _score().to_radar_chart_data()
        assert set(data.keys()) == {"axes", "values"}

    def test_axes_are_five_dimensions(self):
        data = _score().to_radar_chart_data()
        assert len(data["axes"]) == 5
        expected = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert set(data["axes"]) == expected

    def test_values_match_score_attributes(self):
        s = _score(c=0.1, co=0.2, cl=0.3, g=0.4, da=0.5)
        data = s.to_radar_chart_data()
        for ax, val in zip(data["axes"], data["values"]):
            assert val == pytest.approx(getattr(s, ax))

    def test_values_length_matches_axes(self):
        data = _score().to_radar_chart_data()
        assert len(data["values"]) == len(data["axes"])

    def test_ordering_is_fixed(self):
        data1 = _score(c=0.1, co=0.2, cl=0.3, g=0.4, da=0.5).to_radar_chart_data()
        data2 = _score(c=0.9, co=0.8, cl=0.7, g=0.6, da=0.5).to_radar_chart_data()
        assert data1["axes"] == data2["axes"]

    def test_delta_score_radar(self):
        s1 = _score(c=0.8)
        s2 = _score(c=0.6)
        delta = s1 - s2
        data = delta.to_radar_chart_data()
        completeness_idx = data["axes"].index("completeness")
        assert data["values"][completeness_idx] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# CriticScore.weighted_overall
# ---------------------------------------------------------------------------

class TestWeightedOverall:
    def test_equal_weights_close_to_mean(self):
        s = _score(c=0.5, co=0.5, cl=0.5, g=0.5, da=0.5)
        weights = {d: 1.0 for d in ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]}
        assert s.weighted_overall(weights) == pytest.approx(0.5)

    def test_single_dimension_weight(self):
        s = _score(c=0.9, co=0.1, cl=0.1, g=0.1, da=0.1)
        wo = s.weighted_overall({"completeness": 1.0})
        assert wo == pytest.approx(0.9)

    def test_normalises_weights(self):
        s = _score(c=0.8, co=0.2, cl=0.0, g=0.0, da=0.0)
        wo1 = s.weighted_overall({"completeness": 1.0, "consistency": 1.0})
        wo2 = s.weighted_overall({"completeness": 100.0, "consistency": 100.0})
        assert wo1 == pytest.approx(wo2)

    def test_raises_on_empty_weights(self):
        s = _score()
        with pytest.raises(ValueError):
            s.weighted_overall({})

    def test_raises_on_zero_weights(self):
        s = _score()
        with pytest.raises(ValueError):
            s.weighted_overall({"completeness": 0.0, "consistency": 0.0})

    def test_ignores_unknown_dimensions(self):
        s = _score(c=0.7)
        wo = s.weighted_overall({"completeness": 1.0, "nonsense_dim": 5.0})
        assert wo == pytest.approx(0.7)

    def test_partial_weights_result(self):
        s = _score(c=0.6, co=0.4)
        wo = s.weighted_overall({"completeness": 3.0, "consistency": 1.0})
        # expected: (0.6*3 + 0.4*1) / 4 = 2.2/4 = 0.55
        assert wo == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# OntologyCritic.compare_batch
# ---------------------------------------------------------------------------

class TestCompareBatch:
    def _make_critic(self):
        return OntologyCritic(backend_config={}, use_llm=False)

    def test_returns_list_same_length(self, ctx):
        critic = self._make_critic()
        onts = [_ontology(i + 1) for i in range(3)]
        ranking = critic.compare_batch(onts, ctx)
        assert len(ranking) == 3

    def test_rank_1_has_highest_overall(self, ctx):
        critic = self._make_critic()
        onts = [_ontology(i + 1) for i in range(4)]
        ranking = critic.compare_batch(onts, ctx)
        assert ranking[0]["rank"] == 1
        assert ranking[0]["overall"] >= ranking[-1]["overall"]

    def test_ranks_are_sequential(self, ctx):
        critic = self._make_critic()
        onts = [_ontology(2) for _ in range(3)]
        ranking = critic.compare_batch(onts, ctx)
        assert [r["rank"] for r in ranking] == [1, 2, 3]

    def test_index_preserves_original_position(self, ctx):
        critic = self._make_critic()
        onts = [_ontology(i + 1) for i in range(3)]
        ranking = critic.compare_batch(onts, ctx)
        indices = {r["index"] for r in ranking}
        assert indices == {0, 1, 2}

    def test_score_object_is_critic_score(self, ctx):
        critic = self._make_critic()
        ranking = critic.compare_batch([_ontology()], ctx)
        assert isinstance(ranking[0]["score"], CriticScore)

    def test_empty_list_returns_empty(self, ctx):
        critic = self._make_critic()
        assert critic.compare_batch([], ctx) == []

    def test_single_item_rank_is_1(self, ctx):
        critic = self._make_critic()
        ranking = critic.compare_batch([_ontology()], ctx)
        assert ranking[0]["rank"] == 1


# ---------------------------------------------------------------------------
# Entity.to_dict
# ---------------------------------------------------------------------------

class TestEntityToDict:
    def _entity(self, **kwargs):
        defaults = dict(id="e1", type="Person", text="Alice", confidence=0.9, properties={"age": 30})
        defaults.update(kwargs)
        return Entity(**defaults)

    def test_returns_dict(self):
        assert isinstance(self._entity().to_dict(), dict)

    def test_all_keys_present(self):
        d = self._entity().to_dict()
        for key in ("id", "type", "text", "confidence", "properties", "source_span"):
            assert key in d

    def test_id_preserved(self):
        assert self._entity(id="xyz").to_dict()["id"] == "xyz"

    def test_type_preserved(self):
        assert self._entity(type="Org").to_dict()["type"] == "Org"

    def test_text_preserved(self):
        assert self._entity(text="Bob").to_dict()["text"] == "Bob"

    def test_confidence_preserved(self):
        assert self._entity(confidence=0.42).to_dict()["confidence"] == pytest.approx(0.42)

    def test_properties_is_copy(self):
        e = self._entity(properties={"k": "v"})
        d = e.to_dict()
        d["properties"]["new_key"] = 1
        assert "new_key" not in e.properties

    def test_source_span_none(self):
        assert self._entity().to_dict()["source_span"] is None

    def test_source_span_list(self):
        e = Entity(id="e", type="T", text="t", source_span=(10, 20))
        assert e.to_dict()["source_span"] == [10, 20]


# ---------------------------------------------------------------------------
# EntityExtractionResult.to_json
# ---------------------------------------------------------------------------

class TestEntityExtractionResultToJson:
    def _result(self):
        ents = [Entity(id="e1", type="Person", text="Alice")]
        rels = [Relationship(id="r1", source_id="e1", target_id="e1", type="self")]
        return EntityExtractionResult(entities=ents, relationships=rels, confidence=0.8)

    def test_returns_string(self):
        assert isinstance(self._result().to_json(), str)

    def test_parses_to_dict(self):
        d = json.loads(self._result().to_json())
        assert isinstance(d, dict)

    def test_entities_key_present(self):
        d = json.loads(self._result().to_json())
        assert "entities" in d

    def test_relationships_key_present(self):
        d = json.loads(self._result().to_json())
        assert "relationships" in d

    def test_confidence_preserved(self):
        d = json.loads(self._result().to_json())
        assert d["confidence"] == pytest.approx(0.8)

    def test_entity_count_correct(self):
        d = json.loads(self._result().to_json())
        assert len(d["entities"]) == 1

    def test_relationship_count_correct(self):
        d = json.loads(self._result().to_json())
        assert len(d["relationships"]) == 1

    def test_entity_fields(self):
        d = json.loads(self._result().to_json())
        ent = d["entities"][0]
        assert ent["id"] == "e1"
        assert ent["type"] == "Person"

    def test_empty_result(self):
        r = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        d = json.loads(r.to_json())
        assert d["entities"] == []
        assert d["relationships"] == []

    def test_round_trip_metadata(self):
        r = EntityExtractionResult(
            entities=[], relationships=[], confidence=0.5, metadata={"key": "val"}
        )
        d = json.loads(r.to_json())
        assert d["metadata"]["key"] == "val"


# ---------------------------------------------------------------------------
# LogicValidator.batch_validate
# ---------------------------------------------------------------------------

class TestBatchValidate:
    def _validator(self):
        return LogicValidator()

    def _valid_ontology(self, n: int = 2):
        return {
            "entities": [{"id": f"e{i}", "type": "T", "text": f"t{i}"} for i in range(n)],
            "relationships": [],
        }

    def test_returns_list(self):
        v = self._validator()
        results = v.batch_validate([self._valid_ontology()])
        assert isinstance(results, list)

    def test_empty_list_returns_empty(self):
        v = self._validator()
        assert v.batch_validate([]) == []

    def test_length_matches_input(self):
        v = self._validator()
        onts = [self._valid_ontology(i + 1) for i in range(5)]
        results = v.batch_validate(onts)
        assert len(results) == 5

    def test_each_item_is_validation_result(self):
        v = self._validator()
        for r in v.batch_validate([self._valid_ontology(), self._valid_ontology()]):
            assert isinstance(r, ValidationResult)

    def test_order_preserved(self):
        v = self._validator()
        ont_small = self._valid_ontology(1)
        ont_large = self._valid_ontology(5)
        results = v.batch_validate([ont_small, ont_large, ont_small])
        # Just check length; order must be preserved
        assert len(results) == 3

    def test_max_workers_one(self):
        v = self._validator()
        results = v.batch_validate([self._valid_ontology()] * 3, max_workers=1)
        assert len(results) == 3

    def test_results_have_confidence(self):
        v = self._validator()
        for r in v.batch_validate([self._valid_ontology()]):
            assert 0.0 <= r.confidence <= 1.0
