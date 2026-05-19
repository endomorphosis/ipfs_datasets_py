"""Canonical bridge-layer contracts for legal logic IR evaluation.

These dataclasses are intentionally dependency-light.  Adapter modules can
import heavier logic families lazily while the optimizer still has one stable
shape for IR views, graph projections, proof gates, and loss metrics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class LogicIRView:
    """One formal view attached to a legal IR document."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    format: str = ""
    source_component: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "metadata": dict(sorted(self.metadata.items())),
            "name": self.name,
            "payload": dict(self.payload),
            "source_component": self.source_component,
        }


@dataclass(frozen=True)
class LegalIRDocument:
    """Canonical envelope for legal text compiled into formal logic views."""

    document_id: str
    source_text: str
    normalized_text: str
    source: str = "us_code"
    citation: Optional[str] = None
    views: Mapping[str, LogicIRView] = field(default_factory=dict)
    frame_logic_triples: Sequence[Mapping[str, str]] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    version: str = "legal-ir-bridge-v1"

    @property
    def has_frame_logic(self) -> bool:
        return bool(self.frame_logic_triples)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation": self.citation,
            "document_id": self.document_id,
            "frame_logic_triples": [dict(triple) for triple in self.frame_logic_triples],
            "has_frame_logic": self.has_frame_logic,
            "metadata": dict(sorted(self.metadata.items())),
            "normalized_text": self.normalized_text,
            "source": self.source,
            "source_text": self.source_text,
            "version": self.version,
            "views": {
                name: view.to_dict()
                for name, view in sorted(self.views.items())
            },
        }

    def to_json(self) -> str:
        return _stable_json(self.to_dict())

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RoundTripMetrics:
    """Loss and similarity metrics shared by bridge adapters."""

    cosine_similarity: float = 0.0
    cosine_loss: float = 0.0
    cross_entropy_loss: float = 0.0
    reconstruction_loss: float = 0.0
    text_reconstruction_loss: float = 0.0
    frame_ranking_loss: float = 0.0
    flogic_similarity_score: float = 0.0
    flogic_similarity_loss: float = 0.0
    symbolic_validity_penalty: float = 0.0
    extra_losses: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def from_loss_mapping(cls, losses: Mapping[str, Any]) -> "RoundTripMetrics":
        known = {
            "cosine_similarity",
            "cosine_loss",
            "cross_entropy_loss",
            "reconstruction_loss",
            "text_reconstruction_loss",
            "frame_ranking_loss",
            "flogic_similarity_score",
            "flogic_similarity_loss",
            "symbolic_validity_penalty",
        }
        return cls(
            cosine_similarity=_float_loss(losses, "cosine_similarity"),
            cosine_loss=_float_loss(losses, "cosine_loss"),
            cross_entropy_loss=_float_loss(losses, "cross_entropy_loss"),
            reconstruction_loss=_float_loss(losses, "reconstruction_loss"),
            text_reconstruction_loss=_float_loss(losses, "text_reconstruction_loss"),
            frame_ranking_loss=_float_loss(losses, "frame_ranking_loss"),
            flogic_similarity_score=_float_loss(losses, "flogic_similarity_score"),
            flogic_similarity_loss=_float_loss(losses, "flogic_similarity_loss"),
            symbolic_validity_penalty=_float_loss(losses, "symbolic_validity_penalty"),
            extra_losses={
                str(name): _coerce_float(value)
                for name, value in losses.items()
                if name not in known
            },
        )

    def total_loss(
        self,
        *,
        proof_failure_ratio: float = 0.0,
        graph_failure_penalty: float = 0.0,
    ) -> float:
        """Return a compact scalar for optimizer prioritization."""

        return (
            max(0.0, 1.0 - self.cosine_similarity)
            + max(0.0, self.cross_entropy_loss)
            + max(0.0, self.reconstruction_loss)
            + max(0.0, self.text_reconstruction_loss)
            + 0.5 * max(0.0, self.frame_ranking_loss)
            + max(0.0, self.symbolic_validity_penalty)
            + max(0.0, proof_failure_ratio)
            + max(0.0, graph_failure_penalty)
            + sum(max(0.0, _coerce_float(value)) for value in self.extra_losses.values())
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cosine_loss": self.cosine_loss,
            "cosine_similarity": self.cosine_similarity,
            "cross_entropy_loss": self.cross_entropy_loss,
            "extra_losses": dict(sorted(self.extra_losses.items())),
            "flogic_similarity_loss": self.flogic_similarity_loss,
            "flogic_similarity_score": self.flogic_similarity_score,
            "frame_ranking_loss": self.frame_ranking_loss,
            "reconstruction_loss": self.reconstruction_loss,
            "symbolic_validity_penalty": self.symbolic_validity_penalty,
            "text_reconstruction_loss": self.text_reconstruction_loss,
        }


@dataclass(frozen=True)
class ProofGateResult:
    """Compilation/prover health for one bridge evaluation."""

    attempted_count: int = 0
    valid_count: int = 0
    unavailable_count: int = 0
    error_count: int = 0
    failed_count: int = 0
    verified_by: Sequence[str] = field(default_factory=tuple)
    details: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    @property
    def compiles(self) -> bool:
        return self.attempted_count > 0 and self.valid_count == self.attempted_count

    @property
    def failure_ratio(self) -> float:
        if self.attempted_count <= 0:
            return 1.0
        failures = self.unavailable_count + self.error_count + self.failed_count
        return min(1.0, failures / self.attempted_count)

    @classmethod
    def from_signal(cls, signal: Any) -> "ProofGateResult":
        if signal is None:
            return cls(details=({"reason": "proof gate disabled"},))
        return cls(
            attempted_count=int(getattr(signal, "attempted_count", 0) or 0),
            valid_count=int(getattr(signal, "valid_count", 0) or 0),
            unavailable_count=int(getattr(signal, "unavailable_count", 0) or 0),
            error_count=int(getattr(signal, "error_count", 0) or 0),
            failed_count=int(getattr(signal, "failed_count", 0) or 0),
            verified_by=tuple(str(item) for item in getattr(signal, "verified_by", ()) or ()),
            details=tuple(getattr(signal, "details", ()) or ()),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted_count": self.attempted_count,
            "compiles": self.compiles,
            "details": [dict(item) for item in self.details],
            "error_count": self.error_count,
            "failed_count": self.failed_count,
            "failure_ratio": self.failure_ratio,
            "unavailable_count": self.unavailable_count,
            "valid_count": self.valid_count,
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class GraphProjectionResult:
    """Neo4j-compatible graph projection summary for a legal IR document."""

    graph_id: str = ""
    neo4j_compatible: bool = False
    node_count: int = 0
    relationship_count: int = 0
    node_labels: Sequence[str] = field(default_factory=tuple)
    relationship_types: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def graph_failure_penalty(self) -> float:
        if not self.neo4j_compatible:
            return 1.0
        if self.node_count <= 0 or self.relationship_count <= 0:
            return 1.0
        return 0.0

    @classmethod
    def from_graph_data(cls, graph_data: Any) -> "GraphProjectionResult":
        if graph_data is None:
            return cls(metadata={"reason": "graph projection disabled"})
        schema = getattr(graph_data, "schema", None)
        metadata = dict(getattr(graph_data, "metadata", {}) or {})
        return cls(
            graph_id=str(metadata.get("graph_id") or ""),
            neo4j_compatible=bool(metadata.get("neo4j_compatible")),
            node_count=int(getattr(graph_data, "node_count", 0) or 0),
            relationship_count=int(getattr(graph_data, "relationship_count", 0) or 0),
            node_labels=tuple(getattr(schema, "node_labels", ()) or ()),
            relationship_types=tuple(getattr(schema, "relationship_types", ()) or ()),
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_failure_penalty": self.graph_failure_penalty,
            "graph_id": self.graph_id,
            "metadata": dict(sorted(self.metadata.items())),
            "neo4j_compatible": self.neo4j_compatible,
            "node_count": self.node_count,
            "node_labels": sorted(self.node_labels),
            "relationship_count": self.relationship_count,
            "relationship_types": sorted(self.relationship_types),
        }


@dataclass(frozen=True)
class BridgeEvaluationReport:
    """Unified bridge report consumed by optimizer and daemon workflows."""

    adapter_name: str
    target_component: str
    ir_document: LegalIRDocument
    round_trip: RoundTripMetrics
    proof_gate: ProofGateResult = field(default_factory=ProofGateResult)
    graph_projection: GraphProjectionResult = field(default_factory=GraphProjectionResult)
    decoded_text: str = ""
    status: str = "partial"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_loss(self) -> float:
        return self.round_trip.total_loss(
            proof_failure_ratio=self.proof_gate.failure_ratio,
            graph_failure_penalty=self.graph_projection.graph_failure_penalty,
        )

    @property
    def accepted(self) -> bool:
        return (
            self.status == "ok"
            and self.ir_document.has_frame_logic
            and self.proof_gate.compiles
            and self.graph_projection.graph_failure_penalty == 0.0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "adapter_name": self.adapter_name,
            "decoded_text": self.decoded_text,
            "graph_projection": self.graph_projection.to_dict(),
            "ir_document": self.ir_document.to_dict(),
            "metadata": dict(sorted(self.metadata.items())),
            "proof_gate": self.proof_gate.to_dict(),
            "round_trip": self.round_trip.to_dict(),
            "status": self.status,
            "target_component": self.target_component,
            "total_loss": self.total_loss,
        }


def _float_loss(losses: Mapping[str, Any], key: str) -> float:
    return _coerce_float(losses.get(key, 0.0))


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "BridgeEvaluationReport",
    "GraphProjectionResult",
    "LegalIRDocument",
    "LogicIRView",
    "ProofGateResult",
    "RoundTripMetrics",
]
