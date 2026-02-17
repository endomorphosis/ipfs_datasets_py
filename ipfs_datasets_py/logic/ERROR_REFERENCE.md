# Logic Module Error Reference

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Comprehensive Catalog

---

## Table of Contents

- [Exception Hierarchy](#exception-hierarchy)
- [Core Exceptions](#core-exceptions)
- [Conversion Exceptions](#conversion-exceptions)
- [Proof Exceptions](#proof-exceptions)
- [Bridge Exceptions](#bridge-exceptions)
- [Configuration Exceptions](#configuration-exceptions)
- [Security Exceptions](#security-exceptions)
- [Error Codes](#error-codes)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Exception Hierarchy

```
Exception
└── LogicError (base for all logic module exceptions)
    ├── ConversionError
    │   ├── ValidationError
    │   ├── ParsingError
    │   └── UnsupportedFormatError
    ├── ProofError
    │   ├── TimeoutError
    │   ├── ResourceExhaustedError
    │   └── ProofIncompleteError
    ├── TranslationError
    │   └── BridgeError
    ├── ConfigurationError
    │   ├── MissingDependencyError
    │   └── InvalidConfigError
    ├── DeonticError
    │   ├── ConflictDetectionError
    │   └── PolicyViolationError
    ├── ModalError
    ├── TemporalError
    └── SecurityError
        ├── InputTooLargeError
        ├── RateLimitExceeded
        └── SuspiciousPatternError
```

---

## Core Exceptions

### `LogicError`

**Base exception** for all logic module errors.

**Usage:**
```python
from ipfs_datasets_py.logic.common import LogicError

try:
    result = some_logic_operation()
except LogicError as e:
    print(f"Logic operation failed: {e}")
```

**Attributes:**
- `message` (str): Human-readable error message
- `context` (dict): Additional context about the error
- `original_exception` (Exception | None): Wrapped exception if any

**When to catch:** To handle any logic module error generically

---

## Conversion Exceptions

### `ConversionError`

**Description:** Raised when text-to-logic conversion fails.

**Common Causes:**
- Invalid input text format
- Ambiguous natural language
- Unsupported logical constructs
- Parsing failures

**Example:**
```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.common import ConversionError

converter = FOLConverter()
try:
    result = converter.convert("invalid <<< text")
except ConversionError as e:
    print(f"Conversion failed: {e}")
    print(f"Error details: {e.context}")
```

**Attributes:**
- `input_text` (str): The text that failed to convert
- `stage` (str): Which conversion stage failed (parsing, validation, generation)
- `partial_result` (Any | None): Partial conversion result if available

**Solutions:**
1. Check input text for typos or malformed syntax
2. Simplify complex sentences into smaller parts
3. Use fallback mode for better error messages
4. Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for input guidelines

**Error Code:** `E001`

---

### `ValidationError`

**Description:** Input validation failed before processing.

**Common Causes:**
- Input text too long
- Forbidden characters or patterns
- Formula depth exceeds limits
- Invalid configuration

**Example:**
```python
from ipfs_datasets_py.logic.common import ValidationError

try:
    result = converter.convert("a" * 100_000)  # Too long
except ValidationError as e:
    print(f"Validation failed: {e}")
    if e.context.get("reason") == "length_exceeded":
        print(f"Max length: {e.context['max_length']}")
```

**Attributes:**
- `field` (str): Which field failed validation
- `value` (Any): The invalid value
- `constraint` (str): Which constraint was violated
- `max_allowed` (int | None): Maximum allowed value (for length/depth)

**Solutions:**
1. **Input Too Long:** Split into smaller chunks
2. **Invalid Characters:** Remove or escape special characters
3. **Formula Too Deep:** Simplify nested structures
4. **Configuration Invalid:** Check config format

**Error Code:** `E002`

---

### `ParsingError`

**Description:** Failed to parse input text or formula syntax.

**Common Causes:**
- Malformed formula syntax
- Unbalanced parentheses
- Invalid logical operators
- Lexer/parser failure

**Example:**
```python
from ipfs_datasets_py.logic.common import ParsingError

try:
    result = prove_formula("P → (Q")  # Unbalanced parentheses
except ParsingError as e:
    print(f"Parsing failed at position {e.context['position']}")
    print(f"Expected: {e.context['expected']}")
```

**Attributes:**
- `position` (int): Character position where parsing failed
- `line` (int): Line number (for multi-line input)
- `expected` (str): What the parser expected to see
- `found` (str): What was actually found

**Solutions:**
1. Check for **balanced parentheses**: `(`, `[`, `{`
2. Use proper **logical operators**: `→`, `∧`, `∨`, `¬`, `↔`
3. Validate **quantifier syntax**: `∀x`, `∃y`
4. Use formula validation: `validate_formula(text)` before parsing

**Error Code:** `E003`

---

### `UnsupportedFormatError`

**Description:** The requested output format is not supported.

**Example:**
```python
from ipfs_datasets_py.logic.common import UnsupportedFormatError

try:
    result = converter.convert(text, output_format="lisp")  # Not supported
except UnsupportedFormatError as e:
    print(f"Format '{e.context['format']}' not supported")
    print(f"Supported formats: {e.context['supported_formats']}")
```

**Solutions:**
1. Check supported formats: `FOLConverter.supported_formats()`
2. Use default format if unsure
3. Implement custom formatter if needed

**Error Code:** `E004`

---

## Proof Exceptions

### `ProofError`

**Description:** Proof attempt failed.

**Common Causes:**
- Unprovable formula
- Timeout during proof search
- Resource exhaustion
- Missing assumptions

**Example:**
```python
from ipfs_datasets_py.logic.integration import prove_formula
from ipfs_datasets_py.logic.common import ProofError

try:
    result = prove_formula("Q", assumptions=["P"])  # Cannot prove Q from P
except ProofError as e:
    print(f"Proof failed: {e}")
    if e.context.get("reason") == "unprovable":
        print("Formula may be unprovable from given assumptions")
```

**Attributes:**
- `formula` (str): The formula being proven
- `assumptions` (List[str]): Assumptions provided
- `reason` (str): Why proof failed
- `partial_proof` (Any | None): Partial proof steps if available

**Solutions:**
1. **Unprovable:** Check assumptions are sufficient
2. **Timeout:** Increase timeout or simplify formula
3. **Resource exhaustion:** Reduce search depth
4. **Missing assumptions:** Add necessary axioms

**Error Code:** `E010`

---

### `TimeoutError`

**Description:** Proof search exceeded time limit.

**Example:**
```python
from ipfs_datasets_py.logic.common import TimeoutError

try:
    result = prove_formula(complex_formula, timeout=10)
except TimeoutError as e:
    print(f"Timed out after {e.context['elapsed_seconds']}s")
    print(f"Max allowed: {e.context['timeout_seconds']}s")
```

**Solutions:**
1. **Increase timeout:** `prove_formula(formula, timeout=60)`
2. **Simplify formula:** Break into smaller parts
3. **Use faster prover:** Try different prover backend
4. **Enable caching:** Cache intermediate results

**Error Code:** `E011`

---

### `ResourceExhaustedError`

**Description:** Ran out of memory or other resources during proof.

**Example:**
```python
from ipfs_datasets_py.logic.common import ResourceExhaustedError

try:
    result = prove_formula(huge_formula_set)
except ResourceExhaustedError as e:
    print(f"Resource exhausted: {e.context['resource']}")
    print(f"Used: {e.context['used']}, Limit: {e.context['limit']}")
```

**Solutions:**
1. **Memory:** Reduce batch size or formula set size
2. **Search depth:** Limit proof search depth
3. **Streaming:** Use streaming mode for large datasets
4. **Distributed:** Use distributed proving for very large problems

**Error Code:** `E012`

---

## Bridge Exceptions

### `TranslationError`

**Description:** Failed to translate between logic systems.

**Common Causes:**
- Unsupported logical construct
- Loss of information in translation
- Bridge not available

**Example:**
```python
from ipfs_datasets_py.logic.common import TranslationError

try:
    result = bridge.to_target_format(formula)
except TranslationError as e:
    print(f"Translation failed: {e.context['reason']}")
    print(f"Problematic construct: {e.context['construct']}")
```

**Solutions:**
1. Check if construct is supported by target system
2. Use compatibility layer
3. Simplify formula to supported subset

**Error Code:** `E020`

---

### `BridgeError`

**Description:** External prover bridge failed.

**Common Causes:**
- Prover binary not installed
- Prover crashed or timed out
- Invalid prover configuration
- Communication failure

**Example:**
```python
from ipfs_datasets_py.logic.common import BridgeError

try:
    result = z3_bridge.prove(formula)
except BridgeError as e:
    print(f"Bridge error: {e.context['prover']}")
    if e.context.get("reason") == "binary_not_found":
        print("Install Z3: pip install z3-solver")
```

**Solutions:**
1. **Binary not found:** Install prover (`pip install z3-solver`)
2. **Prover crashed:** Check formula syntax for prover
3. **Timeout:** Increase prover timeout
4. **Config invalid:** Validate prover configuration

**Error Code:** `E021`

---

## Configuration Exceptions

### `ConfigurationError`

**Description:** Configuration is invalid or incomplete.

**Example:**
```python
from ipfs_datasets_py.logic.common import ConfigurationError

try:
    converter = FOLConverter(config=invalid_config)
except ConfigurationError as e:
    print(f"Config error: {e.context['field']}")
    print(f"Expected: {e.context['expected_type']}")
```

**Solutions:**
1. Validate config schema
2. Check required fields are present
3. Use default config as template

**Error Code:** `E030`

---

### `MissingDependencyError`

**Description:** Required optional dependency not installed.

**Example:**
```python
from ipfs_datasets_py.logic.common import MissingDependencyError

try:
    converter = FOLConverter(use_spacy=True)
except MissingDependencyError as e:
    print(f"Missing: {e.context['dependency']}")
    print(f"Install: {e.context['install_command']}")
```

**Solutions:**
1. Install dependency: `pip install spacy`
2. Use fallback mode: `use_fallback=True`
3. Check [requirements.txt](../../requirements.txt) for versions

**Error Code:** `E031`

---

## Security Exceptions

### `SecurityError`

**Description:** Security check failed.

**Common Causes:**
- Input validation for security
- Rate limiting
- Suspicious patterns detected

**Example:**
```python
from ipfs_datasets_py.logic.security import SecurityError

try:
    result = secure_converter.convert(user_input)
except SecurityError as e:
    print(f"Security check failed: {e.context['check']}")
```

**Error Code:** `E040`

---

### `InputTooLargeError`

**Description:** Input exceeds maximum size limit.

**Example:**
```python
from ipfs_datasets_py.logic.common import InputTooLargeError

try:
    result = converter.convert(very_long_text)
except InputTooLargeError as e:
    print(f"Input size: {e.context['size_bytes']}")
    print(f"Max allowed: {e.context['max_bytes']}")
```

**Solutions:**
1. Split input into smaller chunks
2. Increase limit if appropriate: `converter.max_input_size = 50000`
3. Use streaming API for large inputs

**Error Code:** `E041`

---

### `RateLimitExceeded`

**Description:** API rate limit exceeded.

**Example:**
```python
from ipfs_datasets_py.logic.common import RateLimitExceeded

try:
    for text in many_texts:
        result = converter.convert(text)
except RateLimitExceeded as e:
    print(f"Rate limit: {e.context['limit']}")
    print(f"Retry after: {e.context['retry_after_seconds']}s")
    time.sleep(e.context['retry_after_seconds'])
```

**Solutions:**
1. Implement exponential backoff
2. Use batch conversion API
3. Request rate limit increase

**Error Code:** `E042`

---

### `SuspiciousPatternError`

**Description:** Input contains suspicious patterns.

**Example:**
```python
from ipfs_datasets_py.logic.common import SuspiciousPatternError

try:
    result = converter.convert(user_input)
except SuspiciousPatternError as e:
    print(f"Suspicious pattern: {e.context['pattern']}")
    print(f"Position: {e.context['position']}")
```

**Solutions:**
1. Review input for injection attempts
2. Sanitize user input
3. Use input validation helpers

**Error Code:** `E043`

---

## Error Codes

### Quick Reference

| Code | Exception | Severity | Common Cause |
|------|-----------|----------|--------------|
| E001 | ConversionError | Medium | Invalid input text |
| E002 | ValidationError | Low | Input validation failed |
| E003 | ParsingError | Medium | Malformed formula syntax |
| E004 | UnsupportedFormatError | Low | Unsupported format requested |
| E010 | ProofError | Medium | Proof attempt failed |
| E011 | TimeoutError | Low | Proof search timeout |
| E012 | ResourceExhaustedError | High | Memory/resource exhaustion |
| E020 | TranslationError | Medium | Bridge translation failed |
| E021 | BridgeError | High | External prover failure |
| E030 | ConfigurationError | High | Invalid configuration |
| E031 | MissingDependencyError | Medium | Missing optional dependency |
| E040 | SecurityError | High | Security check failed |
| E041 | InputTooLargeError | Medium | Input too large |
| E042 | RateLimitExceeded | Low | Rate limit exceeded |
| E043 | SuspiciousPatternError | High | Suspicious input pattern |

### Severity Levels

- **Low:** Expected in normal operation, easily recovered
- **Medium:** Unexpected but recoverable with user action
- **High:** Requires immediate attention or investigation

---

## Troubleshooting Guide

### Generic Error Handling Pattern

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.common import (
    LogicError,
    ConversionError,
    ValidationError,
    TimeoutError,
    MissingDependencyError,
)
import logging

logger = logging.getLogger(__name__)

def safe_convert(text: str) -> Optional[str]:
    """Safe conversion with comprehensive error handling."""
    try:
        converter = FOLConverter()
        result = converter.convert(text)
        
        if not result.success:
            logger.warning(f"Conversion failed: {result.error}")
            return None
            
        return result.fol
        
    except ValidationError as e:
        logger.error(f"Validation failed: {e}")
        # Input was invalid, user needs to fix it
        return None
        
    except TimeoutError as e:
        logger.warning(f"Timeout after {e.context['elapsed_seconds']}s")
        # Retry with longer timeout or simpler input
        return None
        
    except MissingDependencyError as e:
        logger.error(f"Missing dependency: {e.context['dependency']}")
        # Install dependency or use fallback
        converter = FOLConverter(use_fallback=True)
        return converter.convert(text).fol if converter.convert(text).success else None
        
    except ConversionError as e:
        logger.error(f"Conversion error: {e}")
        # Log for investigation
        return None
        
    except LogicError as e:
        logger.exception(f"Unexpected logic error: {e}")
        # Something went wrong, investigate
        raise
        
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        raise
```

### Debug Mode

Enable detailed error information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or environment variable
import os
os.environ['LOGIC_DEBUG'] = '1'

# Errors will now include stack traces and context
```

### Getting Help

1. **Check this reference** for known errors
2. **Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** for common issues
3. **Check [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)** for limitations
4. **Enable debug logging** to see more details
5. **Open an issue** on GitHub with error details

---

## Custom Exception Handling

### Adding Context to Exceptions

```python
from ipfs_datasets_py.logic.common import ConversionError

def my_converter(text):
    try:
        result = risky_operation(text)
    except Exception as e:
        raise ConversionError(
            f"Failed to convert: {text[:50]}...",
            context={
                "stage": "custom_processing",
                "input_length": len(text),
                "original_error": str(e),
            }
        ) from e
```

### Catching Multiple Exceptions

```python
from ipfs_datasets_py.logic.common import (
    ConversionError,
    ValidationError,
    ParsingError,
)

try:
    result = converter.convert(text)
except (ValidationError, ParsingError) as e:
    # Handle input errors
    print(f"Input error: {e}")
except ConversionError as e:
    # Handle general conversion errors
    print(f"Conversion error: {e}")
```

---

## Common Error Patterns

### Pattern 1: Input Validation

```python
# BEFORE: No validation, cryptic errors
result = converter.convert(user_input)

# AFTER: Pre-validate for better errors
from ipfs_datasets_py.logic.common import validate_input

try:
    validate_input(user_input, max_length=10000)
    result = converter.convert(user_input)
except ValidationError as e:
    # Clear, actionable error message
    return f"Invalid input: {e}"
```

### Pattern 2: Graceful Degradation

```python
# Try preferred method, fall back on failure
try:
    converter = FOLConverter(use_symbolic=True)
    result = converter.convert(text)
except MissingDependencyError:
    # Fall back to regex-based converter
    converter = FOLConverter(use_fallback=True)
    result = converter.convert(text)
```

### Pattern 3: Retry with Backoff

```python
import time

def convert_with_retry(text, max_retries=3):
    for attempt in range(max_retries):
        try:
            return converter.convert(text)
        except TimeoutError:
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # Exponential backoff
                time.sleep(wait)
            else:
                raise
```

---

## Performance Tips

### Avoid Common Performance Pitfalls

1. **Don't ignore ValidationError** - It's telling you input is too large
2. **Use caching** - Wrap expensive operations with `@lru_cache`
3. **Batch operations** - Use batch APIs instead of loops
4. **Set timeouts** - Always set reasonable timeouts
5. **Monitor memory** - Watch for ResourceExhaustedError

---

## Summary

- **Exception Hierarchy** - All logic errors inherit from `LogicError`
- **Error Codes** - Quick reference codes (E001-E043)
- **Context** - All exceptions include context dict with details
- **Solutions** - Each error has documented solutions
- **Patterns** - Use established error handling patterns
- **Debug Mode** - Enable for detailed error information

**For more help:**
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues and solutions
- [API_REFERENCE.md](./API_REFERENCE.md) - Complete API documentation
- [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues) - Report bugs

---

**Document Status:** Comprehensive Reference  
**Maintained By:** Logic Module Maintainers  
**Review Frequency:** Every MINOR release
