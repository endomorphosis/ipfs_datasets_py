"""Bounded immutable-Hub state-law queries (LCR-033).

Domain adapter over the generic remote GraphRAG substrate:

* :mod:`ipfs_datasets_py.retrieval.hf_graphrag.remote_search` for public
  BM25 (lexicographic term-range routes only) and dense retrieval
  (evaluated-centroid probes plus exact shard scoring);
* :mod:`ipfs_datasets_py.retrieval.hf_graphrag.query` for budgets,
  adjacency, and structural walks;
* :mod:`ipfs_datasets_py.processors.legal_data.state_laws_graph` (LCR-030)
  for legal vs similarity edge authority;
* :mod:`ipfs_datasets_py.processors.legal_data.state_laws_vectors` (LCR-029)
  for the dedicated ``entry_cid`` locator used by graph-frontier hydration;
* :mod:`ipfs_datasets_py.processors.legal_data.state_laws_bm25` (LCR-027)
  and :mod:`state_laws_adjacency` (LCR-031) as read-only identity/authority
  pins;
* :mod:`ipfs_datasets_py.processors.legal_data.state_laws_hf_release`
  (LCR-032) as the descriptor-complete mini-release source (read-only).

Public operations
-----------------
* ``bm25_search`` / ``vector_search`` — jurisdiction / code / citation
  filters over remote modes;
* ``hybrid_search`` — late fusion of compatible BM25 and vector rankings
  that **preserves component scores** in every hit and explanation;
* ``neighbors`` — bounded adjacency with explicit authority labels;
* ``graph_walk`` — structural BFS enforcing every budget dimension
  (bounded graph);
* ``semantic_graph_walk`` — embedding-guided beam walk that hydrates
  frontier vectors **only** through the entry locator.

Design invariants
-----------------
* BM25 never scans postings; it routes by inclusive lexicographic term
  ranges advertised in the keyword shard index.
* Dense retrieval never scans every centroid; it probes the compact
  evaluated-centroid index and exact-scores only the selected shards.
* Cosine-sorted vector-shard ``first_key`` / ``last_key`` values are
  **not** lexical CID ranges and must not hydrate graph nodes.
* Frontier embeddings resolve ``entry_cid -> centroid/shard/row`` through
  the dedicated entry locator, then fetch those shards under budget.
* Similarity edges (``BM25_NEIGHBOR_OF``, ``SIMILAR_TO``,
  ``EMBEDDING_NEIGHBOR_OF``) are retrieval hints only — never legal
  authority.
* Graph walks charge and stop on depth, node, edge, shard, byte, row, and
  time budgets.
* Immutable Hub pins, digests, and bounds fail closed. Mutable refs such
  as ``main`` are rejected by composing :class:`ImmutableHubResolver`
  without rewriting it.
* Only justified routed shards are fetched. Results are stable by CID
  with auditable traces.

No network I/O in unit tests; compact sealed recipes regenerate miniature
offline releases at test time. This module does not authorize Hub upload
or publication.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional

from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (
    EDGE_AUTHORITY as ADJACENCY_EDGE_AUTHORITY,
    EDGE_PROOF_AUTHORITY as ADJACENCY_EDGE_PROOF_AUTHORITY,
    EDGE_TYPE_BM25_NEIGHBOR,
    TASK_ID as ADJACENCY_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    PRIMARY_KEY as BM25_PRIMARY_KEY,
    TASK_ID as BM25_TASK_ID,
    TOKENIZER_ID as BM25_TOKENIZER_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    DEFAULT_EDGE_CLASS,
    LEGAL_EDGE_TYPES,
    SIMILARITY_EDGE_TYPES,
    TASK_ID as GRAPH_TASK_ID,
    GraphEdgeClass,
    GraphEdgeType,
    GraphOntologyError,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    TASK_ID as HF_RELEASE_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_CANDIDATE_CENTROIDS as SCHEMA_DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vectors import (
    PARENT_KEY as VECTOR_PARENT_KEY,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PRIMARY_KEY as VECTOR_PRIMARY_KEY,
    TASK_ID as VECTORS_TASK_ID,
    VECTOR_ENTRY_LOCATOR_DIR,
)

from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    DEFAULT_TOP_K,
    MAX_TOP_K,
    BoundedRemoteQueryEngine,
    QueryBudgetExhausted,
    QueryEngineResult,
    QueryLimits,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
    RouteJustification,
    select_term_range_shards,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    DEFAULT_CANDIDATE_CENTROIDS,
    ModelSpace,
    QueryEmbedder,
    RemoteSearchClient,
    RemoteSearchError,
    RemoteSearchInputError,
    RemoteSearchResult,
    SearchFilters,
    sparse_io_summary,
    stable_rank,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    MutableRevisionError,
    validate_immutable_revision,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-query-v1"
CONTRACT_SCHEMA_VERSION: Final = "state-laws-query-contract-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-query@1"
TASK_ID: Final = "LCR-033"
GOAL_ID: Final = "LCR-G050"
PRODUCER: Final = "state_laws_query.py"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "remote-query"
CODE_VERSION: Final = "1"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"
CONSUMED_PRODUCERS: Final = (
    "state_laws_hf_release",
    "state_laws_bm25",
    "state_laws_vectors",
    "state_laws_graph",
    "state_laws_adjacency",
)
DEPENDS_ON: Final = (
    HF_RELEASE_TASK_ID,
    BM25_TASK_ID,
    VECTORS_TASK_ID,
    GRAPH_TASK_ID,
    ADJACENCY_TASK_ID,
)

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
IMMUTABLE_PIN_REQUIRED: Final = True
NO_MUTABLE_MAIN_DEFAULT: Final = True
SECRETS_ABSENT: Final = True

REPORT_RELATIVE_PATH: Final = (
    "docs/reports/legal_corpora_reindex/query_contract.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

# Fusion
FUSION_WEIGHTED: Final = "weighted"
FUSION_RRF: Final = "rrf"
FUSION_METHODS: Final = frozenset({FUSION_WEIGHTED, FUSION_RRF})
DEFAULT_BM25_WEIGHT: Final = 0.5
DEFAULT_VECTOR_WEIGHT: Final = 0.5
DEFAULT_RRF_K: Final = 60
FUSION_STAGE: Final = "late"

# Semantic beam defaults
DEFAULT_BEAM_WIDTH: Final = 16
DEFAULT_MAX_DEPTH: Final = 2
DEFAULT_PER_NODE_LIMIT: Final = 16
DEFAULT_SEMANTIC_PROXIMITY_WEIGHT: Final = 0.55
DEFAULT_EDGE_WEIGHT: Final = 0.30
DEFAULT_PATH_PENALTY: Final = 0.15

# Indexes (generic engine names; FR locators bind entry_cid)
BM25_INDEX_NAME: Final = "bm25_keyword_shards"
VECTOR_INDEX_NAME: Final = "vector_chunks"
ENTRY_LOCATOR_INDEX_NAME: Final = Path(VECTOR_ENTRY_LOCATOR_DIR).name
ENTRY_LOCATOR_KEY: Final = VECTOR_PARENT_KEY
VECTOR_SHARD_KEYS_ARE_LEXICAL_RANGES: Final = False

# Routing policy
BM25_ROUTE_POLICY: Final = "lexicographic_term_ranges"
VECTOR_ROUTE_POLICY: Final = "evaluated_centroid_probe"
FRONTIER_HYDRATION_POLICY: Final = "entry_locator"
HYBRID_FUSION_POLICY: Final = "late_fuse_compatible_rankings"

# Edge authority
AUTHORITY_LEGAL: Final = "legal"
AUTHORITY_NON_AUTHORITATIVE: Final = ADJACENCY_EDGE_AUTHORITY
SIMILARITY_EDGE_TYPE_NAMES: Final = frozenset(
    item.value for item in SIMILARITY_EDGE_TYPES
)
LEGAL_EDGE_TYPE_NAMES: Final = frozenset(item.value for item in LEGAL_EDGE_TYPES)

QUERY_MODES: Final = (
    "bm25",
    "vector",
    "hybrid",
    "neighbors",
    "graph_walk",
    "semantic_graph_walk",
)
QUERY_FILTERS: Final = ("jurisdiction", "code", "citation")

# Acceptance-language budgets (engine names are plural except depth/time).
TRAVERSAL_BUDGET_DIMENSIONS: Final = (
    "depth",
    "nodes",
    "edges",
    "shards",
    "bytes",
    "time",
)
ACCEPTANCE_BUDGET_NAMES: Final = (
    "depth",
    "node",
    "edge",
    "shard",
    "byte",
    "time",
)

PathLike = str | Path
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsQueryError(RemoteSearchError):
    """Base error for state-law hybrid / graph query failures."""

    code: str = "state_laws_query_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class StateLawsQueryInputError(
    StateLawsQueryError, RemoteSearchInputError
):
    """Raised when state-law query inputs are malformed."""

    code = "query_input_invalid"


class LegalAuthorityCollisionError(StateLawsQueryError):
    """Raised when a similarity edge is labeled as legal authority."""

    code = "legal_authority_collision"


class FusionConfigError(StateLawsQueryError):
    """Raised when hybrid fusion configuration is invalid."""

    code = "fusion_config_invalid"


class EntryLocatorError(StateLawsQueryError):
    """Raised when frontier hydration cannot use the entry locator."""

    code = "entry_locator_error"


class ImmutablePinError(StateLawsQueryError, MutableRevisionError):
    """Raised when a mutable Hub revision is supplied to the query engine."""

    code = "immutable_pin_required"



def assert_no_secrets(
    payload: Mapping[str, Any],
    *,
    context: str = "state_laws_query",
) -> None:
    """Fail closed when receipts contain tokens or absolute home paths."""

    if not isinstance(payload, Mapping):
        raise StateLawsQueryInputError(f"{context} must be a mapping")
    assert_no_secrets_or_home_paths(payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsQueryInputError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise StateLawsQueryInputError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise StateLawsQueryInputError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StateLawsQueryInputError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StateLawsQueryInputError(
            f"{name} must be a non-negative integer"
        )
    return value


def _require_weight(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FusionConfigError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise FusionConfigError(f"{name} must be a non-negative finite number")
    return number


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _iso_date_prefix(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    """Compose the shared resolver pin check; reject ``main`` / mutable refs."""

    try:
        return validate_immutable_revision(value, name=name)
    except MutableRevisionError as exc:
        raise ImmutablePinError(str(exc)) from exc


def cosine_similarity(
    left: Sequence[float] | None,
    right: Sequence[float] | None,
) -> float:
    """Cosine similarity without a NumPy dependency."""

    if left is None or right is None:
        return 0.0
    try:
        a = tuple(float(x) for x in left)
        b = tuple(float(x) for x in right)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not a or len(a) != len(b):
        return 0.0
    if not all(math.isfinite(x) for x in a) or not all(
        math.isfinite(x) for x in b
    ):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


# ---------------------------------------------------------------------------
# Edge authority (similarity never legal authority)
# ---------------------------------------------------------------------------


def edge_class_for_type(edge_type: str | GraphEdgeType) -> GraphEdgeClass:
    """Return the sealed edge class for a legal/similarity edge type."""

    if isinstance(edge_type, GraphEdgeType):
        edge = edge_type
    else:
        text = str(edge_type or "").strip().upper().replace("-", "_")
        try:
            edge = GraphEdgeType.coerce(text)
        except GraphOntologyError:
            return GraphEdgeClass.SIMILARITY
    return DEFAULT_EDGE_CLASS.get(edge, GraphEdgeClass.SIMILARITY)


def is_similarity_edge_type(edge_type: str | GraphEdgeType | None) -> bool:
    """Return True when *edge_type* is a non-authoritative similarity edge."""

    if edge_type is None:
        return False
    if isinstance(edge_type, GraphEdgeType):
        return edge_type in SIMILARITY_EDGE_TYPES
    text = str(edge_type).strip().upper().replace("-", "_")
    return text in SIMILARITY_EDGE_TYPE_NAMES or text in {
        item.name for item in SIMILARITY_EDGE_TYPES
    }


def is_legal_edge_type(edge_type: str | GraphEdgeType | None) -> bool:
    """Return True when *edge_type* is a legal/structural/provenance edge."""

    if edge_type is None:
        return False
    if isinstance(edge_type, GraphEdgeType):
        return edge_type in LEGAL_EDGE_TYPES
    text = str(edge_type).strip().upper().replace("-", "_")
    return text in LEGAL_EDGE_TYPE_NAMES or text in {
        item.name for item in LEGAL_EDGE_TYPES
    }


def classify_edge_authority(edge_type: str | GraphEdgeType | None) -> dict[str, Any]:
    """Classify an edge type for query result packaging.

    Similarity edges (including BM25 neighbors) are **never** legal
    authority. Unknown types fail soft toward non-authoritative so
    retrieval noise cannot claim legal force.
    """

    if is_similarity_edge_type(edge_type):
        edge_class = GraphEdgeClass.SIMILARITY
        return {
            "authority": AUTHORITY_NON_AUTHORITATIVE,
            "edge_class": edge_class.value,
            "edge_type": (
                edge_type.value
                if isinstance(edge_type, GraphEdgeType)
                else str(edge_type or "")
            ),
            "legal_authority": False,
            "proof_authority": bool(ADJACENCY_EDGE_PROOF_AUTHORITY),
            "retrieval_hint": True,
        }
    if is_legal_edge_type(edge_type):
        edge_class = edge_class_for_type(edge_type)  # type: ignore[arg-type]
        return {
            "authority": AUTHORITY_LEGAL,
            "edge_class": edge_class.value,
            "edge_type": (
                edge_type.value
                if isinstance(edge_type, GraphEdgeType)
                else str(edge_type or "")
            ),
            "legal_authority": True,
            "proof_authority": edge_class
            in {
                GraphEdgeClass.AUTHORITY,
                GraphEdgeClass.CITATION,
                GraphEdgeClass.STRUCTURAL,
            },
            "retrieval_hint": False,
        }
    return {
        "authority": AUTHORITY_NON_AUTHORITATIVE,
        "edge_class": GraphEdgeClass.SIMILARITY.value,
        "edge_type": str(edge_type or ""),
        "legal_authority": False,
        "proof_authority": False,
        "retrieval_hint": True,
    }


def annotate_edge_authority(edge: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *edge* with sealed authority fields.

    Raises :class:`LegalAuthorityCollisionError` if a similarity edge already
    claims legal authority.
    """

    if not isinstance(edge, Mapping):
        raise StateLawsQueryInputError("edge must be a mapping")
    row = dict(edge)
    edge_type = row.get("edge_type") or row.get("relationship_type") or ""
    classification = classify_edge_authority(str(edge_type))
    if is_similarity_edge_type(str(edge_type)):
        claimed_legal = row.get("legal_authority")
        claimed_authority = str(row.get("authority") or "").strip().lower()
        claimed_proof = row.get("proof_authority")
        if claimed_legal is True or claimed_proof is True:
            raise LegalAuthorityCollisionError(
                f"similarity edge {edge_type!r} cannot claim legal/proof "
                f"authority"
            )
        if claimed_authority in {
            "legal",
            "authority",
            "citation",
            "authoritative",
        }:
            raise LegalAuthorityCollisionError(
                f"similarity edge {edge_type!r} cannot use authority="
                f"{claimed_authority!r}"
            )
        if str(row.get("edge_class") or "").strip().lower() in {
            "authority",
            "citation",
            "structural",
            "provenance",
        }:
            raise LegalAuthorityCollisionError(
                f"similarity edge {edge_type!r} cannot use legal edge_class="
                f"{row.get('edge_class')!r}"
            )
    row.update(classification)
    return row


def assert_no_similarity_as_legal_authority(
    edges: Sequence[Mapping[str, Any]],
) -> None:
    """Fail closed when any edge packages similarity as legal authority."""

    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        annotated = annotate_edge_authority(edge)
        if is_similarity_edge_type(str(annotated.get("edge_type") or "")):
            if annotated.get("legal_authority") is not False:
                raise LegalAuthorityCollisionError(
                    "similarity edge presented as legal authority"
                )
            if annotated.get("proof_authority") is not False:
                raise LegalAuthorityCollisionError(
                    "similarity edge presented as proof authority"
                )
            if annotated.get("authority") != AUTHORITY_NON_AUTHORITATIVE:
                raise LegalAuthorityCollisionError(
                    "similarity edge must be non_authoritative"
                )


def similarity_edge_semantics() -> dict[str, Any]:
    """Sealed non-authoritative semantics for similarity edges in queries."""

    return {
        "authority": AUTHORITY_NON_AUTHORITATIVE,
        "edge_class": GraphEdgeClass.SIMILARITY.value,
        "edge_types": sorted(SIMILARITY_EDGE_TYPE_NAMES),
        "legal_authority": False,
        "notes": (
            "Similarity edges (BM25_NEIGHBOR_OF, SIMILAR_TO, "
            "EMBEDDING_NEIGHBOR_OF) are retrieval hints only. They must "
            "never be labeled as legal citation, authority, correction, or "
            "proof. BM25 neighbors are not legal authority."
        ),
        "overlay_edge_type": EDGE_TYPE_BM25_NEIGHBOR,
        "proof_authority": False,
        "retrieval_hint": True,
    }


# ---------------------------------------------------------------------------
# Legal filters (jurisdiction / code / citation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalFilters:
    """State-law jurisdiction / code / citation filters over hits."""

    jurisdiction: str | None = None
    code: str | None = None
    citation: str | None = None
    code_family: str | None = None
    title: str | None = None
    chapter: str | None = None
    section: str | None = None
    source: str | None = None
    release_point: str | None = None
    legal_id: str | None = None
    edition: str | None = None
    version: str | None = None
    status: str | None = None
    entry_cids: tuple[str, ...] = ()
    document_indexes: tuple[int, ...] = ()
    node_types: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    metadata_equals: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def _opt(value: Any, name: str) -> str | None:
            if value is None or value == "":
                return None
            return _require_non_empty_str(value, name, maximum=512)

        object.__setattr__(
            self, "jurisdiction", _opt(self.jurisdiction, "jurisdiction")
        )
        object.__setattr__(self, "code", _opt(self.code, "code"))
        object.__setattr__(self, "citation", _opt(self.citation, "citation"))
        object.__setattr__(
            self, "code_family", _opt(self.code_family, "code_family")
        )
        object.__setattr__(self, "title", _opt(self.title, "title"))
        object.__setattr__(self, "chapter", _opt(self.chapter, "chapter"))
        object.__setattr__(self, "section", _opt(self.section, "section"))
        object.__setattr__(self, "source", _opt(self.source, "source"))
        object.__setattr__(
            self, "release_point", _opt(self.release_point, "release_point")
        )
        object.__setattr__(self, "legal_id", _opt(self.legal_id, "legal_id"))
        object.__setattr__(self, "edition", _opt(self.edition, "edition"))
        object.__setattr__(self, "version", _opt(self.version, "version"))
        object.__setattr__(self, "status", _opt(self.status, "status"))
        if self.code is None and self.code_family is not None:
            object.__setattr__(self, "code", self.code_family)
        if self.code_family is None and self.code is not None:
            object.__setattr__(self, "code_family", self.code)
        object.__setattr__(
            self,
            "entry_cids",
            tuple(
                _require_non_empty_str(item, "entry_cids[]", maximum=256)
                for item in (self.entry_cids or ())
            ),
        )
        indexes: list[int] = []
        for item in self.document_indexes or ():
            if isinstance(item, bool) or not isinstance(item, int):
                raise StateLawsQueryInputError(
                    "document_indexes must contain integers"
                )
            indexes.append(item)
        object.__setattr__(self, "document_indexes", tuple(indexes))
        object.__setattr__(
            self,
            "node_types",
            tuple(
                _require_non_empty_str(item, "node_types[]", maximum=128)
                for item in (self.node_types or ())
            ),
        )
        object.__setattr__(
            self,
            "edge_types",
            tuple(
                _require_non_empty_str(item, "edge_types[]", maximum=128)
                for item in (self.edge_types or ())
            ),
        )
        if not isinstance(self.metadata_equals, Mapping):
            raise StateLawsQueryInputError("metadata_equals must be a mapping")
        object.__setattr__(
            self,
            "metadata_equals",
            MappingProxyType(dict(self.metadata_equals)),
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.jurisdiction,
                self.code,
                self.citation,
                self.code_family,
                self.title,
                self.chapter,
                self.section,
                self.source,
                self.release_point,
                self.legal_id,
                self.edition,
                self.version,
                self.status,
                self.entry_cids,
                self.document_indexes,
                self.node_types,
                self.edge_types,
                self.metadata_equals,
            )
        )

    def to_search_filters(self) -> SearchFilters:
        """Project onto domain-neutral search filters (shared fields only)."""

        meta = dict(self.metadata_equals)
        if self.citation is not None:
            meta.setdefault("citation", self.citation)
        if self.legal_id is not None:
            meta.setdefault("legal_id", self.legal_id)
        if self.jurisdiction is not None:
            meta.setdefault("jurisdiction", self.jurisdiction)
        if self.code is not None:
            meta.setdefault("code", self.code)
        if self.code_family is not None:
            meta.setdefault("code_family", self.code_family)
        if self.edition is not None:
            meta.setdefault("edition", self.edition)
        if self.version is not None:
            meta.setdefault("version", self.version)
        if self.status is not None:
            meta.setdefault("status", self.status)
        return SearchFilters(
            title=self.title,
            chapter=self.chapter,
            section=self.section,
            source=self.source,
            release_point=self.release_point,
            entry_cids=self.entry_cids,
            document_indexes=self.document_indexes,
            node_types=self.node_types,
            edge_types=self.edge_types,
            metadata_equals=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in (
            "jurisdiction",
            "code",
            "citation",
            "code_family",
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
            "legal_id",
            "edition",
            "version",
            "status",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.entry_cids:
            payload["entry_cids"] = list(self.entry_cids)
        if self.document_indexes:
            payload["document_indexes"] = list(self.document_indexes)
        if self.node_types:
            payload["node_types"] = list(self.node_types)
        if self.edge_types:
            payload["edge_types"] = list(self.edge_types)
        if self.metadata_equals:
            payload["metadata_equals"] = dict(self.metadata_equals)
        return payload

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | SearchFilters | None = None
    ) -> "LegalFilters":
        if value is None:
            return cls()
        if isinstance(value, LegalFilters):
            return value
        if isinstance(value, SearchFilters):
            meta = dict(value.metadata_equals)
            return cls(
                jurisdiction=meta.get("jurisdiction"),
                code=meta.get("code") or meta.get("code_family"),
                citation=meta.get("citation"),
                code_family=meta.get("code_family"),
                title=value.title,
                chapter=value.chapter,
                section=value.section,
                source=value.source,
                release_point=value.release_point,
                legal_id=meta.get("legal_id"),
                edition=meta.get("edition"),
                version=meta.get("version"),
                status=meta.get("status"),
                entry_cids=value.entry_cids,
                document_indexes=value.document_indexes,
                node_types=value.node_types,
                edge_types=value.edge_types,
                metadata_equals=meta,
            )
        if not isinstance(value, Mapping):
            raise StateLawsQueryInputError("filters must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in (
            "jurisdiction",
            "code",
            "citation",
            "code_family",
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
            "legal_id",
            "edition",
            "version",
            "status",
        ):
            if key in value and value[key] is not None:
                kwargs[key] = value[key]
        if "jurisdiction_code" in value and value["jurisdiction_code"] is not None:
            kwargs.setdefault("jurisdiction", value["jurisdiction_code"])
        if "state" in value and value["state"] is not None:
            kwargs.setdefault("jurisdiction", value["state"])
        if "code_id" in value and value["code_id"] is not None:
            kwargs.setdefault("code", value["code_id"])
        if "entry_cids" in value and value["entry_cids"] is not None:
            kwargs["entry_cids"] = tuple(value["entry_cids"])
        if "entry_cid" in value and value["entry_cid"] is not None:
            kwargs["entry_cids"] = (value["entry_cid"],) + tuple(
                kwargs.get("entry_cids") or ()
            )
        if "document_indexes" in value and value["document_indexes"] is not None:
            kwargs["document_indexes"] = tuple(value["document_indexes"])
        if "node_types" in value and value["node_types"] is not None:
            kwargs["node_types"] = tuple(value["node_types"])
        if "edge_types" in value and value["edge_types"] is not None:
            kwargs["edge_types"] = tuple(value["edge_types"])
        if "metadata_equals" in value and value["metadata_equals"] is not None:
            kwargs["metadata_equals"] = dict(value["metadata_equals"])
        return cls(**kwargs)


def _hit_legal_field(hit: Mapping[str, Any], logical: str) -> Any:
    aliases = {
        "jurisdiction": (
            "jurisdiction",
            "jurisdiction_code",
            "state",
            "state_code",
        ),
        "code": ("code", "code_family", "code_id", "statute_code"),
        "code_family": ("code_family", "code", "code_id"),
        "citation": ("citation", "bluebook", "state_citation"),
        "legal_id": ("legal_id", "legalId", "state_legal_id"),
        "edition": ("edition", "edition_id", "code_edition"),
        "version": ("version", "version_id"),
        "status": ("status", "statute_status", "currency"),
        "title": ("title", "title_number"),
        "chapter": ("chapter", "chapter_number"),
        "section": ("section", "section_number"),
        "source": ("source",),
        "release_point": ("release_point", "release_point_id", "release"),
    }
    for name in aliases.get(logical, (logical,)):
        if name in hit and hit[name] not in (None, ""):
            return hit[name]
    return None


def hit_matches_legal_filters(
    hit: Mapping[str, Any],
    filters: LegalFilters | Mapping[str, Any] | SearchFilters | None,
) -> bool:
    """Return True when *hit* satisfies all state-law filters."""

    filt = (
        filters
        if isinstance(filters, LegalFilters)
        else LegalFilters.from_mapping(filters)
    )
    if filt.is_empty:
        return True
    if not isinstance(hit, Mapping):
        return False
    base = filt.to_search_filters()
    domain_keys = {
        "citation",
        "legal_id",
        "jurisdiction",
        "code",
        "code_family",
        "edition",
        "version",
        "status",
    }
    base_meta = {
        key: value
        for key, value in base.metadata_equals.items()
        if key not in domain_keys
    }
    base_plain = SearchFilters(
        title=base.title,
        chapter=base.chapter,
        section=base.section,
        source=base.source,
        release_point=base.release_point,
        entry_cids=base.entry_cids,
        document_indexes=base.document_indexes,
        node_types=base.node_types,
        edge_types=base.edge_types,
        metadata_equals=base_meta,
    )
    from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
        hit_matches_filters,
    )

    if not hit_matches_filters(hit, base_plain):
        return False

    def _eq(expected: str | None, logical: str) -> bool:
        if expected is None:
            return True
        actual = _hit_legal_field(hit, logical)
        if actual is None:
            return False
        return str(actual).strip().lower() == expected.strip().lower()

    if not _eq(filt.jurisdiction, "jurisdiction"):
        return False
    if not _eq(filt.code, "code"):
        return False
    if not _eq(filt.code_family, "code_family"):
        return False
    if not _eq(filt.citation, "citation"):
        return False
    if not _eq(filt.legal_id, "legal_id"):
        return False
    if not _eq(filt.edition, "edition"):
        return False
    if not _eq(filt.version, "version"):
        return False
    if not _eq(filt.status, "status"):
        return False
    return True


def apply_legal_filters(
    hits: Sequence[Mapping[str, Any]],
    filters: LegalFilters | Mapping[str, Any] | SearchFilters | None,
) -> list[dict[str, Any]]:
    """Filter hits with legal filters while preserving input order."""

    return [dict(hit) for hit in hits if hit_matches_legal_filters(hit, filters)]


# Fusion (late, component scores preserved)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Hybrid fusion policy with explicit component weights."""

    method: str = FUSION_WEIGHTED
    bm25_weight: float = DEFAULT_BM25_WEIGHT
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    rrf_k: int = DEFAULT_RRF_K
    stage: str = FUSION_STAGE

    def __post_init__(self) -> None:
        method = str(self.method or FUSION_WEIGHTED).strip().lower()
        if method not in FUSION_METHODS:
            raise FusionConfigError(
                f"fusion method must be one of {sorted(FUSION_METHODS)}, "
                f"got {self.method!r}"
            )
        stage = str(self.stage or FUSION_STAGE).strip().lower()
        if stage != FUSION_STAGE:
            raise FusionConfigError(
                f"hybrid fusion must be late; got stage={self.stage!r}"
            )
        bm25_w = _require_weight(self.bm25_weight, "bm25_weight")
        vector_w = _require_weight(self.vector_weight, "vector_weight")
        if method == FUSION_WEIGHTED and bm25_w + vector_w <= 0.0:
            raise FusionConfigError(
                "weighted fusion requires at least one positive weight"
            )
        rrf_k = _require_positive_int(self.rrf_k, "rrf_k")
        if rrf_k > 10_000:
            raise FusionConfigError("rrf_k exceeds hard bound 10000")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "bm25_weight", bm25_w)
        object.__setattr__(self, "vector_weight", vector_w)
        object.__setattr__(self, "rrf_k", rrf_k)
        object.__setattr__(self, "stage", stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_weight": self.bm25_weight,
            "method": self.method,
            "rrf_k": self.rrf_k,
            "stage": self.stage,
            "vector_weight": self.vector_weight,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None = None
    ) -> "FusionConfig":
        if value is None:
            return cls()
        if isinstance(value, FusionConfig):
            return value
        if not isinstance(value, Mapping):
            raise FusionConfigError("fusion config must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in ("method", "bm25_weight", "vector_weight", "rrf_k", "stage"):
            if key in value:
                kwargs[key] = value[key]
        return cls(**kwargs)


def _hit_identity(hit: Mapping[str, Any]) -> str | None:
    for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
        if key in hit and hit[key] is not None and hit[key] != "":
            return f"{key}:{hit[key]}"
    return None


def rankings_are_compatible(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
) -> bool:
    """Return True when both rankings expose a shared identity key space."""

    def _keys(hits: Sequence[Mapping[str, Any]]) -> set[str]:
        found: set[str] = set()
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            identity = _hit_identity(hit)
            if identity is None:
                continue
            found.add(identity.split(":", 1)[0])
        return found

    left_keys = _keys(left)
    right_keys = _keys(right)
    if not left_keys or not right_keys:
        return True
    return bool(left_keys & right_keys)


def _component_score(hit: Mapping[str, Any]) -> float:
    for key in ("normalized_score", "score"):
        score = _finite_score(hit.get(key))
        if score is not None:
            return score
    return 0.0


def fuse_hybrid_results(
    bm25_hits: Sequence[Mapping[str, Any]],
    vector_hits: Sequence[Mapping[str, Any]],
    *,
    config: FusionConfig | Mapping[str, Any] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Late-fuse BM25 and vector rankings while preserving component scores."""

    fusion = (
        config
        if isinstance(config, FusionConfig)
        else FusionConfig.from_mapping(config)
    )
    top_k = _require_positive_int(top_k, "top_k")
    if top_k > MAX_TOP_K:
        raise StateLawsQueryInputError(f"top_k must be <= {MAX_TOP_K}")

    merged: dict[str, dict[str, Any]] = {}
    bm25_rank: dict[str, int] = {}
    vector_rank: dict[str, int] = {}

    for rank, hit in enumerate(bm25_hits, start=1):
        if not isinstance(hit, Mapping):
            continue
        identity = _hit_identity(hit) or f"row:{id(hit)}"
        row = merged.setdefault(
            identity,
            {
                "chunk_cid": hit.get("chunk_cid"),
                "entry_cid": hit.get("entry_cid"),
            },
        )
        for field_name, value in hit.items():
            if field_name in {"score", "normalized_score"}:
                continue
            if field_name not in row or row[field_name] in (None, ""):
                row[field_name] = value
        row["bm25_score"] = _component_score(hit)
        bm25_rank[identity] = rank

    for rank, hit in enumerate(vector_hits, start=1):
        if not isinstance(hit, Mapping):
            continue
        identity = _hit_identity(hit) or f"row:{id(hit)}"
        row = merged.setdefault(
            identity,
            {
                "chunk_cid": hit.get("chunk_cid"),
                "entry_cid": hit.get("entry_cid"),
            },
        )
        for field_name, value in hit.items():
            if field_name in {"score", "normalized_score"}:
                continue
            if field_name not in row or row[field_name] in (None, ""):
                row[field_name] = value
        row["vector_score"] = _component_score(hit)
        vector_rank[identity] = rank

    fused: list[dict[str, Any]] = []
    for identity, row in merged.items():
        bm25_score = float(row.get("bm25_score") or 0.0)
        vector_score = float(row.get("vector_score") or 0.0)
        if fusion.method == FUSION_RRF:
            score = 0.0
            if identity in bm25_rank:
                score += fusion.bm25_weight / (fusion.rrf_k + bm25_rank[identity])
            if identity in vector_rank:
                score += fusion.vector_weight / (
                    fusion.rrf_k + vector_rank[identity]
                )
        else:
            total_w = fusion.bm25_weight + fusion.vector_weight
            score = (
                fusion.bm25_weight * bm25_score
                + fusion.vector_weight * vector_score
            ) / total_w
        payload = dict(row)
        payload["bm25_score"] = bm25_score
        payload["vector_score"] = vector_score
        payload["component_scores"] = {
            "bm25": bm25_score,
            "vector": vector_score,
        }
        payload["score"] = score
        payload["fusion_method"] = fusion.method
        payload["fusion_stage"] = fusion.stage
        payload["sources"] = sorted(
            {
                *(["bm25"] if identity in bm25_rank else []),
                *(["vector"] if identity in vector_rank else []),
            }
        )
        if identity in bm25_rank:
            payload["bm25_rank"] = bm25_rank[identity]
        if identity in vector_rank:
            payload["vector_rank"] = vector_rank[identity]
        fused.append(payload)

    return stable_rank(fused, top_k=top_k)


# ---------------------------------------------------------------------------
# Result packaging
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateLawsQueryResult:
    """Hybrid / graph query result with authority-safe packaging."""

    mode: str
    query: str
    results: tuple[dict[str, Any], ...]
    diagnostics: Mapping[str, Any]
    fetch_trace: Mapping[str, Any]
    complete: bool
    stop_reason: str | None
    usage: Mapping[str, Any]
    limits: Mapping[str, Any]
    explain: Mapping[str, Any] = field(default_factory=dict)
    filters: Mapping[str, Any] = field(default_factory=dict)
    model_space: Mapping[str, Any] = field(default_factory=dict)
    edges: tuple[dict[str, Any], ...] = ()
    sparse_io: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "diagnostics", MappingProxyType(dict(self.diagnostics))
        )
        object.__setattr__(
            self, "fetch_trace", MappingProxyType(dict(self.fetch_trace))
        )
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))
        object.__setattr__(
            self, "explain", MappingProxyType(dict(self.explain))
        )
        object.__setattr__(
            self, "filters", MappingProxyType(dict(self.filters))
        )
        object.__setattr__(
            self, "model_space", MappingProxyType(dict(self.model_space))
        )
        object.__setattr__(
            self, "sparse_io", MappingProxyType(dict(self.sparse_io))
        )
        object.__setattr__(
            self, "results", tuple(dict(item) for item in self.results)
        )
        object.__setattr__(
            self, "edges", tuple(dict(item) for item in self.edges)
        )
        assert_no_similarity_as_legal_authority(self.edges)

    @property
    def result_count(self) -> int:
        return len(self.results)

    def ordered_result_cids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for item in self.results:
            for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
                if key in item and item[key] is not None:
                    ordered.append(str(item[key]))
                    break
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "complete": self.complete,
            "diagnostics": dict(self.diagnostics),
            "fetch_trace": dict(self.fetch_trace),
            "filters": dict(self.filters),
            "goal_id": self.goal_id,
            "limits": dict(self.limits),
            "mode": self.mode,
            "query": self.query,
            "result_count": self.result_count,
            "results": [dict(item) for item in self.results],
            "schema_version": self.schema_version,
            "sparse_io": dict(self.sparse_io),
            "stop_reason": self.stop_reason,
            "task_id": self.task_id,
            "usage": dict(self.usage),
        }
        if self.explain:
            payload["explain"] = dict(self.explain)
        if self.model_space:
            payload["model_space"] = dict(self.model_space)
        if self.edges:
            payload["edges"] = [dict(item) for item in self.edges]
        return payload


def query_replay_fingerprint(
    result: StateLawsQueryResult | Mapping[str, Any],
) -> str:
    """Stable fingerprint for offline replay of legal query modes."""

    if isinstance(result, StateLawsQueryResult):
        payload = {
            "complete": result.complete,
            "filters": dict(result.filters),
            "mode": result.mode,
            "ordered_result_cids": list(result.ordered_result_cids()),
            "query": result.query,
            "result_count": result.result_count,
            "stop_reason": result.stop_reason,
        }
    else:
        if not isinstance(result, Mapping):
            raise StateLawsQueryInputError("result must be a mapping")
        payload = {
            "complete": bool(result.get("complete")),
            "filters": dict(result.get("filters") or {}),
            "mode": result.get("mode"),
            "ordered_result_cids": list(result.get("ordered_result_cids") or []),
            "query": result.get("query"),
            "result_count": result.get("result_count"),
            "stop_reason": result.get("stop_reason"),
        }
    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Semantic beam + entry locator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticBeamConfig:
    """Budgets and blend weights for embedding-guided graph walks."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int | None = None
    max_edges: int | None = None
    per_node_limit: int = DEFAULT_PER_NODE_LIMIT
    beam_width: int = DEFAULT_BEAM_WIDTH
    proximity_weight: float = DEFAULT_SEMANTIC_PROXIMITY_WEIGHT
    edge_weight: float = DEFAULT_EDGE_WEIGHT
    path_penalty: float = DEFAULT_PATH_PENALTY
    candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_depth",
            _require_non_negative_int(self.max_depth, "max_depth"),
        )
        if self.max_nodes is not None:
            object.__setattr__(
                self,
                "max_nodes",
                _require_positive_int(self.max_nodes, "max_nodes"),
            )
        if self.max_edges is not None:
            object.__setattr__(
                self,
                "max_edges",
                _require_positive_int(self.max_edges, "max_edges"),
            )
        object.__setattr__(
            self,
            "per_node_limit",
            _require_positive_int(self.per_node_limit, "per_node_limit"),
        )
        object.__setattr__(
            self,
            "beam_width",
            _require_positive_int(self.beam_width, "beam_width"),
        )
        object.__setattr__(
            self,
            "proximity_weight",
            _require_weight(self.proximity_weight, "proximity_weight"),
        )
        object.__setattr__(
            self,
            "edge_weight",
            _require_weight(self.edge_weight, "edge_weight"),
        )
        object.__setattr__(
            self,
            "path_penalty",
            _require_weight(self.path_penalty, "path_penalty"),
        )
        object.__setattr__(
            self,
            "candidate_centroids",
            _require_positive_int(
                self.candidate_centroids, "candidate_centroids"
            ),
        )
        total = self.proximity_weight + self.edge_weight + self.path_penalty
        if total <= 0.0:
            raise StateLawsQueryInputError(
                "semantic beam requires at least one positive blend weight"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "beam_width": self.beam_width,
            "candidate_centroids": self.candidate_centroids,
            "edge_weight": self.edge_weight,
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "path_penalty": self.path_penalty,
            "per_node_limit": self.per_node_limit,
            "proximity_weight": self.proximity_weight,
        }


def _edge_weight_score(edge: Mapping[str, Any]) -> float:
    raw = edge.get("score")
    if raw is None:
        raw = edge.get("weight")
    score = _finite_score(raw)
    if score is None:
        return 1.0 if is_legal_edge_type(str(edge.get("edge_type") or "")) else 0.5
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def select_entry_locator_pages_for_keys(
    meta_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Map each ``entry_cid`` to its inclusive locator-page descriptor."""

    if not isinstance(meta_rows, Sequence) or isinstance(
        meta_rows, (str, bytes, bytearray)
    ):
        raise StateLawsQueryInputError("meta_rows must be a sequence")
    selected: dict[str, Mapping[str, Any]] = {}
    for key in keys:
        text = str(key or "").strip()
        if not text:
            continue
        matches = [
            dict(row)
            for row in meta_rows
            if isinstance(row, Mapping)
            and str(row.get("first_key") or "")
            <= text
            <= str(row.get("last_key") or "")
        ]
        if not matches:
            continue
        matches.sort(
            key=lambda row: (
                int(row.get("shard_id", 0)),
                str(row.get("relative_path") or ""),
            )
        )
        selected[text] = matches[0]
    return selected


def parse_entry_locator_locations(
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    """Extract ``entry_cid -> shard locations`` from locator-page rows."""

    wanted = {str(key).strip() for key in keys if str(key or "").strip()}
    resolved: dict[str, list[dict[str, Any]]] = {key: [] for key in wanted}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        entry_cid = str(
            row.get("entry_cid")
            or row.get(ENTRY_LOCATOR_KEY)
            or row.get("key")
            or ""
        ).strip()
        if entry_cid not in wanted:
            continue
        locations = row.get("locations")
        parsed: list[dict[str, Any]] = []
        if isinstance(locations, str) and locations.strip():
            try:
                loaded = json.loads(locations)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, Mapping):
                loaded = [loaded]
            if isinstance(loaded, Sequence):
                locations = loaded
        if isinstance(locations, Sequence) and not isinstance(
            locations, (str, bytes, bytearray)
        ):
            for item in locations:
                if isinstance(item, Mapping) and item.get("relative_path"):
                    parsed.append(dict(item))
        path = str(row.get("relative_path") or "").strip()
        if path:
            parsed.append(
                {
                    "cluster_id": row.get("cluster_id"),
                    "entry_cid": entry_cid,
                    "global_shard_id": row.get("global_shard_id", row.get("shard_id")),
                    "relative_path": path,
                    "row_offset": row.get("row_offset", 0),
                }
            )
        for item in parsed:
            path = str(item.get("relative_path") or "").strip()
            if not path:
                continue
            resolved[entry_cid].append(dict(item))
    return {key: value for key, value in resolved.items() if value}


def vector_shard_lexical_range_would_miss(
    meta_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> bool:
    """Return True when cosine-sorted shard keys cannot locate *keys*."""

    if VECTOR_SHARD_KEYS_ARE_LEXICAL_RANGES:
        return False
    hits = select_entry_locator_pages_for_keys(meta_rows, keys)
    return any(str(key).strip() and str(key).strip() not in hits for key in keys)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class StateLawsQueryClient:
    """Hybrid and embedding-guided graph queries over a pinned state-law release.

    Parameters
    ----------
    resolver:
        Pinned :class:`ImmutableHubResolver`. Mutable refs such as
        ``main`` fail closed in the shared resolver; this client composes
        that check and never defaults to a mutable branch.
    limits:
        Optional per-query budgets (bytes / shards / rows / nodes / edges /
        depth / time).
    """

    def __init__(
        self,
        resolver: ImmutableHubResolver | None = None,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        search: RemoteSearchClient | None = None,
        engine: BoundedRemoteQueryEngine | None = None,
        query_embedder: QueryEmbedder | None = None,
        fusion: FusionConfig | Mapping[str, Any] | None = None,
        score_normalization: str = "minmax",
        manifest_path: str = DEFAULT_MANIFEST_NAME,
    ) -> None:
        if search is not None:
            if not isinstance(search, RemoteSearchClient):
                raise StateLawsQueryInputError(
                    "search must be a RemoteSearchClient instance"
                )
            self.search = search
        else:
            if resolver is None:
                raise StateLawsQueryInputError(
                    "resolver is required; state-law queries never "
                    "default to a mutable Hub revision such as 'main'"
                )
            if not isinstance(resolver, ImmutableHubResolver):
                raise StateLawsQueryInputError(
                    "resolver must be an ImmutableHubResolver instance"
                )
            require_immutable_revision(resolver.revision)
            self.search = RemoteSearchClient(
                resolver,
                limits=limits,
                engine=engine,
                query_embedder=query_embedder,
                score_normalization=score_normalization,
                manifest_path=manifest_path,
            )
        require_immutable_revision(self.search.engine.resolver.revision)
        self.engine = self.search.engine
        self.fusion = (
            fusion
            if isinstance(fusion, FusionConfig)
            else FusionConfig.from_mapping(fusion)
        )
        self._vector_cache: dict[str, tuple[float, ...]] = {}
        self._vector_meta: list[dict[str, Any]] | None = None
        self._locator_meta: list[dict[str, Any]] | None = None
        self._centroid_routed_paths: set[str] = set()
        self._frontier_fetch_paths: set[str] = set()
        self._off_centroid_fetch_paths: set[str] = set()
        self._locator_page_paths: set[str] = set()

    @property
    def resolver(self) -> ImmutableHubResolver:
        return self.engine.resolver

    def reset_session(
        self,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        keep_manifest: bool = True,
    ) -> None:
        """Start a fresh budget/trace session."""

        self.search.reset_session(limits=limits, keep_manifest=keep_manifest)
        self._vector_cache.clear()
        if not keep_manifest:
            self._vector_meta = None
            self._locator_meta = None
        self._centroid_routed_paths.clear()
        self._frontier_fetch_paths.clear()
        self._off_centroid_fetch_paths.clear()
        self._locator_page_paths.clear()

    def _coerce_filters(
        self,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None,
    ) -> LegalFilters:
        return LegalFilters.from_mapping(filters)

    def _package_from_remote(
        self,
        remote: RemoteSearchResult,
        *,
        mode: str | None = None,
        filters: LegalFilters | None = None,
        explain_extra: Mapping[str, Any] | None = None,
        diagnostics_extra: Mapping[str, Any] | None = None,
        results: Sequence[Mapping[str, Any]] | None = None,
        edges: Sequence[Mapping[str, Any]] = (),
    ) -> StateLawsQueryResult:
        explain = dict(remote.explain)
        if explain_extra:
            explain.update(dict(explain_extra))
        diagnostics = dict(remote.diagnostics)
        if diagnostics_extra:
            diagnostics.update(dict(diagnostics_extra))
        hits = (
            [dict(item) for item in results]
            if results is not None
            else [dict(item) for item in remote.results]
        )
        annotated_edges = tuple(annotate_edge_authority(edge) for edge in edges)
        return StateLawsQueryResult(
            mode=mode or remote.mode,
            query=remote.query,
            results=tuple(hits),
            diagnostics=diagnostics,
            fetch_trace=dict(remote.fetch_trace),
            complete=remote.complete,
            stop_reason=remote.stop_reason,
            usage=dict(remote.usage),
            limits=dict(remote.limits),
            explain=explain,
            filters=(filters or LegalFilters()).to_dict(),
            model_space=dict(remote.model_space),
            edges=annotated_edges,
            sparse_io=dict(remote.sparse_io)
            or sparse_io_summary(remote.fetch_trace),
        )

    def bm25_search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """BM25 search routed exclusively by lexicographic term ranges."""

        filt = self._coerce_filters(filters)
        remote = self.search.bm25_search(
            query,
            top_k=top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k)),
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=reset_session,
        )
        hits = apply_legal_filters(remote.results, filt)
        hits = stable_rank(hits, top_k=top_k)
        return self._package_from_remote(
            remote,
            mode="bm25",
            filters=filt,
            results=hits,
            explain_extra={
                "legal_filters": filt.to_dict(),
                "route_policy": BM25_ROUTE_POLICY,
                "tokenizer_id": BM25_TOKENIZER_ID,
                "primary_key": BM25_PRIMARY_KEY,
            },
            diagnostics_extra={"route_policy": BM25_ROUTE_POLICY},
        )

    def vector_search(
        self,
        query: str = "",
        *,
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """Dense retrieval that probes evaluated centroids then exact-scores."""

        filt = self._coerce_filters(filters)
        remote = self.search.vector_search(
            query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
            top_k=top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k)),
            candidate_centroids=candidate_centroids,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=reset_session,
        )
        hits = apply_legal_filters(remote.results, filt)
        hits = stable_rank(hits, top_k=top_k)
        return self._package_from_remote(
            remote,
            mode="vector",
            filters=filt,
            results=hits,
            explain_extra={
                "legal_filters": filt.to_dict(),
                "route_policy": VECTOR_ROUTE_POLICY,
                "vector_primary_key": VECTOR_PRIMARY_KEY,
            },
            diagnostics_extra={"route_policy": VECTOR_ROUTE_POLICY},
        )

    def hybrid_search(
        self,
        query: str,
        *,
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        fusion: FusionConfig | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """Late-fuse compatible BM25 and vector rankings."""

        if reset_session:
            self.reset_session(keep_manifest=True)
        filt = self._coerce_filters(filters)
        fusion_cfg = (
            fusion
            if isinstance(fusion, FusionConfig)
            else FusionConfig.from_mapping(fusion)
            if fusion is not None
            else self.fusion
        )
        top_k = _require_positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise StateLawsQueryInputError(f"top_k must be <= {MAX_TOP_K}")

        window = (
            top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k))
        )

        bm25_result = self.search.bm25_search(
            query,
            top_k=window,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=False,
            enforce_sparse_io=False,
        )
        vector_result = self.search.vector_search(
            query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
            top_k=window,
            candidate_centroids=candidate_centroids,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=False,
            enforce_sparse_io=False,
        )

        compatible = rankings_are_compatible(
            bm25_result.results, vector_result.results
        )
        fused = fuse_hybrid_results(
            bm25_result.results,
            vector_result.results,
            config=fusion_cfg,
            top_k=window,
        )
        fused = apply_legal_filters(fused, filt)
        fused = stable_rank(fused, top_k=top_k)

        for hit in fused:
            if "component_scores" not in hit:
                hit["component_scores"] = {
                    "bm25": float(hit.get("bm25_score") or 0.0),
                    "vector": float(hit.get("vector_score") or 0.0),
                }
            if "bm25_score" not in hit:
                hit["bm25_score"] = hit["component_scores"]["bm25"]
            if "vector_score" not in hit:
                hit["vector_score"] = hit["component_scores"]["vector"]
            hit["fusion_stage"] = fusion_cfg.stage

        complete = bm25_result.complete and vector_result.complete
        stop_reason = (
            self.engine._stop_reason
            or bm25_result.stop_reason
            or vector_result.stop_reason
        )
        fetch_trace = self.engine.fetch_trace()
        explain = {
            "bm25_result_count": bm25_result.result_count,
            "bm25_route_policy": BM25_ROUTE_POLICY,
            "compatible_rankings": compatible,
            "component_scores_preserved": True,
            "fusion": fusion_cfg.to_dict(),
            "fusion_policy": HYBRID_FUSION_POLICY,
            "fusion_stage": fusion_cfg.stage,
            "hit_component_scores": [
                {
                    "bm25_score": hit.get("bm25_score"),
                    "chunk_cid": hit.get("chunk_cid"),
                    "component_scores": dict(hit.get("component_scores") or {}),
                    "entry_cid": hit.get("entry_cid"),
                    "score": hit.get("score"),
                    "vector_score": hit.get("vector_score"),
                }
                for hit in fused
            ],
            "legal_filters": filt.to_dict(),
            "ranking": "score_desc_entry_cid_document_index",
            "vector_result_count": vector_result.result_count,
            "vector_route_policy": VECTOR_ROUTE_POLICY,
        }
        diagnostics = {
            "bm25": {
                "complete": bm25_result.complete,
                "result_count": bm25_result.result_count,
                "route_policy": BM25_ROUTE_POLICY,
                "stop_reason": bm25_result.stop_reason,
            },
            "compatible_rankings": compatible,
            "fusion": fusion_cfg.to_dict(),
            "fusion_stage": fusion_cfg.stage,
            "public_mode": "hybrid_search",
            "vector": {
                "complete": vector_result.complete,
                "result_count": vector_result.result_count,
                "route_policy": VECTOR_ROUTE_POLICY,
                "stop_reason": vector_result.stop_reason,
            },
        }
        return StateLawsQueryResult(
            mode="hybrid",
            query=str(query or ""),
            results=tuple(fused),
            diagnostics=diagnostics,
            fetch_trace=fetch_trace,
            complete=complete and stop_reason is None,
            stop_reason=stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            explain=explain,
            filters=filt.to_dict(),
            model_space=dict(vector_result.model_space),
            edges=(),
            sparse_io=sparse_io_summary(fetch_trace),
        )

    def neighbors(
        self,
        node_cid: str,
        *,
        direction: str = "out",
        limit: int = 25,
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """Bounded neighbors with sealed legal/similarity authority labels."""

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(node_cid, "node_cid")
        limit = _require_positive_int(limit, "limit")
        wanted = tuple(
            str(value).strip() for value in edge_types if str(value).strip()
        )
        if not include_similarity and not wanted:
            wanted = tuple(sorted(LEGAL_EDGE_TYPE_NAMES))

        try:
            self.engine._manifest_required()
            raw_edges = self.engine.fetch_adjacency(
                start,
                direction=direction,
                limit=limit,
                edge_types=wanted,
            )
        except QueryBudgetExhausted as exc:
            return StateLawsQueryResult(
                mode="neighbors",
                query=start,
                results=(),
                diagnostics={"budget_exhausted": exc.to_dict()},
                fetch_trace=self.engine.fetch_trace(),
                complete=False,
                stop_reason=exc.dimension,
                usage=self.engine.usage.snapshot(),
                limits=self.engine.limits.to_dict(),
                explain={"similarity_edge_semantics": similarity_edge_semantics()},
                edges=(),
                sparse_io=sparse_io_summary(self.engine.fetch_trace()),
            )

        annotated: list[dict[str, Any]] = []
        for edge in raw_edges:
            if not include_similarity and is_similarity_edge_type(
                str(edge.get("edge_type") or "")
            ):
                continue
            annotated.append(annotate_edge_authority(edge))
        assert_no_similarity_as_legal_authority(annotated)

        neighbor_nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for edge in annotated:
            neighbor = str(edge.get("neighbor_cid") or "")
            if not neighbor or neighbor in seen:
                continue
            seen.add(neighbor)
            neighbor_nodes.append(
                {
                    "depth": 1,
                    "edge_type": edge.get("edge_type"),
                    "legal_authority": edge.get("legal_authority"),
                    "node_cid": neighbor,
                    "score": edge.get("score"),
                }
            )

        stop_reason = self.engine._stop_reason
        return StateLawsQueryResult(
            mode="neighbors",
            query=start,
            results=tuple(neighbor_nodes),
            diagnostics={
                "direction": direction,
                "edge_count": len(annotated),
                "include_similarity": include_similarity,
                "limit": limit,
                "node_cid": start,
                "stop_reason": stop_reason,
            },
            fetch_trace=self.engine.fetch_trace(),
            complete=stop_reason is None,
            stop_reason=stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            explain={
                "similarity_edge_semantics": similarity_edge_semantics(),
                "similarity_never_legal_authority": True,
            },
            edges=tuple(annotated),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )

    def graph_walk(
        self,
        start_node_cid: str,
        *,
        direction: str = "out",
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        per_node_limit: int = DEFAULT_PER_NODE_LIMIT,
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """Bounded structural walk enforcing every budget dimension."""

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(start_node_cid, "start_node_cid")
        wanted = [
            str(value).strip() for value in edge_types if str(value).strip()
        ]
        if not include_similarity and not wanted:
            wanted = sorted(LEGAL_EDGE_TYPE_NAMES)

        engine_result = self.engine.graph_walk(
            start,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            per_node_limit=per_node_limit,
            edge_types=wanted,
        )
        raw_edges = list(engine_result.diagnostics.get("edges") or [])
        annotated: list[dict[str, Any]] = []
        for edge in raw_edges:
            if not include_similarity and is_similarity_edge_type(
                str(edge.get("edge_type") or "")
            ):
                continue
            annotated.append(annotate_edge_authority(edge))
        assert_no_similarity_as_legal_authority(annotated)

        usage = self.engine.usage.snapshot()
        limits = self.engine.limits.to_dict()
        stop_reason = engine_result.stop_reason
        for dimension in BUDGET_DIMENSIONS:
            limit_key = f"max_{dimension}" if dimension != "time" else "max_time_ms"
            usage_key = dimension if dimension != "time" else "time_ms"
            if usage_key not in usage or limit_key not in limits:
                continue
            if int(usage.get(usage_key) or 0) > int(limits[limit_key]):
                stop_reason = stop_reason or dimension

        diagnostics = dict(engine_result.diagnostics)
        diagnostics["edges"] = annotated
        diagnostics["edge_count"] = len(annotated)
        diagnostics["budgets_enforced"] = list(BUDGET_DIMENSIONS)
        diagnostics["traversal_budgets"] = list(TRAVERSAL_BUDGET_DIMENSIONS)
        diagnostics["include_similarity"] = include_similarity
        diagnostics["similarity_edge_semantics"] = similarity_edge_semantics()

        return StateLawsQueryResult(
            mode="graph_walk",
            query=start,
            results=tuple(dict(item) for item in engine_result.results),
            diagnostics=diagnostics,
            fetch_trace=self.engine.fetch_trace(),
            complete=stop_reason is None,
            stop_reason=stop_reason,
            usage=usage,
            limits=limits,
            explain={
                "budgets_enforced": list(BUDGET_DIMENSIONS),
                "mode_alias": "bounded_graph",
                "similarity_edge_semantics": similarity_edge_semantics(),
                "similarity_never_legal_authority": True,
                "traversal_budgets": list(TRAVERSAL_BUDGET_DIMENSIONS),
                "walk_strategy": "structural_bfs",
            },
            edges=tuple(annotated),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )

    def bounded_graph_walk(
        self,
        start_node_cid: str,
        **kwargs: Any,
    ) -> StateLawsQueryResult:
        """Alias for :meth:`graph_walk` (bounded graph mode)."""

        return self.graph_walk(start_node_cid, **kwargs)

    def _load_vector_meta(self) -> list[dict[str, Any]]:
        if self._vector_meta is not None:
            return self._vector_meta
        meta = self.engine.load_routing_index(
            VECTOR_INDEX_NAME, reason="routing_index"
        )
        self._vector_meta = [dict(row) for row in meta]
        return self._vector_meta

    def _load_locator_meta(self) -> list[dict[str, Any]]:
        if self._locator_meta is not None:
            return self._locator_meta
        meta = self.engine.load_routing_index(
            ENTRY_LOCATOR_INDEX_NAME, reason="routing_index"
        )
        self._locator_meta = [dict(row) for row in meta]
        return self._locator_meta

    def _vector_descriptor_for_path(self, path: str) -> Mapping[str, Any] | None:
        for row in self._load_vector_meta():
            if str(row.get("relative_path") or "") == path:
                return row
        return None

    def _probe_centroid_paths(
        self,
        query_vector: Sequence[float],
        *,
        candidate_centroids: int,
    ) -> set[str]:
        """Record centroid-selected paths without downloading vector data."""

        routes = self.engine.route_vector_centroids(
            query_vector,
            candidate_centroids=candidate_centroids,
        )
        paths = {route.relative_path for route in routes}
        self._centroid_routed_paths = set(paths)
        for route in routes:
            _ = RouteJustification(
                family="vectors",
                reason="centroid_probe",
                relative_path=route.relative_path,
                keys=(f"cluster:{route.cluster_id}",),
                score=route.score,
                metadata={"fetch_policy": "centroid_probe_only"},
            )
        return paths

    def fetch_frontier_vectors(
        self,
        node_cids: Sequence[str],
        *,
        query_vector: Sequence[float] | None = None,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    ) -> dict[str, tuple[float, ...]]:
        """Hydrate frontier embeddings through the dedicated entry locator."""

        wanted = [
            str(cid).strip()
            for cid in node_cids
            if str(cid or "").strip() and str(cid).strip() not in self._vector_cache
        ]
        if not wanted:
            return {
                cid: self._vector_cache[cid]
                for cid in node_cids
                if str(cid).strip() in self._vector_cache
            }

        if query_vector is not None and not self._centroid_routed_paths:
            self._probe_centroid_paths(
                query_vector, candidate_centroids=candidate_centroids
            )

        locator_meta = self._load_locator_meta()
        key_to_page = select_entry_locator_pages_for_keys(locator_meta, wanted)
        pages_by_path: dict[str, list[str]] = defaultdict(list)
        page_descriptors: dict[str, Mapping[str, Any]] = {}
        for key, descriptor in key_to_page.items():
            path = str(descriptor.get("relative_path") or "")
            if not path:
                continue
            pages_by_path[path].append(key)
            page_descriptors[path] = descriptor

        locations_by_key: dict[str, list[dict[str, Any]]] = {}
        for path, keys in sorted(pages_by_path.items()):
            descriptor = page_descriptors[path]
            self._locator_page_paths.add(path)
            route = RouteJustification(
                family="routing_index",
                reason="hydrate_hit",
                relative_path=path,
                keys=tuple(sorted(keys)),
                metadata={
                    "fetch_policy": FRONTIER_HYDRATION_POLICY,
                    "locator_key": ENTRY_LOCATOR_KEY,
                    "shard_id": descriptor.get("shard_id"),
                    "vector_shard_keys_are_lexical_ranges": (
                        VECTOR_SHARD_KEYS_ARE_LEXICAL_RANGES
                    ),
                },
            )
            try:
                artifact = self.engine.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                )
            except QueryBudgetExhausted as exc:
                self.engine._stop_reason = exc.dimension
                break
            rows = self.engine._read_rows(artifact, descriptor=descriptor)
            parsed = parse_entry_locator_locations(rows, keys)
            for key, locations in parsed.items():
                locations_by_key.setdefault(key, []).extend(locations)

        by_path: dict[str, list[str]] = defaultdict(list)
        for key, locations in locations_by_key.items():
            for location in locations:
                path = str(location.get("relative_path") or "")
                if path:
                    by_path[path].append(key)

        for path, keys in sorted(by_path.items()):
            descriptor = self._vector_descriptor_for_path(path)
            if descriptor is None:
                raise EntryLocatorError(
                    f"entry locator pointed at unknown vector shard {path}"
                )
            off_centroid = path not in self._centroid_routed_paths
            self._frontier_fetch_paths.add(path)
            if off_centroid:
                self._off_centroid_fetch_paths.add(path)
            route = RouteJustification(
                family="vectors",
                reason="exact_vector_score",
                relative_path=path,
                keys=tuple(sorted(set(keys))),
                metadata={
                    "fetch_policy": FRONTIER_HYDRATION_POLICY,
                    "locator_key": ENTRY_LOCATOR_KEY,
                    "off_centroid": off_centroid,
                    "shard_id": descriptor.get("shard_id"),
                    "vector_shard_keys_are_lexical_ranges": (
                        VECTOR_SHARD_KEYS_ARE_LEXICAL_RANGES
                    ),
                },
            )
            try:
                artifact = self.engine.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                )
            except QueryBudgetExhausted as exc:
                self.engine._stop_reason = exc.dimension
                break
            rows = self.engine._read_rows(artifact, descriptor=descriptor)
            wanted_set = set(keys)
            for row in rows:
                entry_cid = str(row.get("entry_cid") or "")
                if entry_cid not in wanted_set:
                    for candidate_key in ("node_cid", "chunk_cid"):
                        value = str(row.get(candidate_key) or "")
                        if value in wanted_set:
                            entry_cid = value
                            break
                if entry_cid not in wanted_set:
                    continue
                embedding = row.get("embedding")
                if embedding is None:
                    continue
                try:
                    vector = tuple(float(x) for x in embedding)
                except (TypeError, ValueError):
                    continue
                self._vector_cache[entry_cid] = vector
                self.engine.usage.charge(rows=1)

        return {
            cid: self._vector_cache[cid]
            for cid in node_cids
            if str(cid).strip() in self._vector_cache
        }

    def semantic_graph_walk(
        self,
        start_node_cid: str,
        *,
        query: str = "",
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        direction: str = "out",
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        beam: SemanticBeamConfig | Mapping[str, Any] | None = None,
        reset_session: bool = True,
    ) -> StateLawsQueryResult:
        """Embedding-guided beam walk with entry-locator frontier hydration."""

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(start_node_cid, "start_node_cid")
        if isinstance(beam, SemanticBeamConfig):
            beam_cfg = beam
        elif beam is None:
            beam_cfg = SemanticBeamConfig()
        else:
            if not isinstance(beam, Mapping):
                raise StateLawsQueryInputError(
                    "beam config must be a mapping"
                )
            beam_cfg = SemanticBeamConfig(
                **{
                    key: beam[key]
                    for key in (
                        "max_depth",
                        "max_nodes",
                        "max_edges",
                        "per_node_limit",
                        "beam_width",
                        "proximity_weight",
                        "edge_weight",
                        "path_penalty",
                        "candidate_centroids",
                    )
                    if key in beam
                }
            )

        vector, release = self.search.resolve_query_vector(
            query=query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
        )

        depth_limit = beam_cfg.max_depth
        if depth_limit > self.engine.limits.max_depth:
            depth_limit = self.engine.limits.max_depth
        node_limit = beam_cfg.max_nodes or self.engine.limits.max_nodes
        edge_limit = beam_cfg.max_edges or self.engine.limits.max_edges
        node_limit = min(node_limit, self.engine.limits.max_nodes)
        edge_limit = min(edge_limit, self.engine.limits.max_edges)
        beam_width = min(beam_cfg.beam_width, node_limit)

        wanted_types = {
            str(value).strip() for value in edge_types if str(value).strip()
        }
        if not include_similarity and not wanted_types:
            wanted_types = set(LEGAL_EDGE_TYPE_NAMES)

        try:
            self.engine._manifest_required()
            self._probe_centroid_paths(
                vector,
                candidate_centroids=beam_cfg.candidate_centroids,
            )
        except QueryBudgetExhausted as exc:
            return StateLawsQueryResult(
                mode="semantic_graph_walk",
                query=str(query or start),
                results=(),
                diagnostics={"budget_exhausted": exc.to_dict()},
                fetch_trace=self.engine.fetch_trace(),
                complete=False,
                stop_reason=exc.dimension,
                usage=self.engine.usage.snapshot(),
                limits=self.engine.limits.to_dict(),
                explain={"traversal_strategy": "semantic_beam"},
                model_space=release.to_dict(),
                edges=(),
                sparse_io=sparse_io_summary(self.engine.fetch_trace()),
            )

        self.engine.usage.charge(nodes=1, depth=0)
        self.fetch_frontier_vectors(
            [start],
            query_vector=vector,
            candidate_centroids=beam_cfg.candidate_centroids,
        )
        seed_embedding = self._vector_cache.get(start)
        seed_proximity = cosine_similarity(seed_embedding, vector)

        total_w = (
            beam_cfg.proximity_weight
            + beam_cfg.edge_weight
            + beam_cfg.path_penalty
        )
        seed_score = (
            beam_cfg.proximity_weight * max(0.0, seed_proximity)
            + beam_cfg.edge_weight * 1.0
            + beam_cfg.path_penalty * 1.0
        ) / total_w

        visited: dict[str, dict[str, Any]] = {
            start: {
                "depth": 0,
                "edge_weight": 1.0,
                "edge_type": None,
                "from_node_cid": None,
                "has_embedding": seed_embedding is not None,
                "node_cid": start,
                "score": seed_score,
                "semantic_proximity": seed_proximity,
            }
        }
        traversed: list[dict[str, Any]] = []
        frontier: list[str] = [start]
        stop_reason: str | None = "depth" if depth_limit == 0 else None

        try:
            for depth in range(depth_limit):
                projected = depth + 1
                exhausted = self.engine.usage.check(
                    self.engine.limits,
                    projected_depth=projected,
                    raise_on_exhaustion=False,
                )
                if exhausted is not None:
                    stop_reason = exhausted
                    break

                candidates: list[
                    tuple[float, str, dict[str, Any], dict[str, Any]]
                ] = []
                for node_cid in frontier:
                    try:
                        edges = self.engine.fetch_adjacency(
                            node_cid,
                            direction=direction,
                            limit=beam_cfg.per_node_limit,
                            edge_types=tuple(sorted(wanted_types))
                            if wanted_types
                            else (),
                        )
                    except QueryBudgetExhausted as exc:
                        stop_reason = exc.dimension
                        frontier = []
                        break
                    if self.engine._stop_reason is not None:
                        stop_reason = self.engine._stop_reason
                        frontier = []
                        break

                    neighbor_ids = [
                        str(edge.get("neighbor_cid") or "")
                        for edge in edges
                        if edge.get("neighbor_cid")
                    ]
                    if neighbor_ids:
                        self.fetch_frontier_vectors(
                            neighbor_ids,
                            query_vector=vector,
                            candidate_centroids=beam_cfg.candidate_centroids,
                        )
                    if self.engine._stop_reason is not None:
                        stop_reason = self.engine._stop_reason
                        frontier = []
                        break

                    for edge in edges:
                        neighbor = str(edge.get("neighbor_cid") or "")
                        if not neighbor:
                            continue
                        edge_type = str(edge.get("edge_type") or "")
                        if (
                            not include_similarity
                            and is_similarity_edge_type(edge_type)
                        ):
                            continue
                        if wanted_types and edge_type not in wanted_types:
                            continue
                        emb = self._vector_cache.get(neighbor)
                        proximity = cosine_similarity(emb, vector)
                        proximity_unit = (proximity + 1.0) / 2.0
                        e_weight = _edge_weight_score(edge)
                        depth_factor = 1.0 / (1.0 + projected)
                        score = (
                            beam_cfg.proximity_weight * proximity_unit
                            + beam_cfg.edge_weight * e_weight
                            + beam_cfg.path_penalty * depth_factor
                        ) / total_w
                        annotated = annotate_edge_authority(
                            {
                                **edge,
                                "depth": projected,
                                "from_node_cid": node_cid,
                                "semantic_proximity": proximity,
                                "semantic_score": score,
                            }
                        )
                        candidates.append(
                            (
                                score,
                                neighbor,
                                {
                                    "depth": projected,
                                    "edge_weight": e_weight,
                                    "edge_type": edge_type,
                                    "from_node_cid": node_cid,
                                    "has_embedding": emb is not None,
                                    "node_cid": neighbor,
                                    "score": score,
                                    "semantic_proximity": proximity,
                                },
                                annotated,
                            )
                        )

                if stop_reason is not None:
                    break

                candidates.sort(
                    key=lambda item: (
                        -item[0],
                        item[1],
                        str(item[3].get("edge_cid") or ""),
                    )
                )
                next_frontier: list[str] = []
                for score, neighbor, node_payload, edge_payload in candidates:
                    if len(traversed) >= edge_limit:
                        stop_reason = "edges"
                        break
                    if neighbor not in visited:
                        if len(visited) >= node_limit:
                            stop_reason = "nodes"
                            break
                        visited[neighbor] = node_payload
                        next_frontier.append(neighbor)
                        self.engine.usage.charge(nodes=1, depth=projected)
                    elif score > float(visited[neighbor].get("score") or 0.0):
                        visited[neighbor] = {
                            **visited[neighbor],
                            **node_payload,
                        }
                    traversed.append(edge_payload)
                    if len(next_frontier) >= beam_width:
                        break

                if stop_reason is not None:
                    break
                frontier = next_frontier[:beam_width]
                if not frontier:
                    stop_reason = None
                    break
                self.engine.usage.charge(depth=projected)
            else:
                if stop_reason is None and depth_limit > 0 and frontier:
                    stop_reason = "depth"
        except QueryBudgetExhausted as exc:
            stop_reason = exc.dimension

        assert_no_similarity_as_legal_authority(traversed)

        nodes = [
            dict(payload)
            for _, payload in sorted(
                visited.items(),
                key=lambda item: (
                    int(item[1].get("depth") or 0),
                    -float(item[1].get("score") or 0.0),
                    item[0],
                ),
            )
        ]
        complete = stop_reason is None
        usage = self.engine.usage.snapshot()
        limits = self.engine.limits.to_dict()
        diagnostics = {
            "beam_width": beam_width,
            "budgets_enforced": list(BUDGET_DIMENSIONS),
            "candidate_centroids": beam_cfg.candidate_centroids,
            "centroid_routed_paths": sorted(self._centroid_routed_paths),
            "complete": complete,
            "direction": direction,
            "edge_count": len(traversed),
            "entry_locator_pages_fetched": sorted(self._locator_page_paths),
            "frontier_fetch_paths": sorted(self._frontier_fetch_paths),
            "frontier_hydration_policy": FRONTIER_HYDRATION_POLICY,
            "include_similarity": include_similarity,
            "max_depth": depth_limit,
            "max_edges": edge_limit,
            "max_nodes": node_limit,
            "node_count": len(visited),
            "off_centroid_fetch_paths": sorted(self._off_centroid_fetch_paths),
            "off_centroid_frontier_vectors_fetched": bool(
                self._off_centroid_fetch_paths
            ),
            "per_node_limit": beam_cfg.per_node_limit,
            "start_node_cid": start,
            "stop_reason": stop_reason,
            "traversal_budgets": list(TRAVERSAL_BUDGET_DIMENSIONS),
            "traversal_strategy": "semantic_beam",
            "vector_cache_size": len(self._vector_cache),
            "vector_shard_keys_are_lexical_ranges": False,
        }
        explain = {
            "beam": beam_cfg.to_dict(),
            "blend": {
                "edge_weight": beam_cfg.edge_weight,
                "path_penalty": beam_cfg.path_penalty,
                "proximity_weight": beam_cfg.proximity_weight,
            },
            "budgets_enforced": list(BUDGET_DIMENSIONS),
            "entry_locator_frontier_fetch": True,
            "frontier_hydration_policy": FRONTIER_HYDRATION_POLICY,
            "mode_alias": "semantic_graph",
            "off_centroid_selective_fetch": True,
            "similarity_edge_semantics": similarity_edge_semantics(),
            "similarity_never_legal_authority": True,
            "traversal_budgets": list(TRAVERSAL_BUDGET_DIMENSIONS),
            "traversal_strategy": "semantic_beam",
            "vector_shard_keys_are_lexical_ranges": False,
            "vector_space_id": release.vector_space_id,
        }
        return StateLawsQueryResult(
            mode="semantic_graph_walk",
            query=str(query or start),
            results=tuple(nodes),
            diagnostics=diagnostics,
            fetch_trace=self.engine.fetch_trace(),
            complete=complete,
            stop_reason=stop_reason,
            usage=usage,
            limits=limits,
            explain=explain,
            model_space=release.to_dict(),
            edges=tuple(traversed),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )

    def semantic_graph(
        self,
        start_node_cid: str,
        **kwargs: Any,
    ) -> StateLawsQueryResult:
        """Alias for :meth:`semantic_graph_walk`."""

        return self.semantic_graph_walk(start_node_cid, **kwargs)


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------


def hybrid_search(
    client: StateLawsQueryClient,
    query: str,
    **kwargs: Any,
) -> StateLawsQueryResult:
    """Module-level hybrid search entry point."""

    return client.hybrid_search(query, **kwargs)


def neighbors(
    client: StateLawsQueryClient,
    node_cid: str,
    **kwargs: Any,
) -> StateLawsQueryResult:
    """Module-level neighbors entry point."""

    return client.neighbors(node_cid, **kwargs)


def graph_walk(
    client: StateLawsQueryClient,
    start_node_cid: str,
    **kwargs: Any,
) -> StateLawsQueryResult:
    """Module-level structural graph walk entry point."""

    return client.graph_walk(start_node_cid, **kwargs)


def semantic_graph_walk(
    client: StateLawsQueryClient,
    start_node_cid: str,
    **kwargs: Any,
) -> StateLawsQueryResult:
    """Module-level semantic beam walk entry point."""

    return client.semantic_graph_walk(start_node_cid, **kwargs)


# ---------------------------------------------------------------------------
# Query contract
# ---------------------------------------------------------------------------


def default_query_contract_path() -> Path:
    """Repository path for the sealed state-law query contract."""

    return DEFAULT_REPORT_PATH


def build_query_contract_payload() -> dict[str, Any]:
    """Deterministic software-contract payload for LCR-033."""

    payload = {
        "acceptance": {
            "bm25_routes_by_lexicographic_term_ranges": True,
            "dense_retrieval_probes_evaluated_centroids": True,
            "hybrid_scores_late_fuse_compatible_rankings": True,
            "hub_upload": False,
            "immutable_pin_required": True,
            "no_mutable_main_default": True,
            "only_justified_routed_shards_are_fetched": True,
            "secrets_absent": True,
            "semantic_graph_traversal_hydrates_frontier_through_entry_locator": True,
            "similarity_and_bm25_neighbors_are_not_legal_authority": True,
            "traversal_budgets_include_depth_node_edge_shard_byte_time": True,
        },
        "adr_path": ADR_PATH,
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": {
            "acceptance_budget_names": list(ACCEPTANCE_BUDGET_NAMES),
            "budget_dimensions": list(BUDGET_DIMENSIONS),
            "default_beam_width": DEFAULT_BEAM_WIDTH,
            "default_bm25_weight": DEFAULT_BM25_WEIGHT,
            "default_candidate_centroids": SCHEMA_DEFAULT_CANDIDATE_CENTROIDS,
            "default_rrf_k": DEFAULT_RRF_K,
            "default_top_k": DEFAULT_TOP_K,
            "default_vector_weight": DEFAULT_VECTOR_WEIGHT,
            "fusion_methods": sorted(FUSION_METHODS),
            "fusion_stage": FUSION_STAGE,
            "max_top_k": MAX_TOP_K,
            "traversal_budgets": list(TRAVERSAL_BUDGET_DIMENSIONS),
            "vector_shard_first_last_keys_are_lexical_ranges": False,
        },
        "bundle": BUNDLE,
        "checks": {
            "bm25_primary_key": BM25_PRIMARY_KEY,
            "bm25_route_policy": BM25_ROUTE_POLICY,
            "bm25_task_id": BM25_TASK_ID,
            "bm25_tokenizer_id": BM25_TOKENIZER_ID,
            "component_scores_preserved": True,
            "entry_locator_index": ENTRY_LOCATOR_INDEX_NAME,
            "entry_locator_key": ENTRY_LOCATOR_KEY,
            "frontier_hydration_policy": FRONTIER_HYDRATION_POLICY,
            "fusion_policy": HYBRID_FUSION_POLICY,
            "fusion_stage": FUSION_STAGE,
            "graph_task_id": GRAPH_TASK_ID,
            "hf_release_task_id": HF_RELEASE_TASK_ID,
            "hub_upload": False,
            "immutable_pin_required": True,
            "no_hub_upload": True,
            "no_mutable_main_default": True,
            "secrets_absent": True,
            "similarity_never_legal_authority": True,
            "traversal_budgets_present": True,
            "vector_primary_key": VECTOR_PRIMARY_KEY,
            "vector_route_policy": VECTOR_ROUTE_POLICY,
            "vector_shard_keys_are_lexical_ranges": False,
            "vectors_task_id": VECTORS_TASK_ID,
        },
        "code_version": CODE_VERSION,
        "consumed_modules": {
            "adjacency": "state_laws_adjacency",
            "bm25": "state_laws_bm25",
            "graph": "state_laws_graph",
            "hf_release": "state_laws_hf_release",
            "vectors": "state_laws_vectors",
        },
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "depends_on": list(DEPENDS_ON),
        "description": (
            "Software-contract for LCR-033 bounded immutable-Hub state-law "
            "queries. BM25 routes by lexicographic term ranges, dense "
            "retrieval probes evaluated centroids, hybrid scores late-fuse "
            "compatible rankings, and semantic graph traversal hydrates "
            "frontier vectors through the dedicated entry locator under "
            "depth, node, edge, shard, byte, row, and time budgets. "
            "Jurisdiction, code, and citation filters overlay every public "
            "mode. Similarity and BM25 neighbors are not legal authority. "
            "Immutable pins are required; mutable refs such as main are "
            "rejected. This contract does not authorize Hub upload or "
            "publication."
        ),
        "filters": list(QUERY_FILTERS),
        "fusion": {
            "methods": sorted(FUSION_METHODS),
            "policy": HYBRID_FUSION_POLICY,
            "preserves_component_scores": True,
            "stage": FUSION_STAGE,
        },
        "goal_id": GOAL_ID,
        "hub_upload": HUB_UPLOAD,
        "immutable_pin_required": IMMUTABLE_PIN_REQUIRED,
        "indexes": {
            "bm25": BM25_INDEX_NAME,
            "entry_locator": ENTRY_LOCATOR_INDEX_NAME,
            "vectors": VECTOR_INDEX_NAME,
        },
        "mode_aliases": {
            "bounded_graph": "graph_walk",
            "semantic_graph": "semantic_graph_walk",
        },
        "modes": list(QUERY_MODES),
        "no_mutable_main_default": NO_MUTABLE_MAIN_DEFAULT,
        "pinned_model_id": PINNED_MODEL_ID,
        "pinned_model_revision": PINNED_MODEL_REVISION,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
        "query_schema_version": SCHEMA_VERSION,
        "release_profile": RELEASE_PROFILE,
        "report_schema": REPORT_SCHEMA,
        "route_families": sorted(ROUTE_FAMILIES),
        "route_reasons": sorted(ROUTE_REASONS),
        "routing": {
            "bm25": BM25_ROUTE_POLICY,
            "frontier_hydration": FRONTIER_HYDRATION_POLICY,
            "hybrid": HYBRID_FUSION_POLICY,
            "vector": VECTOR_ROUTE_POLICY,
        },
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "secrets_absent": SECRETS_ABSENT,
        "similarity_edge_semantics": similarity_edge_semantics(),
        "task_id": TASK_ID,
        "traversal_budgets": list(TRAVERSAL_BUDGET_DIMENSIONS),
    }
    assert_no_secrets(payload, context="query_contract")
    payload["contract_cid"] = f"sha256:{digest_mapping(payload)}"
    assert_no_secrets(payload, context="query_contract")
    return payload


def load_query_contract(path: str | Path | None = None) -> dict[str, Any]:
    """Load and lightly validate the sealed query contract."""

    target = Path(path) if path is not None else default_query_contract_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise StateLawsQueryInputError("query contract must be an object")
    if payload.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise StateLawsQueryInputError(
            "query contract schema_version mismatch"
        )
    if payload.get("task_id") != TASK_ID:
        raise StateLawsQueryInputError("query contract task_id mismatch")
    if payload.get("goal_id") != GOAL_ID:
        raise StateLawsQueryInputError("query contract goal_id mismatch")
    if payload.get("hub_upload") is not False:
        raise StateLawsQueryInputError("query contract hub_upload must be false")
    if payload.get("authorizing_for_publication") is not False:
        raise StateLawsQueryInputError(
            "query contract authorizing_for_publication must be false"
        )
    if payload.get("immutable_pin_required") is not True:
        raise StateLawsQueryInputError(
            "query contract must require an immutable pin"
        )
    if payload.get("no_mutable_main_default") is not True:
        raise StateLawsQueryInputError(
            "query contract must reject mutable main defaults"
        )
    if payload.get("secrets_absent") is not True:
        raise StateLawsQueryInputError(
            "query contract secrets_absent must be true"
        )
    assert_no_secrets(payload, context="query_contract")
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise StateLawsQueryInputError("query contract missing acceptance")
    required = {
        "bm25_routes_by_lexicographic_term_ranges",
        "dense_retrieval_probes_evaluated_centroids",
        "hybrid_scores_late_fuse_compatible_rankings",
        "semantic_graph_traversal_hydrates_frontier_through_entry_locator",
        "traversal_budgets_include_depth_node_edge_shard_byte_time",
        "hub_upload",
        "secrets_absent",
        "immutable_pin_required",
        "no_mutable_main_default",
    }
    missing = required - set(acceptance)
    if missing:
        raise StateLawsQueryInputError(
            f"query contract missing acceptance keys: {sorted(missing)}"
        )
    return dict(payload)


def write_query_contract(path: str | Path | None = None) -> Path:
    """Write the sealed query contract (deterministic, no timestamps)."""

    target = Path(path) if path is not None else default_query_contract_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_query_contract_payload()
    assert_no_secrets(payload, context="query_contract")
    return write_json_atomic(target, payload)


__all__ = [
    "ACCEPTANCE_BUDGET_NAMES",
    "AUTHORITY_LEGAL",
    "AUTHORITY_NON_AUTHORITATIVE",
    "BM25_ROUTE_POLICY",
    "CONSUMED_PRODUCERS",
    "CONTRACT_SCHEMA_VERSION",
    "DEFAULT_BEAM_WIDTH",
    "DEFAULT_BM25_WEIGHT",
    "DEFAULT_RRF_K",
    "DEFAULT_VECTOR_WEIGHT",
    "ENTRY_LOCATOR_INDEX_NAME",
    "ENTRY_LOCATOR_KEY",
    "FRONTIER_HYDRATION_POLICY",
    "FUSION_METHODS",
    "FUSION_RRF",
    "FUSION_STAGE",
    "FUSION_WEIGHTED",
    "GOAL_ID",
    "HUB_UPLOAD",
    "HYBRID_FUSION_POLICY",
    "LEGAL_EDGE_TYPE_NAMES",
    "PROGRAM_ID",
    "QUERY_FILTERS",
    "QUERY_MODES",
    "SCHEMA_VERSION",
    "SIMILARITY_EDGE_TYPE_NAMES",
    "TASK_ID",
    "TRAVERSAL_BUDGET_DIMENSIONS",
    "VECTOR_ROUTE_POLICY",
    "EntryLocatorError",
    "StateLawsQueryClient",
    "StateLawsQueryError",
    "StateLawsQueryInputError",
    "StateLawsQueryResult",
    "FusionConfig",
    "FusionConfigError",
    "ImmutablePinError",
    "LegalAuthorityCollisionError",
    "LegalFilters",
    "SemanticBeamConfig",
    "annotate_edge_authority",
    "apply_legal_filters",
    "assert_no_similarity_as_legal_authority",
    "build_query_contract_payload",
    "classify_edge_authority",
    "cosine_similarity",
    "default_query_contract_path",
    "edge_class_for_type",
    "fuse_hybrid_results",
    "graph_walk",
    "hit_matches_legal_filters",
    "hybrid_search",
    "is_legal_edge_type",
    "is_similarity_edge_type",
    "load_query_contract",
    "neighbors",
    "parse_entry_locator_locations",
    "query_replay_fingerprint",
    "rankings_are_compatible",
    "require_immutable_revision",
    "select_entry_locator_pages_for_keys",
    "select_term_range_shards",
    "semantic_graph_walk",
    "similarity_edge_semantics",
    "vector_shard_lexical_range_would_miss",
    "write_query_contract",
]
