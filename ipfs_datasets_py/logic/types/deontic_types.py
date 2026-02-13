"""
Deontic Logic Type Definitions

This module provides backward-compatible imports for deontic logic types.
Types are still defined in tools/deontic_logic_core.py but imported here
for centralized access and to prevent circular dependencies.

For internal use within the logic module, import from here:
    from ipfs_datasets_py.logic.types import DeonticOperator, DeonticFormula

For external use, the types are still available from their original location:
    from ipfs_datasets_py.logic.tools.deontic_logic_core import DeonticOperator
"""

# Re-export from original location to maintain backward compatibility
from ..tools.deontic_logic_core import (
    DeonticOperator,
    DeonticFormula,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
    TemporalCondition,
    TemporalOperator,
)

__all__ = [
    "DeonticOperator",
    "DeonticFormula",
    "DeonticRuleSet",
    "LegalAgent",
    "LegalContext",
    "TemporalCondition",
    "TemporalOperator",
]
