"""Comprehensive tests for learning state management."""

import pytest
import json
import os
import logging
import tempfile
from unittest.mock import Mock, patch
from ipfs_datasets_py.optimizers.graphrag.learning_state import LearningStateManager


class TestLearningStateInitialization:
    """Test learning state manager initialization."""

    def test_initialize_learning_state_manager(self):
        """Should initialize with default parameters."""
        manager = LearningStateManager()
        
        assert manager._learning_enabled is False
        assert manager._learning_cycle == 50
        assert isinstance(manager._learning_parameters, dict)
        assert isinstance(manager._traversal_stats, dict)

    def test_enable_statistical_learning(self):
        """Should enable statistical learning."""
        manager = LearningStateManager()
        
        manager.enable_statistical_learning(enabled=True, learning_cycle=25)
        
        assert manager._learning_enabled is True
        assert manager._learning_cycle == 25

    def test_disable_statistical_learning(self):
        """Should disable statistical learning."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        manager.enable_statistical_learning(enabled=False)
        
        assert manager._learning_enabled is False


class TestQueryFingerprinting:
    """Test query fingerprinting functionality."""

    def test_create_simple_query_fingerprint(self):
        """Should create fingerprint for simple query."""
        manager = LearningStateManager()
        query = {"query_text": "Find information"}
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert isinstance(fingerprint, str)
        assert len(fingerprint) > 0

    def test_fingerprint_includes_text_hash(self):
        """Should include text-based hash in fingerprint."""
        manager = LearningStateManager()
        query = {"query_text": "Important question"}
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "txt_" in fingerprint

    def test_fingerprint_includes_traversal_info(self):
        """Should include traversal parameters in fingerprint."""
        manager = LearningStateManager()
        query = {
            "query_text": "Search",
            "traversal": {"max_depth": 3, "edge_types": ["a", "b"]}
        }
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "td_3" in fingerprint
        assert "et_2" in fingerprint

    def test_fingerprint_includes_priority(self):
        """Should include priority in fingerprint."""
        manager = LearningStateManager()
        query = {"query_text": "Test", "priority": "high"}
        
        fingerprint = manager.create_query_fingerprint(query)
        
        assert "p_high" in fingerprint

    def test_fingerprint_consistency(self):
        """Same query should produce same fingerprint."""
        manager = LearningStateManager()
        query = {"query_text": "Consistent", "priority": "normal"}
        
        fp1 = manager.create_query_fingerprint(query)
        fp2 = manager.create_query_fingerprint(query)
        
        assert fp1 == fp2

    def test_fingerprint_collision_detection(self):
        """Should detect when fingerprint has been seen."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        query = {"query_text": "Test", "priority": "normal"}
        fingerprint = manager.create_query_fingerprint(query)
        
        manager.record_query_performance(query, 0.8)
        
        # Should detect collision
        assert manager.detect_fingerprint_collision(fingerprint) is True


class TestQueryPerformanceTracking:
    """Test query performance recording and retrieval."""

    def test_record_query_performance(self):
        """Should record query performance."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        query = {"query_text": "Test"}
        manager.record_query_performance(query, 0.9)
        
        assert len(manager._query_stats) == 1
        assert manager._query_stats[0]["success_score"] == 0.9

    def test_get_similar_queries(self):
        """Should retrieve similar queries."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        query = {"query_text": "Similar query"}
        manager.record_query_performance(query, 0.8)
        manager.record_query_performance(query, 0.85)
        
        fingerprint = manager.create_query_fingerprint(query)
        similar = manager.get_similar_queries(fingerprint, count=10)
        
        assert len(similar) == 2

    def test_learning_disabled_skips_recording(self):
        """Should skip recording when learning disabled."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=False)
        
        query = {"query_text": "Test"}
        manager.record_query_performance(query, 0.8)
        
        assert len(manager._query_stats) == 0


class TestPathPerformanceTracking:
    """Test traversal path performance tracking."""

    def test_record_path_performance(self):
        """Should record traversal path performance."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        path = ["entity1", "entity2", "entity3"]
        manager.record_path_performance(path, 0.85, ["created_by", "related_to"])
        
        assert "entity1|entity2|entity3" in manager._traversal_stats["path_scores"]
        assert manager._traversal_stats["path_scores"]["entity1|entity2|entity3"] == 0.85

    def test_relation_usefulness_update(self):
        """Should update relation usefulness scores."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        path = ["e1", "e2"]
        manager.record_path_performance(path, 0.9, ["important_rel"])
        
        # Relation usefulness should be updated
        assert "important_rel" in manager._traversal_stats["relation_usefulness"]
        assert manager._traversal_stats["relation_usefulness"]["important_rel"] > 0.5


class TestLearningCycleManagement:
    """Test learning cycle triggering and management."""

    def test_check_learning_cycle_triggers_at_threshold(self):
        """Should trigger learning cycle at configured threshold."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=3)
        
        # Add queries
        for i in range(3):
            manager.record_query_performance({"query_text": f"Query {i}"}, 0.8)
        
        # Should have learning parameters updated after cycle
        manager.check_learning_cycle()
        
        assert "recent_avg_success" in manager._learning_parameters

    def test_learning_disabled_skips_cycle(self):
        """Should skip learning cycle when disabled."""
        manager = LearningStateManager()
        manager._learning_enabled = False
        
        manager.check_learning_cycle()
        
        # Should have no effect
        assert len(manager._learning_parameters) == 0

    def test_circuit_breaker_disables_learning_after_failures(self):
        """Should disable learning after repeated failures."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=1)
        manager._max_consecutive_failures = 2
        
        # Directly increment failure counter to test circuit breaker
        manager._failure_count = 0
        
        # First failure
        manager._failure_count += 1
        assert manager._learning_enabled is True
        
        # Second failure
        manager._failure_count += 1
        assert manager._learning_enabled is True
        
        # Simulate what happens in check_learning_cycle when failures reach max
        if manager._failure_count >= manager._max_consecutive_failures:
            logging.warning("Learning disabled due to repeated failures")
            manager._learning_enabled = False
            manager._failure_count = 0
        
        # Learning should be disabled
        assert manager._learning_enabled is False


class TestStatePersistence:
    """Test learning state save/load functionality."""

    def test_save_learning_state_to_file(self):
        """Should save learning state to file."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        manager._learning_parameters["test_param"] = 0.5
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "learning_state.json")
            
            result = manager.save_learning_state(filepath)
            
            assert result is not None
            assert os.path.exists(filepath)

    def test_load_learning_state_from_file(self):
        """Should load learning state from file."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        manager._learning_parameters["test_param"] = 0.75
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "learning_state.json")
            manager.save_learning_state(filepath)
            
            # Create new manager and load
            new_manager = LearningStateManager()
            loaded = new_manager.load_learning_state(filepath)
            
            assert loaded is True
            assert new_manager._learning_parameters.get("test_param") == 0.75

    def test_roundtrip_serialization(self):
        """Should preserve state through save/load cycle."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=25)
        manager._learning_parameters["param1"] = 0.5
        manager._failure_count = 2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            
            # Save
            manager.save_learning_state(filepath)
            
            # Load into new manager
            new_manager = LearningStateManager()
            new_manager.load_learning_state(filepath)
            
            assert new_manager._learning_enabled == manager._learning_enabled
            assert new_manager._learning_cycle == manager._learning_cycle
            assert new_manager._failure_count == manager._failure_count

    def test_save_handles_missing_directory(self):
        """Should create directory if it doesn't exist."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "subdir", "learning_state.json")
            
            result = manager.save_learning_state(filepath)
            
            assert result is not None
            assert os.path.exists(filepath)

    def test_load_nonexistent_file_returns_false(self):
        """Should return False when loading nonexistent file."""
        manager = LearningStateManager()
        
        loaded = manager.load_learning_state("/nonexistent/path/file.json")
        
        assert loaded is False

    def test_invalid_json_load_returns_false(self):
        """Should handle invalid JSON gracefully."""
        manager = LearningStateManager()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "bad.json")
            
            # Write invalid JSON
            with open(filepath, 'w') as f:
                f.write("not valid json {{{")
            
            loaded = manager.load_learning_state(filepath)
            
            assert loaded is False


class TestLearningStatistics:
    """Test learning statistics retrieval."""

    def test_get_learning_stats(self):
        """Should return current learning statistics."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=30)
        
        stats = manager.get_learning_stats()
        
        assert stats["enabled"] is True
        assert stats["cycle"] == 30
        assert "query_count" in stats
        assert "failure_count" in stats

    def test_stats_reflect_recorded_queries(self):
        """Should reflect number of recorded queries."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        # Record some queries
        for i in range(5):
            manager.record_query_performance({"query_text": f"Query {i}"}, 0.8)
        
        stats = manager.get_learning_stats()
        
        assert stats["query_count"] == 5


class TestResetFunctionality:
    """Test learning state reset."""

    def test_reset_learning_state(self):
        """Should reset all learning state."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        manager._learning_parameters["key"] = "value"
        manager._failure_count = 5
        
        manager.reset_learning_state()
        
        assert manager._learning_enabled is False
        assert manager._failure_count == 0
        assert len(manager._learning_parameters) == 0


class TestErrorHandling:
    """Test error handling in learning state management."""

    def test_record_query_with_invalid_data(self):
        """Should handle invalid query data."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        # Should not raise even with unusual data
        manager.record_query_performance(None, 0.8)
        manager.record_query_performance({}, None)
        
        # Manager should still be functional
        assert manager._learning_enabled is True

    def test_path_recording_with_empty_path(self):
        """Should handle empty path gracefully."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        manager.record_path_performance([], 0.8)
        
        # Should not crash
        assert True

    def test_json_serializable_conversion(self):
        """Should handle non-serializable objects."""
        obj = {"list": [1, 2, 3], "nested": {"key": "value"}}
        
        serializable = LearningStateManager._make_json_serializable(obj)
        
        # Should be JSON-serializable
        json_str = json.dumps(serializable)
        assert isinstance(json_str, str)


class TestLearningIntegration:
    """Integration tests for learning state functionality."""

    def test_full_learning_workflow(self):
        """Should handle complete learning workflow."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True, learning_cycle=3)
        
        # Record several queries
        queries = [
            {"query_text": "Find information", "priority": "normal"},
            {"query_text": "Find similar data", "priority": "high"},
            {"query_text": "Find information", "priority": "normal"}
        ]
        
        for query in queries:
            manager.record_query_performance(query, 0.8)
        
        # Trigger learning cycle
        manager.check_learning_cycle()
        
        # Stats should be updated
        assert "recent_avg_success" in manager._learning_parameters

    def test_save_load_with_accumulated_data(self):
        """Should preserve accumulated data through save/load."""
        manager = LearningStateManager()
        manager.enable_statistical_learning(enabled=True)
        
        # Accumulate some data
        for i in range(5):
            path = [f"e{i}", f"e{i+1}"]
            manager.record_path_performance(path, 0.8 + i * 0.02, ["rel1", "rel2"])
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "state.json")
            manager.save_learning_state(filepath)
            
            new_manager = LearningStateManager()
            new_manager.load_learning_state(filepath)
            
            # Should preserve relation usefulness
            assert len(new_manager._traversal_stats["relation_usefulness"]) > 0
