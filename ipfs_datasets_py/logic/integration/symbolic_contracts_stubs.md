# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/logic_integration/symbolic_contracts.py'

Files last updated: 1751408933.6664565

Stub file last updated: 2025-07-07 02:17:00

## ContractedFOLConverter

```python
@contract(pre_remedy=True, post_remedy=True, accumulate_errors=True, verbose=True)
class ContractedFOLConverter(Expression):
    """
    Contract-based FOL converter using SymbolicAI.

This class ensures that FOL conversion follows strict validation
contracts for both input and output.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ContractedFOLConverter

```python
class ContractedFOLConverter:
    """
    Fallback FOL converter without SymbolicAI contracts.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Expression

```python
class Expression:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FOLInput

```python
class FOLInput(BaseModel):
    """
    Input model for FOL conversion with validation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FOLOutput

```python
class FOLOutput(BaseModel):
    """
    Output model for FOL conversion with validation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FOLSyntaxValidator

```python
class FOLSyntaxValidator:
    """
    Specialized validator for FOL syntax and semantics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ValidationContext

```python
@dataclass
class ValidationContext:
    """
    Context for validation operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __call__

```python
def __call__(self, *args, **kwargs):
```
* **Async:** False
* **Method:** True
* **Class:** Expression

## __call__

```python
def __call__(self, input_data: FOLInput) -> FOLOutput:
    """
    Simple conversion without contracts.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## __init__

```python
def __init__(self, *args, **kwargs):
```
* **Async:** False
* **Method:** True
* **Class:** Expression

## __init__

```python
def __init__(self, strict: bool = True):
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## _analyze_structure

```python
def _analyze_structure(self, formula: str) -> Dict[str, Any]:
    """
    Analyze the structure of the formula.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## _check_semantics

```python
def _check_semantics(self, formula: str, structure: Dict[str, Any]) -> List[str]:
    """
    Check semantic issues.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## _check_syntax

```python
def _check_syntax(self, formula: str) -> List[str]:
    """
    Check basic syntax errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## _generate_suggestions

```python
def _generate_suggestions(self, formula: str, structure: Dict[str, Any]) -> List[str]:
    """
    Generate improvement suggestions.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## contract

```python
def contract(**kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_fol_converter

```python
def create_fol_converter(strict_validation: bool = True) -> ContractedFOLConverter:
    """
    Factory function to create FOL converter.

Args:
    strict_validation: Whether to use strict validation
    
Returns:
    ContractedFOLConverter instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decorator

```python
def decorator(cls):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## forward

```python
def forward(self, input_data: FOLInput) -> FOLOutput:
    """
    Main conversion logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## get_statistics

```python
def get_statistics(self) -> Dict[str, Any]:
    """
    Get conversion statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## post

```python
def post(self, output_data: FOLOutput) -> bool:
    """
    Validate output after processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## pre

```python
def pre(self, input_data: FOLInput) -> bool:
    """
    Validate input before processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContractedFOLConverter

## test_contracts

```python
def test_contracts():
    """
    Test function for contract system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## validate_components

```python
@field_validator("logical_components")
@classmethod
def validate_components(cls, v: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate logical components structure.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLOutput

## validate_fol_input

```python
def validate_fol_input(text: str, **kwargs) -> FOLInput:
    """
    Helper function to create validated FOL input.

Args:
    text: Input text
    **kwargs: Additional parameters for FOLInput
    
Returns:
    Validated FOLInput instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## validate_fol_syntax

```python
@field_validator("fol_formula")
@classmethod
def validate_fol_syntax(cls, v: str) -> str:
    """
    Validate FOL formula syntax.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLOutput

## validate_formula

```python
@beartype
def validate_formula(self, formula: str) -> Dict[str, Any]:
    """
    Comprehensive FOL formula validation.

Args:
    formula: FOL formula to validate
    
Returns:
    Dictionary with validation results
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLSyntaxValidator

## validate_predicates

```python
@field_validator("domain_predicates")
@classmethod
def validate_predicates(cls, v: List[str]) -> List[str]:
    """
    Validate domain predicates format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLInput

## validate_text_content

```python
@field_validator("text")
@classmethod
def validate_text_content(cls, v: str) -> str:
    """
    Validate that text contains meaningful content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FOLInput
