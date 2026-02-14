# Logic Common Module

**Created:** 2026-02-13  
**Phase:** Phase 2 - Quality Improvements (Day 3)  
**Purpose:** Provide shared utilities and standardized patterns for logic module

## Overview

The `logic/common/` module contains utilities shared across the logic module to:
1. Reduce code duplication
2. Standardize common patterns
3. Improve error handling consistency
4. Simplify maintenance

## Components

### Error Hierarchy (`errors.py`)

Standardized exception hierarchy replacing inconsistent use of `ValueError`, `TypeError`, and `RuntimeError`:

**Base Exception:**
- `LogicError` - Base for all logic module errors with context support

**Domain-Specific Exceptions:**
- `ConversionError` - Logic conversion failures
- `ValidationError` - Validation failures
- `ProofError` - Proof execution failures
- `TranslationError` - Logic translation failures
- `BridgeError` - Prover bridge operation failures
- `ConfigurationError` - Configuration issues
- `DeonticError` - Deontic logic failures
- `ModalError` - Modal logic failures
- `TemporalError` - Temporal logic failures

**Usage:**

```python
from ipfs_datasets_py.logic.common import ConversionError

def convert_logic(formula):
    if not formula:
        raise ConversionError(
            "Empty formula provided",
            context={"function": "convert_logic", "formula": formula}
        )
    # ... conversion logic
```

**Context Support:**

All errors accept optional context dictionary for debugging:

```python
try:
    convert_formula(formula)
except Exception as e:
    raise ConversionError(
        "Failed to convert formula",
        context={
            "formula": formula,
            "source": "user_input",
            "line": 42
        }
    ) from e
```

## Benefits

1. **Consistent Error Handling:** All logic module exceptions follow same pattern
2. **Better Debugging:** Context dictionary captures error details
3. **Type Safety:** Specific exception types for different failure modes
4. **Backward Compatible:** Doesn't break existing code, used for new code
5. **Clear Intent:** Exception names communicate what went wrong

## Migration Strategy

**Phase 1 (Current):** 
- Common module created
- Available for use in new code
- Existing code continues using old errors

**Phase 2 (Future):**
- Gradually wrap legacy errors in new code paths
- Update new features to use common errors
- Add examples and patterns

**Phase 3 (Optional):**
- Consider migrating critical paths to new errors
- Maintain backward compatibility with wrappers

## Future Additions

The common module will grow to include:
- Conversion utilities (DRY up duplicate logic)
- Base converter classes
- Validation helpers
- Common decorators
- Logging utilities

## References

- [ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md) - Full roadmap
- [Phase 2 Task 7](../../ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md#phase-2-quality-improvements-weeks-3-4---p1) - Extract common logic

## Converter Base Classes (`converters.py`)

**Added:** Phase 2 - Day 4  
**Updated:** 2026-02-14 - Added BoundedCache with TTL and LRU eviction

Standardized base classes for logic conversion operations:

- `LogicConverter[InputType, OutputType]` - Generic base class for converters
- `BoundedCache[T]` - Production-ready cache with TTL and LRU eviction (**NEW**)
- `ChainedConverter` - Chains multiple converters together
- `ConversionResult` - Standardized conversion result format
- `ConversionStatus` - Status enum (SUCCESS, PARTIAL, FAILED, CACHED)
- `ValidationResult` - Input validation result format

**Features:**
- Built-in input validation
- **NEW:** Bounded caching with configurable maxsize and TTL
- **NEW:** LRU eviction prevents unbounded growth
- **NEW:** Thread-safe cache operations
- **NEW:** Rich statistics (hits, misses, evictions, expirations, hit_rate)
- Error handling with context
- Conversion chaining support
- Metadata tracking

### Quick Start

**Basic Converter:**

```python
from ipfs_datasets_py.logic.common import LogicConverter, ValidationResult

class MyConverter(LogicConverter[str, str]):
    def validate_input(self, text: str) -> ValidationResult:
        result = ValidationResult(valid=True)
        if not text:
            result.add_error("Input cannot be empty")
        return result
    
    def _convert_impl(self, text: str, options: Dict[str, Any]) -> str:
        return text.upper()  # Your conversion logic

# Use with default bounded cache (1000 entries, 1 hour TTL)
converter = MyConverter()
result = converter.convert("hello")
if result.success:
    print(result.output)  # "HELLO"
```

**Custom Cache Configuration:**

```python
# Configure cache size and TTL
converter = MyConverter(
    enable_caching=True,
    cache_maxsize=500,   # Max 500 entries
    cache_ttl=1800,      # 30 minute TTL
)

# Get detailed statistics
stats = converter.get_cache_stats()
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Evictions: {stats['evictions']}")

# Manually cleanup expired entries
cleaned = converter.cleanup_expired_cache()
```

**Disable Caching:**

```python
# For testing or when caching isn't needed
converter = MyConverter(enable_caching=False)
```

See `CONVERTER_USAGE.md` for comprehensive documentation with examples of:
- Caching control and configuration
- Validation patterns
- Error handling
- Conversion chaining
- Testing strategies

### BoundedCache Details

The new `BoundedCache` class (in `bounded_cache.py`) provides:

- **TTL Expiration:** Entries automatically expire after configurable time
- **Size Limits:** Maximum entries with LRU eviction when full
- **Thread-Safe:** RLock ensures safe concurrent access
- **Statistics:** Comprehensive metrics for monitoring
- **Performance:** O(1) lookups with minimal overhead

**Direct Usage:**

```python
from ipfs_datasets_py.logic.common.bounded_cache import BoundedCache

# Create cache
cache = BoundedCache[str](maxsize=1000, ttl=3600)

# Store and retrieve
cache.set("key1", "value1")
value = cache.get("key1")  # Returns "value1"

# Statistics
stats = cache.get_stats()
# {
#   'size': 1,
#   'maxsize': 1000,
#   'ttl': 3600,
#   'hits': 1,
#   'misses': 0,
#   'hit_rate': 1.0,
#   'evictions': 0,
#   'expirations': 0
# }
```

## Testing

Tests are located in:
- `tests/unit_tests/logic/test_common.py` - Error hierarchy tests (18 tests)
- `tests/unit_tests/logic/test_converters.py` - Converter base class tests (23 tests)

Run tests with:
```bash
pytest tests/unit_tests/logic/test_common.py
pytest tests/unit_tests/logic/test_converters.py
```
