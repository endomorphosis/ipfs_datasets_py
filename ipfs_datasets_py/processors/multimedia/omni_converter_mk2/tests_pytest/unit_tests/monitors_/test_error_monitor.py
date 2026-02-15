"""
Test suite for monitors/_error_monitor.py converted from unittest to pytest.

This test suite validates the ErrorMonitor component through public contracts only,
following best practices for unit testing with proper AAA pattern and GIVEN/WHEN/THEN
docstring format.
"""
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from logging import Logger
import pathlib
import os
import time

# Skip tests if modules can't be imported
pytest_plugins = []
try:
    from configs import Configs
    from monitors._error_monitor import ErrorMonitor
    from monitors import make_error_monitor
except ImportError:
    raise ImportError("Required modules for testing are not available. Check to make sure they work.")


# Test Constants
VALID_ERROR_TYPE = "FileNotFoundError"
ANOTHER_VALID_ERROR_TYPE = "ValueError"
THIRD_ERROR_TYPE = "IOError"
EXPECTED_SINGLE_ERROR_COUNT = 1
EXPECTED_TRIPLE_ERROR_COUNT = 3
EXPECTED_TOTAL_MIXED_ERRORS = 3
EXPECTED_ZERO_ERRORS = 0
EXPECTED_TEST_ROOT_PATH = "/test/root"
EXPECTED_SUPPRESS_ERRORS_FALSE = False
PERFORMANCE_MAX_DURATION_SECONDS = 1.0
PERFORMANCE_ERROR_COUNT = 1000
PERFORMANCE_ERROR_TYPES = 10


@pytest.fixture
def valid_resources():
    """Create valid mock resources for testing."""
    return {
        'logger': MagicMock(spec=Logger),
        'traceback': MagicMock(),
        'datetime': MagicMock(),
    }


@pytest.fixture
def valid_configs():
    """Create valid mock configs for testing."""
    mock_configs = MagicMock(spec=Configs)
    mock_configs.processing = MagicMock()
    mock_configs.paths = MagicMock()
    mock_configs.processing.suppress_errors = EXPECTED_SUPPRESS_ERRORS_FALSE
    root_dir_return_value = Path(EXPECTED_TEST_ROOT_PATH)
    if os.name == "nt":
        root_dir_spec = pathlib.WindowsPath
    else:
        root_dir_spec = pathlib.PosixPath
    mock_configs.paths.ROOT_DIR = MagicMock(spec=root_dir_spec, return_value=root_dir_return_value)
    return mock_configs


@pytest.fixture
def error_monitor(valid_resources, valid_configs):
    """Create an ErrorMonitor instance for testing."""
    return ErrorMonitor(valid_resources, valid_configs)


@pytest.fixture
def error_monitor_with_single_error(valid_resources, valid_configs):
    """Create an ErrorMonitor with a single tracked error."""
    monitor = ErrorMonitor(valid_resources, valid_configs)
    monitor.track_error(VALID_ERROR_TYPE)
    return monitor


@pytest.fixture
def error_monitor_with_mixed_errors(valid_resources, valid_configs):
    """Create an ErrorMonitor with mixed tracked errors."""
    monitor = ErrorMonitor(valid_resources, valid_configs)
    monitor.track_error(VALID_ERROR_TYPE)
    monitor.track_error(VALID_ERROR_TYPE)
    monitor.track_error(ANOTHER_VALID_ERROR_TYPE)
    return monitor


@pytest.fixture
def error_monitor_for_performance_testing(valid_resources, valid_configs):
    """Create an ErrorMonitor pre-configured for performance testing."""
    return ErrorMonitor(valid_resources, valid_configs)


@pytest.fixture
def resources_missing_logger():
    """Create resources dict missing logger key."""
    return {
        'traceback': MagicMock(),
        'datetime': MagicMock()
    }


@pytest.fixture
def resources_missing_traceback():
    """Create resources dict missing traceback key."""
    return {
        'logger': MagicMock(spec=Logger),
        'datetime': MagicMock()
    }


@pytest.fixture
def resources_missing_datetime():
    """Create resources dict missing datetime key."""
    return {
        'logger': MagicMock(spec=Logger),
        'traceback': MagicMock()
    }


@pytest.mark.unit
class TestErrorMonitorConstruction:
    """Test ErrorMonitor construction functionality."""

    def test_when_creating_error_monitor_with_valid_resources_and_configs_then_returns_error_monitor_instance(
        self, 
        valid_resources, 
        valid_configs
    ):
        """
        GIVEN valid resources dict and valid configs object
        WHEN ErrorMonitor constructor is called
        THEN returns ErrorMonitor instance
        """
        result = ErrorMonitor(valid_resources, valid_configs)
        
        assert isinstance(result, ErrorMonitor), f"Expected ErrorMonitor instance, got {type(result)}"

    def test_when_creating_error_monitor_with_missing_logger_then_raises_key_error(
        self, 
        resources_missing_logger, 
        valid_configs
    ):
        """
        GIVEN resources dict missing logger key
        WHEN ErrorMonitor constructor is called
        THEN raises KeyError
        """
        with pytest.raises(KeyError):
            ErrorMonitor(resources_missing_logger, valid_configs)

    def test_when_creating_error_monitor_with_missing_traceback_then_raises_key_error(
        self, 
        resources_missing_traceback, 
        valid_configs
    ):
        """
        GIVEN resources dict missing traceback key
        WHEN ErrorMonitor constructor is called
        THEN raises KeyError
        """
        with pytest.raises(KeyError):
            ErrorMonitor(resources_missing_traceback, valid_configs)

    def test_when_creating_error_monitor_with_missing_datetime_then_raises_key_error(
        self, 
        resources_missing_datetime, 
        valid_configs
    ):
        """
        GIVEN resources dict missing datetime key
        WHEN ErrorMonitor constructor is called
        THEN raises KeyError
        """
        with pytest.raises(KeyError):
            ErrorMonitor(resources_missing_datetime, valid_configs)

    def test_when_creating_error_monitor_with_none_resources_then_raises_type_error(self, valid_configs):
        """
        GIVEN resources parameter as None
        WHEN ErrorMonitor constructor is called
        THEN raises TypeError
        """
        with pytest.raises(TypeError):
            ErrorMonitor(None, valid_configs)

    def test_when_creating_error_monitor_with_none_configs_then_raises_attribute_error(self, valid_resources):
        """
        GIVEN configs parameter as None
        WHEN ErrorMonitor constructor is called
        THEN raises AttributeError
        """
        with pytest.raises(AttributeError):
            ErrorMonitor(valid_resources, None)


@pytest.mark.unit
class TestErrorMonitorTrackError:
    """Test ErrorMonitor track_error functionality."""

    def test_when_tracking_single_error_then_error_can_be_retrieved(self, error_monitor):
        """
        GIVEN an ErrorMonitor instance
        WHEN track_error is called with a specific error type
        THEN get_error_summary returns that error type with count of one
        """
        error_monitor.track_error(VALID_ERROR_TYPE)
        
        result = error_monitor.get_error_summary()
        
        assert result[VALID_ERROR_TYPE] == EXPECTED_SINGLE_ERROR_COUNT, \
            f"Expected error count {EXPECTED_SINGLE_ERROR_COUNT}, got {result[VALID_ERROR_TYPE]}"

    def test_when_tracking_same_error_three_times_then_count_is_three(self, error_monitor):
        """
        GIVEN an ErrorMonitor instance
        WHEN track_error is called three times with same error type
        THEN get_error_summary returns that error type with count of three
        """
        for _ in range(EXPECTED_TRIPLE_ERROR_COUNT):
            error_monitor.track_error(ANOTHER_VALID_ERROR_TYPE)

        result = error_monitor.get_error_summary()

        assert result[ANOTHER_VALID_ERROR_TYPE] == EXPECTED_TRIPLE_ERROR_COUNT, \
            f"Expected error count {EXPECTED_TRIPLE_ERROR_COUNT}, got {result[ANOTHER_VALID_ERROR_TYPE]}"

    @pytest.mark.parametrize(
        "error_type_to_track",
        [VALID_ERROR_TYPE, ANOTHER_VALID_ERROR_TYPE, THIRD_ERROR_TYPE],
    )
    def test_when_tracking_different_error_types_then_summary_contains_that_error_type(self, error_monitor, error_type_to_track):
        """
        GIVEN an ErrorMonitor instance
        WHEN track_error is called with a specific error type
        THEN get_error_summary contains that error type as a key
        """
        error_monitor.track_error(error_type_to_track)
        
        result = error_monitor.get_error_summary()
        
        assert error_type_to_track in result, \
            f"Expected {error_type_to_track} in summary keys {list(result.keys())}"


@pytest.mark.unit
class TestErrorMonitorGetErrorSummary:
    """Test ErrorMonitor get_error_summary functionality."""

    def test_when_getting_summary_from_monitor_with_mixed_errors_then_returns_dict(self, error_monitor_with_mixed_errors):
        """
        GIVEN an ErrorMonitor with tracked errors
        WHEN get_error_summary is called
        THEN returns dict instance
        """
        result = error_monitor_with_mixed_errors.get_error_summary()
        
        assert isinstance(result, dict), f"Expected dict instance, got {type(result)}"

    @pytest.mark.parametrize(
        "expected_error_type",
        [VALID_ERROR_TYPE, ANOTHER_VALID_ERROR_TYPE,],
    )
    def test_when_getting_summary_from_monitor_with_mixed_errors_then_contains_expected_error_types(
        self, error_monitor_with_mixed_errors, expected_error_type
    ):
        """
        GIVEN an ErrorMonitor with mixed tracked errors
        WHEN get_error_summary is called
        THEN the result contains the expected error types
        """
        result = error_monitor_with_mixed_errors.get_error_summary()

        assert expected_error_type in result, f"Expected {expected_error_type} in summary keys {list(result.keys())}"


@pytest.mark.unit
class TestErrorMonitorGetTotalErrors:
    """Test ErrorMonitor get_total_errors functionality."""

    def test_when_getting_total_from_monitor_with_mixed_errors_then_returns_expected_total(self, error_monitor_with_mixed_errors):
        """
        GIVEN an ErrorMonitor with mixed tracked errors
        WHEN get_total_errors is called
        THEN returns expected total count
        """
        result = error_monitor_with_mixed_errors.get_total_errors()
        
        assert result == EXPECTED_TOTAL_MIXED_ERRORS, f"Expected total errors {EXPECTED_TOTAL_MIXED_ERRORS}, got {result}"

    def test_when_getting_total_from_fresh_monitor_then_returns_zero(self, error_monitor):
        """
        GIVEN an ErrorMonitor with no tracked errors
        WHEN get_total_errors is called
        THEN returns zero
        """
        result = error_monitor.get_total_errors()
        
        assert result == EXPECTED_ZERO_ERRORS, f"Expected zero errors {EXPECTED_ZERO_ERRORS}, got {result}"


@pytest.mark.unit
class TestErrorMonitorHasErrors:
    """Test ErrorMonitor has_errors functionality."""

    def test_when_checking_errors_on_monitor_with_errors_then_returns_true(self, error_monitor_with_single_error):
        """
        GIVEN an ErrorMonitor with tracked errors
        WHEN has_errors is called
        THEN returns True
        """
        result = error_monitor_with_single_error.has_errors()
        
        assert result is True, f"Expected has_errors True, got {result}"

    def test_when_checking_errors_on_fresh_monitor_then_returns_false(self, error_monitor):
        """
        GIVEN an ErrorMonitor with no tracked errors
        WHEN has_errors is called
        THEN returns False
        """
        result = error_monitor.has_errors()
        
        assert result is False, f"Expected has_errors False, got {result}"


@pytest.mark.integration
class TestMakeErrorMonitor:
    """Test make_error_monitor factory functionality."""

    def test_when_calling_make_error_monitor_with_valid_resources_and_configs_then_returns_error_monitor_instance(self):
        """
        GIVEN valid resources and configs
        WHEN make_error_monitor is called
        THEN returns ErrorMonitor instance
        """
        mock_resources = {
            'logger': MagicMock(spec=Logger),
            'traceback': MagicMock(),
            'datetime': MagicMock(),
        }
        mock_configs = MagicMock(spec=Configs)
        mock_configs.processing = MagicMock()
        mock_configs.processing.suppress_errors = EXPECTED_SUPPRESS_ERRORS_FALSE
        mock_configs.paths = MagicMock()
        mock_configs.paths.ROOT_DIR = Path(EXPECTED_TEST_ROOT_PATH)

        result = make_error_monitor(mock_resources, mock_configs)
        
        assert isinstance(result, ErrorMonitor), f"Expected ErrorMonitor instance, got {type(result)}"


@pytest.mark.slow  
class TestErrorMonitorPerformance:
    """Test ErrorMonitor performance characteristics."""

    def test_when_tracking_many_errors_rapidly_then_completes_within_time_limit(self, error_monitor_for_performance_testing):
        """
        GIVEN an ErrorMonitor instance
        WHEN tracking many errors rapidly
        THEN completes within expected time limit
        """
        start_time = time.time()
        for i in range(PERFORMANCE_ERROR_COUNT):
            error_monitor_for_performance_testing.track_error(f"Error{i % PERFORMANCE_ERROR_TYPES}")
        end_time = time.time()
        
        duration = end_time - start_time
        
        assert duration < PERFORMANCE_MAX_DURATION_SECONDS, f"Expected duration < {PERFORMANCE_MAX_DURATION_SECONDS}s, got {duration:.3f}s"

    def test_when_tracking_many_errors_rapidly_then_total_equals_expected_count(self, error_monitor_for_performance_testing):
        """
        GIVEN an ErrorMonitor instance
        WHEN tracking many errors rapidly
        THEN get_total_errors returns expected count
        """
        for i in range(PERFORMANCE_ERROR_COUNT):
            error_monitor_for_performance_testing.track_error(f"Error{i % PERFORMANCE_ERROR_TYPES}")
        
        result = error_monitor_for_performance_testing.get_total_errors()
        
        assert result == PERFORMANCE_ERROR_COUNT, f"Expected error count {PERFORMANCE_ERROR_COUNT}, got {result}"