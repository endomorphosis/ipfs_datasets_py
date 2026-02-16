"""
Tests for GraphRAG Adapter

Tests the adapter that bridges old GraphRAG API to unified query engine.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import warnings

from ipfs_datasets_py.processors.specialized.graphrag.adapter import (
    GraphRAGAdapter,
    create_graphrag_adapter_from_dataset
)
from ipfs_datasets_py.knowledge_graphs.query.unified_engine import GraphRAGResult, QueryResult
from ipfs_datasets_py.search.graph_query.budgets import ExecutionBudgets


class TestGraphRAGAdapter:
    """Tests for GraphRAGAdapter."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        backend = Mock()
        vector_stores = {'model1': Mock()}
        graph_store = Mock()
        
        adapter = GraphRAGAdapter(backend, vector_stores, graph_store)
        
        assert adapter.backend == backend
        assert adapter.vector_stores == vector_stores
        assert adapter.graph_store == graph_store
        assert adapter.engine is not None
    
    def test_adapter_creation_minimal(self):
        """Test adapter with minimal arguments."""
        backend = Mock()
        
        adapter = GraphRAGAdapter(backend)
        
        assert adapter.backend == backend
        assert adapter.vector_stores == {}
        assert adapter.primary_vector_store is None
    
    def test_query_hybrid_search(self):
        """Test query with hybrid search (no LLM)."""
        backend = Mock()
        vector_store = Mock()
        adapter = GraphRAGAdapter(backend, vector_stores={'model1': vector_store})
        
        # Mock the engine's execute_hybrid method
        mock_result = QueryResult(
            items=[{'node_id': 'node1', 'score': 0.9}],
            stats={'elapsed_ms': 100},
            query_type='hybrid',
            success=True
        )
        adapter.engine.execute_hybrid = Mock(return_value=mock_result)
        
        # Execute query (should trigger deprecation warning)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="test query",
                top_k=10,
                include_cross_document_reasoning=False
            )
            
            # Check deprecation warning was issued
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
        
        # Check result format
        assert result['query_text'] == "test query"
        assert result['success'] is True
        assert 'hybrid_results' in result
        assert len(result['hybrid_results']) == 1
    
    def test_query_graphrag_with_llm(self):
        """Test query with full GraphRAG (LLM reasoning)."""
        backend = Mock()
        vector_store = Mock()
        llm_processor = Mock()
        
        adapter = GraphRAGAdapter(
            backend,
            vector_stores={'model1': vector_store},
            llm_processor=llm_processor
        )
        
        # Mock the engine's execute_graphrag method
        mock_result = GraphRAGResult(
            items=[{'node_id': 'node1', 'score': 0.9}],
            stats={'elapsed_ms': 200},
            query_type='graphrag',
            success=True,
            reasoning={'answer': 'Test answer', 'confidence': 0.8},
            evidence_chains=[{'source': 'node1', 'target': 'node2'}],
            confidence=0.8
        )
        adapter.engine.execute_graphrag = Mock(return_value=mock_result)
        
        # Execute query
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="complex query",
                top_k=5,
                include_cross_document_reasoning=True,
                reasoning_depth='deep'
            )
        
        # Check result format
        assert result['query_text'] == "complex query"
        assert result['success'] is True
        assert 'reasoning_result' in result
        assert result['reasoning_result']['answer'] == 'Test answer'
        assert 'evidence_chains' in result
        assert len(result['evidence_chains']) == 1
    
    def test_query_with_custom_budgets(self):
        """Test query with custom budgets."""
        backend = Mock()
        adapter = GraphRAGAdapter(backend)
        
        # Mock the engine
        mock_result = QueryResult(
            items=[],
            stats={},
            query_type='hybrid',
            success=True
        )
        adapter.engine.execute_hybrid = Mock(return_value=mock_result)
        
        # Custom budgets
        budgets = ExecutionBudgets(
            timeout_ms=5000,
            max_nodes_visited=100
        )
        
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="test",
                budgets=budgets,
                include_cross_document_reasoning=False
            )
        
        # Verify budgets were passed
        adapter.engine.execute_hybrid.assert_called_once()
        call_kwargs = adapter.engine.execute_hybrid.call_args[1]
        assert call_kwargs['budgets'] == budgets
    
    def test_metrics_tracking(self):
        """Test metrics are tracked correctly."""
        backend = Mock()
        adapter = GraphRAGAdapter(backend)
        
        # Initial metrics
        metrics = adapter.get_metrics()
        assert metrics['queries_processed'] == 0
        assert metrics['vector_searches'] == 0
        
        # Mock engine
        adapter.engine.execute_hybrid = Mock(return_value=QueryResult(
            items=[], stats={}, query_type='hybrid', success=True
        ))
        
        # Execute query
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            adapter.query("test", include_cross_document_reasoning=False)
        
        # Check metrics updated
        metrics = adapter.get_metrics()
        assert metrics['queries_processed'] == 1
        assert metrics['vector_searches'] == 1
    
    def test_visualize_query_result(self):
        """Test visualization method."""
        backend = Mock()
        adapter = GraphRAGAdapter(backend)
        
        result = {
            'query_text': 'test query',
            'hybrid_results': []
        }
        
        # Test mermaid format
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            viz = adapter.visualize_query_result(result, format='mermaid')
            
            # Should issue deprecation warning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
        
        assert 'mermaid' in viz
        assert 'test query' in viz
    
    def test_visualize_json_format(self):
        """Test JSON visualization."""
        backend = Mock()
        adapter = GraphRAGAdapter(backend)
        
        result = {'query_text': 'test', 'success': True}
        
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            viz = adapter.visualize_query_result(result, format='json')
        
        assert 'query_text' in viz
        assert 'test' in viz


class TestCreateAdapterFromDataset:
    """Tests for create_graphrag_adapter_from_dataset."""
    
    def test_create_from_dataset(self):
        """Test creating adapter from dataset."""
        # Mock dataset
        dataset = Mock()
        dataset.backend = Mock()
        dataset.vector_stores = {'model1': Mock()}
        dataset.graph_store = Mock()
        
        adapter = create_graphrag_adapter_from_dataset(dataset)
        
        assert adapter.backend == dataset.backend
        assert adapter.vector_stores == dataset.vector_stores
        assert adapter.graph_store == dataset.graph_store
    
    def test_create_from_dataset_with_graph_backend(self):
        """Test creating adapter from dataset with graph_backend attr."""
        dataset = Mock()
        dataset.graph_backend = Mock()  # Alternative attribute name
        dataset.vector_stores = {}
        dataset.graph_store = None
        
        adapter = create_graphrag_adapter_from_dataset(dataset)
        
        assert adapter.backend == dataset.graph_backend
    
    def test_create_from_dataset_no_backend_raises(self):
        """Test creating adapter from dataset without backend raises."""
        dataset = Mock()
        # No backend or graph_backend attribute
        dataset.spec = []
        
        with pytest.raises(ValueError, match="backend"):
            create_graphrag_adapter_from_dataset(dataset)
    
    def test_create_with_llm_processor(self):
        """Test creating adapter with LLM processor."""
        dataset = Mock()
        dataset.backend = Mock()
        dataset.vector_stores = {}
        dataset.graph_store = None
        
        llm_processor = Mock()
        
        adapter = create_graphrag_adapter_from_dataset(
            dataset,
            llm_processor=llm_processor
        )
        
        assert adapter.llm_processor == llm_processor


class TestAdapterBackwardCompatibility:
    """Tests for backward compatibility."""
    
    def test_old_api_parameters_work(self):
        """Test that old API parameters are accepted."""
        backend = Mock()
        adapter = GraphRAGAdapter(backend)
        
        adapter.engine.execute_hybrid = Mock(return_value=QueryResult(
            items=[], stats={}, query_type='hybrid', success=True
        ))
        
        # Call with all old parameters
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="test",
                query_embeddings={'model1': [0.1, 0.2]},
                top_k=10,
                include_vector_results=True,
                include_graph_results=True,
                include_cross_document_reasoning=False,
                entity_types=['Person', 'Place'],
                relationship_types=['KNOWS', 'LOCATED_IN'],
                min_relevance=0.7,
                max_graph_hops=3,
                reasoning_depth='moderate',
                return_trace=False
            )
        
        # Should not raise an error
        assert result['success'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
