# Phase 4 Native Implementation - API Reference

## Table of Contents

- [Phase 4A: DCEC Parsing API](#phase-4a-dcec-parsing-api)
- [Phase 4B: Inference Rules API](#phase-4b-inference-rules-api)
- [Phase 4C: Grammar System API](#phase-4c-grammar-system-api)
- [Phase 4D: ShadowProver API](#phase-4d-shadowprover-api)
- [Wrapper APIs](#wrapper-apis)
- [Data Structures](#data-structures)
- [Enumerations](#enumerations)

---

## Phase 4A: DCEC Parsing API

### Core Functions

#### `parse_dcec_string(expression: str, namespace: Optional[DCECPrototypeNamespace] = None) → Formula`

Parse a DCEC string expression into a Formula object.

**Parameters:**
- `expression` (str): DCEC expression to parse
- `namespace` (Optional[DCECPrototypeNamespace]): Custom namespace for types

**Returns:**
- `Formula`: Parsed formula object

**Raises:**
- `ValueError`: If expression syntax is invalid

**Example:**
```python
formula = parse_dcec_string("P & Q")
formula = parse_dcec_string("O(pay_fine)")
```

#### `clean_dcec_expression(expression: str) → str`

Clean a DCEC expression by removing extra whitespace and normalizing.

**Parameters:**
- `expression` (str): Raw DCEC expression

**Returns:**
- `str`: Cleaned expression

**Example:**
```python
clean = clean_dcec_expression("  P  &  Q  ")
# Result: "P&Q"
```

#### `tokenize_dcec(expression: str) → List[str]`

Tokenize a DCEC expression into a list of tokens.

**Parameters:**
- `expression` (str): DCEC expression

**Returns:**
- `List[str]`: List of tokens

**Example:**
```python
tokens = tokenize_dcec("P & (Q -> R)")
# Result: ['P', '&', '(', 'Q', '->', 'R', ')']
```

### Classes

#### `DCECPrototypeNamespace`

Manages sorts, functions, and atomic formulas for DCEC.

**Methods:**

##### `add_sort(sort_name: str, parent: Optional[str] = None) → None`
Add a sort (type) to the namespace.

**Parameters:**
- `sort_name` (str): Name of the sort
- `parent` (Optional[str]): Parent sort for inheritance

**Example:**
```python
namespace = DCECPrototypeNamespace()
namespace.add_sort("Agent")
namespace.add_sort("Person", parent="Agent")
```

##### `add_function(name: str, domain: List[str], range: str) → None`
Add a function to the namespace.

**Parameters:**
- `name` (str): Function name
- `domain` (List[str]): Domain sorts
- `range` (str): Range sort

**Example:**
```python
namespace.add_function("believes", ["Agent", "Formula"], "Formula")
```

##### `add_atomic(name: str, args: List[str]) → None`
Add an atomic formula.

**Parameters:**
- `name` (str): Atomic formula name
- `args` (List[str]): Argument sorts

---

## Phase 4B: Inference Rules API

### Core Classes

#### `InferenceEngine`

Main engine for applying inference rules.

**Methods:**

##### `add_assumption(formula: Any) → None`
Add an assumption to the knowledge base.

**Parameters:**
- `formula` (Any): Formula to add

**Example:**
```python
engine = InferenceEngine()
engine.add_assumption("P")
engine.add_assumption("P -> Q")
```

##### `apply_all_rules() → List[Any]`
Apply all available inference rules.

**Returns:**
- `List[Any]`: Newly derived formulas

**Example:**
```python
results = engine.apply_all_rules()
```

##### `has_formula(formula: Any) → bool`
Check if formula is in the knowledge base.

**Parameters:**
- `formula` (Any): Formula to check

**Returns:**
- `bool`: True if formula exists

**Example:**
```python
if engine.has_formula("Q"):
    print("Q has been derived!")
```

##### `add_rule(rule: InferenceRule) → None`
Add a custom inference rule.

**Parameters:**
- `rule` (InferenceRule): Rule to add

#### `InferenceRule` (Abstract Base Class)

Base class for all inference rules.

**Methods to Implement:**

##### `can_apply(formulas: List[Any]) → bool`
Check if rule can be applied to formulas.

**Parameters:**
- `formulas` (List[Any]): Current formulas

**Returns:**
- `bool`: True if applicable

##### `apply(formulas: List[Any]) → List[Any]`
Apply the rule and return derived formulas.

**Parameters:**
- `formulas` (List[Any]): Input formulas

**Returns:**
- `List[Any]`: Derived formulas

**Example:**
```python
class MyRule(InferenceRule):
    def __init__(self):
        super().__init__("MyRule", "Custom rule")
    
    def can_apply(self, formulas):
        return any("P" in str(f) for f in formulas)
    
    def apply(self, formulas):
        return ["Q"]
```

### Available Rules

**Basic Logic (30 rules):**
- ModusPonens
- Simplification
- ConjunctionIntroduction
- Weakening
- DeMorgan
- Commutativity
- Distribution
- DisjunctiveSyllogism
- ImplicationElimination
- CutElimination
- DoubleNegation
- Contraposition
- HypotheticalSyllogism
- Exportation
- Absorption
- Association
- Resolution
- Transposition
- MaterialImplication
- ClaviusLaw
- Idempotence
- BiconditionalIntroduction
- BiconditionalElimination
- ConstructiveDilemma
- DestructiveDilemma
- TautologyIntroduction
- ContradictionElimination
- ConjunctionElimination
- (and 2 more variants)

**DCEC Categories:**
- Cognitive (15 rules)
- Deontic (7 rules)
- Temporal (15 rules)
- Advanced Logic (10 rules)
- Common Knowledge (13 rules)

---

## Phase 4C: Grammar System API

### Core Classes

#### `GrammarEngine`

Bottom-up chart parsing engine.

**Methods:**

##### `parse(text: str, grammar: Grammar) → List[ParseNode]`
Parse text using grammar.

**Parameters:**
- `text` (str): Text to parse
- `grammar` (Grammar): Grammar to use

**Returns:**
- `List[ParseNode]`: Parse trees

**Example:**
```python
engine = GrammarEngine()
grammar = DCECEnglishGrammar()
trees = engine.parse("Alice believes it is raining", grammar)
```

#### `DCECEnglishGrammar`

English grammar for DCEC.

**Properties:**
- `lexicon` (Dict): 100+ lexical entries
- `rules` (List): 50+ grammar rules

**Methods:**

##### `get_lexicon() → Dict[str, List[LexicalEntry]]`
Get the complete lexicon.

**Returns:**
- `Dict`: Word → [LexicalEntry]

##### `get_rules() → List[GrammarRule]`
Get all grammar rules.

**Returns:**
- `List[GrammarRule]`: Grammar rules

**Example:**
```python
grammar = DCECEnglishGrammar()
print(f"Lexicon size: {len(grammar.lexicon)}")
print(f"Rules: {len(grammar.rules)}")
```

#### `GrammarRule`

Represents a grammar rule.

**Attributes:**
- `lhs` (Category): Left-hand side category
- `rhs` (List[Category]): Right-hand side categories
- `semantic_action` (Callable): Semantic composition function

**Example:**
```python
rule = GrammarRule(
    lhs=Category.SENTENCE,
    rhs=[Category.NOUN, Category.VERB],
    semantic_action=lambda n, v: f"{v}({n})"
)
```

#### `LexicalEntry`

Lexical entry in the grammar.

**Attributes:**
- `word` (str): The word
- `category` (Category): Grammatical category
- `semantics` (str): Semantic representation

**Example:**
```python
entry = LexicalEntry(
    word="believes",
    category=Category.VERB,
    semantics="B"
)
```

### Enumerations

#### `Category`

Grammatical categories.

**Values:**
- SENTENCE
- NOUN
- VERB
- ADJECTIVE
- ADVERB
- DETERMINER
- PREPOSITION
- CONJUNCTION
- MODAL
- NEGATION

---

## Phase 4D: ShadowProver API

### Factory Functions

#### `create_prover(logic: ModalLogic) → ShadowProver`

Create a prover for specified modal logic.

**Parameters:**
- `logic` (ModalLogic): Logic system to use

**Returns:**
- `ShadowProver`: Prover instance

**Example:**
```python
k_prover = create_prover(ModalLogic.K)
s4_prover = create_prover(ModalLogic.S4)
s5_prover = create_prover(ModalLogic.S5)
```

#### `create_cognitive_prover() → CognitiveCalculusProver`

Create a cognitive calculus prover.

**Returns:**
- `CognitiveCalculusProver`: Cognitive prover

**Example:**
```python
prover = create_cognitive_prover()
proof = prover.prove("K(P) → P")
```

### Core Classes

#### `ShadowProver` (Abstract Base Class)

Base class for all provers.

**Methods:**

##### `prove(goal: Any, assumptions: Optional[List[Any]] = None, timeout: Optional[int] = None) → ProofTree`

Prove a goal with optional assumptions.

**Parameters:**
- `goal` (Any): Goal to prove
- `assumptions` (Optional[List[Any]]): List of assumptions
- `timeout` (Optional[int]): Timeout in seconds

**Returns:**
- `ProofTree`: Proof result

**Example:**
```python
prover = create_prover(ModalLogic.K)
proof = prover.prove("P → P")
print(f"Status: {proof.status}")
```

##### `prove_problem(problem: ProblemFile) → List[ProofTree]`

Prove all goals in a problem file.

**Parameters:**
- `problem` (ProblemFile): Problem to prove

**Returns:**
- `List[ProofTree]`: Proofs for each goal

**Example:**
```python
problem = parse_problem_file("problem.p")
proofs = prover.prove_problem(problem)
```

##### `get_statistics() → Dict[str, int]`

Get prover statistics.

**Returns:**
- `Dict[str, int]`: Statistics dictionary

**Example:**
```python
stats = prover.get_statistics()
print(f"Proofs attempted: {stats['proofs_attempted']}")
print(f"Proofs succeeded: {stats['proofs_succeeded']}")
```

##### `clear_cache() → None`

Clear the proof cache.

**Example:**
```python
prover.clear_cache()
```

#### `CognitiveCalculusProver`

Prover for cognitive calculus.

**Attributes:**
- `cognitive_axioms` (List[str]): 19 cognitive axioms

**Methods:**

##### `apply_cognitive_rules(formulas: List[Any]) → List[Any]`

Apply cognitive-specific rules.

**Parameters:**
- `formulas` (List[Any]): Current formulas

**Returns:**
- `List[Any]`: Derived formulas

**Example:**
```python
prover = create_cognitive_prover()
derived = prover.apply_cognitive_rules(["K(P)"])
# Applies K_truth: K(P) → P
```

### Problem Parsing

#### `parse_problem_file(filepath: str) → ProblemFile`

Parse a problem file.

**Parameters:**
- `filepath` (str): Path to problem file

**Returns:**
- `ProblemFile`: Parsed problem

**Raises:**
- `FileNotFoundError`: If file doesn't exist

**Example:**
```python
problem = parse_problem_file("problems/test.p")
```

#### `parse_problem_string(content: str, format_hint: Optional[str] = None) → ProblemFile`

Parse a problem string.

**Parameters:**
- `content` (str): Problem content
- `format_hint` (Optional[str]): 'tptp' or 'custom'

**Returns:**
- `ProblemFile`: Parsed problem

**Example:**
```python
problem = parse_problem_string("""
LOGIC: S4
GOALS:
□P → P
""")
```

---

## Wrapper APIs

### `ShadowProverWrapper`

Unified wrapper with native preference.

**Methods:**

#### `__init__(prover_path: Optional[Path] = None, use_docker: bool = False, prefer_native: bool = True)`

Initialize wrapper.

**Parameters:**
- `prover_path` (Optional[Path]): Path to Java ShadowProver
- `use_docker` (bool): Use Docker for Java
- `prefer_native` (bool): Prefer native implementation

**Example:**
```python
wrapper = ShadowProverWrapper(prefer_native=True)
```

#### `initialize() → bool`

Initialize the prover.

**Returns:**
- `bool`: True if successful

**Example:**
```python
if wrapper.initialize():
    print("Wrapper ready!")
```

#### `prove_formula(formula: str, assumptions: Optional[List[str]] = None, logic: str = "K") → ProofTask`

Prove a formula directly.

**Parameters:**
- `formula` (str): Formula to prove
- `assumptions` (Optional[List[str]]): Assumptions
- `logic` (str): Logic system ('K', 'S4', 'S5', 'cognitive')

**Returns:**
- `ProofTask`: Proof result

**Example:**
```python
task = wrapper.prove_formula("P → P", logic="K")
print(f"Result: {task.result}")
print(f"Native used: {task.native_used}")
```

#### `prove_problem(problem_file: str, timeout: int = 60, logic: Optional[str] = None) → ProofTask`

Prove from problem file.

**Parameters:**
- `problem_file` (str): Path to problem file
- `timeout` (int): Timeout in seconds
- `logic` (Optional[str]): Override logic

**Returns:**
- `ProofTask`: Proof result

**Example:**
```python
task = wrapper.prove_problem("test.p")
```

#### `get_native_status() → Dict[str, Any]`

Get native implementation status.

**Returns:**
- `Dict[str, Any]`: Status information

**Example:**
```python
status = wrapper.get_native_status()
print(f"Available: {status['available']}")
print(f"Version: {status['version']}")
print(f"Features: {status['features']}")
```

---

## Data Structures

### `Formula`

Represents a DCEC formula.

**Attributes:**
- `operator` (str): Main operator
- `operands` (List): Operands

### `ProofTree`

Represents a proof.

**Attributes:**
- `goal` (Any): Goal formula
- `steps` (List[ProofStep]): Proof steps
- `status` (ProofStatus): Proof status
- `logic` (ModalLogic): Logic used
- `metadata` (Dict): Additional metadata

### `ProofStep`

Single step in a proof.

**Attributes:**
- `formula` (Any): Formula at this step
- `rule` (str): Rule applied
- `justification` (str): Why this step

### `ProblemFile`

Problem file representation.

**Attributes:**
- `name` (str): Problem name
- `logic` (ModalLogic): Logic system
- `assumptions` (List[str]): Assumptions
- `goals` (List[str]): Goals to prove
- `metadata` (Dict): Additional data

### `ProofTask`

Result of a proof attempt.

**Attributes:**
- `problem_file` (str): Source problem
- `result` (ProverStatus): Result status
- `output` (Optional[str]): Output text
- `execution_time` (float): Time taken
- `error_message` (Optional[str]): Error if any
- `native_used` (bool): Whether native was used

---

## Enumerations

### `ModalLogic`

Modal logic systems.

**Values:**
- `K` - Basic modal logic
- `T` - K + reflexivity
- `S4` - T + transitivity
- `S5` - S4 + symmetry
- `D` - K + seriality
- `LP` - Linear logic

### `ProofStatus`

Proof result status.

**Values:**
- `SUCCESS` - Proof succeeded
- `FAILURE` - Proof failed
- `TIMEOUT` - Proof timed out
- `ERROR` - Error occurred
- `UNKNOWN` - Status unknown

### `ProverStatus`

Prover execution status.

**Values:**
- `SUCCESS` - Execution succeeded
- `FAILURE` - Execution failed
- `TIMEOUT` - Execution timed out
- `ERROR` - Execution error
- `UNKNOWN` - Status unknown

---

## Type Hints

All APIs include comprehensive type hints:

```python
from typing import List, Dict, Optional, Any, Callable

def parse_dcec_string(
    expression: str,
    namespace: Optional[DCECPrototypeNamespace] = None
) → Formula:
    ...

def create_prover(logic: ModalLogic) → ShadowProver:
    ...
```

Use with mypy for type checking:
```bash
mypy your_code.py
```

---

## Error Handling

### Common Exceptions

#### `ValueError`
Raised for invalid inputs:
```python
try:
    formula = parse_dcec_string("invalid((((")
except ValueError as e:
    print(f"Parse error: {e}")
```

#### `FileNotFoundError`
Raised when files don't exist:
```python
try:
    problem = parse_problem_file("missing.p")
except FileNotFoundError as e:
    print(f"File not found: {e}")
```

#### `ImportError`
Raised when components unavailable:
```python
try:
    from ipfs_datasets_py.logic.CEC.native import TableauProver
except ImportError:
    print("Tableau prover not available")
```

---

## Version Information

```python
from ipfs_datasets_py.logic.CEC.native import __version__

print(f"Version: {__version__}")
# Version: 0.8.0
```

---

## Best Practices

1. **Always specify types** when using type checkers
2. **Reuse provers** for better performance
3. **Clear caches** when processing many formulas
4. **Use native implementation** for best performance
5. **Handle exceptions** appropriately
6. **Check version compatibility** before using features

---

**API Version:** 0.8.0+  
**Last Updated:** 2026-02-12  
**Status:** Stable ✅
