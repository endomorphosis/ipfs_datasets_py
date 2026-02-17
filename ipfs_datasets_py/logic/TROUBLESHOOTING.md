# Logic Module Troubleshooting Guide

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Purpose:** Solutions to common issues and problems

This guide helps you solve common problems when using the logic module.

---

## Table of Contents

- [Decision Tree](#decision-tree)
- [Quick Diagnostic](#quick-diagnostic)
- [Installation Issues](#installation-issues)
- [Import Errors](#import-errors)
- [Conversion Errors](#conversion-errors)
- [Performance Issues](#performance-issues)
- [Theorem Proving Issues](#theorem-proving-issues)
- [Feature Detection Issues](#feature-detection-issues)
- [Testing Issues](#testing-issues)
- [Common Error Messages](#common-error-messages)
- [Getting Help](#getting-help)
- [FAQ](#faq)

---

## Decision Tree

**Start here to quickly diagnose your issue:**

```
┌─────────────────────────────────────┐
│  What type of problem are you      │
│  experiencing?                       │
└──────────────┬──────────────────────┘
               │
    ┌──────────┴──────────┬──────────────────┬─────────────────┐
    │                     │                  │                 │
┌───▼────┐         ┌─────▼──────┐    ┌─────▼──────┐   ┌────▼─────┐
│Import  │         │Conversion  │    │Performance │   │ Proving  │
│Errors  │         │Errors      │    │Issues      │   │ Issues   │
└───┬────┘         └─────┬──────┘    └─────┬──────┘   └────┬─────┘
    │                    │                  │               │
    │                    │                  │               │
    │ ModuleNotFound?    │ No result?       │ Slow?         │ Timeout?
    │ → Install pkg      │ → Check input    │ → Enable      │ → Increase
    │                    │                  │   cache       │   timeout
    │                    │                  │               │
    │ ImportError?       │ Wrong format?    │ Memory?       │ No proof?
    │ → Check deps       │ → Check docs     │ → Limit       │ → Check
    │                    │                  │   batch size  │   axioms
    │                    │                  │               │
    │ DeprecationWarn?   │ Low confidence?  │ CPU high?     │ Error?
    │ → Update imports   │ → Install        │ → Reduce      │ → Check
    │                    │   spaCy/Z3       │   complexity  │   logs
    │                    │                  │               │
    │                    │                  │               │
    └────────────────────┴──────────────────┴───────────────┘
                         │
                         ▼
                 Still not working?
                         │
            ┌────────────┴────────────┐
            │                         │
    ┌───────▼─────────┐      ┌───────▼────────┐
    │ Check           │      │ Open GitHub    │
    │ ERROR_REFERENCE │      │ Issue          │
    └─────────────────┘      └────────────────┘
```

**Quick Links by Problem Type:**
- **Can't install/import?** → [Installation Issues](#installation-issues)
- **Conversion not working?** → [Conversion Errors](#conversion-errors)
- **Too slow?** → [Performance Issues](#performance-issues)
- **Proving fails?** → [Theorem Proving Issues](#theorem-proving-issues)
- **Unknown error?** → [Common Error Messages](#common-error-messages)

---

## Quick Diagnostic

Run this first to check your setup:

```bash
# Check feature availability
python -m ipfs_datasets_py.logic.common.feature_detection

# Check Python version
python --version  # Requires Python 3.12+

# Quick health check
python -c "
from ipfs_datasets_py.logic.fol import FOLConverter
converter = FOLConverter()
result = converter.convert('All cats are animals')
print('✅ Logic module working!' if result.success else '❌ Issue detected')
print(f'Features available: {result.metadata}')
"
```

---

## Installation Issues

### Problem: "No module named 'ipfs_datasets_py'"

**Symptoms:**
```python
>>> from ipfs_datasets_py.logic import FOLConverter
ModuleNotFoundError: No module named 'ipfs_datasets_py'
```

**Solutions:**

1. **Install the package:**
   ```bash
   pip install -e .
   # Or from repository root:
   pip install -e ".[logic]"
   ```

2. **Check installation:**
   ```bash
   pip list | grep ipfs-datasets
   ```

3. **Verify Python path:**
   ```python
   import sys
   print(sys.path)
   # Should include package directory
   ```

### Problem: "Python version too old"

**Symptoms:**
```bash
ERROR: Package requires Python >=3.12
```

**Solutions:**

1. **Check version:**
   ```bash
   python --version
   ```

2. **Upgrade Python:**
   ```bash
   # Ubuntu/Debian
   sudo apt install python3.12
   
   # macOS (Homebrew)
   brew install python@3.12
   
   # Or use pyenv
   pyenv install 3.12.0
   pyenv local 3.12.0
   ```

3. **Use virtual environment:**
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate  # Linux/macOS
   # or: venv\Scripts\activate  # Windows
   ```

### Problem: "Optional dependency warnings"

**Symptoms:**
```
UserWarning: SymbolicAI not available, using fallback
UserWarning: Z3 not available, using native prover
```

**This is NORMAL!** The module works fine with fallbacks.

**To install optional dependencies:**
```bash
# For enhanced performance
pip install symbolicai z3-solver

# For maximum accuracy
pip install symbolicai z3-solver spacy xgboost lightgbm
python -m spacy download en_core_web_sm

# Check what you have
python -m ipfs_datasets_py.logic.common.feature_detection
```

---

## Import Errors

### Problem: "ImportError: cannot import name 'FOLConverter'"

**Symptoms:**
```python
>>> from ipfs_datasets_py.logic.fol import FOLConverter
ImportError: cannot import name 'FOLConverter'
```

**Solutions:**

1. **Check correct import path:**
   ```python
   # Correct:
   from ipfs_datasets_py.logic.fol import FOLConverter
   
   # Also correct (shorter):
   from ipfs_datasets_py.logic import FOLConverter
   ```

2. **Verify module structure:**
   ```bash
   ls ipfs_datasets_py/logic/fol/
   # Should see converter.py
   ```

3. **Reinstall if corrupted:**
   ```bash
   pip uninstall ipfs-datasets-py
   pip install -e .
   ```

### Problem: "DeprecationWarning" messages

**Symptoms:**
```python
DeprecationWarning: ipfs_datasets_py.logic.integrations.phase7_complete_integration is deprecated
```

**Solutions:**

1. **Update import paths:**
   ```python
   # Old (deprecated):
   from ipfs_datasets_py.logic.integrations.phase7_complete_integration import X
   
   # New (correct):
   from ipfs_datasets_py.processors.graphrag.phase7_complete_integration import X
   ```

2. **Suppress warnings (not recommended):**
   ```python
   import warnings
   warnings.filterwarnings('ignore', category=DeprecationWarning)
   ```

### Problem: "ZKP simulation warning"

**Symptoms:**
```python
UserWarning: ⚠️ WARNING: ipfs_datasets_py.logic.zkp is a SIMULATION module, 
NOT cryptographically secure!
```

**This is intentional!** ZKP module is for demonstration only.

**Solutions:**

1. **Use for educational purposes only:**
   ```python
   from ipfs_datasets_py.logic.zkp import SimulatedZKPProver
   # Name makes it clear it's simulated
   ```

2. **For production ZKP, see roadmap:**
   - Read `KNOWN_LIMITATIONS.md` section on ZKP
   - Wait for v2.0 with real zkSNARKs integration
   - Or integrate `py_ecc` yourself

---

## Conversion Errors

### Problem: "Conversion failed" or low success rate

**Symptoms:**
```python
result = converter.convert("complex sentence")
print(result.success)  # False
print(result.errors)   # ["Parsing failed", ...]
```

**Solutions:**

1. **Check input format:**
   ```python
   # Good inputs:
   "All X are Y"
   "P -> Q"
   "If P then Q"
   
   # Bad inputs:
   ""  # Empty
   None  # Not a string
   "???"  # Invalid symbols
   ```

2. **Enable NLP for complex sentences:**
   ```python
   converter = FOLConverter(use_nlp=True)
   result = converter.convert("Professors who teach are educators")
   # NLP helps with complex structure
   ```

3. **Check available features:**
   ```python
   from ipfs_datasets_py.logic.common.feature_detection import FeatureDetector
   
   if not FeatureDetector.has_spacy():
       print("Install spaCy for better accuracy")
       print("pip install spacy")
       print("python -m spacy download en_core_web_sm")
   ```

4. **Use simpler formulations:**
   ```python
   # Complex (may fail):
   "All professors who teach courses that students attend are educators"
   
   # Simpler (more likely to succeed):
   "All professors teach courses"
   "Students attend courses"
   "Teachers are educators"
   ```

### Problem: "AttributeError: 'NoneType' object has no attribute 'formula_string'"

**Symptoms:**
```python
result = converter.convert("text")
print(result.output.formula_string)  # AttributeError
```

**Solutions:**

1. **Always check success first:**
   ```python
   result = converter.convert("text")
   
   if result.success:
       print(result.output.formula_string)
   else:
       print(f"Conversion failed: {result.errors}")
   ```

2. **Use safe access:**
   ```python
   formula = result.output.formula_string if result.success else "N/A"
   ```

### Problem: "Confidence score seems wrong"

**Symptoms:**
```python
result = converter.convert("P -> Q")
print(result.output.confidence)  # 0.65 (seems low)
```

**Solutions:**

1. **Install ML models for better confidence:**
   ```bash
   pip install xgboost lightgbm
   ```

2. **Check if ML is being used:**
   ```python
   from ipfs_datasets_py.logic.common.feature_detection import FeatureDetector
   
   if FeatureDetector.has_ml_models():
       print("Using ML confidence (accurate)")
   else:
       print("Using heuristic confidence (approximate)")
   ```

3. **Understand confidence meaning:**
   - 0.9-1.0: Very high confidence (well-formed, clear)
   - 0.7-0.9: High confidence (good structure)
   - 0.5-0.7: Medium confidence (some ambiguity)
   - 0.3-0.5: Low confidence (unclear structure)
   - 0.0-0.3: Very low confidence (likely incorrect)

---

## Performance Issues

### Problem: "Conversions are slow"

**Symptoms:**
- Processing 100 items takes >10 seconds
- Single conversion >100ms

**Solutions:**

1. **Install performance dependencies:**
   ```bash
   pip install symbolicai
   # 5-10x speedup for symbolic operations
   ```

2. **Enable caching:**
   ```python
   converter = FOLConverter(use_cache=True)
   
   # First call: 50ms
   result1 = converter.convert("text")
   
   # Second call: 3.5ms (14x faster!)
   result2 = converter.convert("text")
   ```

3. **Use batch processing:**
   ```python
   # Slow (sequential):
   results = []
   for text in texts:
       results.append(converter.convert(text))
   
   # Fast (parallel):
   results = converter.convert_batch(texts, max_workers=4)
   # 2-8x faster
   ```

4. **Profile your code:**
   ```python
   import time
   
   start = time.time()
   result = converter.convert("text")
   elapsed = time.time() - start
   
   print(f"Conversion took {elapsed*1000:.2f}ms")
   
   # If >50ms without cache, check:
   # 1. SymbolicAI installed?
   # 2. Complex input?
   # 3. First run (cache miss)?
   ```

### Problem: "High memory usage"

**Symptoms:**
- Memory grows over time
- Out of memory errors

**Solutions:**

1. **Clear cache periodically:**
   ```python
   # If processing large batches
   converter = FOLConverter(use_cache=True)
   
   # Process in chunks
   for chunk in chunks(texts, 1000):
       results = converter.convert_batch(chunk)
       # Cache cleared automatically by LRU
   ```

2. **Disable caching for one-off conversions:**
   ```python
   converter = FOLConverter(use_cache=False)
   ```

3. **Use generator patterns:**
   ```python
   def process_stream(texts):
       converter = FOLConverter()
       for text in texts:
           yield converter.convert(text)
   
   # Memory efficient
   for result in process_stream(large_dataset):
       handle_result(result)
   ```

### Problem: "Batch processing not faster"

**Symptoms:**
```python
# Sequential and batch take similar time
```

**Solutions:**

1. **Ensure enough workers:**
   ```python
   import os
   cpu_count = os.cpu_count()
   
   results = converter.convert_batch(
       texts,
       max_workers=cpu_count  # Use all CPUs
   )
   ```

2. **Check if items are cached:**
   ```python
   # If all items cached, parallel doesn't help
   # First run will be faster with parallel
   ```

3. **Profile batch size:**
   ```python
   import time
   
   for batch_size in [10, 50, 100, 500]:
       start = time.time()
       results = converter.convert_batch(texts[:batch_size])
       elapsed = time.time() - start
       print(f"Batch {batch_size}: {elapsed:.2f}s ({elapsed/batch_size*1000:.1f}ms per item)")
   ```

---

## Theorem Proving Issues

### Problem: "Proof fails for simple theorem"

**Symptoms:**
```python
reasoner.add_knowledge("P")
reasoner.add_knowledge("P -> Q")
result = reasoner.prove("Q")
print(result.is_proved())  # False (should be True)
```

**Solutions:**

1. **Check formula format:**
   ```python
   # Use correct syntax
   reasoner.add_knowledge("P -> Q")  # Correct
   # Not: reasoner.add_knowledge("P implies Q")
   ```

2. **Verify knowledge added:**
   ```python
   print(reasoner.get_knowledge())
   # Should show: ["P", "P -> Q"]
   ```

3. **Try different proving methods:**
   ```python
   # Try forward chaining explicitly
   result = reasoner.prove("Q", method="forward_chaining")
   
   # Or use Z3 if installed
   result = reasoner.prove("Q", method="z3")
   ```

### Problem: "Complex proof times out"

**Symptoms:**
- Proof takes >10 seconds
- Eventually fails

**Solutions:**

1. **Install Z3 for complex proofs:**
   ```bash
   pip install z3-solver
   ```

2. **Increase timeout:**
   ```python
   result = reasoner.prove("Q", timeout=60)  # 60 seconds
   ```

3. **Simplify proof:**
   ```python
   # Instead of one complex proof:
   reasoner.prove("A and B and C and D")
   
   # Break into steps:
   reasoner.prove("A and B")
   reasoner.prove("C and D")
   reasoner.prove("(A and B) and (C and D)")
   ```

4. **Check rule availability:**
   ```python
   # See which rules are available
   print(reasoner.available_rules())
   
   # Complex proofs may need rules we don't have
   ```

### Problem: "Proof succeeds but explanation missing"

**Symptoms:**
```python
result = reasoner.prove("Q")
print(result.is_proved())  # True
print(result.proof_steps)  # []
```

**Solutions:**

1. **Enable proof tracking:**
   ```python
   result = reasoner.prove("Q", track_steps=True)
   print(result.proof_steps)  # Now shows steps
   ```

2. **Check prover method:**
   ```python
   # Z3 may not provide detailed steps
   result = reasoner.prove("Q", method="forward_chaining")
   # Forward chaining gives detailed steps
   ```

---

## Feature Detection Issues

### Problem: "Feature detector shows everything missing"

**Symptoms:**
```bash
$ python -m ipfs_datasets_py.logic.common.feature_detection
Available Features: 0
Missing Features: 5
```

**Solutions:**

1. **Check virtual environment:**
   ```bash
   which python
   # Make sure using correct Python with packages
   ```

2. **Reinstall dependencies:**
   ```bash
   pip install symbolicai z3-solver spacy xgboost lightgbm ipfshttpclient
   ```

3. **Check import manually:**
   ```python
   import sys
   try:
       import symbolicai
       print("SymbolicAI OK")
   except ImportError as e:
       print(f"SymbolicAI missing: {e}")
   ```

### Problem: "spaCy installed but not detected"

**Symptoms:**
```python
FeatureDetector.has_spacy()  # True
FeatureDetector.has_spacy_model()  # False
```

**Solutions:**

1. **Download model:**
   ```bash
   python -m spacy download en_core_web_sm
   ```

2. **Verify model:**
   ```python
   import spacy
   nlp = spacy.load("en_core_web_sm")
   print("Model loaded OK")
   ```

3. **Check model location:**
   ```bash
   python -m spacy info en_core_web_sm
   ```

---

## Testing Issues

### Problem: "Tests fail with import errors"

**Symptoms:**
```bash
$ pytest tests/
ImportError: No module named 'symbolicai'
```

**Solutions:**

1. **Install test dependencies:**
   ```bash
   pip install -e ".[test]"
   ```

2. **Tests should handle missing deps:**
   ```python
   # Good test pattern:
   import pytest
   
   @pytest.mark.skipif(
       not FeatureDetector.has_symbolicai(),
       reason="SymbolicAI not available"
   )
   def test_symbolic_feature():
       # Test code
       pass
   ```

3. **Run tests for available features only:**
   ```bash
   pytest tests/ -m "not requires_symbolicai"
   ```

### Problem: "Tests pass locally but fail in CI"

**Symptoms:**
- Local: All tests pass
- CI: Import errors or missing features

**Solutions:**

1. **Check CI dependencies:**
   ```yaml
   # .github/workflows/test.yml
   - name: Install dependencies
     run: |
       pip install -e ".[test]"
       pip install symbolicai z3-solver  # Add optional deps
   ```

2. **Use feature detection in tests:**
   ```python
   @pytest.mark.skipif(
       not FeatureDetector.has_z3(),
       reason="Z3 not available in CI"
   )
   def test_z3_proof():
       # Test code
       pass
   ```

3. **Separate test suites:**
   ```bash
   # Run core tests (no optional deps)
   pytest tests/ -m "not optional"
   
   # Run full tests (with optional deps)
   pytest tests/
   ```

---

## Common Error Messages

### "ValidationError: Input cannot be empty"

**Cause:** Empty or None input to converter

**Fix:**
```python
# Check input before converting
text = get_text()
if text and text.strip():
    result = converter.convert(text)
else:
    print("Empty input")
```

### "CacheError: Cache size exceeded"

**Cause:** Too many cached items

**Fix:**
```python
# Increase cache size or clear periodically
converter = FOLConverter(
    use_cache=True,
    cache_size=10000  # Default: 1000
)
```

### "TimeoutError: Proof search exceeded time limit"

**Cause:** Complex proof takes too long

**Fix:**
```python
# Increase timeout or simplify proof
result = reasoner.prove("Q", timeout=120)
```

### "UnsupportedFormulaError: Formula type not supported"

**Cause:** Using formula type not implemented

**Fix:**
```python
# Check supported formula types
print(converter.supported_types())

# Use supported type or request feature
```

---

## Getting Help

### Check Documentation

1. **[README.md](./README.md)** - Main documentation
2. **[KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)** - Feature status
3. **[FALLBACK_BEHAVIORS.md](./FALLBACK_BEHAVIORS.md)** - Dependency fallbacks
4. **[INFERENCE_RULES_INVENTORY.md](./INFERENCE_RULES_INVENTORY.md)** - Rule listing

### Run Diagnostics

```bash
# Feature detection
python -m ipfs_datasets_py.logic.common.feature_detection

# Python version
python --version

# Package version
pip show ipfs-datasets-py

# Check installation
python -c "from ipfs_datasets_py.logic import FOLConverter; print('OK')"
```

### Enable Debug Logging

```python
import logging

# Enable debug logs
logging.basicConfig(level=logging.DEBUG)

# Now run your code
converter = FOLConverter()
result = converter.convert("text")
# Will show detailed debugging info
```

### Create Minimal Reproducible Example

```python
# Minimal example for bug reports
from ipfs_datasets_py.logic import FOLConverter

converter = FOLConverter()
result = converter.convert("test input")

print(f"Success: {result.success}")
print(f"Errors: {result.errors}")

# Include:
# 1. Python version: python --version
# 2. Package version: pip show ipfs-datasets-py
# 3. Available features: python -m ...feature_detection
# 4. Expected vs actual behavior
```

### Report Issues

If you find a bug:

1. Check if it's already reported
2. Create minimal reproducible example
3. Include diagnostic information
4. Open GitHub issue with details

---

## FAQ

**Q: Do I need to install all optional dependencies?**

A: No! The module works fine without them, just with reduced performance or accuracy. See [FALLBACK_BEHAVIORS.md](./FALLBACK_BEHAVIORS.md).

**Q: Why do I see DeprecationWarnings?**

A: Old import paths have been moved. Update your imports to the new locations shown in the warning message.

**Q: Is the ZKP module secure?**

A: No! It's a simulation for educational purposes only. See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) section on ZKP.

**Q: Why are my proofs slow?**

A: Install Z3 (`pip install z3-solver`) for faster automated proving, or SymbolicAI for faster symbolic operations.

**Q: How do I know what features are available?**

A: Run `python -m ipfs_datasets_py.logic.common.feature_detection` to see what's installed.

**Q: Can I use this in production?**

A: Yes, for FOL/Deontic conversion, caching, and basic theorem proving. See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) for details on what's production-ready.

---

## Additional Resources

**Comprehensive Documentation:**
- [ERROR_REFERENCE.md](./ERROR_REFERENCE.md) - Complete error catalog with solutions
- [PERFORMANCE_TUNING.md](./PERFORMANCE_TUNING.md) - Performance optimization guide
- [SECURITY_GUIDE.md](./SECURITY_GUIDE.md) - Security best practices
- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) - Production deployment
- [API_VERSIONING.md](./API_VERSIONING.md) - API stability and versioning
- [CONTRIBUTING.md](./CONTRIBUTING.md) - How to contribute

**Quick References:**
- [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) - Known limitations and workarounds
- [FALLBACK_BEHAVIORS.md](./FALLBACK_BEHAVIORS.md) - Fallback behavior details
- [API_REFERENCE.md](./API_REFERENCE.md) - Complete API documentation

---

**Document Version:** 2.0  
**Date:** 2026-02-17  
**Status:** Comprehensive troubleshooting guide with decision tree and error cross-references
