"""
Tests for Knowledge Graph Indexing and Constraints (Phase 5)
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.indexing import (
    IndexManager,
    PropertyIndex,
    LabelIndex,
    CompositeIndex,
    FullTextIndex,
    SpatialIndex,
    VectorIndex,
    RangeIndex,
)
from ipfs_datasets_py.knowledge_graphs.constraints import (
    ConstraintManager,
    UniqueConstraint,
    ExistenceConstraint,
    TypeConstraint,
    ConstraintViolation,
)


class TestPropertyIndex:
    """Test property indexing."""
    
    def test_create_and_search(self):
        """Test creating index and searching."""
        # GIVEN a property index
        index = PropertyIndex("name")
        
        # WHEN inserting and searching
        index.insert("Alice", "entity_1")
        index.insert("Bob", "entity_2")
        
        # THEN should find entities
        results = index.search("Alice")
        assert "entity_1" in results
        assert "entity_2" not in results
    
    def test_multiple_values_same_key(self):
        """Test multiple entities with same property value."""
        # GIVEN a property index
        index = PropertyIndex("age")
        
        # WHEN multiple entities have same value
        index.insert(30, "entity_1")
        index.insert(30, "entity_2")
        index.insert(25, "entity_3")
        
        # THEN search should return all matches
        results = index.search(30)
        assert len(results) == 2
        assert "entity_1" in results
        assert "entity_2" in results


class TestCompositeIndex:
    """Test composite indexing."""
    
    def test_composite_key(self):
        """Test indexing on multiple properties."""
        # GIVEN a composite index
        index = CompositeIndex(["first_name", "last_name"])
        
        # WHEN inserting with composite keys
        index.insert_composite(["Alice", "Smith"], "entity_1")
        index.insert_composite(["Bob", "Jones"], "entity_2")
        
        # THEN should find by composite key
        results = index.search_composite(["Alice", "Smith"])
        assert "entity_1" in results
        assert "entity_2" not in results


class TestRangeIndex:
    """Test range indexing."""
    
    def test_range_query(self):
        """Test range queries."""
        # GIVEN a range index with values
        index = RangeIndex("age")
        index.insert(25, "entity_1")
        index.insert(30, "entity_2")
        index.insert(35, "entity_3")
        index.insert(40, "entity_4")
        
        # WHEN searching a range
        results = index.range_search(28, 36)
        
        # THEN should return entities in range
        assert "entity_2" in results  # 30
        assert "entity_3" in results  # 35
        assert "entity_1" not in results  # 25
        assert "entity_4" not in results  # 40


class TestFullTextIndex:
    """Test full-text search."""
    
    def test_text_search(self):
        """Test basic text search."""
        # GIVEN a full-text index
        index = FullTextIndex("description")
        
        # WHEN indexing documents
        index.insert("The quick brown fox jumps over the lazy dog", "doc_1")
        index.insert("A quick brown dog runs in the park", "doc_2")
        index.insert("The lazy cat sleeps on the mat", "doc_3")
        
        # THEN should find relevant documents
        results = index.search("quick brown", limit=10)
        entity_ids = [r[0] for r in results]
        
        assert "doc_1" in entity_ids
        assert "doc_2" in entity_ids
        assert "doc_3" not in entity_ids
    
    def test_scoring(self):
        """Test that results are scored."""
        # GIVEN a full-text index
        index = FullTextIndex("text")
        
        # WHEN indexing with varying relevance
        index.insert("machine learning algorithms", "doc_1")
        index.insert("learning to code", "doc_2")
        
        # THEN results should have scores
        results = index.search("learning")
        assert len(results) > 0
        assert all(isinstance(r[1], float) for r in results)


class TestSpatialIndex:
    """Test spatial indexing."""
    
    def test_radius_search(self):
        """Test searching within radius."""
        # GIVEN a spatial index
        index = SpatialIndex("location", grid_size=1.0)
        
        # WHEN inserting locations
        index.insert((0.0, 0.0), "loc_1")
        index.insert((1.0, 1.0), "loc_2")
        index.insert((5.0, 5.0), "loc_3")
        
        # THEN should find within radius
        results = index.search_radius((0.0, 0.0), radius=2.0)
        entity_ids = [r[0] for r in results]
        
        assert "loc_1" in entity_ids
        assert "loc_2" in entity_ids
        assert "loc_3" not in entity_ids


class TestVectorIndex:
    """Test vector similarity indexing."""
    
    def test_vector_search(self):
        """Test k-NN search."""
        # GIVEN a vector index
        index = VectorIndex("embedding", dimension=3)
        
        # WHEN inserting vectors
        index.insert([1.0, 0.0, 0.0], "vec_1")
        index.insert([0.9, 0.1, 0.0], "vec_2")
        index.insert([0.0, 1.0, 0.0], "vec_3")
        
        # THEN should find similar vectors
        results = index.search([1.0, 0.0, 0.0], k=2)
        entity_ids = [r[0] for r in results]
        
        assert "vec_1" in entity_ids
        assert "vec_2" in entity_ids


class TestIndexManager:
    """Test index management."""
    
    def test_create_indexes(self):
        """Test creating various indexes."""
        # GIVEN an index manager
        manager = IndexManager()
        
        # WHEN creating indexes
        prop_idx = manager.create_property_index("name")
        comp_idx = manager.create_composite_index(["first", "last"])
        ft_idx = manager.create_fulltext_index("description")
        
        # THEN indexes should exist
        assert manager.get_index(prop_idx) is not None
        assert manager.get_index(comp_idx) is not None
        assert manager.get_index(ft_idx) is not None
    
    def test_list_indexes(self):
        """Test listing indexes."""
        # GIVEN a manager with indexes
        manager = IndexManager()
        manager.create_property_index("name")
        manager.create_property_index("age")
        
        # WHEN listing indexes
        indexes = manager.list_indexes()
        
        # THEN should list all (including default label index)
        assert len(indexes) >= 3
    
    def test_drop_index(self):
        """Test dropping index."""
        # GIVEN a manager with an index
        manager = IndexManager()
        idx_name = manager.create_property_index("temp")
        
        # WHEN dropping index
        result = manager.drop_index(idx_name)
        
        # THEN index should be removed
        assert result is True
        assert manager.get_index(idx_name) is None
    
    def test_insert_entity(self):
        """Test auto-indexing entities."""
        # GIVEN a manager with property index
        manager = IndexManager()
        manager.create_property_index("name")
        
        # WHEN inserting entity
        entity = {
            "id": "entity_1",
            "type": "Person",
            "properties": {
                "name": "Alice"
            }
        }
        manager.insert_entity(entity)
        
        # THEN entity should be in indexes
        idx = manager.get_index("idx_name")
        results = idx.search("Alice")
        assert "entity_1" in results


class TestUniqueConstraint:
    """Test unique constraints."""
    
    def test_unique_validation(self):
        """Test unique constraint validation."""
        # GIVEN a unique constraint
        constraint = UniqueConstraint("unique_email", "email")
        
        # WHEN validating duplicate
        entity1 = {"id": "e1", "type": "Person", "properties": {"email": "alice@example.com"}}
        entity2 = {"id": "e2", "type": "Person", "properties": {"email": "alice@example.com"}}
        
        constraint.register(entity1)
        violation = constraint.validate(entity2)
        
        # THEN should report violation
        assert violation is not None
        assert "email" in violation.message


class TestExistenceConstraint:
    """Test existence constraints."""
    
    def test_required_property(self):
        """Test that property must exist."""
        # GIVEN an existence constraint
        constraint = ExistenceConstraint("email_required", "email", "Person")
        
        # WHEN validating entity without property
        entity = {"id": "e1", "type": "Person", "properties": {}}
        violation = constraint.validate(entity)
        
        # THEN should report violation
        assert violation is not None
        assert "email" in violation.message


class TestTypeConstraint:
    """Test type constraints."""
    
    def test_type_validation(self):
        """Test type validation."""
        # GIVEN a type constraint
        constraint = TypeConstraint("age_int", "age", int)
        
        # WHEN validating wrong type
        entity = {"id": "e1", "type": "Person", "properties": {"age": "30"}}
        violation = constraint.validate(entity)
        
        # THEN should report violation
        assert violation is not None
        assert "int" in violation.message


class TestConstraintManager:
    """Test constraint management."""
    
    def test_add_constraints(self):
        """Test adding constraints."""
        # GIVEN a constraint manager
        manager = ConstraintManager()
        
        # WHEN adding constraints
        unique_name = manager.add_unique_constraint("email")
        exists_name = manager.add_existence_constraint("name", "Person")
        type_name = manager.add_type_constraint("age", int)
        
        # THEN constraints should exist
        constraints = manager.list_constraints()
        assert len(constraints) == 3
    
    def test_validate_entity(self):
        """Test validating entity against constraints."""
        # GIVEN a manager with constraints
        manager = ConstraintManager()
        manager.add_existence_constraint("name", "Person")
        manager.add_type_constraint("age", int, "Person")
        
        # WHEN validating invalid entity
        entity = {
            "id": "e1",
            "type": "Person",
            "properties": {"age": "invalid"}
        }
        violations = manager.validate(entity)
        
        # THEN should have violations
        assert len(violations) == 2  # Missing name, wrong age type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
