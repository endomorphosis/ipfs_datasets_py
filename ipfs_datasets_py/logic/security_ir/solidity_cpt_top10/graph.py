"""Deterministic, provenance-bound GraphRAG materialization for Solidity CPT.

The graph is a retrieval artifact, never an authorization artifact.  Every
node and edge binds exact source and producer-configuration CIDs.  Approximate
similarity is kept in a distinct edge class and is explicitly non-authoritative.

Four authority classes remain separate node types and authority-type labels:

* ``observed_syntax``
* ``inferred_candidate``
* ``reviewed_claim``
* ``verified_result``

Corpus quality scores may appear only as ``quality_score`` nodes and never as
security or safety labels.
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
    FactKind,
    ProjectionResult,
    StructuralFact,
    UnitKind,
)
from .schemas import GraphEdge, GraphNode, canonical_config_cid
from .vocabulary import SolidityAuthorityType, require_authority_type


GRAPH_SCHEMA_VERSION: Final = "solidity-cpt-graphrag-graph/v1"
GRAPH_ONTOLOGY_VERSION: Final = "solidity-cpt-graphrag-ontology/v1"
GRAPH_CONFIG_SCHEMA_VERSION: Final = "solidity-cpt-graphrag-config/v1"
GRAPH_IDENTITY_DOMAIN: Final = "solidity-cpt-security-ir/graphrag-graph"
SOLIDITY_GRAPH_SCHEMA_VERSION: Final = GRAPH_SCHEMA_VERSION
SOLIDITY_GRAPH_ONTOLOGY_VERSION: Final = GRAPH_ONTOLOGY_VERSION

_CID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_IR_CORE_CID_HEADER = b"\x01\x55\x12\x20"


class GraphBuildError(ValueError):
    """Raised when projections cannot be safely materialized."""


class GraphValidationError(ValueError):
    """Raised when a graph or graph record violates the reviewed contract."""


class GraphNodeType(str, Enum):
    """Reviewed node vocabulary for the Solidity contract-security graph."""

    SOURCE = "source"
    SOURCE_UNIT = "source_unit"
    REPOSITORY = "repository"
    LICENSE = "license"
    COMPILER = "compiler"
    ADDRESS_HINT = "address_hint"
    CONTRACT = "contract"
    LIBRARY = "library"
    INTERFACE = "interface"
    FUNCTION = "function"
    MODIFIER = "modifier"
    VARIABLE = "variable"
    EVENT = "event"
    ERROR = "error"
    CALL_SITE = "call_site"
    STATE_ACCESS = "state_access"
    EFFECT_SUMMARY = "effect_summary"
    SECURITY_CONCEPT = "security_concept"
    CANDIDATE_CLAIM = "candidate_claim"
    ASSUMPTION = "assumption"
    MITIGATION = "mitigation"
    PROOF_OBLIGATION = "proof_obligation"
    FORMAL_VIEW = "formal_view"
    PRODUCER_CONFIG = "producer_config"
    OBSERVED_SYNTAX = "observed_syntax"
    INFERRED_CANDIDATE = "inferred_candidate"
    REVIEWED_CLAIM = "reviewed_claim"
    VERIFIED_RESULT = "verified_result"
    QUALITY_SCORE = "quality_score"


class GraphEdgeType(str, Enum):
    """Reviewed, directed relationship vocabulary."""

    CONTAINS = "contains"
    DECLARES = "declares"
    INHERITS = "inherits"
    IMPORTS = "imports"
    CALLS = "calls"
    READS = "reads"
    WRITES = "writes"
    EMITS = "emits"
    GUARDS = "guards"
    MAY_EFFECT = "may_effect"
    DERIVED_FROM = "derived_from"
    GROUNDED_IN = "grounded_in"
    HAS_LICENSE = "has_license"
    HAS_COMPILER = "has_compiler"
    CANDIDATE_FOR = "candidate_for"
    SIMILAR_TO = "similar_to"
    STRUCTURALLY_SIMILAR = "structurally_similar"
    SEMANTICALLY_SIMILAR = "semantically_similar"


class GraphEdgeClass(str, Enum):
    """Edge partition used to exclude approximate evidence from authority."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    SIMILARITY = "similarity"


_SIMILARITY_EDGES: Final = frozenset(
    {
        GraphEdgeType.SIMILAR_TO,
        GraphEdgeType.STRUCTURALLY_SIMILAR,
        GraphEdgeType.SEMANTICALLY_SIMILAR,
    }
)
_SEMANTIC_EDGES: Final = frozenset(
    {
        GraphEdgeType.CANDIDATE_FOR,
        GraphEdgeType.MAY_EFFECT,
    }
)
_AUTHORITY_NODE_TYPES: Final = frozenset(
    {
        GraphNodeType.OBSERVED_SYNTAX,
        GraphNodeType.INFERRED_CANDIDATE,
        GraphNodeType.REVIEWED_CLAIM,
        GraphNodeType.VERIFIED_RESULT,
    }
)
_UNIT_KIND_TO_NODE: Final = MappingProxyType(
    {
        UnitKind.SOURCE_UNIT.value: GraphNodeType.SOURCE_UNIT,
        UnitKind.CONTRACT.value: GraphNodeType.CONTRACT,
        UnitKind.LIBRARY.value: GraphNodeType.LIBRARY,
        UnitKind.INTERFACE.value: GraphNodeType.INTERFACE,
        UnitKind.FUNCTION.value: GraphNodeType.FUNCTION,
        UnitKind.MODIFIER.value: GraphNodeType.MODIFIER,
        UnitKind.VARIABLE.value: GraphNodeType.VARIABLE,
        UnitKind.EVENT.value: GraphNodeType.EVENT,
        UnitKind.ERROR.value: GraphNodeType.ERROR,
        UnitKind.CALL_SITE.value: GraphNodeType.CALL_SITE,
        UnitKind.STATE_ACCESS.value: GraphNodeType.STATE_ACCESS,
        UnitKind.EFFECT.value: GraphNodeType.EFFECT_SUMMARY,
        UnitKind.AUTH_GUARD.value: GraphNodeType.FUNCTION,
        UnitKind.ASSEMBLY.value: GraphNodeType.FUNCTION,
    }
)
_FACT_KIND_TO_NODE: Final = MappingProxyType(
    {
        FactKind.SECURITY_CONCEPT: GraphNodeType.SECURITY_CONCEPT,
        FactKind.ASSUMPTION: GraphNodeType.ASSUMPTION,
        FactKind.MITIGATION: GraphNodeType.MITIGATION,
        FactKind.PROOF_OBLIGATION: GraphNodeType.PROOF_OBLIGATION,
        FactKind.LICENSE: GraphNodeType.LICENSE,
        FactKind.COMPILER: GraphNodeType.COMPILER,
        FactKind.PROVENANCE: GraphNodeType.SOURCE,
    }
)


def _enum_value(enum_type: type[Enum], value: Enum | str, label: str) -> Any:
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

        if edge in _SIMILARITY_EDGES:
            expected_class = GraphEdgeClass.SIMILARITY
        elif edge in _SEMANTIC_EDGES:
            expected_class = GraphEdgeClass.SEMANTIC
        else:
            expected_class = GraphEdgeClass.STRUCTURAL
        if category is not expected_class:
            raise GraphValidationError(
                f"{edge.value} must be classified as {expected_class.value}"
            )

        declaration_nodes = {
            GraphNodeType.SOURCE_UNIT,
            GraphNodeType.CONTRACT,
            GraphNodeType.LIBRARY,
            GraphNodeType.INTERFACE,
            GraphNodeType.FUNCTION,
            GraphNodeType.MODIFIER,
            GraphNodeType.VARIABLE,
            GraphNodeType.EVENT,
            GraphNodeType.ERROR,
        }
        container_nodes = {
            GraphNodeType.SOURCE,
            GraphNodeType.SOURCE_UNIT,
            GraphNodeType.CONTRACT,
            GraphNodeType.LIBRARY,
            GraphNodeType.INTERFACE,
            GraphNodeType.FUNCTION,
        }
        valid = False
        if edge is GraphEdgeType.CONTAINS:
            valid = source in container_nodes and target in declaration_nodes | {
                GraphNodeType.CALL_SITE,
                GraphNodeType.STATE_ACCESS,
                GraphNodeType.EFFECT_SUMMARY,
                GraphNodeType.OBSERVED_SYNTAX,
                GraphNodeType.INFERRED_CANDIDATE,
                GraphNodeType.REVIEWED_CLAIM,
                GraphNodeType.VERIFIED_RESULT,
                GraphNodeType.SECURITY_CONCEPT,
                GraphNodeType.CANDIDATE_CLAIM,
                GraphNodeType.ASSUMPTION,
                GraphNodeType.MITIGATION,
                GraphNodeType.PROOF_OBLIGATION,
                GraphNodeType.LICENSE,
                GraphNodeType.COMPILER,
                GraphNodeType.ADDRESS_HINT,
                GraphNodeType.QUALITY_SCORE,
            }
        elif edge is GraphEdgeType.DECLARES:
            valid = source in {
                GraphNodeType.SOURCE_UNIT,
                GraphNodeType.CONTRACT,
                GraphNodeType.LIBRARY,
                GraphNodeType.INTERFACE,
            } and target in declaration_nodes
        elif edge is GraphEdgeType.INHERITS:
            valid = source in {
                GraphNodeType.CONTRACT,
                GraphNodeType.LIBRARY,
                GraphNodeType.INTERFACE,
            } and target in {
                GraphNodeType.CONTRACT,
                GraphNodeType.LIBRARY,
                GraphNodeType.INTERFACE,
                GraphNodeType.CANDIDATE_CLAIM,
            }
        elif edge is GraphEdgeType.IMPORTS:
            valid = source is GraphNodeType.SOURCE_UNIT and target in {
                GraphNodeType.SOURCE_UNIT,
                GraphNodeType.CANDIDATE_CLAIM,
            }
        elif edge is GraphEdgeType.CALLS:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.CONTRACT,
                GraphNodeType.CALL_SITE,
            } and target in {
                GraphNodeType.FUNCTION,
                GraphNodeType.CALL_SITE,
                GraphNodeType.CANDIDATE_CLAIM,
            }
        elif edge is GraphEdgeType.READS:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.STATE_ACCESS,
            } and target in {
                GraphNodeType.VARIABLE,
                GraphNodeType.STATE_ACCESS,
            }
        elif edge is GraphEdgeType.WRITES:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.STATE_ACCESS,
            } and target in {
                GraphNodeType.VARIABLE,
                GraphNodeType.STATE_ACCESS,
            }
        elif edge is GraphEdgeType.EMITS:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.CONTRACT,
            } and target is GraphNodeType.EVENT
        elif edge is GraphEdgeType.GUARDS:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.MODIFIER,
            } and target in {
                GraphNodeType.MODIFIER,
                GraphNodeType.FUNCTION,
                GraphNodeType.CANDIDATE_CLAIM,
            }
        elif edge is GraphEdgeType.MAY_EFFECT:
            valid = source in {
                GraphNodeType.FUNCTION,
                GraphNodeType.CALL_SITE,
                GraphNodeType.EFFECT_SUMMARY,
            } and target is GraphNodeType.EFFECT_SUMMARY
        elif edge is GraphEdgeType.DERIVED_FROM:
            valid = target is GraphNodeType.SOURCE
        elif edge is GraphEdgeType.GROUNDED_IN:
            valid = target in declaration_nodes | {
                GraphNodeType.SOURCE_UNIT,
                GraphNodeType.CALL_SITE,
                GraphNodeType.STATE_ACCESS,
                GraphNodeType.EFFECT_SUMMARY,
            } and source in _AUTHORITY_NODE_TYPES | {
                GraphNodeType.SECURITY_CONCEPT,
                GraphNodeType.CANDIDATE_CLAIM,
                GraphNodeType.ASSUMPTION,
                GraphNodeType.MITIGATION,
                GraphNodeType.PROOF_OBLIGATION,
                GraphNodeType.FORMAL_VIEW,
                GraphNodeType.LICENSE,
                GraphNodeType.COMPILER,
                GraphNodeType.EFFECT_SUMMARY,
            }
        elif edge is GraphEdgeType.HAS_LICENSE:
            valid = (
                source
                in {
                    GraphNodeType.SOURCE,
                    GraphNodeType.SOURCE_UNIT,
                }
                and target is GraphNodeType.LICENSE
            )
        elif edge is GraphEdgeType.HAS_COMPILER:
            valid = (
                source
                in {
                    GraphNodeType.SOURCE,
                    GraphNodeType.SOURCE_UNIT,
                }
                and target is GraphNodeType.COMPILER
            )
        elif edge is GraphEdgeType.CANDIDATE_FOR:
            valid = source in {
                GraphNodeType.INFERRED_CANDIDATE,
                GraphNodeType.CANDIDATE_CLAIM,
                GraphNodeType.SOURCE_UNIT,
                GraphNodeType.CONTRACT,
                GraphNodeType.FUNCTION,
            } and target in {
                GraphNodeType.SECURITY_CONCEPT,
                GraphNodeType.CANDIDATE_CLAIM,
            }
        elif edge in _SIMILARITY_EDGES:
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
    edge_type: GraphEdgeType = GraphEdgeType.SIMILAR_TO

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
        edge = _enum_value(GraphEdgeType, self.edge_type, "edge_type")
        if edge not in _SIMILARITY_EDGES:
            raise GraphValidationError(
                "similarity observation edge_type must be a similarity edge"
            )
        object.__setattr__(self, "edge_type", edge)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "non_authoritative",
            "edge_type": self.edge_type.value,
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


def _identity_root(value: Mapping[str, Any], domain_suffix: str) -> str:
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
class SoliditySecurityGraph:
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
            if node.node_type == GraphNodeType.QUALITY_SCORE.value:
                if node.payload.get("is_security_label") is not False:
                    raise GraphValidationError(
                        "quality_score nodes must not be security labels"
                    )
            # Authority-type nodes must declare the matching authority_type.
            if node.node_type in {item.value for item in _AUTHORITY_NODE_TYPES}:
                declared = node.payload.get("authority_type")
                if declared != node.node_type:
                    raise GraphValidationError(
                        "authority node type must match authority_type payload"
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
                edge.payload.get("authority") != "non_authoritative"
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

    def nodes_by_type(self, node_type: GraphNodeType | str) -> tuple[GraphNode, ...]:
        value = (
            node_type.value
            if isinstance(node_type, GraphNodeType)
            else str(node_type)
        )
        return tuple(item for item in self.nodes if item.node_type == value)

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
    def from_dict(cls, value: Mapping[str, Any]) -> "SoliditySecurityGraph":
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
    ) -> "SoliditySecurityGraph":
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


def _authority_node_type(
    authority: SolidityAuthorityType,
) -> GraphNodeType:
    return {
        SolidityAuthorityType.OBSERVED_SYNTAX: GraphNodeType.OBSERVED_SYNTAX,
        SolidityAuthorityType.INFERRED_CANDIDATE: GraphNodeType.INFERRED_CANDIDATE,
        SolidityAuthorityType.REVIEWED_CLAIM: GraphNodeType.REVIEWED_CLAIM,
        SolidityAuthorityType.VERIFIED_RESULT: GraphNodeType.VERIFIED_RESULT,
    }[authority]


def _fact_node_type(fact: StructuralFact) -> GraphNodeType:
    # Authority-type partitions are first-class and non-interchangeable.
    # Reviewed and verified facts always land on their authority node type.
    if fact.authority_type in {
        SolidityAuthorityType.REVIEWED_CLAIM,
        SolidityAuthorityType.VERIFIED_RESULT,
    }:
        return _authority_node_type(fact.authority_type)
    if fact.authority_type is SolidityAuthorityType.INFERRED_CANDIDATE:
        # Inferred candidates stay on the inferred partition (or concept).
        if fact.kind is FactKind.SECURITY_CONCEPT:
            return GraphNodeType.SECURITY_CONCEPT
        return GraphNodeType.INFERRED_CANDIDATE
    if fact.kind is FactKind.LICENSE:
        return GraphNodeType.LICENSE
    if fact.kind is FactKind.COMPILER:
        return GraphNodeType.COMPILER
    if fact.kind is FactKind.SECURITY_CONCEPT:
        return GraphNodeType.SECURITY_CONCEPT
    if fact.kind is FactKind.ASSUMPTION:
        return GraphNodeType.ASSUMPTION
    if fact.kind is FactKind.MITIGATION:
        return GraphNodeType.MITIGATION
    if fact.kind is FactKind.PROOF_OBLIGATION:
        return GraphNodeType.PROOF_OBLIGATION
    # Deterministic syntax and residual structural facts.
    return GraphNodeType.OBSERVED_SYNTAX


class SolidityGraphBuilder:
    """Materialize validated projector results into a typed security graph."""

    def __init__(self, config: GraphConfig = GraphConfig()) -> None:
        if not isinstance(config, GraphConfig):
            raise TypeError("config must be GraphConfig")
        self.config = config
        self.config_cid = config.cid

    def build(
        self,
        projections: Sequence[ProjectionResult],
        *,
        similarity_observations: Sequence[SimilarityObservation] = (),
    ) -> SoliditySecurityGraph:
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
            if "authority_type" not in clean_payload and node_type in _AUTHORITY_NODE_TYPES:
                clean_payload["authority_type"] = node_type.value
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
                    raise GraphBuildError(
                        "record maps to conflicting graph nodes"
                    )
            return identity

        for projection in ordered:
            source_key = add_node(
                GraphNodeType.SOURCE,
                projection.source_cid,
                source_cids=(projection.source_cid,),
                parent_cids=(projection.cid,),
                payload={"source_cid": projection.source_cid},
            )
            config_key = add_node(
                GraphNodeType.PRODUCER_CONFIG,
                projection.config_cid,
                source_cids=(projection.source_cid,),
                parent_cids=(projection.cid,),
                payload={"config_cid": projection.config_cid},
            )
            relations.add(
                (GraphEdgeType.DERIVED_FROM, config_key, source_key)
            )

            units_by_cid = {item.cid: item for item in projection.code_units}
            unit_keys: dict[str, tuple[GraphNodeType, str]] = {}
            for unit in projection.code_units:
                node_type = _UNIT_KIND_TO_NODE.get(
                    unit.unit_kind, GraphNodeType.SOURCE_UNIT
                )
                unit_key = add_node(
                    node_type,
                    unit.cid,
                    source_cids=unit.source_cids,
                    parent_cids=(unit.cid, projection.cid),
                    payload={
                        "code_unit_cid": unit.cid,
                        "name": unit.payload.get("name", ""),
                        "path": unit.path,
                        "unit_kind": unit.unit_kind,
                        "authority_type": unit.payload.get(
                            "authority_type",
                            SolidityAuthorityType.OBSERVED_SYNTAX.value,
                        ),
                    },
                    record_cid=unit.cid,
                )
                unit_keys[unit.cid] = unit_key
                relations.add(
                    (GraphEdgeType.DERIVED_FROM, unit_key, source_key)
                )
                if unit.unit_kind == UnitKind.SOURCE_UNIT.value:
                    relations.add(
                        (GraphEdgeType.CONTAINS, source_key, unit_key)
                    )

            # Link declaration hierarchy from parent_cids among code units.
            for unit in projection.code_units:
                unit_key = unit_keys[unit.cid]
                for parent_cid in unit.parent_cids:
                    if parent_cid in unit_keys and parent_cid != unit.cid:
                        parent_key = unit_keys[parent_cid]
                        if unit.unit_kind in {
                            UnitKind.FUNCTION.value,
                            UnitKind.MODIFIER.value,
                            UnitKind.VARIABLE.value,
                            UnitKind.EVENT.value,
                            UnitKind.ERROR.value,
                            UnitKind.CONTRACT.value,
                            UnitKind.LIBRARY.value,
                            UnitKind.INTERFACE.value,
                        }:
                            relations.add(
                                (GraphEdgeType.DECLARES, parent_key, unit_key)
                            )
                        else:
                            relations.add(
                                (GraphEdgeType.CONTAINS, parent_key, unit_key)
                            )
                    elif parent_cid == projection.source_cid:
                        relations.add(
                            (GraphEdgeType.DERIVED_FROM, unit_key, source_key)
                        )

            # Structural call/state edges among concrete declaration nodes.
            functions = [
                unit_keys[item.cid]
                for item in projection.code_units
                if item.unit_kind == UnitKind.FUNCTION.value
            ]
            call_sites = [
                unit_keys[item.cid]
                for item in projection.code_units
                if item.unit_kind == UnitKind.CALL_SITE.value
            ]
            variables = [
                unit_keys[item.cid]
                for item in projection.code_units
                if item.unit_kind == UnitKind.VARIABLE.value
            ]
            state_accesses = [
                (unit_keys[item.cid], item.payload.get("access_kind", ""))
                for item in projection.code_units
                if item.unit_kind == UnitKind.STATE_ACCESS.value
            ]
            effects = [
                unit_keys[item.cid]
                for item in projection.code_units
                if item.unit_kind == UnitKind.EFFECT.value
            ]
            events = [
                unit_keys[item.cid]
                for item in projection.code_units
                if item.unit_kind == UnitKind.EVENT.value
            ]
            for call_key in call_sites:
                for function_key in functions[:1]:
                    relations.add(
                        (GraphEdgeType.CALLS, function_key, call_key)
                    )
            for access_key, access_kind in state_accesses:
                for variable_key in variables[:1]:
                    if access_kind == "read":
                        relations.add(
                            (GraphEdgeType.READS, access_key, variable_key)
                        )
                    elif access_kind == "write":
                        relations.add(
                            (GraphEdgeType.WRITES, access_key, variable_key)
                        )
            for effect_key in effects:
                for function_key in functions[:1]:
                    relations.add(
                        (GraphEdgeType.MAY_EFFECT, function_key, effect_key)
                    )
            for event_key in events:
                for function_key in functions[:1]:
                    relations.add(
                        (GraphEdgeType.EMITS, function_key, event_key)
                    )

            for fact in projection.structural_facts:
                if fact.code_unit_cid not in units_by_cid:
                    raise GraphBuildError(
                        "structural fact references an unknown code unit"
                    )
                unit_key = unit_keys[fact.code_unit_cid]
                fact_type = _fact_node_type(fact)
                fact_key = add_node(
                    fact_type,
                    fact.cid,
                    source_cids=(fact.source_cid,),
                    parent_cids=(fact.cid, fact.code_unit_cid, projection.cid),
                    payload={
                        "authority_type": fact.authority_type.value,
                        "confidence": fact.confidence,
                        "extraction_method": fact.extraction_method.value,
                        "fact_cid": fact.cid,
                        "kind": fact.kind.value,
                        "predicate": fact.predicate,
                    },
                    record_cid=fact.cid,
                )
                relations.add(
                    (GraphEdgeType.GROUNDED_IN, fact_key, unit_key)
                )
                if fact.kind is FactKind.LICENSE:
                    relations.add(
                        (GraphEdgeType.HAS_LICENSE, source_key, fact_key)
                    )
                elif fact.kind is FactKind.COMPILER:
                    relations.add(
                        (GraphEdgeType.HAS_COMPILER, source_key, fact_key)
                    )
                elif fact.kind is FactKind.SECURITY_CONCEPT or (
                    fact.authority_type
                    is SolidityAuthorityType.INFERRED_CANDIDATE
                ):
                    relations.add(
                        (GraphEdgeType.CANDIDATE_FOR, unit_key, fact_key)
                    )

            if projection.quality_score is not None:
                quality_key = add_node(
                    GraphNodeType.QUALITY_SCORE,
                    f"{projection.cid}:quality",
                    source_cids=(projection.source_cid,),
                    parent_cids=(projection.cid,),
                    payload={
                        "is_security_label": False,
                        "score": projection.quality_score,
                    },
                )
                relations.add(
                    (GraphEdgeType.CONTAINS, source_key, quality_key)
                )

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
                parent_cids=tuple(spec.parent_cids) or (self.config_cid,),
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
            if source_key not in node_by_key or target_key not in node_by_key:
                continue
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
                    observation.edge_type,
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
        return SoliditySecurityGraph(
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
        if edge_type in _SIMILARITY_EDGES:
            category = GraphEdgeClass.SIMILARITY
        elif edge_type in _SEMANTIC_EDGES:
            category = GraphEdgeClass.SEMANTIC
        else:
            category = GraphEdgeClass.STRUCTURAL
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
        if category is GraphEdgeClass.SIMILARITY:
            edge_payload.setdefault("authority", "non_authoritative")
        return GraphEdge(
            source_cids=tuple(
                sorted(
                    set(source.source_cids)
                    | set(target.source_cids)
                    | set(extra_source_cids)
                )
            ),
            parent_cids=(source.cid, target.cid),
            config_cid=self.config_cid,
            edge_type=edge_type.value,
            source_node_cid=source.cid,
            target_node_cid=target.cid,
            payload=edge_payload,
        )


def build_solidity_security_graph(
    projections: Sequence[ProjectionResult],
    *,
    config: GraphConfig = GraphConfig(),
    similarity_observations: Sequence[SimilarityObservation] = (),
) -> SoliditySecurityGraph:
    """Convenience wrapper for deterministic graph construction."""

    return SolidityGraphBuilder(config).build(
        projections,
        similarity_observations=similarity_observations,
    )


# Descriptive compatibility aliases.
TypedGraphRAGBuilder = SolidityGraphBuilder
GraphArtifact = SoliditySecurityGraph
GraphRAGGraph = SoliditySecurityGraph
NodeType = GraphNodeType
EdgeType = GraphEdgeType
EdgeClass = GraphEdgeClass
build_graph = build_solidity_security_graph


__all__ = [
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
    "SOLIDITY_GRAPH_ONTOLOGY_VERSION",
    "SOLIDITY_GRAPH_SCHEMA_VERSION",
    "SimilarityObservation",
    "SolidityGraphBuilder",
    "SoliditySecurityGraph",
    "TypedGraphRAGBuilder",
    "build_graph",
    "build_solidity_security_graph",
]
