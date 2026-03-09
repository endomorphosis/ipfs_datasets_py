# CEC API Reference

**Version:** 1.0  
**Last Updated:** 2026-02-18  
**Python Version:** 3.12+

> **Complete reference** for all public APIs in the CEC (Cognitive Event Calculus) native Python implementation.

---

## 📋 Table of Contents

1. [Installation](#installation)
2. [Quick Import Guide](#quick-import-guide)
3. [Core Operators](#core-operators)
4. [Type System](#type-system)
5. [Formula Classes](#formula-classes)
6. [Container & Namespace](#container--namespace)
7. [Theorem Proving](#theorem-proving)
8. [Natural Language Processing](#natural-language-processing)
9. [Grammar Engine](#grammar-engine)
10. [Modal Logic](#modal-logic)
11. [Parsing & Cleaning](#parsing--cleaning)
12. [Problem File Parsing](#problem-file-parsing)
13. [Utility Functions](#utility-functions)
14. [Exceptions](#exceptions)

---

## 📦 Installation

```bash
pip install -e .
```

**Import the module:**
```python
from ipfs_datasets_py.logic.CEC import native
# Or import specific components
from ipfs_datasets_py.logic.CEC.native import DCECContainer, TheoremProver
```

---

## 🚀 Quick Import Guide

### Basic Usage

```python
# Essential imports for most use cases
from ipfs_datasets_py.logic.CEC.native import (
    DCECContainer,           # Main container for DCEC statements
    TheoremProver,           # Automated theorem prover
    NaturalLanguageConverter,# NL ↔ DCEC conversion
)
```

### Advanced Usage

```python
# Advanced imports for specific use cases
from ipfs_datasets_py.logic.CEC.native import (
    # Operators
    DeonticOperator, CognitiveOperator, TemporalOperator,
    # Formula classes
    DeonticFormula, CognitiveFormula, TemporalFormula,
    # Modal logic
    ShadowProver, ModalTableau, TableauProver,
    # Grammar engine
    GrammarEngine, DCECEnglishGrammar,
    # Parsing
    parse_dcec_string, validate_formula,
)
```

---

## 🎭 Core Operators

### DeonticOperator

Operators for normative/deontic reasoning.

```python
class DeonticOperator(Enum):
    OBLIGATION = "O"         # O(φ) - it is obligatory that φ
    PERMISSION = "P"         # P(φ) - it is permitted that φ
    PROHIBITION = "F"        # F(φ) - it is forbidden that φ
    SUPEREROGATION = "S"     # S(φ) - it is supererogatory that φ
    RIGHT = "R"              # R(φ) - φ is a right
    LIBERTY = "L"            # L(φ) - φ is a liberty/privilege
    POWER = "POW"            # POW(φ) - power to bring about φ
    IMMUNITY = "IMM"         # IMM(φ) - immunity from φ
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import DeonticOperator

# Get operator
op = DeonticOperator.OBLIGATION
print(op.value)  # "O"

# Use in formula
obligation = f"{DeonticOperator.OBLIGATION.value}(performTask(robot))"
# Output: "O(performTask(robot))"
```

---

### CognitiveOperator

Operators for cognitive/mental state reasoning.

```python
class CognitiveOperator(Enum):
    BELIEF = "B"             # B(agent, φ) - agent believes φ
    KNOWLEDGE = "K"          # K(agent, φ) - agent knows φ
    INTENTION = "I"          # I(agent, φ) - agent intends φ
    DESIRE = "D"             # D(agent, φ) - agent desires φ
    GOAL = "G"               # G(agent, φ) - agent has goal φ
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import CognitiveOperator

# Create belief
belief = f"{CognitiveOperator.BELIEF.value}(robot, taskComplete)"
# Output: "B(robot, taskComplete)"
```

---

### LogicalConnective

Standard logical connectives.

```python
class LogicalConnective(Enum):
    AND = "∧"                # Conjunction
    OR = "∨"                 # Disjunction
    NOT = "¬"                # Negation
    IMPLIES = "→"            # Implication
    BICONDITIONAL = "↔"      # Biconditional
    EXISTS = "∃"             # Existential quantifier
    FORALL = "∀"             # Universal quantifier
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import LogicalConnective

# Build complex formula
formula = f"A {LogicalConnective.IMPLIES.value} B"
# Output: "A → B"
```

---

### TemporalOperator

Operators for temporal reasoning.

```python
class TemporalOperator(Enum):
    ALWAYS = "□"             # Always/necessarily
    EVENTUALLY = "◊"         # Eventually/possibly
    NEXT = "X"               # Next time point
    UNTIL = "U"              # Until
    SINCE = "S"              # Since
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import TemporalOperator

# Always true
always = f"{TemporalOperator.ALWAYS.value}(safetyRule)"
# Output: "□(safetyRule)"
```

---

## 📐 Type System

### Sort

Represents a type/sort in the logic system.

```python
@dataclass(frozen=True)
class Sort:
    name: str
    parent: Optional['Sort'] = None
    
    def is_subtype_of(self, other: 'Sort') -> bool:
        """Check if this sort is a subtype of another."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import Sort

# Create sorts
entity = Sort("Entity")
agent = Sort("Agent", parent=entity)
robot = Sort("Robot", parent=agent)

# Check subtype
print(robot.is_subtype_of(agent))   # True
print(robot.is_subtype_of(entity))  # True
print(agent.is_subtype_of(robot))   # False
```

---

### Variable

Represents a logical variable with a sort.

```python
@dataclass(frozen=True)
class Variable:
    name: str
    sort: Sort
    
    def __str__(self) -> str:
        return f"{self.name}:{self.sort.name}"
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import Variable, Sort

# Create variable
agent_sort = Sort("Agent")
x = Variable("x", agent_sort)
print(x)  # "x:Agent"
```

---

### Function

Represents a function symbol.

```python
@dataclass
class Function:
    name: str
    argument_sorts: List[Sort]
    return_sort: Sort
    
    def arity(self) -> int:
        """Return the arity (number of arguments)."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import Function, Sort

# Create function
agent = Sort("Agent")
action = Sort("Action")
performs = Function("performs", [agent, action], Sort("Bool"))

print(performs)           # "performs(Agent, Action) -> Bool"
print(performs.arity())   # 2
```

---

### Predicate

Represents a predicate symbol.

```python
@dataclass
class Predicate:
    name: str
    argument_sorts: List[Sort]
    
    def arity(self) -> int:
        """Return the arity (number of arguments)."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import Predicate, Sort

# Create predicate
agent = Sort("Agent")
task = Sort("Task")
completes = Predicate("completes", [agent, task])

print(completes)           # "completes(Agent, Task)"
print(completes.arity())   # 2
```

---

## 🧩 Formula Classes

### Formula (Abstract Base)

Base class for all DCEC formulas.

```python
class Formula(ABC):
    @abstractmethod
    def to_string(self) -> str:
        """Convert formula to string representation."""
    
    @abstractmethod
    def get_free_variables(self) -> Set[Variable]:
        """Get all free variables in this formula."""
    
    @abstractmethod
    def substitute(self, var: Variable, term: Term) -> 'Formula':
        """Substitute a variable with a term."""
```

---

### AtomicFormula

Atomic/basic formula (predicate application).

```python
@dataclass
class AtomicFormula(Formula):
    predicate: Predicate
    arguments: List[Term]
    
    def to_string(self) -> str:
        """Convert to string: 'P(t1, t2, ...)'"""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import (
    AtomicFormula, Predicate, Sort, VariableTerm, Variable
)

# Create predicate
completes = Predicate("completes", [Sort("Agent"), Sort("Task")])

# Create arguments
robot = VariableTerm(Variable("robot", Sort("Agent")))
task = VariableTerm(Variable("task", Sort("Task")))

# Create atomic formula
formula = AtomicFormula(completes, [robot, task])
print(formula.to_string())  # "completes(robot, task)"
```

---

### DeonticFormula

Formula with deontic operator.

```python
@dataclass
class DeonticFormula(Formula):
    operator: DeonticOperator
    inner_formula: Formula
    
    def to_string(self) -> str:
        """Convert to string: 'O(φ)', 'P(φ)', etc."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import DeonticFormula, DeonticOperator, AtomicFormula

# Create obligation
inner = parse_dcec_string("performTask(robot)")
obligation = DeonticFormula(DeonticOperator.OBLIGATION, inner)
print(obligation.to_string())  # "O(performTask(robot))"
```

---

### CognitiveFormula

Formula with cognitive operator.

```python
@dataclass
class CognitiveFormula(Formula):
    operator: CognitiveOperator
    agent: Term
    inner_formula: Formula
    
    def to_string(self) -> str:
        """Convert to string: 'B(agent, φ)', 'K(agent, φ)', etc."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import CognitiveFormula, CognitiveOperator

# Create belief
agent = parse_term("robot")
inner = parse_dcec_string("taskComplete")
belief = CognitiveFormula(CognitiveOperator.BELIEF, agent, inner)
print(belief.to_string())  # "B(robot, taskComplete)"
```

---

### TemporalFormula

Formula with temporal operator.

```python
@dataclass
class TemporalFormula(Formula):
    operator: TemporalOperator
    inner_formula: Formula
    
    def to_string(self) -> str:
        """Convert to string: '□(φ)', '◊(φ)', etc."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import TemporalFormula, TemporalOperator

# Create "always" formula
inner = parse_dcec_string("safetyRule")
always = TemporalFormula(TemporalOperator.ALWAYS, inner)
print(always.to_string())  # "□(safetyRule)"
```

---

### ConnectiveFormula

Formula with logical connective.

```python
@dataclass
class ConnectiveFormula(Formula):
    connective: LogicalConnective
    left: Optional[Formula]     # None for unary NOT
    right: Formula
    
    def to_string(self) -> str:
        """Convert to string: 'φ ∧ ψ', '¬φ', etc."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import ConnectiveFormula, LogicalConnective

# Create implication: A → B
a = parse_dcec_string("A")
b = parse_dcec_string("B")
implies = ConnectiveFormula(LogicalConnective.IMPLIES, a, b)
print(implies.to_string())  # "A → B"

# Create negation: ¬A
not_a = ConnectiveFormula(LogicalConnective.NOT, None, a)
print(not_a.to_string())  # "¬A"
```

---

### QuantifiedFormula

Formula with quantifier (∀ or ∃).

```python
@dataclass
class QuantifiedFormula(Formula):
    quantifier: LogicalConnective  # FORALL or EXISTS
    variable: Variable
    inner_formula: Formula
    
    def to_string(self) -> str:
        """Convert to string: '∀x.φ', '∃x.φ'"""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import (
    QuantifiedFormula, LogicalConnective, Variable, Sort
)

# Create ∀x. P(x)
x = Variable("x", Sort("Agent"))
inner = parse_dcec_string("P(x)")
forall = QuantifiedFormula(LogicalConnective.FORALL, x, inner)
print(forall.to_string())  # "∀x:Agent. P(x)"
```

---

## 📦 Container & Namespace

### DCECContainer

Main container for managing DCEC statements.

```python
class DCECContainer:
    def __init__(self):
        """Initialize an empty DCEC container."""
    
    def create_obligation(self, agent: str, action: str) -> str:
        """Create an obligation formula: O(action(agent))"""
    
    def create_permission(self, agent: str, action: str) -> str:
        """Create a permission formula: P(action(agent))"""
    
    def create_prohibition(self, agent: str, action: str) -> str:
        """Create a prohibition formula: F(action(agent))"""
    
    def create_belief(self, agent: str, proposition: str) -> str:
        """Create a belief formula: B(agent, proposition)"""
    
    def create_knowledge(self, agent: str, proposition: str) -> str:
        """Create a knowledge formula: K(agent, proposition)"""
    
    def create_intention(self, agent: str, action: str) -> str:
        """Create an intention formula: I(agent, action)"""
    
    def add_statement(self, statement: str) -> None:
        """Add a DCEC statement to the container."""
    
    def get_statements(self) -> List[str]:
        """Get all statements in the container."""
    
    def clear(self) -> None:
        """Clear all statements from the container."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer

# Create container
container = DCECContainer()

# Add various statements
obligation = container.create_obligation("robot", "cleanRoom")
belief = container.create_belief("robot", "roomIsDirty")
intention = container.create_intention("robot", "startCleaning")

# Get all statements
print(f"Total statements: {len(container.get_statements())}")
for stmt in container.get_statements():
    print(f"  - {stmt}")

# Clear container
container.clear()
```

---

### DCECNamespace

Namespace management for DCEC symbols.

```python
class DCECNamespace:
    def __init__(self):
        """Initialize a DCEC namespace."""
    
    def declare_sort(self, name: str, parent: Optional[Sort] = None) -> Sort:
        """Declare a new sort/type."""
    
    def declare_variable(self, name: str, sort: Sort) -> Variable:
        """Declare a new variable."""
    
    def declare_function(self, name: str, arg_sorts: List[Sort], 
                         return_sort: Sort) -> Function:
        """Declare a new function symbol."""
    
    def declare_predicate(self, name: str, arg_sorts: List[Sort]) -> Predicate:
        """Declare a new predicate symbol."""
    
    def get_sort(self, name: str) -> Optional[Sort]:
        """Get a sort by name."""
    
    def get_variable(self, name: str) -> Optional[Variable]:
        """Get a variable by name."""
    
    def get_function(self, name: str) -> Optional[Function]:
        """Get a function by name."""
    
    def get_predicate(self, name: str) -> Optional[Predicate]:
        """Get a predicate by name."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import DCECNamespace

# Create namespace
ns = DCECNamespace()

# Declare sorts
entity = ns.declare_sort("Entity")
agent = ns.declare_sort("Agent", parent=entity)
robot = ns.declare_sort("Robot", parent=agent)

# Declare predicates
ns.declare_predicate("performs", [agent, ns.declare_sort("Action")])

# Retrieve symbols
performs = ns.get_predicate("performs")
print(performs)  # "performs(Agent, Action)"
```

---

## 🧠 Theorem Proving

### TheoremProver

Automated theorem prover with 50+ inference rules.

```python
class TheoremProver:
    def __init__(self, enable_cache: bool = True, debug: bool = False):
        """Initialize theorem prover.
        
        Args:
            enable_cache: Enable proof caching (100-20000x speedup)
            debug: Enable debug logging
        """
    
    def add_axiom(self, axiom: str) -> None:
        """Add an axiom to the knowledge base."""
    
    def add_axioms(self, axioms: List[str]) -> None:
        """Add multiple axioms at once."""
    
    def prove(self, goal: str, max_steps: int = 1000) -> ProofResult:
        """Attempt to prove a goal formula.
        
        Args:
            goal: Formula to prove
            max_steps: Maximum proof steps (default: 1000)
        
        Returns:
            ProofResult with is_proven, proof_steps, proof_tree
        """
    
    def clear(self) -> None:
        """Clear all axioms and cached proofs."""
    
    def get_axioms(self) -> List[str]:
        """Get all current axioms."""
    
    def enable_caching(self, enabled: bool = True) -> None:
        """Enable or disable proof caching."""
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get proof cache statistics."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import TheoremProver

# Create prover
prover = TheoremProver(enable_cache=True, debug=False)

# Add axioms
prover.add_axiom("A → B")
prover.add_axiom("B → C")
prover.add_axiom("A")

# Prove theorem
result = prover.prove("C")
print(f"Proven: {result.is_proven}")
print(f"Steps: {len(result.proof_steps)}")

# Cache statistics
stats = prover.get_cache_stats()
print(f"Cache hits: {stats['hits']}")
print(f"Cache misses: {stats['misses']}")
```

---

### ProofResult

Result of a proof attempt.

```python
@dataclass
class ProofResult:
    is_proven: bool                    # True if goal was proven
    goal: str                          # Goal formula
    proof_steps: List[str]             # List of proof steps
    proof_tree: Optional[ProofTree]    # Proof tree structure
    time_taken: float                  # Time in seconds
    cached: bool                       # True if result was cached
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
    
    def __str__(self) -> str:
        """Human-readable representation."""
```

**Example:**
```python
# After proving
result = prover.prove("B")

# Check result
if result.is_proven:
    print("✅ Proof succeeded!")
    print(f"Time: {result.time_taken:.4f}s")
    print(f"Cached: {result.cached}")
    print("\nProof steps:")
    for i, step in enumerate(result.proof_steps, 1):
        print(f"  {i}. {step}")
else:
    print("❌ Proof failed")
```

---

### InferenceEngine

Low-level inference engine (used internally by TheoremProver).

```python
class InferenceEngine:
    def apply_modus_ponens(self, implication: str, antecedent: str) -> Optional[str]:
        """Apply modus ponens: (A → B) ∧ A ⊢ B"""
    
    def apply_modus_tollens(self, implication: str, negated_consequent: str) -> Optional[str]:
        """Apply modus tollens: (A → B) ∧ ¬B ⊢ ¬A"""
    
    def apply_and_elimination(self, conjunction: str) -> List[str]:
        """Apply AND elimination: (A ∧ B) ⊢ A, B"""
    
    def apply_or_introduction(self, formula: str) -> List[str]:
        """Apply OR introduction: A ⊢ (A ∨ B)"""
    
    # ... 50+ more inference rules
```

---

## 🗣️ Natural Language Processing

### NaturalLanguageConverter

Convert between natural language and DCEC formulas.

```python
class NaturalLanguageConverter:
    def __init__(self):
        """Initialize NL converter with 100+ patterns."""
    
    def english_to_dcec(self, text: str) -> str:
        """Convert English text to DCEC formula.
        
        Args:
            text: English sentence
        
        Returns:
            DCEC formula string
        
        Raises:
            ConversionError: If conversion fails
        """
    
    def dcec_to_english(self, formula: str) -> str:
        """Convert DCEC formula to English text.
        
        Args:
            formula: DCEC formula string
        
        Returns:
            English sentence
        
        Raises:
            ConversionError: If conversion fails
        """
    
    def add_pattern(self, pattern: str, template: str) -> None:
        """Add custom conversion pattern."""
    
    def get_patterns(self) -> List[Tuple[str, str]]:
        """Get all conversion patterns."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import NaturalLanguageConverter

# Create converter
converter = NaturalLanguageConverter()

# English to DCEC
sentences = [
    "The robot must perform the task",
    "The robot believes the task is complete",
    "It is permitted to open the door"
]

for sentence in sentences:
    dcec = converter.english_to_dcec(sentence)
    print(f"'{sentence}' → {dcec}")

# DCEC to English
formulas = [
    "O(performTask(robot))",
    "B(robot, taskComplete)",
    "P(openDoor)"
]

for formula in formulas:
    english = converter.dcec_to_english(formula)
    print(f"{formula} → '{english}'")
```

---

### ConversionResult

Result of an NL conversion.

```python
@dataclass
class ConversionResult:
    success: bool
    formula: Optional[str]
    english: Optional[str]
    confidence: float          # 0.0 to 1.0
    pattern_used: Optional[str]
    error: Optional[str]
```

---

## 📝 Grammar Engine

### GrammarEngine

Grammar-based parsing engine.

```python
class GrammarEngine:
    def __init__(self):
        """Initialize grammar engine."""
    
    def parse(self, text: str, start_category: str = "S") -> Optional[ParseNode]:
        """Parse text using grammar rules.
        
        Args:
            text: Text to parse
            start_category: Starting category (default: "S" for sentence)
        
        Returns:
            ParseNode tree or None if parsing fails
        """
    
    def add_lexical_entry(self, word: str, category: str, semantics: str) -> None:
        """Add a lexical entry to the grammar."""
    
    def add_rule(self, rule: GrammarRule) -> None:
        """Add a grammar rule."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import GrammarEngine

# Create engine
grammar = GrammarEngine()

# Add lexical entries
grammar.add_lexical_entry("robot", "NP", "robot")
grammar.add_lexical_entry("must", "AUX", "obligation")
grammar.add_lexical_entry("clean", "V", "clean")

# Parse sentence
parse_tree = grammar.parse("robot must clean")
if parse_tree:
    print(f"Parse successful: {parse_tree}")
```

---

### DCECEnglishGrammar

Pre-built English grammar for DCEC.

```python
def create_dcec_grammar() -> DCECEnglishGrammar:
    """Create a pre-built DCEC English grammar.
    
    Returns:
        DCECEnglishGrammar with 200+ lexical entries and 50+ rules
    """

class DCECEnglishGrammar(GrammarEngine):
    """English grammar specialized for DCEC conversion."""
    
    def parse_to_dcec(self, text: str) -> str:
        """Parse English and convert directly to DCEC."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import create_dcec_grammar

# Create grammar
grammar = create_dcec_grammar()

# Parse to DCEC
dcec = grammar.parse_to_dcec("The robot must clean the room")
print(dcec)  # "O(clean(robot, room))"
```

---

## 🔮 Modal Logic

### ShadowProver

Shadow theorem prover for modal logics.

```python
class ShadowProver:
    def __init__(self, logic: ModalLogic = ModalLogic.K):
        """Initialize shadow prover.
        
        Args:
            logic: Modal logic system (K, S4, S5)
        """
    
    def prove(self, formula: str, axioms: List[str] = None) -> ProofResult:
        """Prove a modal formula."""
    
    def check_satisfiability(self, formula: str) -> bool:
        """Check if formula is satisfiable."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import ShadowProver, ModalLogic

# Create K prover
prover = ShadowProver(logic=ModalLogic.K)

# Prove modal formula
result = prover.prove("□(A → B) ∧ □A → □B")
print(f"Proven: {result.is_proven}")
```

---

### ModalTableau

Modal tableaux method for satisfiability checking.

```python
class ModalTableau:
    def __init__(self, logic: ModalLogic = ModalLogic.K):
        """Initialize modal tableau."""
    
    def check_satisfiability(self, formula: str) -> Tuple[bool, Optional[TableauNode]]:
        """Check satisfiability using tableaux method.
        
        Returns:
            (is_satisfiable, tableau_tree)
        """
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import ModalTableau

# Create tableau
tableau = ModalTableau()

# Check satisfiability
is_sat, tree = tableau.check_satisfiability("□A ∧ ◊¬A")
print(f"Satisfiable: {is_sat}")
```

---

## 🧹 Parsing & Cleaning

### Parsing Functions

```python
def parse_dcec_string(dcec_str: str) -> Formula:
    """Parse a DCEC string into a Formula object.
    
    Args:
        dcec_str: DCEC formula string
    
    Returns:
        Formula object
    
    Raises:
        DCECParsingError: If parsing fails
    """

def validate_formula(formula: str) -> bool:
    """Validate a DCEC formula string.
    
    Args:
        formula: Formula string to validate
    
    Returns:
        True if valid, False otherwise
    """

def parse_expression_to_token(expr: str) -> ParseToken:
    """Parse expression into token tree."""

def token_to_formula(token: ParseToken) -> Formula:
    """Convert token tree to Formula object."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import parse_dcec_string, validate_formula

# Parse DCEC string
formula = parse_dcec_string("O(performTask(robot)) → B(robot, mustWork)")
print(formula.to_string())

# Validate formula
is_valid = validate_formula("O(performTask(robot))")
print(f"Valid: {is_valid}")  # True

is_valid = validate_formula("O(invalid syntax")
print(f"Valid: {is_valid}")  # False
```

---

### Cleaning Functions

```python
def clean_dcec_expression(expr: str) -> str:
    """Clean and normalize a DCEC expression.
    
    Performs:
    - Whitespace normalization
    - Comment removal
    - Parenthesis consolidation
    - Symbol tucking
    """

def strip_whitespace(expr: str) -> str:
    """Remove unnecessary whitespace."""

def strip_comments(expr: str) -> str:
    """Remove comments from expression."""

def consolidate_parens(expr: str) -> str:
    """Consolidate nested parentheses."""

def check_parens(expr: str) -> bool:
    """Check if parentheses are balanced."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import clean_dcec_expression, check_parens

# Clean messy expression
dirty = "  O(  performTask( robot )  )  % comment"
clean = clean_dcec_expression(dirty)
print(clean)  # "O(performTask(robot))"

# Check parentheses
balanced = check_parens("O(A → B)")
print(f"Balanced: {balanced}")  # True

unbalanced = check_parens("O(A → B")
print(f"Balanced: {unbalanced}")  # False
```

---

## 📄 Problem File Parsing

### TPTPParser

Parser for TPTP (Thousands of Problems for Theorem Provers) format.

```python
class TPTPParser:
    def parse_file(self, filename: str) -> List[TPTPFormula]:
        """Parse a TPTP problem file."""
    
    def parse_string(self, content: str) -> List[TPTPFormula]:
        """Parse TPTP content from string."""
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import TPTPParser

# Create parser
parser = TPTPParser()

# Parse file
formulas = parser.parse_file("problem.p")
for formula in formulas:
    print(f"{formula.name}: {formula.formula}")
```

---

### Utility Functions

```python
def parse_problem_file(filename: str, format: str = "tptp") -> List[Formula]:
    """Parse a problem file (TPTP or custom format)."""

def parse_problem_string(content: str, format: str = "tptp") -> List[Formula]:
    """Parse problem content from string."""
```

---

## ⚠️ Exceptions

### DCECParsingError

Raised when DCEC parsing fails.

```python
class DCECParsingError(Exception):
    """Exception raised for DCEC parsing errors."""
    
    def __init__(self, message: str, expression: str, position: Optional[int] = None):
        """Initialize parsing error.
        
        Args:
            message: Error message
            expression: Expression that failed to parse
            position: Position in expression where error occurred
        """
```

**Example:**
```python
from ipfs_datasets_py.logic.CEC.native import parse_dcec_string, DCECParsingError

try:
    formula = parse_dcec_string("O(invalid syntax")
except DCECParsingError as e:
    print(f"Parsing error: {e}")
    print(f"Expression: {e.expression}")
    print(f"Position: {e.position}")
```

---

### ConversionError

Raised when NL conversion fails.

```python
class ConversionError(Exception):
    """Exception raised for conversion errors."""
```

---

## 📊 Feature Availability

Some features may not be available depending on dependencies:

```python
from ipfs_datasets_py.logic.CEC import native

# Check feature availability
print(f"Grammar available: {native.GRAMMAR_AVAILABLE}")
print(f"ShadowProver available: {native.SHADOWPROVER_AVAILABLE}")
print(f"Problem parser available: {native.PROBLEM_PARSER_AVAILABLE}")
```

---

## 🎓 Complete Examples

### Example 1: Robot Task Planning

```python
from ipfs_datasets_py.logic.CEC.native import (
    DCECContainer, TheoremProver, NaturalLanguageConverter
)

# Setup
container = DCECContainer()
prover = TheoremProver()
converter = NaturalLanguageConverter()

# Add rules in English
rules = [
    "The robot must clean the room",
    "The robot believes the room is dirty",
    "If the robot believes the room is dirty, then the robot intends to clean"
]

for rule in rules:
    dcec = converter.english_to_dcec(rule)
    container.add_statement(dcec)
    prover.add_axiom(dcec)

# Prove intention
result = prover.prove("I(robot, clean)")
print(f"Robot intends to clean: {result.is_proven}")
```

---

### Example 2: Legal Contract Reasoning

```python
from ipfs_datasets_py.logic.CEC.native import DCECContainer, TheoremProver

# Contract terms
container = DCECContainer()
prover = TheoremProver()

# Add obligations
container.create_obligation("contractor", "deliverProject")
container.create_obligation("client", "payInvoice")

# Add rules
prover.add_axiom("O(deliverProject(contractor)) → P(requestPayment(contractor))")
prover.add_axiom("O(payInvoice(client)) ∧ P(requestPayment(contractor)) → O(processPayment(client))")

# Check permissions and obligations
can_request = prover.prove("P(requestPayment(contractor))")
must_pay = prover.prove("O(processPayment(client))")

print(f"Contractor can request payment: {can_request.is_proven}")
print(f"Client must process payment: {must_pay.is_proven}")
```

---

## 📚 Additional Resources

- **[QUICKSTART.md](./QUICKSTART.md)** - 5-minute tutorial
- **[CEC_SYSTEM_GUIDE.md](./CEC_SYSTEM_GUIDE.md)** - Comprehensive guide
- **[STATUS.md](./STATUS.md)** - Implementation status
- **[DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)** - Development guide (coming soon)

---

## 🐛 Reporting Issues

Found a bug or have a feature request?

- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Discussions:** [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)

---

**Last Updated:** 2026-02-18  
**API Version:** 1.0.0  
**Python Version:** 3.12+
