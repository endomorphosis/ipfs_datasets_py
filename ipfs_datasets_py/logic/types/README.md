# Logic Types Module

**Created:** 2026-02-13  
**Updated:** 2026-02-13 (Phase 1 Enhancement)  
**Phase:** Phase 1 - Foundation (Type System Consolidation)  
**Purpose:** Centralize shared type definitions to resolve circular dependencies

## Overview

The `logic/types/` module provides a centralized location for type definitions shared across the logic module. This prevents circular dependencies between `tools`, `integration`, `TDFOL`, and other submodules.

## Design Philosophy

### Backward Compatibility
- Types remain defined in their original locations
- This module re-exports them for internal use
- External APIs are unchanged
- No breaking changes to existing code

### Usage Patterns

**Internal use (within logic module):**
```python
# Preferred for new code within logic module
from ipfs_datasets_py.logic.types import DeonticOperator, ProofResult
from ipfs_datasets_py.logic.types import LogicOperator, ConfidenceScore
from ipfs_datasets_py.logic.types import BridgeCapability, ConversionResult
```

**External use (outside logic module):**
```python
# Still supported for backward compatibility
from ipfs_datasets_py.logic.tools.deontic_logic_core import DeonticOperator
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult
```

## Module Structure

```
logic/types/
├── __init__.py             # Main exports, imports all type modules
├── common_types.py         # Common types, protocols, and enums (NEW)
├── deontic_types.py        # Deontic logic types (DeonticOperator, DeonticFormula, etc.)
├── proof_types.py          # Proof types (ProofStatus, ProofResult, ProofStep)
├── bridge_types.py         # Bridge and conversion types (NEW)
├── fol_types.py           # First-order logic types (NEW)
├── translation_types.py    # Translation types (LogicTranslationTarget, TranslationResult)
└── README.md              # This file
```

## Available Types

### Common Types (`common_types.py`) - NEW ✨
- `LogicOperator` - Enum for logical operators (AND, OR, NOT, IMPLIES, etc.)
- `Quantifier` - Enum for quantifiers (UNIVERSAL, EXISTENTIAL)
- `FormulaType` - Enum for formula types (FOL, MODAL, TEMPORAL, etc.)
- `ConfidenceScore` - Type alias for confidence scores (0.0-1.0)
- `ComplexityScore` - Type alias for complexity scores (0-100)
- `ComplexityMetrics` - Dataclass for formula complexity analysis
- `Formula` - Protocol for logical formulas (duck typing)
- `Prover` - Protocol for theorem provers
- `Converter` - Protocol for logic converters

### Bridge Types (`bridge_types.py`) - NEW ✨
- `BridgeCapability` - Enum for bridge capabilities
- `ConversionStatus` - Enum for conversion operation status
- `BridgeMetadata` - Dataclass for prover bridge metadata
- `ConversionResult` - Dataclass for conversion operation results
- `BridgeConfig` - Dataclass for bridge configuration
- `ProverRecommendation` - Dataclass for prover selection recommendations

### FOL Types (`fol_types.py`) - NEW ✨
- `FOLOutputFormat` - Enum for FOL output formats (PROLOG, TPTP, JSON, etc.)
- `PredicateCategory` - Enum for predicate categories
- `Predicate` - Dataclass for predicates in first-order logic
- `FOLFormula` - Dataclass for FOL formulas
- `FOLConversionResult` - Dataclass for FOL conversion results
- `PredicateExtraction` - Dataclass for predicate extraction results

### Deontic Types (`deontic_types.py`)
- `DeonticOperator` - Enum for deontic operators (OBLIGATION, PERMISSION, etc.)
- `DeonticFormula` - Dataclass for deontic logic formulas
- `DeonticRuleSet` - Collection of deontic rules
- `LegalAgent` - Dataclass for legal agents
- `LegalContext` - Dataclass for legal context
- `TemporalCondition` - Dataclass for temporal conditions
- `TemporalOperator` - Enum for temporal operators

### Proof Types (`proof_types.py`)
- `ProofStatus` - Enum for proof status (PROVED, DISPROVED, UNKNOWN, etc.)
- `ProofResult` - Dataclass for proof results
- `ProofStep` - Dataclass for individual proof steps

### Translation Types (`translation_types.py`)
- `LogicTranslationTarget` - Enum for translation targets (LEAN, COQ, SMT-LIB, etc.)
- `TranslationResult` - Dataclass for translation results
- `AbstractLogicFormula` - Platform-independent formula representation

## Benefits

1. **No Circular Dependencies:** Types can be imported without triggering circular imports
2. **Single Source of Truth:** One place to find all shared type definitions
3. **Backward Compatible:** Existing code continues to work without changes
4. **Future-Proof:** Easy to add new types or move existing ones
5. **Clear Separation:** Types vs. implementation logic
6. **Protocol Support:** Duck typing with type safety via Protocol classes
7. **Better IDE Support:** Centralized types improve autocomplete and type hints

## Protocol Classes (NEW)

The type system now includes Protocol classes for duck typing:

```python
from ipfs_datasets_py.logic.types import Formula, Prover, Converter

# Any class implementing these protocols can be used
class MyCustomProver:
    def prove(self, formula: str, timeout: int = 30) -> ProofResult:
        # Implementation
        pass
    
    def get_name(self) -> str:
        return "MyProver"

# MyCustomProver automatically satisfies the Prover protocol
prover: Prover = MyCustomProver()
```

## Type Aliases (NEW)

Convenient type aliases for common patterns:

```python
from ipfs_datasets_py.logic.types import ConfidenceScore, ComplexityScore

# Clear, self-documenting type hints
def calculate_confidence(formula: str) -> ConfidenceScore:
    # Returns float between 0.0 and 1.0
    return 0.85

def estimate_complexity(formula: str) -> ComplexityScore:
    # Returns int between 0 and 100
    return 42
```

## Migration Strategy

The types module uses a gradual migration approach:

1. **Phase 1 (Current):** Types module enhanced with new common, bridge, and FOL types
2. **Phase 2 (Future):** Internal logic module code updated to import from types
3. **Phase 3 (Future):** Consider moving actual type definitions to types module
4. **Phase 4 (Future):** Deprecate old import paths (with long deprecation period)

## Impact on Circular Dependencies

Before types module:
```
tools/deontic_logic_core.py
    ↓
integration/proof_execution_engine.py
    ↓
tools/logic_translation_core.py  ← Potential circular dependency
```

After types module:
```
types/{common,deontic,proof,bridge,fol}_types.py
    ↑
tools/deontic_logic_core.py    integration/proof_execution_engine.py
                                    ↓
                                types/translation_types.py
```

No circular dependencies - both tools and integration can import from types.

## Testing

Types are tested indirectly through the comprehensive test suite in `tests/unit_tests/logic/`:
- 483+ tests cover functionality using these types
- Type safety validated through mypy (if configured)
- Import structure verified in CI/CD
- Protocol classes tested via structural subtyping

## Usage Examples

### Using Common Types
```python
from ipfs_datasets_py.logic.types import (
    LogicOperator, Quantifier, ComplexityMetrics, ConfidenceScore
)

# Build a formula with typed operators
operators = [LogicOperator.AND, LogicOperator.IMPLIES]
quantifiers = [Quantifier.UNIVERSAL]

# Calculate complexity
metrics = ComplexityMetrics(
    quantifier_depth=2,
    nesting_level=3,
    operator_count=5,
    complexity_score=42
)

# Type-safe confidence score
confidence: ConfidenceScore = 0.85
```

### Using Bridge Types
```python
from ipfs_datasets_py.logic.types import (
    BridgeCapability, BridgeMetadata, ConversionResult, ConversionStatus
)

# Define bridge capabilities
bridge = BridgeMetadata(
    name="TDFOL-CEC Bridge",
    version="1.0.0",
    target_system="CEC",
    capabilities=[
        BridgeCapability.BIDIRECTIONAL_CONVERSION,
        BridgeCapability.INCREMENTAL_PROVING
    ],
    requires_external_prover=False,
    description="Bridges TDFOL to CEC theorem prover"
)

# Check capabilities
if bridge.supports_capability(BridgeCapability.OPTIMIZATION):
    # Use optimization features
    pass

# Handle conversion results
result = ConversionResult(
    status=ConversionStatus.SUCCESS,
    source_formula="∀x (P(x) → Q(x))",
    target_formula="(forall x (implies (P x) (Q x)))",
    source_format="TDFOL",
    target_format="CEC",
    confidence=0.95
)

if result.is_successful() and not result.has_warnings():
    # Use converted formula
    pass
```

### Using FOL Types
```python
from ipfs_datasets_py.logic.types import (
    FOLFormula, Predicate, PredicateCategory, FOLOutputFormat
)

# Create predicates
dog = Predicate(name="Dog", arity=1, category=PredicateCategory.ENTITY)
mammal = Predicate(name="Mammal", arity=1, category=PredicateCategory.ENTITY)

# Build FOL formula
formula = FOLFormula(
    formula_string="∀x (Dog(x) → Mammal(x))",
    predicates=[dog, mammal],
    quantifiers=[Quantifier.UNIVERSAL],
    confidence=0.9
)

# Check properties
if formula.has_quantifiers():
    names = formula.get_predicate_names()  # ["Dog", "Mammal"]
```

## Future Enhancements

- Add more shared types as identified during refactoring
- Consider moving actual type definitions here (breaking change)
- Add type validation utilities
- Generate type documentation automatically
- Add serialization/deserialization helpers
- Create type factories for common patterns

## References

- [LOGIC_IMPROVEMENT_PLAN.md](../../LOGIC_IMPROVEMENT_PLAN.md) - Phase 1 type system consolidation
- [IMPLEMENTATION_PROGRESS.md](../../IMPLEMENTATION_PROGRESS.md) - Progress tracking
- [CHANGELOG_LOGIC.md](../../CHANGELOG_LOGIC.md) - Change history
