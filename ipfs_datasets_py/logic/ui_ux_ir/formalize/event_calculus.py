"""Behavioral event-calculus compiler for UI/UX IR (UIEventCalculusCompiler@1)."""

from __future__ import annotations

from ..schema import UIIRDocument
from .contracts import (
    UI_EVENT_CALCULUS_VIEW_ID,
    CoverageDisposition,
    FormalFormula,
    FormalSymbol,
    FormalView,
    SourceMapEntry,
)
from .ontology import document_facts


UI_EVENT_CALCULUS_COMPILER_INTERFACE = "UIEventCalculusCompiler@1"


def compile_event_calculus(
    document: UIIRDocument,
) -> tuple[FormalView, tuple[SourceMapEntry, ...]]:
    """Compile events/transitions/state into event-calculus fluents and happens."""
    symbols: list[FormalSymbol] = [
        FormalSymbol("sym:fluent:Active", "Active", "fluent", arity=1),
        FormalSymbol("sym:fluent:Focus", "Focus", "fluent", arity=1),
        FormalSymbol("sym:event:Happens", "Happens", "event", arity=2),
        FormalSymbol("sym:event:Initiates", "Initiates", "event", arity=3),
        FormalSymbol("sym:event:Terminates", "Terminates", "event", arity=3),
    ]
    formulas: list[FormalFormula] = []
    coverage: list[SourceMapEntry] = []

    # Initial focus on entry components
    for entry in document.entry_components:
        fid = f"ec:InitiallyActive:{entry}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="event_calculus",
                text=f"Initially(Active({entry!r})).",
                free_symbols=("sym:fluent:Active", f"sym:comp:{entry}"),
                source_refs=(entry,),
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=entry,
                source_kind="entry_component",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    for event in document.events:
        fid = f"ec:Happens:{event.event_id}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="event_calculus",
                text=f"Happens({event.event_id!r}, T) <- Trigger({event.kind!r}, T).",
                free_symbols=(f"sym:event:{event.event_id}", "sym:event:Happens"),
                source_refs=(event.event_id,),
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=event.event_id,
                source_kind="event",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # Transitions as initiates/terminates pairs when present as maps
    for index, transition in enumerate(document.transitions):
        if not isinstance(transition, dict):
            continue
        tid = str(transition.get("transition_id") or f"transition:{index}")
        source = str(transition.get("source_state_id") or transition.get("from") or "")
        target = str(transition.get("target_state_id") or transition.get("to") or "")
        event_id = str(transition.get("event_id") or transition.get("on") or "")
        if not (source and target):
            coverage.append(
                SourceMapEntry(
                    source_node_id=tid,
                    source_kind="transition",
                    disposition=CoverageDisposition.APPROXIMATED,
                    note="Transition missing source/target; recorded as partial.",
                )
            )
            continue
        init_id = f"ec:Initiates:{tid}"
        term_id = f"ec:Terminates:{tid}"
        formulas.append(
            FormalFormula(
                formula_id=term_id,
                logic_family="event_calculus",
                text=f"Terminates({event_id or tid!r}, Active({source!r}), T).",
                free_symbols=("sym:event:Terminates", "sym:fluent:Active"),
                source_refs=(tid, source),
            )
        )
        formulas.append(
            FormalFormula(
                formula_id=init_id,
                logic_family="event_calculus",
                text=f"Initiates({event_id or tid!r}, Active({target!r}), T).",
                free_symbols=("sym:event:Initiates", "sym:fluent:Active"),
                source_refs=(tid, target),
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=tid,
                source_kind="transition",
                formula_ids=(init_id, term_id),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # Program bindings as effect events (descriptive, not authorization)
    for fact in document_facts(document):
        if fact["kind"] != "program_binding":
            continue
        fid = f"ec:InvokeEffect:{fact['id']}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="event_calculus",
                text=(
                    f"Happens(Invoke({fact['target_ref']!r}), T) <- "
                    f"Activated({fact['id']!r}, T) /\\ Mediated(T)."
                ),
                free_symbols=(f"sym:binding:{fact['id']}", "sym:event:Happens"),
                source_refs=(fact["id"],),
                note="Invocation remains mediation-gated; EC formula is descriptive.",
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=fact["id"],
                source_kind="program_binding",
                formula_ids=(fid,),
                disposition=CoverageDisposition.APPROXIMATED,
                note="Requires runtime mediation; not an execution grant.",
            )
        )

    if not document.events and not document.transitions:
        coverage.append(
            SourceMapEntry(
                source_node_id=document.document_id,
                source_kind="document",
                disposition=CoverageDisposition.APPROXIMATED,
                note="No explicit events/transitions; EC limited to entry + bindings.",
            )
        )

    view = FormalView(
        view_id=UI_EVENT_CALCULUS_VIEW_ID,
        logic_family="event_calculus",
        description="Behavioral event-calculus fluents, happens, initiates/terminates.",
        symbols=tuple(symbols),
        formulas=tuple(formulas),
        diagnostics=(f"interface={UI_EVENT_CALCULUS_COMPILER_INTERFACE}",),
    )
    return view, tuple(coverage)


__all__ = ["UI_EVENT_CALCULUS_COMPILER_INTERFACE", "compile_event_calculus"]
