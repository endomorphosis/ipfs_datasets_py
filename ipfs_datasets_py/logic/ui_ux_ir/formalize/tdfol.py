"""Temporal-deontic FOL compiler for UI/UX IR (UITDFOLCompiler@1)."""

from __future__ import annotations

from ..schema import UIIRDocument
from .contracts import (
    UI_TDFOL_VIEW_ID,
    CoverageDisposition,
    FormalFormula,
    FormalSymbol,
    FormalView,
    SourceMapEntry,
)
from .ontology import document_facts


UI_TDFOL_COMPILER_INTERFACE = "UITDFOLCompiler@1"


def compile_tdfol(document: UIIRDocument) -> tuple[FormalView, tuple[SourceMapEntry, ...]]:
    """Compile permissions/prohibitions/obligations without weakening norms."""
    symbols: list[FormalSymbol] = [
        FormalSymbol("sym:op:Permitted", "Permitted", "predicate", arity=2),
        FormalSymbol("sym:op:Obligated", "Obligated", "predicate", arity=2),
        FormalSymbol("sym:op:Prohibited", "Prohibited", "predicate", arity=2),
        FormalSymbol("sym:op:Eventually", "Eventually", "predicate", arity=1),
        FormalSymbol("sym:op:Always", "Always", "predicate", arity=1),
    ]
    formulas: list[FormalFormula] = []
    coverage: list[SourceMapEntry] = []

    # Terminal outcomes constrain success/failure obligations
    for outcome in document.terminal_outcomes:
        kind = (
            outcome.kind.value
            if hasattr(outcome.kind, "value")
            else str(outcome.kind)
        )
        fid = f"tdfol:Outcome:{outcome.outcome_id}"
        if kind == "success":
            text = f"Eventually(Reached({outcome.outcome_id!r}))."
            modality = "obligated"
        elif kind == "failure":
            text = (
                f"Always(Reached({outcome.outcome_id!r}) -> "
                f"FeedbackVisible({outcome.outcome_id!r}))."
            )
            modality = "obligated"
        else:
            text = f"Permitted(Reach({outcome.outcome_id!r}), agent)."
            modality = "permitted"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="tdfol",
                text=text,
                free_symbols=("sym:op:Eventually", "sym:op:Always", "sym:op:Obligated"),
                source_refs=(outcome.outcome_id,),
                modality=modality,
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=outcome.outcome_id,
                source_kind="terminal_outcome",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # Program bindings: confirmation/risk classes as deontic constraints
    for fact in document_facts(document):
        if fact["kind"] != "program_binding":
            continue
        bid = fact["id"]
        risk = fact.get("risk_class") or "low"
        conf = fact.get("confirmation_class") or "none"
        formulas_for: list[str] = []

        # Never auto-permit high risk without confirmation
        if conf and conf != "none":
            fid = f"tdfol:Confirm:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="tdfol",
                    text=(
                        f"Obligated(Confirm({bid!r}), agent) before "
                        f"Permitted(Invoke({fact['target_ref']!r}), agent)."
                    ),
                    free_symbols=("sym:op:Obligated", "sym:op:Permitted"),
                    source_refs=(bid,),
                    modality="obligated",
                    note="Confirmation obligation is non-weakening.",
                )
            )
            formulas_for.append(fid)
        if risk in {"high", "critical"}:
            fid = f"tdfol:ProhibitAuto:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="tdfol",
                    text=f"Prohibited(AutoInvoke({fact['target_ref']!r}), agent).",
                    free_symbols=("sym:op:Prohibited",),
                    source_refs=(bid,),
                    modality="prohibited",
                )
            )
            formulas_for.append(fid)
        else:
            fid = f"tdfol:PermitMediated:{bid}"
            formulas.append(
                FormalFormula(
                    formula_id=fid,
                    logic_family="tdfol",
                    text=(
                        f"Permitted(Invoke({fact['target_ref']!r}), agent) "
                        f"only_if Mediated({bid!r})."
                    ),
                    free_symbols=("sym:op:Permitted",),
                    source_refs=(bid,),
                    modality="permitted",
                    note="Permission is conditional on mediation; not an execution grant.",
                )
            )
            formulas_for.append(fid)

        coverage.append(
            SourceMapEntry(
                source_node_id=bid,
                source_kind="program_binding",
                formula_ids=tuple(formulas_for),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    # Feedback contracts as obligations to surface status
    for feedback in document.feedback_contracts:
        fid = f"tdfol:Feedback:{feedback.feedback_id}"
        formulas.append(
            FormalFormula(
                formula_id=fid,
                logic_family="tdfol",
                text=(
                    f"Obligated(SurfaceFeedback({feedback.feedback_id!r}, "
                    f"{feedback.channel!r}), system)."
                ),
                free_symbols=("sym:op:Obligated",),
                source_refs=(feedback.feedback_id,),
                modality="obligated",
            )
        )
        coverage.append(
            SourceMapEntry(
                source_node_id=feedback.feedback_id,
                source_kind="feedback",
                formula_ids=(fid,),
                disposition=CoverageDisposition.REPRESENTED,
            )
        )

    view = FormalView(
        view_id=UI_TDFOL_VIEW_ID,
        logic_family="tdfol",
        description="Temporal-deontic constraints (permission/obligation/prohibition).",
        symbols=tuple(symbols),
        formulas=tuple(formulas),
        diagnostics=(
            f"interface={UI_TDFOL_COMPILER_INTERFACE}",
            "deontic_non_weakening=true",
        ),
    )
    return view, tuple(coverage)


__all__ = ["UI_TDFOL_COMPILER_INTERFACE", "compile_tdfol"]
