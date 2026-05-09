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
            "conditions": sorted(self.conditions),
            "exceptions": sorted(self.exceptions),
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
    "ModalIROperator",
    "ModalIRPredicate",
    "ModalIRProvenance",
]
