"""Versioned ontology and immutable records for the Intent corpus graph.

The corpus graph is an evidence index, not a semantic or proof graph.  Its
records deliberately contain only bounded metadata and content addresses.
Source bodies and embedding vectors are never fields on graph nodes or edges.

``graph_digest`` is the SHA-256 digest of the canonical structural projection
(including every ``source_digest`` but excluding the repeated graph-digest
bindings).  Materializing that digest on every node and edge makes detached
records self-identifying without introducing a circular hash definition.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1, cid_v1_from_digest, sha256_digest


CORPUS_ONTOLOGY_VERSION: Final = "intent-corpus-ontology/v1"
CORPUS_GRAPH_SCHEMA_VERSION: Final = "intent-corpus-graph/v1"
CORPUS_GRAPH_IDENTITY_DOMAIN: Final = "intent-corpus-evidence-graph"
MAX_GRAPH_PROPERTY_BYTES: Final = 65_536
MAX_GRAPH_PROPERTY_STRING_CHARS: Final = 8_192

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")


class CorpusGraphValidationError(ValueError):
    """Raised when a corpus graph violates its ontology or digest bindings."""


class CorpusNodeType(str, Enum):
    """Node vocabulary for ``intent-corpus-ontology/v1``."""

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
    """Edge vocabulary for ``intent-corpus-ontology/v1``."""

    CONTAINS = "CONTAINS"
    DERIVED_FROM = "DERIVED_FROM"
    SAME_PRIMARY_SOURCE = "SAME_PRIMARY_SOURCE"
    DUPLICATE_OF = "DUPLICATE_OF"
    MENTIONS = "MENTIONS"
    HAS_LICENSE = "HAS_LICENSE"
    HAS_DOMAIN = "HAS_DOMAIN"
    CITES = "CITES"
    NEIGHBOR_OF = "NEIGHBOR_OF"


# Public aliases make the vocabulary convenient without weakening its version.
NodeType = CorpusNodeType
EdgeType = CorpusEdgeType


_CONTAINS_SOURCES = frozenset(
    {
        CorpusNodeType.DATASET_REVISION,
        CorpusNodeType.BUNDLE,
        CorpusNodeType.REPOSITORY,
        CorpusNodeType.SOURCE_DOCUMENT,
        CorpusNodeType.SKILL,
        CorpusNodeType.SECTION,
    }
)
_CONTAINS_TARGETS = frozenset(
    {
        CorpusNodeType.BUNDLE,
        CorpusNodeType.SOURCE_DOCUMENT,
        CorpusNodeType.SKILL,
        CorpusNodeType.SECTION,
        CorpusNodeType.SOURCE_SPAN,
    }
)
_EVIDENCE_SOURCES = frozenset(
    {
        CorpusNodeType.BUNDLE,
        CorpusNodeType.REPOSITORY,
        CorpusNodeType.SOURCE_DOCUMENT,
        CorpusNodeType.SKILL,
        CorpusNodeType.SECTION,
        CorpusNodeType.SOURCE_SPAN,
    }
)


@dataclass(frozen=True, slots=True)
class CorpusOntology:
    """Machine-readable declaration of one corpus node/edge vocabulary."""

    version: str = CORPUS_ONTOLOGY_VERSION
    node_types: tuple[str, ...] = tuple(item.value for item in CorpusNodeType)
    edge_types: tuple[str, ...] = tuple(item.value for item in CorpusEdgeType)

    def __post_init__(self) -> None:
        if self.version != CORPUS_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError(
                f"unsupported corpus ontology version: {self.version!r}"
            )
        if self.node_types != tuple(item.value for item in CorpusNodeType):
            raise CorpusGraphValidationError(
                "node_types must exactly match the versioned corpus vocabulary"
            )
        if self.edge_types != tuple(item.value for item in CorpusEdgeType):
            raise CorpusGraphValidationError(
                "edge_types must exactly match the versioned corpus vocabulary"
            )

    def validate_edge(
        self,
        edge_type: CorpusEdgeType | str,
        source_type: CorpusNodeType | str,
        target_type: CorpusNodeType | str,
    ) -> None:
        """Reject edge labels or endpoint combinations outside this version."""

        edge = _enum_value(CorpusEdgeType, edge_type, "edge_type")
        source = _enum_value(CorpusNodeType, source_type, "source_type")
        target = _enum_value(CorpusNodeType, target_type, "target_type")

        valid = False
        if edge is CorpusEdgeType.CONTAINS:
            valid = source in _CONTAINS_SOURCES and target in _CONTAINS_TARGETS
        elif edge is CorpusEdgeType.DERIVED_FROM:
            valid = source in _EVIDENCE_SOURCES and target in _EVIDENCE_SOURCES
        elif edge in {
            CorpusEdgeType.SAME_PRIMARY_SOURCE,
            CorpusEdgeType.DUPLICATE_OF,
        }:
            valid = (
                source in {CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SKILL}
                and target in {CorpusNodeType.SOURCE_DOCUMENT, CorpusNodeType.SKILL}
            )
        elif edge is CorpusEdgeType.MENTIONS:
            valid = (
                source in _EVIDENCE_SOURCES
                and target
                in {
                    CorpusNodeType.TOOL_MENTION,
                    CorpusNodeType.ENTITY_MENTION,
                    CorpusNodeType.AUTHOR_PUBLISHER,
                }
            )
        elif edge is CorpusEdgeType.HAS_LICENSE:
            valid = (
                source in _EVIDENCE_SOURCES
                and target is CorpusNodeType.LICENSE
            )
        elif edge is CorpusEdgeType.HAS_DOMAIN:
            valid = (
                source
                in {
                    CorpusNodeType.DATASET_REVISION,
                    CorpusNodeType.BUNDLE,
                    CorpusNodeType.REPOSITORY,
                    CorpusNodeType.SOURCE_DOCUMENT,
                    CorpusNodeType.SKILL,
                }
                and target is CorpusNodeType.DOMAIN
            )
        elif edge is CorpusEdgeType.CITES:
            valid = (
                source in _EVIDENCE_SOURCES
                and target
                in {
                    CorpusNodeType.SOURCE_DOCUMENT,
                    CorpusNodeType.REPOSITORY,
                }
            )
        elif edge is CorpusEdgeType.NEIGHBOR_OF:
            valid = source is target and source in {
                CorpusNodeType.SOURCE_DOCUMENT,
                CorpusNodeType.SKILL,
                CorpusNodeType.TOOL_MENTION,
                CorpusNodeType.ENTITY_MENTION,
            }
        if not valid:
            raise CorpusGraphValidationError(
                f"{edge.value} does not permit "
                f"{source.value} -> {target.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_types": list(self.edge_types),
            "node_types": list(self.node_types),
            "version": self.version,
        }


CORPUS_ONTOLOGY = CorpusOntology()


@dataclass(frozen=True, slots=True)
class AddressedArtifact:
    """Reference to bytes kept outside the bounded graph artifact."""

    cid: str
    digest: str
    media_type: str
    size_bytes: int
    stored: bool = True

    def __post_init__(self) -> None:
        _require_text(self.cid, "artifact cid")
        _validate_digest(self.digest, "artifact digest")
        expected_cid = cid_v1_from_digest(
            bytes.fromhex(self.digest.removeprefix("sha256:"))
        )
        if self.cid != expected_cid:
            raise CorpusGraphValidationError(
                "artifact cid does not match its fixed-profile digest"
            )
        _require_text(self.media_type, "artifact media_type")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise CorpusGraphValidationError(
                "artifact size_bytes must be a non-negative integer"
            )

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        media_type: str,
        cid: str | None = None,
        stored: bool = True,
    ) -> "AddressedArtifact":
        if not isinstance(payload, bytes):
            raise TypeError("AddressedArtifact.from_bytes expects bytes")
        return cls(
            cid=cid or cid_v1(payload),
            digest=sha256_digest(payload),
            media_type=media_type,
            size_bytes=len(payload),
            stored=stored,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "digest": self.digest,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "stored": self.stored,
        }


@dataclass(frozen=True, slots=True)
class CorpusGraphNode(Mapping[str, Any]):
    """One immutable corpus node, bound to exact source and graph digests."""

    node_id: str
    node_type: CorpusNodeType
    source_digest: str
    graph_digest: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = CORPUS_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _validate_id(self.node_id, "node_id")
        object.__setattr__(
            self, "node_type", _enum_value(CorpusNodeType, self.node_type, "node_type")
        )
        _validate_digest(self.source_digest, "node source_digest")
        _validate_digest(self.graph_digest, "node graph_digest")
        if self.ontology_version != CORPUS_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError("unsupported node ontology_version")
        object.__setattr__(self, "properties", _freeze_mapping(self.properties))
        _assert_no_inline_payload(self.properties)

    @property
    def id(self) -> str:
        return self.node_id

    @property
    def kind(self) -> CorpusNodeType:
        return self.node_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_digest": self.graph_digest,
            "id": self.node_id,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "properties": _thaw(self.properties),
            "source_digest": self.source_digest,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True, slots=True)
class CorpusGraphEdge(Mapping[str, Any]):
    """One immutable ontology-conforming evidence edge."""

    edge_id: str
    edge_type: CorpusEdgeType
    source: str
    target: str
    source_digest: str
    graph_digest: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = CORPUS_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _validate_id(self.edge_id, "edge_id")
        object.__setattr__(
            self, "edge_type", _enum_value(CorpusEdgeType, self.edge_type, "edge_type")
        )
        _validate_id(self.source, "edge source")
        _validate_id(self.target, "edge target")
        if self.source == self.target:
            raise CorpusGraphValidationError("self-referential corpus edges are invalid")
        _validate_digest(self.source_digest, "edge source_digest")
        _validate_digest(self.graph_digest, "edge graph_digest")
        if self.ontology_version != CORPUS_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError("unsupported edge ontology_version")
        object.__setattr__(self, "properties", _freeze_mapping(self.properties))
        _assert_no_inline_payload(self.properties)

    @property
    def id(self) -> str:
        return self.edge_id

    @property
    def kind(self) -> CorpusEdgeType:
        return self.edge_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_type": self.edge_type.value,
            "graph_digest": self.graph_digest,
            "id": self.edge_id,
            "ontology_version": self.ontology_version,
            "properties": _thaw(self.properties),
            "source": self.source,
            "source_digest": self.source_digest,
            "target": self.target,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True, slots=True)
class IntentCorpusGraph(Mapping[str, Any]):
    """Deterministic, content-addressed corpus-evidence graph artifact."""

    nodes: tuple[CorpusGraphNode, ...]
    edges: tuple[CorpusGraphEdge, ...]
    graph_digest: str
    source_digests: tuple[str, ...]
    source_bodies: tuple[AddressedArtifact, ...] = ()
    embeddings: tuple[AddressedArtifact, ...] = ()
    graph_cid: str = ""
    schema_version: str = CORPUS_GRAPH_SCHEMA_VERSION
    ontology_version: str = CORPUS_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "source_digests", tuple(self.source_digests))
        object.__setattr__(self, "source_bodies", tuple(self.source_bodies))
        object.__setattr__(self, "embeddings", tuple(self.embeddings))
        if self.schema_version != CORPUS_GRAPH_SCHEMA_VERSION:
            raise CorpusGraphValidationError("unsupported corpus graph schema_version")
        if self.ontology_version != CORPUS_ONTOLOGY_VERSION:
            raise CorpusGraphValidationError("unsupported graph ontology_version")
        _validate_digest(self.graph_digest, "graph_digest")
        if not self.source_digests:
            raise CorpusGraphValidationError("source_digests must not be empty")
        if tuple(sorted(set(self.source_digests))) != self.source_digests:
            raise CorpusGraphValidationError(
                "source_digests must be unique and canonically sorted"
            )
        for digest in self.source_digests:
            _validate_digest(digest, "source digest")
        if any(not isinstance(node, CorpusGraphNode) for node in self.nodes):
            raise CorpusGraphValidationError(
                "nodes must contain only CorpusGraphNode values"
            )
        if any(not isinstance(edge, CorpusGraphEdge) for edge in self.edges):
            raise CorpusGraphValidationError(
                "edges must contain only CorpusGraphEdge values"
            )
        if any(
            not isinstance(item, AddressedArtifact)
            for item in (*self.source_bodies, *self.embeddings)
        ):
            raise CorpusGraphValidationError(
                "source_bodies and embeddings must contain AddressedArtifact values"
            )
        if tuple(sorted(self.nodes, key=lambda item: item.node_id)) != self.nodes:
            raise CorpusGraphValidationError("nodes must be sorted by node_id")
        if tuple(sorted(self.edges, key=lambda item: item.edge_id)) != self.edges:
            raise CorpusGraphValidationError("edges must be sorted by edge_id")
        node_by_id = {node.node_id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise CorpusGraphValidationError("duplicate node_id")
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise CorpusGraphValidationError("duplicate edge_id")
        for node in self.nodes:
            if node.graph_digest != self.graph_digest:
                raise CorpusGraphValidationError("node graph_digest binding mismatch")
            if node.source_digest not in self.source_digests:
                raise CorpusGraphValidationError("node has an unknown source_digest")
        for edge in self.edges:
            if edge.graph_digest != self.graph_digest:
                raise CorpusGraphValidationError("edge graph_digest binding mismatch")
            if edge.source_digest not in self.source_digests:
                raise CorpusGraphValidationError("edge has an unknown source_digest")
            if edge.source not in node_by_id or edge.target not in node_by_id:
                raise CorpusGraphValidationError("edge endpoint is dangling")
            CORPUS_ONTOLOGY.validate_edge(
                edge.edge_type,
                node_by_id[edge.source].node_type,
                node_by_id[edge.target].node_type,
            )
        actual = structural_graph_digest(
            self.nodes,
            self.edges,
            source_digests=self.source_digests,
        )
        if actual != self.graph_digest:
            raise CorpusGraphValidationError(
                "graph_digest does not match canonical structural projection"
            )
        if tuple(sorted(self.source_bodies, key=lambda item: item.digest)) != (
            self.source_bodies
        ):
            raise CorpusGraphValidationError(
                "source_bodies must be sorted by digest"
            )
        if tuple(sorted(self.embeddings, key=lambda item: item.digest)) != (
            self.embeddings
        ):
            raise CorpusGraphValidationError("embeddings must be sorted by digest")
        for label, artifacts in (
            ("source_bodies", self.source_bodies),
            ("embeddings", self.embeddings),
        ):
            if len({item.digest for item in artifacts}) != len(artifacts):
                raise CorpusGraphValidationError(
                    f"{label} contains a duplicate digest"
                )
            if len({item.cid for item in artifacts}) != len(artifacts):
                raise CorpusGraphValidationError(
                    f"{label} contains a duplicate cid"
                )
        if any(
            item.digest not in self.source_digests
            for item in self.source_bodies
        ):
            raise CorpusGraphValidationError(
                "source body digest is not declared in source_digests"
            )
        body_cids = {item.cid for item in self.source_bodies}
        embedding_cids = {item.cid for item in self.embeddings}
        if body_cids & embedding_cids:
            raise CorpusGraphValidationError(
                "source bodies and embeddings must have distinct addresses"
            )
        if self.graph_cid and self.graph_cid in body_cids | embedding_cids:
            raise CorpusGraphValidationError(
                "graph, source-body, and embedding addresses must be distinct"
            )
        if self.graph_cid:
            _require_text(self.graph_cid, "graph_cid")
            expected_graph_cid = cid_v1(self.canonical_bytes())
            if self.graph_cid != expected_graph_cid:
                raise CorpusGraphValidationError(
                    "graph_cid does not match the canonical graph artifact"
                )

    @property
    def digest(self) -> str:
        return self.graph_digest

    @property
    def cid(self) -> str:
        return self.graph_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "embeddings": [item.to_dict() for item in self.embeddings],
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "nodes": [node.to_dict() for node in self.nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
            "source_bodies": [item.to_dict() for item in self.source_bodies],
            "source_digests": list(self.source_digests),
        }

    def canonical_bytes(self) -> bytes:
        # ``graph_cid`` addresses this preimage and is consequently omitted
        # from it.  This is the same non-circular convention used for the
        # repeated graph-digest bindings in the structural digest.
        payload = self.to_dict()
        payload["graph_cid"] = ""
        return canonical_json_bytes(payload)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


# Compatibility-friendly descriptive names.
CorpusNode = CorpusGraphNode
CorpusEdge = CorpusGraphEdge
CorpusGraphArtifact = IntentCorpusGraph


def structural_graph_digest(
    nodes: tuple[CorpusGraphNode, ...] | list[CorpusGraphNode],
    edges: tuple[CorpusGraphEdge, ...] | list[CorpusGraphEdge],
    *,
    source_digests: tuple[str, ...] | list[str],
) -> str:
    """Hash graph structure while omitting repeated ``graph_digest`` fields."""

    payload = {
        "edges": [
            {
                "edge_type": edge.edge_type.value,
                "id": edge.edge_id,
                "ontology_version": edge.ontology_version,
                "properties": _thaw(edge.properties),
                "source": edge.source,
                "source_digest": edge.source_digest,
                "target": edge.target,
            }
            for edge in sorted(edges, key=lambda item: item.edge_id)
        ],
        "nodes": [
            {
                "id": node.node_id,
                "node_type": node.node_type.value,
                "ontology_version": node.ontology_version,
                "properties": _thaw(node.properties),
                "source_digest": node.source_digest,
            }
            for node in sorted(nodes, key=lambda item: item.node_id)
        ],
        "ontology_version": CORPUS_ONTOLOGY_VERSION,
        "schema_version": CORPUS_GRAPH_SCHEMA_VERSION,
        "source_digests": sorted(set(source_digests)),
    }
    return sha256_digest(canonical_json_bytes(payload))


def _enum_value(enum_type: type[Enum], value: Any, label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CorpusGraphValidationError(f"unknown {label}: {value!r}") from exc


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise CorpusGraphValidationError(
            f"{label} must be non-empty normalized text"
        )
    return value


def _validate_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CorpusGraphValidationError(f"{label} is not a valid stable identifier")


def _validate_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CorpusGraphValidationError(
            f"{label} must be a lowercase sha256:<hex> digest"
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise CorpusGraphValidationError(
        f"graph properties must contain JSON values, not {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusGraphValidationError("properties must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise CorpusGraphValidationError("property names must be strings")
    # Canonicalization also rejects non-finite floats and malformed Unicode.
    encoded = canonical_json_bytes(dict(value))
    if len(encoded) > MAX_GRAPH_PROPERTY_BYTES:
        raise CorpusGraphValidationError(
            f"properties exceed {MAX_GRAPH_PROPERTY_BYTES} canonical bytes"
        )
    _assert_bounded_strings(value)
    return _freeze(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _assert_no_inline_payload(properties: Mapping[str, Any]) -> None:
    prohibited = {
        "body",
        "content",
        "embedding",
        "embedding_vector",
        "library_md",
        "metadata_yaml",
        "skill_md",
        "source_body",
        "source_text",
        "text",
        "vector",
    }
    offending: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold() in prohibited:
                    offending.append(child_path)
                visit(item, child_path)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(properties, "")
    if offending:
        raise CorpusGraphValidationError(
            "graph properties must address source bodies and embeddings "
            f"separately; prohibited field(s): {', '.join(sorted(offending))}"
        )


def _assert_bounded_strings(value: Any) -> None:
    if isinstance(value, str):
        if len(value) > MAX_GRAPH_PROPERTY_STRING_CHARS:
            raise CorpusGraphValidationError(
                "graph property string exceeds "
                f"{MAX_GRAPH_PROPERTY_STRING_CHARS} characters"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_bounded_strings(key)
            _assert_bounded_strings(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_bounded_strings(item)


__all__ = [
    "AddressedArtifact",
    "CORPUS_GRAPH_IDENTITY_DOMAIN",
    "CORPUS_GRAPH_SCHEMA_VERSION",
    "CORPUS_ONTOLOGY",
    "CORPUS_ONTOLOGY_VERSION",
    "MAX_GRAPH_PROPERTY_BYTES",
    "MAX_GRAPH_PROPERTY_STRING_CHARS",
    "CorpusEdge",
    "CorpusEdgeType",
    "CorpusGraphArtifact",
    "CorpusGraphEdge",
    "CorpusGraphNode",
    "CorpusGraphValidationError",
    "CorpusNode",
    "CorpusNodeType",
    "CorpusOntology",
    "EdgeType",
    "IntentCorpusGraph",
    "NodeType",
    "structural_graph_digest",
]
