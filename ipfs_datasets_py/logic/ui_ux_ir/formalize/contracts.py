"""Compiler and backend bounds contracts for UI formalization (UIR-020)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Mapping

from ..schema import UIIRValidationError

UI_FORMALIZE_CONTRACTS_INTERFACE: Final = "UIFormalizeContracts@1"


class FormalView(str, Enum):
    """Cross-view formalization targets shared by UI compilers."""

    FOL_STRUCTURAL = "fol_structural"
    FLOGIC = "flogic"
    EVENT_CALCULUS = "event_calculus"
    TDFOL = "tdfol"
    DCEC = "dcec"
    SYNTHESIS = "synthesis"


class CoverageDisposition(str, Enum):
    """How a source semantic is covered by a formal view."""

    FULL = "full"
    PARTIAL = "partial"
    EXPLICIT_UNSUPPORTED = "explicit_unsupported"
    LOSSY = "lossy"
    OUT_OF_SCOPE = "out_of_scope"


class ResultAuthority(str, Enum):
    """Who may treat a formalization result as authority."""

    DECLARATION = "declaration"
    PROOF = "proof"
    OBSERVATION = "observation"
    ADVISORY = "advisory"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class BackendBound:
    """Explicit bounds for one formalization backend."""

    backend_id: str
    view: FormalView
    max_symbols: int
    max_formulas: int
    supports_proof: bool = False
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CompilerContract:
    """Stable contract for a UI formalization compiler leaf."""

    compiler_id: str
    view: FormalView
    input_symbol_kinds: tuple[str, ...]
    output_artifact_kind: str
    result_authority: ResultAuthority
    backend_bounds: tuple[BackendBound, ...] = ()
    schema_version: str = "ui-formalize-compiler-contract/v1"


def validate_compiler_contract(contract: CompilerContract) -> CompilerContract:
    if not contract.compiler_id.strip():
        raise UIIRValidationError("CompilerContract.compiler_id must not be empty")
    if not contract.input_symbol_kinds:
        raise UIIRValidationError("CompilerContract.input_symbol_kinds must not be empty")
    if not contract.output_artifact_kind.strip():
        raise UIIRValidationError("CompilerContract.output_artifact_kind must not be empty")
    for bound in contract.backend_bounds:
        if bound.max_symbols < 1 or bound.max_formulas < 1:
            raise UIIRValidationError(
                f"BackendBound {bound.backend_id!r} limits must be positive"
            )
        if bound.view is not contract.view:
            raise UIIRValidationError(
                f"BackendBound {bound.backend_id!r} view mismatch with compiler"
            )
    return contract


def default_compiler_contracts() -> tuple[CompilerContract, ...]:
    """Return the closed set of UI formalization compiler contracts."""

    return (
        CompilerContract(
            compiler_id="ui-ux-ir/flogic",
            view=FormalView.FLOGIC,
            input_symbol_kinds=(
                "component",
                "role",
                "relationship",
                "action",
                "capability",
                "source",
            ),
            output_artifact_kind="formalization.flogic.facts",
            result_authority=ResultAuthority.ADVISORY,
            backend_bounds=(
                BackendBound(
                    backend_id="flogic.ergo",
                    view=FormalView.FLOGIC,
                    max_symbols=10_000,
                    max_formulas=50_000,
                    supports_proof=False,
                    result_authority=ResultAuthority.ADVISORY,
                ),
            ),
        ),
        CompilerContract(
            compiler_id="ui-ux-ir/event-calculus",
            view=FormalView.EVENT_CALCULUS,
            input_symbol_kinds=("state", "event", "transition", "actor", "source"),
            output_artifact_kind="formalization.event_calculus.narrative",
            result_authority=ResultAuthority.ADVISORY,
            backend_bounds=(
                BackendBound(
                    backend_id="cec.default",
                    view=FormalView.EVENT_CALCULUS,
                    max_symbols=5_000,
                    max_formulas=25_000,
                    supports_proof=True,
                    result_authority=ResultAuthority.PROOF,
                ),
            ),
        ),
        CompilerContract(
            compiler_id="ui-ux-ir/tdfol",
            view=FormalView.TDFOL,
            input_symbol_kinds=("norm", "action", "actor", "source", "capability"),
            output_artifact_kind="formalization.tdfol.obligations",
            result_authority=ResultAuthority.PROOF,
            backend_bounds=(
                BackendBound(
                    backend_id="tdfol.default",
                    view=FormalView.TDFOL,
                    max_symbols=5_000,
                    max_formulas=25_000,
                    supports_proof=True,
                    result_authority=ResultAuthority.PROOF,
                ),
            ),
        ),
        CompilerContract(
            compiler_id="ui-ux-ir/dcec",
            view=FormalView.DCEC,
            input_symbol_kinds=("actor", "event", "belief", "knowledge", "norm", "source"),
            output_artifact_kind="formalization.dcec.cognitive",
            result_authority=ResultAuthority.ADVISORY,
            backend_bounds=(
                BackendBound(
                    backend_id="dcec.default",
                    view=FormalView.DCEC,
                    max_symbols=5_000,
                    max_formulas=25_000,
                    supports_proof=False,
                    result_authority=ResultAuthority.ADVISORY,
                ),
            ),
        ),
    )


__all__ = [
    "BackendBound",
    "CompilerContract",
    "CoverageDisposition",
    "FormalView",
    "ResultAuthority",
    "UI_FORMALIZE_CONTRACTS_INTERFACE",
    "default_compiler_contracts",
    "validate_compiler_contract",
]
