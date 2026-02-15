"""
Perfect Test Suite for ResourceMonitor

This module demonstrates best practices for unit testing based on:
- Testing through public contracts only
- Testing behavior, not implementation details
- Following AAA (Arrange, Act, Assert) pattern
- Single assertion per test method
- Clear GIVEN/WHEN/THEN docstring format
- No magic numbers or strings
- Proper use of constants and fixtures
"""
import pytest
from unittest.mock import MagicMock, patch
import copy
import time

try:
    import psutil
except ImportError:
    pytest.skip("psutil library is required for resource monitoring. Please install it using 'pip install psutil'.", 
                allow_module_level=True)

from monitors._resource_monitor import ResourceMonitor
from utils.hardware import Hardware
from types_ import Logger
from configs import Configs

# Test Constants
EXPECTED_MEMORY_LIMIT_MB = 512.0
EXPECTED_CPU_LIMIT_PERCENT = 80.0
EXPECTED_MONITORING_INTERVAL_SECONDS = 0.1
EXPECTED_ACTIVE_MONITORING_FALSE = False
EXPECTED_NONE_MONITORING_THREAD = None
EXPECTED_CPU_USAGE_PERCENT = 30.0
EXPECTED_MEMORY_USAGE_MB = 200.0
EXPECTED_MEMORY_PERCENT = 40.0
EXPECTED_DISK_USAGE_PERCENT = 50.0
EXPECTED_OPEN_FILES_COUNT = 3
EXPECTED_CPU_UNDER_LIMIT = 70.0
EXPECTED_MEMORY_UNDER_LIMIT_MB = 400.0
EXPECTED_CPU_OVER_LIMIT = 90.0
EXPECTED_MEMORY_OVER_LIMIT_MB = 600.0
EXPECTED_NEW_MEMORY_LIMIT = 1024.0
EXPECTED_NEW_CPU_LIMIT = 90.0
EXPECTED_PARTIAL_UPDATE_MEMORY_LIMIT = 2048.0
EXPECTED_SUMMARY_MEMORY_LIMIT = 512.0
EXPECTED_SUMMARY_CPU_LIMIT = 80.0
EXPECTED_MONITORING_WAIT_SECONDS = 0.2
MEMORY_INFO_RSS_BYTES = 200 * 1024 * 1024  # 200 MB in bytes
MEMORY_INFO_VMS_BYTES = 240 * 1024 * 1024  # 240 MB in bytes
MEMORY_INFO_SHARED_BYTES = 20 * 1024 * 1024  # 20 MB in bytes


@pytest.fixture
def valid_configs():
    """Create valid mock configs for testing."""
    mock_configs = MagicMock(spec=Configs)
    mock_configs.resources = MagicMock()
    mock_configs.resources.memory_limit_mb = EXPECTED_MEMORY_LIMIT_MB
    mock_configs.resources.cpu_limit_percent = EXPECTED_CPU_LIMIT_PERCENT
    mock_configs.resources.monitoring_interval_seconds = EXPECTED_MONITORING_INTERVAL_SECONDS
    return mock_configs


@pytest.fixture
def valid_resources():
    """Create valid mock resources for testing."""
    base_resources = {
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
    return {
        **copy.deepcopy(base_resources),
        "logger": MagicMock(spec=Logger),
    }


@pytest.fixture
def resource_monitor(valid_resources, valid_configs):
    """Create a ResourceMonitor instance for testing."""
    monitor = ResourceMonitor(resources=valid_resources, configs=valid_configs)
    yield monitor
    # Cleanup: Stop any active monitoring
    if hasattr(monitor, 'active_monitoring') and monitor.active_monitoring:
        monitor.stop_monitoring()


@pytest.fixture
def mock_memory_info():
    """Create mock memory info object."""
    memory_info_mock = MagicMock()
    memory_info_mock.rss = MEMORY_INFO_RSS_BYTES
    memory_info_mock.vms = MEMORY_INFO_VMS_BYTES
    memory_info_mock.shared = MEMORY_INFO_SHARED_BYTES
    return memory_info_mock


@pytest.fixture
def mock_process(mock_memory_info):
    """Create mock psutil process."""
    process_mock = MagicMock(spec="psutil.Process")
    process_mock.memory_info.return_value = mock_memory_info
    process_mock.open_files.return_value = ["file1", "file2", "file3"]
    return process_mock


@pytest.fixture
def mocked_psutil_standard(mock_process):
    """Create standard mocked psutil configuration."""
    with patch('utils.hardware.psutil') as mock_psutil:
        mock_psutil.cpu_percent.return_value = EXPECTED_CPU_USAGE_PERCENT
        mock_psutil.Process.return_value = mock_process
        mock_psutil.virtual_memory.return_value.percent = EXPECTED_MEMORY_PERCENT
        mock_psutil.disk_usage.return_value.percent = EXPECTED_DISK_USAGE_PERCENT
        yield mock_psutil


@pytest.fixture
def mocked_psutil_under_limits(mock_process, mock_memory_info):
    """Create mocked psutil with resources under limits."""
    with patch('utils.hardware.psutil') as mock_psutil:
        mock_psutil.cpu_percent.return_value = EXPECTED_CPU_UNDER_LIMIT
        mock_memory_info.rss = EXPECTED_MEMORY_UNDER_LIMIT_MB * 1024 * 1024
        mock_psutil.Process.return_value = mock_process
        yield mock_psutil


@pytest.fixture
def mocked_psutil_over_cpu_limit(mock_process, mock_memory_info):
    """Create mocked psutil with CPU over limit."""
    with patch('utils.hardware.psutil') as mock_psutil:
        mock_psutil.cpu_percent.return_value = EXPECTED_CPU_OVER_LIMIT
        mock_memory_info.rss = EXPECTED_MEMORY_UNDER_LIMIT_MB * 1024 * 1024
        mock_psutil.Process.return_value = mock_process
        yield mock_psutil


@pytest.fixture
def mocked_psutil_over_memory_limit(mock_process, mock_memory_info):
    """Create mocked psutil with memory over limit."""
    with patch('utils.hardware.psutil') as mock_psutil:
        mock_psutil.cpu_percent.return_value = EXPECTED_CPU_UNDER_LIMIT
        mock_memory_info.rss = EXPECTED_MEMORY_OVER_LIMIT_MB * 1024 * 1024
        mock_psutil.Process.return_value = mock_process
        yield mock_psutil


@pytest.mark.unit
class TestResourceMonitorConstruction:
    """Test ResourceMonitor construction functionality."""

    def test_when_creating_resource_monitor_with_valid_resources_and_configs_then_returns_resource_monitor_instance(
        self, 
        valid_resources, 
        valid_configs
    ):
        """
        GIVEN valid resources and valid configs
        WHEN ResourceMonitor constructor is called
        THEN returns ResourceMonitor instance
        """
        result = ResourceMonitor(resources=valid_resources, configs=valid_configs)
        
        assert isinstance(result, ResourceMonitor), f"Expected ResourceMonitor instance, got {type(result)}"


    @pytest.mark.parametrize(
        "attribute_name, expected_value",
        [
            ("cpu_limit_percent", EXPECTED_CPU_LIMIT_PERCENT),
            ("memory_limit", EXPECTED_MEMORY_LIMIT_MB),
            ("monitoring_interval", EXPECTED_MONITORING_INTERVAL_SECONDS),
            ("active_monitoring", EXPECTED_ACTIVE_MONITORING_FALSE),
            ("monitoring_thread", EXPECTED_NONE_MONITORING_THREAD)
        ],
    )
    def test_when_creating_resource_monitor_then_initial_attributes_are_correct(
        self, resource_monitor, attribute_name, expected_value
    ):
        """
        GIVEN valid resources and configs
        WHEN ResourceMonitor is constructed
        THEN its initial attributes match the expected values
        """
        result = getattr(resource_monitor, attribute_name)
        
        assert result == expected_value, f"Expected {attribute_name} to be {expected_value}, but got {result}"


    @pytest.mark.parametrize("expected_key", [
        "cpu",
        "memory"
    ])
    def test_when_creating_resource_monitor_then_current_resource_usage_contains_expected_keys(self, resource_monitor, expected_key):
        """
        GIVEN valid resources and configs
        WHEN ResourceMonitor is constructed
        THEN current_resource_usage contains the expected key
        """
        result = resource_monitor.current_resource_usage
        
        assert expected_key in result, f"Expected '{expected_key}' key in resource usage, got keys: {list(result.keys())}"

@pytest.mark.unit
class TestResourceMonitorStartMonitoring:
    """Test ResourceMonitor start_monitoring functionality."""

    def test_when_starting_monitoring_then_active_monitoring_becomes_true(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil
        WHEN start_monitoring is called
        THEN active_monitoring becomes True
        """
        resource_monitor.start_monitoring()
        
        assert resource_monitor.active_monitoring is True, f"Expected active monitoring True, got {resource_monitor.active_monitoring}"

    def test_when_starting_monitoring_then_monitoring_thread_is_not_none(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil
        WHEN start_monitoring is called
        THEN monitoring_thread is not None
        """
        resource_monitor.start_monitoring()
        
        assert resource_monitor.monitoring_thread is not None, f"Expected monitoring thread not None, got {resource_monitor.monitoring_thread}"

    def test_when_starting_monitoring_then_monitoring_thread_is_alive(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil
        WHEN start_monitoring is called
        THEN monitoring_thread is alive
        """
        resource_monitor.start_monitoring()
        
        assert resource_monitor.monitoring_thread.is_alive(), f"Expected monitoring thread to be alive, but it's not"


@pytest.mark.unit
class TestResourceMonitorStopMonitoring:
    """Test ResourceMonitor stop_monitoring functionality."""

    def test_when_stopping_monitoring_after_starting_then_active_monitoring_becomes_false(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with active monitoring
        WHEN stop_monitoring is called
        THEN active_monitoring becomes False
        """
        resource_monitor.start_monitoring()
        resource_monitor.stop_monitoring()
        
        assert resource_monitor.active_monitoring is False, f"Expected active monitoring False, got {resource_monitor.active_monitoring}"


@pytest.mark.unit
class TestResourceMonitorGetResourceUsage:
    """Test ResourceMonitor _get_resource_usage functionality."""

    def test_when_getting_resource_usage_then_cpu_usage_equals_expected_value(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil returning specific CPU usage
        WHEN _get_resource_usage is called
        THEN cpu usage equals expected value
        """
        result = resource_monitor._get_resource_usage()
        
        assert result["cpu"] == EXPECTED_CPU_USAGE_PERCENT, f"Expected CPU usage {EXPECTED_CPU_USAGE_PERCENT}, got {result['cpu']}"

    def test_when_getting_resource_usage_then_memory_usage_equals_expected_value(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil returning specific memory usage
        WHEN _get_resource_usage is called
        THEN memory usage equals expected value
        """
        result = resource_monitor._get_resource_usage()
        
        assert result["memory"] == EXPECTED_MEMORY_USAGE_MB, f"Expected memory usage {EXPECTED_MEMORY_USAGE_MB}, got {result['memory']}"

    def test_when_getting_resource_usage_then_memory_percent_equals_expected_value(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil returning specific memory percentage
        WHEN _get_resource_usage is called
        THEN memory_percent equals expected value
        """
        result = resource_monitor._get_resource_usage()
        
        assert result["memory_percent"] == EXPECTED_MEMORY_PERCENT, f"Expected memory percent {EXPECTED_MEMORY_PERCENT}, got {result['memory_percent']}"

    def test_when_getting_resource_usage_then_disk_usage_equals_expected_value(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil returning specific disk usage
        WHEN _get_resource_usage is called
        THEN disk_usage equals expected value
        """
        result = resource_monitor._get_resource_usage()
        
        assert result["disk_usage"] == EXPECTED_DISK_USAGE_PERCENT, f"Expected disk usage {EXPECTED_DISK_USAGE_PERCENT}, got {result['disk_usage']}"

    def test_when_getting_resource_usage_then_open_files_equals_expected_count(self, mocked_psutil_standard, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with mocked psutil returning specific open files count
        WHEN _get_resource_usage is called
        THEN open_files equals expected count
        """
        result = resource_monitor._get_resource_usage()
        
        assert result["open_files"] == EXPECTED_OPEN_FILES_COUNT, f"Expected open files {EXPECTED_OPEN_FILES_COUNT}, got {result['open_files']}"


@pytest.mark.unit
class TestResourceMonitorAreResourcesAvailable:
    """Test ResourceMonitor are_resources_available functionality."""

    def test_when_checking_resources_under_limits_then_returns_true(self, mocked_psutil_under_limits, resource_monitor):
        """
        GIVEN a ResourceMonitor with resources under limits
        WHEN are_resources_available is called
        THEN returns True
        """
        result = resource_monitor.are_resources_available()
        
        assert result is True, f"Expected resources available True, got {result}"

    def test_when_checking_resources_over_cpu_limit_then_returns_false(self, mocked_psutil_over_cpu_limit, resource_monitor):
        """
        GIVEN a ResourceMonitor with CPU usage over limit
        WHEN are_resources_available is called
        THEN returns False
        """
        result = resource_monitor.are_resources_available()
        
        assert result is False, f"Expected resources available False, got {result}"

    def test_when_checking_resources_over_memory_limit_then_returns_false(self, mocked_psutil_over_memory_limit, resource_monitor):
        """
        GIVEN a ResourceMonitor with memory usage over limit
        WHEN are_resources_available is called
        THEN returns False
        """
        result = resource_monitor.are_resources_available()
        
        assert result is False, f"Expected resources available False, got {result}"


@pytest.mark.unit
class TestResourceMonitorSetResourceLimits:
    """Test ResourceMonitor set_resource_limits functionality."""

    def test_when_setting_memory_and_cpu_limits_then_memory_limit_equals_new_value(self, resource_monitor):
        """
        GIVEN a ResourceMonitor instance
        WHEN set_resource_limits is called with new memory limit
        THEN memory_limit equals new value
        """
        resource_monitor.set_resource_limits(
            memory_limit_mb=EXPECTED_NEW_MEMORY_LIMIT, 
            cpu_limit_percent=EXPECTED_NEW_CPU_LIMIT
        )
        
        assert resource_monitor.memory_limit == EXPECTED_NEW_MEMORY_LIMIT, f"Expected memory limit {EXPECTED_NEW_MEMORY_LIMIT}, got {resource_monitor.memory_limit}"

    def test_when_setting_memory_and_cpu_limits_then_cpu_limit_percent_equals_new_value(self, resource_monitor):
        """
        GIVEN a ResourceMonitor instance
        WHEN set_resource_limits is called with new CPU limit
        THEN cpu_limit_percent equals new value
        """
        resource_monitor.set_resource_limits(
            memory_limit_mb=EXPECTED_NEW_MEMORY_LIMIT, 
            cpu_limit_percent=EXPECTED_NEW_CPU_LIMIT
        )
        
        assert resource_monitor.cpu_limit_percent == EXPECTED_NEW_CPU_LIMIT, f"Expected CPU limit {EXPECTED_NEW_CPU_LIMIT}, got {resource_monitor.cpu_limit_percent}"

    def test_when_setting_only_memory_limit_then_memory_limit_equals_new_value(self, resource_monitor):
        """
        GIVEN a ResourceMonitor instance
        WHEN set_resource_limits is called with only memory limit
        THEN memory_limit equals new value
        """
        resource_monitor.set_resource_limits(memory_limit_mb=EXPECTED_PARTIAL_UPDATE_MEMORY_LIMIT)
        
        assert resource_monitor.memory_limit == EXPECTED_PARTIAL_UPDATE_MEMORY_LIMIT, f"Expected memory limit {EXPECTED_PARTIAL_UPDATE_MEMORY_LIMIT}, got {resource_monitor.memory_limit}"

    def test_when_setting_only_memory_limit_then_cpu_limit_percent_remains_unchanged(self, resource_monitor):
        """
        GIVEN a ResourceMonitor instance with existing CPU limit
        WHEN set_resource_limits is called with only memory limit
        THEN cpu_limit_percent remains unchanged
        """
        original_cpu_limit = resource_monitor.cpu_limit_percent
        resource_monitor.set_resource_limits(memory_limit_mb=EXPECTED_PARTIAL_UPDATE_MEMORY_LIMIT)
        
        assert resource_monitor.cpu_limit_percent == original_cpu_limit, f"Expected CPU limit to remain {original_cpu_limit}, got {resource_monitor.cpu_limit_percent}"


@pytest.mark.unit
class TestResourceMonitorGetResourceSummary:
    """Test ResourceMonitor get_resource_summary functionality."""

    @pytest.mark.parametrize("expected_key", [
        "current_usage",
        "limits",
        "within_limits"
    ])
    def test_when_getting_resource_summary_then_contains_expected_keys(self, mocked_psutil_standard, resource_monitor, expected_key):
        """
        GIVEN a ResourceMonitor instance with mocked psutil
        WHEN get_resource_summary is called
        THEN the result contains the expected key
        """
        result = resource_monitor.get_resource_summary()
        
        assert expected_key in result, \
            f"Expected '{expected_key}' key in summary, got keys: {list(result.keys())}"

    @pytest.mark.parametrize("limit_key, expected_value", [
        ("memory_mb", EXPECTED_SUMMARY_MEMORY_LIMIT),
        ("cpu_percent", EXPECTED_SUMMARY_CPU_LIMIT),
    ])
    def test_when_getting_resource_summary_then_limits_contain_expected_values(
        self, 
        mocked_psutil_standard, 
        resource_monitor, 
        limit_key, 
        expected_value
    ):
        """
        GIVEN a ResourceMonitor instance with expected limits
        WHEN get_resource_summary is called
        THEN the limits in the summary contain the expected values
        """
        result = resource_monitor.get_resource_summary()
        
        assert result["limits"][limit_key] == expected_value, \
            f"Expected limit '{limit_key}' to be {expected_value}, got {result['limits'][limit_key]}"