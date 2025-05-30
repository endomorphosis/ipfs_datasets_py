"""
Test suite for the Audit-Provenance Dashboard module.

This test suite verifies the functionality of the integrated audit provenance
dashboard, ensuring that it properly combines audit visualization, data lineage tracking,
and the unified dashboard features.
"""

import os
import time
import unittest
import tempfile
import random
import shutil
from unittest import mock

# Import the modules to test
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditLevel, AuditCategory
from ipfs_datasets_py.data_provenance import ProvenanceManager
from ipfs_datasets_py.audit.audit_provenance_integration import AuditProvenanceDashboard, setup_audit_provenance_dashboard
from ipfs_datasets_py.provenance_dashboard import ProvenanceDashboard


class TestAuditProvenanceDashboard(unittest.TestCase):
    """Test cases for the Audit-Provenance Dashboard."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create temporary directory for output files
        self.temp_dir = tempfile.mkdtemp()

        # Initialize components
        self.audit_metrics = AuditMetricsAggregator()
        self.audit_logger = AuditLogger()
        self.audit_logger.add_handler(lambda event: self.audit_metrics.process_event(event))
        self.provenance_manager = ProvenanceManager()

        # Generate sample data
        self.data_ids = self.generate_sample_data()
        self.generate_sample_audit_events()

        # Create dashboard
        self.dashboard = AuditProvenanceDashboard(
            audit_metrics=self.audit_metrics,
            provenance_dashboard=ProvenanceDashboard(provenance_manager=self.provenance_manager),
            audit_logger=self.audit_logger
        )

    def tearDown(self):
        """Clean up test environment after each test."""
        # Remove temporary directory
        shutil.rmtree(self.temp_dir)

    def generate_sample_data(self):
        """Generate sample provenance data for testing."""
        source_id = "test_source"
        self.provenance_manager.record_source(
            entity_id=source_id,
            source_uri="file:///test/data.csv",
            description="Test data source"
        )

        transform_id = "test_transform"
        self.provenance_manager.record_transformation(
            entity_id=transform_id,
            input_entity_ids=[source_id],
            description="Test transformation",
            duration_ms=100
        )

        return [source_id, transform_id]

    def generate_sample_audit_events(self):
        """Generate sample audit events for testing."""
        # Create a few audit events
        timestamp = time.time()

        for i in range(10):
            event = AuditEvent(
                timestamp=timestamp - (600 - i*60),  # Events over past 10 minutes
                category=AuditCategory.DATA_ACCESS,
                level=AuditLevel.INFO,
                action="read",
                status="success",
                user="test_user",
                resource_id=self.data_ids[0] if i % 2 == 0 else self.data_ids[1],
                resource_type="dataset",
                client_ip="127.0.0.1",
                details={"app": "test_app"}
            )
            self.audit_logger.log_event(event)

    def test_initialization(self):
        """Test proper initialization of the dashboard."""
        # Verify dashboard components are properly set up
        self.assertIsNotNone(self.dashboard.audit_metrics)
        self.assertIsNotNone(self.dashboard.provenance_dashboard)
        self.assertIsNotNone(self.dashboard.audit_logger)
        self.assertIsNotNone(self.dashboard.audit_visualizer)

        # Check that audit metrics were stored in provenance dashboard
        self.assertEqual(self.dashboard.audit_metrics,
                         self.dashboard.provenance_dashboard.audit_metrics)

    @mock.patch('matplotlib.pyplot.savefig')
    def test_create_provenance_audit_timeline(self, mock_savefig):
        """Test creation of the integrated timeline visualization."""
        # Mock plt.savefig to avoid actually saving files
        mock_savefig.return_value = None

        # Call the method
        output_file = os.path.join(self.temp_dir, "timeline.png")
        result = self.dashboard.create_provenance_audit_timeline(
            data_ids=self.data_ids,
            hours=1,
            output_file=output_file
        )

        # Check result
        self.assertEqual(result, output_file)
        mock_savefig.assert_called_once()

    @mock.patch('matplotlib.pyplot.savefig')
    def test_create_provenance_metrics_comparison(self, mock_savefig):
        """Test creation of metrics comparison visualization."""
        # Mock plt.savefig to avoid actually saving files
        mock_savefig.return_value = None

        # Call the method
        output_file = os.path.join(self.temp_dir, "comparison.png")
        result = self.dashboard.create_provenance_metrics_comparison(
            metrics_type='overview',
            output_file=output_file
        )

        # Check result
        self.assertEqual(result, output_file)
        mock_savefig.assert_called_once()

    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.AuditVisualizer.plot_events_by_category')
    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.AuditVisualizer.plot_events_by_level')
    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.AuditVisualizer.plot_event_timeline')
    @mock.patch('ipfs_datasets_py.provenance_dashboard.ProvenanceDashboard.visualize_data_lineage')
    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.AuditProvenanceDashboard.create_provenance_audit_timeline')
    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.AuditProvenanceDashboard.create_provenance_metrics_comparison')
    @mock.patch('ipfs_datasets_py.audit.audit_provenance_integration.Template')
    def test_create_integrated_dashboard(self, mock_template, *mocks):
        """Test creation of the full integrated dashboard."""
        # Mock Template behavior
        mock_template_instance = mock.MagicMock()
        mock_template.return_value = mock_template_instance
        mock_template_instance.render.return_value = "<html>Dashboard</html>"

        # Call the method
        dashboard_path = os.path.join(self.temp_dir, "dashboard.html")
        result = self.dashboard.create_integrated_dashboard(
            output_dir=self.temp_dir,
            data_ids=self.data_ids,
            dashboard_name="dashboard.html"
        )

        # Check result
        self.assertEqual(result, dashboard_path)
        mock_template_instance.render.assert_called_once()

        # Verify file creation with mocked content
        with open(dashboard_path, 'r') as f:
            content = f.read()
            self.assertEqual(content, "<html>Dashboard</html>")

    def test_get_provenance_events(self):
        """Test extraction of provenance events from records."""
        events = self.dashboard._get_provenance_events(self.data_ids)

        # Check that events were extracted
        self.assertEqual(len(events), 2)  # Two records from our setup

        # Verify event data
        event_types = [event['type'] for event in events]
        self.assertIn('source', event_types)
        self.assertIn('transformation', event_types)

    def test_get_audit_events_for_entities(self):
        """Test extraction of audit events related to entities."""
        events = self.dashboard._get_audit_events_for_entities(self.data_ids, hours=1)

        # Check that events were extracted
        self.assertGreater(len(events), 0)

        # Verify event data
        for event in events:
            self.assertEqual(event['category'], 'DATA_ACCESS')
            self.assertEqual(event['action'], 'read')

    def test_get_provenance_metrics(self):
        """Test extraction of provenance metrics."""
        metrics = self.dashboard._get_provenance_metrics()

        # Check that metrics were extracted
        self.assertEqual(metrics['total_records'], 2)  # Two records from our setup
        self.assertEqual(metrics['total_entities'], 2)  # Two entities from our setup

        # Verify metrics data
        self.assertIn('source', metrics['by_type'])
        self.assertIn('transformation', metrics['by_type'])

    def test_factory_function(self):
        """Test the factory function that sets up the dashboard."""
        # Call factory function
        dashboard = setup_audit_provenance_dashboard(
            audit_logger=self.audit_logger,
            provenance_manager=self.provenance_manager
        )

        # Verify the dashboard is properly configured
        self.assertIsInstance(dashboard, AuditProvenanceDashboard)
        self.assertIsNotNone(dashboard.audit_metrics)
        self.assertIsNotNone(dashboard.provenance_dashboard)
        self.assertEqual(dashboard.audit_logger, self.audit_logger)
        self.assertEqual(dashboard.provenance_dashboard.provenance_manager, self.provenance_manager)


if __name__ == '__main__':
    unittest.main()
