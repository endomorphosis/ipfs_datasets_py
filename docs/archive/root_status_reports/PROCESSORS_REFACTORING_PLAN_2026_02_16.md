# Processors Directory Refactoring & AnyIO Migration Plan

**Date:** 2026-02-16  
**Status:** Draft  
**Priority:** HIGH  
**Estimated Duration:** 8-12 weeks  
**Risk Level:** MEDIUM-HIGH  

---

## Executive Summary

The `ipfs_datasets_py/processors/` directory requires comprehensive refactoring to:
1. **Complete migration from `asyncio` to `anyio`** for async framework consistency
2. **Consolidate duplicate functionality** across 3 multimedia conversion systems
3. **Complete architectural migration** from legacy top-level files to organized subdirectories
4. **Simplify complex nested structures** in multimedia subsystems
5. **Establish clear architectural boundaries** between core, adapters, specialized, and domain processors

### Current State
- **685 Python files** across **55 subdirectories**
- **MIXED async frameworks**: 33 asyncio imports, 73 anyio imports
- **3 parallel file conversion systems** with overlapping functionality
- **Transition in progress**: Old top-level files coexist with new subdirectory organization
- **Deep nesting**: Some directories are 8+ levels deep

### Target State
- **100% anyio** for all async operations
- **Single unified conversion system** with clear backend plugins
- **Clean directory structure** with deprecated files removed
- **Maximum 4 levels** of directory nesting
- **Clear architectural tiers**: core → adapters → specialized → domains → infrastructure

---

## Phase 1: Complete AnyIO Migration (2-3 weeks)

**Goal:** Replace all `asyncio` usage with `anyio` for framework consistency and better async/await patterns.

### 1.1 Infrastructure Layer Migration (Priority: CRITICAL)

**Files to Update:**
```
ipfs_datasets_py/processors/infrastructure/
├── profiling.py               [USES asyncio - line 13]
├── error_handling.py          [USES asyncio - line 10]
├── debug_tools.py             [USES asyncio]
└── caching.py                 [CHECK - may use asyncio]
```

**Changes Required:**

#### `profiling.py` (Line 13)
```python
# BEFORE
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def profile(self, operation_name: str = "processing"):
    # Uses asyncio implicitly in async context manager
```

```python
# AFTER
import anyio
from contextlib import asynccontextmanager

@asynccontextmanager
async def profile(self, operation_name: str = "processing"):
    # Uses anyio for all async operations
    # Replace any asyncio.sleep() with anyio.sleep()
    # Replace asyncio.gather() with anyio.create_task_group()
```

#### `error_handling.py` (Lines 10, 150+)
```python
# BEFORE
import asyncio

async def retry_with_backoff(func, *args, **kwargs):
    await asyncio.sleep(delay)
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

```python
# AFTER
import anyio

async def retry_with_backoff(func, *args, **kwargs):
    await anyio.sleep(delay)
    
    # Use task groups for structured concurrency
    async with anyio.create_task_group() as tg:
        for task in tasks:
            tg.start_soon(task)
```

**Testing Strategy:**
- Run existing infrastructure tests with anyio
- Add specific tests for async context managers
- Verify error handling and retry logic
- Test profiling metrics collection

**Estimated Time:** 3-4 days

---

### 1.2 Core Layer Migration (Priority: HIGH)

**Files to Update:**
```
ipfs_datasets_py/processors/
├── universal_processor.py     [USES asyncio - line 13]
└── core/
    └── universal_processor.py [CHECK if exists]
```

**Changes Required:**

#### `universal_processor.py` (Line 13)
```python
# BEFORE
import asyncio

async def process_batch(self, inputs: list) -> list[ProcessingResult]:
    tasks = [self.process(inp) for inp in inputs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

```python
# AFTER
import anyio

async def process_batch(self, inputs: list) -> list[ProcessingResult]:
    results = []
    async with anyio.create_task_group() as tg:
        for inp in inputs:
            tg.start_soon(self._process_and_collect, inp, results)
    return results

async def _process_and_collect(self, inp, results: list):
    result = await self.process(inp)
    results.append(result)
```

**Key Patterns to Replace:**

| asyncio Pattern | anyio Equivalent |
|----------------|------------------|
| `asyncio.sleep(n)` | `anyio.sleep(n)` |
| `asyncio.gather(*tasks)` | `async with anyio.create_task_group() as tg:` |
| `asyncio.create_task(coro)` | `tg.start_soon(coro)` within task group |
| `asyncio.wait_for(coro, timeout)` | `with anyio.fail_after(timeout):` |
| `asyncio.run(coro)` | `anyio.run(coro)` |
| `asyncio.Lock()` | `anyio.Lock()` |
| `asyncio.Event()` | `anyio.Event()` |
| `asyncio.Semaphore(n)` | `anyio.Semaphore(n)` |

**Estimated Time:** 2-3 days

---

### 1.3 Specialized Processors Migration (Priority: MEDIUM)

**Files to Check:**
```
ipfs_datasets_py/processors/specialized/
├── batch/processor.py         [USES asyncio.gather]
├── graphrag/                  [CHECK all files]
├── media/                     [CHECK all files]
└── multimodal/                [CHECK all files]
```

**Changes:** Apply standard asyncio → anyio replacements from table above.

**Estimated Time:** 3-4 days

---

### 1.4 Multimedia Subsystem Migration (Priority: HIGH - COMPLEX)

**Problem:** The multimedia subsystems use heavy asyncio with event loop management.

**Files to Update:**
```
ipfs_datasets_py/processors/multimedia/
├── convert_to_txt_based_on_mime_type/
│   ├── main.py                                    [asyncio.run, event loop]
│   ├── converter_system/
│   │   ├── conversion_pipeline/functions/
│   │   │   ├── core.py                           [asyncio.gather]
│   │   │   ├── pipeline.py                       [asyncio.gather]
│   │   │   └── optimize.py                       [asyncio functions]
│   │   ├── file_path_queue/file_path_queue.py   [asyncio.Queue]
│   │   └── core_resource_manager/               [asyncio management]
│   ├── pools/non_system_resources/
│   │   └── core_functions_pool/
│   │       └── core_functions_pool.py            [asyncio.gather]
│   └── utils/
│       ├── common/asyncio_coroutine.py           [ENTIRE FILE is asyncio utils]
│       └── converter_system/
│           ├── monads/async_.py                  [Async monad with asyncio]
│           ├── run_in_parallel_with_concurrency_limiter.py [asyncio.Semaphore]
│           └── run_in_thread_pool.py             [asyncio.run_in_executor]
└── omni_converter_mk2/
    └── interfaces/_gui.py                        [CHECK]
```

**Special Considerations:**

1. **Event Loop Management** - Remove explicit event loop handling
```python
# BEFORE
loop = asyncio.get_event_loop()
loop.run_until_complete(coro)

# AFTER
anyio.run(coro)  # anyio manages the event loop
```

2. **asyncio.Queue** → `anyio.create_memory_object_stream()`
```python
# BEFORE
queue = asyncio.Queue(maxsize=100)
await queue.put(item)
item = await queue.get()

# AFTER
send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=100)
await send_stream.send(item)
item = await receive_stream.receive()
```

3. **Thread Pool Integration**
```python
# BEFORE
loop.run_in_executor(executor, blocking_func, *args)

# AFTER
await anyio.to_thread.run_sync(blocking_func, *args)
```

4. **Concurrency Limiting**
```python
# BEFORE
semaphore = asyncio.Semaphore(max_concurrent)
async with semaphore:
    await process()

# AFTER
limiter = anyio.CapacityLimiter(max_concurrent)
async with limiter:
    await process()
```

5. **`asyncio_coroutine.py` Utility File**
   - This file provides asyncio-specific utilities
   - Need to create `anyio_coroutine.py` equivalent
   - Migrate all callers

**Testing Strategy for Multimedia:**
- Create integration tests for each conversion pipeline
- Test with various file formats (PDF, audio, video, images)
- Verify concurrency limits work correctly
- Test error handling and retries
- Benchmark performance (anyio should be comparable or faster)

**Estimated Time:** 5-7 days (COMPLEX)

---

### 1.5 Documentation & Migration Guide

**Create:** `docs/ASYNCIO_TO_ANYIO_MIGRATION.md`

**Contents:**
1. Why anyio over asyncio
2. Pattern replacement reference table (from above)
3. Common pitfalls and solutions
4. Testing strategy
5. Rollback plan

**Estimated Time:** 1 day

---

### Phase 1 Summary

**Total Estimated Time:** 2-3 weeks  
**Risk:** MEDIUM (multimedia subsystem is complex)  
**Dependencies:** None  
**Deliverables:**
- ✅ All processors use anyio exclusively
- ✅ Tests updated and passing
- ✅ Migration guide published
- ✅ No asyncio imports remaining

---

## Phase 2: Consolidate Duplicate Functionality (3-4 weeks)

**Goal:** Merge 3 file conversion systems into 1 unified system with clear backend architecture.

### 2.1 Analysis of Current Conversion Systems

**System 1: `file_converter/` (MAIN - KEEP)**
- Location: `ipfs_datasets_py/processors/file_converter/`
- Files: 20+ files
- Architecture: Clean backend system with plugins
- Features: URL handling, IPFS integration, batch processing, archive support
- Backends: Native, Markitdown, Omni
- Status: **Production-ready, well-tested**

**System 2: `multimedia/convert_to_txt_based_on_mime_type/` (LEGACY - DEPRECATE)**
- Location: `ipfs_datasets_py/processors/multimedia/convert_to_txt_based_on_mime_type/`
- Files: 40+ files across 8 directory levels
- Architecture: Complex pool-based system with event loops
- Features: MIME-based routing, parallel processing
- Status: **Legacy, overly complex**

**System 3: `multimedia/omni_converter_mk2/` (NEWER - MERGE INTO MAIN)**
- Location: `ipfs_datasets_py/processors/multimedia/omni_converter_mk2/`
- Files: 30+ files
- Architecture: Modular with monitors and batch processor
- Features: GUI interface, content extraction, type detection
- Status: **Newer but not integrated with main system**

### 2.2 Consolidation Strategy

**Decision:** Consolidate into `file_converter/` as the single source of truth.

**Step 1: Extract Valuable Components from Legacy Systems**

From `convert_to_txt_based_on_mime_type/`:
- ✅ MIME type detection logic (if better than current)
- ✅ Format-specific extractors (if not already in backends)
- ❌ Pool-based architecture (too complex)
- ❌ Event loop management (migrating to anyio)

From `omni_converter_mk2/`:
- ✅ GUI interface → Move to `file_converter/gui/`
- ✅ Enhanced content extraction → Integrate as backend
- ✅ File format detector → Merge with existing detection
- ✅ Batch processor enhancements → Merge with existing
- ✅ Monitoring tools → Integrate with infrastructure/monitoring.py

**Step 2: Create Migration Plan**

```
file_converter/
├── converter.py               [MAIN ENTRY POINT]
├── backends/
│   ├── native_backend.py
│   ├── markitdown_backend.py
│   ├── omni_backend.py        [Enhanced from omni_mk2]
│   └── specialized/
│       ├── pdf_backend.py
│       ├── audio_backend.py
│       ├── video_backend.py
│       └── image_backend.py
├── gui/                       [NEW - from omni_mk2]
│   ├── __init__.py
│   └── converter_gui.py
├── detection/                 [ENHANCED]
│   ├── mime_detector.py       [Merge best from all 3 systems]
│   └── format_analyzer.py
├── batch_processor.py         [ENHANCED]
├── pipeline.py
├── url_handler.py
├── archive_handler.py
└── ipfs_integration/
    ├── ipfs_backend.py
    └── storage.py
```

**Step 3: Deprecate Legacy Systems**

```python
# multimedia/convert_to_txt_based_on_mime_type/__init__.py
import warnings

warnings.warn(
    "multimedia.convert_to_txt_based_on_mime_type is deprecated. "
    "Use ipfs_datasets_py.processors.file_converter instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export for backward compatibility (temporary)
from ...file_converter import FileConverter as ConvertToTxt
```

**Step 4: Create Adapters for Backward Compatibility**

For code using the old APIs:
```python
# Legacy API
from ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type import convert_file

# Adapter redirects to new system
def convert_file(input_path, output_path, **kwargs):
    warnings.warn("Use file_converter.FileConverter instead", DeprecationWarning)
    from ipfs_datasets_py.processors.file_converter import FileConverter
    converter = FileConverter()
    return converter.convert(input_path, output_path, **kwargs)
```

### 2.3 Consolidate Batch Processing

**Problem:** 4+ implementations of batch processing:
1. `specialized/batch/processor.py`
2. `specialized/batch/file_converter_batch.py`
3. `file_converter/batch_processor.py`
4. `multimedia/omni_converter_mk2/batch_processor/`

**Solution:** Merge into single `file_converter/batch_processor.py`

**Features to Preserve:**
- Parallel processing with worker pools
- Progress tracking and cancellation
- Error recovery and retry logic
- Resource limiting (memory, CPU, I/O)
- Chunking strategies for large batches

**Estimated Time:** 1 week

---

### 2.4 Consolidate PDF Processing

**Current State:**
- `pdf_processor.py` (top-level, deprecated)
- `pdf_processing.py` (top-level, legacy)
- `specialized/pdf/pdf_processor.py` (new location)
- `file_converter/` has PDF support in backends

**Solution:**
1. Move all PDF logic to `specialized/pdf/`
2. Integrate with `file_converter/` via backend
3. Remove top-level files
4. Create deprecation wrappers

**Structure:**
```
specialized/pdf/
├── __init__.py
├── pdf_processor.py           [MAIN - extracted text, metadata]
├── pdf_to_graphrag.py         [Knowledge graph extraction]
├── pdf_ocr.py                 [OCR for scanned PDFs]
└── backends/
    ├── pypdf_backend.py
    ├── pdfminer_backend.py
    └── tesseract_backend.py   [OCR]
```

**Estimated Time:** 3-4 days

---

### 2.5 Consolidate Multimodal Processing

**Current State:**
- `multimodal_processor.py` (top-level)
- `enhanced_multimodal_processor.py` (top-level)
- `specialized/multimodal/multimodal_processor.py`

**Solution:** Single implementation in `specialized/multimodal/`

**Structure:**
```
specialized/multimodal/
├── __init__.py
├── processor.py               [MAIN unified processor]
├── image_text_processor.py
├── video_audio_processor.py
└── document_processor.py
```

**Estimated Time:** 2-3 days

---

### Phase 2 Summary

**Total Estimated Time:** 3-4 weeks  
**Risk:** MEDIUM-HIGH (lots of code to migrate)  
**Dependencies:** Phase 1 (anyio migration)  
**Deliverables:**
- ✅ Single unified file conversion system
- ✅ Single batch processing implementation
- ✅ Consolidated PDF processing
- ✅ Consolidated multimodal processing
- ✅ Deprecation wrappers for backward compatibility
- ✅ Migration guide for users

---

## Phase 3: Clean Up Legacy Top-Level Files (1-2 weeks)

**Goal:** Remove deprecated top-level files and enforce new directory structure.

### 3.1 Files to Remove/Deprecate

**Candidates for Removal:**
```
ipfs_datasets_py/processors/
├── advanced_graphrag_website_processor.py  → specialized/graphrag/
├── advanced_media_processing.py            → specialized/media/
├── advanced_web_archiving.py               → specialized/web_archive/
├── batch_processor.py                      → specialized/batch/
├── graphrag_processor.py                   → specialized/graphrag/
├── graphrag_integrator.py                  → specialized/graphrag/
├── multimodal_processor.py                 → specialized/multimodal/
├── enhanced_multimodal_processor.py        → specialized/multimodal/
├── pdf_processor.py                        → specialized/pdf/
├── pdf_processing.py                       → specialized/pdf/
├── website_graphrag_processor.py           → specialized/graphrag/
├── patent_scraper.py                       → domains/patent/
├── patent_dataset_api.py                   → domains/patent/
├── geospatial_analysis.py                  → domains/geospatial/
├── classify_with_llm.py                    → domains/ml/
├── ocr_engine.py                           → specialized/ocr/ (NEW)
├── query_engine.py                         → engines/query/
├── relationship_analyzer.py                → engines/relationship/
└── llm_optimizer.py                        → engines/llm/
```

**Also Clean Up:**
```
ipfs_datasets_py/processors/
├── caching.py            → infrastructure/caching.py (MOVE)
├── cli.py                → infrastructure/cli.py (MOVE)
├── debug_tools.py        → infrastructure/debug_tools.py (MOVE)
├── error_handling.py     → infrastructure/error_handling.py (MOVE)
├── monitoring.py         → infrastructure/monitoring.py (MOVE)
├── profiling.py          → infrastructure/profiling.py (MOVE)
├── protocol.py           → core/protocol.py (ALREADY EXISTS - REMOVE DUPLICATE)
└── registry.py           → core/registry.py (ALREADY EXISTS - REMOVE DUPLICATE)
```

### 3.2 Migration Process

**For Each File:**

1. **Verify New Location Exists**
   ```bash
   # Example for pdf_processor.py
   ls -la ipfs_datasets_py/processors/specialized/pdf/pdf_processor.py
   ```

2. **Create Deprecation Wrapper (if still needed)**
   ```python
   # ipfs_datasets_py/processors/pdf_processor.py
   """
   DEPRECATED: This module has moved to specialized.pdf.pdf_processor
   
   This file will be removed in v3.0.0
   """
   import warnings
   
   warnings.warn(
       "pdf_processor has moved to ipfs_datasets_py.processors.specialized.pdf "
       "This import will be removed in v3.0.0",
       DeprecationWarning,
       stacklevel=2
   )
   
   from .specialized.pdf.pdf_processor import PDFProcessor
   
   __all__ = ['PDFProcessor']
   ```

3. **Update `__init__.py`**
   ```python
   # ipfs_datasets_py/processors/__init__.py
   
   # NEW IMPORTS (preferred)
   from .specialized.pdf import PDFProcessor
   from .specialized.graphrag import GraphRAGProcessor
   from .specialized.batch import BatchProcessor
   
   # DEPRECATED IMPORTS (backward compatibility - remove in v3.0)
   # These trigger deprecation warnings
   from .pdf_processor import PDFProcessor as _DeprecatedPDFProcessor
   ```

4. **Update All Internal References**
   ```bash
   # Find all imports of the old location
   grep -r "from ipfs_datasets_py.processors import pdf_processor" .
   grep -r "from .pdf_processor import" .
   
   # Update them to new location
   # from ipfs_datasets_py.processors import pdf_processor
   # → from ipfs_datasets_py.processors.specialized.pdf import pdf_processor
   ```

5. **Remove File (after deprecation period)**
   - Add to `DEPRECATION_SCHEDULE.md`
   - Wait 1-2 releases
   - Remove file completely

### 3.3 Update Documentation

**Update Files:**
- `README.md` - Show new import paths
- `docs/ARCHITECTURE.md` - Document new structure
- `docs/MIGRATION_GUIDE_V2_TO_V3.md` - Help users migrate
- `CHANGELOG.md` - Note all deprecated modules

**Example Migration Guide Entry:**
```markdown
## Migrating from v2.x to v3.0

### Import Path Changes

All top-level processors have moved to organized subdirectories:

| Old Import | New Import |
|-----------|-----------|
| `from ipfs_datasets_py.processors import PDFProcessor` | `from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor` |
| `from ipfs_datasets_py.processors import BatchProcessor` | `from ipfs_datasets_py.processors.specialized.batch import BatchProcessor` |
| `from ipfs_datasets_py.processors import GraphRAGProcessor` | `from ipfs_datasets_py.processors.specialized.graphrag import GraphRAGProcessor` |

**Backward Compatibility:** Old imports will work until v3.0 but trigger deprecation warnings.
```

### 3.4 Automated Refactoring Script

Create `scripts/migrate_imports.py`:
```python
#!/usr/bin/env python3
"""
Automatically update import statements to new processor locations.

Usage:
    python scripts/migrate_imports.py --check    # Dry run
    python scripts/migrate_imports.py --fix      # Update files
"""

import re
import argparse
from pathlib import Path

MIGRATIONS = {
    r"from ipfs_datasets_py\.processors import PDFProcessor": 
        "from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor",
    r"from ipfs_datasets_py\.processors import BatchProcessor":
        "from ipfs_datasets_py.processors.specialized.batch import BatchProcessor",
    # ... more mappings
}

def migrate_file(filepath: Path, dry_run: bool = True):
    content = filepath.read_text()
    updated = content
    
    for old_pattern, new_import in MIGRATIONS.items():
        updated = re.sub(old_pattern, new_import, updated)
    
    if updated != content:
        if dry_run:
            print(f"Would update: {filepath}")
        else:
            filepath.write_text(updated)
            print(f"Updated: {filepath}")
        return True
    return False

# ... rest of script
```

**Estimated Time:** 1-2 weeks

---

### Phase 3 Summary

**Total Estimated Time:** 1-2 weeks  
**Risk:** LOW-MEDIUM (mostly mechanical changes)  
**Dependencies:** Phase 2 (consolidation complete)  
**Deliverables:**
- ✅ All top-level deprecated files removed or wrapped
- ✅ Clean directory structure enforced
- ✅ Migration guide published
- ✅ Automated migration tooling
- ✅ All imports updated

---

## Phase 4: Flatten Multimedia Directory Structure (1-2 weeks)

**Goal:** Reduce deep nesting in multimedia subsystems from 8+ levels to maximum 4 levels.

### 4.1 Current Structure (BEFORE)

```
multimedia/convert_to_txt_based_on_mime_type/
├── configs/
├── converter_system/
│   ├── conversion_pipeline/
│   │   └── functions/
│   │       ├── core.py
│   │       ├── pipeline.py
│   │       └── optimize.py
│   ├── core_resource_manager/
│   │   └── core_resource_manager.py
│   └── file_path_queue/
│       └── file_path_queue.py
├── pools/
│   ├── system_resources/
│   │   └── system_resources_pool_template.py
│   └── non_system_resources/
│       ├── file_path_pool/
│       │   └── file_path_pool.py
│       └── core_functions_pool/
│           ├── core_functions_pool.py
│           └── analyze_functions_in_directory/
│               └── function_analyzer.py
├── utils/
│   ├── common/
│   │   ├── stopwatch.py
│   │   └── asyncio_coroutine.py
│   └── converter_system/
│       ├── monads/
│       │   ├── monad.py
│       │   └── async_.py
│       └── run_in_parallel_with_concurrency_limiter.py
└── main.py

DEPTH: 8 levels
PROBLEMS: Hard to navigate, unclear dependencies, over-engineered
```

### 4.2 Target Structure (AFTER)

**Option A: Flatten Completely (if deprecating)**
```
multimedia/
├── legacy_converter/              [DEPRECATED - minimal wrapper]
│   ├── __init__.py               [Deprecation warning]
│   └── adapter.py                [Routes to file_converter]
└── ... (rest of multimedia stays organized)
```

**Option B: Simplify but Keep (if still needed)**
```
multimedia/txt_converter/          [Renamed from convert_to_txt_based_on_mime_type]
├── __init__.py
├── converter.py                  [MAIN - from main.py]
├── pipeline.py                   [Flattened from converter_system/]
├── resource_manager.py           [Merged from pools/ and core_resource_manager/]
├── queue.py                      [From file_path_queue/]
└── utils/
    ├── async_helpers.py          [Merged from utils/common/ and monads/]
    └── concurrency.py            [From run_in_parallel_with_concurrency_limiter.py]

DEPTH: 3 levels
```

**Recommendation:** Option A (flatten to deprecation wrapper) since we're consolidating into `file_converter/`.

### 4.3 Flattening Strategy

**Step 1: Identify Essential Components**
- What code is actually used in production?
- What can be deleted vs. what must be preserved?
- Run code coverage analysis

```bash
pytest --cov=ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type \
       --cov-report=html
```

**Step 2: Merge Small Modules**
- Combine files < 100 lines into parent modules
- Example: Merge all `utils/converter_system/monads/` into single `async_helpers.py`

**Step 3: Eliminate Unnecessary Abstractions**
- Remove over-engineered patterns (monads, pools) if not adding value
- Simplify resource management
- Use standard libraries where possible

**Step 4: Create Migration Path**
- Document what moved where
- Create import redirects for any external users

### 4.4 Directory Naming Convention

**Current Issues:**
- `convert_to_txt_based_on_mime_type` - too verbose (35 characters!)
- `omni_converter_mk2` - version suffix in name
- Mixed snake_case and PascalCase

**New Convention:**
```
multimedia/
├── converters/              [Clear, concise]
│   ├── text/
│   ├── audio/
│   └── video/
├── processors/              [Format-specific processing]
│   ├── email_processor.py
│   ├── discord_wrapper.py
│   └── ytdlp_wrapper.py
└── utils/                   [Shared utilities]
```

**Estimated Time:** 1-2 weeks

---

### Phase 4 Summary

**Total Estimated Time:** 1-2 weeks  
**Risk:** LOW (mostly moving files)  
**Dependencies:** Phase 2 (consolidation)  
**Deliverables:**
- ✅ Maximum 4 levels of directory nesting
- ✅ Clear, concise directory names
- ✅ Eliminated over-engineering
- ✅ Documentation of changes

---

## Phase 5: Standardize Architecture Patterns (2-3 weeks)

**Goal:** Establish and enforce clear architectural boundaries.

### 5.1 Define Architecture Tiers

```
┌─────────────────────────────────────────────────┐
│                CORE LAYER                       │
│  - ProcessorProtocol (interface)                │
│  - UniversalProcessor (orchestrator)            │
│  - ProcessorRegistry (discovery)                │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│               ADAPTERS LAYER                     │
│  - Standardize specialized processors           │
│  - Implement ProcessorProtocol                  │
│  - Route to specialized implementations         │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│             SPECIALIZED LAYER                    │
│  - batch/     (batch processing)                │
│  - pdf/       (PDF processing)                  │
│  - graphrag/  (knowledge graphs)                │
│  - media/     (audio/video)                     │
│  - multimodal/(multiple formats)                │
│  - web_archive/ (archiving)                     │
│  - ocr/       (optical character recognition)   │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│               DOMAINS LAYER                      │
│  - patent/      (patent-specific)               │
│  - geospatial/  (geo data)                      │
│  - ml/          (ML workflows)                  │
│  - legal/       (legal scraping)                │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│            INFRASTRUCTURE LAYER                  │
│  - monitoring, profiling, error_handling        │
│  - caching, cli, debug_tools                    │
└─────────────────────────────────────────────────┘
```

### 5.2 Enforce Dependency Rules

**Rule 1:** CORE depends on nothing (except stdlib, anyio, typing)
**Rule 2:** ADAPTERS depend only on CORE
**Rule 3:** SPECIALIZED depend on CORE, may use INFRASTRUCTURE
**Rule 4:** DOMAINS depend on CORE + SPECIALIZED, may use INFRASTRUCTURE
**Rule 5:** INFRASTRUCTURE depends only on CORE

**Violations to Fix:**
- `specialized/batch/processor.py` importing from `domains/` ❌
- `core/universal_processor.py` importing from `specialized/` ❌ (should use registry)
- Circular dependencies between modules

### 5.3 Create Architecture Tests

**File:** `tests/architecture/test_dependencies.py`

```python
"""
Test architectural boundaries and dependency rules.
"""
import ast
import pytest
from pathlib import Path

def get_imports(filepath: Path) -> set[str]:
    """Extract all imports from a Python file."""
    tree = ast.parse(filepath.read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports

def test_core_has_no_internal_dependencies():
    """Core modules should not import from specialized, domains, or infrastructure."""
    core_dir = Path("ipfs_datasets_py/processors/core")
    forbidden = {"specialized", "domains", "infrastructure", "adapters"}
    
    for py_file in core_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        imports = get_imports(py_file)
        for imp in imports:
            if any(f".{forbidden_name}." in imp for forbidden_name in forbidden):
                pytest.fail(f"{py_file.name} imports from {forbidden}: {imp}")

def test_adapters_only_depend_on_core():
    """Adapters should only import from core layer."""
    adapters_dir = Path("ipfs_datasets_py/processors/adapters")
    allowed = {"core", "typing", "dataclasses", "abc"}
    
    # ... similar test
    
def test_no_circular_dependencies():
    """No circular dependencies between modules."""
    # Use tools like `pydeps` or custom analysis
    # ...
```

### 5.4 Standardize Module Structure

**Every processor module should have:**

```python
# specialized/example/processor.py

"""
Example Processor

Processes example inputs and returns standardized results.

Usage:
    from ipfs_datasets_py.processors.specialized.example import ExampleProcessor
    
    processor = ExampleProcessor()
    result = await processor.process(input_data)
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from dataclasses import dataclass

import anyio  # ALWAYS use anyio, never asyncio

from ...core.protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingStatus,
    ProcessingMetadata
)

logger = logging.getLogger(__name__)


@dataclass
class ExampleConfig:
    """Configuration for ExampleProcessor."""
    option1: str = "default"
    option2: int = 42


class ExampleProcessor(ProcessorProtocol):
    """
    Processes example inputs.
    
    Implements the ProcessorProtocol interface for integration with
    UniversalProcessor and adapter layer.
    """
    
    def __init__(self, config: Optional[ExampleConfig] = None):
        """Initialize processor."""
        self.config = config or ExampleConfig()
        self.logger = logger
    
    async def process(self, input_data: Any) -> ProcessingResult:
        """
        Process input data.
        
        Args:
            input_data: Input to process
            
        Returns:
            ProcessingResult with knowledge graph and vectors
            
        Raises:
            ProcessorError: If processing fails
        """
        try:
            # Processing logic here
            async with anyio.create_task_group() as tg:
                # Use anyio for async operations
                pass
            
            return ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                knowledge_graph=...,
                vectors=...,
                metadata=ProcessingMetadata(...)
            )
        except Exception as e:
            self.logger.error(f"Processing failed: {e}")
            return ProcessingResult(
                status=ProcessingStatus.FAILED,
                error=str(e)
            )
    
    def can_handle(self, input_data: Any) -> bool:
        """Check if this processor can handle the input."""
        # Detection logic
        return True
```

### 5.5 Update All Processors to Standard Pattern

**Processors to Standardize:**
- [ ] `specialized/batch/processor.py`
- [ ] `specialized/pdf/pdf_processor.py`
- [ ] `specialized/graphrag/unified_graphrag.py`
- [ ] `specialized/media/advanced_processing.py`
- [ ] `specialized/multimodal/multimodal_processor.py`
- [ ] `specialized/web_archive/advanced_archiving.py`
- [ ] All domain processors (patent, geospatial, ml)

**Checklist for Each:**
1. ✅ Implements `ProcessorProtocol`
2. ✅ Uses `anyio` exclusively
3. ✅ Has comprehensive docstring
4. ✅ Proper error handling with `ProcessorError`
5. ✅ Returns standardized `ProcessingResult`
6. ✅ Logging with module logger
7. ✅ Type hints on all methods
8. ✅ Config dataclass if needed

**Estimated Time:** 2-3 weeks

---

### Phase 5 Summary

**Total Estimated Time:** 2-3 weeks  
**Risk:** LOW (structural improvements)  
**Dependencies:** Phases 2-4  
**Deliverables:**
- ✅ Clear architectural boundaries
- ✅ Dependency rules enforced
- ✅ Architecture tests
- ✅ All processors follow standard pattern
- ✅ Documentation updated

---

## Phase 6: Testing & Documentation (1-2 weeks)

### 6.1 Test Suite Updates

**Integration Tests:**
```python
# tests/integration/processors/test_anyio_integration.py

import anyio
import pytest

@pytest.mark.anyio
async def test_all_processors_use_anyio():
    """Verify all processors work with anyio runtime."""
    from ipfs_datasets_py.processors.core import UniversalProcessor
    
    processor = UniversalProcessor()
    result = await processor.process("test input")
    assert result.status == "success"

@pytest.mark.anyio  
async def test_concurrent_processing():
    """Test multiple processors running concurrently."""
    async with anyio.create_task_group() as tg:
        for i in range(10):
            tg.start_soon(process_item, i)
```

**Update pytest Configuration:**
```ini
# pytest.ini

[pytest]
asyncio_mode = auto
anyio_backend = asyncio  # or trio
testpaths = tests
markers =
    anyio: mark test as requiring anyio
    slow: mark test as slow running
```

### 6.2 Documentation Updates

**Files to Create/Update:**

1. **`docs/ARCHITECTURE.md`** - Complete architecture overview
2. **`docs/PROCESSORS_GUIDE.md`** - How to use processors
3. **`docs/ADDING_PROCESSORS.md`** - How to add new processors
4. **`docs/ASYNCIO_TO_ANYIO_MIGRATION.md`** - Migration guide (from Phase 1)
5. **`docs/MIGRATION_V2_TO_V3.md`** - User migration guide (from Phase 3)
6. **`CHANGELOG.md`** - Comprehensive changelog
7. **`README.md`** - Update with new structure

**Key Documentation Sections:**

```markdown
# Processors Architecture Guide

## Overview

The processors system provides a unified interface for processing various
data types (documents, multimedia, web content) into standardized knowledge
graphs and vector representations.

## Architecture Layers

### Core Layer
The foundation providing:
- `ProcessorProtocol`: Standard interface all processors implement
- `UniversalProcessor`: Orchestrator that routes inputs to appropriate processors
- `ProcessorRegistry`: Dynamic discovery and registration

### Adapters Layer  
Bridges between UniversalProcessor and specialized implementations...

### Specialized Layer
Domain-agnostic processors for specific formats...

### Domains Layer
Domain-specific processing logic...

### Infrastructure Layer
Cross-cutting concerns...

## Using Processors

### Basic Usage
```python
import anyio
from ipfs_datasets_py.processors import UniversalProcessor

async def process_file():
    processor = UniversalProcessor()
    result = await processor.process("document.pdf")
    print(result.knowledge_graph)

anyio.run(process_file)
```

### Advanced Configuration
...
```

### 6.3 Code Examples

Create `examples/processors/` directory with complete working examples:

1. **`basic_usage.py`** - Simple processing
2. **`batch_processing.py`** - Process multiple files
3. **`custom_processor.py`** - Creating a custom processor
4. **`anyio_patterns.py`** - Common anyio patterns
5. **`error_handling.py`** - Robust error handling

**Estimated Time:** 1-2 weeks

---

### Phase 6 Summary

**Total Estimated Time:** 1-2 weeks  
**Risk:** LOW  
**Dependencies:** All previous phases  
**Deliverables:**
- ✅ Comprehensive test suite
- ✅ All tests use anyio
- ✅ Architecture documentation
- ✅ User guides and migration guides
- ✅ Working code examples

---

## Implementation Timeline

```
Week 1-2:   Phase 1 - AnyIO Migration (infrastructure)
Week 3:     Phase 1 - AnyIO Migration (multimedia - complex)
Week 4-5:   Phase 2 - Consolidate Conversion Systems
Week 6:     Phase 2 - Consolidate Batch, PDF, Multimodal
Week 7:     Phase 3 - Clean Up Legacy Files
Week 8:     Phase 4 - Flatten Directory Structure
Week 9-10:  Phase 5 - Standardize Architecture Patterns
Week 11-12: Phase 6 - Testing & Documentation

Total: 8-12 weeks
```

## Risk Mitigation

### HIGH RISK: Phase 1 Multimedia Migration
- **Risk:** Complex asyncio usage may break during migration
- **Mitigation:** 
  - Create comprehensive integration tests FIRST
  - Migrate incrementally, testing after each change
  - Keep asyncio version in feature branch as backup
  - Performance benchmark before/after

### MEDIUM RISK: Phase 2 Consolidation
- **Risk:** Breaking changes for external users
- **Mitigation:**
  - Maintain backward compatibility with deprecation wrappers
  - 2-release deprecation period (v2.9 → v3.0)
  - Clear migration guides
  - Automated import migration script

### LOW RISK: Phase 3-6
- **Risk:** Minimal, mostly mechanical changes
- **Mitigation:** Standard testing and review

## Success Criteria

✅ **Phase 1 Complete:**
- Zero `import asyncio` in processors directory
- All async code uses anyio
- Tests pass with anyio backend
- No performance regression

✅ **Phase 2 Complete:**
- Single file conversion system
- Single batch processing implementation
- All specialized processors consolidated
- Backward compatibility maintained

✅ **Phase 3 Complete:**
- No deprecated top-level files
- Clean directory structure
- All imports use new paths

✅ **Phase 4 Complete:**
- Maximum 4 directory levels
- No over-engineered patterns
- Clear naming conventions

✅ **Phase 5 Complete:**
- All processors implement ProcessorProtocol
- Architecture tests passing
- Dependency rules enforced

✅ **Phase 6 Complete:**
- 90%+ test coverage
- Complete documentation
- Working examples

## Maintenance Plan

**Post-Refactoring:**

1. **Enforce Architecture**
   - CI checks for dependency violations
   - Pre-commit hooks for import validation
   - Regular architecture reviews

2. **Keep Documentation Updated**
   - Document all new processors
   - Update migration guides
   - Maintain examples

3. **Monitor Technical Debt**
   - Regular code quality scans
   - Address issues promptly
   - Prevent duplication

4. **Version Management**
   - Follow semantic versioning
   - Deprecation policy (2 releases minimum)
   - Clear changelog

---

## Appendix A: AnyIO Reference

### Key AnyIO Patterns

#### Task Groups (replaces asyncio.gather)
```python
import anyio

async def process_batch(items):
    results = []
    
    async with anyio.create_task_group() as tg:
        for item in items:
            tg.start_soon(process_item, item, results)
    
    return results

async def process_item(item, results):
    result = await expensive_operation(item)
    results.append(result)
```

#### Timeouts (replaces asyncio.wait_for)
```python
import anyio

async def with_timeout():
    try:
        with anyio.fail_after(30):  # 30 second timeout
            result = await long_operation()
    except TimeoutError:
        print("Operation timed out")
```

#### Concurrency Limiting (replaces asyncio.Semaphore)
```python
import anyio

limiter = anyio.CapacityLimiter(10)  # Max 10 concurrent

async def limited_operation():
    async with limiter:
        await expensive_operation()
```

#### Sleeping (replaces asyncio.sleep)
```python
import anyio

async def wait_a_bit():
    await anyio.sleep(1.0)
```

#### Thread Pool (replaces loop.run_in_executor)
```python
import anyio

async def run_blocking():
    result = await anyio.to_thread.run_sync(blocking_function, arg1, arg2)
    return result
```

#### Memory Channels (replaces asyncio.Queue)
```python
import anyio

async def producer_consumer():
    send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=100)
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(producer, send_stream)
        tg.start_soon(consumer, receive_stream)

async def producer(send_stream):
    async with send_stream:
        for i in range(10):
            await send_stream.send(i)

async def consumer(receive_stream):
    async with receive_stream:
        async for item in receive_stream:
            print(item)
```

---

## Appendix B: File Conversion System Comparison

| Feature | file_converter/ | convert_to_txt/ | omni_mk2/ |
|---------|----------------|-----------------|-----------|
| Lines of Code | ~2,000 | ~3,500 | ~2,500 |
| Directory Depth | 3 levels | 8 levels | 5 levels |
| Backend System | ✅ Clean plugins | ❌ Monolithic | ⚠️ Partial |
| IPFS Integration | ✅ Native | ❌ None | ❌ None |
| Batch Processing | ✅ Yes | ✅ Yes | ✅ Yes |
| URL Support | ✅ Yes | ❌ No | ❌ No |
| Archive Support | ✅ Yes | ❌ No | ❌ No |
| GUI | ❌ No | ❌ No | ✅ Yes |
| Test Coverage | ✅ High | ⚠️ Medium | ⚠️ Medium |
| Async Framework | ✅ anyio | ❌ asyncio | ⚠️ Mixed |
| Maintenance | ✅ Active | ❌ Legacy | ⚠️ Partial |
| **Recommendation** | **KEEP** | **DEPRECATE** | **MERGE** |

---

## Appendix C: Checklist

Use this checklist to track progress:

### Phase 1: AnyIO Migration
- [ ] 1.1 Infrastructure layer migrated
- [ ] 1.2 Core layer migrated
- [ ] 1.3 Specialized processors migrated
- [ ] 1.4 Multimedia subsystem migrated
- [ ] 1.5 Documentation created
- [ ] All tests passing with anyio

### Phase 2: Consolidation
- [ ] 2.1 Conversion systems analyzed
- [ ] 2.2 Valuable components extracted
- [ ] 2.3 Single unified system created
- [ ] 2.4 Batch processing consolidated
- [ ] 2.5 PDF processing consolidated
- [ ] 2.6 Multimodal processing consolidated
- [ ] Backward compatibility maintained

### Phase 3: Legacy Cleanup
- [ ] 3.1 Top-level files removed/deprecated
- [ ] 3.2 Deprecation wrappers created
- [ ] 3.3 __init__.py updated
- [ ] 3.4 Internal references updated
- [ ] 3.5 Documentation updated
- [ ] 3.6 Migration script created

### Phase 4: Flatten Structure
- [ ] 4.1 Essential components identified
- [ ] 4.2 Small modules merged
- [ ] 4.3 Unnecessary abstractions removed
- [ ] 4.4 Directory naming standardized
- [ ] Maximum 4 levels enforced

### Phase 5: Standardize Patterns
- [ ] 5.1 Architecture tiers defined
- [ ] 5.2 Dependency rules enforced
- [ ] 5.3 Architecture tests created
- [ ] 5.4 Module structure standardized
- [ ] 5.5 All processors updated

### Phase 6: Testing & Documentation
- [ ] 6.1 Test suite updated
- [ ] 6.2 Documentation created
- [ ] 6.3 Code examples created
- [ ] All deliverables complete

---

## Conclusion

This comprehensive refactoring plan will:
1. ✅ Standardize on anyio for all async operations
2. ✅ Eliminate duplicate functionality
3. ✅ Simplify complex directory structures
4. ✅ Establish clear architectural boundaries
5. ✅ Improve maintainability and code quality

**Estimated Total Effort:** 8-12 weeks  
**Risk Level:** MEDIUM-HIGH (but well-mitigated)  
**Impact:** HIGH (significantly improved codebase quality)

**Next Steps:**
1. Review and approve this plan
2. Schedule phases with team
3. Begin Phase 1 implementation
4. Regular progress reviews and adjustments

---

*Document Version: 1.0*  
*Last Updated: 2026-02-16*  
*Author: GitHub Copilot Coding Agent*
