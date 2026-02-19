# CEC Native Folder - Comprehensive Refactoring Plan 2026

**Version:** 1.0  
**Date:** 2026-02-19  
**Scope:** `ipfs_datasets_py/logic/CEC/native/` folder only  
**Status:** Ready for Implementation

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Critical Refactorings (P0)](#critical-refactorings-p0)
4. [High Priority Improvements (P1)](#high-priority-improvements-p1)
5. [Medium Priority Enhancements (P2)](#medium-priority-enhancements-p2)
6. [Implementation Roadmap](#implementation-roadmap)
7. [Success Metrics](#success-metrics)
8. [Testing Strategy](#testing-strategy)

---

## 📊 Executive Summary

### Purpose

This document provides a **detailed, actionable refactoring plan** specifically for the `native/` subfolder of the CEC logic system. This folder contains the core Python 3 implementation of the Deontic Cognitive Event Calculus.

### Scope

**Folder:** `ipfs_datasets_py/logic/CEC/native/`  
**Files:** 29 Python files  
**Total LOC:** 16,253  
**Test Files:** 27 (matching coverage)

### Current State

| Metric | Value | Assessment |
|--------|-------|------------|
| **Total LOC** | 16,253 | 🟡 Large subfolder |
| **Python Files** | 29 | 🟢 Reasonable |
| **Largest File** | 2,927 LOC | 🔴 Critical |
| **2nd Largest** | 1,360 LOC | 🔴 Critical |
| **Test Coverage** | 27/29 files | 🟢 Excellent |
| **Circular Deps** | 0 | 🟢 None |
| **Code Duplication** | ~15% | 🟡 Moderate |

### Transformation Goals

| Aspect | Before | After | Impact |
|--------|--------|-------|--------|
| **Largest File** | 2,927 LOC | <500 LOC | -83% |
| **Module Count** | 29 files | ~45 files | +55% modularity |
| **Code Duplication** | ~15% | <3% | -80% |
| **Max Function Size** | ~100 LOC | <50 LOC | -50% |
| **Type Coverage** | ~70% | >95% | +25% |

### Timeline

**Total Effort:** 18-26 hours  
**Duration:** 4-6 weeks  
**Priority:** High (blocks other improvements)

---

## 🔍 Current State Analysis

### File Size Distribution

```
>2,000 LOC: 1 file  (prover_core.py: 2,927 LOC)     🔴 CRITICAL
1,000-2,000: 1 file  (dcec_core.py: 1,360 LOC)      🔴 CRITICAL
600-1,000: 3 files   (shadow_prover, grammar, etc)  🟡 HIGH
500-600: 6 files                                     🟢 ACCEPTABLE
400-500: 9 files                                     🟢 GOOD
<400: 9 files                                        🟢 GOOD
```

### File Categories

**1. Core Types & Infrastructure (5 files, 1,698 LOC)**
```
types.py                    (341 LOC) - Type aliases, protocols
exceptions.py               (319 LOC) - Exception hierarchy
context_manager.py          (423 LOC) - Context tracking
dcec_namespace.py           (380 LOC) - Symbol management
__init__.py                 (302 LOC) - Package exports
```

**2. Core Logic System (4 files, 3,453 LOC)**
```
dcec_core.py              (1,360 LOC) - DCEC formulas/operators 🔴
dcec_parsing.py             (434 LOC) - Parse tokens
dcec_cleaning.py            (293 LOC) - String preprocessing
dcec_integration.py         (363 LOC) - Pipeline integration
```

**3. Theorem Proving (6 files, 4,283 LOC)**
```
prover_core.py            (2,927 LOC) - Inference engine 🔴
shadow_prover.py            (714 LOC) - Modal logic provers
modal_tableaux.py           (585 LOC) - Tableau method
proof_strategies.py         (458 LOC) - Proof tactics
proof_optimization.py       (390 LOC) - Caching & parallel
lemma_generation.py         (501 LOC) - Lemma synthesis
```

**4. Natural Language (4 files, 1,910 LOC)**
```
nl_converter.py             (443 LOC) - NL → formula conversion
grammar_engine.py           (436 LOC) - Grammar-based parsing
dcec_english_grammar.py     (628 LOC) - English rules
enhanced_grammar_parser.py  (413 LOC) - Advanced features
```

**5. Domain Logic (3 files, 1,442 LOC)**
```
event_calculus.py           (549 LOC) - Event-fluent reasoning
fluents.py                  (520 LOC) - Fluent tracking
temporal.py                 (422 LOC) - Temporal constraints
```

**6. Supporting Systems (4 files, 1,532 LOC)**
```
ambiguity_resolver.py       (323 LOC) - Ambiguity handling
syntax_tree.py              (419 LOC) - AST construction
advanced_inference.py       (573 LOC) - Advanced rules
dcec_prototypes.py          (435 LOC) - Prototype builder
```

**7. Optimization & Integration (3 files, 1,299 LOC)**
```
cec_proof_cache.py          (405 LOC) - Proof caching
cec_zkp_integration.py      (551 LOC) - ZKP integration
problem_parser.py           (346 LOC) - TPTP parsing
```

### Dependency Hierarchy

```
Level 1 (Foundation):
├── exceptions.py
├── types.py
└── context_manager.py

Level 2 (Core Types):
├── dcec_core.py (operators, formulas, terms)
├── dcec_namespace.py (symbol tables)
└── dcec_cleaning.py & dcec_parsing.py (preprocessing)

Level 3 (Integration):
├── dcec_integration.py (parsing pipeline)
├── nl_converter.py (NL processing)
├── grammar_engine.py & dcec_english_grammar.py
├── syntax_tree.py & ambiguity_resolver.py
└── event_calculus.py, fluents.py, temporal.py

Level 4 (Proving):
├── prover_core.py (basic inference)
├── shadow_prover.py & modal_tableaux.py (modal logic)
├── proof_strategies.py & lemma_generation.py
└── advanced_inference.py

Level 5 (Optimization):
├── proof_optimization.py
├── cec_proof_cache.py
├── cec_zkp_integration.py
└── problem_parser.py
```

### Code Quality Issues

**Large Files (>600 LOC):**
- ✋ `prover_core.py` (2,927 LOC) - 120+ inference rule classes
- ✋ `dcec_core.py` (1,360 LOC) - operators, formulas, terms mixed
- ⚠️ `shadow_prover.py` (714 LOC) - 4 modal logic provers
- ⚠️ `dcec_english_grammar.py` (628 LOC) - hardcoded rules

**Code Duplication Patterns:**
1. Formula equality checking (3 instances in prover_core.py)
2. Proof statistics tracking (3 different dict structures)
3. Error handling patterns (6 try/except blocks)
4. Operator enum conversion (4 locations)

**Complex Functions (>50 LOC):**
- `dcec_core.py:Formula.substitute()` (~100 LOC)
- `prover_core.py:BasicProver.prove()` (~60 LOC)
- `grammar_engine.py:CompositeGrammar.parse()` (~80 LOC)
- `dcec_integration.py:parse_expression_to_token()` (~50 LOC)

**Type Hint Gaps:**
- `shadow_prover.py`: Generic `Any` return types
- `nl_converter.py`: Pattern types incomplete
- `modal_tableaux.py`: Node types unspecified
- `grammar_engine.py`: ParseNode arguments not fully typed

---

## 🔴 Critical Refactorings (P0)

### P0-1: Split prover_core.py (2,927 LOC → ~500 LOC)

#### Problem Statement

**prover_core.py** is a monolithic file containing:
- 1 ProofResult enum
- 1 InferenceRule ABC
- **120+ inference rule classes** (60-80 LOC each)
- 1 ProofStep dataclass
- 1 ProofTree class
- 1 BasicProver class
- Utility functions

This violates Single Responsibility Principle and makes testing, maintenance, and extension difficult.

#### Proposed Solution

**Create `inference_rules/` subpackage:**

```
native/inference_rules/
├── __init__.py                    # Export all rules
├── base.py                        # InferenceRule ABC + ProofResult
├── propositional.py               # Basic propositional rules (15-20 rules)
│   ├── ModusPonens
│   ├── ModusTollens
│   ├── DisjunctiveSyllogism
│   ├── HypotheticalSyllogism
│   ├── Simplification
│   ├── Addition
│   ├── ConjunctionIntroduction
│   ├── DisjunctionElimination
│   └── ... (12 more)
├── first_order.py                 # First-order logic rules (10-15 rules)
│   ├── UniversalInstantiation
│   ├── ExistentialInstantiation
│   ├── UniversalGeneralization
│   ├── ExistentialGeneralization
│   └── ... (10 more)
├── temporal.py                    # Temporal reasoning rules (15-20 rules)
│   ├── TemporalModusPonens
│   ├── EventSequencing
│   ├── FluentInertia
│   └── ... (15 more)
├── deontic.py                     # Deontic logic rules (10-12 rules)
│   ├── ObligationDischarge
│   ├── PermissionDerivation
│   ├── DeonticDetachment
│   └── ... (10 more)
├── modal.py                       # Modal operators (12-15 rules)
│   ├── NecessityDistribution
│   ├── PossibilityIntroduction
│   ├── S4Transitivity
│   └── ... (12 more)
├── cognitive.py                   # Cognitive operators (10-12 rules)
│   ├── BeliefRevision
│   ├── KnowledgeIntroduction
│   ├── IntentionFormation
│   └── ... (10 more)
└── specialized.py                 # Advanced/specialized (20-25 rules)
    ├── DeMorganTheorem
    ├── DoubleNegationElimination
    ├── ContrapositionRule
    ├── CutElimination
    └── ... (20 more)
```

**Refactor prover_core.py to:**

```python
# native/prover_core.py (reduced to ~500 LOC)
"""Core theorem proving engine for DCEC."""

from typing import List, Set, Dict, Optional
from dataclasses import dataclass, field

from .inference_rules import (
    InferenceRule,
    ProofResult,
    # Import all rule categories
    get_all_propositional_rules,
    get_all_first_order_rules,
    get_all_temporal_rules,
    get_all_deontic_rules,
    get_all_modal_rules,
    get_all_cognitive_rules,
    get_all_specialized_rules,
)
from .dcec_core import Formula


@dataclass
class ProofStep:
    """Represents a single step in a proof."""
    formula: Formula
    rule: str
    premises: List[int] = field(default_factory=list)
    step_number: int = 0


@dataclass
class ProofTree:
    """Represents a complete proof tree."""
    goal: Formula
    axioms: List[Formula]
    steps: List[ProofStep]
    result: ProofResult


class BasicProver:
    """
    Core theorem prover using forward-chaining inference.
    
    This prover maintains a set of known formulas and applies
    inference rules to derive new formulas until the goal is
    reached or no progress can be made.
    """
    
    def __init__(self, max_steps: int = 1000, timeout: float = 30.0):
        self.max_steps = max_steps
        self.timeout = timeout
        
        # Register all inference rules
        self.rules: List[InferenceRule] = []
        self.rules.extend(get_all_propositional_rules())
        self.rules.extend(get_all_first_order_rules())
        self.rules.extend(get_all_temporal_rules())
        self.rules.extend(get_all_deontic_rules())
        self.rules.extend(get_all_modal_rules())
        self.rules.extend(get_all_cognitive_rules())
        self.rules.extend(get_all_specialized_rules())
    
    def prove(self, goal: Formula, axioms: List[Formula]) -> ProofTree:
        """
        Attempt to prove goal from axioms.
        
        Args:
            goal: Formula to prove
            axioms: Known true formulas
            
        Returns:
            ProofTree with result and derivation steps
        """
        # Proving logic here (reduced from 60 LOC to ~40 LOC)
        pass
```

#### Implementation Steps

**Week 1: Create Infrastructure**
1. Create `native/inference_rules/` directory
2. Create `base.py` with InferenceRule ABC and ProofResult
3. Create `__init__.py` with exports
4. Add tests for base infrastructure

**Week 2: Extract Propositional Rules**
1. Create `propositional.py`
2. Move 15-20 propositional rules from prover_core.py
3. Update imports in prover_core.py
4. Run all prover tests

**Week 3: Extract Domain-Specific Rules**
1. Create `first_order.py`, `temporal.py`, `deontic.py`
2. Move rules to respective modules
3. Update imports
4. Run all tests

**Week 4: Extract Modal & Cognitive Rules**
1. Create `modal.py`, `cognitive.py`, `specialized.py`
2. Move remaining rules
3. Clean up prover_core.py
4. Final validation

#### Success Criteria

- ✅ `prover_core.py` reduced from 2,927 LOC to <500 LOC
- ✅ 7-8 new modules created, each <400 LOC
- ✅ All 27 tests passing
- ✅ No import errors
- ✅ Backward compatibility maintained

#### Expected Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **prover_core.py Size** | 2,927 LOC | ~500 LOC | -83% |
| **Module Count** | 29 | 36 | +7 |
| **Rules per File** | 120+ | <20 | -83% |
| **Testability** | Low | High | Much better |
| **Extensibility** | Hard | Easy | Much easier |

---

### P0-2: Split dcec_core.py (1,360 LOC → ~400 LOC)

#### Problem Statement

**dcec_core.py** contains multiple concerns:
- 4 operator enums (Deontic, Cognitive, Logical, Temporal)
- Sort/Variable/Function/Predicate classes (type system)
- Term hierarchy (Variable, Function, Constant)
- Formula hierarchy (Atomic, Connective, Deontic, Cognitive, etc.)
- Serialization/deserialization logic

This mixing makes the module hard to understand and maintain.

#### Proposed Solution

**Split into logical submodules:**

```
native/core/
├── __init__.py                    # Re-export all
├── operators.py                   # All operator enums (~300 LOC)
│   ├── DeonticOperator
│   ├── CognitiveOperator
│   ├── LogicalConnective
│   └── TemporalOperator
├── type_system.py                 # Type system classes (~300 LOC)
│   ├── Sort
│   ├── Variable
│   ├── Function
│   └── Predicate
├── terms.py                       # Term hierarchy (~350 LOC)
│   ├── Term (ABC)
│   ├── VariableTerm
│   ├── FunctionTerm
│   └── ConstantTerm
└── formulas.py                    # Formula hierarchy (~400 LOC)
    ├── Formula (ABC)
    ├── AtomicFormula
    ├── ConnectiveFormula
    ├── DeonticFormula
    ├── CognitiveFormula
    ├── TemporalFormula
    └── QuantifiedFormula
```

**Update dcec_core.py:**

```python
# native/dcec_core.py (becomes compatibility shim)
"""
Deontic Cognitive Event Calculus - Core Types.

For backward compatibility, this module re-exports all types
from the core/ subpackage.
"""

# Re-export everything from core submodules
from .core.operators import (
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    TemporalOperator,
)
from .core.type_system import (
    Sort,
    Variable,
    Function,
    Predicate,
)
from .core.terms import (
    Term,
    VariableTerm,
    FunctionTerm,
    ConstantTerm,
)
from .core.formulas import (
    Formula,
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    QuantifiedFormula,
)

__all__ = [
    # Operators
    'DeonticOperator',
    'CognitiveOperator',
    'LogicalConnective',
    'TemporalOperator',
    # Type system
    'Sort',
    'Variable',
    'Function',
    'Predicate',
    # Terms
    'Term',
    'VariableTerm',
    'FunctionTerm',
    'ConstantTerm',
    # Formulas
    'Formula',
    'AtomicFormula',
    'ConnectiveFormula',
    'DeonticFormula',
    'CognitiveFormula',
    'TemporalFormula',
    'QuantifiedFormula',
]
```

#### Implementation Steps

**Week 1:**
1. Create `native/core/` directory
2. Create `operators.py` with all operator enums
3. Create `__init__.py` with re-exports
4. Test operator imports

**Week 2:**
1. Create `type_system.py` with Sort/Variable/Function/Predicate
2. Create `terms.py` with Term hierarchy
3. Update dcec_core.py to re-export
4. Run tests

**Week 3:**
1. Create `formulas.py` with Formula hierarchy
2. Move serialization methods to formulas.py
3. Update all imports in other modules
4. Final validation

#### Success Criteria

- ✅ `dcec_core.py` becomes <100 LOC (re-export shim)
- ✅ 4 new core modules created, each <400 LOC
- ✅ All tests passing
- ✅ Full backward compatibility
- ✅ No breaking changes for external code

#### Expected Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **dcec_core.py Size** | 1,360 LOC | ~100 LOC | -93% |
| **Module Count** | 29 | 32 | +3 |
| **Largest Core Module** | 1,360 | <400 | -71% |
| **Import Clarity** | Low | High | Better |

---

### P0-3: Eliminate Code Duplication

#### Problem 1: Formula Equality Checking

**Duplication:** 3 instances in `prover_core.py`

```python
# Line 92 in ModusPonens
def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
    return f1.to_string() == f2.to_string()

# Line 642 in DisjunctiveSyllogism
def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
    return f1.to_string() == f2.to_string()

# Line 702 in CutElimination
def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
    return f1.to_string() == f2.to_string()
```

**Solution:** Add to Formula class

```python
# In native/core/formulas.py
class Formula(ABC):
    """Base class for all DCEC formulas."""
    
    def __eq__(self, other: object) -> bool:
        """
        Check structural equality of formulas.
        
        Args:
            other: Object to compare with
            
        Returns:
            True if formulas are structurally equal
        """
        if not isinstance(other, Formula):
            return False
        return self.to_string() == other.to_string()
    
    def __hash__(self) -> int:
        """Hash based on string representation for set/dict usage."""
        return hash(self.to_string())
```

**Impact:** Remove 3 duplicate methods, add set/dict support

---

#### Problem 2: Proof Statistics Tracking

**Duplication:** 3 different dict structures

```python
# In shadow_prover.py (line 145)
self.statistics = {
    'attempts': 0,
    'succeeded': 0,
    'failed': 0,
    'avg_time': 0.0,
}

# In prover_core.py (line 236)
self.stats = {
    'rules_applied': {},
    'steps_taken': 0,
    'time_elapsed': 0.0,
}

# In cec_proof_cache.py (custom tracking)
```

**Solution:** Create unified dataclass

```python
# In native/types.py
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class ProofStatistics:
    """
    Unified statistics tracking for theorem proving.
    
    Attributes:
        attempts: Total proof attempts
        succeeded: Successful proofs
        failed: Failed proofs
        steps_taken: Total inference steps
        avg_time: Average time per proof (seconds)
        cache_hits: Number of cache hits (if caching enabled)
        rules_applied: Count of each rule application
    """
    attempts: int = 0
    succeeded: int = 0
    failed: int = 0
    steps_taken: int = 0
    avg_time: float = 0.0
    cache_hits: int = 0
    rules_applied: Dict[str, int] = field(default_factory=dict)
    
    def record_success(self, steps: int, time: float) -> None:
        """Record a successful proof."""
        self.attempts += 1
        self.succeeded += 1
        self.steps_taken += steps
        self._update_avg_time(time)
    
    def record_failure(self, time: float) -> None:
        """Record a failed proof."""
        self.attempts += 1
        self.failed += 1
        self._update_avg_time(time)
    
    def record_rule(self, rule_name: str) -> None:
        """Record an inference rule application."""
        self.rules_applied[rule_name] = self.rules_applied.get(rule_name, 0) + 1
    
    def _update_avg_time(self, time: float) -> None:
        """Update average time using incremental mean."""
        self.avg_time = (self.avg_time * (self.attempts - 1) + time) / self.attempts
```

**Impact:** Remove 3 dict structures, add type safety

---

#### Problem 3: Error Handling Patterns

**Duplication:** 6 try/except blocks with logging

```python
# Pattern in shadow_prover.py, cec_zkp_integration.py, modal_tableaux.py
try:
    result = self._prove_internal(formula)
    return result
except Exception as e:
    logger.error(f"Proof failed: {e}")
    return ProofResult.ERROR
```

**Solution:** Create error handling utility

```python
# In native/error_handling.py (new file)
"""Utilities for consistent error handling in proving."""

import logging
from typing import Callable, TypeVar, Any
from functools import wraps

from .inference_rules import ProofResult

T = TypeVar('T')

def handle_proof_error(
    logger: logging.Logger,
    default_result: ProofResult = ProofResult.ERROR
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for consistent proof error handling.
    
    Args:
        logger: Logger instance to use
        default_result: Result to return on error
        
    Returns:
        Decorated function with error handling
        
    Example:
        @handle_proof_error(logger)
        def prove_formula(self, formula):
            # Proving logic
            return result
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"{func.__name__} failed: {e}",
                    exc_info=True
                )
                return default_result
        return wrapper
    return decorator


# Usage in shadow_prover.py:
from .error_handling import handle_proof_error

class ShadowProver:
    @handle_proof_error(logger)
    def prove(self, formula: Formula) -> ProofResult:
        result = self._prove_internal(formula)
        return result
```

**Impact:** Remove 6 duplicate try/except blocks

---

#### Implementation Steps

**Week 1: Formula Equality**
1. Add `__eq__` and `__hash__` to Formula class
2. Remove duplicate `_formulas_equal` methods
3. Update all inference rules to use `==` operator
4. Test set/dict operations with formulas

**Week 2: Proof Statistics**
1. Create `ProofStatistics` dataclass in types.py
2. Update shadow_prover.py to use ProofStatistics
3. Update prover_core.py to use ProofStatistics
4. Update cec_proof_cache.py to use ProofStatistics
5. Add tests

**Week 3: Error Handling**
1. Create error_handling.py
2. Add `handle_proof_error` decorator
3. Update 6 files to use decorator
4. Test error handling and logging

#### Success Criteria

- ✅ Formula equality: 3 duplicate methods → 1 implementation
- ✅ Statistics: 3 dict structures → 1 dataclass
- ✅ Error handling: 6 try/except blocks → 1 decorator
- ✅ All tests passing
- ✅ Code duplication reduced from ~15% to <5%

---

## 🟡 High Priority Improvements (P1)

### P1-1: Add Complete Type Hints

#### Problem

Several modules have incomplete type hints:
- `shadow_prover.py`: `Any` return types
- `nl_converter.py`: Pattern types incomplete
- `modal_tableaux.py`: Node types unspecified
- `grammar_engine.py`: ParseNode not fully typed

#### Solution

**Create type definitions:**

```python
# In native/types.py (add):
from typing import Protocol, TypedDict, NamedTuple
import re

class TableauNode(NamedTuple):
    """Node in a tableau proof tree."""
    formulas: List[Formula]
    is_closed: bool
    rule_applied: str
    parent: Optional['TableauNode'] = None
    children: List['TableauNode'] = []

class ParseNode(Protocol):
    """Protocol for grammar parse tree nodes."""
    value: str
    rule_name: str
    children: List['ParseNode']
    span: tuple[int, int]

PatternType = re.Pattern[str]  # Type alias for compiled patterns

class ProofResult(TypedDict):
    """Result of a proof attempt with metadata."""
    status: str
    steps: List[str]
    time: float
    cached: bool
```

**Update modules:**

```python
# In shadow_prover.py
from .types import ProofResult, TableauNode

class ShadowProver:
    def prove(self, formula: Formula) -> ProofResult:  # Not Any
        ...
    
    def _build_tableau(self, formula: Formula) -> TableauNode:  # Not Any
        ...

# In nl_converter.py
from .types import PatternType

class NLConverter:
    def __init__(self):
        self.patterns: Dict[str, PatternType] = {}
```

#### Implementation

- **Time:** 2-3 hours
- **Files:** 4 modules
- **Tests:** Run mypy --strict

---

### P1-2: Extract Grammar Rules to Data File

#### Problem

`dcec_english_grammar.py` (628 LOC) hardcodes grammar rules in Python code, making:
- Rules hard to modify
- Multi-language support difficult
- Non-developers can't contribute rules

#### Solution

**Create YAML grammar file:**

```yaml
# native/grammars/dcec_english.yaml
version: "1.0"
language: "en"

operators:
  deontic:
    obligation:
      patterns: ["must", "should", "obligated to", "required to"]
      priority: 1
    permission:
      patterns: ["may", "can", "permitted to", "allowed to"]
      priority: 2
    prohibition:
      patterns: ["cannot", "must not", "forbidden to", "prohibited from"]
      priority: 1
  
  cognitive:
    belief:
      patterns: ["believes that", "thinks that", "holds that"]
      priority: 1
    knowledge:
      patterns: ["knows that", "is aware that", "understands that"]
      priority: 1
    intention:
      patterns: ["intends to", "plans to", "aims to"]
      priority: 1

temporal:
  operators:
    happens:
      patterns: ["happens", "occurs", "takes place"]
    holds_at:
      patterns: ["holds at", "is true at", "valid at"]
    initiates:
      patterns: ["initiates", "starts", "begins"]
    terminates:
      patterns: ["terminates", "ends", "finishes"]

connectives:
  and: ["and", ",", "furthermore"]
  or: ["or", "alternatively", "either"]
  not: ["not", "it is not the case that", "false that"]
  implies: ["implies", "if...then", "entails"]
```

**Load grammar dynamically:**

```python
# In dcec_english_grammar.py (reduced to ~150 LOC)
import yaml
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class GrammarRule:
    """Single grammar rule definition."""
    patterns: List[str]
    priority: int
    category: str

class EnglishGrammar:
    """English grammar rules loaded from YAML."""
    
    def __init__(self, grammar_file: str = "dcec_english.yaml"):
        self.rules: Dict[str, GrammarRule] = {}
        self._load_grammar(grammar_file)
    
    def _load_grammar(self, filename: str) -> None:
        """Load grammar rules from YAML file."""
        grammar_path = Path(__file__).parent / "grammars" / filename
        with open(grammar_path) as f:
            data = yaml.safe_load(f)
        
        # Parse operators
        for op_type, operators in data['operators'].items():
            for op_name, op_data in operators.items():
                rule = GrammarRule(
                    patterns=op_data['patterns'],
                    priority=op_data['priority'],
                    category=op_type
                )
                self.rules[f"{op_type}.{op_name}"] = rule
        
        # Parse temporal, connectives, etc.
        # ...
    
    def get_patterns_for(self, category: str) -> List[str]:
        """Get all patterns for a given category."""
        return [
            pattern
            for key, rule in self.rules.items()
            if rule.category == category
            for pattern in rule.patterns
        ]
```

#### Benefits

- 628 LOC → ~150 LOC (-76%)
- Non-developers can edit grammar rules
- Easy to add new languages (create new YAML file)
- Grammar versioning and validation

#### Implementation

- **Time:** 2-3 hours
- **Impact:** High (enables multi-language support)

---

### P1-3: Improve Function Complexity

#### Problem

Several functions exceed 50 LOC:
- `dcec_core.py:Formula.substitute()` (~100 LOC)
- `prover_core.py:BasicProver.prove()` (~60 LOC)
- `grammar_engine.py:CompositeGrammar.parse()` (~80 LOC)

#### Solution

**Decompose Formula.substitute():**

```python
# Before (100 LOC)
def substitute(self, var: Variable, term: Term) -> Formula:
    # 100 lines of substitution logic
    pass

# After (decomposed)
def substitute(self, var: Variable, term: Term) -> Formula:
    """Substitute term for variable in formula."""
    if self._is_atomic():
        return self._substitute_atomic(var, term)
    elif self._is_quantified():
        return self._substitute_quantified(var, term)
    else:
        return self._substitute_compound(var, term)

def _substitute_atomic(self, var: Variable, term: Term) -> Formula:
    """Handle substitution in atomic formulas."""
    # 15-20 LOC
    pass

def _substitute_quantified(self, var: Variable, term: Term) -> Formula:
    """Handle substitution with bound variables."""
    # 30-40 LOC
    pass

def _substitute_compound(self, var: Variable, term: Term) -> Formula:
    """Handle substitution in compound formulas."""
    # 20-25 LOC
    pass
```

#### Implementation

- **Time:** 3-4 hours
- **Files:** 3-4 modules
- **Target:** Max function size <50 LOC

---

## 🟢 Medium Priority Enhancements (P2)

### P2-1: Expand Docstrings

**Goal:** Add comprehensive docstrings to:
- 12 inference rule classes (ModusPonens through HypotheticalSyllogism)
- 6 complex functions
- All public APIs

**Effort:** 3-4 hours

---

### P2-2: Add Missing Test Cases

**Goal:** Add tests for:
- Circular import verification (1-2 tests)
- Large formula handling (2-3 tests)
- Temporal-deontic combinations (2-3 tests)
- Grammar parsing edge cases (3-4 tests)

**Effort:** 4-5 hours

---

### P2-3: Performance Optimization

**Goal:** Profile and optimize:
- Formula string conversion (cache results)
- Proof search (add heuristics)
- Grammar parsing (add memoization)

**Effort:** 6-8 hours

---

## 🗺️ Implementation Roadmap

### Phase 1: Critical Refactorings (Weeks 1-4)

**Week 1: Setup & Infrastructure**
- Create `inference_rules/` package structure
- Create `core/` package structure
- Set up tests

**Week 2: Extract Inference Rules (Part 1)**
- Create base.py, propositional.py, first_order.py
- Move 30-35 rules
- Update prover_core.py imports
- Run all tests

**Week 3: Extract Inference Rules (Part 2)**
- Create temporal.py, deontic.py, modal.py
- Move 40-45 rules
- Clean up prover_core.py

**Week 4: Split dcec_core.py**
- Create operators.py, type_system.py, terms.py, formulas.py
- Update all imports
- Final validation

**Milestone:** prover_core.py <500 LOC, dcec_core.py <100 LOC

---

### Phase 2: Code Quality (Weeks 5-6)

**Week 5: Eliminate Duplication**
- Add Formula.__eq__ and __hash__
- Create ProofStatistics dataclass
- Create error_handling.py
- Update all modules

**Week 6: Type Hints & Grammar**
- Add complete type hints to 4 modules
- Create YAML grammar file
- Extract grammar rules
- Run mypy --strict

**Milestone:** <3% code duplication, >95% type coverage

---

### Phase 3: Polish (Weeks 7-8)

**Week 7: Documentation**
- Add docstrings to inference rules
- Add docstrings to complex functions
- Update README

**Week 8: Testing & Performance**
- Add missing test cases
- Profile critical paths
- Optimize hot spots

**Milestone:** 100% docstring coverage, performance validated

---

## 📊 Success Metrics

### Quantitative Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| **Largest File** | 2,927 LOC | <500 LOC | wc -l |
| **Module Count** | 29 | ~45 | ls \| wc -l |
| **Code Duplication** | ~15% | <3% | PMD/CPD |
| **Type Coverage** | ~70% | >95% | mypy |
| **Max Function Size** | ~100 LOC | <50 LOC | radon |
| **Docstring Coverage** | ~60% | 100% | interrogate |
| **Test Count** | 27 files | 45+ files | pytest |

### Qualitative Metrics

| Aspect | Before | After |
|--------|--------|-------|
| **Code Organization** | Monolithic | Modular |
| **Testability** | Difficult | Easy |
| **Extensibility** | Hard | Simple |
| **Maintainability** | Low | High |
| **Onboarding** | Complex | Straightforward |

### Phase Success Criteria

**Phase 1 Complete:**
- ✅ prover_core.py <500 LOC
- ✅ dcec_core.py <100 LOC
- ✅ All 27+ tests passing
- ✅ No import errors

**Phase 2 Complete:**
- ✅ Code duplication <5%
- ✅ Type coverage >90%
- ✅ mypy --strict passes

**Phase 3 Complete:**
- ✅ 100% docstring coverage
- ✅ 45+ test files
- ✅ Performance validated

---

## 🧪 Testing Strategy

### Test Organization

```
tests/unit_tests/logic/CEC/native/
├── inference_rules/          # New test directory
│   ├── test_base.py
│   ├── test_propositional.py
│   ├── test_first_order.py
│   ├── test_temporal.py
│   ├── test_deontic.py
│   ├── test_modal.py
│   ├── test_cognitive.py
│   └── test_specialized.py
├── core/                     # New test directory
│   ├── test_operators.py
│   ├── test_type_system.py
│   ├── test_terms.py
│   └── test_formulas.py
├── test_prover_core.py       # Updated
├── test_dcec_core.py         # Updated (compatibility)
├── test_error_handling.py    # New
└── ... (existing 27 test files)
```

### Test Types

**1. Unit Tests**
- Test individual functions/classes
- Mock dependencies
- Fast execution (<1s per test)

**2. Integration Tests**
- Test module interactions
- Real dependencies
- Moderate execution (<10s per test)

**3. Regression Tests**
- Ensure refactoring doesn't break functionality
- Compare old vs new behavior
- Critical for backward compatibility

**4. Performance Tests**
- Benchmark critical paths
- Track performance over time
- Ensure no regressions

### Continuous Validation

```bash
# Run after each change
pytest tests/unit_tests/logic/CEC/native/ -v

# Check types
mypy ipfs_datasets_py/logic/CEC/native/ --strict

# Check code quality
radon cc ipfs_datasets_py/logic/CEC/native/ -a -nb

# Check duplication
pylint ipfs_datasets_py/logic/CEC/native/ --duplicate-code=yes
```

---

## 📅 Timeline Summary

```
Week 1-2:  ████████ Phase 1 Part 1: Infrastructure & Inference Rules
Week 3-4:  ████████ Phase 1 Part 2: dcec_core Split
Week 5:    ████     Phase 2 Part 1: Code Deduplication
Week 6:    ████     Phase 2 Part 2: Type Hints & Grammar
Week 7:    ██       Phase 3 Part 1: Documentation
Week 8:    ██       Phase 3 Part 2: Testing & Performance

Total: 8 weeks (18-26 hours estimated)
```

---

## 🎯 Quick Reference

### Top 5 Actions

1. **Split prover_core.py** (2,927 → <500 LOC) - P0, 8-10h
2. **Split dcec_core.py** (1,360 → <100 LOC) - P0, 4-6h
3. **Eliminate code duplication** (15% → <3%) - P0, 4-5h
4. **Add complete type hints** (70% → >95%) - P1, 2-3h
5. **Extract grammar to YAML** (628 → 150 LOC) - P1, 2-3h

### Expected Outcomes

**After 8 weeks:**
- ✅ 55% more modules (29 → ~45)
- ✅ 83% reduction in largest file (2,927 → <500 LOC)
- ✅ 80% less duplication (15% → <3%)
- ✅ 25% better type coverage (70% → >95%)
- ✅ 100% docstring coverage
- ✅ Better testability and maintainability

---

## 📞 Contact & Support

**Repository:** https://github.com/endomorphosis/ipfs_datasets_py  
**Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-19  
**Next Review:** Upon Phase 1 completion

---

*This plan is specific to the `native/` subfolder and complements the broader CEC refactoring plan.*
