"""Tests for Neo4j graph loading integration.

This module tests the Neo4jGraphLoader which loads ontology extraction results
into Neo4j graph database. Tests cover:

- Configuration and connection
- Entity loading (entities → nodes)
- Relationship loading (relationships → edges)
- Bulk loading operations
- Complete extraction result loading
- Query helpers (get entity, neighborhood, deletion)
- Edge cases and error handling
"""

import pytest
from datetime import datetime
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.integrations.neo4j_loader import (
    Neo4jConfig,
    Neo4jGraphLoader,
    MockNeo4jDriver,
    MockNeo4jSession,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def neo4j_config() -> Neo4jConfig:
    """Create default Neo4j configuration for testing."""
    return Neo4jConfig(
        uri="bolt://localhost:7687",
        auth=("neo4j", "password"),
        database="neo4j",
        merge_strategy="MERGE",
    )


@pytest.fixture
def mock_driver() -> MockNeo4jDriver:
    """Create mock Neo4j driver."""
    return MockNeo4jDriver(uri="bolt://localhost:7687", auth=("neo4j", "password"))


@pytest.fixture
def loader(neo4j_config: Neo4jConfig, mock_driver: MockNeo4jDriver) -> Neo4jGraphLoader:
    """Create Neo4jGraphLoader with mock driver."""
    return Neo4jGraphLoader(config=neo4j_config, driver=mock_driver)


@pytest.fixture
def sample_entity() -> Dict[str, Any]:
    """Create a sample entity for testing."""
    return {
        "id": "e1",
        "text": "Alice",
        "type": "Person",
        "confidence": 0.95,
        "properties": {"age": 30, "city": "NYC"},
        "context": "Alice works at TechCorp",
    }


@pytest.fixture
def sample_relationship() -> Dict[str, Any]:
    """Create a sample relationship for testing."""
    return {
        "id": "r1",
        "source_id": "e1",
        "target_id": "e2",
        "type": "works_at",
        "confidence": 0.88,
        "properties": {"since": "2020"},
    }


@pytest.fixture
def sample_extraction_result() -> Dict[str, Any]:
    """Create a sample extraction result."""
    return {
        "ontology": {
            "entities": [
                {
                    "id": "e1",
                    "text": "Alice",
                    "type": "Person",
                    "confidence": 0.95,
                    "properties": {"age": 30},
                },
                {
                    "id": "e2",
                    "text": "TechCorp",
                    "type": "Organization",
                    "confidence": 0.90,
                    "properties": {"industry": "tech"},
                },
                {
                    "id": "e3",
                    "text": "Bob",
                    "type": "Person",
                    "confidence": 0.85,
                    "properties": {"age": 25},
                },
            ],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "works_at",
                    "confidence": 0.88,
                },
                {
                    "id": "r2",
                    "source_id": "e3",
                    "target_id": "e2",
                    "type": "works_at",
                    "confidence": 0.75,
                },
                {
                    "id": "r3",
                    "source_id": "e1",
                    "target_id": "e3",
                    "type": "knows",
                    "confidence": 0.92,
                },
            ],
        }
    }


# =============================================================================
# Test Cases: Configuration
# =============================================================================


class TestConfiguration:
    """Test Neo4j configuration and initialization."""

    def test_default_config(self):
        """Test default configuration values."""
        config = Neo4jConfig()
        assert config.uri == "bolt://localhost:7687"
        assert config.database == "neo4j"
        assert config.merge_strategy == "MERGE"
        assert config.node_label_prefix == "Entity"
        assert config.relationship_type_prefix == ""

    def test_custom_config(self):
        """Test custom configuration."""
        config = Neo4jConfig(
            uri="neo4j://remote:7687",
            database="custom_db",
            merge_strategy="CREATE",
            node_label_prefix="Node",
            relationship_type_prefix="REL_",
        )
        assert config.uri == "neo4j://remote:7687"
        assert config.database == "custom_db"
        assert config.merge_strategy == "CREATE"
        assert config.node_label_prefix == "Node"
        assert config.relationship_type_prefix == "REL_"

    def test_loader_initialization(self, neo4j_config: Neo4jConfig, mock_driver: MockNeo4jDriver):
        """Test loader initialization with config and driver."""
        loader = Neo4jGraphLoader(config=neo4j_config, driver=mock_driver)
        assert loader.config == neo4j_config
        assert loader.driver == mock_driver

    def test_loader_default_initialization(self):
        """Test loader initialization with defaults."""
        loader = Neo4jGraphLoader()
        assert loader.config is not None
        assert loader.driver is not None
        assert isinstance(loader.driver, MockNeo4jDriver)

    def test_context_manager(self, loader: Neo4jGraphLoader):
        """Test loader as context manager."""
        with loader as l:
            assert l == loader
        assert loader.driver.closed


# =============================================================================
# Test Cases: Entity Loading
# =============================================================================


class TestEntityLoading:
    """Test entity loading (entities → nodes)."""

    def test_load_single_entity(self, loader: Neo4jGraphLoader, sample_entity: Dict[str, Any]):
        """Test loading a single entity as a node."""
        entity_id = loader.load_entity(sample_entity, "ontology_001")
        assert entity_id == "e1"
        
        # Verify query was executed
        session = loader.driver._sessions[0]
        assert len(session.executed_queries) == 1
        query, params = session.executed_queries[0]
        assert "MERGE (n:Entity:Person" in query
        assert params["entity_id"] == "e1"
        assert params["properties"]["text"] == "Alice"
        assert params["properties"]["confidence"] == 0.95

    def test_load_entity_with_metadata(self, loader: Neo4jGraphLoader, sample_entity: Dict[str, Any]):
        """Test loading entity with metadata."""
        metadata = {"domain": "legal", "source": "contract.pdf"}
        entity_id = loader.load_entity(sample_entity, "ontology_001", metadata)
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["meta_domain"] == "legal"
        assert params["properties"]["meta_source"] == "contract.pdf"

    def test_load_entity_properties_prefixed(self, loader: Neo4jGraphLoader, sample_entity: Dict[str, Any]):
        """Test entity properties are prefixed with prop_."""
        loader.load_entity(sample_entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["prop_age"] == 30
        assert params["properties"]["prop_city"] == "NYC"

    def test_load_entity_node_label(self, loader: Neo4jGraphLoader):
        """Test node label construction from entity type."""
        entity = {"id": "e1", "text": "Test", "type": "Organization", "confidence": 0.8}
        loader.load_entity(entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert ":Entity:Organization" in query

    def test_load_entity_without_properties(self, loader: Neo4jGraphLoader):
        """Test loading entity without optional properties."""
        entity = {"id": "e1", "text": "Minimal", "type": "Thing", "confidence": 0.5}
        entity_id = loader.load_entity(entity, "ontology_001")
        assert entity_id == "e1"

    def test_bulk_load_entities(self, loader: Neo4jGraphLoader):
        """Test bulk loading multiple entities."""
        entities = [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            {"id": "e3", "text": "TechCorp", "type": "Organization", "confidence": 0.90},
        ]
        
        stats = loader.load_entities_bulk(entities, "ontology_001")
        assert stats["nodes_created"] == 3

    def test_bulk_load_entities_batching(self, loader: Neo4jGraphLoader):
        """Test bulk loading respects batch size."""
        entities = [
            {"id": f"e{i}", "text": f"Entity{i}", "type": "Thing", "confidence": 0.5}
            for i in range(10)
        ]
        
        stats = loader.load_entities_bulk(entities, "ontology_001", batch_size=3)
        assert stats["nodes_created"] == 10

    def test_bulk_load_empty_list(self, loader: Neo4jGraphLoader):
        """Test bulk loading empty entity list."""
        stats = loader.load_entities_bulk([], "ontology_001")
        assert stats["nodes_created"] == 0


# =============================================================================
# Test Cases: Relationship Loading
# =============================================================================


class TestRelationshipLoading:
    """Test relationship loading (relationships → edges)."""

    def test_load_single_relationship(self, loader: Neo4jGraphLoader, sample_relationship: Dict[str, Any]):
        """Test loading a single relationship as an edge."""
        rel_id = loader.load_relationship(sample_relationship, "ontology_001")
        assert rel_id == "r1"
        
        # Verify Cypher query
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "MATCH (source {entity_id: $source_id})" in query
        assert "MATCH (target {entity_id: $target_id})" in query
        assert "MERGE (source)-[r:WORKS_AT]->(target)" in query
        assert params["source_id"] == "e1"
        assert params["target_id"] == "e2"

    def test_load_relationship_type_normalization(self, loader: Neo4jGraphLoader):
        """Test relationship type normalization (uppercase, underscores)."""
        rel = {
            "id": "r1",
            "source_id": "e1",
            "target_id": "e2",
            "type": "works at",
            "confidence": 0.8,
        }
        loader.load_relationship(rel, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "WORKS_AT" in query

    def test_load_relationship_with_prefix(self):
        """Test relationship type prefix configuration."""
        config = Neo4jConfig(relationship_type_prefix="REL_")
        driver = MockNeo4jDriver(uri="bolt://localhost:7687")
        loader = Neo4jGraphLoader(config=config, driver=driver)
        
        rel = {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.9}
        loader.load_relationship(rel, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "REL_KNOWS" in query

    def test_load_relationship_with_metadata(self, loader: Neo4jGraphLoader, sample_relationship: Dict[str, Any]):
        """Test loading relationship with metadata."""
        metadata = {"domain": "social"}
        loader.load_relationship(sample_relationship, "ontology_001", metadata)
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["meta_domain"] == "social"

    def test_load_relationship_properties_prefixed(self, loader: Neo4jGraphLoader, sample_relationship: Dict[str, Any]):
        """Test relationship properties are prefixed."""
        loader.load_relationship(sample_relationship, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["prop_since"] == "2020"

    def test_bulk_load_relationships(self, loader: Neo4jGraphLoader):
        """Test bulk loading multiple relationships."""
        relationships = [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.9},
            {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "works_with", "confidence": 0.85},
            {"id": "r3", "source_id": "e1", "target_id": "e3", "type": "manages", "confidence": 0.80},
        ]
        
        stats = loader.load_relationships_bulk(relationships, "ontology_001")
        assert stats["edges_created"] == 3

    def test_bulk_load_relationships_batching(self, loader: Neo4jGraphLoader):
        """Test bulk relationship loading respects batch size."""
        relationships = [
            {"id": f"r{i}", "source_id": "e1", "target_id": "e2", "type": "test", "confidence": 0.5}
            for i in range(10)
        ]
        
        stats = loader.load_relationships_bulk(relationships, "ontology_001", batch_size=3)
        assert stats["edges_created"] == 10

    def test_bulk_load_empty_relationships(self, loader: Neo4jGraphLoader):
        """Test bulk loading empty relationship list."""
        stats = loader.load_relationships_bulk([], "ontology_001")
        assert stats["edges_created"] == 0


# =============================================================================
# Test Cases: Complete Extraction Result Loading
# =============================================================================


class TestExtractionResultLoading:
    """Test loading complete extraction results."""

    def test_load_extraction_result_complete(
        self, loader: Neo4jGraphLoader, sample_extraction_result: Dict[str, Any]
    ):
        """Test loading complete extraction result with entities and relationships."""
        stats = loader.load_extraction_result("ontology_001", sample_extraction_result)
        
        assert stats["ontology_id"] == "ontology_001"
        assert stats["nodes_created"] == 3  # 3 entities
        assert stats["edges_created"] == 3  # 3 relationships

    def test_load_extraction_result_with_metadata(
        self, loader: Neo4jGraphLoader, sample_extraction_result: Dict[str, Any]
    ):
        """Test loading extraction result with metadata."""
        metadata = {"domain": "employment", "source": "hr_system"}
        stats = loader.load_extraction_result("ontology_001", sample_extraction_result, metadata)
        
        assert stats["metadata"] == metadata

    def test_load_extraction_result_entities_only(self, loader: Neo4jGraphLoader):
        """Test loading extraction result with only entities (no relationships)."""
        result = {
            "ontology": {
                "entities": [
                    {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
                    {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
                ],
                "relationships": [],
            }
        }
        
        stats = loader.load_extraction_result("ontology_001", result)
        assert stats["nodes_created"] == 2
        assert stats["edges_created"] == 0

    def test_load_extraction_result_empty(self, loader: Neo4jGraphLoader):
        """Test loading empty extraction result."""
        result = {
            "ontology": {
                "entities": [],
                "relationships": [],
            }
        }
        
        stats = loader.load_extraction_result("ontology_001", result)
        assert stats["nodes_created"] == 0
        assert stats["edges_created"] == 0

    def test_load_extraction_result_custom_batch_size(
        self, loader: Neo4jGraphLoader, sample_extraction_result: Dict[str, Any]
    ):
        """Test loading with custom batch size."""
        stats = loader.load_extraction_result("ontology_001", sample_extraction_result, batch_size=2)
        assert stats["nodes_created"] == 3
        assert stats["edges_created"] == 3


# =============================================================================
# Test Cases: Query Helpers
# =============================================================================


class TestQueryHelpers:
    """Test graph query helper methods."""

    def test_get_entity(self, loader: Neo4jGraphLoader):
        """Test retrieving a single entity by ID."""
        entity = loader.get_entity("e1")
        # Mock returns None (no actual graph), test query execution
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "MATCH (n {entity_id: $entity_id})" in query
        assert params["entity_id"] == "e1"

    def test_get_entity_neighborhood_basic(self, loader: Neo4jGraphLoader):
        """Test getting entity neighborhood subgraph."""
        subgraph = loader.get_entity_neighborhood("e1", max_depth=1)
        
        assert subgraph["center"] == "e1"
        assert subgraph["depth"] == 1
        assert "nodes" in subgraph
        assert "edges" in subgraph

    def test_get_entity_neighborhood_multi_depth(self, loader: Neo4jGraphLoader):
        """Test neighborhood query with depth > 1."""
        subgraph = loader.get_entity_neighborhood("e1", max_depth=3)
        assert subgraph["depth"] == 3

    def test_get_entity_neighborhood_with_relationship_filter(self, loader: Neo4jGraphLoader):
        """Test neighborhood query with relationship type filter."""
        subgraph = loader.get_entity_neighborhood("e1", max_depth=2, relationship_types=["WORKS_AT", "KNOWS"])
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "WORKS_AT|KNOWS" in query

    def test_delete_ontology(self, loader: Neo4jGraphLoader):
        """Test deleting all nodes/edges for an ontology."""
        deleted_count = loader.delete_ontology("ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "MATCH (n {ontology_id: $ontology_id})" in query
        assert "DETACH DELETE n" in query
        assert params["ontology_id"] == "ontology_001"


# =============================================================================
# Test Cases: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_load_entity_minimal_fields(self, loader: Neo4jGraphLoader):
        """Test loading entity with only required fields."""
        entity = {"id": "e1", "type": "Thing", "confidence": 0.0}
        entity_id = loader.load_entity(entity, "ontology_001")
        assert entity_id == "e1"

    def test_load_relationship_minimal_fields(self, loader: Neo4jGraphLoader):
        """Test loading relationship with only required fields."""
        rel = {"id": "r1", "source_id": "e1", "target_id": "e2", "confidence": 0.0}
        rel_id = loader.load_relationship(rel, "ontology_001")
        assert rel_id == "r1"

    def test_load_entity_special_characters_in_id(self, loader: Neo4jGraphLoader):
        """Test entity ID with special characters."""
        entity = {"id": "e-123-abc_456", "text": "Test", "type": "Thing", "confidence": 0.5}
        entity_id = loader.load_entity(entity, "ontology_001")
        assert entity_id == "e-123-abc_456"

    def test_load_entity_unicode_text(self, loader: Neo4jGraphLoader):
        """Test entity with Unicode text."""
        entity = {"id": "e1", "text": "北京市", "type": "Location", "confidence": 0.9}
        loader.load_entity(entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["text"] == "北京市"

    def test_load_entity_confidence_zero(self, loader: Neo4jGraphLoader):
        """Test entity with zero confidence."""
        entity = {"id": "e1", "text": "Uncertain", "type": "Thing", "confidence": 0.0}
        loader.load_entity(entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["confidence"] == 0.0

    def test_load_entity_confidence_one(self, loader: Neo4jGraphLoader):
        """Test entity with maximum confidence."""
        entity = {"id": "e1", "text": "Certain", "type": "Thing", "confidence": 1.0}
        loader.load_entity(entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert params["properties"]["confidence"] == 1.0

    def test_create_strategy(self):
        """Test CREATE merge strategy instead of MERGE."""
        config = Neo4jConfig(merge_strategy="CREATE")
        driver = MockNeo4jDriver(uri="bolt://localhost:7687")
        loader = Neo4jGraphLoader(config=config, driver=driver)
        
        entity = {"id": "e1", "text": "Test", "type": "Thing", "confidence": 0.5}
        loader.load_entity(entity, "ontology_001")
        
        session = loader.driver._sessions[0]
        query, params = session.executed_queries[0]
        assert "CREATE (n:Entity:Thing" in query
        assert "MERGE" not in query


# =============================================================================
# Test Cases: Integration Scenarios
# =============================================================================


class TestIntegration:
    """Test realistic integration scenarios."""

    def test_load_multi_domain_ontology(self, loader: Neo4jGraphLoader):
        """Test loading ontology with multiple entity types."""
        result = {
            "ontology": {
                "entities": [
                    {"id": "p1", "text": "Alice", "type": "Person", "confidence": 0.95},
                    {"id": "o1", "text": "TechCorp", "type": "Organization", "confidence": 0.90},
                    {"id": "l1", "text": "New York", "type": "Location", "confidence": 0.88},
                ],
                "relationships": [
                    {"id": "r1", "source_id": "p1", "target_id": "o1", "type": "works_at", "confidence": 0.85},
                    {"id": "r2", "source_id": "o1", "target_id": "l1", "type": "located_in", "confidence": 0.80},
                ],
            }
        }
        
        stats = loader.load_extraction_result("ontology_multi", result)
        assert stats["nodes_created"] == 3
        assert stats["edges_created"] == 2

    def test_load_large_graph(self, loader: Neo4jGraphLoader):
        """Test loading large graph (100+ entities)."""
        entities = [
            {"id": f"e{i}", "text": f"Entity{i}", "type": "Thing", "confidence": 0.5 + (i % 50) * 0.01}
            for i in range(100)
        ]
        relationships = [
            {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{(i+1) % 100}", "type": "links_to", "confidence": 0.7}
            for i in range(100)
        ]
        
        result = {"ontology": {"entities": entities, "relationships": relationships}}
        stats = loader.load_extraction_result("large_graph", result, batch_size=20)
        
        assert stats["nodes_created"] == 100
        assert stats["edges_created"] == 100

    def test_incremental_loading(self, loader: Neo4jGraphLoader):
        """Test loading ontology incrementally (entities first, then relationships)."""
        # Load entities
        entities = [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
        ]
        entity_stats = loader.load_entities_bulk(entities, "ontology_inc")
        assert entity_stats["nodes_created"] == 2
        
        # Load relationships later
        relationships = [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.9},
        ]
        rel_stats = loader.load_relationships_bulk(relationships, "ontology_inc")
        assert rel_stats["edges_created"] == 1
