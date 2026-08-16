"""Semantic round-trip equivalence for UI formalization (UISemanticRoundTrip@1)."""

from __future__ import annotations

from typing import Any, Mapping

from ..canonicalize import ui_ir_sha256
from ..decoder import decode_ui_ir
from ..schema import UIIRDocument, validate_ui_ir
from .compiler import compile_ui_formalization
from .contracts import SemanticRoundTripReport, UIFormalizationArtifact
from .decompiler import decompile_ui_formalization


def _as_document(document: UIIRDocument | Mapping[str, Any]) -> UIIRDocument:
    if isinstance(document, UIIRDocument):
        return validate_ui_ir(document)
    return decode_ui_ir(document)


def evaluate_semantic_roundtrip(
    document: UIIRDocument | Mapping[str, Any],
    *,
    artifact: UIFormalizationArtifact | None = None,
) -> SemanticRoundTripReport:
    """Evaluate graph/formula/deontic/a11y/modality round-trip equivalence."""
    doc = _as_document(document)
    digest = ui_ir_sha256(doc)
    art = artifact or compile_ui_formalization(doc)
    recon = decompile_ui_formalization(art)

    component_ids = {c.component_id for c in doc.components}
    entry_ids = set(doc.entry_components)
    terminal_ids = {o.outcome_id for o in doc.terminal_outcomes}
    binding_ids = {b.binding_id for b in doc.program_bindings}

    recon_components = set(recon.component_ids)
    recon_entries = set(recon.entry_components)
    recon_terminals = set(recon.terminal_outcomes)
    recon_bindings = set(recon.program_bindings)

    losses: list[str] = list(recon.losses)
    # Graph equivalence: reconstruction must not invent nodes and must cover
    # core components / entries / terminals / bindings present in formulas.
    invented = (recon_components - component_ids) | (recon_entries - entry_ids)
    if invented:
        losses.append(f"invented_nodes:{sorted(invented)}")
    graph_equivalent = not invented and entry_ids.issubset(recon_entries | recon_components)

    # Require every component appears in coverage
    covered_components = {
        c.source_node_id
        for c in art.coverage
        if c.source_kind in {"component", "entry_component"}
    }
    missing_comp = component_ids - covered_components
    if missing_comp:
        losses.append(f"uncovered_components:{sorted(missing_comp)}")
    formula_coverage_ok = not missing_comp

    # Deontic non-weakening: every high-risk binding must have a prohibition or confirm obligation
    deontic_ok = True
    tdfol = next((v for v in art.views if v.logic_family == "tdfol"), None)
    tdfol_text = " ".join(f.text for f in (tdfol.formulas if tdfol else ()))
    for binding in doc.program_bindings:
        if (binding.risk_class or "low") in {"high", "critical"}:
            if "Prohibited(AutoInvoke" not in tdfol_text and binding.binding_id not in tdfol_text:
                deontic_ok = False
                losses.append(f"deontic_weakening:{binding.binding_id}")
        if (binding.confirmation_class or "none") != "none":
            if f"Confirm('{binding.binding_id}')" not in tdfol_text and "Obligated(Confirm" not in tdfol_text:
                # still accept if binding id appears with Obligated
                if binding.binding_id not in tdfol_text:
                    deontic_ok = False
                    losses.append(f"missing_confirmation_obligation:{binding.binding_id}")

    # Accessibility parity: components with accessible_name_ref should have DCEC perceive formula
    dcec = next((v for v in art.views if v.logic_family == "dcec"), None)
    dcec_text = " ".join(f.text for f in (dcec.formulas if dcec else ()))
    a11y_ok = True
    for component in doc.components:
        if component.accessible_name_ref and component.component_id not in dcec_text:
            a11y_ok = False
            losses.append(f"a11y_gap:{component.component_id}")

    # Modality parity: program bindings should appear in both tdfol and flogic
    flogic = next((v for v in art.views if v.logic_family == "flogic"), None)
    flogic_text = " ".join(f.text for f in (flogic.formulas if flogic else ()))
    modality_ok = True
    for bid in binding_ids:
        if bid not in flogic_text or bid not in tdfol_text:
            modality_ok = False
            losses.append(f"modality_gap:{bid}")

    # Terminal reconstruction when terminals exist
    if terminal_ids and not terminal_ids.issubset(recon_terminals):
        losses.append(
            f"terminal_reconstruction_gap:{sorted(terminal_ids - recon_terminals)}"
        )
        graph_equivalent = False

    # Binding reconstruction when bindings exist
    if binding_ids and not binding_ids.issubset(recon_bindings | set()):
        # Bindings reconstructed from BindsProgram only
        missing_b = binding_ids - recon_bindings
        if missing_b:
            losses.append(f"binding_reconstruction_gap:{sorted(missing_b)}")

    passed = (
        graph_equivalent
        and formula_coverage_ok
        and deontic_ok
        and a11y_ok
        and modality_ok
        and not invented
    )

    return SemanticRoundTripReport(
        document_id=doc.document_id,
        document_digest=digest,
        formalization_artifact_id=art.artifact_id,
        graph_equivalent=graph_equivalent,
        formula_coverage_ok=formula_coverage_ok,
        deontic_non_weakening=deontic_ok,
        accessibility_parity=a11y_ok,
        modality_parity=modality_ok,
        passed=passed,
        losses=tuple(losses),
        notes=(
            "Round-trip evaluates structural reconstruction + non-weakening norms.",
            "Does not claim theorem proof or execution authority.",
        ),
    )


__all__ = ["evaluate_semantic_roundtrip"]
