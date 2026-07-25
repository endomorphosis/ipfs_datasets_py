"""Bounded, partition-isolated retrieval over immutable Intent graphs.

The retriever is deliberately a small in-memory facade.  It consumes only the
versioned graph artifacts produced by :mod:`corpus_projector` and
:mod:`semantic_projector`; vector search systems may supply scored candidate
observations, but those observations are checked against an edge in the exact
graph snapshot before they can be returned.

Retrieval results are context, never proofs.  Every returned premise therefore
has ``proof_authority=False`` and retains the graph, edge, source, partition,
and source-family bindings used to admit it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
import time
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from .ontology import (
    CorpusEdgeType,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusNodeType,
    IntentCorpusGraph,
)
from .semantic_projector import (
    SemanticEdgeType,
    SemanticGraphEdge,
    SemanticGraphNode,
    SemanticIntentGraph,
    SemanticNodeType,
)


RETRIEVAL_SCHEMA_VERSION: Final = "intent-graph-retrieval/v1"
RETRIEVAL_AUTHORITY: Final = "context_only"
DEFAULT_K: Final = 8
MAX_K: Final = 100
DEFAULT_MAX_BYTES: Final = 64 * 1024
MAX_MAX_BYTES: Final = 16 * 1024 * 1024
DEFAULT_TIMEOUT_MS: Final = 100
MAX_TIMEOUT_MS: Final = 60_000


class RetrievalValidationError(ValueError):
    """Raised when a retrieval request or isolation assignment is malformed."""


class RetrievalStatus(str, Enum):
    """Explicit terminal state of a bounded retrieval."""

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNSUPPORTED = "unsupported"


class GraphKind(str, Enum):
    """The two graph families supported by this facade."""

    CORPUS = "corpus"
    SEMANTIC = "semantic"


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Immutable identity of the graph searched by one request."""

    graph_kind: GraphKind
    graph_digest: str
    graph_cid: str
    schema_version: str
    ontology_version: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "graph_kind", GraphKind(self.graph_kind))
        except (TypeError, ValueError) as exc:
            raise RetrievalValidationError("unsupported graph_kind") from exc
        _require_text(self.graph_digest, "graph_digest")
        _require_text(self.schema_version, "schema_version")
        _require_text(self.ontology_version, "ontology_version")
        if self.graph_cid:
            _require_text(self.graph_cid, "graph_cid")

    @classmethod
    def from_graph(
        cls, graph: IntentCorpusGraph | SemanticIntentGraph
    ) -> "GraphSnapshot":
        if isinstance(graph, IntentCorpusGraph):
            kind = GraphKind.CORPUS
        elif isinstance(graph, SemanticIntentGraph):
            kind = GraphKind.SEMANTIC
        else:
            raise TypeError("graph must be an Intent corpus or semantic graph")
        return cls(
            graph_kind=kind,
            graph_digest=graph.graph_digest,
            graph_cid=graph.graph_cid,
            schema_version=graph.schema_version,
            ontology_version=graph.ontology_version,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "graph_kind": self.graph_kind.value,
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PartitionAssignment:
    """Trusted split and source-family assignment for one graph node.

    Partition and family information intentionally live outside graph node
    properties: changing a training/evaluation split must not change the
    source graph's content identity.  Missing assignments fail closed.
    """

    partition: str
    source_family: str
    adversarial: bool = False

    def __post_init__(self) -> None:
        _require_text(self.partition, "partition")
        _require_text(self.source_family, "source_family")
        if not isinstance(self.adversarial, bool):
            raise RetrievalValidationError("adversarial must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversarial": self.adversarial,
            "partition": self.partition,
            "source_family": self.source_family,
        }


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Allow/exclude filters applied before ranking or budget accounting."""

    node_types: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    excluded_source_ref_ids: tuple[str, ...] = ()
    excluded_source_digests: tuple[str, ...] = ()
    excluded_source_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "node_types",
            "edge_types",
            "source_ref_ids",
            "excluded_source_ref_ids",
            "excluded_source_digests",
            "excluded_source_families",
        ):
            object.__setattr__(
                self,
                field_name,
                _canonical_strings(getattr(self, field_name), field_name),
            )
        overlap = set(self.source_ref_ids) & set(self.excluded_source_ref_ids)
        if overlap:
            raise RetrievalValidationError(
                "source_ref_ids and excluded_source_ref_ids overlap"
            )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "edge_types": list(self.edge_types),
            "excluded_source_digests": list(self.excluded_source_digests),
            "excluded_source_families": list(
                self.excluded_source_families
            ),
            "excluded_source_ref_ids": list(self.excluded_source_ref_ids),
            "node_types": list(self.node_types),
            "source_ref_ids": list(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class NeighborCandidate:
    """A scored neighbor observation from a retrieval/index backend."""

    node_id: str
    edge_id: str
    score: float
    graph_digest: str

    def __post_init__(self) -> None:
        _require_text(self.node_id, "candidate node_id")
        _require_text(self.edge_id, "candidate edge_id")
        _require_text(self.graph_digest, "candidate graph_digest")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise RetrievalValidationError("candidate score must be numeric")
        score = float(self.score)
        if not math.isfinite(score):
            raise RetrievalValidationError("candidate score must be finite")
        object.__setattr__(self, "score", score)


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """One fixed-size query bound to an exact graph and evaluation scope."""

    query_node_id: str
    snapshot: GraphSnapshot
    partition: str
    source_family: str
    k: int = DEFAULT_K
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    candidates: tuple[NeighborCandidate, ...] = ()
    adversarial: bool = False

    def __post_init__(self) -> None:
        _require_text(self.query_node_id, "query_node_id")
        if not isinstance(self.snapshot, GraphSnapshot):
            raise RetrievalValidationError("snapshot must be a GraphSnapshot")
        _require_text(self.partition, "partition")
        _require_text(self.source_family, "source_family")
        _bounded_integer(self.k, "k", maximum=MAX_K)
        _bounded_integer(
            self.max_bytes, "max_bytes", maximum=MAX_MAX_BYTES
        )
        _bounded_integer(
            self.timeout_ms, "timeout_ms", maximum=MAX_TIMEOUT_MS
        )
        if not isinstance(self.filters, RetrievalFilters):
            raise RetrievalValidationError(
                "filters must be RetrievalFilters"
            )
        if not isinstance(self.adversarial, bool):
            raise RetrievalValidationError("adversarial must be a boolean")
        candidates = tuple(self.candidates)
        if any(not isinstance(item, NeighborCandidate) for item in candidates):
            raise RetrievalValidationError(
                "candidates must contain NeighborCandidate values"
            )
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class RetrievedPremise:
    """One provenance-preserving, explicitly non-authoritative neighbor."""

    node_id: str
    node_type: str
    edge_id: str
    edge_type: str
    score: float
    graph_digest: str
    graph_cid: str
    partition: str
    source_family: str
    source_ids: tuple[str, ...]
    source_digest: str
    properties: Mapping[str, Any]
    proof_authority: bool = False
    authority: str = RETRIEVAL_AUTHORITY

    def __post_init__(self) -> None:
        for field_name in (
            "node_id",
            "node_type",
            "edge_id",
            "edge_type",
            "graph_digest",
            "partition",
            "source_family",
            "source_digest",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.graph_cid:
            _require_text(self.graph_cid, "graph_cid")
        if isinstance(self.score, bool) or not isinstance(
            self.score, (int, float)
        ):
            raise RetrievalValidationError("premise score must be numeric")
        score = float(self.score)
        if not math.isfinite(score):
            raise RetrievalValidationError("premise score must be finite")
        object.__setattr__(self, "score", score)
        if self.proof_authority is not False:
            raise RetrievalValidationError(
                "retrieved premises cannot have proof authority"
            )
        if self.authority != RETRIEVAL_AUTHORITY:
            raise RetrievalValidationError(
                "retrieved premise authority must be context_only"
            )
        object.__setattr__(
            self,
            "source_ids",
            _canonical_strings(self.source_ids, "source_ids"),
        )
        object.__setattr__(
            self, "properties", _freeze_json_mapping(self.properties)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "edge_id": self.edge_id,
            "edge_type": self.edge_type,
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "partition": self.partition,
            "proof_authority": self.proof_authority,
            "properties": _thaw(self.properties),
            "score": self.score,
            "source_digest": self.source_digest,
            "source_family": self.source_family,
            "source_ids": list(self.source_ids),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Bounded result with an explicit empty, partial, or unsupported state."""

    status: RetrievalStatus
    snapshot: GraphSnapshot
    query_node_id: str
    partition: str
    requested_k: int
    max_bytes: int
    timeout_ms: int
    premises: tuple[RetrievedPremise, ...] = ()
    bytes_used: int = 0
    examined_candidates: int = 0
    reason_codes: tuple[str, ...] = ()
    authority: str = RETRIEVAL_AUTHORITY
    schema_version: str = RETRIEVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "status", RetrievalStatus(self.status))
        except (TypeError, ValueError) as exc:
            raise RetrievalValidationError("unsupported retrieval status") from exc
        if self.authority != RETRIEVAL_AUTHORITY:
            raise RetrievalValidationError(
                "retrieval results must be context_only"
            )
        if self.schema_version != RETRIEVAL_SCHEMA_VERSION:
            raise RetrievalValidationError(
                "unsupported retrieval schema_version"
            )
        if not isinstance(self.snapshot, GraphSnapshot):
            raise RetrievalValidationError("snapshot must be a GraphSnapshot")
        _require_text(self.query_node_id, "query_node_id")
        _require_text(self.partition, "partition")
        _bounded_integer(self.requested_k, "requested_k", maximum=MAX_K)
        _bounded_integer(
            self.max_bytes, "max_bytes", maximum=MAX_MAX_BYTES
        )
        _bounded_integer(
            self.timeout_ms, "timeout_ms", maximum=MAX_TIMEOUT_MS
        )
        if (
            isinstance(self.bytes_used, bool)
            or not isinstance(self.bytes_used, int)
            or self.bytes_used < 0
        ):
            raise RetrievalValidationError(
                "bytes_used must be a non-negative integer"
            )
        if (
            isinstance(self.examined_candidates, bool)
            or not isinstance(self.examined_candidates, int)
            or self.examined_candidates < 0
        ):
            raise RetrievalValidationError(
                "examined_candidates must be a non-negative integer"
            )
        premises = tuple(self.premises)
        if any(not isinstance(item, RetrievedPremise) for item in premises):
            raise RetrievalValidationError(
                "premises must contain RetrievedPremise values"
            )
        if len(premises) > self.requested_k:
            raise RetrievalValidationError("result exceeds requested k")
        if self.bytes_used != sum(len(item.canonical_bytes()) for item in premises):
            raise RetrievalValidationError(
                "bytes_used does not match serialized premises"
            )
        if self.bytes_used > self.max_bytes:
            raise RetrievalValidationError("result exceeds max_bytes")
        if self.status in {
            RetrievalStatus.EMPTY,
            RetrievalStatus.BUDGET_EXHAUSTED,
            RetrievalStatus.UNSUPPORTED,
        } and premises:
            raise RetrievalValidationError(
                f"{self.status.value} results cannot contain premises"
            )
        if self.status is RetrievalStatus.OK and not premises:
            raise RetrievalValidationError("ok result must contain premises")
        if self.status is RetrievalStatus.PARTIAL and not premises:
            raise RetrievalValidationError(
                "partial result must contain at least one premise"
            )
        object.__setattr__(self, "premises", premises)
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )

    @property
    def items(self) -> tuple[RetrievedPremise, ...]:
        """Compatibility alias for callers that call retrieval values items."""

        return self.premises

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "bytes_used": self.bytes_used,
            "examined_candidates": self.examined_candidates,
            "max_bytes": self.max_bytes,
            "partition": self.partition,
            "premises": [item.to_dict() for item in self.premises],
            "query_node_id": self.query_node_id,
            "reason_codes": list(self.reason_codes),
            "requested_k": self.requested_k,
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "status": self.status.value,
            "timeout_ms": self.timeout_ms,
        }


_Graph = IntentCorpusGraph | SemanticIntentGraph
_Node = CorpusGraphNode | SemanticGraphNode
_Edge = CorpusGraphEdge | SemanticGraphEdge


class IntentGraphRetriever:
    """Retrieve bounded graph neighbors without crossing a trusted split."""

    def __init__(
        self,
        graph: _Graph,
        assignments: Mapping[str, PartitionAssignment],
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(graph, (IntentCorpusGraph, SemanticIntentGraph)):
            raise TypeError(
                "graph must be an IntentCorpusGraph or SemanticIntentGraph"
            )
        if not isinstance(assignments, Mapping):
            raise TypeError("assignments must be a mapping")
        prepared: dict[str, PartitionAssignment] = {}
        for node_id, assignment in assignments.items():
            _require_text(node_id, "assignment node_id")
            if not isinstance(assignment, PartitionAssignment):
                raise RetrievalValidationError(
                    "assignment values must be PartitionAssignment instances"
                )
            prepared[node_id] = assignment
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        self.graph = graph
        self.snapshot = GraphSnapshot.from_graph(graph)
        self.assignments = MappingProxyType(prepared)
        self._monotonic = monotonic
        self._node_by_id: Mapping[str, _Node] = MappingProxyType(
            {node.node_id: node for node in graph.nodes}
        )
        self._edge_by_id: Mapping[str, _Edge] = MappingProxyType(
            {edge.edge_id: edge for edge in graph.edges}
        )

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Return up to exactly the requested fixed ``k`` after all controls."""

        if not isinstance(request, RetrievalRequest):
            raise TypeError("request must be a RetrievalRequest")
        unsupported = self._unsupported_reason(request)
        if unsupported:
            return self._result(
                request,
                RetrievalStatus.UNSUPPORTED,
                reason_codes=(unsupported,),
            )

        started = self._monotonic()
        deadline = started + (request.timeout_ms / 1000.0)
        if request.candidates:
            raw_candidates = request.candidates
        else:
            raw_candidates, scan_timed_out = self._graph_candidates(
                request.query_node_id, deadline=deadline
            )
            if scan_timed_out:
                return self._result(
                    request,
                    RetrievalStatus.BUDGET_EXHAUSTED,
                    reason_codes=("time_budget_exhausted",),
                )
        eligible: list[tuple[NeighborCandidate, _Node, _Edge, PartitionAssignment]] = []
        examined = 0
        filtered_reasons: set[str] = set()

        for candidate in raw_candidates:
            if self._monotonic() >= deadline:
                return self._result(
                    request,
                    RetrievalStatus.BUDGET_EXHAUSTED,
                    examined_candidates=examined,
                    reason_codes=("time_budget_exhausted",),
                )
            examined += 1
            admitted = self._admit(request, candidate)
            if isinstance(admitted, str):
                filtered_reasons.add(admitted)
                continue
            eligible.append((candidate, *admitted))

        # Rank before de-duplicating nodes, so the best observation for a node
        # wins.  Node and edge IDs are stable final tie breakers.
        eligible.sort(
            key=lambda item: (
                -item[0].score,
                item[0].node_id,
                item[0].edge_id,
            )
        )
        unique: list[tuple[NeighborCandidate, _Node, _Edge, PartitionAssignment]] = []
        seen_nodes: set[str] = set()
        for item in eligible:
            if item[0].node_id in seen_nodes:
                continue
            seen_nodes.add(item[0].node_id)
            unique.append(item)

        premises: list[RetrievedPremise] = []
        bytes_used = 0
        byte_limited = False
        for candidate, node, edge, assignment in unique:
            if len(premises) == request.k:
                break
            if self._monotonic() >= deadline:
                if not premises:
                    return self._result(
                        request,
                        RetrievalStatus.BUDGET_EXHAUSTED,
                        examined_candidates=examined,
                        reason_codes=("time_budget_exhausted",),
                    )
                return self._result(
                    request,
                    RetrievalStatus.PARTIAL,
                    premises=tuple(premises),
                    bytes_used=bytes_used,
                    examined_candidates=examined,
                    reason_codes=("time_budget_exhausted",),
                )
            premise = self._premise(candidate, node, edge, assignment)
            item_bytes = len(premise.canonical_bytes())
            if bytes_used + item_bytes > request.max_bytes:
                byte_limited = True
                break
            premises.append(premise)
            bytes_used += item_bytes

        if not premises:
            if byte_limited:
                return self._result(
                    request,
                    RetrievalStatus.BUDGET_EXHAUSTED,
                    examined_candidates=examined,
                    reason_codes=("byte_budget_exhausted",),
                )
            reasons = tuple(filtered_reasons) or ("no_matching_neighbors",)
            return self._result(
                request,
                RetrievalStatus.EMPTY,
                examined_candidates=examined,
                reason_codes=reasons,
            )
        if byte_limited:
            return self._result(
                request,
                RetrievalStatus.PARTIAL,
                premises=tuple(premises),
                bytes_used=bytes_used,
                examined_candidates=examined,
                reason_codes=("byte_budget_exhausted",),
            )
        return self._result(
            request,
            RetrievalStatus.OK,
            premises=tuple(premises),
            bytes_used=bytes_used,
            examined_candidates=examined,
        )

    def _unsupported_reason(self, request: RetrievalRequest) -> str:
        if request.snapshot != self.snapshot:
            return "graph_snapshot_mismatch"
        query_node = self._node_by_id.get(request.query_node_id)
        if query_node is None:
            return "query_node_not_found"
        assignment = self.assignments.get(request.query_node_id)
        if assignment is None:
            return "query_partition_unassigned"
        if (
            assignment.partition != request.partition
            or assignment.source_family != request.source_family
            or assignment.adversarial != request.adversarial
        ):
            return "query_isolation_binding_mismatch"
        node_vocabulary = (
            {item.value for item in CorpusNodeType}
            if self.snapshot.graph_kind is GraphKind.CORPUS
            else {item.value for item in SemanticNodeType}
        )
        if not set(request.filters.node_types) <= node_vocabulary:
            return "unsupported_node_filter"
        edge_vocabulary = (
            {item.value for item in CorpusEdgeType}
            if self.snapshot.graph_kind is GraphKind.CORPUS
            else {item.value for item in SemanticEdgeType}
        )
        if not set(request.filters.edge_types) <= edge_vocabulary:
            return "unsupported_edge_filter"
        return ""

    def _graph_candidates(
        self, query_node_id: str, *, deadline: float
    ) -> tuple[tuple[NeighborCandidate, ...], bool]:
        candidates: list[NeighborCandidate] = []
        for edge in self.graph.edges:
            if self._monotonic() >= deadline:
                return tuple(candidates), True
            if edge.source == query_node_id:
                neighbor = edge.target
            elif edge.target == query_node_id:
                neighbor = edge.source
            else:
                continue
            raw_score = edge.properties.get(
                "score",
                edge.properties.get(
                    "similarity", edge.properties.get("weight", 0.0)
                ),
            )
            score = (
                float(raw_score)
                if isinstance(raw_score, (int, float))
                and not isinstance(raw_score, bool)
                and math.isfinite(float(raw_score))
                else 0.0
            )
            candidates.append(
                NeighborCandidate(
                    node_id=neighbor,
                    edge_id=edge.edge_id,
                    score=score,
                    graph_digest=self.graph.graph_digest,
                )
            )
        return tuple(candidates), False

    def _admit(
        self, request: RetrievalRequest, candidate: NeighborCandidate
    ) -> tuple[_Node, _Edge, PartitionAssignment] | str:
        if candidate.graph_digest != self.graph.graph_digest:
            return "candidate_snapshot_mismatch"
        node = self._node_by_id.get(candidate.node_id)
        edge = self._edge_by_id.get(candidate.edge_id)
        if node is None or edge is None:
            return "candidate_not_in_snapshot"
        if not (
            (edge.source == request.query_node_id and edge.target == node.node_id)
            or (
                edge.target == request.query_node_id
                and edge.source == node.node_id
            )
        ):
            return "candidate_not_adjacent"
        assignment = self.assignments.get(node.node_id)
        if assignment is None:
            return "candidate_partition_unassigned"
        if assignment.partition != request.partition:
            return "partition_excluded"
        if assignment.adversarial != request.adversarial:
            return "adversarial_excluded"
        # A query's own source family is always excluded, independently of the
        # caller's additional family denylist.
        excluded_families = {
            request.source_family,
            *request.filters.excluded_source_families,
        }
        if assignment.source_family in excluded_families:
            return "source_family_excluded"
        node_type = node.node_type.value
        edge_type = edge.edge_type.value
        if request.filters.node_types and node_type not in request.filters.node_types:
            return "node_type_filtered"
        if request.filters.edge_types and edge_type not in request.filters.edge_types:
            return "edge_type_filtered"
        source_ids = _source_ids(node)
        if request.filters.source_ref_ids and not (
            set(source_ids) & set(request.filters.source_ref_ids)
        ):
            return "source_filter_miss"
        if set(source_ids) & set(request.filters.excluded_source_ref_ids):
            return "source_excluded"
        source_digest = _source_digest(node)
        if source_digest in request.filters.excluded_source_digests:
            return "source_digest_excluded"
        return node, edge, assignment

    def _premise(
        self,
        candidate: NeighborCandidate,
        node: _Node,
        edge: _Edge,
        assignment: PartitionAssignment,
    ) -> RetrievedPremise:
        return RetrievedPremise(
            node_id=node.node_id,
            node_type=node.node_type.value,
            edge_id=edge.edge_id,
            edge_type=edge.edge_type.value,
            score=candidate.score,
            graph_digest=self.graph.graph_digest,
            graph_cid=self.graph.graph_cid,
            partition=assignment.partition,
            source_family=assignment.source_family,
            source_ids=_source_ids(node),
            source_digest=_source_digest(node),
            properties=node.properties,
        )

    def _result(
        self,
        request: RetrievalRequest,
        status: RetrievalStatus,
        *,
        premises: tuple[RetrievedPremise, ...] = (),
        bytes_used: int = 0,
        examined_candidates: int = 0,
        reason_codes: tuple[str, ...] = (),
    ) -> RetrievalResult:
        return RetrievalResult(
            status=status,
            snapshot=self.snapshot,
            query_node_id=request.query_node_id,
            partition=request.partition,
            requested_k=request.k,
            max_bytes=request.max_bytes,
            timeout_ms=request.timeout_ms,
            premises=premises,
            bytes_used=bytes_used,
            examined_candidates=examined_candidates,
            reason_codes=reason_codes,
        )


def _source_ids(node: _Node) -> tuple[str, ...]:
    if isinstance(node, SemanticGraphNode):
        return node.source_ref_ids
    values = []
    for key in ("skill_id", "source_id", "primary_source_id", "source_uri"):
        value = node.properties.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    return tuple(sorted(set(values)))


def _source_digest(node: _Node) -> str:
    return (
        node.source_digest
        if isinstance(node, CorpusGraphNode)
        else node.intent_ir_digest
    )


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RetrievalValidationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _bounded_integer(value: Any, field_name: str, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise RetrievalValidationError(
            f"{field_name} must be an integer between 1 and {maximum}"
        )
    return value


def _canonical_strings(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise RetrievalValidationError(
            f"{field_name} must be an iterable of strings"
        )
    try:
        prepared = tuple(_require_text(value, field_name) for value in values)
    except TypeError as exc:
        raise RetrievalValidationError(
            f"{field_name} must be an iterable of strings"
        ) from exc
    return tuple(sorted(set(prepared)))


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_json_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RetrievalValidationError("properties must be a mapping")
    return _freeze_json(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


__all__ = [
    "DEFAULT_K",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_MS",
    "GraphKind",
    "GraphSnapshot",
    "IntentGraphRetriever",
    "MAX_K",
    "MAX_MAX_BYTES",
    "MAX_TIMEOUT_MS",
    "NeighborCandidate",
    "PartitionAssignment",
    "RETRIEVAL_AUTHORITY",
    "RETRIEVAL_SCHEMA_VERSION",
    "RetrievalFilters",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalStatus",
    "RetrievalValidationError",
    "RetrievedPremise",
]
