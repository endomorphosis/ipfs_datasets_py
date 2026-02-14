"""
Unit tests for optimizer_learning_metrics module.

Tests the OptimizerLearningMetricsCollector class which tracks and
aggregates metrics for statistical learning in the RAG query optimizer.
"""

import json
import os
import tempfile
import time
from pathlib import Path
import pytest

from ipfs_datasets_py.optimizers.optimizer_learning_metrics import (
    LearningMetrics,
    OptimizerLearningMetricsCollector,
)


class TestLearningMetrics:
    """Test LearningMetrics dataclass."""

    def test_learning_metrics_initialization(self):
        """Test creating LearningMetrics with default values."""
        metrics = LearningMetrics()
        
        assert metrics.total_learning_cycles == 0
        assert metrics.total_analyzed_queries == 0
        assert metrics.total_patterns_identified == 0
        assert metrics.total_parameters_adjusted == 0
        assert metrics.average_cycle_time == 0.0
        assert metrics.total_optimizations == 0

    def test_learning_metrics_with_values(self):
        """Test creating LearningMetrics with custom values."""
        metrics = LearningMetrics(
            total_learning_cycles=10,
            total_analyzed_queries=100,
            total_patterns_identified=25,
            total_parameters_adjusted=50,
            average_cycle_time=1.5,
            total_optimizations=75
        )
        
        assert metrics.total_learning_cycles == 10
        assert metrics.total_analyzed_queries == 100
        assert metrics.total_patterns_identified == 25
        assert metrics.total_parameters_adjusted == 50
        assert metrics.average_cycle_time == 1.5
        assert metrics.total_optimizations == 75


class TestOptimizerLearningMetricsCollector:
    """Test OptimizerLearningMetricsCollector class."""

    @pytest.fixture
    def temp_metrics_dir(self):
        """Create a temporary directory for metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def collector(self, temp_metrics_dir):
        """Create a collector instance for testing."""
        return OptimizerLearningMetricsCollector(
            metrics_dir=temp_metrics_dir,
            max_history_size=100
        )

    def test_initialization(self, temp_metrics_dir):
        """Test collector initialization."""
        collector = OptimizerLearningMetricsCollector(
            metrics_dir=temp_metrics_dir,
            max_history_size=50
        )
        
        assert collector.metrics_dir == temp_metrics_dir
        assert collector.max_history_size == 50
        assert os.path.exists(temp_metrics_dir)
        assert collector.learning_cycles == {}
        assert collector.parameter_adaptations == []
        assert collector.strategy_effectiveness == []
        assert collector.query_patterns == []
        assert collector.total_analyzed_queries == 0
        assert collector.total_optimized_queries == 0

    def test_initialization_creates_directory(self):
        """Test that initialization creates metrics directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_path = os.path.join(tmpdir, "new_metrics")
            collector = OptimizerLearningMetricsCollector(metrics_dir=metrics_path)
            
            assert os.path.exists(metrics_path)

    def test_record_learning_cycle(self, collector):
        """Test recording a learning cycle."""
        collector.record_learning_cycle(
            cycle_id="cycle-001",
            analyzed_queries=10,
            patterns_identified=3,
            parameters_adjusted={"param1": 0.5, "param2": 0.8},
            execution_time=1.5
        )
        
        assert "cycle-001" in collector.learning_cycles
        cycle = collector.learning_cycles["cycle-001"]
        assert cycle["analyzed_queries"] == 10
        assert cycle["patterns_identified"] == 3
        assert cycle["parameters_adjusted"] == {"param1": 0.5, "param2": 0.8}
        assert cycle["execution_time"] == 1.5
        assert "timestamp" in cycle

    def test_record_multiple_learning_cycles(self, collector):
        """Test recording multiple learning cycles."""
        for i in range(5):
            collector.record_learning_cycle(
                cycle_id=f"cycle-{i:03d}",
                analyzed_queries=10 + i,
                patterns_identified=i,
                parameters_adjusted={f"param{i}": float(i)},
                execution_time=1.0 + i * 0.1
            )
        
        assert len(collector.learning_cycles) == 5
        assert "cycle-000" in collector.learning_cycles
        assert "cycle-004" in collector.learning_cycles

    def test_record_parameter_adaptation(self, collector):
        """Test recording parameter adaptation."""
        collector.record_parameter_adaptation(
            parameter_name="learning_rate",
            old_value=0.1,
            new_value=0.05,
            adaptation_reason="Performance improvement",
            confidence=0.85
        )
        
        assert len(collector.parameter_adaptations) == 1
        adaptation = collector.parameter_adaptations[0]
        assert adaptation["parameter_name"] == "learning_rate"
        assert adaptation["old_value"] == 0.1
        assert adaptation["new_value"] == 0.05
        assert adaptation["adaptation_reason"] == "Performance improvement"
        assert adaptation["confidence"] == 0.85
        assert "timestamp" in adaptation

    def test_record_strategy_effectiveness(self, collector):
        """Test recording strategy effectiveness."""
        collector.record_strategy_effectiveness(
            strategy_name="semantic_search",
            query_type="technical",
            effectiveness_score=0.85,
            execution_time=1.5,
            result_count=25
        )
        
        assert len(collector.strategy_effectiveness) == 1
        effectiveness = collector.strategy_effectiveness[0]
        assert effectiveness["strategy_name"] == "semantic_search"
        assert effectiveness["query_type"] == "technical"
        assert effectiveness["effectiveness_score"] == 0.85
        assert effectiveness["execution_time"] == 1.5
        assert effectiveness["result_count"] == 25
        assert "timestamp" in effectiveness

    def test_record_query_pattern(self, collector):
        """Test recording query pattern."""
        collector.record_query_pattern(
            pattern_id="pattern-001",
            pattern_type="semantic",
            matching_queries=25,
            average_performance=0.85,
            parameters={"length": "medium", "complexity": "high"}
        )
        
        assert len(collector.query_patterns) == 1
        pattern = collector.query_patterns[0]
        assert pattern["pattern_id"] == "pattern-001"
        assert pattern["pattern_type"] == "semantic"
        assert pattern["matching_queries"] == 25
        assert pattern["average_performance"] == 0.85
        assert pattern["parameters"]["length"] == "medium"

    def test_get_learning_metrics(self, collector):
        """Test getting aggregated learning metrics."""
        # Record some data - parameters_adjusted should be a dict
        collector.record_learning_cycle("c1", 10, 3, {}, 1.0)  # Empty dict
        collector.record_learning_cycle("c2", 15, 4, {"p1": 1.0, "p2": 2.0}, 1.2)  # 2 parameters
        collector.record_parameter_adaptation("param1", 0.1, 0.2, "test", 0.9)
        
        metrics = collector.get_learning_metrics()
        
        assert isinstance(metrics, LearningMetrics)
        assert metrics.total_learning_cycles == 2
        assert metrics.total_analyzed_queries == 25
        assert metrics.total_patterns_identified == 7
        # parameters_adjusted is computed from the length of cycle["parameters_adjusted"]
        assert metrics.total_parameters_adjusted == 2  # From the dict {"p1": 1.0, "p2": 2.0}

    def test_get_effectiveness_by_strategy(self, collector):
        """Test getting effectiveness metrics grouped by strategy."""
        collector.record_strategy_effectiveness("strategy1", "type1", 0.8, 1.0, 10)
        collector.record_strategy_effectiveness("strategy1", "type2", 0.9, 1.2, 12)
        collector.record_strategy_effectiveness("strategy2", "type1", 0.7, 0.8, 8)
        
        effectiveness = collector.get_effectiveness_by_strategy()
        
        assert "strategy1" in effectiveness
        assert "strategy2" in effectiveness
        # Check for actual keys returned by the method
        assert effectiveness["strategy1"]["avg_score"] > 0
        assert effectiveness["strategy1"]["count"] == 2
        assert effectiveness["strategy2"]["count"] == 1

    def test_get_effectiveness_by_query_type(self, collector):
        """Test getting effectiveness metrics grouped by query type."""
        collector.record_strategy_effectiveness("strategy1", "type1", 0.8, 1.0, 10)
        collector.record_strategy_effectiveness("strategy2", "type1", 0.9, 1.2, 12)
        collector.record_strategy_effectiveness("strategy1", "type2", 0.7, 0.8, 8)
        
        effectiveness = collector.get_effectiveness_by_query_type()
        
        assert "type1" in effectiveness
        assert "type2" in effectiveness

    def test_get_patterns_by_type(self, collector):
        """Test getting patterns grouped by type."""
        collector.record_query_pattern("p1", "semantic", 10, 0.8, {})
        collector.record_query_pattern("p2", "semantic", 15, 0.9, {})
        collector.record_query_pattern("p3", "keyword", 20, 0.7, {})
        
        patterns = collector.get_patterns_by_type()
        
        assert "semantic" in patterns
        assert "keyword" in patterns
        # Check for actual keys returned by the method
        assert patterns["semantic"]["count"] == 2
        assert patterns["keyword"]["count"] == 1
        assert patterns["semantic"]["total_queries"] == 25  # 10 + 15

    def test_to_json_serialization(self, collector):
        """Test JSON serialization of collector state."""
        # Add some data
        collector.record_learning_cycle("c1", 10, 3, {"p1": 1.0}, 1.0)
        collector.record_parameter_adaptation("param1", 0.1, 0.2, "test", 0.9)
        
        json_str = collector.to_json()
        
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert "learning_cycles" in data
        assert "parameter_adaptations" in data
        assert "strategy_effectiveness" in data

    def test_from_json_deserialization(self, collector):
        """Test JSON deserialization to restore collector state."""
        # Add some data
        collector.record_learning_cycle("c1", 10, 3, {"p1": 1.0}, 1.0)
        collector.record_parameter_adaptation("param1", 0.1, 0.2, "test", 0.9)
        
        # Serialize
        json_str = collector.to_json()
        
        # Deserialize to new collector
        new_collector = OptimizerLearningMetricsCollector.from_json(json_str)
        
        assert len(new_collector.learning_cycles) == 1
        assert len(new_collector.parameter_adaptations) == 1
        assert "c1" in new_collector.learning_cycles

    def test_max_history_size_enforcement(self):
        """Test that max_history_size limits are enforced."""
        collector = OptimizerLearningMetricsCollector(max_history_size=5)
        
        # Add more items than max_history_size
        for i in range(10):
            collector.record_parameter_adaptation(f"param{i}", i, i+1, "test", 0.9)
        
        # Should only keep the most recent max_history_size items
        assert len(collector.parameter_adaptations) <= 5

    def test_thread_safety(self, collector):
        """Test that metrics collection is thread-safe."""
        import threading
        
        def record_cycles():
            for i in range(10):
                collector.record_learning_cycle(
                    f"cycle-{threading.current_thread().name}-{i}",
                    10, 2, 3, 1.0
                )
        
        threads = []
        for i in range(3):
            thread = threading.Thread(target=record_cycles, name=f"thread-{i}")
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Should have recorded all cycles from all threads
        assert len(collector.learning_cycles) == 30

    def test_empty_metrics(self):
        """Test getting metrics when no data has been recorded."""
        collector = OptimizerLearningMetricsCollector()
        
        metrics = collector.get_learning_metrics()
        
        assert metrics.total_learning_cycles == 0
        assert metrics.total_analyzed_queries == 0
        assert metrics.total_patterns_identified == 0


class TestMetricsPersistence:
    """Test metrics persistence and loading."""

    def test_save_and_load_cycle(self, tmp_path):
        """Test that metrics can be saved and loaded."""
        metrics_dir = str(tmp_path / "metrics")
        
        # Create collector and add data
        collector1 = OptimizerLearningMetricsCollector(metrics_dir=metrics_dir)
        collector1.record_learning_cycle("c1", 10, 3, {"p1": 1.0}, 1.0)
        collector1.record_parameter_adaptation("param1", 0.1, 0.2, "test", 0.9)
        
        # Serialize to JSON
        json_str = collector1.to_json()
        
        # Create new collector from JSON
        collector2 = OptimizerLearningMetricsCollector.from_json(json_str)
        
        # Verify data was preserved
        assert len(collector2.learning_cycles) == 1
        assert len(collector2.parameter_adaptations) == 1
        assert "c1" in collector2.learning_cycles


class TestVisualization:
    """Test visualization methods (when dependencies available)."""

    @pytest.fixture
    def collector_with_data(self, tmp_path):
        """Create a collector with sample data for visualization."""
        collector = OptimizerLearningMetricsCollector(
            metrics_dir=str(tmp_path / "metrics")
        )
        
        # Add sample data
        for i in range(5):
            collector.record_learning_cycle(
                f"cycle-{i}",
                analyzed_queries=10 + i * 2,
                patterns_identified=i + 1,
                parameters_adjusted={f"param{i}": float(i)},
                execution_time=1.0 + i * 0.1
            )
            
            collector.record_strategy_effectiveness(
                f"strategy-{i % 2}",
                f"type-{i % 3}",
                effectiveness_score=0.7 + i * 0.05,
                execution_time=1.0 + i * 0.1,
                result_count=10 + i * 2
            )
        
        return collector

    def test_visualize_learning_cycles_no_error(self, collector_with_data, tmp_path):
        """Test that visualization methods run without error."""
        try:
            output_file = str(tmp_path / "learning_cycles.png")
            collector_with_data.visualize_learning_cycles(
                output_file=output_file,
                show_plot=False
            )
            # If visualization is available, file should be created
            # If not available, method should handle gracefully
        except Exception as e:
            # Should not raise exceptions even if visualization unavailable
            pytest.fail(f"Visualization method raised exception: {e}")

    def test_visualize_strategy_effectiveness_no_error(self, collector_with_data, tmp_path):
        """Test strategy effectiveness visualization."""
        try:
            output_file = str(tmp_path / "strategy_effectiveness.png")
            collector_with_data.visualize_strategy_effectiveness(
                output_file=output_file,
                show_plot=False
            )
        except Exception as e:
            pytest.fail(f"Visualization method raised exception: {e}")

    def test_create_interactive_dashboard_no_error(self, collector_with_data, tmp_path):
        """Test interactive dashboard creation."""
        try:
            output_file = str(tmp_path / "dashboard.html")
            collector_with_data.create_interactive_learning_dashboard(
                output_file=output_file
            )
        except Exception as e:
            pytest.fail(f"Dashboard creation raised exception: {e}")
