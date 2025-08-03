"""
Simplified test for the OptimizerLearningMetricsCollector class.
"""

import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Try to import the necessary modules
try:
    from ipfs_datasets_py.rag.rag_query_visualization import OptimizerLearningMetricsCollector
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Required modules not available: {e}")
    MODULES_AVAILABLE = False


@unittest.skipIf(not MODULES_AVAILABLE, "Required modules not available")
class TestOptimizerLearningMetricsCollector(unittest.TestCase):
    """Test the optimizer learning metrics collection functionality."""

    def setUp(self):
        """Set up test environment."""
        self.metrics_collector = OptimizerLearningMetricsCollector()

        # Create temporary directory for visualization outputs
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary files."""
        # Remove temporary directory and its contents
        shutil.rmtree(self.temp_dir)

    def test_record_learning_cycle(self):
        """Test recording learning cycle metrics."""
        # Record a learning cycle
        self.metrics_collector.record_learning_cycle(
            cycle_id="test-cycle-1",
            analyzed_queries=10,
            patterns_identified=2,
            parameters_adjusted={"max_depth": 3, "similarity_threshold": 0.7},
            execution_time=0.5
        )

        # Verify metrics were recorded
        metrics = self.metrics_collector.get_learning_metrics()
        self.assertEqual(metrics.total_learning_cycles, 1)
        self.assertEqual(metrics.total_analyzed_queries, 10)
        self.assertEqual(metrics.total_patterns_identified, 2)

        # Verify cycle data is stored properly
        self.assertIn("test-cycle-1", self.metrics_collector.learning_cycles)
        cycle_data = self.metrics_collector.learning_cycles["test-cycle-1"]
        self.assertEqual(cycle_data["analyzed_queries"], 10)
        self.assertEqual(cycle_data["patterns_identified"], 2)
        self.assertEqual(cycle_data["execution_time"], 0.5)
        self.assertIn("max_depth", cycle_data["parameters_adjusted"])

    def test_record_parameter_adaptation(self):
        """Test recording parameter adaptation metrics."""
        # Record multiple parameter adaptations
        self.metrics_collector.record_parameter_adaptation(
            parameter_name="max_depth",
            old_value=2,
            new_value=3,
            adaptation_reason="performance_optimization",
            confidence=0.8
        )

        self.metrics_collector.record_parameter_adaptation(
            parameter_name="similarity_threshold",
            old_value=0.5,
            new_value=0.7,
            adaptation_reason="accuracy_improvement",
            confidence=0.9
        )

        # Verify adaptations were recorded
        adaptations = self.metrics_collector.parameter_adaptations
        self.assertEqual(len(adaptations), 2)

        # Check specific adaptations
        self.assertEqual(adaptations[0]["parameter_name"], "max_depth")
        self.assertEqual(adaptations[0]["old_value"], 2)
        self.assertEqual(adaptations[0]["new_value"], 3)
        self.assertEqual(adaptations[0]["adaptation_reason"], "performance_optimization")
        self.assertEqual(adaptations[0]["confidence"], 0.8)

        self.assertEqual(adaptations[1]["parameter_name"], "similarity_threshold")
        self.assertEqual(adaptations[1]["old_value"], 0.5)
        self.assertEqual(adaptations[1]["new_value"], 0.7)

    def test_record_strategy_effectiveness(self):
        """Test recording strategy effectiveness metrics."""
        # Record effectiveness for different strategies
        self.metrics_collector.record_strategy_effectiveness(
            strategy_name="depth_first",
            query_type="complex",
            effectiveness_score=0.85,
            execution_time=0.3,
            result_count=5
        )

        self.metrics_collector.record_strategy_effectiveness(
            strategy_name="breadth_first",
            query_type="complex",
            effectiveness_score=0.75,
            execution_time=0.4,
            result_count=8
        )

        # Verify effectiveness data is recorded
        effectiveness_data = self.metrics_collector.strategy_effectiveness
        self.assertEqual(len(effectiveness_data), 2)

        # Check specific effectiveness records
        depth_first = effectiveness_data[0]
        self.assertEqual(depth_first["strategy_name"], "depth_first")
        self.assertEqual(depth_first["query_type"], "complex")
        self.assertEqual(depth_first["effectiveness_score"], 0.85)
        self.assertEqual(depth_first["execution_time"], 0.3)
        self.assertEqual(depth_first["result_count"], 5)

        # Test getting aggregate effectiveness by strategy
        by_strategy = self.metrics_collector.get_effectiveness_by_strategy()
        self.assertIn("depth_first", by_strategy)
        self.assertIn("breadth_first", by_strategy)
        self.assertEqual(by_strategy["depth_first"]["count"], 1)
        self.assertEqual(by_strategy["depth_first"]["avg_score"], 0.85)

    def test_record_query_pattern(self):
        """Test recording query pattern metrics."""
        # Record some query patterns
        self.metrics_collector.record_query_pattern(
            pattern_id="entity_relationship",
            pattern_type="semantic",
            matching_queries=3,
            average_performance=0.4,
            parameters={"depth": 2, "threshold": 0.6}
        )

        self.metrics_collector.record_query_pattern(
            pattern_id="keyword_based",
            pattern_type="lexical",
            matching_queries=5,
            average_performance=0.3,
            parameters={"depth": 1, "threshold": 0.7}
        )

        # Verify patterns were recorded
        patterns = self.metrics_collector.query_patterns
        self.assertEqual(len(patterns), 2)

        # Check specific patterns
        self.assertEqual(patterns[0]["pattern_id"], "entity_relationship")
        self.assertEqual(patterns[0]["pattern_type"], "semantic")
        self.assertEqual(patterns[0]["matching_queries"], 3)
        self.assertEqual(patterns[0]["average_performance"], 0.4)
        self.assertIn("depth", patterns[0]["parameters"])

        # Check pattern aggregation
        by_type = self.metrics_collector.get_patterns_by_type()
        self.assertIn("semantic", by_type)
        self.assertIn("lexical", by_type)
        self.assertEqual(by_type["semantic"]["count"], 1)
        self.assertEqual(by_type["lexical"]["count"], 1)
        self.assertEqual(by_type["semantic"]["total_queries"], 3)
        self.assertEqual(by_type["lexical"]["total_queries"], 5)

    def test_json_serialization(self):
        """Test JSON serialization of metrics data."""
        # Generate sample metrics data
        self.test_record_learning_cycle()
        self.test_record_parameter_adaptation()
        self.test_record_strategy_effectiveness()

        # Serialize to JSON
        json_data = self.metrics_collector.to_json()

        # Verify serialization was successful
        self.assertIsInstance(json_data, str)

        # Deserialize and verify data integrity
        data = json.loads(json_data)
        self.assertIn("learning_cycles", data)
        self.assertIn("parameter_adaptations", data)
        self.assertIn("strategy_effectiveness", data)
        self.assertIn("query_patterns", data)

        # Check if a specific cycle is properly serialized
        self.assertIn("test-cycle-1", data["learning_cycles"])


if __name__ == '__main__':
    unittest.main()
