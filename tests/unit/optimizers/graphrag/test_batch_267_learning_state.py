"""
Batch 267: Comprehensive tests for LearningStateManager.

Tests all learning state management and query fingerprinting functionality:
- Statistical learning enable/disable with configurable cycles
- Learning cycle checks with circuit breaker pattern
- Save/load state persistence (JSON)
- Query performance recording
- Path performance tracking with relation usefulness
- Query fingerprinting and collision detection
- Similar query retrieval
- Learning statistics and reset

Coverage: 48 tests across 11 test classes
"""

import pytest
import tempfile
import os
import json
from datetime import datetime
from typing import Dict, List, Any

from ipfs_datasets_py.optimizers.graphrag.learning_state import LearningStateManager


@pytest.fixture
def manager():
    """Create a fresh LearningStateManager for each test."""
    return LearningStateManager()


@pytest.fixture
def enabled_manager():
    """Create a manager with learning enabled."""
    mgr = LearningStateManager()
    mgr.enable_statistical_learning(enabled=True, learning_cycle=10)
    return mgr


class TestInitialization:
    """Test LearningStateManager initialization."""
    
    def test_init_defaults(self, manager):
        """Test default initialization values."""
        assert manager._learning_enabled is False
        assert manager._learning_cycle == 50
        assert manager._learning_parameters == {}
        assert manager._entity_importance_cache == {}
        assert manager._query_stats == []
        assert manager._failure_count == 0
        assert manager._max_consecutive_failures == 3
        
        # Check traversal stats structure
        assert "paths_explored" in manager._traversal_stats
        assert "path_scores" in manager._traversal_stats
        assert "entity_frequency" in manager._traversal_stats
        assert "entity_connectivity" in manager._traversal_stats
        assert "relation_usefulness" in manager._traversal_stats


class TestEnableStatisticalLearning:
    """Test enable_statistical_learning method."""
    
    def test_enable_learning_basic(self, manager):
        """Test enabling learning with default cycle."""
        manager.enable_statistical_learning(enabled=True)
        
        assert manager._learning_enabled is True
        assert manager._learning_cycle == 50  # Default
    
    def test_enable_learning_custom_cycle(self, manager):
        """Test enabling learning with custom cycle."""
        manager.enable_statistical_learning(enabled=True, learning_cycle=25)
        
        assert manager._learning_enabled is True
        assert manager._learning_cycle == 25
    
    def test_disable_learning(self, enabled_manager):
        """Test disabling learning."""
        enabled_manager.enable_statistical_learning(enabled=False)
        
        assert enabled_manager._learning_enabled is False
    
    def test_initializes_entity_importance_cache(self, manager):
        """Test that enabling learning initializes entity importance cache if not exists."""
        manager.enable_statistical_learning(enabled=True)
        
        # Cache should be initialized (empty dict)
        assert manager._entity_importance_cache == {}
    
    def test_preserves_existing_cache(self, manager):
        """Test that existing cache is preserved when enabling."""
        manager._entity_importance_cache = {"entity_1": 0.8, "entity_2": 0.6}
        
        manager.enable_statistical_learning(enabled=True)
        
        assert manager._entity_importance_cache == {"entity_1": 0.8, "entity_2": 0.6}


class TestCheckLearningCycle:
    """Test check_learning_cycle method and circuit breaker."""
    
    def test_check_cycle_when_disabled(self, manager):
        """Test that check_learning_cycle does nothing when disabled."""
        manager._query_stats = [{"score": 0.8} for _ in range(60)]
        initial_stats = manager._query_stats.copy()
        
        manager.check_learning_cycle()
        
        # Should not modify stats
        assert manager._query_stats == initial_stats
    
    def test_check_cycle_triggers_learning(self, enabled_manager):
        """Test that check triggers learning when cycle threshold reached."""
        # Add enough queries to trigger learning cycle (learning_cycle=10)
        for i in range(10):
            enabled_manager._query_stats.append({
                "fingerprint": f"query_{i}",
                "success_score": 0.8
            })
        
        initial_params = enabled_manager._learning_parameters.copy()
        
        enabled_manager.check_learning_cycle()
        
        # Learning hook should have been applied
        assert "recent_avg_success" in enabled_manager._learning_parameters
        assert enabled_manager._learning_parameters["recent_avg_success"] == pytest.approx(0.8)
    
    def test_check_cycle_resets_stats_after_learning(self, enabled_manager):
        """Test that stats are reset to last cycle after learning."""
        # Add 15 queries (learning_cycle=10)
        for i in range(15):
            enabled_manager._query_stats.append({"score": 0.8})
        
        enabled_manager.check_learning_cycle()
        
        # Should keep only last 10 queries
        assert len(enabled_manager._query_stats) == 10
    
    def test_circuit_breaker_tracks_failures(self, enabled_manager):
        """Test circuit breaker tracks consecutive failures."""
        # Force an error by making _query_stats not a sequence
        enabled_manager._query_stats = None
        
        enabled_manager.check_learning_cycle()
        
        # Failure count should increment
        assert enabled_manager._failure_count == 1
    
    def test_circuit_breaker_disables_after_max_failures(self, enabled_manager):
        """Test circuit breaker disables learning after max consecutive failures."""
        enabled_manager._max_consecutive_failures = 3
        enabled_manager._query_stats = None  # Force errors
        
        # Trigger 3 failures
        for _ in range(3):
            enabled_manager.check_learning_cycle()
        
        # Learning should be disabled
        assert enabled_manager._learning_enabled is False
        assert enabled_manager._failure_count == 0  # Reset after disabling


class TestSaveLoadLearningState:
    """Test save_learning_state and load_learning_state methods."""
    
    def test_save_state_when_disabled(self, manager):
        """Test that save returns None when learning disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            result = manager.save_learning_state(filepath)
            
            assert result is None
            assert not os.path.exists(filepath)
    
    def test_save_state_with_no_filepath(self, enabled_manager):
        """Test that save returns None when no filepath provided."""
        result = enabled_manager.save_learning_state(filepath=None)
        
        assert result is None
    
    def test_save_state_creates_directory(self, enabled_manager):
        """Test that save creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "subdir", "state.json")
            
            result = enabled_manager.save_learning_state(filepath)
            
            assert result == filepath
            assert os.path.exists(filepath)
    
    def test_save_state_contains_all_fields(self, enabled_manager):
        """Test that saved state contains all expected fields."""
        enabled_manager._learning_parameters = {"param1": 1.0}
        enabled_manager._entity_importance_cache = {"e1": 0.9}
        enabled_manager._failure_count = 2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            enabled_manager.save_learning_state(filepath)
            
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            assert state["learning_enabled"] is True
            assert state["learning_cycle"] == 10
            assert state["learning_parameters"] == {"param1": 1.0}
            assert state["entity_importance_cache"] == {"e1": 0.9}
            assert state["failure_count"] == 2
            assert "timestamp" in state
            assert "traversal_stats" in state
    
    def test_load_state_with_no_filepath(self, manager):
        """Test that load returns False when no filepath provided."""
        result = manager.load_learning_state(filepath=None)
        
        assert result is False
    
    def test_load_state_with_nonexistent_file(self, manager):
        """Test that load returns False for nonexistent file."""
        result = manager.load_learning_state("/nonexistent/path/state.json")
        
        assert result is False
    
    def test_load_state_restores_all_fields(self, manager):
        """Test that load restores all saved fields."""
        # Create a state file
        state = {
            "learning_enabled": True,
            "learning_cycle": 25,
            "learning_parameters": {"param1": 2.0},
            "traversal_stats": {"paths_explored": [["e1", "e2"]]},
            "entity_importance_cache": {"e1": 0.8},
            "failure_count": 1
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            with open(filepath, 'w') as f:
                json.dump(state, f)
            
            result = manager.load_learning_state(filepath)
            
            assert result is True
            assert manager._learning_enabled is True
            assert manager._learning_cycle == 25
            assert manager._learning_parameters == {"param1": 2.0}
            assert manager._entity_importance_cache == {"e1": 0.8}
            assert manager._failure_count == 1
            assert manager._traversal_stats == {"paths_explored": [["e1", "e2"]]}
    
    def test_roundtrip_save_load(self, enabled_manager):
        """Test complete save/load roundtrip."""
        enabled_manager._learning_parameters = {"test_param": 3.0}
        enabled_manager._entity_importance_cache = {"e1": 0.9, "e2": 0.7}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            
            # Save
            saved_path = enabled_manager.save_learning_state(filepath)
            assert saved_path == filepath
            
            # Create new manager and load
            new_manager = LearningStateManager()
            loaded = new_manager.load_learning_state(filepath)
            
            assert loaded is True
            assert new_manager._learning_enabled == enabled_manager._learning_enabled
            assert new_manager._learning_cycle == enabled_manager._learning_cycle
            assert new_manager._learning_parameters == enabled_manager._learning_parameters
            assert new_manager._entity_importance_cache == enabled_manager._entity_importance_cache


class TestRecordQueryPerformance:
    """Test record_query_performance method."""
    
    def test_record_when_disabled(self, manager):
        """Test that record does nothing when learning disabled."""
        query = {"query": "test"}
        
        manager.record_query_performance(query, 0.8)
        
        assert len(manager._query_stats) == 0
    
    def test_record_creates_stat_entry(self, enabled_manager):
        """Test that record creates stat entry with fingerprint."""
        query = {"query": "test query", "priority": "high"}
        
        enabled_manager.record_query_performance(query, 0.85)
        
        assert len(enabled_manager._query_stats) == 1
        stat = enabled_manager._query_stats[0]
        assert "fingerprint" in stat
        assert stat["success_score"] == 0.85
        assert "timestamp" in stat
    
    def test_record_resets_failure_count_on_success(self, enabled_manager):
        """Test that high success score resets failure count."""
        enabled_manager._failure_count = 2
        
        query = {"query": "test"}
        enabled_manager.record_query_performance(query, 0.9)  # > 0.7
        
        assert enabled_manager._failure_count == 0
    
    def test_record_doesnt_reset_failure_count_on_low_score(self, enabled_manager):
        """Test that low success score doesn't reset failure count."""
        enabled_manager._failure_count = 2
        
        query = {"query": "test"}
        enabled_manager.record_query_performance(query, 0.5)  # <= 0.7
        
        assert enabled_manager._failure_count == 2
    
    def test_record_multiple_queries(self, enabled_manager):
        """Test recording multiple queries."""
        queries = [
            {"query": "query 1", "priority": "high"},
            {"query": "query 2", "priority": "normal"},
            {"query": "query 3", "priority": "low"}
        ]
        
        for i, q in enumerate(queries):
            enabled_manager.record_query_performance(q, 0.7 + i * 0.1)
        
        assert len(enabled_manager._query_stats) == 3


class TestRecordPathPerformance:
    """Test record_path_performance method."""
    
    def test_record_path_when_disabled(self, manager):
        """Test that record does nothing when learning disabled."""
        path = ["e1", "e2", "e3"]
        
        manager.record_path_performance(path, 0.8)
        
        assert len(manager._traversal_stats["paths_explored"]) == 0
    
    def test_record_path_basic(self, enabled_manager):
        """Test recording basic path performance."""
        path = ["e1", "e2", "e3"]
        
        enabled_manager.record_path_performance(path, 0.85)
        
        assert path in enabled_manager._traversal_stats["paths_explored"]
        
        path_key = "|".join(path)
        assert path_key in enabled_manager._traversal_stats["path_scores"]
        assert enabled_manager._traversal_stats["path_scores"][path_key] == 0.85
    
    def test_record_path_with_relation_types(self, enabled_manager):
        """Test recording path with relation usefulness tracking."""
        path = ["e1", "e2", "e3"]
        relation_types = ["knows", "works_with"]
        
        enabled_manager.record_path_performance(path, 0.9, relation_types)
        
        # Relation usefulness should be updated
        for rel_type in relation_types:
            assert rel_type in enabled_manager._traversal_stats["relation_usefulness"]
            # Initial value is 0.5, new value = 0.3 * 0.9 + 0.7 * 0.5 = 0.62
            assert enabled_manager._traversal_stats["relation_usefulness"][rel_type] == pytest.approx(0.62)
    
    def test_record_path_updates_existing_relation_usefulness(self, enabled_manager):
        """Test that relation usefulness uses exponential moving average."""
        path1 = ["e1", "e2"]
        path2 = ["e3", "e4"]
        
        # First record: knows = 0.3 * 0.8 + 0.7 * 0.5 = 0.59
        enabled_manager.record_path_performance(path1, 0.8, ["knows"])
        first_score = enabled_manager._traversal_stats["relation_usefulness"]["knows"]
        assert first_score == pytest.approx(0.59)
        
        # Second record: knows = 0.3 * 0.6 + 0.7 * 0.59 = 0.593
        enabled_manager.record_path_performance(path2, 0.6, ["knows"])
        second_score = enabled_manager._traversal_stats["relation_usefulness"]["knows"]
        assert second_score == pytest.approx(0.593)
    
    def test_record_multiple_paths(self, enabled_manager):
        """Test recording multiple paths."""
        paths = [
            ["e1", "e2"],
            ["e2", "e3", "e4"],
            ["e5"]
        ]
        
        for path in paths:
            enabled_manager.record_path_performance(path, 0.7)
        
        assert len(enabled_manager._traversal_stats["paths_explored"]) == 3


class TestCreateQueryFingerprint:
    """Test create_query_fingerprint method."""
    
    def test_fingerprint_with_vector_query(self, manager):
        """Test fingerprint for vector-based query."""
        query = {
            "query_vector": [0.1, 0.2, 0.3, 0.4, 0.5],
            "max_vector_results": 10
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "vec_5" in fingerprint  # Vector length
        assert "vr_10" in fingerprint  # Max vector results
    
    def test_fingerprint_with_text_query(self, manager):
        """Test fingerprint for text-based query."""
        query = {
            "query": "What is the relationship between A and B?"
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        # Should contain text hash
        assert "txt_" in fingerprint
    
    def test_fingerprint_with_query_text_field(self, manager):
        """Test fingerprint with alternative query_text field."""
        query = {
            "query_text": "Find all entities related to X"
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "txt_" in fingerprint
    
    def test_fingerprint_with_traversal_params(self, manager):
        """Test fingerprint includes traversal parameters."""
        query = {
            "query": "test",
            "traversal": {
                "max_depth": 3,
                "edge_types": ["knows", "works_with", "manages"]
            }
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "td_3" in fingerprint  # Traversal depth
        assert "et_3" in fingerprint  # Edge types count
    
    def test_fingerprint_with_priority(self, manager):
        """Test fingerprint includes priority."""
        query = {
            "query": "test",
            "priority": "high"
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "p_high" in fingerprint
    
    def test_fingerprint_defaults_priority(self, manager):
        """Test fingerprint defaults to normal priority."""
        query = {"query": "test"}
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "p_normal" in fingerprint
    
    def test_fingerprint_deterministic(self, manager):
        """Test that same query produces same fingerprint."""
        query = {
            "query": "test query",
            "max_vector_results": 10,
            "traversal": {"max_depth": 2},
            "priority": "high"
        }
        
        fp1 = manager.create_query_fingerprint(query)
        fp2 = manager.create_query_fingerprint(query)
        
        assert fp1 == fp2
    
    def test_fingerprint_different_for_different_queries(self, manager):
        """Test that different queries produce different fingerprints."""
        query1 = {"query": "query A", "priority": "high"}
        query2 = {"query": "query B", "priority": "low"}
        
        fp1 = manager.create_query_fingerprint(query1)
        fp2 = manager.create_query_fingerprint(query2)
        
        assert fp1 != fp2


class TestDetectFingerprintCollision:
    """Test detect_fingerprint_collision method."""
    
    def test_no_collision_on_empty_stats(self, manager):
        """Test no collision when no queries recorded."""
        result = manager.detect_fingerprint_collision("any_fingerprint")
        
        assert result is False
    
    def test_collision_detected(self, manager):
        """Test collision detected for existing fingerprint."""
        manager._query_stats = [
            {"fingerprint": "fp1", "score": 0.8},
            {"fingerprint": "fp2", "score": 0.7},
            {"fingerprint": "fp3", "score": 0.9}
        ]
        
        result = manager.detect_fingerprint_collision("fp2")
        
        assert result is True
    
    def test_no_collision_for_new_fingerprint(self, manager):
        """Test no collision for new fingerprint."""
        manager._query_stats = [
            {"fingerprint": "fp1", "score": 0.8},
            {"fingerprint": "fp2", "score": 0.7}
        ]
        
        result = manager.detect_fingerprint_collision("fp_new")
        
        assert result is False


class TestGetSimilarQueries:
    """Test get_similar_queries method."""
    
    def test_no_similar_queries_on_empty_stats(self, manager):
        """Test returns empty list when no queries recorded."""
        result = manager.get_similar_queries("any_fp")
        
        assert result == []
    
    def test_get_similar_queries_basic(self, manager):
        """Test retrieval of similar queries."""
        manager._query_stats = [
            {"fingerprint": "fp1", "score": 0.8},
            {"fingerprint": "fp2", "score": 0.7},
            {"fingerprint": "fp1", "score": 0.9},
            {"fingerprint": "fp2", "score": 0.6}
        ]
        
        result = manager.get_similar_queries("fp1", count=5)
        
        # Should get both fp1 entries in reverse order (most recent first)
        assert len(result) == 2
        assert result[0]["score"] == 0.9
        assert result[1]["score"] == 0.8
    
    def test_get_similar_queries_respects_count_limit(self, manager):
        """Test count limit is respected."""
        # Create 10 queries with same fingerprint
        manager._query_stats = [{"fingerprint": "fp1", "score": i * 0.1} for i in range(10)]
        
        result = manager.get_similar_queries("fp1", count=3)
        
        assert len(result) == 3
    
    def test_get_similar_queries_checks_last_100(self, manager):
        """Test only checks last 100 queries."""
        # Create 150 queries, first 100 with fp1, last 50 with fp2
        queries_fp1 = [{"fingerprint": "fp1", "score": 0.5} for _ in range(100)]
        queries_fp2 = [{"fingerprint": "fp2", "score": 0.6} for _ in range(50)]
        manager._query_stats = queries_fp1 + queries_fp2
        
        # Should only check last 100 (50 fp2 + 50 fp1)
        result = manager.get_similar_queries("fp1", count=100)
        
        # Should get at most 50 fp1 queries (from last 100)
        assert len(result) <= 50
    
    def test_get_similar_queries_no_matches(self, manager):
        """Test returns empty list when no matching fingerprints."""
        manager._query_stats = [
            {"fingerprint": "fp1", "score": 0.8},
            {"fingerprint": "fp2", "score": 0.7}
        ]
        
        result = manager.get_similar_queries("fp_nonexistent")
        
        assert result == []


class TestGetLearningStats:
    """Test get_learning_stats method."""
    
    def test_get_stats_basic(self, manager):
        """Test get_learning_stats returns all fields."""
        stats = manager.get_learning_stats()
        
        assert "enabled" in stats
        assert "cycle" in stats
        assert "parameters" in stats
        assert "query_count" in stats
        assert "failure_count" in stats
        assert "relation_usefulness" in stats
    
    def test_get_stats_reflects_current_state(self, enabled_manager):
        """Test stats reflect current manager state."""
        enabled_manager._learning_parameters = {"test": 1.0}
        enabled_manager._query_stats = [{"s": 0.8}] * 5
        enabled_manager._failure_count = 2
        enabled_manager._traversal_stats["relation_usefulness"] = {"knows": 0.7}
        
        stats = enabled_manager.get_learning_stats()
        
        assert stats["enabled"] is True
        assert stats["cycle"] == 10
        assert stats["parameters"] == {"test": 1.0}
        assert stats["query_count"] == 5
        assert stats["failure_count"] == 2
        assert stats["relation_usefulness"] == {"knows": 0.7}


class TestResetLearningState:
    """Test reset_learning_state method."""
    
    def test_reset_clears_all_state(self, enabled_manager):
        """Test reset clears all learning state."""
        # Set some state
        enabled_manager._learning_parameters = {"param": 1.0}
        enabled_manager._entity_importance_cache = {"e1": 0.9}
        enabled_manager._query_stats = [{"score": 0.8}]
        enabled_manager._failure_count = 2
        enabled_manager._traversal_stats["paths_explored"] = [["e1", "e2"]]
        
        enabled_manager.reset_learning_state()
        
        # All state should be reset
        assert enabled_manager._learning_enabled is False
        assert enabled_manager._learning_cycle == 50
        assert enabled_manager._learning_parameters == {}
        assert enabled_manager._entity_importance_cache == {}
        assert enabled_manager._query_stats == []
        assert enabled_manager._failure_count == 0
        assert enabled_manager._traversal_stats["paths_explored"] == []
        assert enabled_manager._traversal_stats["path_scores"] == {}


class TestMakeJsonSerializable:
    """Test _make_json_serializable static method."""
    
    def test_serialize_primitives(self):
        """Test primitives pass through unchanged."""
        assert LearningStateManager._make_json_serializable(42) == 42
        assert LearningStateManager._make_json_serializable(3.14) == 3.14
        assert LearningStateManager._make_json_serializable("text") == "text"
        assert LearningStateManager._make_json_serializable(True) is True
        assert LearningStateManager._make_json_serializable(None) is None
    
    def test_serialize_dict(self):
        """Test dict serialization (recursive)."""
        obj = {
            "int": 42,
            "float": 3.14,
            "str": "text",
            "nested": {"key": "value"}
        }
        
        result = LearningStateManager._make_json_serializable(obj)
        
        assert result == obj
    
    def test_serialize_list(self):
        """Test list serialization (recursive)."""
        obj = [1, 2, [3, 4], {"key": "value"}]
        
        result = LearningStateManager._make_json_serializable(obj)
        
        assert result == obj
    
    def test_serialize_tuple_to_list(self):
        """Test tuple converted to list."""
        obj = (1, 2, 3)
        
        result = LearningStateManager._make_json_serializable(obj)
        
        assert result == [1, 2, 3]
        assert isinstance(result, list)
    
    def test_serialize_unknown_type_to_string(self):
        """Test unknown types converted to string."""
        class CustomClass:
            def __str__(self):
                return "custom_representation"
        
        obj = CustomClass()
        
        result = LearningStateManager._make_json_serializable(obj)
        
        assert result == "custom_representation"
        assert isinstance(result, str)


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def test_complete_learning_workflow(self, enabled_manager):
        """Test complete learning workflow: enable → record → check → save → load."""
        # Step 1: Record several queries
        queries = [
            {"query": "query 1", "priority": "high"},
            {"query": "query 2", "priority": "normal"},
            {"query": "query 3", "priority": "low"}
        ]
        
        for i, q in enumerate(queries):
            enabled_manager.record_query_performance(q, 0.7 + i * 0.1)
        
        assert len(enabled_manager._query_stats) == 3
        
        # Step 2: Record path performance
        enabled_manager.record_path_performance(["e1", "e2"], 0.85, ["knows"])
        
        assert len(enabled_manager._traversal_stats["paths_explored"]) == 1
        
        # Step 3: Save state
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            saved_path = enabled_manager.save_learning_state(filepath)
            assert saved_path == filepath
            
            # Step 4: Load into new manager
            new_manager = LearningStateManager()
            loaded = new_manager.load_learning_state(filepath)
            
            assert loaded is True
            assert new_manager._learning_enabled is True
            # Note: _query_stats is NOT persisted (only traversal_stats, learning_params, entity cache)
            # but traversal_stats should be loaded
            assert len(new_manager._traversal_stats["paths_explored"]) == 1
    
    def test_fingerprint_collision_detection_workflow(self, enabled_manager):
        """Test fingerprint collision detection workflow."""
        query = {"query": "test query", "priority": "high"}
        
        # First execution - no collision
        fp = enabled_manager.create_query_fingerprint(query)
        assert enabled_manager.detect_fingerprint_collision(fp) is False
        
        # Record performance
        enabled_manager.record_query_performance(query, 0.8)
        
        # Second execution - collision detected
        assert enabled_manager.detect_fingerprint_collision(fp) is True
        
        # Get similar queries
        similar = enabled_manager.get_similar_queries(fp)
        assert len(similar) == 1
        assert similar[0]["success_score"] == 0.8
    
    def test_adaptive_learning_with_circuit_breaker(self):
        """Test adaptive learning with circuit breaker protection."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=5)
        
        # Record 5 successful queries
        for i in range(5):
            query = {"query": f"query {i}"}
            manager.record_query_performance(query, 0.9)
        
        # Trigger learning cycle
        manager.check_learning_cycle()
        
        # Learning should still be enabled
        assert manager._learning_enabled is True
        assert "recent_avg_success" in manager._learning_parameters
        
        # Force errors
        manager._query_stats = None
        
        # Trigger failures
        for _ in range(3):
            manager.check_learning_cycle()
        
        # Circuit breaker should disable learning
        assert manager._learning_enabled is False
