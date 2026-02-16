"""Unit tests for IPLD Vector Store implementation.

Tests the IPLDVectorStore functionality including collection management,
vector operations, router integration, and IPLD export/import.
"""

import pytest
import numpy as np
from typing import List

# Import modules to test
from ipfs_datasets_py.vector_stores import (
    IPLDVectorStore,
    UnifiedVectorStoreConfig,
    create_ipld_config,
    EmbeddingResult,
    SearchResult,
    VectorStoreType
)


class TestIPLDVectorStoreConfig:
    """Test IPLD vector store configuration."""
    
    def test_create_ipld_config(self):
        """Test creating IPLD config."""
        config = create_ipld_config(
            collection_name="test",
            dimension=768,
            use_embeddings_router=True,
            use_ipfs_router=True
        )
        
        assert config.collection_name == "test"
        assert config.dimension == 768
        assert config.store_type == VectorStoreType.IPLD or config.store_type == "ipld"
        assert config.use_embeddings_router is True
        assert config.use_ipfs_router is True
    
    def test_config_with_ipld_settings(self):
        """Test IPLD-specific settings."""
        config = create_ipld_config(
            "test",
            768,
            auto_pin_to_ipfs=True,
            ipld_chunk_size=500,
            ipld_compression=True
        )
        
        assert config.auto_pin_to_ipfs is True
        assert config.ipld_chunk_size == 500
        assert config.ipld_compression is True


class TestIPLDVectorStoreBasic:
    """Test basic IPLD vector store operations."""
    
    @pytest.mark.asyncio
    async def test_store_creation(self):
        """Test creating store instance."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        assert store is not None
        assert store.collection_name == "test"
        assert store.dimension == 128
    
    @pytest.mark.asyncio
    async def test_create_collection(self):
        """Test creating a collection."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        success = await store.create_collection("test_collection", dimension=128)
        assert success is True
        
        exists = await store.collection_exists("test_collection")
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_list_collections(self):
        """Test listing collections."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("col1", 128)
        await store.create_collection("col2", 128)
        
        collections = await store.list_collections()
        assert "col1" in collections
        assert "col2" in collections
    
    @pytest.mark.asyncio
    async def test_delete_collection(self):
        """Test deleting a collection."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test_del", 128)
        assert await store.collection_exists("test_del")
        
        success = await store.delete_collection("test_del")
        assert success is True
        assert not await store.collection_exists("test_del")


class TestIPLDVectorOperations:
    """Test vector operations (add, search, get, delete)."""
    
    @pytest.mark.asyncio
    async def test_add_embeddings(self):
        """Test adding embeddings."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        # Create test embeddings
        embeddings = [
            EmbeddingResult(
                chunk_id=f"vec_{i}",
                content=f"Document {i}",
                embedding=np.random.rand(128).tolist(),
                metadata={"index": i}
            )
            for i in range(10)
        ]
        
        ids = await store.add_embeddings(embeddings, "test")
        
        assert len(ids) == 10
        assert all(isinstance(id, str) for id in ids)
    
    @pytest.mark.asyncio
    async def test_search_vectors(self):
        """Test searching for similar vectors."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        # Add vectors
        vectors = [np.random.rand(128) for _ in range(20)]
        embeddings = [
            EmbeddingResult(
                chunk_id=f"vec_{i}",
                content=f"Doc {i}",
                embedding=vec.tolist(),
                metadata={"idx": i}
            )
            for i, vec in enumerate(vectors)
        ]
        
        await store.add_embeddings(embeddings, "test")
        
        # Search
        query_vector = vectors[0].tolist()  # Use first vector as query
        results = await store.search(query_vector, top_k=5, collection_name="test")
        
        assert len(results) > 0
        assert len(results) <= 5
        assert all(isinstance(r, SearchResult) for r in results)
        # First result should be exact match
        assert results[0].score > 0.99 or results[0].score < 0.01  # Depending on metric
    
    @pytest.mark.asyncio
    async def test_get_by_id(self):
        """Test retrieving embedding by ID."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        embedding = EmbeddingResult(
            chunk_id="test_id",
            content="Test document",
            embedding=np.random.rand(128).tolist(),
            metadata={"key": "value"}
        )
        
        ids = await store.add_embeddings([embedding], "test")
        vec_id = ids[0]
        
        # Retrieve
        result = await store.get_by_id(vec_id, "test")
        
        assert result is not None
        assert result.chunk_id == vec_id
        assert result.content == "Test document"
    
    @pytest.mark.asyncio
    async def test_delete_by_id(self):
        """Test deleting embedding by ID."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        embedding = EmbeddingResult(
            chunk_id="del_test",
            content="To be deleted",
            embedding=np.random.rand(128).tolist(),
            metadata={}
        )
        
        ids = await store.add_embeddings([embedding], "test")
        vec_id = ids[0]
        
        # Delete
        success = await store.delete_by_id(vec_id, "test")
        assert success is True
        
        # Verify deleted
        result = await store.get_by_id(vec_id, "test")
        assert result is None


class TestIPLDVectorStoreMetadata:
    """Test metadata filtering and collection info."""
    
    @pytest.mark.asyncio
    async def test_search_with_filters(self):
        """Test search with metadata filters."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        # Add vectors with different metadata
        embeddings = [
            EmbeddingResult(
                chunk_id=f"vec_{i}",
                content=f"Doc {i}",
                embedding=np.random.rand(128).tolist(),
                metadata={"category": "A" if i < 10 else "B", "value": i}
            )
            for i in range(20)
        ]
        
        await store.add_embeddings(embeddings, "test")
        
        # Search with filter
        query = np.random.rand(128).tolist()
        results = await store.search(
            query,
            top_k=10,
            collection_name="test",
            filter_dict={"category": "A"}
        )
        
        # All results should have category A
        assert all(r.metadata.get("category") == "A" for r in results if r.metadata)
    
    @pytest.mark.asyncio
    async def test_get_collection_info(self):
        """Test getting collection information."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        # Add some vectors
        embeddings = [
            EmbeddingResult(
                chunk_id=f"vec_{i}",
                content=f"Doc {i}",
                embedding=np.random.rand(128).tolist(),
                metadata={}
            )
            for i in range(15)
        ]
        await store.add_embeddings(embeddings, "test")
        
        # Get info
        info = await store.get_collection_info("test")
        
        assert info["name"] == "test"
        assert info["dimension"] == 128
        assert info["count"] == 15
        assert "metric" in info
    
    @pytest.mark.asyncio
    async def test_get_store_info(self):
        """Test getting store-wide information."""
        config = create_ipld_config("test", 128, use_ipfs_router=False, use_embeddings_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("col1", 128)
        await store.create_collection("col2", 128)
        
        info = await store.get_store_info()
        
        assert info["store_type"] == "IPLDVectorStore"
        assert "col1" in info["collections"]
        assert "col2" in info["collections"]
        assert info["total_collections"] == 2


class TestIPLDExportImport:
    """Test IPLD export/import functionality (without actual IPFS)."""
    
    @pytest.mark.asyncio
    async def test_export_to_ipld_no_router(self):
        """Test export when router not available."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        await store.create_collection("test", 128)
        
        # Should return None when router not available
        cid = await store.export_to_ipld("test")
        assert cid is None
    
    @pytest.mark.asyncio
    async def test_import_from_ipld_no_router(self):
        """Test import when router not available."""
        config = create_ipld_config("test", 128, use_ipfs_router=False)
        store = IPLDVectorStore(config)
        
        # Should return False when router not available
        success = await store.import_from_ipld("QmTest", "test")
        assert success is False


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
