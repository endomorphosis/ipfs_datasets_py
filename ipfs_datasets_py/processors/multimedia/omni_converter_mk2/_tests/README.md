# Omni Converter Test Suite Documentation

This directory contains documentation and fixtures for the end-to-end text conversion pipeline. The links below point to the maintained tests and implementation modules for each test category.

## Test Categories

### 1. [Core Functionality Tests](../tests_pytest/test_working_examples.py)
- Basic conversion tests across all formats
- Empty and minimal file handling
- Data structure variation tests

### 2. [Edge Cases and Error Handling](../tests_pytest/performance_tests/test_skeleton_error_handling.py)
- Malformed input handling
- File system operation tests
- Large file and performance tests

### 3. [Batch Processing Tests](../batch_processor/)
- Directory operation tests
- Batch result tracking and reporting

### 4. [Configuration Tests](../configs.py)
- Output configuration options
- Processing configuration settings

### 5. [Format Detection and Validation](../file_format_detector/)
- Automatic format detection
- Content validation (pre/post conversion)

### 6. [API Behavior Tests](../interfaces/)
- Method signature validation
- State management and thread safety

### 7. [Integration Tests](../tests_pytest/integration_tests/)
- Cross-format conversion matrix
- System integration points

### 8. [Error Recovery and Resilience](../monitors/)
- Failure handling mechanisms
- Recovery strategies

### 9. [User Experience Tests](../interfaces/)
- Error message quality
- Feedback mechanisms

### 10. [Extensibility Tests](../utils/plugin_discovery.py)
- Plugin system functionality

## Directory Structure

```
_tests/
├── README.md (this file)
├── _test_files/                 # Shared input fixtures
├── integration_tests/           # Integration coverage
├── performance_tests/           # Performance and resilience coverage
├── skeleton_tests/              # Test skeletons
└── unit_tests/                  # Unit-test package

tests_pytest/
├── integration_tests/           # Pytest integration coverage
├── performance_tests/           # Pytest performance coverage
├── skeleton_tests/              # Pytest skeletons
└── test_working_examples.py     # End-to-end examples
```

## Usage

The test modules contain the executable test cases and their docstrings. The `_test_files/` directory contains shared sample inputs used by those tests.

## Implementation Notes

- Tests should be independent and idempotent
- Use fixtures for common setup/teardown
- Mock external dependencies where appropriate
- Measure and assert on performance metrics
- Generate test reports with coverage information
- Consider parameterized tests for format combinations
