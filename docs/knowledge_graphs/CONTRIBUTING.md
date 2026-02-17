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
