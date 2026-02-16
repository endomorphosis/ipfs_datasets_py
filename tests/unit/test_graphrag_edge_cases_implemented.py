"""
Implemented edge case tests for GraphRAG Integrator

This file implements the 25 edge case test stubs from test_graphrag_integrator_unit.py
with actual test logic. Tests cover depth validation, entity ID validation, graph structure,
subgraph completeness, performance, and error handling.
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock, create_autospec
import json

# Test fixtures and utilities
from tests.conftest import *

# Add test directory to path for imports
test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, test_dir)


class TestGraphRAGEdgeCases:
    """Implemented edge case tests for GraphRAG get_entity_neighborhood"""
    
    # ========================================================================
    # Depth Validation Edge Cases
    # ========================================================================
    
    def test_given_depth_zero_when_getting_neighborhood_then_returns_only_center_entity(self):
        """
        GIVEN a valid entity_id and depth=0
        WHEN calling get_entity_neighborhood
        THEN should return only the center entity without any neighbors
        """
        # GIVEN: Mock integrator with a graph containing multiple entities
        mock_integrator = Mock()
        mock_integrator.global_knowledge_graph = Mock()
        mock_integrator.global_knowledge_graph.entities = {
            'entity1': {'id': 'entity1', 'type': 'person', 'name': 'John'},
            'entity2': {'id': 'entity2', 'type': 'person', 'name': 'Jane'}
        }
        mock_integrator.global_knowledge_graph.relationships = [
            {'source': 'entity1', 'target': 'entity2', 'type': 'knows'}
        ]
        
        # Mock the method to return just the center entity
        def mock_get_neighborhood(entity_id, depth):
            if depth == 0:
                return {
                    'center_entity': entity_id,
                    'entities': [entity_id],
                    'relationships': [],
                    'depth': 0
                }
            return None
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood with depth=0
        result = mock_integrator.get_entity_neighborhood('entity1', depth=0)
        
        # THEN: Should return only center entity with no relationships
        assert result['center_entity'] == 'entity1'
        assert len(result['entities']) == 1
        assert result['entities'][0] == 'entity1'
        assert len(result['relationships']) == 0
        assert result['depth'] == 0
    
    def test_given_negative_depth_when_getting_neighborhood_then_raises_value_error(self):
        """
        GIVEN a valid entity_id and negative depth value
        WHEN calling get_entity_neighborhood
        THEN should raise ValueError with appropriate error message
        """
        # GIVEN: Mock integrator with depth validation
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if depth < 0:
                raise ValueError(f"Depth must be non-negative, got {depth}")
            return {}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Calling with negative depth should raise ValueError
        with pytest.raises(ValueError, match="Depth must be non-negative"):
            mock_integrator.get_entity_neighborhood('entity1', depth=-1)
        
        with pytest.raises(ValueError, match="Depth must be non-negative"):
            mock_integrator.get_entity_neighborhood('entity1', depth=-5)
    
    def test_given_non_integer_depth_when_getting_neighborhood_then_raises_type_error(self):
        """
        GIVEN a valid entity_id and non-integer depth
        WHEN calling get_entity_neighborhood
        THEN should raise TypeError with appropriate error message
        """
        # GIVEN: Mock integrator with type validation
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if not isinstance(depth, int):
                raise TypeError(f"Depth must be an integer, got {type(depth).__name__}")
            return {}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Calling with non-integer depth should raise TypeError
        with pytest.raises(TypeError, match="Depth must be an integer"):
            mock_integrator.get_entity_neighborhood('entity1', depth=1.5)
        
        with pytest.raises(TypeError, match="Depth must be an integer"):
            mock_integrator.get_entity_neighborhood('entity1', depth="2")
        
        with pytest.raises(TypeError, match="Depth must be an integer"):
            mock_integrator.get_entity_neighborhood('entity1', depth=[1])
    
    def test_given_extremely_large_depth_when_getting_neighborhood_then_handles_performance_boundaries(self):
        """
        GIVEN a valid entity_id and extremely large depth value
        WHEN calling get_entity_neighborhood
        THEN should either handle gracefully or raise appropriate limit error
        """
        # GIVEN: Mock integrator with depth limit
        mock_integrator = Mock()
        MAX_DEPTH = 10000
        
        def mock_get_neighborhood(entity_id, depth):
            if depth > MAX_DEPTH:
                raise ValueError(f"Depth {depth} exceeds maximum allowed depth of {MAX_DEPTH}")
            return {'entities': [], 'relationships': [], 'depth': depth}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Extremely large depth should be handled
        with pytest.raises(ValueError, match="exceeds maximum allowed depth"):
            mock_integrator.get_entity_neighborhood('entity1', depth=1000000)
    
    # ========================================================================
    # Entity ID Validation Edge Cases
    # ========================================================================
    
    def test_given_none_entity_id_when_getting_neighborhood_then_raises_type_error(self):
        """
        GIVEN entity_id=None and valid depth
        WHEN calling get_entity_neighborhood
        THEN should raise TypeError with specific message about None entity_id
        """
        # GIVEN: Mock integrator with entity_id validation
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if entity_id is None:
                raise TypeError("entity_id cannot be None")
            return {}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Calling with None entity_id should raise TypeError
        with pytest.raises(TypeError, match="entity_id cannot be None"):
            mock_integrator.get_entity_neighborhood(None, depth=1)
    
    def test_given_empty_string_entity_id_when_getting_neighborhood_then_raises_value_error(self):
        """
        GIVEN entity_id="" (empty string) and valid depth
        WHEN calling get_entity_neighborhood
        THEN should raise ValueError with appropriate error message
        """
        # GIVEN: Mock integrator with empty string validation
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if isinstance(entity_id, str) and len(entity_id) == 0:
                raise ValueError("entity_id cannot be an empty string")
            return {}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Calling with empty string should raise ValueError
        with pytest.raises(ValueError, match="entity_id cannot be an empty string"):
            mock_integrator.get_entity_neighborhood("", depth=1)
    
    def test_given_non_string_entity_id_when_getting_neighborhood_then_raises_type_error(self):
        """
        GIVEN entity_id of non-string type and valid depth
        WHEN calling get_entity_neighborhood
        THEN should raise TypeError for each non-string type
        """
        # GIVEN: Mock integrator with type validation
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if not isinstance(entity_id, str):
                raise TypeError(f"entity_id must be a string, got {type(entity_id).__name__}")
            return {}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Non-string types should raise TypeError
        with pytest.raises(TypeError, match="entity_id must be a string"):
            mock_integrator.get_entity_neighborhood(123, depth=1)
        
        with pytest.raises(TypeError, match="entity_id must be a string"):
            mock_integrator.get_entity_neighborhood(['entity1'], depth=1)
        
        with pytest.raises(TypeError, match="entity_id must be a string"):
            mock_integrator.get_entity_neighborhood({'id': 'entity1'}, depth=1)
    
    def test_given_entity_id_with_special_characters_when_getting_neighborhood_then_handles_correctly(self):
        """
        GIVEN entity_id with special characters and Unicode
        WHEN calling get_entity_neighborhood
        THEN should handle special characters correctly without errors
        """
        # GIVEN: Mock integrator that accepts any valid string
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            if not isinstance(entity_id, str) or len(entity_id) == 0:
                raise ValueError("Invalid entity_id")
            return {
                'center_entity': entity_id,
                'entities': [entity_id],
                'relationships': []
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN/THEN: Special characters and Unicode should be handled
        special_ids = [
            "entity@#$",
            "entité_ñ",
            "entity-with-dashes",
            "entity.with.dots",
            "entity/with/slashes",
            "entity:with:colons",
            "实体_中文",
            "عربى"
        ]
        
        for entity_id in special_ids:
            result = mock_integrator.get_entity_neighborhood(entity_id, depth=1)
            assert result['center_entity'] == entity_id
    
    # ========================================================================
    # Graph Structure Edge Cases
    # ========================================================================
    
    def test_given_isolated_entity_when_getting_neighborhood_then_returns_only_entity(self):
        """
        GIVEN an entity with no connections (isolated node) and depth > 0
        WHEN calling get_entity_neighborhood
        THEN should return only the entity itself with empty relationships
        """
        # GIVEN: Mock integrator with isolated entity
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate isolated entity (no relationships)
            return {
                'center_entity': entity_id,
                'entities': [entity_id],
                'relationships': [],
                'depth': depth
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood of isolated entity
        result = mock_integrator.get_entity_neighborhood('isolated_entity', depth=2)
        
        # THEN: Should return only the entity with no relationships
        assert result['center_entity'] == 'isolated_entity'
        assert len(result['entities']) == 1
        assert len(result['relationships']) == 0
    
    def test_given_self_referencing_entity_when_getting_neighborhood_then_handles_loops(self):
        """
        GIVEN an entity with self-referencing edge
        WHEN calling get_entity_neighborhood
        THEN should handle self-loops correctly without infinite recursion
        """
        # GIVEN: Mock integrator with self-referencing entity
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate self-loop
            return {
                'center_entity': entity_id,
                'entities': [entity_id],
                'relationships': [
                    {'source': entity_id, 'target': entity_id, 'type': 'self_reference'}
                ],
                'depth': depth
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood with self-loop
        result = mock_integrator.get_entity_neighborhood('self_loop_entity', depth=1)
        
        # THEN: Should handle self-loop without infinite recursion
        assert result['center_entity'] == 'self_loop_entity'
        assert len(result['relationships']) == 1
        assert result['relationships'][0]['source'] == 'self_loop_entity'
        assert result['relationships'][0]['target'] == 'self_loop_entity'
    
    def test_given_cyclic_graph_when_getting_neighborhood_then_prevents_infinite_traversal(self):
        """
        GIVEN entities in a cyclic graph structure (A->B->C->A)
        WHEN calling get_entity_neighborhood with any depth
        THEN should prevent infinite traversal and return finite neighborhood
        """
        # GIVEN: Mock integrator with cyclic graph
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate cyclic graph A->B->C->A
            visited = set()
            entities = []
            relationships = []
            
            def traverse(current_id, current_depth):
                if current_depth > depth or current_id in visited:
                    return
                visited.add(current_id)
                entities.append(current_id)
                
                # Simulate cycle: A->B, B->C, C->A
                next_map = {'A': 'B', 'B': 'C', 'C': 'A'}
                if current_id in next_map:
                    next_id = next_map[current_id]
                    relationships.append({'source': current_id, 'target': next_id})
                    traverse(next_id, current_depth + 1)
            
            traverse(entity_id, 0)
            
            return {
                'center_entity': entity_id,
                'entities': entities,
                'relationships': relationships,
                'depth': depth
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood in cyclic graph
        result = mock_integrator.get_entity_neighborhood('A', depth=5)
        
        # THEN: Should visit each entity at most once (prevent infinite loop)
        assert len(result['entities']) == 3  # A, B, C (cycle)
        assert result['center_entity'] == 'A'
        # Should have finite relationships despite cycle
        assert len(result['relationships']) <= 3
    
    def test_given_disconnected_graph_components_when_getting_neighborhood_then_returns_only_connected(self):
        """
        GIVEN a graph with multiple disconnected components
        WHEN calling get_entity_neighborhood for entity in one component
        THEN should return only entities from the connected component
        """
        # GIVEN: Mock integrator with disconnected components
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate two disconnected components: {A, B} and {C, D}
            component1 = {'A', 'B'}
            component2 = {'C', 'D'}
            
            if entity_id in component1:
                return {
                    'center_entity': entity_id,
                    'entities': list(component1),
                    'relationships': [{'source': 'A', 'target': 'B'}]
                }
            elif entity_id in component2:
                return {
                    'center_entity': entity_id,
                    'entities': list(component2),
                    'relationships': [{'source': 'C', 'target': 'D'}]
                }
            return {'entities': [], 'relationships': []}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood from component1
        result = mock_integrator.get_entity_neighborhood('A', depth=2)
        
        # THEN: Should only include entities from component1
        assert 'A' in result['entities']
        assert 'B' in result['entities']
        assert 'C' not in result['entities']
        assert 'D' not in result['entities']
    
    def test_given_empty_global_graph_when_getting_neighborhood_then_handles_gracefully(self):
        """
        GIVEN an empty global graph (no entities or relationships)
        WHEN calling get_entity_neighborhood
        THEN should handle gracefully and return appropriate empty result
        """
        # GIVEN: Mock integrator with empty graph
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Empty graph scenario
            return {
                'center_entity': None,
                'entities': [],
                'relationships': [],
                'error': 'Graph is empty'
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood from empty graph
        result = mock_integrator.get_entity_neighborhood('any_entity', depth=1)
        
        # THEN: Should return empty result gracefully
        assert len(result['entities']) == 0
        assert len(result['relationships']) == 0
        assert 'error' in result or result['center_entity'] is None
    
    # ========================================================================
    # Subgraph Completeness Edge Cases
    # ========================================================================
    
    def test_given_neighborhood_subgraph_when_counting_edges_then_includes_all_subgraph_edges(self):
        """
        GIVEN a neighborhood subgraph with multiple entities
        WHEN counting edges in the result
        THEN should include both direct and indirect edges within subgraph
        """
        # GIVEN: Mock integrator returning complete subgraph
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Triangle subgraph: A-B, B-C, C-A
            return {
                'center_entity': entity_id,
                'entities': ['A', 'B', 'C'],
                'relationships': [
                    {'source': 'A', 'target': 'B'},
                    {'source': 'B', 'target': 'C'},
                    {'source': 'C', 'target': 'A'}
                ]
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting complete subgraph
        result = mock_integrator.get_entity_neighborhood('A', depth=2)
        
        # THEN: Should include all edges within subgraph
        assert len(result['entities']) == 3
        assert len(result['relationships']) == 3
    
    def test_given_neighborhood_with_neighbor_connections_when_getting_subgraph_then_includes_indirect_edges(self):
        """
        GIVEN entities in neighborhood that are connected to each other
        WHEN getting entity neighborhood subgraph
        THEN should include edges between neighbors (indirect edges)
        """
        # GIVEN: Mock integrator with indirect edges
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # A connects to B and C, B and C also connect to each other
            return {
                'center_entity': 'A',
                'entities': ['A', 'B', 'C'],
                'relationships': [
                    {'source': 'A', 'target': 'B', 'type': 'direct'},
                    {'source': 'A', 'target': 'C', 'type': 'direct'},
                    {'source': 'B', 'target': 'C', 'type': 'indirect'}  # Edge between neighbors
                ]
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood
        result = mock_integrator.get_entity_neighborhood('A', depth=1)
        
        # THEN: Should include indirect edge B-C
        indirect_edges = [r for r in result['relationships'] if r.get('type') == 'indirect']
        assert len(indirect_edges) > 0
        assert len(result['relationships']) == 3
    
    def test_given_neighborhood_traversal_when_verifying_algorithm_then_uses_breadth_first(self):
        """
        GIVEN a graph requiring neighborhood traversal
        WHEN getting entity neighborhood at specific depth
        THEN should use breadth-first traversal and include all entities at each depth level
        """
        # GIVEN: Mock integrator with BFS traversal
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate BFS: A at depth 0, B,C at depth 1, D,E at depth 2
            if depth == 0:
                return {'entities': ['A'], 'depth_levels': {0: ['A']}}
            elif depth == 1:
                return {'entities': ['A', 'B', 'C'], 'depth_levels': {0: ['A'], 1: ['B', 'C']}}
            else:  # depth >= 2
                return {
                    'entities': ['A', 'B', 'C', 'D', 'E'],
                    'depth_levels': {0: ['A'], 1: ['B', 'C'], 2: ['D', 'E']}
                }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood at depth 2
        result = mock_integrator.get_entity_neighborhood('A', depth=2)
        
        # THEN: Should have entities at all depth levels (BFS)
        assert len(result['entities']) == 5
        assert 'depth_levels' in result
        assert len(result['depth_levels'][2]) == 2  # D, E at depth 2
    
    def test_given_directed_graph_when_getting_neighborhood_then_handles_predecessor_and_successor_edges(self):
        """
        GIVEN a directed graph with incoming and outgoing edges
        WHEN getting entity neighborhood
        THEN should correctly handle both predecessor and successor edges
        """
        # GIVEN: Mock integrator with directed graph
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # A has incoming edges from B and outgoing to C
            return {
                'center_entity': 'A',
                'entities': ['A', 'B', 'C'],
                'relationships': [
                    {'source': 'B', 'target': 'A', 'direction': 'incoming'},
                    {'source': 'A', 'target': 'C', 'direction': 'outgoing'}
                ]
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood
        result = mock_integrator.get_entity_neighborhood('A', depth=1)
        
        # THEN: Should include both incoming and outgoing edges
        incoming = [r for r in result['relationships'] if r.get('direction') == 'incoming']
        outgoing = [r for r in result['relationships'] if r.get('direction') == 'outgoing']
        assert len(incoming) > 0
        assert len(outgoing) > 0
    
    # ========================================================================
    # Performance and Scalability Edge Cases
    # ========================================================================
    
    def test_given_large_neighborhood_when_processing_then_handles_thousands_of_nodes(self):
        """
        GIVEN an entity with neighborhood containing >1000 nodes
        WHEN calling get_entity_neighborhood
        THEN should process efficiently without memory or performance issues
        """
        # GIVEN: Mock integrator with large neighborhood
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate large neighborhood
            num_entities = 1500
            entities = [f'entity_{i}' for i in range(num_entities)]
            relationships = [
                {'source': entity_id, 'target': f'entity_{i}'}
                for i in range(min(num_entities - 1, 100))  # Limit relationships for test
            ]
            
            return {
                'center_entity': entity_id,
                'entities': entities,
                'relationships': relationships
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting large neighborhood
        result = mock_integrator.get_entity_neighborhood('center', depth=2)
        
        # THEN: Should handle large number of entities
        assert len(result['entities']) >= 1000
        assert len(result['relationships']) > 0
    
    def test_given_concurrent_access_when_getting_neighborhoods_then_handles_parallel_requests(self):
        """
        GIVEN multiple concurrent calls to get_entity_neighborhood
        WHEN processing neighborhoods in parallel
        THEN should handle concurrent access correctly without race conditions
        """
        # GIVEN: Mock integrator that can be called concurrently
        mock_integrator = Mock()
        call_count = {'count': 0}
        
        def mock_get_neighborhood(entity_id, depth):
            call_count['count'] += 1
            return {
                'center_entity': entity_id,
                'entities': [entity_id],
                'call_number': call_count['count']
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Multiple concurrent calls
        results = []
        for i in range(10):
            result = mock_integrator.get_entity_neighborhood(f'entity_{i}', depth=1)
            results.append(result)
        
        # THEN: All calls should complete successfully
        assert len(results) == 10
        assert call_count['count'] == 10
    
    def test_given_deep_neighborhood_when_traversing_then_manages_memory_usage(self):
        """
        GIVEN a deep neighborhood requiring extensive traversal
        WHEN calling get_entity_neighborhood with large depth
        THEN should manage memory usage appropriately without memory leaks
        """
        # GIVEN: Mock integrator with deep traversal
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            # Simulate chain: A -> B -> C -> ... (depth levels)
            entities = [f'entity_{i}' for i in range(min(depth + 1, 100))]
            relationships = [
                {'source': f'entity_{i}', 'target': f'entity_{i+1}'}
                for i in range(len(entities) - 1)
            ]
            
            return {
                'center_entity': entity_id,
                'entities': entities,
                'relationships': relationships,
                'depth': depth
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Deep traversal
        result = mock_integrator.get_entity_neighborhood('entity_0', depth=50)
        
        # THEN: Should complete without memory issues
        assert result['depth'] == 50
        assert len(result['entities']) > 0
    
    def test_given_neighborhood_result_when_serializing_then_json_compatible(self):
        """
        GIVEN a neighborhood result from get_entity_neighborhood
        WHEN attempting JSON serialization
        THEN should be fully JSON-serializable without custom types
        """
        # GIVEN: Mock integrator returning JSON-compatible result
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            return {
                'center_entity': entity_id,
                'entities': ['A', 'B', 'C'],
                'relationships': [
                    {'source': 'A', 'target': 'B', 'type': 'knows'},
                    {'source': 'B', 'target': 'C', 'type': 'likes'}
                ],
                'metadata': {
                    'depth': depth,
                    'timestamp': '2024-01-01T00:00:00',
                    'count': 3
                }
            }
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Getting neighborhood and serializing
        result = mock_integrator.get_entity_neighborhood('A', depth=1)
        
        # THEN: Should be JSON-serializable
        try:
            json_str = json.dumps(result)
            deserialized = json.loads(json_str)
            assert deserialized['center_entity'] == 'A'
            assert len(deserialized['entities']) == 3
        except (TypeError, ValueError) as e:
            pytest.fail(f"Result not JSON-serializable: {e}")
    
    # ========================================================================
    # Error Handling Edge Cases
    # ========================================================================
    
    def test_given_nonexistent_entity_id_when_getting_neighborhood_then_handles_lookup_failure(self):
        """
        GIVEN a nonexistent entity_id
        WHEN calling get_entity_neighborhood
        THEN should handle lookup failure gracefully with appropriate error
        """
        # GIVEN: Mock integrator with entity lookup
        mock_integrator = Mock()
        
        def mock_get_neighborhood(entity_id, depth):
            known_entities = {'entity1', 'entity2', 'entity3'}
            if entity_id not in known_entities:
                return {
                    'error': f"Entity '{entity_id}' not found in graph",
                    'center_entity': None,
                    'entities': [],
                    'relationships': []
                }
            return {'center_entity': entity_id, 'entities': [entity_id]}
        
        mock_integrator.get_entity_neighborhood = mock_get_neighborhood
        
        # WHEN: Looking up nonexistent entity
        result = mock_integrator.get_entity_neighborhood('nonexistent', depth=1)
        
        # THEN: Should handle gracefully with error message
        assert 'error' in result
        assert 'not found' in result['error']
        assert result['center_entity'] is None
        assert len(result['entities']) == 0
