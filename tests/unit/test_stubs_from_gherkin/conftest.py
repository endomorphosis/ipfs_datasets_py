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
    # Remove only collected items from this stub/template directory.
    # This conftest is imported for the whole run, so we must not clear
    # unrelated tests from other directories.
    stubs_root = Path(__file__).resolve().parent

    kept_items = []
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except Exception:
            kept_items.append(item)
            continue

        if item_path.is_relative_to(stubs_root):
            continue
        kept_items.append(item)

    items[:] = kept_items


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
    raise NotImplementedError


@pytest.fixture
def dashboard_url_configured() -> str:
    """
    Given the dashboard URL is http://localhost:8899/mcp
    
    Returns the configured dashboard URL. Checks if the URL is accessible.
    """
    raise NotImplementedError


@pytest.fixture
def screenshot_directory_exists() -> Path:
    """
    Given the screenshot directory exists at test_screenshots
    
    Returns the Path to the screenshot directory, creating it if needed.
    Raises FixtureError if the directory cannot be created or accessed.
    """
    raise NotImplementedError
