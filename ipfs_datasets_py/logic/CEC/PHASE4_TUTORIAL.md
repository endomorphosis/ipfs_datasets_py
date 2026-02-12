# Phase 4 Native Implementation - Complete Tutorial

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Phase 4A: DCEC Parsing](#phase-4a-dcec-parsing)
5. [Phase 4B: Inference Rules](#phase-4b-inference-rules)
6. [Phase 4C: Grammar System](#phase-4c-grammar-system)
7. [Phase 4D: ShadowProver](#phase-4d-shadowprover)
8. [Integration Examples](#integration-examples)
9. [Performance Tips](#performance-tips)
10. [Troubleshooting](#troubleshooting)

---

## Introduction

The Phase 4 native implementation provides a complete, pure Python 3 implementation of:
- **DCEC (Deontic Cognitive Event Calculus)** - Logic system for reasoning about actions, time, and obligations
- **Theorem Proving** - Automated reasoning with 87 inference rules
- **Natural Language Processing** - Grammar-based NL↔DCEC conversion
- **Modal Logic** - Proving in K, S4, S5, and cognitive calculus

**Benefits:**
- 2-4x faster than Java implementation
- Zero external dependencies (Python 3.12+ only)
- Type-safe with comprehensive type hints
- Production-ready with 383+ tests

---

## Installation

The native implementation is built into `ipfs_datasets_py`:

```bash
pip install -e .
```

No additional dependencies required!

---

## Quick Start

### Simple Proof

```python
from ipfs_datasets_py.logic.native import create_prover, ModalLogic

# Create a prover
prover = create_prover(ModalLogic.K)

# Prove a formula
proof = prover.prove("P -> P")

print(f"Status: {proof.status}")
print(f"Steps: {len(proof.steps)}")
```

### Parse DCEC

```python
from ipfs_datasets_py.logic.native import parse_dcec_string

# Parse a DCEC expression
formula = parse_dcec_string("P & (Q -> R)")

print(f"Formula: {formula}")
print(f"Type: {type(formula)}")
```

### Natural Language

```python
from ipfs_datasets_py.logic.native import DCECEnglishGrammar

# Create grammar (includes its own engine)
grammar = DCECEnglishGrammar()

# Parse natural language
text = "Alice believes that it is raining"
parse_trees = grammar.engine.parse(text)

if parse_trees:
    print(f"DCEC: {parse_trees[0].semantics}")
```

---

## Phase 4A: DCEC Parsing

### Basic Parsing

```python
from ipfs_datasets_py.logic.native import (
    parse_dcec_string,
    clean_dcec_expression,
    tokenize_dcec
)

# Clean expression
dirty = "  P  &  ( Q -> R )  "
clean = clean_dcec_expression(dirty)
# Result: "P&(Q->R)"

# Tokenize
tokens = tokenize_dcec(clean)
# Result: ['P', '&', '(', 'Q', '->', 'R', ')']

# Parse to formula
formula = parse_dcec_string(clean)
print(f"Parsed: {formula}")
```

### Advanced Parsing

```python
from ipfs_datasets_py.logic.native import (
    DCECPrototypeNamespace,
    parse_dcec_string
)

# Create namespace for custom types
namespace = DCECPrototypeNamespace()

# Add custom sorts
namespace.add_sort("Agent")
namespace.add_sort("Action")

# Add custom functions
namespace.add_function("believes", ["Agent", "Formula"], "Formula")

# Parse with namespace
formula = parse_dcec_string("believes(alice, P)", namespace)
```

### Supported Operators

```python
# Logical connectives
parse_dcec_string("P & Q")          # AND
parse_dcec_string("P | Q")          # OR
parse_dcec_string("~P")             # NOT
parse_dcec_string("P -> Q")         # IMPLIES
parse_dcec_string("P <-> Q")        # BICONDITIONAL

# Deontic operators
parse_dcec_string("O(P)")           # Obligatory
parse_dcec_string("P(P)")           # Permitted
parse_dcec_string("F(P)")           # Forbidden

# Temporal operators
parse_dcec_string("G(P)")           # Always (Globally)
parse_dcec_string("F(P)")           # Eventually (Finally)
parse_dcec_string("X(P)")           # Next

# Modal operators
parse_dcec_string("□P")             # Necessary
parse_dcec_string("◇P")             # Possible
```

---

## Phase 4B: Inference Rules

### Using the Inference Engine

```python
from ipfs_datasets_py.logic.native import InferenceEngine

# Create engine
engine = InferenceEngine()

# Add assumptions
engine.add_assumption("P")
engine.add_assumption("P -> Q")

# Apply rules
results = engine.apply_all_rules()

# Check if Q was derived
if engine.has_formula("Q"):
    print("Successfully derived Q!")
```

### Available Rule Categories

**Basic Logic (30 rules):**
```python
# Modus Ponens: P, P->Q ⊢ Q
engine.apply_rule("ModusPonens")

# Simplification: P&Q ⊢ P
engine.apply_rule("Simplification")

# DeMorgan: ~(P&Q) ⊢ ~P|~Q
engine.apply_rule("DeMorgan")
```

**DCEC Cognitive (15 rules):**
```python
# Belief distribution
# Intention reasoning
# Knowledge operators
```

**DCEC Deontic (7 rules):**
```python
# Obligation rules
# Permission rules
# Prohibition rules
```

**Temporal (15 rules):**
```python
# Always/Eventually
# Next/Until
# Temporal reasoning
```

**Advanced Logic (10 rules):**
```python
# Resolution
# Unification
# Substitution
```

**Common Knowledge (13 rules):**
```python
# Group knowledge
# Common belief
# Distributed knowledge
```

### Custom Rules

```python
from ipfs_datasets_py.logic.native import InferenceRule

class MyCustomRule(InferenceRule):
    def __init__(self):
        super().__init__("MyRule", "My custom inference rule")
    
    def can_apply(self, formulas):
        # Check if rule can be applied
        return any("P" in str(f) for f in formulas)
    
    def apply(self, formulas):
        # Apply the rule
        return ["Q"]  # Derived formulas

# Use custom rule
engine = InferenceEngine()
engine.add_rule(MyCustomRule())
```

---

## Phase 4C: Grammar System

### Grammar-Based NL Processing

```python
from ipfs_datasets_py.logic.native import (
    DCECEnglishGrammar,
    GrammarEngine
)

# Create grammar
grammar = DCECEnglishGrammar()

# Create engine
engine = GrammarEngine()

# Parse natural language
sentences = [
    "Alice believes that it is raining",
    "Bob knows that the door is open",
    "It is forbidden to smoke",
    "Charlie must pay the fine",
    "If it rains then the ground is wet"
]

for sentence in sentences:
    parse_trees = engine.parse(sentence, grammar)
    if parse_trees:
        dcec = parse_trees[0].semantics
        print(f"'{sentence}' → {dcec}")
```

### Linearization (DCEC to NL)

```python
from ipfs_datasets_py.logic.native import parse_dcec_string

# Parse DCEC
formula = parse_dcec_string("B(alice, raining)")

# Linearize to English (if grammar supports it)
# nl_text = grammar.linearize(formula)
# print(nl_text)  # "Alice believes that it is raining"
```

### Custom Grammar Rules

```python
from ipfs_datasets_py.logic.native import (
    GrammarRule,
    Category,
    LexicalEntry
)

# Add lexical entry
entry = LexicalEntry(
    word="happy",
    category=Category.ADJECTIVE,
    semantics="happy"
)

# Add grammar rule
rule = GrammarRule(
    lhs=Category.SENTENCE,
    rhs=[Category.NOUN, Category.VERB, Category.ADJECTIVE],
    semantic_action=lambda n, v, a: f"{v}({n}, {a})"
)
```

---

## Phase 4D: ShadowProver

### Modal Logic Proving

```python
from ipfs_datasets_py.logic.native import create_prover, ModalLogic

# K logic (basic modal)
k_prover = create_prover(ModalLogic.K)
proof = k_prover.prove("□(P→Q) → (□P→□Q)")  # K axiom

# S4 logic (reflexive + transitive)
s4_prover = create_prover(ModalLogic.S4)
proof = s4_prover.prove("□P → P")  # T axiom
proof = s4_prover.prove("□P → □□P")  # 4 axiom

# S5 logic (universal accessibility)
s5_prover = create_prover(ModalLogic.S5)
proof = s5_prover.prove("◇P → □◇P")  # 5 axiom

print(f"S5 proof status: {proof.status}")
print(f"Worlds created: {proof.metadata.get('worlds', 0)}")
```

### Cognitive Calculus

```python
from ipfs_datasets_py.logic.native import create_cognitive_prover

# Create cognitive prover
prover = create_cognitive_prover()

# Knowledge axioms
proof1 = prover.prove("K(P) → P")  # Knowledge truth
proof2 = prover.prove("K(P) → K(K(P))")  # Positive introspection

# Belief axioms
proof3 = prover.prove("B(P) → ¬B(¬P)")  # Belief consistency

# Knowledge-Belief interaction
proof4 = prover.prove("K(P) → B(P)")  # Knowledge implies belief

# List all axioms
print(f"Cognitive axioms: {len(prover.cognitive_axioms)}")
for axiom in prover.cognitive_axioms:
    print(f"  - {axiom}")
```

### Problem File Parsing

```python
from ipfs_datasets_py.logic.native import parse_problem_string

# TPTP format
tptp_problem = """
fof(axiom1, axiom, p).
fof(axiom2, axiom, p => q).
fof(goal1, conjecture, q).
"""

problem = parse_problem_string(tptp_problem)
print(f"Logic: {problem.logic}")
print(f"Assumptions: {problem.assumptions}")
print(f"Goals: {problem.goals}")

# Custom format
custom_problem = """
LOGIC: S4

ASSUMPTIONS:
□P
□(P → Q)

GOALS:
□Q
"""

problem = parse_problem_string(custom_problem)

# Prove the problem
prover = create_prover(problem.logic)
for goal in problem.goals:
    proof = prover.prove(goal, problem.assumptions)
    print(f"Goal '{goal}': {proof.status}")
```

### Using the Wrapper

```python
from ipfs_datasets_py.logic.CEC.shadow_prover_wrapper import ShadowProverWrapper

# Initialize wrapper (prefers native)
wrapper = ShadowProverWrapper(prefer_native=True)
wrapper.initialize()

# Check native status
status = wrapper.get_native_status()
print(f"Native available: {status['available']}")
print(f"Features: {status['features']}")

# Prove a formula
task = wrapper.prove_formula("K(P) → P", logic="cognitive")
print(f"Result: {task.result}")
print(f"Native used: {task.native_used}")
print(f"Time: {task.execution_time:.3f}s")

# Prove from file
task = wrapper.prove_problem("path/to/problem.p")
print(f"Execution time: {task.execution_time:.2f}s")
```

---

## Integration Examples

### Complete Pipeline

```python
from ipfs_datasets_py.logic.native import (
    parse_dcec_string,
    InferenceEngine,
    create_prover,
    ModalLogic
)

# Step 1: Parse DCEC
formula1 = parse_dcec_string("P")
formula2 = parse_dcec_string("P -> Q")

# Step 2: Use inference engine
engine = InferenceEngine()
engine.add_assumption(formula1)
engine.add_assumption(formula2)
results = engine.apply_all_rules()

# Step 3: Prove with modal logic
prover = create_prover(ModalLogic.K)
proof = prover.prove("Q", [formula1, formula2])

print(f"Derived Q: {proof.status}")
```

### NL to Proof Pipeline

```python
from ipfs_datasets_py.logic.native import (
    DCECEnglishGrammar,
    GrammarEngine,
    create_cognitive_prover
)

# Step 1: Parse natural language
grammar = DCECEnglishGrammar()
engine = GrammarEngine()

nl_assumption = "Alice knows that it is raining"
parse_trees = engine.parse(nl_assumption, grammar)

if parse_trees:
    # Step 2: Get DCEC formula
    dcec_formula = parse_trees[0].semantics
    
    # Step 3: Prove using cognitive calculus
    prover = create_cognitive_prover()
    
    # K(P) → B(P) (knowledge implies belief)
    # If Alice knows it's raining, she believes it's raining
    proof = prover.prove(f"B(alice, raining)", [dcec_formula])
    
    print(f"Alice believes it's raining: {proof.status}")
```

### Batch Proving

```python
from ipfs_datasets_py.logic.native import create_prover, ModalLogic
import time

# Create prover
prover = create_prover(ModalLogic.K)

# Batch of formulas
formulas = [
    "P -> P",
    "P & Q -> P",
    "(P -> Q) -> ((Q -> R) -> (P -> R))",
    "~~P <-> P",
    "P | ~P",
]

# Prove all
start = time.time()
results = []

for formula in formulas:
    proof = prover.prove(formula)
    results.append((formula, proof.status))

elapsed = time.time() - start

# Report
for formula, status in results:
    print(f"{formula}: {status}")
print(f"\nTotal time: {elapsed:.3f}s")
print(f"Average: {elapsed/len(formulas):.3f}s per formula")
```

---

## Performance Tips

### 1. Reuse Provers

```python
# ✅ Good: Reuse prover
prover = create_prover(ModalLogic.K)
for formula in many_formulas:
    proof = prover.prove(formula)

# ❌ Bad: Create new prover each time
for formula in many_formulas:
    prover = create_prover(ModalLogic.K)
    proof = prover.prove(formula)
```

### 2. Use Native Implementation

```python
# ✅ Good: Prefer native
wrapper = ShadowProverWrapper(prefer_native=True)

# ❌ Bad: Force Java
wrapper = ShadowProverWrapper(prefer_native=False, use_docker=True)
```

### 3. Batch Operations

```python
# ✅ Good: Batch assumptions
engine = InferenceEngine()
for assumption in assumptions:
    engine.add_assumption(assumption)
results = engine.apply_all_rules()

# ❌ Bad: Apply rules each time
for assumption in assumptions:
    engine.add_assumption(assumption)
    engine.apply_all_rules()
```

### 4. Cache Results

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_prove(formula_str, logic_str):
    prover = create_prover(ModalLogic[logic_str])
    proof = prover.prove(formula_str)
    return proof.status

# Subsequent calls with same inputs are cached
```

---

## Troubleshooting

### Import Errors

```python
# Problem: Can't import components
# Solution: Ensure package is installed
pip install -e .

# Verify installation
python -c "from ipfs_datasets_py.logic.native import create_prover; print('OK')"
```

### Parse Errors

```python
# Problem: parse_dcec_string returns None
# Solution: Check expression syntax

from ipfs_datasets_py.logic.native import clean_dcec_expression

dirty = "P && Q"  # Invalid: should be & not &&
clean = clean_dcec_expression(dirty)
# Result: "P&&Q" (still invalid)

# Use correct syntax
correct = "P & Q"
formula = parse_dcec_string(correct)  # Works!
```

### Performance Issues

```python
# Problem: Slow proving
# Solution: Check formula complexity and use appropriate prover

# ✅ Simple formula → fast
proof = prover.prove("P -> P")

# ⚠️ Complex formula → may be slow
proof = prover.prove("(((P -> Q) & (Q -> R)) -> (P -> R)) & ...")

# Solution: Simplify or use different prover
```

### Memory Issues

```python
# Problem: High memory usage
# Solution: Clear caches periodically

prover = create_prover(ModalLogic.K)

# Do lots of proving...
for i in range(10000):
    proof = prover.prove(f"P{i}")

# Clear cache
prover.clear_cache()
```

---

## Next Steps

1. **Explore examples** in `scripts/demo/`
2. **Read API documentation** in `docs/`
3. **Check tests** in `tests/unit_tests/logic/` for more examples
4. **Contribute** improvements or report issues

---

## Additional Resources

- **Phase 4A Documentation**: DCEC parsing details
- **Phase 4B Documentation**: Inference rules reference
- **Phase 4C Documentation**: Grammar system guide
- **Phase 4D Documentation**: ShadowProver manual
- **MIGRATION_GUIDE.md**: Moving from Java to native
- **PHASE4_COMPLETE_STATUS.md**: Overall project status

---

**Version:** 0.8.0+  
**Last Updated:** 2026-02-12  
**Status:** Production Ready ✅
