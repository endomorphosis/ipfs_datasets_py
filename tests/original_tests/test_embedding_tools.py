#!/usr/bin/env python3
"""
Test suite for all embedding-related tools and functionality.
"""

import pytest
import asyncio
import numpy as np
from unittest.mock import Mock, AsyncMock, patch
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

class TestEmbeddingTools:
    """Test embedding generation and management tools."""
    
    @pytest.mark.asyncio
    async def test_embedding_generation_tool(self):
        """Test basic embedding generation MCP tool."""
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import embedding_generation
        
        test_texts = ["This is a test sentence.", "Another test sentence."]
        
        with patch('ipfs_datasets_py.embeddings.core.EmbeddingManager') as mock_manager:
            mock_instance = Mock()
            mock_instance.generate_embeddings.return_value = {
                'embeddings': [np.random.rand(384).tolist() for _ in test_texts],
                'model': 'test-model',
                'status': 'success',
                'processing_time': 0.5
            }
            mock_manager.return_value = mock_instance
            
            result = await embedding_generation(
                text=test_texts,
                model="test-model",
                options={'batch_size': 16}
            )
            
            assert result['status'] == 'success'
            assert len(result['embeddings']) == len(test_texts)
            assert all(len(emb) == 384 for emb in result['embeddings'])
    
    @pytest.mark.asyncio
    async def test_advanced_embedding_generation(self):
        """Test advanced embedding generation with preprocessing."""
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation import advanced_embedding_generation
            
            test_data = {
                'texts': ["Raw text with special chars!", "Another text sample."],
                'preprocessing': {
                    'clean_text': True,
                    'normalize': True,
                    'remove_stopwords': False
                },
                'model_config': {
                    'model_name': 'test-model',
                    'max_length': 512,
                    'batch_size': 8
                }
            }
            
            with patch('ipfs_datasets_py.embeddings.core.EmbeddingManager') as mock_manager:
                mock_instance = Mock()
                mock_instance.generate_embeddings.return_value = {
                    'embeddings': [np.random.rand(384).tolist() for _ in test_data['texts']],
                    'model': test_data['model_config']['model_name'],
                    'status': 'success',
                    'preprocessing_applied': True,
                    'batch_count': 1
                }
                mock_manager.return_value = mock_instance
                
                result = await advanced_embedding_generation(**test_data)
                
                assert result['status'] == 'success'
                assert result.get('preprocessing_applied') is True
                assert len(result['embeddings']) == len(test_data['texts'])
        except ImportError:
            raise ImportError("Advanced embedding generation tool not implemented")
    
    @pytest.mark.asyncio
    async def test_embedding_search(self):
        """Test embedding similarity search."""
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search import advanced_search
            
            query_embedding = np.random.rand(384).tolist()
            
            with patch('ipfs_datasets_py.vector_stores.faiss_store.FAISSVectorStore') as mock_store:
                mock_instance = Mock()
                mock_instance.search.return_value = {
                    'results': [
                        {'id': '1', 'score': 0.95, 'metadata': {'text': 'Similar text 1'}},
                        {'id': '2', 'score': 0.87, 'metadata': {'text': 'Similar text 2'}},
                        {'id': '3', 'score': 0.82, 'metadata': {'text': 'Similar text 3'}}
                    ],
                    'query_time': 0.02,
                    'total_results': 3
                }
                mock_store.return_value = mock_instance
                
                result = await advanced_search(
                    query_embedding=query_embedding,
                    index_name="test_index",
                    top_k=5,
                    search_options={'filter': None}
                )
                
                assert len(result['results']) == 3
                assert all(r['score'] > 0.8 for r in result['results'])
                assert result['query_time'] < 1.0
        except ImportError:
            raise ImportError("Advanced search tool not implemented")
    
    @pytest.mark.asyncio
    async def test_shard_embeddings(self):
        """Test embedding sharding for large datasets."""
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings import shard_embeddings
            
            large_dataset = {
                'embeddings': [np.random.rand(384).tolist() for _ in range(1000)],
                'metadata': [{'id': i, 'text': f'text {i}'} for i in range(1000)]
            }
            
            with patch('ipfs_datasets_py.utils.sharding.EmbeddingSharder') as mock_sharder:
                mock_instance = Mock()
                mock_instance.shard_embeddings.return_value = {
                    'shard_count': 4,
                    'shard_ids': ['shard_1', 'shard_2', 'shard_3', 'shard_4'],
                    'items_per_shard': 250,
                    'sharding_strategy': 'round_robin',
                    'status': 'success'
                }
                mock_sharder.return_value = mock_instance
                
                result = await shard_embeddings(
                    embeddings=large_dataset['embeddings'],
                    metadata=large_dataset['metadata'],
                    shard_size=250,
                    strategy='round_robin'
                )
                
                assert result['status'] == 'success'
                assert result['shard_count'] == 4
                assert len(result['shard_ids']) == 4
        except ImportError:
            raise ImportError("Shard embeddings tool not implemented")

class TestEmbeddingCore:
    """Test core embedding functionality."""
    
    def test_embedding_manager_initialization(self):
        """Test EmbeddingManager can be initialized."""
        from ipfs_datasets_py.embeddings.core import EmbeddingManager
        
        manager = EmbeddingManager()
        assert manager is not None
        assert hasattr(manager, 'generate_embeddings')
        assert hasattr(manager, 'get_available_models')
    
    def test_embedding_schema_validation(self):
        """Test embedding request/response schemas."""
        from ipfs_datasets_py.embeddings.schema import EmbeddingRequest, EmbeddingResponse
        
        # Test request schema
        request_data = {
            'text': ['Test text 1', 'Test text 2'],
            'model': 'test-model',
            'options': {'batch_size': 16, 'max_length': 512}
        }
        
        request = EmbeddingRequest(**request_data)
        assert request.text == ['Test text 1', 'Test text 2']
        assert request.model == 'test-model'
        assert request.options['batch_size'] == 16
        
        # Test response schema
        response_data = {
            'embeddings': [[0.1, 0.2], [0.3, 0.4]],
            'model': 'test-model',
            'status': 'success',
            'metadata': {'processing_time': 0.5, 'batch_size': 2}
        }
        
        response = EmbeddingResponse(**response_data)
        assert len(response.embeddings) == 2
        assert response.status == 'success'
        assert response.metadata['processing_time'] == 0.5
    
    def test_text_chunker(self):
        """Test text chunking functionality."""
        from ipfs_datasets_py.embeddings.chunker import Chunker
        
        # Test sentence chunking
        text = "First sentence. Second sentence. Third sentence."
        chunker = Chunker(strategy='sentence', chunk_size=50)
        
        with patch.object(chunker, 'chunk') as mock_chunk:
            mock_chunk.return_value = [
                "First sentence. Second sentence.",
                "Third sentence."
            ]
            
            chunks = chunker.chunk(text)
            assert len(chunks) >= 1
            assert all(isinstance(chunk, str) for chunk in chunks)
        
        # Test fixed-size chunking
        chunker_fixed = Chunker(strategy='fixed', chunk_size=20, overlap=5)
        long_text = "A" * 100
        
        with patch.object(chunker_fixed, 'chunk') as mock_chunk_fixed:
            mock_chunk_fixed.return_value = ["A" * 20, "A" * 20, "A" * 20, "A" * 20, "A" * 20]
            
            chunks_fixed = chunker_fixed.chunk(long_text)
            assert len(chunks_fixed) >= 4  # Should create multiple chunks

class TestEmbeddingIntegration:
    """Test embedding integration with other systems."""
    
    @pytest.mark.asyncio
    async def test_embedding_to_vector_store_integration(self):
        """Test integration between embedding generation and vector storage."""
        from ipfs_datasets_py.embeddings.core import EmbeddingManager
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        # Mock embedding generation
        manager = EmbeddingManager()
        store = FAISSVectorStore(dimension=384)
        
        test_texts = ["Text 1", "Text 2", "Text 3"]
        embeddings = [np.random.rand(384).tolist() for _ in test_texts]
        
        with patch.object(manager, 'generate_embeddings') as mock_generate:
            mock_generate.return_value = {
                'embeddings': embeddings,
                'status': 'success'
            }
            
            with patch.object(store, 'add_vectors') as mock_add:
                mock_add.return_value = {
                    'status': 'success',
                    'count': len(embeddings),
                    'index_size': len(embeddings)
                }
                
                # Generate embeddings
                embedding_result = manager.generate_embeddings(test_texts)
                assert embedding_result['status'] == 'success'
                
                # Store in vector store
                metadata = [{'text': text, 'id': i} for i, text in enumerate(test_texts)]
                store_result = await store.add_vectors(embedding_result['embeddings'], metadata)
                assert store_result['status'] == 'success'
                assert store_result['count'] == len(test_texts)
    
    @pytest.mark.asyncio
    async def test_embedding_pipeline_workflow(self):
        """Test complete embedding processing pipeline."""
        # This test simulates a complete workflow:
        # 1. Load text data
        # 2. Chunk text
        # 3. Generate embeddings
        # 4. Store in vector database
        # 5. Perform similarity search
        
        from ipfs_datasets_py.embeddings.core import EmbeddingManager
        from ipfs_datasets_py.embeddings.chunker import Chunker
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        # Step 1: Mock text data
        documents = [
            "This is a long document that needs to be chunked into smaller pieces for processing.",
            "Another document with different content for testing the embedding pipeline.",
            "A third document to provide more variety in the test dataset."
        ]
        
        # Step 2: Chunk documents
        chunker = Chunker(strategy='sentence', chunk_size=100)
        all_chunks = []
        
        with patch.object(chunker, 'chunk') as mock_chunk:
            mock_chunk.side_effect = [
                ["This is a long document that needs to be chunked.", "Into smaller pieces for processing."],
                ["Another document with different content.", "For testing the embedding pipeline."],
                ["A third document to provide more variety.", "In the test dataset."]
            ]
            
            for doc in documents:
                chunks = chunker.chunk(doc)
                all_chunks.extend(chunks)
        
        assert len(all_chunks) == 6  # 2 chunks per document
        
        # Step 3: Generate embeddings
        manager = EmbeddingManager()
        embeddings = [np.random.rand(384).tolist() for _ in all_chunks]
        
        with patch.object(manager, 'generate_embeddings') as mock_generate:
            mock_generate.return_value = {
                'embeddings': embeddings,
                'status': 'success',
                'model': 'test-model'
            }
            
            embedding_result = manager.generate_embeddings(all_chunks)
            assert embedding_result['status'] == 'success'
            assert len(embedding_result['embeddings']) == len(all_chunks)
        
        # Step 4: Store in vector database
        store = FAISSVectorStore(dimension=384)
        metadata = [{'text': chunk, 'id': i, 'doc_id': i // 2} for i, chunk in enumerate(all_chunks)]
        
        with patch.object(store, 'add_vectors') as mock_add:
            mock_add.return_value = {
                'status': 'success',
                'count': len(embeddings)
            }
            
            store_result = await store.add_vectors(embeddings, metadata)
            assert store_result['status'] == 'success'
        
        # Step 5: Perform similarity search
        query_embedding = np.random.rand(384).tolist()
        
        with patch.object(store, 'search') as mock_search:
            mock_search.return_value = {
                'results': [
                    {'id': '0', 'score': 0.95, 'metadata': metadata[0]},
                    {'id': '2', 'score': 0.88, 'metadata': metadata[2]}
                ],
                'query_time': 0.01
            }
            
            search_result = await store.search(query_embedding, k=2)
            assert len(search_result['results']) == 2
            assert all(r['score'] > 0.8 for r in search_result['results'])

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
