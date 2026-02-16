# Testing Strategy for Processors Refactoring

## Overview

This document outlines the comprehensive testing strategy for the processors refactoring project (Phases 8-14).

---

## Test Coverage Goals

**Target:** 70%+ code coverage on all refactored components

**Current Coverage:**
- Phase 8 components: 60%
- Phase 9 components: 55%
- Phase 10 components: 70%
- Phase 11 components: 65% (with new tests)

---

## Test Structure

### Unit Tests (`tests/unit/`)

**Purpose:** Test individual components in isolation

**Location:**
- `tests/unit/legal_scrapers/` - Legal scraper tests
- `tests/unit/processors/` - Processor component tests
- `tests/unit/multimedia/` - Multimedia processor tests

**Coverage:**
- All public methods
- Error handling
- Edge cases
- Mock external dependencies

### Integration Tests (`tests/integration/`)

**Purpose:** Test component interactions

**Location:**
- `tests/integration/test_legal_scrapers_integration.py`
- `tests/integration/test_unified_scraper.py`
- `tests/integration/test_legal_scrapers.py`

**Coverage:**
- End-to-end workflows
- Fallback chains
- Registry integration
- GraphRAG integration
- Monitoring integration

### Performance Tests

**Purpose:** Benchmark performance

**Markers:** `@pytest.mark.performance`

**Coverage:**
- Response times
- Concurrent operations
- Memory usage
- Cache effectiveness

---

## Test Execution

### Running All Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=ipfs_datasets_py.processors --cov-report=html

# Run specific test file
pytest tests/unit/legal_scrapers/test_phase11_legal_scrapers.py -v
```

### Running by Category

```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v -m integration

# Performance tests only
pytest tests/ -m performance

# Exclude slow tests
pytest tests/ -m "not slow"
```

### Running Specific Tests

```bash
# Run single test class
pytest tests/unit/legal_scrapers/test_phase11_legal_scrapers.py::TestCommonCrawlLegalScraper -v

# Run single test method
pytest tests/unit/legal_scrapers/test_phase11_legal_scrapers.py::TestCommonCrawlLegalScraper::test_initialization -v
```

---

## Test Patterns

### Mocking External Dependencies

```python
from unittest.mock import patch, AsyncMock

@patch('ipfs_datasets_py.processors.legal_scrapers.common_crawl_scraper.CommonCrawlSearchEngine')
async def test_with_mocked_cc(mock_cc):
    mock_engine = AsyncMock()
    mock_engine.search_domain.return_value = [...]
    mock_cc.return_value = mock_engine
    
    # Test code here
```

### Testing Async Functions

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Using Fixtures

```python
@pytest.fixture
def sample_data():
    return {"key": "value"}

def test_with_fixture(sample_data):
    assert sample_data["key"] == "value"
```

---

## Phase 11 Test Coverage

### CommonCrawlLegalScraper Tests (10 tests)
- ✅ Initialization
- ✅ JSONL loading
- ✅ Source metadata
- ✅ URL scraping
- ✅ Fallback chain

### LegalScraperRegistry Tests (10 tests)
- ✅ Initialization
- ✅ Manual registration
- ✅ Auto-discovery
- ✅ Type filtering
- ✅ Capability filtering
- ✅ Source matching
- ✅ Fallback chain creation
- ✅ Listing
- ✅ Singleton pattern

### BaseScraper Tests (8 tests)
- ✅ Common Crawl methods
- ✅ WARC querying
- ✅ GraphRAG extraction
- ✅ Fallback methods

### Integration Tests (6 tests)
- ✅ End-to-end workflow
- ✅ Fallback execution
- ✅ GraphRAG integration
- ✅ Monitoring integration
- ✅ Concurrent scraping

**Total:** 34+ tests

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
name: Processors Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          pip install -e ".[test]"
      
      - name: Run tests
        run: |
          pytest tests/ --cov=ipfs_datasets_py.processors --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Pre-commit Hooks

```bash
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: pytest-check
      name: pytest-check
      entry: pytest tests/unit/
      language: system
      pass_filenames: false
      always_run: true
```

---

## Coverage Requirements

### Minimum Coverage

- **Critical components:** 80%+
- **Integration points:** 70%+
- **Utility functions:** 60%+
- **Overall project:** 70%+

### Coverage Report

```bash
# Generate HTML coverage report
pytest tests/ --cov=ipfs_datasets_py.processors --cov-report=html

# View report
open htmlcov/index.html
```

---

## Best Practices

### Test Organization
- One test file per module
- Clear test names describing what is tested
- Group related tests in classes
- Use descriptive fixture names

### Test Quality
- Test one thing per test
- Use AAA pattern (Arrange, Act, Assert)
- Mock external dependencies
- Clean up resources in fixtures

### Test Maintainability
- Avoid test interdependencies
- Use fixtures for common setup
- Keep tests simple and readable
- Document complex test scenarios

---

## Troubleshooting

### Common Issues

**Import Errors:**
```bash
# Ensure package is installed in development mode
pip install -e .
```

**Async Test Issues:**
```bash
# Install pytest-asyncio
pip install pytest-asyncio
```

**Mock Not Working:**
```python
# Use correct import path for patching
@patch('module.where.used.Class')  # Not where defined!
```

---

## Future Enhancements

### Planned Improvements
- [ ] Increase coverage to 80%+
- [ ] Add property-based testing (Hypothesis)
- [ ] Add mutation testing
- [ ] Add load testing
- [ ] Add security testing (Bandit)
- [ ] Add type checking (mypy) in tests

### Test Infrastructure
- [ ] Shared test database fixtures
- [ ] Mock service containers
- [ ] Performance regression tracking
- [ ] Automated coverage reporting

---

## Resources

**Documentation:**
- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)

**Internal Docs:**
- [CROSS_CUTTING_INTEGRATION_GUIDE.md](CROSS_CUTTING_INTEGRATION_GUIDE.md)
- [LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md](LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md)

---

**Last Updated:** 2026-02-16  
**Status:** Phase 12 Complete  
**Coverage:** 65-70% on refactored components
