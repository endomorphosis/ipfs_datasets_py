# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/logic_integration/symbolic_logic_primitives.py'

Files last updated: 1751408933.6664565

Stub file last updated: 2025-07-07 02:17:00

## LogicPrimitives

```python
class LogicPrimitives(Primitive):
    """
    Custom primitives for logical operations using SymbolicAI.

This class extends SymbolicAI's primitive operations with logic-specific
functionality for natural language to FOL conversion, logical reasoning,
and formula manipulation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LogicalStructure

```python
@dataclass
class LogicalStructure:
    """
    Represents the logical structure of a statement.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Primitive

```python
class Primitive:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Symbol

```python
class Symbol:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, value: str, semantic: bool = False):
```
* **Async:** False
* **Method:** True
* **Class:** Symbol

## _analyze_structure

```python
@core.interpret(prompt="
        Analyze the logical structure of the given statement. Identify:
        1. Type of logical statement (universal, existential, conditional, etc.)
        2. Main subject and predicate
        3. Logical connectives present
        4. Variables and constants
        5. Overall complexity level
        
        Provide a structured analysis.
        ")
def _analyze_structure(text):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _convert_to_fol

```python
@core.interpret(prompt="
        Convert the given natural language statement to a formal First-Order Logic (FOL) formula.
        
        Instructions:
        1. Identify quantifiers (∀ for universal 'all/every', ∃ for existential 'some/exists')
        2. Extract predicates and relationships 
        3. Determine logical connectives (∧ for 'and', ∨ for 'or', → for 'implies', ¬ for 'not')
        4. Use proper FOL syntax with variables (x, y, z) and predicates
        5. Structure the formula logically
        
        Examples:
        - \"All cats are animals\" → ∀x (Cat(x) → Animal(x))
        - \"Some birds can fly\" → ∃x (Bird(x) ∧ CanFly(x))
        - \"If it rains, then the ground is wet\" → Rain → WetGround
        
        Return only the FOL formula in the requested format.
        ")
def _convert_to_fol(text):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _extract_predicates

```python
@core.interpret(prompt="
        Extract all predicates, verbs, and relationships from the text. Look for:
        - Action verbs: run, fly, study, love, hate
        - State verbs: is, are, has, have, can, must
        - Relationships: belongs to, part of, loves, studies
        
        Return them as a comma-separated list. Focus on the main predicates.
        ")
def _extract_predicates(text):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _extract_quantifiers

```python
@core.interpret(prompt="
        Extract all quantifiers from the given text. Look for:
        - Universal quantifiers: all, every, each, always, never
        - Existential quantifiers: some, exists, there is/are, at least one
        - Numerical quantifiers: many, few, most, several
        
        Return them as a comma-separated list. If no quantifiers found, return 'none'.
        ")
def _extract_quantifiers(text):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _fallback_analyze_structure

```python
def _fallback_analyze_structure(self) -> "Symbol":
    """
    Fallback structure analysis.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_extract_predicates

```python
def _fallback_extract_predicates(self) -> "Symbol":
    """
    Fallback predicate extraction using regex.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_extract_quantifiers

```python
def _fallback_extract_quantifiers(self) -> "Symbol":
    """
    Fallback quantifier extraction using regex.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_implies

```python
def _fallback_implies(self, other: "Symbol") -> "Symbol":
    """
    Fallback implication without SymbolicAI.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_logical_and

```python
def _fallback_logical_and(self, other: "Symbol") -> "Symbol":
    """
    Fallback logical AND without SymbolicAI.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_logical_or

```python
def _fallback_logical_or(self, other: "Symbol") -> "Symbol":
    """
    Fallback logical OR without SymbolicAI.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_negate

```python
def _fallback_negate(self) -> "Symbol":
    """
    Fallback negation without SymbolicAI.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_simplify

```python
def _fallback_simplify(self) -> "Symbol":
    """
    Fallback simplification.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _fallback_to_fol

```python
def _fallback_to_fol(self, output_format: str) -> "Symbol":
    """
    Fallback FOL conversion without SymbolicAI.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## _implies

```python
@core.interpret(prompt="
        Express a logical implication relationship 'if A then B' between two statements.
        Create a natural language implication or formal logic notation.
        ")
def _implies(premise, conclusion):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _logical_and

```python
@core.logic(operator="and")
def _logical_and(a: str, b: str):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _logical_or

```python
@core.logic(operator="or")
def _logical_or(a: str, b: str):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _negate

```python
@core.interpret(prompt="
        Create the logical negation of the given statement.
        Add 'not' or use negation symbols appropriately.
        ")
def _negate(statement):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _simplify

```python
@core.interpret(prompt="
        Simplify the given logical expression by:
        1. Removing redundant terms
        2. Applying logical equivalences
        3. Reducing complex nested expressions
        4. Making the expression more readable
        
        Return the simplified version.
        ")
def _simplify(expression):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _to_type

```python
def _to_type(self, result):
```
* **Async:** False
* **Method:** True
* **Class:** Symbol

## analyze_logical_structure

```python
@beartype
def analyze_logical_structure(self) -> "Symbol":
    """
    Analyze the logical structure of the statement.

Returns:
    Symbol containing the analysis
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## core

```python
class core:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_logic_symbol

```python
def create_logic_symbol(text: str, semantic: bool = True) -> Symbol:
    """
    Create a Symbol with logic primitives enabled.

Args:
    text: Text content for the symbol
    semantic: Whether to enable semantic mode
    
Returns:
    Symbol with logic primitive methods available
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_predicates

```python
@beartype
def extract_predicates(self) -> "Symbol":
    """
    Extract predicates and relationships from text.

Returns:
    Symbol containing identified predicates
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## extract_quantifiers

```python
@beartype
def extract_quantifiers(self) -> "Symbol":
    """
    Extract quantifiers from natural language text.

Returns:
    Symbol containing identified quantifiers
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## get_available_primitives

```python
def get_available_primitives() -> List[str]:
    """
    Get list of available logic primitive methods.

Returns:
    List of method names
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## implies

```python
@beartype
def implies(self, other: "Symbol") -> "Symbol":
    """
    Logical implication.

Args:
    other: Symbol representing the conclusion
    
Returns:
    Symbol representing the implication
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## interpret

```python
@staticmethod
def interpret(prompt: str):
```
* **Async:** False
* **Method:** True
* **Class:** core

## logic

```python
@staticmethod
def logic(operator: str):
```
* **Async:** False
* **Method:** True
* **Class:** core

## logical_and

```python
@beartype
def logical_and(self, other: "Symbol") -> "Symbol":
    """
    Semantic logical conjunction.

Args:
    other: Another Symbol to combine with logical AND
    
Returns:
    Symbol representing the logical conjunction
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## logical_or

```python
@beartype
def logical_or(self, other: "Symbol") -> "Symbol":
    """
    Semantic logical disjunction.

Args:
    other: Another Symbol to combine with logical OR
    
Returns:
    Symbol representing the logical disjunction
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## make_bound_method

```python
def make_bound_method(m, s):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## negate

```python
@beartype
def negate(self) -> "Symbol":
    """
    Logical negation.

Returns:
    Symbol representing the negation
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## simplify_logic

```python
@beartype
def simplify_logic(self) -> "Symbol":
    """
    Simplify logical expressions.

Returns:
    Symbol containing simplified logic
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## test_primitives

```python
def test_primitives():
    """
    Test function for logic primitives.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_fol

```python
@beartype
def to_fol(self, output_format: str = "symbolic") -> "Symbol":
    """
    Convert natural language to First-Order Logic.

Args:
    output_format: Format for the output ("symbolic", "prolog", "tptp")
    
Returns:
    Symbol containing the FOL formula
    """
```
* **Async:** False
* **Method:** True
* **Class:** LogicPrimitives

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
