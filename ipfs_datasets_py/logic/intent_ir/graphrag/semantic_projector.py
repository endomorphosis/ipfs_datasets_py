"""Deterministic projection of validated Intent IR into a semantic graph.

The semantic graph is deliberately distinct from the corpus evidence graph.
Only relationships explicitly represented by validated Intent IR are semantic
assertions.  Retrieval-neighbor and embedding-similarity observations have a
separate edge partition and are never manufactured by this projector.

Every node and edge is bound to the canonical Intent IR digest, the graph
digest, and one or more exact ``SourceRef`` identifiers.  When a corpus graph
is supplied, every source is additionally checked against that graph and its
content digest before any storage side effect occurs.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1, cid_v1_from_digest, sha256_digest
from ..canonicalize import canonical_intent_ir_bytes, intent_ir_sha256
from ..schema import (
    ControlEdgeKind,
    IntentIRDocument,
    IntentIRValidationError,
    NodeGrounding,
    SourceRef,
    StatementKind,
    validate_intent_ir,
)
from .corpus_projector import ContentAddressedStore
from .ontology import CorpusNodeType, IntentCorpusGraph


SEMANTIC_ONTOLOGY_VERSION: Final = "semantic-intent-ontology/v1"
SEMANTIC_GRAPH_SCHEMA_VERSION: Final = "semantic-intent-graph/v1"
SEMANTIC_GRAPH_MEDIA_TYPE: Final = (
    "application/vnd.intent-ir.semantic-graph+json"
)
SEMANTIC_GRAPH_IDENTITY_DOMAIN: Final = "semantic-intent-graph"

# Descriptive aliases for callers that qualify semantic constants explicitly.
INTENT_SEMANTIC_ONTOLOGY_VERSION = SEMANTIC_ONTOLOGY_VERSION
INTENT_SEMANTIC_GRAPH_SCHEMA_VERSION = SEMANTIC_GRAPH_SCHEMA_VERSION
SEMANTIC_INTENT_ONTOLOGY_VERSION = SEMANTIC_ONTOLOGY_VERSION
SEMANTIC_INTENT_GRAPH_SCHEMA_VERSION = SEMANTIC_GRAPH_SCHEMA_VERSION

_ZERO_DIGEST = "sha256:" + ("0" * 64)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")
_MAX_PROPERTY_BYTES = 65_536
_MAX_PROPERTY_STRING_CHARS = 8_192


class SemanticProjectionError(ValueError):
    """Raised when Intent IR cannot be safely projected."""


class SemanticGraphValidationError(ValueError):
    """Raised when a semantic graph artifact violates its contract."""


class SemanticNodeType(str, Enum):
    """Versioned semantic-intent node vocabulary."""

    INTENT_DOCUMENT = "intent_document"
    SOURCE_REFERENCE = "source_reference"
    GOAL = "goal"
    STATEMENT = "statement"
    ACTION = "action"
    ACTOR = "actor"
    RESOURCE = "resource"
    TOOL = "tool"
    INPUT = "input"
    OUTPUT = "output"
    FAILURE = "failure"
    VERIFICATION_CRITERION = "verification_criterion"
    FORMAL_SYMBOL = "formal_symbol"


class SemanticEdgeType(str, Enum):
    """Versioned relationship vocabulary.

    ``SIMILAR_TO`` exists so imported retrieval observations have a typed
    representation, but it is valid only in the graph's similarity partition.
    """

    HAS_GOAL = "HAS_GOAL"
    REQUIRES = "REQUIRES"
    GUARDED_BY = "GUARDED_BY"
    PERFORMS = "PERFORMS"
    USES = "USES"
    CONSUMES = "CONSUMES"
    PRODUCES = "PRODUCES"
    CAUSES = "CAUSES"
    VERIFIED_BY = "VERIFIED_BY"
    NEXT = "NEXT"
    ON_SUCCESS = "ON_SUCCESS"
    ON_FAILURE = "ON_FAILURE"
    CONDITIONAL = "CONDITIONAL"
    RETRIES = "RETRIES"
    PARALLEL_WITH = "PARALLEL_WITH"
    JOINS = "JOINS"
    GROUNDED_IN = "GROUNDED_IN"
    LOWERS_TO = "LOWERS_TO"
    SIMILAR_TO = "SIMILAR_TO"


class SemanticEdgeClass(str, Enum):
    """Assertion class used to keep similarity out of semantic reasoning."""

    SEMANTIC = "semantic"
    CONTROL = "control"
    GROUNDING = "grounding"
    LOWERING = "lowering"
    SIMILARITY = "similarity"


_CONTROL_EDGE_TYPES = frozenset(
    {
        SemanticEdgeType.NEXT,
        SemanticEdgeType.ON_SUCCESS,
        SemanticEdgeType.ON_FAILURE,
        SemanticEdgeType.CONDITIONAL,
        SemanticEdgeType.RETRIES,
        SemanticEdgeType.PARALLEL_WITH,
        SemanticEdgeType.JOINS,
    }
)
_STATEMENT_NODE_TYPES = frozenset(
    {
        SemanticNodeType.GOAL,
        SemanticNodeType.STATEMENT,
        SemanticNodeType.FAILURE,
        SemanticNodeType.VERIFICATION_CRITERION,
    }
)


def _edge_class(edge_type: SemanticEdgeType) -> SemanticEdgeClass:
    if edge_type in _CONTROL_EDGE_TYPES:
        return SemanticEdgeClass.CONTROL
    if edge_type is SemanticEdgeType.GROUNDED_IN:
        return SemanticEdgeClass.GROUNDING
    if edge_type is SemanticEdgeType.LOWERS_TO:
        return SemanticEdgeClass.LOWERING
    if edge_type is SemanticEdgeType.SIMILAR_TO:
        return SemanticEdgeClass.SIMILARITY
    return SemanticEdgeClass.SEMANTIC


@dataclass(frozen=True, slots=True)
class SemanticGraphOntology:
    """Machine-readable declaration of the semantic graph vocabulary."""

    version: str = SEMANTIC_ONTOLOGY_VERSION
    node_types: tuple[str, ...] = tuple(item.value for item in SemanticNodeType)
    edge_types: tuple[str, ...] = tuple(item.value for item in SemanticEdgeType)

    def __post_init__(self) -> None:
        if self.version != SEMANTIC_ONTOLOGY_VERSION:
            raise SemanticGraphValidationError(
                f"unsupported semantic ontology version: {self.version!r}"
            )
        if self.node_types != tuple(item.value for item in SemanticNodeType):
            raise SemanticGraphValidationError(
                "node_types must exactly match the versioned semantic vocabulary"
            )
        if self.edge_types != tuple(item.value for item in SemanticEdgeType):
            raise SemanticGraphValidationError(
                "edge_types must exactly match the versioned semantic vocabulary"
            )

    def validate_edge(
        self,
        edge_type: SemanticEdgeType | str,
        source_type: SemanticNodeType | str,
        target_type: SemanticNodeType | str,
        *,
        edge_class: SemanticEdgeClass | str,
    ) -> None:
        edge = _enum_value(SemanticEdgeType, edge_type, "edge_type")
        source = _enum_value(SemanticNodeType, source_type, "source_type")
        target = _enum_value(SemanticNodeType, target_type, "target_type")
        category = _enum_value(SemanticEdgeClass, edge_class, "edge_class")
        expected_class = _edge_class(edge)
        if category is not expected_class:
            raise SemanticGraphValidationError(
                f"{edge.value} must be classified as {expected_class.value}, "
                f"not {category.value}"
            )

        valid = False
        if edge is SemanticEdgeType.HAS_GOAL:
            valid = (
                source is SemanticNodeType.INTENT_DOCUMENT
                and target is SemanticNodeType.GOAL
            )
        elif edge is SemanticEdgeType.REQUIRES:
            valid = (
                source in {SemanticNodeType.ACTION, SemanticNodeType.INTENT_DOCUMENT}
                and target in _STATEMENT_NODE_TYPES
            )
        elif edge is SemanticEdgeType.GUARDED_BY:
            valid = source is SemanticNodeType.ACTION and target in _STATEMENT_NODE_TYPES
        elif edge is SemanticEdgeType.PERFORMS:
            valid = (
                source is SemanticNodeType.ACTOR
                and target is SemanticNodeType.ACTION
            )
        elif edge is SemanticEdgeType.USES:
            valid = (
                source is SemanticNodeType.ACTION
                and target in {SemanticNodeType.RESOURCE, SemanticNodeType.TOOL}
            )
        elif edge is SemanticEdgeType.CONSUMES:
            valid = (
                source is SemanticNodeType.ACTION
                and target is SemanticNodeType.INPUT
            )
        elif edge is SemanticEdgeType.PRODUCES:
            valid = (
                source is SemanticNodeType.ACTION
                and target is SemanticNodeType.OUTPUT
            )
        elif edge is SemanticEdgeType.CAUSES:
            valid = source is SemanticNodeType.ACTION and target in _STATEMENT_NODE_TYPES
        elif edge is SemanticEdgeType.VERIFIED_BY:
            valid = source is SemanticNodeType.ACTION and target in _STATEMENT_NODE_TYPES
        elif edge in _CONTROL_EDGE_TYPES:
            valid = (
                source is SemanticNodeType.ACTION
                and target is SemanticNodeType.ACTION
            )
        elif edge is SemanticEdgeType.GROUNDED_IN:
            valid = (
                source is not SemanticNodeType.SOURCE_REFERENCE
                and target is SemanticNodeType.SOURCE_REFERENCE
            )
        elif edge is SemanticEdgeType.LOWERS_TO:
            valid = (
                source in _STATEMENT_NODE_TYPES
                and target is SemanticNodeType.FORMAL_SYMBOL
            )
        elif edge is SemanticEdgeType.SIMILAR_TO:
            valid = source is target
        if not valid:
            raise SemanticGraphValidationError(
                f"{edge.value} does not permit {source.value} -> {target.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_types": list(self.edge_types),
            "node_types": list(self.node_types),
            "version": self.version,
        }


SEMANTIC_ONTOLOGY = SemanticGraphOntology()


@dataclass(frozen=True, slots=True)
class SemanticGraphNode(Mapping[str, Any]):
    """One immutable, source-grounded semantic node."""

    node_id: str
    node_type: SemanticNodeType
    intent_ir_digest: str
    graph_digest: str
    source_ref_ids: tuple[str, ...]
    properties: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = SEMANTIC_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _validate_id(self.node_id, "node_id")
        object.__setattr__(
            self,
            "node_type",
            _enum_value(SemanticNodeType, self.node_type, "node_type"),
        )
        _validate_digest(self.intent_ir_digest, "node intent_ir_digest")
        _validate_digest(self.graph_digest, "node graph_digest")
        source_ref_ids = _canonical_ids(self.source_ref_ids, "node source_ref_ids")
        if not source_ref_ids:
            raise SemanticGraphValidationError(
                "semantic nodes must have source_ref_ids"
            )
        object.__setattr__(self, "source_ref_ids", source_ref_ids)
        if self.ontology_version != SEMANTIC_ONTOLOGY_VERSION:
            raise SemanticGraphValidationError("unsupported node ontology_version")
        object.__setattr__(self, "properties", _freeze_mapping(self.properties))

    @property
    def id(self) -> str:
        return self.node_id

    @property
    def kind(self) -> SemanticNodeType:
        return self.node_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_digest": self.graph_digest,
            "id": self.node_id,
            "intent_ir_digest": self.intent_ir_digest,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "properties": _thaw(self.properties),
            "source_ref_ids": list(self.source_ref_ids),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True, slots=True)
class SemanticGraphEdge(Mapping[str, Any]):
    """One typed semantic, control, grounding, lowering, or similarity edge."""

    edge_id: str
    edge_type: SemanticEdgeType
    edge_class: SemanticEdgeClass
    source: str
    target: str
    intent_ir_digest: str
    graph_digest: str
    source_ref_ids: tuple[str, ...]
    properties: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = SEMANTIC_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        _validate_id(self.edge_id, "edge_id")
        object.__setattr__(
            self,
            "edge_type",
            _enum_value(SemanticEdgeType, self.edge_type, "edge_type"),
        )
        object.__setattr__(
            self,
            "edge_class",
            _enum_value(SemanticEdgeClass, self.edge_class, "edge_class"),
        )
        _validate_id(self.source, "edge source")
        _validate_id(self.target, "edge target")
        if self.source == self.target:
            raise SemanticGraphValidationError(
                "self-referential semantic graph edges are invalid"
            )
        _validate_digest(self.intent_ir_digest, "edge intent_ir_digest")
        _validate_digest(self.graph_digest, "edge graph_digest")
        source_ref_ids = _canonical_ids(self.source_ref_ids, "edge source_ref_ids")
        if not source_ref_ids:
            raise SemanticGraphValidationError(
                "semantic graph edges must have source_ref_ids"
            )
        object.__setattr__(self, "source_ref_ids", source_ref_ids)
        if self.ontology_version != SEMANTIC_ONTOLOGY_VERSION:
            raise SemanticGraphValidationError("unsupported edge ontology_version")
        object.__setattr__(self, "properties", _freeze_mapping(self.properties))

    @property
    def id(self) -> str:
        return self.edge_id

    @property
    def kind(self) -> SemanticEdgeType:
        return self.edge_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_class": self.edge_class.value,
            "edge_type": self.edge_type.value,
            "graph_digest": self.graph_digest,
            "id": self.edge_id,
            "intent_ir_digest": self.intent_ir_digest,
            "ontology_version": self.ontology_version,
            "properties": _thaw(self.properties),
            "source": self.source,
            "source_ref_ids": list(self.source_ref_ids),
            "target": self.target,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True, slots=True)
class SemanticIntentGraph(Mapping[str, Any]):
    """A deterministic, content-addressed semantic Intent IR graph."""

    nodes: tuple[SemanticGraphNode, ...]
    semantic_edges: tuple[SemanticGraphEdge, ...]
    similarity_edges: tuple[SemanticGraphEdge, ...]
    intent_ir_digest: str
    intent_ir_cid: str
    graph_digest: str
    source_ref_ids: tuple[str, ...]
    corpus_graph_digest: str = ""
    corpus_graph_cid: str = ""
    graph_cid: str = ""
    schema_version: str = SEMANTIC_GRAPH_SCHEMA_VERSION
    ontology_version: str = SEMANTIC_ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "semantic_edges", tuple(self.semantic_edges))
        object.__setattr__(self, "similarity_edges", tuple(self.similarity_edges))
        source_ref_ids = _canonical_ids(
            self.source_ref_ids, "graph source_ref_ids"
        )
        if not source_ref_ids:
            raise SemanticGraphValidationError(
                "source_ref_ids must not be empty"
            )
        object.__setattr__(self, "source_ref_ids", source_ref_ids)
        if self.schema_version != SEMANTIC_GRAPH_SCHEMA_VERSION:
            raise SemanticGraphValidationError(
                "unsupported semantic graph schema_version"
            )
        if self.ontology_version != SEMANTIC_ONTOLOGY_VERSION:
            raise SemanticGraphValidationError(
                "unsupported semantic graph ontology_version"
            )
        _validate_digest(self.intent_ir_digest, "intent_ir_digest")
        _validate_digest(self.graph_digest, "graph_digest")
        _require_text(self.intent_ir_cid, "intent_ir_cid")
        expected_ir_cid = cid_v1_from_digest(
            bytes.fromhex(self.intent_ir_digest.removeprefix("sha256:"))
        )
        if self.intent_ir_cid != expected_ir_cid:
            raise SemanticGraphValidationError(
                "intent_ir_cid does not match intent_ir_digest"
            )
        if self.corpus_graph_digest:
            _validate_digest(self.corpus_graph_digest, "corpus_graph_digest")
        elif self.corpus_graph_cid:
            raise SemanticGraphValidationError(
                "corpus_graph_cid requires corpus_graph_digest"
            )
        if any(not isinstance(node, SemanticGraphNode) for node in self.nodes):
            raise SemanticGraphValidationError(
                "nodes must contain SemanticGraphNode values"
            )
        all_edges = self.semantic_edges + self.similarity_edges
        if any(not isinstance(edge, SemanticGraphEdge) for edge in all_edges):
            raise SemanticGraphValidationError(
                "edge partitions must contain SemanticGraphEdge values"
            )
        if tuple(sorted(self.nodes, key=lambda item: item.node_id)) != self.nodes:
            raise SemanticGraphValidationError("nodes must be sorted by node_id")
        if tuple(
            sorted(self.semantic_edges, key=lambda item: item.edge_id)
        ) != self.semantic_edges:
            raise SemanticGraphValidationError(
                "semantic_edges must be sorted by edge_id"
            )
        if tuple(
            sorted(self.similarity_edges, key=lambda item: item.edge_id)
        ) != self.similarity_edges:
            raise SemanticGraphValidationError(
                "similarity_edges must be sorted by edge_id"
            )
        node_by_id = {node.node_id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise SemanticGraphValidationError("duplicate node_id")
        if len({edge.edge_id for edge in all_edges}) != len(all_edges):
            raise SemanticGraphValidationError("duplicate edge_id")
        known_sources = set(self.source_ref_ids)
        for node in self.nodes:
            if node.intent_ir_digest != self.intent_ir_digest:
                raise SemanticGraphValidationError(
                    "node Intent IR digest binding mismatch"
                )
            if node.graph_digest != self.graph_digest:
                raise SemanticGraphValidationError(
                    "node graph_digest binding mismatch"
                )
            if not set(node.source_ref_ids) <= known_sources:
                raise SemanticGraphValidationError(
                    "node references an unknown source_ref_id"
                )
        for edge in all_edges:
            if edge.intent_ir_digest != self.intent_ir_digest:
                raise SemanticGraphValidationError(
                    "edge Intent IR digest binding mismatch"
                )
            if edge.graph_digest != self.graph_digest:
                raise SemanticGraphValidationError(
                    "edge graph_digest binding mismatch"
                )
            if edge.source not in node_by_id or edge.target not in node_by_id:
                raise SemanticGraphValidationError("edge endpoint is dangling")
            if not set(edge.source_ref_ids) <= known_sources:
                raise SemanticGraphValidationError(
                    "edge references an unknown source_ref_id"
                )
            SEMANTIC_ONTOLOGY.validate_edge(
                edge.edge_type,
                node_by_id[edge.source].node_type,
                node_by_id[edge.target].node_type,
                edge_class=edge.edge_class,
            )
        if any(
            edge.edge_class is SemanticEdgeClass.SIMILARITY
            for edge in self.semantic_edges
        ):
            raise SemanticGraphValidationError(
                "similarity observations cannot appear in semantic_edges"
            )
        if any(
            edge.edge_class is not SemanticEdgeClass.SIMILARITY
            for edge in self.similarity_edges
        ):
            raise SemanticGraphValidationError(
                "similarity_edges may contain only similarity observations"
            )
        actual_digest = semantic_graph_digest(
            self.nodes,
            self.semantic_edges,
            self.similarity_edges,
            intent_ir_digest=self.intent_ir_digest,
            intent_ir_cid=self.intent_ir_cid,
            source_ref_ids=self.source_ref_ids,
            corpus_graph_digest=self.corpus_graph_digest,
            corpus_graph_cid=self.corpus_graph_cid,
        )
        if actual_digest != self.graph_digest:
            raise SemanticGraphValidationError(
                "graph_digest does not match canonical structural projection"
            )
        if self.graph_cid:
            _require_text(self.graph_cid, "graph_cid")
            if self.graph_cid != cid_v1(self.canonical_bytes()):
                raise SemanticGraphValidationError(
                    "graph_cid does not match canonical graph artifact"
                )

    @property
    def edges(self) -> tuple[SemanticGraphEdge, ...]:
        """Return both partitions without erasing their edge classes."""

        return self.semantic_edges + self.similarity_edges

    @property
    def digest(self) -> str:
        return self.graph_digest

    @property
    def cid(self) -> str:
        return self.graph_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_graph_cid": self.corpus_graph_cid,
            "corpus_graph_digest": self.corpus_graph_digest,
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "intent_ir_cid": self.intent_ir_cid,
            "intent_ir_digest": self.intent_ir_digest,
            "nodes": [node.to_dict() for node in self.nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
            "semantic_edges": [edge.to_dict() for edge in self.semantic_edges],
            "similarity_edges": [
                edge.to_dict() for edge in self.similarity_edges
            ],
            "source_ref_ids": list(self.source_ref_ids),
        }

    def canonical_bytes(self) -> bytes:
        payload = self.to_dict()
        payload["graph_cid"] = ""
        return canonical_json_bytes(payload)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(slots=True)
class _GraphBuilder:
    intent_ir_digest: str
    nodes: dict[str, SemanticGraphNode] = field(default_factory=dict)
    edges: dict[str, SemanticGraphEdge] = field(default_factory=dict)

    def add_node(
        self,
        node_type: SemanticNodeType,
        identity: Mapping[str, Any],
        *,
        source_ref_ids: tuple[str, ...],
        properties: Mapping[str, Any],
    ) -> str:
        node_id = _stable_id("node", node_type.value, identity)
        node = SemanticGraphNode(
            node_id=node_id,
            node_type=node_type,
            intent_ir_digest=self.intent_ir_digest,
            graph_digest=_ZERO_DIGEST,
            source_ref_ids=source_ref_ids,
            properties=properties,
        )
        existing = self.nodes.get(node_id)
        if existing is not None and existing != node:
            raise SemanticProjectionError(
                f"conflicting projection for node {node_id}"
            )
        self.nodes[node_id] = node
        return node_id

    def add_edge(
        self,
        edge_type: SemanticEdgeType,
        source: str,
        target: str,
        *,
        source_ref_ids: tuple[str, ...],
        properties: Mapping[str, Any] | None = None,
    ) -> str:
        edge_properties = dict(properties or {})
        category = _edge_class(edge_type)
        edge_id = _stable_id(
            "edge",
            edge_type.value,
            {
                "edge_class": category.value,
                "properties": edge_properties,
                "source": source,
                "source_ref_ids": sorted(set(source_ref_ids)),
                "target": target,
            },
        )
        edge = SemanticGraphEdge(
            edge_id=edge_id,
            edge_type=edge_type,
            edge_class=category,
            source=source,
            target=target,
            intent_ir_digest=self.intent_ir_digest,
            graph_digest=_ZERO_DIGEST,
            source_ref_ids=source_ref_ids,
            properties=edge_properties,
        )
        existing = self.edges.get(edge_id)
        if existing is not None and existing != edge:
            raise SemanticProjectionError(
                f"conflicting projection for edge {edge_id}"
            )
        self.edges[edge_id] = edge
        return edge_id


_CONTROL_EDGE_MAP: Mapping[ControlEdgeKind, SemanticEdgeType] = MappingProxyType(
    {
        ControlEdgeKind.NEXT: SemanticEdgeType.NEXT,
        ControlEdgeKind.ON_SUCCESS: SemanticEdgeType.ON_SUCCESS,
        ControlEdgeKind.ON_FAILURE: SemanticEdgeType.ON_FAILURE,
        ControlEdgeKind.CONDITIONAL: SemanticEdgeType.CONDITIONAL,
        ControlEdgeKind.RETRY: SemanticEdgeType.RETRIES,
        ControlEdgeKind.PARALLEL: SemanticEdgeType.PARALLEL_WITH,
        ControlEdgeKind.JOIN: SemanticEdgeType.JOINS,
    }
)


class SemanticIntentGraphProjector:
    """Project one validated, fully grounded Intent IR document."""

    def __init__(self, store: ContentAddressedStore | None = None) -> None:
        if store is not None and not isinstance(store, ContentAddressedStore):
            raise TypeError(
                "store must implement put_bytes(payload, media_type=...)"
            )
        self.store = store

    def project(
        self,
        document: IntentIRDocument,
        corpus_graph: IntentCorpusGraph | None = None,
    ) -> SemanticIntentGraph:
        """Build, validate, address, and optionally store a semantic graph."""

        try:
            validated = validate_intent_ir(document)
        except (IntentIRValidationError, TypeError, ValueError) as exc:
            raise SemanticProjectionError(
                f"Intent IR validation failed: {exc}"
            ) from exc
        self._require_exact_grounding(validated)
        if corpus_graph is not None and not isinstance(
            corpus_graph, IntentCorpusGraph
        ):
            raise TypeError("corpus_graph must be an IntentCorpusGraph")

        ir_bytes = canonical_intent_ir_bytes(validated)
        ir_digest = intent_ir_sha256(validated)
        ir_cid = cid_v1(ir_bytes)
        source_by_id = {item.ref_id: item for item in validated.sources}
        statement_by_id = {
            item.statement_id: item for item in validated.statements
        }
        corpus_nodes = {
            source.ref_id: self._resolve_corpus_node(source, corpus_graph)
            for source in validated.sources
        }
        builder = _GraphBuilder(ir_digest)
        all_source_ids = tuple(sorted(source_by_id))
        document_node = builder.add_node(
            SemanticNodeType.INTENT_DOCUMENT,
            {"document_id": validated.document_id},
            source_ref_ids=all_source_ids,
            properties={
                "document_id": validated.document_id,
                "entry_action_ids": list(sorted(validated.entry_action_ids)),
                "intent_kind": validated.intent_kind.value,
                "schema_version": validated.schema_version,
                "tags": list(sorted(validated.tags)),
                "terminal_action_ids": list(sorted(validated.terminal_action_ids)),
                "title": validated.title,
            },
        )

        source_nodes: dict[str, str] = {}
        for source in sorted(validated.sources, key=lambda item: item.ref_id):
            corpus_node_id = corpus_nodes[source.ref_id]
            source_nodes[source.ref_id] = builder.add_node(
                SemanticNodeType.SOURCE_REFERENCE,
                {
                    "document_id": validated.document_id,
                    "ref_id": source.ref_id,
                },
                source_ref_ids=(source.ref_id,),
                properties={
                    "container_sha256": (
                        f"sha256:{source.container_sha256}"
                        if source.container_sha256
                        else ""
                    ),
                    "container_uri": source.container_uri,
                    "content_cid": source.content_cid,
                    "content_digest": f"sha256:{source.content_sha256}",
                    "corpus_node_id": corpus_node_id,
                    "license_expression": source.license_expression,
                    "ref_id": source.ref_id,
                    "review_status": source.review_status.value,
                    "source_id": source.source_id,
                    "source_revision": source.source_revision,
                    "source_uri": source.source_uri,
                    "span": source.span.to_dict() if source.span else None,
                },
            )

        statement_nodes: dict[str, str] = {}
        for statement in sorted(
            validated.statements, key=lambda item: item.statement_id
        ):
            node_type = _statement_node_type(statement.kind)
            statement_node = builder.add_node(
                node_type,
                {
                    "document_id": validated.document_id,
                    "statement_id": statement.statement_id,
                },
                source_ref_ids=statement.source_ref_ids,
                properties={
                    "arguments": list(statement.arguments),
                    "confidence": float(statement.confidence),
                    "grounding": statement.grounding.value,
                    "modality": statement.modality.value,
                    "normalized_text": statement.normalized_text,
                    "predicate": statement.predicate,
                    "review_status": statement.review_status.value,
                    "statement_id": statement.statement_id,
                    "statement_kind": statement.kind.value,
                },
            )
            statement_nodes[statement.statement_id] = statement_node
            if statement.kind is StatementKind.GOAL:
                builder.add_edge(
                    SemanticEdgeType.HAS_GOAL,
                    document_node,
                    statement_node,
                    source_ref_ids=statement.source_ref_ids,
                )

        shared_refs = _shared_action_reference_sources(validated)
        shared_nodes: dict[tuple[SemanticNodeType, str], str] = {}
        for (node_type, value), ref_ids in sorted(
            shared_refs.items(), key=lambda item: (item[0][0].value, item[0][1])
        ):
            shared_nodes[(node_type, value)] = builder.add_node(
                node_type,
                {
                    "document_id": validated.document_id,
                    "value": value,
                },
                source_ref_ids=tuple(sorted(ref_ids)),
                properties={"value": value},
            )

        action_nodes: dict[str, str] = {}
        for action in sorted(validated.actions, key=lambda item: item.action_id):
            action_node = builder.add_node(
                SemanticNodeType.ACTION,
                {
                    "action_id": action.action_id,
                    "document_id": validated.document_id,
                },
                source_ref_ids=action.source_ref_ids,
                properties={
                    "action_id": action.action_id,
                    "actor": action.actor,
                    "entry": action.action_id in validated.entry_action_ids,
                    "grounding": action.grounding.value,
                    "terminal": action.action_id
                    in validated.terminal_action_ids,
                    "verb": action.verb,
                },
            )
            action_nodes[action.action_id] = action_node
            builder.add_edge(
                SemanticEdgeType.PERFORMS,
                shared_nodes[(SemanticNodeType.ACTOR, action.actor)],
                action_node,
                source_ref_ids=action.source_ref_ids,
            )
            for value in action.object_refs:
                builder.add_edge(
                    SemanticEdgeType.USES,
                    action_node,
                    shared_nodes[(SemanticNodeType.RESOURCE, value)],
                    source_ref_ids=action.source_ref_ids,
                )
            for value in action.tool_refs:
                builder.add_edge(
                    SemanticEdgeType.USES,
                    action_node,
                    shared_nodes[(SemanticNodeType.TOOL, value)],
                    source_ref_ids=action.source_ref_ids,
                )
            for value in action.input_refs:
                builder.add_edge(
                    SemanticEdgeType.CONSUMES,
                    action_node,
                    shared_nodes[(SemanticNodeType.INPUT, value)],
                    source_ref_ids=action.source_ref_ids,
                )
            for value in action.output_refs:
                builder.add_edge(
                    SemanticEdgeType.PRODUCES,
                    action_node,
                    shared_nodes[(SemanticNodeType.OUTPUT, value)],
                    source_ref_ids=action.source_ref_ids,
                )
            for statement_id in action.precondition_ids:
                statement = statement_by_id[statement_id]
                edge_type = (
                    SemanticEdgeType.GUARDED_BY
                    if statement.kind is StatementKind.GUARD
                    else SemanticEdgeType.REQUIRES
                )
                builder.add_edge(
                    edge_type,
                    action_node,
                    statement_nodes[statement_id],
                    source_ref_ids=_union_ids(
                        action.source_ref_ids, statement.source_ref_ids
                    ),
                )
            for statement_id in action.effect_ids:
                statement = statement_by_id[statement_id]
                builder.add_edge(
                    SemanticEdgeType.CAUSES,
                    action_node,
                    statement_nodes[statement_id],
                    source_ref_ids=_union_ids(
                        action.source_ref_ids, statement.source_ref_ids
                    ),
                )
            for statement_id in action.verification_ids:
                statement = statement_by_id[statement_id]
                builder.add_edge(
                    SemanticEdgeType.VERIFIED_BY,
                    action_node,
                    statement_nodes[statement_id],
                    source_ref_ids=_union_ids(
                        action.source_ref_ids, statement.source_ref_ids
                    ),
                )

        for control in sorted(
            validated.control_edges, key=lambda item: item.edge_id
        ):
            builder.add_edge(
                _CONTROL_EDGE_MAP[control.kind],
                action_nodes[control.source_action_id],
                action_nodes[control.target_action_id],
                source_ref_ids=control.source_ref_ids,
                properties={
                    "control_edge_id": control.edge_id,
                    "control_edge_kind": control.kind.value,
                    "grounding": control.grounding.value,
                    "guard_statement_id": control.guard_statement_id,
                },
            )
            if control.guard_statement_id:
                guard = statement_by_id[control.guard_statement_id]
                builder.add_edge(
                    SemanticEdgeType.GUARDED_BY,
                    action_nodes[control.source_action_id],
                    statement_nodes[control.guard_statement_id],
                    source_ref_ids=_union_ids(
                        control.source_ref_ids, guard.source_ref_ids
                    ),
                    properties={"control_edge_id": control.edge_id},
                )

        formal_nodes: dict[str, str] = {}
        formal_refs: dict[str, set[str]] = {}
        for statement in validated.statements:
            if statement.predicate:
                formal_refs.setdefault(statement.predicate, set()).update(
                    statement.source_ref_ids
                )
        for predicate, ref_ids in sorted(formal_refs.items()):
            formal_nodes[predicate] = builder.add_node(
                SemanticNodeType.FORMAL_SYMBOL,
                {
                    "document_id": validated.document_id,
                    "predicate": predicate,
                },
                source_ref_ids=tuple(sorted(ref_ids)),
                properties={"predicate": predicate},
            )
        for statement in sorted(
            validated.statements, key=lambda item: item.statement_id
        ):
            if statement.predicate:
                builder.add_edge(
                    SemanticEdgeType.LOWERS_TO,
                    statement_nodes[statement.statement_id],
                    formal_nodes[statement.predicate],
                    source_ref_ids=statement.source_ref_ids,
                )

        # Grounding edges make provenance traversable while each node and edge
        # also carries the exact source IDs for detached validation.
        for node in tuple(sorted(builder.nodes.values(), key=lambda item: item.node_id)):
            if node.node_type is SemanticNodeType.SOURCE_REFERENCE:
                continue
            for ref_id in node.source_ref_ids:
                builder.add_edge(
                    SemanticEdgeType.GROUNDED_IN,
                    node.node_id,
                    source_nodes[ref_id],
                    source_ref_ids=(ref_id,),
                )

        unbound_nodes = tuple(
            sorted(builder.nodes.values(), key=lambda item: item.node_id)
        )
        unbound_semantic_edges = tuple(
            sorted(
                (
                    edge
                    for edge in builder.edges.values()
                    if edge.edge_class is not SemanticEdgeClass.SIMILARITY
                ),
                key=lambda item: item.edge_id,
            )
        )
        similarity_edges: tuple[SemanticGraphEdge, ...] = ()
        corpus_digest = corpus_graph.graph_digest if corpus_graph else ""
        corpus_cid = corpus_graph.graph_cid if corpus_graph else ""
        graph_digest = semantic_graph_digest(
            unbound_nodes,
            unbound_semantic_edges,
            similarity_edges,
            intent_ir_digest=ir_digest,
            intent_ir_cid=ir_cid,
            source_ref_ids=all_source_ids,
            corpus_graph_digest=corpus_digest,
            corpus_graph_cid=corpus_cid,
        )
        nodes = tuple(
            replace(node, graph_digest=graph_digest) for node in unbound_nodes
        )
        semantic_edges = tuple(
            replace(edge, graph_digest=graph_digest)
            for edge in unbound_semantic_edges
        )
        graph = SemanticIntentGraph(
            nodes=nodes,
            semantic_edges=semantic_edges,
            similarity_edges=(),
            intent_ir_digest=ir_digest,
            intent_ir_cid=ir_cid,
            graph_digest=graph_digest,
            source_ref_ids=all_source_ids,
            corpus_graph_digest=corpus_digest,
            corpus_graph_cid=corpus_cid,
        )
        graph_cid = cid_v1(graph.canonical_bytes())
        if self.store is not None:
            stored_cid = self.store.put_bytes(
                graph.canonical_bytes(), media_type=SEMANTIC_GRAPH_MEDIA_TYPE
            )
            if stored_cid != graph_cid:
                raise SemanticProjectionError(
                    "content-addressed store returned an address that does not "
                    "match the fixed raw CIDv1/SHA-256 profile"
                )
        return replace(graph, graph_cid=graph_cid)

    @staticmethod
    def _require_exact_grounding(document: IntentIRDocument) -> None:
        ungrounded: list[str] = []
        for statement in document.statements:
            if (
                statement.grounding is not NodeGrounding.GROUNDED
                or not statement.source_ref_ids
            ):
                ungrounded.append(f"statement {statement.statement_id!r}")
        for action in document.actions:
            if (
                action.grounding is not NodeGrounding.GROUNDED
                or not action.source_ref_ids
            ):
                ungrounded.append(f"action {action.action_id!r}")
        for edge in document.control_edges:
            if (
                edge.grounding is not NodeGrounding.GROUNDED
                or not edge.source_ref_ids
            ):
                ungrounded.append(f"control edge {edge.edge_id!r}")
        if ungrounded:
            raise SemanticProjectionError(
                "semantic projection rejects ungrounded IR nodes or edges: "
                + ", ".join(ungrounded)
            )

    @staticmethod
    def _resolve_corpus_node(
        source: SourceRef, corpus_graph: IntentCorpusGraph | None
    ) -> str:
        if corpus_graph is None:
            return ""
        source_digest = f"sha256:{source.content_sha256}"
        if source_digest not in corpus_graph.source_digests:
            raise SemanticProjectionError(
                f"source {source.ref_id!r} content digest is absent from "
                "the supplied corpus graph"
            )
        if (
            source.container_sha256
            and f"sha256:{source.container_sha256}"
            not in corpus_graph.source_digests
        ):
            raise SemanticProjectionError(
                f"source {source.ref_id!r} container digest is absent from "
                "the supplied corpus graph"
            )
        candidates = [
            node
            for node in corpus_graph.nodes
            if node.source_digest == source_digest
            and node.node_type
            in {
                CorpusNodeType.SOURCE_DOCUMENT,
                CorpusNodeType.SKILL,
                CorpusNodeType.SOURCE_SPAN,
            }
        ]
        exact_identity = [
            node
            for node in candidates
            if source.source_id
            in {
                str(node.properties.get("source_id", "")),
                str(node.properties.get("primary_source_id", "")),
                str(node.properties.get("skill_id", "")),
            }
            or source.source_uri == str(node.properties.get("source_uri", ""))
        ]
        if not exact_identity:
            raise SemanticProjectionError(
                f"source {source.ref_id!r} identity has no exact grounding "
                "node in the supplied corpus graph"
            )
        return min(exact_identity, key=lambda item: item.node_id).node_id


# Short and protocol-oriented spellings retained for convenient discovery.
SemanticProjector = SemanticIntentGraphProjector
SemanticGraphProjector = SemanticIntentGraphProjector
IntentSemanticGraphProjector = SemanticIntentGraphProjector
SemanticGraphArtifact = SemanticIntentGraph
SemanticNode = SemanticGraphNode
SemanticEdge = SemanticGraphEdge
SemanticGraphNodeType = SemanticNodeType
SemanticGraphEdgeType = SemanticEdgeType
SemanticEdgeKind = SemanticEdgeType


def semantic_graph_digest(
    nodes: tuple[SemanticGraphNode, ...] | list[SemanticGraphNode],
    semantic_edges: tuple[SemanticGraphEdge, ...] | list[SemanticGraphEdge],
    similarity_edges: tuple[SemanticGraphEdge, ...] | list[SemanticGraphEdge],
    *,
    intent_ir_digest: str,
    intent_ir_cid: str,
    source_ref_ids: tuple[str, ...] | list[str],
    corpus_graph_digest: str = "",
    corpus_graph_cid: str = "",
) -> str:
    """Hash the canonical graph structure without circular digest bindings."""

    payload = {
        "corpus_graph_cid": corpus_graph_cid,
        "corpus_graph_digest": corpus_graph_digest,
        "intent_ir_cid": intent_ir_cid,
        "intent_ir_digest": intent_ir_digest,
        "nodes": [_node_digest_dict(item) for item in sorted(nodes, key=lambda item: item.node_id)],
        "ontology_version": SEMANTIC_ONTOLOGY_VERSION,
        "schema_version": SEMANTIC_GRAPH_SCHEMA_VERSION,
        "semantic_edges": [
            _edge_digest_dict(item)
            for item in sorted(semantic_edges, key=lambda item: item.edge_id)
        ],
        "similarity_edges": [
            _edge_digest_dict(item)
            for item in sorted(similarity_edges, key=lambda item: item.edge_id)
        ],
        "source_ref_ids": sorted(set(source_ref_ids)),
    }
    return sha256_digest(canonical_json_bytes(payload))


def _node_digest_dict(node: SemanticGraphNode) -> dict[str, Any]:
    return {
        "id": node.node_id,
        "intent_ir_digest": node.intent_ir_digest,
        "node_type": node.node_type.value,
        "ontology_version": node.ontology_version,
        "properties": _thaw(node.properties),
        "source_ref_ids": list(node.source_ref_ids),
    }


def _edge_digest_dict(edge: SemanticGraphEdge) -> dict[str, Any]:
    return {
        "edge_class": edge.edge_class.value,
        "edge_type": edge.edge_type.value,
        "id": edge.edge_id,
        "intent_ir_digest": edge.intent_ir_digest,
        "ontology_version": edge.ontology_version,
        "properties": _thaw(edge.properties),
        "source": edge.source,
        "source_ref_ids": list(edge.source_ref_ids),
        "target": edge.target,
    }


def _statement_node_type(kind: StatementKind) -> SemanticNodeType:
    if kind is StatementKind.GOAL:
        return SemanticNodeType.GOAL
    if kind is StatementKind.FAILURE:
        return SemanticNodeType.FAILURE
    if kind is StatementKind.VERIFICATION:
        return SemanticNodeType.VERIFICATION_CRITERION
    return SemanticNodeType.STATEMENT


def _shared_action_reference_sources(
    document: IntentIRDocument,
) -> dict[tuple[SemanticNodeType, str], set[str]]:
    shared: dict[tuple[SemanticNodeType, str], set[str]] = {}
    for action in document.actions:
        fields = (
            (SemanticNodeType.ACTOR, (action.actor,)),
            (SemanticNodeType.RESOURCE, action.object_refs),
            (SemanticNodeType.TOOL, action.tool_refs),
            (SemanticNodeType.INPUT, action.input_refs),
            (SemanticNodeType.OUTPUT, action.output_refs),
        )
        for node_type, values in fields:
            for value in values:
                shared.setdefault((node_type, value), set()).update(
                    action.source_ref_ids
                )
    return shared


def _union_ids(*collections: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item for values in collections for item in values}))


def _stable_id(namespace: str, kind: str, identity: Mapping[str, Any]) -> str:
    digest = sha256_digest(
        canonical_json_bytes(
            {
                "domain": SEMANTIC_GRAPH_IDENTITY_DOMAIN,
                "identity": dict(identity),
                "kind": kind,
                "namespace": namespace,
                "ontology_version": SEMANTIC_ONTOLOGY_VERSION,
            }
        )
    ).removeprefix("sha256:")
    return f"semantic:{namespace}:{kind}:{digest}"


def _canonical_ids(values: Any, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, tuple):
        raise SemanticGraphValidationError(
            f"{label} must be an immutable tuple"
        )
    for value in values:
        _validate_id(value, label)
    if len(set(values)) != len(values):
        raise SemanticGraphValidationError(
            f"{label} must not contain duplicates"
        )
    return tuple(sorted(values))


def _enum_value(enum_type: type[Enum], value: Any, label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise SemanticGraphValidationError(
            f"unknown {label}: {value!r}"
        ) from exc


def _validate_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise SemanticGraphValidationError(
            f"{label} is not a valid stable identifier"
        )


def _validate_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise SemanticGraphValidationError(
            f"{label} must be a lowercase sha256:<hex> digest"
        )


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise SemanticGraphValidationError(
            f"{label} must be non-empty normalized text"
        )
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticGraphValidationError("properties must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise SemanticGraphValidationError("property names must be strings")
    encoded = canonical_json_bytes(dict(value))
    if len(encoded) > _MAX_PROPERTY_BYTES:
        raise SemanticGraphValidationError(
            f"properties exceed {_MAX_PROPERTY_BYTES} canonical bytes"
        )
    _validate_property_strings(value)
    return _freeze(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SemanticGraphValidationError(
        f"graph properties must contain JSON values, not {type(value).__name__}"
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _validate_property_strings(value: Any) -> None:
    if isinstance(value, str):
        if len(value) > _MAX_PROPERTY_STRING_CHARS:
            raise SemanticGraphValidationError(
                "graph property string exceeds the bounded size"
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_property_strings(key)
            _validate_property_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_property_strings(item)


__all__ = [
    "INTENT_SEMANTIC_GRAPH_SCHEMA_VERSION",
    "INTENT_SEMANTIC_ONTOLOGY_VERSION",
    "IntentSemanticGraphProjector",
    "SEMANTIC_GRAPH_MEDIA_TYPE",
    "SEMANTIC_GRAPH_SCHEMA_VERSION",
    "SEMANTIC_INTENT_GRAPH_SCHEMA_VERSION",
    "SEMANTIC_INTENT_ONTOLOGY_VERSION",
    "SEMANTIC_ONTOLOGY",
    "SEMANTIC_ONTOLOGY_VERSION",
    "SemanticEdge",
    "SemanticEdgeClass",
    "SemanticEdgeKind",
    "SemanticEdgeType",
    "SemanticGraphArtifact",
    "SemanticGraphEdge",
    "SemanticGraphEdgeType",
    "SemanticGraphNode",
    "SemanticGraphNodeType",
    "SemanticGraphOntology",
    "SemanticGraphProjector",
    "SemanticGraphValidationError",
    "SemanticIntentGraph",
    "SemanticIntentGraphProjector",
    "SemanticNode",
    "SemanticNodeType",
    "SemanticProjectionError",
    "SemanticProjector",
    "semantic_graph_digest",
]
