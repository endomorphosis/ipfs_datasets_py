"""Factory fixtures for ontology test creation.

Centralizes mock ontology, entity, and relationship creation to reduce
boilerplate across test suites and ensure consistency.

Provides parameterizable builders for:
- Entity objects (with customizable properties, confidence, spans)
- Relationship objects (with direction, type, confidence)
- Ontology dictionaries (with configurable entity/relationship counts)
- Extraction results (with metadata and quality scores)
"""

import pytest
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class EntityFactory:
    """Factory for creating Entity instances."""
    
    @staticmethod
    def default(
        entity_id: str = "e1",
        entity_type: str = "Person",
        text: str = "Alice",
        confidence: float = 0.9,
        properties: Optional[Dict[str, Any]] = None,
        source_span: Optional[tuple[int, int]] = None,
        last_seen: Optional[float] = None,
    ):
        """Create Entity with sensible defaults.
        
        Args:
            entity_id: Unique identifier (default: 'e1')
            entity_type: Type classification (default: 'Person')
            text: Text representation (default: 'Alice')
            confidence: Confidence score 0-1 (default: 0.9)
            properties: Optional metadata dict
            source_span: Optional (start, end) tuple
            last_seen: Optional Unix timestamp
            
        Returns:
            Entity instance
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        return Entity(
            id=entity_id,
            type=entity_type,
            text=text,
            confidence=confidence,
            properties=properties or {},
            source_span=source_span,
            last_seen=last_seen,
        )
    
    @staticmethod
    def high_confidence(entity_id: str = "e_high", text: str = "HighConf") -> Any:
        """Create entity with high confidence (0.95)."""
        return EntityFactory.default(
            entity_id=entity_id,
            text=text,
            confidence=0.95,
        )
    
    @staticmethod
    def low_confidence(entity_id: str = "e_low", text: str = "LowConf") -> Any:
        """Create entity with low confidence (0.55)."""
        return EntityFactory.default(
            entity_id=entity_id,
            text=text,
            confidence=0.55,
        )
    
    @staticmethod
    def with_properties(
        entity_id: str = "e_props",
        properties: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """Create entity with custom properties."""
        if properties is None:
            properties = {
                "age": 30,
                "department": "Engineering",
                "status": "Active",
            }
        
        return EntityFactory.default(
            entity_id=entity_id,
            properties=properties,
            **kwargs,
        )
    
    @staticmethod
    def with_span(
        entity_id: str = "e_span",
        start: int = 0,
        end: int = 10,
        **kwargs,
    ) -> Any:
        """Create entity with source span."""
        return EntityFactory.default(
            entity_id=entity_id,
            source_span=(start, end),
            **kwargs,
        )
    
    @staticmethod
    def batch(count: int = 5, confidence: float = 0.9) -> List[Any]:
        """Create multiple entities.
        
        Args:
            count: Number of entities to create
            confidence: Confidence for all entities
            
        Returns:
            List of Entity instances
        """
        return [
            EntityFactory.default(
                entity_id=f"e{i}",
                text=f"Entity{i}",
                confidence=confidence,
            )
            for i in range(1, count + 1)
        ]


@dataclass
class RelationshipFactory:
    """Factory for creating Relationship instances."""
    
    @staticmethod
    def default(
        rel_id: str = "r1",
        source_id: str = "e1",
        target_id: str = "e2",
        rel_type: str = "works_for",
        confidence: float = 0.85,
        direction: str = "subject_to_object",
        properties: Optional[Dict[str, Any]] = None,
    ):
        """Create Relationship with sensible defaults.
        
        Args:
            rel_id: Unique identifier
            source_id: Source entity ID
            target_id: Target entity ID
            rel_type: Relationship type
            confidence: Confidence score 0-1
            direction: Directionality (subject_to_object, undirected, unknown)
            properties: Optional metadata
            
        Returns:
            Relationship instance
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        return Relationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            confidence=confidence,
            direction=direction,
            properties=properties or {},
        )
    
    @staticmethod
    def undirected(rel_id: str = "r_undir") -> Any:
        """Create undirected relationship."""
        return RelationshipFactory.default(
            rel_id=rel_id,
            direction="undirected",
        )
    
    @staticmethod
    def unknown_direction(rel_id: str = "r_unknown") -> Any:
        """Create relationship with unknown direction."""
        return RelationshipFactory.default(
            rel_id=rel_id,
            direction="unknown",
        )
    
    @staticmethod
    def batch(
        count: int = 5,
        source_ids: Optional[List[str]] = None,
        target_ids: Optional[List[str]] = None,
    ) -> List[Any]:
        """Create multiple relationships.
        
        Args:
            count: Number of relationships to create
            source_ids: List of source entity IDs (cycles through)
            target_ids: List of target entity IDs (cycles through)
            
        Returns:
            List of Relationship instances
        """
        if source_ids is None:
            source_ids = [f"e{i}" for i in range(1, count + 1)]
        if target_ids is None:
            target_ids = [f"e{i}" for i in range(1, count + 1)]
        
        relationships = []
        for i in range(count):
            source = source_ids[i % len(source_ids)]
            target = target_ids[i % len(target_ids)]
            
            rel = RelationshipFactory.default(
                rel_id=f"r{i+1}",
                source_id=source,
                target_id=target,
                confidence=0.85 - (i * 0.05),  # Varying confidence
            )
            relationships.append(rel)
        
        return relationships


@dataclass
class OntologyFactory:
    """Factory for creating ontology dictionaries."""
    
    @staticmethod
    def minimal() -> Dict[str, Any]:
        """Create minimal ontology (1 entity, 0 relationships)."""
        return {
            "entities": [EntityFactory.default().to_dict()],
            "relationships": [],
        }
    
    @staticmethod
    def simple(
        num_entities: int = 3,
        num_relationships: int = 2,
    ) -> Dict[str, Any]:
        """Create simple ontology with configurable size.
        
        Args:
            num_entities: Number of entities (default: 3)
            num_relationships: Number of relationships (default: 2)
            
        Returns:
            Ontology dictionary
        """
        entities = EntityFactory.batch(count=num_entities)
        entity_ids = [e.id for e in entities]
        
        relationships = RelationshipFactory.batch(
            count=num_relationships,
            source_ids=entity_ids,
            target_ids=entity_ids,
        )
        
        return {
            "entities": [e.to_dict() for e in entities],
            "relationships": [r.to_dict() for r in relationships],
        }
    
    @staticmethod
    def complex(
        num_entities: int = 10,
        num_relationships: int = 15,
        entity_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create complex ontology with diverse entities.
        
        Args:
            num_entities: Number of entities
            num_relationships: Number of relationships
            entity_types: List of entity types to use (cycles through)
            
        Returns:
            Ontology dictionary
        """
        if entity_types is None:
            entity_types = ["Person", "Organization", "Location", "Event"]
        
        entities = []
        for i in range(num_entities):
            entity_type = entity_types[i % len(entity_types)]
            entity = EntityFactory.default(
                entity_id=f"e{i+1}",
                entity_type=entity_type,
                text=f"{entity_type}_{i+1}",
                confidence=0.7 + (i % 3) * 0.1,
            )
            entities.append(entity)
        
        entity_ids = [e.id for e in entities]
        relationships = RelationshipFactory.batch(
            count=num_relationships,
            source_ids=entity_ids,
            target_ids=entity_ids,
        )
        
        return {
            "entities": [e.to_dict() for e in entities],
            "relationships": [r.to_dict() for r in relationships],
        }
    
    @staticmethod
    def empty() -> Dict[str, Any]:
        """Create empty ontology (no entities, no relationships)."""
        return {"entities": [], "relationships": []}


@dataclass
class ExtractionResultFactory:
    """Factory for creating extraction result objects."""
    
    @staticmethod
    def default(
        num_entities: int = 5,
        num_relationships: int = 3,
        average_entity_confidence: float = 0.85,
    ) -> Dict[str, Any]:
        """Create extraction result with entities and relationships.
        
        Args:
            num_entities: Number of extracted entities
            num_relationships: Number of inferred relationships
            average_entity_confidence: Mean entity confidence
            
        Returns:
            Dictionary with 'entities' and 'relationships' keys
        """
        entities = []
        for i in range(num_entities):
            # Vary confidence around the mean
            confidence = average_entity_confidence + (i % 3 - 1) * 0.1
            confidence = max(0.1, min(1.0, confidence))
            
            entity = EntityFactory.default(
                entity_id=f"e{i+1}",
                text=f"Entity{i+1}",
                confidence=confidence,
            )
            entities.append(entity.to_dict())
        
        entity_ids = [e["id"] for e in entities]
        relationships = []
        for i in range(num_relationships):
            rel = RelationshipFactory.default(
                rel_id=f"r{i+1}",
                source_id=entity_ids[i % len(entity_ids)],
                target_id=entity_ids[(i + 1) % len(entity_ids)],
            )
            relationships.append(rel.to_dict())
        
        return {
            "entities": entities,
            "relationships": relationships,
        }


# ==============================================================================
# Pytest fixtures for easy use in tests
# ==============================================================================

@pytest.fixture
def entity_factory():
    """Provide EntityFactory to test functions."""
    return EntityFactory


@pytest.fixture
def relationship_factory():
    """Provide RelationshipFactory to test functions."""
    return RelationshipFactory


@pytest.fixture
def ontology_factory():
    """Provide OntologyFactory to test functions."""
    return OntologyFactory


@pytest.fixture
def extraction_result_factory():
    """Provide ExtractionResultFactory to test functions."""
    return ExtractionResultFactory


@pytest.fixture
def sample_entity():
    """Provide a sample default Entity."""
    return EntityFactory.default()


@pytest.fixture
def sample_relationship():
    """Provide a sample default Relationship."""
    return RelationshipFactory.default()


@pytest.fixture
def sample_ontology():
    """Provide a simple sample ontology."""
    return OntologyFactory.simple()


@pytest.fixture
def sample_extraction_result():
    """Provide a sample extraction result."""
    return ExtractionResultFactory.default()


if __name__ == "__main__":
    """Example usage."""
    # Create various ontologies
    minimal = OntologyFactory.minimal()
    simple = OntologyFactory.simple(num_entities=5, num_relationships=4)
    complex_ont = OntologyFactory.complex(num_entities=20, num_relationships=30)
    
    print("Minimal ontology:")
    print(f"  Entities: {len(minimal['entities'])}")
    print(f"  Relationships: {len(minimal['relationships'])}")
    
    print("\nSimple ontology:")
    print(f"  Entities: {len(simple['entities'])}")
    print(f"  Relationships: {len(simple['relationships'])}")
    
    print("\nComplex ontology:")
    print(f"  Entities: {len(complex_ont['entities'])}")
    print(f"  Relationships: {len(complex_ont['relationships'])}")
    
    # Create extraction result
    result = ExtractionResultFactory.default(num_entities=10, num_relationships=8)
    print(f"\nExtraction result:")
    print(f"  Entities: {len(result['entities'])}")
    print(f"  Relationships: {len(result['relationships'])}")
