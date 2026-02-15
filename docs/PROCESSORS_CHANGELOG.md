# Processors Changelog

All notable changes to the processors module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-02-15

### Major Changes - Async Refactoring

This is a major release with breaking changes. All processors are now fully async with anyio support.

#### Added

**Phase 1: Async Protocol** 
- Async `can_handle()` and `process()` methods in ProcessorProtocol
- anyio integration for unified async backend support (asyncio, trio, etc.)
- `is_processor()` now checks for coroutine functions
- Comprehensive anyio usage examples in docstrings

**Phase 2: Adapter Migration**
- All 8 adapters migrated to async protocol:
  - IPFSProcessorAdapter (priority 20)
  - BatchProcessorAdapter (priority 15)
  - SpecializedScraperAdapter (priority 12)
  - PDFProcessorAdapter (priority 10)
  - GraphRAGProcessorAdapter (priority 10)
  - MultimediaProcessorAdapter (priority 10)
  - WebArchiveProcessorAdapter (priority 8)
  - FileConverterProcessorAdapter (priority 5)

**Phase 3: Core Infrastructure**
- `UniversalProcessor.process()` is now async
- `UniversalProcessor.process_batch()` is now async with concurrent processing
- `ProcessorRegistry.get_processors()` is now async
- `anyio.sleep()` for non-blocking retry delays
- `anyio.fail_after()` for timeout support
- `anyio.create_task_group()` for concurrent batch processing

**Phase 4: Auto-Registration**
- `register_all_adapters()` verified with async processors
- `is_registered()` and `get_available_adapters()` utilities

**Phase 5: Examples & Documentation**
- `04_ipfs_processing.py` updated to use `anyio.run()`
- New `08_async_processing.py` with comprehensive async examples
- `PROCESSORS_ASYNC_ANYIO_REFACTORING_PLAN.md` - complete 6-phase plan
- `PROCESSORS_ASYNC_COMPLETE_SUMMARY.md` - 10KB comprehensive summary

**Phase 6: Testing**
- 7 new async integration tests (all passing):
  - test_async_single_file_processing
  - test_async_batch_processing_sequential
  - test_async_batch_processing_concurrent
  - test_async_processor_registry_get_processors
  - test_async_with_timeout
  - test_async_retry_logic
  - test_anyio_backend_compatibility
- Updated 26 ProcessorRegistry tests for async

**Phase 7: Developer Experience**
- New CLI tool (`processors/cli.py`) with 7 commands:
  - list - Show all processors
  - health - Check processor health
  - test - Test processing a file
  - benchmark - Performance benchmarking
  - debug - Debug routing decisions
  - stats - Show statistics
  - clear-cache - Clear caches
- Debugging tools (`processors/debug_tools.py`):
  - ProcessorDebugger class
  - explain_routing() - Explain processor selection
  - diagnose_context() - Diagnose ProcessingContext
  - diagnose_result() - Diagnose ProcessingResult
  - trace_logging() - Enable detailed logs
- Performance profiling (`processors/profiling.py`):
  - ProcessorProfiler with async context managers
  - ProfileMetrics dataclass
  - CPU, memory, I/O tracking
  - Metrics history and export
  - profile_processing() convenience function

#### Changed

**Breaking: Sync → Async**
- All processor methods now use `async def`
- Must use `await` when calling processor methods
- Must use `anyio.run()` or `asyncio.run()` for top-level execution
- ProcessorRegistry.get_processors() is now async

**Breaking: Import Changes**
- Recommended to import from `processors.core` instead of `processors`
- Old `processors.protocol` is deprecated (use `processors.core.protocol`)

**Non-Breaking Changes**
- `get_capabilities()` remains synchronous (returns static data)
- ProcessorRegistry registration methods remain synchronous
- Auto-registration remains synchronous
- All existing test infrastructure maintained

#### Performance

- **Concurrent batch processing:** 5-50x faster for I/O-bound workloads
- **Single file processing:** Similar to sync (slight async overhead <5%)
- **10 files concurrent:** ~5-8x faster than sequential
- **100 files concurrent:** ~20-50x faster (I/O bound)
- Non-blocking I/O throughout the pipeline
- Better resource utilization with anyio task groups

#### Dependencies

- Added `anyio>=4.0.0` (required)
- Added `pytest-asyncio>=0.23.0` (testing)
- Added `psutil>=5.9.0` (profiling)

#### Deprecated

- `processors/protocol.py` - Use `processors/core/protocol.py` instead
- Synchronous processor implementations - Will be removed in v3.0.0
- Direct asyncio usage - Prefer anyio for backend flexibility

#### Migration Guide

See `docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md` for detailed migration instructions.

**Quick Migration:**
```python
# Before (v1.x - sync)
from ipfs_datasets_py.processors import UniversalProcessor

processor = UniversalProcessor()
result = processor.process("document.pdf")

# After (v2.x - async)
import anyio
from ipfs_datasets_py.processors.core import UniversalProcessor

processor = UniversalProcessor()

async def main():
    result = await processor.process("document.pdf")

anyio.run(main)
```

## [1.0.0] - 2026-02-08

### Initial Release - Week 1 Core Infrastructure

#### Added

**Day 1: Protocol**
- ProcessorProtocol interface
- InputType enum (7 types)
- ProcessingContext dataclass
- ProcessingResult dataclass
- is_processor() utility

**Day 2: Input Detection**
- InputDetector class
- URL detection (HTTP/HTTPS/IPFS/IPNS)
- Magic bytes detection for 12+ formats
- File and folder detection
- Metadata extraction

**Day 3: Registry**
- ProcessorRegistry class
- Priority-based selection
- can_handle() checking
- Enable/disable control
- Capability aggregation

**Day 4: Universal Processor**
- UniversalProcessor class
- Automatic detect→select→process pipeline
- Retry logic with exponential backoff
- Fallback support
- Result aggregation
- Batch processing

**Day 5: Testing & Examples**
- 210+ tests for core infrastructure
- Integration tests
- 3 example scripts
- Comprehensive documentation

#### Performance

- Input classification: 73K ops/sec
- Registry operations: 439K ops/sec
- Latency: <1ms
- Memory: <1MB baseline

---

## Version History

- **2.0.0** (2026-02-15) - Async refactoring with anyio + Developer Experience tools
- **1.0.0** (2026-02-08) - Initial release with core infrastructure

## Upgrade Path

### From 1.x to 2.x

**Required Changes:**
1. Add `async def` to all processor methods
2. Add `await` when calling processor methods
3. Wrap execution in `anyio.run()` or `asyncio.run()`
4. Update imports to use `processors.core`

**Optional Changes:**
1. Use CLI tool for management
2. Add profiling for performance monitoring
3. Use debugging tools for troubleshooting
4. Leverage concurrent batch processing

**Timeline:**
- Deprecation warnings active now
- Old sync protocol will be removed in v3.0.0 (estimated Q2 2026)
- 3-month migration period

See detailed migration guide: `docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md`

## Support

- **Documentation:** `docs/PROCESSORS_MASTER_PLAN.md`
- **Quick Reference:** `docs/PROCESSORS_QUICK_REFERENCE.md`
- **Examples:** `examples/processors/`
- **Issues:** GitHub issue tracker

