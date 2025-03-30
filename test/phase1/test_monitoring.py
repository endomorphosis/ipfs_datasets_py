"""
Tests for the Monitoring and Metrics Collection System.

This module tests the core functionality of the monitoring system, including:
- Configuration
- Logging
- Metrics collection
- Operation tracking
- Context management
- Timed operations
"""

import os
import time
import json
import tempfile
import unittest
import threading
from unittest import mock
from typing import Dict, List

import sys
import logging
import asyncio

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from ipfs_datasets_py.monitoring import (
    configure_monitoring, 
    MonitoringConfig, 
    LoggerConfig, 
    MetricsConfig,
    LogLevel,
    MetricType,
    get_logger, 
    get_metrics_registry,
    log_context,
    monitor_context,
    timed,
    MonitoringSystem
)


class TestMonitoring(unittest.TestCase):
    """Test case for the monitoring system."""
    
    def setUp(self):
        """Set up test case."""
        # Create a temporary directory for test files
        self.temp_dir = tempfile.mkdtemp(prefix="test_monitoring_")
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.metrics_file = os.path.join(self.temp_dir, "test_metrics.json")
        
        # Configure monitoring for tests
        self.config = MonitoringConfig(
            enabled=True,
            component_name="test_component",
            environment="test",
            version="0.0.1",
            logger=LoggerConfig(
                name="test_logger",
                level=LogLevel.DEBUG,
                format="%(levelname)s - %(message)s",
                file_path=self.log_file,
                console=False,
                include_context=True
            ),
            metrics=MetricsConfig(
                enabled=True,
                collect_interval=1,
                output_file=self.metrics_file,
                system_metrics=False,
                memory_metrics=False,
                network_metrics=False,
                global_labels={"test": "true"}
            )
        )
        
        # Initialize monitoring with our config
        configure_monitoring(self.config)
        
        # Get logger and metrics registry
        self.logger = get_logger()
        self.metrics = get_metrics_registry()
    
    def tearDown(self):
        """Clean up after test."""
        # Shutdown monitoring
        MonitoringSystem.get_instance().shutdown()
        
        # Remove temporary files
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_configuration(self):
        """Test monitoring configuration."""
        # Check that monitoring is enabled
        self.assertTrue(MonitoringSystem.get_instance().enabled)
        
        # Check component name
        self.assertEqual(self.config.component_name, "test_component")
        
        # Check logger configuration
        self.assertEqual(self.config.logger.name, "test_logger")
        self.assertEqual(self.config.logger.level, LogLevel.DEBUG)
        
        # Check metrics configuration
        self.assertTrue(self.config.metrics.enabled)
        self.assertEqual(self.config.metrics.collect_interval, 1)
    
    def test_logging(self):
        """Test logging functionality."""
        # Log a message
        self.logger.info("Test log message")
        
        # Verify log file exists
        self.assertTrue(os.path.exists(self.log_file))
        
        # Check log file content
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        self.assertIn("INFO - Test log message", log_content)
    
    def test_logging_with_context(self):
        """Test logging with context."""
        # Log with context
        with log_context(test_key="test_value", another_key=123):
            self.logger.info("Test log message with context")
        
        # Check log file content
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        # Verify context was included (depends on logger format)
        self.assertIn("INFO - Test log message with context", log_content)
    
    def test_metrics_counter(self):
        """Test counter metrics."""
        # Record counter metrics
        self.metrics.increment("test_counter", 1, labels={"label1": "value1"})
        self.metrics.increment("test_counter", 2, labels={"label1": "value1"})
        
        # Check metrics in registry
        metrics_dict = self.metrics.metrics
        self.assertIn("test_counter", metrics_dict)
        
        # Get counter value using labels as key
        labels_key = json.dumps([["label1", "value1"]])
        counter = metrics_dict["test_counter"][labels_key]
        
        # Check counter type and value
        self.assertEqual(counter.type, MetricType.COUNTER)
        self.assertEqual(counter.value, 3)
    
    def test_metrics_gauge(self):
        """Test gauge metrics."""
        # Record gauge metrics
        self.metrics.gauge("test_gauge", 10, labels={"label1": "value1"})
        
        # Update the gauge
        self.metrics.gauge("test_gauge", 20, labels={"label1": "value1"})
        
        # Check metrics in registry
        metrics_dict = self.metrics.metrics
        self.assertIn("test_gauge", metrics_dict)
        
        # Get gauge value
        labels_key = json.dumps([["label1", "value1"]])
        gauge = metrics_dict["test_gauge"][labels_key]
        
        # Check gauge type and value
        self.assertEqual(gauge.type, MetricType.GAUGE)
        self.assertEqual(gauge.value, 20)
    
    def test_metrics_timer(self):
        """Test timer metrics."""
        # Record timer metric
        duration = 123.45
        self.metrics.timer("test_timer", duration, labels={"label1": "value1"})
        
        # Check metrics in registry
        metrics_dict = self.metrics.metrics
        self.assertIn("test_timer", metrics_dict)
        
        # Get timer value
        labels_key = json.dumps([["label1", "value1"]])
        timer = metrics_dict["test_timer"][labels_key]
        
        # Check timer type and value
        self.assertEqual(timer.type, MetricType.TIMER)
        self.assertEqual(timer.value, duration)
    
    def test_metrics_event(self):
        """Test event metrics."""
        # Record event metric
        event_data = {"key1": "value1", "key2": 123}
        self.metrics.event("test_event", event_data, labels={"label1": "value1"})
        
        # Check metrics in registry
        metrics_dict = self.metrics.metrics
        self.assertIn("test_event", metrics_dict)
        
        # Get event value
        labels_key = json.dumps([["label1", "value1"]])
        event = metrics_dict["test_event"][labels_key]
        
        # Check event type and value
        self.assertEqual(event.type, MetricType.EVENT)
        self.assertEqual(event.value, event_data)
    
    def test_operation_tracking(self):
        """Test operation tracking."""
        # Start operation
        operation = self.metrics.start_operation("test_operation", {"label1": "value1"})
        
        # Check operation is in registry
        self.assertIn(operation.operation_id, self.metrics.operations)
        
        # Complete operation
        self.metrics.complete_operation(operation, success=True)
        
        # Check operation status
        self.assertEqual(operation.status, "success")
        self.assertTrue(operation.success)
        self.assertIsNotNone(operation.duration_ms)
    
    def test_monitor_context(self):
        """Test monitor_context context manager."""
        # Use monitor_context
        with monitor_context(operation_name="test_context", test_param="test_value") as op:
            # Check operation started
            self.assertIn(op.operation_id, self.metrics.operations)
            self.assertEqual(op.operation_type, "test_context")
            self.assertEqual(op.labels["test_param"], "test_value")
            
            # Do something inside context
            time.sleep(0.1)
        
        # Check operation completed successfully
        self.assertTrue(op.success)
        self.assertEqual(op.status, "success")
        self.assertGreaterEqual(op.duration_ms, 100)  # At least 100ms
    
    def test_timed_decorator(self):
        """Test timed decorator."""
        # Create a timed function
        @timed(metric_name="test_timed_function", registry=self.metrics)
        def test_function(a, b):
            time.sleep(0.1)
            return a + b
        
        # Call the function
        result = test_function(5, 10)
        
        # Check function result
        self.assertEqual(result, 15)
        
        # Check metrics
        # The operation name should match the metric_name
        operations = list(self.metrics.operations.values())
        timed_ops = [op for op in operations if op.operation_type == "test_timed_function"]
        
        self.assertGreaterEqual(len(timed_ops), 1)
        op = timed_ops[0]
        
        # Check operation was completed successfully
        self.assertTrue(op.success)
        self.assertGreaterEqual(op.duration_ms, 100)  # At least 100ms
    
    def test_async_timed_decorator(self):
        """Test timed decorator with async functions."""
        # Create a timed async function
        @timed(metric_name="test_async_function", registry=self.metrics)
        async def test_async_function(a, b):
            await asyncio.sleep(0.1)
            return a + b
        
        # Call the function
        result = asyncio.run(test_async_function(5, 10))
        
        # Check function result
        self.assertEqual(result, 15)
        
        # Check metrics
        operations = list(self.metrics.operations.values())
        timed_ops = [op for op in operations if op.operation_type == "test_async_function"]
        
        self.assertGreaterEqual(len(timed_ops), 1)
        op = timed_ops[0]
        
        # Check operation was completed successfully
        self.assertTrue(op.success)
        self.assertGreaterEqual(op.duration_ms, 100)  # At least 100ms
    
    def test_metrics_writing(self):
        """Test writing metrics to a file."""
        # Record some metrics
        self.metrics.increment("test_write_counter", 5)
        self.metrics.gauge("test_write_gauge", 10)
        
        # Start and complete an operation
        op = self.metrics.start_operation("test_write_operation")
        self.metrics.complete_operation(op, success=True)
        
        # Write metrics to file
        result = self.metrics.write_metrics()
        self.assertTrue(result)
        
        # Check file exists
        self.assertTrue(os.path.exists(self.metrics_file))
        
        # Read and parse the file
        with open(self.metrics_file, 'r') as f:
            metrics_data = json.load(f)
        
        # Check structure
        self.assertIn("metrics", metrics_data)
        self.assertIn("operations", metrics_data)
        self.assertIn("timestamp", metrics_data)
        
        # Check metrics content
        metrics = metrics_data["metrics"]
        self.assertIn("test_write_counter", metrics)
        self.assertIn("test_write_gauge", metrics)
        
        # Check counter value
        counter_value = metrics["test_write_counter"][0]["value"]
        self.assertEqual(counter_value, 5)
        
        # Check gauge value
        gauge_value = metrics["test_write_gauge"][0]["value"]
        self.assertEqual(gauge_value, 10)
        
        # Check operations
        operations = metrics_data["operations"]
        self.assertGreaterEqual(len(operations), 1)
        self.assertEqual(operations[0]["operation_type"], "test_write_operation")
        self.assertEqual(operations[0]["status"], "success")
    
    def test_error_handling(self):
        """Test error handling in monitoring."""
        # Use monitor_context with an error
        try:
            with monitor_context(operation_name="test_error"):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Check operations in registry
        operations = list(self.metrics.operations.values())
        error_ops = [op for op in operations if op.operation_type == "test_error"]
        
        self.assertGreaterEqual(len(error_ops), 1)
        op = error_ops[0]
        
        # Check operation failed correctly
        self.assertFalse(op.success)
        self.assertEqual(op.status, "error")
        self.assertEqual(op.error, "Test error")
    
    def test_disabled_monitoring(self):
        """Test behavior when monitoring is disabled."""
        # Disable monitoring
        config = MonitoringConfig(enabled=False)
        configure_monitoring(config)
        
        # Get logger and metrics
        logger = get_logger()
        metrics = get_metrics_registry()
        
        # Log a message (should be a no-op)
        logger.info("This should not be logged")
        
        # Record a metric (should be a no-op)
        metrics.increment("disabled_counter")
        
        # Check that the counter was not recorded
        self.assertNotIn("disabled_counter", metrics.metrics)
        
        # Check that the log file wasn't changed
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r') as f:
                log_content = f.read()
            self.assertNotIn("This should not be logged", log_content)
    
    def test_multiple_loggers(self):
        """Test creating multiple loggers."""
        # Create different logger instances
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        # Log messages
        logger1.info("Test message from module1")
        logger2.info("Test message from module2")
        
        # Verify logs
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        self.assertIn("Test message from module1", log_content)
        self.assertIn("Test message from module2", log_content)
    
    def test_custom_labels(self):
        """Test metrics with custom labels."""
        # Add metrics with different labels
        self.metrics.increment("label_test", labels={"service": "api", "method": "GET"})
        self.metrics.increment("label_test", labels={"service": "api", "method": "POST"})
        self.metrics.increment("label_test", labels={"service": "db", "operation": "query"})
        
        # Check metrics were recorded separately
        metrics_dict = self.metrics.metrics
        self.assertIn("label_test", metrics_dict)
        
        # Should have 3 different instances
        self.assertEqual(len(metrics_dict["label_test"]), 3)
    
    def test_exception_logging(self):
        """Test exception logging."""
        try:
            # Raise an exception
            raise ValueError("Test exception")
        except Exception:
            # Log the exception
            MonitoringSystem.get_instance().log_exception(
                exc_info=sys.exc_info(),
                context="test_context"
            )
        
        # Check log file
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        self.assertIn("ERROR - Exception: ValueError: Test exception", log_content)
        self.assertIn("ValueError: Test exception", log_content)


if __name__ == "__main__":
    unittest.main()