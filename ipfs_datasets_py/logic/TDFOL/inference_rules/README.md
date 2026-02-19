# TDFOL Inference Rules Package

This package contains all 60 inference rules for Temporal Deontic First-Order Logic (TDFOL), organized into focused modules by logic type.

## Package Structure

```
inference_rules/
├── __init__.py              # Package exports and get_all_tdfol_rules()
├── base.py                  # TDFOLInferenceRule abstract base class
├── propositional.py         # 13 propositional logic rules
├── first_order.py           # 2 first-order logic rules
├── temporal.py              # 20 temporal logic (LTL) rules
├── deontic.py               # 16 deontic logic (SDL) rules
├── temporal_deontic.py      # 9 combined temporal-deontic rules
└── README.md                # This file
```

## Module Organization

### Base Module (`base.py`)
- **TDFOLInferenceRule**: Abstract base class for all inference rules
- Defines the common interface: `apply()`, `is_applicable()`, `name`, `description`

### Propositional Logic (`propositional.py`) - 13 Rules
Basic propositional reasoning rules:
- **Modus Ponens**: φ, φ→ψ ⊢ ψ
- **Modus Tollens**: φ→ψ, ¬ψ ⊢ ¬φ
- **Disjunctive Syllogism**: φ∨ψ, ¬φ ⊢ ψ
- **Hypothetical Syllogism**: φ→ψ, ψ→χ ⊢ φ→χ
- **Conjunction Introduction**: φ, ψ ⊢ φ∧ψ
- **Conjunction Elimination** (Left/Right): φ∧ψ ⊢ φ, φ∧ψ ⊢ ψ
- **Disjunction Introduction**: φ ⊢ φ∨ψ
- **Double Negation** (Elimination/Introduction): ¬¬φ ⊢ φ, φ ⊢ ¬¬φ
- **Contraposition**: φ→ψ ⊢ ¬ψ→¬φ
- **De Morgan's Laws** (And/Or): ¬(φ∧ψ) ⊢ ¬φ∨¬ψ, ¬(φ∨ψ) ⊢ ¬φ∧¬ψ

### First-Order Logic (`first_order.py`) - 2 Rules
Quantifier reasoning rules:
- **Universal Instantiation**: ∀x.φ(x) ⊢ φ(t)
- **Existential Generalization**: φ(t) ⊢ ∃x.φ(x)

### Temporal Logic (`temporal.py`) - 20 Rules
Linear Temporal Logic (LTL) reasoning:

**Modal Axioms:**
- **K Axiom**: □(φ → ψ) → (□φ → □ψ)
- **T Axiom**: □φ ⊢ φ
- **S4 Axiom**: □φ ⊢ □□φ
- **S5 Axiom**: ◊φ ⊢ □◊φ

**Basic Operators:**
- **Eventually Introduction**: φ ⊢ ◊φ
- **Always Necessitation**: ⊢φ → ⊢□φ

**Until/Release:**
- **Until Unfolding**: φ U ψ ⊢ ψ ∨ (φ ∧ X(φ U ψ))
- **Until Induction**: ψ ∨ (φ ∧ X(φ U ψ)) ⊢ φ U ψ
- **Until-Release Duality**: φ U ψ ⊢ ¬(¬φ R ¬ψ)
- **Release Coinduction**: φ R ψ ⊢ ψ ∧ (φ ∨ X(φ R ψ))

**Distribution:**
- **Always Distribution**: □(φ ∧ ψ) ⊢ □φ ∧ □ψ
- **Next Distribution**: X(φ ∧ ψ) ⊢ Xφ ∧ Xψ
- **Eventually Distribution**: ◊(φ ∧ ψ) → ◊φ

**Expansion:**
- **Eventually Expansion**: ◊φ ⊢ φ ∨ X◊φ
- **Always-Eventually Expansion**: □◊φ ⊢ ◊φ ∧ □◊φ
- **Weak Until Expansion**: φ W ψ ⊢ (φ U ψ) ∨ □φ

**Aggregation/Contraction:**
- **Eventually Aggregation**: ◊φ ∨ ◊ψ ⊢ ◊(φ ∨ ψ)
- **Eventually-Always Contraction**: ◊□φ, φ ⊢ □φ
- **Temporal Induction**: □(φ → Xφ), φ ⊢ □φ
- **Until Induction Step**: φ U ψ ⊢ ψ ∨ (φ ∧ X(φ U ψ))

### Deontic Logic (`deontic.py`) - 16 Rules
Standard Deontic Logic (SDL) reasoning:

**Axioms:**
- **K Axiom**: O(φ → ψ) → (Oφ → Oψ)
- **D Axiom**: Oφ → ¬O¬φ

**Operators:**
- **Prohibition Equivalence**: Fφ ↔ O¬φ
- **Permission Negation**: Pφ ↔ ¬O¬φ
- **Obligation Consistency**: Oφ, Oψ ⊢ O(φ ∧ ψ)
- **Permission Introduction**: φ ⊢ Pφ

**Transformations:**
- **Deontic Necessitation**: ⊢φ → ⊢Oφ
- **Prohibition from Obligation**: Oφ, O¬ψ ⊢ F(φ ∧ ψ)
- **Obligation Weakening**: O(φ ∧ ψ) ⊢ Oφ
- **Permission Strengthening**: Pφ ⊢ P(φ ∨ ψ)
- **Prohibition Contraposition**: F(φ → ψ) ⊢ Oφ → Fψ
- **Deontic Distribution**: O(φ ∧ ψ) ⊢ Oφ ∧ Oψ

**Relationships:**
- **Permission-Prohibition Duality**: Pφ ↔ ¬Fφ
- **Obligation-Permission Implication**: Oφ → Pφ
- **Contrary-to-Duty**: Oφ, O(¬φ → ψ) ⊢ O(φ ∨ ψ)
- **Deontic Detachment**: Oφ, O(φ → ψ) ⊢ Oψ

### Temporal-Deontic Logic (`temporal_deontic.py`) - 9 Rules
Combined temporal and deontic reasoning:

**Temporal Obligations:**
- **Temporal Obligation Persistence**: Oφ ⊢ O(φ ∨ XOφ)
- **Obligation Eventually**: Oφ ⊢ ◊φ
- **Future Obligation Persistence**: XOφ → O(φ ∨ XOφ)

**Temporal Permissions:**
- **Always Permission**: □Pφ ⊢ P□φ
- **Permission Temporal Weakening**: P□φ ⊢ □Pφ

**Combined Operators:**
- **Deontic-Temporal Introduction**: Oφ, □φ ⊢ O□φ
- **Until Obligation**: O(φ U ψ) ⊢ Oψ ∨ (Oφ ∧ XO(φ U ψ))
- **Eventually Forbidden**: ◊Fφ ⊢ F◊φ
- **Always Obligation Distribution**: O□φ ⊢ □Oφ

## Usage

### Importing All Rules

```python
from ipfs_datasets_py.logic.TDFOL.inference_rules import get_all_tdfol_rules

# Get list of all 60 rule instances
rules = get_all_tdfol_rules()
print(f"Loaded {len(rules)} inference rules")
```

### Importing Specific Rules

```python
from ipfs_datasets_py.logic.TDFOL.inference_rules import (
    ModusPonensRule,
    TemporalKAxiomRule,
    DeonticKAxiomRule,
)

# Use individual rules
mp_rule = ModusPonensRule()
print(mp_rule.name)
print(mp_rule.description)
```

### Importing by Module

```python
from ipfs_datasets_py.logic.TDFOL.inference_rules import propositional
from ipfs_datasets_py.logic.TDFOL.inference_rules import temporal
from ipfs_datasets_py.logic.TDFOL.inference_rules import deontic

# Access rules from specific modules
mp = propositional.ModusPonensRule()
k_temporal = temporal.TemporalKAxiomRule()
k_deontic = deontic.DeonticKAxiomRule()
```

## Migration Guide

### For External Users

If you were importing from the old `tdfol_inference_rules` module:

**Before:**
```python
from ipfs_datasets_py.logic.TDFOL.tdfol_inference_rules import (
    ModusPonensRule,
    get_all_tdfol_rules,
)
```

**After:**
```python
from ipfs_datasets_py.logic.TDFOL.inference_rules import (
    ModusPonensRule,
    get_all_tdfol_rules,
)
```

All rule names remain exactly the same. Simply change `tdfol_inference_rules` to `inference_rules` in your imports.

## Benefits of New Structure

1. **Better Organization**: Rules are grouped by logic type (propositional, temporal, deontic, etc.)
2. **Easier Navigation**: Each file is ~200-600 LOC instead of one 1,892 LOC file
3. **Clearer Purpose**: Module names clearly indicate what rules they contain
4. **Better Testing**: Can test each module independently
5. **Improved Documentation**: Each module can have focused documentation
6. **Easier Maintenance**: Changes to one logic type don't affect others
7. **100% Backward Compatible**: All existing code continues to work

## Rule Statistics

| Module | Rules | LOC | Description |
|--------|-------|-----|-------------|
| base.py | 1 (ABC) | 120 | Abstract base class |
| propositional.py | 13 | 365 | Basic logic rules |
| first_order.py | 2 | 82 | Quantifier rules |
| temporal.py | 20 | 598 | LTL rules |
| deontic.py | 16 | 433 | SDL rules |
| temporal_deontic.py | 9 | 278 | Combined rules |
| **Total** | **60** | **2,076** | **All inference rules** |

## Architecture

```
TDFOLInferenceRule (ABC)
    ├── Propositional Rules (13)
    ├── First-Order Rules (2)
    ├── Temporal Rules (20)
    ├── Deontic Rules (16)
    └── Temporal-Deontic Rules (9)
```

All rules implement the common interface defined in `TDFOLInferenceRule`:
- `apply(formula, kb) -> List[Formula]`: Apply the rule
- `is_applicable(formula, kb) -> bool`: Check if rule applies
- `name: str`: Rule name
- `description: str`: Rule description

## Contributing

When adding new inference rules:

1. Choose the appropriate module based on logic type
2. Inherit from `TDFOLInferenceRule`
3. Implement `apply()` and `is_applicable()` methods
4. Add comprehensive docstring with examples
5. Add the rule to `get_all_tdfol_rules()` in `__init__.py`
6. Add the rule name to `__all__` in both the module and `__init__.py`
7. Add tests in `tests/unit_tests/logic/TDFOL/inference_rules/`

## References

- **Propositional Logic**: Classical propositional calculus
- **First-Order Logic**: Predicate calculus with quantifiers
- **Temporal Logic**: Linear Temporal Logic (LTL) - Pnueli (1977)
- **Deontic Logic**: Standard Deontic Logic (SDL) - von Wright (1951)
- **Combined Logic**: Integration for legal and ethical reasoning

## Version History

- **v2.0** (2026-02-19): Refactored into modular package structure (Phase 2 Task 2.1)
  - Split monolithic 1,892 LOC file into 6 focused modules
  - Improved organization and maintainability
  - 100% backward compatible
- **v1.0** (Previous): Single `tdfol_inference_rules.py` file with all 60 rules
