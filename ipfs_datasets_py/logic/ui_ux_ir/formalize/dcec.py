"""Deontic Cognitive Event Calculus compiler for UI/UX IR (UIDCECCompiler@1)."""

from __future__ import annotations

from ..schema import UIIRDocument
from .contracts import (
    UI_DCEC_VIEW_ID,
    CoverageDisposition,
    FormalFormula,
    FormalSymbol,
    FormalView,
    SourceMapEntry,
)
from .ontology import document_facts


UI_DCEC_COMPILER_INTERFACE = "UIDCECCompiler@1"


def compile_dcec(document: UIIRDocument) -> tuple[FormalView, tuple[SourceMapEntry, ...]]:
    """Compile perception/knowledge/intention/consent/delegation cognitively."""
    symbols: list[FormalSymbol] = [
        FormalSymbol("sym:dcec:Knows", "Knows", "predicate", arity=2),
        FormalSymbol("sym:dcec:Believes", "Believes", "predicate", arity=2),
        FormalSymbol("sym:dcec:Intends", "Intends", "predicate", arity=2),
        FormalSymbol("sym:dcec:Consents", "Consents", "predicate", arity=2),
        FormalSymbol("sym:dcec:Delegates", "Delegates", "predicate", arity=3),
        FormalSymbol("sym:dcec:Perceives", "Perceives", "predicate", arity=2),
    ]
    formulas: list[FormalFormula] = []
    coverage: list[SourceMapEntry] = []

    # Entry: agent perceives entry surface
    for entry in document.entry_components:
        fid = f"dcec:Perceive:{entry}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="dcec",
                text=f"Perceives(agent, Surface({entry!r})).",
                free_symbols=("sym:dcec:Perceives",),
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

    # Journeys as intended task sequences
    for journey in document.journeys:
        fid = f"dcec:IntendJourney:{journey.journey_id}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="dcec",
                text=(
                    f"Intends(agent, CompleteJourney({journey.journey_id!r}, "
                    f"{list(journey.task_ids)!r}))."
                ),
                free_symbols=("sym:dcec:Intends",),
                source_refs=(journey.journey_id,),
                modality="intended",
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=journey.journey_id,
                source_kind="journey",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # UX tasks as knowledge of steps
    for task in document.ux_tasks:
        fid = f"dcec:KnowsTask:{task.task_id}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="dcec",
                text=(
                    f"Knows(agent, Steps({task.task_id!r}, "
                    f"{list(task.step_component_ids)!r}))."
                ),
                free_symbols=("sym:dcec:Knows",),
                source_refs=(task.task_id,),
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=task.task_id,
                source_kind="ux_task",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # Program bindings with confirmation → consent; high risk → no silent delegation
    for fact in document_facts(document):
        if fact["kind"] != "program_binding":
            continue
        bid = fact["id"]
        conf = fact.get("confirmation_class") or "none"
        risk = fact.get("risk_class") or "low"
        fids: list[str] = []
        if conf != "none":
            fid = f"dcec:Consent:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="dcec",
                    text=(
                        f"Consents(agent, Invoke({fact['target_ref']!r})) "
                        f"before Happens(Invoke({fact['target_ref']!r}), T)."
                    ),
                    free_symbols=("sym:dcec:Consents",),
                    source_refs=(bid,),
                    modality="obligated",
                )
            )
            fids.append(fid)
        if risk in {"high", "critical"}:
            fid = f"dcec:NoSilentDelegate:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="dcec",
                    text=(
                        f"~Delegates(agent, auto_agent, Invoke({fact['target_ref']!r})) "
                        f"without ExplicitDelegation({bid!r})."
                    ),
                    free_symbols=("sym:dcec:Delegates",),
                    source_refs=(bid,),
                    modality="prohibited",
                )
            )
            fids.append(fid)
        else:
            fid = f"dcec:IntendInvoke:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="dcec",
                    text=(
                        f"Intends(agent, Invoke({fact['target_ref']!r})) "
                        f"only_if Knows(agent, Mediated({bid!r}))."
                    ),
                    free_symbols=("sym:dcec:Intends", "sym:dcec:Knows"),
                    source_refs=(bid,),
                    modality="intended",
                )
            )
            fids.append(fid)
        coverage.append(
            SourceMapEntry(
                source_node_id=bid,
                source_kind="program_binding",
                formula_ids=tuple(fids),
                disposition=CoverageDisposition.REPRESENTED,
                note="Cognitive formulas never authorize runtime effects.",
            )
        )

    # Accessibility: agent must be able to perceive accessible names when present
    for component in document.components:
        if not component.accessible_name_ref:
            coverage.append(
                SourceMapEntry(
                    source_node_id=component.component_id,
                    source_kind="component",
                    disposition=CoverageDisposition.APPROXIMATED,
                    note="No accessible_name_ref; a11y perception approximated.",
                )
            )
            continue
        fid = f"dcec:A11y:{component.component_id}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="dcec",
                text=(
                    f"Perceives(agent, AccessibleName({component.component_id!r}, "
                    f"{component.accessible_name_ref!r}))."
                ),
                free_symbols=("sym:dcec:Perceives",),
                source_refs=(component.component_id,),
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=component.component_id,
                source_kind="component",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    view = FormalView(
        view_id=UI_DCEC_VIEW_ID,
        logic_family="dcec",
        description="Deontic cognitive event calculus (perceive/know/intend/consent/delegate).",
        symbols=tuple(symbols),
        formulas=tuple(formulas),
        diagnostics=(f"interface={UI_DCEC_COMPILER_INTERFACE}",),
    )
    return view, tuple(coverage)


__all__ = ["UI_DCEC_COMPILER_INTERFACE", "compile_dcec"]
