import unittest
from unittest.mock import MagicMock
from pathlib import Path
from logging import Logger
import os
import pathlib


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