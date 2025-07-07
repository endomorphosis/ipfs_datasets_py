# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/logic_formatter.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## convert_to_defeasible_format

```python
def convert_to_defeasible_format(deontic_formula: str, norm_type: str) -> str:
    """
    Convert deontic logic to defeasible logic format.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_to_prolog_format

```python
def convert_to_prolog_format(fol_formula: str) -> str:
    """
    Convert FOL to Prolog format.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_to_tptp_format

```python
def convert_to_tptp_format(fol_formula: str) -> str:
    """
    Convert FOL to TPTP format.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_deontic_metadata

```python
def extract_deontic_metadata(formula: str, norm_type: str) -> Dict[str, Any]:
    """
    Extract metadata from deontic logic formula.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_fol_metadata

```python
def extract_fol_metadata(formula: str) -> Dict[str, Any]:
    """
    Extract metadata from FOL formula.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_deontic

```python
def format_deontic(formula: str, norm_type: str, output_format: str = "symbolic", include_metadata: bool = True) -> Dict[str, Any]:
    """
    Format deontic logic formula for output.

Args:
    formula: Deontic logic formula string
    norm_type: Type of norm ('obligation', 'permission', 'prohibition')
    output_format: Output format ('symbolic', 'defeasible', 'json')
    include_metadata: Whether to include metadata
    
Returns:
    Formatted output dictionary
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_fol

```python
def format_fol(formula: str, output_format: str = "symbolic", include_metadata: bool = True) -> Dict[str, Any]:
    """
    Format First-Order Logic formula for output.

Args:
    formula: FOL formula string
    output_format: Output format ('symbolic', 'prolog', 'tptp', 'json')
    include_metadata: Whether to include metadata
    
Returns:
    Formatted output dictionary
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_output

```python
def format_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any], output_format: str = "json") -> Union[Dict[str, Any], str]:
    """
    Format complete output for logic conversion tools.

Args:
    formulas: List of converted formulas
    summary: Summary statistics
    output_format: Overall output format
    
Returns:
    Formatted output
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_text_output

```python
def format_text_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """
    Format output as human-readable text.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_xml_output

```python
def format_xml_output(formulas: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """
    Format output as XML.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_timestamp

```python
def get_timestamp() -> str:
    """
    Get current timestamp in ISO format.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## parse_deontic_to_json

```python
def parse_deontic_to_json(deontic_formula: str) -> Dict[str, Any]:
    """
    Parse deontic logic formula into structured JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## parse_fol_to_json

```python
def parse_fol_to_json(fol_formula: str) -> Dict[str, Any]:
    """
    Parse FOL formula into structured JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
