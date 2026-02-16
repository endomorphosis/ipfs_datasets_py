# Knowledge Graphs Extraction & Query Migration Guide

**Version:** 1.0.0  
**Last Updated:** 2026-02-16  
**Status:** Production Ready

## Overview

Complete migration guide for the new modular knowledge graphs architecture. Covers migrating from legacy `knowledge_graph_extraction` to the new `extraction/` and `query/` packages.

## Quick Summary

- **Breaking Changes:** NONE - 100% backward compatible
- **Migration Effort:** Low - mostly import updates
- **Benefits:** Better performance, comprehensive docs, modular architecture
- **Timeline:** Gradual - v2.x supports both, v3.0 removes legacy

## Import Migration

### Simple Update

**Old (deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity, Relationship, KnowledgeGraph,
    KnowledgeGraphExtractor, KnowledgeGraphExtractorWithValidation
)
```

**New (recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity, Relationship, KnowledgeGraph,
    KnowledgeGraphExtractor, KnowledgeGraphExtractorWithValidation
)
```

## Query System Migration

### From Legacy Systems

**Old (scattered implementations):**
```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler
compiler = CypherCompiler()
result = compiler.execute(query)
```

**New (unified):**
```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

engine = UnifiedQueryEngine(backend=backend)
budgets = budgets_from_preset('moderate')
result = engine.execute_query(query, budgets=budgets)
```

## Common Patterns

### 1. Basic Extraction (no changes needed)

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph(text)
```

### 2. Batch Processing (use built-in merge)

**Old:**
```python
combined = KnowledgeGraph()
for text in texts:
    kg = extractor.extract_knowledge_graph(text)
    for entity in kg.entities.values():
        combined.add_entity(entity)
    for rel in kg.relationships.values():
        combined.add_relationship(rel)
```

**New:**
```python
combined = KnowledgeGraph()
for text in texts:
    kg = extractor.extract_knowledge_graph(text)
    combined.merge(kg)  # Built-in merge
```

### 3. Query with Budgets (new feature)

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

engine = UnifiedQueryEngine(backend, enable_caching=True)
budgets = budgets_from_preset('moderate')

result = engine.execute_query(query, budgets=budgets)
```

## Troubleshooting

### ImportError

**Problem:** Cannot import from extraction package

**Solution:**
```bash
pip install -e .  # Reinstall package
```

### DeprecationWarning

**Problem:** Warnings about deprecated imports

**Solution:** Update imports to use `extraction` instead of `knowledge_graph_extraction`

### Performance

**Problem:** Slower after migration

**Solution:** Enable caching and tune temperature settings
```python
engine = UnifiedQueryEngine(backend, enable_caching=True)
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.5)
```

## Validation Checklist

- [ ] Update all imports
- [ ] Run test suite
- [ ] Verify no deprecation warnings
- [ ] Check performance (should be equal or better)
- [ ] Update documentation
- [ ] Deploy to staging
- [ ] Monitor production

## Resources

**Note:** This guide replaces the removed `KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md`. All references to that file should now point to `KNOWLEDGE_GRAPHS_EXTRACTION_QUERY_MIGRATION.md`.

- **Extraction API:** `KNOWLEDGE_GRAPHS_EXTRACTION_API.md` - Complete API reference
- **Query API:** `KNOWLEDGE_GRAPHS_QUERY_API.md` - Query system documentation
- **Usage Examples:** `KNOWLEDGE_GRAPHS_USAGE_EXAMPLES.md` - 17 comprehensive examples
- **Integration Guide:** `KNOWLEDGE_GRAPHS_INTEGRATION_GUIDE.md` - End-to-end workflows
- **Performance:** `KNOWLEDGE_GRAPHS_PERFORMANCE_OPTIMIZATION.md` - Optimization techniques
- **Architecture:** `KNOWLEDGE_GRAPHS_QUERY_ARCHITECTURE.md` - System architecture

## Summary

✅ **No breaking changes** - old code still works  
✅ **Easy migration** - mostly import updates  
✅ **Better performance** - optimized implementation  
✅ **191KB+ docs** - comprehensive documentation  
✅ **Production ready** - tested and validated

**Migration is simple - just update your imports and enjoy the benefits!**

---

**Version:** 1.0  
**Updated:** 2026-02-16  
**Team:** Knowledge Graphs
