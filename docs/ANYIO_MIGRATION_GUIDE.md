# anyio Migration and Backend Deprecation Guide

**Version:** 0.4.0  
**Date:** January 30, 2026  
**Status:** Active Migration Period

## Overview

Starting with version 0.4.0, the file_converter module has migrated from `asyncio` to `anyio` and deprecated the external library backends (markitdown, omni) in favor of the native implementation.

## What Changed

### 1. Async Library Migration: asyncio → anyio

**Why anyio?**
- ✅ Compatible with multiple async backends (asyncio, trio, curio)
- ✅ Better structured concurrency primitives
- ✅ More intuitive API (CapacityLimiter vs Semaphore)
- ✅ Better timeout and cancellation handling
- ✅ Cleaner task group management

**Impact:**
- **Users:** No code changes needed! anyio is backward compatible with asyncio.
- **Developers:** Internal implementation uses anyio patterns.

### 2. Backend Deprecation

The following backends are now deprecated:

| Backend | Status | Removal Version | Alternative |
|---------|--------|----------------|-------------|
| `markitdown` | ⚠️ Deprecated | 0.5.0 | `native` |
| `omni` | ⚠️ Deprecated | 0.5.0 | `native` |
| `native` | ✅ Recommended | - | Current default |

## Migration Timeline

### Phase 1: Warning Period (v0.4.0 - Current)

**Status:** Active  
**Duration:** Until v0.5.0 release

- Deprecated backends still work
- Deprecation warnings shown on usage
- Native backend is recommended

### Phase 2: Removal (v0.5.0 - Future)

**Status:** Planned  
**Timeline:** TBD

- Deprecated backends removed from codebase
- Only native backend available
- Breaking change for users still using old backends

## User Migration Guide

### Before (Deprecated)

```python
from ipfs_datasets_py.file_converter import FileConverter

# Using markitdown backend (now deprecated)
converter = FileConverter(backend='markitdown')
result = await converter.convert('document.pdf')

# Using omni backend (now deprecated)
converter = FileConverter(backend='omni')
result = await converter.convert('document.pdf')
```

**Warning Message:**
```
DeprecationWarning: The 'markitdown' backend is deprecated and will be removed in version 0.5.0.
Please migrate to the 'native' backend which provides:
  • Native implementation (no external dependencies)
  • Better performance and reliability
  • Full feature parity
  • IPFS and ML acceleration support

Migration: FileConverter(backend='native')
Documentation: See docs/FILE_CONVERSION_INTEGRATION_PLAN.md
```

### After (Recommended)

```python
from ipfs_datasets_py.file_converter import FileConverter

# Use native backend (recommended)
converter = FileConverter(backend='native')
result = await converter.convert('document.pdf')

# Or let it auto-select (prefers native)
converter = FileConverter(backend='auto')
result = await converter.convert('document.pdf')

# Or use IPFS-accelerated version (includes native)
from ipfs_datasets_py.file_converter import IPFSAcceleratedConverter
converter = IPFSAcceleratedConverter(backend='native')
result = await converter.convert('document.pdf')
```

## Why Migrate?

### Benefits of Native Backend

**Performance:**
- ✅ No external library overhead
- ✅ Direct format detection
- ✅ Optimized text extraction
- ✅ Faster batch processing

**Dependencies:**
- ✅ Zero required external dependencies
- ✅ Optional dependencies for advanced features
- ✅ Smaller installation size
- ✅ Fewer version conflicts

**Features:**
- ✅ Format detection for 60+ file types
- ✅ Native extraction for 15+ formats
- ✅ Rich metadata extraction
- ✅ IPFS storage integration
- ✅ ML acceleration support
- ✅ Enhanced error handling

**Reliability:**
- ✅ Better error messages
- ✅ Graceful degradation
- ✅ Automatic fallback strategies
- ✅ Comprehensive test coverage

## Checking for Deprecated Usage

### Using Deprecation Info

```python
from ipfs_datasets_py.file_converter import (
    is_deprecated,
    get_deprecation_info,
    DEPRECATION_TIMELINE
)

# Check if a backend is deprecated
if is_deprecated('markitdown'):
    print("This backend is deprecated!")

# Get deprecation details
info = get_deprecation_info('markitdown')
print(f"Deprecated in: {info['deprecated_in']}")
print(f"Removal in: {info['removal_in']}")
print(f"Alternative: {info['alternative']}")
print(f"Reason: {info['reason']}")

# View full timeline
print(DEPRECATION_TIMELINE)
```

### Suppressing Warnings (Not Recommended)

If you need to temporarily suppress deprecation warnings:

```python
import warnings
from ipfs_datasets_py.file_converter.deprecation import DeprecationWarning

# Suppress only file_converter deprecation warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

# Use deprecated backend without warning
converter = FileConverter(backend='markitdown')
```

**⚠️ Warning:** This is not recommended. The warnings exist to help you migrate before the backends are removed.

## Feature Comparison

### markitdown Backend vs Native

| Feature | markitdown | native |
|---------|-----------|--------|
| External deps | ❌ Required | ✅ Zero required |
| Format detection | ✅ Basic | ✅ Advanced (60+ types) |
| Text extraction | ✅ Good | ✅ Excellent |
| Metadata | ❌ Limited | ✅ Rich |
| IPFS integration | ❌ No | ✅ Yes |
| ML acceleration | ❌ No | ✅ Yes |
| Error handling | ❌ Basic | ✅ Comprehensive |
| Async pipeline | ❌ No | ✅ Yes |
| Batch optimization | ❌ Basic | ✅ Advanced |
| Status | ⚠️ Deprecated | ✅ Active |

### omni Backend vs Native

| Feature | omni | native |
|---------|------|--------|
| External deps | ❌ Required | ✅ Zero required |
| Format detection | ✅ Good | ✅ Advanced (60+ types) |
| Text extraction | ✅ Good | ✅ Excellent |
| Metadata | ✅ Rich | ✅ Rich |
| IPFS integration | ❌ No | ✅ Yes |
| ML acceleration | ❌ No | ✅ Yes |
| Error handling | ❌ Basic | ✅ Comprehensive |
| Async pipeline | ❌ No | ✅ Yes |
| Batch optimization | ✅ Good | ✅ Advanced |
| Status | ⚠️ Deprecated | ✅ Active |

## anyio for Developers

If you're developing with the file_converter module, here are the key anyio patterns:

### Concurrency Control

**Before (asyncio):**
```python
import asyncio

semaphore = asyncio.Semaphore(5)

async def process(item):
    async with semaphore:
        return await do_work(item)
```

**After (anyio):**
```python
import anyio

limiter = anyio.CapacityLimiter(5)

async def process(item):
    async with limiter:
        return await do_work(item)
```

### Task Groups

**Before (asyncio):**
```python
import asyncio

tasks = [process(item) for item in items]
results = await asyncio.gather(*tasks)
```

**After (anyio):**
```python
import anyio

results = []

async with anyio.create_task_group() as tg:
    for i, item in enumerate(items):
        tg.start_soon(process, item, i)
```

### Timeouts

**Before (asyncio):**
```python
import asyncio

try:
    result = await asyncio.wait_for(
        long_operation(),
        timeout=30.0
    )
except asyncio.TimeoutError:
    print("Timed out!")
```

**After (anyio):**
```python
import anyio

try:
    with anyio.fail_after(30.0):
        result = await long_operation()
except TimeoutError:
    print("Timed out!")
```

### Running Blocking Code

**Before (asyncio):**
```python
import asyncio

result = await asyncio.to_thread(blocking_operation)
```

**After (anyio):**
```python
import anyio

result = await anyio.to_thread.run_sync(blocking_operation)
```

### Sync Wrappers

**Before (asyncio):**
```python
import asyncio

result = asyncio.run(async_function())
```

**After (anyio):**
```python
import anyio

result = anyio.from_thread.run(async_function)
```

## Testing

### Running Tests

The test suite works with both asyncio and anyio backends:

```bash
# Run with asyncio (default)
pytest tests/unit/test_file_converter.py

# Run with trio backend
pytest tests/unit/test_file_converter.py --trio-mode

# Check for deprecation warnings
pytest tests/unit/test_file_converter.py -W default::DeprecationWarning
```

### Testing Deprecated Backends

```python
import pytest
import warnings

def test_deprecated_backend():
    """Test that deprecated backends show warnings."""
    
    with pytest.warns(DeprecationWarning, match="deprecated"):
        converter = FileConverter(backend='markitdown')
    
    # Backend should still work during deprecation period
    assert converter is not None
```

## FAQ

### Q: Do I need to change my code?

**A:** If you're using `backend='native'` or `backend='auto'`, no changes needed. If you're using `backend='markitdown'` or `backend='omni'`, you should migrate to `backend='native'`.

### Q: When will the old backends be removed?

**A:** Version 0.5.0 (timeline TBD). You'll have plenty of warning.

### Q: Will my async code break?

**A:** No. anyio is backward compatible with asyncio. Your existing async code will continue to work.

### Q: What if I need markitdown-specific features?

**A:** The native backend provides feature parity. If you find a feature missing, please file an issue.

### Q: Can I still use the submodules directly?

**A:** Yes, the submodules are still available in `ipfs_datasets_py/multimedia/`. However, using them directly is not recommended.

### Q: How do I suppress the warnings temporarily?

**A:** See the "Suppressing Warnings" section above. But please migrate instead!

## Support

**Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues  
**Documentation:** See `docs/FILE_CONVERSION_INTEGRATION_PLAN.md`  
**Migration Help:** File an issue with the "migration" label

## Summary

**Current Version:** 0.4.0  
**Status:** Active migration period  
**Action Required:** Migrate from markitdown/omni to native backend  
**Timeline:** Before version 0.5.0

**Recommended Migration:**
```python
# Old (deprecated)
converter = FileConverter(backend='markitdown')

# New (recommended)
converter = FileConverter(backend='native')
```

The native backend provides better performance, zero dependencies, and full feature parity with the deprecated backends. Please migrate at your earliest convenience!
