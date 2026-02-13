# Migration Guide: Legacy Functions → Unified Converters

## Overview

The logic module has been refactored to use a unified converter architecture. Legacy async functions (`convert_text_to_fol` and `convert_legal_text_to_deontic`) still work but are deprecated.

This guide helps you migrate to the new, more powerful API.

## Quick Migration

### FOL Conversion

**Before (Deprecated):**
```python
from ipfs_datasets_py.logic.fol import convert_text_to_fol

result = await convert_text_to_fol(
    "All humans are mortal",
    use_nlp=True,
    confidence_threshold=0.7
)
# Returns: {"status": "success", "fol_formulas": [...], ...}
```

**After (Recommended):**
```python
from ipfs_datasets_py.logic.fol import FOLConverter

converter = FOLConverter(
    use_nlp=True,
    confidence_threshold=0.7,
    use_cache=True  # NEW: Automatic caching
)

result = await converter.convert_async("All humans are mortal")
# Returns: ConversionResult with typed output
```

### Deontic/Legal Conversion

**Before (Deprecated):**
```python
from ipfs_datasets_py.logic.deontic import convert_legal_text_to_deontic

result = await convert_legal_text_to_deontic(
    "The tenant must pay rent",
    jurisdiction="us",
    document_type="statute"
)
# Returns: {"status": "success", "deontic_formulas": [...], ...}
```

**After (Recommended):**
```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

converter = DeonticConverter(
    jurisdiction="us",
    document_type="statute",
    use_cache=True  # NEW: Automatic caching
)

result = await converter.convert_async("The tenant must pay rent")
# Returns: ConversionResult with typed output
```

## Benefits of Migrating

### 1. Automatic Caching
```python
converter = FOLConverter(use_cache=True)

# First call - processes text
result1 = converter.convert("text")  # 50ms

# Second call - retrieves from cache
result2 = converter.convert("text")  # 3.5ms (14x faster!)
```

### 2. Batch Processing
```python
converter = FOLConverter()

# Old way - sequential (slow)
results = []
for text in texts:
    result = await convert_text_to_fol(text)
    results.append(result)

# New way - parallel (5-8x faster!)
results = converter.convert_batch(texts, max_workers=4)
```

### 3. ML Confidence Scoring
```python
converter = FOLConverter(use_ml=True)
result = converter.convert("text")

# Get ML-powered confidence score
print(f"Confidence: {result.output.confidence}")  # 0.85
```

### 4. Type Safety
```python
# Old way - untyped dict
result = await convert_text_to_fol("text")
formula = result["fol_formulas"][0]["fol_formula"]  # String access

# New way - typed objects
result = converter.convert("text")
formula = result.output.formula_string  # Type-safe attribute access
```

### 5. Better Error Handling
```python
result = converter.convert("invalid input")

if not result.success:
    print(f"Status: {result.status}")  # VALIDATION_FAILED
    print(f"Errors: {result.errors}")  # ["Input cannot be empty"]
else:
    print(f"Formula: {result.output.formula_string}")
```

## Migration Checklist

- [ ] Replace `convert_text_to_fol()` with `FOLConverter`
- [ ] Replace `convert_legal_text_to_deontic()` with `DeonticConverter`
- [ ] Update result access from dict to typed objects
- [ ] Add caching configuration (`use_cache=True`)
- [ ] Consider batch processing for multiple items
- [ ] Enable ML confidence scoring (`use_ml=True`)
- [ ] Update tests to use new API
- [ ] Remove deprecation warnings

## Step-by-Step Migration

### Step 1: Update Imports

**Old:**
```python
from ipfs_datasets_py.logic.fol import convert_text_to_fol
from ipfs_datasets_py.logic.deontic import convert_legal_text_to_deontic
```

**New:**
```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter
```

### Step 2: Initialize Converters

**Old:**
```python
# No initialization needed - function call directly
```

**New:**
```python
# Initialize converter with configuration
fol_converter = FOLConverter(
    use_cache=True,
    use_ml=True,
    use_nlp=True
)

deontic_converter = DeonticConverter(
    jurisdiction="us",
    use_cache=True
)
```

### Step 3: Update Conversion Calls

**Old:**
```python
result = await convert_text_to_fol("text")
if result["status"] == "success":
    formulas = result["fol_formulas"]
```

**New:**
```python
result = await converter.convert_async("text")
if result.success:
    formula = result.output  # FOLFormula object
```

### Step 4: Update Result Access

**Old - Dict Access:**
```python
formula_string = result["fol_formulas"][0]["fol_formula"]
confidence = result["fol_formulas"][0]["confidence"]
predicates = result["fol_formulas"][0]["predicates_used"]
```

**New - Typed Access:**
```python
formula_string = result.output.formula_string
confidence = result.output.confidence
predicates = result.output.get_predicate_names()
```

### Step 5: Handle Batch Processing

**Old - Sequential:**
```python
results = []
for text in texts:
    result = await convert_text_to_fol(text)
    results.append(result)
```

**New - Parallel:**
```python
results = converter.convert_batch(texts, max_workers=4)
```

## Common Patterns

### Pattern 1: Single Conversion

```python
# Old
result = await convert_text_to_fol("All X are Y")
formula = result["fol_formulas"][0]["fol_formula"]

# New
converter = FOLConverter()
result = converter.convert("All X are Y")
formula = result.output.formula_string
```

### Pattern 2: Batch Conversion

```python
# Old
results = []
for text in texts:
    result = await convert_text_to_fol(text)
    if result["status"] == "success":
        results.append(result["fol_formulas"][0])

# New
converter = FOLConverter()
results = converter.convert_batch(texts)
successful = [r.output for r in results if r.success]
```

### Pattern 3: With Caching

```python
# Old - No caching available
for _ in range(100):
    result = await convert_text_to_fol(same_text)  # Slow!

# New - Automatic caching
converter = FOLConverter(use_cache=True)
for _ in range(100):
    result = converter.convert(same_text)  # 14x faster after first!
```

### Pattern 4: Error Handling

```python
# Old
result = await convert_text_to_fol("")
if result["status"] == "error":
    print(result["message"])

# New
result = converter.convert("")
if not result.success:
    print(f"Status: {result.status}")
    for error in result.errors:
        print(f"Error: {error}")
```

## Deprecation Timeline

- **v1.x:** Legacy functions work with deprecation warnings
- **v2.0:** Legacy functions will be removed
- **Action Required:** Migrate before v2.0 release

## Backward Compatibility

Legacy functions continue to work but issue deprecation warnings:

```python
# This still works
result = await convert_text_to_fol("text")
# DeprecationWarning: convert_text_to_fol() is deprecated...

# But you should migrate to
converter = FOLConverter()
result = await converter.convert_async("text")
```

## Testing Your Migration

### Before Migration
```python
def test_old_way():
    result = await convert_text_to_fol("P -> Q")
    assert result["status"] == "success"
    assert len(result["fol_formulas"]) > 0
```

### After Migration
```python
def test_new_way():
    converter = FOLConverter()
    result = await converter.convert_async("P -> Q")
    assert result.success
    assert result.output is not None
```

## Need Help?

1. **Check the Guide:** See `UNIFIED_CONVERTER_GUIDE.md` for detailed usage
2. **Review Examples:** Look at `tests/unit_tests/logic/fol/test_fol_converter.py`
3. **Run Benchmarks:** Execute `scripts/cli/benchmark_unified_converters.py`

## Summary

| Feature | Old API | New API |
|---------|---------|---------|
| **Caching** | ❌ None | ✅ 14x speedup |
| **Batch Processing** | ❌ Manual loops | ✅ Automatic parallelization |
| **ML Confidence** | ❌ Basic heuristic | ✅ XGBoost models |
| **Type Safety** | ❌ Dicts | ✅ Typed objects |
| **Monitoring** | ❌ None | ✅ Real-time stats |
| **IPFS** | ❌ None | ✅ Distributed caching |

**Migration is strongly recommended for better performance and features!**
