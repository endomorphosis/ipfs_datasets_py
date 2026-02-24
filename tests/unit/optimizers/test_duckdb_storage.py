"""
Tests for DuckDB + Parquet Storage Backend - Batch 246 [integrations].

Comprehensive test coverage for DuckDB storage including:
- Storage configuration and initialization
- Entity CRUD operations
- Relationship CRUD operations
- Extraction result storage
- Query building with filters
- Transactions and rollback
- Bulk operations
- Statistics aggregation
- Pagination
- Thread safety
- Edge cases

Test Coverage:
    - Schema validation
    - Insert operations
    - Query operations with filters/limits/offsets
    - Update operations
    - Delete operations
    - Transactions
    - Bulk inserts
    - Statistics
    - Pagination
    - Thread safety
    - Edge cases (large data, special characters, etc.)
"""

import pytest
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any

from ipfs_datasets_py.optimizers.integrations.duckdb_storage import (
    DuckDBStorage, StorageConfig, CompressionType,
    EntitySchema, RelationshipSchema, ExtractionResultSchema,
    QueryBuilder
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test database."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def storage_config(temp_db_dir):
    """Create storage configuration."""
    return StorageConfig(
        db_dir=temp_db_dir,
        compression=CompressionType.SNAPPY,
        batch_size=100,
        threads=4
    )


@pytest.fixture
def storage(storage_config):
    """Create storage instance."""
    return DuckDBStorage(storage_config)


# ============================================================================
# Test Configuration and Schema
# ============================================================================


class TestStorageConfig:
    """Test storage configuration."""
    
    def test_create_config(self, temp_db_dir):
        """Create storage configuration."""
        config = StorageConfig(
            db_dir=temp_db_dir,
            compression=CompressionType.GZIP,
            batch_size=500
        )
        
        assert config.db_dir == temp_db_dir
        assert config.compression == CompressionType.GZIP
        assert config.batch_size == 500
        assert config.auto_sync is True
    
    def test_compression_types(self):
        """All compression types defined."""
        assert CompressionType.SNAPPY.value == "snappy"
        assert CompressionType.GZIP.value == "gzip"
        assert CompressionType.BROTLI.value == "brotli"
        assert CompressionType.ZSTD.value == "zstd"
        assert CompressionType.UNCOMPRESSED.value == "uncompressed"


class TestEntitySchema:
    """Test entity schema."""
    
    def test_create_entity_schema(self):
        """Create entity schema."""
        entity = EntitySchema(
            id='entity_1',
            text='John Doe',
            type='PERSON',
            confidence=0.95,
            domain='legal'
        )
        
        assert entity.id == 'entity_1'
        assert entity.text == 'John Doe'
        assert entity.type == 'PERSON'
        assert entity.confidence == 0.95
    
    def test_entity_with_properties(self):
        """Entity can have properties and metadata."""
        entity = EntitySchema(
            id='org_1',
            text='TechCorp Inc',
            type='ORGANIZATION',
            confidence=0.92,
            properties={'employees': 5000, 'founded': 2010},
            metadata={'source': 'database', 'version': 1}
        )
        
        assert entity.properties == {'employees': 5000, 'founded': 2010}
        assert entity.metadata == {'source': 'database', 'version': 1}


# ============================================================================
# Test QueryBuilder
# ============================================================================


class TestQueryBuilder:
    """Test SQL query building."""
    
    def test_build_simple_select(self):
        """Build simple SELECT query."""
        query, params = QueryBuilder.build_select('entities')
        
        assert 'SELECT' in query
        assert 'FROM entities' in query
        assert len(params) == 0
    
    def test_build_select_with_columns(self):
        """Build SELECT with specific columns."""
        query, params = QueryBuilder.build_select(
            'entities',
            columns=['id', 'text', 'confidence']
        )
        
        assert 'id' in query
        assert 'text' in query
        assert 'confidence' in query
    
    def test_build_select_with_equality_filter(self):
        """Build SELECT with equality filter."""
        query, params = QueryBuilder.build_select(
            'entities',
            filters={'type': 'PERSON'}
        )
        
        assert 'WHERE' in query
        assert 'type' in query
        assert params == ['PERSON']
    
    def test_build_select_with_comparison_filter(self):
        """Build SELECT with comparison filter."""
        filters = {'confidence': {'>=': 0.8}}
        query, params = QueryBuilder.build_select(
            'entities',
            filters=filters
        )
        
        assert 'WHERE' in query
        assert '>=' in query
        assert 0.8 in params
    
    def test_build_select_with_in_filter(self):
        """Build SELECT with IN filter."""
        filters = {'type': ['PERSON', 'ORGANIZATION', 'LOCATION']}
        query, params = QueryBuilder.build_select(
            'entities',
            filters=filters
        )
        
        assert 'IN' in query
        assert 'PERSON' in params
        assert len(params) == 3
    
    def test_build_select_with_limit_offset(self):
        """Build SELECT with LIMIT and OFFSET."""
        query, params = QueryBuilder.build_select(
            'entities',
            limit=10,
            offset=50
        )
        
        assert 'LIMIT' in query
        assert 'OFFSET' in query
    
    def test_build_insert(self):
        """Build INSERT query."""
        columns = ['id', 'text', 'type', 'confidence']
        query = QueryBuilder.build_insert('entities', columns)
        
        assert 'INSERT INTO' in query
        assert 'entities' in query
        assert len(query.split('?')) == 5  # 4 params + 1
    
    def test_build_delete(self):
        """Build DELETE query."""
        query, params = QueryBuilder.build_delete(
            'entities',
            {'id': 'entity_1'}
        )
        
        assert 'DELETE' in query
        assert 'FROM entities' in query
        assert 'entity_1' in params


# ============================================================================
# Test Entity Operations
# ============================================================================


class TestEntityOperations:
    """Test entity CRUD operations."""
    
    def test_insert_entity(self, storage):
        """Insert entity into storage."""
        entity = {
            'id': 'e1',
            'text': 'John Doe',
            'type': 'PERSON',
            'confidence': 0.95
        }
        
        entity_id = storage.insert_entity(entity)
        
        assert entity_id == 'e1'
        assert storage.count_entities() == 1
    
    def test_get_entity(self, storage):
        """Get entity by ID."""
        entity = {
            'id': 'e1',
            'text': 'Alice',
            'type': 'PERSON',
            'confidence': 0.9
        }
        
        storage.insert_entity(entity)
        retrieved = storage.get_entity('e1')
        
        assert retrieved is not None
        assert retrieved['text'] == 'Alice'
        assert retrieved['confidence'] == 0.9
    
    def test_get_nonexistent_entity(self, storage):
        """Get nonexistent entity returns None."""
        retrieved = storage.get_entity('nonexistent')
        assert retrieved is None
    
    def test_query_entities_all(self, storage):
        """Query all entities."""
        entities = [
            {'id': 'e1', 'text': 'Alice', 'type': 'PERSON', 'confidence': 0.95},
            {'id': 'e2', 'text': 'Bob', 'type': 'PERSON', 'confidence': 0.85},
            {'id': 'e3', 'text': 'TechCorp', 'type': 'ORGANIZATION', 'confidence': 0.92}
        ]
        
        for entity in entities:
            storage.insert_entity(entity)
        
        results = storage.query_entities()
        assert len(results) == 3
    
    def test_query_entities_with_type_filter(self, storage):
        """Query entities filtered by type."""
        entities = [
            {'id': 'e1', 'text': 'Alice', 'type': 'PERSON', 'confidence': 0.95},
            {'id': 'e2', 'text': 'Bob', 'type': 'PERSON', 'confidence': 0.85},
            {'id': 'e3', 'text': 'TechCorp', 'type': 'ORGANIZATION', 'confidence': 0.92}
        ]
        
        for entity in entities:
            storage.insert_entity(entity)
        
        results = storage.query_entities(filters={'type': 'PERSON'})
        assert len(results) == 2
        assert all(r['type'] == 'PERSON' for r in results)
    
    def test_query_entities_with_confidence_filter(self, storage):
        """Query entities with confidence range."""
        entities = [
            {'id': 'e1', 'text': 'Alice', 'type': 'PERSON', 'confidence': 0.95},
            {'id': 'e2', 'text': 'Bob', 'type': 'PERSON', 'confidence': 0.85},
            {'id': 'e3', 'text': 'Charlie', 'type': 'PERSON', 'confidence': 0.65}
        ]
        
        for entity in entities:
            storage.insert_entity(entity)
        
        results = storage.query_entities(
            filters={'confidence': ('>=', 0.8)}
        )
        assert len(results) == 2
        assert all(r['confidence'] >= 0.8 for r in results)
    
    def test_query_entities_with_limit(self, storage):
        """Query with limit."""
        for i in range(10):
            storage.insert_entity({
                'id': f'e{i}',
                'text': f'Entity {i}',
                'type': 'PERSON',
                'confidence': 0.9
            })
        
        results = storage.query_entities(limit=3)
        assert len(results) == 3
    
    def test_query_entities_with_offset(self, storage):
        """Query with offset for pagination."""
        for i in range(10):
            storage.insert_entity({
                'id': f'e{i}',
                'text': f'Entity {i}',
                'type': 'PERSON',
                'confidence': 0.9
            })
        
        page1 = storage.query_entities(limit=3, offset=0)
        page2 = storage.query_entities(limit=3, offset=3)
        
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]['id'] != page2[0]['id']
    
    def test_update_entity(self, storage):
        """Update entity fields."""
        storage.insert_entity({
            'id': 'e1',
            'text': 'Alice',
            'type': 'PERSON',
            'confidence': 0.8
        })
        
        success = storage.update_entity('e1', {'confidence': 0.95})
        assert success is True
        
        updated = storage.get_entity('e1')
        assert updated['confidence'] == 0.95
    
    def test_delete_entity(self, storage):
        """Delete entity."""
        storage.insert_entity({
            'id': 'e1',
            'text': 'Alice',
            'type': 'PERSON',
            'confidence': 0.9
        })
        
        assert storage.count_entities() == 1
        
        deleted = storage.delete_entity('e1')
        assert deleted is True
        assert storage.count_entities() == 0
    
    def test_delete_nonexistent_entity(self, storage):
        """Delete nonexistent entity returns False."""
        deleted = storage.delete_entity('nonexistent')
        assert deleted is False


# ============================================================================
# Test Relationship Operations
# ============================================================================


class TestRelationshipOperations:
    """Test relationship CRUD operations."""
    
    def test_insert_relationship(self, storage):
        """Insert relationship."""
        rel = {
            'id': 'r1',
            'source_id': 'e1',
            'target_id': 'e2',
            'type': 'WORKS_FOR',
            'confidence': 0.9
        }
        
        rel_id = storage.insert_relationship(rel)
        
        assert rel_id == 'r1'
        assert storage.count_relationships() == 1
    
    def test_get_relationship(self, storage):
        """Get relationship by ID."""
        rel = {
            'id': 'r1',
            'source_id': 'e1',
            'target_id': 'e2',
            'type': 'WORKS_FOR',
            'confidence': 0.92
        }
        
        storage.insert_relationship(rel)
        retrieved = storage.get_relationship('r1')
        
        assert retrieved is not None
        assert retrieved['source_id'] == 'e1'
        assert retrieved['target_id'] == 'e2'
    
    def test_query_relationships(self, storage):
        """Query relationships."""
        relationships = [
            {'id': 'r1', 'source_id': 'e1', 'target_id': 'e2', 'type': 'WORKS_FOR', 'confidence': 0.9},
            {'id': 'r2', 'source_id': 'e2', 'target_id': 'e3', 'type': 'MANAGES', 'confidence': 0.85},
        ]
        
        for rel in relationships:
            storage.insert_relationship(rel)
        
        results = storage.query_relationships()
        assert len(results) == 2
    
    def test_query_relationships_by_source(self, storage):
        """Query relationships by source entity."""
        storage.insert_relationship({
            'id': 'r1',
            'source_id': 'e1',
            'target_id': 'e2',
            'type': 'WORKS_FOR',
            'confidence': 0.9
        })
        
        storage.insert_relationship({
            'id': 'r2',
            'source_id': 'e2',
            'target_id': 'e3',
            'type': 'MANAGES',
            'confidence': 0.85
        })
        
        results = storage.query_relationships(
            filters={'source_id': 'e1'}
        )
        assert len(results) == 1
        assert results[0]['source_id'] == 'e1'
    
    def test_delete_relationship(self, storage):
        """Delete relationship."""
        storage.insert_relationship({
            'id': 'r1',
            'source_id': 'e1',
            'target_id': 'e2',
            'type': 'WORKS_FOR',
            'confidence': 0.9
        })
        
        assert storage.count_relationships() == 1
        
        deleted = storage.delete_relationship('r1')
        assert deleted is True
        assert storage.count_relationships() == 0


# ============================================================================
# Test Extraction Results
# ============================================================================


class TestExtractionResults:
    """Test extraction result operations."""
    
    def test_insert_extraction_result(self, storage):
        """Insert extraction result."""
        result = {
            'id': 'res1',
            'source_text': 'Alice works for TechCorp',
            'entity_count': 2,
            'relationship_count': 1,
            'confidence_avg': 0.92
        }
        
        result_id = storage.insert_extraction_result(result)
        
        assert result_id == 'res1'
    
    def test_query_results(self, storage):
        """Query extraction results."""
        results_data = [
            {
                'id': 'res1',
                'source_text': 'Text 1',
                'entity_count': 2,
                'relationship_count': 1,
                'confidence_avg': 0.9
            },
            {
                'id': 'res2',
                'source_text': 'Text 2',
                'entity_count': 3,
                'relationship_count': 2,
                'confidence_avg': 0.85
            }
        ]
        
        for result in results_data:
            storage.insert_extraction_result(result)
        
        results = storage.query_results()
        assert len(results) == 2


# ============================================================================
# Test Bulk Operations
# ============================================================================


class TestBulkOperations:
    """Test bulk insert operations."""
    
    def test_bulk_insert_entities(self, storage):
        """Bulk insert multiple entities."""
        entities = [
            {'id': f'e{i}', 'text': f'Entity {i}', 'type': 'PERSON', 'confidence': 0.9}
            for i in range(50)
        ]
        
        ids = storage.bulk_insert_entities(entities)
        
        assert len(ids) == 50
        assert storage.count_entities() == 50
    
    def test_bulk_insert_relationships(self, storage):
        """Bulk insert multiple relationships."""
        relationships = [
            {
                'id': f'r{i}',
                'source_id': f'e{i}',
                'target_id': f'e{i+1}',
                'type': 'LINKS_TO',
                'confidence': 0.85
            }
            for i in range(30)
        ]
        
        ids = storage.bulk_insert_relationships(relationships)
        
        assert len(ids) == 30
        assert storage.count_relationships() == 30


# ============================================================================
# Test Transactions
# ============================================================================


class TestTransactions:
    """Test transaction support."""
    
    def test_transaction_commit(self, storage):
        """Transaction commits successfully."""
        storage.begin_transaction()
        
        storage.insert_entity({
            'id': 'e1',
            'text': 'Alice',
            'type': 'PERSON',
            'confidence': 0.9
        })
        
        storage.commit_transaction()
        
        assert storage.count_entities() == 1
    
    def test_transaction_rollback(self, storage):
        """Transaction rollback reverts changes."""
        storage.insert_entity({
            'id': 'e0',
            'text': 'Initial',
            'type': 'PERSON',
            'confidence': 0.9
        })
        
        storage.begin_transaction()
        
        storage.insert_entity({
            'id': 'e1',
            'text': 'Alice',
            'type': 'PERSON',
            'confidence': 0.9
        })
        
        assert storage.count_entities() == 2
        
        storage.rollback_transaction()
        
        # Should be back to 1 entity
        assert storage.count_entities() == 1
    
    def test_cannot_nest_transactions(self, storage):
        """Cannot nest transactions."""
        storage.begin_transaction()
        
        with pytest.raises(RuntimeError):
            storage.begin_transaction()
        
        storage.rollback_transaction()
    
    def test_commit_without_transaction(self, storage):
        """Commit without active transaction."""
        with pytest.raises(RuntimeError):
            storage.commit_transaction()


# ============================================================================
# Test Statistics
# ============================================================================


class TestStatistics:
    """Test statistics aggregation."""
    
    def test_aggregate_statistics(self, storage):
        """Get aggregate statistics."""
        # Add entities
        for i in range(10):
            storage.insert_entity({
                'id': f'e{i}',
                'text': f'Entity {i}',
                'type': 'PERSON' if i % 2 == 0 else 'ORGANIZATION',
                'confidence': 0.7 + (i / 100)
            })
        
        # Add relationships
        for i in range(5):
            storage.insert_relationship({
                'id': f'r{i}',
                'source_id': f'e{i}',
                'target_id': f'e{i+1}',
                'type': 'LINKS_TO',
                'confidence': 0.8 + (i / 100)
            })
        
        stats = storage.aggregate_statistics()
        
        assert stats['entities']['count'] == 10
        assert stats['relationships']['count'] == 5
        assert stats['entities']['avg_confidence'] > 0
        assert 'PERSON' in stats['entities']['types']
        assert 'ORGANIZATION' in stats['entities']['types']
    
    def test_count_with_filters(self, storage):
        """Count with filters."""
        for i in range(10):
            storage.insert_entity({
                'id': f'e{i}',
                'text': f'Entity {i}',
                'type': 'PERSON' if i < 5 else 'ORGANIZATION',
                'confidence': 0.9
            })
        
        person_count = storage.count_entities(filters={'type': 'PERSON'})
        org_count = storage.count_entities(filters={'type': 'ORGANIZATION'})
        
        assert person_count == 5
        assert org_count == 5


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases."""
    
    def test_empty_storage(self, storage):
        """Empty storage queries."""
        assert storage.count_entities() == 0
        assert storage.count_relationships() == 0
        assert storage.query_entities() == []
    
    def test_entity_with_special_characters(self, storage):
        """Entity with special characters in text."""
        storage.insert_entity({
            'id': 'e1',
            'text': 'José García-López @Twitter #NLP',
            'type': 'PERSON',
            'confidence': 0.9
        })
        
        retrieved = storage.get_entity('e1')
        assert 'José' in retrieved['text']
        assert '@Twitter' in retrieved['text']
    
    def test_entity_with_unicode(self, storage):
        """Entity with unicode characters."""
        storage.insert_entity({
            'id': 'e1',
            'text': '日本語テキスト中文ελληνικά',
            'type': 'LOCATION',
            'confidence': 0.85
        })
        
        retrieved = storage.get_entity('e1')
        assert '日本語' in retrieved['text']
    
    def test_entity_with_empty_properties(self, storage):
        """Entity with empty properties."""
        storage.insert_entity({
            'id': 'e1',
            'text': 'Name',
            'type': 'PERSON',
            'confidence': 0.9,
            'properties': {},
            'metadata': {}
        })
        
        retrieved = storage.get_entity('e1')
        assert retrieved['properties'] == {}
        assert retrieved['metadata'] == {}
    
    def test_context_manager(self, storage_config):
        """Storage works as context manager."""
        with DuckDBStorage(storage_config) as storage:
            storage.insert_entity({
                'id': 'e1',
                'text': 'Test',
                'type': 'PERSON',
                'confidence': 0.9
            })
            
            assert storage.count_entities() == 1


# ============================================================================
# Test Thread Safety
# ============================================================================


class TestThreadSafety:
    """Test thread-safe operations."""
    
    def test_concurrent_inserts(self, storage):
        """Multiple threads can insert concurrently."""
        def insert_entities(start, count):
            for i in range(start, start + count):
                storage.insert_entity({
                    'id': f'e{i}',
                    'text': f'Entity {i}',
                    'type': 'PERSON',
                    'confidence': 0.9
                })
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=insert_entities, args=(i * 20, 20))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have 100 entities
        assert storage.count_entities() == 100
    
    def test_concurrent_reads(self, storage):
        """Multiple threads can read concurrently."""
        # Populate storage
        for i in range(50):
            storage.insert_entity({
                'id': f'e{i}',
                'text': f'Entity {i}',
                'type': 'PERSON',
                'confidence': 0.9
            })
        
        results = []
        
        def query_entities():
            res = storage.query_entities()
            results.append(len(res))
        
        threads = []
        for _ in range(5):
            t = threading.Thread(target=query_entities)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All threads should see same results
        assert all(r == 50 for r in results)
