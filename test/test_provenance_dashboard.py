"""
Tests for the provenance dashboard module.
"""

import os
import unittest
import tempfile
from unittest.mock import MagicMock, patch

# Define availability flags for optional dependencies
TEMPLATE_ENGINE_AVAILABLE = False
VISUALIZATION_LIBS_AVAILABLE = False

from ipfs_datasets_py.data_provenance import ProvenanceManager
from ipfs_datasets_py.provenance_dashboard import ProvenanceDashboard, setup_provenance_dashboard


class TestProvenanceDashboard(unittest.TestCase):
    """Test cases for the ProvenanceDashboard class."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a mock provenance manager
        self.provenance_manager = MagicMock(spec=ProvenanceManager)
        
        # Mock the graph attribute
        self.provenance_manager.graph = MagicMock()
        
        # Create mock lineage tracker and query visualizer
        self.lineage_tracker = MagicMock()
        self.query_visualizer = MagicMock()
        self.query_visualizer.metrics = MagicMock()
        
        # Create temporary directory for test outputs
        self.temp_dir = tempfile.mkdtemp()
        
        # Create dashboard instance
        self.dashboard = ProvenanceDashboard(
            provenance_manager=self.provenance_manager,
            lineage_tracker=self.lineage_tracker,
            query_visualizer=self.query_visualizer
        )
    
    def tearDown(self):
        """Clean up after tests."""
        # Remove temporary directory
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test dashboard initialization."""
        # Verify the dashboard is correctly initialized
        self.assertEqual(self.dashboard.provenance_manager, self.provenance_manager)
        self.assertEqual(self.dashboard.lineage_tracker, self.lineage_tracker)
        self.assertEqual(self.dashboard.query_visualizer, self.query_visualizer)
    
    @patch('ipfs_datasets_py.provenance_dashboard.VISUALIZATION_LIBS_AVAILABLE', True)
    def test_visualize_data_lineage(self):
        """Test data lineage visualization."""
        # Mock the provenance manager's visualize_provenance method
        self.provenance_manager.visualize_provenance.return_value = "mock_base64_image"
        
        # Call the method
        result = self.dashboard.visualize_data_lineage(
            data_ids=["data1", "data2"],
            return_base64=True
        )
        
        # Verify the method was called with correct arguments
        self.provenance_manager.visualize_provenance.assert_called_once_with(
            data_ids=["data1", "data2"],
            max_depth=5,
            include_parameters=True,
            show_timestamps=True,
            file_path=None,
            return_base64=True
        )
        
        # Verify the result
        self.assertEqual(result, "mock_base64_image")
    
    @patch('ipfs_datasets_py.provenance_dashboard.TEMPLATE_ENGINE_AVAILABLE', True)
    def test_generate_provenance_report_html(self):
        """Test HTML provenance report generation."""
        # Mock the provenance manager's methods
        self.provenance_manager.get_data_lineage.return_value = {
            "record_id": "record1",
            "record": {
                "record_type": "transformation",
                "description": "Test transform",
                "timestamp": 1617235200.0,
                "parameters": {"param1": "value1"}
            },
            "parents": []
        }
        
        # Mock visualization methods
        self.dashboard.visualize_data_lineage = MagicMock(return_value="mock_lineage_image")
        self.provenance_manager.generate_audit_report = MagicMock(return_value="Mock audit report")
        
        # Mock query metrics
        self.query_visualizer.metrics.get_performance_metrics.return_value = {
            "total_queries": 10,
            "avg_duration": 0.5,
            "success_rate": 0.9,
            "error_rate": 0.1,
            "performance_by_type": {}
        }
        
        # Generate report
        output_file = os.path.join(self.temp_dir, "report.html")
        result = self.dashboard.generate_provenance_report(
            data_ids=["data1"],
            format="html",
            output_file=output_file
        )
        
        # Verify output file was created
        self.assertEqual(result, output_file)
        self.assertTrue(os.path.exists(output_file))
        
        # Verify file contains expected content
        with open(output_file, 'r') as f:
            content = f.read()
            self.assertIn("<title>Data Provenance Report</title>", content)
            self.assertIn("data1", content)
    
    @patch('ipfs_datasets_py.provenance_dashboard.TEMPLATE_ENGINE_AVAILABLE', False)
    def test_generate_provenance_report_markdown_fallback(self):
        """Test markdown report generation when template engine is not available."""
        # Mock the provenance manager's methods
        self.provenance_manager.get_data_lineage.return_value = {
            "record_id": "record1",
            "record": {
                "record_type": "transformation",
                "description": "Test transform",
                "timestamp": 1617235200.0
            },
            "parents": []
        }
        
        # Generate report
        result = self.dashboard.generate_provenance_report(
            data_ids=["data1"],
            format="html"  # This should fall back to markdown
        )
        
        # Verify result is markdown
        self.assertIn("# Data Provenance Report", result)
        self.assertIn("data1", result)
    
    @patch('ipfs_datasets_py.provenance_dashboard.VISUALIZATION_LIBS_AVAILABLE', True)
    def test_create_integrated_dashboard(self):
        """Test integrated dashboard creation."""
        # Mock visualization methods
        self.dashboard.visualize_data_lineage = MagicMock()
        self.dashboard.visualize_cross_document_lineage = MagicMock()
        self.dashboard.generate_provenance_report = MagicMock()
        self.dashboard._get_recent_entities = MagicMock(return_value=["data1", "data2"])
        
        # Create dashboard
        dashboard_path = self.dashboard.create_integrated_dashboard(
            output_dir=self.temp_dir,
            data_ids=["data1", "data2"]
        )
        
        # Verify the provenance report was generated
        self.dashboard.generate_provenance_report.assert_called_once()
        
        # Verify integrated dashboard path
        expected_path = os.path.join(self.temp_dir, "provenance_dashboard.html")
        self.assertEqual(dashboard_path, expected_path)
    
    def test_setup_provenance_dashboard(self):
        """Test the setup_provenance_dashboard function."""
        # Create a mock provenance manager
        mock_provenance_manager = MagicMock(spec=ProvenanceManager)
        
        # Call the setup function
        dashboard = setup_provenance_dashboard(
            provenance_manager=mock_provenance_manager
        )
        
        # Verify the dashboard is created with the correct provenance manager
        self.assertIsInstance(dashboard, ProvenanceDashboard)
        self.assertEqual(dashboard.provenance_manager, mock_provenance_manager)


if __name__ == '__main__':
    unittest.main()
