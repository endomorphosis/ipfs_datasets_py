"""
Tests for ProcessorProtocol and related classes.

Tests the core protocol interface and data structures used by all processors.
"""

import pytest
import numpy as np
from datetime import datetime

from ipfs_datasets_py.processors.protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    Entity,
    Relationship,
    VectorStore
)


class TestEntity:
    """Tests for Entity class."""
    
    def test_entity_creation(self):
        """
        GIVEN: Entity parameters
        WHEN: Creating an Entity
        THEN: Entity is created with correct attributes
        """
        entity = Entity(
            id="entity_1",
            type="Person",
            label="John Doe",
            properties={"age": 30, "location": "NYC"},
            confidence=0.95
        )
        
        assert entity.id == "entity_1"
        assert entity.type == "Person"
        assert entity.label == "John Doe"
        assert entity.properties["age"] == 30
        assert entity.confidence == 0.95
    
    def test_entity_confidence_validation(self):
        """
        GIVEN: Invalid confidence value
        WHEN: Creating an Entity
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            Entity(
                id="entity_1",
                type="Person",
                label="John Doe",
                confidence=1.5
            )


class TestKnowledgeGraph:
    """Tests for KnowledgeGraph class."""
    
    def test_add_entity(self):
        """
        GIVEN: A knowledge graph and entity
        WHEN: Adding entity to graph
        THEN: Entity is added successfully
        """
        kg = KnowledgeGraph()
        entity = Entity(id="e1", type="Person", label="John")
        
        kg.add_entity(entity)
        
        assert len(kg.entities) == 1
        assert kg.entities[0] == entity
    
    def test_find_entities_by_type(self):
        """
        GIVEN: A knowledge graph with multiple entities
        WHEN: Finding entities by type
        THEN: Only matching entities are returned
        """
        kg = KnowledgeGraph()
        kg.add_entity(Entity(id="e1", type="Person", label="John"))
        kg.add_entity(Entity(id="e2", type="Organization", label="ACME"))
        kg.add_entity(Entity(id="e3", type="Person", label="Jane"))
        
        persons = kg.find_entities("Person")
        
        assert len(persons) == 2
        assert all(e.type == "Person" for e in persons)


class TestVectorStore:
    """Tests for VectorStore class."""
    
    def test_add_embedding(self):
        """
        GIVEN: A vector store
        WHEN: Adding an embedding
        THEN: Embedding is stored with correct dimension
        """
        vectors = VectorStore()
        embedding = np.array([0.1, 0.2, 0.3])
        
        vectors.add_embedding("content_1", embedding)
        
        assert "content_1" in vectors.embeddings
        assert vectors.dimension == 3
        np.testing.assert_array_equal(vectors.embeddings["content_1"], embedding)
    
    def test_search_similarity(self):
        """
        GIVEN: A vector store with multiple embeddings
        WHEN: Searching for similar vectors
        THEN: Results are returned in order of similarity
        """
        vectors = VectorStore()
        
        # Add embeddings
        vectors.add_embedding("doc1", np.array([1.0, 0.0, 0.0]))
        vectors.add_embedding("doc2", np.array([0.9, 0.1, 0.0]))
        vectors.add_embedding("doc3", np.array([0.0, 1.0, 0.0]))
        
        # Search
        query = np.array([1.0, 0.0, 0.0])
        results = vectors.search(query, top_k=2)
        
        assert len(results) == 2
        assert results[0][0] == "doc1"
        assert results[0][1] > 0.9


class TestProcessorProtocol:
    """Tests for ProcessorProtocol interface."""
    
    def test_protocol_compliance(self):
        """
        GIVEN: A class implementing ProcessorProtocol
        WHEN: Checking protocol compliance
        THEN: Class is recognized as implementing the protocol
        """
        class TestProcessor:
            async def can_process(self, input_source):
                return True
            
            async def process(self, input_source, **options):
                return ProcessingResult(
                    knowledge_graph=KnowledgeGraph(),
                    vectors=VectorStore(),
                    content={},
                    metadata=ProcessingMetadata(processor_name="Test")
                )
            
            def get_supported_types(self):
                return ["test"]
        
        processor = TestProcessor()
        assert isinstance(processor, ProcessorProtocol)
