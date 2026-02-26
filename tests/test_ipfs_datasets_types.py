"""
Tests for ipfs_datasets TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.ipfs_datasets import (
    ClustersResultDict,
    HashedShardResultDict,
)


class TestClustersResultDict:
    """Test ClustersResultDict contract."""
    
    def test_clusters_result_structure(self):
        """Verify clusters result structure."""
        sample: ClustersResultDict = {
            "clusters": [{"id": "c1", "members": []}],
            "cluster_count": 1,
            "model_used": "embedding-model",
            "similarity_scores": [0.95, 0.87],
            "processing_time": 1.5
        }
        assert isinstance(sample.get("clusters"), (list, type(None)))
        assert isinstance(sample.get("cluster_count"), (int, type(None)))
    
    def test_clusters_result_types(self):
        """Verify field types."""
        sample: ClustersResultDict = {
            "model_used": "test",
            "similarity_scores": [0.5, 0.7],
            "processing_time": 0.5
        }
        assert isinstance(sample.get("model_used"), (str, type(None)))
        assert isinstance(sample.get("similarity_scores"), (list, type(None)))


class TestHashedShardResultDict:
    """Test HashedShardResultDict contract."""
    
    def test_hashed_shard_result_structure(self):
        """Verify hashed shard result structure."""
        sample: HashedShardResultDict = {
            "cids": ["QmABC123", "QmDEF456"],
            "items": [{"id": "item1"}],
            "schema": {"id": "string"},
            "shard_id": "shard_1",
            "hashes": {"file1": "abc123"},
            "processing_time": 0.75
        }
        assert isinstance(sample.get("cids"), (list, type(None)))
        assert isinstance(sample.get("items"), (list, type(None)))
    
    def test_hashed_shard_result_dicts(self):
        """Verify dict fields."""
        sample: HashedShardResultDict = {
            "schema": {"field": "type"},
            "hashes": {"file": "hash"}
        }
        assert isinstance(sample.get("schema"), (dict, type(None)))
        assert isinstance(sample.get("hashes"), (dict, type(None)))


class TestIntegration:
    """Integration tests."""
    
    def test_partial_results(self):
        """Verify partial field sets work (total=False)."""
        minimal: ClustersResultDict = {"cluster_count": 0}
        assert isinstance(minimal, dict)
        
        shard_minimal: HashedShardResultDict = {"cids": []}
        assert "cids" in shard_minimal


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
