"""Core logic utilities and primitives.

These functions and classes live in the package (not the MCP server tool layer) so
they can be used directly by Python callers. MCP tools should wrap these APIs.
"""

from .text_to_fol import convert_text_to_fol
from .legal_text_to_deontic import convert_legal_text_to_deontic

from .deontic_logic_core import (
    DeonticOperator,
    DeonticFormula,
    DeonticRuleSet,
    LegalAgent,
    LegalContext,
    TemporalCondition,
    TemporalOperator,
    DeonticLogicValidator,
    create_obligation,
    create_permission,
    create_prohibition,
)

from .logic_translation_core import (
    LogicTranslationTarget,
    TranslationResult,
    AbstractLogicFormula,
    LogicTranslator,
    LeanTranslator,
    CoqTranslator,
    SMTTranslator,
)

from .symbolic_fol_bridge import SymbolicFOLBridge
from .symbolic_logic_primitives import LogicPrimitives, create_logic_symbol
from .modal_logic_extension import (
    ModalLogicSymbol,
    AdvancedLogicConverter,
    ModalFormula,
    LogicClassification,
)

__all__ = [
    "convert_text_to_fol",
    "convert_legal_text_to_deontic",
    "DeonticOperator",
    "DeonticFormula",
    "DeonticRuleSet",
    "LegalAgent",
    "LegalContext",
    "TemporalCondition",
    "TemporalOperator",
    "DeonticLogicValidator",
    "create_obligation",
    "create_permission",
    "create_prohibition",
    "LogicTranslationTarget",
    "TranslationResult",
    "AbstractLogicFormula",
    "LogicTranslator",
    "LeanTranslator",
    "CoqTranslator",
    "SMTTranslator",
    "SymbolicFOLBridge",
    "LogicPrimitives",
    "create_logic_symbol",
    "ModalLogicSymbol",
    "AdvancedLogicConverter",
    "ModalFormula",
    "LogicClassification",
]
