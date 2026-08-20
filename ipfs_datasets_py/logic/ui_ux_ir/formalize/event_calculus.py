"""Event-calculus behavior compiler leaf (UIR-022)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..model.behavior import BehaviorModel, validate_behavior_model
from ..schema import UIIRValidationError
from .contracts import FormalView, ResultAuthority

UI_EVENT_CALCULUS_COMPILER: Final = "ui-ux-ir/event-calculus@1"


@dataclass(frozen=True, slots=True)
class ECFormula:
    kind: str  # initiates | terminates | holds_at | happens
    args: tuple[str, ...]
    source_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EventCalculusCompilation:
    compiler: str
    view: FormalView
    formulas: tuple[ECFormula, ...]
    unsupported: tuple[str, ...] = ()
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    schema_version: str = "ui-event-calculus-compilation/v1"


def compile_behavior_to_event_calculus(model: BehaviorModel) -> EventCalculusCompilation:
    validated = validate_behavior_model(model)
    formulas: list[ECFormula] = []
    for state in validated.states:
        formulas.append(ECFormula(kind="fluent", args=(f"in_state({state.state_id})",)))
    for transition in validated.transitions:
        event = transition.event_id or transition.transition_id
        formulas.append(
            ECFormula(
                kind="happens",
                args=(event, *transition.source_state_ids, transition.target_state_id),
            )
        )
        formulas.append(
            ECFormula(
                kind="initiates",
                args=(event, f"in_state({transition.target_state_id})"),
            )
        )
        for source in transition.source_state_ids:
            formulas.append(
                ECFormula(
                    kind="terminates",
                    args=(event, f"in_state({source})"),
                )
            )
        if transition.timeout_ms is not None:
            formulas.append(
                ECFormula(
                    kind="happens",
                    args=(f"timeout({transition.transition_id})", str(transition.timeout_ms)),
                )
            )
    if not formulas:
        raise UIIRValidationError("Event-calculus compilation produced no formulas")
    formulas_sorted = tuple(sorted(formulas, key=lambda f: (f.kind, f.args)))
    return EventCalculusCompilation(
        compiler=UI_EVENT_CALCULUS_COMPILER,
        view=FormalView.EVENT_CALCULUS,
        formulas=formulas_sorted,
        unsupported=("unstable_internal_ast_variants", "pixel_timing_curves"),
    )


__all__ = [
    "ECFormula",
    "EventCalculusCompilation",
    "UI_EVENT_CALCULUS_COMPILER",
    "compile_behavior_to_event_calculus",
]
