"""
Simple test for the OptimizerLearningMetricsCollector class.

This test avoids importing the entire package to prevent indentation errors
in other modules from affecting our ability to test the metrics collector.
"""

import os
import sys
import tempfile
import datetime
import unittest
import importlib.util

# Get the path to the visualization module
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
module_path = os.path.join(project_root, 'ipfs_datasets_py', 'rag_query_visualization.py')

# Load the module directly without relying on package imports
spec = importlib.util.spec_from_file_location("rag_query_visualization", module_path)
rag_vis = importlib.util.module_from_spec(spec)
sys.modules["rag_query_visualization"] = rag_vis
spec.loader.exec_module(rag_vis)

# Import the class we want to test
OptimizerLearningMetricsCollector = rag_vis.OptimizerLearningMetricsCollector

class TestLearningMetricsBasics(unittest.TestCase):
    """Basic tests for the OptimizerLearningMetricsCollector."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.metrics = OptimizerLearningMetricsCollector(metrics_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_initialization(self):
        """Test that the metrics collector initializes correctly."""
        self.assertEqual(self.metrics.total_learning_cycles, 0)
        self.assertEqual(self.metrics.total_parameter_adaptations, 0)

    def test_record_learning_cycle(self):
        """Test recording a learning cycle."""
        # Create sample data
        cycle_data = {
            'timestamp': datetime.datetime.now(),
            'analyzed_queries': 10,
            'optimization_rules': {'rule1': True, 'rule2': False}
        }

        # Record the cycle
        self.metrics.record_learning_cycle(cycle_data)

        # Verify metrics
        self.assertEqual(self.metrics.total_learning_cycles, 1)
        self.assertEqual(self.metrics.total_queries_analyzed, 10)
        self.assertEqual(len(self.metrics.learning_cycles), 1)

    def test_record_parameter_adaptation(self):
        """Test recording parameter adaptation."""
        # Record adaptation
        self.metrics.record_parameter_adaptation(
            param_name='max_depth',
            old_value=2,
            new_value=3
        )

        # Verify metrics
        self.assertEqual(self.metrics.total_parameter_adaptations, 1)
        self.assertIn('max_depth', self.metrics.parameter_adaptations)

    def test_get_learning_metrics(self):
        """Test getting aggregated metrics."""
        # Add some data
        self.metrics.record_learning_cycle({
            'timestamp': datetime.datetime.now(),
            'analyzed_queries': 15,
            'optimization_rules': {'rule1': True}
        })

        self.metrics.record_parameter_adaptation('cache_size', 100, 200)

        # Get metrics
        metrics = self.metrics.get_learning_metrics()

        # Verify metrics
        self.assertEqual(metrics['total_learning_cycles'], 1)
        self.assertEqual(metrics['total_parameter_adaptations'], 1)
        self.assertEqual(metrics['total_queries_analyzed'], 15)


if __name__ == "__main__":
    unittest.main()
