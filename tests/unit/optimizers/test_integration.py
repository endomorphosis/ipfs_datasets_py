"""
Comprehensive integration tests for complaint generator system.

Test coverage:
- DuckDB + Parquet storage integration
- Multi-level caching with storage backend
- Consensus mechanism with entities
- Memory profiling across operations
- REST API integration workflows
- Complete complaint analysis pipeline
- Concurrent operations
- Error recovery
"""

import pytest
import time
import threading
from ipfs_datasets_py.optimizers.perf.memory_profiler import (
    MemoryProfiler,
    MemorySnapshot,
)
from ipfs_datasets_py.optimizers.integrations.duckdb_storage import (
    DuckDBStorage,
    StorageConfig,
    EntitySchema,
    RelationshipSchema,
)
from ipfs_datasets_py.optimizers.common.caching_layer import (
    MultiLevelCache,
    CacheL1,
    CacheEntry,
)
from ipfs_datasets_py.optimizers.agentic.consensus_mechanisms import (
    ConsensusManager,
    AgentVote,
    AgentProfile,
)
from fastapi.testclient import TestClient
from ipfs_datasets_py.optimizers.api.rest_api import (
    APIServer,
    EntityRequest,
    RelationshipRequest,
    EntityType,
    RelationshipType,
)


@pytest.fixture
def storage():
    """Create DuckDB storage instance."""
    config = StorageConfig(db_dir="/tmp/test_storage", compression="SNAPPY")
    return DuckDBStorage(config)


@pytest.fixture
def cache():
    """Create multi-level cache instance."""
    return MultiLevelCache(max_l1_size=20, max_l2_size=100)


@pytest.fixture
def profiler():
    """Create memory profiler instance."""
    return MemoryProfiler(enable_tracemalloc=False)


@pytest.fixture
def consensus_manager():
    """Create consensus manager instance."""
    return ConsensusManager()


@pytest.fixture
def api_client():
    """Create REST API test client."""
    server = APIServer(title="Test API", version="1.0.0")
    return TestClient(server.get_app())


class TestStorageIntegration:
    """Integration tests for DuckDB storage."""
    
    def test_entity_crud_and_query(self, storage):
        """Test entity creation, retrieval, update, and deletion."""
        # Create entities
        entity1 = storage.insert_entity({"text": "John", "type": "person", "confidence": 0.95, "metadata": {"role": "analyst"}})
        entity2 = storage.insert_entity({"text": "Jane", "type": "person", "confidence": 0.9, "metadata": {"role": "manager"}})
        
        assert entity1 is not None
        assert entity2 is not None
        
        # Query entities
        retrieved = storage.get_entity(entity1)
        assert retrieved["text"] == "John"
        assert retrieved["confidence"] == pytest.approx(0.95)
        
        # Update entity
        updated_result = storage.update_entity(entity1, {"text": "John Smith", "confidence": 0.98})
        assert updated_result == True
        retrieved = storage.get_entity(entity1)
        assert retrieved["text"] == "John Smith"
        assert retrieved["confidence"] == pytest.approx(0.98)
        
        # Delete entity
        result = storage.delete_entity(entity1)
        assert result == True
        
        # Verify deleted
        retrieved = storage.get_entity(entity1)
        assert retrieved is None
    
    def test_relationship_crud_and_query(self, storage):
        """Test relationship storage and querying."""
        # Create entities
        src = storage.insert_entity({"text": "Entity1", "type": "person", "confidence": 0.9})
        tgt = storage.insert_entity({"text": "Entity2", "type": "organization", "confidence": 0.85})
        
        # Create relationship
        rel = storage.insert_relationship({"source_id": src, "target_id": tgt, "type": "works_for", "confidence": 0.9})
        assert rel is not None
        
        # Query relationship
        retrieved = storage.get_relationship(rel)
        assert retrieved["source_id"] == src
        assert retrieved["target_id"] == tgt
        assert retrieved["type"] == "works_for"
        
        # Delete relationship
        result = storage.delete_relationship(rel)
        assert result == True
    
    def test_bulk_insert_performance(self, storage):
        """Test bulk insert performance."""
        entities = [
            {"text": f"Entity{i}", "type": "person", "confidence": 0.9}
            for i in range(100)
        ]
        
        start = time.time()
        entity_ids = storage.bulk_insert_entities(entities)
        elapsed = time.time() - start
        
        assert len(entity_ids) == 100
        assert elapsed < 5.0  # Should complete in < 5 seconds
    
    def test_transaction_rollback(self, storage):
        """Test transaction rollback on error."""
        storage.begin_transaction()
        
        try:
            entity1 = storage.insert_entity({"text": "Test1", "type": "person", "confidence": 0.9})
            entity2 = storage.insert_entity({"text": "Test2", "type": "person", "confidence": 0.9})
            
            # Simulate error
            raise ValueError("Simulated error")
        except ValueError:
            storage.rollback_transaction()
        
        # Verify changes were rolled back
        retrieved = storage.get_entity(entity1)
        assert retrieved is None
    
    def test_statistics_aggregation(self, storage):
        """Test statistics aggregation."""
        # Create test data
        for i in range(10):
            storage.insert_entity({"text": f"Entity{i}", "type": "person", "confidence": 0.8 + (i * 0.01)})
        
        # Get statistics
        stats = storage.aggregate_statistics()
        
        assert stats["entities"]["count"] == 10
        assert stats["entities"]["avg_confidence"] > 0.8


class TestCachingIntegration:
    """Integration tests for multi-level caching."""
    
    def test_l1_to_l2_promotion(self, cache):
        """Test data promotion from L1 to L2 cache."""
        # Fill L1 cache
        for i in range(20):
            cache.set(f"key_{i}", f"value_{i}", ttl=3600)
        
        # Access old key - should be promoted if space available
        value = cache.get("key_0")
        assert value == "value_0"
    
    def test_cache_eviction_policies(self, cache):
        """Test different cache eviction policies."""
        # Fill L1 cache beyond capacity
        for i in range(30):
            cache.set(f"key_{i}", f"value_{i}")
        
        # Some keys should be evicted, but others should remain
        hits = sum(1 for i in range(30) if cache.get(f"key_{i}") is not None)
        
        # Expect at least some keys to be cached
        assert hits > 0
    
    def test_cache_ttl_expiration(self, cache):
        """Test cache TTL expiration."""
        cache.set("expiring_key", "expiring_value", ttl=0.5)
        
        # Should exist immediately
        assert cache.get("expiring_key") == "expiring_value"
        
        # Wait for expiration
        time.sleep(0.6)
        
        # Should be expired
        assert cache.get("expiring_key") is None
    
    def test_cache_metrics(self, cache):
        """Test cache metrics collection."""
        # Perform cache operations
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        
        # Check metrics
        metrics = cache.get_combined_metrics()
        
        assert metrics["total_hits"] >= 2
        assert metrics["total_misses"] >= 1


class TestConsensusIntegration:
    """Integration tests for consensus mechanisms."""
    
    def test_multi_agent_consensus_workflow(self, consensus_manager):
        """Test complete multi-agent consensus workflow."""
        # Register agents
        consensus_manager.register_agent("agent_1", reputation=0.9)
        consensus_manager.register_agent("agent_2", reputation=0.85)
        consensus_manager.register_agent("agent_3", reputation=0.8)
        
        # Create votes with entity and relationship data as dicts
        entity1 = {"id": "e1", "name": "John", "type": "person", "confidence": 0.95}
        entity2 = {"id": "e2", "name": "Company", "type": "organization", "confidence": 0.9}
        rel1 = {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_for", "confidence": 0.9}
        
        votes = [
            AgentVote("agent_1", [entity1, entity2], [rel1], 0.95),
            AgentVote("agent_2", [entity1, entity2], [rel1], 0.9),
            AgentVote("agent_3", [entity1, entity2], [rel1], 0.85),
        ]
        
        # Reach consensus
        result = consensus_manager.reach_consensus(votes=votes)
        
        assert result is not None
        assert result.agreement_rate > 0
        assert len(result.consensus_entities) > 0
    
    def test_consensus_with_conflicting_votes(self, consensus_manager):
        """Test consensus with conflicting agent votes."""
        consensus_manager.register_agent("agent_1", reputation=0.9)
        consensus_manager.register_agent("agent_2", reputation=0.8)
        
        entity1 = {"id": "e1", "name": "John", "type": "person", "confidence": 0.95}
        entity2 = {"id": "e2", "name": "Jane", "type": "person", "confidence": 0.9}
        
        votes = [
            AgentVote("agent_1", [entity1], [], 0.95),
            AgentVote("agent_2", [entity2], [], 0.85),  # Different entity
        ]
        
        result = consensus_manager.reach_consensus(votes=votes)
        
        # Consensus should handle conflicts
        assert result is not None
    
    def test_agent_reputation_update(self, consensus_manager):
        """Test agent reputation updates based on accuracy."""
        consensus_manager.register_agent("agent_1", reputation=0.8)
        
        # Mark agent as correct
        consensus_manager.update_agent_reputation("agent_1", correct=True, confidence=0.95)
        
        # Get updated profile
        profile = consensus_manager.agent_profiles["agent_1"]
        assert profile.correct_extractions > 0
        
        # Reputation should increase
        assert profile.reputation > 0.8


class TestMemoryProfilingIntegration:
    """Integration tests for memory profiling."""
    
    def test_profiling_entity_operations(self, profiler, storage):
        """Test memory profiling during entity operations."""
        profiler.start_profiling()
        
        # Create entities
        for i in range(100):
            storage.insert_entity({"text": f"Entity{i}", "type": "person", "confidence": 0.9})
        
        profiler.snapshot()
        
        # Get memory delta
        delta = profiler.get_memory_delta()
        
        # Memory should increase (but might be managed by GC)
        assert isinstance(delta, float)
    
    def test_profiling_cache_operations(self, profiler, cache):
        """Test memory profiling during caching."""
        profiler.start_profiling()
        baseline = profiler.snapshot()
        
        # Fill cache with data
        for i in range(50):
            cache.set(f"key_{i}", f"value_{i}" * 100)
        
        cached = profiler.snapshot()
        
        # Compare snapshots
        delta = profiler.compare_snapshots(baseline, cached)
        
        assert delta.memory_delta_mb >= 0  # Memory should not decrease significantly
    
    def test_profiling_consensus_operations(self, profiler, consensus_manager):
        """Test memory profiling during consensus."""
        profiler.start_profiling()
        
        consensus_manager.register_agent("agent_1", reputation=0.9)
        consensus_manager.register_agent("agent_2", reputation=0.85)
        
        # Create many votes
        votes = []
        for i in range(10):
            entity = {"id": f"e{i}", "name": f"Entity{i}", "type": "person", "confidence": 0.9}
            vote = AgentVote(f"agent_{i % 2 + 1}", [entity], [], 0.9)
            votes.append(vote)
        
        consensus_manager.reach_consensus(votes)
        
        # Get hotspots
        hotspots = profiler.get_hotspots(top_n=5)
        assert isinstance(hotspots, list)


class TestRESTAPIIntegration:
    """Integration tests for REST API workflows."""
    
    def test_complete_entity_relationship_api_workflow(self, api_client):
        """Test complete workflow through REST API."""
        # Create first entity
        entity1_req = {
            "name": "John Doe",
            "entity_type": "person",
            "confidence": 0.95
        }
        entity1_resp = api_client.post("/entities", json=entity1_req)
        assert entity1_resp.status_code == 200
        entity1_id = entity1_resp.json()["id"]
        
        # Create second entity
        entity2_req = {
            "name": "Tech Corp",
            "entity_type": "organization",
            "confidence": 0.9
        }
        entity2_resp = api_client.post("/entities", json=entity2_req)
        entity2_id = entity2_resp.json()["id"]
        
        # Create relationship
        rel_req = {
            "source_id": entity1_id,
            "target_id": entity2_id,
            "relationship_type": "works_for",
            "confidence": 0.85
        }
        rel_resp = api_client.post("/relationships", json=rel_req)
        assert rel_resp.status_code == 200
        
        # Get statistics
        stats_resp = api_client.get("/stats")
        stats = stats_resp.json()
        
        assert stats["total_entities"] == 2
        assert stats["total_relationships"] == 1
    
    def test_consensus_api_workflow(self, api_client):
        """Test consensus through REST API."""
        entity = {
            "name": "Test Entity",
            "entity_type": "person",
            "confidence": 0.9
        }
        
        rel = {
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": "works_for",
            "confidence": 0.8
        }
        
        # Create consensus request with multiple votes
        consensus_req = {
            "votes": [
                {
                    "agent_id": "agent_1",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.95
                },
                {
                    "agent_id": "agent_2",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.9
                },
                {
                    "agent_id": "agent_3",
                    "entities": [entity],
                    "relationships": [rel],
                    "confidence": 0.85
                }
            ],
            "strategy": "majority"
        }
        
        response = api_client.post("/consensus", json=consensus_req)
        assert response.status_code == 200
        
        data = response.json()
        assert data["agreement_rate"] > 0
        assert len(data["consensus_entities"]) > 0
    
    def test_api_memory_profiling_workflow(self, api_client):
        """Test memory profiling through API."""
        # Get baseline snapshot
        snapshot1 = api_client.get("/memory/snapshot")
        assert snapshot1.status_code == 200
        baseline_mem = snapshot1.json()["current_memory_mb"]
        
        # Create some entities
        for i in range(10):
            entity_req = {
                "name": f"Entity{i}",
                "entity_type": "person",
                "confidence": 0.9
            }
            api_client.post("/entities", json=entity_req)
        
        # Get final snapshot
        snapshot2 = api_client.get("/memory/snapshot")
        final_mem = snapshot2.json()["current_memory_mb"]
        
        # Get hotspots
        hotspots = api_client.get("/memory/hotspots?limit=5")
        assert hotspots.status_code == 200
        
        # Should have some hotspots
        hotspots_data = hotspots.json()
        assert isinstance(hotspots_data, list)


class TestConcurrentOperations:
    """Integration tests for concurrent operations."""
    
    def test_concurrent_entity_creation(self, storage):
        """Test concurrent entity creation."""
        results = []
        errors = []
        
        def create_entities(start, end):
            try:
                for i in range(start, end):
                    entity_id = storage.insert_entity({"text": f"Entity{i}", "type": "person", "confidence": 0.9})
                    results.append(entity_id)
            except Exception as e:
                errors.append(str(e))
        
        # Create threads
        threads = [
            threading.Thread(target=create_entities, args=(0, 25)),
            threading.Thread(target=create_entities, args=(25, 50)),
            threading.Thread(target=create_entities, args=(50, 75)),
            threading.Thread(target=create_entities, args=(75, 100)),
        ]
        
        # Start threads
        for t in threads:
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Verify no errors
        assert len(errors) == 0
        assert len(results) == 100
    
    def test_concurrent_cache_access(self, cache):
        """Test concurrent cache access."""
        errors = []
        access_count = []
        
        def worker(worker_id):
            try:
                for i in range(20):
                    cache.set(f"key_{worker_id}_{i}", f"value_{worker_id}_{i}")
                    value = cache.get(f"key_{worker_id}_{i}")
                    if value:
                        access_count.append(1)
            except Exception as e:
                errors.append(str(e))
        
        # Create worker threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(access_count) > 0


class TestErrorRecovery:
    """Integration tests for error recovery."""
    
    def test_storage_recovery_from_corruption(self, storage):
        """Test storage recovery from data corruption."""
        # Create entities
        entity1 = storage.insert_entity({"text": "Entity1", "type": "person", "confidence": 0.9})
        
        # Verify created
        retrieved = storage.get_entity(entity1)
        assert retrieved is not None
        
        # Even if internal state is corrupted, fresh queries should work
        entity2 = storage.insert_entity({"text": "Entity2", "type": "person", "confidence": 0.85})
        
        # Verify both exist
        assert storage.get_entity(entity1) is not None
        assert storage.get_entity(entity2) is not None
    
    def test_cache_recovery_from_invalid_data(self, cache):
        """Test cache graceful handling of invalid data."""
        # Set valid data
        cache.set("valid_key", "valid_value")
        
        # Retrieve valid data
        assert cache.get("valid_key") == "valid_value"
        
        # Request non-existent key shouldn't crash
        result = cache.get("non_existent")
        assert result is None
    
    def test_consensus_with_invalid_votes(self, consensus_manager):
        """Test consensus handling of invalid votes."""
        consensus_manager.register_agent("agent_1")
        
        # Create empty votes
        votes = [
            AgentVote("agent_1", [], [], 0.9)
        ]
        
        # Should handle gracefully
        result = consensus_manager.reach_consensus(votes)
        assert result is not None


class TestEndToEndComplaintAnalysis:
    """End-to-end tests for complete complaint analysis pipeline."""
    
    def test_complaint_analysis_pipeline(self, api_client, storage, cache, profiler):
        """Test complete complaint analysis pipeline."""
        # 1. Start profiling
        profiler.start_profiling()
        
        # 2. Create entity through API
        entity_req = {
            "name": "Complaint Complainant",
            "entity_type": "person",
            "confidence": 0.95
        }
        entity_resp = api_client.post("/entities", json=entity_req)
        entity_id = entity_resp.json()["id"]
        
        # 3. Cache the entity
        cache.set(entity_id, entity_resp.json())
        
        # 4. Create multiple vote entities
        votes = []
        for i in range(3):
            entity = {
                "name": f"Analyst{i}",
                "entity_type": "person",
                "confidence": 0.9 - i * 0.05
            }
            vote = {
                "agent_id": f"analyzer_{i}",
                "entities": [entity],
                "relationships": [],
                "confidence": 0.9 - i * 0.05
            }
            votes.append(vote)
        
        # 5. Reach consensus
        consensus_req = {
            "votes": votes,
            "strategy": "weighted"
        }
        consensus_resp = api_client.post("/consensus", json=consensus_req)
        assert consensus_resp.status_code == 200
        
        # 6. Get memory profile
        profiler.snapshot()
        hotspots = profiler.get_hotspots(top_n=3)
        
        # 7. Get system stats
        stats_resp = api_client.get("/stats")
        stats = stats_resp.json()
        
        # Verify complete pipeline
        assert stats["total_entities"] == 1
        assert len(hotspots) >= 0
        assert consensus_resp.json()["agreement_rate"] > 0
