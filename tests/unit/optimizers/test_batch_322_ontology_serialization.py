"""
Batch 322: Ontology Serialization Module
=========================================

Implements unified serialization infrastructure for converting between
dict-based representations and typed dataclasses across the ontology system.

Goal: Provide consistent, type-safe serialization/deserialization for all
ontology-related data structures (ontologies, entities, relationships, configs).
"""

from dataclasses import dataclass, asdict, field, fields
from typing import Dict, List, Any, Optional, Type, TypeVar, get_args, get_origin
from abc import ABC, abstractmethod
import json
from enum import Enum
import pytest


T = TypeVar("T")


# ============================================================================
# SERIALIZATION INTERFACES & BASE CLASSES
# ============================================================================

class SerializableDataclass(ABC):
    """Base class for dataclasses that support serialization."""
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        pass
    
    @classmethod
    @abstractmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Create instance from dictionary representation."""
        pass


class DictSerializationMixin:
    """Mixin providing default serialization for dataclasses."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert dataclass to dict."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Create dataclass from dict, filtering unknown fields."""
        allowed_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        return cls(**filtered_data)


class TypeRegistry:
    """Registry for custom type converters during serialization."""
    
    def __init__(self):
        self._converters: Dict[Type, callable] = {}
        self._deserializers: Dict[Type, callable] = {}
    
    def register_converter(self, type_: Type, converter: callable) -> None:
        """Register a custom serialization converter."""
        self._converters[type_] = converter
    
    def register_deserializer(self, type_: Type, deserializer: callable) -> None:
        """Register a custom deserialization function."""
        self._deserializers[type_] = deserializer
    
    def has_converter(self, type_: Type) -> bool:
        """Check if type has custom converter."""
        return type_ in self._converters
    
    def has_deserializer(self, type_: Type) -> bool:
        """Check if type has custom deserializer."""
        return type_ in self._deserializers
    
    def convert(self, value: Any, type_: Type) -> Any:
        """Apply custom converter if registered."""
        if type_ in self._converters:
            return self._converters[type_](value)
        return value
    
    def deserialize(self, value: Any, type_: Type) -> Any:
        """Apply custom deserializer if registered."""
        if type_ in self._deserializers:
            return self._deserializers[type_](value)
        return value


class JSONSerializer:
    """Unified JSON serialization for ontology objects."""
    
    def __init__(self, registry: Optional[TypeRegistry] = None):
        self.registry = registry or TypeRegistry()
        self._setup_default_converters()
    
    def _setup_default_converters(self) -> None:
        """Set up converters for common types."""
        # Enum support
        self.registry.register_converter(
            Enum,
            lambda v: v.value if isinstance(v, Enum) else v
        )
        
        self.registry.register_deserializer(
            Enum,
            lambda v, t=None: v  # Enum deserialization handled by type hints
        )
    
    def serialize(self, obj: Any) -> str:
        """Serialize object to JSON string."""
        def _convert(o):
            if isinstance(o, dict):
                return {k: _convert(v) for k, v in o.items()}
            elif isinstance(o, (list, tuple)):
                return [_convert(v) for v in o]
            elif isinstance(o, Enum):
                return o.value
            elif hasattr(o, "__dict__"):
                return o.__dict__
            else:
                return o
        
        return json.dumps(_convert(obj))
    
    def deserialize(self, json_str: str, target_type: Type[T]) -> T:
        """Deserialize JSON string to typed object."""
        data = json.loads(json_str)
        
        if hasattr(target_type, "from_dict"):
            return target_type.from_dict(data)
        elif hasattr(target_type, "__dataclass_fields__"):
            return target_type.from_dict(data) if hasattr(target_type, "from_dict") else target_type(**data)
        else:
            return data


@dataclass
class Entity(DictSerializationMixin):
    """Basic entity for serialization testing."""
    entity_id: str
    entity_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship(DictSerializationMixin):
    """Basic relationship for serialization testing."""
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimpleOntology(DictSerializationMixin):
    """Simple ontology for testing serialization."""
    ontology_id: str
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Custom serialization handling nested dataclasses."""
        return {
            "ontology_id": self.ontology_id,
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [r.to_dict() for r in self.relationships],
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimpleOntology":
        """Custom deserialization handling nested dataclasses."""
        entities = [
            Entity.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("entities", [])
        ]
        relationships = [
            Relationship.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("relationships", [])
        ]
        return cls(
            ontology_id=data["ontology_id"],
            entities=entities,
            relationships=relationships,
            metadata=data.get("metadata", {}),
        )


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestDictSerializationMixin:
    """Test dict serialization mixin."""
    
    def test_entity_to_dict(self):
        """Verify entity converts to dict."""
        entity = Entity(
            entity_id="e1",
            entity_type="person",
            confidence=0.85,
            metadata={"key": "value"},
        )
        
        data = entity.to_dict()
        
        assert isinstance(data, dict)
        assert data["entity_id"] == "e1"
        assert data["entity_type"] == "person"
        assert data["confidence"] == 0.85
        assert data["metadata"]["key"] == "value"
    
    def test_entity_from_dict(self):
        """Verify entity creates from dict."""
        data = {
            "entity_id": "e2",
            "entity_type": "organization",
            "confidence": 0.9,
            "metadata": {"industry": "tech"},
        }
        
        entity = Entity.from_dict(data)
        
        assert entity.entity_id == "e2"
        assert entity.entity_type == "organization"
        assert entity.confidence == 0.9
        assert entity.metadata["industry"] == "tech"
    
    def test_entity_round_trip(self):
        """Verify entity survives round-trip serialization."""
        original = Entity(
            entity_id="e3",
            entity_type="location",
            confidence=0.75,
        )
        
        data = original.to_dict()
        restored = Entity.from_dict(data)
        
        assert restored.entity_id == original.entity_id
        assert restored.entity_type == original.entity_type
        assert restored.confidence == original.confidence


class TestNestedDataclassSerialization:
    """Test serialization of nested dataclass structures."""
    
    def test_ontology_to_dict(self):
        """Verify ontology with nested entities converts to dict."""
        entity = Entity(entity_id="e1", entity_type="person")
        relationship = Relationship(
            source_id="e1",
            target_id="e2",
            relationship_type="knows",
        )
        ontology = SimpleOntology(
            ontology_id="ont1",
            entities=[entity],
            relationships=[relationship],
        )
        
        data = ontology.to_dict()
        
        assert data["ontology_id"] == "ont1"
        assert len(data["entities"]) == 1
        assert len(data["relationships"]) == 1
        assert data["entities"][0]["entity_id"] == "e1"
        assert data["relationships"][0]["relationship_type"] == "knows"
    
    def test_ontology_from_dict(self):
        """Verify ontology deserializes from dict with nested structures."""
        data = {
            "ontology_id": "ont2",
            "entities": [
                {"entity_id": "e1", "entity_type": "person"},
                {"entity_id": "e2", "entity_type": "person"},
            ],
            "relationships": [
                {
                    "source_id": "e1",
                    "target_id": "e2",
                    "relationship_type": "knows",
                }
            ],
        }
        
        ontology = SimpleOntology.from_dict(data)
        
        assert ontology.ontology_id == "ont2"
        assert len(ontology.entities) == 2
        assert len(ontology.relationships) == 1
        assert ontology.entities[0].entity_id == "e1"
    
    def test_ontology_round_trip(self):
        """Verify ontology survives full round-trip serialization."""
        original = SimpleOntology(
            ontology_id="ont3",
            entities=[
                Entity(entity_id="e1", entity_type="person", confidence=0.8),
                Entity(entity_id="e2", entity_type="person", confidence=0.7),
            ],
            relationships=[
                Relationship(
                    source_id="e1",
                    target_id="e2",
                    relationship_type="knows",
                    confidence=0.9,
                )
            ],
            metadata={"version": "1.0"},
        )
        
        data = original.to_dict()
        restored = SimpleOntology.from_dict(data)
        
        assert restored.ontology_id == original.ontology_id
        assert len(restored.entities) == len(original.entities)
        assert len(restored.relationships) == len(original.relationships)
        assert restored.entities[0].confidence == 0.8
        assert restored.relationships[0].confidence == 0.9


class TestTypeRegistry:
    """Test custom type registry for converters."""
    
    def test_register_converter(self):
        """Verify converter registration."""
        registry = TypeRegistry()
        
        def custom_converter(v):
            return v.upper() if isinstance(v, str) else v
        
        registry.register_converter(str, custom_converter)
        
        assert registry.has_converter(str)
        result = registry.convert("hello", str)
        assert result == "HELLO"
    
    def test_register_deserializer(self):
        """Verify deserializer registration."""
        registry = TypeRegistry()
        
        def custom_deser(v):
            return int(v) if isinstance(v, str) else v
        
        registry.register_deserializer(int, custom_deser)
        
        assert registry.has_deserializer(int)
        result = registry.deserialize("42", int)
        assert result == 42
    
    def test_registry_with_enum(self):
        """Verify registry handles enum types."""
        from enum import Enum
        
        class Color(Enum):
            RED = "red"
            GREEN = "green"
            BLUE = "blue"
        
        registry = TypeRegistry()
        registry.register_converter(
            Color,
            lambda v: v.value if isinstance(v, Color) else v,
        )
        
        assert registry.has_converter(Color)
        assert registry.convert(Color.RED, Color) == "red"


class TestJSONSerializer:
    """Test JSON serialization for ontology objects."""
    
    def test_serialize_dict(self):
        """Verify dict serializes to JSON."""
        serializer = JSONSerializer()
        data = {"key": "value", "number": 42}
        
        json_str = serializer.serialize(data)
        
        assert isinstance(json_str, str)
        assert "key" in json_str
        assert "value" in json_str
    
    def test_serialize_entity(self):
        """Verify entity serializes to JSON."""
        serializer = JSONSerializer()
        entity = Entity(
            entity_id="e1",
            entity_type="person",
            confidence=0.85,
        )
        
        json_str = serializer.serialize(entity)
        
        assert isinstance(json_str, str)
        assert "e1" in json_str
        assert "person" in json_str
    
    def test_deserialize_to_dict(self):
        """Verify deserialization to dict."""
        serializer = JSONSerializer()
        json_str = '{"key": "value", "count": 5}'
        
        # Deserialize to dict (no specific type)
        data = json.loads(json_str)
        
        assert data["key"] == "value"
        assert data["count"] == 5
    
    def test_serialize_enum(self):
        """Verify enum values are properly serialized."""
        from enum import Enum
        
        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"
        
        serializer = JSONSerializer()
        data = {"status": Status.ACTIVE}
        
        json_str = serializer.serialize(data)
        
        assert "active" in json_str
    
    def test_serialize_nested_list(self):
        """Verify nested structures serialize correctly."""
        serializer = JSONSerializer()
        data = {
            "entities": [
                {"id": "e1", "type": "person"},
                {"id": "e2", "type": "person"},
            ],
            "count": 2,
        }
        
        json_str = serializer.serialize(data)
        restored = json.loads(json_str)
        
        assert len(restored["entities"]) == 2
        assert restored["entities"][0]["id"] == "e1"


class TestSerializationRoundTrips:
    """Test full round-trip serialization scenarios."""
    
    def test_entity_json_round_trip(self):
        """Verify entity survives JSON serialization round-trip."""
        original = Entity(
            entity_id="test_entity",
            entity_type="concept",
            confidence=0.95,
            metadata={"domain": "test"},
        )
        
        # Serialize
        json_str = json.dumps(original.to_dict())
        
        # Deserialize
        data = json.loads(json_str)
        restored = Entity.from_dict(data)
        
        assert restored.entity_id == original.entity_id
        assert restored.entity_type == original.entity_type
        assert restored.confidence == original.confidence
        assert restored.metadata == original.metadata
    
    def test_ontology_json_round_trip(self):
        """Verify ontology survives JSON serialization round-trip."""
        original = SimpleOntology(
            ontology_id="test_ontology",
            entities=[
                Entity(entity_id="e1", entity_type="node"),
                Entity(entity_id="e2", entity_type="node"),
            ],
            relationships=[
                Relationship(
                    source_id="e1",
                    target_id="e2",
                    relationship_type="connected",
                )
            ],
            metadata={"format": "standard"},
        )
        
        # Full JSON round-trip
        json_str = json.dumps(original.to_dict())
        data = json.loads(json_str)
        restored = SimpleOntology.from_dict(data)
        
        assert restored.ontology_id == original.ontology_id
        assert len(restored.entities) == 2
        assert len(restored.relationships) == 1
        assert restored.metadata["format"] == "standard"


class TestSerializationEdgeCases:
    """Test edge cases in serialization."""
    
    def test_empty_entity(self):
        """Verify minimal entity serializes."""
        entity = Entity(entity_id="", entity_type="")
        data = entity.to_dict()
        restored = Entity.from_dict(data)
        
        assert restored.entity_id == ""
        assert restored.entity_type == ""
    
    def test_empty_ontology(self):
        """Verify empty ontology serializes."""
        ontology = SimpleOntology(ontology_id="empty")
        data = ontology.to_dict()
        restored = SimpleOntology.from_dict(data)
        
        assert restored.ontology_id == "empty"
        assert len(restored.entities) == 0
        assert len(restored.relationships) == 0
    
    def test_large_metadata(self):
        """Verify large metadata dict serializes."""
        entity = Entity(
            entity_id="e1",
            entity_type="test",
            metadata={f"key_{i}": f"value_{i}" for i in range(100)},
        )
        
        data = entity.to_dict()
        restored = Entity.from_dict(data)
        
        assert len(restored.metadata) == 100
        assert restored.metadata["key_99"] == "value_99"
    
    def test_none_values_in_metadata(self):
        """Verify None values in metadata are preserved."""
        entity = Entity(
            entity_id="e1",
            entity_type="test",
            metadata={"key1": "value", "key2": None, "key3": 0},
        )
        
        data = entity.to_dict()
        restored = Entity.from_dict(data)
        
        assert restored.metadata["key1"] == "value"
        assert restored.metadata["key2"] is None
        assert restored.metadata["key3"] == 0
