"""Batch-69 feature tests.

Covers:
- ExtractionConfig.to_toml() / from_toml()
- EntityExtractionResult.summary()
- OntologyGenerator.anonymize_entities()
- OntologyPipeline.with_domain()
- OntologyCritic.emit_dimension_histogram()
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**kw) -> ExtractionConfig:
    return ExtractionConfig(**kw)


def _score(v: float) -> CriticScore:
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


def _entity(eid="e1", text="Alice", etype="Person") -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=0.9)


def _result(*entities, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=list(rels or []), confidence=0.8
    )


def _gen() -> OntologyGenerator:
    return OntologyGenerator()


def _critic() -> OntologyCritic:
    return OntologyCritic(use_llm=False)


# ---------------------------------------------------------------------------
# ExtractionConfig.to_toml / from_toml
# ---------------------------------------------------------------------------

class TestExtractionConfigToml:
    def test_to_toml_returns_string(self):
        assert isinstance(_cfg().to_toml(), str)

    def test_contains_section_header(self):
        assert "[extraction_config]" in _cfg().to_toml()

    def test_round_trip_confidence_threshold(self):
        cfg = _cfg(confidence_threshold=0.75)
        restored = ExtractionConfig.from_toml(cfg.to_toml())
        assert abs(restored.confidence_threshold - 0.75) < 1e-9

    def test_round_trip_max_entities(self):
        cfg = _cfg(max_entities=42)
        restored = ExtractionConfig.from_toml(cfg.to_toml())
        assert restored.max_entities == 42

    def test_round_trip_include_properties(self):
        cfg = _cfg(include_properties=False)
        restored = ExtractionConfig.from_toml(cfg.to_toml())
        assert restored.include_properties is False

    def test_round_trip_stopwords(self):
        cfg = _cfg(stopwords=["the", "a"])
        toml_str = cfg.to_toml()
        restored = ExtractionConfig.from_toml(toml_str)
        assert set(restored.stopwords) == {"the", "a"}

    def test_default_config_round_trip(self):
        cfg = _cfg()
        restored = ExtractionConfig.from_toml(cfg.to_toml())
        assert abs(restored.confidence_threshold - cfg.confidence_threshold) < 1e-9


# ---------------------------------------------------------------------------
# EntityExtractionResult.summary
# ---------------------------------------------------------------------------

class TestEntityExtractionResultSummary:
    def test_returns_string(self):
        r = _result(_entity())
        assert isinstance(r.summary(), str)

    def test_contains_entity_count(self):
        r = _result(_entity("e1"), _entity("e2", "Bob"))
        assert "2 entities" in r.summary()

    def test_contains_relationship_count(self):
        e1 = _entity("e1", "Alice")
        e2 = _entity("e2", "Bob")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        r = _result(e1, e2, rels=[rel])
        assert "1 relationships" in r.summary()

    def test_contains_confidence(self):
        r = _result(_entity())
        assert "confidence=" in r.summary()

    def test_empty_result(self):
        r = _result()
        summary = r.summary()
        assert "0 entities" in summary

    def test_type_count_in_summary(self):
        r = _result(_entity("e1", "Alice", "Person"), _entity("e2", "ACME", "Org"))
        assert "2 types" in r.summary()


# ---------------------------------------------------------------------------
# OntologyGenerator.anonymize_entities
# ---------------------------------------------------------------------------

class TestAnonymizeEntities:
    def test_returns_new_result(self):
        r = _result(_entity())
        anon = _gen().anonymize_entities(r)
        assert anon is not r

    def test_all_texts_replaced(self):
        r = _result(_entity("e1", "Alice"), _entity("e2", "Bob"))
        anon = _gen().anonymize_entities(r)
        assert all(e.text == "[REDACTED]" for e in anon.entities)

    def test_custom_replacement(self):
        r = _result(_entity("e1", "Alice"))
        anon = _gen().anonymize_entities(r, replacement="***")
        assert anon.entities[0].text == "***"

    def test_entity_ids_preserved(self):
        r = _result(_entity("e_unique"))
        anon = _gen().anonymize_entities(r)
        assert anon.entities[0].id == "e_unique"

    def test_entity_types_preserved(self):
        r = _result(_entity(etype="Organization"))
        anon = _gen().anonymize_entities(r)
        assert anon.entities[0].type == "Organization"

    def test_relationships_preserved(self):
        e1, e2 = _entity("e1"), _entity("e2", "Bob")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        r = _result(e1, e2, rels=[rel])
        anon = _gen().anonymize_entities(r)
        assert len(anon.relationships) == 1

    def test_empty_result(self):
        anon = _gen().anonymize_entities(_result())
        assert anon.entities == []


# ---------------------------------------------------------------------------
# OntologyPipeline.with_domain
# ---------------------------------------------------------------------------

class TestPipelineWithDomain:
    def test_returns_pipeline(self):
        p = OntologyPipeline(domain="general")
        p2 = p.with_domain("legal")
        assert isinstance(p2, OntologyPipeline)

    def test_new_domain_applied(self):
        p = OntologyPipeline(domain="general")
        p2 = p.with_domain("medical")
        assert p2.domain == "medical"

    def test_original_unchanged(self):
        p = OntologyPipeline(domain="general")
        p.with_domain("legal")
        assert p.domain == "general"

    def test_max_rounds_inherited(self):
        p = OntologyPipeline(domain="x", max_rounds=7)
        p2 = p.with_domain("y")
        assert p2._mediator.max_rounds == 7

    def test_chaining(self):
        p = OntologyPipeline(domain="a").with_domain("b").with_domain("c")
        assert p.domain == "c"


# ---------------------------------------------------------------------------
# OntologyCritic.emit_dimension_histogram
# ---------------------------------------------------------------------------

class TestEmitDimensionHistogram:
    def test_returns_dict(self):
        result = _critic().emit_dimension_histogram([_score(0.5)], bins=5)
        assert isinstance(result, dict)

    def test_all_dims_present(self):
        result = _critic().emit_dimension_histogram([_score(0.5)])
        expected_keys = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert set(result.keys()) == expected_keys

    def test_correct_bin_count(self):
        result = _critic().emit_dimension_histogram([_score(0.5)], bins=4)
        for counts in result.values():
            assert len(counts) == 4

    def test_counts_sum_to_n(self):
        scores = [_score(v) for v in [0.1, 0.3, 0.6, 0.9]]
        result = _critic().emit_dimension_histogram(scores, bins=5)
        for dim, counts in result.items():
            assert sum(counts) == 4

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _critic().emit_dimension_histogram([])

    def test_invalid_bins_raises(self):
        with pytest.raises(ValueError):
            _critic().emit_dimension_histogram([_score(0.5)], bins=0)

    def test_single_bin(self):
        result = _critic().emit_dimension_histogram([_score(0.5)], bins=1)
        for counts in result.values():
            assert counts == [1]
