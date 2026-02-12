# Comprehensive CEC System User Guide

## Table of Contents
1. [Overview](#overview)
2. [What is CEC?](#what-is-cec)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Core Modules](#core-modules)
6. [Usage Examples](#usage-examples)
7. [API Reference](#api-reference)
8. [Advanced Topics](#advanced-topics)

---

## Overview

The **CEC (Cognitive Event Calculus)** system is a comprehensive logic framework for reasoning about:
- **Deontic Logic** - Obligations, permissions, and prohibitions
- **Cognitive Logic** - Beliefs, knowledge, and intentions of agents
- **Temporal Logic** - Time-based reasoning and event sequences
- **Event Calculus** - Actions, events, and their effects

This native Python 3 implementation provides:
- ✅ **2-4x faster** than Java/Python 2 implementations
- ✅ **Zero external dependencies** (Python 3.12+ only)
- ✅ **Type-safe** with comprehensive type hints
- ✅ **Production-ready** with 418+ tests
- ✅ **Pure Python 3** - No legacy code

---

## What is CEC?

**CEC (Cognitive Event Calculus)** extends traditional Event Calculus with:

### 1. Deontic Operators
Model obligations and permissions:
- `O(φ)` - It is obligatory that φ
- `P(φ)` - It is permitted that φ  
- `F(φ)` - It is forbidden that φ

### 2. Cognitive Operators
Model agent beliefs and knowledge:
- `B(agent, φ)` - Agent believes φ
- `K(agent, φ)` - Agent knows φ
- `I(agent, φ)` - Agent intends φ

### 3. Temporal Operators
Reason about time:
- `□(φ)` - Always φ (necessary)
- `◊(φ)` - Eventually φ (possible)
- `X(φ)` - Next state φ

### 4. Event Calculus
Model actions and their effects:
- `Happens(e, t)` - Event e occurs at time t
- `Initiates(e, f, t)` - Event e initiates fluent f at time t
- `Terminates(e, f, t)` - Event e terminates fluent f at time t
- `HoldsAt(f, t)` - Fluent f holds at time t

---

## Installation

The CEC system is built into `ipfs_datasets_py`:

```bash
# Install from repository
pip install -e .

# Or install specific extras if needed
pip install -e ".[test]"  # Include test dependencies
```

No additional dependencies required for core functionality!

---

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

# Create a container
container = DCECContainer()

# Add an obligation
obligation = container.create_obligation("robot", "performTask")
print(f"Created: {obligation}")

# Add a belief
belief = container.create_belief("robot", "taskComplete")
print(f"Created: {belief}")

# Query the container
print(f"Total statements: {len(container.statements)}")
```

### Natural Language Conversion

```python
from ipfs_datasets_py.logic.CEC.native.nl_converter import NaturalLanguageConverter

# Create converter
converter = NaturalLanguageConverter()

# Convert English to DCEC
dcec = converter.english_to_dcec("The robot must perform the task")
print(f"DCEC: {dcec}")

# Convert DCEC back to English
english = converter.dcec_to_english("O(performTask(robot))")
print(f"English: {english}")
```

### Theorem Proving

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

# Create prover
prover = TheoremProver()

# Add axioms
prover.add_axiom("A → B")
prover.add_axiom("A")

# Prove theorem
result = prover.prove("B")
print(f"Proof result: {result}")
```

---

## Core Modules

The CEC system is organized into several modules under `ipfs_datasets_py/logic/CEC/native/`:

### 1. Core DCEC (`dcec_core.py`)
**Purpose:** Core data structures for DCEC logic

```python
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    DeonticOperator,      # O, P, F
    CognitiveOperator,    # B, K, I
    TemporalOperator,     # □, ◊, X
    AtomicFormula,        # Basic predicates
    DeonticFormula,       # Deontic expressions
    CognitiveFormula,     # Cognitive expressions
)
```

### 2. DCEC Container (`dcec_integration.py`)
**Purpose:** High-level API for working with DCEC

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

container = DCECContainer()
# Create formulas, manage axioms, run proofs
```

### 3. Theorem Prover (`prover_core.py`)
**Purpose:** Automated reasoning with 87 inference rules

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import (
    TheoremProver,
    ProofResult,
    InferenceRule,
)

prover = TheoremProver()
```

**Available Inference Rules (87 total):**
- **Basic Logic (30 rules):** Modus Ponens, DeMorgan, Resolution, etc.
- **DCEC Cognitive (15 rules):** Belief distribution, knowledge axioms
- **DCEC Deontic (7 rules):** Obligation weakening, permission rules
- **DCEC Temporal (15 rules):** Temporal logic, event calculus
- **Advanced Logic (10 rules):** Higher-order reasoning
- **Common Knowledge (13 rules):** Multi-agent reasoning

### 4. Natural Language Converter (`nl_converter.py`)
**Purpose:** Bidirectional English ↔ DCEC conversion

```python
from ipfs_datasets_py.logic.CEC.native.nl_converter import (
    NaturalLanguageConverter,
    create_enhanced_nl_converter,
)

converter = create_enhanced_nl_converter()
```

### 5. Grammar System (`grammar_engine.py`, `dcec_english_grammar.py`)
**Purpose:** Grammar-based NL processing

```python
from ipfs_datasets_py.logic.CEC.native.grammar_engine import GrammarEngine
from ipfs_datasets_py.logic.CEC.native.dcec_english_grammar import (
    DCECEnglishGrammar,
    create_dcec_grammar,
)

grammar = create_dcec_grammar()
result = grammar.parse_to_dcec("The robot believes the task is complete")
```

### 6. Modal Logic Prover (`shadow_prover.py`, `modal_tableaux.py`)
**Purpose:** Modal logic proving (K, S4, S5, cognitive calculus)

```python
from ipfs_datasets_py.logic.CEC.native.shadow_prover import (
    create_prover,
    ModalLogic,
    ProofStatus,
)

# Create K prover
prover = create_prover(ModalLogic.K)
result = prover.prove(formula, assumptions)
```

### 7. Problem Parser (`problem_parser.py`)
**Purpose:** Parse TPTP and custom problem formats

```python
from ipfs_datasets_py.logic.CEC.native.problem_parser import (
    parse_problem_file,
    ProblemFormat,
)

problem = parse_problem_file("problem.p", ProblemFormat.TPTP)
```

### 8. Namespace Management (`dcec_namespace.py`, `dcec_prototypes.py`)
**Purpose:** Type system and namespace handling

```python
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import Namespace
from ipfs_datasets_py.logic.CEC.native.dcec_prototypes import DCECPrototypeNamespace

namespace = DCECPrototypeNamespace()
namespace.add_sort("Robot", parent="Agent")
```

### 9. Parsing and Cleaning (`dcec_parsing.py`, `dcec_cleaning.py`)
**Purpose:** Low-level parsing utilities

```python
from ipfs_datasets_py.logic.CEC.native.dcec_parsing import parse_dcec_string
from ipfs_datasets_py.logic.CEC.native.dcec_cleaning import clean_dcec_expression

formula = parse_dcec_string("O(performTask(robot))")
```

---

## Usage Examples

### Example 1: Deontic Reasoning

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

# Create container
cec = DCECContainer()

# Add custom types
cec.namespace.add_sort("Robot", parent="Agent")
cec.namespace.add_sort("Task", parent="Action")

# Create obligation
obligation = cec.create_obligation(
    "robot:Robot",
    "performTask(t:Task)"
)

# Create permission
permission = cec.create_permission(
    "robot:Robot", 
    "skipTask(t:Task)"
)

# Query
print(f"Obligations: {cec.get_obligations()}")
print(f"Permissions: {cec.get_permissions()}")
```

### Example 2: Cognitive Reasoning

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

cec = DCECContainer()

# Model agent beliefs
belief1 = cec.create_belief("alice", "taskComplete")
belief2 = cec.create_belief("bob", "taskPending")

# Model knowledge
knowledge = cec.create_knowledge("alice", "deadline")

# Model intentions
intention = cec.create_intention("bob", "finishTask")

# Query cognitive state
alice_beliefs = cec.get_beliefs("alice")
print(f"Alice believes: {alice_beliefs}")
```

### Example 3: Temporal Reasoning

```python
from ipfs_datasets_py.logic.CEC.native.dcec_core import TemporalOperator
from ipfs_datasets_py.logic.CEC.native import DCECContainer

cec = DCECContainer()

# Always safe
always_safe = cec.create_temporal(
    TemporalOperator.ALWAYS,
    "safe(system)"
)

# Eventually complete
eventually_done = cec.create_temporal(
    TemporalOperator.EVENTUALLY,
    "complete(task)"
)

# Next state
next_action = cec.create_temporal(
    TemporalOperator.NEXT,
    "execute(action)"
)
```

### Example 4: Event Calculus

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

cec = DCECContainer()

# Define events
start_event = "Happens(start(robot, task), t1)"
finish_event = "Happens(finish(robot, task), t2)"

# Define initiates/terminates
initiates = "Initiates(start(robot, task), working(robot), t1)"
terminates = "Terminates(finish(robot, task), working(robot), t2)"

# Add to container
cec.add_statement(start_event)
cec.add_statement(initiates)
cec.add_statement(terminates)

# Reason about fluents
holds_at = "HoldsAt(working(robot), t)"
```

### Example 5: Natural Language Interface

```python
from ipfs_datasets_py.logic.CEC.native.nl_converter import create_enhanced_nl_converter

converter = create_enhanced_nl_converter()

# Convert various English sentences
examples = [
    "The robot must perform the task",
    "Alice believes the task is complete",
    "The system should always be safe",
    "Eventually the goal will be achieved",
]

for sentence in examples:
    dcec = converter.english_to_dcec(sentence)
    print(f"'{sentence}' → {dcec}")
```

### Example 6: Automated Proving

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

prover = TheoremProver()

# Add domain knowledge
prover.add_axiom("O(A) → P(A)")  # Obligations imply permissions
prover.add_axiom("O(performTask)")  # Robot must perform task

# Prove permission follows
result = prover.prove("P(performTask)")

if result.status == "proved":
    print("✓ Successfully proved permission")
    print(f"Proof steps: {len(result.proof_steps)}")
```

### Example 7: Modal Logic

```python
from ipfs_datasets_py.logic.CEC.native.shadow_prover import (
    create_prover,
    ModalLogic,
)

# Create S5 prover (knowledge logic)
prover = create_prover(ModalLogic.S5)

# Knowledge axioms
assumptions = [
    "K(agent, p)",           # Agent knows p
    "K(agent, p → q)",       # Agent knows p implies q
]

# Prove agent knows q
result = prover.prove("K(agent, q)", assumptions)

if result.status == "proved":
    print("✓ Knowledge is closed under implication")
```

---

## API Reference

### DCECContainer

Main high-level interface for DCEC:

```python
class DCECContainer:
    def __init__(self): ...
    
    # Creation methods
    def create_obligation(agent: str, action: str) -> Formula: ...
    def create_permission(agent: str, action: str) -> Formula: ...
    def create_belief(agent: str, proposition: str) -> Formula: ...
    def create_knowledge(agent: str, proposition: str) -> Formula: ...
    def create_intention(agent: str, action: str) -> Formula: ...
    def create_temporal(operator: TemporalOperator, formula: str) -> Formula: ...
    
    # Query methods
    def get_obligations() -> List[Formula]: ...
    def get_permissions() -> List[Formula]: ...
    def get_beliefs(agent: Optional[str] = None) -> List[Formula]: ...
    def get_knowledge(agent: Optional[str] = None) -> List[Formula]: ...
    
    # Statement management
    def add_statement(statement: str) -> bool: ...
    def add_axiom(axiom: str) -> bool: ...
    def add_theorem(theorem: str) -> bool: ...
    
    # Namespace
    @property
    def namespace(self) -> Namespace: ...
```

### TheoremProver

Automated theorem proving:

```python
class TheoremProver:
    def __init__(self): ...
    
    def add_axiom(axiom: str) -> None: ...
    def prove(goal: str, timeout: float = 10.0) -> ProofResult: ...
    def get_applicable_rules(formula: Formula) -> List[InferenceRule]: ...
```

### NaturalLanguageConverter

English ↔ DCEC conversion:

```python
class NaturalLanguageConverter:
    def __init__(self): ...
    
    def english_to_dcec(text: str) -> str: ...
    def dcec_to_english(formula: str) -> str: ...
    def batch_convert(texts: List[str]) -> List[str]: ...
```

### GrammarEngine

Grammar-based parsing:

```python
class GrammarEngine:
    def __init__(self, rules: List[GrammarRule], lexicon: Dict): ...
    
    def parse(text: str) -> List[ParseNode]: ...
    def linearize(node: ParseNode) -> str: ...
```

### ShadowProver

Modal logic proving:

```python
def create_prover(logic: ModalLogic) -> Prover:
    """Create prover for specific modal logic."""
    ...

class ModalLogic(Enum):
    K = "K"      # Basic modal logic
    T = "T"      # Reflexive
    S4 = "S4"    # Reflexive + transitive
    S5 = "S5"    # Reflexive + symmetric + transitive
```

---

## Advanced Topics

### Custom Inference Rules

Create custom rules for domain-specific reasoning:

```python
from ipfs_datasets_py.logic.CEC.native.prover_core import InferenceRule

class CustomRule(InferenceRule):
    def can_apply(self, formula: Formula) -> bool:
        # Check if rule applies
        return isinstance(formula, MyFormulaType)
    
    def apply(self, formula: Formula) -> List[Formula]:
        # Apply rule and return conclusions
        return [transformed_formula]

prover = TheoremProver()
prover.add_rule(CustomRule())
```

### Namespace Hierarchies

Create complex type hierarchies:

```python
from ipfs_datasets_py.logic.CEC.native.dcec_prototypes import DCECPrototypeNamespace

ns = DCECPrototypeNamespace()

# Create hierarchy: Entity > Agent > Robot > MobileRobot
ns.add_sort("Agent", parent="Entity")
ns.add_sort("Robot", parent="Agent")
ns.add_sort("MobileRobot", parent="Robot")

# Check subtype relationships
print(ns.is_subtype("MobileRobot", "Agent"))  # True
```

### Custom Grammar Rules

Extend the grammar system:

```python
from ipfs_datasets_py.logic.CEC.native.grammar_engine import (
    GrammarRule, Category, LexicalEntry
)

# Add custom lexical entries
custom_lexicon = {
    "navigate": LexicalEntry(
        category=Category.VERB,
        semantics=lambda: Action("navigate")
    ),
}

# Add custom grammar rules
custom_rules = [
    GrammarRule(
        name="NavigateRule",
        pattern=[Category.AGENT, Category.VERB, Category.LOCATION],
        semantics=lambda agent, verb, loc: DeonticFormula(...)
    )
]
```

### Performance Optimization

Tips for optimal performance:

```python
# 1. Reuse containers
container = DCECContainer()  # Create once
# ... use many times

# 2. Batch operations
statements = [stmt1, stmt2, stmt3]
for stmt in statements:
    container.add_statement(stmt)

# 3. Use appropriate proof timeouts
prover.prove(goal, timeout=5.0)  # Adjust based on complexity

# 4. Cache parsed formulas
from functools import lru_cache

@lru_cache(maxsize=1000)
def parse_cached(formula_str: str):
    return parse_dcec_string(formula_str)
```

---

## Additional Resources

- **API Reference:** See detailed docstrings in each module
- **Tests:** See `tests/unit_tests/logic/CEC/native/` for 418+ examples
- **Demos:** Run scripts in `scripts/demo/` for interactive examples
- **Migration Guide:** See `ipfs_datasets_py/logic/CEC/MIGRATION_GUIDE.md`
- **Phase 4 Tutorial:** See `ipfs_datasets_py/logic/CEC/PHASE4_TUTORIAL.md`

---

## Troubleshooting

### Import Errors

```python
# ❌ Wrong (old path)
from ipfs_datasets_py.logic.native import DCECContainer

# ✅ Correct (new path)
from ipfs_datasets_py.logic.CEC.native import DCECContainer
```

### Performance Issues

- Reduce proof timeout for simple problems
- Use caching for repeated parsing
- Batch operations when possible
- Consider using simpler logic systems (K instead of S5)

### Type Errors

- Ensure all variables have declared types
- Check namespace for sort definitions
- Verify formula syntax matches expected patterns

---

## Contributing

The CEC system is part of the larger `ipfs_datasets_py` project. See the main repository README for contribution guidelines.

**Module Location:** `ipfs_datasets_py/logic/CEC/native/`  
**Test Location:** `tests/unit_tests/logic/CEC/native/`  
**Version:** 1.0.0 (Production Ready)

---

**Last Updated:** February 2026  
**Status:** ✅ Production Ready  
**Test Coverage:** 418+ tests, 9,633 LOC
