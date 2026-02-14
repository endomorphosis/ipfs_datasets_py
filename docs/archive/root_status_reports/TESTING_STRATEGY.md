# Testing Strategy for Logic Module

**Date:** 2026-02-12  
**Status:** Implementation Guide  
**Target Coverage:** 80%+

---

## Executive Summary

This document provides a comprehensive testing strategy for achieving 80%+ code coverage across the logic module while ensuring production quality.

---

## Current State

### Coverage Analysis
```
Current Coverage: 30-40%
Target Coverage: 80%+
Gap: 40-50 percentage points

Current Test Files: 26
Target Test Files: 100+
Gap: 74+ new test files needed
```

### Coverage by Module

| Module | Current | Target | Priority |
|--------|---------|--------|----------|
| TDFOL | 20% | 85% | P0 - CRITICAL |
| Integration | 10% | 80% | P0 - CRITICAL |
| External Provers | 40% | 85% | P0 - HIGH |
| CEC Native | 90% | 95% | P1 - GOOD |
| GraphRAG | 0% | 80% | P1 - NEW |

---

## Testing Pyramid

```
         /\
        /E2E\         5% - End-to-end tests (10 tests)
       /______\
      /        \
     /Integration\    20% - Integration tests (40 tests)
    /____________\
   /              \
  /  Unit Tests    \  75% - Unit tests (150 tests)
 /__________________\
```

### Distribution
- **Unit Tests:** 150+ tests (75%)
- **Integration Tests:** 40+ tests (20%)
- **End-to-End Tests:** 10+ tests (5%)
- **Total:** 200+ tests

---

## Phase 1: Unit Testing (Week 1)

### Priority 1: TDFOL Module

#### test_tdfol_core.py (30 tests)
```python
"""Comprehensive tests for TDFOL core functionality."""

import pytest
from ipfs_datasets_py.logic.TDFOL import *

class TestTerms:
    """Test term construction."""
    
    def test_variable_creation(self):
        """Test creating variables."""
        var = Variable("x", Sort.AGENT)
        assert var.name == "x"
        assert var.sort == Sort.AGENT
    
    def test_constant_creation(self):
        """Test creating constants."""
        const = Constant("Alice", Sort.AGENT)
        assert const.name == "Alice"
    
    def test_function_application(self):
        """Test function application."""
        func = FunctionApplication(
            "owns",
            (Variable("x"), Variable("y"))
        )
        assert func.function_name == "owns"
        assert len(func.arguments) == 2
    
    # ... 27 more term tests

class TestFormulas:
    """Test formula construction."""
    
    def test_predicate(self):
        """Test creating predicates."""
        pred = Predicate("P", (Variable("x"),))
        assert pred.name == "P"
        assert len(pred.terms) == 1
    
    def test_binary_formula(self):
        """Test binary formulas."""
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = BinaryFormula(LogicOperator.IMPLIES, p, q)
        assert impl.operator == LogicOperator.IMPLIES
    
    def test_quantified_formula(self):
        """Test quantified formulas."""
        var = Variable("x", Sort.AGENT)
        pred = Predicate("P", (var,))
        forall = QuantifiedFormula(Quantifier.FORALL, var, pred)
        assert forall.quantifier == Quantifier.FORALL
    
    def test_deontic_formula(self):
        """Test deontic formulas."""
        pred = Predicate("pay", ())
        obl = DeonticFormula(DeonticOperator.OBLIGATION, pred)
        assert obl.operator == DeonticOperator.OBLIGATION
    
    def test_temporal_formula(self):
        """Test temporal formulas."""
        pred = Predicate("P", ())
        always = TemporalFormula(TemporalOperator.ALWAYS, pred)
        assert always.operator == TemporalOperator.ALWAYS
    
    # ... 20 more formula tests

class TestFormulaOperations:
    """Test operations on formulas."""
    
    def test_formula_equality(self):
        """Test formula equality."""
        p1 = Predicate("P", ())
        p2 = Predicate("P", ())
        assert p1 == p2
    
    def test_formula_hashing(self):
        """Test formula can be hashed."""
        p = Predicate("P", ())
        hash_val = hash(p)
        assert isinstance(hash_val, int)
    
    def test_formula_str(self):
        """Test string representation."""
        p = Predicate("P", (Variable("x"),))
        assert "P" in str(p)
        assert "x" in str(p)
    
    # ... 7 more operation tests
```

#### test_tdfol_parser.py (25 tests)
```python
"""Tests for TDFOL parser."""

import pytest
from ipfs_datasets_py.logic.TDFOL import parse_tdfol, TDFOLParser

class TestBasicParsing:
    """Test basic parsing."""
    
    def test_parse_simple_predicate(self):
        """Test parsing 'P'."""
        formula = parse_tdfol("P")
        assert isinstance(formula, Predicate)
        assert formula.name == "P"
    
    def test_parse_predicate_with_args(self):
        """Test parsing 'P(x)'."""
        formula = parse_tdfol("P(x)")
        assert isinstance(formula, Predicate)
        assert len(formula.terms) == 1
    
    def test_parse_implication(self):
        """Test parsing 'P -> Q'."""
        formula = parse_tdfol("P -> Q")
        assert isinstance(formula, BinaryFormula)
        assert formula.operator == LogicOperator.IMPLIES
    
    # ... 10 more basic tests

class TestComplexParsing:
    """Test complex parsing."""
    
    def test_parse_nested_implication(self):
        """Test parsing '(P -> Q) -> R'."""
        formula = parse_tdfol("(P -> Q) -> R")
        assert isinstance(formula, BinaryFormula)
        assert isinstance(formula.left, BinaryFormula)
    
    def test_parse_quantifier(self):
        """Test parsing 'forall x. P(x)'."""
        formula = parse_tdfol("forall x. P(x)")
        assert isinstance(formula, QuantifiedFormula)
        assert formula.quantifier == Quantifier.FORALL
    
    def test_parse_deontic(self):
        """Test parsing 'O(P)'."""
        formula = parse_tdfol("O(P)")
        assert isinstance(formula, DeonticFormula)
        assert formula.operator == DeonticOperator.OBLIGATION
    
    # ... 8 more complex tests

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_parse_empty_string(self):
        """Test parsing empty string raises error."""
        with pytest.raises(ValueError):
            parse_tdfol("")
    
    def test_parse_malformed(self):
        """Test parsing malformed input."""
        with pytest.raises(Exception):
            parse_tdfol("P -> -> Q")
    
    def test_parse_max_depth(self):
        """Test parsing respects max depth."""
        # Create deeply nested formula
        deep = "P"
        for _ in range(200):
            deep = f"({deep} -> P)"
        
        with pytest.raises(ValueError, match="too deep"):
            parse_tdfol(deep)
    
    # ... 4 more edge case tests
```

#### test_tdfol_prover.py (20 tests)
```python
"""Tests for TDFOL prover."""

import pytest
from ipfs_datasets_py.logic.TDFOL import TDFOLProver, parse_tdfol

class TestBasicProving:
    """Test basic proving."""
    
    def test_prove_tautology(self):
        """Test proving P -> P."""
        prover = TDFOLProver()
        formula = parse_tdfol("P -> P")
        result = prover.prove(formula)
        assert result.is_proved()
    
    def test_prove_modus_ponens(self):
        """Test proving with modus ponens."""
        prover = TDFOLProver()
        axioms = [
            parse_tdfol("P"),
            parse_tdfol("P -> Q")
        ]
        goal = parse_tdfol("Q")
        result = prover.prove(goal, axioms=axioms)
        assert result.is_proved()
    
    def test_cannot_prove_invalid(self):
        """Test cannot prove invalid formula."""
        prover = TDFOLProver()
        formula = parse_tdfol("P")  # Without axioms
        result = prover.prove(formula)
        assert not result.is_proved()
    
    # ... 7 more basic tests

class TestInferenceRules:
    """Test specific inference rules."""
    
    def test_conjunction_introduction(self):
        """Test conjunction introduction rule."""
        prover = TDFOLProver()
        axioms = [parse_tdfol("P"), parse_tdfol("Q")]
        goal = parse_tdfol("P & Q")
        result = prover.prove(goal, axioms=axioms)
        assert result.is_proved()
    
    def test_disjunctive_syllogism(self):
        """Test disjunctive syllogism."""
        prover = TDFOLProver()
        axioms = [
            parse_tdfol("P | Q"),
            parse_tdfol("~P")
        ]
        goal = parse_tdfol("Q")
        result = prover.prove(goal, axioms=axioms)
        assert result.is_proved()
    
    # ... 8 more rule tests
```

### Priority 2: Integration Modules (30 tests)

#### test_symbolic_contracts.py (10 tests)
```python
"""Tests for symbolic contracts."""

import pytest
from ipfs_datasets_py.logic.integration import symbolic_contracts

class TestContractCreation:
    """Test creating contracts."""
    
    def test_create_simple_contract(self):
        """Test creating a simple contract."""
        contract = symbolic_contracts.create_contract(
            parties=["Alice", "Bob"],
            obligations=[
                "Alice must pay 100",
                "Bob must deliver goods"
            ]
        )
        assert contract is not None
        assert len(contract.parties) == 2
        assert len(contract.obligations) == 2
    
    # ... 4 more creation tests

class TestContractValidation:
    """Test contract validation."""
    
    def test_validate_consistent_contract(self):
        """Test validating consistent contract."""
        contract = symbolic_contracts.create_contract(...)
        result = symbolic_contracts.validate(contract)
        assert result.is_valid
    
    def test_detect_contradiction(self):
        """Test detecting contradictory terms."""
        contract = symbolic_contracts.create_contract(
            obligations=[
                "Alice must pay",
                "Alice must not pay"
            ]
        )
        result = symbolic_contracts.validate(contract)
        assert not result.is_valid
        assert len(result.errors) > 0
    
    # ... 3 more validation tests
```

### Priority 3: External Provers (20 tests)

#### test_z3_comprehensive.py (10 tests)
#### test_symbolicai_comprehensive.py (10 tests)

---

## Phase 2: Integration Testing (Week 1)

### Integration Test Suite (40 tests)

#### test_tdfol_cec_integration.py (10 tests)
```python
"""Test TDFOL-CEC integration."""

class TestTDFOLCECBridge:
    """Test TDFOL-CEC bridge."""
    
    def test_tdfol_to_dcec_conversion(self):
        """Test converting TDFOL to DCEC."""
        from ipfs_datasets_py.logic.integration import TDFOLCECBridge
        
        bridge = TDFOLCECBridge()
        tdfol_formula = parse_tdfol("P -> Q")
        dcec_formula = bridge.tdfol_to_dcec(tdfol_formula)
        assert dcec_formula is not None
    
    def test_proving_with_both_systems(self):
        """Test proving with TDFOL and CEC."""
        bridge = TDFOLCECBridge()
        formula = parse_tdfol("P -> P")
        
        # Prove with TDFOL
        tdfol_result = bridge.prove_tdfol(formula)
        
        # Prove with CEC
        cec_result = bridge.prove_cec(formula)
        
        # Both should succeed
        assert tdfol_result.is_proved()
        assert cec_result.is_proved()
    
    # ... 8 more integration tests
```

#### test_external_prover_integration.py (10 tests)
#### test_cache_integration.py (10 tests)
#### test_monitoring_integration.py (10 tests)

---

## Phase 3: End-to-End Testing (Week 2)

### E2E Test Suite (10 tests)

#### test_complete_workflow.py (5 tests)
```python
"""End-to-end workflow tests."""

class TestCompleteWorkflow:
    """Test complete neurosymbolic workflows."""
    
    def test_parse_prove_cache_workflow(self):
        """Test: parse → prove → cache → prove again."""
        from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
        
        reasoner = NeurosymbolicReasoner(enable_cache=True)
        
        # Parse
        formula = reasoner.parse("P -> Q")
        
        # Prove (cache miss)
        result1 = reasoner.prove(formula)
        time1 = result1.proof_time
        
        # Prove again (cache hit)
        result2 = reasoner.prove(formula)
        time2 = result2.proof_time
        
        # Verify
        assert result1.is_proved()
        assert result2.is_proved()
        assert time2 < time1 / 10  # At least 10x faster
    
    def test_multi_prover_workflow(self):
        """Test using multiple provers."""
        reasoner = NeurosymbolicReasoner(
            enable_native=True,
            enable_z3=True,
            enable_symbolicai=True
        )
        
        formula = parse_tdfol("P -> P")
        
        # Should try all provers
        result = reasoner.prove(formula, strategy='parallel')
        
        assert result.is_proved()
        assert len(result.all_results) >= 2
    
    # ... 3 more E2E tests
```

#### test_graphrag_workflow.py (5 tests)
```python
"""GraphRAG workflow tests."""

class TestGraphRAGWorkflow:
    """Test GraphRAG integration workflows."""
    
    def test_ingest_query_workflow(self):
        """Test: ingest document → extract entities → query."""
        from ipfs_datasets_py.rag import LogicEnhancedRAG
        
        rag = LogicEnhancedRAG()
        
        # Ingest
        contract = "Alice must pay Bob $100"
        rag.ingest_document(contract, "doc_001")
        
        # Query
        result = rag.query("What are Alice's obligations?")
        
        # Verify
        assert len(result.logical_entities) > 0
        assert "Alice" in str(result)
    
    # ... 4 more GraphRAG tests
```

---

## Performance Testing

### Load Tests
```python
"""Load testing suite."""

class TestLoad:
    """Test system under load."""
    
    @pytest.mark.slow
    def test_100_concurrent_proofs(self):
        """Test 100 concurrent proof requests."""
        import concurrent.futures
        
        reasoner = NeurosymbolicReasoner()
        formula = parse_tdfol("P -> P")
        
        def prove_once():
            return reasoner.prove(formula)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(prove_once) for _ in range(100)]
            results = [f.result() for f in futures]
        
        # All should succeed
        assert all(r.is_proved() for r in results)
    
    @pytest.mark.slow
    def test_sustained_load(self):
        """Test 1000 proofs over 10 minutes."""
        import time
        
        reasoner = NeurosymbolicReasoner()
        start = time.time()
        
        for _ in range(1000):
            reasoner.prove(parse_tdfol("P -> P"))
        
        duration = time.time() - start
        assert duration < 600  # 10 minutes
    
    @pytest.mark.slow
    def test_memory_stability(self):
        """Test memory doesn't leak."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        reasoner = NeurosymbolicReasoner()
        
        # Run 10K proofs
        for _ in range(10000):
            reasoner.prove(parse_tdfol("P -> P"))
        
        final_memory = process.memory_info().rss
        growth = (final_memory - initial_memory) / initial_memory
        
        # Memory growth should be < 20%
        assert growth < 0.2
```

---

## Test Execution Strategy

### Daily Testing
```bash
# Fast tests only (< 1 second each)
pytest -m "not slow" --maxfail=3

# With coverage
pytest -m "not slow" --cov=ipfs_datasets_py.logic --cov-report=html
```

### CI/CD Pipeline
```bash
# Stage 1: Fast tests (5 minutes)
pytest -m "not slow" --maxfail=10

# Stage 2: Integration tests (10 minutes)
pytest -m "integration" --maxfail=5

# Stage 3: Load tests (30 minutes, nightly only)
pytest -m "slow" --maxfail=2
```

### Coverage Tracking
```bash
# Generate coverage report
pytest --cov=ipfs_datasets_py.logic \
       --cov-report=html \
       --cov-report=term-missing \
       --cov-fail-under=80

# Upload to codecov
codecov --token=$CODECOV_TOKEN
```

---

## Success Metrics

### Coverage Targets by Phase

**Phase 1 (Week 1):**
- Unit tests: 150+ tests written
- Coverage: 30% → 55%
- All TDFOL modules >80%

**Phase 2 (Week 1):**
- Integration tests: 40+ tests
- Coverage: 55% → 70%
- All integration modules >50%

**Phase 3 (Week 2):**
- E2E tests: 10+ tests
- Coverage: 70% → 80%
- All critical paths covered

### Quality Gates

**PR Merge Requirements:**
- [ ] All tests passing
- [ ] Coverage ≥ 80% for changed files
- [ ] No new flaky tests
- [ ] Performance within bounds

**Release Requirements:**
- [ ] Overall coverage ≥ 80%
- [ ] All integration tests passing
- [ ] Load tests passing
- [ ] No critical bugs open

---

## Tools & Infrastructure

### Required Tools
```bash
# Install testing dependencies
pip install pytest pytest-cov pytest-parallel pytest-timeout pytest-xdist

# Install performance testing
pip install pytest-benchmark memory_profiler

# Install coverage tools
pip install coverage codecov
```

### Configuration

#### pytest.ini
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    e2e: marks tests as end-to-end tests
    gpu: marks tests requiring GPU
addopts =
    -v
    --strict-markers
    --tb=short
    --disable-warnings
```

#### .coveragerc
```ini
[run]
source = ipfs_datasets_py.logic
omit =
    */tests/*
    */test_*.py
    */__pycache__/*

[report]
precision = 2
show_missing = True
skip_covered = False

[html]
directory = htmlcov
```

---

## Conclusion

This comprehensive testing strategy will achieve:
- ✅ 80%+ code coverage
- ✅ 200+ tests across all layers
- ✅ Confidence in production readiness
- ✅ Continuous quality improvement

**Timeline:** 2 weeks  
**Team:** 1-2 developers  
**Status:** Ready for implementation! 🚀
