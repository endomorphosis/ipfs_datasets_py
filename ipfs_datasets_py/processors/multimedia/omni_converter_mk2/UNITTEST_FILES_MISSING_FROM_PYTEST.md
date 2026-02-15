# Unittest Files Missing from Pytest

This document lists the test files that exist in the unittest test suite (`tests/` directory) but are not present in the pytest test suites (`test_pytest/` and `tests_pytest/` directories).

## Summary

- **Total unittest files**: 44
- **Total unique pytest files**: 43  
- **Unittest files missing from pytest**: 10

## Missing Files

The following unittest files do not have corresponding pytest equivalents:

### Integration Tests
- `integration_tests/pipelines/test_json_pipeline.py`

### Performance Tests
- `performance_tests/test_skeleton_error_handling.py`
- `performance_tests/test_skeleton_format_support_coverage.py`
- `performance_tests/test_skeleton_processing_speed.py`
- `performance_tests/test_skeleton_processing_success_rate.py`
- `performance_tests/test_skeleton_resource_utilization.py`
- `performance_tests/test_skeleton_security_effectiveness.py`
- `performance_tests/test_skeleton_text_quality.py`

### Unit Tests
- `unit_tests/monitors_/test_resource_monitor.py`
- `unit_tests/monitors_/test_security_monitor.py`

## Analysis

The missing files are primarily in the performance testing category (7 out of 10 files), with 2 monitor unit tests and 1 integration test also missing pytest equivalents. The performance tests appear to be skeleton/placeholder tests based on their naming convention.