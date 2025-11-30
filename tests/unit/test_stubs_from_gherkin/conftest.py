"""
Pytest configuration for test stubs directory.

Provides shared fixtures and the FixtureError exception for all test modules.
"""
import pytest
import glob
import os
import importlib
import sys
from pathlib import Path
from typing import Dict, Any
import requests


# Tell pytest to ignore all Python test files in this directory during collection
# Note: conftest.py is automatically excluded by pytest from collection
_all_py_files = glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))
_conftest_path = os.path.join(os.path.dirname(__file__), "conftest.py")
collect_ignore = [f for f in _all_py_files if f != _conftest_path]


def pytest_collection_modifyitems(config, items):
    """
    Skip all test collection in this directory.
    
    These files are stubs/templates for implementing tests with pytest-bdd.
    They are not meant to be run directly.
    """
    # Remove all collected items from this directory
    items[:] = []


def pytest_configure(config):
    """Configure pytest to skip this directory."""
    config.addinivalue_line(
        "markers", "stub: mark test as a stub/template (not to be run)"
    )


class FixtureError(Exception):
    """
    Custom exception for fixture initialization failures.
    
    Provides standardized error reporting for fixture setup issues,
    including resource availability checks and initialization failures.
    """
    pass


# =============================================================================
# Shared Fixtures - Used across multiple test modules
# =============================================================================

@pytest.fixture
def summary_counters_zeroed() -> Dict[str, int]:
    """
    Given the summary counters are set to total=0, passed=0, failed=0, warnings=0
    
    Returns a dictionary with zeroed summary counters for test result tracking.
    """
    try:
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0
        }
        return summary
    except Exception as e:
        raise FixtureError(f"summary_counters_zeroed raised an error: {e}") from e


@pytest.fixture
def dashboard_url_configured() -> str:
    """
    Given the dashboard URL is http://localhost:8899/mcp
    
    Returns the configured dashboard URL. Checks if the URL is accessible.
    """
    try:
        url = "http://localhost:8899/mcp"
        # Check if the dashboard is accessible (with short timeout)
        try:
            response = requests.get(url, timeout=2)
            if response.status_code >= 500:
                raise FixtureError(
                    f"dashboard_url_configured raised an error: Dashboard returned server error {response.status_code}"
                )
        except requests.exceptions.ConnectionError:
            # Dashboard not running - this is expected in test environments
            pass
        except requests.exceptions.Timeout:
            # Dashboard not responding - this is expected in test environments
            pass
        return url
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f"dashboard_url_configured raised an error: {e}") from e


@pytest.fixture
def screenshot_directory_exists() -> Path:
    """
    Given the screenshot directory exists at test_screenshots
    
    Returns the Path to the screenshot directory, creating it if needed.
    Raises FixtureError if the directory cannot be created or accessed.
    """
    try:
        screenshot_dir = Path("test_screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify the directory exists and is accessible
        if not screenshot_dir.exists():
            raise FixtureError(
                f"screenshot_directory_exists raised an error: Directory {screenshot_dir} does not exist"
            )
        if not screenshot_dir.is_dir():
            raise FixtureError(
                f"screenshot_directory_exists raised an error: {screenshot_dir} is not a directory"
            )
        if not os.access(screenshot_dir, os.W_OK):
            raise FixtureError(
                f"screenshot_directory_exists raised an error: Directory {screenshot_dir} is not writable"
            )
        
        return screenshot_dir
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f"screenshot_directory_exists raised an error: {e}") from e
