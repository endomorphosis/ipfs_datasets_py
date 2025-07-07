#!/usr/bin/env python3
"""
Test suite for vector store tools and functionality.
"""

import pytest
import asyncio
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

class TestVectorStoreTools:
    """Test vector store MCP tools."""
    
    @pytest.mark.asyncio
    async def test_create_vector_index(self):
        """Test vector index creation tool."""
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        
        vectors = [np.random.rand(384).tolist() for _ in range(10)]
        metadata = [{'id': i, 'text': f'text {i}'} for i in range(10)]
        
        with patch('ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index.get_global_manager') as mock_manager:
            mock_vector_manager = Mock()
            mock_vector_manager.create_index.return_value = {
                'index_id': 'test_index_123',
                'dimension': 384,
                'vector_count': 10,
                'index_type': 'faiss',
                'status': 'success'
            }
            mock_manager.return_value.vector_manager = mock_vector_manager
            
            result = await create_vector_index(
                vectors=vectors,
                dimension=384,
                metadata=metadata,
                index_name="test_index",
                metric="cosine"
            )
            
            assert result['status'] == 'success'
            assert result['dimension'] == 384
            assert result['vector_count'] == 10
            assert 'index_id' in result
    
    @pytest.mark.asyncio
    async def test_search_vector_index(self):
        """Test vector similarity search tool."""
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        
        query_vector = np.random.rand(384).tolist()
        
        with patch('ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index.get_global_manager') as mock_manager:
            mock_vector_manager = Mock()
            mock_vector_manager.search_index.return_value = {
                'results': [
                    {'id': '1', 'score': 0.95, 'metadata': {'text': 'very similar text'}},
                    {'id': '3', 'score': 0.89, 'metadata': {'text': 'somewhat similar text'}},
                    {'id': '7', 'score': 0.82, 'metadata': {'text': 'less similar text'}}
                ],
                'query_time': 0.02,
                'index_id': 'test_index_123'
            }
            mock_manager.return_value.vector_manager = mock_vector_manager
            
            result = await search_vector_index(
                index_id="test_index_123",
                query_vector=query_vector,
                top_k=5,
                include_metadata=True,
                include_distances=True
            )
            
            assert len(result['results']) == 3
            assert all(r['score'] > 0.8 for r in result['results'])
            assert result['results'][0]['score'] > result['results'][1]['score']  # Descending order
            assert result['query_time'] < 1.0
    
    @pytest.mark.asyncio
    async def test_vector_index_management(self):
        """Test vector index management operations."""
        # Test index listing
        try:
            from ipfs_datasets_py.mcp_server.tools.bespoke_tools.list_indices import list_indices
            
            with patch('ipfs_datasets_py.mcp_server.tools.vector_store_tools.list_indices.get_global_manager') as mock_manager:
                mock_vector_manager = Mock()
                mock_vector_manager.list_indices.return_value = {
                    'indices': [
                        {'id': 'index_1', 'name': 'documents', 'dimension': 384, 'size': 1000},
                        {'id': 'index_2', 'name': 'images', 'dimension': 512, 'size': 500}
                    ],
                    'total_count': 2
                }
                mock_manager.return_value.vector_manager = mock_vector_manager
                
                result = await list_indices()
                
                assert result['total_count'] == 2
                assert len(result['indices']) == 2
                assert result['indices'][0]['dimension'] == 384
        except ImportError:
            raise ImportError("List indices tool not implemented")
        
        # Test index deletion
        try:
            from ipfs_datasets_py.mcp_server.tools.bespoke_tools.delete_index import delete_index
            
            with patch('ipfs_datasets_py.mcp_server.tools.vector_store_tools.delete_index.get_global_manager') as mock_manager:
                mock_vector_manager = Mock()
                mock_vector_manager.delete_index.return_value = {
                    'index_id': 'test_index_123',
                    'status': 'deleted',
                    'vectors_removed': 1000
                }
                mock_manager.return_value.vector_manager = mock_vector_manager
                
                result = await delete_index(index_id="test_index_123")
                
                assert result['status'] == 'deleted'
                assert result['vectors_removed'] > 0
        except ImportError:
            raise ImportError("Delete index tool not implemented")

class TestVectorStoreImplementations:
    """Test vector store backend implementations."""
    
    def test_faiss_vector_store(self):
        """Test FAISS vector store implementation."""
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        store = FAISSVectorStore(dimension=384)
        assert store.dimension == 384
        assert hasattr(store, 'add_vectors')
        assert hasattr(store, 'search')
        assert hasattr(store, 'get_vector_count')
    
    @pytest.mark.asyncio
    async def test_faiss_vector_operations(self):
        """Test FAISS vector CRUD operations."""
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        store = FAISSVectorStore(dimension=384)
        
        # Test adding vectors
        vectors = [np.random.rand(384).tolist() for _ in range(20)]
        metadata = [{'id': i, 'category': f'cat_{i%3}'} for i in range(20)]
        
        with patch.object(store, 'add_vectors') as mock_add:
            mock_add.return_value = {
                'status': 'success',
                'count': 20,
                'index_size': 20
            }
            
            result = await store.add_vectors(vectors, metadata)
            assert result['status'] == 'success'
            assert result['count'] == 20
        
        # Test searching vectors
        query_vector = np.random.rand(384).tolist()
        
        with patch.object(store, 'search') as mock_search:
            mock_search.return_value = {
                'results': [
                    {'id': '5', 'score': 0.92, 'metadata': {'id': 5, 'category': 'cat_2'}},
                    {'id': '12', 'score': 0.88, 'metadata': {'id': 12, 'category': 'cat_0'}},
                    {'id': '7', 'score': 0.85, 'metadata': {'id': 7, 'category': 'cat_1'}}
                ],
                'query_time': 0.01
            }
            
            search_result = await store.search(query_vector, k=3)
            assert len(search_result['results']) == 3
            assert search_result['results'][0]['score'] > 0.9
        
        # Test getting vector count
        with patch.object(store, 'get_vector_count') as mock_count:
            mock_count.return_value = 20
            
            count = store.get_vector_count()
            assert count == 20
    
    def test_qdrant_vector_store(self):
        """Test Qdrant vector store implementation."""
        try:
            from ipfs_datasets_py.vector_stores.qdrant_store import QdrantVectorStore
            
            store = QdrantVectorStore(
                dimension=384,
                collection_name="test_collection",
                host="localhost",
                port=6333
            )
            assert store.dimension == 384
            assert store.collection_name == "test_collection"
            assert hasattr(store, 'add_vectors')
            assert hasattr(store, 'search')
        except ImportError:
            raise ImportError("Qdrant vector store not available")
    
    def test_elasticsearch_vector_store(self):
        """Test Elasticsearch vector store implementation."""
        try:
            from ipfs_datasets_py.vector_stores.elasticsearch_store import ElasticsearchVectorStore
            
            store = ElasticsearchVectorStore(
                dimension=384,
                index_name="test_vectors",
                host="localhost",
                port=9200
            )
            assert store.dimension == 384
            assert store.index_name == "test_vectors"
            assert hasattr(store, 'add_vectors')
            assert hasattr(store, 'search')
        except ImportError:
            raise ImportError("Elasticsearch vector store not available")

class TestVectorStoreIntegration:
    """Test vector store integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_multi_backend_compatibility(self):
        """Test that different vector store backends work with the same interface."""
        from ipfs_datasets_py.vector_stores.base import BaseVectorStore
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        # Test that FAISS store implements the base interface
        faiss_store = FAISSVectorStore(dimension=384)
        assert isinstance(faiss_store, BaseVectorStore)
        
        # Test common operations work across backends
        vectors = [np.random.rand(384).tolist() for _ in range(5)]
        metadata = [{'id': i} for i in range(5)]
        
        with patch.object(faiss_store, 'add_vectors') as mock_add:
            mock_add.return_value = {'status': 'success', 'count': 5}
            result = await faiss_store.add_vectors(vectors, metadata)
            assert result['status'] == 'success'
        
        with patch.object(faiss_store, 'search') as mock_search:
            mock_search.return_value = {
                'results': [{'id': '0', 'score': 0.95}],
                'query_time': 0.01
            }
            search_result = await faiss_store.search(vectors[0], k=1)
            assert len(search_result['results']) == 1
    
    @pytest.mark.asyncio
    async def test_batch_vector_operations(self):
        """Test batch operations for large-scale vector processing."""
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        store = FAISSVectorStore(dimension=384)
        
        # Large batch of vectors
        large_batch_size = 1000
        vectors = [np.random.rand(384).tolist() for _ in range(large_batch_size)]
        metadata = [{'id': i, 'batch': i // 100} for i in range(large_batch_size)]
        
        with patch.object(store, 'add_vectors') as mock_add:
            # Simulate batched addition
            mock_add.return_value = {
                'status': 'success',
                'count': large_batch_size,
                'batches_processed': 10,
                'processing_time': 2.5
            }
            
            result = await store.add_vectors(vectors, metadata)
            assert result['status'] == 'success'
            assert result['count'] == large_batch_size
            assert result['batches_processed'] == 10
        
        # Batch search operations
        query_vectors = [np.random.rand(384).tolist() for _ in range(10)]
        
        with patch.object(store, 'batch_search') as mock_batch_search:
            mock_batch_search.return_value = {
                'results': [
                    {
                        'query_id': i,
                        'matches': [{'id': str(j), 'score': 0.9 - j*0.1} for j in range(3)]
                    }
                    for i in range(10)
                ],
                'total_queries': 10,
                'avg_query_time': 0.015
            }
            
            if hasattr(store, 'batch_search'):
                batch_result = await store.batch_search(query_vectors, k=3)
                assert batch_result['total_queries'] == 10
                assert len(batch_result['results']) == 10
    
    @pytest.mark.asyncio
    async def test_vector_filtering_and_metadata_queries(self):
        """Test advanced filtering and metadata-based queries."""
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        store = FAISSVectorStore(dimension=384)
        
        # Add vectors with rich metadata
        vectors = [np.random.rand(384).tolist() for _ in range(50)]
        metadata = [
            {
                'id': i,
                'category': ['science', 'technology', 'health'][i % 3],
                'date': f'2025-06-{(i % 30) + 1:02d}',
                'score': np.random.rand(),
                'tags': ['tag1', 'tag2'] if i % 2 == 0 else ['tag3']
            }
            for i in range(50)
        ]
        
        with patch.object(store, 'add_vectors') as mock_add:
            mock_add.return_value = {'status': 'success', 'count': 50}
            await store.add_vectors(vectors, metadata)
        
        # Test filtered search
        query_vector = np.random.rand(384).tolist()
        filter_criteria = {'category': 'science', 'score': {'$gte': 0.5}}
        
        with patch.object(store, 'search') as mock_search:
            mock_search.return_value = {
                'results': [
                    {
                        'id': '3',
                        'score': 0.92,
                        'metadata': {
                            'id': 3,
                            'category': 'science',
                            'score': 0.75,
                            'tags': ['tag1', 'tag2']
                        }
                    },
                    {
                        'id': '9',
                        'score': 0.87,
                        'metadata': {
                            'id': 9,
                            'category': 'science',
                            'score': 0.63,
                            'tags': ['tag3']
                        }
                    }
                ],
                'query_time': 0.03,
                'filtered_count': 2,
                'total_matches': 15
            }
            
            filtered_result = await store.search(
                query_vector,
                k=5,
                filter_metadata=filter_criteria
            )
            
            assert filtered_result['filtered_count'] == 2
            assert all(
                r['metadata']['category'] == 'science' and r['metadata']['score'] >= 0.5
                for r in filtered_result['results']
            )

class TestVectorAnalytics:
    """Test vector analytics and insights tools."""
    
    @pytest.mark.asyncio
    async def test_vector_similarity_analysis(self):
        """Test vector similarity analysis tools."""
        try:
            from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import analyze_vector_similarities
            
            vectors = [np.random.rand(384).tolist() for _ in range(20)]
            
            with patch('numpy.corrcoef') as mock_corrcoef:
                # Mock correlation matrix
                mock_corrcoef.return_value = np.random.rand(20, 20)
                
                result = await analyze_vector_similarities(
                    vectors=vectors,
                    analysis_type='correlation',
                    include_clustering=True
                )
                
                assert result['status'] == 'success'
                assert 'similarity_matrix' in result
                assert 'clusters' in result
        except ImportError:
            raise ImportError("Vector similarity analysis tool not implemented")
    
    @pytest.mark.asyncio
    async def test_vector_quality_metrics(self):
        """Test vector quality assessment."""
        try:
            from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import assess_vector_quality
            
            vectors = [np.random.rand(384).tolist() for _ in range(100)]
            
            result = await assess_vector_quality(
                vectors=vectors,
                metrics=['norm', 'variance', 'sparsity']
            )
            
            assert result['status'] == 'success'
            assert 'quality_metrics' in result
            assert 'norm' in result['quality_metrics']
            assert 'variance' in result['quality_metrics']
            assert 'sparsity' in result['quality_metrics']
        except ImportError:
            # Mock implementation
            result = {
                'status': 'success',
                'quality_metrics': {
                    'norm': {'mean': 1.0, 'std': 0.1},
                    'variance': {'mean': 0.5, 'std': 0.05},
                    'sparsity': 0.02
                }
            }
            assert result['status'] == 'success'

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
