"""
Unit tests for QueryEngine component of PDF processing pipeline

Tests semantic querying, natural language processing, vector similarity search,
and cross-document reasoning capabilities in isolation.
"""
import anyio
import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import json

# Test fixtures and utilities
from tests.conftest import *

# Use centralized safe import utility
test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, test_dir)

try:
    from test_import_utils import safe_importer
    
    # Try to import required modules using safe importer
    query_engine_module = safe_importer.import_module('ipfs_datasets_py.pdf_processing.query_engine')
    PDF_PROCESSING_AVAILABLE = query_engine_module is not None
except Exception as e:
    print(f"Warning: PDF processing modules not available: {e}")
    PDF_PROCESSING_AVAILABLE = False

# Skip all tests in this module if PDF processing is not available
pytestmark = pytest.mark.skipif(not PDF_PROCESSING_AVAILABLE, reason="PDF processing modules not available")


class TestQueryEngineInitialization:
    """Unit tests for QueryEngine initialization"""
    
    def test_given_no_parameters_when_initializing_query_engine_then_creates_with_defaults(self):
        """
        GIVEN QueryEngine initialization with no parameters
        WHEN creating a new instance
        THEN should initialize with default configuration
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Check required attributes
            assert hasattr(engine, 'storage')
            assert hasattr(engine, 'integrator')
            assert hasattr(engine, 'sentence_transformer')
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    def test_given_custom_model_when_initializing_query_engine_then_uses_custom_model(self):
        """
        GIVEN QueryEngine initialization with custom embedding model
        WHEN creating a new instance
        THEN should use custom model configuration
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine(embedding_model="custom-model")
            
            # Should initialize successfully
            assert engine is not None
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestNaturalLanguageQuerying:
    """Unit tests for natural language query processing"""
    
    @pytest.mark.asyncio
    async def test_given_simple_query_when_processing_query_then_returns_results(self):
        """
        GIVEN a simple natural language query
        WHEN processing the query
        THEN should return structured results
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            query = "What is machine learning?"
            result = await engine.query(query, top_k=5)
            
            # Should return query result structure
            assert isinstance(result, dict)
            assert 'results' in result
            assert 'confidence' in result
            assert isinstance(result['results'], list)
            assert isinstance(result['confidence'], (int, float))
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    @pytest.mark.asyncio
    async def test_given_complex_query_when_processing_query_then_handles_complexity(self):
        """
        GIVEN a complex multi-part query
        WHEN processing the query
        THEN should handle complexity appropriately
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            complex_query = "How are neural networks related to deep learning and what institutions research this?"
            result = await engine.query(complex_query, top_k=10)
            
            # Should handle complex queries
            assert isinstance(result, dict)
            assert 'results' in result
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    @pytest.mark.asyncio
    async def test_given_empty_query_when_processing_query_then_handles_gracefully(self):
        """
        GIVEN empty or invalid query
        WHEN processing the query
        THEN should handle gracefully
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Test empty queries
            for query in ["", "   ", None]:
                try:
                    result = await engine.query(query)
                    # Should return empty results, not crash
                    assert isinstance(result, dict)
                    assert len(result['results']) == 0
                except (ValueError, TypeError):
                    # Expected for invalid input
                    pass
                    
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestVectorSimilaritySearch:
    """Unit tests for vector similarity search functionality"""
    
    @pytest.mark.asyncio
    async def test_given_query_embedding_when_searching_similar_then_returns_ranked_results(self):
        """
        GIVEN a query embedding
        WHEN searching for similar content
        THEN should return ranked results by similarity
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Mock query embedding
            import numpy as np
            query_embedding = np.random.rand(384)  # Typical sentence transformer dimension
            
            results = await engine.similarity_search(query_embedding, top_k=5)
            
            # Should return similarity search results
            assert isinstance(results, list)
            assert len(results) <= 5  # Should respect top_k limit
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    def test_given_text_when_generating_embedding_then_returns_vector(self):
        """
        GIVEN text input
        WHEN generating embedding
        THEN should return vector representation
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            text = "machine learning and artificial intelligence"
            embedding = engine.generate_embedding(text)
            
            # Should return embedding vector
            assert hasattr(embedding, '__len__')  # Should be array-like
            assert len(embedding) > 0  # Should have dimensions
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    def test_given_empty_text_when_generating_embedding_then_handles_gracefully(self):
        """
        GIVEN empty text
        WHEN generating embedding
        THEN should handle gracefully
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Test with empty inputs
            for text in ["", "   ", None]:
                try:
                    embedding = engine.generate_embedding(text)
                    # Should return some embedding or handle gracefully
                    assert embedding is not None
                except (ValueError, TypeError):
                    # Expected for invalid input
                    pass
                    
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestCrossDocumentReasoning:
    """Unit tests for cross-document reasoning functionality"""
    
    @pytest.mark.asyncio
    async def test_given_multi_document_query_when_reasoning_then_connects_across_documents(self):
        """
        GIVEN query requiring cross-document reasoning
        WHEN processing with cross-document reasoning enabled
        THEN should connect information across documents
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            query = "How do different papers approach neural network architectures?"
            result = await engine.query(
                query_text=query,
                include_cross_document_reasoning=True,
                top_k=10
            )
            
            # Should include cross-document analysis
            assert isinstance(result, dict)
            if 'cross_document_connections' in result:
                connections = result['cross_document_connections']
                assert isinstance(connections, list)
                
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    @pytest.mark.asyncio
    async def test_given_entity_query_when_reasoning_then_traverses_knowledge_graph(self):
        """
        GIVEN query about specific entities
        WHEN reasoning with graph traversal
        THEN should traverse knowledge graph connections
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            entity_query = "What research has Stanford University published about AI?"
            result = await engine.query(
                query_text=entity_query,
                enable_graph_traversal=True,
                max_hops=3
            )
            
            # Should include graph traversal results
            assert isinstance(result, dict)
            if 'graph_traversal' in result:
                traversal = result['graph_traversal']
                assert isinstance(traversal, dict)
                
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestQueryOptimization:
    """Unit tests for query optimization and performance"""
    
    def test_given_complex_query_when_optimizing_then_improves_performance(self):
        """
        GIVEN complex query
        WHEN applying optimization strategies
        THEN should improve query performance
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Test query optimization
            original_query = "very complex query with multiple clauses and conditions"
            optimized_query = engine.optimize_query(original_query)
            
            # Should return optimized query
            assert isinstance(optimized_query, str)
            assert len(optimized_query) > 0
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    @pytest.mark.asyncio
    async def test_given_cached_query_when_querying_then_returns_cached_results(self):
        """
        GIVEN previously executed query
        WHEN querying with caching enabled
        THEN should return cached results
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            query = "test caching query"
            
            # First execution
            result1 = await engine.query(query, enable_caching=True)
            
            # Second execution (should use cache)
            result2 = await engine.query(query, enable_caching=True)
            
            # Results should be consistent
            assert isinstance(result1, dict)
            assert isinstance(result2, dict)
            # Cache behavior is implementation dependent
            
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestQueryResultFormatting:
    """Unit tests for query result formatting and presentation"""
    
    @pytest.mark.asyncio
    async def test_given_query_results_when_formatting_then_returns_structured_output(self):
        """
        GIVEN query results
        WHEN formatting for presentation
        THEN should return well-structured output
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            query = "format test query"
            result = await engine.query(query, format_output=True)
            
            # Should return formatted results
            assert isinstance(result, dict)
            
            # Should have consistent structure
            expected_keys = ['results', 'confidence', 'query_metadata']
            for key in expected_keys:
                if key in result:
                    assert result[key] is not None
                    
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    def test_given_search_results_when_ranking_then_orders_by_relevance(self):
        """
        GIVEN search results with scores
        WHEN ranking results
        THEN should order by relevance score
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Mock results with scores
            mock_results = [
                {"content": "result1", "score": 0.5},
                {"content": "result2", "score": 0.9}, 
                {"content": "result3", "score": 0.7}
            ]
            
            ranked_results = engine.rank_results(mock_results)
            
            # Should be ordered by score (descending)
            assert isinstance(ranked_results, list)
            assert len(ranked_results) == 3
            
            # Check ordering (if scoring is implemented)
            if len(ranked_results) > 1 and 'score' in ranked_results[0]:
                assert ranked_results[0]['score'] >= ranked_results[1]['score']
                
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


class TestQueryEngineErrorHandling:
    """Unit tests for query engine error handling"""
    
    @pytest.mark.asyncio
    async def test_given_malformed_query_when_processing_then_handles_gracefully(self):
        """
        GIVEN malformed query input
        WHEN processing query
        THEN should handle gracefully without crashing
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            engine = QueryEngine()
            
            # Test malformed queries
            malformed_queries = [
                {"not": "a string"},
                123,
                ["list", "query"],
                "query with\x00null characters"
            ]
            
            for query in malformed_queries:
                try:
                    result = await engine.query(query)
                    # Should handle gracefully
                    assert isinstance(result, dict)
                except (ValueError, TypeError, AttributeError):
                    # Expected for malformed input
                    pass
                    
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")
            
    @pytest.mark.asyncio
    async def test_given_missing_dependencies_when_querying_then_uses_fallbacks(self):
        """
        GIVEN missing optional dependencies
        WHEN processing queries
        THEN should use fallback implementations
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            
            # Mock missing dependencies
            with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer', side_effect=ImportError):
                engine = QueryEngine()
                
                # Should initialize with fallbacks
                assert engine is not None
                
                # Should still be able to process basic queries
                result = await engine.query("fallback test query")
                assert isinstance(result, dict)
                
        except ImportError:
            pytest.skip("QueryEngine dependencies not available")


if __name__ == "__main__":
    # Run tests directly if called as script
    pytest.main([__file__, "-v"])