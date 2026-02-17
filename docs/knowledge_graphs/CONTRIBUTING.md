# Knowledge Graphs - Contributing Guide

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

## Overview

Guidelines for contributing to the knowledge graphs module.

## Development Setup

### Prerequisites

- Python 3.12+
- Git
- IPFS daemon (optional, for storage tests)

### Installation

```bash
# Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Install in development mode with all extras
pip install -e ".[knowledge_graphs,test]"

# Install spaCy model
python -m spacy download en_core_web_sm

# Verify installation
python -c "from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor"
```

## Code Style

### Python Style Guide

Follow PEP 8 with these specific requirements:

**Imports:**
```python
# Standard library
import os
from typing import Dict, List, Optional

# Third-party
import spacy
from transformers import pipeline

# Local
from ipfs_datasets_py.knowledge_graphs.extraction import Entity
```

**Type Hints:**
```python
def extract_entities(text: str, min_confidence: float = 0.8) -> List[Entity]:
    """Extract entities from text.
    
    Args:
        text: Input text to process
        min_confidence: Minimum confidence threshold
        
    Returns:
        List of extracted entities
        
    Raises:
        EntityExtractionError: If extraction fails
    """
    pass
```

**Docstrings:**
Use Google-style docstrings for all public functions and classes.

### Documentation Standards

**Module READMEs:**
Each subdirectory should have a README.md with:
1. Overview
2. Core Components
3. Usage Examples (3-5)
4. API Reference
5. Error Handling
6. Performance Tips
7. See Also

**Code Comments:**
- Explain WHY, not WHAT
- Document complex algorithms
- Mark intentional no-ops with clear explanations

## Testing

### Running Tests

```bash
# Run all knowledge graphs tests
pytest tests/unit/knowledge_graphs/ -v

# Run specific test file
pytest tests/unit/knowledge_graphs/test_extraction.py -v

# Run with coverage
pytest tests/unit/knowledge_graphs/ --cov=ipfs_datasets_py.knowledge_graphs --cov-report=html
```

### Writing Tests

Follow GIVEN-WHEN-THEN pattern:

```python
def test_entity_extraction():
    # GIVEN: Input text with known entities
    text = "Marie Curie won the Nobel Prize in Physics."
    extractor = KnowledgeGraphExtractor()
    
    # WHEN: Extracting entities
    graph = extractor.extract(text)
    
    # THEN: Expect correct entities
    assert len(graph.entities) >= 2
    entity_names = [e.name for e in graph.entities]
    assert "Marie Curie" in entity_names
    assert "Nobel Prize" in entity_names
```

### Test Coverage

Target: >85% coverage for all modules

Current coverage:
- extraction/: 85%+
- query/: 80%+
- storage/: 80%+
- transactions/: 80%+
- migration/: 60% (needs improvement)

## Pull Request Process

### Before Submitting

1. Run all tests: `pytest tests/unit/knowledge_graphs/ -v`
2. Check code style: `flake8 ipfs_datasets_py/knowledge_graphs/`
3. Run type checking: `mypy ipfs_datasets_py/knowledge_graphs/`
4. Update documentation if needed
5. Add tests for new functionality

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added
- [ ] Coverage maintained/improved

## Documentation
- [ ] README updated if needed
- [ ] Docstrings added/updated
- [ ] Examples updated if needed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] No new warnings generated
```

### Review Process

1. Automated CI checks must pass
2. At least one maintainer approval required
3. Documentation updates reviewed
4. Breaking changes discussed

## Code Patterns

### Exception Handling

Use specific exception types:

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    EntityExtractionError,
    QueryError,
    StorageError
)

try:
    graph = extractor.extract(text)
except EntityExtractionError as e:
    logger.error(f"Extraction failed: {e}")
    logger.debug(f"Details: {e.details}")
    raise
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)

def process_graph(graph):
    logger.info(f"Processing graph with {len(graph.entities)} entities")
    # ... processing ...
    logger.debug(f"Processed {count} relationships")
```

### Resource Management

```python
# Use context managers
with transaction_manager.begin_transaction() as tx:
    tx.add_entity(entity)
    tx.commit()

# Or explicit cleanup
tx = transaction_manager.begin_transaction()
try:
    tx.add_entity(entity)
    tx.commit()
finally:
    if tx.is_active():
        tx.rollback()
```

---

## Advanced Development Patterns

### Multi-Document Knowledge Graphs

Extract and merge knowledge from multiple documents:

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
kg_combined = None

for document in documents:
    doc_kg = extractor.extract_knowledge_graph(document.text)
    if kg_combined is None:
        kg_combined = doc_kg
    else:
        kg_combined.merge(doc_kg)  # Automatic deduplication

print(f"Combined graph: {len(kg_combined.entities)} entities, "
      f"{len(kg_combined.relationships)} relationships")
```

### Extraction Pipeline Pattern

Build robust extraction pipelines:

```python
def extraction_pipeline(text: str):
    """Complete extraction pipeline with validation."""
    # 1. Extract
    kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.7)
    
    # 2. Validate
    if validator:
        result = validator.validate_graph(kg)
        if result['coverage'] < 0.5:
            logger.warning(f"Low validation coverage: {result['coverage']:.1%}")
    
    # 3. Enrich
    kg = enrich_with_types(kg)
    
    # 4. Query/Export
    return kg
```

### Custom Relation Patterns

Define domain-specific relationships:

```python
custom_patterns = [
    {
        "name": "develops",
        "pattern": r"(\w+)\s+develops?\s+(\w+)",
        "source_type": "person",
        "target_type": "technology",
        "confidence": 0.85
    },
    {
        "name": "founded",
        "pattern": r"(\w+)\s+founded\s+(\w+)",
        "source_type": "person",
        "target_type": "organization"
    }
]

extractor = KnowledgeGraphExtractor(relation_patterns=custom_patterns)
```

---

## Performance Guidelines

### Extraction Optimization

#### Temperature Tuning

Choose temperature based on use case:

```python
# Fast extraction (legal documents, strict requirements)
kg = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.3,  # Conservative
    structure_temperature=0.2
)

# Balanced extraction (general content)
kg = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.5,
    structure_temperature=0.5
)

# Comprehensive extraction (research papers)
kg = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.9,  # Detailed
    structure_temperature=0.8
)
```

#### Batch Processing

Process large document collections efficiently:

```python
from concurrent.futures import ProcessPoolExecutor

def extract_parallel(documents, max_workers=4):
    """Parallel extraction with progress tracking."""
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extractor.extract_knowledge_graph, doc.text): doc
            for doc in documents
        }
        
        results = []
        for future in concurrent.futures.as_completed(futures):
            try:
                kg = future.result()
                results.append(kg)
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
        
        return results
```

### Query Optimization

#### Caching Strategy

Implement multi-level caching:

```python
from functools import lru_cache

# L1: Memory cache (fast)
@lru_cache(maxsize=100)
def cached_query(query_hash):
    return engine.execute_cypher(query)

# L2: Disk cache (persistent)
def query_with_disk_cache(query):
    cache_key = hashlib.md5(query.encode()).hexdigest()
    cache_file = f".cache/queries/{cache_key}.json"
    
    if os.path.exists(cache_file):
        return json.load(open(cache_file))
    
    result = engine.execute_cypher(query)
    json.dump(result, open(cache_file, 'w'))
    return result
```

#### Hybrid Search Tuning

Tune weights for your use case:

```python
# Semantic-focused (entity similarity)
result = hybrid.search(
    "machine learning",
    vector_weight=0.8,
    graph_weight=0.2,
    max_hops=1
)

# Structure-focused (graph relationships)
result = hybrid.search(
    "machine learning",
    vector_weight=0.2,
    graph_weight=0.8,
    max_hops=3
)
```

### Performance Profiling

Profile your extraction code:

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your code here
kg = extractor.extract_knowledge_graph(text)

profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

---

## Security Best Practices

### Input Validation

Always validate inputs:

```python
def validate_extraction_input(text: str, max_length: int = 1_000_000) -> bool:
    """Validate text before extraction."""
    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    if len(text) == 0:
        raise ValueError("Text cannot be empty")
    if len(text) > max_length:
        raise ValueError(f"Text exceeds max length of {max_length}")
    return True

# Use in extraction
validate_extraction_input(text)
kg = extractor.extract_knowledge_graph(text)
```

### Type Safety

Use type hints consistently:

```python
from typing import List, Dict, Optional
from ipfs_datasets_py.knowledge_graphs.extraction import Entity, Relationship

def merge_graphs(
    graphs: List[KnowledgeGraph],
    deduplicate: bool = True
) -> KnowledgeGraph:
    """Merge multiple knowledge graphs.
    
    Args:
        graphs: List of graphs to merge
        deduplicate: Whether to deduplicate entities
        
    Returns:
        Merged knowledge graph
        
    Raises:
        ValueError: If graphs list is empty
        TypeError: If any item is not a KnowledgeGraph
    """
    pass
```

### Exception Handling

Use specific exceptions:

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    ExtractionError,
    ValidationError,
    QueryError,
    StorageError
)

try:
    kg = extractor.extract_knowledge_graph(text)
except ExtractionError as e:
    logger.error(f"Extraction failed: {e}")
    raise
except ValidationError as e:
    logger.warning(f"Validation issue: {e}")
    # Continue with unvalidated graph
```

### Resource Cleanup

Always clean up resources:

```python
# Use context managers
with transaction_manager.begin_transaction() as tx:
    tx.add_entity(entity)
    tx.commit()  # Automatic rollback on exception

# Or explicit cleanup
tx = transaction_manager.begin_transaction()
try:
    tx.add_entity(entity)
    tx.commit()
except Exception:
    tx.rollback()
    raise
finally:
    tx.close()
```

---

## Common Pitfalls

### Extraction Issues

**Pitfall 1: No Entities Extracted**

Problem: Temperature too low

```python
# ❌ Wrong
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.1)

# ✅ Correct
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.7)
```

**Pitfall 2: Duplicate Entities**

Problem: Not using graph merge properly

```python
# ❌ Wrong
for entity in kg1.entities.values():
    kg2.add_entity(entity)  # Creates duplicates

# ✅ Correct
kg2.merge(kg1)  # Automatic deduplication
```

**Pitfall 3: Memory Issues with Large Documents**

Problem: Processing without chunking

```python
# ❌ Wrong
kg = extractor.extract_knowledge_graph(large_text)  # Memory intensive

# ✅ Correct
kg = extractor.extract_enhanced_knowledge_graph(
    large_text,
    use_chunking=True  # Automatic chunking
)
```

### Query Pitfalls

**Pitfall 4: No Error Handling**

```python
# ❌ Wrong
result = validator.extract_knowledge_graph(text)
kg = result["knowledge_graph"]  # May fail

# ✅ Correct
result = validator.extract_knowledge_graph(text)
if "error" in result:
    logger.error(f"Validation error: {result['error']}")
    # Handle gracefully
else:
    kg = result["knowledge_graph"]
```

**Pitfall 5: Cache Invalidation**

```python
# ❌ Wrong
result = cached_query(query)  # Stale data possible

# ✅ Correct
cache.clear_cache()  # Clear when data changes
result = query(query)  # Fresh data
```

---

## Module-Specific Conventions

### Directory Structure

Each module should follow:

```
module/
├── __init__.py          # Public API exports
├── README.md            # Module documentation
├── types.py             # Type definitions
├── core.py              # Core functionality
├── utils.py             # Helper functions
└── exceptions.py        # Custom exceptions
```

### Naming Conventions

- **Classes:** PascalCase (e.g., `KnowledgeGraphExtractor`)
- **Functions:** snake_case (e.g., `extract_entities`)
- **Constants:** UPPER_CASE (e.g., `MAX_ENTITIES`)
- **Private:** Prefix with underscore (e.g., `_internal_method`)

### API Patterns

```python
# Extraction methods
extract_*()          # Basic extraction
extract_enhanced_*() # Advanced extraction with features

# Query methods
get_*_by_*()        # Filtering/lookup
find_*()            # Search operations
list_*()            # List all items

# Validation methods
validate_*()        # Validation operations
check_*()           # Boolean checks
```

### Configuration

Use dictionaries for optional configuration:

```python
config = {
    'extraction_temperature': 0.7,
    'structure_temperature': 0.6,
    'enable_validation': True,
    'cache_enabled': True
}

extractor = KnowledgeGraphExtractor(**config)
```

## Documentation Contributions

### Adding Examples

Place examples in appropriate README:
- Module overview → Subdirectory README
- Integration patterns → USER_GUIDE.md
- API usage → API_REFERENCE.md

### Updating Documentation

1. Edit relevant markdown file
2. Update table of contents if structure changed
3. Test all code examples
4. Update cross-references
5. Submit PR with documentation label

---

## Debugging Tips

### Common Debugging Scenarios

#### Scenario 1: No Entities Extracted

**Diagnostic steps:**

```python
# 1. Check input
print(f"Text length: {len(text)}")
print(f"Text preview: {text[:200]}")

# 2. Test with different temperatures
kg_low = extractor.extract_knowledge_graph(text, extraction_temperature=0.3)
kg_high = extractor.extract_knowledge_graph(text, extraction_temperature=0.9)
print(f"Low temp: {len(kg_low.entities)} entities")
print(f"High temp: {len(kg_high.entities)} entities")

# 3. Check raw entity extraction
entities = extractor.extract_entities(text)
print(f"Raw entities: {len(entities)}")
for entity in entities[:5]:
    print(f"  - {entity.name} ({entity.entity_type}, {entity.confidence:.2f})")
```

#### Scenario 2: Query Returns No Results

**Debugging approach:**

```python
# 1. Verify graph contents
print(f"Total entities: {len(kg.entities)}")
print(f"Total relationships: {len(kg.relationships)}")

# 2. List sample entities
for entity in list(kg.entities.values())[:10]:
    print(f"  Entity: '{entity.name}' (type: {entity.entity_type})")

# 3. Check relationships
for rel in list(kg.relationships.values())[:5]:
    print(f"  {rel.source_entity.name} --[{rel.relationship_type}]--> "
          f"{rel.target_entity.name}")

# 4. Test path finding
if len(kg.entities) >= 2:
    entities_list = list(kg.entities.values())
    path = kg.find_path(entities_list[0].entity_id, entities_list[-1].entity_id)
    print(f"Path exists: {path is not None}")
```

#### Scenario 3: Memory Issues

**Investigation:**

```python
import sys

# Check sizes
print(f"Entity count: {len(kg.entities)}")
print(f"Relationship count: {len(kg.relationships)}")
print(f"Avg entity size: {sum(sys.getsizeof(e) for e in kg.entities.values()) / len(kg.entities):.0f} bytes")

# Use chunking for large documents
if len(text) > 10000:
    kg = extractor.extract_enhanced_knowledge_graph(
        text,
        use_chunking=True
    )
```

#### Scenario 4: Validation Failures

**Debug validation:**

```python
result = validator.extract_knowledge_graph(text, validation_depth=2)

# Check coverage
print(f"Validation coverage: {result['validation_metrics']['overall_coverage']:.2%}")

# Identify issues
if "corrections" in result:
    print("Corrections made:")
    for entity_id, correction in result["corrections"].get("entities", {}).items():
        print(f"  Entity {entity_id}: {correction}")
```

### Enable Debug Logging

```python
import logging

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kg_debug.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('ipfs_datasets_py.knowledge_graphs')
```

### Performance Debugging

```python
import time

# Time extraction
start = time.time()
kg = extractor.extract_knowledge_graph(text)
elapsed = time.time() - start
print(f"Extraction took {elapsed:.2f}s for {len(kg.entities)} entities")
print(f"Rate: {len(kg.entities) / elapsed:.1f} entities/sec")

# Profile with cProfile
import cProfile
profiler = cProfile.Profile()
profiler.enable()
kg = extractor.extract_knowledge_graph(text)
profiler.disable()
profiler.print_stats(sort='cumulative')
```

---

## Release Process

### Pre-Release Checklist

**1. Code Quality**

```bash
# Run all tests
pytest tests/unit/knowledge_graphs/ -v --cov=ipfs_datasets_py.knowledge_graphs

# Generate coverage report (target: >85%)
pytest --cov-report=html
open htmlcov/index.html

# Code style
flake8 ipfs_datasets_py/knowledge_graphs/
black ipfs_datasets_py/knowledge_graphs/ --check

# Type checking
mypy ipfs_datasets_py/knowledge_graphs/
```

**2. Documentation**

- [ ] Update API documentation
- [ ] Update usage examples
- [ ] Update module READMEs
- [ ] Update CHANGELOG.md
- [ ] Document breaking changes in MIGRATION_GUIDE.md

**3. Compatibility**

- [ ] Test backward compatibility
- [ ] Verify legacy imports work
- [ ] Check deprecation warnings
- [ ] Test with Python 3.10, 3.11, 3.12

**4. Performance**

- [ ] Run performance benchmarks
- [ ] Compare with previous release
- [ ] Document any regressions

### Release Steps

**1. Update Version**

```python
# In setup.py and ipfs_datasets_py/__init__.py
__version__ = "X.Y.Z"  # Semantic versioning
```

**2. Update Changelog**

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New feature descriptions

### Fixed
- Bug fix descriptions

### Changed
- Breaking change descriptions

### Deprecated
- Features marked for removal
```

**3. Create Release Branch**

```bash
git checkout -b release/vX.Y.Z
git add .
git commit -m "Release version X.Y.Z"
```

**4. Tag Release**

```bash
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

**5. Build and Upload Package** (if applicable)

```bash
python setup.py sdist bdist_wheel
twine check dist/*
twine upload dist/*
```

### Post-Release

- [ ] Close related issues
- [ ] Update release notes on GitHub
- [ ] Announce in documentation
- [ ] Monitor for issues in first 24-48 hours

---

## Maintenance Guidelines

### Regular Maintenance

**Weekly:**
- Monitor GitHub issues and discussions
- Review test coverage reports
- Check for security advisories

**Monthly:**
- Run full test suite with latest Python
- Review performance metrics
- Update documentation examples

**Quarterly:**
- Refactor high-complexity code
- Update dependencies
- Performance optimization review

### Code Health Indicators

Watch for:
- **Cyclomatic complexity > 10** - Refactor needed
- **Coverage < 80%** - Add tests
- **TODO/FIXME accumulation** - Address technical debt
- **Dependency versions > 2 years old** - Update

### Deprecation Policy

```python
import warnings

def old_function():
    """Deprecated function.
    
    .. deprecated:: 2.1.0
        Use :func:`new_function` instead.
    """
    warnings.warn(
        "old_function is deprecated, use new_function instead",
        DeprecationWarning,
        stacklevel=2
    )
    return new_function()
```

**Deprecation Timeline:**
- Version N: Mark as deprecated, add warnings
- Version N+1: Increase warning level
- Version N+2: Remove deprecated code

### Adding New Modules

When adding subdirectories:

1. **Create structure:**
   ```
   new_module/
   ├── __init__.py          # Public API
   ├── README.md            # Module docs
   ├── types.py             # Type definitions
   ├── core.py              # Core logic
   └── exceptions.py        # Custom exceptions
   ```

2. **Add tests:**
   ```
   tests/unit/knowledge_graphs/test_new_module.py
   ```

3. **Update documentation:**
   - Add to main README.md
   - Create module README.md
   - Update ARCHITECTURE.md

4. **Add to CI/CD** if needed

### Long-Term Sustainability

**Best Practices:**
1. Keep dependencies fresh (quarterly updates)
2. Maintain backward compatibility (1-2 releases)
3. Document architectural decisions (ADRs)
4. Monitor performance metrics over time
5. Encourage contributions (label good first issues)

**Technical Debt Management:**
- Track with TODO/FIXME comments
- Schedule quarterly debt reduction sprints
- Balance new features with maintenance

**Community Building:**
- Respond to issues within 48 hours
- Review PRs within 1 week
- Maintain contributor documentation
- Recognize contributors publicly

---

## Documentation Contributions

### Adding Examples

Place examples in appropriate README:
- Module overview → Subdirectory README
- Integration patterns → USER_GUIDE.md
- API usage → API_REFERENCE.md

### Updating Documentation

1. Edit relevant markdown file
2. Update table of contents if structure changed
3. Test all code examples
4. Update cross-references
5. Submit PR with documentation label

## Issue Guidelines

### Reporting Bugs

Include:
- Python version
- Package version
- Minimal reproduction example
- Expected vs actual behavior
- Error messages/stack traces

### Feature Requests

Include:
- Use case description
- Proposed API
- Alternative solutions considered
- Backward compatibility considerations

## Getting Help

- Documentation: Review all docs in `docs/knowledge_graphs/`
- Examples: Check subdirectory READMEs
- Questions: Open GitHub discussion
- Bugs: Open GitHub issue

## Recognition

Contributors are recognized in:
- Release notes
- CONTRIBUTORS.md
- Git commit history

Thank you for contributing to IPFS Datasets Python!
