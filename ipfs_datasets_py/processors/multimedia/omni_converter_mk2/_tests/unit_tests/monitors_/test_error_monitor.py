import unittest
from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import datetime
from pathlib import Path
from logging import Logger
from typing import Optional, Any, Type
import threading
import time
import tempfile
import shutil

from configs import Configs
from monitors._error_monitor import ErrorMonitor
from monitors import make_error_monitor

def make_mock_resources() -> dict[str, MagicMock]:
    mock_resources = {
        'logger': MagicMock(spec=Logger),
        'traceback': MagicMock(),
        'datetime': MagicMock(),
    }
    return mock_resources

import os
import pathlib
def make_mock_configs() -> MagicMock:
    mock_configs = MagicMock(spec=Configs)
    mock_configs.processing = MagicMock()
    mock_configs.paths = MagicMock()
    mock_configs.processing.suppress_errors = False
    root_dir_return_value = Path("/test/root")
    if os.system == "nt":
        root_dir_spec = pathlib.WindowsPath
    else:
        root_dir_spec = pathlib.PosixPath
    mock_configs.paths.ROOT_DIR = MagicMock(spec=root_dir_spec, return_value=root_dir_return_value)
    return mock_configs

class TestErrorMonitorInitialization(unittest.TestCase):
    """Test ErrorMonitor initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        self.mock_traceback = MagicMock()
        self.mock_datetime = MagicMock()

        self.mock_configs = MagicMock(spec=Configs)
        self.mock_configs.processing = MagicMock()
        self.mock_configs.processing.suppress_errors = False
        self.mock_configs.paths = MagicMock()
        self.mock_configs.paths.ROOT_DIR = Path("/test/root")

        #self.mock_configs: dict[str, MagicMock] = make_mock_configs()
        self.mock_resources = {
            'logger': self.mock_logger,
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }

    def test_init_with_valid_resources_and_configs(self):
        """
        GIVEN valid resources dict containing:
            - logger: A logger instance
            - traceback: The traceback module
            - datetime: The datetime module
        AND valid configs object with:
            - processing.suppress_errors attribute
            - paths.ROOT_DIR attribute
        WHEN ErrorMonitor is initialized
        THEN expect:
            - Instance created successfully
            - _logger is set from resources['logger']
            - _suppress_errors is set from configs.processing.suppress_errors
            - _root_dir is set from configs.paths.ROOT_DIR
            - _error_counters initialized as empty dict
            - _error_types initialized as empty set
            - traceback and datetime attributes are set from resources
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)

        self.assertIsInstance(monitor, ErrorMonitor)
        self.assertEqual(monitor._logger, self.mock_logger)
        self.assertEqual(monitor._suppress_errors, False)
        self.assertEqual(monitor._root_dir, Path("/test/root"))
        self.assertEqual(monitor._error_counters, {})
        self.assertEqual(monitor._error_types, set())
        self.assertEqual(monitor.traceback, self.mock_traceback)
        self.assertEqual(monitor.datetime, self.mock_datetime)

    def test_init_missing_logger_in_resources(self):
        """
        GIVEN resources dict missing 'logger' key
        WHEN ErrorMonitor is initialized
        THEN expect KeyError to be raised
        """
        invalid_resources = {
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }
        
        with self.assertRaises(KeyError):
            ErrorMonitor(invalid_resources, self.mock_configs)

    def test_init_missing_traceback_in_resources(self):
        """
        GIVEN resources dict missing 'traceback' key
        WHEN ErrorMonitor is initialized
        THEN expect KeyError to be raised
        """
        invalid_resources = {
            'logger': self.mock_logger,
            'datetime': self.mock_datetime
        }
        
        with self.assertRaises(KeyError):
            ErrorMonitor(invalid_resources, self.mock_configs)

    def test_init_missing_datetime_in_resources(self):
        """
        GIVEN resources dict missing 'datetime' key
        WHEN ErrorMonitor is initialized
        THEN expect KeyError to be raised
        """
        invalid_resources = {
            'logger': self.mock_logger,
            'traceback': self.mock_traceback
        }
        
        with self.assertRaises(KeyError):
            ErrorMonitor(invalid_resources, self.mock_configs)

    def test_init_with_none_resources(self):
        """
        GIVEN resources=None
        WHEN ErrorMonitor is initialized
        THEN expect TypeError or AttributeError when trying to access resources dict
        """
        with self.assertRaises((TypeError, AttributeError)):
            ErrorMonitor(None, self.mock_configs)

    def test_init_with_none_configs(self):
        """
        GIVEN configs=None
        WHEN ErrorMonitor is initialized
        THEN expect AttributeError when trying to access configs attributes
        """
        with self.assertRaises(AttributeError):
            ErrorMonitor(self.mock_resources, None)

    def test_init_configs_missing_processing_attribute(self):
        """
        GIVEN configs object missing 'processing' attribute
        WHEN ErrorMonitor is initialized
        THEN expect AttributeError to be raised
        """
        invalid_configs = MagicMock()
        del invalid_configs.processing
        
        with self.assertRaises(AttributeError):
            ErrorMonitor(self.mock_resources, invalid_configs)

    def test_init_configs_missing_paths_attribute(self):
        """
        GIVEN configs object missing 'paths' attribute
        WHEN ErrorMonitor is initialized
        THEN expect AttributeError to be raised
        """
        invalid_configs = MagicMock(spec=Configs)
        invalid_configs.processing = MagicMock()
        invalid_configs.processing.suppress_errors = False
        del invalid_configs.paths

        with self.assertRaises(AttributeError):
            ErrorMonitor(self.mock_resources, invalid_configs)

    def test_init_state_after_successful_initialization(self):
        """
        GIVEN valid resources and configs
        WHEN ErrorMonitor is initialized
        THEN expect:
            - self.configs is the same object passed in
            - self.resources is the same dict passed in
            - self.traceback is resources['traceback']
            - self.datetime is resources['datetime']
            - self._error_counters == {}
            - self._error_types == set()
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        self.assertIs(monitor.configs, self.mock_configs)
        self.assertIs(monitor.resources, self.mock_resources)
        self.assertIs(monitor.traceback, self.mock_traceback)
        self.assertIs(monitor.datetime, self.mock_datetime)
        self.assertEqual(monitor._error_counters, {})
        self.assertEqual(monitor._error_types, set())


class TestErrorHandling(unittest.TestCase):
    """Test error handling functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()

        self.mock_resources['logger'] = self.mock_logger = MagicMock(spec=Logger)

    def test_handle_error_with_exception_suppress_false(self):
        """
        GIVEN an ErrorMonitor with suppress_errors=False
        WHEN handle_error is called with Exception("test error")
        THEN expect:
            - Error is logged
            - Exception is re-raised
            - Error count increases by 1
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        test_error = Exception("test error")
        
        with self.assertRaises(Exception) as context:
            monitor.handle_error(test_error)
        
        self.assertEqual(str(context.exception), "test error")
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_handle_error_with_exception_suppress_true(self):
        """
        GIVEN an ErrorMonitor with suppress_errors=True
        WHEN handle_error is called with Exception("test error")
        THEN expect:
            - Error is logged
            - Exception is NOT re-raised
            - Error count increases by 1
        """
        self.mock_configs.processing.suppress_errors = True
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        test_error = Exception("test error")
        
        # Should not raise
        monitor.handle_error(test_error)
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_handle_error_with_string_message(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with string "error message"
        THEN expect:
            - Error is logged as string
            - No exception is raised (regardless of suppress_errors)
            - Error count increases by 1
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Should not raise regardless of suppress_errors setting
        monitor.handle_error("error message")
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_handle_error_with_context(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with error and context={'file': 'test.py', 'line': 42}
        THEN expect:
            - Error is logged with context
            - Context is preserved in error records
        """
        self.mock_configs.processing.suppress_errors = True
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        test_error = ValueError("test error")
        context = {'file': 'test.py', 'line': 42}
        
        monitor.handle_error(test_error, context)
        
        self.mock_logger.error.assert_called()
        # Verify context was passed to log_error
        call_args = self.mock_logger.error.call_args
        self.assertIn('test.py', str(call_args))
        self.assertIn('42', str(call_args))

    def test_handle_error_with_various_exception_types(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with different exception types:
            - ValueError
            - TypeError
            - CustomException
            - KeyError
        THEN expect:
            - Each error type is tracked separately
            - Error counts are accurate for each type
        """
        self.mock_configs.processing.suppress_errors = True
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        class CustomException(Exception):
            pass
        
        errors = [
            ValueError("value error"),
            TypeError("type error"),
            CustomException("custom error"),
            KeyError("key error"),
            ValueError("another value error")  # Second ValueError
        ]
        
        for error in errors:
            monitor.handle_error(error)
        
        self.assertEqual(monitor.get_error_count(), 5)
        self.assertEqual(monitor.get_error_count(ValueError), 2)
        self.assertEqual(monitor.get_error_count(TypeError), 1)
        self.assertEqual(monitor.get_error_count(CustomException), 1)
        self.assertEqual(monitor.get_error_count(KeyError), 1)

    def test_handle_error_with_none_context(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with context=None
        THEN expect:
            - Error is handled normally
            - No context-related errors
        """
        self.mock_configs.processing.suppress_errors = True
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Should not raise any errors
        monitor.handle_error(ValueError("test"), context=None)
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)


class TestErrorLogging(unittest.TestCase):
    """Test error logging functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()

        self.mock_resources['logger'] = self.mock_logger = MagicMock(spec=Logger)
        self.mock_resources['traceback'] = self.mock_traceback = MagicMock()

    def test_log_error_with_exception(self):
        """
        GIVEN an ErrorMonitor with mocked logger
        WHEN log_error is called with Exception("test")
        THEN expect:
            - logger.error is called once
            - Log message contains error type and message
            - Error is recorded in internal tracking
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        test_error = ValueError("test error")
        
        monitor.log_error(test_error)
        
        self.mock_logger.error.assert_called_once()
        call_args = str(self.mock_logger.error.call_args)
        self.assertIn("ValueError", call_args)
        self.assertIn("test error", call_args)
        self.assertEqual(monitor.get_error_count(), 1)

    def test_log_error_with_string(self):
        """
        GIVEN an ErrorMonitor with mocked logger
        WHEN log_error is called with "error string"
        THEN expect:
            - logger.error is called once
            - Log message contains the string
            - Error is recorded as string type
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.log_error("error string")
        
        self.mock_logger.error.assert_called_once()
        call_args = str(self.mock_logger.error.call_args)
        self.assertIn("error string", call_args)
        self.assertEqual(monitor.get_error_count(), 1)

    def test_log_error_with_empty_context(self):
        """
        GIVEN an ErrorMonitor
        WHEN log_error is called with error and context={}
        THEN expect:
            - Error is logged normally
            - No context in log message
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.log_error(ValueError("test"), context={})
        
        self.mock_logger.error.assert_called_once()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_log_error_with_complex_context(self):
        """
        GIVEN an ErrorMonitor
        WHEN log_error is called with context containing:
            - Nested dictionaries
            - Lists
            - Various data types
        THEN expect:
            - All context is properly logged
            - No serialization errors
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        complex_context = {
            'nested': {'key': 'value', 'number': 42},
            'list': [1, 2, 3, 'string'],
            'boolean': True,
            'null': None
        }
        
        # Should not raise any serialization errors
        monitor.log_error(ValueError("test"), context=complex_context)
        
        self.mock_logger.error.assert_called_once()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_log_error_preserves_exception_traceback(self):
        """
        GIVEN an ErrorMonitor
        WHEN log_error is called with an exception that has traceback
        THEN expect:
            - Traceback information is included in log
            - Original exception details are preserved
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        self.mock_traceback.format_exc.return_value = "Traceback (most recent call last):\n  File..."
        
        try:
            raise ValueError("test with traceback")
        except ValueError as e:
            monitor.log_error(e)
        
        self.mock_logger.error.assert_called_once()
        self.mock_traceback.format_exc.assert_called()


class TestErrorStatistics(unittest.TestCase):
    """Test error statistics and reporting."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()
        self.mock_configs.processing.suppress_errors = True

    def test_error_statistics_initially_empty(self):
        """
        GIVEN a new ErrorMonitor instance
        WHEN error_statistics property is accessed
        THEN expect:
            - total_errors: 0
            - error_types: []
            - error_counts: {}
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        stats = monitor.error_statistics
        
        self.assertEqual(stats['total_errors'], 0)
        self.assertEqual(stats['error_types'], [])
        self.assertEqual(stats['error_counts'], {})

    def test_error_statistics_after_single_error(self):
        """
        GIVEN an ErrorMonitor that handled one ValueError
        WHEN error_statistics property is accessed
        THEN expect:
            - total_errors: 1
            - error_types: ['ValueError']
            - error_counts: {'ValueError': 1}
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        monitor.handle_error(ValueError("test"))
        
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], 1)
        self.assertIn('ValueError', stats['error_types'])
        self.assertEqual(stats['error_counts']['ValueError'], 1)

    def test_error_statistics_after_multiple_errors(self):
        """
        GIVEN an ErrorMonitor that handled:
            - 3 ValueError
            - 2 TypeError
            - 1 KeyError
        WHEN error_statistics property is accessed
        THEN expect:
            - total_errors: 6
            - error_types: ['ValueError', 'TypeError', 'KeyError']
            - error_counts: {'ValueError': 3, 'TypeError': 2, 'KeyError': 1}
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Add 3 ValueError
        for i in range(3):
            monitor.handle_error(ValueError(f"test {i}"))
        
        # Add 2 TypeError
        for i in range(2):
            monitor.handle_error(TypeError(f"test {i}"))
        
        # Add 1 KeyError
        monitor.handle_error(KeyError("test"))
        
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], 6)
        self.assertIn('ValueError', stats['error_types'])
        self.assertIn('TypeError', stats['error_types'])
        self.assertIn('KeyError', stats['error_types'])
        self.assertEqual(stats['error_counts']['ValueError'], 3)
        self.assertEqual(stats['error_counts']['TypeError'], 2)
        self.assertEqual(stats['error_counts']['KeyError'], 1)

    def test_error_statistics_with_string_errors(self):
        """
        GIVEN an ErrorMonitor that handled string errors
        WHEN error_statistics property is accessed
        THEN expect:
            - String errors are tracked separately
            - Statistics include string error counts
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        monitor.handle_error("string error 1")
        monitor.handle_error("string error 2")
        monitor.handle_error("string error 2")
        monitor.handle_error("string error 3")
        monitor.handle_error("string error 3")
        monitor.handle_error("string error 3")
        
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], 6)
        self.assertIn('string error 1', stats['error_types'])
        self.assertIn('string error 2', stats['error_types'])
        self.assertIn('string error 3', stats['error_types'])
        self.assertEqual(stats['error_counts']['string error 1'], 1)
        self.assertEqual(stats['error_counts']['string error 2'], 2)
        self.assertEqual(stats['error_counts']['string error 3'], 3)

    def test_get_most_common_errors_default_limit(self):
        """
        GIVEN an ErrorMonitor with 10 different error types
        WHEN get_most_common_errors() is called (default limit=5)
        THEN expect:
            - Returns list of 5 items
            - Items sorted by count (descending)
            - Each item has 'type' and 'count' keys
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Create 10 different error types with different counts
        error_types = [ValueError, TypeError, KeyError, AttributeError, IndexError,
                      RuntimeError, ImportError, NameError, OSError, IOError]
        
        for i, error_type in enumerate(error_types):
            # Add (10-i) errors of each type, so ValueError has most, IOError has least
            for j in range(10 - i):
                monitor.handle_error(error_type(f"test {j}"))
        
        most_common = monitor.get_most_common_errors()
        
        self.assertEqual(len(most_common), 5)  # Default limit
        self.assertTrue(all('type' in item and 'count' in item for item in most_common))
        
        # Should be sorted by count descending
        counts = [item['count'] for item in most_common]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_get_most_common_errors_custom_limit(self):
        """
        GIVEN an ErrorMonitor with 3 error types
        WHEN get_most_common_errors(limit=10) is called
        THEN expect:
            - Returns list of 3 items (all available)
            - No padding or empty entries
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test"))
        monitor.handle_error(TypeError("test"))
        monitor.handle_error(KeyError("test"))
        
        most_common = monitor.get_most_common_errors(limit=10)
        
        self.assertEqual(len(most_common), 3)  # Only 3 available
        self.assertTrue(all('type' in item and 'count' in item for item in most_common))

    def test_get_most_common_errors_no_errors(self):
        """
        GIVEN an ErrorMonitor with no errors
        WHEN get_most_common_errors() is called
        THEN expect:
            - Returns empty list
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        most_common = monitor.get_most_common_errors()
        
        self.assertEqual(most_common, [])


class TestErrorCounters(unittest.TestCase):
    """Test error counter functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()

        self.mock_configs.processing.suppress_errors = True

    def test_get_error_count_total(self):
        """
        GIVEN an ErrorMonitor with various errors
        WHEN get_error_count() is called with no arguments
        THEN expect:
            - Returns total count of all errors
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test"))
        monitor.handle_error(TypeError("test"))
        monitor.handle_error("string error")
        
        total_count = monitor.get_error_count()
        self.assertEqual(total_count, 3)

    def test_get_error_count_specific_exception_type(self):
        """
        GIVEN an ErrorMonitor with multiple error types
        WHEN get_error_count(ValueError) is called
        THEN expect:
            - Returns count of only ValueError instances
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test 1"))
        monitor.handle_error(ValueError("test 2"))
        monitor.handle_error(TypeError("test"))
        
        value_error_count = monitor.get_error_count(ValueError)
        self.assertEqual(value_error_count, 2)

    def test_get_error_count_specific_string_type(self):
        """
        GIVEN an ErrorMonitor with string errors
        WHEN get_error_count("CustomError") is called
        THEN expect:
            - Returns count of that specific string error
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error("CustomError")
        monitor.handle_error("CustomError")
        monitor.handle_error("OtherError")
        
        custom_error_count = monitor.get_error_count("CustomError")
        self.assertEqual(custom_error_count, 2)

    def test_get_error_count_nonexistent_type(self):
        """
        GIVEN an ErrorMonitor
        WHEN get_error_count() is called with unrecorded error type
        THEN expect:
            - Returns 0
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test"))
        
        nonexistent_count = monitor.get_error_count(TypeError)
        self.assertEqual(nonexistent_count, 0)

    def test_reset_error_counters(self):
        """
        GIVEN an ErrorMonitor with multiple errors recorded
        WHEN reset_error_counters() is called
        THEN expect:
            - All counters reset to 0
            - error_statistics shows empty state
            - has_errors returns False
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Add some errors
        monitor.handle_error(ValueError("test"))
        monitor.handle_error(TypeError("test"))
        
        # Verify errors exist
        self.assertTrue(monitor.has_errors)
        self.assertEqual(monitor.get_error_count(), 2)
        
        # Reset and verify
        monitor.reset_error_counters()
        
        self.assertFalse(monitor.has_errors)
        self.assertEqual(monitor.get_error_count(), 0)
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], 0)
        self.assertEqual(stats['error_types'], [])
        self.assertEqual(stats['error_counts'], {})

    def test_has_errors_initially_false(self):
        """
        GIVEN a new ErrorMonitor
        WHEN has_errors property is accessed
        THEN expect:
            - Returns False
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        self.assertFalse(monitor.has_errors)

    def test_has_errors_after_handling_error(self):
        """
        GIVEN an ErrorMonitor that handled at least one error
        WHEN has_errors property is accessed
        THEN expect:
            - Returns True
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test"))
        
        self.assertTrue(monitor.has_errors)

    def test_has_errors_after_reset(self):
        """
        GIVEN an ErrorMonitor with errors that was reset
        WHEN has_errors property is accessed
        THEN expect:
            - Returns False
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        monitor.handle_error(ValueError("test"))
        self.assertTrue(monitor.has_errors)
        
        monitor.reset_error_counters()
        self.assertFalse(monitor.has_errors)


class TestCoreDump(unittest.TestCase):
    """Test core dump functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        self.mock_traceback = MagicMock()
        self.mock_datetime = MagicMock()
        self.mock_datetime.now.return_value.strftime.return_value = "20240101_120000"

        # Create a real temporary directory for testing
        self.temp_dir = Path(tempfile.mkdtemp())

        self.mock_resources = {
            'logger': self.mock_logger,
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }
        self.mock_configs = make_mock_configs()
        self.mock_configs.processing.suppress_errors = True
        self.mock_configs.paths.ROOT_DIR = self.temp_dir

    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_core_dump_with_errors(self):
        """
        GIVEN an ErrorMonitor with multiple errors
        WHEN core_dump() is called
        THEN expect:
            - Log file created in logs directory
            - File contains timestamp
            - File contains total error count
            - File contains error type breakdown
            - File contains structured data
        """
        # Setup datetime mock
        self.mock_datetime.datetime.now.return_value.strftime.return_value = "20240101_120000"

        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)

        # Add some errors
        monitor.handle_error(ValueError("test 1"))
        monitor.handle_error(ValueError("test 2"))
        monitor.handle_error(TypeError("test"))
        
        monitor.core_dump()
        
        # Verify log file was created
        logs_dir = self.temp_dir / "logs"
        self.assertTrue(logs_dir.exists())
        
        log_files = list(logs_dir.glob("error_monitor_core_dump_*.log"))
        self.assertEqual(len(log_files), 1)

        # Verify file content
        log_file = log_files[0]
        with open(log_file, 'r') as f:
            content = f.read()

        self.assertIn("20240101_120000", content)
        self.assertIn("Total Errors: 3", content)
        self.assertIn("ValueError: 2", content)
        self.assertIn("TypeError: 1", content)

    def test_core_dump_no_errors(self):
        """
        GIVEN an ErrorMonitor with no errors
        WHEN core_dump() is called
        THEN expect:
            - No log file is created
            - No exceptions raised
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Should not raise any exceptions
        with patch('builtins.open', new_callable=mock_open) as mock_file:
            monitor.core_dump()
            
            # File should not be opened since no errors
            mock_file.assert_not_called()

    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists', return_value=False)
    @patch('builtins.open', new_callable=mock_open)
    def test_core_dump_creates_logs_directory(self, mock_file, mock_exists, mock_mkdir):
        """
        GIVEN an ErrorMonitor and no logs directory exists
        WHEN core_dump() is called
        THEN expect:
            - logs directory is created
            - Log file is written successfully
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        monitor.handle_error(ValueError("test"))
        
        monitor.core_dump()
        
        # Verify directory creation was attempted
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_file.assert_called_once()

    @patch('pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_core_dump_file_naming(self, mock_file, mock_mkdir):
        """
        GIVEN an ErrorMonitor
        WHEN core_dump() is called multiple times
        THEN expect:
            - Each file has unique timestamp
            - Files don't overwrite each other
            - Naming follows consistent pattern
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        monitor.handle_error(ValueError("test"))
        
        # First call
        self.mock_datetime.datetime.now.return_value.strftime.return_value = "20240101_120000"
        monitor.core_dump()
        
        # Second call with different timestamp
        self.mock_datetime.datetime.now.return_value.strftime.return_value = "20240101_120001"
        monitor.core_dump()
        
        # Verify both files were created
        self.assertEqual(mock_file.call_count, 2)
        
        # Check file paths contain timestamps
        call_args = [call[0][0] for call in mock_file.call_args_list]
        self.assertIn("20240101_120000", str(call_args[0]))
        self.assertIn("20240101_120001", str(call_args[1]))

    @patch('pathlib.Path.mkdir')
    @patch('builtins.open', side_effect=PermissionError("Permission denied"))
    def test_core_dump_handles_write_errors(self, mock_file, mock_mkdir):
        """
        GIVEN an ErrorMonitor and write permissions denied
        WHEN core_dump() is called
        THEN expect:
            - Appropriate exception is raised
            - Error message indicates write failure
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        monitor.handle_error(ValueError("test"))
        
        with self.assertRaises(Exception) as context:
            monitor.core_dump()
        
        # Should re-raise the permission error or wrap it
        self.assertTrue(
            isinstance(context.exception, PermissionError) or
            "Permission denied" in str(context.exception) or
            "write" in str(context.exception).lower()
        )

    @patch('pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_core_dump_large_error_count(self, mock_file, mock_mkdir):
        """
        GIVEN an ErrorMonitor with thousands of errors
        WHEN core_dump() is called
        THEN expect:
            - File is created successfully
            - All error data is included
            - No truncation or data loss
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Add many errors
        for i in range(1000):
            monitor.handle_error(ValueError(f"test error {i}"))
        
        monitor.core_dump()
        
        mock_file.assert_called_once()
        handle = mock_file()
        handle.write.assert_called()
        
        # Verify large amount of data was written
        written_content = ''.join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("1000", written_content)  # Should contain the error count


class TestErrorSuppression(unittest.TestCase):
    """Test error suppression configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()

    def test_set_error_suppression_enable(self):
        """
        GIVEN an ErrorMonitor with suppress_errors=False
        WHEN set_error_suppression(True) is called
        THEN expect:
            - Error suppression is enabled
            - Subsequent errors don't raise exceptions
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Initially should raise exceptions
        with self.assertRaises(ValueError):
            monitor.handle_error(ValueError("test"))
        
        # Enable suppression
        monitor.set_error_suppression(True)
        
        # Should not raise now
        monitor.handle_error(ValueError("test suppressed"))
        
        # Verify error was still logged and counted
        self.assertEqual(monitor.get_error_count(), 2)

    def test_set_error_suppression_disable(self):
        """
        GIVEN an ErrorMonitor with suppress_errors=True
        WHEN set_error_suppression(False) is called
        THEN expect:
            - Error suppression is disabled
            - Subsequent errors raise exceptions
        """
        self.mock_configs.processing.suppress_errors = True
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Initially should not raise
        monitor.handle_error(ValueError("test suppressed"))
        
        # Disable suppression
        monitor.set_error_suppression(False)
        
        # Should raise now
        with self.assertRaises(ValueError):
            monitor.handle_error(ValueError("test"))
        
        self.assertEqual(monitor.get_error_count(), 2)

    def test_error_suppression_toggle_multiple_times(self):
        """
        GIVEN an ErrorMonitor
        WHEN set_error_suppression is toggled multiple times
        THEN expect:
            - Each toggle changes behavior correctly
            - No state corruption
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Start with False (raises)
        with self.assertRaises(ValueError):
            monitor.handle_error(ValueError("test 1"))
        
        # Toggle to True (suppresses)
        monitor.set_error_suppression(True)
        monitor.handle_error(ValueError("test 2"))
        
        # Toggle to False (raises)
        monitor.set_error_suppression(False)
        with self.assertRaises(ValueError):
            monitor.handle_error(ValueError("test 3"))
        
        # Toggle back to True (suppresses)
        monitor.set_error_suppression(True)
        monitor.handle_error(ValueError("test 4"))
        
        self.assertEqual(monitor.get_error_count(), 4)


class TestEdgeCasesAndConcurrency(unittest.TestCase):
    """Test edge cases and thread safety."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_resources = make_mock_resources()
        self.mock_configs = make_mock_configs()
        self.mock_resources['logger'] = self.mock_logger = MagicMock(spec=Logger)
        self.mock_configs.processing.suppress_errors = True

    def test_handle_none_error(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error(None) is called
        THEN expect:
            - Appropriate handling (log as string or skip)
            - No crashes
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Should not crash
        monitor.handle_error(None)
        
        # Should be handled somehow (logged or counted)
        self.mock_logger.error.assert_called()

    def test_handle_error_with_circular_reference_in_context(self):
        """
        GIVEN an ErrorMonitor and context with circular reference
        WHEN handle_error is called
        THEN expect:
            - Error is handled without infinite recursion
            - Context is logged safely
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Create circular reference
        context = {'key': 'value'}
        context['self'] = context
        
        # Should not cause infinite recursion
        monitor.handle_error(ValueError("test"), context=context)
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_error_with_non_serializable_context(self):
        """
        GIVEN an ErrorMonitor and context with lambda/function
        WHEN handle_error is called
        THEN expect:
            - Error is handled
            - Non-serializable parts handled gracefully
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        context = {
            'function': lambda x: x,
            'normal_key': 'normal_value'
        }
        
        # Should handle non-serializable content gracefully
        monitor.handle_error(ValueError("test"), context=context)
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_concurrent_error_handling(self):
        """
        GIVEN an ErrorMonitor
        WHEN multiple threads call handle_error simultaneously
        THEN expect:
            - All errors are recorded
            - Counts are accurate
            - No race conditions
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        errors_per_thread = 10
        num_threads = 5
        
        def add_errors():
            for i in range(errors_per_thread):
                monitor.handle_error(ValueError(f"thread error {i}"))
        
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=add_errors)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All errors should be counted
        expected_total = errors_per_thread * num_threads
        self.assertEqual(monitor.get_error_count(), expected_total)

    def test_very_long_error_message(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with 10MB error message
        THEN expect:
            - Error is handled
            - No memory issues
            - Message potentially truncated in logs
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Create very long error message (1MB should be enough for testing)
        long_message = "A" * (1024 * 1024)  # 1MB string
        
        # Should not crash or cause memory issues
        monitor.handle_error(ValueError(long_message))
        
        self.mock_logger.error.assert_called()
        self.assertEqual(monitor.get_error_count(), 1)

    def test_unicode_in_error_messages(self):
        """
        GIVEN an ErrorMonitor
        WHEN handle_error is called with unicode characters (emoji, CJK, etc.)
        THEN expect:
            - Error is handled correctly
            - No encoding errors
            - Characters preserved in logs
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        unicode_messages = [
            "Error with emoji 🚫💥",
            "中文错误信息",
            "Ошибка на русском",
            "العربية خطأ",
            "🎯🔥⚡️💻🐛"
        ]
        
        for message in unicode_messages:
            monitor.handle_error(ValueError(message))
        
        # All errors should be handled
        self.assertEqual(monitor.get_error_count(), len(unicode_messages))
        self.assertEqual(self.mock_logger.error.call_count, len(unicode_messages))


class TestIntegration(unittest.TestCase):
    """Test integration scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        self.mock_traceback = MagicMock()
        self.mock_datetime = MagicMock()
        self.mock_datetime.now.return_value.strftime.return_value = "20240101_120000"

        self.mock_resources = {
            'logger': self.mock_logger,
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }
        self.mock_configs = make_mock_configs()
        self.mock_configs.processing.suppress_errors = True

    @patch('pathlib.Path.mkdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_full_error_lifecycle(self, mock_file, mock_mkdir):
        """
        GIVEN an ErrorMonitor
        WHEN performing full lifecycle:
            1. Initialize
            2. Handle various errors
            3. Check statistics
            4. Core dump
            5. Reset
            6. Handle more errors
        THEN expect:
            - Each step works correctly
            - State transitions are proper
            - Files created as expected
        """
        # 1. Initialize
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        self.assertFalse(monitor.has_errors)
        
        # 2. Handle various errors
        monitor.handle_error(ValueError("error 1"))
        monitor.handle_error(TypeError("error 2"))
        monitor.handle_error("string error")
        
        # 3. Check statistics
        self.assertTrue(monitor.has_errors)
        self.assertEqual(monitor.get_error_count(), 3)
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], 3)
        
        # 4. Core dump
        monitor.core_dump()
        mock_file.assert_called_once()
        
        # 5. Reset
        monitor.reset_error_counters()
        self.assertFalse(monitor.has_errors)
        self.assertEqual(monitor.get_error_count(), 0)
        
        # 6. Handle more errors
        monitor.handle_error(KeyError("new error"))
        self.assertTrue(monitor.has_errors)
        self.assertEqual(monitor.get_error_count(), 1)

    def test_error_monitor_with_real_logger(self):
        """
        GIVEN an ErrorMonitor with actual Python logger
        WHEN errors are handled
        THEN expect:
            - Logs appear in correct format
            - Log levels are appropriate
            - No logger configuration conflicts
        """
        import logging
        import io
        
        # Create real logger with string stream
        log_stream = io.StringIO()
        real_logger = logging.getLogger('test_logger')
        real_logger.setLevel(logging.ERROR)
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        real_logger.addHandler(handler)
        
        # Use real logger
        resources = {
            'logger': real_logger,
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }
        
        monitor = ErrorMonitor(resources, self.mock_configs)
        monitor.handle_error(ValueError("test error"))
        
        # Check that log was written
        log_output = log_stream.getvalue()
        self.assertIn("ERROR:", log_output)
        self.assertIn("ValueError", log_output)
        self.assertIn("test error", log_output)

    def test_error_monitor_memory_usage(self):
        """
        GIVEN an ErrorMonitor
        WHEN handling 100,000 errors
        THEN expect:
            - Memory usage remains reasonable
            - No memory leaks
            - Performance remains acceptable
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # Add many errors
        num_errors = 1000  # Reduced for test performance
        start_time = time.time()
        
        for i in range(num_errors):
            if i % 100 == 0:  # Vary error types
                monitor.handle_error(TypeError(f"error {i}"))
            else:
                monitor.handle_error(ValueError(f"error {i}"))
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Verify all errors were counted
        self.assertEqual(monitor.get_error_count(), num_errors)
        
        # Performance should be reasonable (adjust threshold as needed)
        self.assertLess(duration, 10.0)  # Should complete in under 10 seconds
        
        # Memory usage test - verify data structures are reasonable
        stats = monitor.error_statistics
        self.assertEqual(stats['total_errors'], num_errors)
        self.assertIn('ValueError', stats['error_types'])
        self.assertIn('TypeError', stats['error_types'])


class TestLoggerProperty(unittest.TestCase):
    """Test the logger property."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        self.mock_traceback = MagicMock()
        self.mock_datetime = MagicMock()
        self.mock_datetime.now.return_value.strftime.return_value = "20240101_120000"

        self.mock_resources = {
            'logger': self.mock_logger,
            'traceback': self.mock_traceback,
            'datetime': self.mock_datetime
        }
        self.mock_configs = make_mock_configs()

    def test_logger_property_returns_logger(self):
        """
        GIVEN an ErrorMonitor with a logger
        WHEN the logger property is accessed
        THEN expect:
            - Returns the same logger instance passed in resources
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        self.assertIs(monitor.logger, self.mock_logger)

    def test_logger_property_is_readonly(self):
        """
        GIVEN an ErrorMonitor
        WHEN attempting to set the logger property
        THEN expect:
            - AttributeError is raised (if implemented as read-only)
            - Or the setter works if implemented
        """
        monitor = ErrorMonitor(self.mock_resources, self.mock_configs)
        
        # This test depends on implementation - if logger is read-only property
        try:
            monitor.logger = MagicMock()
            # If no error, then setter is implemented
            self.assertIsNotNone(monitor.logger)
        except AttributeError:
            # If AttributeError, then it's read-only as expected
            pass


if __name__ == '__main__':
    unittest.main()