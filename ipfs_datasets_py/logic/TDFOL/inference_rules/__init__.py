"""
TDFOL Inference Rules Package

This package contains all inference rules for TDFOL theorem proving, organized into
logical categories for better maintainability and discoverability.

Modules:
- base: Abstract base class (TDFOLInferenceRule)
- propositional: 13 propositional logic rules
- first_order: 2 first-order logic rules (quantifiers)
- temporal: 20 temporal logic rules (LTL operators)
- deontic: 16 deontic logic rules (SDL operators)
- temporal_deontic: 9 combined temporal-deontic rules

Total: 60 inference rules

Usage:
    >>> from ipfs_datasets_py.logic.TDFOL.inference_rules import ModusPonensRule
    >>> rule = ModusPonensRule()
    >>> # Or import from old location (backward compatible):
    >>> from ipfs_datasets_py.logic.TDFOL.tdfol_inference_rules import ModusPonensRule

Author: TDFOL Team
Date: 2026-02-19
Phase: 2 (Architecture Improvements)
Task: 2.1 (Split Inference Rules Monolith)
"""

from __future__ import annotations

# Base class
from .base import TDFOLInferenceRule

# Propositional rules (13 rules)
from .propositional import (
    ModusPonensRule,
    ModusTollensRule,
    DisjunctiveSyllogismRule,
    HypotheticalSyllogismRule,
    ConjunctionIntroductionRule,
    ConjunctionEliminationLeftRule,
    ConjunctionEliminationRightRule,
    DisjunctionIntroductionLeftRule,
    DoubleNegationEliminationRule,
    DoubleNegationIntroductionRule,
    ContrapositionRule,
    DeMorganAndRule,
    DeMorganOrRule,
)

# First-order rules (2 rules)
from .first_order import (
    UniversalInstantiationRule,
    ExistentialGeneralizationRule,
)

# TODO: Import from other modules as they're created
# from .temporal import (...)
# from .deontic import (...)
# from .temporal_deontic import (...)


# All propositional rules
__all__ = [
    # Base
    'TDFOLInferenceRule',
    
    # Propositional (13)
    'ModusPonensRule',
    'ModusTollensRule',
    'DisjunctiveSyllogismRule',
    'HypotheticalSyllogismRule',
    'ConjunctionIntroductionRule',
    'ConjunctionEliminationLeftRule',
    'ConjunctionEliminationRightRule',
    'DisjunctionIntroductionLeftRule',
    'DoubleNegationEliminationRule',
    'DoubleNegationIntroductionRule',
    'ContrapositionRule',
    'DeMorganAndRule',
    'DeMorganOrRule',
    
    # First-Order (2)
    'UniversalInstantiationRule',
    'ExistentialGeneralizationRule',
    
    # TODO: Add more as modules are created
]
