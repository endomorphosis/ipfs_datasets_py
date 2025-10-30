"""
Pytest configuration for test stubs directory.

Some files are templates/stubs, others are implemented tests.
Files marked as implemented (in TODO.md) will be run, others are skipped.
"""
import pytest
import glob
import os

# List of implemented test files that should be collected and run
IMPLEMENTED_TESTS = {
    "test_audit.py",
    "test___init__.py",
    "test__dependencies.py",
    "test_auto_installer.py",
    "test_config.py",
    "test_security.py",
    "test_dataset_manager.py",
    "test_monitoring.py",
    "test_car_conversion.py",
    "test_jsonnet_utils.py",
}

# Tell pytest to ignore stub files (not yet implemented)
_this_dir = os.path.dirname(__file__)
_all_test_files = set(os.path.basename(f) for f in glob.glob(os.path.join(_this_dir, "test_*.py")))
_stub_files = _all_test_files - IMPLEMENTED_TESTS

collect_ignore = [os.path.join(_this_dir, f) for f in _stub_files]

def pytest_collection_modifyitems(config, items):
    """
    Keep only items from implemented test files.
    
    Stub/template files should not be run.
    Implemented files (listed in IMPLEMENTED_TESTS) will be run.
    """
    # Filter out items from non-implemented test files
    items_to_keep = []
    for item in items:
        # Get the test file name
        test_file = os.path.basename(item.fspath)
        if test_file in IMPLEMENTED_TESTS:
            items_to_keep.append(item)
    
    # Replace items list with filtered list
    items[:] = items_to_keep

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "stub: mark test as a stub/template (not to be run)"
    )
    config.addinivalue_line(
        "markers", "implemented: mark test as implemented and ready to run"
    )
