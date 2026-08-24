"""Federal Register agency, rulemaking, citation, and provenance graph (LCR-058).

This module owns the versioned Federal Register legal-graph ontology and the
deterministic projection of:

* agencies
* docket / RIN rulemaking identifiers
* CFR / USC / FR citations
* corrections and related documents
* dates
* official provenance

Design invariants
-----------------
* Legal authority and retrieval similarity are **disjoint**. BM25 neighbors,
  embedding neighbors, and lexical similarity are non-authoritative retrieval
  hints and must never be labeled as citation, correction, or legal validity.
* Unresolved references remain explicit evidence. Targets are never invented.
* Nodes and edges are deterministically content-addressed and CID-sorted.
* Recovery and quarantine rows never increment graph family counts.
* Bounded incoming/outgoing adjacency descriptors are summarized here;
  full adjacency paging belongs to LCR-076.
* Fixture builds are hermetic against the LCR-055 admitted corpus and the
  LCR-056 BM25 identity pins. No network I/O.
* No Hub upload, no tokens, and no absolute home paths in receipts.
* This receipt does not authorize publication.

Depends on LCR-055 (canonical corpus) and LCR-056 BM25 as read-only.
Does not rewrite ``federal_inventory.json`` or ``federal_register_corpus.py``.
"""

from __future__ import annotations

import argparse
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
from typing import Any, Final, Optional, Union

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    SecretInReceiptError,
    assert_no_secrets,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    TASK_ID as BM25_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    CanonicalChunk,
    MaterializedCorpus,
    materialize_federal_register_corpus,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    ADR_PATH,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    PositionalIdentityError,
    reject_positional_durable_identity,
    validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_DATASET_REPO_ID,
    canonical_json_dumps,
    content_sha256,
    digest_mapping,
    repository_root,
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-graph-v1"
ONTOLOGY_VERSION: Final = "federal-register-graph-ontology/v1"
FIXTURE_SCHEMA_VERSION: Final = "federal-register-graph-expected-v1"
CITATION_PARSER_VERSION: Final = "federal-register-citation-parser/v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-graph@1"
TASK_ID: Final = "LCR-058"
GOAL_ID: Final = "LCR-G120"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_graph.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "federal-index-graph"
CODE_VERSION: Final = "1"
CORPUS_TASK_ID: Final = "LCR-055"
ADJACENCY_PAGING_TASK_ID: Final = "LCR-076"

PRIMARY_KEY: Final = "node_cid"
DOCUMENT_KEY: Final = "entry_cid"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

REPORT_RELATIVE_PATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_graph.json"
)

NON_AUTHORITATIVE_AUTHORITY: Final = "non_authoritative"
LEGAL_AUTHORITY: Final = "legal"
MODE_FIXTURE: Final = "fixture"
MODE_LIVE: Final = "live"

NODES_SORTED_BY: Final = "type_then_key_then_cid"
EDGES_SORTED_BY: Final = "type_then_source_then_target_then_cid"
ADJACENCY_SORTED_BY: Final = "node_cid_then_edge_type_then_neighbor_cid"

DEFAULT_TEST_MAX_ADJACENCY_POINTERS: Final = 8
DEFAULT_TEST_MAX_ROWS_PER_SHARD: Final = 2

REQUIRED_COVERAGE_NODE_TYPES: Final = (
    "document",
    "agency",
    "docket",
    "rin",
    "citation_cfr",
    "citation_usc",
    "citation_fr",
    "unresolved_citation",
    "related_document",
    "date",
    "provenance",
    "source",
)

GRAPH_FAMILY_EXCLUDED_DISPOSITIONS: Final = frozenset(
    {
        "excluded",
        "quarantined",
        "quarantine",
        "failed_final",
        "recovery",
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class GraphNodeType(str, Enum):
    """Versioned Federal Register legal graph node vocabulary (LCR-058)."""

    DOCUMENT = "document"
    AGENCY = "agency"
    DOCKET = "docket"
    RIN = "rin"
    CITATION_CFR = "citation_cfr"
    CITATION_USC = "citation_usc"
    CITATION_FR = "citation_fr"
    UNRESOLVED_CITATION = "unresolved_citation"
    RELATED_DOCUMENT = "related_document"
    DATE = "date"
    PROVENANCE = "provenance"
    SOURCE = "source"

    @classmethod
    def coerce(cls, value: Any) -> "GraphNodeType":
        if isinstance(value, GraphNodeType):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "posting": cls.DOCUMENT,
            "fr_document": cls.DOCUMENT,
            "agency_name": cls.AGENCY,
            "docket_id": cls.DOCKET,
            "regulation_id_number": cls.RIN,
            "cfr": cls.CITATION_CFR,
            "cfr_citation": cls.CITATION_CFR,
            "usc": cls.CITATION_USC,
            "usc_citation": cls.CITATION_USC,
            "fr": cls.CITATION_FR,
            "fr_citation": cls.CITATION_FR,
            "unresolved": cls.UNRESOLVED_CITATION,
            "unresolved_cite": cls.UNRESOLVED_CITATION,
            "related": cls.RELATED_DOCUMENT,
            "publication_date": cls.DATE,
            "effective_date": cls.DATE,
            "acquisition": cls.PROVENANCE,
            "source_package": cls.SOURCE,
            "official_source": cls.SOURCE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise GraphOntologyError(f"unsupported graph node type: {value!r}")


class GraphEdgeType(str, Enum):
    """Versioned Federal Register legal / similarity edge vocabulary (LCR-058)."""

    ISSUED_BY = "ISSUED_BY"
    HAS_DOCKET = "HAS_DOCKET"
    HAS_RIN = "HAS_RIN"
    CITES = "CITES"
    CITES_UNRESOLVED = "CITES_UNRESOLVED"
    CORRECTS = "CORRECTS"
    WITHDRAWS = "WITHDRAWS"
    SUPERSEDES = "SUPERSEDES"
    RELATED_TO = "RELATED_TO"
    PUBLISHED_ON = "PUBLISHED_ON"
    EFFECTIVE_ON = "EFFECTIVE_ON"
    HAS_PROVENANCE = "HAS_PROVENANCE"
    HAS_SOURCE = "HAS_SOURCE"
    DERIVED_FROM = "DERIVED_FROM"
    BM25_NEIGHBOR_OF = "BM25_NEIGHBOR_OF"
    SIMILAR_TO = "SIMILAR_TO"
    EMBEDDING_NEIGHBOR_OF = "EMBEDDING_NEIGHBOR_OF"

    @classmethod
    def coerce(cls, value: Any) -> "GraphEdgeType":
        if isinstance(value, GraphEdgeType):
            return value
        text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "AGENCY": cls.ISSUED_BY,
            "ISSUED": cls.ISSUED_BY,
            "DOCKET": cls.HAS_DOCKET,
            "RIN": cls.HAS_RIN,
            "CITE": cls.CITES,
            "UNRESOLVED_CITE": cls.CITES_UNRESOLVED,
            "CITE_UNRESOLVED": cls.CITES_UNRESOLVED,
            "CORRECT": cls.CORRECTS,
            "WITHDRAW": cls.WITHDRAWS,
            "SUPERSEDE": cls.SUPERSEDES,
            "RELATED": cls.RELATED_TO,
            "PUBLISHED": cls.PUBLISHED_ON,
            "EFFECTIVE": cls.EFFECTIVE_ON,
            "PROVENANCE": cls.HAS_PROVENANCE,
            "SOURCE": cls.HAS_SOURCE,
            "BM25": cls.BM25_NEIGHBOR_OF,
            "BM25_NEIGHBOR": cls.BM25_NEIGHBOR_OF,
            "SIMILAR": cls.SIMILAR_TO,
            "EMBEDDING": cls.EMBEDDING_NEIGHBOR_OF,
            "EMBEDDING_NEIGHBOR": cls.EMBEDDING_NEIGHBOR_OF,
            "LEXICAL": cls.BM25_NEIGHBOR_OF,
            "COSINE": cls.EMBEDDING_NEIGHBOR_OF,
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
    """Citation / related-document resolution honesty labels."""

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
        GraphEdgeType.ISSUED_BY,
        GraphEdgeType.HAS_DOCKET,
        GraphEdgeType.HAS_RIN,
        GraphEdgeType.CITES,
        GraphEdgeType.CITES_UNRESOLVED,
        GraphEdgeType.CORRECTS,
        GraphEdgeType.WITHDRAWS,
        GraphEdgeType.SUPERSEDES,
        GraphEdgeType.RELATED_TO,
        GraphEdgeType.PUBLISHED_ON,
        GraphEdgeType.EFFECTIVE_ON,
        GraphEdgeType.HAS_PROVENANCE,
        GraphEdgeType.HAS_SOURCE,
        GraphEdgeType.DERIVED_FROM,
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
    }
)

DEFAULT_EDGE_CLASS: Final[Mapping[GraphEdgeType, GraphEdgeClass]] = MappingProxyType(
    {
        GraphEdgeType.ISSUED_BY: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.HAS_DOCKET: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.HAS_RIN: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.CITES: GraphEdgeClass.CITATION,
        GraphEdgeType.CITES_UNRESOLVED: GraphEdgeClass.UNRESOLVED,
        GraphEdgeType.CORRECTS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.WITHDRAWS: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.SUPERSEDES: GraphEdgeClass.AUTHORITY,
        GraphEdgeType.RELATED_TO: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.PUBLISHED_ON: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.EFFECTIVE_ON: GraphEdgeClass.STRUCTURAL,
        GraphEdgeType.HAS_PROVENANCE: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.HAS_SOURCE: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.DERIVED_FROM: GraphEdgeClass.PROVENANCE,
        GraphEdgeType.BM25_NEIGHBOR_OF: GraphEdgeClass.SIMILARITY,
        GraphEdgeType.SIMILAR_TO: GraphEdgeClass.SIMILARITY,
        GraphEdgeType.EMBEDDING_NEIGHBOR_OF: GraphEdgeClass.SIMILARITY,
    }
)

CORRECTION_EDGE_BY_RELATION: Final[Mapping[str, GraphEdgeType]] = MappingProxyType(
    {
        "corrects": GraphEdgeType.CORRECTS,
        "withdraws": GraphEdgeType.WITHDRAWS,
        "supersedes": GraphEdgeType.SUPERSEDES,
        "corrected_by": GraphEdgeType.RELATED_TO,
        "withdrawn_by": GraphEdgeType.RELATED_TO,
        "superseded_by": GraphEdgeType.RELATED_TO,
    }
)

DOCUMENT_LIKE: Final[frozenset[GraphNodeType]] = frozenset(
    {GraphNodeType.DOCUMENT, GraphNodeType.RELATED_DOCUMENT}
)
CITATION_LIKE: Final[frozenset[GraphNodeType]] = frozenset(
    {
        GraphNodeType.CITATION_CFR,
        GraphNodeType.CITATION_USC,
        GraphNodeType.CITATION_FR,
        GraphNodeType.UNRESOLVED_CITATION,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterGraphError(ValueError):
    """Base error for Federal Register legal graph ontology / projection."""

    code: str = "federal_register_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class GraphOntologyError(FederalRegisterGraphError):
    """Raised when ontology contracts are violated."""

    code = "graph_ontology"


class SourceSpanError(FederalRegisterGraphError):
    """Raised when a source span is unbound or inconsistent."""

    code = "source_span"


class CitationResolutionError(FederalRegisterGraphError):
    """Raised when citation resolution is malformed (not merely unresolved)."""

    code = "citation_resolution"


class GraphProjectionError(FederalRegisterGraphError):
    """Raised when graph projection fails integrity checks."""

    code = "graph_projection"


class GraphFixtureError(FederalRegisterGraphError):
    """Raised when the sealed graph recipe is malformed."""

    code = "graph_fixture"


class LegalSimilarityCollisionError(FederalRegisterGraphError):
    """Raised when legal and similarity semantics are mixed."""

    code = "legal_similarity_collision"


class GraphReceiptError(FederalRegisterGraphError):
    """Raised when the software-contract receipt is malformed."""

    code = "graph_receipt"


class GraphReleaseAuthorizationError(FederalRegisterGraphError):
    """Raised when a graph artifact would authorize publication or Hub upload."""

    code = "graph_release_authorization"


class GraphBoundError(FederalRegisterGraphError):
    """Raised when a physical adjacency / shard bound is violated."""

    code = "graph_bound"


class GraphAdjacencyError(FederalRegisterGraphError):
    """Raised when outgoing/incoming adjacency cannot invert."""

    code = "graph_adjacency"


class GraphCoverageError(FederalRegisterGraphError):
    """Raised when endpoint closure or family coverage fails."""

    code = "graph_coverage"


class GraphConfigError(FederalRegisterGraphError):
    """Raised when graph configuration is invalid."""

    code = "graph_config"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterGraphError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise FederalRegisterGraphError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise FederalRegisterGraphError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value", *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterGraphError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterGraphError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number < 1:
        raise FederalRegisterGraphError(f"{name} must be >= 1")
    return number


def _validate_physical_bound(value: Any, *, name: str, maximum: int) -> int:
    number = _require_positive_int(value, name)
    if number > maximum:
        raise GraphBoundError(f"{name}={number} exceeds physical bound {maximum}")
    return number


def sha256_cid(payload: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:<hex>`` content address."""

    return f"sha256:{digest_mapping(dict(payload))}"


def content_cid(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        digest = content_sha256(bytes(value))
    elif isinstance(value, str):
        digest = content_sha256(value)
    else:
        digest = content_sha256(canonical_json_dumps(value if isinstance(value, Mapping) else {"value": value}))
    return f"sha256:{digest}"


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".fr-graph-",
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


def _slug(value: str) -> str:
    text = unicodedata_normalize(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def unicodedata_normalize(value: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", value)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items: list[str] = []
        for item in value:
            if item is None or item == "":
                continue
            items.append(str(item).strip())
        return tuple(item for item in items if item)
    raise GraphProjectionError("sequence field must be a string or sequence of strings")


def production_graph_bounds() -> dict[str, Any]:
    return {
        "maximum_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "maximum_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "nodes_and_edges_sorted_by": NODES_SORTED_BY,
        "edges_sorted_by": EDGES_SORTED_BY,
        "adjacency_sorted_by": ADJACENCY_SORTED_BY,
        "full_adjacency_paging": ADJACENCY_PAGING_TASK_ID,
        "similarity_cannot_establish_legal_authority": True,
    }


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederalRegisterGraphConfig:
    """Sealed graph projection bounds. Full paging remains LCR-076."""

    max_adjacency_pointers_per_row: int = MAX_ADJACENCY_POINTERS_PER_ROW
    max_rows_per_physical_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    citation_parser_version: str = CITATION_PARSER_VERSION
    mode: str = MODE_FIXTURE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_adjacency_pointers_per_row",
            _validate_physical_bound(
                self.max_adjacency_pointers_per_row,
                name="max_adjacency_pointers_per_row",
                maximum=MAX_ADJACENCY_POINTERS_PER_ROW,
            ),
        )
        object.__setattr__(
            self,
            "max_rows_per_physical_shard",
            _validate_physical_bound(
                self.max_rows_per_physical_shard,
                name="max_rows_per_physical_shard",
                maximum=MAX_ROWS_PER_PHYSICAL_SHARD,
            ),
        )
        mode = _require_non_empty_str(self.mode, "mode", maximum=32).lower()
        if mode not in {MODE_FIXTURE, MODE_LIVE}:
            raise GraphConfigError(f"mode must be fixture or live, got {self.mode!r}")
        object.__setattr__(self, "mode", mode)
        if self.ontology_version != ONTOLOGY_VERSION:
            raise GraphOntologyError(
                f"unsupported ontology version: {self.ontology_version!r}"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise GraphConfigError(
                f"unsupported schema version: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return digest_mapping(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_parser_version": self.citation_parser_version,
            "max_adjacency_pointers_per_row": self.max_adjacency_pointers_per_row,
            "max_rows_per_physical_shard": self.max_rows_per_physical_shard,
            "mode": self.mode,
            "ontology_version": self.ontology_version,
            "schema_version": self.schema_version,
        }


def default_graph_config() -> FederalRegisterGraphConfig:
    return FederalRegisterGraphConfig()


def fixture_graph_config(**overrides: Any) -> FederalRegisterGraphConfig:
    payload = {
        "max_adjacency_pointers_per_row": DEFAULT_TEST_MAX_ADJACENCY_POINTERS,
        "max_rows_per_physical_shard": DEFAULT_TEST_MAX_ROWS_PER_SHARD,
        "mode": MODE_FIXTURE,
    }
    payload.update(overrides)
    return FederalRegisterGraphConfig(**payload)


def production_graph_config() -> FederalRegisterGraphConfig:
    return FederalRegisterGraphConfig(
        max_adjacency_pointers_per_row=MAX_ADJACENCY_POINTERS_PER_ROW,
        max_rows_per_physical_shard=MAX_ROWS_PER_PHYSICAL_SHARD,
        mode=MODE_FIXTURE,
    )


# ---------------------------------------------------------------------------
# Source spans / ontology
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Exact character span bound to a source document.

    Offsets are half-open ``[start, end)``. ``text`` must equal the excerpt
    at those offsets when the source text is available.
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

    @classmethod
    def from_field_value(
        cls,
        value: str,
        *,
        field: str,
        source_cid: Optional[str] = None,
        entry_cid: Optional[str] = None,
    ) -> "SourceSpan":
        text = _require_non_empty_str(value, "span text", maximum=2048)
        return cls(
            start=0,
            end=len(text),
            text=text,
            source_cid=source_cid,
            entry_cid=entry_cid,
            field=field,
        )


@dataclass(frozen=True, slots=True)
class GraphOntology:
    """Machine-readable declaration of the Federal Register graph vocabulary."""

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
    if edge is GraphEdgeType.ISSUED_BY:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.AGENCY
    if edge is GraphEdgeType.HAS_DOCKET:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.DOCKET
    if edge is GraphEdgeType.HAS_RIN:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.RIN
    if edge is GraphEdgeType.CITES:
        return source is GraphNodeType.DOCUMENT and target in CITATION_LIKE | {
            GraphNodeType.DOCUMENT
        }
    if edge is GraphEdgeType.CITES_UNRESOLVED:
        return (
            source is GraphNodeType.DOCUMENT
            and target is GraphNodeType.UNRESOLVED_CITATION
        )
    if edge in {
        GraphEdgeType.CORRECTS,
        GraphEdgeType.WITHDRAWS,
        GraphEdgeType.SUPERSEDES,
        GraphEdgeType.RELATED_TO,
    }:
        return source is GraphNodeType.DOCUMENT and target in DOCUMENT_LIKE
    if edge in {GraphEdgeType.PUBLISHED_ON, GraphEdgeType.EFFECTIVE_ON}:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.DATE
    if edge is GraphEdgeType.HAS_PROVENANCE:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.PROVENANCE
    if edge in {GraphEdgeType.HAS_SOURCE, GraphEdgeType.DERIVED_FROM}:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.SOURCE
    if edge in SIMILARITY_EDGE_TYPES:
        return source is GraphNodeType.DOCUMENT and target is GraphNodeType.DOCUMENT
    return False


GRAPH_ONTOLOGY: Final = GraphOntology()


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

_CFR_RE = re.compile(
    r"""
    (?P<mention>
        (?P<title>\d{1,2})\s*
        (?:C\.?\s*F\.?\s*R\.?|CFR)\s*
        (?:part\s+|§+\s*)?
        (?P<section>\d+(?:\.\d+)?)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_USC_RE = re.compile(
    r"""
    (?P<mention>
        (?P<title>\d+[A-Za-z]?)\s*
        U\.?\s*S\.?\s*C\.?(?:A\.?)?\s*
        (?:§+\s*|sec(?:tion)?\.?\s*)?
        (?P<section>\d+[A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FR_VOLUME_RE = re.compile(
    r"""
    (?P<mention>
        (?P<volume>\d{1,3})\s*
        (?:Fed\.?\s*Reg\.?|F\.?\s*R\.?)\s*
        (?P<page>\d{1,6})
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FR_DOCUMENT_RE = re.compile(
    r"(?P<mention>(?P<document_number>\d{4}-\d{4,5}))"
)
_DOCKET_RE = re.compile(
    r"(?P<mention>(?P<docket>[A-Z]{2,8}(?:-[A-Z0-9]{1,12}){2,6}))"
)
_RIN_RE = re.compile(
    r"(?P<mention>(?:RIN\s*)?(?P<rin>\d{4}-[A-Z]{2}\d{2}))",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True, slots=True)
class CitationMention:
    """One citation occurrence extracted from source text or structured fields."""

    kind: str
    mention_text: str
    start: int
    end: int
    title: Optional[str] = None
    section: Optional[str] = None
    volume: Optional[str] = None
    page: Optional[str] = None
    document_number: Optional[str] = None
    field: str = "text"
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "end": self.end,
            "field": self.field,
            "kind": self.kind,
            "mention_text": self.mention_text,
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
    target_node_key: str
    target_legal_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention": self.mention.to_dict(),
            "resolution_status": self.resolution_status.value,
            "span": self.span.to_dict(),
            "target_legal_id": self.target_legal_id,
            "target_node_key": self.target_node_key,
        }


def _drop_contained_mentions(mentions: list[CitationMention]) -> list[CitationMention]:
    kept: list[CitationMention] = []
    for candidate in sorted(
        mentions, key=lambda item: (item.field, item.start, -(item.end - item.start))
    ):
        contained = False
        for existing in kept:
            if existing.field != candidate.field:
                continue
            if existing.start <= candidate.start and candidate.end <= existing.end:
                if (existing.start, existing.end) != (candidate.start, candidate.end):
                    contained = True
                    break
                if existing.kind != "fr_document" and candidate.kind == "fr_document":
                    contained = True
                    break
        if not contained:
            kept.append(candidate)
    kept.sort(key=lambda item: (item.field, item.start, item.end, item.kind))
    return kept


def extract_citation_mentions(text: str, *, field: str = "text") -> list[CitationMention]:
    """Extract CFR, USC, and FR citation mentions from *text*."""

    if not isinstance(text, str):
        raise CitationResolutionError("text must be a string")
    mentions: list[CitationMention] = []
    for match in _CFR_RE.finditer(text):
        mentions.append(
            CitationMention(
                kind="cfr",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                title=str(int(match.group("title"))),
                section=match.group("section"),
                field=field,
            )
        )
    for match in _USC_RE.finditer(text):
        mentions.append(
            CitationMention(
                kind="usc",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                title=match.group("title"),
                section=match.group("section"),
                field=field,
            )
        )
    for match in _FR_VOLUME_RE.finditer(text):
        mentions.append(
            CitationMention(
                kind="fr_volume",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                volume=str(int(match.group("volume"))),
                page=str(int(match.group("page"))),
                field=field,
            )
        )
    return _drop_contained_mentions(mentions)


def extract_docket_mentions(text: str, *, field: str = "text") -> list[tuple[str, int, int]]:
    if not isinstance(text, str) or not text:
        return []
    found: list[tuple[str, int, int]] = []
    for match in _DOCKET_RE.finditer(text):
        docket = match.group("docket")
        if docket.count("-") < 2:
            continue
        found.append((docket, match.start(), match.end()))
    return found


def extract_rin_mentions(text: str, *, field: str = "text") -> list[tuple[str, int, int]]:
    if not isinstance(text, str) or not text:
        return []
    found: list[tuple[str, int, int]] = []
    for match in _RIN_RE.finditer(text):
        rin = match.group("rin").upper()
        found.append((rin, match.start(), match.end()))
    return found


def _citation_node_key(mention: CitationMention) -> str:
    if mention.kind == "cfr":
        return f"citation:cfr:{mention.title}:{mention.section}"
    if mention.kind == "usc":
        return f"citation:usc:{mention.title}:{mention.section}"
    if mention.kind == "fr_volume":
        return f"unresolved:fr:{mention.volume}-FR-{mention.page}"
    if mention.kind == "fr_document":
        return f"citation:fr:{mention.document_number}"
    return f"unresolved:{_slug(mention.mention_text)}"


def _citation_node_type(mention: CitationMention, *, resolved_fr: bool) -> GraphNodeType:
    if mention.kind == "cfr":
        return GraphNodeType.CITATION_CFR
    if mention.kind == "usc":
        return GraphNodeType.CITATION_USC
    if mention.kind == "fr_document" and resolved_fr:
        return GraphNodeType.CITATION_FR
    return GraphNodeType.UNRESOLVED_CITATION


# ---------------------------------------------------------------------------
# Graph records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FederalRegisterGraphNode:
    """One projected Federal Register graph node with a deterministic CID."""

    node_type: GraphNodeType
    node_key: str
    label: str
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    document_number: Optional[str] = None
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
            reject_positional_durable_identity(self.legal_id, name="legal_id")
            if node_type in {
                GraphNodeType.UNRESOLVED_CITATION,
                GraphNodeType.RELATED_DOCUMENT,
            } and self.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value:
                if node_type is GraphNodeType.UNRESOLVED_CITATION:
                    raise CitationResolutionError(
                        "unresolved citation nodes must not carry an invented legal_id"
                    )
        if self.entry_cid is not None:
            object.__setattr__(
                self,
                "entry_cid",
                validate_entry_cid(
                    _require_non_empty_str(self.entry_cid, "entry_cid", maximum=256)
                ),
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                _require_non_empty_str(
                    self.document_number, "document_number", maximum=64
                ),
            )
        if not isinstance(self.payload, Mapping):
            raise GraphProjectionError("node payload must be a mapping")
        payload = dict(self.payload)
        object.__setattr__(self, "payload", MappingProxyType(payload))
        identity = {
            "document_number": self.document_number,
            "entry_cid": self.entry_cid,
            "label": self.label,
            "legal_id": self.legal_id,
            "node_key": self.node_key,
            "node_type": self.node_type.value,
            "ontology_version": self.ontology_version,
            "payload": payload,
            "schema_version": self.schema_version,
        }
        cid = self.node_cid or sha256_cid(
            {"kind": "federal_register_graph_node", **identity}
        )
        object.__setattr__(self, "node_cid", cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
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
class FederalRegisterGraphEdge:
    """One projected Federal Register graph edge with a deterministic CID."""

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
                self, "resolution_status", ResolutionStatus.coerce(self.resolution_status)
            )
        if not isinstance(self.payload, Mapping):
            raise GraphProjectionError("edge payload must be a mapping")
        payload = dict(self.payload)
        if edge_type in SIMILARITY_EDGE_TYPES:
            payload.setdefault("authority", NON_AUTHORITATIVE_AUTHORITY)
        object.__setattr__(self, "payload", MappingProxyType(payload))
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
        cid = self.edge_cid or sha256_cid(
            {"kind": "federal_register_graph_edge", **identity}
        )
        object.__setattr__(self, "edge_cid", cid)

    @property
    def is_legal(self) -> bool:
        return self.edge_type in LEGAL_EDGE_TYPES

    @property
    def is_similarity(self) -> bool:
        return self.edge_type in SIMILARITY_EDGE_TYPES

    def uniqueness_key(self) -> tuple[str, str, str]:
        return (self.edge_type.value, self.source_node_cid, self.target_node_cid)

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


@dataclass(frozen=True, slots=True)
class AdjacencyPointer:
    """One bounded adjacency pointer (summarized; paging is LCR-076)."""

    edge_cid: str
    neighbor_cid: str
    edge_type: str
    score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_type": self.edge_type,
            "neighbor_cid": self.neighbor_cid,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class AdjacencyDescriptor:
    """Incoming or outgoing adjacency summary for one node."""

    node_cid: str
    node_key: str
    direction: str
    pointers: tuple[AdjacencyPointer, ...]
    page_index: int = 0

    @property
    def pointer_count(self) -> int:
        return len(self.pointers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "node_cid": self.node_cid,
            "node_key": self.node_key,
            "page_index": self.page_index,
            "pointer_count": self.pointer_count,
            "pointers": [item.to_dict() for item in self.pointers],
        }


@dataclass(frozen=True, slots=True)
class GraphPath:
    source_key: str
    target_key: str
    edge_types: tuple[str, ...]
    node_keys: tuple[str, ...]
    edge_cids: tuple[str, ...]
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
class FederalRegisterGraphProjection:
    """Deterministic Federal Register ontology projection plus adjacency summaries."""

    nodes: tuple[FederalRegisterGraphNode, ...]
    edges: tuple[FederalRegisterGraphEdge, ...]
    outgoing: tuple[AdjacencyDescriptor, ...]
    incoming: tuple[AdjacencyDescriptor, ...]
    skipped_row_count: int = 0
    config: FederalRegisterGraphConfig = field(default_factory=default_graph_config)
    ontology_version: str = ONTOLOGY_VERSION
    schema_version: str = SCHEMA_VERSION
    citation_parser_version: str = CITATION_PARSER_VERSION
    corpus_root_cid: Optional[str] = None

    def __post_init__(self) -> None:
        nodes = tuple(
            sorted(
                self.nodes,
                key=lambda item: (item.node_type.value, item.node_key, item.node_cid),
            )
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
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        if not nodes:
            raise GraphProjectionError("cannot project an empty graph")
        seen_keys: set[str] = set()
        seen_cids: set[str] = set()
        for node in nodes:
            if node.node_key in seen_keys:
                raise GraphProjectionError(f"duplicate node_key {node.node_key!r}")
            if node.node_cid in seen_cids:
                raise GraphProjectionError(f"duplicate node_cid {node.node_cid!r}")
            seen_keys.add(node.node_key)
            seen_cids.add(node.node_cid)
        seen_edge_cids: set[str] = set()
        seen_pairs: set[tuple[str, str, str]] = set()
        for edge in edges:
            if edge.edge_cid in seen_edge_cids:
                raise GraphProjectionError(f"duplicate edge_cid {edge.edge_cid!r}")
            key = edge.uniqueness_key()
            if key in seen_pairs:
                raise GraphProjectionError(
                    "duplicate edge "
                    f"{edge.edge_type.value} {edge.source_node_cid}->{edge.target_node_cid}"
                )
            seen_edge_cids.add(edge.edge_cid)
            seen_pairs.add(key)
        object.__setattr__(
            self,
            "outgoing",
            tuple(sorted(self.outgoing, key=lambda item: (item.node_cid, item.page_index))),
        )
        object.__setattr__(
            self,
            "incoming",
            tuple(sorted(self.incoming, key=lambda item: (item.node_cid, item.page_index))),
        )
        self.assert_semantics_disjoint()
        assert_endpoint_closure(self)
        assert_edge_uniqueness(self)
        assert_adjacency_inversion(self)
        assert_family_bounds(self, config=self.config)
        assert_unresolved_reference_accounting(self)

    @property
    def graph_cid(self) -> str:
        return sha256_cid(
            {
                "edges": [item.edge_cid for item in self.edges],
                "nodes": [item.node_cid for item in self.nodes],
                "ontology_version": self.ontology_version,
                "schema_version": self.schema_version,
            }
        )

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def legal_edge_count(self) -> int:
        return sum(1 for item in self.edges if item.is_legal)

    @property
    def similarity_edge_count(self) -> int:
        return sum(1 for item in self.edges if item.is_similarity)

    @property
    def unresolved_count(self) -> int:
        return sum(
            1
            for item in self.nodes
            if item.node_type is GraphNodeType.UNRESOLVED_CITATION
        )

    @property
    def unresolved_related_count(self) -> int:
        return sum(
            1
            for item in self.nodes
            if item.node_type is GraphNodeType.RELATED_DOCUMENT
            and item.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value
        )

    @property
    def document_count(self) -> int:
        return sum(1 for item in self.nodes if item.node_type is GraphNodeType.DOCUMENT)

    def node_by_key(self) -> dict[str, FederalRegisterGraphNode]:
        return {item.node_key: item for item in self.nodes}

    def node_by_cid(self) -> dict[str, FederalRegisterGraphNode]:
        return {item.node_cid: item for item in self.nodes}

    def nodes_of_type(self, node_type: GraphNodeType | str) -> tuple[FederalRegisterGraphNode, ...]:
        wanted = GraphNodeType.coerce(node_type)
        return tuple(item for item in self.nodes if item.node_type is wanted)

    def missing_coverage_node_types(self) -> list[str]:
        present = {item.node_type.value for item in self.nodes}
        return [name for name in REQUIRED_COVERAGE_NODE_TYPES if name not in present]

    def assert_coverage(self) -> None:
        missing = self.missing_coverage_node_types()
        if missing:
            raise GraphCoverageError(
                "projection is missing required coverage node types: "
                f"{missing}"
            )

    def assert_semantics_disjoint(self) -> None:
        assert_legal_similarity_disjoint()
        for edge in self.edges:
            if edge.is_similarity and edge.edge_class is not GraphEdgeClass.SIMILARITY:
                raise LegalSimilarityCollisionError(
                    f"similarity edge {edge.edge_type.value} not classified as similarity"
                )
            if edge.is_legal and edge.edge_class is GraphEdgeClass.SIMILARITY:
                raise LegalSimilarityCollisionError(
                    f"legal edge {edge.edge_type.value} classified as similarity"
                )
            if edge.is_similarity and edge.payload.get("authority") != NON_AUTHORITATIVE_AUTHORITY:
                raise LegalSimilarityCollisionError(
                    f"similarity edge {edge.edge_type.value} missing non-authoritative label"
                )

    def family_counts(self) -> dict[str, int]:
        counts = {
            "graph": self.document_count,
            "graph_nodes": self.node_count,
            "graph_edges": self.edge_count,
            "graph_adjacency_in": len(self.incoming),
            "graph_adjacency_out": len(self.outgoing),
            "legal_edges": self.legal_edge_count,
            "similarity_edges": self.similarity_edge_count,
            "unresolved_citations": self.unresolved_count,
            "unresolved_related_documents": self.unresolved_related_count,
        }
        for node_type in GraphNodeType:
            counts[f"nodes_{node_type.value}"] = sum(
                1 for item in self.nodes if item.node_type is node_type
            )
        return counts

    def adjacency_summary(self) -> dict[str, Any]:
        max_out = max((item.pointer_count for item in self.outgoing), default=0)
        max_in = max((item.pointer_count for item in self.incoming), default=0)
        return {
            "full_paging": ADJACENCY_PAGING_TASK_ID,
            "incoming_descriptor_count": len(self.incoming),
            "max_incoming_pointers": max_in,
            "max_outgoing_pointers": max_out,
            "outgoing_descriptor_count": len(self.outgoing),
            "sorted_by": ADJACENCY_SORTED_BY,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "citation_parser_version": self.citation_parser_version,
            "corpus_root_cid": self.corpus_root_cid,
            "document_count": self.document_count,
            "edge_count": self.edge_count,
            "family_counts": self.family_counts(),
            "graph_cid": self.graph_cid,
            "legal_edge_count": self.legal_edge_count,
            "node_count": self.node_count,
            "ontology_version": self.ontology_version,
            "primary_key": PRIMARY_KEY,
            "schema_version": self.schema_version,
            "similarity_edge_count": self.similarity_edge_count,
            "skipped_row_count": self.skipped_row_count,
            "task_id": TASK_ID,
            "unresolved_count": self.unresolved_count,
            "unresolved_related_count": self.unresolved_related_count,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency_summary": self.adjacency_summary(),
            "citation_parser_version": self.citation_parser_version,
            "edges": [item.to_dict() for item in self.edges],
            "graph_cid": self.graph_cid,
            "incoming": [item.to_dict() for item in self.incoming],
            "legal_edge_count": self.legal_edge_count,
            "nodes": [item.to_dict() for item in self.nodes],
            "ontology_version": self.ontology_version,
            "outgoing": [item.to_dict() for item in self.outgoing],
            "schema_version": self.schema_version,
            "similarity_edge_count": self.similarity_edge_count,
            "skipped_row_count": self.skipped_row_count,
            "unresolved_count": self.unresolved_count,
        }


# ---------------------------------------------------------------------------
# Corpus row
# ---------------------------------------------------------------------------


def _is_excluded_row(value: Mapping[str, Any]) -> bool:
    if value.get("is_recovery") is True:
        return True
    disposition = str(value.get("disposition") or value.get("admission_status") or "admitted")
    text = disposition.strip().lower().replace("-", "_")
    if text in GRAPH_FAMILY_EXCLUDED_DISPOSITIONS:
        return True
    if value.get("configuration") in GRAPH_FAMILY_EXCLUDED_DISPOSITIONS:
        return True
    return False


@dataclass(frozen=True, slots=True)
class GraphCorpusRow:
    """One admitted Federal Register document eligible for graph projection."""

    entry_cid: str
    legal_id: str
    document_number: str
    publication_date: str
    document_type: str
    text: str
    agencies: tuple[str, ...] = ()
    docket_ids: tuple[str, ...] = ()
    regulation_id_numbers: tuple[str, ...] = ()
    title: str = ""
    source_cid: Optional[str] = None
    official_source_url: Optional[str] = None
    acquisition_receipt_id: Optional[str] = None
    parser_version: Optional[str] = None
    observed_at: Optional[str] = None
    release_point: Optional[str] = None
    correction_relation: str = "none"
    related_document_number: Optional[str] = None
    related_document_numbers: tuple[str, ...] = ()
    cfr_references: tuple[str, ...] = ()
    usc_references: tuple[str, ...] = ()
    fr_references: tuple[str, ...] = ()
    effective_date: Optional[str] = None
    year_month: Optional[str] = None
    source_checksum: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entry_cid",
            validate_entry_cid(_require_non_empty_str(self.entry_cid, "entry_cid", maximum=256)),
        )
        legal_id = _require_non_empty_str(self.legal_id, "legal_id", maximum=768)
        reject_positional_durable_identity(legal_id, name="legal_id")
        object.__setattr__(self, "legal_id", legal_id)
        object.__setattr__(
            self,
            "document_number",
            _require_non_empty_str(self.document_number, "document_number", maximum=64),
        )
        object.__setattr__(
            self,
            "publication_date",
            _require_non_empty_str(self.publication_date, "publication_date", maximum=32),
        )
        object.__setattr__(
            self,
            "document_type",
            _require_non_empty_str(self.document_type, "document_type", maximum=64),
        )
        if not isinstance(self.text, str):
            raise GraphProjectionError("text must be a string")
        if "\x00" in self.text:
            raise GraphProjectionError("text must not contain NUL")
        if self.source_cid is not None:
            object.__setattr__(
                self,
                "source_cid",
                validate_entry_cid(
                    _require_non_empty_str(self.source_cid, "source_cid", maximum=256),
                    name="source_cid",
                ),
            )
        object.__setattr__(self, "agencies", tuple(item for item in self.agencies if item))
        object.__setattr__(self, "docket_ids", tuple(item for item in self.docket_ids if item))
        object.__setattr__(
            self,
            "regulation_id_numbers",
            tuple(item.upper() for item in self.regulation_id_numbers if item),
        )

    @property
    def document_key(self) -> str:
        return f"document:{self.legal_id}"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphCorpusRow":
        if not isinstance(value, Mapping):
            raise GraphProjectionError("corpus row must be a mapping")
        text = str(
            value.get("text")
            or value.get("body")
            or value.get("exclusive_text")
            or ""
        )
        legal_id = value.get("legal_id") or ""
        document_number = value.get("document_number") or ""
        publication_date = value.get("publication_date") or ""
        if not legal_id and document_number and publication_date:
            legal_id = f"fr:{document_number}:{publication_date}"
        entry_cid = value.get("parent_entry_cid") or value.get("entry_cid") or ""
        related = list(_as_str_tuple(value.get("related_document_numbers")))
        related_one = value.get("related_document_number")
        if related_one:
            related.append(str(related_one))
        rins = _as_str_tuple(
            value.get("regulation_id_numbers") or value.get("rins") or value.get("rin")
        )
        dockets = _as_str_tuple(value.get("docket_ids") or value.get("dockets") or value.get("docket"))
        agencies = _as_str_tuple(value.get("agencies") or value.get("agency"))
        return cls(
            entry_cid=str(entry_cid),
            legal_id=str(legal_id),
            document_number=str(document_number),
            publication_date=str(publication_date),
            document_type=str(value.get("document_type") or "notice"),
            text=text,
            agencies=agencies,
            docket_ids=dockets,
            regulation_id_numbers=rins,
            title=str(value.get("title") or ""),
            source_cid=value.get("source_cid"),
            official_source_url=_optional_str(value.get("official_source_url")),
            acquisition_receipt_id=_optional_str(value.get("acquisition_receipt_id")),
            parser_version=_optional_str(value.get("parser_version")),
            observed_at=_optional_str(value.get("observed_at") or value.get("acquisition_time")),
            release_point=_optional_str(value.get("release_point")),
            correction_relation=str(value.get("correction_relation") or "none"),
            related_document_number=_optional_str(related_one) if related_one else None,
            related_document_numbers=tuple(dict.fromkeys(related)),
            cfr_references=_as_str_tuple(value.get("cfr_references")),
            usc_references=_as_str_tuple(value.get("usc_references")),
            fr_references=_as_str_tuple(value.get("fr_references")),
            effective_date=_optional_str(value.get("effective_date")),
            year_month=_optional_str(value.get("year_month")),
            source_checksum=_optional_str(value.get("source_checksum") or value.get("official_content_hash")),
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

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SimilarityNeighbor":
        if not isinstance(value, Mapping):
            raise GraphProjectionError("similarity neighbor must be a mapping")
        return cls(
            source_legal_id=str(value.get("source_legal_id") or ""),
            target_legal_id=str(value.get("target_legal_id") or ""),
            score=float(value.get("score") or 0.0),
            edge_type=GraphEdgeType.coerce(value.get("edge_type") or GraphEdgeType.BM25_NEIGHBOR_OF),
            metric=str(value.get("metric") or "bm25"),
            config_cid=_optional_str(value.get("config_cid")),
        )


# ---------------------------------------------------------------------------
# Projector
# ---------------------------------------------------------------------------


class FederalRegisterGraphProjector:
    """Project admitted Federal Register documents into the legal ontology graph."""

    def __init__(
        self,
        ontology: GraphOntology | None = None,
        config: FederalRegisterGraphConfig | None = None,
    ) -> None:
        self.ontology = ontology or GRAPH_ONTOLOGY
        self.config = config or default_graph_config()

    def project(
        self,
        rows: Sequence[GraphCorpusRow | Mapping[str, Any]] | MaterializedCorpus,
        *,
        similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
        corpus_root_cid: Optional[str] = None,
        require_coverage: bool = False,
    ) -> FederalRegisterGraphProjection:
        admitted, skipped = self._admit_rows(rows)
        if not admitted:
            raise GraphProjectionError("cannot project an empty corpus")

        known_legal_ids = {row.legal_id: row for row in admitted}
        known_document_numbers = {row.document_number: row for row in admitted}
        nodes: dict[str, FederalRegisterGraphNode] = {}
        edges: list[FederalRegisterGraphEdge] = []

        for row in admitted:
            self._project_document(nodes, edges, row)

        for row in admitted:
            self._project_citations(
                nodes,
                edges,
                row,
                known_document_numbers=known_document_numbers,
            )
            self._project_relations(
                nodes,
                edges,
                row,
                known_legal_ids=known_legal_ids,
                known_document_numbers=known_document_numbers,
            )

        for neighbor in similarity_neighbors or ():
            sim = (
                neighbor
                if isinstance(neighbor, SimilarityNeighbor)
                else SimilarityNeighbor.from_mapping(neighbor)
            )
            src_key = f"document:{sim.source_legal_id}"
            tgt_key = f"document:{sim.target_legal_id}"
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

        unique_edges: dict[tuple[str, str, str], FederalRegisterGraphEdge] = {}
        for edge in edges:
            unique_edges.setdefault(edge.uniqueness_key(), edge)

        outgoing, incoming = build_adjacency_descriptors(
            nodes.values(),
            unique_edges.values(),
            max_pointers=self.config.max_adjacency_pointers_per_row,
        )
        projection = FederalRegisterGraphProjection(
            nodes=tuple(nodes.values()),
            edges=tuple(unique_edges.values()),
            outgoing=outgoing,
            incoming=incoming,
            skipped_row_count=skipped,
            config=self.config,
            corpus_root_cid=corpus_root_cid,
        )
        if require_coverage:
            projection.assert_coverage()
        return projection

    def _admit_rows(
        self,
        rows: Sequence[GraphCorpusRow | Mapping[str, Any]] | MaterializedCorpus,
    ) -> tuple[list[GraphCorpusRow], int]:
        raw_rows = _coerce_source_rows(rows)
        admitted: list[GraphCorpusRow] = []
        skipped = 0
        seen: set[str] = set()
        for item in raw_rows:
            if isinstance(item, GraphCorpusRow):
                row = item
            else:
                if _is_excluded_row(item):
                    skipped += 1
                    continue
                row = GraphCorpusRow.from_mapping(item)
            if row.legal_id in seen:
                continue
            seen.add(row.legal_id)
            admitted.append(row)
        return admitted, skipped

    def _ensure_node(
        self,
        nodes: dict[str, FederalRegisterGraphNode],
        *,
        node_type: GraphNodeType,
        node_key: str,
        label: str,
        legal_id: Optional[str] = None,
        entry_cid: Optional[str] = None,
        document_number: Optional[str] = None,
        payload: Mapping[str, Any] | None = None,
    ) -> FederalRegisterGraphNode:
        existing = nodes.get(node_key)
        if existing is not None:
            return existing
        node = FederalRegisterGraphNode(
            node_type=node_type,
            node_key=node_key,
            label=label,
            legal_id=legal_id,
            entry_cid=entry_cid,
            document_number=document_number,
            payload=dict(payload or {}),
        )
        nodes[node_key] = node
        return node

    def _edge(
        self,
        edge_type: GraphEdgeType,
        source: FederalRegisterGraphNode,
        target: FederalRegisterGraphNode,
        *,
        source_span: SourceSpan | None = None,
        resolution_status: ResolutionStatus | None = None,
        weight: float | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> FederalRegisterGraphEdge:
        edge_class = self.ontology.validate_edge(
            edge_type, source.node_type, target.node_type
        )
        return FederalRegisterGraphEdge(
            edge_type=edge_type,
            source_node_cid=source.node_cid,
            target_node_cid=target.node_cid,
            edge_class=edge_class,
            source_span=source_span,
            resolution_status=resolution_status,
            weight=weight,
            payload=dict(payload or {}),
        )

    def _project_document(
        self,
        nodes: dict[str, FederalRegisterGraphNode],
        edges: list[FederalRegisterGraphEdge],
        row: GraphCorpusRow,
    ) -> None:
        document = self._ensure_node(
            nodes,
            node_type=GraphNodeType.DOCUMENT,
            node_key=row.document_key,
            label=row.title or row.legal_id,
            legal_id=row.legal_id,
            entry_cid=row.entry_cid,
            document_number=row.document_number,
            payload={
                "document_type": row.document_type,
                "publication_date": row.publication_date,
                "year_month": row.year_month or row.publication_date[:7],
            },
        )
        for agency in row.agencies:
            agency_key = f"agency:{_slug(agency)}"
            agency_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.AGENCY,
                node_key=agency_key,
                label=agency,
                payload={"name": agency, "slug": _slug(agency)},
            )
            edges.append(self._edge(GraphEdgeType.ISSUED_BY, document, agency_node))

        docket_ids = list(row.docket_ids)
        for docket, _start, _end in extract_docket_mentions(row.text):
            if docket not in docket_ids:
                docket_ids.append(docket)
        for docket in docket_ids:
            docket_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.DOCKET,
                node_key=f"docket:{docket}",
                label=docket,
                payload={"docket_id": docket},
            )
            edges.append(self._edge(GraphEdgeType.HAS_DOCKET, document, docket_node))

        rins = list(row.regulation_id_numbers)
        for rin, _start, _end in extract_rin_mentions(row.text):
            if rin not in rins:
                rins.append(rin)
        for rin in rins:
            rin_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.RIN,
                node_key=f"rin:{rin}",
                label=rin,
                payload={"regulation_id_number": rin},
            )
            edges.append(self._edge(GraphEdgeType.HAS_RIN, document, rin_node))

        date_node = self._ensure_node(
            nodes,
            node_type=GraphNodeType.DATE,
            node_key=f"date:{row.publication_date}",
            label=row.publication_date,
            payload={"date": row.publication_date, "role": "publication_date"},
        )
        edges.append(self._edge(GraphEdgeType.PUBLISHED_ON, document, date_node))
        if row.effective_date:
            effective_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.DATE,
                node_key=f"date:{row.effective_date}",
                label=row.effective_date,
                payload={"date": row.effective_date, "role": "effective_date"},
            )
            edges.append(self._edge(GraphEdgeType.EFFECTIVE_ON, document, effective_node))

        if row.source_cid:
            source_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.SOURCE,
                node_key=f"source:{row.source_cid}",
                label=row.official_source_url or row.source_cid,
                payload={
                    "official_source_url": row.official_source_url,
                    "source_cid": row.source_cid,
                    "source_checksum": row.source_checksum,
                },
            )
            edges.append(self._edge(GraphEdgeType.HAS_SOURCE, document, source_node))
            edges.append(self._edge(GraphEdgeType.DERIVED_FROM, document, source_node))

        provenance_payload = {
            "acquisition_receipt_id": row.acquisition_receipt_id,
            "entry_cid": row.entry_cid,
            "observed_at": row.observed_at,
            "official_source_url": row.official_source_url,
            "parser_version": row.parser_version,
            "release_point": row.release_point,
            "source_cid": row.source_cid,
        }
        provenance_digest = digest_mapping(provenance_payload)
        provenance_node = self._ensure_node(
            nodes,
            node_type=GraphNodeType.PROVENANCE,
            node_key=f"provenance:{provenance_digest}",
            label=row.acquisition_receipt_id or row.entry_cid,
            payload=provenance_payload,
        )
        edges.append(self._edge(GraphEdgeType.HAS_PROVENANCE, document, provenance_node))

    def _project_citations(
        self,
        nodes: dict[str, FederalRegisterGraphNode],
        edges: list[FederalRegisterGraphEdge],
        row: GraphCorpusRow,
        *,
        known_document_numbers: Mapping[str, GraphCorpusRow],
    ) -> None:
        document = nodes[row.document_key]
        mentions: list[CitationMention] = []
        mentions.extend(extract_citation_mentions(row.text, field="text"))
        mentions.extend(extract_citation_mentions(row.title, field="title"))
        for raw in row.cfr_references:
            mentions.append(
                CitationMention(
                    kind="cfr",
                    mention_text=raw,
                    start=0,
                    end=len(raw),
                    field="cfr_references",
                    **_parse_structured_cfr(raw),
                )
            )
        for raw in row.usc_references:
            mentions.append(
                CitationMention(
                    kind="usc",
                    mention_text=raw,
                    start=0,
                    end=len(raw),
                    field="usc_references",
                    **_parse_structured_usc(raw),
                )
            )
        for raw in row.fr_references:
            mentions.append(_structured_fr_mention(raw))

        for mention in _drop_contained_mentions(mentions):
            if mention.kind == "fr_document" and mention.document_number == row.document_number:
                continue
            if mention.field in {"text", "title"}:
                source_text = row.text if mention.field == "text" else row.title
                try:
                    span = SourceSpan.from_occurrence(
                        source_text,
                        mention.mention_text,
                        source_cid=row.source_cid,
                        entry_cid=row.entry_cid,
                        field=mention.field,
                        start_hint=mention.start,
                    )
                except SourceSpanError:
                    span = SourceSpan.from_field_value(
                        mention.mention_text,
                        field=mention.field,
                        source_cid=row.source_cid,
                        entry_cid=row.entry_cid,
                    )
            else:
                span = SourceSpan.from_field_value(
                    mention.mention_text,
                    field=mention.field,
                    source_cid=row.source_cid,
                    entry_cid=row.entry_cid,
                )

            resolved_fr = False
            target_legal_id = None
            if mention.kind == "fr_document" and mention.document_number in known_document_numbers:
                resolved_fr = True
                target_legal_id = known_document_numbers[mention.document_number].legal_id
            node_type = _citation_node_type(mention, resolved_fr=resolved_fr)
            if node_type is GraphNodeType.UNRESOLVED_CITATION:
                node_key = _citation_node_key(mention)
                if not node_key.startswith("unresolved:"):
                    node_key = f"unresolved:{node_key.split(':', 1)[-1]}"
                status = ResolutionStatus.UNRESOLVED
                citation_node = self._ensure_node(
                    nodes,
                    node_type=node_type,
                    node_key=node_key,
                    label=mention.mention_text,
                    payload={
                        "kind": mention.kind,
                        "mention_text": mention.mention_text,
                        "parser_version": CITATION_PARSER_VERSION,
                        "resolution_status": status.value,
                        "section": mention.section,
                        "title": mention.title,
                        "document_number": mention.document_number,
                        "volume": mention.volume,
                        "page": mention.page,
                    },
                )
                edges.append(
                    self._edge(
                        GraphEdgeType.CITES_UNRESOLVED,
                        document,
                        citation_node,
                        source_span=span,
                        resolution_status=status,
                        payload={
                            "parser_version": CITATION_PARSER_VERSION,
                            "mention_text": mention.mention_text,
                        },
                    )
                )
                continue

            node_key = _citation_node_key(mention)
            status = ResolutionStatus.RESOLVED
            citation_node = self._ensure_node(
                nodes,
                node_type=node_type,
                node_key=node_key,
                label=mention.mention_text,
                payload={
                    "kind": mention.kind,
                    "mention_text": mention.mention_text,
                    "parser_version": CITATION_PARSER_VERSION,
                    "resolution_status": status.value,
                    "section": mention.section,
                    "title": mention.title,
                    "document_number": mention.document_number,
                    "target_legal_id": target_legal_id,
                },
            )
            edges.append(
                self._edge(
                    GraphEdgeType.CITES,
                    document,
                    citation_node,
                    source_span=span,
                    resolution_status=status,
                    payload={
                        "parser_version": CITATION_PARSER_VERSION,
                        "mention_text": mention.mention_text,
                    },
                )
            )

    def _project_relations(
        self,
        nodes: dict[str, FederalRegisterGraphNode],
        edges: list[FederalRegisterGraphEdge],
        row: GraphCorpusRow,
        *,
        known_legal_ids: Mapping[str, GraphCorpusRow],
        known_document_numbers: Mapping[str, GraphCorpusRow],
    ) -> None:
        document = nodes[row.document_key]
        targets = list(row.related_document_numbers)
        if row.related_document_number and row.related_document_number not in targets:
            targets.append(row.related_document_number)
        relation = (row.correction_relation or "none").strip().lower().replace("-", "_")
        edge_type = CORRECTION_EDGE_BY_RELATION.get(relation, GraphEdgeType.RELATED_TO)
        if relation == "none" and not targets:
            return
        if relation != "none" and not targets:
            related_key = f"related_document:unresolved:{row.document_number}"
            related_node = self._ensure_node(
                nodes,
                node_type=GraphNodeType.RELATED_DOCUMENT,
                node_key=related_key,
                label=f"unresolved related of {row.document_number}",
                payload={
                    "resolution_status": ResolutionStatus.UNRESOLVED.value,
                    "source_document_number": row.document_number,
                    "relation": relation,
                },
            )
            edges.append(
                self._edge(
                    edge_type,
                    document,
                    related_node,
                    resolution_status=ResolutionStatus.UNRESOLVED,
                    payload={"relation": relation, "invented_target": False},
                )
            )
            return
        for target_number in targets:
            known = known_document_numbers.get(target_number)
            if known is not None:
                target_node = nodes[known.document_key]
                status = ResolutionStatus.RESOLVED
            else:
                related_key = f"related_document:{target_number}"
                target_node = self._ensure_node(
                    nodes,
                    node_type=GraphNodeType.RELATED_DOCUMENT,
                    node_key=related_key,
                    label=target_number,
                    document_number=target_number,
                    payload={
                        "document_number": target_number,
                        "resolution_status": ResolutionStatus.UNRESOLVED.value,
                        "relation": relation,
                    },
                )
                status = ResolutionStatus.UNRESOLVED
            payload = {
                "relation": relation,
                "related_document_number": target_number,
            }
            if status is ResolutionStatus.UNRESOLVED:
                payload["invented_target"] = False
            edges.append(
                self._edge(
                    edge_type if relation != "none" else GraphEdgeType.RELATED_TO,
                    document,
                    target_node,
                    resolution_status=status,
                    payload=payload,
                )
            )


def _parse_structured_cfr(raw: str) -> dict[str, Optional[str]]:
    match = _CFR_RE.search(raw)
    if not match:
        raise CitationResolutionError(f"malformed CFR reference {raw!r}")
    return {"title": str(int(match.group("title"))), "section": match.group("section")}


def _parse_structured_usc(raw: str) -> dict[str, Optional[str]]:
    match = _USC_RE.search(raw)
    if not match:
        raise CitationResolutionError(f"malformed USC reference {raw!r}")
    return {"title": match.group("title"), "section": match.group("section")}


def _structured_fr_mention(raw: str) -> CitationMention:
    volume = _FR_VOLUME_RE.search(raw)
    if volume:
        return CitationMention(
            kind="fr_volume",
            mention_text=raw,
            start=0,
            end=len(raw),
            volume=str(int(volume.group("volume"))),
            page=str(int(volume.group("page"))),
            field="fr_references",
        )
    document = _FR_DOCUMENT_RE.search(raw)
    if document:
        return CitationMention(
            kind="fr_document",
            mention_text=raw,
            start=0,
            end=len(raw),
            document_number=document.group("document_number"),
            field="fr_references",
        )
    raise CitationResolutionError(f"malformed FR reference {raw!r}")


def _coerce_source_rows(
    source: MaterializedCorpus | Sequence[GraphCorpusRow | Mapping[str, Any]] | Iterable[Any],
) -> list[Mapping[str, Any] | GraphCorpusRow]:
    if isinstance(source, MaterializedCorpus):
        return list(rows_from_materialized_corpus(source))
    if isinstance(source, (str, bytes, bytearray)):
        raise GraphProjectionError("corpus rows must be an iterable of mappings")
    rows: list[Mapping[str, Any] | GraphCorpusRow] = []
    for position, row in enumerate(source):
        if isinstance(row, GraphCorpusRow):
            rows.append(row)
            continue
        if isinstance(row, CanonicalChunk):
            payload = row.to_dict()
            payload["disposition"] = "admitted"
            payload["body"] = row.exclusive_text or row.text
            payload["parent_entry_cid"] = row.entry_cid
            rows.append(payload)
            continue
        if not isinstance(row, Mapping):
            raise GraphProjectionError(f"corpus row {position} must be a mapping")
        rows.append(row)
    return rows


def rows_from_materialized_corpus(corpus: MaterializedCorpus) -> list[dict[str, Any]]:
    """Project LCR-055 admitted documents into graph input rows."""

    if not isinstance(corpus, MaterializedCorpus):
        raise GraphProjectionError("corpus must be a MaterializedCorpus")
    lineage = {row.entry_cid: row for row in corpus.source_lineage}
    rows: list[dict[str, Any]] = []
    for record in corpus.corpus_records:
        payload = record.to_dict()
        payload["disposition"] = "admitted"
        extra = lineage.get(record.entry_cid)
        if extra is not None:
            payload.setdefault("official_source_url", extra.official_source_url)
            payload.setdefault("observed_at", extra.observed_at)
            payload.setdefault("release_point", extra.release_point)
            payload.setdefault("acquisition_receipt_id", extra.acquisition_receipt_id)
            payload.setdefault("parser_version", extra.parser_version)
        rows.append(payload)
    if not rows:
        raise GraphCoverageError("materialized corpus emitted no admitted documents")
    return rows


def build_corpus_root_cid(
    rows: MaterializedCorpus | Sequence[Mapping[str, Any]] | Sequence[GraphCorpusRow],
) -> str:
    if isinstance(rows, MaterializedCorpus):
        identities = [
            {
                "entry_cid": record.entry_cid,
                "legal_id": record.legal_id,
                "source_cid": record.source_cid,
            }
            for record in rows.corpus_records
        ]
    else:
        identities = []
        for row in rows:
            if isinstance(row, GraphCorpusRow):
                identities.append(
                    {
                        "entry_cid": row.entry_cid,
                        "legal_id": row.legal_id,
                        "source_cid": row.source_cid,
                    }
                )
                continue
            if isinstance(row, Mapping) and _is_excluded_row(row):
                continue
            mapping = row if isinstance(row, Mapping) else {}
            identities.append(
                {
                    "entry_cid": mapping.get("parent_entry_cid") or mapping.get("entry_cid"),
                    "legal_id": mapping.get("legal_id"),
                    "source_cid": mapping.get("source_cid"),
                }
            )
    identities.sort(key=lambda item: (str(item.get("legal_id") or ""), str(item.get("entry_cid") or "")))
    return sha256_cid({"kind": "federal_register_graph_corpus_root", "rows": identities})


# ---------------------------------------------------------------------------
# Adjacency / acceptance gates
# ---------------------------------------------------------------------------


def build_adjacency_descriptors(
    nodes: Iterable[FederalRegisterGraphNode],
    edges: Iterable[FederalRegisterGraphEdge],
    *,
    max_pointers: int = MAX_ADJACENCY_POINTERS_PER_ROW,
) -> tuple[tuple[AdjacencyDescriptor, ...], tuple[AdjacencyDescriptor, ...]]:
    """Summarize bounded in/out adjacency. Full paging is LCR-076."""

    bound = _validate_physical_bound(
        max_pointers,
        name="max_adjacency_pointers_per_row",
        maximum=MAX_ADJACENCY_POINTERS_PER_ROW,
    )
    by_cid = {node.node_cid: node for node in nodes}
    outgoing_map: dict[str, list[AdjacencyPointer]] = defaultdict(list)
    incoming_map: dict[str, list[AdjacencyPointer]] = defaultdict(list)
    for edge in edges:
        outgoing_map[edge.source_node_cid].append(
            AdjacencyPointer(
                edge_cid=edge.edge_cid,
                neighbor_cid=edge.target_node_cid,
                edge_type=edge.edge_type.value,
                score=edge.weight,
            )
        )
        incoming_map[edge.target_node_cid].append(
            AdjacencyPointer(
                edge_cid=edge.edge_cid,
                neighbor_cid=edge.source_node_cid,
                edge_type=edge.edge_type.value,
                score=edge.weight,
            )
        )

    def _descriptors(
        mapping: Mapping[str, list[AdjacencyPointer]],
        direction: str,
    ) -> list[AdjacencyDescriptor]:
        descriptors: list[AdjacencyDescriptor] = []
        for node_cid, pointers in mapping.items():
            ordered = sorted(
                pointers,
                key=lambda item: (item.edge_type, item.neighbor_cid, item.edge_cid),
            )
            node = by_cid.get(node_cid)
            node_key = node.node_key if node is not None else node_cid
            if not ordered:
                continue
            # Summarize bounded descriptor pages here. Physical parquet paging
            # of those pages is LCR-076.
            page_count = (len(ordered) + bound - 1) // bound
            for page_index in range(page_count):
                start = page_index * bound
                chunk = ordered[start : start + bound]
                if len(chunk) > bound:
                    raise GraphBoundError(
                        f"{direction} adjacency page {page_index} for {node_cid} "
                        f"has {len(chunk)} pointers; exceeds {bound}"
                    )
                descriptors.append(
                    AdjacencyDescriptor(
                        node_cid=node_cid,
                        node_key=node_key,
                        direction=direction,
                        pointers=tuple(chunk),
                        page_index=page_index,
                    )
                )
        return descriptors

    return tuple(_descriptors(outgoing_map, "out")), tuple(_descriptors(incoming_map, "in"))


def assert_endpoint_closure(projection: FederalRegisterGraphProjection) -> None:
    """Fail closed when an edge endpoint is missing from the node set."""

    cids = {node.node_cid for node in projection.nodes}
    for edge in projection.edges:
        if edge.source_node_cid not in cids:
            raise GraphCoverageError(
                f"edge {edge.edge_cid} source {edge.source_node_cid} is not a node"
            )
        if edge.target_node_cid not in cids:
            raise GraphCoverageError(
                f"edge {edge.edge_cid} target {edge.target_node_cid} is not a node"
            )


def assert_edge_uniqueness(projection: FederalRegisterGraphProjection) -> None:
    """Fail closed on duplicate edge CIDs or typed endpoint pairs."""

    cids = [edge.edge_cid for edge in projection.edges]
    if len(cids) != len(set(cids)):
        raise GraphProjectionError("graph edges are not unique by edge_cid")
    pairs = [edge.uniqueness_key() for edge in projection.edges]
    if len(pairs) != len(set(pairs)):
        raise GraphProjectionError("graph edges are not unique by type and endpoints")


def assert_adjacency_inversion(projection: FederalRegisterGraphProjection) -> None:
    """Fail closed unless outgoing is the exact inverse of incoming."""

    outgoing: dict[str, tuple[str, str]] = {}
    incoming: dict[str, tuple[str, str]] = {}
    for descriptor in projection.outgoing:
        if descriptor.direction != "out":
            raise GraphAdjacencyError("outgoing descriptor direction must be out")
        for pointer in descriptor.pointers:
            if pointer.edge_cid in outgoing:
                raise GraphAdjacencyError(
                    f"edge {pointer.edge_cid} appears twice in outgoing adjacency"
                )
            outgoing[pointer.edge_cid] = (descriptor.node_cid, pointer.neighbor_cid)
    for descriptor in projection.incoming:
        if descriptor.direction != "in":
            raise GraphAdjacencyError("incoming descriptor direction must be in")
        for pointer in descriptor.pointers:
            if pointer.edge_cid in incoming:
                raise GraphAdjacencyError(
                    f"edge {pointer.edge_cid} appears twice in incoming adjacency"
                )
            incoming[pointer.edge_cid] = (pointer.neighbor_cid, descriptor.node_cid)
    edge_cids = {edge.edge_cid for edge in projection.edges}
    if set(outgoing) != edge_cids or set(incoming) != edge_cids:
        raise GraphAdjacencyError(
            "adjacency descriptors do not cover every durable edge exactly once"
        )
    for edge in projection.edges:
        expected = (edge.source_node_cid, edge.target_node_cid)
        if outgoing.get(edge.edge_cid) != expected:
            raise GraphAdjacencyError(
                f"outgoing adjacency for {edge.edge_cid} is not source->target"
            )
        if incoming.get(edge.edge_cid) != expected:
            raise GraphAdjacencyError(
                f"incoming adjacency for {edge.edge_cid} is not the inverse of outgoing"
            )


def assert_family_bounds(
    projection: FederalRegisterGraphProjection,
    *,
    config: FederalRegisterGraphConfig | None = None,
) -> None:
    """Fail closed when descriptor pointer counts exceed the physical bound."""

    bounds = config or projection.config
    for descriptor in (*projection.outgoing, *projection.incoming):
        if descriptor.pointer_count > bounds.max_adjacency_pointers_per_row:
            raise GraphBoundError(
                f"{descriptor.direction} adjacency for {descriptor.node_key} "
                f"has {descriptor.pointer_count} pointers; exceeds "
                f"{bounds.max_adjacency_pointers_per_row}"
            )
        if descriptor.pointer_count > MAX_ADJACENCY_POINTERS_PER_ROW:
            raise GraphBoundError("adjacency exceeds the production 4096 pointer bound")
    if bounds.max_rows_per_physical_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise GraphBoundError("physical shard bound must remain <= 4096")


def assert_provenance_paths(projection: FederalRegisterGraphProjection) -> list[GraphPath]:
    """Fail closed unless every document has official provenance and source paths."""

    by_cid = projection.node_by_cid()
    documents = projection.nodes_of_type(GraphNodeType.DOCUMENT)
    if not documents:
        raise GraphCoverageError("graph has no document nodes")
    adjacency: dict[str, list[FederalRegisterGraphEdge]] = defaultdict(list)
    for edge in projection.edges:
        if edge.edge_type in {
            GraphEdgeType.HAS_PROVENANCE,
            GraphEdgeType.HAS_SOURCE,
            GraphEdgeType.DERIVED_FROM,
        }:
            adjacency[edge.source_node_cid].append(edge)
    paths: list[GraphPath] = []
    for document in documents:
        provenance_edges = [
            edge
            for edge in adjacency.get(document.node_cid, ())
            if edge.edge_type is GraphEdgeType.HAS_PROVENANCE
        ]
        source_edges = [
            edge
            for edge in adjacency.get(document.node_cid, ())
            if edge.edge_type in {GraphEdgeType.HAS_SOURCE, GraphEdgeType.DERIVED_FROM}
        ]
        if not provenance_edges:
            raise GraphCoverageError(
                f"document {document.node_key} is missing a HAS_PROVENANCE path"
            )
        if not source_edges:
            raise GraphCoverageError(
                f"document {document.node_key} is missing a HAS_SOURCE/DERIVED_FROM path"
            )
        for edge in provenance_edges:
            target = by_cid[edge.target_node_cid]
            if target.node_type is not GraphNodeType.PROVENANCE:
                raise GraphCoverageError(
                    f"provenance path for {document.node_key} does not end at a provenance node"
                )
            if not (
                target.payload.get("official_source_url")
                or target.payload.get("source_cid")
                or target.payload.get("acquisition_receipt_id")
            ):
                raise GraphCoverageError(
                    f"provenance node {target.node_key} lacks official provenance fields"
                )
            paths.append(
                GraphPath(
                    source_key=document.node_key,
                    target_key=target.node_key,
                    edge_types=(edge.edge_type.value,),
                    node_keys=(document.node_key, target.node_key),
                    edge_cids=(edge.edge_cid,),
                    path_kind="provenance",
                )
            )
        for edge in source_edges:
            target = by_cid[edge.target_node_cid]
            if target.node_type is not GraphNodeType.SOURCE:
                raise GraphCoverageError(
                    f"source path for {document.node_key} does not end at a source node"
                )
            paths.append(
                GraphPath(
                    source_key=document.node_key,
                    target_key=target.node_key,
                    edge_types=(edge.edge_type.value,),
                    node_keys=(document.node_key, target.node_key),
                    edge_cids=(edge.edge_cid,),
                    path_kind="provenance",
                )
            )
    return paths


def assert_unresolved_reference_accounting(
    projection: FederalRegisterGraphProjection,
) -> dict[str, int]:
    """Fail closed when unresolved references invent targets or drift in count."""

    unresolved_nodes = [
        node
        for node in projection.nodes
        if node.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    unresolved_edges = [
        edge
        for edge in projection.edges
        if edge.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    for node in unresolved_nodes:
        if node.legal_id is not None:
            raise CitationResolutionError(
                f"unresolved citation {node.node_key} invented legal_id {node.legal_id!r}"
            )
        if node.payload.get("resolution_status") != ResolutionStatus.UNRESOLVED.value:
            raise CitationResolutionError(
                f"unresolved citation {node.node_key} is missing unresolved status"
            )
        if not node.payload.get("mention_text"):
            raise CitationResolutionError(
                f"unresolved citation {node.node_key} is missing mention evidence"
            )
        if node.payload.get("parser_version") != CITATION_PARSER_VERSION:
            raise CitationResolutionError(
                f"unresolved citation {node.node_key} is missing parser version"
            )
    for edge in unresolved_edges:
        if edge.resolution_status is not ResolutionStatus.UNRESOLVED:
            raise CitationResolutionError(
                f"CITES_UNRESOLVED {edge.edge_cid} is not labeled unresolved"
            )
        if edge.source_span is None:
            raise SourceSpanError(f"CITES_UNRESOLVED {edge.edge_cid} lacks a source span")
    related_unresolved = [
        node
        for node in projection.nodes
        if node.node_type is GraphNodeType.RELATED_DOCUMENT
        and node.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value
    ]
    for node in related_unresolved:
        if node.legal_id is not None:
            raise CitationResolutionError(
                f"unresolved related document {node.node_key} invented legal_id"
            )
        if node.payload.get("invented_target") is True:
            raise CitationResolutionError(
                f"unresolved related document {node.node_key} invented a target"
            )
    if projection.unresolved_count != len(unresolved_nodes):
        raise GraphCoverageError("unresolved citation count drifted")
    return {
        "unresolved_citations": len(unresolved_nodes),
        "unresolved_citation_edges": len(unresolved_edges),
        "unresolved_related_documents": len(related_unresolved),
    }


def find_graph_paths(
    projection: FederalRegisterGraphProjection,
    *,
    max_depth: int = 4,
    legal_only: bool = True,
    source_keys: Iterable[str] | None = None,
    target_keys: Iterable[str] | None = None,
) -> list[GraphPath]:
    if max_depth < 1:
        raise GraphProjectionError("max_depth must be >= 1")
    by_cid = projection.node_by_cid()
    by_key = projection.node_by_key()
    adjacency: dict[str, list[FederalRegisterGraphEdge]] = defaultdict(list)
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
    paths.sort(key=lambda item: (item.source_key, item.target_key, item.edge_types, item.node_keys))
    return paths


# ---------------------------------------------------------------------------
# Public projectors
# ---------------------------------------------------------------------------


def project_federal_register_graph(
    rows: Sequence[GraphCorpusRow | Mapping[str, Any]] | MaterializedCorpus,
    *,
    similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
    config: FederalRegisterGraphConfig | None = None,
    corpus_root_cid: Optional[str] = None,
    require_coverage: bool = False,
) -> FederalRegisterGraphProjection:
    projector = FederalRegisterGraphProjector(config=config)
    root = corpus_root_cid or build_corpus_root_cid(rows)
    return projector.project(
        rows,
        similarity_neighbors=similarity_neighbors,
        corpus_root_cid=root,
        require_coverage=require_coverage,
    )


def project_federal_register_graph_from_corpus(
    corpus: MaterializedCorpus,
    *,
    config: FederalRegisterGraphConfig | None = None,
    similarity_neighbors: Sequence[SimilarityNeighbor | Mapping[str, Any]] | None = None,
) -> FederalRegisterGraphProjection:
    if not isinstance(corpus, MaterializedCorpus):
        raise GraphProjectionError("corpus must be a MaterializedCorpus")
    return project_federal_register_graph(
        corpus,
        similarity_neighbors=similarity_neighbors,
        config=config,
        corpus_root_cid=build_corpus_root_cid(corpus),
        require_coverage=False,
    )


def reconcile_roots(
    projection: FederalRegisterGraphProjection,
    *,
    expected_corpus_root_cid: str,
) -> dict[str, Any]:
    if projection.corpus_root_cid != expected_corpus_root_cid:
        raise GraphCoverageError(
            "graph corpus_root_cid does not reconcile with admitted documents: "
            f"{projection.corpus_root_cid!r} != {expected_corpus_root_cid!r}"
        )
    return {
        "corpus_root_cid": projection.corpus_root_cid,
        "document_count": projection.document_count,
        "reconciled": True,
    }


# ---------------------------------------------------------------------------
# Compact sealed fixture recipe
# ---------------------------------------------------------------------------


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def fixture_graph_rows() -> list[dict[str, Any]]:
    """Compact admitted Federal Register document sample for sealed unit fixtures."""

    return [
        {
            "entry_cid": _cid("a"),
            "source_cid": _cid("b"),
            "legal_id": "fr:2026-04567:2026-03-16:type=rule",
            "document_number": "2026-04567",
            "document_type": "rule",
            "publication_date": "2026-03-16",
            "effective_date": "2026-04-15",
            "year_month": "2026-03",
            "agencies": ["Environmental Protection Agency"],
            "docket_ids": ["EPA-HQ-OAR-2026-0001"],
            "regulation_id_numbers": ["2060-AV00"],
            "title": "EPA emissions reporting rule",
            "body": (
                "The Environmental Protection Agency adopts emissions reporting "
                "requirements for stationary sources under 40 C.F.R. § 98.1 and "
                "42 U.S.C. § 7412. Docket EPA-HQ-OAR-2026-0001; RIN 2060-AV00. "
                "See also 91 FR 99999. Unique token epaemissionsrule."
            ),
            "official_source_url": "https://www.federalregister.gov/documents/2026/03/16/2026-04567",
            "acquisition_receipt_id": "fr-acquire-2026-03",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "aa" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("c"),
            "source_cid": _cid("d"),
            "legal_id": "fr:2026-04568:2026-03-16:type=proposed_rule",
            "document_number": "2026-04568",
            "document_type": "proposed_rule",
            "publication_date": "2026-03-16",
            "year_month": "2026-03",
            "agencies": ["Environmental Protection Agency"],
            "docket_ids": ["EPA-HQ-OAR-2026-0001"],
            "regulation_id_numbers": ["2060-AV00"],
            "title": "EPA proposed emissions amendments",
            "body": (
                "EPA proposes amendments to emissions reporting for mobile "
                "sources under 40 CFR 98.2. Docket EPA-HQ-OAR-2026-0001; "
                "RIN 2060-AV00. Unique token epaproposedrule."
            ),
            "official_source_url": "https://www.federalregister.gov/documents/2026/03/16/2026-04568",
            "acquisition_receipt_id": "fr-acquire-2026-03",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "cc" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("e"),
            "source_cid": _cid("f"),
            "legal_id": "fr:2026-05001:2026-03-20:type=notice",
            "document_number": "2026-05001",
            "document_type": "notice",
            "publication_date": "2026-03-20",
            "year_month": "2026-03",
            "agencies": ["Department of Transportation"],
            "docket_ids": ["DOT-OST-2026-0002"],
            "title": "DOT freight corridor notice",
            "body": (
                "The Department of Transportation publishes a freight corridor "
                "notice citing 49 U.S.C. § 5301. Docket DOT-OST-2026-0002. "
                "Unique token dotnoticeunique."
            ),
            "official_source_url": "https://www.federalregister.gov/documents/2026/03/20/2026-05001",
            "acquisition_receipt_id": "fr-acquire-2026-03",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "ee" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("1"),
            "source_cid": _cid("2"),
            "legal_id": "fr:2026-06010:2026-04-02:type=rule",
            "document_number": "2026-06010",
            "document_type": "rule",
            "publication_date": "2026-04-02",
            "year_month": "2026-04",
            "agencies": ["Department of Agriculture"],
            "docket_ids": ["AMS-NOP-2026-0003"],
            "regulation_id_numbers": ["0581-AE00"],
            "title": "USDA organic labeling rule",
            "body": (
                "USDA amends organic labeling. Docket AMS-NOP-2026-0003; "
                "RIN 0581-AE00. Unique token usdaorganicrule."
            ),
            "official_source_url": "https://www.federalregister.gov/documents/2026/04/02/2026-06010",
            "acquisition_receipt_id": "fr-acquire-2026-04",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "11" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("3"),
            "source_cid": _cid("4"),
            "legal_id": "fr:2026-06111:2026-04-08:type=proposed_rule",
            "document_number": "2026-06111",
            "document_type": "proposed_rule",
            "publication_date": "2026-04-08",
            "year_month": "2026-04",
            "agencies": ["Department of Health and Human Services"],
            "docket_ids": ["HHS-OS-2026-0004"],
            "regulation_id_numbers": ["0910-AI00"],
            "title": "HHS coverage proposed rule",
            "body": (
                "HHS proposes coverage amendments. Docket HHS-OS-2026-0004; "
                "RIN 0910-AI00. Unique token hhsproposedrule."
            ),
            "official_source_url": "https://www.federalregister.gov/documents/2026/04/08/2026-06111",
            "acquisition_receipt_id": "fr-acquire-2026-04",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "33" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("5"),
            "source_cid": _cid("6"),
            "legal_id": "fr:2026-07001:2026-06-01:type=notice:rel=corrects:related=2026-04567",
            "document_number": "2026-07001",
            "document_type": "notice",
            "publication_date": "2026-06-01",
            "year_month": "2026-06",
            "agencies": ["Environmental Protection Agency"],
            "title": "EPA correction notice",
            "body": (
                "EPA issues a correction notice that corrects 2026-04567. "
                "Unique token epacorrectionnotice."
            ),
            "correction_relation": "corrects",
            "related_document_number": "2026-04567",
            "official_source_url": "https://www.federalregister.gov/documents/2026/06/01/2026-07001",
            "acquisition_receipt_id": "fr-acquire-2026-06",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "55" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("7"),
            "source_cid": _cid("8"),
            "legal_id": "fr:2026-07100:2026-06-12:type=rule",
            "document_number": "2026-07100",
            "document_type": "rule",
            "publication_date": "2026-06-12",
            "year_month": "2026-06",
            "agencies": ["Department of Commerce"],
            "docket_ids": ["DOC-BIS-2026-0005"],
            "title": "Commerce export controls rule",
            "body": (
                "Commerce amends export controls citing 15 U.S.C. § 78j. "
                "Docket DOC-BIS-2026-0005. Unique token commerceruleunique."
            ),
            "related_document_numbers": ["2026-99999"],
            "official_source_url": "https://www.federalregister.gov/documents/2026/06/12/2026-07100",
            "acquisition_receipt_id": "fr-acquire-2026-06",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "77" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": _cid("9"),
            "source_cid": _cid("0"),
            "legal_id": "fr:2026-07222:2026-06-18:type=notice",
            "document_number": "2026-07222",
            "document_type": "notice",
            "publication_date": "2026-06-18",
            "year_month": "2026-06",
            "agencies": ["Department of the Interior"],
            "title": "Interior public lands notice",
            "body": (
                "Interior publishes a public lands notice citing 43 U.S.C. § 1701 "
                "and Federal Register document 2026-04567. Unique token "
                "interiornoticeunique."
            ),
            "fr_references": ["2026-04567"],
            "official_source_url": "https://www.federalregister.gov/documents/2026/06/18/2026-07222",
            "acquisition_receipt_id": "fr-acquire-2026-06",
            "parser_version": "federal-register-parser/v2",
            "observed_at": "2026-08-10T12:00:00Z",
            "release_point": "fr/cutoff/2026-08-10",
            "source_checksum": "99" * 32,
            "disposition": "admitted",
        },
        {
            "entry_cid": "",
            "legal_id": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter the graph",
        },
        {
            "entry_cid": _cid("f"),
            "legal_id": "fr:2026-09999:2026-01-01:type=notice",
            "document_number": "2026-09999",
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "document_type": "notice",
            "year_month": "2026-01",
            "publication_date": "2026-01-01",
        },
    ]


def fixture_similarity_neighbors() -> list[dict[str, Any]]:
    return [
        {
            "source_legal_id": "fr:2026-04567:2026-03-16:type=rule",
            "target_legal_id": "fr:2026-04568:2026-03-16:type=proposed_rule",
            "score": 0.42,
            "edge_type": GraphEdgeType.BM25_NEIGHBOR_OF.value,
            "metric": "bm25",
        }
    ]


def bind_fixture_graph(
    rows: Sequence[Mapping[str, Any]] | MaterializedCorpus | None = None,
    **overrides: Any,
) -> FederalRegisterGraphProjection:
    """Bind the compact fixture recipe with tight physical test bounds."""

    if rows is None:
        source: MaterializedCorpus | Sequence[Mapping[str, Any]] = fixture_graph_rows()
        neighbors = overrides.pop("similarity_neighbors", fixture_similarity_neighbors())
        require_coverage = overrides.pop("require_coverage", True)
    else:
        source = rows
        neighbors = overrides.pop("similarity_neighbors", None)
        require_coverage = overrides.pop("require_coverage", False)
    config = overrides.pop("config", None) or fixture_graph_config(**overrides)
    return project_federal_register_graph(
        source,
        similarity_neighbors=neighbors,
        config=config,
        require_coverage=require_coverage,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def default_graph_report_path(repo_root: PathLike | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else repository_root()
    return (root / REPORT_RELATIVE_PATH).resolve()


def _acceptance_block() -> dict[str, Any]:
    return {
        "adjacency_inversion": True,
        "criteria": (
            "Endpoint closure, edge uniqueness, adjacency inversion, family "
            "bounds, provenance paths, and unresolved-reference accounting pass."
        ),
        "edge_uniqueness": True,
        "endpoint_closure": True,
        "family_bounds": True,
        "hub_upload": False,
        "provenance_paths": True,
        "secrets_absent": True,
        "similarity_not_legal_authority": True,
        "unresolved_reference_accounting": True,
    }


def build_federal_graph_report(
    *,
    corpus: MaterializedCorpus | None = None,
    compact_projection: FederalRegisterGraphProjection | None = None,
) -> dict[str, Any]:
    """Build the sealed, secret-free LCR-058 graph receipt."""

    demo = compact_projection if compact_projection is not None else bind_fixture_graph()
    materialized = corpus or materialize_federal_register_corpus()
    admitted = project_federal_register_graph_from_corpus(
        materialized, config=fixture_graph_config()
    )
    demo.assert_coverage()
    assert_endpoint_closure(demo)
    assert_edge_uniqueness(demo)
    assert_adjacency_inversion(demo)
    assert_family_bounds(demo)
    demo_paths = assert_provenance_paths(demo)
    demo_unresolved = assert_unresolved_reference_accounting(demo)
    assert_endpoint_closure(admitted)
    assert_edge_uniqueness(admitted)
    assert_adjacency_inversion(admitted)
    assert_family_bounds(admitted)
    admitted_paths = assert_provenance_paths(admitted)
    admitted_unresolved = assert_unresolved_reference_accounting(admitted)
    payload: dict[str, Any] = {
        "acceptance": _acceptance_block(),
        "adr_path": ADR_PATH,
        "admitted": {
            "corpus_count": len(materialized.corpus_records),
            "chunk_count": len(materialized.chunks),
            "corpus_root_cid": admitted.corpus_root_cid,
            "document_count": admitted.document_count,
            "edge_count": admitted.edge_count,
            "graph_cid": admitted.graph_cid,
            "incoming_descriptor_count": len(admitted.incoming),
            "node_count": admitted.node_count,
            "outgoing_descriptor_count": len(admitted.outgoing),
            "unresolved_citations": admitted.unresolved_count,
            "unresolved_related_documents": admitted.unresolved_related_count,
        },
        "adjacency": {
            **demo.adjacency_summary(),
            "inversion_holds": True,
            "production_max_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        },
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "board_namespace": BOARD_NAMESPACE,
        "bounds": production_graph_bounds(),
        "bundle": BUNDLE,
        "checks": {
            "admitted_document_count": admitted.document_count,
            "admitted_edge_count": admitted.edge_count,
            "admitted_node_count": admitted.node_count,
            "admitted_provenance_path_count": len(admitted_paths),
            "adjacency_inversion": True,
            "bm25_is_not_legal_authority": True,
            "bm25_task_id": BM25_TASK_ID,
            "demo_document_count": demo.document_count,
            "demo_edge_count": demo.edge_count,
            "demo_node_count": demo.node_count,
            "demo_unresolved_citations": demo.unresolved_count,
            "edge_uniqueness": True,
            "endpoint_closure": True,
            "family_bounds": True,
            "full_adjacency_paging_owned_by": ADJACENCY_PAGING_TASK_ID,
            "no_hub_upload": True,
            "ontology_version": ONTOLOGY_VERSION,
            "production_max_adjacency_pointers": MAX_ADJACENCY_POINTERS_PER_ROW,
            "production_max_rows_per_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
            "provenance_paths": True,
            "recovery_excluded_from_graph": True,
            "required_coverage_node_types": list(REQUIRED_COVERAGE_NODE_TYPES),
            "similarity_not_legal_authority": True,
            "unresolved_reference_accounting": True,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "demo": {
            "adjacency_summary": demo.adjacency_summary(),
            "corpus_root_cid": demo.corpus_root_cid,
            "document_count": demo.document_count,
            "document_keys": [
                node.node_key
                for node in demo.nodes
                if node.node_type is GraphNodeType.DOCUMENT
            ],
            "edge_count": demo.edge_count,
            "family_counts": demo.family_counts(),
            "graph_cid": demo.graph_cid,
            "legal_edge_count": demo.legal_edge_count,
            "node_count": demo.node_count,
            "node_type_counts": {
                node_type.value: sum(
                    1 for node in demo.nodes if node.node_type is node_type
                )
                for node_type in GraphNodeType
            },
            "ontology_version": demo.ontology_version,
            "provenance_path_count": len(demo_paths),
            "similarity_edge_count": demo.similarity_edge_count,
            "skipped_row_count": demo.skipped_row_count,
            "unresolved": demo_unresolved,
        },
        "depends_on": [CORPUS_TASK_ID, BM25_TASK_ID],
        "description": (
            "LCR-058 Federal Register agency, rulemaking, citation, and "
            "provenance graph. Projects typed nodes and edges, bounded "
            "incoming/outgoing adjacency descriptors, unresolved-reference "
            "evidence, and conservation reports. Hermetic against the LCR-055 "
            "admitted corpus. BM25/lexical neighbors are not legal authority. "
            "Full adjacency paging is LCR-076. Does not authorize Hub upload."
        ),
        "family_counts": {
            "chunks": len(materialized.chunks),
            "corpus": len(materialized.corpus_records),
            "graph": admitted.document_count,
            "graph_edges": admitted.edge_count,
            "graph_nodes": admitted.node_count,
        },
        "goal_id": GOAL_ID,
        "mode": MODE_FIXTURE,
        "network_required": False,
        "ontology": GRAPH_ONTOLOGY.to_dict(),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "report_kind": "fixture_graph",
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "unresolved": admitted_unresolved,
    }
    compact = dict(payload)
    assert_no_secrets(compact, context="federal_graph")
    blob = json.dumps(compact, sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("graph report contains an absolute home path")
    compact["report_digest_sha256"] = digest_mapping(
        {key: value for key, value in compact.items() if key != "report_digest_sha256"}
    )
    return compact


def write_federal_graph_report(
    path: PathLike | None = None,
    *,
    corpus: MaterializedCorpus | None = None,
) -> Path:
    target = Path(path) if path is not None else default_graph_report_path()
    payload = build_federal_graph_report(corpus=corpus)
    write_json_atomic(target, payload)
    return target


def load_federal_graph_report(path: PathLike | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_graph_report_path()
    if not target.is_file():
        raise GraphReceiptError(f"graph report not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise GraphReceiptError("graph report root must be an object")
    return dict(payload)


def assert_federal_graph_report(payload: Mapping[str, Any]) -> None:
    """Fail closed if the report would authorize release or weaken the contract."""

    if payload.get("task_id") != TASK_ID:
        raise GraphReceiptError(f"report task_id must be {TASK_ID!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise GraphReceiptError(f"report schema_version must be {SCHEMA_VERSION!r}")
    if payload.get("authorizing_hub_upload") is True:
        raise GraphReleaseAuthorizationError("graph report cannot authorize Hub upload")
    if payload.get("authorizing_for_publication") is True:
        raise GraphReleaseAuthorizationError(
            "graph report cannot authorize publication"
        )
    if payload.get("hub_upload") is True:
        raise GraphReleaseAuthorizationError("graph report cannot set hub_upload")
    acceptance = payload.get("acceptance") or {}
    if not isinstance(acceptance, Mapping):
        raise GraphReceiptError("report acceptance must be a mapping")
    required = (
        "endpoint_closure",
        "edge_uniqueness",
        "adjacency_inversion",
        "family_bounds",
        "provenance_paths",
        "unresolved_reference_accounting",
        "secrets_absent",
    )
    for key in required:
        if acceptance.get(key) is not True:
            raise GraphReceiptError(f"report must prove {key}")
    if acceptance.get("hub_upload") is not False:
        raise GraphReceiptError("report must not claim Hub upload")
    bounds = payload.get("bounds") or {}
    if not isinstance(bounds, Mapping):
        raise GraphReceiptError("report bounds must be a mapping")
    if bounds.get("maximum_rows_per_physical_shard") != MAX_ROWS_PER_PHYSICAL_SHARD:
        raise GraphReceiptError("report physical shard bound must be 4096")
    if bounds.get("maximum_adjacency_pointers_per_row") != MAX_ADJACENCY_POINTERS_PER_ROW:
        raise GraphReceiptError("report adjacency pointer bound must be 4096")
    if bounds.get("similarity_cannot_establish_legal_authority") is not True:
        raise GraphReceiptError("report must keep similarity disjoint from legal authority")
    if payload.get("mode") != MODE_FIXTURE:
        raise GraphReceiptError("report mode must be fixture")
    if payload.get("network_required") is True:
        raise GraphReceiptError("graph fixture report must not require network")
    blob = json.dumps(dict(payload), sort_keys=True)
    if "/home/" in blob or "/Users/" in blob:
        raise SecretInReceiptError("graph report contains an absolute home path")
    assert_no_secrets(payload, context="federal_graph")
    if find_secret_surfaces(payload):
        raise SecretInReceiptError("graph report contains secret surfaces")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the LCR-058 Federal Register graph receipt."
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        default=True,
        help="Hermetic sealed fixture mode (default). Never contacts the network.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional receipt path. Defaults to docs/reports/legal_corpora_reindex/federal_graph.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate an existing receipt without rewriting it.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.fixture_only:
        raise GraphConfigError("LCR-058 graph builds are fixture-only; live network is forbidden")
    target = Path(args.output) if args.output else default_graph_report_path()
    if args.check:
        payload = load_federal_graph_report(target)
        assert_federal_graph_report(payload)
        print(f"checked {target.as_posix()} task_id={payload['task_id']}")
        return 0
    written = write_federal_graph_report(target)
    payload = load_federal_graph_report(written)
    assert_federal_graph_report(payload)
    print(
        f"wrote {REPORT_RELATIVE_PATH.as_posix()} "
        f"admitted_documents={payload['admitted']['document_count']} "
        f"demo_documents={payload['demo']['document_count']}"
    )
    return 0


__all__ = [
    "ADJACENCY_PAGING_TASK_ID",
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "BM25_TASK_ID",
    "CITATION_PARSER_VERSION",
    "DEFAULT_TEST_MAX_ADJACENCY_POINTERS",
    "GOAL_ID",
    "GRAPH_ONTOLOGY",
    "LEGAL_EDGE_TYPES",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MODE_FIXTURE",
    "NON_AUTHORITATIVE_AUTHORITY",
    "ONTOLOGY_VERSION",
    "PRIMARY_KEY",
    "PRODUCER",
    "PROGRAM_ID",
    "REPORT_SCHEMA",
    "REQUIRED_COVERAGE_NODE_TYPES",
    "SCHEMA_VERSION",
    "SIMILARITY_EDGE_TYPES",
    "TASK_ID",
    "AdjacencyDescriptor",
    "AdjacencyPointer",
    "CitationMention",
    "FederalRegisterGraphConfig",
    "FederalRegisterGraphEdge",
    "FederalRegisterGraphError",
    "FederalRegisterGraphNode",
    "FederalRegisterGraphProjection",
    "FederalRegisterGraphProjector",
    "GraphAdjacencyError",
    "GraphBoundError",
    "GraphConfigError",
    "GraphCorpusRow",
    "GraphCoverageError",
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
    "ResolutionStatus",
    "ResolvedCitation",
    "SimilarityNeighbor",
    "SourceSpan",
    "SourceSpanError",
    "assert_adjacency_inversion",
    "assert_edge_uniqueness",
    "assert_endpoint_closure",
    "assert_family_bounds",
    "assert_federal_graph_report",
    "assert_legal_similarity_disjoint",
    "assert_provenance_paths",
    "assert_unresolved_reference_accounting",
    "bind_fixture_graph",
    "build_adjacency_descriptors",
    "build_corpus_root_cid",
    "build_federal_graph_report",
    "default_graph_config",
    "default_graph_report_path",
    "extract_citation_mentions",
    "find_graph_paths",
    "fixture_graph_config",
    "fixture_graph_rows",
    "fixture_similarity_neighbors",
    "load_federal_graph_report",
    "production_graph_bounds",
    "production_graph_config",
    "project_federal_register_graph",
    "project_federal_register_graph_from_corpus",
    "reconcile_roots",
    "rows_from_materialized_corpus",
    "write_federal_graph_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
