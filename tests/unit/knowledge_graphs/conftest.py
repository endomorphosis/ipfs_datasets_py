"""
Shared fixtures for knowledge graphs tests.

This module provides common fixtures and utilities for testing
knowledge graph extraction, reasoning, and related functionality.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation,
)


@pytest.fixture
def sample_text():
    """Sample text for extraction tests."""
    return """
    Apple Inc. is an American multinational technology company 
    headquartered in Cupertino, California. Steve Jobs founded 
    Apple in 1976 with Steve Wozniak. The company produces popular 
    products including the iPhone and MacBook.
    """


@pytest.fixture
def simple_text():
    """Simple text for basic tests."""
    return "John Smith works at Microsoft in Seattle."


@pytest.fixture
def sample_entity():
    """Sample entity for testing."""
    return Entity(
        entity_id="e1",
        entity_type="organization",
        name="Apple Inc.",
        properties={"founded": "1976", "location": "Cupertino"},
        confidence=0.95
    )


@pytest.fixture
def sample_entities():
    """Sample entities for testing."""
    return [
        Entity(
            entity_id="e1",
            entity_type="organization",
            name="Apple Inc.",
            properties={"founded": "1976"},
            confidence=0.95
        ),
        Entity(
            entity_id="e2",
            entity_type="person",
            name="Steve Jobs",
            properties={"role": "founder"},
            confidence=0.98
        ),
        Entity(
            entity_id="e3",
            entity_type="location",
            name="Cupertino",
            properties={"state": "California"},
            confidence=0.92
        ),
    ]


@pytest.fixture
def sample_relationship(sample_entities):
    """Sample relationship for testing."""
    return Relationship(
        source_entity=sample_entities[1],  # Steve Jobs
        target_entity=sample_entities[0],  # Apple Inc.
        relationship_type="FOUNDED",
        properties={"year": "1976"},
        confidence=0.90
    )


@pytest.fixture
def sample_relationships(sample_entities):
    """Sample relationships for testing."""
    return [
        Relationship(
            source_entity=sample_entities[1],  # Steve Jobs
            target_entity=sample_entities[0],  # Apple Inc.
            relationship_type="FOUNDED",
            properties={"year": "1976"},
            confidence=0.90
        ),
        Relationship(
            source_entity=sample_entities[0],  # Apple Inc.
            target_entity=sample_entities[2],  # Cupertino
            relationship_type="LOCATED_IN",
            properties={},
            confidence=0.88
        ),
    ]


@pytest.fixture
def empty_knowledge_graph():
    """Empty knowledge graph for testing."""
    return KnowledgeGraph()


@pytest.fixture
def populated_knowledge_graph(sample_entities, sample_relationships):
    """Knowledge graph populated with sample data."""
    kg = KnowledgeGraph()
    for entity in sample_entities:
        kg.add_entity(entity)
    for relationship in sample_relationships:
        kg.add_relationship(relationship)
    return kg


@pytest.fixture
def basic_extractor():
    """Basic knowledge graph extractor instance."""
    return KnowledgeGraphExtractor()


@pytest.fixture
def validation_extractor():
    """Validation knowledge graph extractor instance."""
    return KnowledgeGraphExtractorWithValidation()


@pytest.fixture
def mock_wikipedia_response():
    """Mock Wikipedia API response for testing."""
    return {
        "query": {
            "pages": {
                "123": {
                    "title": "Apple Inc.",
                    "extract": "Apple Inc. is an American multinational technology company..."
                }
            }
        }
    }
