"""Shared contracts for UI/UX IR formalization (UIFormalization@1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


UI_FORMALIZATION_INTERFACE = "UIFormalization@1"
UI_RECONSTRUCTION_INTERFACE = "UIReconstruction@1"
UI_SEMANTIC_ROUNDTRIP_INTERFACE = "UISemanticRoundTrip@1"

UI_FORMALIZATION_COMPILER_VERSION = "ui-formalization-compiler/v1"
UI_FORMALIZATION_PRODUCER_ID = "ui-ux-ir-formalization-compiler"
UI_FORMALIZATION_CONFIG_ID = "ui-ux-ir-formalization-default"

UIFLOGIC_VIEW_ID = "ui-ux-ir-view/flogic/v1"
UI_EVENT_CALCULUS_VIEW_ID = "ui-ux-ir-view/event-calculus/v1"
UI_TDFOL_VIEW_ID = "ui-ux-ir-view/tdfol/v1"
UI_DCEC_VIEW_ID = "ui-ux-ir-view/dcec/v1"


class CoverageDisposition(str, Enum):
    REPRESENTED = "represented"
    APPROXIMATED = "approximated"
    UNSUPPORTED = "unsupported"
    NON_FORMAL = "non_formal"


class ResultAuthority(str, Enum):
    """Layered authority — formalization never grants execution."""

    DECLARATION = "declaration"
    SATISFIABILITY = "satisfiability"
    PROOF = "proof"
    POLICY = "policy"
    MONITOR = "monitor"
    PROJECTION = "projection"
    # Compilers emit only declaration / structural views unless a backend proves more.
    COMPILER_OUTPUT = "compiler_output"


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    source_node_id: str
    source_kind: str
    formula_ids: tuple[str, ...] = ()
    symbol_ids: tuple[str, ...] = ()
    disposition: CoverageDisposition = CoverageDisposition.REPRESENTED
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "formula_ids": list(self.formula_ids),
            "note": self.note,
            "source_kind": self.source_kind,
            "source_node_id": self.source_node_id,
            "symbol_ids": list(self.symbol_ids),
        }


@dataclass(frozen=True, slots=True)
class FormalSymbol:
    symbol_id: str
    name: str
    kind: str  # type | predicate | fluent | event | agent | role | action
    arity: int = 0
    sort: str = ""
    source_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "arity": self.arity,
            "kind": self.kind,
            "name": self.name,
            "sort": self.sort,
            "source_ref": self.source_ref,
            "symbol_id": self.symbol_id,
        }


@dataclass(frozen=True, slots=True)
class FormalFormula:
    formula_id: str
    logic_family: str
    text: str
    free_symbols: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    modality: str = ""  # permitted | obligated | prohibited | intended | knows | ...
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "free_symbols": list(self.free_symbols),
            "logic_family": self.logic_family,
            "modality": self.modality,
            "note": self.note,
            "source_refs": list(self.source_refs),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class FormalView:
    view_id: str
    logic_family: str
    description: str
    symbols: tuple[FormalSymbol, ...] = ()
    formulas: tuple[FormalFormula, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "diagnostics": list(self.diagnostics),
            "formulas": [f.to_dict() for f in self.formulas],
            "logic_family": self.logic_family,
            "symbols": [s.to_dict() for s in self.symbols],
            "view_id": self.view_id,
        }


@dataclass(frozen=True, slots=True)
class CrossViewLink:
    link_id: str
    relation: str
    left_view_id: str
    left_symbol_or_formula: str
    right_view_id: str
    right_symbol_or_formula: str
    source_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_symbol_or_formula": self.left_symbol_or_formula,
            "left_view_id": self.left_view_id,
            "link_id": self.link_id,
            "relation": self.relation,
            "right_symbol_or_formula": self.right_symbol_or_formula,
            "right_view_id": self.right_view_id,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class UIFormalizationArtifact:
    """Integrated multi-view formalization of one UIIRDocument."""

    artifact_id: str
    document_id: str
    document_digest: str
    interface: str = UI_FORMALIZATION_INTERFACE
    compiler_version: str = UI_FORMALIZATION_COMPILER_VERSION
    producer_id: str = UI_FORMALIZATION_PRODUCER_ID
    result_authority: ResultAuthority = ResultAuthority.COMPILER_OUTPUT
    views: tuple[FormalView, ...] = ()
    links: tuple[CrossViewLink, ...] = ()
    coverage: tuple[SourceMapEntry, ...] = ()
    grants_execution_authority: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "compiler_version": self.compiler_version,
            "coverage": [c.to_dict() for c in self.coverage],
            "document_digest": self.document_digest,
            "document_id": self.document_id,
            "grants_execution_authority": False,
            "interface": self.interface,
            "links": [link.to_dict() for link in self.links],
            "notes": list(self.notes),
            "producer_id": self.producer_id,
            "result_authority": self.result_authority.value,
            "views": [v.to_dict() for v in self.views],
        }

    def coverage_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {d.value: 0 for d in CoverageDisposition}
        for item in self.coverage:
            counts[item.disposition.value] = counts.get(item.disposition.value, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class UIReconstructionArtifact:
    interface: str = UI_RECONSTRUCTION_INTERFACE
    source_artifact_id: str = ""
    reconstructed_document_id: str = ""
    component_ids: tuple[str, ...] = ()
    entry_components: tuple[str, ...] = ()
    terminal_outcomes: tuple[str, ...] = ()
    program_bindings: tuple[str, ...] = ()
    losses: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    grants_execution_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguous": list(self.ambiguous),
            "component_ids": list(self.component_ids),
            "entry_components": list(self.entry_components),
            "grants_execution_authority": False,
            "interface": self.interface,
            "losses": list(self.losses),
            "program_bindings": list(self.program_bindings),
            "reconstructed_document_id": self.reconstructed_document_id,
            "source_artifact_id": self.source_artifact_id,
            "terminal_outcomes": list(self.terminal_outcomes),
        }


@dataclass(frozen=True, slots=True)
class SemanticRoundTripReport:
    interface: str = UI_SEMANTIC_ROUNDTRIP_INTERFACE
    document_id: str = ""
    document_digest: str = ""
    formalization_artifact_id: str = ""
    graph_equivalent: bool = False
    formula_coverage_ok: bool = False
    deontic_non_weakening: bool = False
    accessibility_parity: bool = False
    modality_parity: bool = False
    passed: bool = False
    losses: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_parity": self.accessibility_parity,
            "deontic_non_weakening": self.deontic_non_weakening,
            "document_digest": self.document_digest,
            "document_id": self.document_id,
            "formalization_artifact_id": self.formalization_artifact_id,
            "formula_coverage_ok": self.formula_coverage_ok,
            "graph_equivalent": self.graph_equivalent,
            "interface": self.interface,
            "losses": list(self.losses),
            "modality_parity": self.modality_parity,
            "notes": list(self.notes),
            "passed": self.passed,
        }


__all__ = [
    "CoverageDisposition",
    "CrossViewLink",
    "FormalFormula",
    "FormalSymbol",
    "FormalView",
    "ResultAuthority",
    "SemanticRoundTripReport",
    "SourceMapEntry",
    "UI_DCEC_VIEW_ID",
    "UI_EVENT_CALCULUS_VIEW_ID",
    "UI_FORMALIZATION_COMPILER_VERSION",
    "UI_FORMALIZATION_CONFIG_ID",
    "UI_FORMALIZATION_INTERFACE",
    "UI_FORMALIZATION_PRODUCER_ID",
    "UI_RECONSTRUCTION_INTERFACE",
    "UI_SEMANTIC_ROUNDTRIP_INTERFACE",
    "UI_TDFOL_VIEW_ID",
    "UIFLOGIC_VIEW_ID",
    "UIFormalizationArtifact",
    "UIReconstructionArtifact",
]
