"""
Tests for Elasticsearch Integration - Batch 237 [integrations].

Comprehensive test coverage for Elasticsearch indexing integration:
    - Configuration and initialization
    - Index creation and management
    - Entity indexing (single and bulk)
    - Relationship indexing
    - Full extraction result indexing
    - Search functionality (entities and relationships)
    - Error handling and edge cases
    - Mock client behavior validation

Test Coverage:
    - Index creation with custom mappings
    - Document indexing with metadata
    - Bulk indexing operations
    - Search queries with filters
    - Missing field handling
    - Empty result handling
    - Large batch indexing
"""

import pytest
from datetime import datetime

from ipfs_datasets_py.optimizers.integrations.elasticsearch_indexer import (
    ElasticsearchIndexer,
    ElasticsearchConfig,
    MockElasticsearchClient,
    ENTITY_MAPPING,
    RELATIONSHIP_MAPPING,
    ONTOLOGY_MAPPING,
)


# ============================================================================
# Test Configuration
# ============================================================================


class TestElasticsearchConfig:
    """Test Elasticsearch configuration."""
    
    def test_default_config_creation(self):
        """Default configuration has expected values."""
        config = ElasticsearchConfig()
        
        assert config.hosts == ["http://localhost:9200"]
        assert config.index_prefix == "ontology"
        assert config.timeout == 30
        assert config.max_retries == 3
        assert config.use_ssl is False
        assert config.verify_certs is True
        assert config.http_auth is None
        assert config.create_indices_on_init is True
    
    def test_custom_config_creation(self):
        """Custom configuration values are preserved."""
        config = ElasticsearchConfig(
            hosts=["http://es1:9200", "http://es2:9200"],
            index_prefix="test",
            timeout=60,
            max_retries=5,
            use_ssl=True,
            verify_certs=False,
            http_auth=("user", "pass"),
            create_indices_on_init=False,
        )
        
        assert config.hosts == ["http://es1:9200", "http://es2:9200"]
        assert config.index_prefix == "test"
        assert config.timeout == 60
        assert config.max_retries == 5
        assert config.use_ssl is True
        assert config.verify_certs is False
        assert config.http_auth == ("user", "pass")
        assert config.create_indices_on_init is False


# ============================================================================
# Test Mock Client
# ============================================================================


class TestMockElasticsearchClient:
    """Test mock Elasticsearch client."""
    
    def test_mock_client_initialization(self):
        """Mock client initializes with hosts."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        
        assert client.hosts == ["http://localhost:9200"]
        assert client.indices_data == {}
        assert client.documents == {}
    
    def test_index_creation(self):
        """Mock client creates indices."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        
        response = client.indices_create(
            index="test-index",
            body={"mappings": {"properties": {"field": {"type": "text"}}}},
        )
        
        assert response["acknowledged"] is True
        assert response["index"] == "test-index"
        assert client.indices_exists(index="test-index") is True
    
    def test_document_indexing(self):
        """Mock client indexes documents."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        
        response = client.index(
            index="test-index",
            id="doc1",
            body={"text": "test document"},
        )
        
        assert response["_id"] == "doc1"
        assert response["result"] == "created"
        assert client.documents["test-index"]["doc1"]["text"] == "test document"
    
    def test_bulk_indexing(self):
        """Mock client performs bulk indexing."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        
        bulk_body = [
            {"index": {"_index": "test-index", "_id": "doc1"}},
            {"text": "document 1"},
            {"index": {"_index": "test-index", "_id": "doc2"}},
            {"text": "document 2"},
        ]
        
        response = client.bulk(body=bulk_body)
        
        assert response["errors"] is False
        assert len(response["items"]) == 2
        assert client.documents["test-index"]["doc1"]["text"] == "document 1"
        assert client.documents["test-index"]["doc2"]["text"] == "document 2"
    
    def test_search_documents(self):
        """Mock client searches documents."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        
        # Index test documents
        client.index("test-index", "doc1", {"text": "test"})
        client.index("test-index", "doc2", {"text": "another"})
        
        response = client.search(
            index="test-index",
            body={"query": {"match_all": {}}},
        )
        
        assert response["hits"]["total"]["value"] == 2
        assert len(response["hits"]["hits"]) == 2


# ============================================================================
# Test Indexer Initialization
# ============================================================================


class TestElasticsearchIndexerInit:
    """Test Elasticsearch indexer initialization."""
    
    def test_indexer_with_default_config(self):
        """Indexer initializes with default configuration."""
        indexer = ElasticsearchIndexer()
        
        assert indexer.config.hosts == ["http://localhost:9200"]
        assert indexer.entity_index == "ontology-entities"
        assert indexer.relationship_index == "ontology-relationships"
        assert indexer.ontology_index == "ontology-metadata"
    
    def test_indexer_with_custom_config(self):
        """Indexer initializes with custom configuration."""
        config = ElasticsearchConfig(
            hosts=["http://es:9200"],
            index_prefix="custom",
        )
        indexer = ElasticsearchIndexer(config=config)
        
        assert indexer.entity_index == "custom-entities"
        assert indexer.relationship_index == "custom-relationships"
        assert indexer.ontology_index == "custom-metadata"
    
    def test_indexer_with_custom_client(self):
        """Indexer accepts custom client."""
        client = MockElasticsearchClient(hosts=["http://custom:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        assert indexer.client is client
    
    def test_indexer_creates_indices_on_init(self):
        """Indexer creates indices on initialization."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        assert client.indices_exists("ontology-entities")
        assert client.indices_exists("ontology-relationships")
        assert client.indices_exists("ontology-metadata")
    
    def test_indexer_skips_index_creation_if_disabled(self):
        """Indexer skips index creation when disabled."""
        config = ElasticsearchConfig(create_indices_on_init=False)
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(config=config, client=client)
        
        assert not client.indices_exists("ontology-entities")


# ============================================================================
# Test Entity Indexing
# ============================================================================


class TestEntityIndexing:
    """Test entity indexing operations."""
    
    def test_index_single_entity(self):
        """Single entity is indexed correctly."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {
            "text": "Contract Agreement",
            "type": "LEGAL_DOCUMENT",
            "confidence": 0.95,
            "properties": {"category": "contract"},
        }
        
        entity_id = indexer.index_entity(
            ontology_id="doc_001",
            entity=entity,
            metadata={"domain": "legal"},
        )
        
        assert entity_id == "Contract Agreement"
        doc = client.documents[indexer.entity_index][entity_id]
        assert doc["text"] == "Contract Agreement"
        assert doc["entity_type"] == "LEGAL_DOCUMENT"
        assert doc["confidence"] == 0.95
        assert doc["domain"] == "legal"
    
    def test_index_entity_without_metadata(self):
        """Entity indexed without metadata uses defaults."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {"text": "Entity", "type": "GENERIC"}
        entity_id = indexer.index_entity("doc_001", entity)
        
        doc = client.documents[indexer.entity_index][entity_id]
        assert doc["domain"] == "unknown"
        assert doc["metadata"] == {}
    
    def test_index_entity_with_custom_id(self):
        """Entity with custom ID is indexed with provided ID."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {
            "id": "entity_custom_123",
            "text": "Custom Entity",
            "type": "CUSTOM",
        }
        
        entity_id = indexer.index_entity("doc_001", entity)
        assert entity_id == "entity_custom_123"
    
    def test_bulk_index_entities(self):
        """Multiple entities are bulk indexed."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entities = [
            {"text": "Entity 1", "type": "TYPE_A", "confidence": 0.9},
            {"text": "Entity 2", "type": "TYPE_B", "confidence": 0.8},
            {"text": "Entity 3", "type": "TYPE_A", "confidence": 0.85},
        ]
        
        result = indexer.bulk_index_entities(
            ontology_id="doc_001",
            entities=entities,
            metadata={"domain": "technical"},
        )
        
        assert result["indexed"] == 3
        assert result["errors"] is False
        assert len(client.documents[indexer.entity_index]) == 3
    
    def test_bulk_index_empty_list(self):
        """Bulk indexing empty list completes without error."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        result = indexer.bulk_index_entities("doc_001", [])
        
        assert result["indexed"] == 0


# ============================================================================
# Test Relationship Indexing
# ============================================================================


class TestRelationshipIndexing:
    """Test relationship indexing operations."""
    
    def test_index_single_relationship(self):
        """Single relationship is indexed correctly."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationship = {
            "source": "Entity A",
            "target": "Entity B",
            "type": "CONNECTS_TO",
            "confidence": 0.88,
            "properties": {"weight": 0.7},
        }
        
        rel_id = indexer.index_relationship(
            ontology_id="doc_001",
            relationship=relationship,
            metadata={"domain": "technical"},
        )
        
        assert rel_id == "Entity A_Entity B"
        doc = client.documents[indexer.relationship_index][rel_id]
        assert doc["source"] == "Entity A"
        assert doc["target"] == "Entity B"
        assert doc["relationship_type"] == "CONNECTS_TO"
        assert doc["confidence"] == 0.88
    
    def test_index_relationship_without_metadata(self):
        """Relationship indexed without metadata uses defaults."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationship = {
            "source": "A",
            "target": "B",
            "type": "RELATED",
        }
        
        rel_id = indexer.index_relationship("doc_001", relationship)
        
        doc = client.documents[indexer.relationship_index][rel_id]
        assert doc["domain"] == "unknown"
        assert doc["confidence"] == 0.0


# ============================================================================
# Test Full Extraction Result Indexing
# ============================================================================


class TestExtractionResultIndexing:
    """Test full extraction result indexing."""
    
    def test_index_extraction_result_complete(self):
        """Complete extraction result is indexed."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        result = {
            "entities": [
                {"text": "Contract", "type": "DOC", "confidence": 0.9},
                {"text": "Party A", "type": "PERSON", "confidence": 0.85},
            ],
            "relationships": [
                {"source": "Contract", "target": "Party A", "type": "SIGNED_BY"},
            ],
            "extraction_time_ms": 250.5,
            "confidence_avg": 0.875,
        }
        
        summary = indexer.index_extraction_result(
            ontology_id="doc_001",
            result=result,
            metadata={"domain": "legal", "source": "contract.pdf"},
        )
        
        assert summary["ontology_id"] == "doc_001"
        assert summary["entities_indexed"] == 2
        assert summary["relationships_indexed"] == 1
        assert len(summary["entity_ids"]) == 2
        assert len(summary["relationship_ids"]) == 1
        
        # Check ontology metadata indexed
        ontology_doc = client.documents[indexer.ontology_index]["doc_001"]
        assert ontology_doc["entity_count"] == 2
        assert ontology_doc["relationship_count"] == 1
        assert ontology_doc["domain"] == "legal"
    
    def test_index_extraction_result_entities_only(self):
        """Extraction result with only entities is indexed."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        result = {
            "entities": [
                {"text": "Entity 1", "type": "TYPE_A"},
            ],
            "relationships": [],
        }
        
        summary = indexer.index_extraction_result("doc_001", result)
        
        assert summary["entities_indexed"] == 1
        assert summary["relationships_indexed"] == 0
    
    def test_index_extraction_result_empty(self):
        """Empty extraction result is indexed."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        result = {"entities": [], "relationships": []}
        
        summary = indexer.index_extraction_result("doc_001", result)
        
        assert summary["entities_indexed"] == 0
        assert summary["relationships_indexed"] == 0


# ============================================================================
# Test Search Operations
# ============================================================================


class TestSearchOperations:
    """Test entity and relationship search."""
    
    def test_search_entities_basic(self):
        """Basic entity search returns results."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        # Index test entities
        entities = [
            {"text": "Contract Agreement", "type": "DOC", "confidence": 0.9},
            {"text": "Employment Contract", "type": "DOC", "confidence": 0.85},
        ]
        indexer.bulk_index_entities("doc_001", entities, {"domain": "legal"})
        
        # Search
        results = indexer.search_entities(query="contract", size=10)
        
        assert len(results) == 2
    
    def test_search_entities_with_domain_filter(self):
        """Entity search with domain filter."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        # Index entities from different domains
        legal_entities = [{"text": "Contract", "type": "DOC"}]
        medical_entities = [{"text": "Diagnosis", "type": "MED"}]
        
        indexer.bulk_index_entities("doc_001", legal_entities, {"domain": "legal"})
        indexer.bulk_index_entities("doc_002", medical_entities, {"domain": "medical"})
        
        # Search with filter (mock returns all, but query is constructed)
        results = indexer.search_entities(query="contract", domain="legal")
        
        # Mock returns all, but in real ES this would filter
        assert isinstance(results, list)
    
    def test_search_entities_with_type_filter(self):
        """Entity search with entity type filter."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entities = [
            {"text": "Contract", "type": "DOCUMENT"},
            {"text": "Party", "type": "PERSON"},
        ]
        indexer.bulk_index_entities("doc_001", entities)
        
        results = indexer.search_entities(query="entity", entity_type="DOCUMENT")
        
        assert isinstance(results, list)
    
    def test_search_entities_with_confidence_threshold(self):
        """Entity search with minimum confidence filter."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entities = [
            {"text": "High Confidence", "confidence": 0.9},
            {"text": "Low Confidence", "confidence": 0.3},
        ]
        indexer.bulk_index_entities("doc_001", entities)
        
        results = indexer.search_entities(query="confidence", min_confidence=0.7)
        
        assert isinstance(results, list)
    
    def test_search_relationships_by_source(self):
        """Search relationships by source entity."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationships = [
            {"source": "Entity A", "target": "Entity B", "type": "CONNECTS"},
            {"source": "Entity A", "target": "Entity C", "type": "CONNECTS"},
        ]
        
        for rel in relationships:
            indexer.index_relationship("doc_001", rel)
        
        results = indexer.search_relationships(source="Entity A")
        
        assert len(results) == 2
    
    def test_search_relationships_by_target(self):
        """Search relationships by target entity."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationships = [
            {"source": "A", "target": "Target", "type": "CONNECTS"},
            {"source": "B", "target": "Target", "type": "CONNECTS"},
        ]
        
        for rel in relationships:
            indexer.index_relationship("doc_001", rel)
        
        results = indexer.search_relationships(target="Target")
        
        assert len(results) == 2
    
    def test_search_relationships_by_type(self):
        """Search relationships by relationship type."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationships = [
            {"source": "A", "target": "B", "type": "CONNECTS"},
            {"source": "C", "target": "D", "type": "DEPENDS_ON"},
        ]
        
        for rel in relationships:
            indexer.index_relationship("doc_001", rel)
        
        results = indexer.search_relationships(relationship_type="CONNECTS")
        
        assert isinstance(results, list)
    
    def test_search_relationships_no_filters(self):
        """Search relationships without filters returns all."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationships = [
            {"source": "A", "target": "B", "type": "TYPE1"},
            {"source": "C", "target": "D", "type": "TYPE2"},
        ]
        
        for rel in relationships:
            indexer.index_relationship("doc_001", rel)
        
        results = indexer.search_relationships()
        
        assert len(results) == 2


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_index_entity_missing_required_fields(self):
        """Entity with missing fields uses defaults."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {"text": "Minimal Entity"}  # Missing type, confidence
        entity_id = indexer.index_entity("doc_001", entity)
        
        doc = client.documents[indexer.entity_index][entity_id]
        assert doc["entity_type"] == "unknown"
        assert doc["confidence"] == 0.0
    
    def test_index_relationship_missing_optional_fields(self):
        """Relationship with missing fields uses defaults."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        relationship = {
            "source": "A",
            "target": "B",
            # Missing type, confidence, properties
        }
        
        rel_id = indexer.index_relationship("doc_001", relationship)
        
        doc = client.documents[indexer.relationship_index][rel_id]
        assert doc["relationship_type"] == "unknown"
        assert doc["confidence"] == 0.0
        assert doc["properties"] == {}
    
    def test_large_batch_indexing(self):
        """Large batch of entities is indexed."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        # Create 100 entities
        entities = [
            {"text": f"Entity {i}", "type": "TYPE", "confidence": 0.8}
            for i in range(100)
        ]
        
        result = indexer.bulk_index_entities("doc_001", entities)
        
        assert result["indexed"] == 100
        assert len(client.documents[indexer.entity_index]) == 100
    
    def test_unicode_entity_text(self):
        """Entity with unicode text is indexed correctly."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {"text": "Ü니코드 Entity 中文", "type": "UNICODE"}
        entity_id = indexer.index_entity("doc_001", entity)
        
        doc = client.documents[indexer.entity_index][entity_id]
        assert doc["text"] == "Ü니코드 Entity 中文"
    
    def test_special_characters_in_entity_id(self):
        """Entity with special characters in ID is handled."""
        client = MockElasticsearchClient(hosts=["http://localhost:9200"])
        indexer = ElasticsearchIndexer(client=client)
        
        entity = {"text": "Entity / with : special & chars", "type": "SPECIAL"}
        entity_id = indexer.index_entity("doc_001", entity)
        
        # Should use text as ID
        assert entity_id in client.documents[indexer.entity_index]
