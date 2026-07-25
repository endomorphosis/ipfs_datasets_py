"""Versioned ontology and immutable records for Intent corpus graphs.

The graph payload is deliberately source-body-free.  Nodes and relationships
carry only bounded properties, immutable addresses for separately stored
source/embedding bytes, and digests that bind them to both their evidence and
the complete deterministic graph projection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.provenance import freeze_json_mapping, thaw_json


INTENT_GRAPH_ONTOLOGY_VERSION: Final = "intent-graph-ontology/v1"
CORPUS_GRAPH_SCHEMA_VERSION: Final = "intent-corpus-graph/v1"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_PROPERTY_KEYS = frozenset(
    {
        "body",
        "body_bytes",
        "content",
        "content_bytes",
        "embedding",
        "embedding_bytes",
        "library_md",
        "metadata_yaml",
        "raw_text",
        "skill_md",
        "source_text",
        "text",
        "vector",
        "vectors",
    }
)


class CorpusGraphValidationError(ValueError):
    """Raised when an ontology term or graph binding is invalid."""


class CorpusNodeKind(str, Enum):
    """The v1 corpus-evidence node vocabulary."""

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


class CorpusEdgeKind(str, Enum):
    """The v1 corpus-evidence relationship vocabulary."""

    CONTAINS = "CONTAINS"
    DERIVED_FROM = "DERIVED_FROM"
    SAME_PRIMARY_SOURCE = "SAME_PRIMARY_SOURCE"
    DUPLICATE_OF = "DUPLICATE_OF"
    MENTIONS = "MENTIONS"
    HAS_LICENSE = "HAS_LICENSE"
    HAS_DOMAIN = "HAS_DOMAIN"
    CITES = "CITES"
    NEIGHBOR_OF = "NEIGHBOR_OF"


# Short aliases make the ontology pleasant to consume while the qualified
# names remain unambiguous at package boundaries.
NodeKind = CorpusNodeKind
EdgeKind = CorpusEdgeKind


_ALLOWED_ENDPOINTS: Mapping[
    CorpusEdgeKind, frozenset[tuple[CorpusNodeKind, CorpusNodeKind]]
] = {
    CorpusEdgeKind.CONTAINS: frozenset(
        {
            (CorpusNodeKind.DATASET_REVISION, CorpusNodeKind.BUNDLE),
            (
                CorpusNodeKind.AUTHOR_PUBLISHER,
                CorpusNodeKind.DATASET_REVISION,
            ),
            (CorpusNodeKind.BUNDLE, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.BUNDLE, CorpusNodeKind.SKILL),
            (CorpusNodeKind.REPOSITORY, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SKILL, CorpusNodeKind.SECTION),
            (CorpusNodeKind.SECTION, CorpusNodeKind.SOURCE_SPAN),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.SOURCE_SPAN),
        }
    ),
    CorpusEdgeKind.DERIVED_FROM: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.REPOSITORY),
            (CorpusNodeKind.SECTION, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.SOURCE_DOCUMENT),
        }
    ),
    CorpusEdgeKind.SAME_PRIMARY_SOURCE: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.SKILL),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.SOURCE_DOCUMENT),
        }
    ),
    CorpusEdgeKind.DUPLICATE_OF: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.SKILL),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.SOURCE_DOCUMENT),
        }
    ),
    CorpusEdgeKind.MENTIONS: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.TOOL_MENTION),
            (CorpusNodeKind.SKILL, CorpusNodeKind.ENTITY_MENTION),
            (CorpusNodeKind.SECTION, CorpusNodeKind.TOOL_MENTION),
            (CorpusNodeKind.SECTION, CorpusNodeKind.ENTITY_MENTION),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.TOOL_MENTION),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.ENTITY_MENTION),
        }
    ),
    CorpusEdgeKind.HAS_LICENSE: frozenset(
        {
            (CorpusNodeKind.BUNDLE, CorpusNodeKind.LICENSE),
            (CorpusNodeKind.REPOSITORY, CorpusNodeKind.LICENSE),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.LICENSE),
            (CorpusNodeKind.SKILL, CorpusNodeKind.LICENSE),
        }
    ),
    CorpusEdgeKind.HAS_DOMAIN: frozenset(
        {
            (CorpusNodeKind.BUNDLE, CorpusNodeKind.DOMAIN),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.DOMAIN),
            (CorpusNodeKind.SKILL, CorpusNodeKind.DOMAIN),
        }
    ),
    CorpusEdgeKind.CITES: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SECTION, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.SOURCE_DOCUMENT),
            (CorpusNodeKind.SKILL, CorpusNodeKind.REPOSITORY),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.REPOSITORY),
            (CorpusNodeKind.SKILL, CorpusNodeKind.ENTITY_MENTION),
            (CorpusNodeKind.SOURCE_SPAN, CorpusNodeKind.ENTITY_MENTION),
        }
    ),
    CorpusEdgeKind.NEIGHBOR_OF: frozenset(
        {
            (CorpusNodeKind.SKILL, CorpusNodeKind.SKILL),
            (CorpusNodeKind.SECTION, CorpusNodeKind.SECTION),
            (CorpusNodeKind.SOURCE_DOCUMENT, CorpusNodeKind.SOURCE_DOCUMENT),
        }
    ),
}

SYMMETRIC_EDGE_KINDS: Final = frozenset(
    {
        CorpusEdgeKind.SAME_PRIMARY_SOURCE,
        CorpusEdgeKind.DUPLICATE_OF,
        CorpusEdgeKind.NEIGHBOR_OF,
    }
)
SIMILARITY_EDGE_KINDS: Final = frozenset({CorpusEdgeKind.NEIGHBOR_OF})


def _coerce_node_kind(value: CorpusNodeKind | str) -> CorpusNodeKind:
    if isinstance(value, CorpusNodeKind):
        return value
    try:
        return CorpusNodeKind(value)
    except (TypeError, ValueError) as exc:
        raise CorpusGraphValidationError(
            f"unsupported corpus node kind {value!r}"
        ) from exc


def _coerce_edge_kind(value: CorpusEdgeKind | str) -> CorpusEdgeKind:
    if isinstance(value, CorpusEdgeKind):
        return value
    try:
        return CorpusEdgeKind(value)
    except (TypeError, ValueError) as exc:
        raise CorpusGraphValidationError(
            f"unsupported corpus edge kind {value!r}"
        ) from exc


def _require_identifier(label: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value) > 512
    ):
        raise CorpusGraphValidationError(
            f"{label} must be bounded non-empty normalized text"
        )


def _require_address(label: str, value: str) -> None:
    if not value:
        return
    _require_identifier(label, value)


def _require_digest(label: str, value: str) -> None:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise CorpusGraphValidationError(
            f"{label} must be an algorithm-qualified lowercase SHA-256 digest"
        )


def _normalized_source_digests(
    values: Sequence[str],
    *,
    label: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise CorpusGraphValidationError(f"{label} must be a sequence of digests")
    result = tuple(sorted(set(values)))
    if not result:
        raise CorpusGraphValidationError(f"{label} must not be empty")
    for value in result:
        _require_digest(label, value)
    return result


def combined_source_digest(source_digests: Sequence[str]) -> str:
    """Return one binding digest for an exact set of evidence digests."""

    normalized = _normalized_source_digests(
        source_digests, label="source_digests"
    )
    if len(normalized) == 1:
        return normalized[0]
    return "sha256:" + hashlib.sha256(
        canonical_json_bytes(list(normalized))
    ).hexdigest()


def _validate_properties(value: Any, *, path: str = "properties") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CorpusGraphValidationError(
                    f"{path} keys must all be strings"
                )
            normalized_key = key.casefold().replace("-", "_")
            if normalized_key in _FORBIDDEN_PROPERTY_KEYS:
                raise CorpusGraphValidationError(
                    f"{path}.{key} embeds source or vector data; store it "
                    "separately and retain only its immutable address"
                )
            _validate_properties(child, path=f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            _validate_properties(child, path=f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise CorpusGraphValidationError(
            f"{path} contains non-JSON value {type(value).__name__}"
        )


@dataclass(frozen=True, slots=True)
class CorpusGraphNode:
    """One source-grounded node in a sealed corpus projection."""

    node_id: str
    kind: CorpusNodeKind
    source_digests: tuple[str, ...]
    graph_digest: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    source_body_cid: str = ""
    embedding_cid: str = ""
    ontology_version: str = INTENT_GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_node_kind(self.kind))
        object.__setattr__(
            self,
            "source_digests",
            _normalized_source_digests(
                self.source_digests, label=f"node {self.node_id!r}.source_digests"
            ),
        )
        object.__setattr__(self, "properties", freeze_json_mapping(self.properties))

    @property
    def id(self) -> str:
        return self.node_id

    @property
    def type(self) -> str:
        return self.kind.value

    @property
    def source_digest(self) -> str:
        return combined_source_digest(self.source_digests)

    def validate(self, *, expected_graph_digest: str | None = None) -> None:
        _require_identifier("CorpusGraphNode.node_id", self.node_id)
        if self.ontology_version != INTENT_GRAPH_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError(
                f"node {self.node_id!r} has unsupported ontology_version"
            )
        _require_digest("CorpusGraphNode.graph_digest", self.graph_digest)
        if (
            expected_graph_digest is not None
            and self.graph_digest != expected_graph_digest
        ):
            raise CorpusGraphValidationError(
                f"node {self.node_id!r} is not bound to the graph digest"
            )
        _require_address("CorpusGraphNode.source_body_cid", self.source_body_cid)
        _require_address("CorpusGraphNode.embedding_cid", self.embedding_cid)
        _validate_properties(self.properties)

    def identity_dict(self) -> dict[str, Any]:
        """Return the digest preimage fields, excluding the graph binding."""

        return {
            "embedding_cid": self.embedding_cid,
            "id": self.node_id,
            "ontology_version": self.ontology_version,
            "properties": thaw_json(self.properties),
            "source_body_cid": self.source_body_cid,
            "source_digest": self.source_digest,
            "source_digests": list(self.source_digests),
            "type": self.kind.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "graph_digest": self.graph_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusGraphNode":
        result = cls(
            node_id=str(data.get("id") or data.get("node_id") or ""),
            kind=_coerce_node_kind(data.get("type") or data.get("kind") or ""),
            source_digests=tuple(data.get("source_digests") or ()),
            graph_digest=str(data.get("graph_digest") or ""),
            properties=data.get("properties") or {},
            source_body_cid=str(data.get("source_body_cid") or ""),
            embedding_cid=str(data.get("embedding_cid") or ""),
            ontology_version=str(
                data.get("ontology_version") or INTENT_GRAPH_ONTOLOGY_VERSION
            ),
        )
        supplied_source_digest = data.get("source_digest")
        if (
            supplied_source_digest is not None
            and supplied_source_digest != result.source_digest
        ):
            raise CorpusGraphValidationError(
                f"node {result.node_id!r} source_digest does not match "
                "source_digests"
            )
        return result


@dataclass(frozen=True, slots=True)
class CorpusGraphEdge:
    """One ontology-checked, source-grounded corpus relationship."""

    edge_id: str
    kind: CorpusEdgeKind
    source_node_id: str
    target_node_id: str
    source_digests: tuple[str, ...]
    graph_digest: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    embedding_cid: str = ""
    ontology_version: str = INTENT_GRAPH_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_edge_kind(self.kind))
        object.__setattr__(
            self,
            "source_digests",
            _normalized_source_digests(
                self.source_digests, label=f"edge {self.edge_id!r}.source_digests"
            ),
        )
        object.__setattr__(self, "properties", freeze_json_mapping(self.properties))

    @property
    def id(self) -> str:
        return self.edge_id

    @property
    def type(self) -> str:
        return self.kind.value

    @property
    def start_node(self) -> str:
        return self.source_node_id

    @property
    def end_node(self) -> str:
        return self.target_node_id

    @property
    def source_digest(self) -> str:
        return combined_source_digest(self.source_digests)

    @property
    def relation_class(self) -> str:
        return (
            "similarity"
            if self.kind in SIMILARITY_EDGE_KINDS
            else "corpus_evidence"
        )

    @property
    def directed(self) -> bool:
        return self.kind not in SYMMETRIC_EDGE_KINDS

    def validate(
        self,
        *,
        nodes_by_id: Mapping[str, CorpusGraphNode],
        expected_graph_digest: str | None = None,
    ) -> None:
        _require_identifier("CorpusGraphEdge.edge_id", self.edge_id)
        _require_identifier("CorpusGraphEdge.source_node_id", self.source_node_id)
        _require_identifier("CorpusGraphEdge.target_node_id", self.target_node_id)
        if self.source_node_id == self.target_node_id:
            raise CorpusGraphValidationError(
                f"edge {self.edge_id!r} cannot be a self relationship"
            )
        if self.ontology_version != INTENT_GRAPH_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError(
                f"edge {self.edge_id!r} has unsupported ontology_version"
            )
        _require_digest("CorpusGraphEdge.graph_digest", self.graph_digest)
        if (
            expected_graph_digest is not None
            and self.graph_digest != expected_graph_digest
        ):
            raise CorpusGraphValidationError(
                f"edge {self.edge_id!r} is not bound to the graph digest"
            )
        try:
            source_kind = nodes_by_id[self.source_node_id].kind
            target_kind = nodes_by_id[self.target_node_id].kind
        except KeyError as exc:
            raise CorpusGraphValidationError(
                f"edge {self.edge_id!r} has a dangling endpoint {exc.args[0]!r}"
            ) from exc
        if (source_kind, target_kind) not in _ALLOWED_ENDPOINTS[self.kind]:
            raise CorpusGraphValidationError(
                f"{self.kind.value} does not permit "
                f"{source_kind.value}->{target_kind.value}"
            )
        _require_address("CorpusGraphEdge.embedding_cid", self.embedding_cid)
        if self.kind is CorpusEdgeKind.NEIGHBOR_OF and not self.embedding_cid:
            raise CorpusGraphValidationError(
                "NEIGHBOR_OF must bind the separately addressed embedding evidence"
            )
        if self.kind is not CorpusEdgeKind.NEIGHBOR_OF and self.embedding_cid:
            raise CorpusGraphValidationError(
                f"{self.kind.value} cannot carry an embedding address"
            )
        _validate_properties(self.properties)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "directed": self.directed,
            "embedding_cid": self.embedding_cid,
            "end_node": self.target_node_id,
            "id": self.edge_id,
            "ontology_version": self.ontology_version,
            "properties": thaw_json(self.properties),
            "relation_class": self.relation_class,
            "source_digest": self.source_digest,
            "source_digests": list(self.source_digests),
            "start_node": self.source_node_id,
            "type": self.kind.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "graph_digest": self.graph_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusGraphEdge":
        result = cls(
            edge_id=str(data.get("id") or data.get("edge_id") or ""),
            kind=_coerce_edge_kind(data.get("type") or data.get("kind") or ""),
            source_node_id=str(
                data.get("start_node") or data.get("source_node_id") or ""
            ),
            target_node_id=str(
                data.get("end_node") or data.get("target_node_id") or ""
            ),
            source_digests=tuple(data.get("source_digests") or ()),
            graph_digest=str(data.get("graph_digest") or ""),
            properties=data.get("properties") or {},
            embedding_cid=str(data.get("embedding_cid") or ""),
            ontology_version=str(
                data.get("ontology_version") or INTENT_GRAPH_ONTOLOGY_VERSION
            ),
        )
        supplied_source_digest = data.get("source_digest")
        if (
            supplied_source_digest is not None
            and supplied_source_digest != result.source_digest
        ):
            raise CorpusGraphValidationError(
                f"edge {result.edge_id!r} source_digest does not match "
                "source_digests"
            )
        supplied_relation_class = data.get("relation_class")
        if (
            supplied_relation_class is not None
            and supplied_relation_class != result.relation_class
        ):
            raise CorpusGraphValidationError(
                f"edge {result.edge_id!r} relation_class does not match its type"
            )
        supplied_directed = data.get("directed")
        if supplied_directed is not None and supplied_directed is not result.directed:
            raise CorpusGraphValidationError(
                f"edge {result.edge_id!r} directed flag does not match its type"
            )
        return result


def graph_projection_digest(
    nodes: Sequence[CorpusGraphNode],
    relationships: Sequence[CorpusGraphEdge],
) -> str:
    """Digest a graph projection before stamping its non-recursive binding.

    ``graph_digest`` fields are intentionally excluded from this preimage;
    otherwise binding every element to the graph would require an impossible
    self-referential hash fixed point.
    """

    payload = {
        "nodes": [
            node.identity_dict() for node in sorted(nodes, key=lambda item: item.id)
        ],
        "ontology_version": INTENT_GRAPH_ONTOLOGY_VERSION,
        "relationships": [
            edge.identity_dict()
            for edge in sorted(relationships, key=lambda item: item.id)
        ],
        "schema_version": CORPUS_GRAPH_SCHEMA_VERSION,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class IntentCorpusGraph:
    """A deterministic, ontology-checked corpus evidence graph."""

    graph_digest: str
    nodes: tuple[CorpusGraphNode, ...]
    relationships: tuple[CorpusGraphEdge, ...]
    ontology_version: str = INTENT_GRAPH_ONTOLOGY_VERSION
    schema_version: str = CORPUS_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "nodes", tuple(sorted(self.nodes, key=lambda item: item.id))
        )
        object.__setattr__(
            self,
            "relationships",
            tuple(sorted(self.relationships, key=lambda item: item.id)),
        )

    @property
    def graph_id(self) -> str:
        return f"intent-corpus-graph:{self.graph_digest.removeprefix('sha256:')[:24]}"

    @property
    def edges(self) -> tuple[CorpusGraphEdge, ...]:
        return self.relationships

    @property
    def source_digests(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    digest
                    for item in (*self.nodes, *self.relationships)
                    for digest in item.source_digests
                }
            )
        )

    @property
    def source_body_cids(self) -> tuple[str, ...]:
        return tuple(
            sorted({node.source_body_cid for node in self.nodes if node.source_body_cid})
        )

    @property
    def embedding_cids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.embedding_cid
                    for item in (*self.nodes, *self.relationships)
                    if item.embedding_cid
                }
            )
        )

    def validate(self) -> "IntentCorpusGraph":
        if self.schema_version != CORPUS_GRAPH_SCHEMA_VERSION:
            raise CorpusGraphValidationError("unsupported corpus graph schema_version")
        if self.ontology_version != INTENT_GRAPH_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError("unsupported corpus graph ontology_version")
        _require_digest("IntentCorpusGraph.graph_digest", self.graph_digest)
        if not self.nodes:
            raise CorpusGraphValidationError("a corpus graph must contain nodes")
        nodes_by_id = {node.id: node for node in self.nodes}
        if len(nodes_by_id) != len(self.nodes):
            raise CorpusGraphValidationError("corpus graph contains duplicate node IDs")
        edge_ids = {edge.id for edge in self.relationships}
        if len(edge_ids) != len(self.relationships):
            raise CorpusGraphValidationError("corpus graph contains duplicate edge IDs")
        for node in self.nodes:
            node.validate(expected_graph_digest=self.graph_digest)
        for edge in self.relationships:
            edge.validate(
                nodes_by_id=nodes_by_id,
                expected_graph_digest=self.graph_digest,
            )
        expected = graph_projection_digest(self.nodes, self.relationships)
        if expected != self.graph_digest:
            raise CorpusGraphValidationError(
                "graph_digest does not match the deterministic graph projection"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_digest": self.graph_digest,
            "graph_id": self.graph_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "ontology_version": self.ontology_version,
            "relationships": [edge.to_dict() for edge in self.relationships],
            "schema_version": self.schema_version,
            "source_body_cids": list(self.source_body_cids),
            "source_digests": list(self.source_digests),
            "embedding_cids": list(self.embedding_cids),
        }

    def canonical_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.to_dict())

    @property
    def artifact_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntentCorpusGraph":
        graph = cls(
            graph_digest=str(data.get("graph_digest") or ""),
            nodes=tuple(
                CorpusGraphNode.from_dict(item)
                for item in _mapping_sequence(data.get("nodes"), "nodes")
            ),
            relationships=tuple(
                CorpusGraphEdge.from_dict(item)
                for item in _mapping_sequence(
                    data.get("relationships") or data.get("edges"),
                    "relationships",
                )
            ),
            ontology_version=str(
                data.get("ontology_version") or INTENT_GRAPH_ONTOLOGY_VERSION
            ),
            schema_version=str(
                data.get("schema_version") or CORPUS_GRAPH_SCHEMA_VERSION
            ),
        )
        graph.validate()
        supplied_graph_id = data.get("graph_id")
        if supplied_graph_id is not None and supplied_graph_id != graph.graph_id:
            raise CorpusGraphValidationError(
                "graph_id does not match graph_digest"
            )
        for label, supplied, expected in (
            ("source_digests", data.get("source_digests"), graph.source_digests),
            ("source_body_cids", data.get("source_body_cids"), graph.source_body_cids),
            ("embedding_cids", data.get("embedding_cids"), graph.embedding_cids),
        ):
            if supplied is not None and tuple(supplied) != expected:
                raise CorpusGraphValidationError(
                    f"{label} does not match graph elements"
                )
        return graph


@dataclass(frozen=True, slots=True)
class IntentGraphOntology:
    """Machine-readable declaration of the corpus ontology contract."""

    version: str = INTENT_GRAPH_ONTOLOGY_VERSION

    @property
    def node_kinds(self) -> tuple[str, ...]:
        return tuple(kind.value for kind in CorpusNodeKind)

    @property
    def edge_kinds(self) -> tuple[str, ...]:
        return tuple(kind.value for kind in CorpusEdgeKind)

    def permits(
        self,
        edge_kind: CorpusEdgeKind | str,
        source_kind: CorpusNodeKind | str,
        target_kind: CorpusNodeKind | str,
    ) -> bool:
        if self.version != INTENT_GRAPH_ONTOLOGY_VERSION:
            return False
        edge = _coerce_edge_kind(edge_kind)
        return (
            _coerce_node_kind(source_kind),
            _coerce_node_kind(target_kind),
        ) in _ALLOWED_ENDPOINTS[edge]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_kinds": list(self.edge_kinds),
            "node_kinds": list(self.node_kinds),
            "similarity_edge_kinds": sorted(
                kind.value for kind in SIMILARITY_EDGE_KINDS
            ),
            "symmetric_edge_kinds": sorted(
                kind.value for kind in SYMMETRIC_EDGE_KINDS
            ),
            "version": self.version,
        }


CORPUS_GRAPH_ONTOLOGY: Final = IntentGraphOntology()


def _mapping_sequence(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise CorpusGraphValidationError(f"{label} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CorpusGraphValidationError(f"{label} entries must be mappings")
        result.append(item)
    return tuple(result)


__all__ = [
    "CORPUS_GRAPH_ONTOLOGY",
    "CORPUS_GRAPH_SCHEMA_VERSION",
    "INTENT_GRAPH_ONTOLOGY_VERSION",
    "SIMILARITY_EDGE_KINDS",
    "SYMMETRIC_EDGE_KINDS",
    "CorpusEdgeKind",
    "CorpusGraphEdge",
    "CorpusGraphNode",
    "CorpusGraphValidationError",
    "CorpusNodeKind",
    "EdgeKind",
    "IntentCorpusGraph",
    "IntentGraphOntology",
    "NodeKind",
    "combined_source_digest",
    "graph_projection_digest",
]
