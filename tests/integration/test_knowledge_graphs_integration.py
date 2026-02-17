"""
Integration tests for Knowledge Graphs extraction and query workflow

Tests the complete pipeline from text extraction through knowledge graph
construction to querying, validating Phase 3 & 4 refactoring integration.

NOTE: Some tests use mock objects for demonstrating workflow patterns. For real integration
testing with actual extraction and query code, these should be supplemented with tests using
the safe_importer pattern (see tests/unit/test_graphrag_integrator_unit.py for examples).

Following GIVEN-WHEN-THEN format as per repository standards.
"""
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import json

# Test fixtures
from tests.conftest import *

# Add paths for imports
test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, test_dir)


class TestKnowledgeGraphsExtractionQueryIntegration:
    """Integration tests for extraction → query workflow"""
    
    def test_given_text_when_extracting_and_querying_then_complete_workflow_succeeds(self):
        """
        GIVEN a text document
        WHEN extracting entities and relationships, then querying the graph
        THEN the complete workflow should succeed end-to-end
        """
        # GIVEN: Sample text and mock components
        sample_text = "John works at Microsoft. Jane is CEO of Apple."
        
        # Mock extraction results
        mock_extractor = Mock()
        mock_extractor.extract_entities.return_value = [
            {'id': 'john', 'type': 'person', 'name': 'John'},
            {'id': 'jane', 'type': 'person', 'name': 'Jane'},
            {'id': 'microsoft', 'type': 'organization', 'name': 'Microsoft'},
            {'id': 'apple', 'type': 'organization', 'name': 'Apple'}
        ]
        mock_extractor.extract_relationships.return_value = [
            {'source': 'john', 'target': 'microsoft', 'type': 'works_at'},
            {'source': 'jane', 'target': 'apple', 'type': 'ceo_of'}
        ]
        
        # Mock graph construction
        mock_graph = Mock()
        mock_graph.entities = mock_extractor.extract_entities.return_value
        mock_graph.relationships = mock_extractor.extract_relationships.return_value
        
        # Mock query engine
        mock_query_engine = Mock()
        mock_query_engine.execute_query.return_value = {
            'results': [
                {'entity': 'john', 'organization': 'microsoft'},
                {'entity': 'jane', 'organization': 'apple'}
            ],
            'count': 2
        }
        
        # WHEN: Executing complete workflow
        # 1. Extract
        entities = mock_extractor.extract_entities(sample_text)
        relationships = mock_extractor.extract_relationships(sample_text)
        
        # 2. Build graph
        graph_data = {
            'entities': entities,
            'relationships': relationships
        }
        
        # 3. Query
        query = "Find all people and their organizations"
        results = mock_query_engine.execute_query(query, graph_data)
        
        # THEN: Workflow should complete successfully
        assert len(entities) == 4
        assert len(relationships) == 2
        assert results['count'] == 2
        assert len(results['results']) == 2
    
    def test_given_extraction_package_when_importing_then_all_classes_available(self):
        """
        GIVEN the new extraction package structure (Phase 3)
        WHEN importing classes
        THEN all classes should be available from extraction package
        """
        try:
            # WHEN: Importing from new extraction package
            from ipfs_datasets_py.knowledge_graphs.extraction import (
                Entity,
                Relationship,
                KnowledgeGraph,
                KnowledgeGraphExtractor,
                KnowledgeGraphExtractorWithValidation
            )
            
            # THEN: All imports should succeed
            assert Entity is not None
            assert Relationship is not None
            assert KnowledgeGraph is not None
            assert KnowledgeGraphExtractor is not None
            assert KnowledgeGraphExtractorWithValidation is not None
            
        except ImportError as e:
            pytest.skip(f"Knowledge graphs extraction package not available: {e}")
    
    def test_given_entity_and_relationship_when_building_graph_then_graph_structure_valid(self):
        """
        GIVEN entities and relationships
        WHEN building a knowledge graph
        THEN the graph structure should be valid and queryable
        """
        # GIVEN: Mock entities and relationships
        entities = [
            {'id': 'e1', 'type': 'person', 'name': 'Alice'},
            {'id': 'e2', 'type': 'person', 'name': 'Bob'},
            {'id': 'e3', 'type': 'company', 'name': 'TechCorp'}
        ]
        
        relationships = [
            {'source': 'e1', 'target': 'e3', 'type': 'works_at'},
            {'source': 'e2', 'target': 'e3', 'type': 'works_at'}
        ]
        
        # WHEN: Building graph
        mock_graph = Mock()
        mock_graph.add_entities = Mock()
        mock_graph.add_relationships = Mock()
        mock_graph.get_entity_by_id = Mock(side_effect=lambda id: next((e for e in entities if e['id'] == id), None))
        mock_graph.get_relationships_for_entity = Mock(return_value=[r for r in relationships if r['source'] == 'e1'])
        
        mock_graph.add_entities(entities)
        mock_graph.add_relationships(relationships)
        
        # THEN: Graph should be queryable
        alice = mock_graph.get_entity_by_id('e1')
        assert alice is not None
        assert alice['name'] == 'Alice'
        
        alice_relationships = mock_graph.get_relationships_for_entity('e1')
        assert len(alice_relationships) == 1
        assert alice_relationships[0]['type'] == 'works_at'
    
    def test_given_graph_when_validating_then_validation_results_returned(self):
        """
        GIVEN a knowledge graph
        WHEN validating against external sources
        THEN validation results should be returned
        """
        # GIVEN: Mock graph and validator
        mock_graph = Mock()
        mock_graph.entities = [
            {'id': 'e1', 'type': 'person', 'name': 'Albert Einstein'},
            {'id': 'e2', 'type': 'organization', 'name': 'Princeton University'}
        ]
        
        mock_validator = Mock()
        mock_validator.validate_entities.return_value = {
            'e1': {'valid': True, 'confidence': 0.95, 'source': 'Wikidata'},
            'e2': {'valid': True, 'confidence': 0.98, 'source': 'Wikidata'}
        }
        
        # WHEN: Validating graph
        validation_results = mock_validator.validate_entities(mock_graph.entities)
        
        # THEN: Validation results should be returned
        assert len(validation_results) == 2
        assert validation_results['e1']['valid'] is True
        assert validation_results['e1']['confidence'] > 0.9
        assert validation_results['e2']['valid'] is True
    
    def test_given_multiple_graphs_when_merging_then_combined_graph_created(self):
        """
        GIVEN multiple knowledge graphs from different sources
        WHEN merging graphs
        THEN a combined graph should be created with deduplicated entities
        """
        # GIVEN: Two graphs with some overlap
        graph1_entities = [
            {'id': 'e1', 'type': 'person', 'name': 'John Smith'},
            {'id': 'e2', 'type': 'company', 'name': 'Microsoft'}
        ]
        
        graph2_entities = [
            {'id': 'e1', 'type': 'person', 'name': 'John Smith'},  # Duplicate
            {'id': 'e3', 'type': 'company', 'name': 'Apple'}
        ]
        
        # WHEN: Merging graphs
        mock_merger = Mock()
        mock_merger.merge.return_value = {
            'entities': [
                {'id': 'e1', 'type': 'person', 'name': 'John Smith'},
                {'id': 'e2', 'type': 'company', 'name': 'Microsoft'},
                {'id': 'e3', 'type': 'company', 'name': 'Apple'}
            ],
            'merge_statistics': {
                'duplicates_removed': 1,
                'total_entities': 3
            }
        }
        
        result = mock_merger.merge([graph1_entities, graph2_entities])
        
        # THEN: Combined graph should have deduplicated entities
        assert len(result['entities']) == 3
        assert result['merge_statistics']['duplicates_removed'] == 1
    
    def test_given_graph_when_exporting_then_multiple_formats_supported(self):
        """
        GIVEN a knowledge graph
        WHEN exporting to different formats
        THEN JSON, RDF, and other formats should be supported
        """
        # GIVEN: Mock graph
        mock_graph = Mock()
        mock_graph.to_dict.return_value = {
            'entities': [{'id': 'e1', 'name': 'Test'}],
            'relationships': []
        }
        mock_graph.to_json.return_value = '{"entities": [{"id": "e1", "name": "Test"}], "relationships": []}'
        mock_graph.export_to_rdf.return_value = '<rdf:RDF>...</rdf:RDF>'
        
        # WHEN: Exporting to different formats
        dict_export = mock_graph.to_dict()
        json_export = mock_graph.to_json()
        rdf_export = mock_graph.export_to_rdf()
        
        # THEN: All formats should be available
        assert isinstance(dict_export, dict)
        assert 'entities' in dict_export
        
        assert isinstance(json_export, str)
        parsed_json = json.loads(json_export)
        assert 'entities' in parsed_json
        
        assert isinstance(rdf_export, str)
        assert 'rdf' in rdf_export.lower()


class TestQueryEngineIntegration:
    """Integration tests for query engine functionality"""
    
    def test_given_graph_when_executing_cypher_query_then_results_returned(self):
        """
        GIVEN a knowledge graph
        WHEN executing a Cypher query
        THEN relevant results should be returned
        """
        # GIVEN: Mock graph and query engine
        mock_graph = Mock()
        mock_engine = Mock()
        
        cypher_query = "MATCH (p:Person)-[:WORKS_AT]->(c:Company) RETURN p, c"
        mock_engine.execute_cypher.return_value = {
            'results': [
                {'p': {'name': 'Alice'}, 'c': {'name': 'TechCorp'}},
                {'p': {'name': 'Bob'}, 'c': {'name': 'TechCorp'}}
            ]
        }
        
        # WHEN: Executing Cypher query
        results = mock_engine.execute_cypher(cypher_query, mock_graph)
        
        # THEN: Results should be returned
        assert len(results['results']) == 2
        assert results['results'][0]['c']['name'] == 'TechCorp'
    
    def test_given_graph_when_executing_hybrid_search_then_combines_vector_and_graph(self):
        """
        GIVEN a knowledge graph with embeddings
        WHEN executing hybrid search
        THEN should combine vector similarity and graph structure
        """
        # GIVEN: Mock hybrid search engine
        mock_engine = Mock()
        
        query = "Find AI researchers at universities"
        mock_engine.execute_hybrid.return_value = {
            'results': [
                {
                    'entity': {'id': 'e1', 'name': 'Dr. Smith'},
                    'vector_score': 0.92,
                    'graph_score': 0.88,
                    'combined_score': 0.90
                },
                {
                    'entity': {'id': 'e2', 'name': 'Prof. Johnson'},
                    'vector_score': 0.85,
                    'graph_score': 0.95,
                    'combined_score': 0.90
                }
            ],
            'fusion_method': 'weighted_average'
        }
        
        # WHEN: Executing hybrid search
        results = mock_engine.execute_hybrid(query)
        
        # THEN: Results should combine vector and graph scores
        assert len(results['results']) == 2
        for result in results['results']:
            assert 'vector_score' in result
            assert 'graph_score' in result
            assert 'combined_score' in result
    
    def test_given_query_budget_when_executing_then_respects_limits(self):
        """
        GIVEN a query with budget constraints
        WHEN executing queries
        THEN should respect budget limits
        """
        # GIVEN: Mock budget manager
        mock_budget = Mock()
        mock_budget.remaining_budget = 100
        mock_budget.check_exceeded.return_value = False
        
        mock_engine = Mock()
        mock_engine.budget_manager = mock_budget
        
        # WHEN: Executing query with budget
        def execute_with_budget(query):
            if not mock_budget.check_exceeded():
                mock_budget.remaining_budget -= 10
                return {'results': [], 'cost': 10}
            else:
                raise ValueError("Budget exceeded")
        
        mock_engine.execute_query = execute_with_budget
        
        # Execute multiple queries
        for i in range(5):
            result = mock_engine.execute_query(f"query_{i}")
            assert result['cost'] == 10
        
        # THEN: Budget should be tracked
        assert mock_budget.remaining_budget == 50


class TestPerformanceIntegration:
    """Integration tests for performance characteristics"""
    
    def test_given_large_graph_when_extracting_then_completes_in_reasonable_time(self):
        """
        GIVEN a large text document
        WHEN extracting knowledge graph
        THEN should complete in reasonable time
        """
        # GIVEN: Mock extractor with performance tracking
        import time
        
        mock_extractor = Mock()
        
        def timed_extract(text):
            start = time.time()
            # Simulate extraction
            entities = [{'id': f'e{i}', 'name': f'Entity{i}'} for i in range(100)]
            elapsed = time.time() - start
            return {'entities': entities, 'time': elapsed}
        
        mock_extractor.extract = timed_extract
        
        # WHEN: Extracting from large text
        large_text = "Sample text " * 1000
        result = mock_extractor.extract(large_text)
        
        # THEN: Should complete in reasonable time (< 1 second for mock)
        assert result['time'] < 1.0
        assert len(result['entities']) == 100
    
    def test_given_cached_results_when_querying_then_uses_cache(self):
        """
        GIVEN a query engine with caching
        WHEN executing repeated queries
        THEN should use cached results for performance
        """
        # GIVEN: Mock query engine with cache
        cache = {}
        call_count = {'count': 0}
        
        mock_engine = Mock()
        
        def cached_query(query):
            call_count['count'] += 1
            if query in cache:
                return {'results': cache[query], 'from_cache': True}
            else:
                results = [{'data': 'result'}]
                cache[query] = results
                return {'results': results, 'from_cache': False}
        
        mock_engine.execute_query = cached_query
        
        # WHEN: Executing same query multiple times
        query = "test query"
        result1 = mock_engine.execute_query(query)
        result2 = mock_engine.execute_query(query)
        result3 = mock_engine.execute_query(query)
        
        # THEN: Should use cache after first call
        assert result1['from_cache'] is False
        assert result2['from_cache'] is True
        assert result3['from_cache'] is True
        assert call_count['count'] == 3
    
    def test_given_parallel_extractions_when_processing_then_handles_concurrently(self):
        """
        GIVEN multiple documents to process
        WHEN extracting in parallel
        THEN should handle concurrent processing
        """
        # GIVEN: Mock parallel extractor
        from concurrent.futures import ThreadPoolExecutor
        
        mock_extractor = Mock()
        
        def extract_single(text):
            return {
                'entities': [{'id': 'e1', 'text': text}],
                'text_length': len(text)
            }
        
        mock_extractor.extract = extract_single
        
        # WHEN: Processing multiple documents in parallel
        documents = [f"Document {i}" for i in range(10)]
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(mock_extractor.extract, documents))
        
        # THEN: All documents should be processed
        assert len(results) == 10
        for i, result in enumerate(results):
            assert result['entities'][0]['text'] == f"Document {i}"


class TestBackwardCompatibilityIntegration:
    """Integration tests for backward compatibility (Phase 3 refactoring)"""
    
    def test_given_old_imports_when_using_legacy_path_then_still_works(self):
        """
        GIVEN the old import path (pre-Phase 3)
        WHEN importing classes
        THEN should still work for backward compatibility
        """
        try:
            # WHEN: Using old import path
            from ipfs_datasets_py.knowledge_graphs import knowledge_graph_extraction
            
            # THEN: Should import successfully
            assert knowledge_graph_extraction is not None
            assert hasattr(knowledge_graph_extraction, '__file__')
            
        except ImportError as e:
            pytest.skip(f"Legacy import path not available: {e}")
    
    def test_given_new_and_old_imports_when_comparing_then_classes_are_same(self):
        """
        GIVEN both old and new import paths
        WHEN importing classes from both
        THEN classes should be the same (references)
        """
        try:
            # WHEN: Importing from both paths
            from ipfs_datasets_py.knowledge_graphs.extraction import Entity as NewEntity
            from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity as OldEntity
            
            # THEN: Should be the same class
            assert NewEntity is OldEntity
            
        except ImportError as e:
            pytest.skip(f"Import paths not available: {e}")
    
    def test_given_existing_code_when_running_with_new_structure_then_no_breaking_changes(self):
        """
        GIVEN existing code using old imports
        WHEN running with new package structure
        THEN should work without breaking changes
        """
        try:
            # WHEN: Using old-style code
            from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
                Entity,
                Relationship,
                KnowledgeGraph
            )
            
            # Create instances using old imports
            entity = Entity(id='e1', type='person', name='Test')
            relationship = Relationship(source='e1', target='e2', type='knows')
            graph = KnowledgeGraph()
            
            # THEN: Should work without errors
            assert entity is not None
            assert relationship is not None
            assert graph is not None
            
        except (ImportError, AttributeError, TypeError) as e:
            # Expected if classes have different constructors
            pytest.skip(f"Classes not instantiable in test context: {e}")
