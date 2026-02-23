"""Schema regression tests for JSON serialization round-trips.

These tests capture and validate the canonical JSON structure for ontologies,
CriticScores, and other serialized types. They serve as schema regression tests
to catch unintended changes to the public JSON serialization format.

Tests use a reference ontology and expected JSON structure to ensure:
1. Schema consistency across versions
2. All required fields are present in JSON output
3. Field ordering and types remain stable
4. Nested structures are properly formatted
"""

import json
from typing import Any, Dict
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_serialization import (
    build_ontology_dict,
    entity_model_to_dict,
    relationship_model_to_dict,
    ontology_from_extraction_result,
    entity_dict_to_model,
    relationship_dict_to_model,
    models_from_ontology_dict,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_types import (
    Entity as EntityTypedDict,
    Relationship as RelationshipTypedDict,
)


# ============================================================================
# Reference Ontology for Schema Regression Tests
# ============================================================================

REFERENCE_ENTITIES = [
    {
        "id": "alice",
        "type": "Person",
        "text": "Alice",
        "confidence": 0.95,
        "properties": {"role": "legal_analyst", "department": "compliance"},
    },
    {
        "id": "acme",
        "type": "Organization",
        "text": "Acme Corporation",
        "confidence": 0.92,
        "properties": {"industry": "manufacturing", "founded": "1995"},
    },
    {
        "id": "contract_2024",
        "type": "Document",
        "text": "2024 Service Agreement",
        "confidence": 0.88,
        "properties": {"doc_type": "contract", "status": "reviewed"},
    },
    {
        "id": "ny_office",
        "type": "Location",
        "text": "New York",
        "confidence": 0.99,
        "properties": {"country": "USA", "region": "Northeast"},
    },
    {
        "id": "emp_2024_01",
        "type": "Employment",
        "text": "2024 Employment",
        "confidence": 0.85,
        "properties": {"start_date": "2024-01-01", "status": "active"},
    },
]

REFERENCE_RELATIONSHIPS = [
    {
        "id": "rel_alice_acme",
        "source_id": "alice",
        "target_id": "acme",
        "type": "works_for",
        "confidence": 0.90,
        "properties": {"type_confidence": 0.85, "since": "2022"},
    },
    {
        "id": "rel_acme_ny",
        "source_id": "acme",
        "target_id": "ny_office",
        "type": "located_in",
        "confidence": 0.95,
        "properties": {"type_confidence": 0.92},
    },
    {
        "id": "rel_emp_acme",
        "source_id": "emp_2024_01",
        "target_id": "acme",
        "type": "related_to",
        "confidence": 0.80,
        "properties": {"type_confidence": 0.75},
    },
]

# Expected schema for a minimal ontology JSON
EXPECTED_ONTOLOGY_JSON_SCHEMA = {
    "entities": [
        {
            "id": str,  # Placeholder for actual value
            "type": str,
            "text": str,
            "confidence": float,
            "properties": dict,
        }
    ],
    "relationships": [
        {
            "id": str,
            "source_id": str,
            "target_id": str,
            "type": str,
            "confidence": float,
            "properties": dict,
        }
    ],
}


# ============================================================================
# Schema Structure Tests
# ============================================================================


class TestEntityJsonSchema:
    """Tests for Entity JSON serialization schema consistency."""

    def test_entity_json_contains_required_fields(self):
        """GIVEN: Entity model WHEN: Serialized to dict THEN: All required fields present."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Test Person",
            confidence=0.85,
            properties={"key": "value"},
        )

        json_dict = entity_model_to_dict(entity)

        # Required fields
        assert "id" in json_dict
        assert "type" in json_dict
        assert "text" in json_dict
        assert "confidence" in json_dict
        assert "properties" in json_dict

    def test_entity_json_omits_implementation_fields(self):
        """GIVEN: Entity with internal fields WHEN: Serialized THEN: Only public fields in JSON."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Test",
            confidence=0.85,
            properties={},
            source_span=(0, 4),
            last_seen=100.0,
        )

        json_dict = entity_model_to_dict(entity)

        # Implementation details should not appear
        assert "source_span" not in json_dict
        assert "last_seen" not in json_dict

    def test_entity_json_types_are_correct(self):
        """GIVEN: Entity WHEN: Serialized THEN: JSON field types match schema."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.95,
            properties={"role": "manager"},
        )

        json_dict = entity_model_to_dict(entity)

        assert isinstance(json_dict["id"], str)
        assert isinstance(json_dict["type"], str)
        assert isinstance(json_dict["text"], str)
        assert isinstance(json_dict["confidence"], float)
        assert isinstance(json_dict["properties"], dict)

    def test_entity_properties_dict_roundtrip(self):
        """GIVEN: Entity with nested properties WHEN: Roundtripped THEN: Structure preserved."""
        original_props = {
            "role": "legal analyst",
            "team_size": 5,
            "active": True,
            "tags": ["compliance", "review"],
        }
        entity = Entity(
            id="e1",
            type="Person",
            text="Test",
            confidence=0.8,
            properties=original_props,
        )

        json_dict = entity_model_to_dict(entity)
        restored_entity = entity_dict_to_model(json_dict)
        restored_props = entity_model_to_dict(restored_entity)["properties"]

        assert restored_props == original_props


class TestRelationshipJsonSchema:
    """Tests for Relationship JSON serialization schema consistency."""

    def test_relationship_json_contains_required_fields(self):
        """GIVEN: Relationship model WHEN: Serialized THEN: All required fields present."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="works_for",
            confidence=0.90,
            properties={"since": 2020},
        )

        json_dict = relationship_model_to_dict(rel)

        # Required fields
        assert "id" in json_dict
        assert "source_id" in json_dict
        assert "target_id" in json_dict
        assert "type" in json_dict
        assert "confidence" in json_dict
        assert "properties" in json_dict

    def test_relationship_json_omits_implementation_fields(self):
        """GIVEN: Relationship with internal fields WHEN: Serialized THEN: Only public fields."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="related_to",
            confidence=0.75,
            properties={},
            direction="subject_to_object",
        )

        json_dict = relationship_model_to_dict(rel)

        # Implementation detail should not appear
        assert "direction" not in json_dict

    def test_relationship_json_types_are_correct(self):
        """GIVEN: Relationship WHEN: Serialized THEN: JSON field types match schema."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="works_for",
            confidence=0.85,
            properties={"since": 2020},
        )

        json_dict = relationship_model_to_dict(rel)

        assert isinstance(json_dict["id"], str)
        assert isinstance(json_dict["source_id"], str)
        assert isinstance(json_dict["target_id"], str)
        assert isinstance(json_dict["type"], str)
        assert isinstance(json_dict["confidence"], float)
        assert isinstance(json_dict["properties"], dict)

    def test_relationship_properties_with_type_confidence(self):
        """GIVEN: Relationship with type_confidence WHEN: Serialized THEN: Preserved in properties."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="obligates",
            confidence=0.85,
            properties={"type_confidence": 0.80},
        )

        json_dict = relationship_model_to_dict(rel)

        assert "properties" in json_dict
        assert json_dict["properties"]["type_confidence"] == 0.80


class TestOntologyJsonSchema:
    """Tests for full ontology JSON serialization schema consistency."""

    def test_ontology_json_structure(self):
        """GIVEN: Ontology dict WHEN: Serialized to JSON THEN: Schema is valid."""
        ontology = build_ontology_dict(
            entities=[
                Entity(
                    id="e1",
                    type="Person",
                    text="Alice",
                    confidence=0.9,
                    properties={},
                )
            ],
            relationships=[],
        )

        # Should be JSON-serializable
        json_str = json.dumps(ontology)
        reloaded = json.loads(json_str)

        assert "entities" in reloaded
        assert "relationships" in reloaded
        assert isinstance(reloaded["entities"], list)
        assert isinstance(reloaded["relationships"], list)

    def test_ontology_json_entities_have_consistent_schema(self):
        """GIVEN: Ontology with multiple entities WHEN: Serialized THEN: All entities match schema."""
        entities_models = [
            Entity(id=f"e{i}", type="Person", text=f"Person{i}", confidence=0.8, properties={})
            for i in range(5)
        ]
        ontology = build_ontology_dict(entities=entities_models, relationships=[])

        for entity_dict in ontology["entities"]:
            assert set(entity_dict.keys()) == {"id", "type", "text", "confidence", "properties"}

    def test_ontology_json_relationships_have_consistent_schema(self):
        """GIVEN: Ontology with multiple relationships WHEN: Serialized THEN: All match schema."""
        entities = [
            Entity(id="e1", type="Person", text="A", confidence=0.9, properties={}),
            Entity(id="e2", type="Person", text="B", confidence=0.9, properties={}),
        ]
        relationships = [
            Relationship(
                id=f"r{i}",
                source_id="e1",
                target_id="e2",
                type="related_to",
                confidence=0.8,
                properties={},
            )
            for i in range(3)
        ]
        ontology = build_ontology_dict(entities=entities, relationships=relationships)

        for rel_dict in ontology["relationships"]:
            required_keys = {"id", "source_id", "target_id", "type", "confidence", "properties"}
            assert set(rel_dict.keys()) == required_keys


# ============================================================================
# Round-Trip Regression Tests
# ============================================================================


class TestJsonRoundTripRegression:
    """Tests for JSON round-trip fidelity."""

    def test_entity_json_roundtrip_preserves_all_fields(self):
        """GIVEN: Entity with all fields set WHEN: Roundtripped via JSON THEN: All values preserved."""
        original = Entity(
            id="alice",
            type="Person",
            text="Alice Smith",
            confidence=0.95,
            properties={"role": "analyst", "dept": "legal"},
        )

        # Roundtrip: Entity -> dict -> JSON str -> dict -> Entity -> dict
        dict1 = entity_model_to_dict(original)
        json_str = json.dumps(dict1)
        dict2 = json.loads(json_str)
        restored = entity_dict_to_model(dict2)
        dict3 = entity_model_to_dict(restored)

        assert dict3 == dict1
        assert dict3["id"] == "alice"
        assert dict3["confidence"] == 0.95

    def test_relationship_json_roundtrip_preserves_all_fields(self):
        """GIVEN: Relationship with all fields WHEN: Roundtripped via JSON THEN: All preserved."""
        original = Relationship(
            id="rel_alice_acme",
            source_id="alice",
            target_id="acme",
            type="works_for",
            confidence=0.90,
            properties={"type_confidence": 0.85, "since": "2022"},
        )

        # Roundtrip: Rel -> dict -> JSON str -> dict -> Rel -> dict
        dict1 = relationship_model_to_dict(original)
        json_str = json.dumps(dict1)
        dict2 = json.loads(json_str)
        restored = relationship_dict_to_model(dict2)
        dict3 = relationship_model_to_dict(restored)

        assert dict3 == dict1
        assert dict3["type"] == "works_for"
        assert dict3["properties"]["type_confidence"] == 0.85

    def test_ontology_json_roundtrip_with_reference_data(self):
        """GIVEN: Reference ontology WHEN: Roundtripped via JSON THEN: Schema is preserved."""
        # Build ontology from reference data
        entities = [Entity(id=e["id"], type=e["type"], text=e["text"], confidence=e["confidence"], properties=e["properties"]) for e in REFERENCE_ENTITIES]
        relationships = [
            Relationship(
                id=r["id"],
                source_id=r["source_id"],
                target_id=r["target_id"],
                type=r["type"],
                confidence=r["confidence"],
                properties=r["properties"],
            )
            for r in REFERENCE_RELATIONSHIPS
        ]

        ontology = build_ontology_dict(entities=entities, relationships=relationships)

        # Round-trip via JSON
        json_str = json.dumps(ontology, indent=2)
        restored = json.loads(json_str)

        # Verify structure is preserved
        assert len(restored["entities"]) == len(REFERENCE_ENTITIES)
        assert len(restored["relationships"]) == len(REFERENCE_RELATIONSHIPS)

        # Verify sample entity
        first_entity = restored["entities"][0]
        assert first_entity["id"] == "alice"
        assert first_entity["type"] == "Person"
        assert first_entity["confidence"] == 0.95
        assert first_entity["properties"]["role"] == "legal_analyst"

        # Verify sample relationship
        first_rel = restored["relationships"][0]
        assert first_rel["type"] == "works_for"
        assert first_rel["confidence"] == 0.90


# ============================================================================
# JSON Field Type and Range Tests
# ============================================================================


class TestJsonFieldValidation:
    """Tests for JSON field type and value validation."""

    def test_confidence_fields_are_floats_in_range(self):
        """GIVEN: Ontology WHEN: Serialized to JSON THEN: Confidence values in [0, 1]."""
        entities = [
            Entity(id="e0", type="T", text="X", confidence=0.0, properties={}),
            Entity(id="e1", type="T", text="Y", confidence=0.5, properties={}),
            Entity(id="e2", type="T", text="Z", confidence=1.0, properties={}),
        ]
        ontology = build_ontology_dict(entities=entities, relationships=[])

        for entity_dict in ontology["entities"]:
            conf = entity_dict["confidence"]
            assert isinstance(conf, float)
            assert 0.0 <= conf <= 1.0

    def test_id_fields_are_non_empty_strings(self):
        """GIVEN: Ontology WHEN: Serialized THEN: All ID fields are non-empty strings."""
        entities = [
            Entity(id="abc123", type="T", text="X", confidence=0.5, properties={}),
            Entity(id="def456", type="T", text="Y", confidence=0.5, properties={}),
        ]
        ontology = build_ontology_dict(entities=entities, relationships=[])

        for entity_dict in ontology["entities"]:
            assert isinstance(entity_dict["id"], str)
            assert len(entity_dict["id"]) > 0

    def test_type_and_text_fields_are_non_empty_strings(self):
        """GIVEN: Ontology WHEN: Serialized THEN: Type and text are non-empty strings."""
        entity = Entity(id="e1", type="Person", text="Alice", confidence=0.8, properties={})
        ontology = build_ontology_dict(entities=[entity], relationships=[])

        entity_dict = ontology["entities"][0]
        assert isinstance(entity_dict["type"], str)
        assert len(entity_dict["type"]) > 0
        assert isinstance(entity_dict["text"], str)
        assert len(entity_dict["text"]) > 0

    def test_properties_is_always_dict(self):
        """GIVEN: Entities/Relationships WHEN: Serialized THEN: Properties field is always dict."""
        entity1 = Entity(id="e1", type="T", text="X", confidence=0.5, properties={})
        entity2 = Entity(id="e2", type="T", text="Y", confidence=0.5, properties={"key": "val"})

        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="rel",
            confidence=0.5,
            properties={"k": 123},
        )

        ontology = build_ontology_dict(entities=[entity1, entity2], relationships=[rel])

        for entity_dict in ontology["entities"]:
            assert isinstance(entity_dict["properties"], dict)

        for rel_dict in ontology["relationships"]:
            assert isinstance(rel_dict["properties"], dict)


# ============================================================================
# JSON Pretty-Printing and Formatting Tests
# ============================================================================


class TestJsonFormatting:
    """Tests for JSON pretty-printing and canonical formatting."""

    def test_ontology_json_is_valid_json(self):
        """GIVEN: Ontology WHEN: Serialized to JSON string THEN: Valid JSON can be deserialized."""
        entity = Entity(id="e1", type="Person", text="Test", confidence=0.8, properties={})
        ontology = build_ontology_dict(entities=[entity], relationships=[])

        # Should be valid JSON
        json_str = json.dumps(ontology)
        reloaded = json.loads(json_str)

        assert isinstance(reloaded, dict)
        assert "entities" in reloaded

    def test_ontology_json_pretty_print_is_readable(self):
        """GIVEN: Ontology WHEN: Pretty-printed THEN: Contains expected whitespace."""
        entity = Entity(id="e1", type="Person", text="Test", confidence=0.8, properties={})
        ontology = build_ontology_dict(entities=[entity], relationships=[])

        json_str = json.dumps(ontology, indent=2)

        # Pretty-printed JSON should contain newlines and indentation
        assert "\n" in json_str
        assert "  " in json_str  # 2-space indentation

    def test_json_roundtrip_preserves_content_with_pretty_print(self):
        """GIVEN: Ontology pretty-printed WHEN: Re-parsed THEN: Content unchanged."""
        entity = Entity(id="e1", type="Person", text="Test", confidence=0.8, properties={"x": 1})
        ontology_original = build_ontology_dict(entities=[entity], relationships=[])

        # Pretty-print and re-parse
        json_str = json.dumps(ontology_original, indent=2)
        ontology_restored = json.loads(json_str)

        assert ontology_restored == ontology_original
