"""Temporal deontic first-order compiler leaf (UIR-023)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..model.bindings import RiskClass, UIActionBinding, validate_action_binding
from ..schema import UIIRValidationError
from .contracts import FormalView, ResultAuthority

UI_TDFOL_COMPILER: Final = "ui-ux-ir/tdfol@1"


@dataclass(frozen=True, slots=True)
class DeonticFormula:
    operator: str  # obligation | permission | prohibition
    proposition: str
    strength: str  # must not weaken on round-trip
    source_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TDFOLCompilation:
    compiler: str
    view: FormalView
    formulas: tuple[DeonticFormula, ...]
    unsupported: tuple[str, ...] = ()
    result_authority: ResultAuthority = ResultAuthority.PROOF
    schema_version: str = "ui-tdfol-compilation/v1"


def compile_action_bindings_to_tdfol(
    bindings: tuple[UIActionBinding, ...],
) -> TDFOLCompilation:
    if not bindings:
        raise UIIRValidationError("TDFOL compilation requires at least one action binding")
    formulas: list[DeonticFormula] = []
    for binding in bindings:
        validated = validate_action_binding(binding)
        action = validated.action_id
        if validated.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL} if hasattr(RiskClass, "CRITICAL") else validated.risk_class is RiskClass.HIGH:
            formulas.append(
                DeonticFormula(
                    operator="prohibition",
                    proposition=f"invoke({action}) before confirm({action})",
                    strength="strict",
                    source_ref_ids=validated.source_ref_ids,
                )
            )
            formulas.append(
                DeonticFormula(
                    operator="obligation",
                    proposition=f"confirm({action}) before invoke({action})",
                    strength="strict",
                    source_ref_ids=validated.source_ref_ids,
                )
            )
        else:
            formulas.append(
                DeonticFormula(
                    operator="permission",
                    proposition=f"invoke({action})",
                    strength="weak",
                    source_ref_ids=validated.source_ref_ids,
                )
            )
        formulas.append(
            DeonticFormula(
                operator="prohibition",
                proposition=f"weaken_norm({action})",
                strength="strict",
                source_ref_ids=validated.source_ref_ids,
            )
        )
    formulas_sorted = tuple(sorted(formulas, key=lambda f: (f.operator, f.proposition)))
    return TDFOLCompilation(
        compiler=UI_TDFOL_COMPILER,
        view=FormalView.TDFOL,
        formulas=formulas_sorted,
        unsupported=("stale_grant_runtime_state",),
    )


__all__ = [
    "DeonticFormula",
    "TDFOLCompilation",
    "UI_TDFOL_COMPILER",
    "compile_action_bindings_to_tdfol",
]
