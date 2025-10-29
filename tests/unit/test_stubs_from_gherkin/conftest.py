"""
Pytest configuration for test stubs directory.

These are template files, not actual tests to run.
They should be excluded from test collection.
"""
import pytest
import glob
import os

# Tell pytest to ignore all Python files in this directory during collection
collect_ignore = glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))

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
