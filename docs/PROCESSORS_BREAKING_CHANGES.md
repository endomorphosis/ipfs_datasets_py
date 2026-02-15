# Processors Breaking Changes

This document lists all breaking changes introduced in the processors module, organized by version.

## Version 2.0.0 (2026-02-15) - Async Refactoring

### Overview

Version 2.0.0 introduces a complete async refactoring of the processor system. While we've maintained backward compatibility where possible, several breaking changes are necessary for the async architecture.

### Breaking Changes

#### 1. All Processor Methods Are Now Async

**Impact:** HIGH - Affects all processor implementations

**What Changed:**
- `can_handle(context)` → `async def can_handle(context)`
- `process(context)` → `async def process(context)`
- `ProcessorRegistry.get_processors(context)` → `async def get_processors(context)`
- `UniversalProcessor.process(input)` → `async def process(input)`
- `UniversalProcessor.process_batch(inputs)` → `async def process_batch(inputs)`

**Migration:**

```python
# Before (v1.x)
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()
result = processor.process("document.pdf")  # Synchronous

if result.success:
    print(f"Processed: {result.get_entity_count()} entities")

# After (v2.x)
import anyio
from ipfs_datasets_py.processors.core import UniversalProcessor

processor = UniversalProcessor()

async def main():
    result = await processor.process("document.pdf")  # Must await
    
    if result.success:
        print(f"Processed: {result.get_entity_count()} entities")

anyio.run(main)  # Must run in async context
```

**Why:** Enables non-blocking I/O for better performance with I/O-bound operations like network requests, file reading, and IPFS operations.

#### 2. Import Path Changes

**Impact:** MEDIUM - Affects imports

**What Changed:**
- Recommended: `from ipfs_datasets_py.processors.core import ...`
- Deprecated: `from ipfs_datasets_py.processors import ...`
- Old protocol deprecated: `processors/protocol.py`
- New protocol: `processors/core/protocol.py`

**Migration:**

```python
# Before (v1.x)
from ipfs_datasets_py.processors import (
    UniversalProcessor,
    ProcessorRegistry,
    ProcessingContext,
    ProcessingResult
)

# After (v2.x)
from ipfs_datasets_py.processors.core import (
    UniversalProcessor,
    ProcessorRegistry,
    ProcessingContext,
    ProcessingResult
)
```

**Why:** Clearer separation between core functionality and adapters. Old imports still work with deprecation warnings.

#### 3. ProcessorProtocol Interface Changes

**Impact:** HIGH - Affects custom processor implementations

**What Changed:**

```python
# Before (v1.x)
class MyProcessor:
    def can_handle(self, context: ProcessingContext) -> bool:
        return context.get_format() == 'myformat'
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        # Process synchronously
        return result
    
    def get_capabilities(self) -> Dict[str, Any]:
        return {'formats': ['myformat']}

# After (v2.x)
class MyProcessor:
    async def can_handle(self, context: ProcessingContext) -> bool:
        # Can do async checks now (e.g., network requests)
        return context.get_format() == 'myformat'
    
    async def process(self, context: ProcessingContext) -> ProcessingResult:
        # Process asynchronously
        # Can use await for I/O operations
        return result
    
    def get_capabilities(self) -> Dict[str, Any]:
        # Still synchronous - returns static data
        return {'formats': ['myformat']}
```

**Why:** Allows processors to perform async I/O operations efficiently.

#### 4. Method Signature Changes

**Impact:** MEDIUM - Affects method calls

**What Changed:**
- Must use `await` when calling processor methods
- Must use `async with` for context managers
- Batch processing now supports `parallel=True` for concurrency

**Migration:**

```python
# Before (v1.x)
processor = UniversalProcessor()

# Single file
result = processor.process("file.pdf")

# Batch (sequential only)
results = processor.process_batch(["f1.pdf", "f2.pdf", "f3.pdf"])

# After (v2.x)
processor = UniversalProcessor()

async def main():
    # Single file - must await
    result = await processor.process("file.pdf")
    
    # Batch sequential
    results = await processor.process_batch(["f1.pdf", "f2.pdf", "f3.pdf"])
    
    # Batch concurrent (NEW - much faster!)
    results = await processor.process_batch(
        ["f1.pdf", "f2.pdf", "f3.pdf"],
        parallel=True  # Process concurrently
    )

anyio.run(main)
```

**Why:** Enables concurrent batch processing for better performance.

#### 5. Execution Context Requirements

**Impact:** HIGH - Affects all top-level code

**What Changed:**
- Must run processors in async context
- Use `anyio.run()` or `asyncio.run()` for top-level execution
- Cannot call processor methods directly at module level

**Migration:**

```python
# Before (v1.x) - Direct execution
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()
result = processor.process("document.pdf")  # Works at module level

# After (v2.x) - Async context required
import anyio
from ipfs_datasets_py.processors.core import UniversalProcessor

processor = UniversalProcessor()

async def main():
    result = await processor.process("document.pdf")

if __name__ == '__main__':
    anyio.run(main)  # Must wrap in async runner
```

**Why:** Required by Python's async/await syntax.

### Non-Breaking Changes (Maintained Compatibility)

#### 1. get_capabilities() Remains Synchronous

```python
# Still works the same
processor = MyProcessor()
caps = processor.get_capabilities()  # No await needed
```

**Why:** Returns static data, no I/O operations needed.

#### 2. ProcessorRegistry Registration

```python
# Still synchronous
from ipfs_datasets_py.processors.core import get_global_registry

registry = get_global_registry()
registry.register(processor, priority=10, name="MyProcessor")
```

**Why:** Registration is a quick operation, no need for async.

#### 3. Auto-Registration

```python
# Still works the same
from ipfs_datasets_py.processors.adapters import register_all_adapters

count = register_all_adapters()  # Still synchronous
```

**Why:** Registration happens once at startup.

#### 4. Data Structures

```python
# All dataclasses remain the same
ProcessingContext(
    input_type=InputType.FILE,
    source="document.pdf",
    metadata={'format': 'pdf'}
)

ProcessingResult(
    success=True,
    knowledge_graph={'entities': [], 'relationships': []},
    vectors=[],
    metadata={}
)
```

**Why:** Data structures don't need to change for async.

### Deprecation Timeline

#### Immediate (v2.0.0 - Released 2026-02-15)
- ✅ Deprecation warnings added to old protocol
- ✅ Old sync implementations still work with warnings
- ✅ Migration guide available

#### 3 Months (v2.1.0 - Estimated May 2026)
- 🔄 More prominent deprecation warnings
- 🔄 Example migration tools
- 🔄 Automated migration scripts

#### 6 Months (v3.0.0 - Estimated August 2026)
- ❌ Remove old sync protocol
- ❌ Remove deprecated imports
- ❌ Async-only from v3.0.0

### Migration Strategies

#### Strategy 1: Incremental Migration (Recommended)

1. **Week 1:** Update imports to use `processors.core`
2. **Week 2:** Add `async/await` to top-level code
3. **Week 3:** Update custom processors (if any)
4. **Week 4:** Test and validate
5. **Week 5:** Deploy

#### Strategy 2: Quick Migration

1. Wrap all processor calls in async functions
2. Use `anyio.run()` at entry points
3. Test thoroughly
4. Deploy

#### Strategy 3: Side-by-Side

1. Create new async versions alongside old code
2. Gradually migrate callers
3. Remove old code when migration complete

### Testing Your Migration

#### 1. Check for Deprecation Warnings

```python
import warnings
warnings.filterwarnings('error', category=DeprecationWarning)

# Your code here - will raise errors on deprecation warnings
```

#### 2. Run Provided Tests

```bash
# Run async integration tests
pytest tests/integration/processors/test_async_integration.py -v

# Run all processor tests
pytest tests/unit/processors/ -v
pytest tests/integration/processors/ -v
```

#### 3. Use CLI Tool

```bash
# Test your files
python -m ipfs_datasets_py.processors.cli test your_file.pdf

# Benchmark performance
python -m ipfs_datasets_py.processors.cli benchmark your_file.pdf
```

### Getting Help

#### Documentation
- **Migration Guide:** `docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md`
- **Async Summary:** `docs/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md`
- **Quick Reference:** `docs/PROCESSORS_QUICK_REFERENCE.md`

#### Examples
- **Basic Async:** `examples/processors/08_async_processing.py`
- **IPFS Processing:** `examples/processors/04_ipfs_processing.py`

#### Tools
- **CLI Tool:** `python -m ipfs_datasets_py.processors.cli --help`
- **Debugger:** `processors/debug_tools.py`
- **Profiler:** `processors/profiling.py`

### FAQs

#### Q: Do I have to use anyio? Can I use asyncio directly?

**A:** You can use asyncio directly, but anyio is recommended for backend flexibility. Both work:

```python
# With anyio (recommended)
import anyio
anyio.run(main)

# With asyncio (also works)
import asyncio
asyncio.run(main())
```

#### Q: Will my custom processors break?

**A:** They'll work with deprecation warnings until v3.0.0. Migrate by adding `async def` and `await`.

#### Q: Can I mix sync and async processors?

**A:** No. All processors must use the same protocol. Migrate all custom processors together.

#### Q: What about performance?

**A:** Single file processing is similar. Batch processing is 5-50x faster with `parallel=True`.

#### Q: How do I test my migration?

**A:** Use the CLI tool: `python -m ipfs_datasets_py.processors.cli test your_file.pdf`

#### Q: What if I find a bug?

**A:** Report it on GitHub with:
- Python version
- Processor version
- Minimal reproduction code
- Error messages

### Summary

**Breaking Changes Count:** 5 major changes
**Impact:** HIGH for async migration, MEDIUM for imports
**Migration Time:** 1-5 weeks depending on codebase size
**Support Period:** 6 months (through v2.x)
**Next Breaking Release:** v3.0.0 (August 2026)

**Bottom Line:** The async migration is necessary for performance but we've minimized breaking changes and provided extensive migration support.

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-15  
**Applies To:** v2.0.0 and later
