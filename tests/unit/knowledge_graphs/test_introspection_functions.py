"""
Tests for Cypher introspection functions.

Tests the introspection functions:
- type(relationship)
- id(entity)
- properties(entity)
- labels(node)
- keys(map)
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.cypher.functions import (
    fn_type,
    fn_id,
    fn_properties,
    fn_labels,
    fn_keys,
    evaluate_function
)


class MockNode:
    """Mock node for testing."""
    
    def __init__(self, id: str, labels: list, properties: dict):
        self.id = id
        self.labels = labels
        self.properties = properties


class MockRelationship:
    """Mock relationship for testing."""
    
    def __init__(self, id: str, type: str, properties: dict):
        self.id = id
        self.type = type
        self.properties = properties


class TestTypeFunction:
    """Tests for type() function."""
    
    def test_type_basic(self):
        """Test getting relationship type."""
        rel = MockRelationship('rel1', 'KNOWS', {'since': 2020})
        result = fn_type(rel)
        assert result == 'KNOWS'
    
    def test_type_different_types(self):
        """Test different relationship types."""
        rel1 = MockRelationship('r1', 'FOLLOWS', {})
        rel2 = MockRelationship('r2', 'LIKES', {})
        
        assert fn_type(rel1) == 'FOLLOWS'
        assert fn_type(rel2) == 'LIKES'
    
    def test_type_null(self):
        """Test type on NULL."""
        result = fn_type(None)
        assert result is None
    
    def test_type_no_attribute(self):
        """Test type on object without type attribute."""
        obj = {'not': 'a relationship'}
        result = fn_type(obj)
        assert result is None
    
    def test_type_via_registry(self):
        """Test type via function registry."""
        rel = MockRelationship('rel1', 'WORKS_AT', {})
        result = evaluate_function('type', rel)
        assert result == 'WORKS_AT'


class TestIdFunction:
    """Tests for id() function."""
    
    def test_id_node(self):
        """Test getting node ID."""
        node = MockNode('node123', ['Person'], {'name': 'Alice'})
        result = fn_id(node)
        assert result == 'node123'
    
    def test_id_relationship(self):
        """Test getting relationship ID."""
        rel = MockRelationship('rel456', 'KNOWS', {})
        result = fn_id(rel)
        assert result == 'rel456'
    
    def test_id_null(self):
        """Test id on NULL."""
        result = fn_id(None)
        assert result is None
    
    def test_id_no_attribute(self):
        """Test id on object without id attribute."""
        obj = {'not': 'an entity'}
        result = fn_id(obj)
        assert result is None
    
    def test_id_via_registry(self):
        """Test id via function registry."""
        node = MockNode('abc123', ['Label'], {})
        result = evaluate_function('id', node)
        assert result == 'abc123'


class TestPropertiesFunction:
    """Tests for properties() function."""
    
    def test_properties_node(self):
        """Test getting node properties."""
        node = MockNode('n1', ['Person'], {'name': 'Bob', 'age': 30})
        result = fn_properties(node)
        assert result == {'name': 'Bob', 'age': 30}
    
    def test_properties_relationship(self):
        """Test getting relationship properties."""
        rel = MockRelationship('r1', 'KNOWS', {'since': 2020, 'strength': 0.8})
        result = fn_properties(rel)
        assert result == {'since': 2020, 'strength': 0.8}
    
    def test_properties_empty(self):
        """Test properties with no properties."""
        node = MockNode('n1', ['Empty'], {})
        result = fn_properties(node)
        assert result == {}
    
    def test_properties_null(self):
        """Test properties on NULL."""
        result = fn_properties(None)
        assert result is None
    
    def test_properties_fallback_to_dict(self):
        """Test properties fallback to __dict__."""
        class SimpleObject:
            def __init__(self):
                self.name = 'test'
                self.value = 42
                self._private = 'hidden'
        
        obj = SimpleObject()
        result = fn_properties(obj)
        assert 'name' in result
        assert 'value' in result
        assert '_private' not in result
    
    def test_properties_via_registry(self):
        """Test properties via function registry."""
        node = MockNode('n1', ['Test'], {'key': 'value'})
        result = evaluate_function('properties', node)
        assert result == {'key': 'value'}


class TestLabelsFunction:
    """Tests for labels() function."""
    
    def test_labels_basic(self):
        """Test getting node labels."""
        node = MockNode('n1', ['Person'], {})
        result = fn_labels(node)
        assert result == ['Person']
    
    def test_labels_multiple(self):
        """Test node with multiple labels."""
        node = MockNode('n1', ['Person', 'Employee', 'Manager'], {})
        result = fn_labels(node)
        assert result == ['Person', 'Employee', 'Manager']
    
    def test_labels_empty(self):
        """Test node with no labels."""
        node = MockNode('n1', [], {})
        result = fn_labels(node)
        assert result == []
    
    def test_labels_null(self):
        """Test labels on NULL."""
        result = fn_labels(None)
        assert result is None
    
    def test_labels_no_attribute(self):
        """Test labels on object without labels attribute."""
        obj = {'not': 'a node'}
        result = fn_labels(obj)
        assert result == []
    
    def test_labels_via_registry(self):
        """Test labels via function registry."""
        node = MockNode('n1', ['A', 'B'], {})
        result = evaluate_function('labels', node)
        assert result == ['A', 'B']


class TestKeysFunction:
    """Tests for keys() function."""
    
    def test_keys_dict(self):
        """Test getting dictionary keys."""
        result = fn_keys({'a': 1, 'b': 2, 'c': 3})
        assert set(result) == {'a', 'b', 'c'}
    
    def test_keys_node(self):
        """Test getting node property keys."""
        node = MockNode('n1', ['Person'], {'name': 'Alice', 'age': 30})
        result = fn_keys(node)
        assert set(result) == {'name', 'age'}
    
    def test_keys_relationship(self):
        """Test getting relationship property keys."""
        rel = MockRelationship('r1', 'KNOWS', {'since': 2020})
        result = fn_keys(rel)
        assert result == ['since']
    
    def test_keys_empty(self):
        """Test keys on empty dict."""
        result = fn_keys({})
        assert result == []
    
    def test_keys_null(self):
        """Test keys on NULL."""
        result = fn_keys(None)
        assert result is None
    
    def test_keys_fallback_to_dict(self):
        """Test keys fallback to __dict__."""
        class SimpleObject:
            def __init__(self):
                self.key1 = 'value1'
                self.key2 = 'value2'
                self._private = 'hidden'
        
        obj = SimpleObject()
        result = fn_keys(obj)
        assert 'key1' in result
        assert 'key2' in result
        assert '_private' not in result
    
    def test_keys_via_registry(self):
        """Test keys via function registry."""
        result = evaluate_function('keys', {'x': 1, 'y': 2})
        assert set(result) == {'x', 'y'}


class TestIntrospectionIntegration:
    """Integration tests for introspection functions."""
    
    def test_node_introspection(self):
        """Test all introspection functions on a node."""
        node = MockNode('node123', ['Person', 'Employee'], {'name': 'Alice', 'age': 30})
        
        assert fn_id(node) == 'node123'
        assert fn_labels(node) == ['Person', 'Employee']
        assert fn_properties(node) == {'name': 'Alice', 'age': 30}
        assert set(fn_keys(node)) == {'name', 'age'}
    
    def test_relationship_introspection(self):
        """Test all introspection functions on a relationship."""
        rel = MockRelationship('rel456', 'KNOWS', {'since': 2020, 'strength': 0.9})
        
        assert fn_id(rel) == 'rel456'
        assert fn_type(rel) == 'KNOWS'
        assert fn_properties(rel) == {'since': 2020, 'strength': 0.9}
        assert set(fn_keys(rel)) == {'since', 'strength'}
    
    def test_dict_introspection(self):
        """Test introspection on plain dictionary."""
        data = {'field1': 'value1', 'field2': 'value2'}
        
        assert set(fn_keys(data)) == {'field1', 'field2'}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
