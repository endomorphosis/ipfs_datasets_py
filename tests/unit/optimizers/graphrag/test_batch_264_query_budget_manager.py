"""
Batch 264: Comprehensive tests for QueryBudgetManager
Tests query budget allocation, consumption tracking, and early stopping.
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.query_budget import (
    QueryBudgetManager,
    BudgetManagerProtocol
)


class TestQueryBudgetManagerInitialization:
    """Test QueryBudgetManager initialization."""
    
    def test_init_with_defaults(self):
        """Test initialization with default budget values."""
        manager = QueryBudgetManager()
        
        assert manager.default_budget is not None
        assert "vector_search_ms" in manager.default_budget
        assert "graph_traversal_ms" in manager.default_budget
        assert "ranking_ms" in manager.default_budget
        assert "max_nodes" in manager.default_budget
        assert "max_edges" in manager.default_budget
        assert "timeout_ms" in manager.default_budget
        
        # Check default values
        assert manager.default_budget["vector_search_ms"] == 500.0
        assert manager.default_budget["graph_traversal_ms"] == 1000.0
        assert manager.default_budget["ranking_ms"] == 200.0
        assert manager.default_budget["max_nodes"] == 1000.0
        assert manager.default_budget["max_edges"] == 5000.0
        assert manager.default_budget["timeout_ms"] == 2000.0
        
        # Check initialization of tracking structures
        assert isinstance(manager.budget_history, dict)
        assert "vector_search_ms" in manager.budget_history
        assert isinstance(manager.budget_history["vector_search_ms"], list)
        assert len(manager.budget_history["vector_search_ms"]) == 0
    
    def test_init_with_custom_budget(self):
        """Test initialization with custom budget values."""
        custom_budget = {
            "vector_search_ms": 1000.0,
            "graph_traversal_ms": 2000.0,
            "ranking_ms": 400.0,
            "max_nodes": 2000.0,
            "max_edges": 10000.0,
            "timeout_ms": 5000.0
        }
        manager = QueryBudgetManager(default_budget=custom_budget)
        
        assert manager.default_budget == custom_budget
        assert manager.default_budget["vector_search_ms"] == 1000.0
        assert manager.default_budget["graph_traversal_ms"] == 2000.0
    
    def test_init_budget_history_structure(self):
        """Test that budget history is properly initialized."""
        manager = QueryBudgetManager()
        
        expected_keys = [
            "vector_search_ms",
            "graph_traversal_ms",
            "ranking_ms",
            "nodes_visited",
            "edges_traversed"
        ]
        
        for key in expected_keys:
            assert key in manager.budget_history
            assert isinstance(manager.budget_history[key], list)


class TestAllocateBudget:
    """Test budget allocation based on query complexity and priority."""
    
    def test_allocate_budget_normal_priority(self):
        """Test budget allocation with normal priority."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2, "edge_types": ["related_to"]}
        }
        
        budget = manager.allocate_budget(query, priority="normal")
        
        assert budget is not None
        assert "vector_search_ms" in budget
        assert "graph_traversal_ms" in budget
        # Normal priority should use default multiplier (1.0)
        # Medium complexity should also use 1.0 multiplier
        # So budget should be equal to defaults for medium complexity
        assert isinstance(budget["vector_search_ms"], float)
    
    def test_allocate_budget_low_priority(self):
        """Test budget allocation with low priority."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 1}
        }
        
        budget = manager.allocate_budget(query, priority="low")
        
        # Low priority should reduce budget (0.5 multiplier)
        assert budget["vector_search_ms"] < manager.default_budget["vector_search_ms"]
        assert budget["graph_traversal_ms"] < manager.default_budget["graph_traversal_ms"]
    
    def test_allocate_budget_high_priority(self):
        """Test budget allocation with high priority."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2}
        }
        
        budget = manager.allocate_budget(query, priority="high")
        
        # High priority should increase budget (2.0 multiplier)
        assert budget["vector_search_ms"] > manager.default_budget["vector_search_ms"]
        assert budget["graph_traversal_ms"] > manager.default_budget["graph_traversal_ms"]
    
    def test_allocate_budget_critical_priority(self):
        """Test budget allocation with critical priority."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2}
        }
        
        budget = manager.allocate_budget(query, priority="critical")
        
        # Critical priority should significantly increase budget (5.0 multiplier)
        assert budget["vector_search_ms"] >= manager.default_budget["vector_search_ms"] * 4
    
    def test_allocate_budget_initializes_consumption_tracking(self):
        """Test that allocate_budget initializes consumption tracking."""
        manager = QueryBudgetManager()
        query = {"vector_params": {}}
        
        manager.allocate_budget(query)
        
        assert hasattr(manager, "current_consumption")
        assert "vector_search_ms" in manager.current_consumption
        assert manager.current_consumption["vector_search_ms"] == 0.0


class TestEstimateComplexity:
    """Test query complexity estimation."""
    
    def test_estimate_low_complexity(self):
        """Test estimation of low complexity query."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 3},
            "traversal": {"max_depth": 1, "edge_types": []}
        }
        
        complexity = manager._estimate_complexity(query)
        
        # top_k=3 * 0.5 = 1.5, max_depth=1 * 2 = 2, total = 3.5 < 5
        assert complexity == "low"
    
    def test_estimate_medium_complexity(self):
        """Test estimation of medium complexity query."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2, "edge_types": ["related_to"]}
        }
        
        complexity = manager._estimate_complexity(query)
        
        # top_k=5 * 0.5 = 2.5, max_depth=2 * 2 = 4, edge_types=1 * 0.3 = 0.3, total = 6.8
        assert complexity == "medium"
    
    def test_estimate_high_complexity(self):
        """Test estimation of high complexity query."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 10},
            "traversal": {"max_depth": 3, "edge_types": ["related_to", "contains"]}
        }
        
        complexity = manager._estimate_complexity(query)
        
        # top_k=10 * 0.5 = 5, max_depth=3 * 2 = 6, edge_types=2 * 0.3 = 0.6, total = 11.6
        assert complexity == "high"
    
    def test_estimate_very_high_complexity(self):
        """Test estimation of very high complexity query."""
        manager = QueryBudgetManager()
        query = {
            "vector_params": {"top_k": 20},
            "traversal": {
                "max_depth": 5,
                "edge_types": ["related_to", "contains", "part_of", "instance_of"]
            }
        }
        
        complexity = manager._estimate_complexity(query)
        
        # top_k=20 * 0.5 = 10, max_depth=5 * 2 = 10, edge_types=4 * 0.3 = 1.2, total = 21.2
        assert complexity == "very_high"
    
    def test_estimate_complexity_missing_params(self):
        """Test complexity estimation with missing query parameters."""
        manager = QueryBudgetManager()
        query = {}
        
        complexity = manager._estimate_complexity(query)
        
        # Empty query should have low complexity
        assert complexity == "low"


class TestTrackConsumption:
    """Test resource consumption tracking."""
    
    def test_track_consumption_single_resource(self):
        """Test tracking consumption for a single resource."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0
        }
        
        manager.track_consumption("vector_search_ms", 100.0)
        
        assert manager.current_consumption["vector_search_ms"] == 100.0
    
    def test_track_consumption_cumulative(self):
        """Test that consumption tracking is cumulative."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 50.0,
            "graph_traversal_ms": 0.0
        }
        
        manager.track_consumption("vector_search_ms", 75.0)
        
        assert manager.current_consumption["vector_search_ms"] == 125.0
    
    def test_track_consumption_multiple_resources(self):
        """Test tracking consumption for multiple resources."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0,
            "ranking_ms": 0.0
        }
        
        manager.track_consumption("vector_search_ms", 100.0)
        manager.track_consumption("graph_traversal_ms", 250.0)
        manager.track_consumption("ranking_ms", 50.0)
        
        assert manager.current_consumption["vector_search_ms"] == 100.0
        assert manager.current_consumption["graph_traversal_ms"] == 250.0
        assert manager.current_consumption["ranking_ms"] == 50.0
    
    def test_track_consumption_unknown_resource(self):
        """Test tracking consumption for unknown resource."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 0.0}
        
        # Should not raise error
        manager.track_consumption("unknown_resource", 100.0)
        
        # Should not add to current_consumption
        assert "unknown_resource" not in manager.current_consumption


class TestIsBudgetExceeded:
    """Test budget exceeded checks."""
    
    def test_is_budget_exceeded_false(self):
        """Test when budget is not exceeded."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 400.0}
        manager.default_budget = {"vector_search_ms": 500.0}
        
        exceeded = manager.is_budget_exceeded("vector_search_ms")
        
        assert exceeded is False
    
    def test_is_budget_exceeded_true(self):
        """Test when budget is exceeded."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 600.0}
        manager.default_budget = {"vector_search_ms": 500.0}
        
        exceeded = manager.is_budget_exceeded("vector_search_ms")
        
        assert exceeded is True
    
    def test_is_budget_exceeded_exact_limit(self):
        """Test when consumption equals budget limit."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 500.0}
        manager.default_budget = {"vector_search_ms": 500.0}
        
        exceeded = manager.is_budget_exceeded("vector_search_ms")
        
        # Exact limit should not be considered exceeded (> not >=)
        assert exceeded is False
    
    def test_is_budget_exceeded_unknown_resource(self):
        """Test budget check for unknown resource."""
        manager = QueryBudgetManager()
        manager.current_consumption = {}
        manager.default_budget = {}
        
        exceeded = manager.is_budget_exceeded("unknown_resource")
        
        assert exceeded is False


class TestRecordCompletion:
    """Test recording query completion."""
    
    def test_record_completion_success(self):
        """Test recording successful query completion."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 100.0,
            "graph_traversal_ms": 200.0,
            "ranking_ms": 50.0,
            "nodes_visited": 100.0,
            "edges_traversed": 500.0
        }
        
        manager.record_completion(success=True)
        
        # Check that consumption was added to history
        assert len(manager.budget_history["vector_search_ms"]) == 1
        assert manager.budget_history["vector_search_ms"][0] == 100.0
        assert len(manager.budget_history["graph_traversal_ms"]) == 1
        assert manager.budget_history["graph_traversal_ms"][0] == 200.0
    
    def test_record_completion_failure(self):
        """Test recording failed query completion."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 150.0,
            "graph_traversal_ms": 300.0
        }
        
        manager.record_completion(success=False)
        
        # History should still be updated even on failure
        assert len(manager.budget_history["vector_search_ms"]) == 1
        assert manager.budget_history["vector_search_ms"][0] == 150.0
    
    def test_record_completion_history_limit(self):
        """Test that history is limited to 100 entries."""
        manager = QueryBudgetManager()
        
        # Add 105 completions
        for i in range(105):
            manager.current_consumption = {"vector_search_ms": float(i)}
            manager.record_completion()
        
        # History should be limited to 100
        assert len(manager.budget_history["vector_search_ms"]) == 100
        # Should keep the most recent 100
        assert manager.budget_history["vector_search_ms"][0] == 5.0  # First of recent 100
        assert manager.budget_history["vector_search_ms"][-1] == 104.0  # Last entry


class TestApplyHistoricalAdjustment:
    """Test historical budget adjustment."""
    
    def test_apply_historical_adjustment_empty_history(self):
        """Test adjustment with no historical data."""
        manager = QueryBudgetManager()
        budget = manager.default_budget.copy()
        original_budget = budget.copy()
        
        manager._apply_historical_adjustment(budget)
        
        # Budget should remain unchanged with no history
        assert budget == original_budget
    
    def test_apply_historical_adjustment_with_history(self):
        """Test adjustment based on historical consumption."""
        manager = QueryBudgetManager()
        
        # Add historical data showing consistent lower consumption
        manager.budget_history["vector_search_ms"] = [200.0, 250.0, 220.0, 240.0, 230.0]
        
        budget = {"vector_search_ms": 500.0}
        manager._apply_historical_adjustment(budget)
        
        # Budget should be adjusted based on avg and p95
        # avg = 228, p95 = 250, adjusted = 239
        # But should not go below 80% of default (400)
        assert budget["vector_search_ms"] > 0
    
    def test_apply_historical_adjustment_respects_minimum(self):
        """Test that adjustment respects minimum budget threshold."""
        manager = QueryBudgetManager()
        
        # Add historical data showing very low consumption
        manager.budget_history["vector_search_ms"] = [50.0, 60.0, 55.0, 58.0, 52.0]
        
        budget = {"vector_search_ms": 500.0}
        manager.default_budget["vector_search_ms"] = 500.0
        
        manager._apply_historical_adjustment(budget)
        
        # Budget should not go below 80% of default (400)
        assert budget["vector_search_ms"] >= 400.0


class TestSuggestEarlyStopping:
    """Test early stopping suggestions."""
    
    def test_suggest_early_stopping_insufficient_results(self):
        """Test that early stopping is not suggested with few results."""
        manager = QueryBudgetManager()
        results = [{"score": 0.9}, {"score": 0.8}]
        
        should_stop = manager.suggest_early_stopping(results, budget_consumed_ratio=0.9)
        
        assert should_stop is False
    
    def test_suggest_early_stopping_high_quality_high_consumption(self):
        """Test early stopping with high quality results and high consumption."""
        manager = QueryBudgetManager()
        results = [
            {"score": 0.95},
            {"score": 0.92},
            {"score": 0.90},
            {"score": 0.88}
        ]
        
        should_stop = manager.suggest_early_stopping(results, budget_consumed_ratio=0.8)
        
        # High quality (avg > 0.85) + high consumption (> 0.7) should suggest stopping
        assert should_stop is True
    
    def test_suggest_early_stopping_low_quality_high_consumption(self):
        """Test no early stopping with low quality despite high consumption."""
        manager = QueryBudgetManager()
        results = [
            {"score": 0.7},
            {"score": 0.65},
            {"score": 0.6},
            {"score": 0.55}
        ]
        
        should_stop = manager.suggest_early_stopping(results, budget_consumed_ratio=0.9)
        
        # Low quality should not suggest early stopping
        assert should_stop is False
    
    def test_suggest_early_stopping_score_dropoff(self):
        """Test early stopping based on score drop-off."""
        manager = QueryBudgetManager()
        results = [
            {"score": 0.95},
            {"score": 0.9},
            {"score": 0.85},
            {"score": 0.8},
            {"score": 0.6},  # Significant drop
            {"score": 0.55}
        ]
        
        should_stop = manager.suggest_early_stopping(results, budget_consumed_ratio=0.5)
        
        # Score drop-off > 0.3 should suggest stopping
        assert should_stop is True
    
    def test_suggest_early_stopping_no_scores(self):
        """Test early stopping when results don't have scores."""
        manager = QueryBudgetManager()
        results = [
            {"text": "result1"},
            {"text": "result2"},
            {"text": "result3"},
            {"text": "result4"}
        ]
        
        should_stop = manager.suggest_early_stopping(results, budget_consumed_ratio=0.9)
        
        # Without scores, should not suggest early stopping
        assert should_stop is False


class TestGetCurrentConsumptionReport:
    """Test consumption report generation."""
    
    def test_get_consumption_report_structure(self):
        """Test that consumption report has correct structure."""
        manager = QueryBudgetManager()
        manager.current_consumption = {
            "vector_search_ms": 250.0,
            "graph_traversal_ms": 500.0,
            "ranking_ms": 100.0
        }
        
        report = manager.get_current_consumption_report()
        
        assert "vector_search_ms" in report
        assert "graph_traversal_ms" in report
        assert "ranking_ms" in report
        assert "budget" in report
        assert "ratios" in report
        assert "overall_consumption_ratio" in report
    
    def test_get_consumption_report_ratios(self):
        """Test that consumption ratios are calculated correctly."""
        manager = QueryBudgetManager()
        manager.default_budget = {
            "vector_search_ms": 500.0,
            "graph_traversal_ms": 1000.0
        }
        manager.current_consumption = {
            "vector_search_ms": 250.0,  # 50% of budget
            "graph_traversal_ms": 500.0  # 50% of budget
        }
        
        report = manager.get_current_consumption_report()
        
        assert report["ratios"]["vector_search_ms"] == 0.5
        assert report["ratios"]["graph_traversal_ms"] == 0.5
        assert report["overall_consumption_ratio"] == 0.5
    
    def test_get_consumption_report_zero_budget(self):
        """Test consumption report when budget is zero."""
        manager = QueryBudgetManager()
        manager.default_budget = {"vector_search_ms": 0.0}
        manager.current_consumption = {"vector_search_ms": 100.0}
        
        report = manager.get_current_consumption_report()
        
        # Should handle zero budget gracefully
        assert "ratios" in report
        assert report["ratios"]["vector_search_ms"] == 0.0
    
    def test_get_consumption_report_includes_budget(self):
        """Test that report includes budget information."""
        manager = QueryBudgetManager()
        manager.default_budget = {
            "vector_search_ms": 500.0,
            "graph_traversal_ms": 1000.0
        }
        manager.current_consumption = {"vector_search_ms": 100.0}
        
        report = manager.get_current_consumption_report()
        
        assert "budget" in report
        assert report["budget"]["vector_search_ms"] == 500.0
        assert report["budget"]["graph_traversal_ms"] == 1000.0


class TestBudgetManagerProtocol:
    """Test BudgetManagerProtocol compliance."""
    
    def test_implements_protocol(self):
        """Test that QueryBudgetManager implements BudgetManagerProtocol."""
        manager = QueryBudgetManager()
        
        # Check that manager implements the protocol
        assert isinstance(manager, BudgetManagerProtocol)
    
    def test_protocol_methods_callable(self):
        """Test that protocol methods are callable."""
        manager = QueryBudgetManager()
        
        assert callable(manager.allocate_budget)
        assert callable(manager.track_consumption)
        assert callable(manager.get_current_consumption_report)


class TestIntegrationScenarios:
    """Test integrated budget management workflows."""
    
    def test_complete_budget_lifecycle(self):
        """Test complete lifecycle: allocate, track, check, record."""
        manager = QueryBudgetManager()
        
        # Allocate budget
        query = {
            "vector_params": {"top_k": 10},
            "traversal": {"max_depth": 3}
        }
        budget = manager.allocate_budget(query, priority="high")
        
        # Track consumption
        manager.track_consumption("vector_search_ms", 300.0)
        manager.track_consumption("graph_traversal_ms", 700.0)
        
        # Check budget status
        exceeded = manager.is_budget_exceeded("vector_search_ms")
        
        # Get report
        report = manager.get_current_consumption_report()
        
        # Record completion
        manager.record_completion(success=True)
        
        assert budget is not None
        assert report["vector_search_ms"] == 300.0
        assert len(manager.budget_history["vector_search_ms"]) == 1
    
    def test_multiple_queries_with_adaptation(self):
        """Test multiple queries with historical budget adaptation."""
        manager = QueryBudgetManager()
        
        # Execute multiple queries
        for i in range(5):
            query = {
                "vector_params": {"top_k": 5},
                "traversal": {"max_depth": 2}
            }
            
            budget = manager.allocate_budget(query)
            manager.track_consumption("vector_search_ms", 200.0 + i * 10)
            manager.record_completion(success=True)
        
        # Sixth query should benefit from historical data
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2}
        }
        adapted_budget = manager.allocate_budget(query)
        
        assert len(manager.budget_history["vector_search_ms"]) == 5
        assert adapted_budget is not None


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_query(self):
        """Test budget allocation with empty query."""
        manager = QueryBudgetManager()
        query = {}
        
        budget = manager.allocate_budget(query)
        
        # Should handle empty query gracefully
        assert budget is not None
        assert "vector_search_ms" in budget
    
    def test_negative_consumption(self):
        """Test tracking negative consumption."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 100.0}
        
        manager.track_consumption("vector_search_ms", -50.0)
        
        # Should allow negative tracking (e.g., for corrections)
        assert manager.current_consumption["vector_search_ms"] == 50.0
    
    def test_very_large_consumption(self):
        """Test tracking very large consumption values."""
        manager = QueryBudgetManager()
        manager.current_consumption = {"vector_search_ms": 0.0}
        
        manager.track_consumption("vector_search_ms", 1e10)
        
        assert manager.current_consumption["vector_search_ms"] == 1e10
    
    def test_unknown_priority_level(self):
        """Test budget allocation with unknown priority level."""
        manager = QueryBudgetManager()
        query = {"vector_params": {}}
        
        budget = manager.allocate_budget(query, priority="unknown")
        
        # Should use default multiplier (1.0) for unknown priority
        assert budget is not None
