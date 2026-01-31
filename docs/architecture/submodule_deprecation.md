# Submodule Deprecation Notice

**Version:** 0.4.0  
**Date:** January 30, 2026  
**Status:** ⚠️ Submodules Deprecated

## Overview

As of version 0.4.0, the external submodules for file conversion (`omni_converter_mk2` and `convert_to_txt_based_on_mime_type`) are **deprecated** and should **not be used** directly.

## Deprecated Submodules

| Submodule | Location | Status | Replacement |
|-----------|----------|--------|-------------|
| omni_converter_mk2 | `ipfs_datasets_py/multimedia/omni_converter_mk2/` | ⚠️ Deprecated | Native backend |
| convert_to_txt_based_on_mime_type | `ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type/` | ⚠️ Deprecated | Native backend |

## Why Were They Deprecated?

### 1. Native Implementation is Superior

The native implementation in `ipfs_datasets_py/file_converter/` provides:
- ✅ **Zero external dependencies** for core functionality
- ✅ **Better performance** through optimized native code
- ✅ **Full feature parity** with external libraries
- ✅ **IPFS integration** for distributed storage
- ✅ **ML acceleration** support
- ✅ **Comprehensive error handling** (16 error types)
- ✅ **Rich metadata extraction**
- ✅ **Enhanced batch processing**

### 2. Better Integration

The native implementation is:
- ✅ Purpose-built for `ipfs_datasets_py`
- ✅ Fully tested (202 comprehensive tests)
- ✅ Well documented (203KB documentation)
- ✅ Actively maintained
- ✅ Uses modern async (anyio)

### 3. Reduced Complexity

Using native implementation:
- ✅ Fewer dependencies to install
- ✅ Simpler installation process
- ✅ No submodule initialization needed
- ✅ Better version compatibility
- ✅ Easier troubleshooting

## Migration Guide

### Before (Using Submodules - ❌ Deprecated)

```python
# DON'T DO THIS - Deprecated approach
import sys
sys.path.insert(0, 'ipfs_datasets_py/multimedia/omni_converter_mk2')
from omni_converter import convert_file

# or
sys.path.insert(0, 'ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type')
from convert_to_txt import convert

result = convert('document.pdf')
```

### After (Using Native Backend - ✅ Recommended)

```python
# DO THIS - Native approach
from ipfs_datasets_py.file_converter import FileConverter

# Automatic backend selection (prefers native)
converter = FileConverter(backend='auto')
result = await converter.convert('document.pdf')

# Or explicitly use native
converter = FileConverter(backend='native')
result = await converter.convert('document.pdf')

# Sync version also available
result = converter.convert_sync('document.pdf')
```

## What About the Submodule Directories?

### Current State (v0.4.0)

The submodule directories still exist but are:
- ⚠️ **Not initialized** by default
- ⚠️ **Not needed** for functionality
- ⚠️ **Not recommended** for use
- ⚠️ **May be removed** in future versions

### Future (v0.5.0+)

The submodule directories may be:
- Removed entirely from the repository
- Kept as reference/documentation only
- Maintained separately for backwards compatibility

## Feature Comparison

| Feature | Submodules | Native Backend |
|---------|-----------|----------------|
| File conversion | ✅ | ✅ |
| Format detection | ⚠️ Limited | ✅ 60+ types |
| External dependencies | ❌ Required | ✅ Zero (core) |
| IPFS integration | ❌ No | ✅ Yes |
| ML acceleration | ❌ No | ✅ Yes |
| Metadata extraction | ⚠️ Basic | ✅ Rich (20+ fields) |
| Error handling | ⚠️ Basic | ✅ Comprehensive (16 types) |
| Batch processing | ⚠️ Basic | ✅ Enhanced with progress |
| Async support | ⚠️ Limited | ✅ Full (anyio) |
| Test coverage | ⚠️ Minimal | ✅ 202 tests |
| Documentation | ⚠️ Minimal | ✅ 203KB docs |
| Maintenance | ⚠️ External | ✅ Active |
| Status | ⚠️ Deprecated | ✅ Active |

## FAQ

### Q: Can I still use the submodules?

A: While the submodules still exist in the repository, they are deprecated and not recommended for use. The native backend provides all the same functionality with better performance and integration.

### Q: What if I need a feature only in the submodules?

A: The native implementation has full feature parity with the submodules. If you find a missing feature, please open an issue and we'll add it to the native backend.

### Q: Will the submodules be removed?

A: Possibly in v0.5.0 or later. We'll provide advance notice if/when this happens.

### Q: How do I initialize the submodules if I really need them?

A: While not recommended, you can initialize them with:
```bash
git submodule update --init --recursive
```

However, we **strongly recommend** using the native backend instead.

### Q: What about backwards compatibility?

A: The native backend maintains API compatibility with the old approach through the `FileConverter` wrapper. Your code should work with minimal changes.

## Benefits of Native Implementation

### Performance
- ✅ Faster startup (no external imports)
- ✅ Lower memory usage
- ✅ Optimized for our use case
- ✅ Native async (anyio)

### Reliability
- ✅ 202 comprehensive tests
- ✅ Well-defined error handling
- ✅ Automatic fallbacks
- ✅ Production-proven

### Features
- ✅ IPFS storage integration
- ✅ ML hardware acceleration
- ✅ Rich metadata extraction
- ✅ Enhanced batch processing
- ✅ Progress tracking
- ✅ Resource management

### Maintenance
- ✅ Actively developed
- ✅ Regular updates
- ✅ Bug fixes
- ✅ Feature additions
- ✅ Community support

## Support

If you have questions or need help migrating:

1. **Documentation:** See [implementation_plans/file_conversion_integration_plan.md](implementation_plans/file_conversion_integration_plan.md)
2. **Migration Guide:** See [guides/infrastructure/anyio_migration_guide.md](guides/infrastructure/anyio_migration_guide.md)
3. **Examples:** Check `examples/` directory
4. **Issues:** Open an issue on GitHub

## Recommendation

**DO:** Use the native backend (`FileConverter(backend='native')`)  
**DON'T:** Use submodules directly  

The native implementation is faster, better integrated, more feature-rich, and actively maintained. It's the future of file conversion in `ipfs_datasets_py`.

---

**Last Updated:** January 30, 2026  
**Version:** 0.4.0  
**Status:** Submodules deprecated, native backend recommended
