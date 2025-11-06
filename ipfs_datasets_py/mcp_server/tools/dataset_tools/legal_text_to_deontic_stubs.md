# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/legal_text_to_deontic.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## calculate_deontic_confidence

```python
def calculate_deontic_confidence(element: Dict[str, Any], deontic_formula: str) -> float:
    """
    Calculate confidence score for deontic logic conversion.

Args:
    element: Normative element dictionary
    deontic_formula: Generated deontic logic formula
    
Returns:
    Confidence score between 0.0 and 1.0
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_legal_text_to_deontic

```python
async def convert_legal_text_to_deontic(legal_text: Union[str, Dict[str, Any]], jurisdiction: str = "us", document_type: str = "statute", output_format: str = "json", extract_obligations: bool = True, include_exceptions: bool = True) -> Dict[str, Any]:
    """
    Convert legal text to deontic logic.

This tool converts legal text (statutes, regulations, contracts) into deontic
logic for legal reasoning, compliance checking, and normative analysis.

Args:
    legal_text: String or dataset containing legal text
    jurisdiction: Legal jurisdiction context ('us', 'eu', 'uk', 'international')
    document_type: Type of legal document ('statute', 'regulation', 'contract', 'policy')
    output_format: Format for deontic logic output ('symbolic', 'defeasible', 'json')
    extract_obligations: Whether to extract obligation structures
    include_exceptions: Whether to include exception handling

Returns:
    Dict containing:
    - status: "success" or "error"
    - deontic_formulas: List of converted formulas with metadata
    - normative_structure: Analysis of normative relationships
    - legal_entities: Identified legal subjects
    - actions: Extracted legal actions
    - temporal_constraints: Time-based requirements
    - message: Error message if status is "error"

Raises:
    ValueError: If legal_text is invalid or parameters are malformed
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## convert_to_defeasible_logic

```python
def convert_to_defeasible_logic(deontic_formula: str, norm_type: str, exceptions: List[str]) -> str:
    """
    Convert deontic logic formula to defeasible logic representation.

Args:
    deontic_formula: Original deontic logic formula
    norm_type: Type of norm (obligation, permission, prohibition)
    exceptions: List of exceptions
    
Returns:
    Defeasible logic formula string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_all_legal_actions

```python
def extract_all_legal_actions(results: List[Dict[str, Any]]) -> List[str]:
    """
    Extract all unique legal actions from results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_all_legal_entities

```python
def extract_all_legal_entities(results: List[Dict[str, Any]]) -> List[str]:
    """
    Extract all unique legal entities from results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_all_temporal_constraints

```python
def extract_all_temporal_constraints(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Extract all temporal constraints from results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_legal_text_from_dataset

```python
def extract_legal_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """
    Extract legal text strings from dataset dictionary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## legal_text_to_deontic

```python
async def legal_text_to_deontic(text_input: Union[str, Dict[str, Any]], jurisdiction: str = "us", document_type: str = "statute", output_format: str = "json", extract_obligations: bool = True, include_exceptions: bool = True) -> Dict[str, Any]:
    """
    MCP tool function for converting legal text to deontic logic.

Args:
    text_input: Legal text or dataset to convert
    jurisdiction: Legal jurisdiction context
    document_type: Type of legal document
    output_format: Output format for the results
    extract_obligations: Whether to extract obligation statements
    include_exceptions: Whether to include exception handling
    
Returns:
    Dict with conversion results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## main

```python
async def main() -> Dict[str, Any]:
    """
    Main function for MCP tool registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## normalize_exception

```python
def normalize_exception(exception: str) -> str:
    """
    Normalize exception text into a logical predicate.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
