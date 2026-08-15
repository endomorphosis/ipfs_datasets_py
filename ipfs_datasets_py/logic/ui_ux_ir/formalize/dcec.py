"""Deontic cognitive event-calculus compiler leaf (UIR-024)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..runtime.events import CanonicalInteractionEvent, EventProvenance, validate_event
from ..schema import UIIRValidationError
from .contracts import FormalView, ResultAuthority

UI_DCEC_COMPILER: Final = "ui-ux-ir/dcec@1"


@dataclass(frozen=True, slots=True)
class CognitiveFormula:
    kind: str  # knows | believes | intends | observes | delegates
    actor: str
    content: str
    source_ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DCECCompilation:
    compiler: str
    view: FormalView
    formulas: tuple[CognitiveFormula, ...]
    unsupported: tuple[str, ...] = ()
    result_authority: ResultAuthority = ResultAuthority.ADVISORY
    schema_version: str = "ui-dcec-compilation/v1"


def compile_events_to_dcec(
    events: tuple[CanonicalInteractionEvent, ...],
    *,
    actor_id: str = "user",
) -> DCECCompilation:
    if not events:
        raise UIIRValidationError("DCEC compilation requires events")
    if not actor_id.strip():
        raise UIIRValidationError("actor_id must not be empty")
    formulas: list[CognitiveFormula] = []
    for event in events:
        validated = validate_event(event)
        # Observed input is not automatically user intent.
        formulas.append(
            CognitiveFormula(
                kind="observes",
                actor=actor_id,
                content=f"{validated.kind.value}({validated.target_component_id})",
            )
        )
        if validated.provenance is EventProvenance.AGENT:
            formulas.append(
                CognitiveFormula(
                    kind="delegates",
                    actor="agent",
                    content=f"propose({validated.event_id})",
                )
            )
            # Agent action requires valid delegation — do not promote to user intent.
            formulas.append(
                CognitiveFormula(
                    kind="believes",
                    actor=actor_id,
                    content=f"not_auto_intent({validated.event_id})",
                )
            )
        elif validated.provenance is EventProvenance.HUMAN:
            formulas.append(
                CognitiveFormula(
                    kind="intends",
                    actor=actor_id,
                    content=f"maybe_intent({validated.event_id})",
                )
            )
        # Unknown remains unknown: no knows() without evidence.
    formulas_sorted = tuple(sorted(formulas, key=lambda f: (f.kind, f.actor, f.content)))
    return DCECCompilation(
        compiler=UI_DCEC_COMPILER,
        view=FormalView.DCEC,
        formulas=formulas_sorted,
        unsupported=("raw_neural_belief_extraction",),
    )


__all__ = [
    "CognitiveFormula",
    "DCECCompilation",
    "UI_DCEC_COMPILER",
    "compile_events_to_dcec",
]
