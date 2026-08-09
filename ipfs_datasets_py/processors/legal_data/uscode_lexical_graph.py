"""Postings-backed lexical graph overlay for U.S. Code (USCIR-023).

The BM25 inverted index is the canonical lexical graph. This module exposes:

* **virtual** term→document and document→term traversal through postings
  (no durable edge materialization by default);
* optional deterministic, score-ordered, **bounded** top-K
  ``BM25_NEIGHBOR_OF`` document-to-document edges with config CIDs; and
* explicit **non-authoritative** edge semantics that never collide with
  legal citation/authority edges.

Design invariants
-----------------
* Vocabulary and postings are derived from the same
  :class:`~uscode_bm25.UscodeBm25Index` surface (parity with USCIR-015).
* Default mode is
  ``virtual_term_document_edges_plus_bounded_bm25_neighbors`` (release
  policy). Full term–document edge expansion is **opt-in only** — the
  legacy US Code index has 13,602,252 document-term pairs and must not
  dominate the durable legal graph.
* Neighbor materialization enforces ``neighbor_k`` / ``max_neighbors_per_document``
  caps; scores and config digests are recorded on every edge.
* Similarity edges carry ``authority=non_authoritative`` and
  ``proof_authority=False``; they are retrieval hints only.

No network I/O; unit tests use compact sealed recipes only.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Optional, Union

from ipfs_datasets_py.processors.legal_data.uscode_bm25 import (
    DEFAULT_B,
    DEFAULT_K1,
    FIELD_ORDER,
    PRIMARY_KEY,
    Bm25Hit,
    LegalBm25Document,
    UscodeBm25Config,
    UscodeBm25Index,
    build_uscode_bm25_index,
    content_cid,
    content_sha256,
)
from ipfs_datasets_py.processors.legal_data.uscode_graph import (
    GraphEdgeClass,
    GraphEdgeType,
    SimilarityNeighbor,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    TOKENIZER_ID,
    TokenizerConfig,
    tokenize_legal_text,
)

# ---------------------------------------------------------------------------
# Identity / pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-lexical-graph-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-bm25-neighbors-v1"
TASK_ID: Final = "USCIR-023"
GOAL_ID: Final = "USCIR-G060"
PRODUCER: Final = "uscode_lexical_graph.py"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

# Release-policy default: virtual term-document edges + bounded neighbors.
LEXICAL_GRAPH_DEFAULT_MODE: Final = (
    "virtual_term_document_edges_plus_bounded_bm25_neighbors"
)

# Legacy US Code index document-term pair count (plan §2.3 / risk table).
# Materializing every pair as a durable edge would dominate the legal graph.
LEGACY_DOCUMENT_TERM_PAIR_COUNT: Final = 13_602_252

# Neighbor projection bounds (aligned with SkillCenter / adjacency policy).
DEFAULT_NEIGHBOR_K: Final = 8
MAX_NEIGHBOR_K: Final = 64
DEFAULT_MAX_NEIGHBOR_QUERY_TERMS: Final = 16
DEFAULT_MIN_NEIGHBOR_TERM_LENGTH: Final = 3

# Explicit non-authoritative edge semantics.
EDGE_AUTHORITY: Final = "non_authoritative"
EDGE_PROOF_AUTHORITY: Final = False
EDGE_TYPE_BM25_NEIGHBOR: Final = GraphEdgeType.BM25_NEIGHBOR_OF.value
EDGE_CLASS_SIMILARITY: Final = GraphEdgeClass.SIMILARITY.value
EDGE_METRIC_BM25: Final = "bm25"
RETRIEVAL_METHOD: Final = "bm25-field-weighted"

# Virtual edge type labels (not durable graph ontology members).
VIRTUAL_TERM_DOCUMENT_EDGE_TYPE: Final = "TERM_OCCURS_IN"
VIRTUAL_DOCUMENT_TERM_EDGE_TYPE: Final = "HAS_TERM"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeLexicalGraphError(ValueError):
    """Base error for lexical graph overlay failures."""

    code: str = "uscode_lexical_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class LexicalGraphConfigError(UscodeLexicalGraphError):
    """Raised when lexical graph configuration is invalid."""

    code = "config_invalid"


class LexicalGraphParityError(UscodeLexicalGraphError):
    """Raised when overlay vocabulary/postings diverge from BM25."""

    code = "parity_invalid"


class LexicalGraphNeighborCapError(UscodeLexicalGraphError):
    """Raised when neighbor materialization exceeds declared caps."""

    code = "neighbor_cap_exceeded"


class LexicalGraphExpansionError(UscodeLexicalGraphError):
    """Raised when full durable term-document expansion is requested unsafely."""

    code = "expansion_refused"


class LexicalGraphFixtureError(UscodeLexicalGraphError):
    """Raised when the sealed neighbor fixture is malformed."""

    code = "fixture_invalid"


class LexicalGraphLookupError(UscodeLexicalGraphError):
    """Raised when a term or document is unknown to the overlay."""

    code = "lookup_invalid"


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
        raise LexicalGraphConfigError(
            f"{name}={value} exceeds maximum {maximum}"
        )
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LexicalGraphConfigError(f"{name} must be a non-negative integer")
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LexicalGraphConfig:
    """Bounded lexical overlay configuration.

    ``materialize_term_document_edges`` defaults to ``False`` so the overlay
    never expands the full posting table into durable graph edges unless the
    caller explicitly opts in (and acknowledges the legacy 13.6M-pair risk).
    """

    neighbor_k: int = DEFAULT_NEIGHBOR_K
    max_neighbors_per_document: int = DEFAULT_NEIGHBOR_K
    max_neighbor_query_terms: int = DEFAULT_MAX_NEIGHBOR_QUERY_TERMS
    min_neighbor_term_length: int = DEFAULT_MIN_NEIGHBOR_TERM_LENGTH
    materialize_term_document_edges: bool = False
    materialize_neighbors: bool = True
    allow_full_postings_expansion: bool = False
    mode: str = LEXICAL_GRAPH_DEFAULT_MODE
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "neighbor_k",
            _require_positive_int(
                self.neighbor_k, "neighbor_k", maximum=MAX_NEIGHBOR_K
            ),
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
        mode = _require_non_empty_str(self.mode, "mode", maximum=256)
        object.__setattr__(self, "mode", mode)
        if self.schema_version != SCHEMA_VERSION:
            raise LexicalGraphConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if self.materialize_term_document_edges and not self.allow_full_postings_expansion:
            raise LexicalGraphConfigError(
                "materialize_term_document_edges requires "
                "allow_full_postings_expansion=True; full durable expansion of "
                f"~{LEGACY_DOCUMENT_TERM_PAIR_COUNT:,} document-term pairs is "
                "refused by default"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_full_postings_expansion": self.allow_full_postings_expansion,
            "legacy_document_term_pair_count": LEGACY_DOCUMENT_TERM_PAIR_COUNT,
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
        return content_sha256(self.to_dict())

    @property
    def config_cid(self) -> str:
        return "sha256:" + self.digest


def default_lexical_graph_config() -> LexicalGraphConfig:
    """Return the sealed default lexical overlay configuration."""

    return LexicalGraphConfig()


# ---------------------------------------------------------------------------
# Records
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
        object.__setattr__(
            self, "rank", _require_non_negative_int(self.rank, "rank")
        )

    @property
    def edge_cid(self) -> str:
        """Deterministic content address for the neighbor edge identity."""

        return content_cid(
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
        """Project into the legal-graph similarity input type (USCIR-021)."""

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
    """Sorted posting list for one vocabulary term."""

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


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UscodeLexicalGraphOverlay:
    """Postings-backed lexical graph overlay bound to a BM25 index."""

    index: UscodeBm25Index
    config: LexicalGraphConfig
    vocabulary: tuple[str, ...]
    postings: Mapping[str, TermPostingList]
    document_terms: Mapping[str, tuple[str, ...]]
    term_document_pair_count: int
    neighbor_edges: tuple[Bm25NeighborEdge, ...] = ()
    config_cid: str = ""
    bm25_config_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.index, UscodeBm25Index):
            raise LexicalGraphConfigError("index must be a UscodeBm25Index")
        if not isinstance(self.config, LexicalGraphConfig):
            raise LexicalGraphConfigError("config must be a LexicalGraphConfig")
        object.__setattr__(
            self, "postings", MappingProxyType(dict(self.postings))
        )
        object.__setattr__(
            self, "document_terms", MappingProxyType(dict(self.document_terms))
        )
        if not self.config_cid:
            object.__setattr__(self, "config_cid", self.config.config_cid)
        if not self.bm25_config_digest:
            object.__setattr__(self, "bm25_config_digest", self.index.config.digest)
        # Fail closed on vocabulary/postings parity with BM25.
        self.assert_bm25_parity()
        # Neighbor caps are always enforced on stored edges.
        self._assert_neighbor_caps()

    # -- identity -----------------------------------------------------------

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
        """Count of edges intended for durable materialization.

        Virtual term-document edges are never counted here unless the caller
        explicitly opted into full expansion (still tracked separately).
        """

        return self.neighbor_edge_count

    @property
    def expands_full_term_document_edges(self) -> bool:
        return bool(self.config.materialize_term_document_edges)

    # -- vocabulary / postings (virtual traversal) --------------------------

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
        """Virtual term→document traversal through postings (non-durable)."""

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
            term_iter = tuple(
                _require_non_empty_str(term, "term") for term in terms
            )
        for term in term_iter:
            if term not in self.postings:
                continue
            yield from self.postings[term].postings

    def materialize_all_term_document_edges(self) -> tuple[VirtualTermDocumentEdge, ...]:
        """Explicit opt-in full expansion of term-document edges.

        Refused unless ``allow_full_postings_expansion`` and
        ``materialize_term_document_edges`` are both true. Default overlay
        builds never take this path so the 13.6M-pair table cannot dominate
        the durable legal graph.
        """

        if not (
            self.config.materialize_term_document_edges
            and self.config.allow_full_postings_expansion
        ):
            raise LexicalGraphExpansionError(
                "full term-document edge expansion is disabled by default "
                f"(legacy pair count ≈ {LEGACY_DOCUMENT_TERM_PAIR_COUNT:,}); "
                "set materialize_term_document_edges=True and "
                "allow_full_postings_expansion=True to opt in, or use "
                "iter_virtual_term_document_edges() / documents_for_term()"
            )
        return tuple(self.iter_virtual_term_document_edges())

    # -- neighbors ----------------------------------------------------------

    def neighbors_for_document(
        self,
        entry_cid: str,
        *,
        top_k: int | None = None,
    ) -> tuple[Bm25NeighborEdge, ...]:
        """Return bounded BM25 neighbor edges for one document."""

        key = _require_non_empty_str(entry_cid, "entry_cid")
        if key not in self.document_terms:
            raise LexicalGraphLookupError(f"unknown document: {key!r}")
        k = self.config.neighbor_k if top_k is None else top_k
        k = _require_positive_int(k, "top_k", maximum=self.config.max_neighbors_per_document)
        edges = [edge for edge in self.neighbor_edges if edge.source_entry_cid == key]
        # Already sorted deterministically at build time.
        return tuple(edges[:k])

    def to_similarity_neighbors(self) -> tuple[SimilarityNeighbor, ...]:
        """Export neighbor edges for legal-graph projection (USCIR-021)."""

        return tuple(edge.to_similarity_neighbor() for edge in self.neighbor_edges)

    # -- parity / caps ------------------------------------------------------

    def assert_bm25_parity(self) -> None:
        """Fail closed when overlay vocabulary/postings diverge from BM25."""

        bm25_vocab = set(self.index.document_frequency.keys())
        overlay_vocab = set(self.vocabulary)
        if bm25_vocab != overlay_vocab:
            missing = sorted(bm25_vocab - overlay_vocab)[:8]
            extra = sorted(overlay_vocab - bm25_vocab)[:8]
            raise LexicalGraphParityError(
                "overlay vocabulary does not match BM25; "
                f"missing={missing!r} extra={extra!r}"
            )
        if len(self.vocabulary) != self.index.term_count:
            raise LexicalGraphParityError(
                f"term_count mismatch: overlay={len(self.vocabulary)} "
                f"bm25={self.index.term_count}"
            )
        for term, df in self.index.document_frequency.items():
            posting = self.postings.get(term)
            if posting is None:
                raise LexicalGraphParityError(f"missing postings for term {term!r}")
            if posting.document_frequency != int(df):
                raise LexicalGraphParityError(
                    f"df mismatch for {term!r}: overlay={posting.document_frequency} "
                    f"bm25={df}"
                )
            if len(posting.postings) != int(df):
                raise LexicalGraphParityError(
                    f"posting length mismatch for {term!r}"
                )
        # Document coverage.
        index_ids = {doc.entry_cid for doc in self.index.documents}
        overlay_ids = set(self.document_terms.keys())
        if index_ids != overlay_ids:
            raise LexicalGraphParityError(
                "document coverage diverges from BM25 index"
            )

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

    # -- receipts -----------------------------------------------------------

    def expansion_receipt(self) -> dict[str, Any]:
        """Receipt proving full durable expansion was avoided by default."""

        return {
            "allow_full_postings_expansion": self.config.allow_full_postings_expansion,
            "default_mode": LEXICAL_GRAPH_DEFAULT_MODE,
            "durable_edge_count": self.durable_edge_count,
            "durable_term_document_edges": 0
            if not self.expands_full_term_document_edges
            else self.term_document_pair_count,
            "legacy_document_term_pair_count": LEGACY_DOCUMENT_TERM_PAIR_COUNT,
            "materialize_neighbors": self.config.materialize_neighbors,
            "materialize_term_document_edges": self.config.materialize_term_document_edges,
            "mode": self.config.mode,
            "neighbor_edge_count": self.neighbor_edge_count,
            "term_document_pair_count": self.term_document_pair_count,
            "virtual_traversal_only": not self.expands_full_term_document_edges,
        }

    def to_manifest_fragment(self) -> dict[str, Any]:
        return {
            "goal_id": GOAL_ID,
            "lexical_graph": {
                "bm25_config_digest": self.bm25_config_digest,
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
            "neighbor_edge_count": self.neighbor_edge_count,
            "neighbor_edges": [edge.to_dict() for edge in self.neighbor_edges],
            "term_count": self.term_count,
            "term_document_pair_count": self.term_document_pair_count,
            "vocabulary_head": list(self.vocabulary[:32]),
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _document_term_frequencies(
    document: LegalBm25Document,
) -> dict[str, int]:
    """Aggregate multi-field term frequencies for one document."""

    frequencies: dict[str, int] = defaultdict(int)
    for field_name in FIELD_ORDER:
        stream = document.fields.get(field_name)
        if stream is None:
            continue
        for term, count in stream.term_frequencies().items():
            frequencies[term] += int(count)
    return dict(frequencies)


def _build_postings(
    index: UscodeBm25Index,
) -> tuple[
    tuple[str, ...],
    dict[str, TermPostingList],
    dict[str, tuple[str, ...]],
    int,
]:
    """Build sorted vocabulary, postings, and per-document term maps."""

    term_to_edges: dict[str, list[VirtualTermDocumentEdge]] = defaultdict(list)
    document_terms: dict[str, tuple[str, ...]] = {}
    pair_count = 0

    for document in index.documents:
        frequencies = _document_term_frequencies(document)
        terms = tuple(sorted(frequencies.keys()))
        document_terms[document.entry_cid] = terms
        for term in terms:
            tf = int(frequencies[term])
            if tf <= 0:
                continue
            term_to_edges[term].append(
                VirtualTermDocumentEdge(
                    term=term,
                    entry_cid=document.entry_cid,
                    document_index=document.document_index,
                    term_frequency=tf,
                    legal_id=document.legal_id,
                )
            )
            pair_count += 1

    vocabulary = tuple(sorted(term_to_edges.keys()))
    postings: dict[str, TermPostingList] = {}
    for term in vocabulary:
        edges = sorted(
            term_to_edges[term],
            key=lambda edge: (edge.entry_cid, edge.document_index),
        )
        df = int(index.document_frequency.get(term, 0))
        # Parity: posting list length must equal BM25 df.
        if len(edges) != df:
            raise LexicalGraphParityError(
                f"built postings for {term!r} have length {len(edges)} "
                f"but BM25 df={df}"
            )
        postings[term] = TermPostingList(
            term=term,
            document_frequency=df,
            postings=tuple(edges),
        )
    return vocabulary, postings, document_terms, pair_count


def _neighbor_query_terms(
    document: LegalBm25Document,
    *,
    config: LexicalGraphConfig,
    tokenizer: TokenizerConfig,
) -> tuple[str, ...]:
    """Select discriminative query terms for neighbor scoring.

    Prefer longer authority-field terms (heading/citation/title/hierarchy),
    then body/note. Terms shorter than ``min_neighbor_term_length`` are
    dropped unless no longer candidates exist.
    """

    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    # Authority fields first (higher priority).
    priority_fields = ("heading", "citation", "title", "hierarchy", "body", "note")
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

    # Fallback: re-tokenize heading + body with the sealed legal tokenizer.
    fallback_text = " ".join(
        part
        for part in (
            document.fields.get("heading").text if document.fields.get("heading") else "",
            document.fields.get("body").text if document.fields.get("body") else "",
            document.fields.get("citation").text if document.fields.get("citation") else "",
        )
        if part
    )
    if not fallback_text:
        return ()
    tokenized = tokenize_legal_text(fallback_text, config=tokenizer)
    fallback = list(dict.fromkeys(tokenized.indexable_terms))
    return tuple(fallback[: config.max_neighbor_query_terms])


def _score_neighbors_for_document(
    index: UscodeBm25Index,
    document: LegalBm25Document,
    *,
    query_terms: Sequence[str],
    top_k: int,
) -> list[Bm25Hit]:
    """Score other documents as BM25 neighbors of *document*."""

    if not query_terms or top_k < 1:
        return []
    hits: list[Bm25Hit] = []
    for candidate in index.documents:
        if candidate.entry_cid == document.entry_cid:
            continue
        score, matched, explanations = index.score_document(candidate, query_terms)
        if score <= 0.0 or not matched:
            continue
        hits.append(
            Bm25Hit(
                entry_cid=candidate.entry_cid,
                document_index=candidate.document_index,
                score=score,
                matched_terms=matched,
                explanations=explanations,
                filters=candidate.filters,
                legal_id=candidate.legal_id,
                authority=EDGE_AUTHORITY,
                proof_authority=EDGE_PROOF_AUTHORITY,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.entry_cid))
    return hits[:top_k]


def materialize_bm25_neighbor_edges(
    index: UscodeBm25Index,
    *,
    config: LexicalGraphConfig | None = None,
    config_cid: str | None = None,
) -> tuple[Bm25NeighborEdge, ...]:
    """Emit deterministic bounded top-K ``BM25_NEIGHBOR_OF`` edges.

    Neighbor caps (``neighbor_k`` / ``max_neighbors_per_document``) are
    enforced per source document. Edges are sorted by
    ``(source_entry_cid, -score, target_entry_cid)``.
    """

    cfg = config or default_lexical_graph_config()
    if not isinstance(cfg, LexicalGraphConfig):
        raise LexicalGraphConfigError("config must be a LexicalGraphConfig")
    if not cfg.materialize_neighbors:
        return ()

    cid = config_cid or cfg.config_cid
    edges: list[Bm25NeighborEdge] = []
    for document in index.documents:
        query_terms = _neighbor_query_terms(
            document,
            config=cfg,
            tokenizer=index.config.tokenizer,
        )
        hits = _score_neighbors_for_document(
            index,
            document,
            query_terms=query_terms,
            top_k=cfg.neighbor_k,
        )
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
        key=lambda edge: (
            edge.source_entry_cid,
            -edge.score,
            edge.target_entry_cid,
        )
    )
    # Final per-source cap check (fail closed).
    per_source: dict[str, int] = defaultdict(int)
    for edge in edges:
        per_source[edge.source_entry_cid] += 1
        if per_source[edge.source_entry_cid] > cfg.max_neighbors_per_document:
            raise LexicalGraphNeighborCapError(
                "neighbor cap exceeded after materialization for "
                f"{edge.source_entry_cid}"
            )
    return tuple(edges)


def build_uscode_lexical_graph(
    index: UscodeBm25Index,
    *,
    config: LexicalGraphConfig | None = None,
) -> UscodeLexicalGraphOverlay:
    """Build the postings-backed lexical graph overlay from a BM25 index.

    By default:

    * term-document relationships remain **virtual** (postings traversal);
    * bounded ``BM25_NEIGHBOR_OF`` edges are materialized with scores and
      config CIDs when ``materialize_neighbors=True``;
    * full durable expansion of all document-term pairs is refused.
    """

    if not isinstance(index, UscodeBm25Index):
        raise LexicalGraphConfigError("index must be a UscodeBm25Index")
    cfg = config or default_lexical_graph_config()
    if not isinstance(cfg, LexicalGraphConfig):
        raise LexicalGraphConfigError("config must be a LexicalGraphConfig")

    vocabulary, postings, document_terms, pair_count = _build_postings(index)
    neighbor_edges = materialize_bm25_neighbor_edges(
        index, config=cfg, config_cid=cfg.config_cid
    )

    overlay = UscodeLexicalGraphOverlay(
        index=index,
        config=cfg,
        vocabulary=vocabulary,
        postings=postings,
        document_terms=document_terms,
        term_document_pair_count=pair_count,
        neighbor_edges=neighbor_edges,
        config_cid=cfg.config_cid,
        bm25_config_digest=index.config.digest,
    )
    return overlay


def build_uscode_lexical_graph_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bm25_config: UscodeBm25Config | None = None,
    lexical_config: LexicalGraphConfig | None = None,
) -> UscodeLexicalGraphOverlay:
    """Convenience: project admitted rows → BM25 index → lexical overlay."""

    index = build_uscode_bm25_index(rows, config=bm25_config)
    return build_uscode_lexical_graph(index, config=lexical_config)


# ---------------------------------------------------------------------------
# Fixture recipe (compact; no bulk golden dumps)
# ---------------------------------------------------------------------------


def _sample_corpus_rows() -> list[dict[str, Any]]:
    """Compact admitted corpus sample shared with BM25 fixture spirit."""

    return [
        {
            "entry_cid": "sha256:" + ("a" * 64),
            "chunk_cid": "sha256:" + ("b" * 64),
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "heading": (
                "Public information; agency rules, opinions, orders, records, "
                "and proceedings"
            ),
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "body": (
                "Each agency shall make available to the public information "
                "as follows: final opinions and orders made in the adjudication "
                "of cases under the Freedom of Information Act."
            ),
            "note": "Known as the Freedom of Information Act.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("c" * 64),
            "chunk_cid": "sha256:" + ("d" * 64),
            "legal_id": "usc:us:5:552a",
            "title": "5",
            "section": "552a",
            "heading": "Records maintained on individuals",
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "body": (
                "No agency shall disclose any record which is contained in a "
                "system of records by any means of communication to any person "
                "or to another agency."
            ),
            "note": "Privacy Act of 1974.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("e" * 64),
            "chunk_cid": "sha256:" + ("f" * 64),
            "legal_id": "usc:us:35:101",
            "title": "35",
            "section": "101",
            "heading": "Inventions patentable",
            "chapter": "10",
            "citation": "35 U.S.C. § 101",
            "body": (
                "Whoever invents or discovers any new and useful process, "
                "machine, manufacture, or composition of matter may obtain a patent."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("1" * 64),
            "chunk_cid": "sha256:" + ("2" * 64),
            "legal_id": "usc:us:35:103",
            "title": "35",
            "section": "103",
            "heading": "Conditions for patentability; non-obvious subject matter",
            "chapter": "10",
            "citation": "35 U.S.C. § 103",
            "body": (
                "A patent for a claimed invention may not be obtained if the "
                "differences between the claimed invention and the prior art "
                "would have been obvious before the effective filing date."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("3" * 64),
            "chunk_cid": "sha256:" + ("4" * 64),
            "legal_id": "usc:us:17:107",
            "title": "17",
            "section": "107",
            "heading": "Limitations on exclusive rights: Fair use",
            "chapter": "1",
            "citation": "17 U.S.C. § 107",
            "body": (
                "Notwithstanding the provisions of sections 106 and 106A, the "
                "fair use of a copyrighted work is not an infringement of copyright."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "entry_cid": "sha256:" + ("9" * 64),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
        },
    ]


def build_default_bm25_neighbors_fixture_payload() -> dict[str, Any]:
    """Compact sealed recipe for USCIR-023 (no bulk edge golden dumps)."""

    return {
        "acceptance": {
            "edge_semantics_explicitly_non_authoritative": True,
            "full_term_document_expansion_disabled_by_default": True,
            "neighbor_caps_enforced": True,
            "overlay_matches_bm25_vocabulary_postings": True,
        },
        "cases": [
            {
                "case_id": "vocabulary-postings-parity",
                "expect": {
                    "document_count": 5,
                    "vocabulary_matches_bm25": True,
                },
                "kind": "parity",
            },
            {
                "case_id": "virtual-term-document-traversal",
                "expect": {
                    "min_postings": 1,
                    "term": "patent",
                },
                "kind": "virtual_traversal",
            },
            {
                "case_id": "bounded-neighbors",
                "expect": {
                    "max_neighbors_per_source": DEFAULT_NEIGHBOR_K,
                    "neighbor_k": DEFAULT_NEIGHBOR_K,
                },
                "kind": "neighbor_cap",
            },
            {
                "case_id": "no-full-expansion-by-default",
                "expect": {
                    "durable_term_document_edges": 0,
                    "legacy_pair_count": LEGACY_DOCUMENT_TERM_PAIR_COUNT,
                    "virtual_traversal_only": True,
                },
                "kind": "no_full_expansion",
            },
            {
                "case_id": "non-authoritative-semantics",
                "expect": {
                    "authority": EDGE_AUTHORITY,
                    "edge_type": EDGE_TYPE_BM25_NEIGHBOR,
                    "proof_authority": False,
                },
                "kind": "non_authoritative",
            },
            {
                "case_id": "neighbor-scores-and-config-cid",
                "expect": {
                    "min_neighbor_edges": 1,
                    "require_config_cid": True,
                    "require_positive_scores": True,
                },
                "kind": "neighbor_scores",
            },
        ],
        "default_parameters": {
            "b": DEFAULT_B,
            "k1": DEFAULT_K1,
            "max_neighbors_per_document": DEFAULT_NEIGHBOR_K,
            "mode": LEXICAL_GRAPH_DEFAULT_MODE,
            "neighbor_k": DEFAULT_NEIGHBOR_K,
            "tokenizer_id": TOKENIZER_ID,
        },
        "edge_semantics": non_authoritative_edge_semantics(),
        "goal_id": GOAL_ID,
        "legacy_document_term_pair_count": LEGACY_DOCUMENT_TERM_PAIR_COUNT,
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
    }


def default_bm25_neighbors_fixture_path() -> Path:
    """Path to the sealed on-disk fixture relative to the tests tree."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_bm25_neighbors.json"
    )


def load_bm25_neighbors_fixture_payload(
    path: PathLike | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the sealed BM25 neighbors fixture."""

    target = Path(path) if path is not None else default_bm25_neighbors_fixture_path()
    if not target.is_file():
        raise LexicalGraphFixtureError(f"neighbors fixture missing: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LexicalGraphFixtureError(
            f"neighbors fixture is unreadable: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise LexicalGraphFixtureError("neighbors fixture root must be a mapping")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise LexicalGraphFixtureError(
            f"unexpected fixture schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("task_id") != TASK_ID:
        raise LexicalGraphFixtureError(
            f"unexpected fixture task_id: {payload.get('task_id')!r}"
        )
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise LexicalGraphFixtureError(
            "neighbors fixture cases must be a non-empty list"
        )
    return dict(payload)


def run_fixture_case(
    case: Mapping[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    bm25_config: UscodeBm25Config | None = None,
    lexical_config: LexicalGraphConfig | None = None,
) -> dict[str, Any]:
    """Execute one sealed fixture case and return a result envelope."""

    if not isinstance(case, Mapping):
        raise LexicalGraphFixtureError("fixture case must be a mapping")
    case_id = str(case.get("case_id") or "")
    kind = str(case.get("kind") or "")
    expect = dict(case.get("expect") or {})
    sample = list(rows) if rows is not None else _sample_corpus_rows()
    index = build_uscode_bm25_index(sample, config=bm25_config)
    overlay = build_uscode_lexical_graph(index, config=lexical_config)

    if kind == "parity":
        try:
            overlay.assert_bm25_parity()
            parity_ok = True
            error = None
        except LexicalGraphParityError as exc:
            parity_ok = False
            error = str(exc)
        expected_docs = int(expect.get("document_count", overlay.document_count))
        ok = (
            parity_ok
            and overlay.document_count == expected_docs
            and bool(expect.get("vocabulary_matches_bm25", True))
        )
        return {
            "case_id": case_id,
            "document_count": overlay.document_count,
            "error": error,
            "kind": kind,
            "ok": ok,
            "term_count": overlay.term_count,
        }

    if kind == "virtual_traversal":
        term = str(expect.get("term") or "patent")
        if not overlay.has_term(term):
            # Fall back to any vocabulary term present in BM25.
            term = overlay.vocabulary[0] if overlay.vocabulary else term
        edges = overlay.documents_for_term(term)
        ok = len(edges) >= int(expect.get("min_postings", 1)) and all(
            not edge.durable and edge.authority == EDGE_AUTHORITY for edge in edges
        )
        return {
            "case_id": case_id,
            "kind": kind,
            "ok": ok,
            "posting_count": len(edges),
            "term": term,
        }

    if kind == "neighbor_cap":
        max_per = int(expect.get("max_neighbors_per_source", overlay.config.neighbor_k))
        k = int(expect.get("neighbor_k", overlay.config.neighbor_k))
        counts: dict[str, int] = defaultdict(int)
        for edge in overlay.neighbor_edges:
            counts[edge.source_entry_cid] += 1
        ok = all(count <= max_per and count <= k for count in counts.values()) and (
            overlay.config.neighbor_k == k
            or k == overlay.config.neighbor_k
        )
        # Cap must hold even when top_k request is larger than allowed.
        if overlay.neighbor_edges:
            source = overlay.neighbor_edges[0].source_entry_cid
            try:
                capped = overlay.neighbors_for_document(
                    source, top_k=overlay.config.max_neighbors_per_document
                )
                ok = ok and len(capped) <= overlay.config.max_neighbors_per_document
            except LexicalGraphLookupError:
                ok = False
        return {
            "case_id": case_id,
            "kind": kind,
            "max_observed": max(counts.values()) if counts else 0,
            "neighbor_edge_count": overlay.neighbor_edge_count,
            "ok": ok,
        }

    if kind == "no_full_expansion":
        receipt = overlay.expansion_receipt()
        ok = (
            receipt["virtual_traversal_only"]
            is bool(expect.get("virtual_traversal_only", True))
            and int(receipt["durable_term_document_edges"])
            == int(expect.get("durable_term_document_edges", 0))
            and int(receipt["legacy_document_term_pair_count"])
            == int(expect.get("legacy_pair_count", LEGACY_DOCUMENT_TERM_PAIR_COUNT))
            and not overlay.expands_full_term_document_edges
        )
        expansion_refused = False
        try:
            overlay.materialize_all_term_document_edges()
        except LexicalGraphExpansionError:
            expansion_refused = True
        ok = ok and expansion_refused
        return {
            "case_id": case_id,
            "expansion_refused": expansion_refused,
            "kind": kind,
            "ok": ok,
            "receipt": receipt,
        }

    if kind == "non_authoritative":
        expected_authority = str(expect.get("authority") or EDGE_AUTHORITY)
        expected_type = str(expect.get("edge_type") or EDGE_TYPE_BM25_NEIGHBOR)
        expected_proof = bool(expect.get("proof_authority", False))
        ok = True
        for edge in overlay.neighbor_edges:
            if edge.authority != expected_authority:
                ok = False
            if edge.proof_authority != expected_proof:
                ok = False
            if edge.edge_type != expected_type:
                ok = False
            if edge.edge_class != EDGE_CLASS_SIMILARITY:
                ok = False
        semantics = non_authoritative_edge_semantics()
        ok = ok and semantics["authority"] == expected_authority
        ok = ok and semantics["proof_authority"] is False
        ok = ok and semantics["legal_authority"] is False
        return {
            "case_id": case_id,
            "edge_count": overlay.neighbor_edge_count,
            "kind": kind,
            "ok": ok,
            "semantics": semantics,
        }

    if kind == "neighbor_scores":
        min_edges = int(expect.get("min_neighbor_edges", 1))
        ok = overlay.neighbor_edge_count >= min_edges
        if expect.get("require_positive_scores", True):
            ok = ok and all(edge.score > 0.0 for edge in overlay.neighbor_edges)
        if expect.get("require_config_cid", True):
            ok = ok and all(
                isinstance(edge.config_cid, str) and edge.config_cid.startswith("sha256:")
                for edge in overlay.neighbor_edges
            )
            ok = ok and overlay.config_cid.startswith("sha256:")
        # Deterministic order: non-increasing score within each source.
        by_source: dict[str, list[Bm25NeighborEdge]] = defaultdict(list)
        for edge in overlay.neighbor_edges:
            by_source[edge.source_entry_cid].append(edge)
        for group in by_source.values():
            scores = [edge.score for edge in group]
            ok = ok and scores == sorted(scores, reverse=True)
        return {
            "case_id": case_id,
            "kind": kind,
            "neighbor_edge_count": overlay.neighbor_edge_count,
            "ok": ok,
            "sample": overlay.neighbor_edges[0].to_dict()
            if overlay.neighbor_edges
            else None,
        }

    raise LexicalGraphFixtureError(f"unknown fixture case kind: {kind!r}")


def run_all_fixture_cases(
    path: PathLike | None = None,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run every sealed fixture case and return result envelopes."""

    payload = load_bm25_neighbors_fixture_payload(path)
    sample = list(rows) if rows is not None else _sample_corpus_rows()
    return [run_fixture_case(case, rows=sample) for case in payload["cases"]]


__all__ = [
    "DEFAULT_NEIGHBOR_K",
    "EDGE_AUTHORITY",
    "EDGE_CLASS_SIMILARITY",
    "EDGE_PROOF_AUTHORITY",
    "EDGE_TYPE_BM25_NEIGHBOR",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "LEGACY_DOCUMENT_TERM_PAIR_COUNT",
    "LEXICAL_GRAPH_DEFAULT_MODE",
    "MAX_NEIGHBOR_K",
    "PRODUCER",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "TASK_ID",
    "VIRTUAL_DOCUMENT_TERM_EDGE_TYPE",
    "VIRTUAL_TERM_DOCUMENT_EDGE_TYPE",
    "Bm25NeighborEdge",
    "LexicalEdgeKind",
    "LexicalGraphConfig",
    "LexicalGraphConfigError",
    "LexicalGraphExpansionError",
    "LexicalGraphFixtureError",
    "LexicalGraphLookupError",
    "LexicalGraphNeighborCapError",
    "LexicalGraphParityError",
    "TermPostingList",
    "UscodeLexicalGraphError",
    "UscodeLexicalGraphOverlay",
    "VirtualTermDocumentEdge",
    "build_default_bm25_neighbors_fixture_payload",
    "build_uscode_lexical_graph",
    "build_uscode_lexical_graph_from_rows",
    "default_bm25_neighbors_fixture_path",
    "default_lexical_graph_config",
    "load_bm25_neighbors_fixture_payload",
    "materialize_bm25_neighbor_edges",
    "non_authoritative_edge_semantics",
    "run_all_fixture_cases",
    "run_fixture_case",
]
