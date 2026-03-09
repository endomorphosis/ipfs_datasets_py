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

---

## Migrating from tools/ to integration/ (Phase 3)

### Background

The `tools/` directory contains duplicate and outdated implementations that mirror the `integration/` directory. As part of the refactoring plan, the `tools/` directory will be deleted and all imports should use `integration/` or module-specific locations.

### Import Path Changes

#### 1. FOL Text Conversion
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools import text_to_fol
from ipfs_datasets_py.logic.tools.text_to_fol import convert_text_to_fol
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.fol import text_to_fol
from ipfs_datasets_py.logic.fol import FOLConverter  # Recommended
```

#### 2. Deontic Logic Core
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent
)
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.integration.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent
)
# Or use the type definitions:
from ipfs_datasets_py.logic.types import DeonticFormula
```

#### 3. Symbolic FOL Bridge
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.symbolic_fol_bridge import SymbolicFOLBridge
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import SymbolicFOLBridge
```

#### 4. Symbolic Logic Primitives
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.symbolic_logic_primitives import (
    LogicSymbol,
    Quantifier,
    LogicOperator
)
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.integration.symbolic_logic_primitives import (
    LogicSymbol,
    Quantifier,
    LogicOperator
)
# Or use type definitions:
from ipfs_datasets_py.logic.types import LogicOperator, Quantifier
```

#### 5. Modal Logic Extension
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.modal_logic_extension import ModalLogicSymbol
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.integration.modal_logic_extension import ModalLogicSymbol
```

#### 6. Logic Translation Core
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.logic_translation_core import LogicTranslator
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.integration.logic_translation_core import LogicTranslator
```

#### 7. Legal Text to Deontic
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.legal_text_to_deontic import convert_legal_text
```

**New (Correct):**
```python
from ipfs_datasets_py.logic.deontic import legal_text_to_deontic
from ipfs_datasets_py.logic.deontic import DeonticConverter  # Recommended
```

### Utility Files Migration

#### 8. Logic Utils (Parsers, Formatters, Extractors)
**Old (Deprecated):**
```python
from ipfs_datasets_py.logic.tools.logic_utils import (
    fol_parser,
    deontic_parser,
    logic_formatter,
    predicate_extractor
)
```

**New (Correct):**
```python
# FOL utilities
from ipfs_datasets_py.logic.fol.utils import fol_parser
from ipfs_datasets_py.logic.fol.utils import predicate_extractor
from ipfs_datasets_py.logic.fol.utils import logic_formatter

# Deontic utilities
from ipfs_datasets_py.logic.deontic.utils import deontic_parser
```

### Automated Migration Script

You can use this script to update your imports:

```bash
#!/bin/bash
# migrate_imports.sh - Automatically update imports from tools/ to integration/

# Replace tools/ imports
find . -name "*.py" -type f -exec sed -i \
  's/from ipfs_datasets_py\.logic\.tools/from ipfs_datasets_py.logic.integration/g' {} +

# Replace specific module imports
find . -name "*.py" -type f -exec sed -i \
  's/from ipfs_datasets_py\.logic\.tools\.text_to_fol/from ipfs_datasets_py.logic.fol/g' {} +

find . -name "*.py" -type f -exec sed -i \
  's/from ipfs_datasets_py\.logic\.tools\.legal_text_to_deontic/from ipfs_datasets_py.logic.deontic/g' {} +

echo "Migration complete. Please review changes and test."
```

### Testing After Migration

After updating imports, run the test suite to ensure everything works:

```bash
# Test specific modules
pytest tests/unit_tests/logic/fol/
pytest tests/unit_tests/logic/deontic/
pytest tests/unit_tests/logic/integration/

# Run full logic module tests
pytest tests/unit_tests/logic/

# Check for any remaining tools/ imports
grep -r "from.*logic.tools" ipfs_datasets_py/ tests/
```

### Timeline

**Phase 3 Schedule:**
- Analysis of dependencies: Week 2
- Import path updates: Week 2
- Testing and validation: Week 2-3
- tools/ directory deletion: Week 3

### Backward Compatibility

During the transition period, a compatibility layer is available in `logic/__init__.py`:

```python
# Temporary backward compatibility (will be removed in v2.0)
import warnings

# Redirect old imports to new locations
def __getattr__(name):
    if name == "tools":
        warnings.warn(
            "Importing from logic.tools is deprecated. "
            "Use integration/ or module-specific imports instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from . import integration
        return integration
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### Need Help?

- **Full Refactoring Plan:** See `REFACTORING_PLAN.md` Phase 3
- **Import Analysis:** Run `grep -r "from.*logic.tools" .` to find all imports
- **Questions:** Refer to the main README.md or FEATURES.md

---

**Last Updated:** 2026-02-13  
**Status:** Active migration - tools/ directory scheduled for removal in Phase 3
