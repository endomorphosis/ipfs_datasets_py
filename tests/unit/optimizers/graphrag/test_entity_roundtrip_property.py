"""Property-based tests for Entity round-trip serialization.

Validates that Entity.to_dict() → from_dict() preserves all fields using
Hypothesis-generated random Entity instances.
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
from tests.unit.optimizers.graphrag.strategies import valid_entity


class TestEntityRoundTripProperty:
    """Property-based tests for Entity serialization round-tripping."""

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_to_dict_from_dict_roundtrip(self, entity: Entity):
        """Entity.from_dict(entity.to_dict()) == entity for all valid entities.
        
        This property test generates random Entity instances and verifies that
        serialization via to_dict() followed by deserialization via from_dict()
        produces an equivalent Entity.
        """
        # Serialize to dict
        entity_dict = entity.to_dict()
        
        # Deserialize back to Entity
        restored = Entity.from_dict(entity_dict)
        
        # All fields must match
        assert restored.id == entity.id
        assert restored.type == entity.type
        assert restored.text == entity.text
        assert restored.confidence == pytest.approx(entity.confidence, abs=1e-9)
        assert restored.properties == entity.properties
        assert restored.source_span == entity.source_span

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_to_dict_contains_required_keys(self, entity: Entity):
        """Entity.to_dict() always includes required keys."""
        entity_dict = entity.to_dict()
        
        # Required keys must be present
        assert "id" in entity_dict
        assert "type" in entity_dict
        assert "text" in entity_dict
        assert "confidence" in entity_dict
        assert "properties" in entity_dict
        assert "source_span" in entity_dict

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_to_dict_serializes_source_span_correctly(self, entity: Entity):
        """source_span is serialized as a list or None."""
        entity_dict = entity.to_dict()
        
        if entity.source_span is None:
            assert entity_dict["source_span"] is None
        else:
            assert isinstance(entity_dict["source_span"], list)
            assert len(entity_dict["source_span"]) == 2
            assert entity_dict["source_span"] == list(entity.source_span)

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_from_dict_restores_source_span_as_tuple(self, entity: Entity):
        """from_dict() converts source_span list back to tuple."""
        entity_dict = entity.to_dict()
        restored = Entity.from_dict(entity_dict)
        
        if entity.source_span is None:
            assert restored.source_span is None
        else:
            assert isinstance(restored.source_span, tuple)
            assert len(restored.source_span) == 2
            assert restored.source_span == entity.source_span

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_properties_are_preserved(self, entity: Entity):
        """Properties dict is preserved through round-trip."""
        entity_dict = entity.to_dict()
        restored = Entity.from_dict(entity_dict)
        
        assert len(restored.properties) == len(entity.properties)
        for key in entity.properties:
            assert key in restored.properties
            # Float values need approximate comparison
            original_val = entity.properties[key]
            restored_val = restored.properties[key]
            if isinstance(original_val, float):
                assert restored_val == pytest.approx(original_val, abs=1e-9)
            else:
                assert restored_val == original_val

    @given(entity=valid_entity())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_confidence_bounds_preserved(self, entity: Entity):
        """Confidence remains in [0, 1] after round-trip."""
        entity_dict = entity.to_dict()
        restored = Entity.from_dict(entity_dict)
        
        assert 0.0 <= restored.confidence <= 1.0
        assert 0.0 <= entity.confidence <= 1.0

    def test_entity_from_dict_with_minimal_dict(self):
        """from_dict() works with minimal required fields only."""
        minimal_dict = {
            "id": "test-123",
            "type": "Person",
            "text": "Alice",
        }
        
        entity = Entity.from_dict(minimal_dict)
        
        assert entity.id == "test-123"
        assert entity.type == "Person"
        assert entity.text == "Alice"
        assert entity.confidence == 1.0  # default
        assert entity.properties == {}  # default
        assert entity.source_span is None  # default

    def test_entity_from_dict_raises_on_missing_required_field(self):
        """from_dict() raises KeyError when required fields are missing."""
        with pytest.raises(KeyError):
            Entity.from_dict({"id": "test", "type": "Person"})  # missing 'text'
        
        with pytest.raises(KeyError):
            Entity.from_dict({"id": "test", "text": "Alice"})  # missing 'type'
        
        with pytest.raises(KeyError):
            Entity.from_dict({"type": "Person", "text": "Alice"})  # missing 'id'

    @given(
        entity=valid_entity(),
        new_text=st.text(min_size=1, max_size=50),
    )
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_copy_with_preserves_other_fields(self, entity: Entity, new_text: str):
        """copy_with() only changes the specified field."""
        modified = entity.copy_with(text=new_text)
        
        assert modified.text == new_text
        assert modified.id == entity.id
        assert modified.type == entity.type
        assert modified.confidence == entity.confidence
        assert modified.properties == entity.properties
        assert modified.source_span == entity.source_span

    def test_entity_copy_with_raises_on_unknown_field(self):
        """copy_with() raises TypeError for unknown field names."""
        entity = Entity(id="e1", type="Person", text="Alice")
        
        with pytest.raises(TypeError, match="Unknown Entity field"):
            entity.copy_with(unknown_field="value")

    @given(entity=valid_entity())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_entity_to_text_format(self, entity: Entity):
        """to_text() returns expected format."""
        text_repr = entity.to_text()
        
        assert entity.text in text_repr
        assert entity.type in text_repr
        assert "conf=" in text_repr
        # Should be parseable format
        assert "(" in text_repr
        assert ")" in text_repr
