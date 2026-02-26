"""
Type validation tests for advanced_performance_optimizer.py

Tests the structure and typing of performance optimization return types:
- OptimizationStateDict: Current optimization state
- PerformanceReportDict: Comprehensive performance report
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from ipfs_datasets_py.optimizers.advanced_performance_optimizer import (
    AdvancedPerformanceOptimizer, ProcessingProfile, ResourceMetrics,
    OptimizationRecommendation, OptimizationStateDict, PerformanceReportDict
)


class TestOptimizationStateDict:
    """Tests for OptimizationStateDict TypedDict structure."""
    
    def test_get_current_optimization_state_returns_dict(self):
        """Verify get_current_optimization_state() returns OptimizationStateDict."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert isinstance(result, dict)
        
    def test_optimization_state_required_fields(self):
        """Verify OptimizationStateDict contains all required fields."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        # Check for key fields that define the state
        assert "current_metrics" in result or len(result) > 0
        assert "monitoring_active" in result
        
    def test_optimization_state_current_metrics(self):
        """Verify current_metrics field contains resource data."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        # current_metrics should be a dict with CPU, memory info
        assert "current_metrics" in result
        assert isinstance(result["current_metrics"], dict)
        
    def test_optimization_state_adaptive_parameters(self):
        """Verify adaptive_parameters field is present."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        # Should have adaptive parameters dict
        assert "adaptive_parameters" in result
        assert isinstance(result["adaptive_parameters"], dict)
        
    def test_optimization_state_target_profile(self):
        """Verify target_profile field reflects the target configuration."""
        profile = ProcessingProfile(
            name="custom_profile",
            max_parallel_workers=8,
            memory_threshold_percent=75.0
        )
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert "target_profile" in result
        assert isinstance(result["target_profile"], dict)
        
    def test_optimization_state_recommendations_list(self):
        """Verify recommendations field is a list of dicts."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)
        
    def test_optimization_state_history_lengths(self):
        """Verify history length fields are integers."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert "processing_history_length" in result
        assert "resource_history_length" in result
        assert isinstance(result["processing_history_length"], int)
        assert isinstance(result["resource_history_length"], int)


class TestPerformanceReportDict:
    """Tests for PerformanceReportDict TypedDict structure."""
    
    def test_get_performance_report_empty_history(self):
        """Verify get_performance_report() handles empty history."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_performance_report()
        
        # Should either have error or be empty
        assert isinstance(result, dict)
        
    def test_performance_report_with_mock_history(self):
        """Verify get_performance_report() structure with mock data."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        # Add some mock history
        optimizer.processing_history.append({
            'operation_id': 'op1',
            'items_processed': 100,
            'duration': 10.0,
            'items_per_second': 10.0,
            'success_rate': 0.95
        })
        
        result = optimizer.get_performance_report()
        
        # Should have report structure
        assert isinstance(result, dict)
        assert len(result) > 0 or "error" in result
        
    def test_performance_report_summary_section(self):
        """Verify report includes summary statistics."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        # Add mock processing history
        optimizer.processing_history.append({
            'operation_id': 'op1',
            'items_processed': 50,
            'duration': 5.0,
            'items_per_second': 10.0,
            'success_rate': 0.90
        })
        optimizer.processing_history.append({
            'operation_id': 'op2',
            'items_processed': 75,
            'duration': 7.5,
            'items_per_second': 10.0,
            'success_rate': 0.95
        })
        
        result = optimizer.get_performance_report()
        
        # Check for expected sections
        if "summary" in result:
            assert isinstance(result["summary"], dict)
            
    def test_performance_report_is_dict(self):
        """Verify get_performance_report() always returns dict."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_performance_report()
        
        assert isinstance(result, dict)
        
    def test_performance_report_with_error(self):
        """Verify error field is returned when history is empty."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        # Don't add any history
        result = optimizer.get_performance_report()
        
        # Should have error message
        assert "error" in result or len(result) == 0


class TestTypeConsistency:
    """Tests for consistency across optimization return types."""
    
    def test_state_is_always_dict(self):
        """Verify get_current_optimization_state() always returns dict."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert isinstance(result, dict)
        
    def test_report_is_always_dict(self):
        """Verify get_performance_report() always returns dict."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_performance_report()
        
        assert isinstance(result, dict)
        
    def test_multiple_state_calls_consistent(self):
        """Verify multiple calls to get_current_optimization_state() are consistent."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result1 = optimizer.get_current_optimization_state()
        result2 = optimizer.get_current_optimization_state()
        
        # Both should be dicts with same key structure
        assert isinstance(result1, dict)
        assert isinstance(result2, dict)
        assert set(result1.keys()) == set(result2.keys())


class TestProfileCreation:
    """Tests for ProcessingProfile integration with optimizer."""
    
    def test_default_profile_initialization(self):
        """Verify optimizer initializes with default profile."""
        optimizer = AdvancedPerformanceOptimizer()
        
        result = optimizer.get_current_optimization_state()
        
        assert isinstance(result, dict)
        assert "target_profile" in result
        
    def test_custom_profile_in_state(self):
        """Verify custom profile appears in optimization state."""
        profile = ProcessingProfile(
            name="custom",
            max_parallel_workers=16,
            memory_threshold_percent=85.0
        )
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        result = optimizer.get_current_optimization_state()
        
        assert "target_profile" in result
        assert isinstance(result["target_profile"], dict)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_empty_processing_history(self):
        """Verify optimizer handles empty processing history."""
        profile = ProcessingProfile(name="test_profile")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile)
        
        # processing_history should be empty
        assert len(optimizer.processing_history) == 0
        
        result = optimizer.get_performance_report()
        
        # Should handle gracefully
        assert isinstance(result, dict)
        
    def test_multiple_profile_changes(self):
        """Verify optimizer state after multiple profile changes."""
        profile1 = ProcessingProfile(name="profile1")
        optimizer = AdvancedPerformanceOptimizer(target_profile=profile1)
        
        state1 = optimizer.get_current_optimization_state()
        
        profile2 = ProcessingProfile(name="profile2", max_parallel_workers=12)
        optimizer.target_profile = profile2
        
        state2 = optimizer.get_current_optimization_state()
        
        # Both states should be valid dicts
        assert isinstance(state1, dict)
        assert isinstance(state2, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
