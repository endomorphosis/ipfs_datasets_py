# TDFOL Refactoring - Quick Reference Guide
## Developer Cheat Sheet - February 18, 2026

**Quick Links:**
- 📋 [Full Plan](./REFACTORING_PLAN_2026_02_18.md)
- 📊 [Executive Summary](./REFACTORING_EXECUTIVE_SUMMARY_2026_02_18.md)
- 📚 [Module README](./README.md)

---

## 🎯 At a Glance

**Current Status:** Phase 7 Complete (NL Processing ✅)  
**Next Phase:** Track 1 Quick Wins (2-3 weeks)  
**Priority:** 🔴 Critical - Must complete before production

**Key Stats:**
- 📦 13,073 LOC delivered (Phases 1-7)
- ✅ 190 tests (100% pass rate)
- 🎯 Target: 910+ tests, 90%+ coverage
- ⏱️ Timeline: 17-22 weeks to production

---

## 📋 Task Checklists

### ✅ Track 1: Quick Wins (Weeks 1-3)

#### Week 1: Foundation
- [ ] **Task 1.1:** Create `exceptions.py` (7 classes) - 4h
  - [ ] `TDFOLError` base class
  - [ ] `ParseError` with position info
  - [ ] `ProofError` and `ProofTimeoutError`
  - [ ] `ConversionError`, `InferenceError`
  - [ ] `NLProcessingError`, `PatternMatchError`

- [ ] **Task 1.2:** Fix unsafe error handling - 6h
  - [ ] Remove bare except at `tdfol_prover.py:549`
  - [ ] Narrow Exception catches (8 locations)
  - [ ] Add proper logging
  - [ ] Test error propagation

#### Week 2: Core Tests
- [ ] **Task 1.5:** Test `tdfol_prover.py` (85+ tests) - 16h
  - [ ] Basic proving (20 tests)
  - [ ] Inference rules (30 tests)
  - [ ] Complex proofs (15 tests)
  - [ ] Integration (10 tests)
  - [ ] Edge cases (10 tests)

- [ ] **Task 1.6:** Test `tdfol_parser.py` (85+ tests) - 12h
  - [ ] Lexer tests (20 tests)
  - [ ] Parser tests (40 tests)
  - [ ] Error handling (15 tests)
  - [ ] Edge cases (10 tests)

- [ ] **Task 1.7:** Test `tdfol_converter.py` (60+ tests) - 10h
  - [ ] TDFOL ↔ DCEC (20 tests)
  - [ ] TDFOL → FOL (15 tests)
  - [ ] TDFOL → TPTP (15 tests)
  - [ ] Error handling (10 tests)

#### Week 3: Polish
- [ ] **Task 1.3:** Eliminate duplication - 8h
  - [ ] Generic `_traverse_formula()` helper
  - [ ] Refactor 3 tree traversal methods
  - [ ] Create `nl/spacy_utils.py`
  - [ ] Deduplicate import blocks

- [ ] **Task 1.4:** Improve type hints - 6h
  - [ ] Fix `any` → `Any` typo
  - [ ] Add return types (34% missing)
  - [ ] Run mypy --strict
  - [ ] Target: 90%+ coverage

- [ ] **Task 1.8:** Test `tdfol_inference_rules.py` (40+ tests) - 14h
- [ ] **Task 1.9:** Test `tdfol_dcec_parser.py` (25+ tests) - 8h
- [ ] **Task 1.10:** Complete docstrings - 4h

**Week 3 Output:** Production-ready v1.1

---

### 🚀 Phase 8: Complete Prover (Weeks 4-8)

#### Tasks
- [ ] **8.1:** Add 10 temporal rules - 16h
- [ ] **8.2:** Add 8 deontic rules - 12h
- [ ] **8.3:** Add 10 combined rules - 14h
- [ ] **8.4:** Implement modal tableaux - 24h
- [ ] **8.5:** Proof explanation system - 16h

**Week 8 Output:** Feature-complete v1.2 (60+ rules)

---

### ⚡ Phase 9: Optimization (Weeks 9-12)

#### Tasks
- [ ] **9.1:** Fix O(n³) → O(n² log n) - 12h ⚠️ **CRITICAL**
- [ ] **9.2:** Strategy selection (4 strategies) - 20h
- [ ] **9.3:** Parallel search (2-8 workers) - 24h
- [ ] **9.4:** A* heuristic search - 20h

**Week 12 Output:** High-performance v1.3 (3-5x faster)

---

### 🧪 Phase 10: Testing (Weeks 13-16)

#### Tasks
- [ ] Integration tests (50 tests)
- [ ] Performance tests (20 tests)
- [ ] Property-based tests (30 tests)
- [ ] 90%+ coverage

**Week 16 Output:** Fully tested v1.4

---

### 👁️ Phase 11: Visualization (Weeks 17-19)

#### Tasks
- [ ] ASCII proof trees
- [ ] GraphViz proof trees
- [ ] Formula dependency graphs
- [ ] Interactive HTML

**Week 19 Output:** Visualization-ready v1.5

---

### 🚢 Phase 12: Production (Weeks 20-22)

#### Tasks
- [ ] Performance profiling
- [ ] Security validation
- [ ] Complete documentation
- [ ] Deployment guides

**Week 22 Output:** Production v2.0 🎉

---

## 🔥 Critical Issues (Must Fix)

### 1. Missing Test Coverage (🔴 Blocker)
**Impact:** 75% of core code untested (3,457 LOC)

**Files:**
- `tdfol_prover.py` (777 LOC) - **NO TESTS**
- `tdfol_parser.py` (564 LOC) - **NO TESTS**
- `tdfol_converter.py` (528 LOC) - **NO TESTS**
- `tdfol_inference_rules.py` (1,215 LOC) - **NO TESTS**
- `tdfol_dcec_parser.py` (373 LOC) - **NO TESTS**

**Action:** Complete Track 1 Week 2-3 (40 hours)

---

### 2. O(n³) Performance Bottleneck (🔴 Blocker)
**Impact:** Timeout on >100 formulas

**Location:** `tdfol_prover.py:487-568`

**Problem:**
```python
for iteration in range(max_iterations):  # 100x
    for formula in derived:               # Nx
        for rule in self.rules:           # Mx
            # O(100 × N × M) = O(n³)
```

**Solution:** Indexed KB (Task 9.1, 12 hours)
```python
# O(n² log n) with indexing
applicable_rules = self._get_applicable_rules(current)  # O(log n)
```

**Action:** Week 9 Task 9.1 (highest priority in Phase 9)

---

### 3. Unsafe Error Handling (🔴 Blocker)
**Impact:** Silent failures, hard to debug

**Issues:**
- Bare except: `tdfol_prover.py:549`
- 7× overly broad `except Exception:`
- No custom exception hierarchy

**Action:** Week 1 Tasks 1.1-1.2 (10 hours)

---

## 📊 Metrics Dashboard

### Current vs Target

| Metric | Current | Week 3 | Week 8 | Week 22 | Priority |
|--------|---------|--------|--------|---------|----------|
| **Tests** | 190 | 440 | 560 | 910+ | 🔴 |
| **Coverage** | 55% | 85% | 87% | 90%+ | 🔴 |
| **Rules** | 40 | 40 | 60+ | 60+ | 🔴 |
| **Type Hints** | 66% | 90% | 90% | 95%+ | 🟡 |
| **Performance** | O(n³) | O(n³) | O(n³) | O(n² log n) | 🔴 |
| **Exceptions** | 0 | 7 | 7 | 7 | 🔴 |

### Weekly Goals

**Week 1:** Exceptions + error handling (20h)  
**Week 2:** Prover + parser tests (28h)  
**Week 3:** Converter tests + polish (36h)  
**Week 4-8:** Complete prover (82h)  
**Week 9-12:** Optimization (76h)  
**Week 13-22:** Testing + production (174h)

**Total:** 420 hours (17-22 weeks with 1 FTE)

---

## 🛠️ Quick Commands

### Testing
```bash
# Run all TDFOL tests
pytest tests/unit_tests/logic/TDFOL/ -v

# Run with coverage
pytest tests/unit_tests/logic/TDFOL/ --cov=ipfs_datasets_py.logic.TDFOL --cov-report=html

# Run specific test file
pytest tests/unit_tests/logic/TDFOL/test_tdfol_prover.py -v

# Run parallel (fast)
pytest tests/unit_tests/logic/TDFOL/ -n auto
```

### Type Checking
```bash
# Check type hints
mypy ipfs_datasets_py/logic/TDFOL/ --ignore-missing-imports

# Strict mode
mypy ipfs_datasets_py/logic/TDFOL/ --strict

# Count coverage
mypy ipfs_datasets_py/logic/TDFOL/ --html-report mypy-report/
```

### Code Quality
```bash
# Count LOC
find ipfs_datasets_py/logic/TDFOL -name "*.py" | xargs wc -l

# Find type:ignore
grep -r "type: ignore" ipfs_datasets_py/logic/TDFOL/

# Find bare except
grep -r "except:" ipfs_datasets_py/logic/TDFOL/

# Find TODO/FIXME
grep -r "TODO\|FIXME\|XXX" ipfs_datasets_py/logic/TDFOL/
```

### Performance
```bash
# Profile proof execution
python -m cProfile -o profile.stats scripts/demo/demonstrate_phase5_pipeline.py

# Analyze profile
python -m pstats profile.stats
# Then: sort cumulative, stats 20

# Benchmark
pytest tests/unit_tests/logic/TDFOL/ --benchmark-only
```

---

## 📝 Code Examples

### Custom Exceptions (Task 1.1)

```python
# NEW: ipfs_datasets_py/logic/TDFOL/exceptions.py

class TDFOLError(Exception):
    """Base exception for all TDFOL errors."""
    pass

class ParseError(TDFOLError):
    """Raised when parsing fails."""
    def __init__(self, message: str, position: int, line: int, column: int):
        self.position = position
        self.line = line
        self.column = column
        super().__init__(f"{message} at line {line}, column {column}")

# Usage in tdfol_parser.py:
raise ParseError("Unexpected token", pos, line, col)
```

### Generic Tree Traversal (Task 1.3)

```python
# NEW: Generic helper in tdfol_prover.py

def _traverse_formula(
    formula: Formula,
    predicate: Callable[[Formula], bool],
    depth: int = 0,
    max_depth: Optional[int] = None
) -> bool:
    """Generic formula tree traversal."""
    if max_depth is not None and depth > max_depth:
        return False
    
    if predicate(formula):
        return True
    
    if isinstance(formula, UnaryFormula):
        return _traverse_formula(formula.formula, predicate, depth + 1, max_depth)
    elif isinstance(formula, BinaryFormula):
        return (_traverse_formula(formula.left, predicate, depth + 1, max_depth) or
                _traverse_formula(formula.right, predicate, depth + 1, max_depth))
    # ... (handle all types)
    
    return False

# REFACTORED: Use generic helper
def _has_deontic_operators(self, formula: Formula) -> bool:
    return self._traverse_formula(formula, lambda f: isinstance(f, DeonticFormula))
```

### Indexed Knowledge Base (Task 9.1)

```python
# NEW: ipfs_datasets_py/logic/TDFOL/tdfol_optimization.py

class IndexedKnowledgeBase(TDFOLKnowledgeBase):
    """Knowledge base with indexes for O(log n) lookup."""
    
    def __init__(self):
        super().__init__()
        self._predicate_index: Dict[str, Set[Formula]] = {}
        self._operator_index: Dict[LogicOperator, Set[Formula]] = {}
    
    def get_formulas_with_predicate(self, name: str) -> Set[Formula]:
        """O(1) lookup by predicate name."""
        return self._predicate_index.get(name, set())
```

---

## 🎓 Testing Guidelines

### Test Structure (GIVEN-WHEN-THEN)

```python
def test_forward_chaining_modus_ponens(self):
    """Test forward chaining applies modus ponens."""
    # GIVEN: KB with P and P → Q
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(parse_tdfol("P"))
    kb.add_axiom(parse_tdfol("P -> Q"))
    prover = TDFOLProver(kb)
    
    # WHEN: Prove Q
    goal = parse_tdfol("Q")
    result = prover.prove(goal, max_iterations=10)
    
    # THEN: Q is proved
    assert result.is_proved()
    assert result.method == "forward_chaining"
    assert "modus_ponens" in result.proof_steps[0].rule_name.lower()
```

### Test Categories

1. **Unit Tests:** Individual functions/methods
2. **Integration Tests:** Module interactions
3. **Performance Tests:** Speed and memory
4. **Property Tests:** Invariants (soundness, completeness)
5. **Edge Cases:** Empty inputs, deep nesting, large inputs

### Coverage Targets

- **Critical modules:** 85%+ (prover, parser)
- **Core modules:** 80%+ (converter, rules)
- **Supporting modules:** 75%+ (NL, integration)
- **Overall:** 90%+

---

## 📚 Documentation Standards

### Docstring Format (NumPy Style)

```python
def prove(
    self,
    goal: Formula,
    max_iterations: int = 100,
    timeout: float = 60.0,
    strategy: ProofStrategy = ProofStrategy.AUTO
) -> ProofResult:
    """
    Prove a goal formula using TDFOL inference rules.
    
    This method attempts to prove the goal using the specified strategy.
    It will try multiple approaches: direct lookup, forward chaining,
    backward chaining, and modal tableaux.
    
    Parameters
    ----------
    goal : Formula
        The formula to prove
    max_iterations : int, optional
        Maximum forward chaining iterations (default: 100)
    timeout : float, optional
        Timeout in seconds (default: 60.0)
    strategy : ProofStrategy, optional
        Proof search strategy (default: AUTO)
    
    Returns
    -------
    ProofResult
        Result containing proof status, method, steps, and timing
    
    Raises
    ------
    ProofTimeoutError
        If proof exceeds timeout
    ProofError
        If proof fails due to internal error
    
    Examples
    --------
    >>> kb = TDFOLKnowledgeBase()
    >>> kb.add_axiom(parse_tdfol("P"))
    >>> kb.add_axiom(parse_tdfol("P -> Q"))
    >>> prover = TDFOLProver(kb)
    >>> result = prover.prove(parse_tdfol("Q"))
    >>> assert result.is_proved()
    
    Notes
    -----
    The AUTO strategy automatically selects the best approach based on:
    - Formula structure (depth, operator types)
    - Knowledge base size
    - Previous proof statistics
    
    See Also
    --------
    prove_parallel : Parallel proof search
    TDFOLKnowledgeBase : Knowledge base management
    """
```

### Required Sections

- **Summary:** One-line description
- **Parameters:** All arguments with types
- **Returns:** Return value with type
- **Raises:** All exceptions
- **Examples:** At least one usage example
- **Notes:** Additional details (optional)
- **See Also:** Related functions (optional)

---

## 🔍 Code Review Checklist

Before submitting PR, verify:

### Code Quality
- [ ] All tests pass (`pytest`)
- [ ] Type hints added (`mypy --strict`)
- [ ] Docstrings complete (NumPy style)
- [ ] No bare `except:` clauses
- [ ] Custom exceptions used
- [ ] No code duplication (>5 lines)
- [ ] No type:ignore without comment

### Testing
- [ ] New tests added for new code
- [ ] Edge cases covered
- [ ] Error cases tested
- [ ] Coverage ≥80% for changed files
- [ ] Performance tests (if applicable)

### Documentation
- [ ] CHANGELOG.md updated
- [ ] README.md updated (if API changed)
- [ ] Examples added to docstrings
- [ ] Breaking changes documented

### Performance
- [ ] No obvious O(n²) or worse algorithms
- [ ] Large lists/dicts use appropriate data structures
- [ ] Caching used where appropriate
- [ ] No memory leaks

---

## 🚨 Common Pitfalls

### 1. Bare Except Clauses ❌
```python
# BAD:
try:
    result = some_operation()
except:  # Catches EVERYTHING including KeyboardInterrupt!
    pass

# GOOD:
try:
    result = some_operation()
except (ValueError, KeyError) as e:
    logger.warning(f"Operation failed: {e}")
    raise
```

### 2. Missing Type Hints ❌
```python
# BAD:
def parse_formula(text):
    return do_parsing(text)

# GOOD:
def parse_formula(text: str) -> Formula:
    """Parse TDFOL formula from string."""
    return do_parsing(text)
```

### 3. Code Duplication ❌
```python
# BAD: 3 nearly identical methods
def _has_deontic(formula):
    if isinstance(formula, DeonticFormula): return True
    if isinstance(formula, BinaryFormula):
        return _has_deontic(formula.left) or _has_deontic(formula.right)
    # ... repeat for all types

# GOOD: Generic helper
def _traverse_formula(formula, predicate):
    if predicate(formula): return True
    # ... generic traversal logic
```

### 4. O(n³) Algorithms ❌
```python
# BAD: Nested loops over same collection
for i in items:
    for j in items:
        for k in items:
            # O(n³) - very slow!

# GOOD: Use indexes or filters
for i in items:
    relevant = index.get(i.key)  # O(log n)
    for j in relevant:
        # O(n × m) where m << n
```

---

## 📞 Support & Resources

### Getting Help

**Questions?**
- Open GitHub issue with `tdfol` + `refactoring` labels
- Tag: `@copilot-agent` for AI assistance
- Slack: #tdfol-refactoring channel

**Bug Reports:**
- Label: `bug` + `tdfol`
- Include: Steps to reproduce, expected vs actual behavior
- Attach: Logs, stack traces, minimal repro code

### Key Documents

- **[REFACTORING_PLAN_2026_02_18.md](./REFACTORING_PLAN_2026_02_18.md)** - Complete technical plan (44,938 chars)
- **[REFACTORING_EXECUTIVE_SUMMARY_2026_02_18.md](./REFACTORING_EXECUTIVE_SUMMARY_2026_02_18.md)** - Executive summary (12,213 chars)
- **[QUICK_REFERENCE_2026_02_18.md](./QUICK_REFERENCE_2026_02_18.md)** - This document
- **[README.md](./README.md)** - Module overview
- **[PHASE7_COMPLETION_REPORT.md](./PHASE7_COMPLETION_REPORT.md)** - Phase 7 results

### External Resources

- **TDFOL Theory:** [Stanford Encyclopedia of Philosophy - Deontic Logic](https://plato.stanford.edu/entries/logic-deontic/)
- **Modal Logic:** [Modal Logic for Open Minds](https://johanvanbenthemamsterdamorg/)
- **Testing:** [pytest documentation](https://docs.pytest.org/)
- **Type Hints:** [mypy documentation](https://mypy.readthedocs.io/)

---

## 🎉 Quick Wins (This Week!)

Want to contribute? Start here:

### Easy Tasks (2-4 hours each)

1. **Add docstring examples** (Task 1.10)
   - Pick any public function
   - Add Examples section to docstring
   - Test example works

2. **Fix type hint typo** (Task 1.4)
   - File: `tdfol_nl_generator.py:79`
   - Change: `any` → `Any`
   - Add: `from typing import Any`

3. **Add 5 tests** (Tasks 1.5-1.9)
   - Pick any core module
   - Write 5 unit tests
   - Follow GIVEN-WHEN-THEN format

### Medium Tasks (4-8 hours each)

4. **Create custom exception** (Task 1.1)
   - File: `exceptions.py` (new)
   - Class: `ParseError` with position info
   - Update: `tdfol_parser.py` to use it

5. **Refactor tree traversal** (Task 1.3)
   - Create: Generic `_traverse_formula()` helper
   - Replace: 3 near-identical methods
   - Test: All tests still pass

6. **Add 20 prover tests** (Task 1.5)
   - File: `test_tdfol_prover.py` (new)
   - Category: Basic proving
   - Tests: 20 covering all proof methods

---

**Last Updated:** 2026-02-18  
**Version:** 2.0.0  
**Maintainer:** GitHub Copilot Agent  
**Status:** 🟢 ACTIVE
