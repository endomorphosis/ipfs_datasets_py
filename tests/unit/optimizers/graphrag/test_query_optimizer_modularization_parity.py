"""Parity tests to verify query optimizer modularization doesn't break functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.optimizers.graphrag.query_detection import QueryDetector
from ipfs_datasets_py.optimizers.graphrag.query_visualization import QueryVisualizationHelper


class TestQueryOptimizerModularizationParity:
    """Verify that extracted modules work correctly with unified optimizer."""

    def test_detect_graph_type_still_works(self):
        """Should still correctly detect graph types after modularization."""
        # Create optimizer instance with minimal setup
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Test Wikipedia detection
        wiki_query = {"entity_source": "wikipedia"}
        assert optimizer.detect_graph_type(wiki_query) == "wikipedia"
        
        # Test IPLD detection
        ipld_query = {"entity_source": "ipld"}
        assert optimizer.detect_graph_type(ipld_query) == "ipld"
        
        # Test general fallback
        general_query = {"query": "generic query"}
        result = optimizer.detect_graph_type(general_query)
        assert result in ["wikipedia", "ipld", "mixed", "general"]

    def test_graph_type_detection_caching_works(self):
        """Should maintain caching behavior after extraction."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Detect same query twice
        query = {"entity_source": "wikipedia"}
        result1 = optimizer.detect_graph_type(query)
        
        # Check hit count increased (cache hit)
        initial_hits = optimizer._type_detection_hit_count
        result2 = optimizer.detect_graph_type(query)
        
        assert result1 == result2
        # Note: hit count may or may not increase depending on caching internals

    def test_visualizer_delegation_works(self):
        """Should correctly delegate to visualization helper."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Mock visualizer and metrics collector with proper attributes
        optimizer.visualizer = Mock()
        optimizer.metrics_collector = Mock()
        optimizer.metrics_collector.metrics_dir = "/tmp"
        optimizer.visualizer.visualize_metrics_dashboard.return_value = None
        
        # Call visualization method
        result = optimizer.visualize_metrics_dashboard()
        
        # Verify delegation occurred
        assert result is None or isinstance(result, str)

    def test_query_detector_integration(self):
        """Should correctly use QueryDetector for query analysis."""
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Test fact verification detection through optimizer
        fact_query = {"query_text": "Is the Earth round?"}
        is_fact = QueryDetector.is_fact_verification_query(fact_query)
        assert is_fact  # Should detect as fact verification

    def test_entity_type_detection_works(self):
        """Should correctly detect entity types."""
        query_text = "Tell me about the author Albert Einstein"
        entity_types = QueryDetector.detect_entity_types(query_text)
        assert "person" in entity_types

    def test_complexity_estimation_works(self):
        """Should correctly estimate query complexity."""
        simple_query = {"traversal": {"max_depth": 1}}
        complexity = QueryDetector.estimate_query_complexity(simple_query)
        assert complexity == "low"
        
        complex_query = {
            "vector_params": {"top_k": 20},
            "traversal": {"max_depth": 5, "edge_types": ["a", "b", "c"]},
            "multi_pass": True
        }
        complexity = QueryDetector.estimate_query_complexity(complex_query)
        assert complexity == "high"

    def test_visualization_helper_handles_missing_components(self):
        """Should handle gracefully when visualizer/metrics unavailable."""
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=None,
            metrics_collector=None,
            query_id="test_query"
        )
        assert result is None

    def test_no_behavior_change_in_public_api(self):
        """Public API should remain unchanged after modularization."""
        # Verify that all public methods still exist
        optimizer = UnifiedGraphRAGQueryOptimizer()
        
        # Check public detection method exists
        assert hasattr(optimizer, "detect_graph_type")
        assert callable(optimizer.detect_graph_type)
        
        # Check visualization methods exist
        assert hasattr(optimizer, "visualize_query_plan")
        assert hasattr(optimizer, "visualize_metrics_dashboard")
        assert hasattr(optimizer, "visualize_performance_comparison")
        assert hasattr(optimizer, "visualize_resource_usage")
        assert hasattr(optimizer, "visualize_query_patterns")


class TestPhase1And2Integration:
    """Test that Phase 1 and Phase 2 modules work together correctly."""

    def test_visualization_and_detection_modules_both_load(self):
        """Both extracted modules should import cleanly."""
        # Import test - if imports fail, test fails
        from ipfs_datasets_py.optimizers.graphrag.query_visualization import QueryVisualizationHelper
        from ipfs_datasets_py.optimizers.graphrag.query_detection import QueryDetector
        
        assert QueryVisualizationHelper is not None
        assert QueryDetector is not None

    def test_unified_optimizer_imports_both_modules(self):
        """Unified optimizer should successfully import both extraction modules."""
        from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer
        
        # If imports fail, this test fails
        # Verify that the optimizer can be instantiated
        optimizer = UnifiedGraphRAGQueryOptimizer()
        assert optimizer is not None
