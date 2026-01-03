# UCAN Callables Test Stubs

This directory contains pytest test stub files generated from Gherkin feature specifications for all UCANManager callable methods.

## Overview

These test stubs provide a structured template for implementing actual tests based on the Gherkin specifications in `tests/gherkin_features/ucan_callables/`.

## Structure

Each test stub file corresponds to one Gherkin feature file:

| Test Stub | Gherkin Feature | Method Tested |
|-----------|-----------------|---------------|
| `test_get_instance.py` | `get_instance.feature` | `UCANManager.get_instance()` |
| `test_initialize.py` | `initialize.feature` | `UCANManager.initialize()` |
| `test_generate_keypair.py` | `generate_keypair.feature` | `UCANManager.generate_keypair()` |
| `test_import_keypair.py` | `import_keypair.feature` | `UCANManager.import_keypair()` |
| `test_get_keypair.py` | `get_keypair.feature` | `UCANManager.get_keypair()` |
| `test_create_token.py` | `create_token.feature` | `UCANManager.create_token()` |
| `test_verify_token.py` | `verify_token.feature` | `UCANManager.verify_token()` |
| `test_revoke_token.py` | `revoke_token.feature` | `UCANManager.revoke_token()` |
| `test_get_token.py` | `get_token.feature` | `UCANManager.get_token()` |
| `test_get_capabilities.py` | `get_capabilities.feature` | `UCANManager.get_capabilities()` |
| `test_has_capability.py` | `has_capability.feature` | `UCANManager.has_capability()` |
| `test_delegate_capability.py` | `delegate_capability.feature` | `UCANManager.delegate_capability()` |

## Format

Each test stub file follows this pattern:

### 1. Module Docstring
Contains the feature description from the Gherkin file.

### 2. Imports
```python
import pytest
```

### 3. Background Fixtures
Each line from the Gherkin Background section becomes a pytest fixture:
```python
@pytest.fixture
def a_ucanmanager_instance_is_initialized():
    """
    Given a UCANManager instance is initialized
    """
    # TODO: Implement fixture
    pass
```

### 4. Test Functions
Each Gherkin scenario becomes a test function:
- **Function name**: Derived from the scenario name (snake_case with `test_` prefix)
- **Parameters**: All background fixtures are passed as parameters
- **Docstring**: Contains the full Gherkin scenario (Given/When/Then clauses)
- **Body**: Placeholder with `# TODO: Implement test`

Example:
```python
def test_first_call_to_get_instance_returns_ucan_manager_instance(ucan_manager_class_is_imported):
    """
    Scenario: First call to get_instance returns UCANManager instance
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then a UCANManager instance is returned
    """
    # TODO: Implement test
    pass
```

## Statistics

- **Total test stub files**: 12 (plus 1 `__init__.py`)
- **Total lines of code**: 3,352
- **Total test functions**: 216+ (matches number of Gherkin scenarios)
- **Total fixtures**: ~30 (from all Background sections)

## Usage

To implement a test:

1. **Implement the fixtures**: Replace the `pass` statements in fixtures with actual setup code
2. **Implement the test**: Replace the `pass` statement in the test function with:
   - Arrange: Use the fixtures to set up test state
   - Act: Execute the method being tested
   - Assert: Verify the expected outcome from the Then clause

Example implementation:
```python
@pytest.fixture
def ucan_manager_class_is_imported():
    """
    Given the UCANManager class is imported
    """
    from ipfs_datasets_py.ucan import UCANManager
    return UCANManager

def test_first_call_to_get_instance_returns_ucan_manager_instance(ucan_manager_class_is_imported):
    """
    Scenario: First call to get_instance returns UCANManager instance
    
    Given the UCANManager class is imported
    When get_instance() is called for the first time
    Then a UCANManager instance is returned
    """
    UCANManager = ucan_manager_class_is_imported
    
    # When
    instance = UCANManager.get_instance()
    
    # Then
    assert isinstance(instance, UCANManager)
```

## Running Tests

Once implemented, run tests with:
```bash
# Run all UCAN callable tests
pytest tests/unit/test_stubs_from_gherkin/ucan_callables/

# Run a specific test file
pytest tests/unit/test_stubs_from_gherkin/ucan_callables/test_get_instance.py

# Run a specific test
pytest tests/unit/test_stubs_from_gherkin/ucan_callables/test_get_instance.py::test_first_call_to_get_instance_returns_ucan_manager_instance
```

## Notes

- All test stubs are generated from Gherkin specifications
- Each scenario has a single GIVEN, WHEN, and THEN clause (no AND after THEN)
- Fixtures are derived from Background steps
- All code is currently stub implementations (marked with `# TODO`)
- Test function names are sanitized versions of scenario names
- Fixture names are sanitized versions of Given clauses

## Maintenance

These test stubs should be kept in sync with the Gherkin feature files. If the Gherkin specifications change:

1. Regenerate the test stubs using the generation script
2. Merge any implemented test code from the old stubs into the new stubs
3. Update fixtures as needed to match new Background steps
