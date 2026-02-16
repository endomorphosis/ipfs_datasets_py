# Processors Async Refactoring Plan with Anyio

**Date:** 2026-02-15  
**Status:** In Progress  
**Objective:** Make all processor infrastructure async-first with anyio support

---

## Overview

Based on feedback, we're reversing the sync migration and making the entire processor system async-first using anyio for unified async/await support across different async backends (asyncio, trio, etc.).

---

## Why Async + Anyio?

1. **I/O Bound Operations:** Most processor operations involve I/O (network requests, file reading, IPFS operations)
2. **Concurrent Processing:** Can process multiple inputs simultaneously
3. **Backend Flexibility:** Anyio allows switching between asyncio, trio, etc. without code changes
4. **Modern Python:** Async/await is the standard for I/O-bound Python applications
5. **Better Performance:** Non-blocking I/O for network-heavy workloads

---

## Changes Required

### Phase 1: Core Protocol (DONE ✅)
- [x] Update `processors/core/protocol.py` to use async methods
- [x] Add anyio import and availability check
- [x] Change `can_handle()` to `async def`
- [x] Change `process()` to `async def`
- [x] Keep `get_capabilities()` synchronous (returns static data)
- [x] Update `is_processor()` to check for coroutine functions
- [x] Add anyio usage examples in docstrings

### Phase 2: Adapters (DONE ✅ - Reverted to Original Async)
- [x] pdf_adapter.py - Already async
- [x] graphrag_adapter.py - Already async
- [x] multimedia_adapter.py - Already async
- [x] file_converter_adapter.py - Already async
- [x] batch_adapter.py - Already async
- [x] ipfs_adapter.py - Already async
- [x] web_archive_adapter.py - Already async
- [x] specialized_scraper_adapter.py - Already async

All adapters are already using the async protocol from `processors/protocol.py`.

### Phase 3: Core Infrastructure (DONE ✅)
- [x] Update `UniversalProcessor` to use async methods
  - `async def process()`
  - `async def process_batch()`
  - Handle async processor selection
- [x] Update `ProcessorRegistry` for async
  - `async def get_processors()` - needs to call async `can_handle()`
- [x] Update `InputDetector` (can stay sync - no I/O)
- [x] Add anyio utilities module for common patterns

### Phase 4: Auto-Registration (DONE ✅)
- [x] Keep auto-registration synchronous (just registers, doesn't process)
- [x] Update to work with async processors (no changes needed)
- [x] Add anyio backend detection (not needed)

### Phase 5: Examples & Documentation (DONE ✅)
- [x] Update all examples to use async/await
- [x] Add anyio installation instructions
- [x] Document async best practices
- [x] Create async processing example (08_async_processing.py)
- [x] Update IPFS example to use anyio

### Phase 6: Testing (DONE ✅)
- [x] Use pytest-asyncio for tests
- [x] Test async processor integration
- [x] Add async integration tests
- [x] All existing tests updated and passing

---

## Anyio Integration Patterns

### Pattern 1: Async File I/O
```python
import anyio

async def process_file(path):
    async with anyio.open_file(path, 'r') as f:
        content = await f.read()
    return content
```

### Pattern 2: Concurrent Tasks
```python
async def process_multiple(items):
    async with anyio.create_task_group() as tg:
        for item in items:
            tg.start_soon(process_item, item)
```

### Pattern 3: CPU-Bound Work
```python
async def process_with_cpu_work(data):
    # Run CPU-bound work in thread pool
    result = await anyio.to_thread.run_sync(cpu_intensive_function, data)
    return result
```

### Pattern 4: Timeouts
```python
async def process_with_timeout(data, timeout=30):
    with anyio.fail_after(timeout):
        result = await process(data)
    return result
```

---

## API Changes

### Before (Sync - What we just did)
```python
from ipfs_datasets_py.processors.core import UniversalProcessor

processor = UniversalProcessor()
result = processor.process("document.pdf")  # Sync
```

### After (Async with Anyio)
```python
import anyio
from ipfs_datasets_py.processors.core import UniversalProcessor

async def main():
    processor = UniversalProcessor()
    result = await processor.process("document.pdf")  # Async
    
# Run with anyio (works with asyncio, trio, etc.)
anyio.run(main)
```

---

## Migration Path for Users

### Option 1: Use anyio.run()
```python
import anyio
from ipfs_datasets_py.processors.core import process

result = anyio.run(process, "document.pdf")
```

### Option 2: Already in async context
```python
async def my_application():
    result = await process("document.pdf")
```

### Option 3: Sync wrapper (for backward compat)
```python
def process_sync(input_data):
    """Synchronous wrapper for async process."""
    import anyio
    return anyio.run(process, input_data)
```

---

## Dependencies

### Required
- `anyio` - Core async abstraction library

### Optional
- `trio` - Alternative async backend (if not using asyncio)
- `pytest-anyio` - For testing with anyio
- `aiofiles` - Async file operations (if needed beyond anyio)

---

## Implementation Timeline

1. **Phase 1** ✅ - Core protocol async (DONE)
2. **Phase 2** ✅ - Adapters (already async, reverted sync changes)
3. **Phase 3** 🚧 - Core infrastructure (IN PROGRESS)
4. **Phase 4** 📋 - Auto-registration
5. **Phase 5** 📋 - Examples & docs
6. **Phase 6** 📋 - Testing

**Estimated Time:** 4-6 hours for complete implementation

---

## Benefits

1. **Concurrent Processing:** Process multiple files simultaneously
2. **Non-Blocking I/O:** Better resource utilization
3. **Backend Flexibility:** Switch between asyncio/trio without code changes
4. **Modern Patterns:** Follows current Python async best practices
5. **Better Performance:** For I/O-bound workloads (IPFS, network, file I/O)

---

## Challenges & Solutions

### Challenge 1: Mixing Async and Sync Code
**Solution:** Use `anyio.to_thread.run_sync()` for CPU-bound or sync operations

### Challenge 2: Testing Complexity
**Solution:** Use pytest-anyio for unified test approach

### Challenge 3: Backward Compatibility
**Solution:** Provide sync wrapper functions for gradual migration

### Challenge 4: Learning Curve
**Solution:** Comprehensive examples and documentation

---

## Performance Expectations

### I/O-Bound Operations (Expected Improvement)
- Single file: Similar to sync
- 10 files: ~5-8x faster (concurrent processing)
- 100 files: ~20-50x faster (limited by I/O)

### CPU-Bound Operations
- No significant improvement (use anyio.to_thread.run_sync())
- May have slight overhead from async machinery

---

## Next Steps

1. ✅ Update core protocol to async
2. ✅ Revert adapters to async
3. 🚧 Update UniversalProcessor for async
4. 🚧 Update ProcessorRegistry for async  
5. 📋 Update examples
6. 📋 Update documentation
7. 📋 Add tests

---

**Last Updated:** 2026-02-15  
**Status:** Phase 3 Starting
