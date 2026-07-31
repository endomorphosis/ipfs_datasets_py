"""Deterministic, provenance-bound GraphRAG materialization for CVEfixes.

The graph is a retrieval artifact, never an authorization artifact.  Every
node and edge is represented by the canonical derived-record contracts from
``schemas`` and binds the exact pinned source rows from which it was derived.
Approximate similarity is kept in a distinct edge class and is explicitly
non-authoritative.

Graph construction has two integrity layers:

* each node and edge has its own content-derived ``record_id``;
* canonical node, edge, and adjacency tables are committed by a deterministic
  graph root.

Consequently a detached graph can be decoded and verified without trusting
its producer, and rebuilding the same projections in a different input order
produces the same bytes and root.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity
from .projector import (
    ProjectionResult,
    SemanticFact,
    SemanticKind,
    VulnerableFixedPair,
)
from .schemas import GraphEdge, GraphNode, canonical_config_cid


GRAPH_SCHEMA_VERSION: Final = "cvefixes-graphrag-graph/v1"
GRAPH_ONTOLOGY_VERSION: Final = "cvefixes-graphrag-ontology/v1"
GRAPH_CONFIG_SCHEMA_VERSION: Final = "cvefixes-graphrag-config/v1"
GRAPH_IDENTITY_DOMAIN: Final = "cvefixes-security-ir/graphrag-graph"
CVEFIXES_GRAPH_SCHEMA_VERSION: Final = GRAPH_SCHEMA_VERSION
CVEFIXES_GRAPH_ONTOLOGY_VERSION: Final = GRAPH_ONTOLOGY_VERSION

_CID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_IR_CORE_CID_HEADER = b"\x01\x55\x12\x20"


class GraphBuildError(ValueError):
    """Raised when projections cannot be safely materialized."""


class GraphValidationError(ValueError):
    """Raised when a graph or graph record violates the reviewed contract."""


class GraphNodeType(str, Enum):
    """Reviewed node vocabulary for CVEfixes GraphRAG."""

    SOURCE = "source"
    CVE = "cve"
    CWE = "cwe"
    REPOSITORY = "repository"
    COMMIT = "commit"
    LANGUAGE = "language"
    CODE_UNIT = "code_unit"
    PRECONDITION = "precondition"
    ACTION = "action"
    EFFECT = "effect"
    MITIGATION = "mitigation"


class GraphEdgeType(str, Enum):
    """Reviewed, directed relationship vocabulary."""

    DESCRIBES = "DESCRIBES"
    AFFECTS = "AFFECTS"
    FIXED_BY = "FIXED_BY"
    CLASSIFIED_AS = "CLASSIFIED_AS"
    CONTAINS = "CONTAINS"
    CHANGES = "CHANGES"
    WRITTEN_IN = "WRITTEN_IN"
    OBSERVES = "OBSERVES"
    PAIRS_WITH = "PAIRS_WITH"
    SIMILAR_TO = "SIMILAR_TO"


class GraphEdgeClass(str, Enum):
    """Edge partition used to exclude approximate evidence from authority."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    SIMILARITY = "similarity"


_SEMANTIC_NODE_TYPES: Final = frozenset(
    {
        GraphNodeType.PRECONDITION,
        GraphNodeType.ACTION,
        GraphNodeType.EFFECT,
        GraphNodeType.MITIGATION,
    }
)


def _enum_value(
    enum_type: type[Enum], value: Enum | str, label: str
) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise GraphValidationError(f"unsupported {label}: {value!r}") from exc


def _cid(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 59
        or not value.startswith("b")
        or any(character not in _CID_ALPHABET for character in value)
    ):
        raise GraphValidationError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        )
    try:
        encoded = value[1:].upper()
        raw = base64.b32decode(encoded + ("=" * ((-len(encoded)) % 8)))
    except (ValueError, base64.binascii.Error) as exc:
        raise GraphValidationError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        ) from exc
    if len(raw) != 36 or not raw.startswith(_IR_CORE_CID_HEADER):
        raise GraphValidationError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        )
    return value


def _cid_tuple(
    value: Any, label: str, *, nonempty: bool = True
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise GraphValidationError(f"{label} must be a sequence of CIDs")
    result = tuple(sorted(_cid(item, f"{label} item") for item in value))
    if nonempty and not result:
        raise GraphValidationError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise GraphValidationError(f"{label} contains duplicate CIDs")
    return result


@dataclass(frozen=True, slots=True)
class GraphOntology:
    """Machine-readable declaration of valid node and edge directions."""

    version: str = GRAPH_ONTOLOGY_VERSION
    node_types: tuple[str, ...] = tuple(item.value for item in GraphNodeType)
    edge_types: tuple[str, ...] = tuple(item.value for item in GraphEdgeType)

    def __post_init__(self) -> None:
        if self.version != GRAPH_ONTOLOGY_VERSION:
            raise GraphValidationError("unsupported graph ontology version")
        if self.node_types != tuple(item.value for item in GraphNodeType):
            raise GraphValidationError(
                "node_types must exactly match the reviewed vocabulary"
            )
        if self.edge_types != tuple(item.value for item in GraphEdgeType):
            raise GraphValidationError(
                "edge_types must exactly match the reviewed vocabulary"
            )

    def validate_edge(
        self,
        edge_type: GraphEdgeType | str,
        source_type: GraphNodeType | str,
        target_type: GraphNodeType | str,
        *,
        edge_class: GraphEdgeClass | str,
    ) -> None:
        edge = _enum_value(GraphEdgeType, edge_type, "edge_type")
        source = _enum_value(GraphNodeType, source_type, "source_type")
        target = _enum_value(GraphNodeType, target_type, "target_type")
        category = _enum_value(GraphEdgeClass, edge_class, "edge_class")

        expected_class = (
            GraphEdgeClass.SIMILARITY
            if edge is GraphEdgeType.SIMILAR_TO
            else (
                GraphEdgeClass.SEMANTIC
                if edge is GraphEdgeType.OBSERVES
                else GraphEdgeClass.STRUCTURAL
            )
        )
        if category is not expected_class:
            raise GraphValidationError(
                f"{edge.value} must be classified as {expected_class.value}"
            )

        valid = False
        if edge is GraphEdgeType.DESCRIBES:
            valid = (
                source is GraphNodeType.SOURCE
                and target is GraphNodeType.CVE
            )
        elif edge is GraphEdgeType.AFFECTS:
            valid = (
                source is GraphNodeType.CVE
                and target is GraphNodeType.REPOSITORY
            )
        elif edge is GraphEdgeType.FIXED_BY:
            valid = (
                source is GraphNodeType.CVE
                and target is GraphNodeType.COMMIT
            )
        elif edge is GraphEdgeType.CLASSIFIED_AS:
            valid = (
                source is GraphNodeType.CVE
                and target is GraphNodeType.CWE
            )
        elif edge is GraphEdgeType.CONTAINS:
            valid = (
                source is GraphNodeType.REPOSITORY
                and target is GraphNodeType.COMMIT
            )
        elif edge is GraphEdgeType.CHANGES:
            valid = (
                source is GraphNodeType.COMMIT
                and target is GraphNodeType.CODE_UNIT
            )
        elif edge is GraphEdgeType.WRITTEN_IN:
            valid = (
                source is GraphNodeType.CODE_UNIT
                and target is GraphNodeType.LANGUAGE
            )
        elif edge is GraphEdgeType.OBSERVES:
            valid = (
                source is GraphNodeType.CODE_UNIT
                and target in _SEMANTIC_NODE_TYPES
            )
        elif edge is GraphEdgeType.PAIRS_WITH:
            valid = source is target is GraphNodeType.CODE_UNIT
        elif edge is GraphEdgeType.SIMILAR_TO:
            valid = source is target and source is not GraphNodeType.SOURCE
        if not valid:
            raise GraphValidationError(
                f"{edge.value} does not permit "
                f"{source.value} -> {target.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_types": list(self.edge_types),
            "node_types": list(self.node_types),
            "version": self.version,
        }


GRAPH_ONTOLOGY: Final = GraphOntology()


@dataclass(frozen=True, slots=True)
class GraphConfig:
    """Resource bounds and identity-affecting graph configuration."""

    max_nodes: int = 1_000_000
    max_edges: int = 4_000_000
    schema_version: str = GRAPH_CONFIG_SCHEMA_VERSION
    ontology_version: str = GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        for name in ("max_nodes", "max_edges"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise GraphValidationError(f"{name} must be a positive integer")
        if self.schema_version != GRAPH_CONFIG_SCHEMA_VERSION:
            raise GraphValidationError("unsupported graph config schema")
        if self.ontology_version != GRAPH_ONTOLOGY_VERSION:
            raise GraphValidationError("unsupported graph config ontology")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
        }

    @property
    def cid(self) -> str:
        return canonical_config_cid(
            self.to_dict(), schema_version=self.schema_version
        )


@dataclass(frozen=True, slots=True)
class SimilarityObservation:
    """Approximate neighbor evidence over two exact projected records."""

    source_record_cid: str
    target_record_cid: str
    evidence_cids: tuple[str, ...]
    model_id: str
    model_revision: str
    model_config_cid: str
    score: float
    metric: str = "cosine"

    def __post_init__(self) -> None:
        for name in (
            "source_record_cid",
            "target_record_cid",
            "model_config_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        if self.source_record_cid == self.target_record_cid:
            raise GraphValidationError(
                "similarity observation endpoints must be distinct"
            )
        object.__setattr__(
            self,
            "evidence_cids",
            _cid_tuple(self.evidence_cids, "evidence_cids"),
        )
        for name in ("model_id", "model_revision", "metric"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                raise GraphValidationError(f"{name} must be clean non-empty text")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not -1.0 <= float(self.score) <= 1.0
        ):
            raise GraphValidationError("similarity score must be between -1 and 1")
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "non_authoritative",
            "evidence_cids": list(self.evidence_cids),
            "grants_execution_authority": False,
            "metric": self.metric,
            "model_config_cid": self.model_config_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "score": self.score,
            "source_record_cid": self.source_record_cid,
            "target_record_cid": self.target_record_cid,
        }


def _edge_class(edge: GraphEdge) -> GraphEdgeClass:
    try:
        value = edge.payload["edge_class"]
    except KeyError as exc:
        raise GraphValidationError("edge payload must declare edge_class") from exc
    return _enum_value(GraphEdgeClass, value, "edge_class")


def _record_node_type(node: GraphNode) -> GraphNodeType:
    return _enum_value(GraphNodeType, node.node_type, "node_type")


def _identity_root(
    value: Mapping[str, Any], domain_suffix: str
) -> str:
    return canonical_identity(
        value,
        domain=f"{GRAPH_IDENTITY_DOMAIN}/{domain_suffix}",
        schema_version=GRAPH_SCHEMA_VERSION,
    ).cid


def _build_adjacency(
    nodes: Sequence[GraphNode], edges: Sequence[GraphEdge]
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    outgoing: dict[str, list[str]] = {node.cid: [] for node in nodes}
    incoming: dict[str, list[str]] = {node.cid: [] for node in nodes}
    for edge in edges:
        try:
            outgoing[edge.source_node_cid].append(edge.cid)
            incoming[edge.target_node_cid].append(edge.cid)
        except KeyError as exc:
            raise GraphValidationError("edge endpoint is dangling") from exc
    return (
        {key: tuple(sorted(value)) for key, value in sorted(outgoing.items())},
        {key: tuple(sorted(value)) for key, value in sorted(incoming.items())},
    )


def _freeze_adjacency(
    value: Mapping[str, Sequence[str]], label: str
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise GraphValidationError(f"{label} must be a mapping")
    result: dict[str, tuple[str, ...]] = {}
    for key, edge_ids in value.items():
        node_cid = _cid(key, f"{label} node")
        result[node_cid] = _cid_tuple(
            edge_ids, f"{label}[{node_cid}]", nonempty=False
        )
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class CVEfixesGraph:
    """Immutable graph tables, adjacency indexes, and their integrity roots."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    source_cids: tuple[str, ...]
    projection_cids: tuple[str, ...]
    config_cid: str
    outgoing: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    incoming: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    node_table_root: str = ""
    edge_table_root: str = ""
    adjacency_root: str = ""
    graph_root: str = ""
    schema_version: str = GRAPH_SCHEMA_VERSION
    ontology_version: str = GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GRAPH_SCHEMA_VERSION:
            raise GraphValidationError("unsupported graph schema version")
        if self.ontology_version != GRAPH_ONTOLOGY_VERSION:
            raise GraphValidationError("unsupported graph ontology version")
        nodes = tuple(sorted(self.nodes, key=lambda item: item.cid))
        edges = tuple(sorted(self.edges, key=lambda item: item.cid))
        if any(not isinstance(item, GraphNode) for item in nodes):
            raise GraphValidationError("nodes must contain GraphNode records")
        if any(not isinstance(item, GraphEdge) for item in edges):
            raise GraphValidationError("edges must contain GraphEdge records")
        if len({item.cid for item in nodes}) != len(nodes):
            raise GraphValidationError("duplicate graph node")
        if len({item.cid for item in edges}) != len(edges):
            raise GraphValidationError("duplicate graph edge")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        source_cids = _cid_tuple(self.source_cids, "source_cids")
        projection_cids = _cid_tuple(self.projection_cids, "projection_cids")
        object.__setattr__(self, "source_cids", source_cids)
        object.__setattr__(self, "projection_cids", projection_cids)
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))

        node_by_id = {item.cid: item for item in nodes}
        known_sources = set(source_cids)
        for node in nodes:
            _record_node_type(node)
            if not set(node.source_cids) <= known_sources:
                raise GraphValidationError("node binds an unknown source CID")
            if node.config_cid != self.config_cid:
                raise GraphValidationError("node config binding mismatch")
            if node.payload.get("grants_execution_authority") is not False:
                raise GraphValidationError(
                    "graph nodes must explicitly deny execution authority"
                )
        for edge in edges:
            if edge.source_node_cid not in node_by_id:
                raise GraphValidationError("edge source endpoint is dangling")
            if edge.target_node_cid not in node_by_id:
                raise GraphValidationError("edge target endpoint is dangling")
            if not edge.source_cids:
                raise GraphValidationError("edge must bind source evidence")
            if not set(edge.source_cids) <= known_sources:
                raise GraphValidationError("edge binds an unknown source CID")
            if edge.config_cid != self.config_cid:
                raise GraphValidationError("edge config binding mismatch")
            if edge.payload.get("grants_execution_authority") is not False:
                raise GraphValidationError(
                    "graph edges must explicitly deny execution authority"
                )
            category = _edge_class(edge)
            GRAPH_ONTOLOGY.validate_edge(
                edge.edge_type,
                node_by_id[edge.source_node_cid].node_type,
                node_by_id[edge.target_node_cid].node_type,
                edge_class=category,
            )
            if category is GraphEdgeClass.SIMILARITY and (
                edge.authority.value != "non_authoritative"
                or edge.payload.get("authoritative") is not False
            ):
                raise GraphValidationError(
                    "similarity edges must be explicitly non-authoritative"
                )

        expected_outgoing, expected_incoming = _build_adjacency(nodes, edges)
        outgoing = (
            _freeze_adjacency(self.outgoing, "outgoing")
            if self.outgoing
            else _freeze_adjacency(expected_outgoing, "outgoing")
        )
        incoming = (
            _freeze_adjacency(self.incoming, "incoming")
            if self.incoming
            else _freeze_adjacency(expected_incoming, "incoming")
        )
        if dict(outgoing) != expected_outgoing or dict(incoming) != expected_incoming:
            raise GraphValidationError("adjacency index does not match graph edges")
        object.__setattr__(self, "outgoing", outgoing)
        object.__setattr__(self, "incoming", incoming)

        computed_node_root = _identity_root(
            {"records": [item.to_dict() for item in nodes]}, "node-table"
        )
        computed_edge_root = _identity_root(
            {"records": [item.to_dict() for item in edges]}, "edge-table"
        )
        computed_adjacency_root = _identity_root(
            {
                "incoming": {
                    key: list(value) for key, value in incoming.items()
                },
                "outgoing": {
                    key: list(value) for key, value in outgoing.items()
                },
            },
            "adjacency-index",
        )
        for name, supplied, computed in (
            ("node_table_root", self.node_table_root, computed_node_root),
            ("edge_table_root", self.edge_table_root, computed_edge_root),
            ("adjacency_root", self.adjacency_root, computed_adjacency_root),
        ):
            if supplied and supplied != computed:
                raise GraphValidationError(f"{name} does not match graph content")
            object.__setattr__(self, name, computed)
        computed_graph_root = _identity_root(
            {
                "adjacency_root": computed_adjacency_root,
                "config_cid": self.config_cid,
                "edge_table_root": computed_edge_root,
                "node_table_root": computed_node_root,
                "ontology_version": self.ontology_version,
                "projection_cids": list(projection_cids),
                "schema_version": self.schema_version,
                "source_cids": list(source_cids),
            },
            "root",
        )
        if self.graph_root and self.graph_root != computed_graph_root:
            raise GraphValidationError(
                "graph_root does not match canonical graph tables"
            )
        object.__setattr__(self, "graph_root", computed_graph_root)

    @property
    def cid(self) -> str:
        return self.graph_root

    @property
    def semantic_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(
            item
            for item in self.edges
            if _edge_class(item) is not GraphEdgeClass.SIMILARITY
        )

    @property
    def similarity_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(
            item
            for item in self.edges
            if _edge_class(item) is GraphEdgeClass.SIMILARITY
        )

    def edge_ids_from(self, node_cid: str) -> tuple[str, ...]:
        try:
            return self.outgoing[node_cid]
        except KeyError as exc:
            raise GraphValidationError("unknown adjacency node CID") from exc

    def edge_ids_to(self, node_cid: str) -> tuple[str, ...]:
        try:
            return self.incoming[node_cid]
        except KeyError as exc:
            raise GraphValidationError("unknown adjacency node CID") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency_root": self.adjacency_root,
            "config_cid": self.config_cid,
            "edge_table_root": self.edge_table_root,
            "edges": [item.to_dict() for item in self.edges],
            "graph_root": self.graph_root,
            "incoming": {
                key: list(value) for key, value in self.incoming.items()
            },
            "node_table_root": self.node_table_root,
            "nodes": [item.to_dict() for item in self.nodes],
            "ontology_version": self.ontology_version,
            "outgoing": {
                key: list(value) for key, value in self.outgoing.items()
            },
            "projection_cids": list(self.projection_cids),
            "schema_version": self.schema_version,
            "source_cids": list(self.source_cids),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CVEfixesGraph":
        if not isinstance(value, Mapping):
            raise GraphValidationError("graph must be a mapping")
        allowed = {
            "adjacency_root",
            "config_cid",
            "edge_table_root",
            "edges",
            "graph_root",
            "incoming",
            "node_table_root",
            "nodes",
            "ontology_version",
            "outgoing",
            "projection_cids",
            "schema_version",
            "source_cids",
        }
        unknown = sorted(set(value) - allowed)
        missing = sorted(allowed - set(value))
        if unknown or missing:
            details = []
            if unknown:
                details.append(f"unknown fields: {', '.join(unknown)}")
            if missing:
                details.append(f"missing fields: {', '.join(missing)}")
            raise GraphValidationError("; ".join(details))
        try:
            nodes = tuple(GraphNode.from_dict(item) for item in value["nodes"])
            edges = tuple(GraphEdge.from_dict(item) for item in value["edges"])
            return cls(
                nodes=nodes,
                edges=edges,
                source_cids=tuple(value["source_cids"]),
                projection_cids=tuple(value["projection_cids"]),
                config_cid=value["config_cid"],
                outgoing=value["outgoing"],
                incoming=value["incoming"],
                node_table_root=value["node_table_root"],
                edge_table_root=value["edge_table_root"],
                adjacency_root=value["adjacency_root"],
                graph_root=value["graph_root"],
                schema_version=value["schema_version"],
                ontology_version=value["ontology_version"],
            )
        except GraphValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphValidationError(f"invalid graph artifact: {exc}") from exc

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "CVEfixesGraph":
        """Decode strict JSON and revalidate every record and table root."""

        if not isinstance(value, (str, bytes, bytearray)):
            raise GraphValidationError("graph JSON must be text or bytes")

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in items:
                if key in result:
                    raise GraphValidationError(
                        f"graph JSON contains duplicate field {key!r}"
                    )
                result[key] = item
            return result

        def reject_constant(constant: str) -> None:
            raise GraphValidationError(
                f"graph JSON contains non-finite number {constant}"
            )

        try:
            decoded = json.loads(
                value,
                object_pairs_hook=pairs,
                parse_constant=reject_constant,
            )
        except GraphValidationError:
            raise
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise GraphValidationError("graph is not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise GraphValidationError("graph JSON must contain an object")
        return cls.from_dict(decoded)


@dataclass(slots=True)
class _NodeSpec:
    node_type: GraphNodeType
    key: str
    source_cids: set[str] = field(default_factory=set)
    parent_cids: set[str] = field(default_factory=set)
    payload: dict[str, Any] = field(default_factory=dict)


class CVEfixesGraphBuilder:
    """Materialize validated projector results into a typed graph."""

    def __init__(self, config: GraphConfig = GraphConfig()) -> None:
        if not isinstance(config, GraphConfig):
            raise TypeError("config must be GraphConfig")
        self.config = config
        self.config_cid = config.cid

    def build(
        self,
        projections: Sequence[ProjectionResult],
        *,
        cwe_by_cve: Mapping[str, str] | None = None,
        similarity_observations: Sequence[SimilarityObservation] = (),
    ) -> CVEfixesGraph:
        if isinstance(projections, (str, bytes, bytearray)) or not isinstance(
            projections, Sequence
        ):
            raise TypeError("projections must be a sequence")
        if not projections:
            raise GraphBuildError("at least one projection is required")
        if not all(isinstance(item, ProjectionResult) for item in projections):
            raise TypeError("every projection must be ProjectionResult")
        if isinstance(
            similarity_observations, (str, bytes, bytearray)
        ) or not isinstance(similarity_observations, Sequence):
            raise TypeError("similarity_observations must be a sequence")
        if not all(
            isinstance(item, SimilarityObservation)
            for item in similarity_observations
        ):
            raise TypeError(
                "every similarity observation must be SimilarityObservation"
            )
        cwe_by_cve = cwe_by_cve or {}
        if not isinstance(cwe_by_cve, Mapping):
            raise TypeError("cwe_by_cve must be a mapping")
        for cve_id, cwe_id in cwe_by_cve.items():
            if not isinstance(cve_id, str) or not cve_id.startswith("CVE-"):
                raise GraphBuildError("cwe_by_cve keys must be CVE IDs")
            if not isinstance(cwe_id, str) or not cwe_id.startswith("CWE-"):
                raise GraphBuildError("cwe_by_cve values must be CWE IDs")

        ordered = tuple(sorted(projections, key=lambda item: item.cid))
        if len({item.cid for item in ordered}) != len(ordered):
            raise GraphBuildError("duplicate projection")
        specs: dict[tuple[GraphNodeType, str], _NodeSpec] = {}
        relations: set[
            tuple[
                GraphEdgeType,
                tuple[GraphNodeType, str],
                tuple[GraphNodeType, str],
            ]
        ] = set()
        record_keys: dict[str, tuple[GraphNodeType, str]] = {}

        def add_node(
            node_type: GraphNodeType,
            key: str,
            *,
            source_cids: Sequence[str],
            parent_cids: Sequence[str],
            payload: Mapping[str, Any],
            record_cid: str = "",
        ) -> tuple[GraphNodeType, str]:
            identity = (node_type, key)
            spec = specs.get(identity)
            clean_payload = dict(payload)
            clean_payload["grants_execution_authority"] = False
            clean_payload["retrieval_only"] = True
            if spec is None:
                spec = _NodeSpec(node_type=node_type, key=key)
                spec.payload = clean_payload
                specs[identity] = spec
            elif spec.payload != clean_payload:
                raise GraphBuildError(
                    f"conflicting payload for {node_type.value} node {key!r}"
                )
            spec.source_cids.update(source_cids)
            spec.parent_cids.update(parent_cids)
            if record_cid:
                previous = record_keys.setdefault(record_cid, identity)
                if previous != identity:
                    raise GraphBuildError("record maps to conflicting graph nodes")
            return identity

        for projection in ordered:
            source_key = add_node(
                GraphNodeType.SOURCE,
                projection.source_cid,
                source_cids=(projection.source_cid,),
                parent_cids=(projection.cid,),
                payload={"source_cid": projection.source_cid},
            )
            units_by_cid = {item.cid: item for item in projection.code_units}
            cve_ids = {
                item.payload.get("cve_id")
                for item in projection.code_units
                if isinstance(item.payload.get("cve_id"), str)
                and item.payload.get("cve_id")
            }
            repositories = {
                item.payload.get("repository")
                for item in projection.code_units
                if isinstance(item.payload.get("repository"), str)
                and item.payload.get("repository")
            }
            commits = {
                item.payload.get("commit_hash")
                for item in projection.code_units
                if isinstance(item.payload.get("commit_hash"), str)
                and item.payload.get("commit_hash")
            }
            if len(cve_ids) > 1 or len(repositories) > 1 or len(commits) > 1:
                raise GraphBuildError(
                    "one projection cannot describe conflicting CVE metadata"
                )
            cve_key = (
                add_node(
                    GraphNodeType.CVE,
                    next(iter(cve_ids)),
                    source_cids=(projection.source_cid,),
                    parent_cids=(projection.cid,),
                    payload={"cve_id": next(iter(cve_ids))},
                )
                if cve_ids
                else None
            )
            repository_key = (
                add_node(
                    GraphNodeType.REPOSITORY,
                    next(iter(repositories)),
                    source_cids=(projection.source_cid,),
                    parent_cids=(projection.cid,),
                    payload={"repository": next(iter(repositories))},
                )
                if repositories
                else None
            )
            commit_key = (
                add_node(
                    GraphNodeType.COMMIT,
                    next(iter(commits)),
                    source_cids=(projection.source_cid,),
                    parent_cids=(projection.cid,),
                    payload={"commit_hash": next(iter(commits))},
                )
                if commits
                else None
            )
            language_key = add_node(
                GraphNodeType.LANGUAGE,
                projection.language,
                source_cids=(projection.source_cid,),
                parent_cids=(projection.cid,),
                payload={"language": projection.language},
            )
            if cve_key is not None:
                relations.add((GraphEdgeType.DESCRIBES, source_key, cve_key))
                if repository_key is not None:
                    relations.add((GraphEdgeType.AFFECTS, cve_key, repository_key))
                if commit_key is not None:
                    relations.add((GraphEdgeType.FIXED_BY, cve_key, commit_key))
                cwe_id = cwe_by_cve.get(cve_key[1])
                if cwe_id:
                    cwe_key = add_node(
                        GraphNodeType.CWE,
                        cwe_id,
                        source_cids=(projection.source_cid,),
                        parent_cids=(projection.cid,),
                        payload={"cwe_id": cwe_id},
                    )
                    relations.add(
                        (GraphEdgeType.CLASSIFIED_AS, cve_key, cwe_key)
                    )
            if repository_key is not None and commit_key is not None:
                relations.add(
                    (GraphEdgeType.CONTAINS, repository_key, commit_key)
                )

            for unit in projection.code_units:
                unit_key = add_node(
                    GraphNodeType.CODE_UNIT,
                    unit.cid,
                    source_cids=unit.source_cids,
                    parent_cids=(unit.cid, projection.cid),
                    payload={
                        "code_unit_cid": unit.cid,
                        "evidence_polarity": unit.payload.get(
                            "evidence_polarity", ""
                        ),
                        "path": unit.path,
                        "polarity": unit.polarity,
                        "unit_kind": unit.unit_kind,
                    },
                    record_cid=unit.cid,
                )
                if commit_key is not None:
                    relations.add((GraphEdgeType.CHANGES, commit_key, unit_key))
                relations.add(
                    (GraphEdgeType.WRITTEN_IN, unit_key, language_key)
                )
            for fact in projection.semantic_facts:
                unit_key = record_keys.get(fact.code_unit_cid)
                if unit_key is None or fact.code_unit_cid not in units_by_cid:
                    raise GraphBuildError(
                        "semantic fact references an unknown code unit"
                    )
                fact_type = _semantic_node_type(fact)
                fact_key = add_node(
                    fact_type,
                    fact.cid,
                    source_cids=(fact.source_cid,),
                    parent_cids=(fact.cid, fact.code_unit_cid, projection.cid),
                    payload={
                        "confidence": fact.confidence,
                        "evidence_polarity": fact.evidence_polarity.value,
                        "extraction_method": fact.extraction_method.value,
                        "fact_cid": fact.cid,
                        "predicate": fact.predicate,
                    },
                    record_cid=fact.cid,
                )
                relations.add((GraphEdgeType.OBSERVES, unit_key, fact_key))
            for pair in projection.pairs:
                _add_pair_relation(pair, record_keys, relations)

        if len(specs) > self.config.max_nodes:
            raise GraphBuildError(
                f"graph has {len(specs)} nodes; max_nodes is "
                f"{self.config.max_nodes}"
            )
        nodes: list[GraphNode] = []
        node_by_key: dict[tuple[GraphNodeType, str], GraphNode] = {}
        for identity, spec in sorted(
            specs.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            node = GraphNode(
                source_cids=tuple(spec.source_cids),
                parent_cids=tuple(spec.parent_cids),
                config_cid=self.config_cid,
                node_type=spec.node_type.value,
                payload=spec.payload,
            )
            nodes.append(node)
            node_by_key[identity] = node

        edges: list[GraphEdge] = []
        for edge_type, source_key, target_key in sorted(
            relations,
            key=lambda item: (
                item[0].value,
                item[1][0].value,
                item[1][1],
                item[2][0].value,
                item[2][1],
            ),
        ):
            edges.append(
                self._edge(
                    edge_type,
                    node_by_key[source_key],
                    node_by_key[target_key],
                )
            )
        for observation in sorted(
            similarity_observations,
            key=lambda item: (
                item.source_record_cid,
                item.target_record_cid,
                item.model_id,
                item.model_revision,
                item.score,
            ),
        ):
            try:
                source = node_by_key[record_keys[observation.source_record_cid]]
                target = node_by_key[record_keys[observation.target_record_cid]]
            except KeyError as exc:
                raise GraphBuildError(
                    "similarity endpoint is outside the supplied projections"
                ) from exc
            if source.node_type != target.node_type:
                raise GraphBuildError(
                    "similarity endpoints must have the same node type"
                )
            edges.append(
                self._edge(
                    GraphEdgeType.SIMILAR_TO,
                    source,
                    target,
                    extra_source_cids=observation.evidence_cids,
                    payload=observation.to_dict(),
                )
            )
        if len(edges) > self.config.max_edges:
            raise GraphBuildError(
                f"graph has {len(edges)} edges; max_edges is "
                f"{self.config.max_edges}"
            )
        return CVEfixesGraph(
            nodes=tuple(nodes),
            edges=tuple(edges),
            source_cids=tuple(
                sorted(
                    {
                        source
                        for projection in ordered
                        for source in (projection.source_cid,)
                    }
                    | {
                        evidence
                        for observation in similarity_observations
                        for evidence in observation.evidence_cids
                    }
                )
            ),
            projection_cids=tuple(item.cid for item in ordered),
            config_cid=self.config_cid,
        )

    def _edge(
        self,
        edge_type: GraphEdgeType,
        source: GraphNode,
        target: GraphNode,
        *,
        extra_source_cids: Sequence[str] = (),
        payload: Mapping[str, Any] | None = None,
    ) -> GraphEdge:
        category = (
            GraphEdgeClass.SIMILARITY
            if edge_type is GraphEdgeType.SIMILAR_TO
            else (
                GraphEdgeClass.SEMANTIC
                if edge_type is GraphEdgeType.OBSERVES
                else GraphEdgeClass.STRUCTURAL
            )
        )
        GRAPH_ONTOLOGY.validate_edge(
            edge_type,
            source.node_type,
            target.node_type,
            edge_class=category,
        )
        edge_payload = dict(payload or {})
        edge_payload.update(
            {
                "authoritative": False,
                "edge_class": category.value,
                "grants_execution_authority": False,
                "retrieval_only": True,
            }
        )
        source_evidence = (
            set(source.source_cids) & set(target.source_cids)
        ) | set(extra_source_cids)
        if not source_evidence:
            raise GraphBuildError(
                "graph edge has no shared or explicit source evidence"
            )
        return GraphEdge(
            # An edge is supported by evidence shared by both endpoints, plus
            # any explicit observation receipt.  Copying the union of
            # aggregate endpoint provenance into every edge is both
            # semantically too broad and quadratic for common CVE/language/
            # repository nodes.
            source_cids=tuple(sorted(source_evidence)),
            parent_cids=(source.cid, target.cid),
            config_cid=self.config_cid,
            edge_type=edge_type.value,
            source_node_cid=source.cid,
            target_node_cid=target.cid,
            payload=edge_payload,
        )


def _semantic_node_type(fact: SemanticFact) -> GraphNodeType:
    return {
        SemanticKind.PRECONDITION: GraphNodeType.PRECONDITION,
        SemanticKind.ACTION: GraphNodeType.ACTION,
        SemanticKind.EFFECT: GraphNodeType.EFFECT,
        SemanticKind.MITIGATION: GraphNodeType.MITIGATION,
    }[fact.kind]


def _add_pair_relation(
    pair: VulnerableFixedPair,
    record_keys: Mapping[str, tuple[GraphNodeType, str]],
    relations: set[
        tuple[
            GraphEdgeType,
            tuple[GraphNodeType, str],
            tuple[GraphNodeType, str],
        ]
    ],
) -> None:
    if not pair.complete:
        return
    try:
        vulnerable = record_keys[pair.vulnerable_cid]
        fixed = record_keys[pair.fixed_cid]
    except KeyError as exc:
        raise GraphBuildError("pair endpoint is outside the projection") from exc
    relations.add((GraphEdgeType.PAIRS_WITH, vulnerable, fixed))


def build_cvefixes_graph(
    projections: Sequence[ProjectionResult],
    *,
    config: GraphConfig = GraphConfig(),
    cwe_by_cve: Mapping[str, str] | None = None,
    similarity_observations: Sequence[SimilarityObservation] = (),
) -> CVEfixesGraph:
    """Convenience wrapper for deterministic graph construction."""

    return CVEfixesGraphBuilder(config).build(
        projections,
        cwe_by_cve=cwe_by_cve,
        similarity_observations=similarity_observations,
    )


# Descriptive compatibility aliases for downstream retrieval/release tasks.
TypedGraphRAGBuilder = CVEfixesGraphBuilder
GraphArtifact = CVEfixesGraph
GraphRAGGraph = CVEfixesGraph
NodeType = GraphNodeType
EdgeType = GraphEdgeType
EdgeClass = GraphEdgeClass
build_graph = build_cvefixes_graph


__all__ = [
    "CVEfixesGraph",
    "CVEfixesGraphBuilder",
    "CVEFIXES_GRAPH_ONTOLOGY_VERSION",
    "CVEFIXES_GRAPH_SCHEMA_VERSION",
    "EdgeClass",
    "EdgeType",
    "GRAPH_CONFIG_SCHEMA_VERSION",
    "GRAPH_ONTOLOGY",
    "GRAPH_ONTOLOGY_VERSION",
    "GRAPH_SCHEMA_VERSION",
    "GraphArtifact",
    "GraphBuildError",
    "GraphConfig",
    "GraphEdgeClass",
    "GraphEdgeType",
    "GraphNodeType",
    "GraphOntology",
    "GraphRAGGraph",
    "GraphValidationError",
    "NodeType",
    "SimilarityObservation",
    "TypedGraphRAGBuilder",
    "build_cvefixes_graph",
    "build_graph",
]
