# Knowledge Graphs - Test Guide

**Last Updated:** 2026-02-18  
**Purpose:** Guide to testing the knowledge_graphs module

---

## Overview

The knowledge_graphs module has **43 test files** covering **116+ tests** with an overall **75% coverage** rate. This guide helps developers understand what's tested, how to run tests, and where to add new tests.

---

## Test Statistics

### Overall Coverage
- **Total Test Files:** 43
- **Total Tests:** 116+
- **Pass Rate:** 94%+ (excluding intentional skips)
- **Overall Coverage:** ~75%

### Coverage by Module

| Module | Unit Tests | Integration Tests | Coverage | Status |
|--------|------------|-------------------|----------|--------|
| **Extraction** | 15 | 3 | 85% | ✅ Excellent |
| **Cypher** | 12 | 3 | 80% | ✅ Good |
| **Query** | 8 | 2 | 80% | ✅ Good |
| **Core** | 10 | 2 | 75% | ✅ Good |
| **Storage** | 6 | 2 | 70% | ✅ Good |
| **Neo4j Compat** | 8 | 2 | 85% | ✅ Excellent |
| **Transactions** | 7 | 2 | 75% | ✅ Good |
| **Migration** | 27 | 3 | 40% | ⚠️ Needs improvement |
| **Lineage** | 5 | 2 | 70% | ✅ Good |
| **Indexing** | 6 | 1 | 75% | ✅ Good |
| **JSON-LD** | 8 | 2 | 80% | ✅ Good |
| **Constraints** | 4 | 1 | 70% | ✅ Good |

---

## Running Tests

### Quick Start

```bash
# Run all knowledge_graphs tests
pytest tests/knowledge_graphs/

# Run with coverage
pytest tests/knowledge_graphs/ --cov=ipfs_datasets_py.knowledge_graphs --cov-report=html

# Run specific module tests
pytest tests/knowledge_graphs/extraction/
pytest tests/knowledge_graphs/cypher/
pytest tests/knowledge_graphs/migration/

# Run unit tests only
pytest tests/unit_tests/knowledge_graphs/

# Run integration tests only
pytest tests/integration/knowledge_graphs/
```

### Running Specific Test Categories

```bash
# Fast tests only (exclude slow tests)
pytest tests/knowledge_graphs/ -m "not slow"

# GPU tests only
pytest tests/knowledge_graphs/ -m gpu

# Integration tests
pytest tests/knowledge_graphs/ -m integration

# Unit tests
pytest tests/knowledge_graphs/ -m unit
```

### Parallel Execution

```bash
# Use all CPU cores
pytest tests/knowledge_graphs/ -n auto

# Use 4 workers
pytest tests/knowledge_graphs/ -n 4
```

---

## Test Organization

### Directory Structure

```
tests/
├── unit_tests/knowledge_graphs/       # Unit tests (individual components)
│   ├── test_extraction.py
│   ├── test_cypher_compiler.py
│   ├── test_query_engine.py
│   ├── test_storage_backend.py
│   └── ...
├── integration/knowledge_graphs/      # Integration tests (component interactions)
│   ├── test_graphrag_integration.py
│   ├── test_end_to_end_workflow.py
│   ├── test_neo4j_migration.py
│   └── ...
├── e2e/knowledge_graphs/              # End-to-end tests (full workflows)
│   └── test_complete_pipeline.py
└── performance/knowledge_graphs/      # Performance benchmarks
    └── test_large_graph_operations.py
```

---

## Test Categories

### 1. Extraction Tests (85% coverage)

**What's Tested:**
- Entity extraction from text
- Relationship extraction
- Wikipedia enrichment
- SPARQL validation
- Error handling
- Edge cases (empty text, special characters)

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_extraction.py`
- `tests/unit_tests/knowledge_graphs/test_entity_extraction.py`
- `tests/integration/knowledge_graphs/test_extraction_pipeline.py`

**Example:**
```python
def test_entity_extraction_basic():
    """Test basic entity extraction from simple text."""
    extractor = KnowledgeGraphExtractor()
    text = "Marie Curie was a physicist at the University of Paris."
    kg = extractor.extract_knowledge_graph(text)
    
    assert len(kg.entities) >= 2
    assert any(e.name == "Marie Curie" for e in kg.entities)
    assert any(e.name == "University of Paris" for e in kg.entities)
```

---

### 2. Cypher Tests (80% coverage)

**What's Tested:**
- Query compilation
- Query execution
- MATCH/WHERE/RETURN clauses
- Aggregations (COUNT, SUM, AVG)
- Property access
- Error handling

**What's NOT Tested (Intentionally):**
- NOT operator (not yet implemented - v2.1.0)
- CREATE relationships (not yet implemented - v2.1.0)

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_cypher_compiler.py`
- `tests/unit_tests/knowledge_graphs/test_cypher_execution.py`
- `tests/integration/knowledge_graphs/test_cypher_queries.py`

**Example:**
```python
def test_cypher_match_where_return():
    """Test basic Cypher query execution."""
    query = """
    MATCH (p:Person)
    WHERE p.age > 30
    RETURN p.name, p.age
    """
    result = engine.execute(query)
    assert all(row["p.age"] > 30 for row in result)
```

---

### 3. Migration Tests (40% coverage) ⚠️

**What's Tested:**
- CSV import/export
- JSON import/export
- RDF import/export
- Basic error handling

**What's NOT Tested (Intentionally):**
- GraphML format (not yet implemented - v2.2.0)
- GEXF format (not yet implemented - v2.2.0)
- Pajek format (not yet implemented - v2.2.0)
- CAR format (not yet implemented - v2.2.0)

**Coverage Gap Reason:**
- Tests for unimplemented formats are intentionally skipped
- Need more edge case tests for implemented formats
- Need more error handling tests

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_migration_csv.py`
- `tests/unit_tests/knowledge_graphs/test_migration_json.py`
- `tests/unit_tests/knowledge_graphs/test_migration_rdf.py`
- `tests/integration/knowledge_graphs/test_migration_roundtrip.py`

**Example:**
```python
def test_csv_export_import_roundtrip():
    """Test that exporting and re-importing preserves graph structure."""
    # Create original graph
    original = KnowledgeGraph()
    original.add_entity(Entity("Alice", "Person"))
    original.add_entity(Entity("Bob", "Person"))
    original.add_relationship(Relationship("Alice", "Bob", "KNOWS"))
    
    # Export to CSV
    save_to_file(original, "test.csv", format="csv")
    
    # Import back
    imported = load_from_file("test.csv", format="csv")
    
    # Verify structure preserved
    assert len(imported.entities) == len(original.entities)
    assert len(imported.relationships) == len(original.relationships)
```

**What's Needed (v2.0.1):**
- Error handling tests (malformed input, invalid format)
- Edge case tests (empty graphs, very large graphs, unicode)
- Format-specific tests (different CSV delimiters, nested JSON)

---

### 4. Storage Tests (70% coverage)

**What's Tested:**
- IPLD backend operations (add, get, pin)
- Write-ahead log
- Transaction commit/rollback
- Cache operations
- Error recovery

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_storage_backend.py`
- `tests/unit_tests/knowledge_graphs/test_ipld_operations.py`
- `tests/integration/knowledge_graphs/test_storage_integrity.py`

---

### 5. Neo4j Compatibility Tests (85% coverage)

**What's Tested:**
- Driver API compatibility
- Session management
- Transaction support
- Query execution
- Result formatting

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_neo4j_driver.py`
- `tests/integration/knowledge_graphs/test_neo4j_migration.py`

---

### 6. Transaction Tests (75% coverage)

**What's Tested:**
- ACID guarantees
- Commit/rollback operations
- Conflict detection
- Isolation levels
- Concurrent transactions

**Key Test Files:**
- `tests/unit_tests/knowledge_graphs/test_transactions.py`
- `tests/integration/knowledge_graphs/test_concurrent_transactions.py`

---

## Skipped Tests

### Intentionally Skipped (13 tests)

**Reason:** Optional dependencies not available

```python
# Example skip patterns:
@pytest.mark.skipif(not HAS_REPORTLAB, reason="reportlab not available")
def test_pdf_export():
    """Test PDF export functionality."""
    pass

@pytest.mark.skipif(not HAS_TRANSFORMERS, reason="transformers not available")
def test_neural_extraction():
    """Test neural relationship extraction."""
    pass

@pytest.mark.skipif(not HAS_NLTK_DATA, reason="NLTK data not available")
def test_nltk_features():
    """Test NLTK-based text processing."""
    pass
```

**Categories:**
- **PDF creation tests** (3 tests) - requires `reportlab`
- **Neural extraction tests** (4 tests) - requires `transformers`
- **Advanced NLP tests** (6 tests) - requires NLTK data

**These are NOT failures** - they're optional enhancements that skip gracefully when dependencies aren't installed.

---

## Adding New Tests

### Test Template

```python
import pytest
from ipfs_datasets_py.knowledge_graphs import KnowledgeGraphExtractor

class TestFeatureName:
    """Test suite for specific feature."""
    
    def test_basic_functionality(self):
        """Test basic case - should always pass."""
        # Given
        extractor = KnowledgeGraphExtractor()
        text = "Simple test input."
        
        # When
        result = extractor.extract_knowledge_graph(text)
        
        # Then
        assert result is not None
        assert len(result.entities) > 0
    
    def test_edge_case_empty_input(self):
        """Test edge case - empty input."""
        # Given
        extractor = KnowledgeGraphExtractor()
        text = ""
        
        # When
        result = extractor.extract_knowledge_graph(text)
        
        # Then
        assert result is not None
        assert len(result.entities) == 0
    
    def test_error_handling(self):
        """Test error handling - invalid input."""
        # Given
        extractor = KnowledgeGraphExtractor()
        
        # When/Then
        with pytest.raises(ValueError):
            extractor.extract_knowledge_graph(None)
    
    @pytest.mark.slow
    def test_performance_large_input(self):
        """Test performance with large input."""
        # Given
        extractor = KnowledgeGraphExtractor()
        text = "Large text input " * 10000
        
        # When
        import time
        start = time.time()
        result = extractor.extract_knowledge_graph(text)
        duration = time.time() - start
        
        # Then
        assert duration < 10.0  # Should complete in <10 seconds
        assert result is not None
```

### Where to Add Tests

**For Unit Tests:**
- Add to `tests/unit_tests/knowledge_graphs/test_<module>.py`
- Create new file if testing new module

**For Integration Tests:**
- Add to `tests/integration/knowledge_graphs/test_<feature>.py`
- Create new file if testing new integration scenario

**For Performance Tests:**
- Add to `tests/performance/knowledge_graphs/test_<operation>.py`

---

## Test Markers

### Available Markers

```python
@pytest.mark.unit            # Unit test
@pytest.mark.integration     # Integration test
@pytest.mark.slow           # Slow test (>5 seconds)
@pytest.mark.gpu            # Requires GPU
@pytest.mark.optional       # Optional dependency required
```

### Usage

```python
@pytest.mark.slow
@pytest.mark.integration
def test_large_graph_migration():
    """Test migrating a large graph (>100k nodes)."""
    # Test implementation
    pass
```

---

## Coverage Targets

### Current (v2.0.0)
- **Overall:** 75%
- **Critical modules:** 80-85%
- **Migration:** 40%

### Target (v2.0.1)
- **Overall:** 75-80%
- **Critical modules:** 80-85%
- **Migration:** 70%+

### Target (v2.1.0)
- **Overall:** 80%+
- **All modules:** 75%+
- **New features (NOT, CREATE):** 90%+

---

## Common Test Patterns

### Pattern 1: Basic Functionality

```python
def test_basic_operation():
    """Test that basic operation works."""
    # Given - Setup
    component = Component()
    
    # When - Execute
    result = component.do_something()
    
    # Then - Verify
    assert result is not None
    assert result.property == expected_value
```

### Pattern 2: Error Handling

```python
def test_error_handling():
    """Test that errors are handled correctly."""
    component = Component()
    
    with pytest.raises(ExpectedError):
        component.do_something_invalid()
```

### Pattern 3: Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("simple", 1),
    ("complex text", 2),
    ("", 0),
])
def test_multiple_cases(input, expected):
    """Test multiple cases with same logic."""
    result = extract_entities(input)
    assert len(result) == expected
```

### Pattern 4: Fixtures

```python
@pytest.fixture
def sample_graph():
    """Create a sample graph for testing."""
    kg = KnowledgeGraph()
    kg.add_entity(Entity("Alice", "Person"))
    kg.add_entity(Entity("Bob", "Person"))
    kg.add_relationship(Relationship("Alice", "Bob", "KNOWS"))
    return kg

def test_using_fixture(sample_graph):
    """Test using the fixture."""
    assert len(sample_graph.entities) == 2
```

---

## CI/CD Integration

### Automated Testing

Tests run automatically on:
- Every push to main branch
- Every pull request
- Nightly builds

### GitHub Actions Workflow

```yaml
- name: Run knowledge_graphs tests
  run: |
    pytest tests/knowledge_graphs/ \
      --cov=ipfs_datasets_py.knowledge_graphs \
      --cov-report=xml \
      --cov-report=html \
      -n auto
```

---

## Debugging Failed Tests

### Step 1: Run Specific Test

```bash
# Run only the failing test
pytest tests/knowledge_graphs/test_file.py::test_function -v

# With full output
pytest tests/knowledge_graphs/test_file.py::test_function -vv -s
```

### Step 2: Check Test Logs

```bash
# Run with more detailed logging
pytest tests/knowledge_graphs/test_file.py::test_function --log-cli-level=DEBUG
```

### Step 3: Use pytest Debugger

```bash
# Drop into debugger on failure
pytest tests/knowledge_graphs/test_file.py::test_function --pdb
```

---

## Performance Testing

### Running Performance Tests

```bash
# Run performance tests only
pytest tests/performance/knowledge_graphs/ -v

# Run with profiling
pytest tests/performance/knowledge_graphs/ --profile
```

### Benchmarking

```bash
# Install pytest-benchmark
pip install pytest-benchmark

# Run benchmarks
pytest tests/performance/knowledge_graphs/test_benchmarks.py --benchmark-only
```

---

## Contributing Tests

### Before Adding Tests
1. Check if similar test already exists
2. Ensure test follows existing patterns
3. Add appropriate markers (@pytest.mark.unit, etc.)
4. Update this guide if adding new test category

### Test Quality Checklist
- [ ] Test has clear docstring
- [ ] Test follows GIVEN-WHEN-THEN pattern
- [ ] Test is independent (no test dependencies)
- [ ] Test uses appropriate fixtures
- [ ] Test has meaningful assertions
- [ ] Test includes error handling if applicable

---

## See Also

- [Knowledge Graphs README](../../ipfs_datasets_py/knowledge_graphs/README.md)
- [IMPLEMENTATION_STATUS.md](../../ipfs_datasets_py/knowledge_graphs/IMPLEMENTATION_STATUS.md)
- [CONTRIBUTING.md](../../docs/knowledge_graphs/CONTRIBUTING.md)
- [NEW_COMPREHENSIVE_IMPROVEMENT_PLAN](../../ipfs_datasets_py/knowledge_graphs/NEW_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md)

---

**Last Updated:** 2026-02-18  
**Next Review:** Q2 2026 (after v2.0.1 test improvements)  
**Maintainer:** Knowledge Graphs Team
