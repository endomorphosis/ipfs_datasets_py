# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/text_to_fol.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:13

## calculate_conversion_confidence

```python
def calculate_conversion_confidence(sentence: str, fol_formula: str, predicates: Dict[str, List[str]], quantifiers: List[Dict[str, Any]]) -> float:
    """
    Calculate confidence score for FOL conversion.

Args:
    sentence: Original sentence
    fol_formula: Generated FOL formula
    predicates: Extracted predicates
    quantifiers: Parsed quantifiers
    
Returns:
    Confidence score between 0.0 and 1.0
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_text_to_fol

```python
async def convert_text_to_fol(text_input: Union[str, Dict[str, Any]], domain_predicates: Optional[List[str]] = None, output_format: str = "json", confidence_threshold: float = 0.7, include_metadata: bool = True) -> Dict[str, Any]:
    """
    Convert natural language text to First-Order Logic.

This tool converts natural language statements into First-Order Logic (FOL)
formulas for formal reasoning, theorem proving, and logical analysis.

Args:
    text_input: String or dataset containing natural language text
    domain_predicates: Optional list of domain-specific predicates
    output_format: Format for FOL output ('prolog', 'tptp', 'json', 'symbolic')
    confidence_threshold: Minimum confidence for conversion (0.0-1.0)
    include_metadata: Whether to include conversion metadata

Returns:
    Dict containing:
    - status: "success" or "error"
    - fol_formulas: List of converted formulas with metadata
    - summary: Conversion statistics and analysis
    - message: Error message if status is "error"

Raises:
    ValueError: If text_input is invalid or parameters are malformed
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## count_logical_indicators

```python
def count_logical_indicators(sentence: str) -> int:
    """
    Count logical indicator words in sentence.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## estimate_formula_complexity

```python
def estimate_formula_complexity(formula: str) -> float:
    """
    Estimate the complexity of a FOL formula.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## estimate_sentence_complexity

```python
def estimate_sentence_complexity(sentence: str) -> float:
    """
    Estimate the logical complexity of a sentence.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_predicate_names

```python
def extract_predicate_names(predicates: Dict[str, List[str]]) -> List[str]:
    """
    Extract all predicate names from predicates dictionary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_text_from_dataset

```python
def extract_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """
    Extract text strings from dataset dictionary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_operator_distribution

```python
def get_operator_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Get distribution of logical operators in results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_quantifier_distribution

```python
def get_quantifier_distribution(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Get distribution of quantifier types in results.
    """
```
* **Async:** False
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

## text_to_fol

```python
async def text_to_fol(text_input: Union[str, Dict[str, Any]], domain_predicates: Optional[List[str]] = None, output_format: str = "json", include_metadata: bool = True, confidence_threshold: float = 0.5) -> Dict[str, Any]:
    """
    MCP tool function for converting text to FOL.

Args:
    text_input: Natural language text or dataset to convert
    domain_predicates: Optional list of domain-specific predicates
    output_format: Output format ('json', 'prolog', 'tptp')
    include_metadata: Whether to include metadata in results
    confidence_threshold: Minimum confidence score for results
    
Returns:
    Dict with conversion results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
