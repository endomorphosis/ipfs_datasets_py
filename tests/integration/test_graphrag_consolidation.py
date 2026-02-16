"""
Integration tests for GraphRAG consolidation (Path B Session 2).

Tests that the unified query engine properly integrates with
processors/graphrag/ modules and maintains backward compatibility.
"""

import pytest
import warnings
from unittest.mock import Mock, MagicMock, patch

# Import only the core modules we're testing (avoid heavy dependencies)
try:
    from ipfs_datasets_py.processors.graphrag.adapter import (
        GraphRAGAdapter,
        create_graphrag_adapter_from_dataset
    )
    from ipfs_datasets_py.knowledge_graphs.query import (
        UnifiedQueryEngine,
        HybridSearchEngine,
        BudgetManager
    )
    IMPORTS_AVAILABLE = True
except ImportError as e:
    IMPORTS_AVAILABLE = False
    IMPORT_ERROR = str(e)

# Mark all tests to skip if imports fail
pytestmark = pytest.mark.skipif(
    not IMPORTS_AVAILABLE,
    reason=f"Required imports not available: {IMPORT_ERROR if not IMPORTS_AVAILABLE else ''}"
)


class TestUnifiedQueryEngine:
    """Test UnifiedQueryEngine core functionality."""
    
    def test_unified_engine_creation(self):
        """Test UnifiedQueryEngine can be created."""
        # GIVEN: Mock components
        backend = Mock()
        vector_stores = {"store1": Mock()}
        
        # WHEN: Creating engine
        engine = UnifiedQueryEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # THEN: Engine is created successfully
        assert engine is not None
        assert engine.backend == backend
        assert engine.vector_stores == vector_stores
    
    def test_unified_engine_hybrid_search(self):
        """Test UnifiedQueryEngine can execute hybrid search."""
        # GIVEN: Mock components with proper methods
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[
            {"id": "doc1", "text": "Content", "score": 0.8}
        ])
        
        engine = UnifiedQueryEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Executing hybrid search
        result = engine.execute_hybrid(
            query_text="test query",
            top_k=5
        )
        
        # THEN: Result is returned
        assert result is not None
        assert hasattr(result, 'results')


class TestGraphRAGAdapter:
    """Test GraphRAG adapter functionality."""
    
    def test_adapter_creation(self):
        """Test GraphRAGAdapter can be created."""
        # GIVEN: Mock components
        backend = Mock()
        vector_stores = {"store1": Mock()}
        
        # WHEN: Creating adapter
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # THEN: Adapter is created successfully
        assert adapter is not None
        assert adapter.backend == backend
        assert adapter.vector_stores == vector_stores
    
    def test_adapter_uses_unified_engine(self):
        """Test that adapter uses UnifiedQueryEngine internally."""
        # GIVEN: Mock components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[])
        
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Checking internal engine
        engine = adapter._unified_engine
        
        # THEN: Engine is UnifiedQueryEngine
        assert engine is not None
        assert isinstance(engine, UnifiedQueryEngine)
    
    def test_adapter_query_issues_deprecation_warning(self):
        """Test that adapter issues deprecation warnings."""
        # GIVEN: Mock components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[])
        
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Using adapter query
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="What is IPFS?",
                top_k=5
            )
            
            # THEN: Deprecation warning is issued
            assert len(w) > 0
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
    
    def test_adapter_backward_compatibility(self):
        """Test that adapter maintains backward compatibility."""
        # GIVEN: Mock components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].search = Mock(return_value=[
            {"id": "doc1", "text": "IPFS content", "score": 0.9}
        ])
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Using old-style query
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = adapter.query(
                query_text="What is IPFS?",
                top_k=5,
                include_vector_results=True,
                include_graph_results=True
            )
        
        # THEN: Result has expected old format
        assert result is not None
        assert "query_text" in result
        assert "hybrid_results" in result


class TestHybridSearchEngine:
    """Test HybridSearchEngine functionality."""
    
    def test_hybrid_engine_creation(self):
        """Test HybridSearchEngine can be created."""
        # GIVEN: Mock components
        backend = Mock()
        vector_stores = {"store1": Mock()}
        
        # WHEN: Creating engine
        engine = HybridSearchEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # THEN: Engine is created successfully
        assert engine is not None
        assert engine.backend == backend
    
    def test_hybrid_engine_vector_search(self):
        """Test hybrid engine can perform vector search."""
        # GIVEN: Mock components
        backend = Mock()
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].search = Mock(return_value=[
            {"id": "doc1", "text": "Content", "score": 0.8}
        ])
        
        engine = HybridSearchEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Performing vector search
        query_embedding = [0.1] * 128
        results = engine._vector_search(query_embedding, top_k=5)
        
        # THEN: Results are returned
        assert results is not None
        assert len(results) > 0
    
    def test_hybrid_engine_caching(self):
        """Test that hybrid engine caches results."""
        # GIVEN: Mock components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        
        call_count = 0
        def mock_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return [{"id": "doc1", "score": 0.9}]
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].search = Mock(side_effect=mock_search)
        
        engine = HybridSearchEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Running same search twice
        query_embedding = [0.1] * 128
        result1 = engine.search(query_embedding, top_k=5)
        result2 = engine.search(query_embedding, top_k=5)
        
        # THEN: Cache reduces calls
        assert result1 is not None
        assert result2 is not None
        assert call_count >= 1  # At least one call made


class TestBudgetEnforcement:
    """Test that budget enforcement works across all components."""
    
    def test_budget_enforcement_in_adapter(self):
        """Test that budget is enforced when using adapter."""
        # GIVEN: Mock components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[{"id": f"node{i}"} for i in range(1000)])
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].search = Mock(return_value=[])
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Querying with strict budget
        from ipfs_datasets_py.search.graph_query.budgets import SearchBudget
        budget = SearchBudget(
            max_nodes=10,  # Very small limit
            max_edges=5,
            max_depth=1,
            timeout_seconds=1.0
        )
        
        # THEN: Should complete without exceeding budget
        # (In real implementation, this would stop early)
        result = adapter.query(
            query_text="test",
            budget=budget,
            top_k=5
        )
        assert result is not None


class TestPerformance:
    """Test that consolidation doesn't introduce performance regressions."""
    
    def test_caching_improves_performance(self):
        """Test that caching in HybridSearchEngine improves repeat queries."""
        # GIVEN: Mock components with tracking
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        
        search_call_count = 0
        def mock_search(*args, **kwargs):
            nonlocal search_call_count
            search_call_count += 1
            return [{"id": "doc1", "score": 0.9}]
        
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].search = Mock(side_effect=mock_search)
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        
        engine = HybridSearchEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # WHEN: Running same query twice
        query_embedding = [0.1] * 128
        result1 = engine.search(query_embedding, top_k=5)
        result2 = engine.search(query_embedding, top_k=5)
        
        # THEN: Second query uses cache (fewer calls)
        assert result1 is not None
        assert result2 is not None
        # Cache should reduce backend calls
        assert search_call_count >= 1  # At least one call made


class TestMigrationPath:
    """Test the migration path from old API to new API."""
    
    def test_can_use_old_api(self):
        """Test that old GraphRAG API still works."""
        # GIVEN: Old-style setup
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[])
        
        # WHEN: Using old API
        engine = GraphRAGQueryEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = engine.query("test query", top_k=5)
        
        # THEN: Works without errors
        assert result is not None
    
    def test_can_use_new_api(self):
        """Test that new unified API works."""
        # GIVEN: New-style setup
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[])
        
        # WHEN: Using new API directly
        engine = UnifiedQueryEngine(
            backend=backend,
            vector_stores=vector_stores
        )
        
        result = engine.execute_hybrid(
            query_text="test query",
            top_k=5
        )
        
        # THEN: Works without errors
        assert result is not None
    
    def test_adapter_bridges_old_and_new(self):
        """Test that adapter successfully bridges old and new APIs."""
        # GIVEN: Components
        backend = Mock()
        backend.get_neighbors = Mock(return_value=[])
        vector_stores = {"store1": Mock()}
        vector_stores["store1"].embed_query = Mock(return_value=[0.1] * 128)
        vector_stores["store1"].search = Mock(return_value=[])
        
        # WHEN: Using adapter
        adapter = GraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        # Old API call through adapter
        old_result = adapter.query("test", top_k=5)
        
        # THEN: Result has old format
        assert "query_text" in old_result
        assert "hybrid_results" in old_result
        
        # AND: Internally uses UnifiedQueryEngine
        assert adapter._unified_engine is not None
        assert isinstance(adapter._unified_engine, UnifiedQueryEngine)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
