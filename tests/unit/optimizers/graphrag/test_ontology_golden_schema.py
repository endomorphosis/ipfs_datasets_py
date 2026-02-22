"""
Golden-file tests for GraphRAG ontology dict schema.

Validates that ontology dictionaries conform to expected schema,
with proper entity/relationship/metadata structure and invariants.
"""

import json
import pytest
from pathlib import Path
from typing import Any, Dict, List


# Path to golden fixture
GOLDEN_FIXTURE = Path(__file__).parent / "fixtures" / "ontology_golden_schema.json"


@pytest.fixture
def golden_ontology() -> Dict[str, Any]:
    """Load the golden ontology fixture."""
    with open(GOLDEN_FIXTURE) as f:
        return json.load(f)


class TestOntologySchemaStructure:
    """Test ontology dict has expected top-level structure."""

    def test_ontology_has_required_top_level_keys(self, golden_ontology: Dict[str, Any]):
        """Ontology dict must have 'entities', 'relationships', 'metadata'."""
        required_keys = {"entities", "relationships", "metadata"}
        assert required_keys.issubset(golden_ontology.keys()), \
            f"Missing keys: {required_keys - set(golden_ontology.keys())}"

    def test_entities_is_list(self, golden_ontology: Dict[str, Any]):
        """Entities must be a list."""
        assert isinstance(golden_ontology["entities"], list)
        assert len(golden_ontology["entities"]) > 0, "Entities list should not be empty"

    def test_relationships_is_list(self, golden_ontology: Dict[str, Any]):
        """Relationships must be a list."""
        assert isinstance(golden_ontology["relationships"], list)

    def test_metadata_is_dict(self, golden_ontology: Dict[str, Any]):
        """Metadata must be a dict."""
        assert isinstance(golden_ontology["metadata"], dict)


class TestEntityInvariants:
    """Test entity objects conform to schema."""

    def test_each_entity_has_required_fields(self, golden_ontology: Dict[str, Any]):
        """Each entity must have id, type, text, confidence."""
        required_fields = {"id", "type", "text", "confidence"}
        for entity in golden_ontology["entities"]:
            assert required_fields.issubset(entity.keys()), \
                f"Entity {entity.get('id')} missing fields: {required_fields - set(entity.keys())}"

    def test_entity_ids_are_unique_strings(self, golden_ontology: Dict[str, Any]):
        """Entity IDs must be unique, non-empty strings."""
        ids = []
        for entity in golden_ontology["entities"]:
            entity_id = entity["id"]
            assert isinstance(entity_id, str) and entity_id, "Entity ID must be non-empty string"
            assert entity_id not in ids, f"Duplicate entity ID: {entity_id}"
            ids.append(entity_id)

    def test_entity_type_is_string(self, golden_ontology: Dict[str, Any]):
        """Entity type must be a non-empty string."""
        for entity in golden_ontology["entities"]:
            assert isinstance(entity["type"], str) and entity["type"], \
                f"Entity {entity.get('id')} has invalid type"

    def test_entity_text_is_string(self, golden_ontology: Dict[str, Any]):
        """Entity text must be a non-empty string."""
        for entity in golden_ontology["entities"]:
            assert isinstance(entity["text"], str) and entity["text"], \
                f"Entity {entity.get('id')} has invalid text"

    def test_entity_confidence_in_range(self, golden_ontology: Dict[str, Any]):
        """Entity confidence must be between 0.0 and 1.0."""
        for entity in golden_ontology["entities"]:
            conf = entity["confidence"]
            assert isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0, \
                f"Entity {entity.get('id')} has confidence out of range: {conf}"

    def test_entity_properties_is_dict(self, golden_ontology: Dict[str, Any]):
        """Entity properties must be a dict (optional)."""
        for entity in golden_ontology["entities"]:
            if "properties" in entity:
                assert isinstance(entity["properties"], dict), \
                    f"Entity {entity.get('id')} properties must be dict"

    def test_entity_source_span_valid(self, golden_ontology: Dict[str, Any]):
        """Entity source_span must be null or [int, int] tuple."""
        for entity in golden_ontology["entities"]:
            if "source_span" in entity:
                span = entity["source_span"]
                if span is not None:
                    assert isinstance(span, list) and len(span) == 2 and \
                           all(isinstance(x, int) for x in span), \
                        f"Entity {entity.get('id')} has invalid source_span: {span}"


class TestRelationshipInvariants:
    """Test relationship objects conform to schema."""

    def test_each_relationship_has_required_fields(self, golden_ontology: Dict[str, Any]):
        """Each relationship must have id, source_id, target_id, type, confidence."""
        required_fields = {"id", "source_id", "target_id", "type", "confidence"}
        for rel in golden_ontology["relationships"]:
            assert required_fields.issubset(rel.keys()), \
                f"Relationship {rel.get('id')} missing fields: {required_fields - set(rel.keys())}"

    def test_relationship_ids_are_unique_strings(self, golden_ontology: Dict[str, Any]):
        """Relationship IDs must be unique, non-empty strings."""
        ids = []
        for rel in golden_ontology["relationships"]:
            rel_id = rel["id"]
            assert isinstance(rel_id, str) and rel_id, "Relationship ID must be non-empty string"
            assert rel_id not in ids, f"Duplicate relationship ID: {rel_id}"
            ids.append(rel_id)

    def test_relationship_endpoints_exist(self, golden_ontology: Dict[str, Any]):
        """Relationship endpoints (source_id, target_id) must reference existing entities."""
        entity_ids = {e["id"] for e in golden_ontology["entities"]}
        for rel in golden_ontology["relationships"]:
            source = rel["source_id"]
            target = rel["target_id"]
            assert source in entity_ids, \
                f"Relationship {rel['id']} references non-existent source: {source}"
            assert target in entity_ids, \
                f"Relationship {rel['id']} references non-existent target: {target}"

    def test_relationship_type_is_string(self, golden_ontology: Dict[str, Any]):
        """Relationship type must be a non-empty string."""
        for rel in golden_ontology["relationships"]:
            assert isinstance(rel["type"], str) and rel["type"], \
                f"Relationship {rel.get('id')} has invalid type"

    def test_relationship_confidence_in_range(self, golden_ontology: Dict[str, Any]):
        """Relationship confidence must be between 0.0 and 1.0."""
        for rel in golden_ontology["relationships"]:
            conf = rel["confidence"]
            assert isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0, \
                f"Relationship {rel.get('id')} has confidence out of range: {conf}"

    def test_relationship_properties_is_dict(self, golden_ontology: Dict[str, Any]):
        """Relationship properties must be a dict (optional)."""
        for rel in golden_ontology["relationships"]:
            if "properties" in rel:
                assert isinstance(rel["properties"], dict), \
                    f"Relationship {rel.get('id')} properties must be dict"


class TestOntologyGlobalInvariants:
    """Test invariants across the entire ontology."""

    def test_no_isolated_entities(self, golden_ontology: Dict[str, Any]):
        """Warn if entities have no relationships (may be intentional but worth flagging)."""
        entity_ids = {e["id"] for e in golden_ontology["entities"]}
        related_entity_ids = set()
        for rel in golden_ontology["relationships"]:
            related_entity_ids.add(rel["source_id"])
            related_entity_ids.add(rel["target_id"])
        
        isolated = entity_ids - related_entity_ids
        if isolated:
            # Don't fail; just note it (isolated entities are sometimes intentional)
            pytest.skip(f"Found {len(isolated)} isolated entities (no relationships)")

    def test_confidence_distribution_reasonable(self, golden_ontology: Dict[str, Any]):
        """Confidence scores should have a reasonable distribution."""
        all_confidences = []
        for entity in golden_ontology["entities"]:
            all_confidences.append(entity["confidence"])
        for rel in golden_ontology["relationships"]:
            all_confidences.append(rel["confidence"])
        
        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0
        assert avg_confidence >= 0.5, \
            f"Average confidence too low: {avg_confidence:.2f} (expected >= 0.5)"

    def test_metadata_has_extraction_info(self, golden_ontology: Dict[str, Any]):
        """Metadata should document source and extraction strategy."""
        metadata = golden_ontology["metadata"]
        assert "source" in metadata or "domain" in metadata, \
            "Metadata should have 'source' or 'domain' field"


class TestOntologySerializationRoundtrip:
    """Test ontology can be serialized and deserialized without loss."""

    def test_json_roundtrip(self, golden_ontology: Dict[str, Any]):
        """Ontology should survive JSON roundtrip without data loss."""
        json_str = json.dumps(golden_ontology, indent=2)
        restored = json.loads(json_str)
        
        # Deep equality check
        assert restored == golden_ontology, "Roundtrip changed ontology"

    def test_fixture_is_valid_json(self):
        """Golden fixture must be valid JSON."""
        with open(GOLDEN_FIXTURE) as f:
            ontology = json.load(f)
        assert isinstance(ontology, dict)
        assert "entities" in ontology
        assert "relationships" in ontology
