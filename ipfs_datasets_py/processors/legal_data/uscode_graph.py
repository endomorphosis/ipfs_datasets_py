"""Legal ontology and citation projection for the U.S. Code graph (USCIR-021).

This module owns the versioned legal graph ontology and the deterministic
projection of structural, citation, public-law, amendment/repeal/transfer,
version, source, and unresolved-reference nodes/edges with evidence spans.

Design invariants
-----------------
* Legal and similarity edge semantics are **disjoint**. Similarity edges
  (``BM25_NEIGHBOR_OF``, ``SIMILAR_TO``) are non-authoritative retrieval hints
  and must never be labeled as legal citation or authority.
* Unresolved citations are preserved honestly: source text, parser version,
  and ``resolution_status=unresolved`` are retained. Targets are never
  invented.
* Legal edges that cite textual evidence bind exact source spans
  (``start``/``end`` offsets and excerpt text) to a source document.
* Node and edge CIDs are deterministic content addresses over stable
  identity payloads (``sha256:<hex>``).
* Physical adjacency paging and BM25 neighbor materialization belong to
  USCIR-022 / USCIR-023; this module emits the legal ontology projection
  only.

No network I/O or Parquet I/O; unit tests use sealed compact fixtures.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.uscode_identity import (
    DEFAULT_JURISDICTION,
    build_legal_id,
    normalize_section_token,
    normalize_title,
    parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    GraphEdgeRecord,
    GraphNodeRecord,
    content_sha256,
    digest_mapping,
)

# ---------------------------------------------------------------------------
# Schema / task pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-graph-v1"
ONTOLOGY_VERSION: Final = "uscode-graph-ontology/v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-graph-expected-v1"
CITATION_PARSER_VERSION: Final = "uscode-citation-parser/v1"
TASK_ID: Final = "USCIR-021"
GOAL_ID: Final = "USCIR-G060"
PRODUCER: Final = "uscode_graph.py"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class GraphNodeType(str, Enum):
    """Versioned legal graph node vocabulary (USCIR-021)."""

    CODE = "code"
    TITLE = "title"
    SUBTITLE = "subtitle"
    CHAPTER = "chapter"
    SUBCHAPTER = "subchapter"
    PART = "part"
    SUBPART = "subpart"
    SECTION = "section"
    SUBSECTION = "subsection"
    NOTE = "note"
    PUBLIC_LAW = "public_law"
    STATUTES_AT_LARGE = "statutes_at_large"
    SOURCE_PACKAGE = "source_package"
    SOURCE_GRANULE = "source_granule"
    RELEASE_POINT = "release_point"
    AGENCY = "agency"
    UNRESOLVED_CITATION = "unresolved_citation"
    BM25_TERM = "bm25_term"
    VERSION = "version"

    @classmethod
    def coerce(cls, value: Any) -> "GraphNodeType":
        if isinstance(value, GraphNodeType):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise GraphOntologyError(f"unsupported graph node type: {value!r}")


class GraphEdgeType(str, Enum):
    """Versioned legal / similarity edge vocabulary (USCIR-021)."""

    CONTAINS = "CONTAINS"
    CODIFIES = "CODIFIES"
    CITES = "CITES"
    AMENDS = "AMENDS"
    REPEALS = "REPEALS"
    TRANSFERS = "TRANSFERS"
    DERIVED_FROM = "DERIVED_FROM"
    HAS_SOURCE = "HAS_SOURCE"
    HAS_VERSION = "HAS_VERSION"
    CITES_UNRESOLVED = "CITES_UNRESOLVED"
    BM25_NEIGHBOR_OF = "BM25_NEIGHBOR_OF"
    SIMILAR_TO = "SIMILAR_TO"

    @classmethod
    def coerce(cls, value: Any) -> "GraphEdgeType":
        if isinstance(value, GraphEdgeType):
            return value
        text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name == text:
                return item
        raise GraphOntologyError(f"unsupported graph edge type: {value!r}")


class GraphEdgeClass(str, Enum):
    """Edge partition that keeps legal authority disjoint from similarity."""

    STRUCTURAL = "structural"
    AUTHORITY = "authority"
    CITATION = "citation"
    PROVENANCE = "provenance"
    UNRESOLVED = "unresolved"
    SIMILARITY = "similarity"

    @classmethod
    def coerce(cls, value: Any) -> "GraphEdgeClass":
        if isinstance(value, GraphEdgeClass):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise GraphOntologyError(f"unsupported graph edge class: {value!r}")


class ResolutionStatus(str, Enum):
    """Citation resolution honesty labels."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"

    @classmethod
    def coerce(cls, value: Any) -> "ResolutionStatus":
        if isinstance(value, ResolutionStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise GraphOntologyError(f"unsupported resolution status: {value!r}")


# Legal edge types (authoritative / structural / provenance).
LEGAL_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.CONTAINS,
        GraphEdgeType.CODIFIES,
        GraphEdgeType.CITES,
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
        GraphEdgeType.DERIVED_FROM,
        GraphEdgeType.HAS_SOURCE,
        GraphEdgeType.HAS_VERSION,
        GraphEdgeType.CITES_UNRESOLVED,
    }
)

# Similarity edge types (non-authoritative retrieval hints).
SIMILARITY_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.BM25_NEIGHBOR_OF,
        GraphEdgeType.SIMILAR_TO,
    }
)

# Edge types that require a bound source span.
SPAN_REQUIRED_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.CITES,
        GraphEdgeType.CODIFIES,
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
        GraphEdgeType.CITES_UNRESOLVED,
        GraphEdgeType.DERIVED_FROM,
    }
)

LEGAL_EDGE_CLASSES: Final[frozenset[GraphEdgeClass]] = frozenset(
    {
        GraphEdgeClass.STRUCTURAL,
        GraphEdgeClass.AUTHORITY,
        GraphEdgeClass.CITATION,
        GraphEdgeClass.PROVENANCE,
        GraphEdgeClass.UNRESOLVED,
    }
)

DEFAULT_EDGE_CLASS: Final[Mapping[GraphEdgeType, GraphEdgeClass]] = MappingProxyType(
    {
        GraphEdgeType.CONTAINS: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.CODIFIES: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.CITES: GraphEdgeClass.CITATION,
        GraphEdgeType.AMENDS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.REPEALS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.TRANSFERS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.DERIVED_FROM: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.HAS_SOURCE: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.HAS_VERSION: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.CITES_UNRESOLVED: GraphEdgeClass.UNRESOLVED,
        GraphEdgeType.BM25_NEIGHBOR_OF: GraphEdgeClass.SIMILARITY,
        GraphEdgeType.SIMILAR_TO: GraphEdgeClass.SIMILARITY,
    }
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeGraphError(ValueError):
    """Base error for legal graph ontology / projection failures."""

    code: str = "uscode_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class GraphOntologyError(UscodeGraphError):
    """Raised when ontology contracts are violated."""

    code = "graph_ontology"


class SourceSpanError(UscodeGraphError):
    """Raised when a source span is unbound or inconsistent."""

    code = "source_span"


class CitationResolutionError(UscodeGraphError):
    """Raised when citation resolution is malformed (not merely unresolved)."""

    code = "citation_resolution"


class GraphProjectionError(UscodeGraphError):
    """Raised when graph projection fails integrity checks."""

    code = "graph_projection"


class GraphFixtureError(UscodeGraphError):
    """Raised when the sealed graph fixture is malformed."""

    code = "graph_fixture"


class LegalSimilarityCollisionError(UscodeGraphError):
    """Raised when legal and similarity semantics are mixed."""

    code = "legal_similarity_collision"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeGraphError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise UscodeGraphError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise UscodeGraphError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UscodeGraphError(f"{name} must be an integer")
    if value < 0:
        raise UscodeGraphError(f"{name} must be >= 0")
    return value


def sha256_cid(payload: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:<hex>`` content address."""

    digest = digest_mapping(dict(payload))
    return f"sha256:{digest}"


def assert_legal_similarity_disjoint() -> None:
    """Fail closed if legal and similarity edge vocabularies overlap."""

    overlap = LEGAL_EDGE_TYPES & SIMILARITY_EDGE_TYPES
    if overlap:
        names = sorted(item.value for item in overlap)
        raise LegalSimilarityCollisionError(
            f"legal and similarity edge types must be disjoint; overlap={names}"
        )
    for edge_type in GraphEdgeType:
        if edge_type not in LEGAL_EDGE_TYPES and edge_type not in SIMILARITY_EDGE_TYPES:
            raise GraphOntologyError(
                f"edge type {edge_type.value} is neither legal nor similarity"
            )
    for edge_type, edge_class in DEFAULT_EDGE_CLASS.items():
        if edge_type in SIMILARITY_EDGE_TYPES and edge_class is not GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"similarity edge {edge_type.value} must use class similarity"
            )
        if edge_type in LEGAL_EDGE_TYPES and edge_class is GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"legal edge {edge_type.value} must not use class similarity"
            )


# ---------------------------------------------------------------------------
# Source spans
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Exact character span bound to a source document.

    Offsets are half-open ``[start, end)`` into ``source_text`` when the
    full text is available. ``text`` must equal the excerpt at those offsets.
    """

    start: int
    end: int
    text: str
    source_cid: Optional[str] = None
    entry_cid: Optional[str] = None
    field: str = "text"

    def __post_init__(self) -> None:
        start = _require_non_negative_int(self.start, "start")
        end = _require_non_negative_int(self.end, "end")
        if end < start:
            raise SourceSpanError(f"span end {end} must be >= start {start}")
        text = self.text if isinstance(self.text, str) else ""
        if "\x00" in text:
            raise SourceSpanError("span text must not contain NUL")
        if len(text) != end - start:
            raise SourceSpanError(
                f"span text length {len(text)} must equal end-start ({end - start})"
            )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "text", text)
        if self.source_cid is not None:
            object.__setattr__(
                self,
                "source_cid",
                _require_non_empty_str(self.source_cid, "source_cid", maximum=256),
            )
        if self.entry_cid is not None:
            object.__setattr__(
                self,
                "entry_cid",
                _require_non_empty_str(self.entry_cid, "entry_cid", maximum=256),
            )
        object.__setattr__(
            self,
            "field",
            _require_non_empty_str(self.field or "text", "field", maximum=64),
        )

    def bind_to_source(self, source_text: str) -> "SourceSpan":
        """Validate that this span is consistent with *source_text*."""

        if not isinstance(source_text, str):
            raise SourceSpanError("source_text must be a string")
        if self.end > len(source_text):
            raise SourceSpanError(
                f"span end {self.end} exceeds source length {len(source_text)}"
            )
        excerpt = source_text[self.start : self.end]
        if excerpt != self.text:
            raise SourceSpanError(
                "span text does not match source_text[start:end]; "
                f"expected {excerpt!r}, got {self.text!r}"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "end": self.end,
            "entry_cid": self.entry_cid,
            "field": self.field,
            "source_cid": self.source_cid,
            "start": self.start,
            "text": self.text,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceSpan":
        if not isinstance(value, Mapping):
            raise SourceSpanError("source span must be a mapping")
        return cls(
            start=int(value.get("start", 0)),
            end=int(value.get("end", 0)),
            text=str(value.get("text") or ""),
            source_cid=value.get("source_cid"),
            entry_cid=value.get("entry_cid"),
            field=str(value.get("field") or "text"),
        )

    @classmethod
    def from_occurrence(
        cls,
        source_text: str,
        mention: str,
        *,
        source_cid: Optional[str] = None,
        entry_cid: Optional[str] = None,
        field: str = "text",
        start_hint: Optional[int] = None,
    ) -> "SourceSpan":
        """Locate *mention* in *source_text* and bind a span."""

        if not isinstance(source_text, str):
            raise SourceSpanError("source_text must be a string")
        if not isinstance(mention, str) or not mention:
            raise SourceSpanError("mention must be a non-empty string")
        if start_hint is not None:
            start = int(start_hint)
            end = start + len(mention)
            if source_text[start:end] != mention:
                raise SourceSpanError(
                    f"mention {mention!r} not found at start_hint={start}"
                )
        else:
            start = source_text.find(mention)
            if start < 0:
                raise SourceSpanError(f"mention {mention!r} not found in source_text")
            end = start + len(mention)
        return cls(
            start=start,
            end=end,
            text=mention,
            source_cid=source_cid,
            entry_cid=entry_cid,
            field=field,
        ).bind_to_source(source_text)


# ---------------------------------------------------------------------------
# Ontology contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphOntology:
    """Machine-readable declaration of legal graph node/edge vocabulary."""

    version: str = ONTOLOGY_VERSION
    node_types: tuple[str, ...] = tuple(item.value for item in GraphNodeType)
    edge_types: tuple[str, ...] = tuple(item.value for item in GraphEdgeType)
    legal_edge_types: tuple[str, ...] = tuple(
        sorted(item.value for item in LEGAL_EDGE_TYPES)
    )
    similarity_edge_types: tuple[str, ...] = tuple(
        sorted(item.value for item in SIMILARITY_EDGE_TYPES)
    )
    edge_class_by_type: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {k.value: v.value for k, v in DEFAULT_EDGE_CLASS.items()}
        )
    )

    def __post_init__(self) -> None:
        if self.version != ONTOLOGY_VERSION:
            raise GraphOntologyError(
                f"unsupported ontology version: {self.version!r}; "
                f"expected {ONTOLOGY_VERSION!r}"
            )
        expected_nodes = tuple(item.value for item in GraphNodeType)
        expected_edges = tuple(item.value for item in GraphEdgeType)
        if self.node_types != expected_nodes:
            raise GraphOntologyError("node_types must exactly match the versioned vocabulary")
        if self.edge_types != expected_edges:
            raise GraphOntologyError("edge_types must exactly match the versioned vocabulary")
        assert_legal_similarity_disjoint()
        legal_set = set(self.legal_edge_types)
        sim_set = set(self.similarity_edge_types)
        if legal_set & sim_set:
            raise LegalSimilarityCollisionError(
                "ontology legal_edge_types and similarity_edge_types overlap"
            )

    def edge_class_for(self, edge_type: GraphEdgeType | str) -> GraphEdgeClass:
        edge = GraphEdgeType.coerce(edge_type)
        raw = self.edge_class_by_type.get(edge.value)
        if raw is None:
            raise GraphOntologyError(f"no edge class for {edge.value}")
        return GraphEdgeClass.coerce(raw)

    def is_legal_edge(self, edge_type: GraphEdgeType | str) -> bool:
        return GraphEdgeType.coerce(edge_type) in LEGAL_EDGE_TYPES

    def is_similarity_edge(self, edge_type: GraphEdgeType | str) -> bool:
        return GraphEdgeType.coerce(edge_type) in SIMILARITY_EDGE_TYPES

    def validate_edge(
        self,
        edge_type: GraphEdgeType | str,
        source_type: GraphNodeType | str,
        target_type: GraphNodeType | str,
        *,
        edge_class: GraphEdgeClass | str | None = None,
    ) -> GraphEdgeClass:
        """Validate edge direction and class; return the resolved class."""

        edge = GraphEdgeType.coerce(edge_type)
        source = GraphNodeType.coerce(source_type)
        target = GraphNodeType.coerce(target_type)
        expected = self.edge_class_for(edge)
        if edge_class is not None:
            provided = GraphEdgeClass.coerce(edge_class)
            if provided is not expected:
                raise GraphOntologyError(
                    f"{edge.value} must be classified as {expected.value}, "
                    f"got {provided.value}"
                )
            category = provided
        else:
            category = expected

        # Legal / similarity disjointness at classification time.
        if edge in SIMILARITY_EDGE_TYPES and category is not GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"similarity edge {edge.value} cannot use class {category.value}"
            )
        if edge in LEGAL_EDGE_TYPES and category is GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"legal edge {edge.value} cannot use class similarity"
            )

        valid = _edge_direction_allowed(edge, source, target)
        if not valid:
            raise GraphOntologyError(
                f"{edge.value} does not permit {source.value} -> {target.value}"
            )
        return category

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_class_by_type": dict(self.edge_class_by_type),
            "edge_types": list(self.edge_types),
            "legal_edge_types": list(self.legal_edge_types),
            "node_types": list(self.node_types),
            "similarity_edge_types": list(self.similarity_edge_types),
            "version": self.version,
        }


def _edge_direction_allowed(
    edge: GraphEdgeType,
    source: GraphNodeType,
    target: GraphNodeType,
) -> bool:
    structural_parents = {
        GraphNodeType.CODE,
        GraphNodeType.TITLE,
        GraphNodeType.SUBTITLE,
        GraphNodeType.CHAPTER,
        GraphNodeType.SUBCHAPTER,
        GraphNodeType.PART,
        GraphNodeType.SUBPART,
        GraphNodeType.SECTION,
    }
    structural_children = structural_parents | {
        GraphNodeType.SUBSECTION,
        GraphNodeType.NOTE,
    }
    section_like = {
        GraphNodeType.SECTION,
        GraphNodeType.SUBSECTION,
        GraphNodeType.NOTE,
    }

    if edge is GraphEdgeType.CONTAINS:
        return source in structural_parents and target in structural_children
    if edge is GraphEdgeType.CODIFIES:
        return source is GraphNodeType.PUBLIC_LAW and target in section_like
    if edge is GraphEdgeType.CITES:
        return source in section_like and target in section_like
    if edge is GraphEdgeType.CITES_UNRESOLVED:
        return source in section_like and target is GraphNodeType.UNRESOLVED_CITATION
    if edge in {
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
    }:
        return (
            source in section_like | {GraphNodeType.PUBLIC_LAW}
            and target in section_like
        )
    if edge is GraphEdgeType.DERIVED_FROM:
        return source in section_like and target in {
            GraphNodeType.PUBLIC_LAW,
            GraphNodeType.STATUTES_AT_LARGE,
            GraphNodeType.SOURCE_PACKAGE,
            GraphNodeType.SOURCE_GRANULE,
        }
    if edge is GraphEdgeType.HAS_SOURCE:
        return source in section_like and target in {
            GraphNodeType.SOURCE_PACKAGE,
            GraphNodeType.SOURCE_GRANULE,
            GraphNodeType.RELEASE_POINT,
        }
    if edge is GraphEdgeType.HAS_VERSION:
        return source in section_like and target is GraphNodeType.VERSION
    if edge is GraphEdgeType.BM25_NEIGHBOR_OF:
        return source in section_like and target in section_like
    if edge is GraphEdgeType.SIMILAR_TO:
        return source == target or (
            source in section_like and target in section_like
        )
    return False


GRAPH_ONTOLOGY: Final = GraphOntology()


# ---------------------------------------------------------------------------
# Citation extraction / resolution
# ---------------------------------------------------------------------------

_USC_CITATION_RE = re.compile(
    r"""
    (?P<mention>
        (?P<title>\d+[A-Za-z]?)\s*
        U\.?\s*S\.?\s*C\.?(?:A\.?)?\s*
        (?:§+\s*|sec(?:tion)?\.?\s*)?
        (?P<section>\d+[A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_PUBLIC_LAW_RE = re.compile(
    r"""
    (?P<mention>
        (?:Pub(?:lic)?\.?\s*L(?:aw)?\.?|P\.?\s*L\.?)\s*
        (?:No\.?\s*)?
        (?P<congress>\d+)\s*[-–—]\s*(?P<number>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_STATUTES_AT_LARGE_RE = re.compile(
    r"""
    (?P<mention>
        (?P<volume>\d+)\s*
        Stat\.?\s*
        (?P<page>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class CitationMention:
    """One citation occurrence extracted from source text."""

    kind: str  # usc | public_law | statutes_at_large
    mention_text: str
    start: int
    end: int
    title: Optional[str] = None
    section: Optional[str] = None
    congress: Optional[str] = None
    number: Optional[str] = None
    volume: Optional[str] = None
    page: Optional[str] = None
    parser_version: str = CITATION_PARSER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _require_non_empty_str(self.kind, "kind", maximum=64)
        )
        object.__setattr__(
            self,
            "mention_text",
            _require_non_empty_str(self.mention_text, "mention_text", maximum=512),
        )
        object.__setattr__(self, "start", _require_non_negative_int(self.start, "start"))
        object.__setattr__(self, "end", _require_non_negative_int(self.end, "end"))
        if self.end < self.start:
            raise CitationResolutionError("citation end must be >= start")
        object.__setattr__(
            self,
            "parser_version",
            _require_non_empty_str(self.parser_version, "parser_version", maximum=128),
        )

    @property
    def span_length(self) -> int:
        return self.end - self.start

    def candidate_legal_id(self, *, jurisdiction: str = DEFAULT_JURISDICTION) -> Optional[str]:
        if self.kind != "usc" or not self.title or not self.section:
            return None
        try:
            return build_legal_id(
                title=self.title,
                section=self.section,
                jurisdiction=jurisdiction,
            )
        except Exception:
            return None

    def public_law_id(self) -> Optional[str]:
        if self.kind != "public_law" or not self.congress or not self.number:
            return None
        return f"pl:us:{int(self.congress)}:{int(self.number)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "congress": self.congress,
            "end": self.end,
            "kind": self.kind,
            "mention_text": self.mention_text,
            "number": self.number,
            "page": self.page,
            "parser_version": self.parser_version,
            "section": self.section,
            "start": self.start,
            "title": self.title,
            "volume": self.volume,
        }


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """Resolved or honestly-unresolved citation with evidence span."""

    mention: CitationMention
    resolution_status: ResolutionStatus
    span: SourceSpan
    target_legal_id: Optional[str] = None
    target_public_law_id: Optional[str] = None
    target_node_key: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention": self.mention.to_dict(),
            "resolution_status": self.resolution_status.value,
            "span": self.span.to_dict(),
            "target_legal_id": self.target_legal_id,
            "target_node_key": self.target_node_key,
            "target_public_law_id": self.target_public_law_id,
        }


def extract_citation_mentions(text: str) -> list[CitationMention]:
    """Extract U.S.C., public-law, and Statutes-at-Large mentions."""

    if not isinstance(text, str):
        raise CitationResolutionError("text must be a string")
    # NFKC for stable matching without altering offsets on original text.
    # Patterns operate on the original string so spans stay bound.
    mentions: list[CitationMention] = []
    seen_spans: set[tuple[int, int, str]] = set()

    for match in _USC_CITATION_RE.finditer(text):
        key = (match.start(), match.end(), "usc")
        if key in seen_spans:
            continue
        seen_spans.add(key)
        title = match.group("title")
        section = match.group("section")
        try:
            title_n = normalize_title(title)
            section_n = normalize_section_token(section)
        except Exception:
            title_n = title
            section_n = section
        mentions.append(
            CitationMention(
                kind="usc",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                title=title_n,
                section=section_n,
            )
        )

    for match in _PUBLIC_LAW_RE.finditer(text):
        key = (match.start(), match.end(), "public_law")
        if key in seen_spans:
            continue
        seen_spans.add(key)
        mentions.append(
            CitationMention(
                kind="public_law",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                congress=str(int(match.group("congress"))),
                number=str(int(match.group("number"))),
            )
        )

    for match in _STATUTES_AT_LARGE_RE.finditer(text):
        key = (match.start(), match.end(), "statutes_at_large")
        if key in seen_spans:
            continue
        seen_spans.add(key)
        mentions.append(
            CitationMention(
                kind="statutes_at_large",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                volume=str(int(match.group("volume"))),
                page=str(int(match.group("page"))),
            )
        )

    mentions.sort(key=lambda item: (item.start, item.end, item.kind))
    return mentions


def resolve_citations(
    text: str,
    *,
    known_legal_ids: Iterable[str] | None = None,
    source_cid: Optional[str] = None,
    entry_cid: Optional[str] = None,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> list[ResolvedCitation]:
    """Resolve extracted citations against a known legal-id set.

    Unknown U.S.C. targets become ``unresolved`` rather than invented nodes
    with guessed legal identities.
    """

    known = {str(item) for item in (known_legal_ids or []) if item}
    resolved: list[ResolvedCitation] = []
    for mention in extract_citation_mentions(text):
        span = SourceSpan(
            start=mention.start,
            end=mention.end,
            text=text[mention.start : mention.end],
            source_cid=source_cid,
            entry_cid=entry_cid,
            field="text",
        ).bind_to_source(text)

        if mention.kind == "usc":
            candidate = mention.candidate_legal_id(jurisdiction=jurisdiction)
            if candidate and candidate in known:
                resolved.append(
                    ResolvedCitation(
                        mention=mention,
                        resolution_status=ResolutionStatus.RESOLVED,
                        span=span,
                        target_legal_id=candidate,
                        target_node_key=f"section:{candidate}",
                    )
                )
            else:
                # Honest unresolved: keep mention, never invent target.
                unresolved_key = (
                    f"unresolved:usc:"
                    f"{mention.title or '?'}:{mention.section or '?'}"
                    f":{content_sha256(mention.mention_text)[:16]}"
                )
                resolved.append(
                    ResolvedCitation(
                        mention=mention,
                        resolution_status=ResolutionStatus.UNRESOLVED,
                        span=span,
                        target_legal_id=None,
                        target_node_key=unresolved_key,
                    )
                )
        elif mention.kind == "public_law":
            pl_id = mention.public_law_id()
            resolved.append(
                ResolvedCitation(
                    mention=mention,
                    resolution_status=ResolutionStatus.RESOLVED,
                    span=span,
                    target_public_law_id=pl_id,
                    target_node_key=f"public_law:{pl_id}",
                )
            )
        else:
            sal_key = (
                f"statutes_at_large:{mention.volume}:{mention.page}"
            )
            resolved.append(
                ResolvedCitation(
                    mention=mention,
                    resolution_status=ResolutionStatus.RESOLVED,
                    span=span,
                    target_node_key=sal_key,
                )
            )
    return resolved


# ---------------------------------------------------------------------------
# Graph node / edge records (projection-local)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UscodeGraphNode:
    """One projected legal graph node with deterministic node CID."""

    node_type: GraphNodeType
    node_key: str
    label: str
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    node_cid: str = ""

    def __post_init__(self) -> None:
        node_type = GraphNodeType.coerce(self.node_type)
        object.__setattr__(self, "node_type", node_type)
        key = _require_non_empty_str(self.node_key, "node_key", maximum=512)
        object.__setattr__(self, "node_key", key)
        object.__setattr__(
            self, "label", _require_non_empty_str(self.label, "label", maximum=1024)
        )
        if self.legal_id is not None:
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=512),
            )
        if self.entry_cid is not None:
            object.__setattr__(
                self,
                "entry_cid",
                _require_non_empty_str(self.entry_cid, "entry_cid", maximum=256),
            )
        if not isinstance(self.payload, Mapping):
            raise GraphProjectionError("node payload must be a mapping")
        payload = dict(self.payload)
        object.__setattr__(self, "payload", MappingProxyType(payload))
        object.__setattr__(
            self,
            "ontology_version",
            _require_non_empty_str(self.ontology_version, "ontology_version"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        identity = {
            "entry_cid": self.entry_cid,
            "label": self.label,
            "legal_id": self.legal_id,
            "node_key": self.node_key,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "payload": payload,
            "schema_version": self.schema_version,
        }
        cid = self.node_cid or sha256_cid({"kind": "uscode_graph_node", **identity})
        object.__setattr__(self, "node_cid", cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_cid": self.entry_cid,
            "label": self.label,
            "legal_id": self.legal_id,
            "node_cid": self.node_cid,
            "node_key": self.node_key,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "payload": dict(self.payload),
            "schema_version": self.schema_version,
        }

    def to_release_record(self) -> GraphNodeRecord:
        return GraphNodeRecord(
            node_cid=self.node_cid,
            node_type=self.node_type.value,
            legal_id=self.legal_id,
            entry_cid=self.entry_cid,
            label=self.label,
            payload={
                "node_key": self.node_key,
                "ontology_version": self.ontology_version,
                **dict(self.payload),
            },
        )


@dataclass(frozen=True, slots=True)
class UscodeGraphEdge:
    """One projected legal graph edge with deterministic edge CID."""

    edge_type: GraphEdgeType
    source_node_cid: str
    target_node_cid: str
    edge_class: GraphEdgeClass
    source_span: Optional[SourceSpan] = None
    resolution_status: Optional[ResolutionStatus] = None
    weight: Optional[float] = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    edge_cid: str = ""

    def __post_init__(self) -> None:
        edge_type = GraphEdgeType.coerce(self.edge_type)
        edge_class = GraphEdgeClass.coerce(self.edge_class)
        object.__setattr__(self, "edge_type", edge_type)
        object.__setattr__(self, "edge_class", edge_class)

        # Disjointness enforcement.
        if edge_type in SIMILARITY_EDGE_TYPES and edge_class is not GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"{edge_type.value} must use edge_class=similarity"
            )
        if edge_type in LEGAL_EDGE_TYPES and edge_class is GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"{edge_type.value} is a legal edge and cannot use similarity class"
            )

        object.__setattr__(
            self,
            "source_node_cid",
            _require_non_empty_str(self.source_node_cid, "source_node_cid", maximum=256),
        )
        object.__setattr__(
            self,
            "target_node_cid",
            _require_non_empty_str(self.target_node_cid, "target_node_cid", maximum=256),
        )
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            raise SourceSpanError("source_span must be a SourceSpan")
        if edge_type in SPAN_REQUIRED_EDGE_TYPES and self.source_span is None:
            raise SourceSpanError(
                f"{edge_type.value} requires a bound source_span"
            )
        if self.resolution_status is not None:
            object.__setattr__(
                self,
                "resolution_status",
                ResolutionStatus.coerce(self.resolution_status),
            )
        if edge_type is GraphEdgeType.CITES_UNRESOLVED:
            if self.resolution_status is not ResolutionStatus.UNRESOLVED:
                raise CitationResolutionError(
                    "CITES_UNRESOLVED requires resolution_status=unresolved"
                )
        if self.weight is not None:
            if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
                raise GraphProjectionError("weight must be a number")
            object.__setattr__(self, "weight", float(self.weight))
        if not isinstance(self.payload, Mapping):
            raise GraphProjectionError("edge payload must be a mapping")
        payload = dict(self.payload)
        object.__setattr__(self, "payload", MappingProxyType(payload))
        object.__setattr__(
            self,
            "ontology_version",
            _require_non_empty_str(self.ontology_version, "ontology_version"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        identity = {
            "edge_class": self.edge_class.value,
            "edge_type": self.edge_type.value,
            "ontology_version": self.ontology_version,
            "payload": payload,
            "resolution_status": (
                self.resolution_status.value if self.resolution_status else None
            ),
            "schema_version": self.schema_version,
            "source_node_cid": self.source_node_cid,
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "target_node_cid": self.target_node_cid,
            "weight": self.weight,
        }
        cid = self.edge_cid or sha256_cid({"kind": "uscode_graph_edge", **identity})
        object.__setattr__(self, "edge_cid", cid)

    @property
    def is_legal(self) -> bool:
        return self.edge_type in LEGAL_EDGE_TYPES

    @property
    def is_similarity(self) -> bool:
        return self.edge_type in SIMILARITY_EDGE_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_class": self.edge_class.value,
            "edge_type": self.edge_type.value,
            "ontology_version": self.ontology_version,
            "payload": dict(self.payload),
            "resolution_status": (
                self.resolution_status.value if self.resolution_status else None
            ),
            "schema_version": self.schema_version,
            "source_node_cid": self.source_node_cid,
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "target_node_cid": self.target_node_cid,
            "weight": self.weight,
        }

    def to_release_record(self) -> GraphEdgeRecord:
        payload = {
            "edge_class": self.edge_class.value,
            "ontology_version": self.ontology_version,
            "resolution_status": (
                self.resolution_status.value if self.resolution_status else None
            ),
            "source_span": self.source_span.to_dict() if self.source_span else None,
            **dict(self.payload),
        }
        return GraphEdgeRecord(
            edge_cid=self.edge_cid,
            edge_type=self.edge_type.value,
            source_node_cid=self.source_node_cid,
            target_node_cid=self.target_node_cid,
            weight=self.weight,
            payload=payload,
        )


# ---------------------------------------------------------------------------
# Projection result / paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphPath:
    """One directed path of edge types between legal identities / node keys."""

    source_key: str
    target_key: str
    edge_types: tuple[str, ...]
    node_keys: tuple[str, ...]
    edge_cids: tuple[str, ...] = ()
    path_kind: str = "legal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cids": list(self.edge_cids),
            "edge_types": list(self.edge_types),
            "node_keys": list(self.node_keys),
            "path_kind": self.path_kind,
            "source_key": self.source_key,
            "target_key": self.target_key,
        }


@dataclass(frozen=True, slots=True)
class UscodeGraphProjection:
    """Deterministic legal graph projection for a sealed corpus slice."""

    nodes: tuple[UscodeGraphNode, ...]
    edges: tuple[UscodeGraphEdge, ...]
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    citation_parser_version: str = CITATION_PARSER_VERSION
    unresolved_count: int = 0
    legal_edge_count: int = 0
    similarity_edge_count: int = 0
    graph_cid: str = ""

    def __post_init__(self) -> None:
        nodes = tuple(sorted(self.nodes, key=lambda n: (n.node_type.value, n.node_key, n.node_cid)))
        edges = tuple(
            sorted(
                self.edges,
                key=lambda e: (
                    e.edge_type.value,
                    e.source_node_cid,
                    e.target_node_cid,
                    e.edge_cid,
                ),
            )
        )
        if len({n.node_cid for n in nodes}) != len(nodes):
            raise GraphProjectionError("duplicate node_cid in projection")
        if len({e.edge_cid for e in edges}) != len(edges):
            raise GraphProjectionError("duplicate edge_cid in projection")
        node_cids = {n.node_cid for n in nodes}
        for edge in edges:
            if edge.source_node_cid not in node_cids or edge.target_node_cid not in node_cids:
                raise GraphProjectionError(
                    f"dangling edge {edge.edge_cid}: missing endpoint"
                )
        legal_count = sum(1 for e in edges if e.is_legal)
        sim_count = sum(1 for e in edges if e.is_similarity)
        unresolved = sum(
            1
            for e in edges
            if e.edge_type is GraphEdgeType.CITES_UNRESOLVED
            or e.resolution_status is ResolutionStatus.UNRESOLVED
        )
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "legal_edge_count", legal_count)
        object.__setattr__(self, "similarity_edge_count", sim_count)
        object.__setattr__(self, "unresolved_count", unresolved)
        root = {
            "citation_parser_version": self.citation_parser_version,
            "edge_cids": [e.edge_cid for e in edges],
            "node_cids": [n.node_cid for n in nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
        }
        object.__setattr__(self, "graph_cid", self.graph_cid or sha256_cid(root))

    def node_by_key(self) -> dict[str, UscodeGraphNode]:
        return {n.node_key: n for n in self.nodes}

    def node_by_cid(self) -> dict[str, UscodeGraphNode]:
        return {n.node_cid: n for n in self.nodes}

    def legal_edges(self) -> tuple[UscodeGraphEdge, ...]:
        return tuple(e for e in self.edges if e.is_legal)

    def similarity_edges(self) -> tuple[UscodeGraphEdge, ...]:
        return tuple(e for e in self.edges if e.is_similarity)

    def assert_semantics_disjoint(self) -> None:
        for edge in self.edges:
            if edge.is_legal and edge.is_similarity:
                raise LegalSimilarityCollisionError(
                    f"edge {edge.edge_cid} is both legal and similarity"
                )
            if edge.is_legal and edge.edge_class is GraphEdgeClass.SIMILARITY:
                raise LegalSimilarityCollisionError(
                    f"legal edge {edge.edge_type.value} classified as similarity"
                )
            if edge.is_similarity and edge.edge_class is not GraphEdgeClass.SIMILARITY:
                raise LegalSimilarityCollisionError(
                    f"similarity edge {edge.edge_type.value} not classified as similarity"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_parser_version": self.citation_parser_version,
            "edges": [e.to_dict() for e in self.edges],
            "graph_cid": self.graph_cid,
            "legal_edge_count": self.legal_edge_count,
            "nodes": [n.to_dict() for n in self.nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
            "similarity_edge_count": self.similarity_edge_count,
            "unresolved_count": self.unresolved_count,
        }

    def path_summaries(
        self,
        *,
        max_depth: int = 4,
        legal_only: bool = True,
    ) -> list[GraphPath]:
        """Enumerate bounded simple paths for fixture matching."""

        return find_graph_paths(self, max_depth=max_depth, legal_only=legal_only)


def find_graph_paths(
    projection: UscodeGraphProjection,
    *,
    max_depth: int = 4,
    legal_only: bool = True,
    source_keys: Iterable[str] | None = None,
    target_keys: Iterable[str] | None = None,
) -> list[GraphPath]:
    """Find directed paths over the projected graph (bounded BFS)."""

    if max_depth < 1:
        raise GraphProjectionError("max_depth must be >= 1")
    by_cid = projection.node_by_cid()
    by_key = projection.node_by_key()
    adjacency: dict[str, list[UscodeGraphEdge]] = defaultdict(list)
    for edge in projection.edges:
        if legal_only and not edge.is_legal:
            continue
        adjacency[edge.source_node_cid].append(edge)

    starts = list(source_keys) if source_keys is not None else list(by_key.keys())
    target_set = set(target_keys) if target_keys is not None else None
    paths: list[GraphPath] = []
    seen_path_keys: set[tuple[str, ...]] = set()

    for start_key in starts:
        start_node = by_key.get(start_key)
        if start_node is None:
            continue
        # state: current_cid, node_keys, edge_types, edge_cids
        queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = deque()
        queue.append((start_node.node_cid, (start_key,), (), ()))
        while queue:
            current, node_keys, edge_types, edge_cids = queue.popleft()
            depth = len(edge_types)
            if depth > 0:
                path_key = node_keys + edge_types
                if path_key not in seen_path_keys:
                    seen_path_keys.add(path_key)
                    end_key = node_keys[-1]
                    if target_set is None or end_key in target_set:
                        paths.append(
                            GraphPath(
                                source_key=node_keys[0],
                                target_key=end_key,
                                edge_types=edge_types,
                                node_keys=node_keys,
                                edge_cids=edge_cids,
                                path_kind="legal" if legal_only else "mixed",
                            )
                        )
            if depth >= max_depth:
                continue
            for edge in adjacency.get(current, ()):
                target = by_cid.get(edge.target_node_cid)
                if target is None:
                    continue
                if target.node_key in node_keys:
                    continue  # simple paths only
                queue.append(
                    (
                        target.node_cid,
                        node_keys + (target.node_key,),
                        edge_types + (edge.edge_type.value,),
                        edge_cids + (edge.edge_cid,),
                    )
                )

    paths.sort(
        key=lambda p: (
            p.source_key,
            p.target_key,
            p.edge_types,
            p.node_keys,
        )
    )
    return paths


def match_expected_paths(
    projection: UscodeGraphProjection,
    expected_paths: Sequence[Mapping[str, Any]],
    *,
    max_depth: int = 6,
) -> list[dict[str, Any]]:
    """Match sealed expected path recipes against a projection."""

    actual = find_graph_paths(projection, max_depth=max_depth, legal_only=True)
    results: list[dict[str, Any]] = []
    for spec in expected_paths:
        if not isinstance(spec, Mapping):
            raise GraphFixtureError("expected path must be a mapping")
        source = str(spec.get("source_key") or spec.get("source_legal_id") or "")
        target = str(spec.get("target_key") or spec.get("target_legal_id") or "")
        edge_types = tuple(str(x) for x in (spec.get("edge_types") or ()))
        # Allow source/target as legal_id by normalizing to node keys.
        source_candidates = _path_key_candidates(source)
        target_candidates = _path_key_candidates(target)

        matched = None
        for path in actual:
            if path.source_key not in source_candidates:
                continue
            if path.target_key not in target_candidates:
                continue
            if edge_types and path.edge_types != edge_types:
                # Also allow subsequence match when path is longer structural chain.
                if not _is_subsequence(edge_types, path.edge_types):
                    continue
            matched = path
            break
        results.append(
            {
                "edge_types": list(edge_types),
                "matched": matched is not None,
                "matched_path": matched.to_dict() if matched else None,
                "source_key": source,
                "target_key": target,
            }
        )
    return results


def _path_key_candidates(raw: str) -> set[str]:
    if not raw:
        return set()
    candidates = {raw}
    if raw.startswith("usc:"):
        candidates.add(f"section:{raw}")
        candidates.add(raw)
    if raw.startswith("section:"):
        candidates.add(raw)
        candidates.add(raw[len("section:") :])
    if raw.startswith("pl:") or raw.startswith("public_law:"):
        pl = raw if raw.startswith("public_law:") else f"public_law:{raw}"
        candidates.add(pl)
        candidates.add(raw)
    if raw.startswith("title:"):
        candidates.add(raw)
    if raw.startswith("chapter:"):
        candidates.add(raw)
    if not raw.startswith(("section:", "title:", "chapter:", "public_law:", "unresolved:")):
        # Bare legal id / public law id.
        if raw.startswith("usc:"):
            candidates.add(f"section:{raw}")
        elif re.fullmatch(r"pl:us:\d+:\d+", raw):
            candidates.add(f"public_law:{raw}")
    return candidates


def _is_subsequence(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    if not needle:
        return True
    i = 0
    for item in haystack:
        if item == needle[i]:
            i += 1
            if i == len(needle):
                return True
    return False


# ---------------------------------------------------------------------------
# Corpus row projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphCorpusRow:
    """One admitted corpus row eligible for legal graph projection."""

    entry_cid: str
    legal_id: str
    text: str
    title: str
    section: str
    source_cid: Optional[str] = None
    chapter: Optional[str] = None
    subsection: Optional[str] = None
    heading: str = ""
    release_point: Optional[str] = None
    edition: Optional[str] = None
    granule: Optional[str] = None
    public_laws: tuple[str, ...] = ()
    amends: tuple[str, ...] = ()
    repeals: tuple[str, ...] = ()
    transfers: tuple[str, ...] = ()
    version_id: Optional[str] = None
    jurisdiction: str = DEFAULT_JURISDICTION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entry_cid",
            _require_non_empty_str(self.entry_cid, "entry_cid", maximum=256),
        )
        object.__setattr__(
            self,
            "legal_id",
            _require_non_empty_str(self.legal_id, "legal_id", maximum=512),
        )
        if not isinstance(self.text, str):
            raise GraphProjectionError("text must be a string")
        if "\x00" in self.text:
            raise GraphProjectionError("text must not contain NUL")
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "section", normalize_section_token(self.section))
        if self.source_cid is not None:
            object.__setattr__(
                self,
                "source_cid",
                _require_non_empty_str(self.source_cid, "source_cid", maximum=256),
            )
        if self.chapter is not None and str(self.chapter).strip():
            object.__setattr__(
                self,
                "chapter",
                _require_non_empty_str(str(self.chapter), "chapter", maximum=64),
            )
        else:
            object.__setattr__(self, "chapter", None)
        object.__setattr__(
            self,
            "public_laws",
            tuple(str(x) for x in (self.public_laws or ()) if x),
        )
        object.__setattr__(
            self, "amends", tuple(str(x) for x in (self.amends or ()) if x)
        )
        object.__setattr__(
            self, "repeals", tuple(str(x) for x in (self.repeals or ()) if x)
        )
        object.__setattr__(
            self, "transfers", tuple(str(x) for x in (self.transfers or ()) if x)
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphCorpusRow":
        if not isinstance(value, Mapping):
            raise GraphProjectionError("corpus row must be a mapping")
        legal_id = value.get("legal_id")
        title = value.get("title")
        section = value.get("section")
        if legal_id and (title is None or section is None):
            try:
                identity = parse_legal_id(str(legal_id))
                title = title or identity.title
                section = section or identity.section
            except Exception:
                pass
        if not legal_id and title is not None and section is not None:
            legal_id = build_legal_id(
                title=title,
                section=section,
                jurisdiction=value.get("jurisdiction", DEFAULT_JURISDICTION),
                subsection=value.get("subsection"),
                edition=value.get("edition"),
                granule=value.get("granule"),
            )
        return cls(
            entry_cid=str(value.get("entry_cid") or ""),
            legal_id=str(legal_id or ""),
            text=str(value.get("text") or ""),
            title=str(title or ""),
            section=str(section or ""),
            source_cid=value.get("source_cid"),
            chapter=value.get("chapter"),
            subsection=value.get("subsection"),
            heading=str(value.get("heading") or ""),
            release_point=value.get("release_point"),
            edition=value.get("edition"),
            granule=value.get("granule"),
            public_laws=tuple(value.get("public_laws") or ()),
            amends=tuple(value.get("amends") or ()),
            repeals=tuple(value.get("repeals") or ()),
            transfers=tuple(value.get("transfers") or ()),
            version_id=value.get("version_id") or value.get("edition"),
            jurisdiction=str(value.get("jurisdiction") or DEFAULT_JURISDICTION),
        )


@dataclass(frozen=True, slots=True)
class SimilarityNeighbor:
    """Optional non-authoritative similarity edge input."""

    source_legal_id: str
    target_legal_id: str
    score: float
    edge_type: GraphEdgeType = GraphEdgeType.BM25_NEIGHBOR_OF
    metric: str = "bm25"
    config_cid: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_legal_id",
            _require_non_empty_str(self.source_legal_id, "source_legal_id"),
        )
        object.__setattr__(
            self,
            "target_legal_id",
            _require_non_empty_str(self.target_legal_id, "target_legal_id"),
        )
        edge = GraphEdgeType.coerce(self.edge_type)
        if edge not in SIMILARITY_EDGE_TYPES:
            raise LegalSimilarityCollisionError(
                f"SimilarityNeighbor edge_type must be similarity, got {edge.value}"
            )
        object.__setattr__(self, "edge_type", edge)
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise GraphProjectionError("similarity score must be a number")
        object.__setattr__(self, "score", float(self.score))


class UscodeGraphProjector:
    """Project admitted corpus rows into the legal ontology graph."""

    def __init__(self, ontology: GraphOntology | None = None) -> None:
        self.ontology = ontology or GRAPH_ONTOLOGY

    def project(
        self,
        rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
        *,
        similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
        include_code_root: bool = True,
    ) -> UscodeGraphProjection:
        corpus = [self._coerce_row(item) for item in rows]
        if not corpus:
            raise GraphProjectionError("cannot project an empty corpus")

        known_legal_ids = {row.legal_id for row in corpus}
        nodes: dict[str, UscodeGraphNode] = {}
        edges: list[UscodeGraphEdge] = []

        if include_code_root:
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.CODE,
                node_key="code:us",
                label="United States Code",
                payload={"jurisdiction": "us"},
            )

        # First pass: structural section nodes and hierarchy.
        for row in corpus:
            section_key = f"section:{row.legal_id}"
            node_type = (
                GraphNodeType.SUBSECTION
                if row.subsection
                else GraphNodeType.SECTION
            )
            self._ensure_node(
                nodes,
                node_type=node_type,
                node_key=section_key,
                label=row.heading or row.legal_id,
                legal_id=row.legal_id,
                entry_cid=row.entry_cid,
                payload={
                    "chapter": row.chapter,
                    "section": row.section,
                    "title": row.title,
                },
            )

            title_key = f"title:{row.title}"
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.TITLE,
                node_key=title_key,
                label=f"Title {row.title}",
                payload={"title": row.title},
            )
            if include_code_root:
                edges.append(
                    self._edge(
                        GraphEdgeType.CONTAINS,
                        nodes["code:us"],
                        nodes[title_key],
                    )
                )

            if row.chapter:
                chapter_key = f"chapter:{row.title}:{row.chapter}"
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.CHAPTER,
                    node_key=chapter_key,
                    label=f"Title {row.title} Chapter {row.chapter}",
                    payload={"chapter": row.chapter, "title": row.title},
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.CONTAINS,
                        nodes[title_key],
                        nodes[chapter_key],
                    )
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.CONTAINS,
                        nodes[chapter_key],
                        nodes[section_key],
                    )
                )
            else:
                edges.append(
                    self._edge(
                        GraphEdgeType.CONTAINS,
                        nodes[title_key],
                        nodes[section_key],
                    )
                )

            # Source / release / version provenance.
            if row.source_cid or row.granule:
                source_key = f"source:{row.source_cid or row.granule}"
                self._ensure_node(
                    nodes,
                    node_type=(
                        GraphNodeType.SOURCE_GRANULE
                        if row.granule
                        else GraphNodeType.SOURCE_PACKAGE
                    ),
                    node_key=source_key,
                    label=row.granule or row.source_cid or source_key,
                    payload={
                        "granule": row.granule,
                        "source_cid": row.source_cid,
                    },
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.HAS_SOURCE,
                        nodes[section_key],
                        nodes[source_key],
                    )
                )

            if row.release_point:
                rp_key = f"release_point:{row.release_point}"
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.RELEASE_POINT,
                    node_key=rp_key,
                    label=row.release_point,
                    payload={"release_point": row.release_point},
                )
                # Optional second source edge from section to release point.
                edges.append(
                    self._edge(
                        GraphEdgeType.HAS_SOURCE,
                        nodes[section_key],
                        nodes[rp_key],
                        payload={"role": "release_point"},
                    )
                )

            if row.version_id:
                version_key = f"version:{row.legal_id}:{row.version_id}"
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.VERSION,
                    node_key=version_key,
                    label=str(row.version_id),
                    legal_id=row.legal_id,
                    payload={"version_id": row.version_id},
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.HAS_VERSION,
                        nodes[section_key],
                        nodes[version_key],
                    )
                )

        # Second pass: citations, public laws, amendments.
        for row in corpus:
            section_key = f"section:{row.legal_id}"
            source_node = nodes[section_key]
            citations = resolve_citations(
                row.text,
                known_legal_ids=known_legal_ids,
                source_cid=row.source_cid,
                entry_cid=row.entry_cid,
                jurisdiction=row.jurisdiction,
            )
            # Skip self-citations of the host section's own citation form.
            for citation in citations:
                if citation.mention.kind == "usc":
                    if (
                        citation.resolution_status is ResolutionStatus.RESOLVED
                        and citation.target_legal_id
                        and citation.target_legal_id != row.legal_id
                    ):
                        target_key = f"section:{citation.target_legal_id}"
                        if target_key not in nodes:
                            # Known legal id from set but node missing — should not happen.
                            continue
                        edges.append(
                            self._edge(
                                GraphEdgeType.CITES,
                                source_node,
                                nodes[target_key],
                                source_span=citation.span,
                                resolution_status=ResolutionStatus.RESOLVED,
                                payload={
                                    "mention": citation.mention.mention_text,
                                    "parser_version": citation.mention.parser_version,
                                },
                            )
                        )
                    elif citation.resolution_status is ResolutionStatus.UNRESOLVED:
                        unresolved_key = citation.target_node_key or (
                            f"unresolved:{content_sha256(citation.mention.mention_text)[:16]}"
                        )
                        self._ensure_node(
                            nodes,
                            node_type=GraphNodeType.UNRESOLVED_CITATION,
                            node_key=unresolved_key,
                            label=citation.mention.mention_text,
                            payload={
                                "mention_text": citation.mention.mention_text,
                                "parser_version": citation.mention.parser_version,
                                "resolution_status": ResolutionStatus.UNRESOLVED.value,
                                "section": citation.mention.section,
                                "title": citation.mention.title,
                            },
                        )
                        edges.append(
                            self._edge(
                                GraphEdgeType.CITES_UNRESOLVED,
                                source_node,
                                nodes[unresolved_key],
                                source_span=citation.span,
                                resolution_status=ResolutionStatus.UNRESOLVED,
                                payload={
                                    "mention": citation.mention.mention_text,
                                    "parser_version": citation.mention.parser_version,
                                    "resolution_status": ResolutionStatus.UNRESOLVED.value,
                                },
                            )
                        )
                elif citation.mention.kind == "public_law":
                    pl_id = citation.target_public_law_id
                    if not pl_id:
                        continue
                    pl_key = f"public_law:{pl_id}"
                    self._ensure_node(
                        nodes,
                        node_type=GraphNodeType.PUBLIC_LAW,
                        node_key=pl_key,
                        label=citation.mention.mention_text,
                        payload={
                            "congress": citation.mention.congress,
                            "number": citation.mention.number,
                            "public_law_id": pl_id,
                        },
                    )
                    # Public law codifies the section; section derived_from public law.
                    edges.append(
                        self._edge(
                            GraphEdgeType.CODIFIES,
                            nodes[pl_key],
                            source_node,
                            source_span=citation.span,
                            resolution_status=ResolutionStatus.RESOLVED,
                            payload={
                                "mention": citation.mention.mention_text,
                                "parser_version": citation.mention.parser_version,
                            },
                        )
                    )
                    edges.append(
                        self._edge(
                            GraphEdgeType.DERIVED_FROM,
                            source_node,
                            nodes[pl_key],
                            source_span=citation.span,
                            payload={
                                "mention": citation.mention.mention_text,
                                "parser_version": citation.mention.parser_version,
                            },
                        )
                    )
                elif citation.mention.kind == "statutes_at_large":
                    sal_key = citation.target_node_key or (
                        f"statutes_at_large:{citation.mention.volume}:{citation.mention.page}"
                    )
                    self._ensure_node(
                        nodes,
                        node_type=GraphNodeType.STATUTES_AT_LARGE,
                        node_key=sal_key,
                        label=citation.mention.mention_text,
                        payload={
                            "page": citation.mention.page,
                            "volume": citation.mention.volume,
                        },
                    )
                    edges.append(
                        self._edge(
                            GraphEdgeType.DERIVED_FROM,
                            source_node,
                            nodes[sal_key],
                            source_span=citation.span,
                            payload={
                                "mention": citation.mention.mention_text,
                                "parser_version": citation.mention.parser_version,
                            },
                        )
                    )

            # Explicit public_laws / amends / repeals / transfers fields.
            for pl_raw in row.public_laws:
                pl_id = self._normalize_public_law_id(pl_raw)
                pl_key = f"public_law:{pl_id}"
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.PUBLIC_LAW,
                    node_key=pl_key,
                    label=pl_raw,
                    payload={"public_law_id": pl_id},
                )
                # Synthetic span over the explicit field name when no text span.
                span = self._synthetic_field_span(
                    row,
                    field_name="public_laws",
                    mention=str(pl_raw),
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.CODIFIES,
                        nodes[pl_key],
                        source_node,
                        source_span=span,
                        payload={"public_law_id": pl_id, "origin": "explicit_field"},
                    )
                )

            for target_id, edge_type in (
                *((item, GraphEdgeType.AMENDS) for item in row.amends),
                *((item, GraphEdgeType.REPEALS) for item in row.repeals),
                *((item, GraphEdgeType.TRANSFERS) for item in row.transfers),
            ):
                target_legal = self._coerce_legal_id(target_id)
                target_key = f"section:{target_legal}"
                if target_key not in nodes:
                    # Create a structural placeholder section node for the target.
                    try:
                        identity = parse_legal_id(target_legal)
                    except Exception:
                        identity = None
                    self._ensure_node(
                        nodes,
                        node_type=GraphNodeType.SECTION,
                        node_key=target_key,
                        label=target_legal,
                        legal_id=target_legal,
                        payload={
                            "placeholder": True,
                            "section": identity.section if identity else None,
                            "title": identity.title if identity else None,
                        },
                    )
                span = self._synthetic_field_span(
                    row,
                    field_name=edge_type.value.lower(),
                    mention=str(target_id),
                )
                edges.append(
                    self._edge(
                        edge_type,
                        source_node,
                        nodes[target_key],
                        source_span=span,
                        resolution_status=ResolutionStatus.RESOLVED,
                        payload={"origin": "explicit_field", "target": target_legal},
                    )
                )

        # Similarity neighbors (non-authoritative).
        for neighbor in similarity_neighbors or ():
            sim = self._coerce_similarity(neighbor)
            src_key = f"section:{sim.source_legal_id}"
            tgt_key = f"section:{sim.target_legal_id}"
            if src_key not in nodes or tgt_key not in nodes:
                raise GraphProjectionError(
                    "similarity neighbor endpoints must exist in the legal graph: "
                    f"{sim.source_legal_id!r} -> {sim.target_legal_id!r}"
                )
            edges.append(
                self._edge(
                    sim.edge_type,
                    nodes[src_key],
                    nodes[tgt_key],
                    weight=sim.score,
                    payload={
                        "authority": "non_authoritative",
                        "config_cid": sim.config_cid,
                        "metric": sim.metric,
                    },
                )
            )

        # Deduplicate edges by edge_cid (deterministic).
        unique_edges: dict[str, UscodeGraphEdge] = {}
        for edge in edges:
            unique_edges[edge.edge_cid] = edge

        projection = UscodeGraphProjection(
            nodes=tuple(nodes.values()),
            edges=tuple(unique_edges.values()),
        )
        projection.assert_semantics_disjoint()
        return projection

    def _coerce_row(self, value: GraphCorpusRow | Mapping[str, Any]) -> GraphCorpusRow:
        if isinstance(value, GraphCorpusRow):
            return value
        if isinstance(value, Mapping):
            return GraphCorpusRow.from_mapping(value)
        raise GraphProjectionError("corpus row must be GraphCorpusRow or mapping")

    def _coerce_similarity(
        self, value: SimilarityNeighbor | Mapping[str, Any]
    ) -> SimilarityNeighbor:
        if isinstance(value, SimilarityNeighbor):
            return value
        if isinstance(value, Mapping):
            return SimilarityNeighbor(
                source_legal_id=str(value.get("source_legal_id") or ""),
                target_legal_id=str(value.get("target_legal_id") or ""),
                score=float(value.get("score") or 0.0),
                edge_type=GraphEdgeType.coerce(
                    value.get("edge_type") or GraphEdgeType.BM25_NEIGHBOR_OF
                ),
                metric=str(value.get("metric") or "bm25"),
                config_cid=value.get("config_cid"),
            )
        raise GraphProjectionError("similarity neighbor must be mapping or SimilarityNeighbor")

    def _ensure_node(
        self,
        nodes: dict[str, UscodeGraphNode],
        *,
        node_type: GraphNodeType,
        node_key: str,
        label: str,
        legal_id: Optional[str] = None,
        entry_cid: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> UscodeGraphNode:
        existing = nodes.get(node_key)
        if existing is not None:
            return existing
        node = UscodeGraphNode(
            node_type=node_type,
            node_key=node_key,
            label=label,
            legal_id=legal_id,
            entry_cid=entry_cid,
            payload=dict(payload or {}),
        )
        nodes[node_key] = node
        return node

    def _edge(
        self,
        edge_type: GraphEdgeType,
        source: UscodeGraphNode,
        target: UscodeGraphNode,
        *,
        source_span: Optional[SourceSpan] = None,
        resolution_status: Optional[ResolutionStatus] = None,
        weight: Optional[float] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> UscodeGraphEdge:
        edge_class = self.ontology.validate_edge(
            edge_type,
            source.node_type,
            target.node_type,
        )
        return UscodeGraphEdge(
            edge_type=edge_type,
            source_node_cid=source.node_cid,
            target_node_cid=target.node_cid,
            edge_class=edge_class,
            source_span=source_span,
            resolution_status=resolution_status,
            weight=weight,
            payload=dict(payload or {}),
        )

    @staticmethod
    def _normalize_public_law_id(value: str) -> str:
        text = str(value).strip()
        if text.startswith("pl:us:"):
            return text
        match = re.search(r"(\d+)\s*[-–—]\s*(\d+)", text)
        if match:
            return f"pl:us:{int(match.group(1))}:{int(match.group(2))}"
        raise GraphProjectionError(f"cannot normalize public law id: {value!r}")

    @staticmethod
    def _coerce_legal_id(value: str) -> str:
        text = str(value).strip()
        if text.startswith("usc:"):
            return text
        # Accept "35 U.S.C. § 102" style.
        match = _USC_CITATION_RE.search(text)
        if match:
            return build_legal_id(
                title=match.group("title"),
                section=match.group("section"),
            )
        # Accept "35:102"
        if re.fullmatch(r"\d+[A-Za-z]?:\S+", text):
            title, section = text.split(":", 1)
            return build_legal_id(title=title, section=section)
        raise GraphProjectionError(f"cannot coerce legal id: {value!r}")

    @staticmethod
    def _synthetic_field_span(
        row: GraphCorpusRow,
        *,
        field_name: str,
        mention: str,
    ) -> SourceSpan:
        """Bind a span when evidence comes from a structured field.

        Prefer locating *mention* inside the body text; otherwise bind a
        zero-width-safe synthetic span over a deterministic prefix field
        marker so authority edges still carry bound offsets.
        """

        if mention and mention in row.text:
            return SourceSpan.from_occurrence(
                row.text,
                mention,
                source_cid=row.source_cid,
                entry_cid=row.entry_cid,
                field="text",
            )
        # Synthetic: encode field evidence as a bound span of the mention
        # itself with offsets 0..len(mention) against a virtual field string.
        virtual = mention
        return SourceSpan(
            start=0,
            end=len(virtual),
            text=virtual,
            source_cid=row.source_cid,
            entry_cid=row.entry_cid,
            field=field_name,
        )


def project_uscode_graph(
    rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
    *,
    similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
    include_code_root: bool = True,
) -> UscodeGraphProjection:
    """Project corpus rows into a deterministic legal graph."""

    return UscodeGraphProjector().project(
        rows,
        similarity_neighbors=similarity_neighbors,
        include_code_root=include_code_root,
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_graph_expected_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_graph_expected.json"
    )


def _fixture_seed_records() -> list[dict[str, Any]]:
    """Compact sealed corpus slice used by the expected-path fixture."""

    return [
        {
            "entry_cid": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "source_cid": (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "legal_id": "usc:us:35:101",
            "title": "35",
            "section": "101",
            "chapter": "10",
            "heading": "Inventions patentable",
            "release_point": "us/pl/118/45",
            "edition": "olrc-us-pl-118-45",
            "text": (
                "Whoever invents or discovers any new and useful process, "
                "machine, manufacture, or composition of matter may obtain a "
                "patent therefor, subject to the conditions and requirements "
                "of this title. See also 35 U.S.C. § 102 and 35 U.S.C. § 103. "
                "Codified from Pub. L. 112-29. See also 99 U.S.C. § 9999."
            ),
            "public_laws": ["Pub. L. 112-29"],
            "amends": [],
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:cccccccccccccccccccccccccccccccc"
                "cccccccccccccccccccccccccccccccc"
            ),
            "source_cid": (
                "sha256:dddddddddddddddddddddddddddddddd"
                "dddddddddddddddddddddddddddddddd"
            ),
            "legal_id": "usc:us:35:102",
            "title": "35",
            "section": "102",
            "chapter": "10",
            "heading": "Conditions for patentability; novelty",
            "release_point": "us/pl/118/45",
            "edition": "olrc-us-pl-118-45",
            "text": (
                "A person shall be entitled to a patent unless the claimed "
                "invention was patented or described. Cross-reference "
                "35 U.S.C. § 101. Derived from 125 Stat. 284."
            ),
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            ),
            "source_cid": (
                "sha256:ffffffffffffffffffffffffffffffff"
                "ffffffffffffffffffffffffffffffff"
            ),
            "legal_id": "usc:us:35:103",
            "title": "35",
            "section": "103",
            "chapter": "10",
            "heading": "Conditions for patentability; non-obvious subject matter",
            "release_point": "us/pl/118/45",
            "text": (
                "A patent for a claimed invention may not be obtained if the "
                "differences would have been obvious. See 35 U.S.C. § 102."
            ),
            "amends": ["usc:us:35:102"],
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:11111111111111111111111111111111"
                "11111111111111111111111111111111"
            ),
            "source_cid": (
                "sha256:22222222222222222222222222222222"
                "22222222222222222222222222222222"
            ),
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "chapter": "5",
            "heading": "Public information; agency rules, opinions, orders, records, and proceedings",
            "release_point": "us/pl/118/45",
            "text": (
                "Each agency shall make available to the public information. "
                "Related privacy obligations appear at 5 U.S.C. § 552a. "
                "Pub. L. 89-487."
            ),
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:33333333333333333333333333333333"
                "33333333333333333333333333333333"
            ),
            "source_cid": (
                "sha256:44444444444444444444444444444444"
                "44444444444444444444444444444444"
            ),
            "legal_id": "usc:us:5:552a",
            "title": "5",
            "section": "552a",
            "chapter": "5",
            "heading": "Records maintained on individuals",
            "release_point": "us/pl/118/45",
            "text": (
                "No agency shall disclose any record except pursuant to a "
                "written request. See FOIA procedures in 5 U.S.C. § 552."
            ),
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:55555555555555555555555555555555"
                "55555555555555555555555555555555"
            ),
            "source_cid": (
                "sha256:66666666666666666666666666666666"
                "66666666666666666666666666666666"
            ),
            "legal_id": "usc:us:28:1331",
            "title": "28",
            "section": "1331",
            "chapter": "85",
            "heading": "Federal question",
            "release_point": "us/pl/118/45",
            "text": (
                "The district courts shall have original jurisdiction of all "
                "civil actions arising under the Constitution, laws, or "
                "treaties of the United States. Supplemental jurisdiction is "
                "addressed in 28 U.S.C. § 1367. This section transfers "
                "related matters formerly under 28 U.S.C. § 41."
            ),
            "transfers": ["usc:us:28:1367"],
            "version_id": "olrc-us-pl-118-45",
        },
        {
            "entry_cid": (
                "sha256:77777777777777777777777777777777"
                "77777777777777777777777777777777"
            ),
            "source_cid": (
                "sha256:88888888888888888888888888888888"
                "88888888888888888888888888888888"
            ),
            "legal_id": "usc:us:28:1367",
            "title": "28",
            "section": "1367",
            "chapter": "85",
            "heading": "Supplemental jurisdiction",
            "release_point": "us/pl/118/45",
            "text": (
                "Except as provided in subsections (b) and (c) or as "
                "expressly provided otherwise by Federal statute, in any "
                "civil action of which the district courts have original "
                "jurisdiction under 28 U.S.C. § 1331, the district courts "
                "shall have supplemental jurisdiction."
            ),
            "version_id": "olrc-us-pl-118-45",
        },
    ]


def _fixture_similarity_neighbors() -> list[dict[str, Any]]:
    return [
        {
            "source_legal_id": "usc:us:35:101",
            "target_legal_id": "usc:us:35:103",
            "score": 12.5,
            "edge_type": "BM25_NEIGHBOR_OF",
            "metric": "bm25",
            "config_cid": (
                "sha256:99999999999999999999999999999999"
                "99999999999999999999999999999999"
            ),
        }
    ]


def _fixture_expected_paths() -> list[dict[str, Any]]:
    return [
        {
            "path_id": "title-contains-chapter-contains-section",
            "source_key": "title:35",
            "target_key": "section:usc:us:35:101",
            "edge_types": ["CONTAINS", "CONTAINS"],
        },
        {
            "path_id": "section-cites-section",
            "source_key": "section:usc:us:35:101",
            "target_key": "section:usc:us:35:102",
            "edge_types": ["CITES"],
        },
        {
            "path_id": "public-law-codifies-section",
            "source_key": "public_law:pl:us:112:29",
            "target_key": "section:usc:us:35:101",
            "edge_types": ["CODIFIES"],
        },
        {
            "path_id": "section-amends-section",
            "source_key": "section:usc:us:35:103",
            "target_key": "section:usc:us:35:102",
            "edge_types": ["AMENDS"],
        },
        {
            "path_id": "section-transfers-section",
            "source_key": "section:usc:us:28:1331",
            "target_key": "section:usc:us:28:1367",
            "edge_types": ["TRANSFERS"],
        },
        {
            "path_id": "section-has-source",
            "source_key": "section:usc:us:5:552",
            "target_key": (
                "source:sha256:22222222222222222222222222222222"
                "22222222222222222222222222222222"
            ),
            "edge_types": ["HAS_SOURCE"],
        },
        {
            "path_id": "section-has-version",
            "source_key": "section:usc:us:35:101",
            "target_key": "version:usc:us:35:101:olrc-us-pl-118-45",
            "edge_types": ["HAS_VERSION"],
        },
        {
            "path_id": "cross-title-foia-privacy-citation",
            "source_key": "section:usc:us:5:552",
            "target_key": "section:usc:us:5:552a",
            "edge_types": ["CITES"],
        },
        {
            "path_id": "federal-question-cites-supplemental",
            "source_key": "section:usc:us:28:1331",
            "target_key": "section:usc:us:28:1367",
            "edge_types": ["CITES"],
        },
        {
            "path_id": "patentability-citation-chain",
            "source_key": "section:usc:us:35:101",
            "target_key": "section:usc:us:35:103",
            "edge_types": ["CITES"],
        },
    ]


def build_default_graph_expected_fixture_payload() -> dict[str, Any]:
    """Compact sealed expected-path recipe (no bulk node/edge dumps)."""

    records = _fixture_seed_records()
    neighbors = _fixture_similarity_neighbors()
    projection = project_uscode_graph(records, similarity_neighbors=neighbors)
    expected_paths = _fixture_expected_paths()
    # Verify paths match before sealing so the recipe is self-consistent.
    matches = match_expected_paths(projection, expected_paths)
    unmatched = [m for m in matches if not m["matched"]]
    if unmatched:
        raise GraphFixtureError(
            f"default fixture paths do not match projection: {unmatched!r}"
        )

    return {
        "acceptance": {
            "fixture_graph_paths_match": True,
            "legal_and_similarity_semantics_disjoint": True,
            "source_spans_are_bound": True,
            "unresolved_citations_preserved_honestly": True,
        },
        "citation_parser_version": CITATION_PARSER_VERSION,
        "description": (
            "Compact legal graph expected-path recipe for USCIR-021. Cases "
            "exercise structural, citation, public-law, amendment/transfer, "
            "version, source, and unresolved-reference projection. Similarity "
            "edges are present but non-authoritative and disjoint from legal "
            "semantics. Expand via run_fixture_case(); do not store bulk "
            "node/edge golden dumps."
        ),
        "expected_paths": expected_paths,
        "goal_id": GOAL_ID,
        "notes": (
            "Recipe form: seed records + expected path predicates. Full graph "
            "is projected deterministically by uscode_graph.project_uscode_graph."
        ),
        "ontology_version": ONTOLOGY_VERSION,
        "producer": PRODUCER,
        "projection_expectations": {
            "legal_edge_count_min": 15,
            "min_nodes": 20,
            "similarity_edge_count": 1,
            "unresolved_count_min": 1,
        },
        "records": records,
        "release_profile": RELEASE_PROFILE,
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "similarity_neighbors": neighbors,
        "task_id": TASK_ID,
        "unresolved_expectations": {
            "must_not_invent_target_legal_id": True,
            "must_preserve_parser_version": True,
            "must_preserve_source_text": True,
            "resolution_status": ResolutionStatus.UNRESOLVED.value,
            "sample_mention_substring": "99 U.S.C. § 9999",
        },
    }


def load_graph_expected_fixture_payload(
    path: PathLike | None = None,
) -> dict[str, Any]:
    fixture_path = (
        Path(path) if path is not None else default_graph_expected_fixture_path()
    )
    if not fixture_path.is_file():
        raise GraphFixtureError(f"graph expected fixture not found: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GraphFixtureError(f"invalid graph fixture JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise GraphFixtureError("graph fixture root must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise GraphFixtureError(
            f"unsupported graph fixture schema_version: {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )
    if "records" not in payload or "expected_paths" not in payload:
        raise GraphFixtureError(
            "graph fixture must include records and expected_paths"
        )
    return dict(payload)


def run_fixture_case(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project the sealed fixture and verify acceptance predicates."""

    data = (
        dict(payload)
        if payload is not None
        else load_graph_expected_fixture_payload()
    )
    records = list(data.get("records") or [])
    neighbors = list(data.get("similarity_neighbors") or [])
    expected_paths = list(data.get("expected_paths") or [])
    projection = project_uscode_graph(records, similarity_neighbors=neighbors)
    projection.assert_semantics_disjoint()

    # Source spans bound on span-required edges.
    span_errors: list[str] = []
    for edge in projection.edges:
        if edge.edge_type in SPAN_REQUIRED_EDGE_TYPES:
            if edge.source_span is None:
                span_errors.append(f"{edge.edge_cid}: missing span")
            elif edge.source_span.end < edge.source_span.start:
                span_errors.append(f"{edge.edge_cid}: inverted span")

    # Unresolved honesty.
    unresolved_edges = [
        e
        for e in projection.edges
        if e.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    unresolved_nodes = [
        n
        for n in projection.nodes
        if n.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    unresolved_ok = True
    for node in unresolved_nodes:
        if node.payload.get("resolution_status") != ResolutionStatus.UNRESOLVED.value:
            unresolved_ok = False
        if node.legal_id is not None:
            unresolved_ok = False  # must not invent a target legal_id
        if not node.payload.get("mention_text"):
            unresolved_ok = False
        if not node.payload.get("parser_version"):
            unresolved_ok = False
    for edge in unresolved_edges:
        if edge.resolution_status is not ResolutionStatus.UNRESOLVED:
            unresolved_ok = False
        if edge.source_span is None or not edge.source_span.text:
            unresolved_ok = False

    path_matches = match_expected_paths(projection, expected_paths)
    paths_ok = all(item["matched"] for item in path_matches)

    expectations = data.get("projection_expectations") or {}
    counts_ok = True
    if projection.legal_edge_count < int(expectations.get("legal_edge_count_min") or 0):
        counts_ok = False
    if len(projection.nodes) < int(expectations.get("min_nodes") or 0):
        counts_ok = False
    if projection.similarity_edge_count != int(
        expectations.get("similarity_edge_count") or projection.similarity_edge_count
    ):
        # Only enforce when fixture declares an exact count.
        if "similarity_edge_count" in expectations:
            counts_ok = False
    if projection.unresolved_count < int(expectations.get("unresolved_count_min") or 0):
        counts_ok = False

    # Similarity edges must not appear in legal path matching.
    legal_path_edge_types = {
        et for path in find_graph_paths(projection, legal_only=True) for et in path.edge_types
    }
    similarity_leaked = bool(
        legal_path_edge_types
        & {item.value for item in SIMILARITY_EDGE_TYPES}
    )

    ok = (
        paths_ok
        and unresolved_ok
        and not span_errors
        and counts_ok
        and not similarity_leaked
        and projection.similarity_edge_count >= 0
    )
    return {
        "graph_cid": projection.graph_cid,
        "legal_edge_count": projection.legal_edge_count,
        "node_count": len(projection.nodes),
        "ok": ok,
        "path_matches": path_matches,
        "similarity_edge_count": projection.similarity_edge_count,
        "similarity_leaked_into_legal_paths": similarity_leaked,
        "span_errors": span_errors,
        "unresolved_count": projection.unresolved_count,
        "unresolved_ok": unresolved_ok,
    }


def write_default_graph_expected_fixture(
    path: PathLike | None = None,
) -> Path:
    """Write the sealed compact expected-path fixture atomically."""

    fixture_path = (
        Path(path) if path is not None else default_graph_expected_fixture_path()
    )
    payload = build_default_graph_expected_fixture_payload()
    outcome = run_fixture_case(payload)
    if not outcome.get("ok"):
        raise GraphFixtureError(f"fixture failed self-check: {outcome!r}")
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fixture_path.write_text(text, encoding="utf-8")
    return fixture_path


__all__ = [
    "SCHEMA_VERSION",
    "ONTOLOGY_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "CITATION_PARSER_VERSION",
    "TASK_ID",
    "GOAL_ID",
    "PRODUCER",
    "RELEASE_PROFILE",
    "LEGAL_EDGE_TYPES",
    "SIMILARITY_EDGE_TYPES",
    "SPAN_REQUIRED_EDGE_TYPES",
    "DEFAULT_EDGE_CLASS",
    "GRAPH_ONTOLOGY",
    "GraphNodeType",
    "GraphEdgeType",
    "GraphEdgeClass",
    "ResolutionStatus",
    "UscodeGraphError",
    "GraphOntologyError",
    "SourceSpanError",
    "CitationResolutionError",
    "GraphProjectionError",
    "GraphFixtureError",
    "LegalSimilarityCollisionError",
    "SourceSpan",
    "GraphOntology",
    "CitationMention",
    "ResolvedCitation",
    "UscodeGraphNode",
    "UscodeGraphEdge",
    "GraphPath",
    "UscodeGraphProjection",
    "GraphCorpusRow",
    "SimilarityNeighbor",
    "UscodeGraphProjector",
    "assert_legal_similarity_disjoint",
    "sha256_cid",
    "extract_citation_mentions",
    "resolve_citations",
    "project_uscode_graph",
    "find_graph_paths",
    "match_expected_paths",
    "default_graph_expected_fixture_path",
    "build_default_graph_expected_fixture_payload",
    "load_graph_expected_fixture_payload",
    "run_fixture_case",
    "write_default_graph_expected_fixture",
]
