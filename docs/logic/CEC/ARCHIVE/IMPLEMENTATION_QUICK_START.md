# CEC Implementation Quick Start Guide

**Date:** 2026-02-18  
**For:** Developers starting work on CEC phases  
**See Also:** [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md)

---

## 🚀 Getting Started

### Prerequisites

```bash
# Python 3.12+ required
python --version  # Should be 3.12+

# Install development dependencies
pip install -e ".[test]"

# Verify installation
python -c "from ipfs_datasets_py.logic.CEC.native import DCECContainer; print('✓ CEC imported')"
```

### Run Existing Tests

```bash
# Run all CEC tests
pytest tests/unit_tests/logic/CEC/ -v

# Run specific test file
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py -v

# Run with coverage
pytest tests/unit_tests/logic/CEC/ --cov=ipfs_datasets_py.logic.CEC --cov-report=html

# View coverage report
open htmlcov/index.html  # On macOS
xdg-open htmlcov/index.html  # On Linux
```

### Code Quality Checks

```bash
# Type checking (should have zero errors)
mypy ipfs_datasets_py/logic/CEC/native/

# Specific file
mypy ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Linting
flake8 ipfs_datasets_py/logic/CEC/native/
```

---

## 📋 Current Phase: Phase 3 - Test Enhancement

**Start Date:** Week 4  
**Duration:** 2 weeks  
**Goal:** 418 tests → 550+ tests, 80% → 85% coverage

### Week 4 Tasks (Choose One)

#### Option A: DCEC Core Tests (30 tests)
**File:** `tests/unit_tests/logic/CEC/native/test_dcec_core.py`

```python
# Example new test to add
def test_complex_nested_deontic_operators():
    """
    GIVEN a DCECContainer with nested deontic operators
    WHEN creating O(agent, P(agent2, F(agent3, action)))
    THEN the formula should be properly validated and structured
    """
    container = DCECContainer()
    # Test implementation...
```

**Tasks:**
- [ ] Add 10 tests for advanced formula validation
- [ ] Add 8 tests for complex nested operators
- [ ] Add 6 tests for edge cases in deontic operators
- [ ] Add 6 tests for cognitive operator interactions

#### Option B: Theorem Prover Tests (25 tests)
**File:** `tests/unit_tests/logic/CEC/native/test_prover.py`

```python
# Example new test to add
def test_complex_multi_step_proof_with_caching():
    """
    GIVEN a prover with proof caching enabled
    WHEN proving a complex 10-step theorem twice
    THEN the second proof should use cached results (100x faster)
    """
    prover = TheoremProver(enable_cache=True)
    # Test implementation...
```

**Tasks:**
- [ ] Add 10 tests for complex proof scenarios
- [ ] Add 8 tests for proof caching validation
- [ ] Add 7 tests for strategy selection

#### Option C: NL Converter Tests (20 tests)
**File:** `tests/unit_tests/logic/CEC/native/test_nl_converter.py`

```python
# Example new test to add
def test_ambiguous_sentence_conversion_with_context():
    """
    GIVEN an NL converter with context tracking
    WHEN converting an ambiguous sentence
    THEN the converter should use context to resolve ambiguity
    """
    converter = NLConverter()
    # Test implementation...
```

**Tasks:**
- [ ] Add 12 tests for new conversion patterns
- [ ] Add 8 tests for ambiguity handling

### Week 5 Tasks (Choose One)

#### Option D: Integration Tests (30 tests)
**File:** `tests/unit_tests/logic/CEC/test_integration.py` (new file)

```python
# Example integration test
def test_end_to_end_nl_to_proof():
    """
    GIVEN a natural language sentence
    WHEN converting to DCEC and proving a conjecture
    THEN the complete pipeline should work end-to-end
    """
    # NL → DCEC → Prove
    sentence = "John must close the door"
    # Test implementation...
```

**Tasks:**
- [ ] Add 15 end-to-end conversion tests
- [ ] Add 10 multi-component integration tests
- [ ] Add 5 wrapper integration tests

#### Option E: Performance Benchmarks (15 tests)
**Directory:** `tests/performance/logic/CEC/` (new directory)

```python
# Example benchmark test
@pytest.mark.benchmark
def test_formula_creation_performance(benchmark):
    """Benchmark formula creation speed"""
    result = benchmark(create_formula, "O(john, close_door)")
    assert result.time_ms < 0.05  # Should be <50 microseconds
```

**Tasks:**
- [ ] Create benchmark suite structure
- [ ] Add 5 formula creation benchmarks
- [ ] Add 5 theorem proving benchmarks
- [ ] Add 5 NL conversion benchmarks

---

## 📝 Test Writing Guidelines

### Follow GIVEN-WHEN-THEN Format

All tests MUST follow this format (see `docs/_example_test_format.md`):

```python
def test_descriptive_name():
    """
    GIVEN initial conditions and setup
    WHEN action or operation is performed
    THEN expected outcome should occur
    """
    # GIVEN
    container = DCECContainer()
    agent = container.create_agent("john")
    
    # WHEN
    formula = container.create_obligation(agent, "close_door")
    
    # THEN
    assert formula.is_valid()
    assert formula.operator == "O"
    assert formula.agent == agent
```

### Test Naming Convention

- `test_<component>_<scenario>_<expected_outcome>`
- Examples:
  - `test_dcec_core_nested_operators_validates_correctly`
  - `test_prover_complex_proof_returns_proof_tree`
  - `test_nl_converter_ambiguous_sentence_uses_context`

### Use Type Hints

```python
from typing import List, Optional
from ipfs_datasets_py.logic.CEC.native import DCECContainer, Formula

def test_type_annotated() -> None:
    container: DCECContainer = DCECContainer()
    formulas: List[Formula] = container.get_all_formulas()
    assert len(formulas) == 0
```

### Add Docstrings

Every test function needs a docstring with GIVEN-WHEN-THEN:

```python
def test_example():
    """
    GIVEN a DCECContainer with 5 formulas
    WHEN querying for formulas with operator 'O'
    THEN exactly 2 obligation formulas should be returned
    """
    pass
```

---

## 🔧 Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/phase3-dcec-core-tests
```

### 2. Write Tests (TDD Approach)

```bash
# 1. Write failing test
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py::test_new_feature -v

# 2. Implement feature
vim ipfs_datasets_py/logic/CEC/native/dcec_core.py

# 3. Test passes
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py::test_new_feature -v

# 4. Refactor and verify
pytest tests/unit_tests/logic/CEC/native/test_dcec_core.py -v
```

### 3. Run Quality Checks

```bash
# Type checking
mypy ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Linting
flake8 ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Coverage
pytest tests/unit_tests/logic/CEC/ --cov=ipfs_datasets_py.logic.CEC --cov-report=term-missing
```

### 4. Commit Changes

```bash
# Stage changes
git add tests/unit_tests/logic/CEC/native/test_dcec_core.py
git add ipfs_datasets_py/logic/CEC/native/dcec_core.py

# Commit with descriptive message
git commit -m "Add 10 tests for advanced formula validation in DCEC core"

# Push to remote
git push origin feature/phase3-dcec-core-tests
```

### 5. Create Pull Request

- Use PR template
- Link to issue/plan
- Add tests and coverage info
- Request review

---

## 📚 Code Examples

### Example 1: Testing DCEC Core

```python
def test_nested_deontic_operators_with_multiple_agents():
    """
    GIVEN a DCECContainer
    WHEN creating O(john, P(mary, close_door))
    THEN nested deontic operators should be properly represented
    """
    # GIVEN
    container = DCECContainer()
    john = container.create_agent("john")
    mary = container.create_agent("mary")
    action = container.create_action("close_door")
    
    # WHEN
    inner = container.create_permission(mary, action)
    outer = container.create_obligation(john, inner)
    
    # THEN
    assert outer.operator == "O"
    assert outer.agent == john
    assert outer.inner_formula.operator == "P"
    assert outer.inner_formula.agent == mary
```

### Example 2: Testing Theorem Prover

```python
def test_proof_caching_provides_100x_speedup():
    """
    GIVEN a prover with caching enabled
    WHEN proving the same theorem twice
    THEN the second proof should be at least 100x faster
    """
    # GIVEN
    prover = TheoremProver(enable_cache=True)
    axioms = ["A → B", "A"]
    conjecture = "B"
    
    # WHEN - First proof
    import time
    start1 = time.time()
    result1 = prover.prove(conjecture, axioms)
    time1 = time.time() - start1
    
    # WHEN - Second proof (cached)
    start2 = time.time()
    result2 = prover.prove(conjecture, axioms)
    time2 = time.time() - start2
    
    # THEN
    assert result1.success
    assert result2.success
    assert time1 / time2 >= 100  # At least 100x faster
```

### Example 3: Testing NL Converter

```python
def test_nl_converter_handles_complex_sentence():
    """
    GIVEN an NL converter
    WHEN converting "John believes Mary must close the door"
    THEN it should create B(john, O(mary, close_door))
    """
    # GIVEN
    converter = NLConverter()
    
    # WHEN
    sentence = "John believes Mary must close the door"
    formula = converter.convert(sentence)
    
    # THEN
    assert formula.operator == "B"
    assert formula.agent.name == "john"
    assert formula.inner_formula.operator == "O"
    assert formula.inner_formula.agent.name == "mary"
    assert formula.inner_formula.action == "close_door"
```

---

## 🎯 Phase-Specific Quick Links

### Phase 3: Test Enhancement (Current)
- **Goal:** 418 → 550+ tests
- **Files:** `tests/unit_tests/logic/CEC/native/test_*.py`
- **Duration:** 2 weeks
- **Focus:** Core, prover, NL converter, integration, performance

### Phase 4: Native Completion (Next)
- **Goal:** 81% → 95% coverage
- **Files:** `ipfs_datasets_py/logic/CEC/native/*.py`
- **Duration:** 4-6 weeks
- **Focus:** DCEC core, prover enhancement, NL completion

### Phase 5: NL Enhancement
- **Goal:** 4 languages (en, es, fr, de)
- **Files:** `ipfs_datasets_py/logic/CEC/native/nl_*.py`
- **Duration:** 4-5 weeks
- **Focus:** Multi-language, domain vocabularies

### Phase 6: Prover Integration
- **Goal:** 7 total provers
- **Files:** `ipfs_datasets_py/logic/CEC/provers/*.py`
- **Duration:** 3-4 weeks
- **Focus:** Z3, Vampire, E, Isabelle integration

### Phase 7: Performance
- **Goal:** 5-10x improvement
- **Files:** All files (optimization)
- **Duration:** 3-4 weeks
- **Focus:** Profiling, caching, algorithms

### Phase 8: API Interface
- **Goal:** 30+ REST endpoints
- **Files:** `ipfs_datasets_py/logic/CEC/api/*.py`
- **Duration:** 4-5 weeks
- **Focus:** FastAPI, authentication, deployment

---

## 🐛 Common Issues & Solutions

### Issue 1: Import Errors

```bash
# Error: ModuleNotFoundError: No module named 'ipfs_datasets_py'
# Solution: Install in development mode
pip install -e .
```

### Issue 2: Type Checking Errors

```bash
# Error: Incompatible types in assignment
# Solution: Add type hints or use type: ignore
from typing import Optional
value: Optional[str] = None
```

### Issue 3: Test Discovery Issues

```bash
# Error: Tests not found
# Solution: Ensure __init__.py exists in test directories
touch tests/unit_tests/logic/CEC/__init__.py
touch tests/unit_tests/logic/CEC/native/__init__.py
```

### Issue 4: Coverage Not Working

```bash
# Error: No coverage data
# Solution: Install pytest-cov
pip install pytest-cov

# Run with coverage
pytest --cov=ipfs_datasets_py.logic.CEC tests/unit_tests/logic/CEC/
```

---

## 📞 Getting Help

### Documentation
- **Main Plan:** [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md)
- **Status:** [STATUS.md](./STATUS.md)
- **API Reference:** [API_REFERENCE.md](./API_REFERENCE.md)
- **System Guide:** [CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)

### Communication
- **GitHub Issues:** Bug reports, feature requests
- **GitHub Discussions:** Questions, design discussions
- **Pull Requests:** Code reviews

### Code Review
- All PRs require review
- Follow test format guidelines
- Maintain type hints and docstrings
- Ensure tests pass before submitting

---

## ✅ Quick Checklist

Before starting work:
- [ ] Python 3.12+ installed
- [ ] Development dependencies installed (`pip install -e ".[test]"`)
- [ ] Can import CEC (`from ipfs_datasets_py.logic.CEC.native import DCECContainer`)
- [ ] Tests run successfully (`pytest tests/unit_tests/logic/CEC/`)
- [ ] Type checking works (`mypy ipfs_datasets_py/logic/CEC/native/`)

Before committing:
- [ ] All tests pass
- [ ] Type checking passes (zero errors)
- [ ] Linting passes
- [ ] Coverage maintained or improved
- [ ] Docstrings added (GIVEN-WHEN-THEN)
- [ ] Code follows existing patterns

Before PR:
- [ ] Feature branch created
- [ ] Commits are atomic and well-described
- [ ] PR description explains changes
- [ ] Tests added for new features
- [ ] Documentation updated if needed

---

**Ready to start? Pick a task from Phase 3 and begin!**

See [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md) for complete details.
