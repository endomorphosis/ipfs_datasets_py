# File Converter Migration Guide

**Date:** 2026-02-16  
**Status:** Active  
**Target Version:** v3.0.0  

---

## Deprecated Systems

The following conversion systems are **deprecated** and will be removed in **v3.0.0**:

1. **`multimedia.convert_to_txt_based_on_mime_type`** (103 files, 1.2MB)
   - Legacy asyncio-based system
   - Complex nested structure (8 levels deep)
   - Limited features (no IPFS, URL, archive support)

2. **`multimedia.omni_converter_mk2`** (342 files, 13MB)
   - Large GUI-focused system
   - Partial feature overlap
   - Not integrated with main system

---

## New Unified System

**Use:** `ipfs_datasets_py.processors.file_converter.FileConverter`

### Why Migrate?

✅ **Single source of truth** - One well-tested conversion system  
✅ **Modern async** - Uses anyio (not asyncio)  
✅ **More features** - IPFS, URLs, archives, batch processing  
✅ **Better architecture** - Clean backend plugin system  
✅ **Active maintenance** - Primary focus for improvements  

---

## Migration Examples

### Example 1: Basic File Conversion

#### Before (Deprecated ❌)
```python
# OLD - Don't use
from ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type import convert_file

result = convert_file("document.pdf", "output.txt")
```

#### After (Recommended ✅)
```python
# NEW - Use this
from ipfs_datasets_py.processors.file_converter import FileConverter

converter = FileConverter()
result = converter.convert("document.pdf", output_path="output.txt")
```

---

### Example 2: Batch Processing

#### Before (Deprecated ❌)
```python
# OLD
from ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type import batch_convert

files = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
results = batch_convert(files, output_dir="outputs/")
```

#### After (Recommended ✅)
```python
# NEW
from ipfs_datasets_py.processors.file_converter import FileConverter

converter = FileConverter()
files = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]

results = []
for file in files:
    result = converter.convert(file, output_dir="outputs/")
    results.append(result)

# Or use batch processor
from ipfs_datasets_py.processors.file_converter.batch_processor import BatchProcessor

batch = BatchProcessor(converter)
results = batch.process_batch(files, output_dir="outputs/")
```

---

### Example 3: Custom Backend

#### Before (Deprecated ❌)
```python
# OLD - Limited customization
from ipfs_datasets_py.processors.multimedia.omni_converter_mk2 import OmniConverter

converter = OmniConverter(backend="custom")
result = converter.convert("document.pdf")
```

#### After (Recommended ✅)
```python
# NEW - Clean backend system
from ipfs_datasets_py.processors.file_converter import FileConverter
from ipfs_datasets_py.processors.file_converter.backends import MarkitdownBackend

converter = FileConverter(backend=MarkitdownBackend())
result = converter.convert("document.pdf")
```

---

## Feature Comparison

| Feature | convert_to_txt | omni_mk2 | file_converter |
|---------|----------------|----------|----------------|
| **Async Framework** | asyncio ❌ | mixed ⚠️ | anyio ✅ |
| **IPFS Support** | No ❌ | No ❌ | Yes ✅ |
| **URL Support** | No ❌ | No ❌ | Yes ✅ |
| **Archive Support** | No ❌ | No ❌ | Yes ✅ |
| **Batch Processing** | Yes ✅ | Yes ✅ | Yes ✅ |
| **Backend System** | No ❌ | Partial ⚠️ | Yes ✅ |
| **PDF Processing** | Basic ⚠️ | Good ✅ | Good ✅ |
| **Audio/Video** | Basic ⚠️ | Good ✅ | Good ✅ |
| **Image Processing** | Basic ⚠️ | Good ✅ | Good ✅ |
| **Office Formats** | Basic ⚠️ | Good ✅ | Good ✅ |
| **GUI** | No ❌ | Yes ✅ | Planned 🔮 |
| **File Count** | 103 files | 342 files | 25 files |
| **Size** | 1.2MB | 13MB | 344KB |
| **Complexity** | High 😰 | Very High 😱 | Low 😊 |

---

## Common Migration Patterns

### Pattern 1: Import Path Change

```python
# OLD ❌
from ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type import X

# NEW ✅
from ipfs_datasets_py.processors.file_converter import X
```

### Pattern 2: Class Instantiation

```python
# OLD ❌
converter = OldConverter(config=old_config)

# NEW ✅
from ipfs_datasets_py.processors.file_converter import FileConverter, FileConverterConfig

config = FileConverterConfig(
    backend="markitdown",  # or "native", "omni"
    # ... other options
)
converter = FileConverter(config=config)
```

### Pattern 3: Async Usage

```python
# OLD ❌ (asyncio)
import asyncio


async def main():
    result = await old_converter.convert_async("file.pdf")


asyncio.run(main())

# NEW ✅ (anyio)
import anyio


async def main():
    result = await converter.convert("file.pdf")


anyio.run(main)
```

---

## Migration Checklist

Use this checklist when migrating your code:

- [ ] **Audit Usage**
  - [ ] Find all imports from deprecated systems
  - [ ] List all conversion operations
  - [ ] Identify custom configurations

- [ ] **Update Imports**
  - [ ] Replace `convert_to_txt_based_on_mime_type` imports
  - [ ] Replace `omni_converter_mk2` imports
  - [ ] Use `file_converter` instead

- [ ] **Update Code**
  - [ ] Change class instantiation
  - [ ] Update method calls if needed
  - [ ] Migrate asyncio → anyio if applicable

- [ ] **Test**
  - [ ] Run existing tests
  - [ ] Verify conversions work
  - [ ] Check output quality

- [ ] **Deploy**
  - [ ] Update production code
  - [ ] Monitor for issues
  - [ ] Document any problems

---

## Timeline

### Current: v2.9.x
- ✅ Deprecation warnings added
- ✅ Migration guide published
- ✅ Both systems still work
- ⚠️ Warnings appear on import

### Future: v3.0.0
- ❌ Legacy systems removed
- ✅ Only `file_converter` available
- 📅 Date TBD (estimated 6-12 months)

### Transition Period
You have **at least 6 months** (probably longer) to migrate.

---

## Need Help?

### Documentation
- **Refactoring Plan:** `PROCESSORS_REFACTORING_PLAN_2026_02_16.md`
- **file_converter README:** `ipfs_datasets_py/processors/file_converter/README.md`
- **AnyIO Quick Reference:** `PROCESSORS_ANYIO_QUICK_REFERENCE.md`

### Examples
- **Basic Usage:** `examples/file_converter/basic_usage.py`
- **Batch Processing:** `examples/file_converter/batch_processing.py`
- **Custom Backends:** `examples/file_converter/custom_backend.py`

### Support
- **GitHub Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues
- **Discussions:** https://github.com/endomorphosis/ipfs_datasets_py/discussions
- **Tag:** Use `migration:file-converter` label

---

## FAQ

### Q: Why are these systems being deprecated?

**A:** We had 3 overlapping file conversion systems totaling 445 files and 14.2MB. This created:
- Maintenance burden
- User confusion (which to use?)
- Duplicate features
- Mixed async frameworks (asyncio vs anyio)

Consolidating to 1 system (`file_converter`) provides a better experience for everyone.

### Q: Will my code break immediately?

**A:** No! Your code will continue working but show deprecation warnings. You have until v3.0.0 to migrate.

### Q: What if I need a feature from the old system?

**A:** Check if `file_converter` has it (probably does). If not:
1. Open a GitHub issue describing the feature
2. We'll prioritize adding it before removing old systems
3. Contribute a PR if you can!

### Q: What about the GUI from omni_mk2?

**A:** The GUI is being evaluated for extraction. If needed, it will be added to `file_converter/gui/` before v3.0.

### Q: Can I help?

**A:** Yes! We welcome:
- Testing `file_converter` with your use cases
- Reporting missing features
- Contributing backend implementations
- Improving documentation

### Q: When exactly is v3.0.0?

**A:** Not yet scheduled. We'll give plenty of notice (at least 6 months) before removing deprecated systems.

---

## Success Stories

*After v3.0 ships, we'll add success stories from users who migrated successfully.*

---

**Last Updated:** 2026-02-16  
**Status:** Active Migration Guide  
**Questions?** Open a GitHub issue with tag `migration:file-converter`
