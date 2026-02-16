# Knowledge Graph Extraction Package

## Status: Planning Phase

This directory is prepared for the gradual refactoring of `knowledge_graph_extraction.py` (2,969 lines).

## Why Not Split Immediately?

The knowledge_graph_extraction.py file has complex interdependencies:

1. **Entity** and **Relationship** classes are tightly coupled
2. **KnowledgeGraph** class depends on both
3. **KnowledgeGraphExtractor** orchestrates all of them
4. **KnowledgeGraphExtractorWithValidation** extends the base extractor

Breaking these immediately would risk production systems using this code.

## Future Structure

When test coverage reaches 80%+ and dependencies are well-understood:

```
extraction/
├── __init__.py                # Package exports
├── entities.py (~400 lines)   # Entity and Relationship classes
├── extractors.py (~1,000 lines)  # Extraction algorithms
├── analyzers.py (~800 lines)     # Semantic analysis
└── builders.py (~700 lines)      # Graph construction
```

## Migration Plan

### Phase 1: Preparation (Current)
- ✅ Create directory structure
- ✅ Document rationale
- [ ] Increase test coverage to 80%+
- [ ] Analyze all usages

### Phase 2: Gradual Extraction (Future)
- [ ] Extract Entity and Relationship to entities.py
- [ ] Create adapter in old location
- [ ] Update tests
- [ ] Monitor for issues

### Phase 3: Continue Extraction
- [ ] Extract extractor classes
- [ ] Extract analysis functions
- [ ] Extract graph builders
- [ ] Update all imports

### Phase 4: Deprecation
- [ ] Add deprecation warnings
- [ ] 6-month transition period
- [ ] Archive old file

## Current Usage

**Until migration is complete, use the original module:**

```python
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)
```

## Timeline

- **Now**: Planning and documentation
- **Month 1-2**: Test coverage improvement
- **Month 3-4**: Gradual extraction begins
- **Month 5-6**: Migration complete
- **Month 7+**: Old file deprecated

## Questions?

See `docs/MIGRATION_GUIDE.md` for more information.
