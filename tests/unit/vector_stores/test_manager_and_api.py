"""Unit tests for VectorStoreManager and high-level API."""

import pytest
import numpy as np

from ipfs_datasets_py.vector_stores import (
    VectorStoreManager,
    create_vector_store,
    create_manager,
    create_ipld_config,
    create_faiss_config,
    EmbeddingResult
)


class TestVectorStoreManager:
    """Test VectorStoreManager functionality."""
    
    def test_manager_creation(self):
        """Test creating a manager instance."""
        manager = create_manager()
        assert manager is not None
        assert isinstance(manager, VectorStoreManager)
    
    def test_register_store(self):
        """Test registering stores with manager."""
        manager = create_manager()
        
        config1 = create_ipld_config("docs", 128, use_ipfs_router=False)
        config2 = create_faiss_config("docs", 128)
        
        manager.register_store("ipld", config1)
        manager.register_store("faiss", config2)
        
        assert "ipld" in manager.list_stores()
        assert "faiss" in manager.list_stores()
    
    @pytest.mark.asyncio
    async def test_get_store(self):
        """Test getting a store instance."""
        manager = create_manager()
        
        config = create_ipld_config("docs", 128, use_ipfs_router=False)
        manager.register_store("ipld", config)
        
        store = await manager.get_store("ipld")
        assert store is not None
        assert store.collection_name == "docs"
    
    @pytest.mark.asyncio
    async def test_get_store_health(self):
        """Test getting store health status."""
        manager = create_manager()
        
        config = create_ipld_config("docs", 128, use_ipfs_router=False)
        manager.register_store("ipld", config)
        
        health = await manager.get_store_health("ipld")
        assert "name" in health
        assert "healthy" in health
        assert health["name"] == "ipld"
    
    @pytest.mark.asyncio
    async def test_get_all_health(self):
        """Test getting health for all stores."""
        manager = create_manager()
        
        config1 = create_ipld_config("docs", 128, use_ipfs_router=False)
        config2 = create_faiss_config("docs", 128)
        
        manager.register_store("ipld", config1)
        manager.register_store("faiss", config2)
        
        health = await manager.get_all_health()
        assert "ipld" in health
        assert "faiss" in health


class TestHighLevelAPI:
    """Test high-level API functions."""
    
    @pytest.mark.asyncio
    async def test_create_vector_store(self):
        """Test creating a vector store via API."""
        store = await create_vector_store(
            "ipld",
            "test",
            dimension=128,
            use_ipfs_router=False
        )
        
        assert store is not None
        assert store.collection_name == "test"
        assert store.dimension == 128
    
    @pytest.mark.asyncio
    async def test_create_faiss_store(self):
        """Test creating FAISS store via API."""
        store = await create_vector_store(
            "faiss",
            "test",
            dimension=128
        )
        
        assert store is not None
        assert store.collection_name == "test"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
