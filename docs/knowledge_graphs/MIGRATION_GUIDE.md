# Knowledge Graphs - Migration Guide

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

## Overview

Guide for upgrading between versions, handling breaking changes, and maintaining compatibility.

## Migration from Legacy API

### Old Import Path (Deprecated)

```python
# Old (still works but shows deprecation warning)
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

### New Import Path (Recommended)

```python
# New (recommended)
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

**Migration Steps:**
1. Update import statements to use `extraction` package
2. Test that all functionality works as expected
3. Remove old imports once validated

**Backward Compatibility:** Both paths work identically - no code changes needed beyond imports.

## Breaking Changes

### Version 2.0.0

**Change:** Consolidated extraction module structure
- **Impact:** Import paths changed
- **Migration:** Update imports from `knowledge_graph_extraction` to `extraction`
- **Timeline:** Old imports supported until v3.0.0

**Change:** Custom exception hierarchy
- **Impact:** More specific exception types
- **Migration:** Catch specific exceptions (EntityExtractionError, QueryError, etc.)
- **Timeline:** Generic Exception catching still works but not recommended

### Version 1.0.0

**Change:** Initial stable release
- **Impact:** API stabilized
- **Migration:** N/A (first stable version)

## Compatibility Matrix

| Version | Python | spaCy | IPFS |
|---------|--------|-------|------|
| 2.0.0   | 3.12+  | 3.0+  | Any  |
| 1.0.0   | 3.10+  | 3.0+  | Any  |

## Migration Checklist

### From 1.x to 2.0

- [ ] Update import paths to use `extraction` package
- [ ] Update exception handling to use specific exceptions
- [ ] Add spaCy to dependencies if not already included
- [ ] Test all extraction and query workflows
- [ ] Update documentation and examples
- [ ] Deploy to staging environment
- [ ] Run integration tests
- [ ] Deploy to production

## Common Migration Issues

### Issue: ImportError after upgrade

**Solution:** Install knowledge graphs extras
```bash
pip install "ipfs_datasets_py[knowledge_graphs]"
python -m spacy download en_core_web_sm
```

### Issue: Deprecation warnings

**Solution:** Update import paths
```python
# Before
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity

# After
from ipfs_datasets_py.knowledge_graphs.extraction import Entity
```

### Issue: Exception handling changes

**Solution:** Use specific exception types
```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    EntityExtractionError,
    QueryError
)

try:
    graph = extractor.extract(text)
except EntityExtractionError as e:
    # Handle extraction errors
    pass
```

## Deprecation Timeline

- **v2.0.0** (2026-02-17): Old imports deprecated, still functional
- **v2.5.0** (Planned 2026-Q3): Warning level increased
- **v3.0.0** (Planned 2026-Q4): Old imports removed

## Getting Help

For migration assistance:
- Check [USER_GUIDE.md](USER_GUIDE.md) for updated usage patterns
- Review [API_REFERENCE.md](API_REFERENCE.md) for API changes
- See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines
