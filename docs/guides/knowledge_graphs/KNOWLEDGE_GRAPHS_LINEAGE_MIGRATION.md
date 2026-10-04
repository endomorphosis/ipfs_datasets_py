# Knowledge Graphs Lineage Package Migration Guide

**Version:** 1.0  
**Date:** February 16, 2026  
**Status:** Active - Deprecation Period  

---

## Overview

The cross-document lineage tracking functionality has been refactored into a modern, modular package structure. The legacy `cross_document_lineage.py` and `cross_document_lineage_enhanced.py` files (totaling 6,423 lines) have been replaced with a focused `lineage/` package (2,025 lines, 68.5% reduction).

### Deprecation Timeline

- **Deprecation Announced:** February 16, 2026
- **Deprecation Period:** 4-6 months
- **Removal Target:** Q2 2026 (Version 2.0)
- **Backward Compatibility:** Available during transition

---

## What Changed

### Old Structure (Deprecated)
```
knowledge_graphs/
├── cross_document_lineage.py           # 4,066 lines 🔴 DEPRECATED
└── cross_document_lineage_enhanced.py  # 2,357 lines 🔴 DEPRECATED
```

### New Structure (Current)
```
knowledge_graphs/
└── lineage/                            # 2,025 lines ✅ ACTIVE
    ├── __init__.py                     # Package exports
    ├── types.py                        # Data classes (7 types)
    ├── core.py                         # LineageGraph, LineageTracker
    ├── enhanced.py                     # Enhanced analysis classes
    ├── visualization.py                # LineageVisualizer
    └── metrics.py                      # Metrics and analysis
```

---

## Migration Examples

### Example 1: Basic Lineage Tracking

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    CrossDocumentLineageTracker,
    CrossDocumentLineageGraph,
)

tracker = CrossDocumentLineageTracker()
graph = CrossDocumentLineageGraph()
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker, LineageGraph

tracker = LineageTracker()
graph = LineageGraph()
```

### Example 2: Enhanced Lineage Features

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import (
    EnhancedLineageTracker,
    SemanticAnalyzer,
)

tracker = EnhancedLineageTracker()
analyzer = SemanticAnalyzer()
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker, SemanticAnalyzer

tracker = EnhancedLineageTracker()
analyzer = SemanticAnalyzer()
```

### Example 3: Data Types

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    LineageNode,
    LineageLink,
    LineageTransformationDetail,
)
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageNode,
    LineageLink,
    LineageTransformationDetail,
)
```

### Example 4: Visualization

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import LineageVisualizer
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageVisualizer
```

### Example 5: Metrics and Analysis

**Old Code (Deprecated):**
```python
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import (
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)
```

**New Code (Recommended):**
```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageMetrics,
    ImpactAnalyzer,
    DependencyAnalyzer,
)
```

---

## API Compatibility

### Unchanged APIs
The following APIs remain **100% compatible**:

✅ `LineageTracker` - All methods unchanged  
✅ `LineageGraph` - All methods unchanged  
✅ `EnhancedLineageTracker` - All methods unchanged  
✅ `LineageNode` - Data structure unchanged  
✅ `LineageLink` - Data structure unchanged  
✅ `LineageVisualizer` - All methods unchanged  

### Deprecated Aliases
The following aliases are provided for backward compatibility but will be removed in v2.0:

⚠️ `CrossDocumentLineageTracker` → Use `LineageTracker`  
⚠️ `CrossDocumentLineageGraph` → Use `LineageGraph`  
⚠️ `CrossDocumentLineageEnhancer` → Use `EnhancedLineageTracker`  

---

## Automated Migration

### Using sed (Unix/Linux/macOS)
```bash
# Replace cross_document_lineage imports
find . -name "*.py" -type f -exec sed -i '' \
  's/from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import/from ipfs_datasets_py.knowledge_graphs.lineage import/g' {} +

# Replace cross_document_lineage_enhanced imports
find . -name "*.py" -type f -exec sed -i '' \
  's/from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import/from ipfs_datasets_py.knowledge_graphs.lineage import/g' {} +
```

### Using Python Script
```python
import os
import re
from pathlib import Path


def migrate_imports(directory):
    """Migrate all Python files in directory."""
    for py_file in Path(directory).rglob("*.py"):
        content = py_file.read_text()

        # Replace imports
        content = content.replace(
            "from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import",
            "from ipfs_datasets_py.knowledge_graphs.lineage import",
        )
        content = content.replace(
            "from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import",
            "from ipfs_datasets_py.knowledge_graphs.lineage import",
        )

        py_file.write_text(content)
        print(f"Migrated: {py_file}")


# Usage
migrate_imports("your_project_directory")
```

---

## Benefits of Migration

### Code Quality
- ✅ **68.5% code reduction** (6,423 → 2,025 lines)
- ✅ **Modular architecture** (5 focused files vs 2 monolithic files)
- ✅ **95%+ type hints** (improved IDE support)
- ✅ **67 comprehensive tests** (85% coverage)

### Performance
- ⚡ **Faster imports** (smaller module size)
- ⚡ **Better tree shaking** (import only what you need)
- ⚡ **Reduced memory footprint**

### Maintainability
- 📦 **Clear separation of concerns**
- 📦 **Easier to extend**
- 📦 **Better documentation**
- 📦 **Production-ready quality**

---

## Testing Your Migration

### Step 1: Enable Deprecation Warnings
```python
import warnings

warnings.simplefilter("always", DeprecationWarning)

# Your code here - warnings will show up
```

### Step 2: Run Your Tests
```bash
# Run with warnings visible
python -W always::DeprecationWarning your_tests.py

# Or with pytest
pytest -W always::DeprecationWarning
```

### Step 3: Verify Functionality
```python
# Test that imports work
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

tracker = LineageTracker()
assert tracker is not None
print("✓ Migration successful!")
```

---

## Known Issues

### Issue 1: Import Errors
**Problem:** `ImportError: cannot import name 'X' from lineage`  
**Solution:** Check that the class name is spelled correctly. Some classes were renamed for consistency.

### Issue 2: Deprecated Warnings in Tests
**Problem:** Test output cluttered with deprecation warnings  
**Solution:** Update your imports to use the new `lineage` package.

---

## Support and Questions

### Internal Users
- Check existing imports: `grep -r "cross_document_lineage" --include="*.py" .`
- Update imports using automated migration scripts above
- Run tests to verify functionality

### External Users
- Review this migration guide
- Test in development environment first
- Report issues via GitHub Issues

### Timeline
- **Now - Q2 2026:** Transition period with backward compatibility
- **Q2 2026:** Legacy files removed in v2.0

---

## Additional Resources

- **Master Refactoring Plan:** `../archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md`
- **Implementation Guide:** `KNOWLEDGE_GRAPHS_IMPLEMENTATION_GUIDE_2026_02_16.md`
- **Test Examples:** `tests/unit/knowledge_graphs/lineage/`

---

**Last Updated:** February 16, 2026  
**Document Version:** 1.0  
**Maintained By:** Knowledge Graphs Team  
