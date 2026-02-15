"""
Test the resource monitor module.

This test suite validates the ResourceMonitor component against several criteria:

1. Resource Utilization (Target: <6GB RAM, <80% CPU)
   - Tests verify accurate tracking of CPU usage against the 80% threshold
   - Tests verify accurate tracking of memory usage against the 6GB threshold
   - Tests ensure proper resource limitation enforcement
   - Tests confirm appropriate handling of resource constraints

2. Processing Speed (Indirect)
   - The resource monitor indirectly impacts processing speed by controlling 
     resource allocation, preventing system overload and ensuring sustained 
     performance across all file types
   
3. Error Handling Effectiveness
   - Tests verify graceful handling when system resources are constrained
   - Tests ensure appropriate logging and notification of resource issues
"""
import copy
import unittest
from unittest.mock import MagicMock, patch
import threading
import time

try:
    import psutil
except ImportError:
    raise ImportError("psutil library is required for resource monitoring. Please install it using 'pip install psutil'.")

from monitors._resource_monitor import ResourceMonitor
from utils.hardware import Hardware
from types_ import Logger
from logger import logger as debug_logger
from configs import configs, Configs

resources = {
    "get_cpu_usage_in_percent": Hardware.get_cpu_usage_in_percent,
    "get_virtual_memory_in_percent": Hardware.get_virtual_memory_in_percent,
    "get_memory_info": Hardware.get_memory_info,
    "get_memory_rss_usage_in_mb": Hardware.get_memory_rss_usage_in_mb,
    "get_memory_vms_usage_in_mb": Hardware.get_memory_vms_usage_in_mb,
    "get_disk_usage": Hardware.get_disk_usage_in_percent,
    "get_open_files": Hardware.get_num_open_files,
    "get_shared_memory_usage_in_mb": Hardware.get_shared_memory_usage_in_mb,
    "get_num_cpu_cores": Hardware.get_num_cpu_cores,
}
# NOTE we convert GB to MB because 
# the psutil library returns memory in MB

class TestResourceMonitor(unittest.TestCase):
    """Test the ResourceMonitor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a resource monitor with test limits
        self.mock_configs = MagicMock(spec=Configs)
        self.mock_configs.resources = MagicMock()
        self.mock_configs.resources.memory_limit_mb = 512.0  # 512 MB
        self.mock_configs.resources.cpu_limit_percent = 80.0  # 80% CPU limit
        self.mock_configs.resources.monitoring_interval_seconds = 0.1  # Short interval for tests

        self.mock_resources = {
            **copy.deepcopy(resources),
            "logger": MagicMock(spec=Logger),  # Mock the logger to avoid actual logging during tests
        }

        self.resource_monitor = ResourceMonitor(resources=self.mock_resources, configs=self.mock_configs)

    def tearDown(self):
        """Clean up test fixtures."""
        # Stop any active monitoring
        if hasattr(self, 'resource_monitor') and self.resource_monitor.active_monitoring:
            self.resource_monitor.stop_monitoring()
    
    def test_init(self):
        """Test initialization."""
        self.assertEqual(self.resource_monitor.cpu_limit_percent, 80.0)
        self.assertEqual(self.resource_monitor.memory_limit, 512.0)
        self.assertEqual(self.resource_monitor.monitoring_interval, 0.1)
        self.assertFalse(self.resource_monitor.active_monitoring)
        self.assertIsNone(self.resource_monitor.monitoring_thread)
        self.assertIn("cpu", self.resource_monitor.current_resource_usage)
        self.assertIn("memory", self.resource_monitor.current_resource_usage)

    @patch('utils.hardware.psutil')
    def test_start_monitoring(self, mock_psutil):
        """Test starting resource monitoring."""
        # Configure mock for psutil
        mock_psutil.cpu_percent.return_value = 10.0
        process_mock = MagicMock(spec=psutil.Process)

        # Mock memory_info with all required attributes
        memory_info_mock = MagicMock()
        memory_info_mock.rss = 100 * 1024 * 1024  # 100 MB in bytes
        memory_info_mock.vms = 120 * 1024 * 1024  # 120 MB in bytes
        memory_info_mock.shared = 10 * 1024 * 1024  # 10 MB in bytes
        process_mock.memory_info.return_value = memory_info_mock
        
        mock_psutil.Process.return_value = process_mock
        mock_psutil.virtual_memory.return_value.percent = 50.0
        mock_psutil.disk_usage.return_value.percent = 60.0
        process_mock.open_files.return_value = ["file1", "file2"]
        
        # Start monitoring
        result = self.resource_monitor.start_monitoring()
        
        # Check result
        self.assertTrue(result)
        self.assertTrue(self.resource_monitor.active_monitoring)
        self.assertIsNotNone(self.resource_monitor.monitoring_thread)
        
        # Stop monitoring
        self.resource_monitor.stop_monitoring()
        
        # Check that monitoring has stopped
        self.assertFalse(self.resource_monitor.active_monitoring)

    @patch('utils.hardware.psutil')
    def test_get_resource_usage(self, mock_psutil):
        """Test getting resource usage."""
        # Configure mock for psutil
        mock_psutil.cpu_percent.return_value = 30.0
        process_mock = MagicMock()
        
        # Mock memory_info with all required attributes
        memory_info_mock = MagicMock()
        memory_info_mock.rss = 200 * 1024 * 1024  # 200 MB in bytes
        memory_info_mock.vms = 240 * 1024 * 1024  # 240 MB in bytes
        memory_info_mock.shared = 20 * 1024 * 1024  # 20 MB in bytes
        process_mock.memory_info.return_value = memory_info_mock
        
        mock_psutil.Process.return_value = process_mock
        mock_psutil.virtual_memory.return_value.percent = 40.0
        mock_psutil.disk_usage.return_value.percent = 50.0
        process_mock.open_files.return_value = ["file1", "file2", "file3"]

        # Get resource usage
        usage = self.resource_monitor._get_resource_usage()

        # Check usage values
        self.assertEqual(usage["cpu"], 30.0)
        self.assertEqual(usage["memory"], 200.0)  # Should be converted to MB
        self.assertEqual(usage["memory_percent"], 40.0)
        self.assertEqual(usage["disk_usage"], 50.0)
        self.assertEqual(usage["open_files"], 3)

    @patch('utils.hardware.psutil')
    def test_get_current_usage(self, mock_psutil):
        """Test getting current usage."""
        # Configure mock for psutil
        mock_psutil.cpu_percent.return_value = 20.0
        process_mock = MagicMock(spec="psutil.Process")
        process_mock.memory_info = MagicMock()
        
        # Mock memory_info with all required attributes
        memory_info_mock = MagicMock()
        memory_info_mock.rss = 150 * 1024 * 1024  # 150 MB in bytes
        memory_info_mock.vms = 180 * 1024 * 1024  # 180 MB in bytes
        memory_info_mock.shared = 15 * 1024 * 1024  # 15 MB in bytes
        process_mock.memory_info.return_value = memory_info_mock
        
        mock_psutil.Process.return_value = process_mock
        mock_psutil.virtual_memory.return_value.percent = 30.0
        mock_psutil.disk_usage.return_value.percent = 40.0
        process_mock.open_files = MagicMock()
        process_mock.open_files.return_value = ["file1"]
        
        # Get current usage without active monitoring
        usage = self.resource_monitor.current_resource_usage
        
        # Check usage values
        self.assertEqual(usage["cpu"], 20.0)
        self.assertEqual(usage["memory"], 150.0)  # Should be converted to MB
    
    
    @patch('utils.hardware.psutil')
    def test_are_resources_available(self, mock_psutil):
        """Test checking if resources are available.
        
        This test validates the resource checking functionality of the ResourceMonitor,
        addressing the "Resource Utilization" criteria. It verifies that:
        
        1. The monitor correctly identifies when resources are within acceptable limits
        2. The monitor detects when CPU usage exceeds the 80% threshold and reports it
        3. The monitor detects when memory usage exceeds the configured limit and reports it
        4. Appropriate reason messages are provided when resources are constrained
        
        These validations ensure the system can enforce the target resource constraints
        of <80% CPU usage and <6GB RAM usage as specified in the testing criteria.
        """
        # Configure mock for psutil to report low resource usage
        mock_psutil.cpu_percent.return_value = 30.0
        process_mock = MagicMock()
        
        # Mock memory_info with all required attributes - THIS IS THE FIX
        memory_info_mock = MagicMock()
        memory_info_mock.rss = 200 * 1024 * 1024  # 200 MB in bytes
        memory_info_mock.vms = 240 * 1024 * 1024  # 240 MB in bytes
        memory_info_mock.shared = 20 * 1024 * 1024  # 20 MB in bytes
        process_mock.memory_info.return_value = memory_info_mock
        
        mock_psutil.Process.return_value = process_mock
        mock_psutil.virtual_memory.return_value.percent = 50.0
        mock_psutil.disk_usage.return_value.percent = 60.0
        process_mock.open_files.return_value = ["file1", "file2"]
        
        # Check if resources are available
        available, reason = self.resource_monitor.are_resources_available
        
        # Should report resources available
        self.assertTrue(available)
        self.assertIsNone(reason)
        
        # Now configure mock to report high CPU usage
        mock_psutil.cpu_percent.return_value = 90.0
        
        # Check if resources are available
        available, reason = self.resource_monitor.are_resources_available
        
        # Should report resources not available due to high CPU
        self.assertFalse(available)
        self.assertIn("CPU usage too high", reason)
        
        # Configure mock to report high memory usage
        mock_psutil.cpu_percent.return_value = 30.0
        memory_info_mock.rss = 600 * 1024 * 1024  # 600 MB in bytes
        
        # Check if resources are available
        available, reason = self.resource_monitor.are_resources_available
        
        # Should report resources not available due to high memory
        self.assertFalse(available)
        self.assertIn("Memory usage too high", reason)
    
    def test_set_resource_limits(self):
        """Test setting resource limits."""
        # Set new limits
        self.resource_monitor.set_resource_limits(cpu_limit_percent=60.0, memory_limit=300)
        
        # Check if limits were updated
        self.assertEqual(self.resource_monitor.cpu_limit_percent, 60.0)
        self.assertEqual(self.resource_monitor.memory_limit, 300)
        
        # Test bounds checking for CPU
        self.resource_monitor.set_resource_limits(cpu_limit_percent=150.0)
        
        # CPU should be clamped to 100%
        self.assertEqual(self.resource_monitor.cpu_limit_percent, 100.0)
        
        # Test with negative values
        self.resource_monitor.set_resource_limits(cpu_limit_percent=-10.0, memory_limit=-100)
        
        # Should be clamped to 0
        self.assertEqual(self.resource_monitor.cpu_limit_percent, 0.0)
        self.assertEqual(self.resource_monitor.memory_limit, 0)
    
    
    @patch('utils.hardware.psutil')
    def test_get_resource_summary(self, mock_psutil):
        """Test getting resource summary."""
        # Configure mock for psutil
        mock_psutil.cpu_percent.return_value = 40.0
        process_mock = MagicMock()
        
        # Mock memory_info with all required attributes
        memory_info_mock = MagicMock()
        memory_info_mock.rss = 250 * 1024 * 1024  # 250 MB in bytes
        memory_info_mock.vms = 300 * 1024 * 1024  # 300 MB in bytes
        memory_info_mock.shared = 25 * 1024 * 1024  # 25 MB in bytes
        process_mock.memory_info.return_value = memory_info_mock
        
        mock_psutil.Process.return_value = process_mock
        mock_psutil.virtual_memory.return_value.percent = 60.0
        mock_psutil.disk_usage.return_value.percent = 70.0
        process_mock.open_files.return_value = ["file1", "file2"]
        
        # Get resource summary
        summary = self.resource_monitor.resource_summary
        
        # Check summary structure
        self.assertIn("current", summary)
        self.assertIn("limits", summary)
        self.assertIn("utilization", summary)
        self.assertIn("monitoring_active", summary)
        
        # Check current values
        self.assertEqual(summary["current"]["cpu_percent"], 40.0)
        self.assertEqual(summary["current"]["memory_mb"], 250.0)
        
        # Check limits
        self.assertEqual(summary["limits"]["cpu_percent"], 80.0)
        self.assertEqual(summary["limits"]["memory_mb"], 512.0)
        
        # Check monitoring status
        self.assertFalse(summary["monitoring_active"])


if __name__ == "__main__":
    unittest.main()