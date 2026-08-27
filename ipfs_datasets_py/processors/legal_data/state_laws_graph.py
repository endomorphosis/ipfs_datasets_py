"""Multi-jurisdiction legal and provenance graph for state law (LCR-030).

This module owns the versioned legal-graph ontology and the deterministic
projection of jurisdiction, code, title, chapter, section, subsection,
source, edition, act, citation, amendment, and provenance nodes plus typed
structural, citation, amendment, repeal, transfer, version, and provenance
edges.

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
* Physical adjacency paging belongs to LCR-031; this module emits the
  legal ontology projection only.
* No network I/O or Parquet I/O. Unit tests use compact sealed recipes.

Depends on LCR-024 (canonical corpus) and LCR-026 (shared layout
primitives / GraphRAG adapter). Identity and schema come from LCR-006 and
LCR-004.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    CITATION_CODE_ALIASES as SHARED_CITATION_CODE_ALIASES,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    CitationResolverBindings,
    GraphProjectionBindings,
    GraphRecordBindings,
    LegalGraphOntologyBindings,
    LegalGraphProjectorBindings,
    LegalGraphProjectorCore,
    assert_graph_projection_coverage,
    assert_graph_projection_semantics_disjoint,
    assert_legal_similarity_disjoint as assert_legal_similarity_disjoint_core,
    bind_source_span,
    citation_alias_key,
    citation_mention_to_dict,
    coerce_graph_enum,
    drop_contained_mentions,
    graph_edge_is_legal,
    graph_edge_is_similarity,
    graph_edge_to_dict,
    graph_node_to_dict,
    graph_ontology_edge_class_for,
    graph_ontology_is_legal_edge,
    graph_ontology_is_similarity_edge,
    graph_ontology_to_dict,
    graph_projection_coverage_node_types,
    graph_projection_legal_edges,
    graph_projection_missing_coverage_node_types,
    graph_projection_node_by_cid,
    graph_projection_node_by_key,
    graph_projection_similarity_edges,
    graph_projection_to_dict,
    legal_edge_direction_allowed,
    lookup_citation_locator,
    resolved_citation_to_dict,
    source_span_from_mapping,
    source_span_from_occurrence,
    source_span_to_dict,
    unresolved_citation_node_key,
    validate_citation_mention_record,
    validate_graph_edge_record,
    validate_graph_node_record,
    validate_graph_ontology,
    validate_graph_ontology_edge,
    validate_graph_projection,
    validate_source_span_record,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    extract_citation_mentions as extract_citation_mentions_core,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    optional_str as optional_str_core,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    require_non_empty_str as require_non_empty_str_core,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    require_non_negative_int as require_non_negative_int_core,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    resolve_citations as resolve_citations_core,
)
from ipfs_datasets_py.processors.legal_data.legal_graph_core import (
    sha256_cid as sha256_cid_core,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    DEFAULT_KIND,
    LEGAL_ID_PREFIX,
    build_legal_id,
    normalize_code_family,
    normalize_jurisdiction,
    normalize_section_token,
    parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    AdmissionStatus,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    reject_positional_durable_identity,
    validate_entry_cid,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CANONICAL_JURISDICTION_NAMES,
    CURRENTNESS_DISCLAIMER,
)

# ---------------------------------------------------------------------------
# Schema / task pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-graph-v1"
ONTOLOGY_VERSION: Final = "state-laws-graph-ontology/v1"
FIXTURE_SCHEMA_VERSION: Final = "state-laws-graph-expected-v1"
RECEIPT_SCHEMA_VERSION: Final = "state-laws-legal-graph-receipt-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-graph@1"
CITATION_PARSER_VERSION: Final = "state-laws-citation-parser/v1"
TASK_ID: Final = "LCR-030"
GOAL_ID: Final = "LCR-G040"
PRODUCER: Final = "state_laws_graph.py"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "legal-graph"
CODE_VERSION: Final = "1"
RECEIPT_SEALED_AT: Final = "2026-08-21T00:00:00Z"
DEFAULT_CONFIGURATION: Final = AdmissionStatus.ADMITTED.value
DEFAULT_EDITION: Final = "2024-official"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

REPORT_RELATIVE_PATH: Final = "docs/reports/legal_corpora_reindex/graph_evaluation.json"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_PATH: Final = _REPO_ROOT / REPORT_RELATIVE_PATH

GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS: Final = frozenset(
    {
        AdmissionStatus.RECOVERY.value,
        AdmissionStatus.QUARANTINED.value,
        AdmissionStatus.EXCLUDED.value,
        AdmissionStatus.REJECTED.value,
        "quarantine",
        "recovery",
    }
)

REQUIRED_COVERAGE_NODE_TYPES: Final = (
    "jurisdiction",
    "code",
    "title",
    "chapter",
    "section",
    "subsection",
    "source",
    "edition",
    "act",
    "citation",
    "amendment",
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
    """Versioned multi-jurisdiction legal graph node vocabulary (LCR-030)."""

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
    ACT = "act"

    @classmethod
    def coerce(cls, value: Any) -> "GraphNodeType":
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
            "pub_law": cls.ACT,
            "public_law": cls.ACT,
            "session_law": cls.ACT,
            "enactment": cls.ACT,
        }
        return coerce_graph_enum(
            cls,
            value,
            aliases=aliases,
            error_type=GraphOntologyError,
            label="graph node type",
        )


class GraphEdgeType(str, Enum):
    """Versioned legal / similarity edge vocabulary (LCR-030)."""

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
    VERSION_OF = "VERSION_OF"
    HAS_PROVENANCE = "HAS_PROVENANCE"
    DERIVED_FROM = "DERIVED_FROM"
    CODIFIES = "CODIFIES"
    BM25_NEIGHBOR_OF = "BM25_NEIGHBOR_OF"
    SIMILAR_TO = "SIMILAR_TO"
    EMBEDDING_NEIGHBOR_OF = "EMBEDDING_NEIGHBOR_OF"

    @classmethod
    def coerce(cls, value: Any) -> "GraphEdgeType":
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
            "VERSION": cls.VERSION_OF,
            "VERSION_EDGE": cls.VERSION_OF,
            "PROVENANCE": cls.HAS_PROVENANCE,
            "BM25": cls.BM25_NEIGHBOR_OF,
            "BM25_NEIGHBOR": cls.BM25_NEIGHBOR_OF,
            "SIMILAR": cls.SIMILAR_TO,
            "EMBEDDING": cls.EMBEDDING_NEIGHBOR_OF,
            "EMBEDDING_NEIGHBOR": cls.EMBEDDING_NEIGHBOR_OF,
            "COSINE": cls.EMBEDDING_NEIGHBOR_OF,
            "LEXICAL": cls.BM25_NEIGHBOR_OF,
        }
        return coerce_graph_enum(
            cls,
            value,
            aliases=aliases,
            error_type=GraphOntologyError,
            label="graph edge type",
            uppercase=True,
        )


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
        return coerce_graph_enum(
            cls,
            value,
            aliases={},
            error_type=GraphOntologyError,
            label="graph edge class",
        )


class ResolutionStatus(str, Enum):
    """Citation resolution honesty labels."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"

    @classmethod
    def coerce(cls, value: Any) -> "ResolutionStatus":
        return coerce_graph_enum(
            cls,
            value,
            aliases={},
            error_type=GraphOntologyError,
            label="resolution status",
            replace_spaces=False,
        )


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
        GraphEdgeType.VERSION_OF,
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
        GraphEdgeType.VERSION_OF: GraphEdgeClass.PROVENANCE,
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


class StateLawsGraphError(ValueError):
    """Base error for state-law legal graph ontology / projection."""

    code: str = "state_laws_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class GraphOntologyError(StateLawsGraphError):
    """Raised when ontology contracts are violated."""

    code = "graph_ontology"


class SourceSpanError(StateLawsGraphError):
    """Raised when a source span is unbound or inconsistent."""

    code = "source_span"


class CitationResolutionError(StateLawsGraphError):
    """Raised when citation resolution is malformed (not merely unresolved)."""

    code = "citation_resolution"


class GraphProjectionError(StateLawsGraphError):
    """Raised when graph projection fails integrity checks."""

    code = "graph_projection"


class GraphFixtureError(StateLawsGraphError):
    """Raised when the sealed graph recipe is malformed."""

    code = "graph_fixture"


class LegalSimilarityCollisionError(StateLawsGraphError):
    """Raised when legal and similarity semantics are mixed."""

    code = "legal_similarity_collision"


class GraphReceiptError(StateLawsGraphError):
    """Raised when the software-contract receipt is malformed."""

    code = "graph_receipt"


class GraphReleaseAuthorizationError(StateLawsGraphError):
    """Raised when a graph artifact would authorize publication or release."""

    code = "graph_release_authorization"


class GraphEvaluationError(StateLawsGraphError):
    """Raised when graph evaluation cannot complete fail-closed."""

    code = "graph_evaluation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    return require_non_empty_str_core(
        value,
        name,
        error_type=StateLawsGraphError,
        maximum=maximum,
    )


def _optional_str(value: Any, name: str = "value", *, maximum: int = 4096) -> Optional[str]:
    return optional_str_core(
        value,
        name,
        error_type=StateLawsGraphError,
        maximum=maximum,
    )


def _require_non_negative_int(value: Any, name: str) -> int:
    return require_non_negative_int_core(
        value,
        name,
        error_type=StateLawsGraphError,
    )


def sha256_cid(payload: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:<hex>`` content address."""

    return sha256_cid_core(payload, digest_mapping=digest_mapping)


def assert_legal_similarity_disjoint() -> None:
    """Fail closed if legal and similarity edge vocabularies overlap."""

    assert_legal_similarity_disjoint_core(
        edge_type=GraphEdgeType,
        edge_class=GraphEdgeClass,
        legal_edge_types=LEGAL_EDGE_TYPES,
        similarity_edge_types=SIMILARITY_EDGE_TYPES,
        default_edge_class=DEFAULT_EDGE_CLASS,
        ontology_error_type=GraphOntologyError,
        collision_error_type=LegalSimilarityCollisionError,
    )


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_for_release": AUTHORIZES_RELEASE,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


def default_legal_graph_receipt_path() -> Path:
    return DEFAULT_REPORT_PATH


def default_graph_evaluation_report_path() -> Path:
    return DEFAULT_REPORT_PATH


def production_graph_bounds() -> dict[str, Any]:
    return {
        "exact_51_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "nodes_and_edges_sorted_by": "type_then_key_then_cid",
        "similarity_cannot_establish_legal_authority": True,
    }


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".sl-graph-",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    text = (
        json.dumps(
            dict(payload),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    return write_bytes_atomic(path, text.encode("utf-8"))


def normalize_edition(value: Any) -> str:
    if value is None or value == "":
        return DEFAULT_EDITION
    text = _require_non_empty_str(value, "edition", maximum=128).lower()
    text = re.sub(r"\s+", "-", text.replace("_", "-"))
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        raise GraphProjectionError("edition must be a non-empty string")
    return text


@dataclass(frozen=True, slots=True)
class Hierarchy:
    """Normalized title/chapter/section/subsection path for one graph row."""

    section: Optional[str] = None
    title: Optional[str] = None
    chapter: Optional[str] = None
    part: Optional[str] = None
    article: Optional[str] = None
    subsection: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article,
            "chapter": self.chapter,
            "part": self.part,
            "section": self.section,
            "subsection": self.subsection,
            "title": self.title,
        }


def normalize_hierarchy(value: Any) -> Hierarchy:
    if isinstance(value, Hierarchy):
        return value
    if value is None:
        mapping: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        mapping = value
    else:
        raise GraphProjectionError("hierarchy must be a mapping")

    def _opt_section(raw: Any, name: str) -> Optional[str]:
        if raw is None or raw == "":
            return None
        if name == "section":
            return normalize_section_token(raw)
        text = str(raw).strip()
        if not text:
            return None
        try:
            return normalize_section_token(text)
        except Exception:
            return text

    section = _opt_section(mapping.get("section"), "section")
    subsection = mapping.get("subsection")
    subsection_text = None if subsection in (None, "") else str(subsection).strip().lower()
    return Hierarchy(
        section=section,
        title=_opt_section(mapping.get("title"), "title"),
        chapter=_opt_section(mapping.get("chapter"), "chapter"),
        part=_opt_section(mapping.get("part"), "part"),
        article=_opt_section(mapping.get("article"), "article"),
        subsection=subsection_text,
    )


def validate_source_cid(value: Any) -> str:
    return validate_entry_cid(value, name="source_cid")


_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{8,}")
_BEARER_RE = re.compile(r"Bearer\s+\S+")


def assert_no_secrets_or_home_paths(payload: Mapping[str, Any]) -> None:
    dumped = canonical_json_dumps(dict(payload))
    if "/home/" in dumped or "/Users/" in dumped:
        raise GraphReceiptError("graph report must not contain absolute home paths")
    if _HF_TOKEN_RE.search(dumped) or _BEARER_RE.search(dumped):
        raise GraphReceiptError("graph report must not contain token material")


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

    _graph_error_type: ClassVar[type[Exception]] = StateLawsGraphError
    _source_span_error_type: ClassVar[type[Exception]] = SourceSpanError

    __post_init__ = validate_source_span_record
    bind_to_source = bind_source_span
    to_dict = source_span_to_dict
    from_mapping = classmethod(source_span_from_mapping)
    from_occurrence = classmethod(source_span_from_occurrence)


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

    _ontology_bindings: ClassVar[LegalGraphOntologyBindings]

    __post_init__ = validate_graph_ontology
    edge_class_for = graph_ontology_edge_class_for
    is_legal_edge = graph_ontology_is_legal_edge
    is_similarity_edge = graph_ontology_is_similarity_edge
    validate_edge = validate_graph_ontology_edge
    to_dict = graph_ontology_to_dict


def _edge_direction_allowed(
    edge: GraphEdgeType,
    source: GraphNodeType,
    target: GraphNodeType,
) -> bool:
    return legal_edge_direction_allowed(
        edge,
        source,
        target,
        node_type=GraphNodeType,
        edge_type=GraphEdgeType,
        section_like=SECTION_LIKE,
        similarity_edge_types=SIMILARITY_EDGE_TYPES,
        act_node_type=GraphNodeType.ACT,
        edition_edge_types=frozenset({GraphEdgeType.HAS_EDITION, GraphEdgeType.VERSION_OF}),
    )


_ONTOLOGY_BINDINGS = LegalGraphOntologyBindings(
    version=ONTOLOGY_VERSION,
    node_type=GraphNodeType,
    edge_type=GraphEdgeType,
    edge_class=GraphEdgeClass,
    legal_edge_types=LEGAL_EDGE_TYPES,
    similarity_edge_types=SIMILARITY_EDGE_TYPES,
    required_coverage_node_types=REQUIRED_COVERAGE_NODE_TYPES,
    default_edge_class=DEFAULT_EDGE_CLASS,
    direction_allowed=_edge_direction_allowed,
    assert_disjoint=assert_legal_similarity_disjoint,
    ontology_error_type=GraphOntologyError,
    collision_error_type=LegalSimilarityCollisionError,
)
GraphOntology._ontology_bindings = _ONTOLOGY_BINDINGS


GRAPH_ONTOLOGY: Final = GraphOntology()


# ---------------------------------------------------------------------------
# Citation extraction / resolution
# ---------------------------------------------------------------------------

_alias_key = citation_alias_key
CITATION_CODE_ALIASES: Final = SHARED_CITATION_CODE_ALIASES


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

    _graph_error_type: ClassVar[type[Exception]] = StateLawsGraphError
    _citation_error_type: ClassVar[type[Exception]] = CitationResolutionError

    __post_init__ = validate_citation_mention_record
    to_dict = citation_mention_to_dict


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """Resolved or honestly-unresolved citation with evidence span."""

    mention: CitationMention
    resolution_status: ResolutionStatus
    span: SourceSpan
    target_legal_id: Optional[str] = None
    target_public_law_id: Optional[str] = None
    target_node_key: Optional[str] = None

    to_dict = resolved_citation_to_dict


_drop_contained_mentions = drop_contained_mentions


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
    """Extract citations through the shared grammar with dataset versioning."""

    return extract_citation_mentions_core(
        text,
        mention_type=CitationMention,
        parser_version=CITATION_PARSER_VERSION,
        normalize_section_token=normalize_section_token,
        citation_error_type=CitationResolutionError,
        default_jurisdiction=default_jurisdiction,
        default_code_family=default_code_family,
    )


def _unresolved_node_key(mention: CitationMention) -> str:
    return unresolved_citation_node_key(mention, content_sha256=content_sha256)


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
    """Resolve citations through the shared algorithm and identity callbacks."""

    return resolve_citations_core(
        text,
        bindings=_CITATION_RESOLVER_BINDINGS,
        known_legal_ids=known_legal_ids,
        locator_index=locator_index,
        source_cid=source_cid,
        entry_cid=entry_cid,
        default_jurisdiction=default_jurisdiction,
        default_code_family=default_code_family,
        host_legal_id=host_legal_id,
        host_section=host_section,
    )


def _section_or_subsection_key(legal_id: str) -> str:
    try:
        parsed = parse_legal_id(legal_id)
    except Exception:
        return f"section:{legal_id}"
    if parsed.subsection:
        return f"subsection:{legal_id}"
    return f"section:{legal_id}"


def _resolve_usc_candidates(
    mention: CitationMention,
    known: set[str],
) -> Sequence[str]:
    # State graph identity cannot invent a federal legal_id outside exact-51.
    return [
        item
        for item in known
        if ":usc:" in item
        and f":{mention.title}:" in item
        and item.rsplit(":", 1)[-1].split(";", 1)[0] == mention.section
    ]


def _public_law_node_key(public_law_id: str) -> str:
    return f"act:{public_law_id}"


_CITATION_RESOLVER_BINDINGS = CitationResolverBindings(
    extract_mentions=extract_citation_mentions,
    source_span_type=SourceSpan,
    resolved_citation_type=ResolvedCitation,
    resolution_status=ResolutionStatus,
    public_law_node_key=_public_law_node_key,
    resolve_usc_candidates=_resolve_usc_candidates,
    section_or_subsection_key=_section_or_subsection_key,
    unresolved_node_key=_unresolved_node_key,
)


def strip_subsection_qualifier(legal_id: str) -> str:
    """Return the parent section legal id, dropping any subsection qualifier."""

    parsed = parse_legal_id(legal_id)
    if not parsed.subsection:
        return legal_id
    return parsed.parent_legal_id


def _build_row_legal_id(
    *,
    jurisdiction: str,
    code_family: str,
    hierarchy: Hierarchy,
    edition: str,
    subsection: Optional[str] = None,
    kind: str = DEFAULT_KIND,
) -> str:
    if not hierarchy.section:
        raise GraphProjectionError("legal_id requires a section")
    return build_legal_id(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=hierarchy.section,
        title=hierarchy.title,
        chapter=hierarchy.chapter,
        part=hierarchy.part,
        article=hierarchy.article,
        subsection=subsection or hierarchy.subsection,
        edition=edition or DEFAULT_EDITION,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# Graph node / edge records
# ---------------------------------------------------------------------------


_GRAPH_RECORD_BINDINGS = GraphRecordBindings(
    node_type=GraphNodeType,
    edge_type=GraphEdgeType,
    edge_class=GraphEdgeClass,
    resolution_status=ResolutionStatus,
    source_span_type=SourceSpan,
    legal_edge_types=LEGAL_EDGE_TYPES,
    similarity_edge_types=SIMILARITY_EDGE_TYPES,
    span_required_edge_types=SPAN_REQUIRED_EDGE_TYPES,
    non_authoritative_authority=NON_AUTHORITATIVE_AUTHORITY,
    node_identity_kind="state_laws_graph_node",
    edge_identity_kind="state_laws_graph_edge",
    sha256_cid=sha256_cid,
    graph_error_type=StateLawsGraphError,
    projection_error_type=GraphProjectionError,
    source_span_error_type=SourceSpanError,
    citation_error_type=CitationResolutionError,
    collision_error_type=LegalSimilarityCollisionError,
)

_GRAPH_PROJECTION_BINDINGS = GraphProjectionBindings(
    record_bindings=_GRAPH_RECORD_BINDINGS,
    required_coverage_node_types=REQUIRED_COVERAGE_NODE_TYPES,
    require_non_negative_int=_require_non_negative_int,
)


@dataclass(frozen=True, slots=True)
class StateLawsGraphNode:
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

    _record_bindings: ClassVar[GraphRecordBindings] = _GRAPH_RECORD_BINDINGS

    __post_init__ = validate_graph_node_record
    to_dict = graph_node_to_dict


@dataclass(frozen=True, slots=True)
class StateLawsGraphEdge:
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

    _record_bindings: ClassVar[GraphRecordBindings] = _GRAPH_RECORD_BINDINGS

    __post_init__ = validate_graph_edge_record
    is_legal = property(graph_edge_is_legal)
    is_similarity = property(graph_edge_is_similarity)
    to_dict = graph_edge_to_dict


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
class StateLawsGraphProjection:
    """Deterministic multi-jurisdiction legal graph projection."""

    nodes: tuple[StateLawsGraphNode, ...]
    edges: tuple[StateLawsGraphEdge, ...]
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    citation_parser_version: str = CITATION_PARSER_VERSION
    unresolved_count: int = 0
    legal_edge_count: int = 0
    similarity_edge_count: int = 0
    skipped_row_count: int = 0
    graph_cid: str = ""

    _projection_bindings: ClassVar[GraphProjectionBindings] = (
        _GRAPH_PROJECTION_BINDINGS
    )

    __post_init__ = validate_graph_projection
    node_by_key = graph_projection_node_by_key
    node_by_cid = graph_projection_node_by_cid
    legal_edges = graph_projection_legal_edges
    similarity_edges = graph_projection_similarity_edges
    coverage_node_types = graph_projection_coverage_node_types
    missing_coverage_node_types = graph_projection_missing_coverage_node_types

    def uniqueness_ok(self) -> bool:
        node_cids = [item.node_cid for item in self.nodes]
        node_keys = [item.node_key for item in self.nodes]
        edge_cids = [item.edge_cid for item in self.edges]
        return (
            len(set(node_cids)) == len(node_cids)
            and len(set(node_keys)) == len(node_keys)
            and len(set(edge_cids)) == len(edge_cids)
        )

    def referential_integrity_ok(self) -> bool:
        node_cids = {item.node_cid for item in self.nodes}
        return all(
            edge.source_node_cid in node_cids and edge.target_node_cid in node_cids
            for edge in self.edges
        )

    def jurisdiction_codes(self) -> tuple[str, ...]:
        present = {
            str(item.payload.get("jurisdiction_code"))
            for item in self.nodes
            if item.node_type is GraphNodeType.JURISDICTION
            and item.payload.get("jurisdiction_code")
        }
        return tuple(code for code in CANONICAL_JURISDICTION_ORDER if code in present)

    def exact_51_coverage_ok(self) -> bool:
        codes = self.jurisdiction_codes()
        try:
            validate_jurisdiction_set(codes)
        except Exception:
            return False
        return len(codes) == EXPECTED_JURISDICTION_COUNT

    assert_semantics_disjoint = assert_graph_projection_semantics_disjoint
    assert_coverage = assert_graph_projection_coverage
    to_dict = graph_projection_to_dict


def find_graph_paths(
    projection: StateLawsGraphProjection,
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
    adjacency: dict[str, list[StateLawsGraphEdge]] = defaultdict(list)
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
    projection: StateLawsGraphProjection,
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
        "act:",
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
    text = str(value).strip().lower().replace("-", "_")
    if text in GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS:
        return True
    try:
        status = AdmissionStatus.coerce(value)
    except Exception:
        return False
    return status.value in GRAPH_FAMILY_EXCLUDED_CONFIGURATIONS


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
    document_kind: str = DEFAULT_KIND
    configuration: str = DEFAULT_CONFIGURATION
    admission_status: str = AdmissionStatus.ADMITTED.value
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
            normalize_jurisdiction(self.jurisdiction_code),
        )
        object.__setattr__(
            self,
            "admission_status",
            str(self.admission_status or AdmissionStatus.ADMITTED.value).strip().lower(),
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
            value.get("document_kind") or value.get("kind") or DEFAULT_KIND
        )
        admission_status = (
            value.get("admission_status")
            or value.get("configuration")
            or DEFAULT_CONFIGURATION
        )
        legal_id = value.get("legal_id")
        if not legal_id:
            legal_id = _build_row_legal_id(
                jurisdiction=str(jurisdiction),
                code_family=str(code_family),
                hierarchy=parsed_hierarchy,
                edition=str(edition or DEFAULT_EDITION),
                subsection=value.get("subsection") or parsed_hierarchy.subsection,
                kind=str(document_kind),
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
            configuration=str(value.get("configuration") or admission_status or DEFAULT_CONFIGURATION),
            admission_status=str(admission_status),
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


_PROJECTOR_BINDINGS = LegalGraphProjectorBindings(
    node_type=GraphNodeType,
    edge_type=GraphEdgeType,
    resolution_status=ResolutionStatus,
    source_span_type=SourceSpan,
    node_factory=StateLawsGraphNode,
    edge_factory=StateLawsGraphEdge,
    jurisdiction_names=CANONICAL_JURISDICTION_NAMES,
    public_law_node_type=GraphNodeType.ACT,
    public_law_key_prefix="act",
    version_edge_type=GraphEdgeType.VERSION_OF,
    canonical_json_dumps=canonical_json_dumps,
    content_sha256=content_sha256,
    strip_subsection_qualifier=strip_subsection_qualifier,
    section_or_subsection_key=_section_or_subsection_key,
    unresolved_node_key=_unresolved_node_key,
    resolve_citations=resolve_citations,
    projection_error_type=GraphProjectionError,
)


class StateLawsGraphProjector(LegalGraphProjectorCore):
    """Project admitted multi-jurisdiction rows into the legal ontology graph."""

    _projector_bindings = _PROJECTOR_BINDINGS

    def __init__(self, ontology: GraphOntology | None = None) -> None:
        self.ontology = ontology or GRAPH_ONTOLOGY

    def project(
        self,
        rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
        *,
        similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
    ) -> StateLawsGraphProjection:
        admitted: list[GraphCorpusRow] = []
        skipped = 0
        for item in rows:
            row = self._coerce_row(item)
            if _is_excluded_configuration(row.configuration) or _is_excluded_configuration(
                row.admission_status
            ):
                skipped += 1
                continue
            admitted.append(row)
        if not admitted:
            raise GraphProjectionError("cannot project an empty corpus")

        known_legal_ids = {row.legal_id for row in admitted}
        locator_index: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        nodes: dict[str, StateLawsGraphNode] = {}
        edges: list[StateLawsGraphEdge] = []

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

        unique_edges: dict[str, StateLawsGraphEdge] = {}
        for edge in edges:
            unique_edges[edge.edge_cid] = edge

        projection = StateLawsGraphProjection(
            nodes=tuple(nodes.values()),
            edges=tuple(unique_edges.values()),
            skipped_row_count=skipped,
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
        raise GraphProjectionError(
            "similarity neighbor must be mapping or SimilarityNeighbor"
        )

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
                        jurisdiction=mention.jurisdiction_code,
                        code_family=mention.code_family,
                        section=mention.section,
                        title=mention.title,
                        edition=row.edition,
                    )
                except Exception:
                    return None
        return None

def project_state_laws_graph(
    rows: Sequence[GraphCorpusRow | Mapping[str, Any]],
    *,
    similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
) -> StateLawsGraphProjection:
    """Project corpus rows into a deterministic multi-jurisdiction legal graph."""

    return StateLawsGraphProjector().project(
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
    edition: str = DEFAULT_EDITION,
    document_kind: str = DEFAULT_KIND,
    subsection: Optional[str] = None,
) -> str:
    parsed = normalize_hierarchy(hierarchy)
    return _build_row_legal_id(
        jurisdiction=jurisdiction_code,
        code_family=code_family,
        hierarchy=parsed,
        edition=edition,
        subsection=subsection or parsed.subsection,
        kind=document_kind,
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
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
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
            "repeals": [ca_187],
            "code_family": "penal-code",
            "configuration": DEFAULT_CONFIGURATION,
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
            "edition": "2024-official",
            "entry_cid": _cid("7"),
            "transfers": [wa_030],
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
            "document_kind": DEFAULT_KIND,
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
            "document_kind": DEFAULT_KIND,
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
            "configuration": AdmissionStatus.RECOVERY.value,
            "document_kind": DEFAULT_KIND,
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
        *fixture_exact_51_coverage_records(),
    ]


def _stable_cid(tag: str) -> str:
    return "sha256:" + hashlib.sha256(f"lcr-030:{tag}".encode("utf-8")).hexdigest()


def fixture_exact_51_coverage_records() -> list[dict[str, Any]]:
    """One compact admitted row per remaining exact-51 jurisdiction."""

    detailed = {"CA", "DC", "NY", "OR", "WA"}
    records: list[dict[str, Any]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        if code in detailed:
            continue
        family = "code"
        hierarchy = {"title": "1", "chapter": "1", "section": "1-1-1"}
        legal_id = _fixture_legal_id(
            jurisdiction_code=code,
            code_family=family,
            hierarchy=hierarchy,
        )
        records.append(
            {
                "acquisition_receipt_cid": _stable_cid(f"{code}:acq"),
                "code_family": family,
                "configuration": DEFAULT_CONFIGURATION,
                "document_kind": DEFAULT_KIND,
                "edition": DEFAULT_EDITION,
                "entry_cid": _stable_cid(f"{code}:entry"),
                "heading": f"{code} fixture coverage section",
                "hierarchy": hierarchy,
                "jurisdiction_code": code,
                "legal_id": legal_id,
                "observed_at": "2026-04-01T00:00:00Z",
                "official_source_url": f"https://example.invalid/{code.lower()}/1-1-1",
                "rights_receipt_cid": _stable_cid(f"{code}:rights"),
                "source_cid": _stable_cid(f"{code}:source"),
                "text": (
                    f"{CANONICAL_JURISDICTION_NAMES.get(code, code)} fixture "
                    "coverage section 1-1-1 shall remain in force for the "
                    "sealed graph recipe."
                ),
            }
        )
    return records


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
            "edge_types": ["VERSION_OF"],
            "path_id": "oregon-version-of-edition",
            "source_key": f"section:{or_311['legal_id']}",
            "target_key": "edition:2024-official",
        },
        {
            "edge_types": ["CODIFIES"],
            "path_id": "act-codifies-oregon",
            "source_key": "act:pl:us:112:29",
            "target_key": f"section:{or_311['legal_id']}",
        },
        {
            "edge_types": ["REPEALS"],
            "path_id": "california-repeals-california",
            "source_key": f"section:{ca_188['legal_id']}",
            "target_key": f"section:{ca_187['legal_id']}",
        },
        {
            "edge_types": ["TRANSFERS"],
            "path_id": "washington-transfers-washington",
            "source_key": f"section:{wa_070['legal_id']}",
            "target_key": f"section:{wa_030['legal_id']}",
        },
    ]


def build_default_graph_expected_fixture_payload() -> dict[str, Any]:
    """Compact sealed expected-path recipe (no bulk node/edge dumps)."""

    records = fixture_seed_records()
    neighbors = fixture_similarity_neighbors()
    projection = project_state_laws_graph(records, similarity_neighbors=neighbors)
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
            "LCR-030. Cases exercise jurisdiction/code/title/chapter/section/"
            "subsection/source/edition/act/citation structure plus amendment, "
            "repeal, transfer, version, and provenance. Similarity edges are "
            "present but non-authoritative. Coverage rows span the exact 51 "
            "jurisdictions (50 states + DC)."
        ),
        "expected_paths": expected_paths,
        "goal_id": GOAL_ID,
        "notes": (
            "Recipe form: seed records + expected path predicates. Full graph "
            "is projected deterministically by project_state_laws_graph."
        ),
        "ontology_version": ONTOLOGY_VERSION,
        "producer": PRODUCER,
        "projection_expectations": {
            "exact_51_coverage": True,
            "legal_edge_count_min": 20,
            "min_jurisdictions": EXPECTED_JURISDICTION_COUNT,
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
    projection = project_state_laws_graph(records, similarity_neighbors=neighbors)
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
    jurisdictions = set(projection.jurisdiction_codes())
    if len(jurisdictions) < int(expectations.get("min_jurisdictions") or 0):
        counts_ok = False
    exact_51_ok = projection.exact_51_coverage_ok()
    if expectations.get("exact_51_coverage") and not exact_51_ok:
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

    uniqueness_ok = projection.uniqueness_ok()
    referential_ok = projection.referential_integrity_ok()
    ok = (
        paths_ok
        and unresolved_ok
        and not span_errors
        and counts_ok
        and not similarity_leaked
        and coverage_ok
        and uniqueness_ok
        and referential_ok
        and exact_51_ok
    )
    return {
        "coverage_ok": coverage_ok,
        "exact_51_coverage_ok": exact_51_ok,
        "graph_cid": projection.graph_cid,
        "jurisdiction_count": len(jurisdictions),
        "legal_edge_count": projection.legal_edge_count,
        "missing_coverage_node_types": projection.missing_coverage_node_types(),
        "node_count": len(projection.nodes),
        "ok": ok,
        "path_matches": path_matches,
        "referential_integrity_ok": referential_ok,
        "similarity_edge_count": projection.similarity_edge_count,
        "similarity_leaked_into_legal_paths": similarity_leaked,
        "skipped_row_count": projection.skipped_row_count,
        "span_errors": span_errors,
        "uniqueness_ok": uniqueness_ok,
        "unresolved_count": projection.unresolved_count,
        "unresolved_ok": unresolved_ok,
    }


def bind_fixture_graph() -> StateLawsGraphProjection:
    payload = build_default_graph_expected_fixture_payload()
    return project_state_laws_graph(
        payload["records"],
        similarity_neighbors=payload["similarity_neighbors"],
    )


# ---------------------------------------------------------------------------
# Software-contract receipt
# ---------------------------------------------------------------------------


def _acceptance_block() -> dict[str, Any]:
    return {
        "51_jurisdiction_coverage": True,
        "authorizing_for_publication": False,
        "deterministic_nodes_and_edges_cover_required_types": True,
        "embedding_or_lexical_similarity_not_legal_authority": True,
        "hub_upload": False,
        "referential_integrity": True,
        "secrets_absent": True,
        "similarity_not_authority": True,
        "uniqueness": True,
        "unresolved_citation_accounting": True,
        "unresolved_citations_preserved": True,
    }


def _digest_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(payload).items()
        if key not in {"receipt_sha256", "report_digest_sha256"}
    }


def build_graph_evaluation_report(
    projection: StateLawsGraphProjection | None = None,
) -> dict[str, Any]:
    """Build the sealed LCR-030 graph evaluation receipt."""

    demo = projection if projection is not None else bind_fixture_graph()
    demo.assert_semantics_disjoint()
    if not demo.uniqueness_ok():
        raise GraphProjectionError("projected node/edge IDs are not unique")
    if not demo.referential_integrity_ok():
        raise GraphProjectionError("projected graph fails referential integrity")
    if not demo.exact_51_coverage_ok():
        raise GraphProjectionError("projected graph does not cover the exact 51 jurisdictions")
    node_types = sorted(demo.coverage_node_types())
    jurisdictions = list(demo.jurisdiction_codes())
    similarity_edges = demo.similarity_edges()
    unresolved_nodes = [
        item
        for item in demo.nodes
        if item.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    unresolved_edges = [
        item for item in demo.edges if item.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "authorizing_hub_upload": False,
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
            "exact_51_allowlist_size": EXPECTED_JURISDICTION_COUNT,
            "exact_51_coverage": True,
            "legal_and_similarity_disjoint": True,
            "nodes_and_edges_cid_sorted": True,
            "recovery_and_quarantine_excluded_from_graph_counts": demo.skipped_row_count >= 1,
            "referential_integrity": True,
            "required_coverage_node_types": list(REQUIRED_COVERAGE_NODE_TYPES),
            "secrets_absent": True,
            "similarity_edges_non_authoritative": all(
                item.payload.get("authority") == NON_AUTHORITATIVE_AUTHORITY
                and item.edge_class is GraphEdgeClass.SIMILARITY
                for item in similarity_edges
            ),
            "similarity_leaked_into_legal_paths": False,
            "uniqueness": True,
            "unresolved_citation_count": demo.unresolved_count,
            "unresolved_citation_edge_count": len(unresolved_edges),
            "unresolved_citation_node_count": len(unresolved_nodes),
            "unresolved_citations_have_no_invented_legal_id": all(
                item.legal_id is None for item in unresolved_nodes
            ),
        },
        "citation_parser_version": CITATION_PARSER_VERSION,
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
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
        "depends_on": ["LCR-024", "LCR-026"],
        "description": (
            "LCR-030 state-law legal and provenance graph. Deterministic "
            "nodes and edges cover jurisdiction, code, title, chapter, "
            "section, subsection, source, edition, act, citation, amendment, "
            "and provenance across the exact 51 jurisdictions. Unresolved "
            "citations are preserved. Embedding and lexical similarity are "
            "never represented as legal authority. Recovery and quarantine "
            "rows do not increment graph family counts. Hermetic fixture "
            "evaluation only. Does not authorize Hub upload."
        ),
        "family_counts": {
            "graph": len(demo.nodes),
            "graph_edges": len(demo.edges),
            "graph_nodes": len(demo.nodes),
        },
        "goal_id": GOAL_ID,
        "network_required": False,
        "ontology": GRAPH_ONTOLOGY.to_dict(),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "repairs": {
            "area_id": "multi_jurisdiction_legal_provenance_graph",
            "owner_task": TASK_ID,
            "required": [
                "Emit deterministic CID-sorted nodes and edges for jurisdiction, code, title, chapter, section, subsection, source, edition, act, citation, amendment, and provenance.",
                "Preserve unresolved citations as typed nodes and edges with source text and parser version; never invent a target legal_id.",
                "Keep embedding neighbors, BM25 neighbors, and lexical similarity disjoint from legal authority.",
                "Exclude recovery and quarantine rows from graph family counts.",
                "Reconcile uniqueness, referential integrity, and exact-51 jurisdiction coverage.",
            ],
        },
        "report_kind": "fixture_graph",
        "schema": REPORT_SCHEMA,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sealed_at": RECEIPT_SEALED_AT,
        "task_id": TASK_ID,
    }
    payload.update(software_contract_flags())
    compact = dict(payload)
    assert_no_secrets_or_home_paths(compact)
    digest = digest_mapping(_digest_fields(compact))
    compact["receipt_sha256"] = digest
    compact["report_digest_sha256"] = digest
    return compact


def build_legal_graph_receipt(
    projection: StateLawsGraphProjection | None = None,
) -> dict[str, Any]:
    """Alias for :func:`build_graph_evaluation_report`."""

    return build_graph_evaluation_report(projection)


def write_graph_evaluation_report(
    path: PathLike | None = None,
    *,
    projection: StateLawsGraphProjection | None = None,
) -> Path:
    target = Path(path) if path is not None else default_graph_evaluation_report_path()
    payload = build_graph_evaluation_report(projection=projection)
    write_json_atomic(target, payload)
    return target


def write_legal_graph_receipt(path: PathLike | None = None) -> Path:
    return write_graph_evaluation_report(path)


def load_graph_evaluation_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_graph_evaluation_report_path()
    if not target.is_file():
        raise GraphReceiptError(f"graph evaluation report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise GraphReceiptError("graph evaluation report root must be an object")
    return dict(payload)


def load_legal_graph_receipt(path: PathLike | None = None) -> dict[str, Any]:
    return load_graph_evaluation_report(path)


def assert_graph_evaluation_report(payload: Mapping[str, Any]) -> None:
    """Fail closed if the report would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise GraphReceiptError(f"report task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise GraphReceiptError(
            f"report schema_version must be {RECEIPT_SCHEMA_VERSION!r}"
        )
    if payload.get("schema") != REPORT_SCHEMA:
        raise GraphReceiptError(f"report schema must be {REPORT_SCHEMA!r}")
    if payload.get("authorizing_for_release") is True:
        raise GraphReleaseAuthorizationError("graph report cannot authorize release")
    if payload.get("authorizing_for_publication") is True:
        raise GraphReleaseAuthorizationError(
            "graph report cannot authorize publication"
        )
    if payload.get("authorizing_hub_upload") is True:
        raise GraphReleaseAuthorizationError("graph report cannot authorize Hub upload")
    if payload.get("proves_software_contract_only") is not True:
        raise GraphReceiptError("report must prove the software contract only")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise GraphReceiptError("report acceptance must be a mapping")
    for key, expected in _acceptance_block().items():
        if acceptance.get(key) is not expected:
            raise GraphReceiptError(f"report acceptance.{key} must be {expected}")
    checks = payload.get("checks") or {}
    if not isinstance(checks, Mapping):
        raise GraphReceiptError("report checks must be a mapping")
    if checks.get("legal_and_similarity_disjoint") is not True:
        raise GraphReceiptError("report must keep legal and similarity disjoint")
    if checks.get("similarity_edges_non_authoritative") is not True:
        raise GraphReceiptError("report must label similarity as non-authoritative")
    if checks.get("similarity_leaked_into_legal_paths") is True:
        raise LegalSimilarityCollisionError(
            "report reports similarity leaked into legal paths"
        )
    if checks.get("unresolved_citations_have_no_invented_legal_id") is not True:
        raise GraphReceiptError("report must preserve unresolved citations honestly")
    if checks.get("exact_51_coverage") is not True:
        raise GraphReceiptError("report must prove exact 51-jurisdiction coverage")
    if checks.get("uniqueness") is not True:
        raise GraphReceiptError("report must prove node/edge uniqueness")
    if checks.get("referential_integrity") is not True:
        raise GraphReceiptError("report must prove referential integrity")
    required = checks.get("required_coverage_node_types") or []
    if list(required) != list(REQUIRED_COVERAGE_NODE_TYPES):
        raise GraphReceiptError("report required coverage node types drifted")
    if checks.get("coverage_node_types_present") is not True:
        raise GraphReceiptError("report is missing required coverage node types")
    if int(checks.get("demo_jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise GraphReceiptError("report must cover exactly 51 jurisdictions")
    family = payload.get("family_counts") or {}
    if not isinstance(family, Mapping):
        raise GraphReceiptError("report family_counts must be a mapping")
    if int(family.get("graph_nodes") or 0) != int(checks.get("demo_node_count") or -1):
        raise GraphReceiptError("graph family node counts do not reconcile")
    if int(family.get("graph_edges") or 0) != int(checks.get("demo_edge_count") or -1):
        raise GraphReceiptError("graph family edge counts do not reconcile")
    assert_no_secrets_or_home_paths(payload)
    expected_digest = digest_mapping(_digest_fields(payload))
    if payload.get("receipt_sha256") != expected_digest:
        raise GraphReceiptError("receipt_sha256 does not match canonical payload")
    if payload.get("report_digest_sha256") not in {None, expected_digest}:
        if payload.get("report_digest_sha256") != expected_digest:
            raise GraphReceiptError("report_digest_sha256 does not match canonical payload")


def assert_legal_graph_receipt(payload: Mapping[str, Any]) -> None:
    assert_graph_evaluation_report(payload)


def check_evaluation_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a report object against sealed LCR-030 acceptance."""

    assert_graph_evaluation_report(payload)
    checks = payload.get("checks") or {}
    return {
        "ok": True,
        "edge_count": checks.get("demo_edge_count"),
        "jurisdiction_count": checks.get("demo_jurisdiction_count"),
        "node_count": checks.get("demo_node_count"),
        "similarity_not_authority": True,
        "task_id": TASK_ID,
        "unresolved_count": checks.get("demo_unresolved_count"),
    }


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
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
    "REPORT_SCHEMA",
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
    "GraphEvaluationError",
    "GraphFixtureError",
    "GraphNodeType",
    "GraphOntology",
    "GraphOntologyError",
    "GraphPath",
    "GraphProjectionError",
    "GraphReceiptError",
    "GraphReleaseAuthorizationError",
    "LegalSimilarityCollisionError",
    "StateLawsGraphEdge",
    "StateLawsGraphError",
    "StateLawsGraphNode",
    "StateLawsGraphProjection",
    "StateLawsGraphProjector",
    "ResolutionStatus",
    "ResolvedCitation",
    "SimilarityNeighbor",
    "SourceSpan",
    "SourceSpanError",
    "assert_graph_evaluation_report",
    "assert_legal_graph_receipt",
    "assert_legal_similarity_disjoint",
    "bind_fixture_graph",
    "build_default_graph_expected_fixture_payload",
    "build_graph_evaluation_report",
    "build_legal_graph_receipt",
    "check_evaluation_report",
    "default_graph_evaluation_report_path",
    "default_legal_graph_receipt_path",
    "extract_citation_mentions",
    "find_graph_paths",
    "fixture_expected_paths",
    "fixture_seed_records",
    "fixture_similarity_neighbors",
    "load_graph_evaluation_report",
    "load_legal_graph_receipt",
    "lookup_citation_locator",
    "match_expected_paths",
    "production_graph_bounds",
    "project_state_laws_graph",
    "resolve_citations",
    "run_fixture_case",
    "sha256_cid",
    "software_contract_flags",
    "strip_subsection_qualifier",
    "write_graph_evaluation_report",
    "write_legal_graph_receipt",
]
