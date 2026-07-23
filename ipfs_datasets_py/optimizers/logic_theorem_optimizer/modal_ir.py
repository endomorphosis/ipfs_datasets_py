"""Canonical intermediate representation for modal legal parsing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class ModalIRProvenance:
    """Text span and citation provenance for an IR node."""

    source_id: str
    start_char: int
    end_char: int
    citation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation": self.citation,
            "end_char": self.end_char,
            "source_id": self.source_id,
            "start_char": self.start_char,
        }


@dataclass(frozen=True)
class ModalIROperator:
    """Operator selected for a modal formula."""

    family: str
    system: str
    symbol: str
    label: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "family": self.family,
            "label": self.label,
            "symbol": self.symbol,
            "system": self.system,
        }


@dataclass(frozen=True)
class ModalIRPredicate:
    """Predicate payload for a modal statement."""

    name: str
    arguments: List[str] = field(default_factory=list)
    role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "name": self.name,
            "role": self.role,
        }


@dataclass(frozen=True)
class ModalIRFrame:
    """Ontology frame candidate or selected frame."""

    frame_id: str
    score: float
    matched_terms: List[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation": self.explanation,
            "frame_id": self.frame_id,
            "matched_terms": sorted(self.matched_terms),
            "score": self.score,
        }


@dataclass(frozen=True)
class ModalIRFrameLogicTriple:
    """One frame-logic assertion carried by the modal IR."""

    subject: str
    predicate: str
    object: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "object": self.object,
            "predicate": self.predicate,
            "subject": self.subject,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ModalIRFrameLogicTriple":
        return cls(
            subject=str(data.get("subject", "")),
            predicate=str(data.get("predicate", "")),
            object=str(data.get("object", "")),
        )


@dataclass(frozen=True)
class ModalIRFrameLogic:
    """Frame-logic layer embedded in the modal legal IR."""

    ontology_name: str = "modal_flogic_ir"
    triples: List[ModalIRFrameLogicTriple] = field(default_factory=list)
    selected_frame: Optional[str] = None
    graph_id: Optional[str] = None
    neo4j_node_labels: List[str] = field(default_factory=list)
    neo4j_relationship_types: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_triples(self) -> List[Dict[str, str]]:
        return [triple.to_dict() for triple in self.triples]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "metadata": dict(sorted(self.metadata.items())),
            "neo4j_node_labels": sorted(self.neo4j_node_labels),
            "neo4j_relationship_types": sorted(self.neo4j_relationship_types),
            "ontology_name": self.ontology_name,
            "selected_frame": self.selected_frame,
            "triples": [triple.to_dict() for triple in self.triples],
        }

    @classmethod
    def from_triples(
        cls,
        triples: List[Mapping[str, Any]],
        *,
        ontology_name: str = "modal_flogic_ir",
        selected_frame: Optional[str] = None,
        graph_id: Optional[str] = None,
        neo4j_node_labels: Optional[List[str]] = None,
        neo4j_relationship_types: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ModalIRFrameLogic":
        return cls(
            ontology_name=ontology_name,
            triples=[ModalIRFrameLogicTriple.from_mapping(triple) for triple in triples],
            selected_frame=selected_frame,
            graph_id=graph_id,
            neo4j_node_labels=neo4j_node_labels or [],
            neo4j_relationship_types=neo4j_relationship_types or [],
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class ModalIRFormula:
    """One formula node in the modal IR."""

    formula_id: str
    operator: ModalIROperator
    predicate: ModalIRPredicate
    provenance: ModalIRProvenance
    conditions: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            # Preserve clause order because scope/temporal semantics depend on
            # source sequencing (for example, "if ... by ... after ...").
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "formula_id": self.formula_id,
            "metadata": dict(sorted(self.metadata.items())),
            "operator": self.operator.to_dict(),
            "predicate": self.predicate.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class ModalIRDocument:
    """Document-level modal IR with deterministic serialization."""

    document_id: str
    source: str
    normalized_text: str
    formulas: List[ModalIRFormula] = field(default_factory=list)
    frame_candidates: List[ModalIRFrame] = field(default_factory=list)
    frame_logic: ModalIRFrameLogic = field(default_factory=ModalIRFrameLogic)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "modal-ir-v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "formulas": [
                formula.to_dict()
                for formula in sorted(self.formulas, key=lambda item: item.formula_id)
            ],
            "frame_candidates": [
                frame.to_dict()
                for frame in sorted(
                    self.frame_candidates,
                    key=lambda item: (-item.score, item.frame_id),
                )
            ],
            "frame_logic": self.frame_logic.to_dict(),
            "metadata": dict(sorted(self.metadata.items())),
            "normalized_text": self.normalized_text,
            "source": self.source,
            "version": self.version,
        }

    def to_json(self) -> str:
        """Return stable compact JSON."""
        return _stable_json(self.to_dict())

    def canonical_hash(self) -> str:
        """Return a deterministic SHA-256 hash for cache keys."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


__all__ = [
    "ModalIRDocument",
    "ModalIRFormula",
    "ModalIRFrame",
    "ModalIRFrameLogic",
    "ModalIRFrameLogicTriple",
    "ModalIROperator",
    "ModalIRPredicate",
    "ModalIRProvenance",
]
