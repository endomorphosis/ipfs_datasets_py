"""Unit tests for Entity and Relationship JSON serialization.

Tests the to_json(), to_dict(), and from_dict() methods for Entity and
Relationship dataclasses.
"""

import json
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, Relationship


class TestEntityToJson:
    """Test Entity.to_json() method."""

    def test_to_json_basic(self):
        """Test basic JSON serialization of an entity."""
        entity = Entity(
            id="e1",
            type="Person",
            text="Alice",
            confidence=0.95,
        )
        
        json_str = entity.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["id"] == "e1"
        assert parsed["type"] == "Person"
        assert parsed["text"] == "Alice"
        assert parsed["confidence"] == 0.95

    def test_to_json_with_properties(self):
        """Test JSON serialization with properties."""
        entity = Entity(
            id="e2",
            type="Organization",
            text="ACME Corp",
            properties={"industry": "Technology", "founded": 1999},
            confidence=0.88,
        )
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["properties"]["industry"] == "Technology"
        assert parsed["properties"]["founded"] == 1999

    def test_to_json_with_source_span(self):
        """Test JSON serialization with source span."""
        entity = Entity(
            id="e3",
            type="Location",
            text="New York",
            source_span=(10, 18),
            confidence=0.92,
        )
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["source_span"] == [10, 18]

    def test_to_json_with_last_seen(self):
        """Test JSON serialization with last_seen timestamp."""
        import time
        
        timestamp = time.time()
        entity = Entity(
            id="e4",
            type="Event",
            text="Conference",
            last_seen=timestamp,
        )
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["last_seen"] == timestamp

    def test_to_json_pretty_print(self):
        """Test JSON serialization with pretty printing."""
        entity = Entity(
            id="e5",
            type="Concept",
            text="Democracy",
        )
        
        json_str = entity.to_json(indent=2)
        
        # Should have newlines for pretty formatting
        assert "\n" in json_str
        assert "  " in json_str  # Indentation

    def test_to_json_sorted_keys(self):
        """Test JSON serialization with sorted keys."""
        entity = Entity(
            id="e6",
            type="Person",
            text="Bob",
        )
        
        json_str = entity.to_json(sort_keys=True)
        
        # Parse and check that keys would be sorted
        parsed = json.loads(json_str)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_to_json_round_trip(self):
        """Test that to_json -> parse -> from_dict works."""
        original = Entity(
            id="e7",
            type="Person",
            text="Charlie",
            properties={"age": 30, "role": "Developer"},
            confidence=0.85,
            source_span=(5, 12),
        )
        
        json_str = original.to_json()
        parsed_dict = json.loads(json_str)
        reconstructed = Entity.from_dict(parsed_dict)
        
        assert reconstructed.id == original.id
        assert reconstructed.type == original.type
        assert reconstructed.text == original.text
        assert reconstructed.properties == original.properties
        assert reconstructed.confidence == original.confidence
        assert reconstructed.source_span == original.source_span


class TestRelationshipToDict:
    """Test Relationship.to_dict() method."""

    def test_to_dict_basic(self):
        """Test basic dictionary serialization."""
        rel = Relationship(
            id="r1",
            source_id="e1",
            target_id="e2",
            type="owns",
        )
        
        d = rel.to_dict()
        
        assert d["id"] == "r1"
        assert d["source_id"] == "e1"
        assert d["target_id"] == "e2"
        assert d["type"] == "owns"
        assert d["confidence"] == 1.0
        assert d["direction"] == "unknown"

    def test_to_dict_with_properties(self):
        """Test serialization with properties."""
        rel = Relationship(
            id="r2",
            source_id="e3",
            target_id="e4",
            type="causes",
            properties={"strength": "strong", "evidence": "text-based"},
            confidence=0.75,
        )
        
        d = rel.to_dict()
        
        assert d["properties"]["strength"] == "strong"
        assert d["properties"]["evidence"] == "text-based"
        assert d["confidence"] == 0.75

    def test_to_dict_with_direction(self):
        """Test serialization with explicit direction."""
        rel = Relationship(
            id="r3",
            source_id="e5",
            target_id="e6",
            type="obligates",
            direction="subject_to_object",
        )
        
        d = rel.to_dict()
        
        assert d["direction"] == "subject_to_object"


class TestRelationshipFromDict:
    """Test Relationship.from_dict() method."""

    def test_from_dict_basic(self):
        """Test reconstruction from dictionary."""
        d = {
            "id": "r4",
            "source_id": "e7",
            "target_id": "e8",
            "type": "related_to",
        }
        
        rel = Relationship.from_dict(d)
        
        assert rel.id == "r4"
        assert rel.source_id == "e7"
        assert rel.target_id == "e8"
        assert rel.type == "related_to"

    def test_from_dict_with_defaults(self):
        """Test that missing optional fields use defaults."""
        d = {
            "id": "r5",
            "source_id": "e9",
            "target_id": "e10",
            "type": "depends_on",
        }
        
        rel = Relationship.from_dict(d)
        
        assert rel.confidence == 1.0
        assert rel.direction == "unknown"
        assert rel.properties == {}

    def test_from_dict_with_all_fields(self):
        """Test reconstruction with all fields populated."""
        d = {
            "id": "r6",
            "source_id": "e11",
            "target_id": "e12",
            "type": "contains",
            "confidence": 0.88,
            "properties": {"scope": "full", "temporal": "always"},
            "direction": "undirected",
        }
        
        rel = Relationship.from_dict(d)
        
        assert rel.id == "r6"
        assert rel.confidence == 0.88
        assert rel.properties["scope"] == "full"
        assert rel.direction == "undirected"

    def test_from_dict_round_trip(self):
        """Test that to_dict -> from_dict preserves all data."""
        original = Relationship(
            id="r7",
            source_id="e13",
            target_id="e14",
            type="interacts_with",
            confidence=0.67,
            properties={"frequency": "high"},
            direction="subject_to_object",
        )
        
        d = original.to_dict()
        reconstructed = Relationship.from_dict(d)
        
        assert reconstructed.id == original.id
        assert reconstructed.source_id == original.source_id
        assert reconstructed.target_id == original.target_id
        assert reconstructed.type == original.type
        assert reconstructed.confidence == original.confidence
        assert reconstructed.properties == original.properties
        assert reconstructed.direction == original.direction


class TestRelationshipToJson:
    """Test Relationship.to_json() method."""

    def test_to_json_basic(self):
        """Test basic JSON serialization."""
        rel = Relationship(
            id="r8",
            source_id="e15",
            target_id="e16",
            type="links_to",
        )
        
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["id"] == "r8"
        assert parsed["source_id"] == "e15"
        assert parsed["target_id"] == "e16"
        assert parsed["type"] == "links_to"

    def test_to_json_with_properties(self):
        """Test JSON serialization with properties."""
        rel = Relationship(
            id="r9",
            source_id="e17",
            target_id="e18",
            type="precedes",
            properties={"temporal_gap": "1 day", "certainty": "high"},
            confidence=0.92,
        )
        
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["properties"]["temporal_gap"] == "1 day"
        assert parsed["confidence"] == 0.92

    def test_to_json_pretty_print(self):
        """Test JSON serialization with indentation."""
        rel = Relationship(
            id="r10",
            source_id="e19",
            target_id="e20",
            type="supports",
        )
        
        json_str = rel.to_json(indent=2, sort_keys=True)
        
        # Should be formatted
        assert "\n" in json_str
        assert "  " in json_str

    def test_to_json_round_trip(self):
        """Test full round-trip: to_json -> parse -> from_dict."""
        original = Relationship(
            id="r11",
            source_id="e21",
            target_id="e22",
            type="influences",
            confidence=0.79,
            properties={"degree": "moderate"},
            direction="subject_to_object",
        )
        
        json_str = original.to_json()
        parsed_dict = json.loads(json_str)
        reconstructed = Relationship.from_dict(parsed_dict)
        
        assert reconstructed.id == original.id
        assert reconstructed.source_id == original.source_id
        assert reconstructed.target_id == original.target_id
        assert reconstructed.type == original.type
        assert reconstructed.confidence == original.confidence
        assert reconstructed.properties == original.properties
        assert reconstructed.direction == original.direction


class TestJsonEdgeCases:
    """Test edge cases and error handling."""

    def test_entity_to_json_with_none_values(self):
        """Test that None values are serialized correctly."""
        entity = Entity(
            id="e-none",
            type="Test",
            text="None Test",
            source_span=None,
            last_seen=None,
        )
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["source_span"] is None
        assert parsed["last_seen"] is None

    def test_relationship_from_dict_missing_required_field(self):
        """Test that missing required fields raise KeyError."""
        d = {
            "id": "r-incomplete",
            "source_id": "e1",
            # Missing target_id and type
        }
        
        with pytest.raises(KeyError):
            Relationship.from_dict(d)

    def test_entity_json_with_empty_properties(self):
        """Test that empty properties dict is serialized."""
        entity = Entity(
            id="e-empty",
            type="Test",
            text="Empty Props",
            properties={},
        )
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["properties"] == {}

    def test_relationship_json_with_special_characters(self):
        """Test JSON serialization with special characters in strings."""
        rel = Relationship(
            id="r-special",
            source_id="e1",
            target_id="e2",
            type='contains "quotes"',
            properties={"note": "Line1\nLine2"},
        )
        
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        
        # JSON should handle escaping
        assert parsed["type"] == 'contains "quotes"'
        assert parsed["properties"]["note"] == "Line1\nLine2"

    def test_entity_to_json_kwargs_forwarded(self):
        """Test that kwargs are forwarded to json.dumps."""
        entity = Entity(id="e-kwargs", type="Test", text="Kwargs Test")
        
        # Test with ensure_ascii=False
        json_str = entity.to_json(ensure_ascii=False)
        
        # Should be callable without error
        assert isinstance(json_str, str)

    def test_relationship_confidence_float_conversion(self):
        """Test that confidence is properly converted to float."""
        d = {
            "id": "r-float",
            "source_id": "e1",
            "target_id": "e2",
            "type": "test",
            "confidence": "0.85",  # String instead of float
        }
        
        rel = Relationship.from_dict(d)
        
        # Should convert string to float
        assert isinstance(rel.confidence, float)
        assert rel.confidence == 0.85
