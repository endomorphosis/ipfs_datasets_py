# Processing Engines Documentation

## Overview

The `processors/engines/` package provides modular access to complex processing capabilities that were previously in monolithic files. This document describes the architecture, usage, and migration paths.

**Created:** February 2026  
**Status:** Production-ready (facade pattern)  
**Compatibility:** 100% backward compatible

---

## Architecture

### Design Pattern: Facade

The engines use a **facade pattern** that:
- Provides modular structure immediately
- Imports from original monolithic files
- Maintains 100% backward compatibility
- Establishes foundation for future extraction

### Directory Structure

```
processors/
├── engines/              # Complex processing engines
│   ├── __init__.py       # Package exports
│   ├── llm/              # LLM optimization (8 modules)
│   │   ├── __init__.py
│   │   ├── optimizer.py   # Main LLMOptimizer facade
│   │   ├── chunker.py     # Text chunking strategies
│   │   ├── tokenizer.py   # Token optimization
│   │   ├── embeddings.py  # Embedding generation
│   │   ├── context.py     # Context management
│   │   ├── summarizer.py  # Text summarization
│   │   └── multimodal.py  # Multi-modal content
│   ├── query/            # Query processing (7 modules)
│   │   ├── __init__.py
│   │   ├── engine.py      # Main QueryEngine facade
│   │   ├── parser.py      # Query parsing
│   │   ├── optimizer.py   # Query optimization
│   │   ├── executor.py    # Query execution
│   │   ├── formatter.py   # Result formatting
│   │   └── cache.py       # Query caching
│   └── relationship/     # Relationship analysis (4 modules)
│       ├── __init__.py
│       ├── analyzer.py    # RelationshipAnalyzer facade
│       ├── api.py         # API interface
│       └── corpus.py      # Corpus queries
```

---

## Usage Guide

### LLM Engine

The LLM engine provides text optimization for LLM consumption.

**New Import (Recommended):**
```python
from ipfs_datasets_py.processors.engines.llm import (
    LLMOptimizer,
    LLMChunk,
    LLMDocument,
    ChunkOptimizer,
    TextProcessor,
)
```

**Old Import (Still Works):**
```python
from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer
```

**Example Usage:**
```python
from ipfs_datasets_py.processors.engines.llm import LLMOptimizer

# Create optimizer
optimizer = LLMOptimizer()

# Use as before - all functionality preserved
# (Actual usage depends on LLMOptimizer implementation)
```

**Submodules Available:**
- `engines.llm.optimizer` - Main orchestration
- `engines.llm.chunker` - Text chunking
- `engines.llm.tokenizer` - Token management
- `engines.llm.embeddings` - Embedding generation
- `engines.llm.context` - Context management
- `engines.llm.summarizer` - Text summarization
- `engines.llm.multimodal` - Multi-modal handling

---

### Query Engine

The query engine provides query processing and execution.

**New Import (Recommended):**
```python
from ipfs_datasets_py.processors.engines.query import QueryEngine
```

**Old Import (Still Works):**
```python
from ipfs_datasets_py.processors.query_engine import QueryEngine
```

**Example Usage:**
```python
from ipfs_datasets_py.processors.engines.query import QueryEngine

# Create engine
engine = QueryEngine()

# Use as before - all functionality preserved
```

**Submodules Available:**
- `engines.query.engine` - Main orchestration
- `engines.query.parser` - Query parsing
- `engines.query.optimizer` - Query optimization
- `engines.query.executor` - Query execution
- `engines.query.formatter` - Result formatting
- `engines.query.cache` - Query caching

---

### Relationship Engine

The relationship engine provides relationship analysis.

**New Import (Recommended):**
```python
from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer
```

**Old Import (Still Works):**
```python
from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer
```

**Example Usage:**
```python
from ipfs_datasets_py.processors.engines.relationship import RelationshipAnalyzer

# Create analyzer
analyzer = RelationshipAnalyzer()

# Use async methods
results = await analyzer.analyze_entity_relationships(
    documents=documents,
    min_confidence=0.6
)
```

**Submodules Available:**
- `engines.relationship.analyzer` - Core analysis
- `engines.relationship.api` - API interface
- `engines.relationship.corpus` - Corpus queries

---

## Migration Guide

### When to Migrate

**You should migrate if:**
- Starting new code
- Major refactoring existing code
- Want clearer code organization

**You can wait if:**
- Code is stable and working
- No major changes planned
- Migration scheduled for v2.0.0

### Migration Timeline

- **v1.9.0 - v1.15.0** (Current - Aug 2026): Grace period, both work
- **v2.0.0** (Aug 2026): Old imports removed

### Migration Steps

1. **Update imports:**
```python
# Old
from ipfs_datasets_py.processors.llm_optimizer import LLMOptimizer

# New
from ipfs_datasets_py.processors.engines.llm import LLMOptimizer
```

2. **Test thoroughly** - Verify behavior identical

3. **Update documentation** - Reference new paths

4. **Consider CI checks** - Catch old imports

### Automated Migration

Use the provided migration script:
```bash
python scripts/migrate_processors_imports.py --path /your/code
```

---

## Benefits

### Immediate Benefits

1. **Clearer Organization**
   - Logical grouping of related functionality
   - Easy to find what you need

2. **Better Documentation**
   - Clear entry points
   - Organized by purpose

3. **Modular Structure**
   - Foundation for future improvements
   - Easier to understand architecture

### Future Benefits

1. **Code Extraction**
   - Can move actual code into facade modules
   - Without changing public APIs

2. **Independent Updates**
   - Update modules independently
   - Better testing isolation

3. **Performance Optimization**
   - Optimize individual modules
   - Clearer performance profiling

---

## Implementation Details

### Current Status

**Pattern:** Facade (Phase 2 implementation)
- Facades import from original files
- Zero code duplication
- 100% backward compatible

**Original Files Still Active:**
- `llm_optimizer.py` (3,377 lines)
- `query_engine.py` (2,996 lines)
- `relationship_analyzer.py` (260 lines)

### Future Evolution

When ready for full extraction:
1. Move actual code into facade modules
2. Update facade imports to local code
3. Update original files to import from facades
4. Eventually deprecate original files

**Timeline:** TBD based on project needs

---

## Testing

### Test Coverage

**Integration Tests:**
- `tests/integration/processors/test_engines_facade.py` - 28 tests
- `tests/integration/processors/test_structure_lightweight.py` - 17 tests

**What's Tested:**
- Import paths work correctly
- Facades return same objects as originals
- Package structure is correct
- Documentation exists
- Deprecation shims in place

### Running Tests

```bash
# All engines tests
pytest tests/integration/processors/ -v

# Specific test files
pytest tests/integration/processors/test_engines_facade.py -v
pytest tests/integration/processors/test_structure_lightweight.py -v
```

---

## Troubleshooting

### Import Errors

**Problem:** `ModuleNotFoundError: No module named 'ipfs_datasets_py.processors.engines'`

**Solution:** Ensure you're using the latest code from the refactoring branch.

### Deprecation Warnings

**Problem:** Getting deprecation warnings

**Solution:** Update imports to use new paths (see Migration Guide above).

### Functionality Differences

**Problem:** Behavior seems different

**Solution:** This shouldn't happen - facades return identical objects. File an issue if you see differences.

---

## Related Documentation

- [Comprehensive Plan](PROCESSORS_COMPREHENSIVE_PLAN_2026.md) - Full refactoring plan
- [Quick Reference](PROCESSORS_PLAN_QUICK_REFERENCE.md) - Quick lookup guide
- [Visual Summary](PROCESSORS_VISUAL_SUMMARY.md) - Architecture diagrams
- [Migration Guide](PROCESSORS_MIGRATION_GUIDE.md) - Detailed migration info

---

## Support

**Questions?** Check existing documentation first.

**Issues?** File a GitHub issue with:
- Import path you're using
- Error message (if any)
- Expected vs actual behavior

---

## Changelog

### February 2026
- **Phase 2 Complete:** Created engines/ structure with facade pattern
- **Phase 3 Complete:** Added comprehensive tests (45 tests)
- **Phase 5 In Progress:** Documentation consolidation

---

## License

Same as main project (check repository LICENSE file).
