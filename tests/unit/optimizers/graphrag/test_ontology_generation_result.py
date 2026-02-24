"""Tests for OntologyGenerationResult dataclass (batch 38).

Covers: from_ontology(), field computations, edge cases,
generate_ontology_rich() integration, and public import.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerationResult,
    OntologyGenerator,
)


@pytest.fixture
def ontology_builder(ontology_dict_factory):
    def _build(
        n_entities: int = 3,
        n_rels: int = 2,
        entity_types: list | None = None,
        confidence: float = 0.8,
    ) -> dict:
        types = entity_types or ["Person", "Org", "Concept"]
        ontology = ontology_dict_factory(
            entity_count=n_entities,
            relationship_count=0,
            entity_types=types,
        )
        ontology["entities"] = [
            {
                "id": f"e{i}",
                "type": types[i % len(types)],
                "text": f"Item{i}",
                "confidence": confidence,
            }
            for i in range(n_entities)
        ]
        ontology["relationships"] = [
            {
                "id": f"r{i}",
                "source_id": f"e{i}",
                "target_id": f"e{(i + 1) % n_entities}",
                "type": "related",
                "confidence": 0.7,
            }
            for i in range(n_rels)
        ]
        return ontology

    return _build


class TestOntologyGenerationResultFromOntology:
    def test_entity_count_correct(self, ontology_builder):
        result = OntologyGenerationResult.from_ontology(ontology_builder(n_entities=5))
        assert result.entity_count == 5

    def test_relationship_count_correct(self, ontology_builder):
        result = OntologyGenerationResult.from_ontology(
            ontology_builder(n_entities=4, n_rels=3)
        )
        assert result.relationship_count == 3

    def test_entity_type_diversity_correct(self):
        # 4 entities with 2 distinct types
        ontology = {
            "entities": [
                {"id": "e0", "type": "Person", "confidence": 0.8},
                {"id": "e1", "type": "Person", "confidence": 0.8},
                {"id": "e2", "type": "Org", "confidence": 0.8},
                {"id": "e3", "type": "Org", "confidence": 0.8},
            ],
            "relationships": [],
        }
        result = OntologyGenerationResult.from_ontology(ontology)
        assert result.entity_type_diversity == 2

    def test_mean_entity_confidence_correct(self):
        ontology = {
            "entities": [
                {"id": "e0", "type": "A", "confidence": 0.8},
                {"id": "e1", "type": "B", "confidence": 0.6},
            ],
            "relationships": [],
        }
        result = OntologyGenerationResult.from_ontology(ontology)
        assert abs(result.mean_entity_confidence - 0.7) < 1e-9

    def test_mean_rel_confidence_correct(self):
        ontology = {
            "entities": [{"id": "e0", "type": "A", "confidence": 1.0}],
            "relationships": [
                {"id": "r0", "type": "rel", "confidence": 0.4},
                {"id": "r1", "type": "rel", "confidence": 0.8},
            ],
        }
        result = OntologyGenerationResult.from_ontology(ontology)
        assert abs(result.mean_relationship_confidence - 0.6) < 1e-9

    def test_empty_entities_zero_counts(self):
        result = OntologyGenerationResult.from_ontology({"entities": [], "relationships": []})
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.entity_type_diversity == 0
        assert result.mean_entity_confidence == 0.0
        assert result.mean_relationship_confidence == 0.0

    def test_ontology_stored(self, ontology_builder):
        ontology = ontology_builder(n_entities=2)
        result = OntologyGenerationResult.from_ontology(ontology)
        assert result.ontology is ontology

    def test_extraction_strategy_stored(self, ontology_builder):
        result = OntologyGenerationResult.from_ontology(
            ontology_builder(), extraction_strategy="rule_based"
        )
        assert result.extraction_strategy == "rule_based"

    def test_domain_stored(self, ontology_builder):
        result = OntologyGenerationResult.from_ontology(ontology_builder(), domain="legal")
        assert result.domain == "legal"

    def test_metadata_stored(self, ontology_builder):
        result = OntologyGenerationResult.from_ontology(
            ontology_builder(), metadata={"backend": "openai"}
        )
        assert result.metadata["backend"] == "openai"


class TestGenerateOntologyRich:
    @pytest.fixture
    def ctx(self):
        return OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )

    def test_returns_generation_result(self, ctx):
        gen = OntologyGenerator(use_ipfs_accelerate=False)
        result = gen.generate_ontology_rich("Alice knows Bob. Bob works at Acme Corp.", ctx)
        assert isinstance(result, OntologyGenerationResult)

    def test_ontology_is_dict(self, ctx):
        gen = OntologyGenerator(use_ipfs_accelerate=False)
        result = gen.generate_ontology_rich("Alice knows Bob.", ctx)
        assert isinstance(result.ontology, dict)
        assert "entities" in result.ontology

    def test_entity_count_matches_ontology(self, ctx):
        gen = OntologyGenerator(use_ipfs_accelerate=False)
        result = gen.generate_ontology_rich("Alice and Bob are people.", ctx)
        assert result.entity_count == len(result.ontology.get("entities", []))

    def test_strategy_set(self, ctx):
        gen = OntologyGenerator(use_ipfs_accelerate=False)
        result = gen.generate_ontology_rich("Alice.", ctx)
        assert result.extraction_strategy == "rule_based"

    def test_domain_set(self, ctx):
        gen = OntologyGenerator(use_ipfs_accelerate=False)
        result = gen.generate_ontology_rich("Alice.", ctx)
        assert result.domain == "general"


class TestPublicImport:
    def test_importable_from_graphrag(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerationResult  # noqa: F401
        assert OntologyGenerationResult is not None
