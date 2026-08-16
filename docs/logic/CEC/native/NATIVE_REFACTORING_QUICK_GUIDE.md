# CEC Native Folder - Quick Refactoring Guide

**Version:** 1.0  
**Date:** 2026-02-19  
**For:** Quick implementation reference

---

## 🎯 Top 3 Priorities

### 1. Split prover_core.py (P0, 8-10 hours)

**Current:** 2,927 LOC monolith with 120+ inference rule classes

**Target:** Create `inference_rules/` subpackage

```
native/inference_rules/
├── base.py              # InferenceRule ABC, ProofResult
├── propositional.py     # 15-20 basic logic rules
├── first_order.py       # 10-15 quantifier rules
├── temporal.py          # 15-20 event calculus rules
├── deontic.py           # 10-12 normative rules
├── modal.py             # 12-15 modal logic rules
├── cognitive.py         # 10-12 belief/knowledge rules
└── specialized.py       # 20-25 advanced rules

native/prover_core.py → ~500 LOC (just engine)
```

**Commands:**
```bash
# Create structure
mkdir -p ipfs_datasets_py/logic/CEC/native/inference_rules
cd ipfs_datasets_py/logic/CEC/native/inference_rules
touch __init__.py base.py propositional.py first_order.py
touch temporal.py deontic.py modal.py cognitive.py specialized.py

# Run tests
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py -v
```

**Success:**
- ✅ 2,927 → 500 LOC (-83%)
- ✅ 8 new modules created
- ✅ All tests passing

---

### 2. Split dcec_core.py (P0, 4-6 hours)

**Current:** 1,360 LOC mixing operators, types, terms, formulas

**Target:** Create `core/` subpackage

```
native/core/
├── operators.py       # DeonticOperator, CognitiveOperator, etc. (300 LOC)
├── type_system.py     # Sort, Variable, Function, Predicate (300 LOC)
├── terms.py           # Term hierarchy (350 LOC)
└── formulas.py        # Formula hierarchy (400 LOC)

native/dcec_core.py → ~100 LOC (re-exports for compatibility)
```

**Implementation:**
```python
# native/dcec_core.py becomes:
"""DCEC Core - Compatibility shim."""

from .core.operators import (
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    TemporalOperator,
)
from .core.type_system import Sort, Variable, Function, Predicate
from .core.terms import Term, VariableTerm, FunctionTerm, ConstantTerm
from .core.formulas import (
    Formula,
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    QuantifiedFormula,
)

__all__ = [...]  # List all exports
```

**Commands:**
```bash
# Create structure
mkdir -p ipfs_datasets_py/logic/CEC/native/core
cd ipfs_datasets_py/logic/CEC/native/core
touch __init__.py operators.py type_system.py terms.py formulas.py

# Test
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py -v
```

**Success:**
- ✅ 1,360 → 100 LOC (-93%)
- ✅ 4 new modules (<400 LOC each)
- ✅ Full backward compatibility

---

### 3. Eliminate Code Duplication (P0, 4-5 hours)

**Problem 1: Formula Equality (3 duplicate methods)**

```python
# ADD to native/core/formulas.py:Formula class
def __eq__(self, other: object) -> bool:
    """Check structural equality."""
    if not isinstance(other, Formula):
        return False
    return self.to_string() == other.to_string()


def __hash__(self) -> int:
    """Hash for set/dict usage."""
    return hash(self.to_string())
```

Remove from:
- prover_core.py:ModusPonens._formulas_equal()
- prover_core.py:DisjunctiveSyllogism._formulas_equal()
- prover_core.py:CutElimination._formulas_equal()

---

**Problem 2: Proof Statistics (3 dict structures)**

```python
# ADD to native/types.py
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ProofStatistics:
    """Unified proof statistics."""

    attempts: int = 0
    succeeded: int = 0
    failed: int = 0
    steps_taken: int = 0
    avg_time: float = 0.0
    cache_hits: int = 0
    rules_applied: Dict[str, int] = field(default_factory=dict)

    def record_success(self, steps: int, time: float) -> None:
        self.attempts += 1
        self.succeeded += 1
        self.steps_taken += steps
        self._update_avg_time(time)

    def record_failure(self, time: float) -> None:
        self.attempts += 1
        self.failed += 1
        self._update_avg_time(time)

    def _update_avg_time(self, time: float) -> None:
        self.avg_time = (self.avg_time * (self.attempts - 1) + time) / self.attempts
```

Replace in:
- shadow_prover.py (dict with 4 keys)
- prover_core.py (dict with 3 keys)
- cec_proof_cache.py (custom tracking)

---

**Problem 3: Error Handling (6 try/except blocks)**

```python
# CREATE native/error_handling.py
import logging
from typing import Callable, TypeVar
from functools import wraps

T = TypeVar("T")


def handle_proof_error(logger: logging.Logger, default_result=None) -> Callable:
    """Decorator for consistent error handling."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"{func.__name__} failed: {e}", exc_info=True)
                return default_result

        return wrapper

    return decorator


# USAGE:
from .error_handling import handle_proof_error


class ShadowProver:
    @handle_proof_error(logger, default_result=ProofResult.ERROR)
    def prove(self, formula: Formula) -> ProofResult:
        # Logic here
        pass
```

Replace in:
- shadow_prover.py (2 places)
- cec_zkp_integration.py (2 places)
- modal_tableaux.py (2 places)

**Success:**
- ✅ 15% → <3% duplication
- ✅ Type-safe statistics
- ✅ Consistent error handling

---

## 📊 Quick Metrics Check

### File Sizes
```bash
# Check largest files
cd ipfs_datasets_py/logic/CEC/native
find . -name "*.py" -exec wc -l {} + | sort -rn | head -10

# Target: No file >600 LOC
```

### Code Duplication
```bash
# Check duplication
pylint ipfs_datasets_py/logic/CEC/native/ --duplicate-code=yes

# Target: <3% duplication
```

### Type Coverage
```bash
# Check types
mypy ipfs_datasets_py/logic/CEC/native/ --strict

# Target: 0 errors
```

### Tests
```bash
# Run tests
pytest tests/unit_tests/logic/CEC/native/ -v

# Target: All passing
```

---

## 🗺️ Implementation Order

```
Week 1:  ████ Setup infrastructure
Week 2:  ████ Extract inference rules (propositional, first-order)
Week 3:  ████ Extract inference rules (temporal, deontic, modal)
Week 4:  ████ Split dcec_core.py
Week 5:  ██   Eliminate duplication
Week 6:  ██   Type hints & grammar extraction
Week 7:  █    Documentation
Week 8:  █    Testing & performance
```

---

## ⚡ Quick Commands

### Create Packages
```bash
# Inference rules
mkdir -p ipfs_datasets_py/logic/CEC/native/inference_rules
cd ipfs_datasets_py/logic/CEC/native/inference_rules
for f in __init__ base propositional first_order temporal deontic modal cognitive specialized; do
    touch ${f}.py
done

# Core
mkdir -p ipfs_datasets_py/logic/CEC/native/core
cd ipfs_datasets_py/logic/CEC/native/core
for f in __init__ operators type_system terms formulas; do
    touch ${f}.py
done
```

### Testing
```bash
# Run native folder tests
pytest tests/unit_tests/logic/CEC/native/ -v

# Run specific test file
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py -v

# Run with coverage
pytest --cov=ipfs_datasets_py.logic.CEC.native tests/unit_tests/logic/CEC/native/
```

### Code Quality
```bash
# Type check
mypy ipfs_datasets_py/logic/CEC/native/ --strict

# Complexity check
radon cc ipfs_datasets_py/logic/CEC/native/ -a -nb

# Duplication check
pylint ipfs_datasets_py/logic/CEC/native/ --duplicate-code=yes
```

---

## 🎯 Success Criteria

### Phase 1 Complete (Weeks 1-4)
- ✅ prover_core.py: 2,927 → <500 LOC
- ✅ dcec_core.py: 1,360 → <100 LOC
- ✅ 11 new modules created
- ✅ All 27+ tests passing

### Phase 2 Complete (Weeks 5-6)
- ✅ Code duplication: 15% → <3%
- ✅ Type coverage: 70% → >95%
- ✅ ProofStatistics unified
- ✅ Error handling consistent

### Phase 3 Complete (Weeks 7-8)
- ✅ 100% docstring coverage
- ✅ 45+ test files
- ✅ Performance validated
- ✅ All quality metrics met

---

## 📚 Reference Documents

- **Full Plan:** `NATIVE_REFACTORING_PLAN_2026.md` (34KB, comprehensive)
- **Parent Plan:** `../CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` (CEC folder)
- **Tests:** `tests/unit_tests/logic/CEC/native/`

---

## 🔍 Common Issues

### Issue: Import Errors After Split
```python
# Solution: Update imports
# Before:
from .prover_core import ModusPonens

# After:
from .inference_rules.propositional import ModusPonens
```

### Issue: Tests Failing
```bash
# Solution: Check imports
python -c "from ipfs_datasets_py.logic.CEC.native import prover_core"
python -c "from ipfs_datasets_py.logic.CEC.native.inference_rules import base"

# Run incrementally
pytest tests/unit_tests/logic/CEC/native/test_prover_core.py::TestBasicProver -v
```

### Issue: Circular Imports
```python
# Solution: Use TYPE_CHECKING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dcec_core import Formula
```

---

## 💡 Tips

1. **Work incrementally** - Don't try to refactor everything at once
2. **Run tests frequently** - After every significant change
3. **Keep backup** - Use git branches for each phase
4. **Update imports carefully** - Use IDE refactoring tools when possible
5. **Document as you go** - Add docstrings immediately

---

## 📈 Expected Impact

| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Largest File | 2,927 LOC | <500 LOC | -83% |
| Module Count | 29 | ~45 | +55% |
| Duplication | 15% | <3% | -80% |
| Type Coverage | 70% | >95% | +25% |
| Testability | Low | High | ++ |
| Maintainability | Medium | High | ++ |

---

**Quick Guide Version:** 1.0  
**Last Updated:** 2026-02-19  
**For:** Native folder refactoring implementation
