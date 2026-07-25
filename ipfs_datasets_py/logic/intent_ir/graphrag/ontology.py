"""Versioned ontology for the Intent corpus-evidence graph.

The corpus graph is a provenance and retrieval artifact, not a semantic
assertion graph.  Its vocabulary is deliberately small and versioned
independently from Intent IR.  All serialized nodes and edges carry both the
ontology version and immutable bindings to their contributing source records
and graph projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any


CORPUS_GRAPH_ONTOLOGY_VERSION = "intent-corpus-evidence-ontology/v1"
CORPUS_GRAPH_SCHEMA_VERSION = "intent-corpus-evidence-graph/v1"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class CorpusNodeType(str, Enum):
    """Node vocabulary for source-level corpus evidence."""

    DATASET_REVISION = "dataset_revision"
    BUNDLE = "bundle"
    SOURCE_DOCUMENT = "source_document"
    REPOSITORY = "repository"
    SKILL = "skill"
    SECTION = "section"
    SOURCE_SPAN = "source_span"
    LICENSE = "license"
    DOMAIN = "domain"
    AUTHOR_PUBLISHER = "author_publisher"
    TOOL_MENTION = "tool_mention"
    ENTITY_MENTION = "entity_mention"


class CorpusEdgeType(str, Enum):
    """Edge vocabulary for source-level corpus evidence."""

    CONTAINS = "CONTAINS"
    DERIVED_FROM = "DERIVED_FROM"
    SAME_PRIMARY_SOURCE = "SAME_PRIMARY_SOURCE"
    DUPLICATE_OF = "DUPLICATE_OF"
    MENTIONS = "MENTIONS"
    HAS_LICENSE = "HAS_LICENSE"
    HAS_DOMAIN = "HAS_DOMAIN"
    CITES = "CITES"
    NEIGHBOR_OF = "NEIGHBOR_OF"


_ALLOWED_ENDPOINTS: Mapping[
    CorpusEdgeType, frozenset[tuple[CorpusNodeType, CorpusNodeType]]
] = {
    CorpusEdgeType.CONTAINS: frozenset(
        {
            (CorpusNodeType.DATASET_REVISION, CorpusNodeType.BUNDLE),
            (CorpusNodeType.BUNDLE, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.REPOSITORY, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SKILL),
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SECTION),
            (CorpusNodeType.SKILL, CorpusNodeType.SECTION),
            (CorpusNodeType.SECTION, CorpusNodeType.SOURCE_SPAN),
        }
    ),
    CorpusEdgeType.DERIVED_FROM: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.REPOSITORY),
            (CorpusNodeType.SKILL, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.REPOSITORY, CorpusNodeType.AUTHOR_PUBLISHER),
        }
    ),
    CorpusEdgeType.SAME_PRIMARY_SOURCE: frozenset(
        {(CorpusNodeType.SKILL, CorpusNodeType.SKILL)}
    ),
    CorpusEdgeType.DUPLICATE_OF: frozenset(
        {(CorpusNodeType.SKILL, CorpusNodeType.SKILL)}
    ),
    CorpusEdgeType.MENTIONS: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.TOOL_MENTION),
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.ENTITY_MENTION),
            (CorpusNodeType.SKILL, CorpusNodeType.TOOL_MENTION),
            (CorpusNodeType.SKILL, CorpusNodeType.ENTITY_MENTION),
            (CorpusNodeType.SECTION, CorpusNodeType.TOOL_MENTION),
            (CorpusNodeType.SECTION, CorpusNodeType.ENTITY_MENTION),
            (CorpusNodeType.SOURCE_SPAN, CorpusNodeType.TOOL_MENTION),
            (CorpusNodeType.SOURCE_SPAN, CorpusNodeType.ENTITY_MENTION),
        }
    ),
    CorpusEdgeType.HAS_LICENSE: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.LICENSE),
            (CorpusNodeType.SKILL, CorpusNodeType.LICENSE),
        }
    ),
    CorpusEdgeType.HAS_DOMAIN: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.DOMAIN),
            (CorpusNodeType.SKILL, CorpusNodeType.DOMAIN),
        }
    ),
    CorpusEdgeType.CITES: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.SECTION, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.SOURCE_SPAN, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.REPOSITORY),
            (CorpusNodeType.SECTION, CorpusNodeType.REPOSITORY),
            (CorpusNodeType.SOURCE_SPAN, CorpusNodeType.REPOSITORY),
        }
    ),
    CorpusEdgeType.NEIGHBOR_OF: frozenset(
        {
            (CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SOURCE_DOCUMENT),
            (CorpusNodeType.SKILL, CorpusNodeType.SKILL),
        }
    ),
}


def _plain_json_value(value: Any) -> Any:
    """Return an immutable, JSON-shaped defensive copy."""

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("graph property mapping keys must be strings")
        return MappingProxyType(
            {
                key: _plain_json_value(item)
                for key, item in sorted(value.items())
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_plain_json_value(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("graph property numbers must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        "graph properties must contain only JSON scalar, mapping, and sequence values"
    )


def _mutable_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _mutable_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable_json_value(item) for item in value]
    return value


def _require_digest(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label} must be a sha256:<64 lowercase hex> digest")


def _require_identifier(value: str, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise ValueError(f"{label} must be non-empty normalized text")


@dataclass(frozen=True, slots=True)
class CorpusGraphNode:
    """One immutable, fully provenance-bound corpus graph node."""

    node_id: str
    node_type: CorpusNodeType
    properties: Mapping[str, Any]
    source_digest: str
    source_digests: tuple[str, ...]
    graph_digest: str
    ontology_version: str = CORPUS_GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.node_id, label="node_id")
        if not isinstance(self.node_type, CorpusNodeType):
            raise TypeError("node_type must be a CorpusNodeType")
        if self.ontology_version != CORPUS_GRAPH_ONTOLOGY_VERSION:
            raise ValueError("unsupported corpus graph ontology_version")
        _require_digest(self.source_digest, label="source_digest")
        _require_digest(self.graph_digest, label="graph_digest")
        digests = tuple(sorted(set(self.source_digests)))
        if not digests:
            raise ValueError("every graph node must bind at least one source digest")
        for digest in digests:
            _require_digest(digest, label="source_digests item")
        object.__setattr__(self, "source_digests", digests)
        object.__setattr__(self, "properties", _plain_json_value(self.properties))

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_digest": self.graph_digest,
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "properties": _mutable_json_value(self.properties),
            "source_digest": self.source_digest,
            "source_digests": list(self.source_digests),
        }


@dataclass(frozen=True, slots=True)
class CorpusGraphEdge:
    """One immutable, fully provenance-bound corpus graph edge."""

    edge_id: str
    edge_type: CorpusEdgeType
    source_node_id: str
    target_node_id: str
    properties: Mapping[str, Any]
    source_digest: str
    source_digests: tuple[str, ...]
    graph_digest: str
    ontology_version: str = CORPUS_GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.edge_id, label="edge_id")
        _require_identifier(self.source_node_id, label="source_node_id")
        _require_identifier(self.target_node_id, label="target_node_id")
        if not isinstance(self.edge_type, CorpusEdgeType):
            raise TypeError("edge_type must be a CorpusEdgeType")
        if self.ontology_version != CORPUS_GRAPH_ONTOLOGY_VERSION:
            raise ValueError("unsupported corpus graph ontology_version")
        _require_digest(self.source_digest, label="source_digest")
        _require_digest(self.graph_digest, label="graph_digest")
        digests = tuple(sorted(set(self.source_digests)))
        if not digests:
            raise ValueError("every graph edge must bind at least one source digest")
        for digest in digests:
            _require_digest(digest, label="source_digests item")
        object.__setattr__(self, "source_digests", digests)
        object.__setattr__(self, "properties", _plain_json_value(self.properties))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_type": self.edge_type.value,
            "graph_digest": self.graph_digest,
            "ontology_version": self.ontology_version,
            "properties": _mutable_json_value(self.properties),
            "source_digest": self.source_digest,
            "source_digests": list(self.source_digests),
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
        }


@dataclass(frozen=True, slots=True)
class CorpusGraphOntology:
    """Machine-readable declaration and conformance checker for ontology v1."""

    version: str = CORPUS_GRAPH_ONTOLOGY_VERSION
    graph_schema_version: str = CORPUS_GRAPH_SCHEMA_VERSION

    @property
    def node_types(self) -> tuple[str, ...]:
        return tuple(item.value for item in CorpusNodeType)

    @property
    def edge_types(self) -> tuple[str, ...]:
        return tuple(item.value for item in CorpusEdgeType)

    @property
    def allowed_endpoint_pairs(self) -> dict[str, list[list[str]]]:
        return {
            edge_type.value: [
                [source.value, target.value]
                for source, target in sorted(
                    pairs, key=lambda pair: (pair[0].value, pair[1].value)
                )
            ]
            for edge_type, pairs in _ALLOWED_ENDPOINTS.items()
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_endpoint_pairs": self.allowed_endpoint_pairs,
            "edge_types": list(self.edge_types),
            "graph_schema_version": self.graph_schema_version,
            "node_types": list(self.node_types),
            "version": self.version,
        }

    def validate(
        self,
        nodes: tuple[CorpusGraphNode, ...],
        edges: tuple[CorpusGraphEdge, ...],
        *,
        graph_digest: str,
    ) -> None:
        """Reject unknown vocabulary, dangling edges, or missing bindings."""

        if self.version != CORPUS_GRAPH_ONTOLOGY_VERSION:
            raise ValueError("unsupported corpus graph ontology version")
        _require_digest(graph_digest, label="graph_digest")
        node_ids: set[str] = set()
        node_types: dict[str, CorpusNodeType] = {}
        for node in nodes:
            if node.node_id in node_ids:
                raise ValueError(f"duplicate corpus graph node_id: {node.node_id}")
            node_ids.add(node.node_id)
            node_types[node.node_id] = node.node_type
            if node.ontology_version != self.version:
                raise ValueError(f"{node.node_id} has a foreign ontology version")
            if node.graph_digest != graph_digest:
                raise ValueError(f"{node.node_id} is not bound to the graph digest")
        edge_ids: set[str] = set()
        for edge in edges:
            if edge.edge_id in edge_ids:
                raise ValueError(f"duplicate corpus graph edge_id: {edge.edge_id}")
            edge_ids.add(edge.edge_id)
            if edge.ontology_version != self.version:
                raise ValueError(f"{edge.edge_id} has a foreign ontology version")
            if edge.graph_digest != graph_digest:
                raise ValueError(f"{edge.edge_id} is not bound to the graph digest")
            if edge.source_node_id not in node_ids:
                raise ValueError(f"{edge.edge_id} has a missing source node")
            if edge.target_node_id not in node_ids:
                raise ValueError(f"{edge.edge_id} has a missing target node")
            endpoints = (
                node_types[edge.source_node_id],
                node_types[edge.target_node_id],
            )
            if endpoints not in _ALLOWED_ENDPOINTS[edge.edge_type]:
                raise ValueError(
                    f"{edge.edge_id} has invalid {edge.edge_type.value} endpoints: "
                    f"{endpoints[0].value} -> {endpoints[1].value}"
                )


CORPUS_GRAPH_ONTOLOGY = CorpusGraphOntology()


__all__ = [
    "CORPUS_GRAPH_ONTOLOGY",
    "CORPUS_GRAPH_ONTOLOGY_VERSION",
    "CORPUS_GRAPH_SCHEMA_VERSION",
    "CorpusEdgeType",
    "CorpusGraphEdge",
    "CorpusGraphNode",
    "CorpusGraphOntology",
    "CorpusNodeType",
]
