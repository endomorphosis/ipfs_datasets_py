"""UI formal ontology and cross-view symbol registry (UIR-020)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Iterable, Mapping

from ..schema import UIIRValidationError
from .contracts import (
    CoverageDisposition,
    FormalView,
    default_compiler_contracts,
    validate_compiler_contract,
)

UI_FORMAL_ONTOLOGY_INTERFACE: Final = "UIFormalOntology@1"


class SymbolKind(str, Enum):
    COMPONENT = "component"
    ROLE = "role"
    RELATIONSHIP = "relationship"
    ACTION = "action"
    EVENT = "event"
    STATE = "state"
    ACTOR = "actor"
    DEVICE = "device"
    CAPABILITY = "capability"
    NORM = "norm"
    SOURCE = "source"
    PROGRAM_REF = "program_ref"


@dataclass(frozen=True, slots=True)
class OntologySymbol:
    """One stable cross-view formal symbol."""

    symbol_id: str
    kind: SymbolKind
    label: str
    source_ref_ids: tuple[str, ...] = ()
    view_coverage: Mapping[FormalView, CoverageDisposition] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.view_coverage is None:
            object.__setattr__(self, "view_coverage", {})


@dataclass(frozen=True, slots=True)
class SourceSemanticCoverage:
    """Coverage disposition of one source semantic across formal views."""

    source_semantic_id: str
    dispositions: Mapping[FormalView, CoverageDisposition]
    notes: str = ""


@dataclass(frozen=True, slots=True)
class UIFormalOntology:
    ontology_id: str
    symbols: tuple[OntologySymbol, ...]
    source_coverage: tuple[SourceSemanticCoverage, ...] = ()
    schema_version: str = "ui-formal-ontology/v1"


REQUIRED_SYMBOL_KINDS: Final = frozenset(SymbolKind)


def _require_unique_ids(ids: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for item in ids:
        if not item or not str(item).strip():
            raise UIIRValidationError(f"{label} must be non-empty")
        if item in seen:
            raise UIIRValidationError(f"Duplicate {label}: {item!r}")
        seen.add(item)


def validate_ontology(ontology: UIFormalOntology) -> UIFormalOntology:
    """Validate the closed UI formal ontology."""

    if not ontology.ontology_id.strip():
        raise UIIRValidationError("UIFormalOntology.ontology_id must not be empty")
    _require_unique_ids((s.symbol_id for s in ontology.symbols), "symbol_id")
    kinds = {s.kind for s in ontology.symbols}
    missing = REQUIRED_SYMBOL_KINDS - kinds
    if missing:
        raise UIIRValidationError(
            "Ontology missing required symbol kinds: "
            + ", ".join(sorted(k.value for k in missing))
        )
    for symbol in ontology.symbols:
        if not symbol.label.strip():
            raise UIIRValidationError(
                f"Symbol {symbol.symbol_id!r} label must not be empty"
            )
        if not symbol.view_coverage:
            raise UIIRValidationError(
                f"Symbol {symbol.symbol_id!r} must declare view_coverage"
            )
        for view, disposition in symbol.view_coverage.items():
            if not isinstance(view, FormalView):
                raise UIIRValidationError(
                    f"Symbol {symbol.symbol_id!r} has non-FormalView key"
                )
            if not isinstance(disposition, CoverageDisposition):
                raise UIIRValidationError(
                    f"Symbol {symbol.symbol_id!r} has non-CoverageDisposition value"
                )
    for coverage in ontology.source_coverage:
        if not coverage.source_semantic_id.strip():
            raise UIIRValidationError("source_semantic_id must not be empty")
        if not coverage.dispositions:
            raise UIIRValidationError(
                f"Source semantic {coverage.source_semantic_id!r} needs dispositions"
            )
    # Compiler contracts must remain valid against the same closed views.
    for contract in default_compiler_contracts():
        validate_compiler_contract(contract)
    return ontology


def default_ui_formal_ontology() -> UIFormalOntology:
    """Return a minimal closed ontology covering every required symbol kind."""

    full_all = {view: CoverageDisposition.FULL for view in FormalView if view is not FormalView.SYNTHESIS}
    partial_cognitive = {
        FormalView.FOL_STRUCTURAL: CoverageDisposition.PARTIAL,
        FormalView.FLOGIC: CoverageDisposition.PARTIAL,
        FormalView.EVENT_CALCULUS: CoverageDisposition.FULL,
        FormalView.TDFOL: CoverageDisposition.FULL,
        FormalView.DCEC: CoverageDisposition.FULL,
    }
    symbols = (
        OntologySymbol("sym:component", SymbolKind.COMPONENT, "UI Component", view_coverage=full_all),
        OntologySymbol("sym:role", SymbolKind.ROLE, "Semantic Role", view_coverage=full_all),
        OntologySymbol(
            "sym:relationship",
            SymbolKind.RELATIONSHIP,
            "Composition Relationship",
            view_coverage=full_all,
        ),
        OntologySymbol("sym:action", SymbolKind.ACTION, "UI Action", view_coverage=full_all),
        OntologySymbol("sym:event", SymbolKind.EVENT, "UI Event", view_coverage=full_all),
        OntologySymbol("sym:state", SymbolKind.STATE, "UI State", view_coverage=full_all),
        OntologySymbol("sym:actor", SymbolKind.ACTOR, "Actor", view_coverage=partial_cognitive),
        OntologySymbol("sym:device", SymbolKind.DEVICE, "Device Profile", view_coverage=full_all),
        OntologySymbol(
            "sym:capability", SymbolKind.CAPABILITY, "Modality Capability", view_coverage=full_all
        ),
        OntologySymbol("sym:norm", SymbolKind.NORM, "Norm / Obligation", view_coverage=partial_cognitive),
        OntologySymbol("sym:source", SymbolKind.SOURCE, "Source Reference", view_coverage=full_all),
        OntologySymbol(
            "sym:program_ref",
            SymbolKind.PROGRAM_REF,
            "Program Binding Reference",
            view_coverage={
                FormalView.FOL_STRUCTURAL: CoverageDisposition.FULL,
                FormalView.FLOGIC: CoverageDisposition.FULL,
                FormalView.EVENT_CALCULUS: CoverageDisposition.PARTIAL,
                FormalView.TDFOL: CoverageDisposition.FULL,
                FormalView.DCEC: CoverageDisposition.PARTIAL,
            },
        ),
    )
    coverage = (
        SourceSemanticCoverage(
            source_semantic_id="source.semantic.component_graph",
            dispositions={
                FormalView.FLOGIC: CoverageDisposition.FULL,
                FormalView.EVENT_CALCULUS: CoverageDisposition.PARTIAL,
                FormalView.TDFOL: CoverageDisposition.PARTIAL,
                FormalView.DCEC: CoverageDisposition.EXPLICIT_UNSUPPORTED,
            },
        ),
        SourceSemanticCoverage(
            source_semantic_id="source.semantic.destructive_action",
            dispositions={
                FormalView.TDFOL: CoverageDisposition.FULL,
                FormalView.DCEC: CoverageDisposition.FULL,
                FormalView.EVENT_CALCULUS: CoverageDisposition.PARTIAL,
                FormalView.FLOGIC: CoverageDisposition.PARTIAL,
            },
        ),
        SourceSemanticCoverage(
            source_semantic_id="source.semantic.raw_emg",
            dispositions={view: CoverageDisposition.OUT_OF_SCOPE for view in FormalView},
            notes="Raw EMG is rejected by the v1 architecture contract.",
        ),
    )
    return validate_ontology(
        UIFormalOntology(
            ontology_id="ui-ux-ir/formal-ontology/v1",
            symbols=symbols,
            source_coverage=coverage,
        )
    )


__all__ = [
    "OntologySymbol",
    "REQUIRED_SYMBOL_KINDS",
    "SourceSemanticCoverage",
    "SymbolKind",
    "UIFormalOntology",
    "UI_FORMAL_ONTOLOGY_INTERFACE",
    "default_ui_formal_ontology",
    "validate_ontology",
]
