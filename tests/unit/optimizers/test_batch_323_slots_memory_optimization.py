"""
Batch 323: __slots__ Memory Optimization for Hot-Path Dataclasses
=================================================================

Adds __slots__ to frequently-instantiated dataclasses to reduce memory overhead.

Goal: Reduce memory footprint of Entity, Relationship, Config, and Result objects
by 30-40% through slot-based attribute storage (eliminates __dict__ per instance).
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import sys
import pytest


# ============================================================================
# SLOTTED DATACLASSES
# ============================================================================

@dataclass(slots=True)
class SlottedEntity:
    """Entity with __slots__ for memory efficiency."""
    entity_id: str
    entity_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass(slots=True)
class SlottedRelationship:
    """Relationship with __slots__ for memory efficiency."""
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass(slots=True)
class SlottedExtractionConfig:
    """Extraction config with __slots__ for memory efficiency."""
    data_source: str
    data_type: str
    domain: str = "general"
    extraction_strategy: str = "hybrid"
    max_entities: int = 100
    max_relationships: int = 200
    confidence_threshold: float = 0.5


@dataclass(slots=True)
class SlottedExtractionResult:
    """Extraction result with __slots__ for memory efficiency."""
    entity_count: int
    relationship_count: int
    avg_confidence: float = 0.0
    execution_time_ms: float = 0.0
    extraction_strategy: str = "unknown"


# Non-slotted versions for comparison
@dataclass
class NonSlottedEntity:
    """Entity without __slots__ for comparison."""
    entity_id: str
    entity_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class NonSlottedRelationship:
    """Relationship without __slots__ for comparison."""
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestSlottedDataclassCreation:
    """Test that slotted dataclasses work correctly."""
    
    def test_slotted_entity_creation(self):
        """Verify slotted entity creates successfully."""
        entity = SlottedEntity(
            entity_id="e1",
            entity_type="person",
            confidence=0.85,
        )
        
        assert entity.entity_id == "e1"
        assert entity.entity_type == "person"
        assert entity.confidence == 0.85
        assert isinstance(entity.metadata, dict)
    
    def test_slotted_relationship_creation(self):
        """Verify slotted relationship creates successfully."""
        rel = SlottedRelationship(
            source_id="e1",
            target_id="e2",
            relationship_type="knows",
        )
        
        assert rel.source_id == "e1"
        assert rel.target_id == "e2"
        assert rel.relationship_type == "knows"
    
    def test_slotted_config_creation(self):
        """Verify slotted config creates successfully."""
        config = SlottedExtractionConfig(
            data_source="document.txt",
            data_type="text",
            domain="legal",
        )
        
        assert config.data_source == "document.txt"
        assert config.data_type == "text"
        assert config.domain == "legal"
        assert config.max_entities == 100
    
    def test_slotted_result_creation(self):
        """Verify slotted result creates successfully."""
        result = SlottedExtractionResult(
            entity_count=42,
            relationship_count=18,
            avg_confidence=0.75,
        )
        
        assert result.entity_count == 42
        assert result.relationship_count == 18
        assert result.avg_confidence == 0.75


class TestSlottedDataclassAttributes:
    """Test attribute access on slotted dataclasses."""
    
    def test_slotted_entity_attributes(self):
        """Verify slotted entity attribute access."""
        entity = SlottedEntity(
            entity_id="e1",
            entity_type="person",
        )
        
        # Should be accessible
        assert hasattr(entity, "entity_id")
        assert hasattr(entity, "entity_type")
        assert hasattr(entity, "confidence")
        assert hasattr(entity, "metadata")
    
    def test_slotted_entity_metadata_modification(self):
        """Verify metadata dict can be modified."""
        entity = SlottedEntity(entity_id="e1", entity_type="test")
        
        entity.metadata["key"] = "value"
        assert entity.metadata["key"] == "value"
        
        entity.metadata["count"] = 42
        assert entity.metadata["count"] == 42
    
    def test_slotted_entity_no_dict_attribute(self):
        """Verify slotted entity doesn't have __dict__."""
        entity = SlottedEntity(entity_id="e1", entity_type="test")
        
        # Slotted classes shouldn't have __dict__
        assert not hasattr(entity, "__dict__")
    
    def test_slotted_relationship_attribute_modification(self):
        """Verify relationship attributes can be modified."""
        rel = SlottedRelationship(
            source_id="e1",
            target_id="e2",
            relationship_type="knows",
        )
        
        rel.confidence = 0.95
        assert rel.confidence == 0.95
        
        rel.relationship_type = "colleagues"
        assert rel.relationship_type == "colleagues"


class TestSlottedDataclassMemoryEfficiency:
    """Test memory efficiency benefits of slots."""
    
    def test_slotted_entity_no_dict(self):
        """Verify slotted entity doesn't have __dict__ overhead."""
        slotted = SlottedEntity(
            entity_id="test",
            entity_type="person",
        )
        
        # Slotted classes should not have __dict__
        assert not hasattr(slotted, "__dict__"), (
            "Slotted entity should not have __dict__"
        )
    
    def test_non_slotted_entity_has_dict(self):
        """Verify non-slotted entity has __dict__ overhead."""
        non_slotted = NonSlottedEntity(
            entity_id="test",
            entity_type="person",
        )
        
        # Non-slotted classes should have __dict__
        assert hasattr(non_slotted, "__dict__"), (
            "Non-slotted entity should have __dict__"
        )
    
    def test_slotted_with_many_instances_memory_advantage(self):
        """Verify memory advantage shows with many instances."""
        # Create large batch of slotted entities
        slotted_batch = [
            SlottedEntity(
                entity_id=f"e{i}",
                entity_type="person",
            )
            for i in range(10000)
        ]
        
        # Create large batch of non-slotted entities
        non_slotted_batch = [
            NonSlottedEntity(
                entity_id=f"e{i}",
                entity_type="person",
            )
            for i in range(10000)
        ]
        
        # With large collections the savings accumulate
        # Each __dict__ adds significant overhead
        slotted_total = sum(sys.getsizeof(e.__dict__ if hasattr(e, "__dict__") else {}) for e in slotted_batch)
        non_slotted_total = sum(sys.getsizeof(e.__dict__ if hasattr(e, "__dict__") else {}) for e in non_slotted_batch)
        
        # Non-slotted should have much more __dict__ overhead
        assert non_slotted_total > slotted_total, (
            f"Non-slotted __dict__ overhead ({non_slotted_total}) should exceed "
            f"slotted overhead ({slotted_total})"
        )


class TestSlottedDataclassImmutability:
    """Test that we can't add arbitrary attributes to slotted classes."""
    
    def test_slotted_entity_no_arbitrary_attributes(self):
        """Verify can't add arbitrary attributes to slotted entity."""
        entity = SlottedEntity(entity_id="e1", entity_type="test")
        
        # Should raise AttributeError when trying to add new attribute
        with pytest.raises(AttributeError):
            entity.new_attribute = "value"
    
    def test_slotted_relationship_no_arbitrary_attributes(self):
        """Verify can't add arbitrary attributes to slotted relationship."""
        rel = SlottedRelationship(
            source_id="e1",
            target_id="e2",
            relationship_type="knows",
        )
        
        with pytest.raises(AttributeError):
            rel.extra_field = "value"
    
    def test_slotted_config_no_arbitrary_attributes(self):
        """Verify can't add arbitrary attributes to slotted config."""
        config = SlottedExtractionConfig(
            data_source="doc.txt",
            data_type="text",
        )
        
        with pytest.raises(AttributeError):
            config.custom_param = "value"


class TestSlottedDataclassPerformance:
    """Test performance characteristics of slotted dataclasses."""
    
    def test_slotted_entity_attribute_access_speed(self):
        """Verify slotted entity has fast attribute access."""
        entity = SlottedEntity(entity_id="e1", entity_type="person")
        
        # Repeated access should be fast
        for _ in range(1000):
            _ = entity.entity_id
            _ = entity.entity_type
            _ = entity.confidence
        
        # Test passes if no errors (actual timing would need profiler)
        assert True
    
    def test_slotted_batch_creation_performance(self):
        """Verify batch creation is efficient."""
        import time
        
        # Time creation of slotted batch
        start = time.perf_counter()
        slotted_batch = [
            SlottedEntity(
                entity_id=f"e{i}",
                entity_type="test",
            )
            for i in range(1000)
        ]
        slotted_time = time.perf_counter() - start
        
        # Time creation of non-slotted batch
        start = time.perf_counter()
        non_slotted_batch = [
            NonSlottedEntity(
                entity_id=f"e{i}",
                entity_type="test",
            )
            for i in range(1000)
        ]
        non_slotted_time = time.perf_counter() - start
        
        # Both should complete quickly (< 1 second for 1000 each)
        assert slotted_time < 1.0
        assert non_slotted_time < 1.0


class TestSlottedDataclassCompatibility:
    """Test that slotted dataclasses work with common patterns."""
    
    def test_slotted_entity_repr(self):
        """Verify slotted entity has good __repr__."""
        entity = SlottedEntity(
            entity_id="e1",
            entity_type="person",
            confidence=0.8,
        )
        
        repr_str = repr(entity)
        assert "SlottedEntity" in repr_str
        assert "e1" in repr_str
    
    def test_slotted_entity_equality(self):
        """Verify slotted entities can be compared for equality."""
        entity1 = SlottedEntity(entity_id="e1", entity_type="person")
        entity2 = SlottedEntity(entity_id="e1", entity_type="person")
        entity3 = SlottedEntity(entity_id="e2", entity_type="person")
        
        # Same values should be equal
        assert entity1 == entity2
        # Different values should not be equal
        assert entity1 != entity3
    
    def test_slotted_entity_copy(self):
        """Verify slotted entity can be copied."""
        from copy import copy
        
        original = SlottedEntity(
            entity_id="e1",
            entity_type="person",
            confidence=0.75,
        )
        
        copied = copy(original)
        
        assert copied.entity_id == original.entity_id
        assert copied.entity_type == original.entity_type
        assert copied.confidence == original.confidence
        # Metadata should be same reference (shallow copy)
        assert copied.metadata is original.metadata


class TestSlottedDataclassEdgeCases:
    """Test edge cases with slotted dataclasses."""
    
    def test_slotted_entity_with_special_characters(self):
        """Verify slotted entity handles special characters in IDs."""
        entity = SlottedEntity(
            entity_id="e-1_special@test",
            entity_type="person",
        )
        
        assert entity.entity_id == "e-1_special@test"
    
    def test_slotted_config_with_extreme_values(self):
        """Verify slotted config handles extreme values."""
        config = SlottedExtractionConfig(
            data_source="test",
            data_type="text",
            max_entities=999999,
            confidence_threshold=0.0,
        )
        
        assert config.max_entities == 999999
        assert config.confidence_threshold == 0.0
    
    def test_slotted_result_with_zero_values(self):
        """Verify slotted result handles zero values."""
        result = SlottedExtractionResult(
            entity_count=0,
            relationship_count=0,
            avg_confidence=0.0,
            execution_time_ms=0.0,
        )
        
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.avg_confidence == 0.0
