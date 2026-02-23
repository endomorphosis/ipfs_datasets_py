"""Property-based tests for round-trip serialization using Hypothesis.

Tests that `to_dict()` → `from_dict()` round-trips preserve data integrity
for ExtractionConfig, Entity, and Relationship classes.

All tests use Hypothesis to generate hundreds of random instances to catch
edge cases that manual tests might miss.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

# Import the strategies we created earlier
from tests.unit.optimizers.graphrag.strategies import (
    valid_extraction_config, 
    valid_entity,
)


class TestExtractionConfigRoundTrip:
    """Property-based round-trip tests for ExtractionConfig serialization."""
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(config=valid_extraction_config())
    def test_to_dict_from_dict_preserves_all_fields(self, config):
        """ExtractionConfig round-trip through to_dict/from_dict preserves all fields."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        
        # Round-trip: config → dict → config
        as_dict = config.to_dict()
        restored = ExtractionConfig.from_dict(as_dict)
        
        # Assert all fields match
        assert restored.confidence_threshold == config.confidence_threshold
        assert restored.max_entities == config.max_entities
        assert restored.max_relationships == config.max_relationships
        assert restored.window_size == config.window_size
        assert restored.include_properties == config.include_properties
        assert restored.domain_vocab == config.domain_vocab
        assert restored.custom_rules == config.custom_rules
        assert restored.llm_fallback_threshold == config.llm_fallback_threshold
        assert restored.min_entity_length == config.min_entity_length
        assert restored.stopwords == config.stopwords
        assert restored.allowed_entity_types == config.allowed_entity_types
        assert restored.max_confidence == config.max_confidence
    
    @settings(max_examples=50)
    @given(config=valid_extraction_config())
    def test_to_dict_produces_json_serializable_dict(self, config):
        """The dict from to_dict() can be serialized to JSON."""
        import json
        
        as_dict = config.to_dict()
        # Should not raise
        json_str = json.dumps(as_dict)
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    @settings(max_examples=50)
    @given(config=valid_extraction_config())
    def test_from_dict_idempotent(self, config):
        """Calling from_dict twice on the same dict produces equivalent configs."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        
        as_dict = config.to_dict()
        first = ExtractionConfig.from_dict(as_dict)
        second = ExtractionConfig.from_dict(as_dict)
        
        assert first.confidence_threshold == second.confidence_threshold
        assert first.max_entities == second.max_entities
        assert first.stopwords == second.stopwords


class TestEntityRoundTrip:
    """Property-based round-trip tests for Entity serialization."""
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(entity=valid_entity())
    def test_to_dict_from_dict_preserves_all_fields(self, entity):
        """Entity round-trip through to_dict/from_dict preserves all fields."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        # Round-trip: entity → dict → entity
        as_dict = entity.to_dict()
        restored = Entity.from_dict(as_dict)
        
        # Assert all core fields match
        assert restored.id == entity.id
        assert restored.text == entity.text
        assert restored.type == entity.type
        assert restored.confidence == entity.confidence
        
        # Properties should match (both may be empty dicts)
        assert restored.properties == entity.properties
        
        # Source span should match if present
        if entity.source_span is not None:
            assert restored.source_span == entity.source_span
        else:
            assert restored.source_span is None
    
    @settings(max_examples=50)
    @given(entity=valid_entity())
    def test_to_dict_produces_json_serializable_dict(self, entity):
        """The dict from Entity.to_dict() can be serialized to JSON."""
        import json
        
        as_dict = entity.to_dict()
        # Should not raise
        json_str = json.dumps(as_dict)
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    @settings(max_examples=50)
    @given(entity=valid_entity())
    def test_from_dict_idempotent(self, entity):
        """Calling Entity.from_dict twice on the same dict produces equivalent entities."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        as_dict = entity.to_dict()
        first = Entity.from_dict(as_dict)
        second = Entity.from_dict(as_dict)
        
        assert first.id == second.id
        assert first.text == second.text
        assert first.type == second.type
        assert first.confidence == second.confidence
    
    @settings(max_examples=30)
    @given(entity=valid_entity())
    def test_to_json_from_json_round_trip(self, entity):
        """Entity.to_json() → from_dict(json.loads(...)) round-trip works."""
        import json
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        json_str = entity.to_json()
        parsed = json.loads(json_str)
        restored = Entity.from_dict(parsed)
        
        assert restored.id == entity.id
        assert restored.text == entity.text


class TestRelationshipRoundTrip:
    """Property-based round-trip tests for Relationship serialization."""
    
    @st.composite
    def valid_relationship(draw) -> "Relationship":  # type: ignore[return]
        """Generate a valid Relationship instance."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        rel_id = draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
            min_size=1, max_size=20,
        ))
        source_id = draw(st.text(min_size=1, max_size=20))
        target_id = draw(st.text(min_size=1, max_size=20))
        rel_type = draw(st.sampled_from([
            "works_for", "located_in", "part_of", "is_a", "causes",
            "employs", "manages", "obligates", "owns", "produces"
        ]))
        confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        direction = draw(st.sampled_from(["forward", "bidirectional", "unknown"]))
        
        # Properties: dict with string keys
        properties = draw(st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.one_of(st.text(max_size=50), st.floats(allow_nan=False, allow_infinity=False), st.booleans()),
            min_size=0, max_size=5,
        ))
        
        return Relationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            confidence=confidence,
            direction=direction,
            properties=properties,
        )
    
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(rel=valid_relationship())
    def test_to_dict_from_dict_preserves_all_fields(self, rel):
        """Relationship round-trip through to_dict/from_dict preserves all fields."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        # Round-trip: relationship → dict → relationship
        as_dict = rel.to_dict()
        restored = Relationship.from_dict(as_dict)
        
        # Assert all core fields match
        assert restored.id == rel.id
        assert restored.source_id == rel.source_id
        assert restored.target_id == rel.target_id
        assert restored.type == rel.type
        assert restored.confidence == rel.confidence
        assert restored.direction == rel.direction
        assert restored.properties == rel.properties
    
    @settings(max_examples=50)
    @given(rel=valid_relationship())
    def test_to_dict_produces_json_serializable_dict(self, rel):
        """The dict from Relationship.to_dict() can be serialized to JSON."""
        import json
        
        as_dict = rel.to_dict()
        # Should not raise
        json_str = json.dumps(as_dict)
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    @settings(max_examples=50)
    @given(rel=valid_relationship())
    def test_from_dict_idempotent(self, rel):
        """Calling Relationship.from_dict twice on the same dict produces equivalent relationships."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        as_dict = rel.to_dict()
        first = Relationship.from_dict(as_dict)
        second = Relationship.from_dict(as_dict)
        
        assert first.id == second.id
        assert first.source_id == second.source_id
        assert first.target_id == second.target_id
        assert first.type == second.type
        assert first.confidence == second.confidence
    
    @settings(max_examples=30)
    @given(rel=valid_relationship())
    def test_to_json_from_json_round_trip(self, rel):
        """Relationship.to_json() → from_dict(json.loads(...)) round-trip works."""
        import json
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        restored = Relationship.from_dict(parsed)
        
        assert restored.id == rel.id
        assert restored.source_id == rel.source_id
        assert restored.target_id == rel.target_id


class TestEntityExtractionResultRoundTrip:
    """Property-based round-trip tests for EntityExtractionResult serialization."""
    
    @st.composite
    def valid_extraction_result(draw) -> "EntityExtractionResult":  # type: ignore[return]
        """Generate a valid EntityExtractionResult."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult, Entity, Relationship,
        )
        
        # Generate 0-10 entities
        num_entities = draw(st.integers(min_value=0, max_value=10))
        entities = [draw(valid_entity()) for _ in range(num_entities)]
        
        # Generate 0-5 relationships (only if we have entities)
        relationships = []
        if num_entities >= 2:
            entity_ids = [e.id for e in entities]
            num_rels = draw(st.integers(min_value=0, max_value=min(5, num_entities)))
            for _ in range(num_rels):
                src = draw(st.sampled_from(entity_ids))
                tgt = draw(st.sampled_from(entity_ids))
                rel_type = draw(st.sampled_from(["works_for", "part_of", "is_a"]))
                conf = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
                rel_id = f"rel_{src}_{tgt}_{len(relationships)}"
                relationships.append(Relationship(
                    id=rel_id, source_id=src, target_id=tgt,
                    type=rel_type, confidence=conf, direction="forward",
                    properties={}
                ))
        
        confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
        metadata = draw(st.dictionaries(
            keys=st.text(min_size=1, max_size=10),
            values=st.one_of(st.text(max_size=20), st.floats(allow_nan=False)),
            min_size=0, max_size=3,
        ))
        errors = draw(st.lists(st.text(max_size=50), min_size=0, max_size=3))
        
        return EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=confidence,
            metadata=metadata,
            errors=errors,
        )
    
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
    @given(result=valid_extraction_result())
    def test_to_dict_from_dict_preserves_structure(self, result):
        """EntityExtractionResult round-trip preserves entity and relationship counts."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        
        as_dict = result.to_dict()
        restored = EntityExtractionResult.from_dict(as_dict)
        
        assert len(restored.entities) == len(result.entities)
        assert len(restored.relationships) == len(result.relationships)
        assert restored.confidence == result.confidence
    
    @settings(max_examples=30)
    @given(result=valid_extraction_result())
    def test_to_json_parseable(self, result):
        """EntityExtractionResult.to_json() produces parseable JSON."""
        import json
        
        json_str = result.to_json()
        parsed = json.loads(json_str)
        
        assert "entities" in parsed
        assert "relationships" in parsed
        assert "confidence" in parsed
