# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/logic_integration/modal_logic_extension.py'

Files last updated: 1751408933.6664565

Stub file last updated: 2025-07-07 02:17:00

## AdvancedLogicConverter

```python
class AdvancedLogicConverter:
    """
    Advanced logic converter supporting multiple modal logics.
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

## LogicClassification

```python
@dataclass
class LogicClassification:
    """
    Classification result for identifying logic type.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ModalFormula

```python
@dataclass
class ModalFormula:
    """
    Represents a modal logic formula with metadata.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ModalLogicSymbol

```python
class ModalLogicSymbol(Symbol):
    """
    Extended Symbol class with modal logic operators.
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

## __init__

```python
def __init__(self, value: str, semantic: bool = False):
```
* **Async:** False
* **Method:** True
* **Class:** Symbol

## __init__

```python
def __init__(self, value: str, semantic: bool = True):
    """
    Initialize modal logic symbol.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## __init__

```python
def __init__(self, confidence_threshold: float = 0.7):
    """
    Initialize the converter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## _convert_to_deontic_logic

```python
def _convert_to_deontic_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
    """
    Convert text to deontic logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## _convert_to_epistemic_logic

```python
def _convert_to_epistemic_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
    """
    Convert text to epistemic logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## _convert_to_fol

```python
def _convert_to_fol(self, text: str, classification: LogicClassification) -> ModalFormula:
    """
    Convert text to standard First-Order Logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## _convert_to_modal_logic

```python
def _convert_to_modal_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
    """
    Convert text to alethic modal logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## _convert_to_temporal_logic

```python
def _convert_to_temporal_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
    """
    Convert text to temporal logic.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## belief

```python
def belief(self, agent: str = "agent") -> "ModalLogicSymbol":
    """
    Apply epistemic belief operator (B).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## convert_to_modal

```python
@beartype
def convert_to_modal(text: str, confidence_threshold: float = 0.7) -> ModalFormula:
    """
    Quick conversion to modal logic.

Args:
    text: Natural language text
    confidence_threshold: Minimum confidence for conversion
    
Returns:
    ModalFormula result
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## convert_to_modal_logic

```python
@beartype
def convert_to_modal_logic(self, text: str) -> ModalFormula:
    """
    Convert text to appropriate modal logic formula.

Args:
    text: Input natural language text
    
Returns:
    ModalFormula with converted logic
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## detect_logic_type

```python
@beartype
def detect_logic_type(self, text: str) -> LogicClassification:
    """
    Detect the type of logic most appropriate for the given text.

Args:
    text: Input natural language text
    
Returns:
    LogicClassification with detected type and confidence
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedLogicConverter

## detect_logic_type

```python
@beartype
def detect_logic_type(text: str) -> LogicClassification:
    """
    Quick logic type detection.

Args:
    text: Natural language text
    
Returns:
    LogicClassification result
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## knowledge

```python
def knowledge(self, agent: str = "agent") -> "ModalLogicSymbol":
    """
    Apply epistemic knowledge operator (K).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## necessarily

```python
def necessarily(self) -> "ModalLogicSymbol":
    """
    Apply necessity modal operator (□).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## obligation

```python
def obligation(self) -> "ModalLogicSymbol":
    """
    Apply deontic obligation operator (O).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## permission

```python
def permission(self) -> "ModalLogicSymbol":
    """
    Apply deontic permission operator (P).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## possibly

```python
def possibly(self) -> "ModalLogicSymbol":
    """
    Apply possibility modal operator (◇).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## prohibition

```python
def prohibition(self) -> "ModalLogicSymbol":
    """
    Apply deontic prohibition operator (F).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## query

```python
def query(self, prompt: str) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** Symbol

## temporal_always

```python
def temporal_always(self) -> "ModalLogicSymbol":
    """
    Apply temporal always operator (□).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## temporal_eventually

```python
def temporal_eventually(self) -> "ModalLogicSymbol":
    """
    Apply temporal eventually operator (◇).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## temporal_next

```python
def temporal_next(self) -> "ModalLogicSymbol":
    """
    Apply temporal next operator (X).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol

## temporal_until

```python
def temporal_until(self, condition: str) -> "ModalLogicSymbol":
    """
    Apply temporal until operator (U).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ModalLogicSymbol
