"""
Translation Type Definitions

This module provides backward-compatible imports for translation-related types.
Types are still defined in integration/logic_translation_core.py but imported here
for centralized access and to prevent circular dependencies.

For internal use within the logic module, import from here:
    from ipfs_datasets_py.logic.types import LogicTranslationTarget, TranslationResult

For external use, the types are still available from their original location:
    from ipfs_datasets_py.logic.integration.logic_translation_core import TranslationResult
"""

# Re-export from original location to maintain backward compatibility
from ..integration.converters.logic_translation_core import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
)

__all__ = [
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
]
