# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/deontic_parser.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## analyze_normative_sentence

```python
def analyze_normative_sentence(sentence: str, document_type: str) -> Optional[Dict[str, Any]]:
    """
    Analyze a single sentence for normative content.

Args:
    sentence: Input sentence
    document_type: Type of legal document
    
Returns:
    Normative element dictionary or None
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## build_deontic_formula

```python
def build_deontic_formula(element: Dict[str, Any]) -> str:
    """
    Build a deontic logic formula from normative elements.

Args:
    element: Normative element dictionary
    
Returns:
    Deontic logic formula string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## detect_normative_conflicts

```python
def detect_normative_conflicts(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect potential conflicts between normative statements.

Args:
    elements: List of normative elements
    
Returns:
    List of detected conflicts
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_conditions

```python
def extract_conditions(sentence: str) -> List[str]:
    """
    Extract conditions under which the norm applies.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_exceptions

```python
def extract_exceptions(sentence: str) -> List[str]:
    """
    Extract exceptions and exemptions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_legal_action

```python
def extract_legal_action(sentence: str) -> List[str]:
    """
    Extract legal actions (what must/may/cannot be done).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_legal_subject

```python
def extract_legal_subject(sentence: str) -> List[str]:
    """
    Extract legal subjects (who the norm applies to).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_normative_elements

```python
def extract_normative_elements(text: str, document_type: str = "statute") -> List[Dict[str, Any]]:
    """
    Extract normative elements from legal text.

Args:
    text: Legal text input
    document_type: Type of legal document
    
Returns:
    List of normative element dictionaries
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_temporal_constraints

```python
def extract_temporal_constraints(sentence: str) -> List[Dict[str, str]]:
    """
    Extract temporal constraints (deadlines, periods, etc.).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## identify_obligations

```python
def identify_obligations(elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Identify and categorize different types of obligations.

Args:
    elements: List of normative elements
    
Returns:
    Categorized obligations dictionary
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## normalize_predicate_name

```python
def normalize_predicate_name(name: str) -> str:
    """
    Normalize predicate names for deontic logic.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
