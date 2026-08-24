"""Multi-jurisdiction legal and provenance graph for Open US Law (OUL-030).

This module owns the versioned legal-graph ontology and the deterministic
projection of jurisdiction, code, title, chapter, section, subsection,
citation, amendment, source, edition, and provenance nodes and edges.

Design invariants
-----------------
* Legal authority and retrieval similarity are **disjoint**. Embedding
  neighbors, BM25 neighbors, and lexical similarity are non-authoritative
  retrieval hints and must never be labeled as citation, amendment, or
  legal validity.
* Unresolved citations are preserved honestly: source text, parser
  version, and ``resolution_status=unresolved`` are retained. Targets are
  never invented.
* Nodes and edges are deterministically content-addressed and CID-sorted.
* Recovery and quarantine rows never increment graph family counts.
* Physical adjacency paging belongs to OUL-031; this module emits the
  legal ontology projection only.
* No network I/O or Parquet I/O. Unit tests use compact sealed recipes.

Depends on OUL-024 (canonical corpus identity) and OUL-026 (streaming
atomic writers / shared layout primitives).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ADR_PATH,
    DEFAULT_CONFIGURATION,
    EXACT_51_JURISDICTION_CODES,
    JURISDICTION_NAMES,
    LEGAL_ID_PREFIX,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    DocumentKind,
    Hierarchy,
    ReleaseConfiguration,
    StatuteStatus,
    build_legal_id,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    normalize_code_family,
    normalize_edition,
    normalize_hierarchy,
    normalize_jurisdiction_code,
    normalize_section_token,
    parse_legal_id,
    reject_positional_durable_identity,
    validate_entry_cid,
    validate_source_cid,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    write_json_atomic,
)

# ---------------------------------------------------------------------------
# Schema / task pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-graph-v1"
ONTOLOGY_VERSION: Final = "open-us-law-graph-ontology/v1"
FIXTURE_SCHEMA_VERSION: Final = "open-us-law-graph-expected-v1"
RECEIPT_SCHEMA_VERSION: Final = "open-us-law-legal-graph-receipt-v1"
CITATION_PARSER_VERSION: Final = "open-us-law-citation-parser/v1"
TASK_ID: Final = "OUL-030"
GOAL_ID: Final = "OUL-G040"
PRODUCER: Final = "open_us_law_graph.py"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "legal-graph"
RECEIPT_SEALED_AT: Final = "2026-08-14T00:00:00Z"
EXACT_51_SEED_ROW_LOWER_BOUND: Final = 1_904_919

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

REPORT_RELATIVE_PATH: Final = "docs/reports/open_us_law_reindex/legal_graph_receipt.json"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS: Final = frozenset(
    {
        ReleaseConfiguration.RECOVERY.value,
        ReleaseConfiguration.QUARANTINE.value,
    }
)

REQUIRED_COVERAGE_NODE_TYPES: Final = (
    "jurisdiction",
    "code",
    "title",
    "chapter",
    "section",
    "subsection",
    "citation",
    "amendment",
    "source",
    "edition",
    "provenance",
)

NON_AUTHORITATIVE_AUTHORITY: Final = "non_authoritative"
LEGAL_AUTHORITY: Final = "legal"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class GraphNodeType(str, Enum):
    """Versioned multi-jurisdiction legal graph node vocabulary (OUL-030)."""

    JURISDICTION = "jurisdiction"
    CODE = "code"
    TITLE = "title"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    CITATION = "citation"
    UNRESOLVED_CITATION = "unresolved_citation"
    AMENDMENT = "amendment"
    SOURCE = "source"
    EDITION = "edition"
    PROVENANCE = "provenance"
    PUBLIC_LAW = "public_law"

    @classmethod
    def coerce(cls, value: Any) -> "GraphNodeType":
        if isinstance(value, GraphNodeType):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "state": cls.JURISDICTION,
            "statute_code": cls.CODE,
            "code_family": cls.CODE,
            "cite": cls.CITATION,
            "unresolved": cls.UNRESOLVED_CITATION,
            "unresolved_cite": cls.UNRESOLVED_CITATION,
            "amends": cls.AMENDMENT,
            "source_package": cls.SOURCE,
            "source_granule": cls.SOURCE,
            "version": cls.EDITION,
            "acquisition": cls.PROVENANCE,
            "pub_law": cls.PUBLIC_LAW,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise GraphOntologyError(f"unsupported graph node type: {value!r}")


class GraphEdgeType(str, Enum):
    """Versioned legal / similarity edge vocabulary (OUL-030)."""

    CONTAINS = "CONTAINS"
    CITES = "CITES"
    CITES_UNRESOLVED = "CITES_UNRESOLVED"
    HAS_CITATION = "HAS_CITATION"
    AMENDS = "AMENDS"
    REPEALS = "REPEALS"
    TRANSFERS = "TRANSFERS"
    HAS_AMENDMENT = "HAS_AMENDMENT"
    HAS_SOURCE = "HAS_SOURCE"
    HAS_EDITION = "HAS_EDITION"
    HAS_PROVENANCE = "HAS_PROVENANCE"
    DERIVED_FROM = "DERIVED_FROM"
    CODIFIES = "CODIFIES"
    BM25_NEIGHBOR_OF = "BM25_NEIGHBOR_OF"
    SIMILAR_TO = "SIMILAR_TO"
    EMBEDDING_NEIGHBOR_OF = "EMBEDDING_NEIGHBOR_OF"

    @classmethod
    def coerce(cls, value: Any) -> "GraphEdgeType":
        if isinstance(value, GraphEdgeType):
            return value
        text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "CONTAIN": cls.CONTAINS,
            "CITE": cls.CITES,
            "UNRESOLVED_CITE": cls.CITES_UNRESOLVED,
            "CITE_UNRESOLVED": cls.CITES_UNRESOLVED,
            "AMEND": cls.AMENDS,
            "REPEAL": cls.REPEALS,
            "TRANSFER": cls.TRANSFERS,
            "SOURCE": cls.HAS_SOURCE,
            "EDITION": cls.HAS_EDITION,
            "PROVENANCE": cls.HAS_PROVENANCE,
            "BM25": cls.BM25_NEIGHBOR_OF,
            "BM25_NEIGHBOR": cls.BM25_NEIGHBOR_OF,
            "SIMILAR": cls.SIMILAR_TO,
            "EMBEDDING": cls.EMBEDDING_NEIGHBOR_OF,
            "EMBEDDING_NEIGHBOR": cls.EMBEDDING_NEIGHBOR_OF,
            "COSINE": cls.EMBEDDING_NEIGHBOR_OF,
            "LEXICAL": cls.BM25_NEIGHBOR_OF,
        }
        if text in aliases:
            return aliases[text]
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


LEGAL_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.CONTAINS,
        GraphEdgeType.CITES,
        GraphEdgeType.CITES_UNRESOLVED,
        GraphEdgeType.HAS_CITATION,
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
        GraphEdgeType.HAS_AMENDMENT,
        GraphEdgeType.HAS_SOURCE,
        GraphEdgeType.HAS_EDITION,
        GraphEdgeType.HAS_PROVENANCE,
        GraphEdgeType.DERIVED_FROM,
        GraphEdgeType.CODIFIES,
    }
)

SIMILARITY_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.BM25_NEIGHBOR_OF,
        GraphEdgeType.SIMILAR_TO,
        GraphEdgeType.EMBEDDING_NEIGHBOR_OF,
    }
)

SPAN_REQUIRED_EDGE_TYPES: Final[frozenset[GraphEdgeType]] = frozenset(
    {
        GraphEdgeType.CITES,
        GraphEdgeType.CITES_UNRESOLVED,
        GraphEdgeType.HAS_CITATION,
        GraphEdgeType.AMENDS,
        GraphEdgeType.REPEALS,
        GraphEdgeType.TRANSFERS,
        GraphEdgeType.HAS_AMENDMENT,
        GraphEdgeType.DERIVED_FROM,
        GraphEdgeType.CODIFIES,
    }
)

DEFAULT_EDGE_CLASS: Final[Mapping[GraphEdgeType, GraphEdgeClass]] = MappingProxyType(
    {
        GraphEdgeType.CONTAINS: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.CITES: GraphEdgeClass.CITATION,
        GraphEdgeType.CITES_UNRESOLVED: GraphEdgeClass.UNRESOLVED,
        GraphEdgeType.HAS_CITATION: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.AMENDS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.REPEALS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.TRANSFERS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.HAS_AMENDMENT: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.HAS_SOURCE: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.HAS_EDITION: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.HAS_PROVENANCE: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.DERIVED_FROM: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.CODIFIES: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.BM25_NEIGHBOR_OF: GraphEdgeClass.SIMILARITY,
        GraphEdgeType.SIMILAR_TO: GraphEdgeClass.SIMILARITY,
        GraphEdgeType.EMBEDDING_NEIGHBOR_OF: GraphEdgeClass.SIMILARITY,
    }
)

SECTION_LIKE: Final[frozenset[GraphNodeType]] = frozenset(
    {GraphNodeType.SECTION, GraphNodeType.SUBSECTION}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawGraphError(ValueError):
    """Base error for Open US Law legal graph ontology / projection."""

    code: str = "open_us_law_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class GraphOntologyError(OpenUsLawGraphError):
    """Raised when ontology contracts are violated."""

    code = "graph_ontology"


class SourceSpanError(OpenUsLawGraphError):
    """Raised when a source span is unbound or inconsistent."""

    code = "source_span"


class CitationResolutionError(OpenUsLawGraphError):
    """Raised when citation resolution is malformed (not merely unresolved)."""

    code = "citation_resolution"


class GraphProjectionError(OpenUsLawGraphError):
    """Raised when graph projection fails integrity checks."""

    code = "graph_projection"


class GraphFixtureError(OpenUsLawGraphError):
    """Raised when the sealed graph recipe is malformed."""

    code = "graph_fixture"


class LegalSimilarityCollisionError(OpenUsLawGraphError):
    """Raised when legal and similarity semantics are mixed."""

    code = "legal_similarity_collision"


class GraphReceiptError(OpenUsLawGraphError):
    """Raised when the software-contract receipt is malformed."""

    code = "graph_receipt"


class GraphReleaseAuthorizationError(OpenUsLawGraphError):
    """Raised when a graph artifact would authorize publication or release."""

    code = "graph_release_authorization"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawGraphError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise OpenUsLawGraphError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise OpenUsLawGraphError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value", *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawGraphError(f"{name} must be an integer")
    if value < 0:
        raise OpenUsLawGraphError(f"{name} must be >= 0")
    return value


def sha256_cid(payload: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:<hex>`` content address."""

    return f"sha256:{digest_mapping(dict(payload))}"


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


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def default_legal_graph_receipt_path() -> Path:
    return DEFAULT_REPORT_PATH


def production_graph_bounds() -> dict[str, Any]:
    return {
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "nodes_and_edges_sorted_by": "type_then_key_then_cid",
        "similarity_cannot_establish_legal_authority": True,
    }


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
    required_coverage_node_types: tuple[str, ...] = REQUIRED_COVERAGE_NODE_TYPES
    edge_class_by_type: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(
            {key.value: value.value for key, value in DEFAULT_EDGE_CLASS.items()}
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
        missing = [name for name in REQUIRED_COVERAGE_NODE_TYPES if name not in expected_nodes]
        if missing:
            raise GraphOntologyError(
                f"ontology is missing required coverage node types: {missing}"
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

        if edge in SIMILARITY_EDGE_TYPES and category is not GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"similarity edge {edge.value} cannot use class {category.value}"
            )
        if edge in LEGAL_EDGE_TYPES and category is GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"legal edge {edge.value} cannot use class similarity"
            )
        if not _edge_direction_allowed(edge, source, target):
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
            "required_coverage_node_types": list(self.required_coverage_node_types),
            "similarity_edge_types": list(self.similarity_edge_types),
            "version": self.version,
        }


def _edge_direction_allowed(
    edge: GraphEdgeType,
    source: GraphNodeType,
    target: GraphNodeType,
) -> bool:
    if edge is GraphEdgeType.CONTAINS:
        allowed = {
            (GraphNodeType.JURISDICTION, GraphNodeType.CODE),
            (GraphNodeType.CODE, GraphNodeType.TITLE),
            (GraphNodeType.CODE, GraphNodeType.CHAPTER),
            (GraphNodeType.CODE, GraphNodeType.SECTION),
            (GraphNodeType.TITLE, GraphNodeType.CHAPTER),
            (GraphNodeType.TITLE, GraphNodeType.SECTION),
            (GraphNodeType.CHAPTER, GraphNodeType.SECTION),
            (GraphNodeType.SECTION, GraphNodeType.SUBSECTION),
        }
        return (source, target) in allowed
    if edge is GraphEdgeType.CITES:
        return source in SECTION_LIKE and target in SECTION_LIKE
    if edge is GraphEdgeType.CITES_UNRESOLVED:
        return source in SECTION_LIKE and target is GraphNodeType.UNRESOLVED_CITATION
    if edge is GraphEdgeType.HAS_CITATION:
        return source in SECTION_LIKE and target is GraphNodeType.CITATION
    if edge in {GraphEdgeType.AMENDS, GraphEdgeType.REPEALS, GraphEdgeType.TRANSFERS}:
        return source in SECTION_LIKE | {GraphNodeType.AMENDMENT, GraphNodeType.PUBLIC_LAW} and (
            target in SECTION_LIKE
        )
    if edge is GraphEdgeType.HAS_AMENDMENT:
        return source in SECTION_LIKE and target is GraphNodeType.AMENDMENT
    if edge is GraphEdgeType.HAS_SOURCE:
        return source in SECTION_LIKE and target is GraphNodeType.SOURCE
    if edge is GraphEdgeType.HAS_EDITION:
        return source in {
            GraphNodeType.JURISDICTION,
            GraphNodeType.CODE,
            GraphNodeType.TITLE,
            GraphNodeType.CHAPTER,
            GraphNodeType.SECTION,
            GraphNodeType.SUBSECTION,
        } and target is GraphNodeType.EDITION
    if edge is GraphEdgeType.HAS_PROVENANCE:
        return source in SECTION_LIKE and target is GraphNodeType.PROVENANCE
    if edge is GraphEdgeType.DERIVED_FROM:
        return source in SECTION_LIKE and target in {
            GraphNodeType.PUBLIC_LAW,
            GraphNodeType.SOURCE,
            GraphNodeType.PROVENANCE,
        }
    if edge is GraphEdgeType.CODIFIES:
        return source is GraphNodeType.PUBLIC_LAW and target in SECTION_LIKE
    if edge in SIMILARITY_EDGE_TYPES:
        return source in SECTION_LIKE and target in SECTION_LIKE
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

_SHORT_CODE_RE = re.compile(
    r"""
    (?P<mention>
        (?P<code>
            ORS|RCW|NRS|CRS|ARS|C\.R\.S\.|A\.R\.S\.|USC|
            D\.C\.\s*Code|DC\s+Code
        )
        \s+
        (?:§+\s*)?
        (?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_BLUEBOOK_RE = re.compile(
    r"""
    (?P<mention>
        (?P<prefix>
            Cal\.|Calif\.|California|
            N\.Y\.|NY|New\s+York|
            Or\.|Ore\.|Oregon|
            Tex\.|Texas|
            Wash\.|Washington|
            D\.C\.|DC
        )
        \s+
        (?P<code>
            Penal\s+Code|Penal\s+Law|Rev\.\s*Stat\.|Rev\.\s*Code|
            Revised\s+Statutes|Revised\s+Code|Code
        )
        \s*
        (?:§+\s*)
        (?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_INTERNAL_SECTION_RE = re.compile(
    r"(?P<mention>§+\s*(?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*))"
)

CITATION_CODE_ALIASES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "ors": ("OR", "ors"),
        "or rev stat": ("OR", "ors"),
        "or. rev. stat": ("OR", "ors"),
        "ore rev stat": ("OR", "ors"),
        "oregon revised statutes": ("OR", "ors"),
        "or. revised statutes": ("OR", "ors"),
        "rcw": ("WA", "rcw"),
        "wash rev code": ("WA", "rcw"),
        "wash. rev. code": ("WA", "rcw"),
        "washington revised code": ("WA", "rcw"),
        "cal penal code": ("CA", "penal-code"),
        "cal. penal code": ("CA", "penal-code"),
        "calif penal code": ("CA", "penal-code"),
        "california penal code": ("CA", "penal-code"),
        "n.y. penal law": ("NY", "penal-law"),
        "ny penal law": ("NY", "penal-law"),
        "new york penal law": ("NY", "penal-law"),
        "d.c. code": ("DC", "code"),
        "dc code": ("DC", "code"),
        "usc": ("US", "usc"),
        "u.s.c": ("US", "usc"),
        "u.s.c.a": ("US", "usc"),
        "united states code": ("US", "usc"),
    }
)


def _alias_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = normalized.replace("§", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s+\.", ".", normalized)
    return normalized.strip(" .")


def lookup_citation_locator(
    code_text: str,
    *,
    prefix: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """Map a citation code phrase onto ``(jurisdiction_code, code_family)``."""

    candidates = [code_text]
    if prefix:
        candidates.append(f"{prefix} {code_text}")
    for raw in candidates:
        key = _alias_key(raw)
        if key in CITATION_CODE_ALIASES:
            return CITATION_CODE_ALIASES[key]
        dotted = key.replace(" ", "")
        for alias, locator in CITATION_CODE_ALIASES.items():
            if alias.replace(" ", "") == dotted or alias.replace(".", "") == key.replace(".", ""):
                return locator
    return None


@dataclass(frozen=True, slots=True)
class CitationMention:
    """One citation occurrence extracted from source text."""

    kind: str
    mention_text: str
    start: int
    end: int
    jurisdiction_code: Optional[str] = None
    code_family: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    congress: Optional[str] = None
    number: Optional[str] = None
    parser_version: str = CITATION_PARSER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_non_empty_str(self.kind, "kind", maximum=64))
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_family": self.code_family,
            "congress": self.congress,
            "end": self.end,
            "jurisdiction_code": self.jurisdiction_code,
            "kind": self.kind,
            "mention_text": self.mention_text,
            "number": self.number,
            "parser_version": self.parser_version,
            "section": self.section,
            "start": self.start,
            "title": self.title,
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


def _drop_contained_mentions(mentions: list[CitationMention]) -> list[CitationMention]:
    kept: list[CitationMention] = []
    for candidate in sorted(mentions, key=lambda item: (item.start, -(item.end - item.start))):
        contained = False
        for existing in kept:
            if existing.start <= candidate.start and candidate.end <= existing.end:
                if (existing.start, existing.end) != (candidate.start, candidate.end):
                    contained = True
                    break
                if existing.kind != "internal" and candidate.kind == "internal":
                    contained = True
                    break
        if not contained:
            kept.append(candidate)
    kept.sort(key=lambda item: (item.start, item.end, item.kind))
    return kept


def _normalize_extracted_section(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return normalize_section_token(value)
    except Exception:
        return value.strip()


def extract_citation_mentions(
    text: str,
    *,
    default_jurisdiction: Optional[str] = None,
    default_code_family: Optional[str] = None,
) -> list[CitationMention]:
    """Extract USC, state-code, public-law, and internal section mentions."""

    if not isinstance(text, str):
        raise CitationResolutionError("text must be a string")
    mentions: list[CitationMention] = []

    for match in _USC_CITATION_RE.finditer(text):
        mentions.append(
            CitationMention(
                kind="usc",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code="US",
                code_family="usc",
                title=match.group("title"),
                section=_normalize_extracted_section(match.group("section")),
            )
        )

    for match in _PUBLIC_LAW_RE.finditer(text):
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

    for match in _SHORT_CODE_RE.finditer(text):
        locator = lookup_citation_locator(match.group("code"))
        jurisdiction, family = locator if locator else (None, None)
        mentions.append(
            CitationMention(
                kind="state_code",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=jurisdiction,
                code_family=family,
                section=_normalize_extracted_section(match.group("section")),
            )
        )

    for match in _BLUEBOOK_RE.finditer(text):
        locator = lookup_citation_locator(
            match.group("code"),
            prefix=match.group("prefix"),
        )
        jurisdiction, family = locator if locator else (None, None)
        mentions.append(
            CitationMention(
                kind="bluebook",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=jurisdiction,
                code_family=family,
                section=_normalize_extracted_section(match.group("section")),
            )
        )

    for match in _INTERNAL_SECTION_RE.finditer(text):
        mentions.append(
            CitationMention(
                kind="internal",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=default_jurisdiction,
                code_family=default_code_family,
                section=_normalize_extracted_section(match.group("section")),
            )
        )

    return _drop_contained_mentions(mentions)


def _unresolved_node_key(mention: CitationMention) -> str:
    digest = content_sha256(mention.mention_text)[:16]
    jurisdiction = mention.jurisdiction_code or "?"
    family = mention.code_family or "?"
    section = mention.section or "?"
    return f"unresolved:{mention.kind}:{jurisdiction}:{family}:{section}:{digest}"


def resolve_citations(
    text: str,
    *,
    known_legal_ids: Iterable[str] | None = None,
    locator_index: Mapping[tuple[str, str, str], Sequence[str]] | None = None,
    source_cid: Optional[str] = None,
    entry_cid: Optional[str] = None,
    default_jurisdiction: Optional[str] = None,
    default_code_family: Optional[str] = None,
    host_legal_id: Optional[str] = None,
    host_section: Optional[str] = None,
) -> list[ResolvedCitation]:
    """Resolve extracted citations against known legal identities.

    Unknown targets become ``unresolved`` rather than invented nodes with
    guessed legal identities. Ambiguous locator matches are also unresolved.
    """

    known = {str(item) for item in (known_legal_ids or []) if item}
    locators = locator_index or {}
    resolved: list[ResolvedCitation] = []
    for mention in extract_citation_mentions(
        text,
        default_jurisdiction=default_jurisdiction,
        default_code_family=default_code_family,
    ):
        span = SourceSpan(
            start=mention.start,
            end=mention.end,
            text=text[mention.start : mention.end],
            source_cid=source_cid,
            entry_cid=entry_cid,
            field="text",
        ).bind_to_source(text)

        if mention.kind == "public_law":
            if mention.congress and mention.number:
                pl_id = f"pl:us:{int(mention.congress)}:{int(mention.number)}"
                resolved.append(
                    ResolvedCitation(
                        mention=mention,
                        resolution_status=ResolutionStatus.RESOLVED,
                        span=span,
                        target_public_law_id=pl_id,
                        target_node_key=f"public_law:{pl_id}",
                    )
                )
            continue

        if mention.kind == "internal" and host_section and mention.section == host_section:
            continue

        jurisdiction = mention.jurisdiction_code or default_jurisdiction
        family = mention.code_family or default_code_family
        section = mention.section
        matches: list[str] = []
        if jurisdiction and family and section:
            matches = list(locators.get((jurisdiction, family, section), ()))
        if not matches and mention.kind == "usc" and mention.title and mention.section:
            usc_candidate = None
            try:
                usc_candidate = build_legal_id(
                    document_kind=DocumentKind.FEDERAL,
                    jurisdiction_code="US",
                    code_family="usc",
                    hierarchy={"title": mention.title, "section": mention.section},
                    edition="unspecified",
                )
            except Exception:
                usc_candidate = None
            if usc_candidate and usc_candidate in known:
                matches = [usc_candidate]
            else:
                matches = [
                    item
                    for item in known
                    if ":usc:" in item
                    and f":{mention.title}:" in item
                    and item.rsplit(":", 1)[-1].split(";", 1)[0] == mention.section
                ]

        unique = []
        seen: set[str] = set()
        for item in matches:
            if item in known and item not in seen:
                unique.append(item)
                seen.add(item)
        if host_legal_id and unique and all(item == host_legal_id for item in unique):
            continue
        unique = [item for item in unique if item != host_legal_id]

        if len(unique) == 1:
            target = unique[0]
            resolved.append(
                ResolvedCitation(
                    mention=mention,
                    resolution_status=ResolutionStatus.RESOLVED,
                    span=span,
                    target_legal_id=target,
                    target_node_key=_section_or_subsection_key(target),
                )
            )
        else:
            status = (
                ResolutionStatus.AMBIGUOUS
                if len(unique) > 1
                else ResolutionStatus.UNRESOLVED
            )
            resolved.append(
                ResolvedCitation(
                    mention=mention,
                    resolution_status=status
                    if status is ResolutionStatus.AMBIGUOUS
                    else ResolutionStatus.UNRESOLVED,
                    span=span,
                    target_legal_id=None,
                    target_node_key=_unresolved_node_key(mention),
                )
            )
    return resolved


def _section_or_subsection_key(legal_id: str) -> str:
    try:
        parsed = parse_legal_id(legal_id)
    except Exception:
        return f"section:{legal_id}"
    if parsed.get("subsection"):
        return f"subsection:{legal_id}"
    return f"section:{legal_id}"


def strip_subsection_qualifier(legal_id: str) -> str:
    """Return the parent section legal id, dropping any subsection qualifier."""

    parsed = parse_legal_id(legal_id)
    hierarchy = parsed["hierarchy"]
    if not isinstance(hierarchy, Hierarchy) or not hierarchy.subsection:
        return legal_id
    parent = Hierarchy(
        section=hierarchy.section,
        title=hierarchy.title,
        chapter=hierarchy.chapter,
        part=hierarchy.part,
        article=hierarchy.article,
        subsection=None,
    )
    edition = parsed.get("edition") or "unspecified"
    return build_legal_id(
        document_kind=parsed["document_kind"],
        jurisdiction_code=parsed["jurisdiction_code"],
        code_family=parsed["code_family"],
        hierarchy=parent,
        edition=edition,
        status=parsed.get("status") or StatuteStatus.CURRENT,
        granule=parsed.get("granule"),
        note=parsed.get("note"),
    )


# ---------------------------------------------------------------------------
# Graph node / edge records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenUsLawGraphNode:
    """One projected legal graph node with a deterministic node CID."""

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
        key = _require_non_empty_str(self.node_key, "node_key", maximum=768)
        object.__setattr__(self, "node_key", key)
        object.__setattr__(
            self, "label", _require_non_empty_str(self.label, "label", maximum=1024)
        )
        if self.legal_id is not None:
            object.__setattr__(
                self,
                "legal_id",
                _require_non_empty_str(self.legal_id, "legal_id", maximum=768),
            )
            if node_type is GraphNodeType.UNRESOLVED_CITATION:
                raise CitationResolutionError(
                    "unresolved citation nodes must not carry an invented legal_id"
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
        cid = self.node_cid or sha256_cid({"kind": "open_us_law_graph_node", **identity})
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


@dataclass(frozen=True, slots=True)
class OpenUsLawGraphEdge:
    """One projected legal graph edge with a deterministic edge CID."""

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

        if edge_type in SIMILARITY_EDGE_TYPES and edge_class is not GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"{edge_type.value} must use edge_class=similarity"
            )
        if edge_type in LEGAL_EDGE_TYPES and edge_class is GraphEdgeClass.SIMILARITY:
            raise LegalSimilarityCollisionError(
                f"{edge_type.value} is a legal edge and cannot use similarity class"
            )
        if edge_type in SIMILARITY_EDGE_TYPES:
            authority = None
            if isinstance(self.payload, Mapping):
                authority = self.payload.get("authority")
            if authority not in {None, NON_AUTHORITATIVE_AUTHORITY}:
                raise LegalSimilarityCollisionError(
                    f"{edge_type.value} cannot claim legal authority={authority!r}"
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
            raise SourceSpanError(f"{edge_type.value} requires a bound source_span")
        if self.resolution_status is not None:
            object.__setattr__(
                self,
                "resolution_status",
                ResolutionStatus.coerce(self.resolution_status),
            )
        if edge_type is GraphEdgeType.CITES_UNRESOLVED:
            if self.resolution_status not in {
                ResolutionStatus.UNRESOLVED,
                ResolutionStatus.AMBIGUOUS,
            }:
                raise CitationResolutionError(
                    "CITES_UNRESOLVED requires unresolved or ambiguous status"
                )
        if self.weight is not None:
            if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
                raise GraphProjectionError("weight must be a number")
            object.__setattr__(self, "weight", float(self.weight))
        if not isinstance(self.payload, Mapping):
            raise GraphProjectionError("edge payload must be a mapping")
        payload = dict(self.payload)
        if edge_type in SIMILARITY_EDGE_TYPES:
            payload.setdefault("authority", NON_AUTHORITATIVE_AUTHORITY)
            if payload.get("authority") != NON_AUTHORITATIVE_AUTHORITY:
                raise LegalSimilarityCollisionError(
                    f"{edge_type.value} payload.authority must be {NON_AUTHORITATIVE_AUTHORITY}"
                )
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
        cid = self.edge_cid or sha256_cid({"kind": "open_us_law_graph_edge", **identity})
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


# ---------------------------------------------------------------------------
# Projection result / paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphPath:
    """One directed path of edge types between node keys."""

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
class OpenUsLawGraphProjection:
    """Deterministic multi-jurisdiction legal graph projection."""

    nodes: tuple[OpenUsLawGraphNode, ...]
    edges: tuple[OpenUsLawGraphEdge, ...]
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    citation_parser_version: str = CITATION_PARSER_VERSION
    unresolved_count: int = 0
    legal_edge_count: int = 0
    similarity_edge_count: int = 0
    skipped_row_count: int = 0
    graph_cid: str = ""

    def __post_init__(self) -> None:
        nodes = tuple(
            sorted(self.nodes, key=lambda item: (item.node_type.value, item.node_key, item.node_cid))
        )
        edges = tuple(
            sorted(
                self.edges,
                key=lambda item: (
                    item.edge_type.value,
                    item.source_node_cid,
                    item.target_node_cid,
                    item.edge_cid,
                ),
            )
        )
        if len({item.node_cid for item in nodes}) != len(nodes):
            raise GraphProjectionError("duplicate node_cid in projection")
        if len({item.edge_cid for item in edges}) != len(edges):
            raise GraphProjectionError("duplicate edge_cid in projection")
        node_cids = {item.node_cid for item in nodes}
        for edge in edges:
            if edge.source_node_cid not in node_cids or edge.target_node_cid not in node_cids:
                raise GraphProjectionError(
                    f"dangling edge {edge.edge_cid}: missing endpoint"
                )
        legal_count = sum(1 for item in edges if item.is_legal)
        sim_count = sum(1 for item in edges if item.is_similarity)
        unresolved = sum(
            1
            for item in edges
            if item.edge_type is GraphEdgeType.CITES_UNRESOLVED
            or item.resolution_status
            in {ResolutionStatus.UNRESOLVED, ResolutionStatus.AMBIGUOUS}
        )
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "legal_edge_count", legal_count)
        object.__setattr__(self, "similarity_edge_count", sim_count)
        object.__setattr__(self, "unresolved_count", unresolved)
        object.__setattr__(
            self, "skipped_row_count", _require_non_negative_int(self.skipped_row_count, "skipped_row_count")
        )
        root = {
            "citation_parser_version": self.citation_parser_version,
            "edge_cids": [item.edge_cid for item in edges],
            "node_cids": [item.node_cid for item in nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
            "skipped_row_count": self.skipped_row_count,
        }
        object.__setattr__(self, "graph_cid", self.graph_cid or sha256_cid(root))

    def node_by_key(self) -> dict[str, OpenUsLawGraphNode]:
        return {item.node_key: item for item in self.nodes}

    def node_by_cid(self) -> dict[str, OpenUsLawGraphNode]:
        return {item.node_cid: item for item in self.nodes}

    def legal_edges(self) -> tuple[OpenUsLawGraphEdge, ...]:
        return tuple(item for item in self.edges if item.is_legal)

    def similarity_edges(self) -> tuple[OpenUsLawGraphEdge, ...]:
        return tuple(item for item in self.edges if item.is_similarity)

    def coverage_node_types(self) -> set[str]:
        return {item.node_type.value for item in self.nodes}

    def missing_coverage_node_types(self) -> list[str]:
        present = self.coverage_node_types()
        return [name for name in REQUIRED_COVERAGE_NODE_TYPES if name not in present]

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
            if edge.is_similarity and edge.payload.get("authority") != NON_AUTHORITATIVE_AUTHORITY:
                raise LegalSimilarityCollisionError(
                    f"similarity edge {edge.edge_type.value} missing non-authoritative label"
                )

    def assert_coverage(self) -> None:
        missing = self.missing_coverage_node_types()
        if missing:
            raise GraphProjectionError(
                "projection is missing required coverage node types: "
                f"{missing}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_parser_version": self.citation_parser_version,
            "edges": [item.to_dict() for item in self.edges],
            "graph_cid": self.graph_cid,
            "legal_edge_count": self.legal_edge_count,
            "nodes": [item.to_dict() for item in self.nodes],
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
            "similarity_edge_count": self.similarity_edge_count,
            "skipped_row_count": self.skipped_row_count,
            "unresolved_count": self.unresolved_count,
        }


def find_graph_paths(
    projection: OpenUsLawGraphProjection,
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
    adjacency: dict[str, list[OpenUsLawGraphEdge]] = defaultdict(list)
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
                if target is None or target.node_key in node_keys:
                    continue
                queue.append(
                    (
                        target.node_cid,
                        node_keys + (target.node_key,),
                        edge_types + (edge.edge_type.value,),
                        edge_cids + (edge.edge_cid,),
                    )
                )

    paths.sort(
        key=lambda item: (
            item.source_key,
            item.target_key,
            item.edge_types,
            item.node_keys,
        )
    )
    return paths


def match_expected_paths(
    projection: OpenUsLawGraphProjection,
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
        edge_types = tuple(str(item) for item in (spec.get("edge_types") or ()))
        source_candidates = _path_key_candidates(source)
        target_candidates = _path_key_candidates(target)
        matched = None
        for path in actual:
            if path.source_key not in source_candidates:
                continue
            if path.target_key not in target_candidates:
                continue
            if edge_types and path.edge_types != edge_types:
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
    prefixes = (
        "section:",
        "subsection:",
        "jurisdiction:",
        "code:",
        "title:",
        "chapter:",
        "citation:",
        "unresolved:",
        "amendment:",
        "source:",
        "edition:",
        "provenance:",
        "public_law:",
    )
    if raw.startswith(f"{LEGAL_ID_PREFIX}:"):
        candidates.add(f"section:{raw}")
        candidates.add(f"subsection:{raw}")
    if raw.startswith("section:"):
        candidates.add(raw[len("section:") :])
    if raw.startswith("subsection:"):
        candidates.add(raw[len("subsection:") :])
    if not raw.startswith(prefixes) and raw.startswith(f"{LEGAL_ID_PREFIX}:"):
        candidates.add(f"section:{raw}")
    return candidates


def _is_subsequence(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    if not needle:
        return True
    index = 0
    for item in haystack:
        if item == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


# ---------------------------------------------------------------------------
# Corpus row projection
# ---------------------------------------------------------------------------


def _is_excluded_configuration(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        config = ReleaseConfiguration.coerce(value)
    except Exception:
        text = str(value).strip().lower().replace("-", "_")
        return text in GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS
    return config.value in GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS


@dataclass(frozen=True, slots=True)
class GraphCorpusRow:
    """One admitted corpus row eligible for legal graph projection."""

    entry_cid: str
    legal_id: str
    text: str
    jurisdiction_code: str
    code_family: str
    edition: str
    hierarchy: Hierarchy
    source_cid: Optional[str] = None
    heading: str = ""
    document_kind: str = DocumentKind.STATUTE.value
    configuration: str = DEFAULT_CONFIGURATION
    acquisition_receipt_cid: Optional[str] = None
    rights_receipt_cid: Optional[str] = None
    official_source_url: Optional[str] = None
    observed_at: Optional[str] = None
    public_laws: tuple[str, ...] = ()
    cites: tuple[str, ...] = ()
    amends: tuple[str, ...] = ()
    repeals: tuple[str, ...] = ()
    transfers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entry_cid",
            validate_entry_cid(_require_non_empty_str(self.entry_cid, "entry_cid", maximum=256)),
        )
        legal_id = _require_non_empty_str(self.legal_id, "legal_id", maximum=768)
        reject_positional_durable_identity(legal_id, name="legal_id")
        object.__setattr__(self, "legal_id", legal_id)
        if not isinstance(self.text, str):
            raise GraphProjectionError("text must be a string")
        if "\x00" in self.text:
            raise GraphProjectionError("text must not contain NUL")
        object.__setattr__(
            self,
            "jurisdiction_code",
            normalize_jurisdiction_code(self.jurisdiction_code, allow_non_default=True),
        )
        object.__setattr__(self, "code_family", normalize_code_family(self.code_family))
        object.__setattr__(self, "edition", normalize_edition(self.edition))
        object.__setattr__(self, "hierarchy", normalize_hierarchy(self.hierarchy))
        if self.source_cid is not None:
            object.__setattr__(self, "source_cid", validate_source_cid(self.source_cid))
        object.__setattr__(self, "heading", str(self.heading or ""))
        object.__setattr__(
            self,
            "public_laws",
            tuple(str(item) for item in (self.public_laws or ()) if item),
        )
        object.__setattr__(self, "cites", tuple(str(item) for item in (self.cites or ()) if item))
        object.__setattr__(self, "amends", tuple(str(item) for item in (self.amends or ()) if item))
        object.__setattr__(self, "repeals", tuple(str(item) for item in (self.repeals or ()) if item))
        object.__setattr__(
            self, "transfers", tuple(str(item) for item in (self.transfers or ()) if item)
        )

    @property
    def section(self) -> Optional[str]:
        return self.hierarchy.section

    @property
    def title(self) -> Optional[str]:
        return self.hierarchy.title

    @property
    def chapter(self) -> Optional[str]:
        return self.hierarchy.chapter

    @property
    def subsection(self) -> Optional[str]:
        return self.hierarchy.subsection

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphCorpusRow":
        if not isinstance(value, Mapping):
            raise GraphProjectionError("corpus row must be a mapping")
        hierarchy = value.get("hierarchy")
        if hierarchy in (None, ""):
            hierarchy = {
                key: value.get(key)
                for key in ("title", "chapter", "part", "article", "section", "subsection")
                if value.get(key) not in (None, "")
            }
        parsed_hierarchy = normalize_hierarchy(hierarchy)
        jurisdiction = value.get("jurisdiction_code") or value.get("jurisdiction") or ""
        code_family = value.get("code_family") or value.get("codeFamily") or ""
        edition = value.get("edition") or ""
        document_kind = (
            value.get("document_kind") or value.get("kind") or DocumentKind.STATUTE.value
        )
        legal_id = value.get("legal_id")
        if not legal_id:
            legal_id = build_legal_id(
                document_kind=document_kind,
                jurisdiction_code=jurisdiction,
                code_family=code_family,
                hierarchy=parsed_hierarchy,
                edition=edition,
                status=value.get("status") or StatuteStatus.CURRENT,
                subsection=value.get("subsection"),
                granule=value.get("granule"),
            )
        return cls(
            entry_cid=str(value.get("entry_cid") or ""),
            legal_id=str(legal_id or ""),
            text=str(value.get("text") or ""),
            jurisdiction_code=str(jurisdiction),
            code_family=str(code_family),
            edition=str(edition),
            hierarchy=parsed_hierarchy,
            source_cid=value.get("source_cid"),
            heading=str(value.get("heading") or ""),
            document_kind=str(document_kind),
            configuration=str(value.get("configuration") or DEFAULT_CONFIGURATION),
            acquisition_receipt_cid=_optional_str(value.get("acquisition_receipt_cid")),
            rights_receipt_cid=_optional_str(value.get("rights_receipt_cid")),
            official_source_url=_optional_str(value.get("official_source_url")),
            observed_at=_optional_str(value.get("observed_at")),
            public_laws=tuple(value.get("public_laws") or ()),
            cites=tuple(value.get("cites") or value.get("citations") or ()),
            amends=tuple(value.get("amends") or ()),
            repeals=tuple(value.get("repeals") or ()),
            transfers=tuple(value.get("transfers") or ()),
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
        object.__setattr__(
            self,
            "metric",
            _require_non_empty_str(self.metric or "bm25", "metric", maximum=64),
        )


class OpenUsLawGraphProjector:
    """Project admitted multi-jurisdiction rows into the legal ontology graph."""

    def __init__(self, ontology: GraphOntology | None = None) -> None:
        self.ontology = ontology or GRAPH_ONTOLOGY

    def project(
        self,
        rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
        *,
        similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
    ) -> OpenUsLawGraphProjection:
        admitted: list[GraphCorpusRow] = []
        skipped = 0
        for item in rows:
            row = self._coerce_row(item)
            if _is_excluded_configuration(row.configuration):
                skipped += 1
                continue
            admitted.append(row)
        if not admitted:
            raise GraphProjectionError("cannot project an empty corpus")

        known_legal_ids = {row.legal_id for row in admitted}
        locator_index: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        nodes: dict[str, OpenUsLawGraphNode] = {}
        edges: list[OpenUsLawGraphEdge] = []

        for row in admitted:
            self._project_structure(nodes, edges, row)
            if row.section:
                locator_index[(row.jurisdiction_code, row.code_family, row.section)].append(
                    row.legal_id
                )
            parent_id = strip_subsection_qualifier(row.legal_id)
            if parent_id != row.legal_id:
                known_legal_ids.add(parent_id)
                parent_section = row.section
                if parent_section:
                    locator_index[
                        (row.jurisdiction_code, row.code_family, parent_section)
                    ].append(parent_id)

        for row in admitted:
            self._project_citations(
                nodes,
                edges,
                row,
                known_legal_ids=known_legal_ids,
                locator_index=locator_index,
            )
            self._project_amendments(nodes, edges, row)

        for neighbor in similarity_neighbors or ():
            sim = self._coerce_similarity(neighbor)
            src_key = _section_or_subsection_key(sim.source_legal_id)
            tgt_key = _section_or_subsection_key(sim.target_legal_id)
            if src_key not in nodes:
                src_key = f"section:{sim.source_legal_id}"
            if tgt_key not in nodes:
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
                        "authority": NON_AUTHORITATIVE_AUTHORITY,
                        "config_cid": sim.config_cid,
                        "metric": sim.metric,
                    },
                )
            )

        unique_edges: dict[str, OpenUsLawGraphEdge] = {}
        for edge in edges:
            unique_edges[edge.edge_cid] = edge

        projection = OpenUsLawGraphProjection(
            nodes=tuple(nodes.values()),
            edges=tuple(unique_edges.values()),
            skipped_row_count=skipped,
        )
        projection.assert_semantics_disjoint()
        return projection

    def _project_structure(
        self,
        nodes: dict[str, OpenUsLawGraphNode],
        edges: list[OpenUsLawGraphEdge],
        row: GraphCorpusRow,
    ) -> None:
        jurisdiction_key = f"jurisdiction:{row.jurisdiction_code}"
        jurisdiction_label = JURISDICTION_NAMES.get(
            row.jurisdiction_code, row.jurisdiction_code
        )
        self._ensure_node(
            nodes,
            node_type=GraphNodeType.JURISDICTION,
            node_key=jurisdiction_key,
            label=jurisdiction_label,
            payload={
                "jurisdiction_code": row.jurisdiction_code,
                "jurisdiction_name": jurisdiction_label,
            },
        )

        code_key = f"code:{row.jurisdiction_code}:{row.code_family}"
        self._ensure_node(
            nodes,
            node_type=GraphNodeType.CODE,
            node_key=code_key,
            label=f"{row.jurisdiction_code} {row.code_family}",
            payload={
                "code_family": row.code_family,
                "jurisdiction_code": row.jurisdiction_code,
            },
        )
        edges.append(
            self._edge(GraphEdgeType.CONTAINS, nodes[jurisdiction_key], nodes[code_key])
        )

        parent_key = code_key
        if row.title:
            title_key = f"title:{row.jurisdiction_code}:{row.code_family}:{row.title}"
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.TITLE,
                node_key=title_key,
                label=f"Title {row.title}",
                payload={
                    "code_family": row.code_family,
                    "jurisdiction_code": row.jurisdiction_code,
                    "title": row.title,
                },
            )
            edges.append(
                self._edge(GraphEdgeType.CONTAINS, nodes[parent_key], nodes[title_key])
            )
            parent_key = title_key

        if row.chapter:
            chapter_key = (
                f"chapter:{row.jurisdiction_code}:{row.code_family}:"
                f"{row.title or '_'}:{row.chapter}"
            )
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.CHAPTER,
                node_key=chapter_key,
                label=f"Chapter {row.chapter}",
                payload={
                    "chapter": row.chapter,
                    "code_family": row.code_family,
                    "jurisdiction_code": row.jurisdiction_code,
                    "title": row.title,
                },
            )
            edges.append(
                self._edge(GraphEdgeType.CONTAINS, nodes[parent_key], nodes[chapter_key])
            )
            parent_key = chapter_key

        section_legal_id = strip_subsection_qualifier(row.legal_id)
        section_key = f"section:{section_legal_id}"
        self._ensure_node(
            nodes,
            node_type=GraphNodeType.SECTION,
            node_key=section_key,
            label=row.heading or section_legal_id,
            legal_id=section_legal_id,
            entry_cid=row.entry_cid if not row.subsection else None,
            payload={
                "chapter": row.chapter,
                "code_family": row.code_family,
                "configuration": row.configuration,
                "jurisdiction_code": row.jurisdiction_code,
                "section": row.section,
                "title": row.title,
            },
        )
        edges.append(
            self._edge(GraphEdgeType.CONTAINS, nodes[parent_key], nodes[section_key])
        )

        leaf_key = section_key
        if row.subsection:
            subsection_key = f"subsection:{row.legal_id}"
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.SUBSECTION,
                node_key=subsection_key,
                label=f"{row.heading or row.section}({row.subsection})",
                legal_id=row.legal_id,
                entry_cid=row.entry_cid,
                payload={
                    "chapter": row.chapter,
                    "code_family": row.code_family,
                    "configuration": row.configuration,
                    "jurisdiction_code": row.jurisdiction_code,
                    "section": row.section,
                    "subsection": row.subsection,
                    "title": row.title,
                },
            )
            edges.append(
                self._edge(
                    GraphEdgeType.CONTAINS, nodes[section_key], nodes[subsection_key]
                )
            )
            leaf_key = subsection_key

        if row.source_cid:
            source_key = f"source:{row.source_cid}"
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.SOURCE,
                node_key=source_key,
                label=row.official_source_url or row.source_cid,
                payload={
                    "official_source_url": row.official_source_url,
                    "source_cid": row.source_cid,
                },
            )
            edges.append(
                self._edge(GraphEdgeType.HAS_SOURCE, nodes[leaf_key], nodes[source_key])
            )

        edition_key = f"edition:{row.edition}"
        self._ensure_node(
            nodes,
            node_type=GraphNodeType.EDITION,
            node_key=edition_key,
            label=row.edition,
            payload={"edition": row.edition},
        )
        edges.append(
            self._edge(GraphEdgeType.HAS_EDITION, nodes[leaf_key], nodes[edition_key])
        )

        provenance_digest = content_sha256(
            canonical_json_dumps(
                {
                    "acquisition_receipt_cid": row.acquisition_receipt_cid,
                    "entry_cid": row.entry_cid,
                    "observed_at": row.observed_at,
                    "rights_receipt_cid": row.rights_receipt_cid,
                    "source_cid": row.source_cid,
                }
            )
        )
        provenance_key = f"provenance:{provenance_digest}"
        self._ensure_node(
            nodes,
            node_type=GraphNodeType.PROVENANCE,
            node_key=provenance_key,
            label=row.acquisition_receipt_cid or row.entry_cid,
            payload={
                "acquisition_receipt_cid": row.acquisition_receipt_cid,
                "entry_cid": row.entry_cid,
                "observed_at": row.observed_at,
                "rights_receipt_cid": row.rights_receipt_cid,
                "source_cid": row.source_cid,
            },
        )
        edges.append(
            self._edge(
                GraphEdgeType.HAS_PROVENANCE, nodes[leaf_key], nodes[provenance_key]
            )
        )

    def _project_citations(
        self,
        nodes: dict[str, OpenUsLawGraphNode],
        edges: list[OpenUsLawGraphEdge],
        row: GraphCorpusRow,
        *,
        known_legal_ids: set[str],
        locator_index: Mapping[tuple[str, str, str], Sequence[str]],
    ) -> None:
        leaf_key = (
            f"subsection:{row.legal_id}"
            if row.subsection
            else f"section:{strip_subsection_qualifier(row.legal_id)}"
        )
        source_node = nodes[leaf_key]
        citations = resolve_citations(
            row.text,
            known_legal_ids=known_legal_ids,
            locator_index=locator_index,
            source_cid=row.source_cid,
            entry_cid=row.entry_cid,
            default_jurisdiction=row.jurisdiction_code,
            default_code_family=row.code_family,
            host_legal_id=row.legal_id,
            host_section=row.section,
        )
        for citation in citations:
            if citation.mention.kind == "public_law":
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
                continue

            if (
                citation.resolution_status is ResolutionStatus.RESOLVED
                and citation.target_legal_id
            ):
                target_key = citation.target_node_key or _section_or_subsection_key(
                    citation.target_legal_id
                )
                if target_key not in nodes:
                    target_key = f"section:{citation.target_legal_id}"
                if target_key not in nodes:
                    continue
                citation_key = (
                    "citation:"
                    + content_sha256(
                        canonical_json_dumps(
                            {
                                "end": citation.span.end,
                                "mention": citation.mention.mention_text,
                                "source": row.legal_id,
                                "start": citation.span.start,
                                "target": citation.target_legal_id,
                            }
                        )
                    )[:32]
                )
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.CITATION,
                    node_key=citation_key,
                    label=citation.mention.mention_text,
                    payload={
                        "mention_text": citation.mention.mention_text,
                        "parser_version": citation.mention.parser_version,
                        "resolution_status": ResolutionStatus.RESOLVED.value,
                        "target_legal_id": citation.target_legal_id,
                    },
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.HAS_CITATION,
                        source_node,
                        nodes[citation_key],
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
            else:
                unresolved_key = citation.target_node_key or _unresolved_node_key(
                    citation.mention
                )
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.UNRESOLVED_CITATION,
                    node_key=unresolved_key,
                    label=citation.mention.mention_text,
                    payload={
                        "code_family": citation.mention.code_family,
                        "jurisdiction_code": citation.mention.jurisdiction_code,
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
                        resolution_status=citation.resolution_status
                        if citation.resolution_status
                        is not ResolutionStatus.RESOLVED
                        else ResolutionStatus.UNRESOLVED,
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                            "resolution_status": (
                                citation.resolution_status.value
                                if citation.resolution_status
                                else ResolutionStatus.UNRESOLVED.value
                            ),
                        },
                    )
                )

        for raw in row.cites:
            target = self._coerce_target_legal_id(raw, row=row)
            if not target or target == row.legal_id:
                continue
            target_key = _section_or_subsection_key(target)
            if target_key not in nodes:
                target_key = f"section:{target}"
            if target_key not in nodes:
                continue
            span = self._synthetic_field_span(row, field_name="cites", mention=str(raw))
            edges.append(
                self._edge(
                    GraphEdgeType.CITES,
                    source_node,
                    nodes[target_key],
                    source_span=span,
                    resolution_status=ResolutionStatus.RESOLVED,
                    payload={"origin": "explicit_field", "target": target},
                )
            )

        for pl_raw in row.public_laws:
            pl_id = self._normalize_public_law_id(pl_raw)
            pl_key = f"public_law:{pl_id}"
            self._ensure_node(
                nodes,
                node_type=GraphNodeType.PUBLIC_LAW,
                node_key=pl_key,
                label=str(pl_raw),
                payload={"public_law_id": pl_id},
            )
            span = self._synthetic_field_span(
                row, field_name="public_laws", mention=str(pl_raw)
            )
            edges.append(
                self._edge(
                    GraphEdgeType.CODIFIES,
                    nodes[pl_key],
                    source_node,
                    source_span=span,
                    payload={"origin": "explicit_field", "public_law_id": pl_id},
                )
            )

    def _project_amendments(
        self,
        nodes: dict[str, OpenUsLawGraphNode],
        edges: list[OpenUsLawGraphEdge],
        row: GraphCorpusRow,
    ) -> None:
        leaf_key = (
            f"subsection:{row.legal_id}"
            if row.subsection
            else f"section:{strip_subsection_qualifier(row.legal_id)}"
        )
        source_node = nodes[leaf_key]
        for target_raw, edge_type in (
            *((item, GraphEdgeType.AMENDS) for item in row.amends),
            *((item, GraphEdgeType.REPEALS) for item in row.repeals),
            *((item, GraphEdgeType.TRANSFERS) for item in row.transfers),
        ):
            target = self._coerce_target_legal_id(target_raw, row=row)
            if not target:
                continue
            target_key = _section_or_subsection_key(target)
            if target_key not in nodes:
                target_key = f"section:{target}"
            if target_key not in nodes:
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.SECTION,
                    node_key=target_key,
                    label=target,
                    legal_id=target,
                    payload={"placeholder": True, "target": target},
                )
            span = self._synthetic_field_span(
                row, field_name=edge_type.value.lower(), mention=str(target_raw)
            )
            if edge_type is GraphEdgeType.AMENDS:
                amendment_key = f"amendment:{row.legal_id}:{target}"
                self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.AMENDMENT,
                    node_key=amendment_key,
                    label=f"{row.legal_id} amends {target}",
                    payload={
                        "source_legal_id": row.legal_id,
                        "target_legal_id": target,
                    },
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.HAS_AMENDMENT,
                        source_node,
                        nodes[amendment_key],
                        source_span=span,
                        resolution_status=ResolutionStatus.RESOLVED,
                        payload={"origin": "explicit_field", "target": target},
                    )
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.AMENDS,
                        nodes[amendment_key],
                        nodes[target_key],
                        source_span=span,
                        resolution_status=ResolutionStatus.RESOLVED,
                        payload={"origin": "explicit_field", "target": target},
                    )
                )
            edges.append(
                self._edge(
                    edge_type,
                    source_node,
                    nodes[target_key],
                    source_span=span,
                    resolution_status=ResolutionStatus.RESOLVED,
                    payload={"origin": "explicit_field", "target": target},
                )
            )

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
        raise GraphProjectionError(
            "similarity neighbor must be mapping or SimilarityNeighbor"
        )

    def _ensure_node(
        self,
        nodes: dict[str, OpenUsLawGraphNode],
        *,
        node_type: GraphNodeType,
        node_key: str,
        label: str,
        legal_id: Optional[str] = None,
        entry_cid: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> OpenUsLawGraphNode:
        existing = nodes.get(node_key)
        if existing is not None:
            return existing
        node = OpenUsLawGraphNode(
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
        source: OpenUsLawGraphNode,
        target: OpenUsLawGraphNode,
        *,
        source_span: Optional[SourceSpan] = None,
        resolution_status: Optional[ResolutionStatus] = None,
        weight: Optional[float] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> OpenUsLawGraphEdge:
        edge_class = self.ontology.validate_edge(
            edge_type,
            source.node_type,
            target.node_type,
        )
        return OpenUsLawGraphEdge(
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

    def _coerce_target_legal_id(self, value: str, *, row: GraphCorpusRow) -> Optional[str]:
        text = str(value).strip()
        if not text:
            return None
        if text.startswith(f"{LEGAL_ID_PREFIX}:"):
            return text
        mentions = extract_citation_mentions(
            text,
            default_jurisdiction=row.jurisdiction_code,
            default_code_family=row.code_family,
        )
        if mentions:
            mention = mentions[0]
            if mention.jurisdiction_code and mention.code_family and mention.section:
                try:
                    return build_legal_id(
                        document_kind=row.document_kind,
                        jurisdiction_code=mention.jurisdiction_code,
                        code_family=mention.code_family,
                        hierarchy={"section": mention.section, "title": mention.title},
                        edition=row.edition,
                    )
                except Exception:
                    return None
        return None

    @staticmethod
    def _synthetic_field_span(
        row: GraphCorpusRow,
        *,
        field_name: str,
        mention: str,
    ) -> SourceSpan:
        if mention and mention in row.text:
            return SourceSpan.from_occurrence(
                row.text,
                mention,
                source_cid=row.source_cid,
                entry_cid=row.entry_cid,
                field="text",
            )
        virtual = mention
        return SourceSpan(
            start=0,
            end=len(virtual),
            text=virtual,
            source_cid=row.source_cid,
            entry_cid=row.entry_cid,
            field=field_name,
        )


def project_open_us_law_graph(
    rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
    *,
    similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
) -> OpenUsLawGraphProjection:
    """Project corpus rows into a deterministic multi-jurisdiction legal graph."""

    return OpenUsLawGraphProjector().project(
        rows, similarity_neighbors=similarity_neighbors
    )


# ---------------------------------------------------------------------------
# Sealed fixture recipe
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def _fixture_legal_id(
    *,
    jurisdiction_code: str,
    code_family: str,
    hierarchy: Mapping[str, Any],
    edition: str = "2024-official",
    document_kind: str = DocumentKind.STATUTE.value,
    subsection: Optional[str] = None,
) -> str:
    return build_legal_id(
        document_kind=document_kind,
        jurisdiction_code=jurisdiction_code,
        code_family=code_family,
        hierarchy=hierarchy,
        edition=edition,
        subsection=subsection,
    )


def fixture_seed_records() -> list[dict[str, Any]]:
    """Compact multi-jurisdiction recipe used by tests and the receipt."""

    or_311 = _fixture_legal_id(
        jurisdiction_code="OR",
        code_family="ors",
        hierarchy={"title": "192", "section": "192.311"},
    )
    or_314 = _fixture_legal_id(
        jurisdiction_code="OR",
        code_family="ors",
        hierarchy={"title": "192", "section": "192.314"},
    )
    ca_187 = _fixture_legal_id(
        jurisdiction_code="CA",
        code_family="penal-code",
        hierarchy={"section": "187"},
    )
    ca_188 = _fixture_legal_id(
        jurisdiction_code="CA",
        code_family="penal-code",
        hierarchy={"section": "188"},
    )
    ny_125 = _fixture_legal_id(
        jurisdiction_code="NY",
        code_family="penal-law",
        hierarchy={"section": "125.25", "subsection": "a"},
        subsection="a",
    )
    wa_030 = _fixture_legal_id(
        jurisdiction_code="WA",
        code_family="rcw",
        hierarchy={"title": "42", "chapter": "56", "section": "42.56.030"},
    )
    wa_070 = _fixture_legal_id(
        jurisdiction_code="WA",
        code_family="rcw",
        hierarchy={"title": "42", "chapter": "56", "section": "42.56.070"},
    )
    dc_531 = _fixture_legal_id(
        jurisdiction_code="DC",
        code_family="code",
        hierarchy={"title": "2", "section": "2-531"},
    )
    dc_532 = _fixture_legal_id(
        jurisdiction_code="DC",
        code_family="code",
        hierarchy={"title": "2", "section": "2-532"},
    )

    return [
        {
            "acquisition_receipt_cid": _cid("1"),
            "amends": [],
            "code_family": "ors",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("a"),
            "heading": "Definitions for public records law",
            "hierarchy": {"title": "192", "section": "192.311"},
            "jurisdiction_code": "OR",
            "legal_id": or_311,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors192.html",
            "public_laws": ["Pub. L. 112-29"],
            "rights_receipt_cid": _cid("2"),
            "source_cid": _cid("b"),
            "text": (
                "As used in ORS 192.311 to 192.431, public record has the "
                "meaning given. Inspection rights appear in ORS 192.314. "
                "Compare Cal. Penal Code § 187. A fictional crosswalk is "
                "ORS 99.9999. Codified from Pub. L. 112-29."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("3"),
            "code_family": "ors",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("c"),
            "heading": "Right to inspect public records",
            "hierarchy": {"title": "192", "section": "192.314"},
            "jurisdiction_code": "OR",
            "legal_id": or_314,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors192.html",
            "rights_receipt_cid": _cid("4"),
            "source_cid": _cid("d"),
            "text": (
                "Every person has a right to inspect any public record of a "
                "public body in this state. Definitions appear in ORS 192.311."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("5"),
            "code_family": "penal-code",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("e"),
            "heading": "Murder defined",
            "hierarchy": {"section": "187"},
            "jurisdiction_code": "CA",
            "legal_id": ca_187,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml",
            "rights_receipt_cid": _cid("6"),
            "source_cid": _cid("f"),
            "text": (
                "Murder is the unlawful killing of a human being, or a fetus, "
                "with malice aforethought. Malice is defined in Cal. Penal "
                "Code § 188."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("7"),
            "amends": [ca_187],
            "code_family": "penal-code",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("1"),
            "heading": "Malice defined",
            "hierarchy": {"section": "188"},
            "jurisdiction_code": "CA",
            "legal_id": ca_188,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml",
            "rights_receipt_cid": _cid("8"),
            "source_cid": _cid("2"),
            "text": "Malice may be express or implied. This section amends Cal. Penal Code § 187.",
        },
        {
            "acquisition_receipt_cid": _cid("9"),
            "code_family": "penal-law",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("3"),
            "heading": "Murder in the second degree",
            "hierarchy": {"section": "125.25", "subsection": "a"},
            "jurisdiction_code": "NY",
            "legal_id": ny_125,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://www.nysenate.gov/legislation/laws/PEN/125.25",
            "rights_receipt_cid": _cid("a"),
            "source_cid": _cid("4"),
            "text": (
                "A person is guilty of murder in the second degree when: "
                "(a) With intent to cause the death of another person, he "
                "causes the death of such person."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("b"),
            "code_family": "rcw",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("5"),
            "heading": "Construction of public records act",
            "hierarchy": {"title": "42", "chapter": "56", "section": "42.56.030"},
            "jurisdiction_code": "WA",
            "legal_id": wa_030,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://app.leg.wa.gov/RCW/default.aspx?cite=42.56.030",
            "rights_receipt_cid": _cid("c"),
            "source_cid": _cid("6"),
            "text": (
                "The people of this state do not yield their sovereignty to "
                "the agencies that serve them. Documents are produced under "
                "RCW 42.56.070."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("d"),
            "code_family": "rcw",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("7"),
            "heading": "Documents and indexes to be made public",
            "hierarchy": {"title": "42", "chapter": "56", "section": "42.56.070"},
            "jurisdiction_code": "WA",
            "legal_id": wa_070,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://app.leg.wa.gov/RCW/default.aspx?cite=42.56.070",
            "rights_receipt_cid": _cid("e"),
            "source_cid": _cid("8"),
            "text": (
                "Each agency shall make available for public inspection and "
                "copying all public records. Construction is governed by "
                "RCW 42.56.030."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("f"),
            "code_family": "code",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("9"),
            "heading": "Public policy of the District",
            "hierarchy": {"title": "2", "section": "2-531"},
            "jurisdiction_code": "DC",
            "legal_id": dc_531,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://code.dccouncil.gov/us/dc/council/code/sections/2-531",
            "rights_receipt_cid": _cid("0"),
            "source_cid": _cid("a"),
            "text": (
                "The public policy of the District of Columbia is that all "
                "persons are entitled to full and complete information. See "
                "D.C. Code § 2-532."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("b"),
            "code_family": "code",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("c"),
            "heading": "Right of access to public records",
            "hierarchy": {"title": "2", "section": "2-532"},
            "jurisdiction_code": "DC",
            "legal_id": dc_532,
            "observed_at": "2026-04-01T00:00:00Z",
            "official_source_url": "https://code.dccouncil.gov/us/dc/council/code/sections/2-532",
            "rights_receipt_cid": _cid("d"),
            "source_cid": _cid("e"),
            "text": (
                "Any person has a right to inspect, and at that person's "
                "expense copy, any public record of a public body. Policy is "
                "stated in D.C. Code § 2-531."
            ),
        },
        {
            "acquisition_receipt_cid": _cid("0"),
            "code_family": "recovery",
            "configuration": ReleaseConfiguration.RECOVERY.value,
            "document_kind": DocumentKind.STATUTE.value,
            "edition": "2024-official",
            "entry_cid": _cid("f"),
            "heading": "Recovery-only row excluded from graph counts",
            "hierarchy": {"section": "recovery-1"},
            "jurisdiction_code": "OR",
            "legal_id": _fixture_legal_id(
                jurisdiction_code="OR",
                code_family="recovery",
                hierarchy={"section": "recovery-1"},
            ),
            "observed_at": "2026-04-01T00:00:00Z",
            "rights_receipt_cid": _cid("1"),
            "source_cid": _cid("2"),
            "text": "This recovery row must not increment graph family counts.",
        },
    ]


def fixture_similarity_neighbors() -> list[dict[str, Any]]:
    or_row = next(
        item
        for item in fixture_seed_records()
        if item["jurisdiction_code"] == "OR" and item["hierarchy"]["section"] == "192.311"
    )
    wa_row = next(
        item
        for item in fixture_seed_records()
        if item["jurisdiction_code"] == "WA" and item["hierarchy"]["section"] == "42.56.030"
    )
    return [
        {
            "config_cid": _cid("9"),
            "edge_type": GraphEdgeType.BM25_NEIGHBOR_OF.value,
            "metric": "bm25",
            "score": 11.25,
            "source_legal_id": or_row["legal_id"],
            "target_legal_id": wa_row["legal_id"],
        },
        {
            "config_cid": _cid("8"),
            "edge_type": GraphEdgeType.EMBEDDING_NEIGHBOR_OF.value,
            "metric": "gte-small-cosine",
            "score": 0.81,
            "source_legal_id": or_row["legal_id"],
            "target_legal_id": wa_row["legal_id"],
        },
    ]


def fixture_expected_paths() -> list[dict[str, Any]]:
    records = fixture_seed_records()
    or_311 = next(
        item for item in records if item["hierarchy"].get("section") == "192.311"
    )
    or_314 = next(
        item for item in records if item["hierarchy"].get("section") == "192.314"
    )
    ca_187 = next(item for item in records if item["hierarchy"].get("section") == "187")
    ca_188 = next(item for item in records if item["hierarchy"].get("section") == "188")
    wa_030 = next(
        item for item in records if item["hierarchy"].get("section") == "42.56.030"
    )
    wa_070 = next(
        item for item in records if item["hierarchy"].get("section") == "42.56.070"
    )
    dc_531 = next(
        item for item in records if item["hierarchy"].get("section") == "2-531"
    )
    dc_532 = next(
        item for item in records if item["hierarchy"].get("section") == "2-532"
    )
    return [
        {
            "edge_types": ["CONTAINS"],
            "path_id": "jurisdiction-contains-code",
            "source_key": "jurisdiction:OR",
            "target_key": "code:OR:ors",
        },
        {
            "edge_types": ["CONTAINS", "CONTAINS"],
            "path_id": "code-contains-title-contains-section",
            "source_key": "code:OR:ors",
            "target_key": f"section:{or_311['legal_id']}",
        },
        {
            "edge_types": ["CONTAINS", "CONTAINS"],
            "path_id": "title-contains-chapter-contains-section",
            "source_key": "title:WA:rcw:42",
            "target_key": f"section:{wa_030['legal_id']}",
        },
        {
            "edge_types": ["CITES"],
            "path_id": "oregon-cites-oregon",
            "source_key": f"section:{or_311['legal_id']}",
            "target_key": f"section:{or_314['legal_id']}",
        },
        {
            "edge_types": ["CITES"],
            "path_id": "oregon-cites-california",
            "source_key": f"section:{or_311['legal_id']}",
            "target_key": f"section:{ca_187['legal_id']}",
        },
        {
            "edge_types": ["CITES"],
            "path_id": "washington-cites-washington",
            "source_key": f"section:{wa_030['legal_id']}",
            "target_key": f"section:{wa_070['legal_id']}",
        },
        {
            "edge_types": ["CITES"],
            "path_id": "dc-cites-dc",
            "source_key": f"section:{dc_531['legal_id']}",
            "target_key": f"section:{dc_532['legal_id']}",
        },
        {
            "edge_types": ["AMENDS"],
            "path_id": "california-amends-california",
            "source_key": f"section:{ca_188['legal_id']}",
            "target_key": f"section:{ca_187['legal_id']}",
        },
        {
            "edge_types": ["HAS_SOURCE"],
            "path_id": "oregon-has-source",
            "source_key": f"section:{or_311['legal_id']}",
            "target_key": f"source:{or_311['source_cid']}",
        },
        {
            "edge_types": ["HAS_EDITION"],
            "path_id": "oregon-has-edition",
            "source_key": f"section:{or_311['legal_id']}",
            "target_key": "edition:2024-official",
        },
        {
            "edge_types": ["CODIFIES"],
            "path_id": "public-law-codifies-oregon",
            "source_key": "public_law:pl:us:112:29",
            "target_key": f"section:{or_311['legal_id']}",
        },
    ]


def build_default_graph_expected_fixture_payload() -> dict[str, Any]:
    """Compact sealed expected-path recipe (no bulk node/edge dumps)."""

    records = fixture_seed_records()
    neighbors = fixture_similarity_neighbors()
    projection = project_open_us_law_graph(records, similarity_neighbors=neighbors)
    expected_paths = fixture_expected_paths()
    matches = match_expected_paths(projection, expected_paths)
    unmatched = [item for item in matches if not item["matched"]]
    if unmatched:
        raise GraphFixtureError(
            f"default fixture paths do not match projection: {unmatched!r}"
        )
    missing = projection.missing_coverage_node_types()
    if missing:
        raise GraphFixtureError(f"fixture projection missing coverage types: {missing}")

    return {
        "acceptance": {
            "fixture_graph_paths_match": True,
            "legal_and_similarity_semantics_disjoint": True,
            "required_coverage_node_types_present": True,
            "source_spans_are_bound": True,
            "unresolved_citations_preserved_honestly": True,
        },
        "citation_parser_version": CITATION_PARSER_VERSION,
        "description": (
            "Compact multi-jurisdiction legal graph expected-path recipe for "
            "OUL-030. Cases exercise jurisdiction/code/title/chapter/section/"
            "subsection structure, citation, amendment, source, edition, and "
            "provenance. Similarity edges are present but non-authoritative."
        ),
        "expected_paths": expected_paths,
        "goal_id": GOAL_ID,
        "notes": (
            "Recipe form: seed records + expected path predicates. Full graph "
            "is projected deterministically by project_open_us_law_graph."
        ),
        "ontology_version": ONTOLOGY_VERSION,
        "producer": PRODUCER,
        "projection_expectations": {
            "legal_edge_count_min": 20,
            "min_jurisdictions": 4,
            "min_nodes": 24,
            "similarity_edge_count": 2,
            "skipped_row_count": 1,
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
            "sample_mention_substring": "ORS 99.9999",
        },
    }


def run_fixture_case(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project the sealed recipe and verify acceptance predicates."""

    data = (
        dict(payload)
        if payload is not None
        else build_default_graph_expected_fixture_payload()
    )
    records = list(data.get("records") or [])
    neighbors = list(data.get("similarity_neighbors") or [])
    expected_paths = list(data.get("expected_paths") or [])
    projection = project_open_us_law_graph(records, similarity_neighbors=neighbors)
    projection.assert_semantics_disjoint()

    span_errors: list[str] = []
    for edge in projection.edges:
        if edge.edge_type in SPAN_REQUIRED_EDGE_TYPES:
            if edge.source_span is None:
                span_errors.append(f"{edge.edge_cid}: missing span")
            elif edge.source_span.end < edge.source_span.start:
                span_errors.append(f"{edge.edge_cid}: inverted span")

    unresolved_edges = [
        item for item in projection.edges if item.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    unresolved_nodes = [
        item
        for item in projection.nodes
        if item.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    unresolved_ok = bool(unresolved_edges) and bool(unresolved_nodes)
    for node in unresolved_nodes:
        if node.payload.get("resolution_status") != ResolutionStatus.UNRESOLVED.value:
            unresolved_ok = False
        if node.legal_id is not None:
            unresolved_ok = False
        if not node.payload.get("mention_text"):
            unresolved_ok = False
        if not node.payload.get("parser_version"):
            unresolved_ok = False
    for edge in unresolved_edges:
        if edge.resolution_status not in {
            ResolutionStatus.UNRESOLVED,
            ResolutionStatus.AMBIGUOUS,
        }:
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
    if "similarity_edge_count" in expectations:
        if projection.similarity_edge_count != int(expectations["similarity_edge_count"]):
            counts_ok = False
    if projection.unresolved_count < int(expectations.get("unresolved_count_min") or 0):
        counts_ok = False
    if "skipped_row_count" in expectations:
        if projection.skipped_row_count != int(expectations["skipped_row_count"]):
            counts_ok = False
    jurisdictions = {
        item.payload.get("jurisdiction_code")
        for item in projection.nodes
        if item.node_type is GraphNodeType.JURISDICTION
    }
    if len(jurisdictions) < int(expectations.get("min_jurisdictions") or 0):
        counts_ok = False

    legal_path_edge_types = {
        edge_type
        for path in find_graph_paths(projection, legal_only=True)
        for edge_type in path.edge_types
    }
    similarity_leaked = bool(
        legal_path_edge_types & {item.value for item in SIMILARITY_EDGE_TYPES}
    )
    coverage_ok = not projection.missing_coverage_node_types()

    ok = (
        paths_ok
        and unresolved_ok
        and not span_errors
        and counts_ok
        and not similarity_leaked
        and coverage_ok
    )
    return {
        "coverage_ok": coverage_ok,
        "graph_cid": projection.graph_cid,
        "legal_edge_count": projection.legal_edge_count,
        "missing_coverage_node_types": projection.missing_coverage_node_types(),
        "node_count": len(projection.nodes),
        "ok": ok,
        "path_matches": path_matches,
        "similarity_edge_count": projection.similarity_edge_count,
        "similarity_leaked_into_legal_paths": similarity_leaked,
        "skipped_row_count": projection.skipped_row_count,
        "span_errors": span_errors,
        "unresolved_count": projection.unresolved_count,
        "unresolved_ok": unresolved_ok,
    }


def bind_fixture_graph() -> OpenUsLawGraphProjection:
    payload = build_default_graph_expected_fixture_payload()
    return project_open_us_law_graph(
        payload["records"],
        similarity_neighbors=payload["similarity_neighbors"],
    )


# ---------------------------------------------------------------------------
# Software-contract receipt
# ---------------------------------------------------------------------------


def _acceptance_block() -> dict[str, bool]:
    return {
        "deterministic_nodes_and_edges_cover_required_types": True,
        "embedding_or_lexical_similarity_not_legal_authority": True,
        "unresolved_citations_preserved": True,
    }


def build_legal_graph_receipt(
    projection: OpenUsLawGraphProjection | None = None,
) -> dict[str, Any]:
    """Build the sealed software-contract legal-graph receipt."""

    demo = projection if projection is not None else bind_fixture_graph()
    demo.assert_semantics_disjoint()
    node_types = sorted(demo.coverage_node_types())
    jurisdictions = sorted(
        {
            str(item.payload.get("jurisdiction_code"))
            for item in demo.nodes
            if item.node_type is GraphNodeType.JURISDICTION
            and item.payload.get("jurisdiction_code")
        }
    )
    similarity_edges = demo.similarity_edges()
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_graph_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "coverage_node_types_present": not demo.missing_coverage_node_types(),
            "demo_edge_count": len(demo.edges),
            "demo_jurisdiction_count": len(jurisdictions),
            "demo_legal_edge_count": demo.legal_edge_count,
            "demo_node_count": len(demo.nodes),
            "demo_similarity_edge_count": demo.similarity_edge_count,
            "demo_skipped_row_count": demo.skipped_row_count,
            "demo_unresolved_count": demo.unresolved_count,
            "deterministic_cid_sort": True,
            "exact_51_allowlist_size": len(EXACT_51_JURISDICTION_CODES),
            "legal_and_similarity_disjoint": True,
            "nodes_and_edges_cid_sorted": True,
            "recovery_and_quarantine_excluded_from_graph_counts": demo.skipped_row_count >= 1,
            "required_coverage_node_types": list(REQUIRED_COVERAGE_NODE_TYPES),
            "similarity_edges_non_authoritative": all(
                item.payload.get("authority") == NON_AUTHORITATIVE_AUTHORITY
                and item.edge_class is GraphEdgeClass.SIMILARITY
                for item in similarity_edges
            ),
            "similarity_leaked_into_legal_paths": False,
            "unresolved_citations_have_no_invented_legal_id": all(
                item.legal_id is None
                for item in demo.nodes
                if item.node_type is GraphNodeType.UNRESOLVED_CITATION
            ),
        },
        "citation_parser_version": CITATION_PARSER_VERSION,
        "demo": {
            "authorizing_for_release": False,
            "edge_count": len(demo.edges),
            "graph_cid": demo.graph_cid,
            "jurisdiction_codes": jurisdictions,
            "legal_edge_count": demo.legal_edge_count,
            "node_count": len(demo.nodes),
            "node_types": node_types,
            "similarity_edge_count": demo.similarity_edge_count,
            "skipped_row_count": demo.skipped_row_count,
            "unresolved_count": demo.unresolved_count,
        },
        "description": (
            "Software-contract receipt for OUL-030. Deterministic nodes and "
            "edges cover jurisdiction, code, title, chapter, section, "
            "subsection, citation, amendment, source, edition, and "
            "provenance. Unresolved citations are preserved. Embedding and "
            "lexical similarity are never represented as legal authority. "
            "This receipt does not claim the live exact-51 corpus has been "
            "graphed."
        ),
        "exact_51_seed_row_lower_bound": EXACT_51_SEED_ROW_LOWER_BOUND,
        "goal_id": GOAL_ID,
        "ontology": GRAPH_ONTOLOGY.to_dict(),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "multi_jurisdiction_legal_provenance_graph",
            "owner_task": TASK_ID,
            "required": [
                "Emit deterministic CID-sorted nodes and edges for jurisdiction, code, title, chapter, section, subsection, citation, amendment, source, edition, and provenance.",
                "Preserve unresolved citations as typed nodes and edges with source text and parser version; never invent a target legal_id.",
                "Keep embedding neighbors, BM25 neighbors, and lexical similarity disjoint from legal authority.",
                "Exclude recovery and quarantine rows from graph family counts.",
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


def write_legal_graph_receipt(path: PathLike | None = None) -> Path:
    target = Path(path) if path is not None else default_legal_graph_receipt_path()
    payload = build_legal_graph_receipt()
    write_json_atomic(target, payload)
    return target


def load_legal_graph_receipt(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_legal_graph_receipt_path()
    if not target.is_file():
        raise GraphReceiptError(f"legal graph receipt not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise GraphReceiptError("legal graph receipt root must be an object")
    return dict(payload)


def assert_legal_graph_receipt(payload: Mapping[str, Any]) -> None:
    """Fail closed if the receipt would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise GraphReceiptError(f"receipt task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise GraphReceiptError(
            f"receipt schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("authorizing_for_release") is True:
        raise GraphReleaseAuthorizationError("legal graph receipt cannot authorize release")
    if payload.get("authorizing_for_publication") is True:
        raise GraphReleaseAuthorizationError(
            "legal graph receipt cannot authorize publication"
        )
    if payload.get("proves_software_contract_only") is not True:
        raise GraphReceiptError("receipt must prove the software contract only")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise GraphReceiptError("receipt acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) is not expected:
            raise GraphReceiptError(f"receipt acceptance.{key} must be {expected}")
    checks = payload.get("checks") or {}
    if not isinstance(checks, Mapping):
        raise GraphReceiptError("receipt checks must be a mapping")
    if checks.get("legal_and_similarity_disjoint") is not True:
        raise GraphReceiptError("receipt must keep legal and similarity disjoint")
    if checks.get("similarity_edges_non_authoritative") is not True:
        raise GraphReceiptError("receipt must label similarity as non-authoritative")
    if checks.get("similarity_leaked_into_legal_paths") is True:
        raise LegalSimilarityCollisionError(
            "receipt reports similarity leaked into legal paths"
        )
    if checks.get("unresolved_citations_have_no_invented_legal_id") is not True:
        raise GraphReceiptError("receipt must preserve unresolved citations honestly")
    required = checks.get("required_coverage_node_types") or []
    if list(required) != list(REQUIRED_COVERAGE_NODE_TYPES):
        raise GraphReceiptError("receipt required coverage node types drifted")
    if checks.get("coverage_node_types_present") is not True:
        raise GraphReceiptError("receipt is missing required coverage node types")
    expected_digest = content_sha256(
        canonical_json_dumps(
            {key: value for key, value in dict(payload).items() if key != "receipt_sha256"}
        )
    )
    if payload.get("receipt_sha256") != expected_digest:
        raise GraphReceiptError("receipt_sha256 does not match canonical payload")


__all__ = [
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "CITATION_PARSER_VERSION",
    "DEFAULT_EDGE_CLASS",
    "DEFAULT_REPORT_PATH",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "GRAPH_ONTOLOGY",
    "LEGAL_EDGE_TYPES",
    "NON_AUTHORITATIVE_AUTHORITY",
    "ONTOLOGY_VERSION",
    "PRODUCER",
    "PROGRAM_ID",
    "RECEIPT_SCHEMA_VERSION",
    "REPORT_RELATIVE_PATH",
    "REQUIRED_COVERAGE_NODE_TYPES",
    "SCHEMA_VERSION",
    "SIMILARITY_EDGE_TYPES",
    "SPAN_REQUIRED_EDGE_TYPES",
    "TASK_ID",
    "CitationMention",
    "CitationResolutionError",
    "GraphCorpusRow",
    "GraphEdgeClass",
    "GraphEdgeType",
    "GraphFixtureError",
    "GraphNodeType",
    "GraphOntology",
    "GraphOntologyError",
    "GraphPath",
    "GraphProjectionError",
    "GraphReceiptError",
    "GraphReleaseAuthorizationError",
    "LegalSimilarityCollisionError",
    "OpenUsLawGraphEdge",
    "OpenUsLawGraphError",
    "OpenUsLawGraphNode",
    "OpenUsLawGraphProjection",
    "OpenUsLawGraphProjector",
    "ResolutionStatus",
    "ResolvedCitation",
    "SimilarityNeighbor",
    "SourceSpan",
    "SourceSpanError",
    "assert_legal_graph_receipt",
    "assert_legal_similarity_disjoint",
    "bind_fixture_graph",
    "build_default_graph_expected_fixture_payload",
    "build_legal_graph_receipt",
    "default_legal_graph_receipt_path",
    "extract_citation_mentions",
    "find_graph_paths",
    "fixture_expected_paths",
    "fixture_seed_records",
    "fixture_similarity_neighbors",
    "load_legal_graph_receipt",
    "lookup_citation_locator",
    "match_expected_paths",
    "production_graph_bounds",
    "project_open_us_law_graph",
    "resolve_citations",
    "run_fixture_case",
    "sha256_cid",
    "software_contract_flags",
    "strip_subsection_qualifier",
    "write_legal_graph_receipt",
]
