import pytest
import asyncio
import os
import tempfile
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# Define sample data
sample_embeddings = np.random.rand(20, 384).tolist()
sample_metadata = [{"id": i, "text": f"sample text {i}"} for i in range(20)]

# Define test constants
TEST_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
TEST_BATCH_SIZE = 16

@pytest.fixture
def temp_dir():
    """Provides a temporary directory for test artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir

@pytest.fixture
def mock_embedding_service():
    """Provides a mock EmbeddingService instance."""
    mock_service = Mock()
    mock_service.create_embeddings = AsyncMock(return_value={
        "success": True,
        "embeddings": sample_embeddings,
        "metadata": sample_metadata,
        "count": len(sample_embeddings)
    })
    mock_service.generate_embedding = AsyncMock(return_value=sample_embeddings[0])
    mock_service.generate_batch_embeddings = AsyncMock(return_value=sample_embeddings)
    mock_service.compare_embeddings = AsyncMock(return_value={"similarity_score": 0.8})
    return mock_service

@pytest.fixture
def mock_search_service():
    """Provides a mock SearchService instance."""
    mock_service = Mock()
    mock_service.search = AsyncMock(return_value={
        "success": True,
        "results": [{"id": "1", "score": 0.9, "text": "Result 1"}],
        "query_time": 0.1
    })
    mock_service.batch_search = AsyncMock(return_value={
        "success": True,
        "total_queries": 1,
        "results": [{"query": "test", "results": [{"id": "1", "score": 0.9}]}]
    })
    return mock_service

@pytest.fixture
def mock_storage_manager():
    """Provides a mock StorageManager instance."""
    mock_manager = Mock()
    mock_manager.save_embeddings = AsyncMock(return_value={
        "success": True,
        "file_path": "/mock/path/embeddings.parquet",
        "count": 10,
        "size_bytes": 1000
    })
    mock_manager.load_embeddings = AsyncMock(return_value={
        "success": True,
        "embeddings": sample_embeddings[:5],
        "metadata": sample_metadata[:5],
        "count": 5
    })
    return mock_manager

@pytest.fixture
def mock_vector_service():
    """Provides a mock VectorService instance."""
    mock_service = Mock()
    mock_service.create_index = AsyncMock(return_value={"success": True, "store_id": "mock_store_id"})
    mock_service.update_index = AsyncMock(return_value={"success": True})
    mock_service.delete_index = AsyncMock(return_value={"success": True})
    mock_service.get_index_info = AsyncMock(return_value={"success": True, "stats": {"total_vectors": 100}})
    mock_service.retrieve_vectors = AsyncMock(return_value=[{"id": "1", "vector": [0.1]*384}])
    mock_service.get_vector_metadata = AsyncMock(return_value={"success": True, "metadata": {"key": "value"}})
    mock_service.update_vector_metadata = AsyncMock(return_value={"success": True})
    mock_service.delete_vector_metadata = AsyncMock(return_value={"success": True})
    mock_service.list_vector_metadata = AsyncMock(return_value=[{"id": "1", "metadata": {"key": "value"}}])
    mock_service.index_knn = AsyncMock(return_value=[{"id": "1", "score": 0.9}]) # Used by search_embeddings
    return mock_service


def create_sample_file(file_path, content):
    """Helper function to create a sample file."""
    with open(file_path, "w") as f:
        f.write(content)
