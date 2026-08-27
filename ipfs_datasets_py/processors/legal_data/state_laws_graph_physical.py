"""Write state-law legal graphs with the shared HF GraphRAG layout.

This module bridges state-law graph rows to the domain-neutral,
query-compatible graph writers. It deliberately does not define a second
graph ontology or a second physical layout:

* state-law ``node_cid`` and ``edge_cid`` values are retained verbatim;
* legal graph edges and non-authoritative similarity edges remain disjoint;
* optional BM25 neighbors are resolved to section/subsection nodes without
  silently dropping an unmappable or ambiguous endpoint;
* BM25 vocabulary/posting parity is asserted and reported without expanding
  the virtual term-document graph into durable edges; and
* :func:`write_streaming_graph_layout` owns production node, edge, incoming
  adjacency, outgoing adjacency, and canonical routing-index Parquet files;
* the older full-projection/materialised path remains fixture-compatible but
  is explicitly nonproduction.

The writer is local-only.  It neither publishes nor contacts the Hub.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (
    CANDIDATE_ACCUMULATION_METHOD,
    EDGE_AUTHORITY,
    EDGE_CLASS_SIMILARITY,
    EDGE_PROOF_AUTHORITY,
    EDGE_TYPE_BM25_NEIGHBOR,
    VIRTUAL_TERM_DOCUMENT_EDGE_TYPE,
    Bm25NeighborEdge,
    StateLawsLexicalGraphOverlay,
)
from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (
    RETRIEVAL_METHOD as BM25_RETRIEVAL_METHOD,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    LEGAL_AUTHORITY,
    LEGAL_EDGE_TYPES,
    NON_AUTHORITATIVE_AUTHORITY,
    SIMILARITY_EDGE_TYPES,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjection,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import (
    GRAPH_EDGE_INDEX_PATH,
    GRAPH_IN_ADJACENCY_INDEX_PATH,
    GRAPH_NODE_INDEX_PATH,
    GRAPH_OUT_ADJACENCY_INDEX_PATH,
    MAX_ADJACENCY_POINTERS_PER_SHARD,
    GraphEdge,
    GraphLayoutWriteResult,
    GraphNode,
    graph_bounds_policy,
    validate_graph_layout,
    write_graph_layout,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_bm25 import (
    StreamingBM25Error,
    digest_sorted_bm25_term_statistics,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
    StreamingGraphWriteResult,
    write_streaming_graph_layout,
)

SCHEMA_VERSION: Final = "state-laws-graph-physical/v1"
PRODUCER: Final = "state_laws_graph_physical.py"
PHYSICAL_ROW_ENCODING: Final = "direct_parquet_columns"
LEGACY_OVERLAY_PRODUCTION_READY: Final = False
LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY: Final = False
STREAMING_GRAPH_WRITER_PRODUCTION_READY: Final = True
PHYSICAL_BM25_EVIDENCE_PRODUCTION_READY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

CANONICAL_GRAPH_INDEX_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_node_chunks": GRAPH_NODE_INDEX_PATH,
        "graph_edge_chunks": GRAPH_EDGE_INDEX_PATH,
        "graph_out_adjacency": GRAPH_OUT_ADJACENCY_INDEX_PATH,
        "graph_in_adjacency": GRAPH_IN_ADJACENCY_INDEX_PATH,
    }
)

_SECTION_NODE_TYPES: Final = frozenset(
    {GraphNodeType.SECTION, GraphNodeType.SUBSECTION}
)
_SIMILARITY_EDGE_VALUES: Final = frozenset(
    edge_type.value for edge_type in SIMILARITY_EDGE_TYPES
)
_LEGAL_EDGE_VALUES: Final = frozenset(edge_type.value for edge_type in LEGAL_EDGE_TYPES)
_STATE_EDGE_VALUES: Final = _LEGAL_EDGE_VALUES | _SIMILARITY_EDGE_VALUES
_NODE_TYPE_VALUES: Final = frozenset(node_type.value for node_type in GraphNodeType)


class StateLawsGraphPhysicalError(ValueError):
    """Base error for the state-law physical graph bridge."""


class GraphProjectionIdentityError(StateLawsGraphPhysicalError):
    """Raised when projection identities cannot be retained exactly."""


class Bm25VocabularyParityError(StateLawsGraphPhysicalError):
    """Raised when the lexical overlay diverges from its BM25 index."""


class Bm25EndpointResolutionError(StateLawsGraphPhysicalError):
    """Raised when a BM25 neighbor endpoint is absent or ambiguous."""


class Bm25SemanticPromotionError(StateLawsGraphPhysicalError):
    """Raised when a BM25 edge attempts to claim legal/proof authority."""


class DurableTermDocumentExpansionError(StateLawsGraphPhysicalError):
    """Raised when full durable term-document expansion is enabled."""


class GraphEdgeIdentityCollisionError(StateLawsGraphPhysicalError):
    """Raised when the same edge CID describes different durable edges."""


class MissingCanonicalGraphIndexError(StateLawsGraphPhysicalError):
    """Raised when a query-required graph routing index is not written."""


@runtime_checkable
class PhysicalBm25VocabularyEvidence(Protocol):
    """Narrow disk-backed BM25 evidence consumed by the production graph."""

    @property
    def production_ready(self) -> bool: ...

    def to_manifest_fragment(self) -> Mapping[str, Any]: ...

    def iter_vocabulary_document_frequencies(
        self,
    ) -> Iterable[tuple[str, int]]: ...


def _digest_sequence(values: Sequence[Any]) -> str:
    return content_sha256(canonical_json_dumps(list(values)))


@dataclass(frozen=True, slots=True)
class Bm25VocabularyParityProof:
    """Compact proof binding graph vocabulary to canonical BM25 postings.

    Production evidence is recomputed from disk-backed physical posting rows.
    The legacy overlay path remains available for fixtures and optional
    neighbors, but is explicitly non-production. No virtual term-document
    edge is copied into this proof or the durable graph.
    """

    enabled: bool
    term_count: int = 0
    document_count: int = 0
    term_document_pair_count: int = 0
    vocabulary_sha256: str = ""
    document_frequency_sha256: str = ""
    bm25_config_digest: str = ""
    index_root_cid: str = ""
    neighbor_edge_count: int = 0
    evidence_source: str = "none"
    production_ready: bool = False
    optional_neighbor_edges_source: str = "none"
    optional_neighbor_edges_production_ready: bool = True

    def to_dict(self) -> dict[str, Any]:
        physical = self.evidence_source == "streaming_physical_postings"
        return {
            "bm25_config_digest": self.bm25_config_digest,
            "bm25_document_frequencies_match_physical_postings_exactly": (
                self.enabled and physical
            ),
            "bm25_vocabulary_matches_physical_postings_exactly": (
                self.enabled and physical
            ),
            "bm25_vocabulary_matches_overlay_exactly": self.enabled,
            "document_count": self.document_count,
            "document_frequency_sha256": self.document_frequency_sha256,
            "durable_term_document_edge_count": 0,
            "full_term_document_expansion_performed": False,
            "index_root_cid": self.index_root_cid,
            "neighbor_edge_count": self.neighbor_edge_count,
            "evidence_source": self.evidence_source,
            "legacy_overlay_compatibility": (
                self.evidence_source == "legacy_in_memory_overlay"
            ),
            "optional_neighbor_edges_production_ready": (
                self.optional_neighbor_edges_production_ready
            ),
            "optional_neighbor_edges_source": self.optional_neighbor_edges_source,
            "postings_parity_asserted": self.enabled,
            "production_ready": self.production_ready,
            "term_count": self.term_count,
            "term_document_pair_count": self.term_document_pair_count,
            "term_document_edges_are_virtual": True,
            "vocabulary_sha256": self.vocabulary_sha256,
        }


def prove_physical_bm25_vocabulary_parity(
    evidence: PhysicalBm25VocabularyEvidence,
) -> Bm25VocabularyParityProof:
    """Recompute and verify disk-backed vocabulary/DF evidence in one pass."""

    if not isinstance(evidence, PhysicalBm25VocabularyEvidence):
        raise Bm25VocabularyParityError(
            "bm25 must implement the physical vocabulary evidence protocol"
        )
    if evidence.production_ready is not True:
        raise Bm25VocabularyParityError(
            "physical BM25 evidence is not marked production-ready"
        )
    fragment = evidence.to_manifest_fragment()
    if not isinstance(fragment, Mapping):
        raise Bm25VocabularyParityError("BM25 manifest fragment must be a mapping")
    bm25 = fragment.get("bm25")
    counts = fragment.get("counts")
    if not isinstance(bm25, Mapping) or not isinstance(counts, Mapping):
        raise Bm25VocabularyParityError(
            "physical BM25 evidence lacks bm25/counts mappings"
        )
    try:
        document_count = int(counts["bm25_documents"])
        expected_term_count = int(counts["bm25_terms"])
        expected_pair_count = int(counts["bm25_postings"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Bm25VocabularyParityError(
            "physical BM25 counts are absent or malformed"
        ) from exc
    if min(document_count, expected_term_count, expected_pair_count) < 1:
        raise Bm25VocabularyParityError("physical BM25 counts must be positive")

    config_digest = str(bm25.get("config_digest") or "").strip()
    index_root_cid = str(bm25.get("index_root_cid") or "").strip()
    vocabulary_sha256 = str(bm25.get("vocabulary_sha256") or "").strip()
    document_frequency_sha256 = str(bm25.get("document_frequency_sha256") or "").strip()
    if not all(
        (
            config_digest,
            index_root_cid,
            vocabulary_sha256,
            document_frequency_sha256,
        )
    ):
        raise Bm25VocabularyParityError(
            "physical BM25 root/config/vocabulary/DF evidence is incomplete"
        )
    physical_proof = bm25.get("physical_vocabulary_proof")
    if not isinstance(physical_proof, Mapping) or (
        physical_proof.get("posting_rows_are_lexicographic") is not True
        or physical_proof.get("vocabulary_sha256") != vocabulary_sha256
        or physical_proof.get("document_frequency_sha256") != document_frequency_sha256
        or not str(physical_proof.get("keyword_index_path") or "").strip()
        or not str(physical_proof.get("posting_glob") or "").strip()
    ):
        raise Bm25VocabularyParityError(
            "physical BM25 vocabulary proof metadata is incomplete or inconsistent"
        )

    def checked_rows() -> Iterable[tuple[str, int]]:
        for position, item in enumerate(
            evidence.iter_vocabulary_document_frequencies()
        ):
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise Bm25VocabularyParityError(
                    f"physical BM25 term row {position} must be a (term, df) pair"
                )
            term = str(item[0])
            try:
                document_frequency = int(item[1])
            except (TypeError, ValueError) as exc:
                raise Bm25VocabularyParityError(
                    f"physical BM25 DF at row {position} is malformed"
                ) from exc
            if document_frequency > document_count:
                raise Bm25VocabularyParityError(
                    f"physical BM25 DF exceeds document count for {term!r}"
                )
            yield term, document_frequency

    try:
        recomputed = digest_sorted_bm25_term_statistics(checked_rows())
    except (StreamingBM25Error, OSError, ValueError) as exc:
        raise Bm25VocabularyParityError(str(exc)) from exc
    if recomputed.term_count != expected_term_count:
        raise Bm25VocabularyParityError(
            "physical BM25 vocabulary count does not reconcile"
        )
    if recomputed.term_document_pair_count != expected_pair_count:
        raise Bm25VocabularyParityError(
            "physical BM25 term-document pair count does not reconcile"
        )
    if recomputed.vocabulary_sha256 != vocabulary_sha256:
        raise Bm25VocabularyParityError(
            "physical BM25 vocabulary digest does not reconcile"
        )
    if recomputed.document_frequency_sha256 != document_frequency_sha256:
        raise Bm25VocabularyParityError(
            "physical BM25 document-frequency digest does not reconcile"
        )
    return Bm25VocabularyParityProof(
        enabled=True,
        term_count=recomputed.term_count,
        document_count=document_count,
        term_document_pair_count=recomputed.term_document_pair_count,
        vocabulary_sha256=recomputed.vocabulary_sha256,
        document_frequency_sha256=recomputed.document_frequency_sha256,
        bm25_config_digest=config_digest,
        index_root_cid=index_root_cid,
        evidence_source="streaming_physical_postings",
        production_ready=True,
    )


def prove_bm25_vocabulary_parity(
    overlay: StateLawsLexicalGraphOverlay | None,
) -> Bm25VocabularyParityProof:
    """Compatibility proof over the legacy in-memory overlay/index stack."""

    if overlay is None:
        return Bm25VocabularyParityProof(enabled=False)
    if not isinstance(overlay, StateLawsLexicalGraphOverlay):
        raise Bm25VocabularyParityError(
            "overlay must be a StateLawsLexicalGraphOverlay"
        )
    if overlay.expands_full_term_document_edges:
        raise DurableTermDocumentExpansionError(
            "durable term-document expansion is forbidden for the physical "
            "state-law graph; use canonical BM25 postings for virtual traversal"
        )

    try:
        overlay.assert_bm25_parity()
    except Exception as exc:
        raise Bm25VocabularyParityError(str(exc)) from exc

    bm25_rows = sorted(
        (
            term_row.term,
            int(term_row.document_frequency),
        )
        for shard in overlay.index.term_shards
        for term_row in shard.terms
    )
    bm25_vocabulary = tuple(term for term, _ in bm25_rows)
    overlay_vocabulary = tuple(sorted(overlay.vocabulary))
    if bm25_vocabulary != overlay_vocabulary:
        raise Bm25VocabularyParityError(
            "overlay vocabulary ordering/content diverges from BM25 term shards"
        )

    overlay_df = tuple(
        sorted(
            (term, int(posting.document_frequency))
            for term, posting in overlay.postings.items()
        )
    )
    bm25_df = tuple(bm25_rows)
    if bm25_df != overlay_df:
        raise Bm25VocabularyParityError(
            "overlay document frequencies diverge from BM25 term shards"
        )

    vocabulary_digest = _digest_sequence(bm25_vocabulary)
    overlay_vocabulary_digest = _digest_sequence(overlay_vocabulary)
    if vocabulary_digest != overlay_vocabulary_digest:  # defensive
        raise Bm25VocabularyParityError("BM25 vocabulary digests diverged")

    return Bm25VocabularyParityProof(
        enabled=True,
        term_count=len(bm25_vocabulary),
        document_count=overlay.document_count,
        term_document_pair_count=overlay.term_document_pair_count,
        vocabulary_sha256=vocabulary_digest,
        document_frequency_sha256=_digest_sequence(bm25_df),
        bm25_config_digest=overlay.bm25_config_digest,
        index_root_cid=overlay.index.index_root_cid,
        neighbor_edge_count=overlay.neighbor_edge_count,
        evidence_source="legacy_in_memory_overlay",
        production_ready=LEGACY_OVERLAY_PRODUCTION_READY,
        optional_neighbor_edges_source=(
            "legacy_in_memory_overlay" if overlay.neighbor_edge_count else "none"
        ),
        optional_neighbor_edges_production_ready=(overlay.neighbor_edge_count == 0),
    )


def _select_bm25_vocabulary_proof(
    *,
    bm25: PhysicalBm25VocabularyEvidence | None,
    overlay: StateLawsLexicalGraphOverlay | None,
) -> Bm25VocabularyParityProof:
    if bm25 is None:
        return prove_bm25_vocabulary_parity(overlay)
    physical = prove_physical_bm25_vocabulary_parity(bm25)
    if overlay is None:
        return physical
    legacy = prove_bm25_vocabulary_parity(overlay)
    comparable = (
        "term_count",
        "document_count",
        "term_document_pair_count",
        "vocabulary_sha256",
        "document_frequency_sha256",
        "bm25_config_digest",
    )
    drift = [
        name for name in comparable if getattr(physical, name) != getattr(legacy, name)
    ]
    if drift:
        raise Bm25VocabularyParityError(
            "optional legacy neighbor overlay diverges from physical BM25 "
            f"evidence: {drift}"
        )
    return replace(
        physical,
        neighbor_edge_count=legacy.neighbor_edge_count,
        optional_neighbor_edges_source=(
            "legacy_in_memory_overlay" if legacy.neighbor_edge_count else "none"
        ),
        optional_neighbor_edges_production_ready=(legacy.neighbor_edge_count == 0),
    )


def _projection_node_to_shared(node: StateLawsGraphNode) -> GraphNode:
    properties = dict(node.payload)
    properties.update(
        {
            "legal_id": node.legal_id,
            "node_key": node.node_key,
            "ontology_version": node.ontology_version,
            "source_schema_version": node.schema_version,
        }
    )
    return GraphNode(
        node_cid=node.node_cid,
        node_type=node.node_type.value,
        label=node.label,
        entry_cid=node.entry_cid,
        properties=properties,
    )


def _projection_edge_retrieval_method(edge: StateLawsGraphEdge) -> str:
    if edge.edge_type is GraphEdgeType.BM25_NEIGHBOR_OF:
        return BM25_RETRIEVAL_METHOD
    if edge.is_similarity:
        metric = str(edge.payload.get("metric") or "similarity").strip().lower()
        return f"{metric}-similarity"
    return f"legal-graph-{edge.edge_class.value}"


def _projection_edge_to_shared(edge: StateLawsGraphEdge) -> GraphEdge:
    if edge.is_similarity:
        claimed_authority = edge.payload.get("authority")
        if claimed_authority != NON_AUTHORITATIVE_AUTHORITY:
            raise Bm25SemanticPromotionError(
                f"similarity edge {edge.edge_cid} lacks non-authoritative semantics"
            )
        if edge.payload.get("proof_authority") is True:
            raise Bm25SemanticPromotionError(
                f"similarity edge {edge.edge_cid} claims proof authority"
            )
        authority = NON_AUTHORITATIVE_AUTHORITY
        legal_authority = False
    else:
        authority = LEGAL_AUTHORITY
        legal_authority = True

    properties = dict(edge.payload)
    properties.update(
        {
            "authority": authority,
            "edge_class": edge.edge_class.value,
            "legal_authority": legal_authority,
            "ontology_version": edge.ontology_version,
            "proof_authority": False if edge.is_similarity else None,
            "resolution_status": (
                edge.resolution_status.value if edge.resolution_status else None
            ),
            "source_schema_version": edge.schema_version,
            "source_span": edge.source_span.to_dict() if edge.source_span else None,
        }
    )
    return GraphEdge(
        edge_cid=edge.edge_cid,
        edge_type=edge.edge_type.value,
        source_node_cid=edge.source_node_cid,
        target_node_cid=edge.target_node_cid,
        score=edge.weight,
        retrieval_method=_projection_edge_retrieval_method(edge),
        properties=properties,
    )


@dataclass(slots=True)
class _StreamingStateGraphMetrics:
    node_count: int = 0
    edge_count: int = 0
    legal_edge_count: int = 0
    non_authoritative_edge_count: int = 0


def _mapping_node_to_shared(row: Mapping[str, Any], position: int) -> GraphNode:
    properties = row.get("properties") or row.get("payload") or {}
    if not isinstance(properties, Mapping):
        raise GraphProjectionIdentityError(
            f"nodes[{position}].properties must be a mapping"
        )
    node_type = row.get("node_type") or row.get("type") or ""
    if isinstance(node_type, GraphNodeType):
        node_type = node_type.value
    return GraphNode(
        node_cid=str(row.get("node_cid") or row.get("cid") or row.get("id") or ""),
        node_type=str(node_type),
        label=row.get("label"),
        entry_cid=row.get("entry_cid"),
        properties=dict(properties),
    )


def _mapping_edge_to_shared(row: Mapping[str, Any], position: int) -> GraphEdge:
    properties = row.get("properties") or row.get("payload") or {}
    if not isinstance(properties, Mapping):
        raise GraphProjectionIdentityError(
            f"edges[{position}].properties must be a mapping"
        )
    edge_type = row.get("edge_type") or row.get("type") or ""
    if isinstance(edge_type, GraphEdgeType):
        edge_type = edge_type.value
    return GraphEdge(
        edge_cid=str(row.get("edge_cid") or row.get("cid") or row.get("id") or ""),
        edge_type=str(edge_type),
        source_node_cid=str(
            row.get("source_node_cid")
            or row.get("source_cid")
            or row.get("source")
            or ""
        ),
        target_node_cid=str(
            row.get("target_node_cid")
            or row.get("target_cid")
            or row.get("target")
            or ""
        ),
        score=row.get("score", row.get("weight")),
        retrieval_method=str(row.get("retrieval_method") or "structural"),
        properties=dict(properties),
    )


def _validate_streaming_state_edge(
    edge: GraphEdge,
    *,
    metrics: _StreamingStateGraphMetrics,
) -> GraphEdge:
    if edge.edge_type == VIRTUAL_TERM_DOCUMENT_EDGE_TYPE:
        raise DurableTermDocumentExpansionError(
            "virtual BM25 term-document relationships must remain in postings"
        )
    if edge.edge_type not in _STATE_EDGE_VALUES:
        raise GraphProjectionIdentityError(
            f"edge {edge.edge_cid} uses an unknown state-law edge type"
        )
    properties = edge.properties
    is_similarity = edge.edge_type in _SIMILARITY_EDGE_VALUES
    claimed_similarity = properties.get("edge_class") == GraphEdgeClass.SIMILARITY.value
    if is_similarity != claimed_similarity and properties.get("edge_class") is not None:
        raise Bm25SemanticPromotionError(
            f"edge {edge.edge_cid} mixes legal and similarity classifications"
        )
    if is_similarity:
        if (
            properties.get("authority") != NON_AUTHORITATIVE_AUTHORITY
            or properties.get("legal_authority") is not False
            or properties.get("proof_authority") is not False
        ):
            raise Bm25SemanticPromotionError(
                f"similarity edge {edge.edge_cid} lacks non-authoritative semantics"
            )
        if (
            edge.edge_type == GraphEdgeType.BM25_NEIGHBOR_OF.value
            and edge.retrieval_method != BM25_RETRIEVAL_METHOD
        ):
            raise Bm25SemanticPromotionError(
                f"BM25 edge {edge.edge_cid} lacks the canonical retrieval method"
            )
        metrics.non_authoritative_edge_count += 1
    else:
        if (
            properties.get("authority") == NON_AUTHORITATIVE_AUTHORITY
            or properties.get("legal_authority") is False
        ):
            raise Bm25SemanticPromotionError(
                f"legal edge {edge.edge_cid} claims non-authoritative semantics"
            )
        metrics.legal_edge_count += 1
    metrics.edge_count += 1
    return edge


def _iter_streaming_state_nodes(
    nodes: Iterable[StateLawsGraphNode | GraphNode | Mapping[str, Any]],
    metrics: _StreamingStateGraphMetrics,
) -> Iterator[GraphNode]:
    for position, source in enumerate(nodes):
        if isinstance(source, StateLawsGraphNode):
            node = _projection_node_to_shared(source)
        elif isinstance(source, GraphNode):
            node = source
        elif isinstance(source, Mapping):
            node = _mapping_node_to_shared(source, position)
        else:
            raise GraphProjectionIdentityError(
                f"nodes[{position}] must be a state/shared graph node or mapping"
            )
        if node.node_type not in _NODE_TYPE_VALUES:
            raise GraphProjectionIdentityError(
                f"node {node.node_cid} uses an unknown state-law node type"
            )
        metrics.node_count += 1
        yield node


def _iter_streaming_state_edges(
    edges: Iterable[StateLawsGraphEdge | GraphEdge | Mapping[str, Any]],
    metrics: _StreamingStateGraphMetrics,
) -> Iterator[GraphEdge]:
    for position, source in enumerate(edges):
        if isinstance(source, StateLawsGraphEdge):
            edge = _projection_edge_to_shared(source)
        elif isinstance(source, GraphEdge):
            edge = source
        elif isinstance(source, Mapping):
            edge = _mapping_edge_to_shared(source, position)
        else:
            raise GraphProjectionIdentityError(
                f"edges[{position}] must be a state/shared graph edge or mapping"
            )
        yield _validate_streaming_state_edge(edge, metrics=metrics)


def _section_node_indexes(
    projection: StateLawsGraphProjection,
) -> tuple[
    Mapping[str, tuple[StateLawsGraphNode, ...]],
    Mapping[str, tuple[StateLawsGraphNode, ...]],
]:
    by_legal: dict[str, list[StateLawsGraphNode]] = defaultdict(list)
    by_entry: dict[str, list[StateLawsGraphNode]] = defaultdict(list)
    for node in projection.nodes:
        if node.node_type not in _SECTION_NODE_TYPES:
            continue
        if node.legal_id:
            by_legal[node.legal_id].append(node)
        if node.entry_cid:
            by_entry[node.entry_cid].append(node)
    return (
        MappingProxyType({key: tuple(value) for key, value in by_legal.items()}),
        MappingProxyType({key: tuple(value) for key, value in by_entry.items()}),
    )


def _overlay_document_index(
    overlay: StateLawsLexicalGraphOverlay,
) -> Mapping[str, tuple[Any, ...]]:
    documents: dict[str, list[Any]] = defaultdict(list)
    for document in overlay.index.documents:
        for identity in {document.entry_cid, document.chunk_cid}:
            documents[identity].append(document)
    return MappingProxyType({key: tuple(value) for key, value in documents.items()})


def _single_overlay_document(
    document_index: Mapping[str, tuple[Any, ...]],
    entry_cid: str,
    *,
    endpoint_name: str,
) -> Any:
    candidates = document_index.get(entry_cid, ())
    unique = {item.entry_cid: item for item in candidates}
    if len(unique) != 1:
        raise Bm25EndpointResolutionError(
            f"{endpoint_name} BM25 identity {entry_cid!r} resolves to "
            f"{len(unique)} documents"
        )
    return next(iter(unique.values()))


def _resolve_neighbor_endpoint(
    *,
    endpoint_name: str,
    entry_cid: str,
    chunk_cid: str | None,
    legal_id: str | None,
    by_legal: Mapping[str, tuple[StateLawsGraphNode, ...]],
    by_entry: Mapping[str, tuple[StateLawsGraphNode, ...]],
    document_index: Mapping[str, tuple[Any, ...]],
) -> StateLawsGraphNode:
    document = _single_overlay_document(
        document_index, entry_cid, endpoint_name=endpoint_name
    )
    legal_keys = {
        value
        for value in (legal_id, document.legal_id)
        if isinstance(value, str) and value.strip()
    }
    entry_keys = {
        value
        for value in (
            entry_cid,
            chunk_cid,
            document.entry_cid,
            document.chunk_cid,
            document.parent_entry_cid,
        )
        if isinstance(value, str) and value.strip()
    }

    resolved: dict[str, StateLawsGraphNode] = {}
    evidence_sets: list[set[str]] = []
    evidence: list[str] = []
    for namespace, keys, index in (
        ("legal_id", legal_keys, by_legal),
        ("entry_cid", entry_keys, by_entry),
    ):
        for key in sorted(keys):
            matches = index.get(key, ())
            if matches:
                match_cids = {match.node_cid for match in matches}
                evidence_sets.append(match_cids)
                for match in matches:
                    resolved[match.node_cid] = match
                evidence.append(f"{namespace}={key}")

    if not evidence_sets:
        raise Bm25EndpointResolutionError(
            f"{endpoint_name} BM25 neighbor endpoint {entry_cid!r} does not "
            "resolve to a section/subsection node"
        )
    possible = set(evidence_sets[0])
    for candidates in evidence_sets[1:]:
        possible.intersection_update(candidates)
    if len(possible) != 1:
        raise Bm25EndpointResolutionError(
            f"{endpoint_name} endpoint evidence disagrees across graph nodes; "
            f"evidence={evidence!r} candidate_node_cids={sorted(possible)!r}"
        )
    return resolved[next(iter(possible))]


def _neighbor_edge_to_shared(
    neighbor: Bm25NeighborEdge,
    *,
    by_legal: Mapping[str, tuple[StateLawsGraphNode, ...]],
    by_entry: Mapping[str, tuple[StateLawsGraphNode, ...]],
    document_index: Mapping[str, tuple[Any, ...]],
) -> GraphEdge:
    if (
        neighbor.edge_type != EDGE_TYPE_BM25_NEIGHBOR
        or neighbor.edge_class != EDGE_CLASS_SIMILARITY
        or neighbor.authority != EDGE_AUTHORITY
        or neighbor.proof_authority is not EDGE_PROOF_AUTHORITY
        or neighbor.candidate_accumulation != CANDIDATE_ACCUMULATION_METHOD
    ):
        raise Bm25SemanticPromotionError(
            f"BM25 neighbor {neighbor.edge_cid} violates non-authoritative "
            "postings-driven semantics"
        )

    source = _resolve_neighbor_endpoint(
        endpoint_name="source",
        entry_cid=neighbor.source_entry_cid,
        chunk_cid=neighbor.source_chunk_cid,
        legal_id=neighbor.source_legal_id,
        by_legal=by_legal,
        by_entry=by_entry,
        document_index=document_index,
    )
    target = _resolve_neighbor_endpoint(
        endpoint_name="target",
        entry_cid=neighbor.target_entry_cid,
        chunk_cid=neighbor.target_chunk_cid,
        legal_id=neighbor.target_legal_id,
        by_legal=by_legal,
        by_entry=by_entry,
        document_index=document_index,
    )
    if source.node_cid == target.node_cid:
        raise Bm25EndpointResolutionError(
            f"BM25 neighbor {neighbor.edge_cid} collapses to a graph self-loop"
        )

    properties = neighbor.to_dict()
    properties.update(
        {
            "authority": NON_AUTHORITATIVE_AUTHORITY,
            "edge_class": EDGE_CLASS_SIMILARITY,
            "legal_authority": False,
            "proof_authority": False,
            "retrieval_hint": True,
        }
    )
    return GraphEdge(
        edge_cid=neighbor.edge_cid,
        edge_type=neighbor.edge_type,
        source_node_cid=source.node_cid,
        target_node_cid=target.node_cid,
        score=neighbor.score,
        retrieval_method=neighbor.retrieval_method,
        properties=properties,
    )


def _durable_edge_identity(edge: GraphEdge) -> tuple[Any, ...]:
    return (
        edge.edge_cid,
        edge.edge_type,
        edge.source_node_cid,
        edge.target_node_cid,
        edge.score,
    )


@dataclass(frozen=True, slots=True)
class StateLawsPhysicalGraph:
    """Query-writer inputs plus state-law identity and parity evidence."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    projection_graph_cid: str
    projection_node_cids: tuple[str, ...]
    projection_edge_cids: tuple[str, ...]
    overlay_neighbor_edge_cids: tuple[str, ...]
    legal_edge_cids: tuple[str, ...]
    non_authoritative_edge_cids: tuple[str, ...]
    reused_overlay_edge_count: int
    vocabulary_parity: Bm25VocabularyParityProof

    def __post_init__(self) -> None:
        node_cids = {node.node_cid for node in self.nodes}
        edge_cids = {edge.edge_cid for edge in self.edges}
        if node_cids != set(self.projection_node_cids):
            raise GraphProjectionIdentityError(
                "shared graph node identities diverge from the projection"
            )
        expected_edge_cids = set(self.projection_edge_cids) | set(
            self.overlay_neighbor_edge_cids
        )
        if edge_cids != expected_edge_cids:
            raise GraphProjectionIdentityError(
                "shared graph edge identities diverge from projection/overlay"
            )
        if set(self.legal_edge_cids) & set(self.non_authoritative_edge_cids):
            raise Bm25SemanticPromotionError(
                "a durable edge is both legal and non-authoritative"
            )

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def report(self) -> dict[str, Any]:
        non_authoritative = set(self.non_authoritative_edge_cids)
        return {
            "bounds": graph_bounds_policy(),
            "checks": {
                "bm25_physical_vocabulary_proof": (
                    self.vocabulary_parity.production_ready
                ),
                "bm25_neighbors_non_authoritative": all(
                    edge.properties.get("authority") == NON_AUTHORITATIVE_AUTHORITY
                    and edge.properties.get("legal_authority") is False
                    and edge.properties.get("proof_authority") is False
                    for edge in self.edges
                    if edge.edge_cid in non_authoritative
                ),
                "direct_parquet_columns": True,
                "edge_identities_exact": True,
                "endpoint_integrity": True,
                "node_identities_exact": True,
                "optional_bm25_neighbors_production_ready": (
                    self.vocabulary_parity.optional_neighbor_edges_production_ready
                ),
                "term_document_edges_not_materialized": True,
                "two_way_adjacency_required": True,
            },
            "edge_count": self.edge_count,
            "legal_edge_count": len(self.legal_edge_cids),
            "non_authoritative_edge_count": len(self.non_authoritative_edge_cids),
            "node_count": self.node_count,
            "physical_row_encoding": PHYSICAL_ROW_ENCODING,
            "producer": PRODUCER,
            "projection_graph_cid": self.projection_graph_cid,
            "reused_overlay_edge_count": self.reused_overlay_edge_count,
            "schema_version": SCHEMA_VERSION,
            "vocabulary_parity": self.vocabulary_parity.to_dict(),
        }


def adapt_state_laws_graph_projection(
    projection: StateLawsGraphProjection,
    *,
    bm25: PhysicalBm25VocabularyEvidence | None = None,
    overlay: StateLawsLexicalGraphOverlay | None = None,
) -> StateLawsPhysicalGraph:
    """Convert a projection using physical BM25 proof and optional neighbors.

    Every source identity is retained verbatim.  Unlike the older adjacency
    helper, this bridge fails closed instead of skipping an unmappable BM25
    endpoint, because silent loss would make graph/adjacency counts diverge.
    """

    if not isinstance(projection, StateLawsGraphProjection):
        raise GraphProjectionIdentityError(
            "projection must be a StateLawsGraphProjection"
        )
    if not projection.uniqueness_ok():
        raise GraphProjectionIdentityError(
            "projection node/edge identities are not unique"
        )
    if not projection.referential_integrity_ok():
        raise GraphProjectionIdentityError("projection contains dangling edges")
    projection.assert_semantics_disjoint()

    vocabulary_parity = _select_bm25_vocabulary_proof(
        bm25=bm25,
        overlay=overlay,
    )
    nodes = tuple(_projection_node_to_shared(node) for node in projection.nodes)
    node_cids = {node.node_cid for node in nodes}

    edge_by_cid: dict[str, GraphEdge] = {}
    legal_edge_cids: set[str] = set()
    non_authoritative_edge_cids: set[str] = set()
    for source_edge in projection.edges:
        edge = _projection_edge_to_shared(source_edge)
        if (
            edge.source_node_cid not in node_cids
            or edge.target_node_cid not in node_cids
        ):
            raise GraphProjectionIdentityError(
                f"projection edge {edge.edge_cid} has a dangling endpoint"
            )
        edge_by_cid[edge.edge_cid] = edge
        if source_edge.is_similarity:
            non_authoritative_edge_cids.add(edge.edge_cid)
        else:
            legal_edge_cids.add(edge.edge_cid)

    overlay_edge_cids: list[str] = []
    reused_overlay_edges = 0
    if overlay is not None:
        by_legal, by_entry = _section_node_indexes(projection)
        document_index = _overlay_document_index(overlay)
        seen_overlay: set[str] = set()
        for neighbor in overlay.neighbor_edges:
            if neighbor.edge_cid in seen_overlay:
                raise GraphEdgeIdentityCollisionError(
                    f"duplicate BM25 neighbor edge CID {neighbor.edge_cid}"
                )
            seen_overlay.add(neighbor.edge_cid)
            edge = _neighbor_edge_to_shared(
                neighbor,
                by_legal=by_legal,
                by_entry=by_entry,
                document_index=document_index,
            )
            existing = edge_by_cid.get(edge.edge_cid)
            if existing is not None:
                if _durable_edge_identity(existing) != _durable_edge_identity(edge):
                    raise GraphEdgeIdentityCollisionError(
                        f"edge CID {edge.edge_cid} identifies different projection "
                        "and BM25 edges"
                    )
                if existing.properties.get("authority") != NON_AUTHORITATIVE_AUTHORITY:
                    raise Bm25SemanticPromotionError(
                        f"reused BM25 edge {edge.edge_cid} is not non-authoritative"
                    )
                reused_overlay_edges += 1
            else:
                edge_by_cid[edge.edge_cid] = edge
            overlay_edge_cids.append(edge.edge_cid)
            non_authoritative_edge_cids.add(edge.edge_cid)

    ordered_nodes = tuple(sorted(nodes, key=lambda item: item.node_cid))
    ordered_edges = tuple(sorted(edge_by_cid.values(), key=lambda item: item.edge_cid))
    return StateLawsPhysicalGraph(
        nodes=ordered_nodes,
        edges=ordered_edges,
        projection_graph_cid=projection.graph_cid,
        projection_node_cids=tuple(node.node_cid for node in projection.nodes),
        projection_edge_cids=tuple(edge.edge_cid for edge in projection.edges),
        overlay_neighbor_edge_cids=tuple(overlay_edge_cids),
        legal_edge_cids=tuple(sorted(legal_edge_cids)),
        non_authoritative_edge_cids=tuple(sorted(non_authoritative_edge_cids)),
        reused_overlay_edge_count=reused_overlay_edges,
        vocabulary_parity=vocabulary_parity,
    )


@dataclass(frozen=True, slots=True)
class StateLawsStreamingGraphPhysicalWriteResult:
    """Production state-law wrapper around the shared streaming graph result."""

    physical: StreamingGraphWriteResult
    vocabulary_parity: Bm25VocabularyParityProof
    legal_edge_count: int
    non_authoritative_edge_count: int

    @property
    def production_ready(self) -> bool:
        proof = self.vocabulary_parity
        return (
            STREAMING_GRAPH_WRITER_PRODUCTION_READY
            and self.physical.production_ready
            and proof.enabled
            and proof.production_ready
            and proof.evidence_source == "streaming_physical_postings"
            and proof.neighbor_edge_count == 0
            and proof.optional_neighbor_edges_source == "none"
            and proof.optional_neighbor_edges_production_ready
            and self.legal_edge_count + self.non_authoritative_edge_count
            == self.physical.counts["edges"]
        )

    @property
    def key_evidence(self) -> dict[str, Iterable[str]]:
        """Replay parent/source graph keys from verified node Parquet shards."""

        return self.physical.key_evidence

    @property
    def counts(self) -> Mapping[str, int]:
        return self.physical.counts

    def graph_report(self) -> dict[str, Any]:
        proof = self.vocabulary_parity.to_dict()
        shared = self.physical.graph_report()
        shared_checks = shared["checks"]
        physical_vocabulary_ok = (
            self.vocabulary_parity.enabled
            and self.vocabulary_parity.production_ready
            and self.vocabulary_parity.evidence_source == "streaming_physical_postings"
        )
        neighbor_semantics_ok = (
            self.legal_edge_count + self.non_authoritative_edge_count
            == self.physical.counts["edges"]
        )
        optional_neighbors_ok = (
            self.vocabulary_parity.neighbor_edge_count == 0
            and self.vocabulary_parity.optional_neighbor_edges_source == "none"
            and self.vocabulary_parity.optional_neighbor_edges_production_ready
        )
        shared.update(
            {
                "bounds": graph_bounds_policy(),
                "checks": {
                    "bm25_physical_vocabulary_proof": physical_vocabulary_ok,
                    "bm25_neighbors_non_authoritative": neighbor_semantics_ok,
                    "direct_parquet_columns": shared_checks["direct_parquet_columns"],
                    "edge_identities_exact": shared_checks["edge_identities_exact"],
                    "endpoint_integrity": shared_checks["endpoint_integrity"],
                    "node_identities_exact": shared_checks["node_identities_exact"],
                    "optional_bm25_neighbors_production_ready": (optional_neighbors_ok),
                    "term_document_edges_not_materialized": shared_checks[
                        "term_document_edges_not_materialized"
                    ],
                    "two_way_adjacency_required": shared_checks[
                        "two_way_adjacency_required"
                    ],
                },
                "legal_edge_count": self.legal_edge_count,
                "non_authoritative_edge_count": self.non_authoritative_edge_count,
                "physical_row_encoding": PHYSICAL_ROW_ENCODING,
                "producer": PRODUCER,
                "schema_version": SCHEMA_VERSION,
                "streaming_production_path": True,
                "vocabulary_parity": proof,
            }
        )
        return shared

    def manifest_fragment(self) -> dict[str, Any]:
        fragment = self.physical.manifest_fragment()
        fragment.update(
            {
                "graph": self.graph_report(),
                "production_ready": self.production_ready,
                "state_schema_version": SCHEMA_VERSION,
            }
        )
        return fragment

    def verify(self) -> None:
        self.physical.verify()
        if not self.production_ready:
            raise StateLawsGraphPhysicalError(
                "streaming state-law graph failed its production closure"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph": self.graph_report(),
            "manifest_fragment": self.manifest_fragment(),
            "physical": self.physical.to_dict(),
            "production_ready": self.production_ready,
        }


def write_state_laws_streaming_graph_layout(
    nodes: Iterable[StateLawsGraphNode | GraphNode | Mapping[str, Any]],
    edges: Iterable[StateLawsGraphEdge | GraphEdge | Mapping[str, Any]],
    output_root: str | Path,
    *,
    bm25: PhysicalBm25VocabularyEvidence,
    config: StreamingGraphConfig | None = None,
) -> StateLawsStreamingGraphPhysicalWriteResult:
    """Write a production graph from one-shot state/shared row streams.

    Physical BM25 vocabulary and document-frequency evidence is recomputed
    exactly once. Only the resulting compact proof mapping crosses into the
    shared graph writer; vocabulary terms and postings are never expanded into
    graph edges.
    """

    vocabulary_parity = prove_physical_bm25_vocabulary_parity(bm25)
    compact_vocabulary_proof = vocabulary_parity.to_dict()
    metrics = _StreamingStateGraphMetrics()
    physical = write_streaming_graph_layout(
        _iter_streaming_state_nodes(nodes, metrics),
        _iter_streaming_state_edges(edges, metrics),
        output_root,
        config=config,
        bm25_vocabulary_proof=compact_vocabulary_proof,
    )
    if metrics.node_count != physical.counts["nodes"]:
        raise GraphProjectionIdentityError(
            "streaming state/shared node count diverges from physical graph"
        )
    if metrics.edge_count != physical.counts["edges"]:
        raise GraphProjectionIdentityError(
            "streaming state/shared edge count diverges from physical graph"
        )
    result = StateLawsStreamingGraphPhysicalWriteResult(
        physical=physical,
        vocabulary_parity=vocabulary_parity,
        legal_edge_count=metrics.legal_edge_count,
        non_authoritative_edge_count=metrics.non_authoritative_edge_count,
    )
    result.verify()
    # Force the exact state/local-release graph surface before returning.
    result.manifest_fragment()
    return result


@dataclass(frozen=True, slots=True)
class StateLawsGraphPhysicalWriteResult:
    """Legacy materialised state-law graph result (compatibility only)."""

    graph: StateLawsPhysicalGraph
    physical: GraphLayoutWriteResult

    @property
    def layout(self) -> Any:
        return self.physical.layout

    @property
    def production_ready(self) -> bool:
        """Materialising the full graph is never a production-scale path."""

        return LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY

    def manifest_fragment(self) -> dict[str, Any]:
        indexes: dict[str, dict[str, Any]] = {}
        for name, expected_path in CANONICAL_GRAPH_INDEX_PATHS.items():
            descriptor = self.physical.index_descriptors.get(name)
            if descriptor is None:
                raise MissingCanonicalGraphIndexError(
                    f"query-required graph index {name!r} is absent"
                )
            payload = (
                descriptor.to_dict()
                if hasattr(descriptor, "to_dict")
                else dict(descriptor)
            )
            if payload.get("relative_path") != expected_path:
                raise MissingCanonicalGraphIndexError(
                    f"graph index {name!r} path drifted from {expected_path!r}"
                )
            indexes[name] = payload
        return {
            "artifacts": [
                descriptor.to_dict()
                if hasattr(descriptor, "to_dict")
                else dict(descriptor)
                for descriptor in self.physical.data_descriptors
            ],
            "graph": self.graph.report(),
            "indexes": indexes,
            "legacy_materialized": True,
            "production_ready": self.production_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph": self.graph.report(),
            "manifest_fragment": self.manifest_fragment(),
            "physical": self.physical.to_dict(),
            "production_ready": self.production_ready,
        }


def write_state_laws_graph_layout(
    projection: StateLawsGraphProjection,
    output_root: str | Path,
    *,
    bm25: PhysicalBm25VocabularyEvidence | None = None,
    overlay: StateLawsLexicalGraphOverlay | None = None,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW,
    max_pointers_per_shard: int = MAX_ADJACENCY_POINTERS_PER_SHARD,
) -> StateLawsGraphPhysicalWriteResult:
    """Write the legacy materialised compatibility layout (nonproduction)."""

    graph = adapt_state_laws_graph_projection(
        projection,
        bm25=bm25,
        overlay=overlay,
    )
    if not graph.edges:
        raise MissingCanonicalGraphIndexError(
            "query-compatible graph output requires at least one durable edge "
            "so edge and two-way adjacency indexes are non-empty"
        )
    physical = write_graph_layout(
        graph.nodes,
        graph.edges,
        output_root,
        max_rows_per_shard=max_rows_per_shard,
        max_pointers_per_page=max_pointers_per_page,
        max_pointers_per_shard=max_pointers_per_shard,
        write_indexes=True,
    )
    validate_graph_layout(physical.layout)

    if set(physical.layout.all_node_cids()) != set(graph.projection_node_cids):
        raise GraphProjectionIdentityError(
            "physical layout changed projection node identities"
        )
    expected_edges = set(graph.projection_edge_cids) | set(
        graph.overlay_neighbor_edge_cids
    )
    if set(physical.layout.all_edge_cids()) != expected_edges:
        raise GraphProjectionIdentityError(
            "physical layout changed projection/overlay edge identities"
        )

    result = StateLawsGraphPhysicalWriteResult(graph=graph, physical=physical)
    # Force canonical index closure before returning a purportedly
    # query-compatible result.
    result.manifest_fragment()
    return result


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "BM25_RETRIEVAL_METHOD",
    "CANONICAL_GRAPH_INDEX_PATHS",
    "LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY",
    "LEGACY_OVERLAY_PRODUCTION_READY",
    "PERFORMS_NETWORK_IO",
    "PHYSICAL_BM25_EVIDENCE_PRODUCTION_READY",
    "PHYSICAL_ROW_ENCODING",
    "PRODUCER",
    "SCHEMA_VERSION",
    "STREAMING_GRAPH_WRITER_PRODUCTION_READY",
    "Bm25EndpointResolutionError",
    "Bm25SemanticPromotionError",
    "Bm25VocabularyParityError",
    "Bm25VocabularyParityProof",
    "DurableTermDocumentExpansionError",
    "GraphEdgeIdentityCollisionError",
    "GraphProjectionIdentityError",
    "MissingCanonicalGraphIndexError",
    "PhysicalBm25VocabularyEvidence",
    "StateLawsGraphPhysicalError",
    "StateLawsGraphPhysicalWriteResult",
    "StateLawsPhysicalGraph",
    "StateLawsStreamingGraphPhysicalWriteResult",
    "adapt_state_laws_graph_projection",
    "prove_bm25_vocabulary_parity",
    "prove_physical_bm25_vocabulary_parity",
    "write_state_laws_graph_layout",
    "write_state_laws_streaming_graph_layout",
]
