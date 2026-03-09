# LogicConverter Base Class - Usage Guide

## Overview

The `LogicConverter` base class provides a standardized interface for all logic conversion operations in the system. It includes built-in support for:

- Input validation
- Result caching
- Error handling with context
- Conversion chaining
- Metadata tracking

## Basic Usage

### Creating a Simple Converter

```python
from ipfs_datasets_py.logic.common import (
    LogicConverter,
    ConversionResult,
    ValidationResult,
    ConversionError
)

class NaturalLanguageToFOLConverter(LogicConverter[str, str]):
    """Convert natural language to First-Order Logic."""
    
    def validate_input(self, text: str) -> ValidationResult:
        """Validate the input text."""
        result = ValidationResult(valid=True)
        
        if not text or not text.strip():
            result.add_error("Input text cannot be empty")
        
        if len(text) > 10000:
            result.add_warning("Text is very long and may take time to process")
        
        return result
    
    def _convert_impl(self, text: str, options: Dict[str, Any]) -> str:
        """Implement the actual conversion logic."""
        # Your conversion logic here
        fol_formula = parse_nl_to_fol(text)
        
        if not fol_formula:
            raise ConversionError(
                "Failed to parse natural language",
                context={"text": text[:100]}
            )
        
        return fol_formula

# Usage
converter = NaturalLanguageToFOLConverter()
result = converter.convert("Alice must pay Bob")

if result.success:
    print(f"Converted: {result.output}")
else:
    print(f"Errors: {result.errors}")
```

### Using Conversion Results

```python
result = converter.convert("Some input")

# Check if successful
if result.success:
    # Access the output
    output = result.output
    
    # Check status details
    if result.status == ConversionStatus.SUCCESS:
        print("Perfect conversion!")
    elif result.status == ConversionStatus.PARTIAL:
        print(f"Conversion succeeded with warnings: {result.warnings}")
    elif result.status == ConversionStatus.CACHED:
        print("Result from cache")
else:
    # Handle errors
    for error in result.errors:
        print(f"Error: {error}")
    
    # Access error context if available
    if "error_contexts" in result.metadata:
        for ctx in result.metadata["error_contexts"]:
            print(f"Context: {ctx}")

# Convert to dict for serialization
result_dict = result.to_dict()
```

## Advanced Features

### Caching

Caching is enabled by default but can be controlled:

```python
# Enable caching (default)
converter = NaturalLanguageToFOLConverter(enable_caching=True)

# First call - performs conversion
result1 = converter.convert("Alice pays Bob")

# Second call - returns cached result
result2 = converter.convert("Alice pays Bob")
assert result2.status == ConversionStatus.CACHED

# Bypass cache for specific call
result3 = converter.convert("Alice pays Bob", use_cache=False)

# Clear the cache
converter.clear_cache()

# Get cache statistics
stats = converter.get_cache_stats()
print(f"Cache size: {stats['cache_size']}")
```

### Validation Control

```python
# Enable validation (default)
converter = NaturalLanguageToFOLConverter(enable_validation=True)

# Disable validation for performance
fast_converter = NaturalLanguageToFOLConverter(enable_validation=False)
```

### Custom Cache Keys

Override `_generate_cache_key` for custom caching behavior:

```python
class CustomConverter(LogicConverter[str, str]):
    def _generate_cache_key(self, input_data: str, options: Dict[str, Any]) -> str:
        # Only cache based on input, ignore options
        return f"{self.__class__.__name__}:{input_data}"
    
    # ... other methods ...
```

### Conversion Options

Pass options to control conversion behavior:

```python
result = converter.convert(
    "Alice must pay Bob",
    options={
        "confidence": 0.8,
        "timeout": 30,
        "model": "gpt-4",
        "max_length": 1000
    }
)

# Options are passed to _convert_impl
def _convert_impl(self, input_data: str, options: Dict[str, Any]) -> str:
    timeout = options.get("timeout", 60)
    model = options.get("model", "default")
    # Use options in conversion
```

## Chaining Converters

Use `ChainedConverter` to compose multi-step conversions:

```python
from ipfs_datasets_py.logic.common import ChainedConverter

# Create a pipeline: NL → FOL → TDFOL → SMT
pipeline = ChainedConverter([
    NaturalLanguageToFOLConverter(),
    FOLToTDFOLConverter(),
    TDFOLToSMTConverter()
])

# Execute the entire chain
result = pipeline.convert("Alice must pay Bob")

if result.success:
    print(f"Final SMT formula: {result.output}")
else:
    # Error will indicate which step failed
    print(f"Pipeline failed: {result.errors}")
```

## Error Handling

The converter system uses the standardized error hierarchy from `logic.common.errors`:

```python
from ipfs_datasets_py.logic.common import ConversionError

def _convert_impl(self, input_data: str, options: Dict[str, Any]) -> str:
    try:
        # Conversion logic
        result = complex_conversion(input_data)
        
        if not result:
            raise ConversionError(
                "Conversion produced empty result",
                context={
                    "input_length": len(input_data),
                    "input_preview": input_data[:50]
                }
            )
        
        return result
        
    except SomeExternalError as e:
        # Convert external errors to ConversionError
        raise ConversionError(
            f"External error: {str(e)}",
            context={"original_error": type(e).__name__}
        )
```

## Type Safety

The converter uses generics for type safety:

```python
from typing import Dict

class DictToJSONConverter(LogicConverter[Dict, str]):
    """Convert dictionary to JSON string."""
    
    def validate_input(self, input_data: Dict) -> ValidationResult:
        result = ValidationResult(valid=True)
        if not isinstance(input_data, dict):
            result.add_error("Input must be a dictionary")
        return result
    
    def _convert_impl(self, input_data: Dict, options: Dict[str, Any]) -> str:
        import json
        return json.dumps(input_data, indent=2)
```

## Testing Converters

Example test structure:

```python
import pytest
from your_module import YourConverter

class TestYourConverter:
    def test_successful_conversion(self):
        """GIVEN valid input
        WHEN converting
        THEN output is correct
        """
        converter = YourConverter()
        result = converter.convert("valid input")
        
        assert result.success is True
        assert result.output == "expected output"
        assert len(result.errors) == 0
    
    def test_validation_error(self):
        """GIVEN invalid input
        WHEN converting
        THEN validation fails
        """
        converter = YourConverter()
        result = converter.convert("invalid")
        
        assert result.success is False
        assert len(result.errors) > 0
    
    def test_caching(self):
        """GIVEN same input twice
        WHEN converting
        THEN second result is cached
        """
        converter = YourConverter()
        
        result1 = converter.convert("input")
        result2 = converter.convert("input")
        
        assert result2.status == ConversionStatus.CACHED
```

## Migration from Legacy Converters

### Before (without base class):

```python
def convert_nl_to_fol(text: str) -> str:
    if not text:
        raise ValueError("Empty input")
    # Conversion logic
    return result
```

### After (with base class):

```python
class NLToFOLConverter(LogicConverter[str, str]):
    def validate_input(self, text: str) -> ValidationResult:
        result = ValidationResult(valid=True)
        if not text:
            result.add_error("Empty input")
        return result
    
    def _convert_impl(self, text: str, options: Dict[str, Any]) -> str:
        # Same conversion logic
        return result

# Usage remains simple
converter = NLToFOLConverter()
result = converter.convert(text)
output = result.output if result.success else None
```

## Best Practices

1. **Always implement validation** - Even if it just returns `ValidationResult(valid=True)`
2. **Raise ConversionError with context** - Include relevant information for debugging
3. **Add warnings for non-critical issues** - Use `result.add_warning()` in validation
4. **Test edge cases** - Empty input, very large input, malformed input
5. **Document options** - If your converter accepts options, document them
6. **Keep converters focused** - One converter = one transformation
7. **Chain for complex workflows** - Use `ChainedConverter` for multi-step processes

## See Also

- `logic/common/errors.py` - Error hierarchy
- `logic/common/README.md` - Common module overview
- `tests/unit_tests/logic/test_converters.py` - Test examples
