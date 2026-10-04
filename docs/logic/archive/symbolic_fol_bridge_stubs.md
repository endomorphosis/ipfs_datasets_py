# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/logic_integration/symbolic_fol_bridge.py'

Files last updated: 1751408933.6664565

Stub file last updated: 2025-07-07 02:17:00

## Expression

```python
class Expression:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FOLConversionResult

```python
@dataclass
class FOLConversionResult:
    """
    Result of FOL conversion with metadata.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LogicalComponents

```python
@dataclass
class LogicalComponents:
    """
    Structure for holding extracted logical components.
    """
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

## SymbolicFOLBridge

```python
class SymbolicFOLBridge:
    """
    Bridge between SymbolicAI and existing FOL system.

This class provides the core integration functionality, allowing for
semantic analysis of natural language text and conversion to FOL formulas
with enhanced understanding through SymbolicAI.
    """
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

## __init__

```python
def __init__(self, confidence_threshold: float = 0.7, fallback_enabled: bool = True, enable_caching: bool = True):
    """
    Initialize the SymbolicFOL Bridge.

Args:
    confidence_threshold: Minimum confidence required for conversion
    fallback_enabled: Whether to fallback to original system on failure
    enable_caching: Whether to cache conversion results
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** FOLConversionResult

## _build_fol_formula

```python
def _build_fol_formula(self, components: LogicalComponents, output_format: str) -> Tuple[str, List[str]]:
    """
    Build FOL formula from extracted components.

Args:
    components: Extracted logical components
    output_format: Desired output format
    
Returns:
    Tuple of (fol_formula, reasoning_steps)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _fallback_conversion

```python
def _fallback_conversion(self, text: str, output_format: str) -> FOLConversionResult:
    """
    Fallback conversion using original FOL system.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _fallback_extraction

```python
def _fallback_extraction(self, text: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Fallback extraction using regex patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _initialize_fallback_system

```python
def _initialize_fallback_system(self):
    """
    Initialize fallback components from original FOL system.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _parse_comma_list

```python
def _parse_comma_list(self, text: str) -> List[str]:
    """
    Parse comma-separated list from SymbolicAI response.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _pattern_match_to_fol

```python
def _pattern_match_to_fol(self, components: LogicalComponents, reasoning_steps: List[str]) -> str:
    """
    Match logical patterns to generate FOL formulas.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _to_prolog_format

```python
def _to_prolog_format(self, formula: str) -> str:
    """
    Convert to Prolog format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## _to_tptp_format

```python
def _to_tptp_format(self, formula: str) -> str:
    """
    Convert to TPTP format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## clear_cache

```python
def clear_cache(self):
    """
    Clear the conversion cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## create_semantic_symbol

```python
@beartype
def create_semantic_symbol(self, text: str) -> Union[Symbol, None]:
    """
    Create a semantic symbol from natural language text.

Args:
    text: Natural language text to convert to semantic symbol
    
Returns:
    Symbol object in semantic mode, or None if creation fails
    
Raises:
    ValueError: If text is empty or invalid
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## extract_logical_components

```python
@beartype
def extract_logical_components(self, symbol: Symbol) -> LogicalComponents:
    """
    Extract logical components from a semantic symbol.

Args:
    symbol: Symbol object to analyze
    
Returns:
    LogicalComponents object with extracted elements
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## get_statistics

```python
def get_statistics(self) -> Dict[str, Any]:
    """
    Get statistics about the bridge usage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## query

```python
def query(self, prompt: str) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** Symbol

## semantic_to_fol

```python
@beartype
def semantic_to_fol(self, symbol: Symbol, output_format: str = "symbolic") -> FOLConversionResult:
    """
    Convert semantic symbol to FOL formula.

Args:
    symbol: Symbol object to convert
    output_format: Output format for FOL formula
    
Returns:
    FOLConversionResult with formula and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge

## validate_fol_formula

```python
def validate_fol_formula(self, formula: str) -> Dict[str, Any]:
    """
    Validate the syntax and structure of a FOL formula.

Args:
    formula: FOL formula to validate
    
Returns:
    Dictionary with validation results
    """
```
* **Async:** False
* **Method:** True
* **Class:** SymbolicFOLBridge
