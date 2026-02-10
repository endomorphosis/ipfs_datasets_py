# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/predicate_extractor.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## extract_logical_relations

```python
def extract_logical_relations(text: str) -> List[Dict[str, Any]]:
    """
    Extract logical relationships from text.

Args:
    text: Input text
    
Returns:
    List of relation dictionaries
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_predicates

```python
def extract_predicates(text: str, nlp_doc: Any = None) -> Dict[str, List[str]]:
    """
    Extract predicates from natural language text.

Args:
    text: Input text
    nlp_doc: Optional spaCy document for advanced parsing
    
Returns:
    Dictionary with predicate types and extracted predicates
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_variables

```python
def extract_variables(predicates: Dict[str, List[str]]) -> List[str]:
    """
    Generate appropriate variable names for predicates.

Args:
    predicates: Dictionary of extracted predicates
    
Returns:
    List of variable names
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## normalize_predicate

```python
def normalize_predicate(predicate: str) -> str:
    """
    Normalize a predicate name for logical representation.

Args:
    predicate: Raw predicate string
    
Returns:
    Normalized predicate name
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
