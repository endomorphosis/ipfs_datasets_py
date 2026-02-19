# TDFOL Implementation Quick Start Guide

**Version:** 2.0  
**Last Updated:** 2026-02-18  
**Target Audience:** Developers implementing TDFOL enhancements

---

## Quick Navigation

- **Status:** [STATUS_2026.md](./STATUS_2026.md) - Current implementation status
- **Roadmap:** [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md) - Master plan
- **API Reference:** [QUICK_REFERENCE_2026_02_18.md](./QUICK_REFERENCE_2026_02_18.md) - API docs
- **Main Docs:** [README.md](./README.md) - Getting started

---

## Getting Started

### Prerequisites

```bash
# Python 3.12+ required
python --version  # Should be 3.12+

# Install TDFOL with all dependencies
pip install -e ".[all]"

# Or install specific features
pip install -e ".[test]"     # Testing dependencies
pip install -e ".[tdfol]"    # TDFOL core
```

### Running Tests

```bash
# Run all TDFOL tests
pytest tests/unit_tests/logic/TDFOL/ -v

# Run specific test file
pytest tests/unit_tests/logic/TDFOL/test_tdfol_prover.py -v

# Run with coverage
pytest tests/unit_tests/logic/TDFOL/ --cov=ipfs_datasets_py.logic.TDFOL --cov-report=html

# Run parallel (fast)
pytest tests/unit_tests/logic/TDFOL/ -n auto
```

### Project Structure

```
ipfs_datasets_py/logic/TDFOL/
├── Core Modules (Must Read)
│   ├── tdfol_core.py                   # Data structures - START HERE
│   ├── tdfol_parser.py                 # String parsing
│   ├── tdfol_prover.py                 # Theorem prover
│   └── exceptions.py                   # Error handling
│
├── Advanced Features
│   ├── tdfol_inference_rules.py        # 50+ inference rules
│   ├── tdfol_optimization.py           # Optimization strategies
│   ├── modal_tableaux.py               # Modal logic
│   └── proof_explainer.py              # Explanations
│
├── Natural Language
│   └── nl/                             # NL processing (20+ patterns)
│
├── Visualization
│   ├── proof_tree_visualizer.py        # Proof trees
│   ├── formula_dependency_graph.py     # Dependency graphs
│   └── performance_dashboard.py        # Performance monitoring
│
└── Documentation
    ├── README.md                       # Main docs
    ├── STATUS_2026.md                  # Current status
    ├── UNIFIED_REFACTORING_ROADMAP_2026.md  # Master plan
    └── ... (28 more MD files)
```

---

## Development Workflow

### 1. Choose a Phase/Task

**Completed (Reference Only):**
- ✅ Phases 1-12 (All complete)

**Available for Implementation:**
- 📋 Phase 13: REST API Interface (2-3 weeks)
- 📋 Phase 14: Multi-Language NL Support (4-6 weeks)
- 📋 Phase 15: External ATP Integration (3-4 weeks)
- 📋 Phase 16: GraphRAG Deep Integration (4-5 weeks)
- 📋 Phase 17: Performance & Scalability (2-3 weeks)

### 2. Read Relevant Documentation

**Before starting any phase, read:**
1. [STATUS_2026.md](./STATUS_2026.md) - Understand current state
2. [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md) - Find your phase
3. Existing code in similar modules
4. Related test files

### 3. Follow the Standard Pattern

**All new code should follow:**

#### File Structure Pattern
```python
"""
Module: <module_name>

Brief description of what this module does.

This module is part of Phase <N>: <Phase Name>

Example:
    >>> from ipfs_datasets_py.logic.TDFOL import <ClassName>
    >>> obj = <ClassName>()
    >>> result = obj.method()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from .tdfol_core import Formula, TDFOLKnowledgeBase
from .exceptions import TDFOLError


@dataclass(frozen=True)
class YourClass:
    """
    Brief description of class.
    
    Detailed description with use cases.
    
    Attributes:
        field1: Description of field1
        field2: Description of field2
    
    Example:
        >>> obj = YourClass(field1="value", field2=42)
        >>> result = obj.method()
        >>> print(result)
        Expected output
    """
    field1: str
    field2: int
    
    def method(self) -> str:
        """
        Brief description of method.
        
        Detailed description of what it does, algorithm, complexity.
        
        Args:
            None (uses self.field1, self.field2)
        
        Returns:
            str: Description of return value
        
        Raises:
            TDFOLError: When something goes wrong
        
        Example:
            >>> obj = YourClass(field1="test", field2=10)
            >>> result = obj.method()
            >>> print(result)
            "test: 10"
        
        Note:
            - Important note 1
            - Important note 2
        """
        # Implementation with clear comments for complex logic
        result = f"{self.field1}: {self.field2}"
        return result
```

#### Test Structure Pattern
```python
"""
Tests for <module_name>

This module tests Phase <N>: <Phase Name>
Test count: <N> tests
Coverage: ~<X>%
"""

import pytest
from ipfs_datasets_py.logic.TDFOL import <YourClass>
from ipfs_datasets_py.logic.TDFOL.exceptions import <YourError>


class TestYourClass:
    """Tests for YourClass functionality"""
    
    def test_method_basic_functionality(self):
        """
        GIVEN: A YourClass instance with valid fields
        WHEN: Calling method()
        THEN: Returns expected formatted string
        """
        # Arrange (GIVEN)
        obj = YourClass(field1="test", field2=10)
        
        # Act (WHEN)
        result = obj.method()
        
        # Assert (THEN)
        assert result == "test: 10"
        assert isinstance(result, str)
    
    def test_method_edge_case_empty_string(self):
        """
        GIVEN: A YourClass instance with empty field1
        WHEN: Calling method()
        THEN: Returns formatted string with empty prefix
        """
        # Arrange
        obj = YourClass(field1="", field2=10)
        
        # Act
        result = obj.method()
        
        # Assert
        assert result == ": 10"
    
    def test_method_error_handling(self):
        """
        GIVEN: A YourClass instance with invalid data
        WHEN: Calling method() that triggers error
        THEN: Raises appropriate TDFOLError
        """
        # Arrange
        obj = YourClass(field1="test", field2=-1)  # Invalid
        
        # Act & Assert
        with pytest.raises(TDFOLError, match="Invalid field2"):
            obj.method_that_validates()
```

---

## Implementation Guidelines

### Code Style

**General Rules:**
1. ✅ Python 3.12+ with modern type hints
2. ✅ Use frozen dataclasses for immutable data
3. ✅ Use descriptive variable names
4. ✅ Keep functions <50 lines (split if longer)
5. ✅ Use helper functions for complex logic
6. ✅ Add docstrings to ALL public APIs
7. ✅ Follow existing patterns in the codebase

**Type Hints:**
```python
# Good ✅
def prove(
    formula: Formula,
    kb: TDFOLKnowledgeBase,
    timeout: float = 10.0
) -> Optional[Proof]:
    ...

# Bad ❌
def prove(formula, kb, timeout=10.0):
    ...
```

**Docstrings:**
```python
# Good ✅
def parse(text: str) -> Formula:
    """
    Parse TDFOL formula from string.
    
    Supports both symbolic (∀∃∧∨) and ASCII (forall exists and or) notation.
    
    Args:
        text: Formula string to parse
    
    Returns:
        Formula: Parsed TDFOL formula
    
    Raises:
        ParseError: If text is malformed
    
    Example:
        >>> formula = parse("∀x.(P(x) → Q(x))")
        >>> print(formula)
        ∀x.(P(x) → Q(x))
    """
    ...

# Bad ❌
def parse(text: str) -> Formula:
    """Parse formula"""
    ...
```

**Error Handling:**
```python
# Good ✅
try:
    result = risky_operation()
except SpecificError as e:
    raise TDFOLError(f"Failed to perform operation: {e}") from e

# Bad ❌
try:
    result = risky_operation()
except:
    pass
```

### Testing Guidelines

**Test Coverage Requirements:**
- New code must have ≥90% test coverage
- All public APIs must have tests
- All error paths must have tests
- Edge cases must be tested

**Test Structure:**
```python
# Good ✅ - GIVEN-WHEN-THEN format
def test_prove_with_valid_formula(self):
    """
    GIVEN: A valid formula and knowledge base
    WHEN: Calling prove()
    THEN: Returns a valid proof
    """
    # Arrange (GIVEN)
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(parse("P(a)"))
    kb.add_axiom(parse("∀x.(P(x) → Q(x))"))
    formula = parse("Q(a)")
    
    # Act (WHEN)
    proof = prove(formula, kb)
    
    # Assert (THEN)
    assert proof is not None
    assert proof.conclusion == formula
    assert len(proof.steps) >= 2

# Bad ❌ - No structure
def test_prove(self):
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(parse("P(a)"))
    assert prove(parse("Q(a)"), kb) is not None
```

**Test Organization:**
- Group related tests in classes
- Use descriptive test names
- Test one thing per test
- Use fixtures for common setup
- Parametrize similar tests

### Performance Guidelines

**Optimization Priorities:**
1. ✅ Correctness first
2. ✅ Readability second
3. ✅ Performance third

**When to Optimize:**
- Profile first (use `performance_profiler.py`)
- Optimize hot paths only
- Measure before and after
- Document optimization decisions

**Common Optimizations:**
```python
# Caching
from functools import lru_cache

@lru_cache(maxsize=1000)
def expensive_computation(x: int) -> int:
    ...

# Indexing
class IndexedKnowledgeBase:
    def __init__(self):
        self._predicate_index: Dict[str, List[Formula]] = {}
    
    def get_by_predicate(self, pred_name: str) -> List[Formula]:
        return self._predicate_index.get(pred_name, [])

# Lazy evaluation
@property
def expensive_property(self) -> ComplexType:
    if not hasattr(self, '_cached_property'):
        self._cached_property = compute_expensive_thing()
    return self._cached_property
```

---

## Common Implementation Patterns

### Pattern 1: Parser Extension

**Use Case:** Adding new syntax or language support

**Steps:**
1. Extend lexer with new tokens (in `tdfol_parser.py` or new file)
2. Add parsing rules
3. Update AST generation
4. Add tests (20+ tests)

**Example: Adding Spanish Keywords**
```python
# nl/es/tdfol_nl_patterns_es.py

SPANISH_PATTERNS = [
    Pattern(
        pattern="todos? (?P<var>\w+) deben? (?P<action>.+)",
        template="∀{var}.({var_type}({var}) → O({action}))",
        examples=["todos los doctores deben respetar la privacidad"],
    ),
    # ... 19 more patterns
]

def parse_spanish(text: str) -> Formula:
    """Parse Spanish legal text to TDFOL"""
    for pattern in SPANISH_PATTERNS:
        match = pattern.match(text)
        if match:
            return pattern.to_formula(match)
    raise ParseError(f"No pattern matched: {text}")
```

### Pattern 2: ATP Integration

**Use Case:** Adding external theorem prover

**Steps:**
1. Create adapter in `atps/` directory
2. Implement conversion (TDFOL → ATP format)
3. Implement result parsing (ATP → TDFOL proof)
4. Add fallback mechanism
5. Add tests (50+ tests)

**Example: Z3 Adapter**
```python
# atps/z3_adapter.py

from z3 import *
from ..tdfol_core import Formula, Proof
from ..tdfol_converter import TDFOLToSMTConverter

class Z3Adapter:
    """Adapter for Z3 SMT solver"""
    
    def prove(self, formula: Formula, kb: TDFOLKnowledgeBase) -> Optional[Proof]:
        """
        Prove formula using Z3.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base with axioms
        
        Returns:
            Proof if valid, None otherwise
        """
        # Convert TDFOL to SMT-LIB
        converter = TDFOLToSMTConverter()
        smt_formula = converter.convert(formula)
        smt_axioms = [converter.convert(ax) for ax in kb.axioms]
        
        # Create Z3 solver
        solver = Solver()
        solver.add(smt_axioms)
        solver.add(Not(smt_formula))  # Prove by contradiction
        
        # Check satisfiability
        result = solver.check()
        
        if result == unsat:
            # Valid! Extract proof
            return self._extract_proof(solver.proof())
        else:
            return None
```

### Pattern 3: Visualization Tool

**Use Case:** Adding new visualization

**Steps:**
1. Create visualizer class in main directory
2. Implement ASCII rendering (for CLI)
3. Implement GraphViz export (for static images)
4. Implement interactive HTML (for web)
5. Add tests (30+ tests)

**Example: Proof Tree Visualizer**
```python
# proof_tree_visualizer.py

class ProofTreeVisualizer:
    """Visualize proof trees in multiple formats"""
    
    def visualize_ascii(self, proof: Proof) -> str:
        """Render proof tree as ASCII art"""
        ...
    
    def export_graphviz(self, proof: Proof, output_path: str) -> None:
        """Export proof tree as PNG/SVG via GraphViz"""
        ...
    
    def interactive_html(self, proof: Proof, output_path: str) -> None:
        """Create interactive HTML visualization"""
        ...
```

---

## Phase-Specific Guides

### Phase 13: REST API Interface

**Quick Start:**
```bash
cd ipfs_datasets_py/logic/TDFOL
mkdir -p api/routers api/models api/middleware
touch api/main.py api/__init__.py
```

**Key Files to Create:**
- `api/main.py` - FastAPI app
- `api/routers/parsing.py` - Parsing endpoints
- `api/routers/proving.py` - Proving endpoints
- `api/routers/conversion.py` - Conversion endpoints
- `api/routers/visualization.py` - Visualization endpoints
- `api/models/requests.py` - Request models
- `api/models/responses.py` - Response models
- `api/middleware/auth.py` - Authentication
- `api/middleware/rate_limiting.py` - Rate limiting

**Testing:**
```bash
# Install FastAPI dependencies
pip install fastapi uvicorn httpx pytest-asyncio

# Run server
uvicorn ipfs_datasets_py.logic.TDFOL.api.main:app --reload

# Run tests
pytest tests/unit_tests/logic/TDFOL/api/ -v
```

### Phase 14: Multi-Language NL Support

**Quick Start:**
```bash
cd ipfs_datasets_py/logic/TDFOL/nl
mkdir -p es fr de domains
touch es/__init__.py fr/__init__.py de/__init__.py domains/__init__.py
```

**Key Files to Create:**
- `nl/es/tdfol_nl_patterns_es.py` - Spanish patterns (20+)
- `nl/es/tdfol_nl_generator_es.py` - Spanish generation
- `nl/fr/tdfol_nl_patterns_fr.py` - French patterns (20+)
- `nl/fr/tdfol_nl_generator_fr.py` - French generation
- `nl/de/tdfol_nl_patterns_de.py` - German patterns (20+)
- `nl/de/tdfol_nl_generator_de.py` - German generation
- `nl/domains/medical_patterns.py` - Medical domain
- `nl/domains/financial_patterns.py` - Financial domain
- `nl/domains/regulatory_patterns.py` - Regulatory domain

**Testing:**
```bash
# Install language dependencies
pip install spacy
python -m spacy download es_core_news_sm
python -m spacy download fr_core_news_sm
python -m spacy download de_core_news_sm

# Run tests
pytest tests/unit_tests/logic/TDFOL/nl/ -v
```

### Phase 15: External ATP Integration

**Quick Start:**
```bash
cd ipfs_datasets_py/logic/TDFOL
mkdir -p atps
touch atps/__init__.py atps/z3_adapter.py atps/vampire_adapter.py atps/e_prover_adapter.py
```

**Key Files to Create:**
- `atps/z3_adapter.py` - Z3 SMT solver integration
- `atps/vampire_adapter.py` - Vampire ATP integration
- `atps/e_prover_adapter.py` - E prover integration
- `atps/atp_coordinator.py` - Unified interface

**Testing:**
```bash
# Install ATP dependencies
pip install z3-solver
# For Vampire/E, install binaries separately

# Run tests
pytest tests/unit_tests/logic/TDFOL/atps/ -v
```

### Phase 16: GraphRAG Deep Integration

**Quick Start:**
```bash
cd ipfs_datasets_py/logic/TDFOL
mkdir -p graphrag_integration
touch graphrag_integration/__init__.py graphrag_integration/logic_aware_kg.py
```

**Key Files to Create:**
- `graphrag_integration/logic_aware_kg.py` - Logic-aware knowledge graphs
- `graphrag_integration/theorem_rag.py` - Theorem-augmented RAG
- `graphrag_integration/hybrid_reasoning.py` - Neural-symbolic hybrid

**Testing:**
```bash
# Install GraphRAG dependencies
pip install networkx sentence-transformers faiss-cpu

# Run tests
pytest tests/unit_tests/logic/TDFOL/graphrag_integration/ -v
```

### Phase 17: Performance & Scalability

**Quick Start:**
```bash
cd ipfs_datasets_py/logic/TDFOL
mkdir -p acceleration distributed
touch acceleration/__init__.py acceleration/gpu_prover.py
touch distributed/__init__.py distributed/distributed_prover.py
```

**Key Files to Create:**
- `acceleration/gpu_prover.py` - GPU-accelerated proving
- `distributed/distributed_prover.py` - Distributed proving

**Testing:**
```bash
# Install acceleration dependencies
pip install cupy-cuda12x  # For GPU
pip install ray  # For distributed

# Run tests (requires GPU)
pytest tests/unit_tests/logic/TDFOL/acceleration/ -v -m gpu

# Run tests (requires Ray cluster)
pytest tests/unit_tests/logic/TDFOL/distributed/ -v
```

---

## Troubleshooting

### Common Issues

**Issue: Import errors**
```bash
# Solution: Install in development mode
pip install -e .

# Or with specific extras
pip install -e ".[test,tdfol]"
```

**Issue: Tests failing**
```bash
# Solution: Check test dependencies
pip install pytest pytest-cov pytest-timeout pytest-asyncio

# Run with verbose output
pytest tests/unit_tests/logic/TDFOL/ -vv
```

**Issue: Type checking errors**
```bash
# Solution: Install mypy and fix errors
pip install mypy
mypy ipfs_datasets_py/logic/TDFOL/ --ignore-missing-imports

# Common fixes:
# - Add type hints to function signatures
# - Use Optional[T] for nullable types
# - Use List[T], Dict[K, V] for collections
```

**Issue: Documentation not rendering**
```bash
# Solution: Use proper docstring format
# Follow examples in tdfol_core.py
# Include Args, Returns, Raises, Example sections
```

### Getting Help

1. **Read existing code** in similar modules
2. **Check test files** for usage examples
3. **Review documentation** in MD files
4. **Ask in GitHub issues** if stuck
5. **Check repository memories** for context

---

## Checklist for New Features

**Before starting:**
- [ ] Read [STATUS_2026.md](./STATUS_2026.md)
- [ ] Read relevant phase in [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md)
- [ ] Review similar existing code
- [ ] Check for related tests

**During development:**
- [ ] Follow code style guidelines
- [ ] Add type hints to all functions
- [ ] Write comprehensive docstrings
- [ ] Write tests first (TDD)
- [ ] Keep functions small (<50 lines)
- [ ] Use descriptive variable names
- [ ] Handle errors gracefully
- [ ] Add examples in docstrings

**Before submitting:**
- [ ] All tests pass (`pytest`)
- [ ] Type checking passes (`mypy`)
- [ ] Coverage ≥90% for new code
- [ ] All public APIs documented
- [ ] Examples work correctly
- [ ] No regressions in existing tests
- [ ] Update relevant MD documentation

---

## Quick Commands Reference

```bash
# Development
pip install -e ".[all]"                    # Install with all features
pip install -e ".[test]"                   # Install for testing

# Testing
pytest tests/unit_tests/logic/TDFOL/      # Run all tests
pytest -v -s                               # Verbose with print statements
pytest -k "test_prove"                     # Run tests matching pattern
pytest --cov=ipfs_datasets_py.logic.TDFOL  # With coverage
pytest -n auto                             # Parallel execution

# Code Quality
mypy ipfs_datasets_py/logic/TDFOL/         # Type checking
flake8 ipfs_datasets_py/logic/TDFOL/       # Linting
black ipfs_datasets_py/logic/TDFOL/        # Formatting

# Profiling
python -m cProfile -o profile.stats script.py  # Profile script
python -m pstats profile.stats                 # View results

# Documentation
pydoc ipfs_datasets_py.logic.TDFOL.tdfol_core  # View docs
```

---

## Resources

**Code:**
- Repository: https://github.com/endomorphosis/ipfs_datasets_py
- Module: `ipfs_datasets_py/logic/TDFOL/`
- Tests: `tests/unit_tests/logic/TDFOL/`

**Documentation:**
- [STATUS_2026.md](./STATUS_2026.md) - Current status
- [UNIFIED_REFACTORING_ROADMAP_2026.md](./UNIFIED_REFACTORING_ROADMAP_2026.md) - Master plan
- [README.md](./README.md) - Getting started
- [QUICK_REFERENCE_2026_02_18.md](./QUICK_REFERENCE_2026_02_18.md) - API reference

**External:**
- Python 3.12 docs: https://docs.python.org/3.12/
- Type hints: https://docs.python.org/3/library/typing.html
- pytest: https://docs.pytest.org/
- FastAPI: https://fastapi.tiangolo.com/ (Phase 13)
- spaCy: https://spacy.io/ (NL processing)

---

**Last Updated:** 2026-02-18  
**Version:** 2.0  
**Maintainers:** IPFS Datasets Team
