"""
Tests for SearchGraphRAGAdapter

Tests the adapter layer that bridges search/graphrag_integration to
the unified query engine.
"""

import pytest
import warnings
import numpy as np
from unittest.mock import Mock, MagicMock, patch

# Try to import the adapter
try:
    from ipfs_datasets_py.search.graphrag_integration.adapter import (
        SearchGraphRAGAdapter,
        create_search_adapter_from_dataset,
        HAVE_UNIFIED_ENGINE
    )
    HAVE_ADAPTER = True
except ImportError:
    HAVE_ADAPTER = False
    pytest.skip("SearchGraphRAGAdapter not available", allow_module_level=True)


class TestSearchGraphRAGAdapter:
    """Test SearchGraphRAGAdapter functionality."""
    
    def test_adapter_creation(self):
        """Test adapter can be created."""
        backend = Mock()
        vector_stores = {"default": Mock()}
        
        adapter = SearchGraphRAGAdapter(
            backend=backend,
            vector_stores=vector_stores
        )
        
        assert adapter.backend == backend
        assert adapter.vector_stores == vector_stores
        assert isinstance(adapter.metrics, dict)
    
    def test_hybrid_search_returns_list(self):
        """Test that hybrid_search returns list."""
        backend = Mock()
        adapter = SearchGraphRAGAdapter(
            backend=backend,
            issue_deprecation_warnings=False
        )
        
        query_embedding = np.random.rand(128)
        result = adapter.hybrid_search(query_embedding, top_k=10)
        
        assert isinstance(result, list)
    
    def test_graphrag_query_returns_dict(self):
        """Test that graphrag_query returns dict."""
        backend = Mock()
        adapter = SearchGraphRAGAdapter(
            backend=backend,
            issue_deprecation_warnings=False
        )
        
        result = adapter.graphrag_query("test query", top_k=10)
        
        assert isinstance(result, dict)
        assert "query_text" in result
        assert "hybrid_results" in result
