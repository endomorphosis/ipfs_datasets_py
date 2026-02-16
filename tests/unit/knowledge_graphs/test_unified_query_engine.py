"""
Tests for Unified Query Engine

Tests the consolidated GraphRAG query engine components:
- UnifiedQueryEngine
- BudgetManager
- HybridSearchEngine
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

from ipfs_datasets_py.knowledge_graphs.query import (
    UnifiedQueryEngine,
    HybridSearchEngine,
    BudgetManager
)
from ipfs_datasets_py.knowledge_graphs.query.unified_engine import (
    QueryResult,
    GraphRAGResult
)
from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchResult
from ipfs_datasets_py.search.graph_query.budgets import (
    ExecutionBudgets,
    ExecutionCounters,
    budgets_from_preset
)


class TestBudgetManager:
    """Tests for BudgetManager."""
    
    def test_budget_manager_creation(self):
        """Test budget manager can be created."""
        manager = BudgetManager()
        assert manager is not None
        assert manager.current_tracker is None
    
    def test_budget_tracking_context(self):
        """Test budget tracking context manager."""
        manager = BudgetManager()
        budgets = budgets_from_preset('safe')
        
        with manager.track(budgets) as tracker:
            assert tracker is not None
            assert tracker.budgets == budgets
            assert tracker.counters.nodes_visited == 0
        
        # After context, tracker should be None
        assert manager.current_tracker is None
    
    def test_budget_counter_increments(self):
        """Test incrementing budget counters."""
        manager = BudgetManager()
        budgets = budgets_from_preset('safe')
        
        with manager.track(budgets) as tracker:
            tracker.increment_nodes(10)
            assert tracker.counters.nodes_visited == 10
            
            tracker.increment_edges(50)
            assert tracker.counters.edges_scanned == 50
            
            tracker.increment_depth(2)
            assert tracker.counters.depth == 2
    
    def test_budget_exceeded_detection(self):
        """Test budget exceeded detection."""
        manager = BudgetManager()
        # Create strict budgets
        budgets = ExecutionBudgets(
            max_nodes_visited=10,
            max_edges_scanned=50,
            max_depth=2
        )
        
        with manager.track(budgets) as tracker:
            # Should not raise
            tracker.increment_nodes(5)
            
            # Should raise when exceeded
            with pytest.raises(Exception):  # BudgetExceededError
                tracker.increment_nodes(10)  # Total would be 15 > 10
    
    def test_create_preset_budgets(self):
        """Test creating budgets from preset."""
        manager = BudgetManager()
        
        budgets = manager.create_preset_budgets('safe', max_results=50)
        assert budgets is not None
        assert budgets.max_results == 50
    
    def test_get_stats(self):
        """Test getting execution statistics."""
        manager = BudgetManager()
        budgets = budgets_from_preset('safe')
        
        with manager.track(budgets) as tracker:
            tracker.increment_nodes(10)
            tracker.increment_edges(50)
            
            stats = tracker.get_stats()
            assert 'elapsed_ms' in stats
            assert stats['nodes_visited'] == 10
            assert stats['edges_scanned'] == 50
            assert not stats['exceeded']


class TestHybridSearchEngine:
    """Tests for HybridSearchEngine."""
    
    def test_hybrid_search_creation(self):
        """Test hybrid search engine can be created."""
        backend = Mock()
        engine = HybridSearchEngine(backend)
        
        assert engine.backend == backend
        assert engine.vector_store is None
        assert engine.default_vector_weight == 0.6
        assert engine.default_graph_weight == 0.4
    
    def test_hybrid_search_with_weights(self):
        """Test creating engine with custom weights."""
        backend = Mock()
        engine = HybridSearchEngine(
            backend,
            default_vector_weight=0.7,
            default_graph_weight=0.3
        )
        
        assert engine.default_vector_weight == 0.7
        assert engine.default_graph_weight == 0.3
    
    def test_vector_search_no_store(self):
        """Test vector search without vector store."""
        backend = Mock()
        engine = HybridSearchEngine(backend)
        
        results = engine.vector_search("test query", k=10)
        assert results == []
    
    def test_expand_graph_basic(self):
        """Test basic graph expansion."""
        backend = Mock()
        engine = HybridSearchEngine(backend)
        
        # Mock _get_neighbors to return empty list
        engine._get_neighbors = Mock(return_value=[])
        
        result = engine.expand_graph(['node1', 'node2'], max_hops=1)
        assert 'node1' in result
        assert 'node2' in result
        assert result['node1'] == 0  # Hop distance 0
        assert result['node2'] == 0
    
    def test_fuse_results_basic(self):
        """Test fusing vector and graph results."""
        backend = Mock()
        engine = HybridSearchEngine(backend)
        
        # Create mock results
        vector_results = [
            HybridSearchResult(
                node_id='node1',
                score=0.9,
                vector_score=0.9
            ),
            HybridSearchResult(
                node_id='node2',
                score=0.7,
                vector_score=0.7
            )
        ]
        
        graph_nodes = {
            'node1': 0,  # Hop distance 0
            'node3': 1   # Hop distance 1
        }
        
        fused = engine.fuse_results(
            vector_results,
            graph_nodes,
            vector_weight=0.6,
            graph_weight=0.4,
            k=10
        )
        
        assert len(fused) == 3  # node1, node2, node3
        # node1 should be first (high vector score + low hop distance)
        assert fused[0].node_id == 'node1'
    
    def test_cache_functionality(self):
        """Test result caching."""
        backend = Mock()
        vector_store = Mock()
        engine = HybridSearchEngine(backend, vector_store=vector_store)
        
        # Mock vector search to return a result
        mock_result = HybridSearchResult(node_id='node1', score=0.9, vector_score=0.9)
        engine.vector_search = Mock(return_value=[mock_result])
        engine.expand_graph = Mock(return_value={'node1': 0})
        
        # First search
        results1 = engine.search("test query", k=5, enable_cache=True)
        
        # Second search with same params should use cache
        results2 = engine.search("test query", k=5, enable_cache=True)
        
        # Vector search should only be called once due to cache
        assert engine.vector_search.call_count == 1
    
    def test_clear_cache(self):
        """Test clearing the cache."""
        backend = Mock()
        engine = HybridSearchEngine(backend)
        
        # Add something to cache
        engine._cache['test'] = []
        assert len(engine._cache) == 1
        
        engine.clear_cache()
        assert len(engine._cache) == 0


class TestUnifiedQueryEngine:
    """Tests for UnifiedQueryEngine."""
    
    def test_engine_creation(self):
        """Test unified engine can be created."""
        backend = Mock()
        engine = UnifiedQueryEngine(backend)
        
        assert engine.backend == backend
        assert engine.vector_store is None
        assert engine.llm_processor is None
        assert engine.enable_caching is True
    
    def test_engine_with_components(self):
        """Test engine with all components."""
        backend = Mock()
        vector_store = Mock()
        llm_processor = Mock()
        
        engine = UnifiedQueryEngine(
            backend=backend,
            vector_store=vector_store,
            llm_processor=llm_processor
        )
        
        assert engine.backend == backend
        assert engine.vector_store == vector_store
        assert engine.llm_processor == llm_processor
    
    def test_query_type_detection_cypher(self):
        """Test detecting Cypher queries."""
        backend = Mock()
        engine = UnifiedQueryEngine(backend)
        
        # Test various Cypher queries
        assert engine._detect_query_type("MATCH (n) RETURN n") == 'cypher'
        assert engine._detect_query_type("CREATE (n:Person)") == 'cypher'
        assert engine._detect_query_type("MERGE (n) SET n.name = 'test'") == 'cypher'
    
    def test_query_type_detection_hybrid(self):
        """Test detecting hybrid search queries."""
        backend = Mock()
        engine = UnifiedQueryEngine(backend)
        
        # Non-Cypher queries default to hybrid
        assert engine._detect_query_type("What is IPFS?") == 'hybrid'
        assert engine._detect_query_type("Find documents about AI") == 'hybrid'
    
    def test_execute_hybrid_basic(self):
        """Test basic hybrid search execution."""
        backend = Mock()
        vector_store = Mock()
        engine = UnifiedQueryEngine(backend, vector_store=vector_store)
        
        # Mock hybrid search
        mock_results = [
            HybridSearchResult(node_id='node1', score=0.9, vector_score=0.9)
        ]
        engine.hybrid_search.search = Mock(return_value=mock_results)
        
        result = engine.execute_hybrid("test query", k=5)
        
        assert result.success is True
        assert result.query_type == 'hybrid'
        assert len(result.items) == 1
        assert result.items[0]['node_id'] == 'node1'
    
    def test_execute_hybrid_with_budgets(self):
        """Test hybrid search with custom budgets."""
        backend = Mock()
        engine = UnifiedQueryEngine(backend)
        
        # Mock hybrid search
        engine.hybrid_search.search = Mock(return_value=[])
        
        # Custom budgets
        budgets = ExecutionBudgets(
            timeout_ms=5000,
            max_nodes_visited=100
        )
        
        result = engine.execute_hybrid("test query", budgets=budgets)
        
        assert result.success is True
        assert result.counters is not None
    
    def test_execute_graphrag_without_llm(self):
        """Test GraphRAG execution without LLM processor."""
        backend = Mock()
        vector_store = Mock()
        engine = UnifiedQueryEngine(backend, vector_store=vector_store)
        
        # Mock hybrid search
        engine.hybrid_search.search = Mock(return_value=[])
        
        result = engine.execute_graphrag("What is IPFS?", k=5)
        
        assert isinstance(result, GraphRAGResult)
        assert result.success is True
        assert result.query_type == 'graphrag'
        assert result.reasoning is None  # No LLM processor
    
    def test_execute_graphrag_with_llm(self):
        """Test GraphRAG execution with LLM processor."""
        backend = Mock()
        vector_store = Mock()
        llm_processor = Mock()
        
        # Mock LLM reasoning
        llm_processor.reason = Mock(return_value={
            'answer': 'IPFS is a distributed file system.',
            'confidence': 0.8,
            'evidence': []
        })
        
        engine = UnifiedQueryEngine(
            backend,
            vector_store=vector_store,
            llm_processor=llm_processor
        )
        
        # Mock hybrid search
        engine.hybrid_search.search = Mock(return_value=[])
        
        result = engine.execute_graphrag("What is IPFS?", k=5)
        
        assert isinstance(result, GraphRAGResult)
        assert result.success is True
        assert result.reasoning is not None
        assert result.confidence == 0.8
    
    def test_get_stats(self):
        """Test getting engine statistics."""
        backend = Mock()
        engine = UnifiedQueryEngine(backend)
        
        stats = engine.get_stats()
        
        assert 'backend' in stats
        assert 'vector_store_enabled' in stats
        assert 'llm_processor_enabled' in stats
        assert 'caching_enabled' in stats
        assert stats['vector_store_enabled'] is False
        assert stats['llm_processor_enabled'] is False


class TestQueryResults:
    """Tests for result dataclasses."""
    
    def test_query_result_creation(self):
        """Test QueryResult can be created."""
        result = QueryResult(
            items=[1, 2, 3],
            stats={'count': 3},
            query_type='test',
            success=True
        )
        
        assert len(result.items) == 3
        assert result.stats['count'] == 3
        assert result.query_type == 'test'
        assert result.success is True
    
    def test_query_result_to_dict(self):
        """Test converting QueryResult to dict."""
        counters = ExecutionCounters(nodes_visited=10, edges_scanned=50)
        result = QueryResult(
            items=[1, 2],
            stats={'count': 2},
            counters=counters,
            query_type='test'
        )
        
        result_dict = result.to_dict()
        
        assert 'items' in result_dict
        assert 'stats' in result_dict
        assert 'counters' in result_dict
        assert result_dict['counters']['nodes_visited'] == 10
    
    def test_graphrag_result_creation(self):
        """Test GraphRAGResult can be created."""
        result = GraphRAGResult(
            items=[],
            stats={},
            query_type='graphrag',
            reasoning={'answer': 'test'},
            confidence=0.75
        )
        
        assert result.query_type == 'graphrag'
        assert result.reasoning['answer'] == 'test'
        assert result.confidence == 0.75


class TestHybridSearchResult:
    """Tests for HybridSearchResult."""
    
    def test_hybrid_search_result_creation(self):
        """Test HybridSearchResult can be created."""
        result = HybridSearchResult(
            node_id='node1',
            score=0.9,
            vector_score=0.8,
            graph_score=0.7,
            hop_distance=1
        )
        
        assert result.node_id == 'node1'
        assert result.score == 0.9
        assert result.vector_score == 0.8
        assert result.graph_score == 0.7
        assert result.hop_distance == 1
    
    def test_hybrid_search_result_repr(self):
        """Test HybridSearchResult string representation."""
        result = HybridSearchResult(
            node_id='test_node',
            score=0.85
        )
        
        repr_str = repr(result)
        assert 'test_node' in repr_str
        assert '0.850' in repr_str


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
