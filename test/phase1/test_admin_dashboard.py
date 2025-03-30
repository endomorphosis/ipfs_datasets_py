"""
Tests for the Admin Dashboard.

This module tests the core functionality of the admin dashboard, including:
- Configuration
- Dashboard initialization
- Server startup and shutdown
- API endpoints
"""

import os
import sys
import json
import time
import unittest
import tempfile
import threading
from unittest import mock
from typing import Dict, List, Any

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Try to import Flask for testing
try:
    import flask
    from flask import Flask
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

from ipfs_datasets_py.monitoring import (
    configure_monitoring,
    MonitoringConfig,
    LoggerConfig,
    MetricsConfig,
    LogLevel
)

from ipfs_datasets_py.admin_dashboard import (
    AdminDashboard,
    DashboardConfig,
    start_dashboard,
    stop_dashboard,
    get_dashboard_status
)


@unittest.skipIf(not FLASK_AVAILABLE, "Flask is not available")
class TestAdminDashboard(unittest.TestCase):
    """Test case for the admin dashboard."""
    
    def setUp(self):
        """Set up test case."""
        # Create a temporary directory for test files
        self.temp_dir = tempfile.mkdtemp(prefix="test_admin_dashboard_")
        self.log_file = os.path.join(self.temp_dir, "test.log")
        
        # Configure monitoring for tests
        self.monitoring_config = MonitoringConfig(
            enabled=True,
            component_name="test_component",
            environment="test",
            version="0.0.1",
            logger=LoggerConfig(
                name="test_logger",
                level=LogLevel.DEBUG,
                format="%(levelname)s - %(message)s",
                file_path=self.log_file,
                console=False
            ),
            metrics=MetricsConfig(
                enabled=True,
                system_metrics=False,
                memory_metrics=False,
                network_metrics=False
            )
        )
        
        # Configure the dashboard
        self.dashboard_config = DashboardConfig(
            enabled=True,
            host="127.0.0.1",
            port=12345,  # Use a non-standard port for testing
            refresh_interval=1,
            open_browser=False,
            data_dir=self.temp_dir,
            monitoring_config=self.monitoring_config
        )
        
        # Initialize monitoring
        configure_monitoring(self.monitoring_config)
    
    def tearDown(self):
        """Clean up after test."""
        # Stop any running dashboard
        stop_dashboard()
        
        # Remove temporary files
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_dashboard_initialization(self):
        """Test dashboard initialization."""
        # Initialize dashboard
        dashboard = AdminDashboard.initialize(self.dashboard_config)
        
        # Check that it's initialized
        self.assertTrue(dashboard.initialized)
        self.assertEqual(dashboard.config.port, 12345)
        self.assertEqual(dashboard.config.host, "127.0.0.1")
        
        # Check that Flask app was created
        self.assertIsNotNone(dashboard.app)
        self.assertIsInstance(dashboard.app, Flask)
    
    def test_start_stop_dashboard(self):
        """Test starting and stopping the dashboard."""
        # Start dashboard
        dashboard = start_dashboard(self.dashboard_config)
        
        # Check that it's running
        self.assertTrue(dashboard.running)
        self.assertIsNotNone(dashboard.server_thread)
        self.assertTrue(dashboard.server_thread.is_alive())
        
        # Small delay to let the server start
        time.sleep(0.5)
        
        # Check status
        status = get_dashboard_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["port"], 12345)
        
        # Stop dashboard
        result = stop_dashboard()
        self.assertTrue(result)
        
        # Check that it's stopped
        self.assertFalse(dashboard.running)
        
        # Give thread time to exit
        time.sleep(0.5)
        self.assertFalse(dashboard.server_thread.is_alive())
    
    def test_create_templates_and_static(self):
        """Test creating template and static files."""
        # Initialize dashboard
        dashboard = AdminDashboard.initialize(self.dashboard_config)
        
        # Check that template directory exists
        template_dir = os.path.join(os.path.dirname(os.path.dirname(self.temp_dir)), 
                                  "ipfs_datasets_py", "templates", "admin")
        self.assertTrue(os.path.exists(template_dir))
        
        # Check that the index.html template exists
        index_path = os.path.join(template_dir, "index.html")
        self.assertTrue(os.path.exists(index_path))
        
        # Check that the static directory exists
        static_dir = os.path.join(os.path.dirname(os.path.dirname(self.temp_dir)), 
                                "ipfs_datasets_py", "static", "admin")
        self.assertTrue(os.path.exists(static_dir))
        
        # Check that CSS and JS directories exist
        css_dir = os.path.join(static_dir, "css")
        js_dir = os.path.join(static_dir, "js")
        self.assertTrue(os.path.exists(css_dir))
        self.assertTrue(os.path.exists(js_dir))
        
        # Check that dashboard.css exists
        css_path = os.path.join(css_dir, "dashboard.css")
        self.assertTrue(os.path.exists(css_path))
        
        # Check that dashboard.js exists
        js_path = os.path.join(js_dir, "dashboard.js")
        self.assertTrue(os.path.exists(js_path))
    
    def test_dashboard_routes(self):
        """Test dashboard routes using Flask's test client."""
        # Create and mock the test client
        dashboard = AdminDashboard.initialize(self.dashboard_config)
        
        # Mock the server thread to avoid actually starting it
        with mock.patch.object(threading.Thread, 'start'):
            # Create routes
            dashboard._setup_routes()
            
            # Create a test client
            client = dashboard.app.test_client()
            
            # Test the index route
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'IPFS Datasets Admin Dashboard', response.data)
            
            # Test the API routes
            api_routes = ['/api/metrics', '/api/operations', '/api/logs', '/api/system']
            for route in api_routes:
                response = client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.is_json)
    
    def test_system_stats(self):
        """Test system statistics collection."""
        # Initialize dashboard
        dashboard = AdminDashboard.initialize(self.dashboard_config)
        
        # Get system stats
        stats = dashboard._get_system_stats()
        
        # Check that we got some stats
        self.assertIn("cpu_percent", stats)
        self.assertIn("memory_used", stats)
        self.assertIn("memory_total", stats)
        self.assertIn("disk_used", stats)
        self.assertIn("disk_total", stats)
    
    @unittest.skipIf(True, "Skipping authentication test for now")
    def test_authentication(self):
        """Test authentication when required."""
        # Configure dashboard with authentication
        config = self.dashboard_config
        config.require_auth = True
        config.username = "testuser"
        config.password = "testpass"
        
        # Initialize dashboard
        dashboard = AdminDashboard.initialize(config)
        
        # Mock the server thread to avoid actually starting it
        with mock.patch.object(threading.Thread, 'start'):
            # Create routes
            dashboard._setup_routes()
            
            # Create a test client
            client = dashboard.app.test_client()
            
            # Test the login route - GET
            response = client.get('/login')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Please sign in', response.data)
            
            # Test the login route - POST with wrong credentials
            response = client.post('/login', data={
                'username': 'wronguser',
                'password': 'wrongpass'
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Invalid credentials', response.data)
            
            # Test the login route - POST with correct credentials
            response = client.post('/login', data={
                'username': 'testuser',
                'password': 'testpass'
            })
            self.assertEqual(response.status_code, 302)  # Should redirect to index
            
            # In a real implementation, we'd check session cookies, etc.
    
    def test_get_recent_logs(self):
        """Test retrieving recent logs."""
        # Create a log file with some sample data
        with open(self.log_file, 'w') as f:
            f.write("2023-01-01 12:00:00 - test_logger - INFO - Test log 1\n")
            f.write("2023-01-01 12:01:00 - test_logger - DEBUG - Test log 2\n")
            f.write("2023-01-01 12:02:00 - test_logger - WARNING - Test log 3\n")
            f.write("2023-01-01 12:03:00 - test_logger - ERROR - Test log 4\n")
        
        # Initialize dashboard
        dashboard = AdminDashboard.initialize(self.dashboard_config)
        
        # Get recent logs
        logs = dashboard._get_recent_logs()
        
        # Check that we got some logs
        self.assertEqual(len(logs), 4)
        
        # Check log structure
        self.assertIn("timestamp", logs[0])
        self.assertIn("name", logs[0])
        self.assertIn("level", logs[0])
        self.assertIn("message", logs[0])
        
        # Check log content
        error_log = [log for log in logs if log["level"] == "ERROR"][0]
        self.assertEqual(error_log["message"], "Test log 4")


if __name__ == "__main__":
    unittest.main()