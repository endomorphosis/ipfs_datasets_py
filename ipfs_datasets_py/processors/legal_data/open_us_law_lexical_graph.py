"""BM25-backed lexical graph and bounded two-way adjacency (OUL-031).

The BM25 inverted index is the canonical lexical graph. This module exposes:

* **virtual** term→document and document→term traversal through BM25
  postings (no durable edge materialization by default);
* optional deterministic, score-ordered, **bounded** top-K
  ``BM25_NEIGHBOR_OF`` edges whose candidates are accumulated from
  posting lists rather than all-pairs ``O(N^2)`` scans; and
* incoming and outgoing adjacency pages and physical shards with at most
  4,096 pointers or rows.

Design invariants
-----------------
* Vocabulary and postings are projected from the sealed
  :class:`~open_us_law_bm25.OpenUsLawBm25Index` posting cells. The
  inverted index is the source of truth; documents are not re-scanned
  to invent a second term-document graph.
* Default mode is
  ``virtual_term_document_edges_plus_bounded_bm25_neighbors``. Full
  term–document edge expansion is opt-in only.
* Neighbor materialization walks posting cells of the source document's
  query terms, scores only those candidates, and enforces
  ``neighbor_k`` / ``max_neighbors_per_document`` caps.
* Similarity edges carry ``authority=non_authoritative`` and
  ``proof_authority=False``. They cannot establish citation, amendment,
  or legal validity.
* Incoming and outgoing adjacency inverses reconcile. Every pointer
  resolves. Production pages and shards never exceed 4,096.

Physical adjacency paging belongs here (OUL-031). OUL-030 owns the
legal ontology projection only.

No network I/O and no Parquet I/O. Unit tests use compact sealed
recipes only. This receipt proves the software contract; it does not
claim the live exact-51 corpus has been graphed.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (
    FIELD_ORDER,
    PRIMARY_KEY,
    TOKENIZER_ID,
    Bm25Hit,
    LegalBm25Document,
    OpenUsLawBm25Config,
    OpenUsLawBm25Index,
    bind_fixture_bm25,
    fixture_bm25_chunks,
    fixture_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_graph import (
    EXACT_51_SEED_ROW_LOWER_BOUND,
    NON_AUTHORITATIVE_AUTHORITY,
    SECTION_LIKE,
    GraphEdgeClass,
    GraphEdgeType,
    OpenUsLawGraphNode,
    OpenUsLawGraphProjection,
    SimilarityNeighbor,
    fixture_seed_records,
    project_open_us_law_graph,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ADR_PATH as SCHEMA_ADR_PATH,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    TokenizerConfig,
    tokenize_legal_text,
)
from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (
    HierarchicalRouteIndex,
    RouteDescriptor,
    build_hierarchical_routes,
)

# ---------------------------------------------------------------------------
# Identity / pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-lexical-graph-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-graph-adjacency-receipt-v1"
TASK_ID: Final = "OUL-031"
GOAL_ID: Final = "OUL-G040"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "open_us_law_lexical_graph.py"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "lexical-graph"
ADR_PATH: Final = SCHEMA_ADR_PATH
RECEIPT_SEALED_AT: Final = "2026-08-16T00:00:00Z"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

REPORT_RELATIVE_PATH: Final = (
    "docs/reports/open_us_law_reindex/graph_adjacency_receipt.json"
)
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

LEXICAL_GRAPH_DEFAULT_MODE: Final = (
    "virtual_term_document_edges_plus_bounded_bm25_neighbors"
)
CANDIDATE_ACCUMULATION_METHOD: Final = "postings_driven"
FORBIDDEN_CANDIDATE_METHODS: Final = frozenset(
    {"all_pairs", "o_n_squared", "pairwise_scan", "full_corpus_scan"}
)

# Exact-51 seed observation. Durable expansion of every document-term
# pair at that scale must never be the default.
EXACT_51_DOCUMENT_TERM_PAIR_LOWER_BOUND: Final = EXACT_51_SEED_ROW_LOWER_BOUND

DEFAULT_NEIGHBOR_K: Final = 8
MAX_NEIGHBOR_K: Final = 64
DEFAULT_MAX_NEIGHBOR_QUERY_TERMS: Final = 16
DEFAULT_MIN_NEIGHBOR_TERM_LENGTH: Final = 3

DEFAULT_TEST_MAX_POINTERS_PER_PAGE: Final = 2
DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_ROUTE_PAGE_ROWS: Final = 2

EDGE_AUTHORITY: Final = NON_AUTHORITATIVE_AUTHORITY
EDGE_PROOF_AUTHORITY: Final = False
EDGE_TYPE_BM25_NEIGHBOR: Final = GraphEdgeType.BM25_NEIGHBOR_OF.value
EDGE_CLASS_SIMILARITY: Final = GraphEdgeClass.SIMILARITY.value
EDGE_METRIC_BM25: Final = "bm25"
RETRIEVAL_METHOD: Final = "bm25-field-weighted"

VIRTUAL_TERM_DOCUMENT_EDGE_TYPE: Final = "TERM_OCCURS_IN"
VIRTUAL_DOCUMENT_TERM_EDGE_TYPE: Final = "HAS_TERM"

OUTGOING_ADJACENCY_DIR: Final = "data/graph/adjacency/out"
INCOMING_ADJACENCY_DIR: Final = "data/graph/adjacency/in"
OUTGOING_ROUTE_DIR: Final = "indexes/graph_adjacency_out_routes"
INCOMING_ROUTE_DIR: Final = "indexes/graph_adjacency_in_routes"

RECOVERY_CONFIGURATIONS: Final = frozenset({"recovery", "quarantine"})

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawLexicalGraphError(ValueError):
    """Base error for lexical graph / adjacency failures."""

    code: str = "open_us_law_lexical_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class LexicalGraphConfigError(OpenUsLawLexicalGraphError):
    """Raised when lexical graph or adjacency configuration is invalid."""

    code = "config_invalid"


class LexicalGraphParityError(OpenUsLawLexicalGraphError):
    """Raised when overlay vocabulary/postings diverge from BM25."""

    code = "parity_invalid"


class LexicalGraphNeighborCapError(OpenUsLawLexicalGraphError):
    """Raised when neighbor materialization exceeds declared caps."""

    code = "neighbor_cap_exceeded"


class LexicalGraphExpansionError(OpenUsLawLexicalGraphError):
    """Raised when full durable term-document expansion is requested unsafely."""

    code = "expansion_refused"


class LexicalGraphLookupError(OpenUsLawLexicalGraphError):
    """Raised when a term or document is unknown to the overlay."""

    code = "lookup_invalid"


class LexicalGraphScanError(OpenUsLawLexicalGraphError):
    """Raised when neighbor search would perform an all-pairs scan."""

    code = "all_pairs_scan_refused"


class AdjacencyBoundError(OpenUsLawLexicalGraphError):
    """Raised when an adjacency page or shard exceeds the 4,096 bound."""

    code = "adjacency_bound_exceeded"


class AdjacencyReconciliationError(OpenUsLawLexicalGraphError):
    """Raised when incoming and outgoing adjacency inverses diverge."""

    code = "adjacency_unreconciled"


class AdjacencyReceiptError(OpenUsLawLexicalGraphError):
    """Raised when the adjacency receipt is missing or invalid."""

    code = "receipt_invalid"


class GraphReleaseAuthorizationError(OpenUsLawLexicalGraphError):
    """Raised when a software-contract receipt attempts to authorize release."""

    code = "release_authorization_forbidden"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LexicalEdgeKind(str, Enum):
    """Partition of lexical overlay edge kinds."""

    VIRTUAL_TERM_DOCUMENT = "virtual_term_document"
    BM25_NEIGHBOR = "bm25_neighbor"

    @classmethod
    def coerce(cls, value: Any) -> "LexicalEdgeKind":
        if isinstance(value, LexicalEdgeKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise LexicalGraphConfigError(f"unknown lexical edge kind: {value!r}")


class AdjacencyDirection(str, Enum):
    """Incoming or outgoing adjacency family."""

    IN = "in"
    OUT = "out"

    @classmethod
    def coerce(cls, value: Any) -> "AdjacencyDirection":
        if isinstance(value, AdjacencyDirection):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "incoming": cls.IN,
            "in": cls.IN,
            "outgoing": cls.OUT,
            "out": cls.OUT,
        }
        if text in aliases:
            return aliases[text]
        raise LexicalGraphConfigError(f"unknown adjacency direction: {value!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LexicalGraphConfigError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise LexicalGraphConfigError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise LexicalGraphConfigError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LexicalGraphConfigError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise LexicalGraphConfigError(f"{name}={value} exceeds maximum {maximum}")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LexicalGraphConfigError(f"{name} must be a non-negative integer")
    return value


def _validate_physical_bound(value: Any, *, name: str, maximum: int) -> int:
    bound = _require_positive_int(value, name, maximum=maximum)
    if bound > maximum:
        raise AdjacencyBoundError(f"{name}={bound} exceeds bound {maximum}")
    return bound


def _sha256_cid(value: Mapping[str, Any]) -> str:
    return "sha256:" + content_sha256(canonical_json_dumps(value))


def non_authoritative_edge_semantics() -> dict[str, Any]:
    """Sealed non-authoritative semantics for every lexical edge."""

    return {
        "authority": EDGE_AUTHORITY,
        "edge_class": EDGE_CLASS_SIMILARITY,
        "legal_authority": False,
        "proof_authority": EDGE_PROOF_AUTHORITY,
        "retrieval_hint": True,
        "notes": (
            "BM25 lexical edges are retrieval hints only. They must never be "
            "labeled as legal citation, authority, amendment, or proof."
        ),
    }


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def production_adjacency_bounds() -> dict[str, Any]:
    return {
        "candidate_accumulation_method": CANDIDATE_ACCUMULATION_METHOD,
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "forbidden_candidate_methods": sorted(FORBIDDEN_CANDIDATE_METHODS),
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "similarity_cannot_establish_legal_authority": True,
    }


def _acceptance_block() -> dict[str, bool]:
    return {
        "bm25_postings_are_canonical_virtual_term_document_graph": True,
        "incoming_and_outgoing_pages_and_shards_at_most_4096": True,
        "optional_topk_neighbors_use_postings_driven_accumulation": True,
    }


def _is_recovery_or_quarantine_row(row: Mapping[str, Any]) -> bool:
    configuration = str(row.get("configuration") or "").strip().lower()
    if configuration in RECOVERY_CONFIGURATIONS:
        return True
    disposition = str(row.get("disposition") or "").strip().lower()
    if disposition in RECOVERY_CONFIGURATIONS or disposition in {
        "excluded",
        "replaced",
    }:
        return True
    return bool(row.get("is_recovery"))


def admitted_rows_for_bm25(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Drop recovery/quarantine rows before they can enter BM25."""

    return [dict(row) for row in rows if not _is_recovery_or_quarantine_row(row)]


def part_relative_path(directory: str, shard_id: int) -> str:
    return f"{directory.rstrip('/')}/part-{shard_id:05d}.json"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LexicalGraphConfig:
    """Bounded lexical overlay configuration.

    ``materialize_term_document_edges`` defaults to ``False`` so the
    overlay never expands the full posting table into durable graph
    edges unless the caller explicitly opts in.

    ``candidate_accumulation`` is pinned to ``postings_driven``. All-pairs
    scans are refused.
    """

    neighbor_k: int = DEFAULT_NEIGHBOR_K
    max_neighbors_per_document: int = DEFAULT_NEIGHBOR_K
    max_neighbor_query_terms: int = DEFAULT_MAX_NEIGHBOR_QUERY_TERMS
    min_neighbor_term_length: int = DEFAULT_MIN_NEIGHBOR_TERM_LENGTH
    materialize_term_document_edges: bool = False
    materialize_neighbors: bool = True
    allow_full_postings_expansion: bool = False
    candidate_accumulation: str = CANDIDATE_ACCUMULATION_METHOD
    mode: str = LEXICAL_GRAPH_DEFAULT_MODE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "neighbor_k",
            _require_positive_int(self.neighbor_k, "neighbor_k", maximum=MAX_NEIGHBOR_K),
        )
        object.__setattr__(
            self,
            "max_neighbors_per_document",
            _require_positive_int(
                self.max_neighbors_per_document,
                "max_neighbors_per_document",
                maximum=MAX_NEIGHBOR_K,
            ),
        )
        if self.neighbor_k > self.max_neighbors_per_document:
            raise LexicalGraphConfigError(
                "neighbor_k cannot exceed max_neighbors_per_document "
                f"({self.neighbor_k} > {self.max_neighbors_per_document})"
            )
        object.__setattr__(
            self,
            "max_neighbor_query_terms",
            _require_positive_int(
                self.max_neighbor_query_terms,
                "max_neighbor_query_terms",
                maximum=64,
            ),
        )
        object.__setattr__(
            self,
            "min_neighbor_term_length",
            _require_positive_int(
                self.min_neighbor_term_length,
                "min_neighbor_term_length",
                maximum=32,
            ),
        )
        if not isinstance(self.materialize_term_document_edges, bool):
            raise LexicalGraphConfigError(
                "materialize_term_document_edges must be a boolean"
            )
        if not isinstance(self.materialize_neighbors, bool):
            raise LexicalGraphConfigError("materialize_neighbors must be a boolean")
        if not isinstance(self.allow_full_postings_expansion, bool):
            raise LexicalGraphConfigError(
                "allow_full_postings_expansion must be a boolean"
            )
        method = _require_non_empty_str(
            self.candidate_accumulation, "candidate_accumulation", maximum=64
        ).replace("-", "_")
        if method in FORBIDDEN_CANDIDATE_METHODS or method != CANDIDATE_ACCUMULATION_METHOD:
            raise LexicalGraphScanError(
                "neighbor candidate accumulation must be postings_driven; "
                f"got {self.candidate_accumulation!r}"
            )
        object.__setattr__(self, "candidate_accumulation", method)
        mode = _require_non_empty_str(self.mode, "mode", maximum=256)
        object.__setattr__(self, "mode", mode)
        if self.schema_version != SCHEMA_VERSION:
            raise LexicalGraphConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if self.materialize_term_document_edges and not self.allow_full_postings_expansion:
            raise LexicalGraphConfigError(
                "materialize_term_document_edges requires "
                "allow_full_postings_expansion=True; full durable expansion "
                "of the exact-51 posting table is refused by default"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_full_postings_expansion": self.allow_full_postings_expansion,
            "candidate_accumulation": self.candidate_accumulation,
            "exact_51_document_term_pair_lower_bound": (
                EXACT_51_DOCUMENT_TERM_PAIR_LOWER_BOUND
            ),
            "materialize_neighbors": self.materialize_neighbors,
            "materialize_term_document_edges": self.materialize_term_document_edges,
            "max_neighbor_query_terms": self.max_neighbor_query_terms,
            "max_neighbors_per_document": self.max_neighbors_per_document,
            "min_neighbor_term_length": self.min_neighbor_term_length,
            "mode": self.mode,
            "neighbor_k": self.neighbor_k,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return content_sha256(canonical_json_dumps(self.to_dict()))

    @property
    def config_cid(self) -> str:
        return "sha256:" + self.digest


def default_lexical_graph_config() -> LexicalGraphConfig:
    """Return the sealed default lexical overlay configuration."""

    return LexicalGraphConfig()


@dataclass(frozen=True, slots=True)
class AdjacencyConfig:
    """Physical paging bounds for incoming and outgoing adjacency."""

    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_route_page_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD
    include_legal_edges: bool = True
    include_similarity_edges: bool = True
    include_bm25_neighbors: bool = True
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_pointers_per_page",
            _validate_physical_bound(
                self.max_pointers_per_page,
                name="max_pointers_per_page",
                maximum=MAX_ADJACENCY_POINTERS_PER_ROW,
            ),
        )
        object.__setattr__(
            self,
            "max_rows_per_shard",
            _validate_physical_bound(
                self.max_rows_per_shard,
                name="max_rows_per_shard",
                maximum=MAX_ROWS_PER_PHYSICAL_SHARD,
            ),
        )
        object.__setattr__(
            self,
            "max_route_page_rows",
            _validate_physical_bound(
                self.max_route_page_rows,
                name="max_route_page_rows",
                maximum=MAX_ROWS_PER_PHYSICAL_SHARD,
            ),
        )
        for flag_name in (
            "include_legal_edges",
            "include_similarity_edges",
            "include_bm25_neighbors",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise LexicalGraphConfigError(f"{flag_name} must be a boolean")
        if self.schema_version != SCHEMA_VERSION:
            raise LexicalGraphConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_bm25_neighbors": self.include_bm25_neighbors,
            "include_legal_edges": self.include_legal_edges,
            "include_similarity_edges": self.include_similarity_edges,
            "max_pointers_per_page": self.max_pointers_per_page,
            "max_route_page_rows": self.max_route_page_rows,
            "max_rows_per_shard": self.max_rows_per_shard,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return content_sha256(canonical_json_dumps(self.to_dict()))

    @property
    def config_cid(self) -> str:
        return "sha256:" + self.digest


def default_adjacency_config() -> AdjacencyConfig:
    """Return the sealed production adjacency configuration (4,096 bounds)."""

    return AdjacencyConfig()


def fixture_adjacency_config(**overrides: Any) -> AdjacencyConfig:
    """Tight physical bounds for unit fixtures (still 4,096-capped)."""

    params: dict[str, Any] = {
        "max_pointers_per_page": DEFAULT_TEST_MAX_POINTERS_PER_PAGE,
        "max_rows_per_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "max_route_page_rows": DEFAULT_TEST_ROUTE_PAGE_ROWS,
    }
    params.update(overrides)
    return AdjacencyConfig(**params)


# ---------------------------------------------------------------------------
# Virtual term-document records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VirtualTermDocumentEdge:
    """Virtual term→document posting edge (not durable by default)."""

    term: str
    entry_cid: str
    document_index: int
    term_frequency: int
    legal_id: Optional[str] = None
    edge_type: str = VIRTUAL_TERM_DOCUMENT_EDGE_TYPE
    kind: LexicalEdgeKind = LexicalEdgeKind.VIRTUAL_TERM_DOCUMENT
    authority: str = EDGE_AUTHORITY
    proof_authority: bool = EDGE_PROOF_AUTHORITY
    durable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "term", _require_non_empty_str(self.term, "term"))
        object.__setattr__(
            self, "entry_cid", _require_non_empty_str(self.entry_cid, "entry_cid")
        )
        object.__setattr__(
            self,
            "document_index",
            _require_non_negative_int(self.document_index, "document_index"),
        )
        object.__setattr__(
            self,
            "term_frequency",
            _require_positive_int(self.term_frequency, "term_frequency"),
        )
        object.__setattr__(self, "kind", LexicalEdgeKind.coerce(self.kind))
        if self.authority != EDGE_AUTHORITY:
            raise LexicalGraphConfigError(
                "virtual term-document edges must be non_authoritative"
            )
        if self.proof_authority:
            raise LexicalGraphConfigError(
                "virtual term-document edges cannot claim proof_authority"
            )
        if self.durable:
            raise LexicalGraphConfigError(
                "virtual term-document edges cannot be marked durable"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "document_index": self.document_index,
            "durable": self.durable,
            "edge_type": self.edge_type,
            "entry_cid": self.entry_cid,
            "kind": self.kind.value,
            "legal_id": self.legal_id,
            "proof_authority": self.proof_authority,
            "term": self.term,
            "term_frequency": self.term_frequency,
        }


@dataclass(frozen=True, slots=True)
class Bm25NeighborEdge:
    """Bounded document-to-document BM25 neighbor edge (optional durable)."""

    source_entry_cid: str
    target_entry_cid: str
    score: float
    matched_terms: tuple[str, ...]
    config_cid: str
    source_legal_id: Optional[str] = None
    target_legal_id: Optional[str] = None
    edge_type: str = EDGE_TYPE_BM25_NEIGHBOR
    edge_class: str = EDGE_CLASS_SIMILARITY
    metric: str = EDGE_METRIC_BM25
    retrieval_method: str = RETRIEVAL_METHOD
    kind: LexicalEdgeKind = LexicalEdgeKind.BM25_NEIGHBOR
    authority: str = EDGE_AUTHORITY
    proof_authority: bool = EDGE_PROOF_AUTHORITY
    durable: bool = True
    rank: int = 0
    candidate_accumulation: str = CANDIDATE_ACCUMULATION_METHOD

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_entry_cid",
            _require_non_empty_str(self.source_entry_cid, "source_entry_cid"),
        )
        object.__setattr__(
            self,
            "target_entry_cid",
            _require_non_empty_str(self.target_entry_cid, "target_entry_cid"),
        )
        if self.source_entry_cid == self.target_entry_cid:
            raise LexicalGraphConfigError("neighbor edge cannot be self-loop")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise LexicalGraphConfigError("score must be a finite number")
        score = float(self.score)
        if not math.isfinite(score) or score <= 0.0:
            raise LexicalGraphConfigError("score must be a positive finite number")
        object.__setattr__(self, "score", score)
        terms = tuple(
            _require_non_empty_str(term, "matched_term")
            for term in (self.matched_terms or ())
        )
        object.__setattr__(self, "matched_terms", terms)
        object.__setattr__(
            self, "config_cid", _require_non_empty_str(self.config_cid, "config_cid")
        )
        object.__setattr__(self, "kind", LexicalEdgeKind.coerce(self.kind))
        if self.edge_type != EDGE_TYPE_BM25_NEIGHBOR:
            raise LexicalGraphConfigError(
                f"neighbor edge_type must be {EDGE_TYPE_BM25_NEIGHBOR}, "
                f"got {self.edge_type!r}"
            )
        if self.edge_class != EDGE_CLASS_SIMILARITY:
            raise LexicalGraphConfigError(
                "neighbor edges must use edge_class=similarity"
            )
        if self.authority != EDGE_AUTHORITY:
            raise LexicalGraphConfigError(
                "BM25_NEIGHBOR_OF edges must be non_authoritative"
            )
        if self.proof_authority:
            raise LexicalGraphConfigError(
                "BM25_NEIGHBOR_OF edges cannot claim proof_authority"
            )
        method = _require_non_empty_str(
            self.candidate_accumulation, "candidate_accumulation", maximum=64
        ).replace("-", "_")
        if method != CANDIDATE_ACCUMULATION_METHOD:
            raise LexicalGraphScanError(
                "neighbor edges must record postings_driven accumulation"
            )
        object.__setattr__(self, "candidate_accumulation", method)
        object.__setattr__(self, "rank", _require_non_negative_int(self.rank, "rank"))

    @property
    def edge_cid(self) -> str:
        return _sha256_cid(
            {
                "config_cid": self.config_cid,
                "edge_type": self.edge_type,
                "metric": self.metric,
                "schema_version": SCHEMA_VERSION,
                "score": self.score,
                "source_entry_cid": self.source_entry_cid,
                "target_entry_cid": self.target_entry_cid,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "candidate_accumulation": self.candidate_accumulation,
            "config_cid": self.config_cid,
            "durable": self.durable,
            "edge_cid": self.edge_cid,
            "edge_class": self.edge_class,
            "edge_type": self.edge_type,
            "kind": self.kind.value,
            "matched_terms": list(self.matched_terms),
            "metric": self.metric,
            "proof_authority": self.proof_authority,
            "rank": self.rank,
            "retrieval_method": self.retrieval_method,
            "score": self.score,
            "source_entry_cid": self.source_entry_cid,
            "source_legal_id": self.source_legal_id,
            "target_entry_cid": self.target_entry_cid,
            "target_legal_id": self.target_legal_id,
        }

    def to_similarity_neighbor(self) -> SimilarityNeighbor:
        source = self.source_legal_id or self.source_entry_cid
        target = self.target_legal_id or self.target_entry_cid
        return SimilarityNeighbor(
            source_legal_id=source,
            target_legal_id=target,
            score=self.score,
            edge_type=GraphEdgeType.BM25_NEIGHBOR_OF,
            metric=self.metric,
            config_cid=self.config_cid,
        )


@dataclass(frozen=True, slots=True)
class TermPostingList:
    """Sorted posting list for one vocabulary term (virtual graph)."""

    term: str
    document_frequency: int
    postings: tuple[VirtualTermDocumentEdge, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "term", _require_non_empty_str(self.term, "term"))
        object.__setattr__(
            self,
            "document_frequency",
            _require_non_negative_int(self.document_frequency, "document_frequency"),
        )
        if len(self.postings) != self.document_frequency:
            raise LexicalGraphParityError(
                f"posting length for {self.term!r} ({len(self.postings)}) "
                f"!= document_frequency ({self.document_frequency})"
            )

    def entry_cids(self) -> tuple[str, ...]:
        return tuple(edge.entry_cid for edge in self.postings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_frequency": self.document_frequency,
            "entry_cids": list(self.entry_cids()),
            "term": self.term,
        }


@dataclass(frozen=True, slots=True)
class NeighborBuildStats:
    """Evidence that neighbors were accumulated from postings, not all-pairs."""

    method: str = CANDIDATE_ACCUMULATION_METHOD
    source_documents_considered: int = 0
    posting_candidates: int = 0
    candidates_scored: int = 0
    full_corpus_pair_scans: int = 0
    neighbor_edges_emitted: int = 0

    def __post_init__(self) -> None:
        method = _require_non_empty_str(self.method, "method", maximum=64)
        if method != CANDIDATE_ACCUMULATION_METHOD:
            raise LexicalGraphScanError(
                f"neighbor build method must be {CANDIDATE_ACCUMULATION_METHOD}"
            )
        if self.full_corpus_pair_scans != 0:
            raise LexicalGraphScanError(
                "neighbor materialization recorded an all-pairs corpus scan"
            )
        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "source_documents_considered",
            _require_non_negative_int(
                self.source_documents_considered, "source_documents_considered"
            ),
        )
        object.__setattr__(
            self,
            "posting_candidates",
            _require_non_negative_int(self.posting_candidates, "posting_candidates"),
        )
        object.__setattr__(
            self,
            "candidates_scored",
            _require_non_negative_int(self.candidates_scored, "candidates_scored"),
        )
        object.__setattr__(
            self,
            "neighbor_edges_emitted",
            _require_non_negative_int(
                self.neighbor_edges_emitted, "neighbor_edges_emitted"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates_scored": self.candidates_scored,
            "full_corpus_pair_scans": self.full_corpus_pair_scans,
            "method": self.method,
            "neighbor_edges_emitted": self.neighbor_edges_emitted,
            "posting_candidates": self.posting_candidates,
            "source_documents_considered": self.source_documents_considered,
        }


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenUsLawLexicalGraphOverlay:
    """Postings-backed lexical graph overlay bound to a BM25 index."""

    index: OpenUsLawBm25Index
    config: LexicalGraphConfig
    vocabulary: tuple[str, ...]
    postings: Mapping[str, TermPostingList]
    document_terms: Mapping[str, tuple[str, ...]]
    term_document_pair_count: int
    neighbor_edges: tuple[Bm25NeighborEdge, ...] = ()
    neighbor_build_stats: NeighborBuildStats = field(
        default_factory=NeighborBuildStats
    )
    config_cid: str = ""
    bm25_config_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.index, OpenUsLawBm25Index):
            raise LexicalGraphConfigError("index must be an OpenUsLawBm25Index")
        if not isinstance(self.config, LexicalGraphConfig):
            raise LexicalGraphConfigError("config must be a LexicalGraphConfig")
        object.__setattr__(self, "postings", MappingProxyType(dict(self.postings)))
        object.__setattr__(
            self, "document_terms", MappingProxyType(dict(self.document_terms))
        )
        if not isinstance(self.neighbor_build_stats, NeighborBuildStats):
            raise LexicalGraphConfigError(
                "neighbor_build_stats must be a NeighborBuildStats"
            )
        if not self.config_cid:
            object.__setattr__(self, "config_cid", self.config.config_cid)
        if not self.bm25_config_digest:
            object.__setattr__(self, "bm25_config_digest", self.index.config.digest)
        self.assert_bm25_parity()
        self._assert_neighbor_caps()

    @property
    def document_count(self) -> int:
        return self.index.document_count

    @property
    def term_count(self) -> int:
        return len(self.vocabulary)

    @property
    def neighbor_edge_count(self) -> int:
        return len(self.neighbor_edges)

    @property
    def durable_edge_count(self) -> int:
        return self.neighbor_edge_count

    @property
    def expands_full_term_document_edges(self) -> bool:
        return bool(self.config.materialize_term_document_edges)

    def has_term(self, term: str) -> bool:
        return term in self.postings

    def posting_list(self, term: str) -> TermPostingList:
        key = _require_non_empty_str(term, "term")
        try:
            return self.postings[key]
        except KeyError as exc:
            raise LexicalGraphLookupError(f"unknown term: {key!r}") from exc

    def documents_for_term(
        self,
        term: str,
        *,
        limit: int | None = None,
    ) -> tuple[VirtualTermDocumentEdge, ...]:
        """Virtual term→document traversal through canonical BM25 postings."""

        postings = self.posting_list(term).postings
        if limit is None:
            return postings
        cap = _require_positive_int(limit, "limit")
        return postings[:cap]

    def terms_for_document(self, entry_cid: str) -> tuple[str, ...]:
        """Virtual document→term traversal (sorted vocabulary subset)."""

        key = _require_non_empty_str(entry_cid, "entry_cid")
        try:
            return self.document_terms[key]
        except KeyError as exc:
            raise LexicalGraphLookupError(f"unknown document: {key!r}") from exc

    def iter_virtual_term_document_edges(
        self,
        *,
        terms: Sequence[str] | None = None,
    ) -> Iterable[VirtualTermDocumentEdge]:
        """Yield virtual term-document edges without materializing all at once."""

        if terms is None:
            term_iter = self.vocabulary
        else:
            term_iter = tuple(_require_non_empty_str(term, "term") for term in terms)
        for term in term_iter:
            if term not in self.postings:
                continue
            yield from self.postings[term].postings

    def materialize_all_term_document_edges(self) -> tuple[VirtualTermDocumentEdge, ...]:
        """Explicit opt-in full expansion of term-document edges."""

        if not (
            self.config.materialize_term_document_edges
            and self.config.allow_full_postings_expansion
        ):
            raise LexicalGraphExpansionError(
                "full term-document edge expansion is disabled by default "
                f"(exact-51 pair lower bound ≥ "
                f"{EXACT_51_DOCUMENT_TERM_PAIR_LOWER_BOUND:,}); "
                "set materialize_term_document_edges=True and "
                "allow_full_postings_expansion=True to opt in, or use "
                "iter_virtual_term_document_edges() / documents_for_term()"
            )
        return tuple(self.iter_virtual_term_document_edges())

    def neighbors_for_document(
        self,
        entry_cid: str,
        *,
        top_k: int | None = None,
    ) -> tuple[Bm25NeighborEdge, ...]:
        key = _require_non_empty_str(entry_cid, "entry_cid")
        if key not in self.document_terms:
            raise LexicalGraphLookupError(f"unknown document: {key!r}")
        k = self.config.neighbor_k if top_k is None else top_k
        k = _require_positive_int(
            k, "top_k", maximum=self.config.max_neighbors_per_document
        )
        edges = [edge for edge in self.neighbor_edges if edge.source_entry_cid == key]
        return tuple(edges[:k])

    def to_similarity_neighbors(self) -> tuple[SimilarityNeighbor, ...]:
        return tuple(edge.to_similarity_neighbor() for edge in self.neighbor_edges)

    def assert_bm25_parity(self) -> None:
        """Fail closed when overlay vocabulary/postings diverge from BM25."""

        bm25_vocab: set[str] = set()
        bm25_df: dict[str, int] = {}
        for shard in self.index.term_shards:
            for term_row in shard.terms:
                bm25_vocab.add(term_row.term)
                bm25_df[term_row.term] = int(term_row.document_frequency)
        overlay_vocab = set(self.vocabulary)
        if bm25_vocab != overlay_vocab:
            missing = sorted(bm25_vocab - overlay_vocab)[:8]
            extra = sorted(overlay_vocab - bm25_vocab)[:8]
            raise LexicalGraphParityError(
                "overlay vocabulary does not match BM25 postings; "
                f"missing={missing!r} extra={extra!r}"
            )
        if len(self.vocabulary) != self.index.term_count:
            raise LexicalGraphParityError(
                f"term_count mismatch: overlay={len(self.vocabulary)} "
                f"bm25={self.index.term_count}"
            )
        for term, df in bm25_df.items():
            posting = self.postings.get(term)
            if posting is None:
                raise LexicalGraphParityError(f"missing postings for term {term!r}")
            if posting.document_frequency != df:
                raise LexicalGraphParityError(
                    f"df mismatch for {term!r}: overlay={posting.document_frequency} "
                    f"bm25={df}"
                )
            if len(posting.postings) != df:
                raise LexicalGraphParityError(f"posting length mismatch for {term!r}")
        index_ids = {document.entry_cid for document in self.index.documents}
        overlay_ids = set(self.document_terms.keys())
        if index_ids != overlay_ids:
            raise LexicalGraphParityError("document coverage diverges from BM25 index")

    def _assert_neighbor_caps(self) -> None:
        counts: dict[str, int] = defaultdict(int)
        for edge in self.neighbor_edges:
            counts[edge.source_entry_cid] += 1
            if counts[edge.source_entry_cid] > self.config.max_neighbors_per_document:
                raise LexicalGraphNeighborCapError(
                    "neighbor cap exceeded for "
                    f"{edge.source_entry_cid}: "
                    f"{counts[edge.source_entry_cid]} > "
                    f"{self.config.max_neighbors_per_document}"
                )
            if counts[edge.source_entry_cid] > self.config.neighbor_k:
                raise LexicalGraphNeighborCapError(
                    "neighbor_k exceeded for "
                    f"{edge.source_entry_cid}: "
                    f"{counts[edge.source_entry_cid]} > {self.config.neighbor_k}"
                )
            if edge.authority != EDGE_AUTHORITY or edge.proof_authority:
                raise LexicalGraphConfigError(
                    "neighbor edge semantics must remain non-authoritative"
                )
            if edge.edge_type != EDGE_TYPE_BM25_NEIGHBOR:
                raise LexicalGraphConfigError(
                    f"unexpected neighbor edge_type {edge.edge_type!r}"
                )
            if edge.candidate_accumulation != CANDIDATE_ACCUMULATION_METHOD:
                raise LexicalGraphScanError(
                    "neighbor edge is missing postings-driven accumulation"
                )

    def expansion_receipt(self) -> dict[str, Any]:
        return {
            "allow_full_postings_expansion": self.config.allow_full_postings_expansion,
            "candidate_accumulation": self.config.candidate_accumulation,
            "default_mode": LEXICAL_GRAPH_DEFAULT_MODE,
            "durable_edge_count": self.durable_edge_count,
            "durable_term_document_edges": (
                0
                if not self.expands_full_term_document_edges
                else self.term_document_pair_count
            ),
            "exact_51_document_term_pair_lower_bound": (
                EXACT_51_DOCUMENT_TERM_PAIR_LOWER_BOUND
            ),
            "materialize_neighbors": self.config.materialize_neighbors,
            "materialize_term_document_edges": self.config.materialize_term_document_edges,
            "mode": self.config.mode,
            "neighbor_build_stats": self.neighbor_build_stats.to_dict(),
            "neighbor_edge_count": self.neighbor_edge_count,
            "term_document_pair_count": self.term_document_pair_count,
            "virtual_traversal_only": not self.expands_full_term_document_edges,
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "goal_id": GOAL_ID,
            "lexical_graph": {
                "bm25_config_digest": self.bm25_config_digest,
                "candidate_accumulation": self.config.candidate_accumulation,
                "config_cid": self.config_cid,
                "config_digest": self.config.digest,
                "document_count": self.document_count,
                "edge_semantics": non_authoritative_edge_semantics(),
                "expansion": self.expansion_receipt(),
                "index_root_cid": self.index.index_root_cid,
                "mode": self.config.mode,
                "neighbor_edge_count": self.neighbor_edge_count,
                "neighbor_k": self.config.neighbor_k,
                "primary_key": PRIMARY_KEY,
                "schema_version": SCHEMA_VERSION,
                "term_count": self.term_count,
                "term_document_pair_count": self.term_document_pair_count,
                "tokenizer_id": TOKENIZER_ID,
            },
            "producer": PRODUCER,
            "release_profile": RELEASE_PROFILE,
            "task_id": TASK_ID,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_config_digest": self.bm25_config_digest,
            "config": self.config.to_dict(),
            "config_cid": self.config_cid,
            "document_count": self.document_count,
            "edge_semantics": non_authoritative_edge_semantics(),
            "expansion": self.expansion_receipt(),
            "neighbor_build_stats": self.neighbor_build_stats.to_dict(),
            "neighbor_edge_count": self.neighbor_edge_count,
            "neighbor_edges": [edge.to_dict() for edge in self.neighbor_edges],
            "term_count": self.term_count,
            "term_document_pair_count": self.term_document_pair_count,
            "vocabulary_head": list(self.vocabulary[:32]),
        }


# ---------------------------------------------------------------------------
# Postings projection and postings-driven neighbors
# ---------------------------------------------------------------------------


def project_virtual_postings(
    index: OpenUsLawBm25Index,
) -> tuple[
    tuple[str, ...],
    dict[str, TermPostingList],
    dict[str, tuple[str, ...]],
    int,
]:
    """Project the canonical virtual term-document graph from BM25 postings."""

    if not isinstance(index, OpenUsLawBm25Index):
        raise LexicalGraphConfigError("index must be an OpenUsLawBm25Index")

    legal_by_cid = {document.entry_cid: document.legal_id for document in index.documents}
    term_to_edges: dict[str, list[VirtualTermDocumentEdge]] = {}
    document_term_sets: dict[str, set[str]] = {
        document.entry_cid: set() for document in index.documents
    }
    pair_count = 0

    for shard in index.term_shards:
        for term_row in shard.terms:
            edges: list[VirtualTermDocumentEdge] = []
            for cell in term_row.cells:
                for pointer in cell.pointers:
                    edges.append(
                        VirtualTermDocumentEdge(
                            term=term_row.term,
                            entry_cid=pointer.entry_cid,
                            document_index=pointer.document_index,
                            term_frequency=int(pointer.tf),
                            legal_id=legal_by_cid.get(pointer.entry_cid),
                        )
                    )
                    if pointer.entry_cid not in document_term_sets:
                        raise LexicalGraphParityError(
                            f"posting pointer {pointer.entry_cid} is not a BM25 document"
                        )
                    document_term_sets[pointer.entry_cid].add(term_row.term)
                    pair_count += 1
            edges.sort(key=lambda edge: (edge.entry_cid, edge.document_index))
            if len(edges) != int(term_row.document_frequency):
                raise LexicalGraphParityError(
                    f"canonical postings for {term_row.term!r} have length "
                    f"{len(edges)} but BM25 df={term_row.document_frequency}"
                )
            term_to_edges[term_row.term] = edges

    vocabulary = tuple(sorted(term_to_edges))
    postings = {
        term: TermPostingList(
            term=term,
            document_frequency=len(term_to_edges[term]),
            postings=tuple(term_to_edges[term]),
        )
        for term in vocabulary
    }
    document_terms = {
        entry_cid: tuple(sorted(terms))
        for entry_cid, terms in document_term_sets.items()
    }
    return vocabulary, postings, document_terms, pair_count


def neighbor_query_terms(
    document: LegalBm25Document,
    *,
    config: LexicalGraphConfig,
    tokenizer: TokenizerConfig | None = None,
) -> tuple[str, ...]:
    """Select discriminative query terms for neighbor scoring.

    Prefer longer authority-field terms, then body/note. Terms shorter
    than ``min_neighbor_term_length`` are dropped unless no longer
    candidates exist.
    """

    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    priority_fields = (
        "heading",
        "citation",
        "title",
        "hierarchy",
        "jurisdiction",
        "body",
        "note",
    )
    for priority, field_name in enumerate(priority_fields):
        stream = document.fields.get(field_name)
        if stream is None:
            continue
        for term in stream.terms:
            if term in seen:
                continue
            if len(term) < config.min_neighbor_term_length:
                continue
            seen.add(term)
            ranked.append((-len(term), priority, term))
    ranked.sort()
    terms = [term for _, _, term in ranked[: config.max_neighbor_query_terms]]
    if terms:
        return tuple(terms)

    fallback_text = " ".join(
        part
        for part in (
            document.fields[name].text
            for name in FIELD_ORDER
            if name in document.fields and document.fields[name].text
        )
        if part
    )
    if not fallback_text:
        return ()
    tok = tokenizer or TokenizerConfig()
    tokenized = tokenize_legal_text(fallback_text, config=tok)
    fallback = list(dict.fromkeys(tokenized.indexable_terms))
    return tuple(fallback[: config.max_neighbor_query_terms])


def accumulate_neighbor_candidates(
    index: OpenUsLawBm25Index,
    query_terms: Sequence[str],
    *,
    exclude_entry_cid: str,
) -> dict[str, list[str]]:
    """Accumulate neighbor candidates from posting lists of *query_terms*.

    This is the only legal candidate source. Callers must not fall back
    to scanning ``index.documents``.
    """

    if not query_terms:
        return {}
    exclude = _require_non_empty_str(exclude_entry_cid, "exclude_entry_cid")
    candidates: dict[str, list[str]] = {}
    seen_terms: set[str] = set()
    for term in query_terms:
        key = _require_non_empty_str(term, "query_term")
        if key in seen_terms:
            continue
        seen_terms.add(key)
        posting = index.term_posting(key)
        if posting is None:
            continue
        for cell in posting.cells:
            for pointer in cell.pointers:
                if pointer.entry_cid == exclude:
                    continue
                matched = candidates.setdefault(pointer.entry_cid, [])
                if key not in matched:
                    matched.append(key)
    return candidates


def score_posting_candidates(
    index: OpenUsLawBm25Index,
    *,
    candidates: Mapping[str, Sequence[str]],
    top_k: int,
) -> list[Bm25Hit]:
    """Score only posting-accumulated candidates. Never scans the corpus."""

    if not candidates or top_k < 1:
        return []
    by_cid = {document.entry_cid: document for document in index.documents}
    hits: list[Bm25Hit] = []
    for entry_cid, terms in candidates.items():
        document = by_cid.get(entry_cid)
        if document is None:
            continue
        score = 0.0
        matched: list[str] = []
        explanations = []
        for term in terms:
            explanation = index.explain_term(document, term)
            if explanation.total_score <= 0.0:
                continue
            score += explanation.total_score
            matched.append(term)
            explanations.append(explanation)
        if score <= 0.0 or not matched:
            continue
        hits.append(
            Bm25Hit(
                entry_cid=document.entry_cid,
                document_index=document.document_index,
                score=score,
                matched_terms=tuple(matched),
                explanations=tuple(explanations),
                filters=document.filters,
                legal_id=document.legal_id,
                authority=EDGE_AUTHORITY,
                proof_authority=EDGE_PROOF_AUTHORITY,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.entry_cid))
    return hits[:top_k]


def materialize_bm25_neighbor_edges(
    index: OpenUsLawBm25Index,
    *,
    config: LexicalGraphConfig | None = None,
    config_cid: str | None = None,
) -> tuple[tuple[Bm25NeighborEdge, ...], NeighborBuildStats]:
    """Emit deterministic bounded top-K ``BM25_NEIGHBOR_OF`` edges.

    Candidates are accumulated from BM25 posting cells of each source
    document's query terms. The corpus is never scanned pairwise.
    """

    cfg = config or default_lexical_graph_config()
    if not isinstance(cfg, LexicalGraphConfig):
        raise LexicalGraphConfigError("config must be a LexicalGraphConfig")
    if cfg.candidate_accumulation != CANDIDATE_ACCUMULATION_METHOD:
        raise LexicalGraphScanError(
            "neighbor materialization refuses non-postings candidate methods"
        )
    if not cfg.materialize_neighbors:
        return (), NeighborBuildStats()

    cid = config_cid or cfg.config_cid
    edges: list[Bm25NeighborEdge] = []
    posting_candidates = 0
    candidates_scored = 0
    for document in index.documents:
        query_terms = neighbor_query_terms(
            document,
            config=cfg,
            tokenizer=index.config.tokenizer,
        )
        candidates = accumulate_neighbor_candidates(
            index,
            query_terms,
            exclude_entry_cid=document.entry_cid,
        )
        posting_candidates += len(candidates)
        hits = score_posting_candidates(
            index, candidates=candidates, top_k=cfg.neighbor_k
        )
        candidates_scored += len(candidates)
        if len(hits) > cfg.max_neighbors_per_document:
            raise LexicalGraphNeighborCapError(
                f"neighbor materialization exceeded cap for {document.entry_cid}"
            )
        for rank, hit in enumerate(hits):
            edges.append(
                Bm25NeighborEdge(
                    source_entry_cid=document.entry_cid,
                    target_entry_cid=hit.entry_cid,
                    score=hit.score,
                    matched_terms=hit.matched_terms,
                    config_cid=cid,
                    source_legal_id=document.legal_id,
                    target_legal_id=hit.legal_id,
                    rank=rank,
                )
            )

    edges.sort(
        key=lambda edge: (edge.source_entry_cid, -edge.score, edge.target_entry_cid)
    )
    per_source: dict[str, int] = defaultdict(int)
    for edge in edges:
        per_source[edge.source_entry_cid] += 1
        if per_source[edge.source_entry_cid] > cfg.max_neighbors_per_document:
            raise LexicalGraphNeighborCapError(
                "neighbor cap exceeded after materialization for "
                f"{edge.source_entry_cid}"
            )
    stats = NeighborBuildStats(
        method=CANDIDATE_ACCUMULATION_METHOD,
        source_documents_considered=index.document_count,
        posting_candidates=posting_candidates,
        candidates_scored=candidates_scored,
        full_corpus_pair_scans=0,
        neighbor_edges_emitted=len(edges),
    )
    return tuple(edges), stats


def build_open_us_law_lexical_graph(
    index: OpenUsLawBm25Index,
    *,
    config: LexicalGraphConfig | None = None,
) -> OpenUsLawLexicalGraphOverlay:
    """Build the postings-backed lexical graph overlay from a BM25 index."""

    if not isinstance(index, OpenUsLawBm25Index):
        raise LexicalGraphConfigError("index must be an OpenUsLawBm25Index")
    cfg = config or default_lexical_graph_config()
    if not isinstance(cfg, LexicalGraphConfig):
        raise LexicalGraphConfigError("config must be a LexicalGraphConfig")

    vocabulary, postings, document_terms, pair_count = project_virtual_postings(index)
    neighbor_edges, stats = materialize_bm25_neighbor_edges(
        index, config=cfg, config_cid=cfg.config_cid
    )
    return OpenUsLawLexicalGraphOverlay(
        index=index,
        config=cfg,
        vocabulary=vocabulary,
        postings=postings,
        document_terms=document_terms,
        term_document_pair_count=pair_count,
        neighbor_edges=neighbor_edges,
        neighbor_build_stats=stats,
        config_cid=cfg.config_cid,
        bm25_config_digest=index.config.digest,
    )


def build_open_us_law_lexical_graph_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bm25_config: OpenUsLawBm25Config | None = None,
    lexical_config: LexicalGraphConfig | None = None,
) -> OpenUsLawLexicalGraphOverlay:
    """Convenience: project admitted rows → BM25 index → lexical overlay."""

    from ipfs_datasets_py.processors.legal_data.open_us_law_bm25 import (
        build_open_us_law_bm25_index,
    )

    admitted = admitted_rows_for_bm25(rows)
    index = build_open_us_law_bm25_index(
        admitted, config=bm25_config or fixture_bm25_config()
    )
    return build_open_us_law_lexical_graph(index, config=lexical_config)


# ---------------------------------------------------------------------------
# Bounded two-way adjacency
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdjacencyPointer:
    """One resolved edge pointer on an adjacency page."""

    edge_cid: str
    neighbor_node_cid: str
    edge_type: str
    edge_class: str
    weight: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_cid", _require_non_empty_str(self.edge_cid, "edge_cid")
        )
        object.__setattr__(
            self,
            "neighbor_node_cid",
            _require_non_empty_str(self.neighbor_node_cid, "neighbor_node_cid"),
        )
        object.__setattr__(
            self, "edge_type", _require_non_empty_str(self.edge_type, "edge_type")
        )
        object.__setattr__(
            self, "edge_class", _require_non_empty_str(self.edge_class, "edge_class")
        )
        if self.weight is not None:
            if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
                raise LexicalGraphConfigError("weight must be a number")
            if not math.isfinite(float(self.weight)):
                raise LexicalGraphConfigError("weight must be finite")
            object.__setattr__(self, "weight", float(self.weight))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_class": self.edge_class,
            "edge_type": self.edge_type,
            "neighbor_node_cid": self.neighbor_node_cid,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class AdjacencyPage:
    """At most 4,096 edge pointers for one node in one direction."""

    node_cid: str
    direction: AdjacencyDirection
    page_index: int
    pointers: tuple[AdjacencyPointer, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_cid", _require_non_empty_str(self.node_cid, "node_cid")
        )
        object.__setattr__(self, "direction", AdjacencyDirection.coerce(self.direction))
        object.__setattr__(
            self, "page_index", _require_non_negative_int(self.page_index, "page_index")
        )
        pointers = tuple(self.pointers)
        if not pointers:
            raise AdjacencyBoundError("adjacency page must contain at least one pointer")
        if len(pointers) > MAX_ADJACENCY_POINTERS_PER_ROW:
            raise AdjacencyBoundError(
                f"adjacency page has {len(pointers)} pointers; "
                f"exceeds bound {MAX_ADJACENCY_POINTERS_PER_ROW}"
            )
        object.__setattr__(self, "pointers", pointers)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    @property
    def pointer_count(self) -> int:
        return len(self.pointers)

    @property
    def first_key(self) -> str:
        return adjacency_page_key(self.node_cid, self.page_index)

    @property
    def last_key(self) -> str:
        return self.first_key

    @property
    def edge_cids(self) -> tuple[str, ...]:
        return tuple(pointer.edge_cid for pointer in self.pointers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "edge_cids": list(self.edge_cids),
            "first_key": self.first_key,
            "last_key": self.last_key,
            "node_cid": self.node_cid,
            "page_index": self.page_index,
            "pointer_count": self.pointer_count,
            "pointers": [pointer.to_dict() for pointer in self.pointers],
            "schema_version": self.schema_version,
        }


def adjacency_page_key(node_cid: str, page_index: int) -> str:
    return f"{node_cid}:{page_index:08d}"


def page_adjacency_pointers(
    node_cid: str,
    direction: AdjacencyDirection | str,
    pointers: Sequence[AdjacencyPointer],
    *,
    max_pointers: int = MAX_ADJACENCY_POINTERS_PER_ROW,
) -> tuple[AdjacencyPage, ...]:
    """Split one node's pointers into pages of at most *max_pointers*."""

    bound = _validate_physical_bound(
        max_pointers, name="max_pointers", maximum=MAX_ADJACENCY_POINTERS_PER_ROW
    )
    direction_enum = AdjacencyDirection.coerce(direction)
    ordered = tuple(
        sorted(
            pointers,
            key=lambda item: (item.edge_cid, item.neighbor_node_cid, item.edge_type),
        )
    )
    if not ordered:
        return ()
    pages: list[AdjacencyPage] = []
    for page_index, start in enumerate(range(0, len(ordered), bound)):
        chunk = ordered[start : start + bound]
        if len(chunk) > bound:
            raise AdjacencyBoundError("adjacency page split exceeded the configured bound")
        pages.append(
            AdjacencyPage(
                node_cid=node_cid,
                direction=direction_enum,
                page_index=page_index,
                pointers=chunk,
            )
        )
    return tuple(pages)


@dataclass(frozen=True, slots=True)
class AdjacencyShard:
    """At most 4,096 adjacency page rows for one direction."""

    direction: AdjacencyDirection
    shard_id: int
    pages: tuple[AdjacencyPage, ...]
    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", AdjacencyDirection.coerce(self.direction))
        object.__setattr__(
            self, "shard_id", _require_non_negative_int(self.shard_id, "shard_id")
        )
        pages = tuple(self.pages)
        if not pages:
            raise AdjacencyBoundError("adjacency shard must contain at least one page")
        if len(pages) > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise AdjacencyBoundError(
                f"adjacency shard has {len(pages)} rows; "
                f"exceeds bound {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        for page in pages:
            if page.direction is not self.direction:
                raise AdjacencyBoundError(
                    "adjacency shard mixes incoming and outgoing pages"
                )
        object.__setattr__(self, "pages", pages)
        object.__setattr__(
            self,
            "relative_path",
            _require_non_empty_str(self.relative_path, "relative_path", maximum=512),
        )
        object.__setattr__(self, "sha256", _require_non_empty_str(self.sha256, "sha256"))
        object.__setattr__(
            self, "size_bytes", _require_non_negative_int(self.size_bytes, "size_bytes")
        )

    @property
    def row_count(self) -> int:
        return len(self.pages)

    @property
    def first_key(self) -> str:
        return self.pages[0].first_key

    @property
    def last_key(self) -> str:
        return self.pages[-1].first_key

    @property
    def max_pointers_on_page(self) -> int:
        return max(page.pointer_count for page in self.pages)

    def to_route_descriptor(self) -> RouteDescriptor:
        kind = (
            "graph_adjacency_out"
            if self.direction is AdjacencyDirection.OUT
            else "graph_adjacency_in"
        )
        return RouteDescriptor(
            first_key=self.first_key,
            last_key=self.last_key,
            relative_path=self.relative_path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            row_count=self.row_count,
            shard_id=self.shard_id,
            kind=kind,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "max_pointers_on_page": self.max_pointers_on_page,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "shard_id": self.shard_id,
            "size_bytes": self.size_bytes,
        }


def shard_adjacency_pages(
    pages: Sequence[AdjacencyPage],
    *,
    direction: AdjacencyDirection | str,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    directory: str | None = None,
) -> tuple[AdjacencyShard, ...]:
    """Split sorted adjacency pages into physical shards of at most *max_rows*."""

    bound = _validate_physical_bound(
        max_rows, name="max_rows", maximum=MAX_ROWS_PER_PHYSICAL_SHARD
    )
    direction_enum = AdjacencyDirection.coerce(direction)
    dest = directory or (
        OUTGOING_ADJACENCY_DIR
        if direction_enum is AdjacencyDirection.OUT
        else INCOMING_ADJACENCY_DIR
    )
    ordered = tuple(
        sorted(pages, key=lambda page: (page.node_cid, page.page_index, page.first_key))
    )
    if not ordered:
        return ()
    for page in ordered:
        if page.direction is not direction_enum:
            raise AdjacencyBoundError("cannot shard mixed adjacency directions")
        if page.pointer_count > MAX_ADJACENCY_POINTERS_PER_ROW:
            raise AdjacencyBoundError(
                f"page for {page.node_cid} has {page.pointer_count} pointers"
            )
    shards: list[AdjacencyShard] = []
    for shard_id, start in enumerate(range(0, len(ordered), bound)):
        chunk = ordered[start : start + bound]
        if len(chunk) > bound:
            raise AdjacencyBoundError("adjacency shard split exceeded the configured bound")
        payload = {
            "direction": direction_enum.value,
            "pages": [page.to_dict() for page in chunk],
            "schema_version": SCHEMA_VERSION,
            "shard_id": shard_id,
        }
        blob = canonical_json_dumps(payload)
        digest = content_sha256(blob)
        shards.append(
            AdjacencyShard(
                direction=direction_enum,
                shard_id=shard_id,
                pages=chunk,
                relative_path=part_relative_path(dest, shard_id),
                sha256=digest,
                size_bytes=len(blob.encode("utf-8")),
            )
        )
    return tuple(shards)


def _section_nodes(
    projection: OpenUsLawGraphProjection,
) -> tuple[dict[str, OpenUsLawGraphNode], dict[str, OpenUsLawGraphNode]]:
    by_legal: dict[str, OpenUsLawGraphNode] = {}
    by_entry: dict[str, OpenUsLawGraphNode] = {}
    for node in projection.nodes:
        if node.node_type not in SECTION_LIKE:
            continue
        if node.legal_id:
            by_legal.setdefault(node.legal_id, node)
        if node.entry_cid:
            by_entry.setdefault(node.entry_cid, node)
    return by_legal, by_entry


def _resolve_section_node(
    *,
    by_legal: Mapping[str, OpenUsLawGraphNode],
    by_entry: Mapping[str, OpenUsLawGraphNode],
    entry_cid: str | None,
    legal_id: str | None,
) -> OpenUsLawGraphNode | None:
    if legal_id and legal_id in by_legal:
        return by_legal[legal_id]
    if entry_cid and entry_cid in by_entry:
        return by_entry[entry_cid]
    return None


@dataclass(frozen=True, slots=True)
class ResolvedAdjacencyEdge:
    """One directed graph edge used as an adjacency pointer source."""

    edge_cid: str
    source_node_cid: str
    target_node_cid: str
    edge_type: str
    edge_class: str
    weight: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_class": self.edge_class,
            "edge_type": self.edge_type,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
            "weight": self.weight,
        }


def collect_adjacency_edges(
    projection: OpenUsLawGraphProjection,
    *,
    overlay: OpenUsLawLexicalGraphOverlay | None = None,
    config: AdjacencyConfig | None = None,
) -> tuple[ResolvedAdjacencyEdge, ...]:
    """Collect legal, similarity, and optional BM25-neighbor edges."""

    cfg = config or default_adjacency_config()
    collected: dict[str, ResolvedAdjacencyEdge] = {}
    for edge in projection.edges:
        if edge.is_legal and not cfg.include_legal_edges:
            continue
        if edge.is_similarity and not cfg.include_similarity_edges:
            continue
        collected[edge.edge_cid] = ResolvedAdjacencyEdge(
            edge_cid=edge.edge_cid,
            source_node_cid=edge.source_node_cid,
            target_node_cid=edge.target_node_cid,
            edge_type=edge.edge_type.value,
            edge_class=edge.edge_class.value,
            weight=edge.weight,
        )
    if overlay is not None and cfg.include_bm25_neighbors:
        by_legal, by_entry = _section_nodes(projection)
        for neighbor in overlay.neighbor_edges:
            source = _resolve_section_node(
                by_legal=by_legal,
                by_entry=by_entry,
                entry_cid=neighbor.source_entry_cid,
                legal_id=neighbor.source_legal_id,
            )
            target = _resolve_section_node(
                by_legal=by_legal,
                by_entry=by_entry,
                entry_cid=neighbor.target_entry_cid,
                legal_id=neighbor.target_legal_id,
            )
            if source is None or target is None:
                continue
            if source.node_cid == target.node_cid:
                continue
            resolved = ResolvedAdjacencyEdge(
                edge_cid=neighbor.edge_cid,
                source_node_cid=source.node_cid,
                target_node_cid=target.node_cid,
                edge_type=neighbor.edge_type,
                edge_class=neighbor.edge_class,
                weight=neighbor.score,
            )
            collected.setdefault(resolved.edge_cid, resolved)
    ordered = tuple(
        sorted(
            collected.values(),
            key=lambda item: (
                item.edge_type,
                item.source_node_cid,
                item.target_node_cid,
                item.edge_cid,
            ),
        )
    )
    return ordered


@dataclass(frozen=True, slots=True)
class TwoWayAdjacency:
    """Incoming and outgoing adjacency pages/shards for one legal graph."""

    outgoing_pages: tuple[AdjacencyPage, ...]
    incoming_pages: tuple[AdjacencyPage, ...]
    outgoing_shards: tuple[AdjacencyShard, ...]
    incoming_shards: tuple[AdjacencyShard, ...]
    outgoing_routes: HierarchicalRouteIndex
    incoming_routes: HierarchicalRouteIndex
    edges: Mapping[str, ResolvedAdjacencyEdge]
    node_cids: tuple[str, ...]
    config: AdjacencyConfig
    graph_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "edges", MappingProxyType(dict(self.edges)))
        assert_adjacency_bounded(self)
        assert_adjacency_reconciled(self)

    @property
    def outgoing_page_count(self) -> int:
        return len(self.outgoing_pages)

    @property
    def incoming_page_count(self) -> int:
        return len(self.incoming_pages)

    @property
    def outgoing_shard_count(self) -> int:
        return len(self.outgoing_shards)

    @property
    def incoming_shard_count(self) -> int:
        return len(self.incoming_shards)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def max_outgoing_pointers(self) -> int:
        return max((page.pointer_count for page in self.outgoing_pages), default=0)

    @property
    def max_incoming_pointers(self) -> int:
        return max((page.pointer_count for page in self.incoming_pages), default=0)

    @property
    def max_outgoing_shard_rows(self) -> int:
        return max((shard.row_count for shard in self.outgoing_shards), default=0)

    @property
    def max_incoming_shard_rows(self) -> int:
        return max((shard.row_count for shard in self.incoming_shards), default=0)

    def pages_for(
        self, node_cid: str, direction: AdjacencyDirection | str
    ) -> tuple[AdjacencyPage, ...]:
        key = _require_non_empty_str(node_cid, "node_cid")
        family = (
            self.outgoing_pages
            if AdjacencyDirection.coerce(direction) is AdjacencyDirection.OUT
            else self.incoming_pages
        )
        return tuple(page for page in family if page.node_cid == key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "edge_count": self.edge_count,
            "graph_cid": self.graph_cid,
            "incoming_page_count": self.incoming_page_count,
            "incoming_shard_count": self.incoming_shard_count,
            "max_incoming_pointers": self.max_incoming_pointers,
            "max_incoming_shard_rows": self.max_incoming_shard_rows,
            "max_outgoing_pointers": self.max_outgoing_pointers,
            "max_outgoing_shard_rows": self.max_outgoing_shard_rows,
            "node_count": len(self.node_cids),
            "outgoing_page_count": self.outgoing_page_count,
            "outgoing_shard_count": self.outgoing_shard_count,
        }


def _triple_set(pages: Sequence[AdjacencyPage], *, outgoing: bool) -> set[tuple[str, str, str]]:
    triples: set[tuple[str, str, str]] = set()
    for page in pages:
        for pointer in page.pointers:
            if outgoing:
                triples.add((page.node_cid, pointer.edge_cid, pointer.neighbor_node_cid))
            else:
                triples.add((pointer.neighbor_node_cid, pointer.edge_cid, page.node_cid))
    return triples


def assert_adjacency_bounded(adjacency: TwoWayAdjacency) -> None:
    """Fail closed if any page or shard exceeds the production 4,096 bound."""

    for page in (*adjacency.outgoing_pages, *adjacency.incoming_pages):
        if page.pointer_count > MAX_ADJACENCY_POINTERS_PER_ROW:
            raise AdjacencyBoundError(
                f"adjacency page {page.node_cid} p{page.page_index} has "
                f"{page.pointer_count} pointers"
            )
        if page.pointer_count > adjacency.config.max_pointers_per_page:
            raise AdjacencyBoundError(
                f"adjacency page {page.node_cid} p{page.page_index} exceeds "
                f"configured max_pointers_per_page="
                f"{adjacency.config.max_pointers_per_page}"
            )
    for shard in (*adjacency.outgoing_shards, *adjacency.incoming_shards):
        if shard.row_count > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise AdjacencyBoundError(
                f"adjacency shard {shard.relative_path} has {shard.row_count} rows"
            )
        if shard.row_count > adjacency.config.max_rows_per_shard:
            raise AdjacencyBoundError(
                f"adjacency shard {shard.relative_path} exceeds configured "
                f"max_rows_per_shard={adjacency.config.max_rows_per_shard}"
            )


def assert_adjacency_reconciled(adjacency: TwoWayAdjacency) -> None:
    """Fail closed unless incoming and outgoing inverses match and resolve."""

    outgoing = _triple_set(adjacency.outgoing_pages, outgoing=True)
    incoming = _triple_set(adjacency.incoming_pages, outgoing=False)
    if outgoing != incoming:
        missing_in = sorted(outgoing - incoming)[:8]
        missing_out = sorted(incoming - outgoing)[:8]
        raise AdjacencyReconciliationError(
            "incoming/outgoing adjacency inverses do not reconcile; "
            f"missing_incoming={missing_in!r} missing_outgoing={missing_out!r}"
        )
    node_set = set(adjacency.node_cids)
    for page in (*adjacency.outgoing_pages, *adjacency.incoming_pages):
        if page.node_cid not in node_set:
            raise AdjacencyReconciliationError(
                f"adjacency page node {page.node_cid} is not in the node set"
            )
        for pointer in page.pointers:
            if pointer.edge_cid not in adjacency.edges:
                raise AdjacencyReconciliationError(
                    f"adjacency pointer {pointer.edge_cid} does not resolve"
                )
            if pointer.neighbor_node_cid not in node_set:
                raise AdjacencyReconciliationError(
                    f"adjacency neighbor {pointer.neighbor_node_cid} does not resolve"
                )
            edge = adjacency.edges[pointer.edge_cid]
            if page.direction is AdjacencyDirection.OUT:
                if (
                    page.node_cid != edge.source_node_cid
                    or pointer.neighbor_node_cid != edge.target_node_cid
                ):
                    raise AdjacencyReconciliationError(
                        f"outgoing pointer {pointer.edge_cid} endpoints drifted"
                    )
            else:
                if (
                    page.node_cid != edge.target_node_cid
                    or pointer.neighbor_node_cid != edge.source_node_cid
                ):
                    raise AdjacencyReconciliationError(
                        f"incoming pointer {pointer.edge_cid} endpoints drifted"
                    )


def build_two_way_adjacency(
    projection: OpenUsLawGraphProjection,
    *,
    overlay: OpenUsLawLexicalGraphOverlay | None = None,
    config: AdjacencyConfig | None = None,
) -> TwoWayAdjacency:
    """Page incoming and outgoing adjacency from a legal-graph projection."""

    if not isinstance(projection, OpenUsLawGraphProjection):
        raise LexicalGraphConfigError("projection must be an OpenUsLawGraphProjection")
    cfg = config or default_adjacency_config()
    if not isinstance(cfg, AdjacencyConfig):
        raise LexicalGraphConfigError("config must be an AdjacencyConfig")

    edges = collect_adjacency_edges(projection, overlay=overlay, config=cfg)
    edge_index = {edge.edge_cid: edge for edge in edges}
    node_cids = tuple(sorted({node.node_cid for node in projection.nodes}))
    outgoing_by_node: dict[str, list[AdjacencyPointer]] = defaultdict(list)
    incoming_by_node: dict[str, list[AdjacencyPointer]] = defaultdict(list)
    for edge in edges:
        outgoing_by_node[edge.source_node_cid].append(
            AdjacencyPointer(
                edge_cid=edge.edge_cid,
                neighbor_node_cid=edge.target_node_cid,
                edge_type=edge.edge_type,
                edge_class=edge.edge_class,
                weight=edge.weight,
            )
        )
        incoming_by_node[edge.target_node_cid].append(
            AdjacencyPointer(
                edge_cid=edge.edge_cid,
                neighbor_node_cid=edge.source_node_cid,
                edge_type=edge.edge_type,
                edge_class=edge.edge_class,
                weight=edge.weight,
            )
        )

    outgoing_pages: list[AdjacencyPage] = []
    incoming_pages: list[AdjacencyPage] = []
    for node_cid in node_cids:
        outgoing_pages.extend(
            page_adjacency_pointers(
                node_cid,
                AdjacencyDirection.OUT,
                outgoing_by_node.get(node_cid, ()),
                max_pointers=cfg.max_pointers_per_page,
            )
        )
        incoming_pages.extend(
            page_adjacency_pointers(
                node_cid,
                AdjacencyDirection.IN,
                incoming_by_node.get(node_cid, ()),
                max_pointers=cfg.max_pointers_per_page,
            )
        )
    outgoing_pages_t = tuple(
        sorted(outgoing_pages, key=lambda page: (page.node_cid, page.page_index))
    )
    incoming_pages_t = tuple(
        sorted(incoming_pages, key=lambda page: (page.node_cid, page.page_index))
    )
    outgoing_shards = shard_adjacency_pages(
        outgoing_pages_t,
        direction=AdjacencyDirection.OUT,
        max_rows=cfg.max_rows_per_shard,
        directory=OUTGOING_ADJACENCY_DIR,
    )
    incoming_shards = shard_adjacency_pages(
        incoming_pages_t,
        direction=AdjacencyDirection.IN,
        max_rows=cfg.max_rows_per_shard,
        directory=INCOMING_ADJACENCY_DIR,
    )
    outgoing_routes = build_hierarchical_routes(
        [shard.to_route_descriptor() for shard in outgoing_shards],
        kind="graph_adjacency_out",
        max_rows_per_page=cfg.max_route_page_rows,
        route_dir=OUTGOING_ROUTE_DIR,
    )
    incoming_routes = build_hierarchical_routes(
        [shard.to_route_descriptor() for shard in incoming_shards],
        kind="graph_adjacency_in",
        max_rows_per_page=cfg.max_route_page_rows,
        route_dir=INCOMING_ROUTE_DIR,
    )
    return TwoWayAdjacency(
        outgoing_pages=outgoing_pages_t,
        incoming_pages=incoming_pages_t,
        outgoing_shards=outgoing_shards,
        incoming_shards=incoming_shards,
        outgoing_routes=outgoing_routes,
        incoming_routes=incoming_routes,
        edges=edge_index,
        node_cids=node_cids,
        config=cfg,
        graph_cid=projection.graph_cid,
    )


# ---------------------------------------------------------------------------
# Fixture binders
# ---------------------------------------------------------------------------


def isolated_alaska_chunk() -> dict[str, Any]:
    """Compact isolated document used to prove postings-driven candidates.

    Body, heading, citation, and title use nonce tokens that do not appear
    in the sealed BM25 fixture so posting-driven accumulation cannot reach
    this document from any other source.
    """

    nonce = "zzzxqwvplkmnjhbgtfvcd"
    return {
        "body": f"{nonce} {nonce}alt",
        "citation": "ZZZXQW 000 § 000",
        "disposition": "admitted",
        "document_index": 99,
        "edition": "2024",
        "entry_cid": "sha256:" + ("0" * 64),
        "heading": nonce,
        "jurisdiction_code": "AK",
        "legal_id": "oul:ak:99:1",
        "section": "000",
        "title": "000",
        "title_name": nonce,
    }


def fixture_lexical_chunks(*, include_isolated: bool = False) -> list[dict[str, Any]]:
    rows = list(fixture_bm25_chunks())
    if include_isolated:
        rows.append(isolated_alaska_chunk())
    return rows


def bind_fixture_lexical_graph(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    *,
    lexical_config: LexicalGraphConfig | None = None,
    include_isolated: bool = False,
    **bm25_overrides: Any,
) -> OpenUsLawLexicalGraphOverlay:
    """Bind the compact BM25 fixture to a lexical overlay."""

    rows = (
        list(chunks)
        if chunks is not None
        else fixture_lexical_chunks(include_isolated=include_isolated)
    )
    index = bind_fixture_bm25(rows, **bm25_overrides)
    return build_open_us_law_lexical_graph(index, config=lexical_config)


def _mappable_similarity_neighbors(
    overlay: OpenUsLawLexicalGraphOverlay,
    records: Sequence[Mapping[str, Any]],
) -> list[SimilarityNeighbor]:
    """Keep only BM25 neighbors whose endpoints exist as graph legal ids."""

    legal_ids = {
        str(row.get("legal_id")).strip()
        for row in records
        if isinstance(row.get("legal_id"), str) and str(row.get("legal_id")).strip()
        and not _is_recovery_or_quarantine_row(row)
    }
    mapped: list[SimilarityNeighbor] = []
    for neighbor in overlay.to_similarity_neighbors():
        if neighbor.source_legal_id in legal_ids and neighbor.target_legal_id in legal_ids:
            mapped.append(neighbor)
    return mapped


def graph_rows_for_bm25(
    records: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Admit graph-seed rows with unique content-addressed BM25 identities.

    The legal-graph fixture reuses a few ``entry_cid`` nibbles across
    rows. BM25 forbids duplicate document identities, so this helper
    derives a unique ``entry_cid`` from each legal id while leaving the
    legal-graph projection's original records untouched.
    """

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in admitted_rows_for_bm25(records or fixture_seed_records()):
        copy = dict(row)
        legal_id = str(copy.get("legal_id") or "").strip()
        if not legal_id:
            continue
        copy["entry_cid"] = "sha256:" + content_sha256(
            canonical_json_dumps({"kind": "oul-031-bm25-identity", "legal_id": legal_id})
        )
        if copy["entry_cid"] in seen:
            raise LexicalGraphParityError(
                f"derived BM25 identity collided for legal_id {legal_id!r}"
            )
        seen.add(copy["entry_cid"])
        rows.append(copy)
    return rows


def bind_fixture_graph_adjacency(
    *,
    lexical_config: LexicalGraphConfig | None = None,
    adjacency_config: AdjacencyConfig | None = None,
) -> tuple[OpenUsLawLexicalGraphOverlay, OpenUsLawGraphProjection, TwoWayAdjacency]:
    """Bind graph + BM25 overlay + two-way adjacency for the sealed recipe."""

    records = fixture_seed_records()
    overlay = bind_fixture_lexical_graph(
        graph_rows_for_bm25(records), lexical_config=lexical_config
    )
    projection = project_open_us_law_graph(
        records,
        similarity_neighbors=_mappable_similarity_neighbors(overlay, records),
    )
    adjacency = build_two_way_adjacency(
        projection,
        overlay=overlay,
        config=adjacency_config or fixture_adjacency_config(),
    )
    return overlay, projection, adjacency


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_graph_adjacency_receipt_path() -> Path:
    return DEFAULT_REPORT_PATH


def build_graph_adjacency_receipt(
    *,
    overlay: OpenUsLawLexicalGraphOverlay | None = None,
    projection: OpenUsLawGraphProjection | None = None,
    adjacency: TwoWayAdjacency | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract adjacency / lexical-graph receipt."""

    if overlay is None or projection is None or adjacency is None:
        bound_overlay, bound_projection, bound_adjacency = bind_fixture_graph_adjacency()
        overlay = overlay or bound_overlay
        projection = projection or bound_projection
        adjacency = adjacency or bound_adjacency
    overlay.assert_bm25_parity()
    projection.assert_semantics_disjoint()
    assert_adjacency_bounded(adjacency)
    assert_adjacency_reconciled(adjacency)

    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_adjacency_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "adjacency_inverses_reconcile": True,
            "all_adjacency_pointers_resolve": True,
            "candidate_accumulation_method": overlay.config.candidate_accumulation,
            "demo_document_count": overlay.document_count,
            "demo_incoming_page_count": adjacency.incoming_page_count,
            "demo_incoming_shard_count": adjacency.incoming_shard_count,
            "demo_max_incoming_pointers": adjacency.max_incoming_pointers,
            "demo_max_incoming_shard_rows": adjacency.max_incoming_shard_rows,
            "demo_max_outgoing_pointers": adjacency.max_outgoing_pointers,
            "demo_max_outgoing_shard_rows": adjacency.max_outgoing_shard_rows,
            "demo_neighbor_edge_count": overlay.neighbor_edge_count,
            "demo_outgoing_page_count": adjacency.outgoing_page_count,
            "demo_outgoing_shard_count": adjacency.outgoing_shard_count,
            "demo_term_count": overlay.term_count,
            "demo_term_document_pair_count": overlay.term_document_pair_count,
            "durable_term_document_expansion_disabled": (
                not overlay.expands_full_term_document_edges
            ),
            "full_corpus_pair_scans": overlay.neighbor_build_stats.full_corpus_pair_scans,
            "incoming_and_outgoing_families_present": (
                adjacency.incoming_page_count >= 1 and adjacency.outgoing_page_count >= 1
            ),
            "lexical_edges_non_authoritative": all(
                edge.authority == EDGE_AUTHORITY and not edge.proof_authority
                for edge in overlay.neighbor_edges
            ),
            "overlay_matches_bm25_postings": True,
            "postings_are_canonical_virtual_graph": True,
            "production_max_adjacency_pointers": MAX_ADJACENCY_POINTERS_PER_ROW,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "similarity_cannot_establish_legal_authority": True,
        },
        "demo": {
            "authorizing_for_release": False,
            "bm25_config_digest": overlay.bm25_config_digest,
            "candidate_accumulation": overlay.config.candidate_accumulation,
            "config_cid": overlay.config_cid,
            "document_count": overlay.document_count,
            "graph_cid": projection.graph_cid,
            "incoming_page_count": adjacency.incoming_page_count,
            "incoming_route_page_count": adjacency.incoming_routes.page_count,
            "incoming_shard_count": adjacency.incoming_shard_count,
            "index_root_cid": overlay.index.index_root_cid,
            "max_incoming_pointers": adjacency.max_incoming_pointers,
            "max_incoming_shard_rows": adjacency.max_incoming_shard_rows,
            "max_outgoing_pointers": adjacency.max_outgoing_pointers,
            "max_outgoing_shard_rows": adjacency.max_outgoing_shard_rows,
            "neighbor_build_stats": overlay.neighbor_build_stats.to_dict(),
            "neighbor_edge_count": overlay.neighbor_edge_count,
            "neighbor_k": overlay.config.neighbor_k,
            "outgoing_page_count": adjacency.outgoing_page_count,
            "outgoing_route_page_count": adjacency.outgoing_routes.page_count,
            "outgoing_shard_count": adjacency.outgoing_shard_count,
            "term_count": overlay.term_count,
            "term_document_pair_count": overlay.term_document_pair_count,
            "tokenizer_id": TOKENIZER_ID,
        },
        "description": (
            "Software-contract receipt for OUL-031. BM25 postings are the "
            "canonical virtual term-document graph. Optional top-k "
            "BM25_NEIGHBOR_OF edges accumulate candidates from posting lists "
            "rather than all-pairs scans. Incoming and outgoing adjacency "
            "pages and physical shards contain at most 4096 pointers or rows. "
            "This receipt does not claim the live exact-51 corpus has been "
            "graphed."
        ),
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "goal_id": GOAL_ID,
        "lexical_graph": overlay.to_manifest_fragment()["lexical_graph"],
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "bm25_backed_lexical_graph_and_bounded_adjacency",
            "owner_task": TASK_ID,
            "required": [
                "Treat BM25 postings as the canonical virtual term-document graph; do not expand every document-term pair into durable edges by default.",
                "Accumulate optional top-k BM25 neighbor candidates from posting lists rather than O(N^2) all-pairs scans.",
                "Page incoming and outgoing adjacency with at most 4096 pointers per row and 4096 rows per physical shard, and reconcile inverses.",
                "Keep BM25 lexical edges non-authoritative so they cannot establish citation, amendment, or legal validity.",
            ],
        },
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sealed_at": RECEIPT_SEALED_AT,
        "task_id": TASK_ID,
    }
    payload.update(software_contract_flags())
    payload["receipt_sha256"] = content_sha256(
        canonical_json_dumps(
            {key: value for key, value in payload.items() if key != "receipt_sha256"}
        )
    )
    return payload


def write_graph_adjacency_receipt(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_graph_adjacency_receipt_path()
    payload = build_graph_adjacency_receipt()
    write_json_atomic(target, payload)
    return target


def load_graph_adjacency_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_graph_adjacency_receipt_path()
    if not target.is_file():
        raise AdjacencyReceiptError(f"graph adjacency receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise AdjacencyReceiptError("graph adjacency receipt root must be an object")
    return dict(payload)


def assert_graph_adjacency_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise AdjacencyReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise AdjacencyReceiptError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_for_release") is True:
        raise GraphReleaseAuthorizationError(
            "graph adjacency receipt cannot authorize release"
        )
    if payload.get("authorizing_for_publication") is True:
        raise GraphReleaseAuthorizationError(
            "graph adjacency receipt cannot authorize publication"
        )
    if payload.get("proves_software_contract_only") is not True:
        raise AdjacencyReceiptError("receipt must prove the software contract only")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise AdjacencyReceiptError("receipt acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) is not expected:
            raise AdjacencyReceiptError(f"receipt acceptance.{key} must be {expected}")
    checks = payload.get("checks") or {}
    if not isinstance(checks, Mapping):
        raise AdjacencyReceiptError("receipt checks must be a mapping")
    if checks.get("candidate_accumulation_method") != CANDIDATE_ACCUMULATION_METHOD:
        raise AdjacencyReceiptError(
            "receipt must record postings-driven candidate accumulation"
        )
    if checks.get("full_corpus_pair_scans") not in {0, False}:
        raise LexicalGraphScanError("receipt reports an all-pairs corpus scan")
    if checks.get("overlay_matches_bm25_postings") is not True:
        raise AdjacencyReceiptError("receipt must prove BM25 postings parity")
    if checks.get("postings_are_canonical_virtual_graph") is not True:
        raise AdjacencyReceiptError(
            "receipt must treat BM25 postings as the canonical virtual graph"
        )
    if checks.get("adjacency_inverses_reconcile") is not True:
        raise AdjacencyReceiptError("receipt must reconcile incoming/outgoing inverses")
    if checks.get("all_adjacency_pointers_resolve") is not True:
        raise AdjacencyReceiptError("receipt must resolve every adjacency pointer")
    if checks.get("production_max_adjacency_pointers") != MAX_ADJACENCY_POINTERS_PER_ROW:
        raise AdjacencyReceiptError("receipt production pointer bound drifted")
    if checks.get("production_max_rows_per_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise AdjacencyReceiptError("receipt production shard bound drifted")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise AdjacencyReceiptError("receipt bounds must be a mapping")
    if bounds.get("maximum_adjacency_pointers_per_row") != MAX_ADJACENCY_POINTERS_PER_ROW:
        raise AdjacencyReceiptError("receipt bound maximum_adjacency_pointers_per_row drifted")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise AdjacencyReceiptError("receipt bound maximum_rows_per_physical_shard drifted")
    if bounds.get("candidate_accumulation_method") != CANDIDATE_ACCUMULATION_METHOD:
        raise AdjacencyReceiptError("receipt bound candidate method drifted")
    expected_digest = content_sha256(
        canonical_json_dumps(
            {key: value for key, value in dict(payload).items() if key != "receipt_sha256"}
        )
    )
    if payload.get("receipt_sha256") != expected_digest:
        raise AdjacencyReceiptError("receipt_sha256 does not match canonical payload")


__all__ = [
    "ADR_PATH",
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "BUNDLE",
    "CANDIDATE_ACCUMULATION_METHOD",
    "DEFAULT_NEIGHBOR_K",
    "DEFAULT_REPORT_PATH",
    "EDGE_AUTHORITY",
    "EDGE_CLASS_SIMILARITY",
    "EDGE_PROOF_AUTHORITY",
    "EDGE_TYPE_BM25_NEIGHBOR",
    "EXACT_51_DOCUMENT_TERM_PAIR_LOWER_BOUND",
    "GOAL_ID",
    "INCOMING_ADJACENCY_DIR",
    "LEXICAL_GRAPH_DEFAULT_MODE",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_NEIGHBOR_K",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "OUTGOING_ADJACENCY_DIR",
    "PRODUCER",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA_VERSION",
    "REPORT_RELATIVE_PATH",
    "SCHEMA_VERSION",
    "TASK_ID",
    "VIRTUAL_DOCUMENT_TERM_EDGE_TYPE",
    "VIRTUAL_TERM_DOCUMENT_EDGE_TYPE",
    "AdjacencyBoundError",
    "AdjacencyConfig",
    "AdjacencyDirection",
    "AdjacencyPage",
    "AdjacencyPointer",
    "AdjacencyReceiptError",
    "AdjacencyReconciliationError",
    "AdjacencyShard",
    "Bm25NeighborEdge",
    "GraphReleaseAuthorizationError",
    "LexicalEdgeKind",
    "LexicalGraphConfig",
    "LexicalGraphConfigError",
    "LexicalGraphExpansionError",
    "LexicalGraphLookupError",
    "LexicalGraphNeighborCapError",
    "LexicalGraphParityError",
    "LexicalGraphScanError",
    "NeighborBuildStats",
    "OpenUsLawLexicalGraphError",
    "OpenUsLawLexicalGraphOverlay",
    "ResolvedAdjacencyEdge",
    "TermPostingList",
    "TwoWayAdjacency",
    "VirtualTermDocumentEdge",
    "accumulate_neighbor_candidates",
    "admitted_rows_for_bm25",
    "adjacency_page_key",
    "assert_adjacency_bounded",
    "assert_adjacency_reconciled",
    "assert_graph_adjacency_receipt",
    "bind_fixture_graph_adjacency",
    "bind_fixture_lexical_graph",
    "build_graph_adjacency_receipt",
    "build_open_us_law_lexical_graph",
    "build_open_us_law_lexical_graph_from_rows",
    "build_two_way_adjacency",
    "collect_adjacency_edges",
    "default_adjacency_config",
    "default_graph_adjacency_receipt_path",
    "default_lexical_graph_config",
    "fixture_adjacency_config",
    "fixture_lexical_chunks",
    "graph_rows_for_bm25",
    "isolated_alaska_chunk",
    "load_graph_adjacency_receipt",
    "materialize_bm25_neighbor_edges",
    "neighbor_query_terms",
    "non_authoritative_edge_semantics",
    "page_adjacency_pointers",
    "production_adjacency_bounds",
    "project_virtual_postings",
    "score_posting_candidates",
    "shard_adjacency_pages",
    "software_contract_flags",
    "write_graph_adjacency_receipt",
]
