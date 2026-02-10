# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/fol_parser.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## build_fol_formula

```python
def build_fol_formula(quantifiers: List[Dict[str, Any]], predicates: Dict[str, List[str]], operators: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> str:
    """
    Build a First-Order Logic formula from parsed components.

Args:
    quantifiers: Parsed quantifier information
    predicates: Extracted predicates
    operators: Parsed logical operators
    relations: Extracted logical relations
    
Returns:
    FOL formula string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_to_prolog

```python
def convert_to_prolog(fol_formula: str) -> str:
    """
    Convert FOL formula to Prolog syntax.

Args:
    fol_formula: FOL formula in symbolic notation
    
Returns:
    Prolog clause string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_to_tptp

```python
def convert_to_tptp(fol_formula: str) -> str:
    """
    Convert FOL formula to TPTP syntax.

Args:
    fol_formula: FOL formula in symbolic notation
    
Returns:
    TPTP format string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## normalize_predicate_name

```python
def normalize_predicate_name(name: str) -> str:
    """
    Normalize predicate names for FOL.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## parse_logical_operators

```python
def parse_logical_operators(text: str) -> List[Dict[str, Any]]:
    """
    Parse logical operators from text.

Args:
    text: Input text
    
Returns:
    List of logical operator information
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## parse_quantifiers

```python
def parse_quantifiers(text: str) -> List[Dict[str, Any]]:
    """
    Parse quantifier words and expressions from text.

Args:
    text: Input text
    
Returns:
    List of quantifier information dictionaries
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## parse_simple_predicate

```python
def parse_simple_predicate(text: str) -> str:
    """
    Parse a simple predicate expression.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## validate_fol_syntax

```python
def validate_fol_syntax(formula: str) -> Dict[str, Any]:
    """
    Validate the syntax of a FOL formula.

Args:
    formula: FOL formula string
    
Returns:
    Validation result dictionary
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
