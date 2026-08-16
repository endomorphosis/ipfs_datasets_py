"""Integrated UI formalization compiler (UIFormalizationCompiler@1)."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from ..canonicalize import ui_ir_sha256
from ..decoder import decode_ui_ir
from ..schema import UIIRDocument, validate_ui_ir
from .contracts import (
    UI_FORMALIZATION_COMPILER_VERSION,
    CrossViewLink,
    SourceMapEntry,
    UIFormalizationArtifact,
)
from .dcec import compile_dcec
from .event_calculus import compile_event_calculus
from .flogic import compile_flogic
from .tdfol import compile_tdfol


UI_FORMALIZATION_COMPILER_INTERFACE = "UIFormalizationCompiler@1"


def _as_document(document: UIIRDocument | Mapping[str, Any]) -> UIIRDocument:
    if isinstance(document, UIIRDocument):
        return validate_ui_ir(document)
    return decode_ui_ir(document)


def _merge_coverage(
    *parts: tuple[SourceMapEntry, ...],
) -> tuple[SourceMapEntry, ...]:
    # Prefer represented over approximated for same (source_node_id, source_kind)
    best: dict[tuple[str, str], SourceMapEntry] = {}
    rank = {"represented": 3, "approximated": 2, "unsupported": 1, "non_formal": 0}
    for group in parts:
        for entry in group:
            key = (entry.source_node_id, entry.source_kind)
            prev = best.get(key)
            if prev is None or rank.get(entry.disposition.value, 0) > rank.get(
                prev.disposition.value, 0
            ):
                best[key] = entry
            elif prev is not None and entry.disposition == prev.disposition:
                # merge formula/symbol ids
                best[key] = SourceMapEntry(
                    source_node_id=prev.source_node_id,
                    source_kind=prev.source_kind,
                    formula_ids=tuple(
                        sorted(set(prev.formula_ids) | set(entry.formula_ids))
                    ),
                    symbol_ids=tuple(
                        sorted(set(prev.symbol_ids) | set(entry.symbol_ids))
                    ),
                    disposition=prev.disposition,
                    note=prev.note or entry.note,
                )
    return tuple(sorted(best.values(), key=lambda e: (e.source_kind, e.source_node_id)))


def compile_ui_formalization(
    document: UIIRDocument | Mapping[str, Any],
) -> UIFormalizationArtifact:
    """Compile all logic-family views and join with cross-view links."""
    doc = _as_document(document)
    digest = ui_ir_sha256(doc)

    flogic_view, flogic_cov = compile_flogic(doc)
    ec_view, ec_cov = compile_event_calculus(doc)
    tdfol_view, tdfol_cov = compile_tdfol(doc)
    dcec_view, dcec_cov = compile_dcec(doc)

    links: list[CrossViewLink] = []
    # Link program bindings across structural / temporal / cognitive views
    for binding in doc.program_bindings:
        bid = binding.binding_id
        links.append(
            CrossViewLink(
                link_id=f"link:flogic-tdfol:{bid}",
                relation="same_binding",
                left_view_id=flogic_view.view_id,
                left_symbol_or_formula=f"flogic:Bind:{bid}",
                right_view_id=tdfol_view.view_id,
                right_symbol_or_formula=f"tdfol:PermitMediated:{bid}",
                source_ref=bid,
            )
        )
        links.append(
            CrossViewLink(
                link_id=f"link:tdfol-dcec:{bid}",
                relation="deontic_cognitive",
                left_view_id=tdfol_view.view_id,
                left_symbol_or_formula=f"tdfol:PermitMediated:{bid}",
                right_view_id=dcec_view.view_id,
                right_symbol_or_formula=f"dcec:IntendInvoke:{bid}",
                source_ref=bid,
            )
        )
        links.append(
            CrossViewLink(
                link_id=f"link:ec-tdfol:{bid}",
                relation="behavior_to_deontic",
                left_view_id=ec_view.view_id,
                left_symbol_or_formula=f"ec:InvokeEffect:{bid}",
                right_view_id=tdfol_view.view_id,
                right_symbol_or_formula=f"tdfol:PermitMediated:{bid}",
                source_ref=bid,
            )
        )

    for entry in doc.entry_components:
        links.append(
            CrossViewLink(
                link_id=f"link:entry:{entry}",
                relation="entry_focus",
                left_view_id=flogic_view.view_id,
                left_symbol_or_formula=f"flogic:Entry:{entry}",
                right_view_id=ec_view.view_id,
                right_symbol_or_formula=f"ec:InitiallyActive:{entry}",
                source_ref=entry,
            )
        )

    artifact_seed = f"{doc.document_id}|{digest}|{UI_FORMALIZATION_COMPILER_VERSION}"
    artifact_id = (
        f"ui-formal:{hashlib.sha256(artifact_seed.encode('utf-8')).hexdigest()[:16]}"
    )

    return UIFormalizationArtifact(
        artifact_id=artifact_id,
        document_id=doc.document_id,
        document_digest=digest,
        views=(flogic_view, ec_view, tdfol_view, dcec_view),
        links=tuple(links),
        coverage=_merge_coverage(flogic_cov, ec_cov, tdfol_cov, dcec_cov),
        notes=(
            f"interface={UI_FORMALIZATION_COMPILER_INTERFACE}",
            f"compiler_version={UI_FORMALIZATION_COMPILER_VERSION}",
            "Formalization is compiler_output authority only; never KERNEL_VERIFIED.",
            "Invocation remains mediation-gated outside this artifact.",
        ),
    )


__all__ = [
    "UI_FORMALIZATION_COMPILER_INTERFACE",
    "compile_ui_formalization",
]
