"""Federal Register BM25 lexical neighbors and two-way adjacency gate (LCR-076).

Consumes the sealed LCR-056 BM25 index and LCR-058 legal graph as read-only
inputs and produces:

* bounded, postings-driven ``BM25_NEIGHBOR_OF`` lexical overlay edges;
* physical incoming/outgoing adjacency pages and shards (≤ 4,096 pointers
  or rows); and
* a secret-free reconciliation receipt whose digests later query, build,
  and release tasks can bind.

Design invariants
-----------------
* Lexical overlay edges are derived only from the sealed BM25 posting
  space. Candidates are accumulated from posting cells, never all-pairs
  scans. The overlay is a retrieval hint and is **not** legal authority.
* Every durable graph edge appears exactly once in outgoing adjacency and
  exactly once as the inverse in incoming adjacency.
* Overlay, posting, document, and node keys have zero dangling or
  duplicate identities.
* Production pages and shards never exceed 4,096 pointers or rows.
* Fixture-only. No Hub upload, no tokens, no absolute home paths.

BM25 (``federal_register_bm25.py``) and graph (``federal_register_graph.py``)
remain immutable inputs.
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

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    SecretInReceiptError,
    assert_no_secrets,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    FIELD_ORDER,
    PRIMARY_KEY as BM25_PRIMARY_KEY,
    TASK_ID as BM25_TASK_ID,
    TOKENIZER_ID,
    Bm25Hit,
    FederalRegisterBm25Index,
    LegalBm25Document,
    bind_fixture_bm25,
    fixture_bm25_chunks,
)
from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
    ADJACENCY_PAGING_TASK_ID,
    ADJACENCY_SORTED_BY,
    TASK_ID as GRAPH_TASK_ID,
    FederalRegisterGraphNode,
    FederalRegisterGraphProjection,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    SimilarityNeighbor,
    assert_adjacency_inversion,
    assert_edge_uniqueness,
    assert_endpoint_closure,
    bind_fixture_graph,
    sha256_cid,
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    ADR_PATH,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    repository_root,
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
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-adjacency-gate-v1"
RECEIPT_SCHEMA_VERSION: Final = "federal-register-adjacency-reconciliation-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-adjacency@1"
TASK_ID: Final = "LCR-076"
GOAL_ID: Final = "LCR-G120"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_adjacency_gate.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-graph-adjacency-reconciliation"
CODE_VERSION: Final = "1"
MODE_FIXTURE: Final = "fixture"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
HUB_UPLOAD: Final = False

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json"
)

LEXICAL_GRAPH_DEFAULT_MODE: Final = (
    "virtual_term_document_edges_plus_bounded_bm25_neighbors"
)
CANDIDATE_ACCUMULATION_METHOD: Final = "postings_driven"
FORBIDDEN_CANDIDATE_METHODS: Final = frozenset(
    {"all_pairs", "o_n_squared", "pairwise_scan", "full_corpus_scan"}
)

DEFAULT_NEIGHBOR_K: Final = 8
MAX_NEIGHBOR_K: Final = 64
DEFAULT_MAX_NEIGHBOR_QUERY_TERMS: Final = 16
DEFAULT_MIN_NEIGHBOR_TERM_LENGTH: Final = 3

DEFAULT_TEST_MAX_POINTERS_PER_PAGE: Final = 2
DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2
DEFAULT_TEST_ROUTE_PAGE_ROWS: Final = 2

EDGE_AUTHORITY: Final = "non_authoritative"
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

RECOVERY_DISPOSITIONS: Final = frozenset(
    {
        "excluded",
        "quarantined",
        "quarantine",
        "recovery",
        "replaced",
        "failed_final",
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterAdjacencyGateError(ValueError):
    """Base error for Federal Register adjacency-gate failures."""

    code: str = "federal_register_adjacency_gate_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class LexicalGraphConfigError(FederalRegisterAdjacencyGateError):
    """Raised when lexical overlay or adjacency configuration is invalid."""

    code = "config_invalid"


class LexicalGraphParityError(FederalRegisterAdjacencyGateError):
    """Raised when overlay vocabulary/postings diverge from BM25."""

    code = "parity_invalid"


class LexicalGraphNeighborCapError(FederalRegisterAdjacencyGateError):
    """Raised when neighbor materialization exceeds declared caps."""

    code = "neighbor_cap_exceeded"


class LexicalGraphExpansionError(FederalRegisterAdjacencyGateError):
    """Raised when full durable term-document expansion is requested unsafely."""

    code = "expansion_refused"


class LexicalGraphLookupError(FederalRegisterAdjacencyGateError):
    """Raised when a term or document is unknown to the overlay."""

    code = "lookup_invalid"


class LexicalGraphScanError(FederalRegisterAdjacencyGateError):
    """Raised when neighbor search would perform an all-pairs scan."""

    code = "all_pairs_scan_refused"


class AdjacencyBoundError(FederalRegisterAdjacencyGateError):
    """Raised when an adjacency page or shard exceeds the 4,096 bound."""

    code = "adjacency_bound_exceeded"


class AdjacencyReconciliationError(FederalRegisterAdjacencyGateError):
    """Raised when incoming and outgoing adjacency inverses diverge."""

    code = "adjacency_unreconciled"


class AdjacencyKeyParityError(FederalRegisterAdjacencyGateError):
    """Raised when posting, document, or node keys dangle or duplicate."""

    code = "key_parity_invalid"


class AdjacencyReceiptError(FederalRegisterAdjacencyGateError):
    """Raised when the adjacency receipt is missing or invalid."""

    code = "receipt_invalid"


class GraphReleaseAuthorizationError(FederalRegisterAdjacencyGateError):
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
    return sha256_cid(dict(value))


def non_authoritative_edge_semantics() -> dict[str, Any]:
    """Sealed non-authoritative semantics for every lexical overlay edge."""

    return {
        "authority": EDGE_AUTHORITY,
        "edge_class": EDGE_CLASS_SIMILARITY,
        "legal_authority": False,
        "notes": (
            "BM25 lexical overlay edges are retrieval hints only. They are "
            "not legal authority and must never be labeled as citation, "
            "correction, or legal validity."
        ),
        "proof_authority": EDGE_PROOF_AUTHORITY,
        "retrieval_hint": True,
    }


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "hub_upload": HUB_UPLOAD,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def production_adjacency_bounds() -> dict[str, Any]:
    return {
        "adjacency_sorted_by": ADJACENCY_SORTED_BY,
        "candidate_accumulation_method": CANDIDATE_ACCUMULATION_METHOD,
        "forbidden_candidate_methods": sorted(FORBIDDEN_CANDIDATE_METHODS),
        "full_adjacency_paging": TASK_ID,
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "similarity_cannot_establish_legal_authority": True,
    }


def _acceptance_block() -> dict[str, Any]:
    return {
        "bm25_neighbor_lexical_edges_bounded_and_derived_from_sealed_bm25": True,
        "criteria": (
            "Bounded BM25-neighbor lexical edges are derived from the sealed "
            "BM25 space; every graph edge appears exactly once in both "
            "directions; dangling/duplicate keys are zero; shard/pointer "
            "bounds of 4096 hold; receipt digests gate later tasks. Lexical "
            "overlay is not legal authority."
        ),
        "every_graph_edge_appears_exactly_once_in_both_directions": True,
        "hub_upload": False,
        "lexical_overlay_is_not_legal_authority": True,
        "secrets_absent": True,
        "shard_and_pointer_bounds_4096": True,
        "zero_dangling_or_duplicate_keys": True,
    }


def _is_recovery_or_quarantine_row(row: Mapping[str, Any]) -> bool:
    if bool(row.get("is_recovery")):
        return True
    configuration = str(row.get("configuration") or "").strip().lower()
    if configuration in RECOVERY_DISPOSITIONS:
        return True
    disposition = str(row.get("disposition") or row.get("admission_status") or "").strip().lower()
    disposition = disposition.replace("-", "_")
    return disposition in RECOVERY_DISPOSITIONS


def admitted_rows_for_bm25(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
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

    ``candidate_accumulation`` is pinned to ``postings_driven``. All-pairs
    scans are refused. Full term-document expansion is opt-in only.
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
                "allow_full_postings_expansion=True"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_full_postings_expansion": self.allow_full_postings_expansion,
            "candidate_accumulation": self.candidate_accumulation,
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
        return digest_mapping(self.to_dict())

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
        return digest_mapping(self.to_dict())

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
    chunk_cid: Optional[str] = None
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
            "chunk_cid": self.chunk_cid or self.entry_cid,
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
    source_chunk_cid: Optional[str] = None
    target_chunk_cid: Optional[str] = None
    source_document_number: Optional[str] = None
    target_document_number: Optional[str] = None
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
                "kind": "federal_register_bm25_neighbor",
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
            "source_chunk_cid": self.source_chunk_cid or self.source_entry_cid,
            "source_document_number": self.source_document_number,
            "source_entry_cid": self.source_entry_cid,
            "source_legal_id": self.source_legal_id,
            "target_chunk_cid": self.target_chunk_cid or self.target_entry_cid,
            "target_document_number": self.target_document_number,
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
class FederalRegisterLexicalGraphOverlay:
    """Postings-backed lexical graph overlay bound to a sealed BM25 index."""

    index: FederalRegisterBm25Index
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
        if not isinstance(self.index, FederalRegisterBm25Index):
            raise LexicalGraphConfigError("index must be a FederalRegisterBm25Index")
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
                "full term-document edge expansion is disabled by default; "
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
        posting_cids: set[str] = set()
        for shard in self.index.term_shards:
            for term_row in shard.terms:
                bm25_vocab.add(term_row.term)
                bm25_df[term_row.term] = int(term_row.document_frequency)
                for cell in term_row.cells:
                    for pointer in cell.pointers:
                        posting_cids.add(pointer.entry_cid)
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
        if posting_cids != index_ids:
            raise LexicalGraphParityError(
                "posting pointer keys diverge from BM25 document keys"
            )

    def _assert_neighbor_caps(self) -> None:
        counts: dict[str, int] = defaultdict(int)
        seen_pairs: set[tuple[str, str]] = set()
        for edge in self.neighbor_edges:
            pair = (edge.source_entry_cid, edge.target_entry_cid)
            if pair in seen_pairs:
                raise LexicalGraphParityError(
                    "duplicate BM25 neighbor pair "
                    f"{edge.source_entry_cid}->{edge.target_entry_cid}"
                )
            seen_pairs.add(pair)
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
                "primary_key": BM25_PRIMARY_KEY,
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
    index: FederalRegisterBm25Index,
) -> tuple[
    tuple[str, ...],
    dict[str, TermPostingList],
    dict[str, tuple[str, ...]],
    int,
]:
    """Project the canonical virtual term-document graph from BM25 postings."""

    if not isinstance(index, FederalRegisterBm25Index):
        raise LexicalGraphConfigError("index must be a FederalRegisterBm25Index")

    legal_by_cid = {document.entry_cid: document.legal_id for document in index.documents}
    chunk_by_cid = {document.entry_cid: document.chunk_cid for document in index.documents}
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
                            chunk_cid=pointer.chunk_cid or chunk_by_cid.get(pointer.entry_cid),
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
    """Select discriminative query terms for neighbor scoring."""

    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for priority, field_name in enumerate(FIELD_ORDER):
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
    index: FederalRegisterBm25Index,
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
    index: FederalRegisterBm25Index,
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
                chunk_cid=document.chunk_cid,
                legal_id=document.legal_id,
                document_number=document.document_number,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.entry_cid))
    return hits[:top_k]


def materialize_bm25_neighbor_edges(
    index: FederalRegisterBm25Index,
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
    by_cid = {document.entry_cid: document for document in index.documents}
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
            target = by_cid.get(hit.entry_cid)
            edges.append(
                Bm25NeighborEdge(
                    source_entry_cid=document.entry_cid,
                    target_entry_cid=hit.entry_cid,
                    score=hit.score,
                    matched_terms=hit.matched_terms,
                    config_cid=cid,
                    source_legal_id=document.legal_id,
                    target_legal_id=hit.legal_id,
                    source_chunk_cid=document.chunk_cid,
                    target_chunk_cid=(
                        target.chunk_cid if target is not None else hit.chunk_cid
                    ),
                    source_document_number=document.document_number,
                    target_document_number=(
                        target.document_number
                        if target is not None
                        else hit.document_number
                    ),
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


def build_federal_register_lexical_graph(
    index: FederalRegisterBm25Index,
    *,
    config: LexicalGraphConfig | None = None,
) -> FederalRegisterLexicalGraphOverlay:
    """Build the postings-backed lexical graph overlay from a BM25 index."""

    if not isinstance(index, FederalRegisterBm25Index):
        raise LexicalGraphConfigError("index must be a FederalRegisterBm25Index")
    cfg = config or default_lexical_graph_config()
    if not isinstance(cfg, LexicalGraphConfig):
        raise LexicalGraphConfigError("config must be a LexicalGraphConfig")

    vocabulary, postings, document_terms, pair_count = project_virtual_postings(index)
    neighbor_edges, stats = materialize_bm25_neighbor_edges(
        index, config=cfg, config_cid=cfg.config_cid
    )
    return FederalRegisterLexicalGraphOverlay(
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


def build_federal_register_lexical_graph_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    lexical_config: LexicalGraphConfig | None = None,
    **bm25_overrides: Any,
) -> FederalRegisterLexicalGraphOverlay:
    """Convenience: project admitted rows → BM25 index → lexical overlay."""

    admitted = admitted_rows_for_bm25(rows)
    index = bind_fixture_bm25(admitted, **bm25_overrides)
    return build_federal_register_lexical_graph(index, config=lexical_config)


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
            key=lambda item: (item.edge_type, item.neighbor_node_cid, item.edge_cid),
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


def _document_nodes(
    projection: FederalRegisterGraphProjection,
) -> tuple[
    dict[str, FederalRegisterGraphNode],
    dict[str, FederalRegisterGraphNode],
    dict[str, list[FederalRegisterGraphNode]],
]:
    by_legal: dict[str, FederalRegisterGraphNode] = {}
    by_entry: dict[str, FederalRegisterGraphNode] = {}
    by_number: dict[str, list[FederalRegisterGraphNode]] = defaultdict(list)
    for node in projection.nodes:
        if node.node_type is not GraphNodeType.DOCUMENT:
            continue
        if node.legal_id:
            by_legal.setdefault(node.legal_id, node)
        if node.entry_cid:
            by_entry.setdefault(node.entry_cid, node)
        if node.document_number:
            by_number[node.document_number].append(node)
    return by_legal, by_entry, by_number


def _resolve_document_node(
    *,
    by_legal: Mapping[str, FederalRegisterGraphNode],
    by_entry: Mapping[str, FederalRegisterGraphNode],
    by_number: Mapping[str, Sequence[FederalRegisterGraphNode]],
    entry_cid: str | None,
    chunk_cid: str | None,
    legal_id: str | None,
    document_number: str | None,
) -> FederalRegisterGraphNode | None:
    for cid in (entry_cid, chunk_cid):
        if cid and cid in by_entry:
            return by_entry[cid]
    if legal_id:
        if legal_id in by_legal:
            return by_legal[legal_id]
        matches = [
            node
            for key, node in by_legal.items()
            if key == legal_id or key.startswith(legal_id + ":")
        ]
        if len(matches) == 1:
            return matches[0]
    if document_number:
        numbered = list(by_number.get(document_number, ()))
        if len(numbered) == 1:
            return numbered[0]
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
    origin: str = "graph"

    def uniqueness_key(self) -> tuple[str, str, str]:
        return (self.edge_type, self.source_node_cid, self.target_node_cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_class": self.edge_class,
            "edge_type": self.edge_type,
            "origin": self.origin,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
            "weight": self.weight,
        }


def collect_adjacency_edges(
    projection: FederalRegisterGraphProjection,
    *,
    overlay: FederalRegisterLexicalGraphOverlay | None = None,
    config: AdjacencyConfig | None = None,
) -> tuple[ResolvedAdjacencyEdge, ...]:
    """Collect legal, similarity, and optional BM25-neighbor edges."""

    cfg = config or default_adjacency_config()
    collected: dict[str, ResolvedAdjacencyEdge] = {}
    pairs: set[tuple[str, str, str]] = set()
    for edge in projection.edges:
        if edge.is_legal and not cfg.include_legal_edges:
            continue
        if edge.is_similarity and not cfg.include_similarity_edges:
            continue
        resolved = ResolvedAdjacencyEdge(
            edge_cid=edge.edge_cid,
            source_node_cid=edge.source_node_cid,
            target_node_cid=edge.target_node_cid,
            edge_type=edge.edge_type.value,
            edge_class=edge.edge_class.value,
            weight=edge.weight,
            origin="graph",
        )
        collected[resolved.edge_cid] = resolved
        pairs.add(resolved.uniqueness_key())
    if overlay is not None and cfg.include_bm25_neighbors:
        by_legal, by_entry, by_number = _document_nodes(projection)
        for neighbor in overlay.neighbor_edges:
            source = _resolve_document_node(
                by_legal=by_legal,
                by_entry=by_entry,
                by_number=by_number,
                entry_cid=neighbor.source_entry_cid,
                chunk_cid=neighbor.source_chunk_cid,
                legal_id=neighbor.source_legal_id,
                document_number=neighbor.source_document_number,
            )
            target = _resolve_document_node(
                by_legal=by_legal,
                by_entry=by_entry,
                by_number=by_number,
                entry_cid=neighbor.target_entry_cid,
                chunk_cid=neighbor.target_chunk_cid,
                legal_id=neighbor.target_legal_id,
                document_number=neighbor.target_document_number,
            )
            if source is None or target is None:
                continue
            if source.node_cid == target.node_cid:
                continue
            pair = (neighbor.edge_type, source.node_cid, target.node_cid)
            if pair in pairs:
                continue
            resolved = ResolvedAdjacencyEdge(
                edge_cid=neighbor.edge_cid,
                source_node_cid=source.node_cid,
                target_node_cid=target.node_cid,
                edge_type=neighbor.edge_type,
                edge_class=neighbor.edge_class,
                weight=neighbor.score,
                origin="bm25_overlay",
            )
            collected.setdefault(resolved.edge_cid, resolved)
            pairs.add(pair)
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
    graph_edge_cids: tuple[str, ...]
    config: AdjacencyConfig
    graph_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "edges", MappingProxyType(dict(self.edges)))
        object.__setattr__(self, "graph_edge_cids", tuple(self.graph_edge_cids))
        assert_adjacency_bounded(self)
        assert_adjacency_reconciled(self)
        assert_graph_edges_invert_exactly_once(self)
        assert_zero_dangling_or_duplicate_keys(self)

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
            "graph_edge_count": len(self.graph_edge_cids),
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


def assert_graph_edges_invert_exactly_once(adjacency: TwoWayAdjacency) -> None:
    """Fail closed unless every graph edge appears once out and once in."""

    outgoing: dict[str, tuple[str, str]] = {}
    incoming: dict[str, tuple[str, str]] = {}
    for page in adjacency.outgoing_pages:
        for pointer in page.pointers:
            if pointer.edge_cid in outgoing:
                raise AdjacencyReconciliationError(
                    f"edge {pointer.edge_cid} appears twice in outgoing adjacency"
                )
            outgoing[pointer.edge_cid] = (page.node_cid, pointer.neighbor_node_cid)
    for page in adjacency.incoming_pages:
        for pointer in page.pointers:
            if pointer.edge_cid in incoming:
                raise AdjacencyReconciliationError(
                    f"edge {pointer.edge_cid} appears twice in incoming adjacency"
                )
            incoming[pointer.edge_cid] = (pointer.neighbor_node_cid, page.node_cid)
    graph_cids = set(adjacency.graph_edge_cids)
    if not graph_cids.issubset(outgoing) or not graph_cids.issubset(incoming):
        missing_out = sorted(graph_cids - set(outgoing))[:8]
        missing_in = sorted(graph_cids - set(incoming))[:8]
        raise AdjacencyReconciliationError(
            "adjacency does not cover every graph edge exactly once; "
            f"missing_outgoing={missing_out!r} missing_incoming={missing_in!r}"
        )
    for edge_cid in graph_cids:
        edge = adjacency.edges[edge_cid]
        expected = (edge.source_node_cid, edge.target_node_cid)
        if outgoing.get(edge_cid) != expected:
            raise AdjacencyReconciliationError(
                f"outgoing adjacency for graph edge {edge_cid} is not source->target"
            )
        if incoming.get(edge_cid) != expected:
            raise AdjacencyReconciliationError(
                f"incoming adjacency for graph edge {edge_cid} is not the inverse"
            )


def assert_zero_dangling_or_duplicate_keys(adjacency: TwoWayAdjacency) -> None:
    """Fail closed on dangling pointers or duplicate page/edge/node keys."""

    if len(adjacency.node_cids) != len(set(adjacency.node_cids)):
        raise AdjacencyKeyParityError("duplicate node_cid keys in adjacency")
    if len(adjacency.edges) != len(set(adjacency.edges)):
        raise AdjacencyKeyParityError("duplicate edge_cid keys in adjacency")
    if len(adjacency.graph_edge_cids) != len(set(adjacency.graph_edge_cids)):
        raise AdjacencyKeyParityError("duplicate graph edge_cid keys")
    page_keys: list[str] = []
    for page in (*adjacency.outgoing_pages, *adjacency.incoming_pages):
        page_keys.append(f"{page.direction.value}:{page.first_key}")
        if page.node_cid not in set(adjacency.node_cids):
            raise AdjacencyKeyParityError(f"dangling page node {page.node_cid}")
        seen_edges: set[str] = set()
        for pointer in page.pointers:
            if pointer.edge_cid in seen_edges:
                raise AdjacencyKeyParityError(
                    f"duplicate pointer {pointer.edge_cid} on page {page.first_key}"
                )
            seen_edges.add(pointer.edge_cid)
            if pointer.edge_cid not in adjacency.edges:
                raise AdjacencyKeyParityError(
                    f"dangling adjacency pointer {pointer.edge_cid}"
                )
            if pointer.neighbor_node_cid not in set(adjacency.node_cids):
                raise AdjacencyKeyParityError(
                    f"dangling neighbor {pointer.neighbor_node_cid}"
                )
    if len(page_keys) != len(set(page_keys)):
        raise AdjacencyKeyParityError("duplicate adjacency page keys")
    shard_paths = [
        shard.relative_path
        for shard in (*adjacency.outgoing_shards, *adjacency.incoming_shards)
    ]
    if len(shard_paths) != len(set(shard_paths)):
        raise AdjacencyKeyParityError("duplicate adjacency shard paths")


def build_two_way_adjacency(
    projection: FederalRegisterGraphProjection,
    *,
    overlay: FederalRegisterLexicalGraphOverlay | None = None,
    config: AdjacencyConfig | None = None,
) -> TwoWayAdjacency:
    """Page incoming and outgoing adjacency from a legal-graph projection."""

    if not isinstance(projection, FederalRegisterGraphProjection):
        raise LexicalGraphConfigError(
            "projection must be a FederalRegisterGraphProjection"
        )
    cfg = config or default_adjacency_config()
    if not isinstance(cfg, AdjacencyConfig):
        raise LexicalGraphConfigError("config must be an AdjacencyConfig")

    assert_endpoint_closure(projection)
    assert_edge_uniqueness(projection)
    assert_adjacency_inversion(projection)

    edges = collect_adjacency_edges(projection, overlay=overlay, config=cfg)
    edge_index = {edge.edge_cid: edge for edge in edges}
    if len(edge_index) != len(edges):
        raise AdjacencyKeyParityError("collected adjacency edges are not unique by cid")
    node_cids = tuple(sorted({node.node_cid for node in projection.nodes}))
    graph_edge_cids = tuple(sorted(edge.edge_cid for edge in projection.edges))
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
        graph_edge_cids=graph_edge_cids,
        config=cfg,
        graph_cid=projection.graph_cid,
    )


# ---------------------------------------------------------------------------
# Fixture binders
# ---------------------------------------------------------------------------


def isolated_federal_chunk() -> dict[str, Any]:
    """Compact isolated document used to prove postings-driven candidates."""

    nonce = "zzzxqwvplkmnjhbgtfvcd"
    return {
        "agencies": [nonce],
        "body": f"{nonce} {nonce}alt",
        "chunk_cid": "sha256:" + ("c0" * 32),
        "chunk_id": "fr:2026-08888:2026-07-01#chunk=0000",
        "chunk_index": 0,
        "citation": nonce,
        "disposition": "admitted",
        "document_number": "2026-08888",
        "document_type": nonce,
        "entry_cid": "sha256:" + ("c0" * 32),
        "heading": nonce,
        "legal_id": "fr:2026-08888:2026-07-01",
        "parent_entry_cid": "sha256:" + ("c1" * 32),
        "title": nonce,
        "year_month": "2026-07",
    }


def fixture_lexical_chunks(*, include_isolated: bool = False) -> list[dict[str, Any]]:
    rows = list(fixture_bm25_chunks())
    if include_isolated:
        rows.append(isolated_federal_chunk())
    return rows


def bind_fixture_lexical_graph(
    chunks: Sequence[Mapping[str, Any]] | None = None,
    *,
    lexical_config: LexicalGraphConfig | None = None,
    include_isolated: bool = False,
    **bm25_overrides: Any,
) -> FederalRegisterLexicalGraphOverlay:
    """Bind the compact BM25 fixture to a lexical overlay."""

    rows = (
        list(chunks)
        if chunks is not None
        else fixture_lexical_chunks(include_isolated=include_isolated)
    )
    index = bind_fixture_bm25(rows, **bm25_overrides)
    return build_federal_register_lexical_graph(index, config=lexical_config)


def bind_fixture_graph_adjacency(
    *,
    lexical_config: LexicalGraphConfig | None = None,
    adjacency_config: AdjacencyConfig | None = None,
) -> tuple[
    FederalRegisterLexicalGraphOverlay,
    FederalRegisterGraphProjection,
    TwoWayAdjacency,
]:
    """Bind graph + BM25 overlay + two-way adjacency for the sealed recipe."""

    overlay = bind_fixture_lexical_graph(lexical_config=lexical_config)
    projection = bind_fixture_graph()
    adjacency = build_two_way_adjacency(
        projection,
        overlay=overlay,
        config=adjacency_config or fixture_adjacency_config(),
    )
    return overlay, projection, adjacency


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def default_adjacency_reconciliation_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / REPORT_RELATIVE_PATH).resolve()


def _payload_without_digests(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload).items()
        if key not in {"report_digest_sha256", "receipt_sha256"}
    }


def build_federal_adjacency_reconciliation(
    *,
    overlay: FederalRegisterLexicalGraphOverlay | None = None,
    projection: FederalRegisterGraphProjection | None = None,
    adjacency: TwoWayAdjacency | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract adjacency reconciliation receipt."""

    if overlay is None or projection is None or adjacency is None:
        bound_overlay, bound_projection, bound_adjacency = bind_fixture_graph_adjacency()
        overlay = overlay or bound_overlay
        projection = projection or bound_projection
        adjacency = adjacency or bound_adjacency
    overlay.assert_bm25_parity()
    projection.assert_semantics_disjoint()
    assert_endpoint_closure(projection)
    assert_edge_uniqueness(projection)
    assert_adjacency_inversion(projection)
    assert_adjacency_bounded(adjacency)
    assert_adjacency_reconciled(adjacency)
    assert_graph_edges_invert_exactly_once(adjacency)
    assert_zero_dangling_or_duplicate_keys(adjacency)

    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "adjacency": adjacency.to_dict(),
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_adjacency_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "adjacency_inverses_reconcile": True,
            "all_adjacency_pointers_resolve": True,
            "bm25_task_id": BM25_TASK_ID,
            "candidate_accumulation_method": overlay.config.candidate_accumulation,
            "dangling_keys": 0,
            "demo_document_count": overlay.document_count,
            "demo_graph_edge_count": projection.edge_count,
            "demo_graph_node_count": projection.node_count,
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
            "duplicate_keys": 0,
            "durable_term_document_expansion_disabled": (
                not overlay.expands_full_term_document_edges
            ),
            "full_adjacency_paging_owned_by": ADJACENCY_PAGING_TASK_ID,
            "full_corpus_pair_scans": overlay.neighbor_build_stats.full_corpus_pair_scans,
            "graph_edges_invert_exactly_once": True,
            "graph_task_id": GRAPH_TASK_ID,
            "hub_upload": False,
            "incoming_and_outgoing_families_present": (
                adjacency.incoming_page_count >= 1 and adjacency.outgoing_page_count >= 1
            ),
            "lexical_edges_non_authoritative": all(
                edge.authority == EDGE_AUTHORITY and not edge.proof_authority
                for edge in overlay.neighbor_edges
            ),
            "lexical_overlay_derived_from_sealed_bm25": True,
            "lexical_overlay_is_not_legal_authority": True,
            "no_hub_upload": True,
            "overlay_matches_bm25_postings": True,
            "postings_are_canonical_virtual_graph": True,
            "production_max_adjacency_pointers": MAX_ADJACENCY_POINTERS_PER_ROW,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "secrets_absent": True,
            "similarity_cannot_establish_legal_authority": True,
            "zero_dangling_or_duplicate_keys": True,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "authorizing_for_release": False,
            "bm25_config_digest": overlay.bm25_config_digest,
            "candidate_accumulation": overlay.config.candidate_accumulation,
            "config_cid": overlay.config_cid,
            "document_count": overlay.document_count,
            "graph_cid": projection.graph_cid,
            "graph_edge_count": projection.edge_count,
            "graph_node_count": projection.node_count,
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
        "depends_on": [BM25_TASK_ID, GRAPH_TASK_ID],
        "description": (
            "LCR-076 Federal Register BM25 lexical-neighbor and two-way graph "
            "adjacency reconciliation. Bounded BM25_NEIGHBOR_OF overlay edges "
            "are derived from the sealed BM25 posting space. Every graph edge "
            "appears exactly once in outgoing adjacency and exactly once as "
            "the inverse in incoming adjacency. Dangling and duplicate keys "
            "are zero. Physical pages and shards stay at or below 4096. "
            "Lexical overlay is not legal authority. Does not authorize Hub "
            "upload."
        ),
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "lexical_graph": overlay.to_manifest_fragment()["lexical_graph"],
        "mode": MODE_FIXTURE,
        "network_required": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_adjacency_reconciliation",
        "schema": REPORT_SCHEMA,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "task_id": TASK_ID,
    }
    payload.update(software_contract_flags())
    compact = _payload_without_digests(payload)
    assert_no_secrets(compact, context="federal_adjacency_reconciliation")
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError(
            "adjacency reconciliation receipt contains an absolute home path"
        )
    if find_secret_surfaces(compact):
        raise SecretInReceiptError(
            "adjacency reconciliation receipt contains secret surfaces"
        )
    digest = digest_mapping(compact)
    payload["report_digest_sha256"] = digest
    payload["receipt_sha256"] = digest
    return payload


def write_federal_adjacency_reconciliation(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_adjacency_reconciliation_path()
    payload = build_federal_adjacency_reconciliation()
    write_json_atomic(target, payload)
    return target


def load_federal_adjacency_reconciliation(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_adjacency_reconciliation_path()
    if not target.is_file():
        raise AdjacencyReceiptError(
            f"federal adjacency reconciliation receipt not found: {target}"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise AdjacencyReceiptError(
            "federal adjacency reconciliation receipt root must be an object"
        )
    return dict(payload)


def assert_federal_adjacency_reconciliation(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise AdjacencyReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("goal_id") != GOAL_ID:
        raise AdjacencyReceiptError(f"receipt goal_id must be {GOAL_ID!r}")
    if payload.get("program_id") != PROGRAM_ID:
        raise AdjacencyReceiptError(f"receipt program_id must be {PROGRAM_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise AdjacencyReceiptError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_for_release") is True:
        raise GraphReleaseAuthorizationError(
            "adjacency reconciliation receipt cannot authorize release"
        )
    if payload.get("authorizing_for_publication") is True:
        raise GraphReleaseAuthorizationError(
            "adjacency reconciliation receipt cannot authorize publication"
        )
    if payload.get("authorizing_hub_upload") is True:
        raise GraphReleaseAuthorizationError(
            "adjacency reconciliation receipt cannot authorize Hub upload"
        )
    if payload.get("hub_upload") is True:
        raise GraphReleaseAuthorizationError(
            "adjacency reconciliation receipt cannot set hub_upload"
        )
    if payload.get("proves_software_contract_only") is not True:
        raise AdjacencyReceiptError("receipt must prove the software contract only")
    if payload.get("mode") != MODE_FIXTURE:
        raise AdjacencyReceiptError("receipt mode must be fixture")
    if payload.get("network_required") is True:
        raise AdjacencyReceiptError("fixture receipt must not require network")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise AdjacencyReceiptError("receipt acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) != expected:
            raise AdjacencyReceiptError(f"receipt acceptance.{key} must be {expected!r}")
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
    if checks.get("graph_edges_invert_exactly_once") is not True:
        raise AdjacencyReceiptError("receipt must invert every graph edge exactly once")
    if checks.get("all_adjacency_pointers_resolve") is not True:
        raise AdjacencyReceiptError("receipt must resolve every adjacency pointer")
    if checks.get("lexical_overlay_is_not_legal_authority") is not True:
        raise AdjacencyReceiptError("receipt must keep lexical overlay non-authoritative")
    if checks.get("dangling_keys") not in {0, False}:
        raise AdjacencyKeyParityError("receipt reports dangling keys")
    if checks.get("duplicate_keys") not in {0, False}:
        raise AdjacencyKeyParityError("receipt reports duplicate keys")
    if checks.get("zero_dangling_or_duplicate_keys") is not True:
        raise AdjacencyKeyParityError("receipt must prove zero dangling/duplicate keys")
    if checks.get("production_max_adjacency_pointers") != MAX_ADJACENCY_POINTERS_PER_ROW:
        raise AdjacencyReceiptError("receipt production pointer bound drifted")
    if checks.get("production_max_rows_per_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise AdjacencyReceiptError("receipt production shard bound drifted")
    if checks.get("full_adjacency_paging_owned_by") != TASK_ID:
        raise AdjacencyReceiptError("receipt full paging owner drifted")
    if checks.get("secrets_absent") is not True:
        raise AdjacencyReceiptError("receipt must prove secrets_absent")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise AdjacencyReceiptError("receipt bounds must be a mapping")
    if bounds.get("maximum_adjacency_pointers_per_row") != MAX_ADJACENCY_POINTERS_PER_ROW:
        raise AdjacencyReceiptError("receipt bound maximum_adjacency_pointers_per_row drifted")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise AdjacencyReceiptError("receipt bound maximum_rows_per_physical_shard drifted")
    if bounds.get("candidate_accumulation_method") != CANDIDATE_ACCUMULATION_METHOD:
        raise AdjacencyReceiptError("receipt bound candidate method drifted")
    if bounds.get("full_adjacency_paging") != TASK_ID:
        raise AdjacencyReceiptError("receipt bound full_adjacency_paging drifted")
    expected_digest = digest_mapping(_payload_without_digests(payload))
    if payload.get("report_digest_sha256") != expected_digest:
        raise AdjacencyReceiptError("report_digest_sha256 does not match canonical payload")
    if payload.get("receipt_sha256") != expected_digest:
        raise AdjacencyReceiptError("receipt_sha256 does not match canonical payload")
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("receipt contains an absolute home path")
    assert_no_secrets(payload, context="federal_adjacency_reconciliation")
    if find_secret_surfaces(payload):
        raise SecretInReceiptError("receipt contains secret surfaces")


__all__ = [
    "ADR_PATH",
    "ADJACENCY_PAGING_TASK_ID",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "BUNDLE",
    "CANDIDATE_ACCUMULATION_METHOD",
    "DEFAULT_NEIGHBOR_K",
    "EDGE_AUTHORITY",
    "EDGE_CLASS_SIMILARITY",
    "EDGE_PROOF_AUTHORITY",
    "EDGE_TYPE_BM25_NEIGHBOR",
    "GOAL_ID",
    "HUB_UPLOAD",
    "INCOMING_ADJACENCY_DIR",
    "LEXICAL_GRAPH_DEFAULT_MODE",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_NEIGHBOR_K",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MODE_FIXTURE",
    "OUTGOING_ADJACENCY_DIR",
    "PRODUCER",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA_VERSION",
    "REPORT_RELATIVE_PATH",
    "REPORT_SCHEMA",
    "SCHEMA_VERSION",
    "TASK_ID",
    "VIRTUAL_TERM_DOCUMENT_EDGE_TYPE",
    "AdjacencyBoundError",
    "AdjacencyConfig",
    "AdjacencyDirection",
    "AdjacencyKeyParityError",
    "AdjacencyPage",
    "AdjacencyPointer",
    "AdjacencyReceiptError",
    "AdjacencyReconciliationError",
    "AdjacencyShard",
    "Bm25NeighborEdge",
    "FederalRegisterAdjacencyGateError",
    "FederalRegisterLexicalGraphOverlay",
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
    "ResolvedAdjacencyEdge",
    "TermPostingList",
    "TwoWayAdjacency",
    "VirtualTermDocumentEdge",
    "accumulate_neighbor_candidates",
    "admitted_rows_for_bm25",
    "adjacency_page_key",
    "assert_adjacency_bounded",
    "assert_adjacency_reconciled",
    "assert_federal_adjacency_reconciliation",
    "assert_graph_edges_invert_exactly_once",
    "assert_zero_dangling_or_duplicate_keys",
    "bind_fixture_graph_adjacency",
    "bind_fixture_lexical_graph",
    "build_federal_adjacency_reconciliation",
    "build_federal_register_lexical_graph",
    "build_federal_register_lexical_graph_from_rows",
    "build_two_way_adjacency",
    "collect_adjacency_edges",
    "default_adjacency_config",
    "default_adjacency_reconciliation_path",
    "default_lexical_graph_config",
    "fixture_adjacency_config",
    "fixture_lexical_chunks",
    "isolated_federal_chunk",
    "load_federal_adjacency_reconciliation",
    "materialize_bm25_neighbor_edges",
    "neighbor_query_terms",
    "non_authoritative_edge_semantics",
    "page_adjacency_pointers",
    "production_adjacency_bounds",
    "project_virtual_postings",
    "shard_adjacency_pages",
    "software_contract_flags",
    "write_federal_adjacency_reconciliation",
]
