
```python
import unittest

class TestErrorMonitorInitialization(unittest.TestCase):
    """Test ErrorMonitor initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""

    def test_init_creates_instance_successfully(self):
        """
        GIVEN valid resources dict containing:
            - logger: A logger instance
            - traceback: The traceback module
            - datetime: The datetime module
        AND valid configs object with:
            - processing.suppress_errors attribute
            - paths.ROOT_DIR attribute
        WHEN ErrorMonitor is initialized
        THEN expect instance created successfully
        """

    def test_init_sets_logger_from_resources(self):
        """
        GIVEN valid resources dict containing 'logger'
        WHEN ErrorMonitor is initialized
        THEN expect logger is set from resources['logger']
        """

    def test_init_sets_suppress_errors_from_configs(self):
        """
        GIVEN valid configs object with processing.suppress_errors attribute
        WHEN ErrorMonitor is initialized
        THEN expect suppress_errors is set from configs.processing.suppress_errors
        """

    def test_init_sets_root_dir_from_configs(self):
        """
        GIVEN valid configs object with paths.ROOT_DIR attribute
        WHEN ErrorMonitor is initialized
        THEN expect root_dir is set from configs.paths.ROOT_DIR
        """

    def test_init_initializes_error_counters_as_empty_dict(self):
        """
        GIVEN valid initialization parameters
        WHEN ErrorMonitor is initialized
        THEN expect error_counters initialized as empty dict
        """

    def test_init_initializes_error_types_as_empty_set(self):
        """
        GIVEN valid initialization parameters
        WHEN ErrorMonitor is initialized
        THEN expect error_types initialized as empty set
        """

    def test_init_sets_traceback_and_datetime_from_resources(self):
        """
        GIVEN valid resources dict containing traceback and datetime modules
        WHEN ErrorMonitor is initialized
        THEN expect traceback and datetime attributes are set from resources
        """

    def test_init_missing_logger_in_resources(self):
        """
        GIVEN resources dict missing 'logger' key
        WHEN ErrorMonitor is initialized
        THEN expect KeyError to be raised
        """

    def test_init_missing_traceback_in_resources(self):
        """
        GIVEN resources dict missing 'traceback' key
        WHEN ErrorMonitor is initialized
        THEN expect KeyError to be raised
        """

if __name__ == '__main__':
    unittest.main()
```