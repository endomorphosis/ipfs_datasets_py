"""
Tests for the OptimizerLearningMetricsCollector and visualization capabilities.

This module tests the collection and visualization of metrics related to the RAG
query optimizer's statistical learning process, including learning cycles, parameter
adaptations, and strategy effectiveness.
"""

import os
import sys
import tempfile
import unittest
import datetime
import numpy as np
from unittest.mock import patch, MagicMock

# Add the project root to the Python path to ensure we're using the local version
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Direct imports from local files
import ipfs_datasets_py.rag_query_visualization as rag_vis

# Import components to test
OptimizerLearningMetricsCollector = rag_vis.OptimizerLearningMetricsCollector
RAGQueryDashboard = rag_vis.RAGQueryDashboard
QueryMetricsCollector = rag_vis.QueryMetricsCollector

class TestOptimizerLearningMetricsCollector(unittest.TestCase):
    """Tests for the OptimizerLearningMetricsCollector class."""
    
    def setUp(self):
        """Set up test environment with a temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.metrics_collector = OptimizerLearningMetricsCollector(
            metrics_dir=self.temp_dir
        )
        
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
        
    def test_initialization(self):
        """Test that the metrics collector initializes properly."""
        self.assertEqual(self.metrics_collector.total_learning_cycles, 0)
        self.assertEqual(self.metrics_collector.total_parameter_adaptations, 0)
        self.assertEqual(self.metrics_collector.total_queries_analyzed, 0)
        self.assertIsNone(self.metrics_collector.last_learning_cycle_time)
        
    def test_record_learning_cycle(self):
        """Test recording a learning cycle."""
        # Create a sample learning cycle
        cycle_data = {
            'timestamp': datetime.datetime.now(),
            'analyzed_queries': 10,
            'optimization_rules': {
                'max_depth': 3,
                'caching_enabled': True
            }
        }
        
        # Record the cycle
        self.metrics_collector.record_learning_cycle(cycle_data)
        
        # Verify metrics were updated
        self.assertEqual(self.metrics_collector.total_learning_cycles, 1)
        self.assertEqual(self.metrics_collector.total_queries_analyzed, 10)
        self.assertIsNotNone(self.metrics_collector.last_learning_cycle_time)
        
        # Verify cycle was added to history
        self.assertEqual(len(self.metrics_collector.learning_cycles), 1)
        self.assertEqual(self.metrics_collector.learning_cycles[0]['analyzed_queries'], 10)
        self.assertEqual(self.metrics_collector.learning_cycles[0]['rule_count'], 2)
        
    def test_record_parameter_adaptation(self):
        """Test recording a parameter adaptation."""
        # Record parameter change
        self.metrics_collector.record_parameter_adaptation(
            param_name='max_depth',
            old_value=2,
            new_value=3
        )
        
        # Verify metrics were updated
        self.assertEqual(self.metrics_collector.total_parameter_adaptations, 1)
        
        # Verify adaptation was recorded
        self.assertIn('max_depth', self.metrics_collector.parameter_adaptations)
        self.assertEqual(len(self.metrics_collector.parameter_adaptations['max_depth']), 1)
        
        adaptation = self.metrics_collector.parameter_adaptations['max_depth'][0]
        self.assertEqual(adaptation['old_value'], 2)
        self.assertEqual(adaptation['new_value'], 3)
        self.assertEqual(adaptation['delta'], 1)
        
    def test_record_strategy_effectiveness(self):
        """Test recording strategy effectiveness."""
        # Record strategy effectiveness
        self.metrics_collector.record_strategy_effectiveness(
            strategy_name='wiki_optimization',
            success=True,
            execution_time=0.5
        )
        
        # Record another data point
        self.metrics_collector.record_strategy_effectiveness(
            strategy_name='wiki_optimization',
            success=False,
            execution_time=1.2
        )
        
        # Verify metrics were updated
        self.assertIn('wiki_optimization', self.metrics_collector.strategy_effectiveness)
        
        strategy_metrics = self.metrics_collector.strategy_effectiveness['wiki_optimization']
        self.assertEqual(strategy_metrics['total_count'], 2)
        self.assertEqual(strategy_metrics['success_count'], 1)
        self.assertAlmostEqual(strategy_metrics['total_time'], 1.7)
        self.assertAlmostEqual(strategy_metrics['avg_time'], 0.85)
        
        # Verify history was recorded
        self.assertEqual(len(strategy_metrics['history']), 2)
        
    def test_record_query_pattern(self):
        """Test recording query patterns."""
        # Record a pattern
        pattern1 = {
            'type': 'vector_only',
            'vector_dim': 768,
            'top_k': 5
        }
        
        self.metrics_collector.record_query_pattern(pattern1)
        
        # Record the same pattern again
        self.metrics_collector.record_query_pattern(pattern1)
        
        # Record a different pattern
        pattern2 = {
            'type': 'hybrid',
            'vector_dim': 768,
            'graph_depth': 2
        }
        
        self.metrics_collector.record_query_pattern(pattern2)
        
        # Get top patterns
        top_patterns = self.metrics_collector.get_top_query_patterns()
        
        # Verify patterns were recorded correctly
        self.assertEqual(len(top_patterns), 2)
        
        # First pattern should have count=2
        self.assertEqual(top_patterns[0]['count'], 2)
        
        # Second pattern should have count=1
        self.assertEqual(top_patterns[1]['count'], 1)
        
    @unittest.skipIf(not hasattr(np, 'ndarray'), "NumPy not available")
    def test_numpy_serialization(self):
        """Test handling of NumPy arrays in serialization."""
        # Create a parameter adaptation with NumPy values
        self.metrics_collector.record_parameter_adaptation(
            param_name='embedding_weights',
            old_value=np.array([0.1, 0.2, 0.3]),
            new_value=np.array([0.2, 0.3, 0.4])
        )
        
        # Verify serialization works
        serialized = self.metrics_collector._convert_to_serializable(
            self.metrics_collector.parameter_adaptations
        )
        
        # Verify NumPy arrays were converted to lists
        new_value = serialized['embedding_weights'][0]['new_value']
        self.assertIsInstance(new_value, list)
        self.assertEqual(new_value, [0.2, 0.3, 0.4])
        
    def test_get_learning_metrics(self):
        """Test getting aggregated learning metrics."""
        # Record some data
        self.metrics_collector.record_learning_cycle({
            'timestamp': datetime.datetime.now(),
            'analyzed_queries': 15,
            'optimization_rules': {'rule1': True, 'rule2': False}
        })
        
        self.metrics_collector.record_parameter_adaptation(
            'max_depth', 2, 3
        )
        
        self.metrics_collector.record_query_pattern({'type': 'test'})
        
        # Get metrics
        metrics = self.metrics_collector.get_learning_metrics()
        
        # Verify metrics
        self.assertEqual(metrics['total_learning_cycles'], 1)
        self.assertEqual(metrics['total_parameter_adaptations'], 1)
        self.assertEqual(metrics['total_queries_analyzed'], 15)
        self.assertEqual(metrics['recognized_patterns'], 1)
        self.assertEqual(metrics['tracked_parameters'], 1)


class TestOptimizerLearningVisualization(unittest.TestCase):
    """Tests for the visualization capabilities of OptimizerLearningMetricsCollector."""
    
    def setUp(self):
        """Set up test environment with sample data."""
        self.temp_dir = tempfile.mkdtemp()
        self.metrics_collector = OptimizerLearningMetricsCollector(
            metrics_dir=self.temp_dir
        )
        
        # Add sample data for visualization
        self._add_sample_data()
        
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
        
    def _add_sample_data(self):
        """Add sample data for visualizations."""
        # Add learning cycles
        for i in range(5):
            cycle_time = datetime.datetime.now() - datetime.timedelta(hours=5-i)
            self.metrics_collector.record_learning_cycle({
                'timestamp': cycle_time,
                'analyzed_queries': 10 + i*5,
                'optimization_rules': {f'rule_{j}': True for j in range(i+1)}
            })
        
        # Add parameter adaptations
        for i in range(4):
            param_time = datetime.datetime.now() - datetime.timedelta(hours=4-i)
            # Parameter 1: max_depth
            self.metrics_collector.record_parameter_adaptation(
                param_name='max_depth',
                old_value=i+1,
                new_value=i+2,
                # Override timestamp for testing
                timestamp=param_time
            )
            
            # Parameter 2: cache_size
            self.metrics_collector.record_parameter_adaptation(
                param_name='cache_size',
                old_value=100 + i*50,
                new_value=150 + i*50,
                # Override timestamp for testing
                timestamp=param_time
            )
        
        # Add strategy effectiveness
        strategies = ['vector_search', 'graph_traversal', 'hybrid']
        for strategy in strategies:
            for i in range(5):
                success = i > 1  # First two attempts fail, rest succeed
                execution_time = 0.5 - (0.05 * i) if success else 1.5
                self.metrics_collector.record_strategy_effectiveness(
                    strategy_name=strategy,
                    success=success,
                    execution_time=execution_time
                )
        
        # Add query patterns
        patterns = [
            {'type': 'vector_only', 'top_k': 5},
            {'type': 'vector_only', 'top_k': 10},
            {'type': 'graph_only', 'max_depth': 2},
            {'type': 'hybrid', 'top_k': 5, 'max_depth': 1}
        ]
        
        # Record patterns with different frequencies
        for i, pattern in enumerate(patterns):
            for _ in range(4 - i):  # First pattern appears most often
                self.metrics_collector.record_query_pattern(pattern)
    
    @patch('matplotlib.pyplot.savefig')  
    @patch('matplotlib.pyplot.show')
    def test_visualize_learning_cycles(self, mock_show, mock_savefig):
        """Test learning cycles visualization."""
        # Skip if matplotlib is not available
        try:
            import matplotlib.pyplot
        except ImportError:
            self.skipTest("Matplotlib not available")
        
        # Test visualization without showing
        output_file = os.path.join(self.temp_dir, "learning_cycles.png")
        fig = self.metrics_collector.visualize_learning_cycles(
            output_file=output_file,
            show_plot=False
        )
        
        # Verify figure was created
        self.assertIsNotNone(fig)
        
        # Verify savefig was called
        mock_savefig.assert_called_once()
        
        # Verify show was not called
        mock_show.assert_not_called()
    
    @patch('matplotlib.pyplot.savefig')  
    @patch('matplotlib.pyplot.show')
    def test_visualize_parameter_adaptations(self, mock_show, mock_savefig):
        """Test parameter adaptations visualization."""
        # Skip if matplotlib is not available
        try:
            import matplotlib.pyplot
        except ImportError:
            self.skipTest("Matplotlib not available")
        
        # Test visualization without showing
        output_file = os.path.join(self.temp_dir, "parameter_adaptations.png")
        fig = self.metrics_collector.visualize_parameter_adaptations(
            output_file=output_file,
            show_plot=False
        )
        
        # Verify figure was created
        self.assertIsNotNone(fig)
        
        # Verify savefig was called
        mock_savefig.assert_called_once()
        
        # Verify show was not called
        mock_show.assert_not_called()
    
    @patch('matplotlib.pyplot.savefig')  
    @patch('matplotlib.pyplot.show')
    def test_visualize_strategy_effectiveness(self, mock_show, mock_savefig):
        """Test strategy effectiveness visualization."""
        # Skip if matplotlib is not available
        try:
            import matplotlib.pyplot
        except ImportError:
            self.skipTest("Matplotlib not available")
        
        # Test visualization without showing
        output_file = os.path.join(self.temp_dir, "strategy_effectiveness.png")
        fig = self.metrics_collector.visualize_strategy_effectiveness(
            output_file=output_file,
            show_plot=False
        )
        
        # Verify figure was created
        self.assertIsNotNone(fig)
        
        # Verify savefig was called
        mock_savefig.assert_called_once()
        
        # Verify show was not called
        mock_show.assert_not_called()
    
    @unittest.skipIf(True, "Plotly test skipped to avoid external dependencies")
    def test_create_interactive_learning_dashboard(self):
        """Test creating an interactive learning dashboard."""
        # This test is skipped by default as it requires plotly
        # Skip if plotly is not available
        try:
            import plotly.graph_objects
            from jinja2 import Template
        except ImportError:
            self.skipTest("Plotly or Jinja2 not available")
        
        # Test creating interactive dashboard
        output_file = os.path.join(self.temp_dir, "learning_dashboard.html")
        result = self.metrics_collector.create_interactive_learning_dashboard(
            output_file=output_file,
            show_plot=False
        )
        
        # Verify file was created
        self.assertTrue(os.path.exists(output_file))
        self.assertGreater(os.path.getsize(output_file), 0)
        
        # Verify returned path matches output file
        self.assertEqual(result, output_file)


class TestDashboardIntegration(unittest.TestCase):
    """Test integration of learning metrics with the dashboard."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create query metrics collector
        self.query_metrics = QueryMetricsCollector()
        
        # Create learning metrics collector with sample data
        self.learning_metrics = OptimizerLearningMetricsCollector(
            metrics_dir=self.temp_dir
        )
        
        # Add sample data
        self._add_sample_data()
        
        # Create dashboard
        self.dashboard = RAGQueryDashboard(
            metrics_collector=self.query_metrics,
            learning_metrics=self.learning_metrics
        )
        
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
        
    def _add_sample_data(self):
        """Add sample data for dashboard testing."""
        # Add learning cycles
        for i in range(3):
            self.learning_metrics.record_learning_cycle({
                'timestamp': datetime.datetime.now() - datetime.timedelta(hours=3-i),
                'analyzed_queries': 10 + i*5,
                'optimization_rules': {f'rule_{j}': True for j in range(i+1)}
            })
        
        # Add parameter adaptations
        for i in range(2):
            self.learning_metrics.record_parameter_adaptation(
                param_name='max_depth',
                old_value=i+1,
                new_value=i+2
            )
        
        # Add query metrics
        for i in range(5):
            query_id = f"query_{i}"
            self.query_metrics.record_query_start(query_id, {"query_text": f"Test query {i}"})
            # Simulate processing time
            self.query_metrics.record_query_end(query_id, results=[f"Result {i}"])
    
    @patch('matplotlib.pyplot.savefig')
    def test_dashboard_with_learning_metrics(self, mock_savefig):
        """Test dashboard generation with learning metrics."""
        # Skip if dependencies are not available
        try:
            from jinja2 import Template
        except ImportError:
            self.skipTest("Jinja2 not available")
        
        # Generate dashboard with learning metrics
        dashboard_file = os.path.join(self.temp_dir, "dashboard.html")
        result = self.dashboard.generate_integrated_dashboard(
            output_file=dashboard_file,
            include_learning_metrics=True,
            interactive=False
        )
        
        # Verify dashboard file exists
        self.assertTrue(os.path.exists(dashboard_file))
        
        # Read content to verify learning metrics section exists
        with open(dashboard_file, 'r') as f:
            content = f.read()
            self.assertIn("Optimizer Learning Metrics", content)
            
        # Verify savefig was called for learning visualizations
        self.assertGreaterEqual(mock_savefig.call_count, 1)


if __name__ == "__main__":
    unittest.main()