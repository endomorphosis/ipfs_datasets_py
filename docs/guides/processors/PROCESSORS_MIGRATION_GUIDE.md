# Processors Refactoring Migration Guide

## Overview

The processors directory has been refactored for better organization and maintainability. This guide helps you migrate your code to the new structure.

## What Changed

### Before (Old Structure)
```
processors/
├── graphrag_processor.py
├── pdf_processor.py
├── batch_processor.py
├── caching.py
├── patent_scraper.py
└── ... (32 root files)
```

### After (New Structure)
```
processors/
├── specialized/      # Domain-specific processors
│   ├── graphrag/    # GraphRAG processing
│   ├── pdf/         # PDF processing
│   ├── multimodal/  # Multimodal processing
│   └── batch/       # Batch processing
├── infrastructure/   # Cross-cutting concerns
│   ├── caching.py
│   ├── monitoring.py
│   ├── error_handling.py
│   └── ... (6 files)
└── domains/         # Domain-specific processors
    ├── patent/      # Patent processing
    ├── geospatial/  # Geographic analysis
    └── ml/          # ML & classification
```

## Migration Paths

### GraphRAG Processors

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
from ipfs_datasets_py.processors.graphrag_integrator import GraphRAGIntegrator
from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
from ipfs_datasets_py.processors.specialized.graphrag import GraphRAGIntegration
from ipfs_datasets_py.processors.specialized.graphrag import WebsiteGraphRAGSystem
```

### PDF Processors

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
from ipfs_datasets_py.processors.ocr_engine import OCREngine
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
from ipfs_datasets_py.processors.specialized.pdf import OCREngine
```

### Multimodal Processors

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.multimodal_processor import MultiModalContentProcessor
from ipfs_datasets_py.processors.enhanced_multimodal_processor import EnhancedMultiModalProcessor
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.specialized.multimodal import MultiModalContentProcessor
from ipfs_datasets_py.processors.specialized.multimodal import EnhancedMultiModalProcessor
```

### Batch Processors

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.batch_processor import BatchProcessor
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.specialized.batch import BatchProcessor
```

### Infrastructure

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.caching import CacheManager
from ipfs_datasets_py.processors.monitoring import MetricsCollector
from ipfs_datasets_py.processors.error_handling import ErrorHandler
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.infrastructure.caching import CacheManager
from ipfs_datasets_py.processors.infrastructure.monitoring import MetricsCollector
from ipfs_datasets_py.processors.infrastructure.error_handling import ErrorHandler
```

### Domain-Specific Processors

**Old (Deprecated):**
```python
from ipfs_datasets_py.processors.patent_scraper import PatentScraper
from ipfs_datasets_py.processors.geospatial_analysis import GeospatialAnalysis
from ipfs_datasets_py.processors.classify_with_llm import ClassifyWithLLM
```

**New (Recommended):**
```python
from ipfs_datasets_py.processors.domains.patent import PatentScraper
from ipfs_datasets_py.processors.domains.geospatial import GeospatialAnalysis
from ipfs_datasets_py.processors.domains.ml import ClassifyWithLLM
```

## Backward Compatibility

### Grace Period

- **Current:** Old imports work with deprecation warnings
- **Until:** v2.0.0 (August 2026) - 6 months
- **After:** Old imports will be removed

### Deprecation Warnings

When using old imports, you'll see:
```
DeprecationWarning: processors.graphrag_processor is deprecated. 
Use processors.specialized.graphrag.UnifiedGraphRAGProcessor instead. 
This import will be removed in v2.0.0 (August 2026).
```

## Migration Strategy

### Recommended Approach

1. **Immediate (No Rush):**
   - Continue using old imports if needed
   - Plan migration for next major refactoring

2. **Within 6 Months:**
   - Update imports in new code
   - Gradually update existing code
   - Test thoroughly

3. **Before August 2026:**
   - Complete all migrations
   - Remove any remaining old imports

### Quick Migration Script

```python
# Replace old imports in your codebase
import re

replacements = {
    'from ipfs_datasets_py.processors.graphrag_processor': 
        'from ipfs_datasets_py.processors.specialized.graphrag',
    'from ipfs_datasets_py.processors.pdf_processor': 
        'from ipfs_datasets_py.processors.specialized.pdf',
    'from ipfs_datasets_py.processors.batch_processor': 
        'from ipfs_datasets_py.processors.specialized.batch',
    'from ipfs_datasets_py.processors.caching': 
        'from ipfs_datasets_py.processors.infrastructure.caching',
    # Add more as needed...
}

def migrate_imports(file_content):
    for old, new in replacements.items():
        file_content = file_content.replace(old, new)
    return file_content
```

## Benefits of New Structure

### Better Organization
- Clear separation of concerns
- Logical grouping by domain
- Easier to navigate

### Reduced Complexity
- 96.1% code reduction (702KB → 27.4KB)
- ~15,000 lines eliminated
- 20 files consolidated

### Improved Maintainability
- Specialized packages for specific domains
- Infrastructure separated from business logic
- Domain-specific processors grouped together

### Cleaner Root
- Only __init__.py in root
- All functionality in subdirectories
- Clear module boundaries

## Support

### Questions?

- See: `../archive/processors/phase_reports/PROCESSORS_PHASES_1_7_COMPLETE.md` for full details
- See: `../archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` for original plan
- See: `PROCESSORS_REFACTORING_QUICK_REFERENCE.md` for quick lookup

### Issues?

If you encounter any migration issues:
1. Check deprecation warning for correct new path
2. Verify optional dependencies are installed
3. Test with new imports in isolation
4. Report any bugs or unclear migrations

## Timeline

- **Now:** Old and new imports both work
- **June 2026:** Final migration reminders
- **August 2026:** Old imports removed in v2.0.0

---

**Last Updated:** February 15, 2026  
**Version:** 1.0.0 (Phases 1-7 Complete)
