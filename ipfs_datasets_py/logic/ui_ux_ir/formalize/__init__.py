"""UI/UX IR multi-view formalization (FOL/F-logic, event calculus, TDFOL, DCEC)."""

from .compiler import UI_FORMALIZATION_COMPILER_INTERFACE, compile_ui_formalization
from .contracts import (
    CoverageDisposition,
    CrossViewLink,
    FormalFormula,
    FormalSymbol,
    FormalView,
    ResultAuthority,
    SemanticRoundTripReport,
    SourceMapEntry,
    UI_FORMALIZATION_INTERFACE,
    UIFormalizationArtifact,
    UIReconstructionArtifact,
)
from .dcec import UI_DCEC_COMPILER_INTERFACE, compile_dcec
from .decompiler import UI_FORMAL_DECOMPILER_INTERFACE, decompile_ui_formalization
from .event_calculus import (
    UI_EVENT_CALCULUS_COMPILER_INTERFACE,
    compile_event_calculus,
)
from .flogic import UIFLOGIC_COMPILER_INTERFACE, compile_flogic
from .roundtrip import evaluate_semantic_roundtrip
from .tdfol import UI_TDFOL_COMPILER_INTERFACE, compile_tdfol

__all__ = [
    "CoverageDisposition",
    "CrossViewLink",
    "FormalFormula",
    "FormalSymbol",
    "FormalView",
    "ResultAuthority",
    "SemanticRoundTripReport",
    "SourceMapEntry",
    "UI_DCEC_COMPILER_INTERFACE",
    "UI_EVENT_CALCULUS_COMPILER_INTERFACE",
    "UI_FORMALIZATION_COMPILER_INTERFACE",
    "UI_FORMALIZATION_INTERFACE",
    "UI_FORMAL_DECOMPILER_INTERFACE",
    "UI_TDFOL_COMPILER_INTERFACE",
    "UIFLOGIC_COMPILER_INTERFACE",
    "UIFormalizationArtifact",
    "UIReconstructionArtifact",
    "compile_dcec",
    "compile_event_calculus",
    "compile_flogic",
    "compile_tdfol",
    "compile_ui_formalization",
    "decompile_ui_formalization",
    "evaluate_semantic_roundtrip",
]
