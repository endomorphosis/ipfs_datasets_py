# CEC Refactoring Quick Reference 2026

**Version:** 1.0  
**Date:** 2026-02-19  
**For:** Quick implementation guidance

---

## 🎯 Top 5 Priorities

### 1. Split prover_core.py (P0, 3-4 weeks)
```bash
# Current: 2,927 LOC monolithic file
# Target: 8 modules × ~350 LOC

native/inference_rules/
├── base.py              # InferenceRule ABC
├── propositional.py     # AND, OR, NOT, IMPLIES
├── first_order.py       # Universal/existential
├── temporal.py          # Temporal reasoning
├── deontic.py           # Deontic logic
├── modal.py             # Modal operators
├── cognitive.py         # Belief/knowledge
└── specialized.py       # Advanced rules

native/prover/
├── engine.py            # Core proof engine
├── cache.py             # Proof caching
├── tree.py              # Proof tree generation
├── strategy.py          # Strategy management
└── utils.py             # Helper functions
```

**Commands:**
```bash
# Week 1-2: Create structure
mkdir -p ipfs_datasets_py/logic/CEC/native/inference_rules
mkdir -p ipfs_datasets_py/logic/CEC/native/prover
touch ipfs_datasets_py/logic/CEC/native/inference_rules/__init__.py
touch ipfs_datasets_py/logic/CEC/native/prover/__init__.py

# Week 2-3: Extract rules
# Move rule classes to appropriate modules
# Update imports

# Week 3-4: Extract prover components
# Move engine, cache, tree, strategy
# Validate tests
pytest tests/unit_tests/logic/CEC/native/test_prover.py
```

---

### 2. Consolidate Language Parsers (P0, 2-3 weeks)
```bash
# Current: 3 files × 600 LOC = 1,814 LOC (95% duplicate)
# Target: 1 file + 4 vocab configs = 1,000 LOC

nl/multilingual_parser.py      # Unified parser (600 LOC)
nl/vocabularies/
├── __init__.py
├── english.py                  # Vocab config (200 LOC)
├── german.py                   # Vocab config (200 LOC)
├── french.py                   # Vocab config (200 LOC)
└── spanish.py                  # Vocab config (200 LOC)
```

**Implementation:**
```python
# nl/multilingual_parser.py
class MultilingualParser(BaseParser):
    def __init__(self, language: str = "en"):
        self.language = language
        self.vocab = LANGUAGE_VOCABULARIES[language]
    
    # Single implementation of parsing logic
    # Works for all languages
```

**Commands:**
```bash
# Week 1: Create unified parser
touch ipfs_datasets_py/logic/CEC/nl/multilingual_parser.py

# Week 1-2: Extract vocabularies
mkdir -p ipfs_datasets_py/logic/CEC/nl/vocabularies
# Extract vocab dicts from each parser

# Week 2: Test and validate
pytest tests/unit_tests/logic/CEC/nl/
```

---

### 3. Create ARCHITECTURE.md (P0, 2 weeks)
```markdown
# ARCHITECTURE.md structure

1. Overview
   - Design principles
   - Component diagram
   - Dependency graph

2. Core Components
   - dcec_core: Type system
   - prover: Theorem proving
   - inference_rules: Rule system

3. Subsystems
   - NL processing pipeline
   - Temporal reasoning
   - Modal logic
   - Caching & optimization

4. Extension Points
   - Adding inference rules
   - Adding operators
   - Adding languages
   - Integrating provers

5. Design Patterns
   - Visitor (formula traversal)
   - Strategy (proving)
   - Adapter (external provers)
   - Factory (formula creation)

6. Developer Guides
   - Quick start
   - Common patterns
   - Debugging tips
```

---

### 4. Add __all__ Exports (P1, 1 week)
```python
# Every module should have __all__

# Example: native/__init__.py
__all__ = [
    # Types
    "Formula",
    "AtomicFormula",
    "ConnectiveFormula",
    # Operators
    "DeonticOperator",
    "CognitiveOperator",
    # Provers
    "Prover",
    "ProofResult",
]

# From sub-packages
from .types import Formula, AtomicFormula
from .prover import Prover, ProofResult
```

**Commands:**
```bash
# Add to all 57 Python files
for file in $(find ipfs_datasets_py/logic/CEC -name "*.py"); do
    # Add __all__ = [...] at top of file
    echo "Adding __all__ to $file"
done
```

---

### 5. Create Stringifiable Mixin (P1, 2 weeks)
```python
# native/mixins.py (new file)
from abc import ABC, abstractmethod
from typing import Dict, Any


class Stringifiable(ABC):
    """Mixin for consistent string representation."""

    @abstractmethod
    def _to_string_parts(self) -> Dict[str, Any]:
        """Return dict of parts for string representation."""
        pass

    def to_string(self, verbose: bool = False) -> str:
        """Generate string representation."""
        parts = self._to_string_parts()
        if verbose:
            return (
                f"{parts['type']}({', '.join(f'{k}={v}' for k, v in parts.items() if k != 'type')})"
            )
        return self._format_simple(parts)

    def __str__(self) -> str:
        return self.to_string(verbose=False)

    def __repr__(self) -> str:
        return self.to_string(verbose=True)
```

**Usage:**
```python
class AtomicFormula(Stringifiable):
    def _to_string_parts(self):
        return {
            "type": "AtomicFormula",
            "predicate": self.predicate,
            "terms": self.terms,
        }
```

---

## 📊 Success Metrics Cheat Sheet

### File Sizes
```bash
# Check largest files
find ipfs_datasets_py/logic/CEC -name "*.py" -exec wc -l {} + | sort -rn | head -10

# Target: No file >600 LOC
```

### Type Coverage
```bash
# Run mypy
mypy ipfs_datasets_py/logic/CEC --strict

# Target: 0 errors
```

### Test Coverage
```bash
# Run with coverage
pytest --cov=ipfs_datasets_py.logic.CEC --cov-report=term tests/unit_tests/logic/CEC/

# Target: >85% coverage
```

### Code Duplication
```bash
# Use PMD/CPD or similar
# Target: <5% duplication
```

### Import Time
```bash
# Measure import time
time python -c "from ipfs_datasets_py.logic.CEC import native"

# Target: <1 second
```

---

## 🗺️ Implementation Order

```
Week 1-4:   ████████ Phase 1: Split Files (P0-1)
Week 3-5:     ██████ Phase 2: Consolidate (P0-2)
Week 5-7:       ██████ Phase 3: Documentation (P0-3)
Week 7-9:         ██████ Phase 4: Type Safety (P1-3)
Week 9-10:          ████ Phase 5: Imports (P1-1)
Week 10-12:           ██████ Phase 6: Polish (P1-2, P2)
```

---

## ⚡ Quick Commands

### Testing
```bash
# Run all CEC tests
pytest tests/unit_tests/logic/CEC/

# Run specific test file
pytest tests/unit_tests/logic/CEC/native/test_prover.py

# Run with coverage
pytest --cov=ipfs_datasets_py.logic.CEC tests/unit_tests/logic/CEC/

# Run parallel (faster)
pytest -n auto tests/unit_tests/logic/CEC/
```

### Linting
```bash
# Format code
black ipfs_datasets_py/logic/CEC/

# Sort imports
isort ipfs_datasets_py/logic/CEC/

# Check style
flake8 ipfs_datasets_py/logic/CEC/

# Type check
mypy ipfs_datasets_py/logic/CEC/
```

### Analysis
```bash
# Count LOC
find ipfs_datasets_py/logic/CEC -name "*.py" -exec wc -l {} + | tail -1

# Find large files
find ipfs_datasets_py/logic/CEC -name "*.py" -exec wc -l {} + | sort -rn | head -20

# Count functions/classes
python -c "
import ast
import glob
funcs = 0
classes = 0
for f in glob.glob('ipfs_datasets_py/logic/CEC/**/*.py', recursive=True):
    try:
        with open(f) as file:
            tree = ast.parse(file.read())
            funcs += sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
            classes += sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    except: pass
print(f'Functions: {funcs}, Classes: {classes}')
"
```

---

## 🎯 Target State

### File Structure After Refactoring
```
CEC/
├── native/
│   ├── types/               # From dcec_core.py split
│   ├── prover/              # From prover_core.py split
│   ├── inference_rules/     # From prover_core.py split
│   └── [other modules]
├── nl/
│   ├── multilingual_parser.py   # Unified parser
│   ├── vocabularies/            # Language configs
│   └── [other modules]
├── provers/                 # External provers
├── optimization/            # Performance
└── [wrappers]

Largest file: <600 LOC (was 2,927)
Total LOC: ~22,500 (was 24,286, -7%)
Type safety: >90% (was ~60%)
```

### Metrics After Refactoring
```
✅ No file >600 LOC
✅ Code duplication <5%
✅ Type coverage >90%
✅ Test coverage >85%
✅ mypy --strict passes
✅ Import time <1s
✅ All 208+ tests passing
✅ Maintainability index >75
```

---

## 🔍 Common Issues & Solutions

### Issue: Import Errors After Refactoring
```python
# Solution: Update imports
# Before:
from .prover_core import Prover

# After:
from .prover import Prover
```

### Issue: Circular Imports
```python
# Solution: Use absolute imports
# Before:
from ..native import Formula

# After:
from ipfs_datasets_py.logic.CEC.native import Formula
```

### Issue: Tests Failing
```bash
# Solution: Run tests incrementally
pytest tests/unit_tests/logic/CEC/native/test_prover.py -v

# Check imports
python -c "from ipfs_datasets_py.logic.CEC.native import Prover"
```

### Issue: Type Errors
```python
# Solution: Add proper type hints
# Before:
def process(data: Any) -> Any: ...


# After:
def process(data: List[Formula]) -> ProofResult: ...
```

---

## 📚 Reference Documents

- **Full Plan:** `CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md`
- **Current Status:** `STATUS.md`
- **Architecture:** `ARCHITECTURE.md` (to be created)
- **API Reference:** `API_REFERENCE_v2.md` (to be created)

---

## 🤝 Getting Help

**Questions?**
- Check full plan document
- Check STATUS.md
- Open GitHub issue
- Ask in discussions

**Found a bug?**
- Open GitHub issue with:
  - Steps to reproduce
  - Expected behavior
  - Actual behavior
  - Code snippet

---

**Quick Reference Version:** 1.0  
**Last Updated:** 2026-02-19  
**Maintained By:** IPFS Datasets Team
