"""Federal Register Sparse GraphRAG v2 release schema and identity contract (LCR-050).

This module owns the versioned release-level dataclasses and fail-closed
validators for the ``federal-register-ir-graphrag/v2`` Federal Register release.
It defines corpus, source-receipt, admission, posting, vector, centroid, graph,
adjacency, locator, descriptor, manifest, publication, and rollback records.

It deliberately does **not** reimplement Federal Register API acquisition,
GovInfo package resolution, or Parquet/Hub I/O. Downstream writers and builders
consume these contracts; this module performs no network I/O.

Design invariants
-----------------
* Durable identity is ``entry_cid`` (primary key) plus ``legal_id``
  (document-number / publication identity) plus ``source_cid``
  (normalized official-source evidence). Positional labels such as
  ``row-N`` or release-local ``document_index`` are **not** durable identity.
* Official provenance is mandatory on admitted rows: release/as-of pin,
  source checksum, verification result, acquisition time, official URL(s),
  official content hashes, acquisition receipt id, parser version, document
  number, publication date, document type, and text-availability disposition.
* Correction / withdrawal identity is explicit: a document may declare a
  correction relationship to another document number without collapsing
  either identity.
* Model and release references must be immutable (Hub commit SHA, SHA-256,
  or CID). Tokens such as ``latest``, ``main``, or ``HEAD`` are rejected.
* The integer ``4,096`` means physical rows/pointers per retrieval unit.
  Model-token ceilings use separate, explicitly named fields.
* Artifact paths are relative, POSIX, and confined to the release root.
  Corpus partitions use publication year/month and document type.
* A valid default release must close the required semantic families
  (corpus, BM25 documents/postings, vectors, centroids, graph nodes/edges,
  in/out adjacency, locators, and manifest).
* Publication and rollback receipts bind immutable Hub pins only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-sparse-graphrag-release-schema-v2"
RELEASE_PROFILE: Final = "federal-register-ir-graphrag/v2"
ADR_PATH: Final = "docs/architecture/federal_register_sparse_graphrag_schema.md"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_federal_register"
PREVIOUS_PUBLIC_PIN: Final = "720668ae016cc400916dda884c9005e03618edfa"
DEFAULT_EMBEDDING_MODEL_ID: Final = "thenlper/gte-small"
DEFAULT_EMBEDDING_MODEL_REVISION: Final = (
    "17e1f347d17fe144873b1201da91788898c639cd"
)
DEFAULT_EMBEDDING_DIMENSION: Final = 384
TASK_ID: Final = "LCR-050"
DEFAULT_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"

# ---------------------------------------------------------------------------
# Physical bounds (authoritative; never reuse as token ceilings)
# ---------------------------------------------------------------------------

MAX_ROWS_PER_PHYSICAL_SHARD: Final = 4096
MAX_POSTING_POINTERS_PER_ROW: Final = 4096
MAX_ADJACENCY_POINTERS_PER_ROW: Final = 4096
MAX_TERM_ROWS_PER_SHARD: Final = 4096
MAX_ROUTING_ROWS_PER_INDEX: Final = 4096
MAX_ROWS_PER_VECTOR_CENTROID: Final = 8192
MAX_VECTOR_SHARDS_PER_CENTROID: Final = 2
DEFAULT_CANDIDATE_CENTROIDS: Final = 4

PHYSICAL_BOUND_FIELD_NAMES: Final = frozenset(
    {
        "max_rows_per_physical_shard",
        "maximum_rows_per_physical_shard",
        "max_posting_pointers_per_row",
        "maximum_posting_pointers_per_row",
        "max_adjacency_pointers_per_row",
        "maximum_adjacency_pointers_per_row",
        "max_term_rows_per_shard",
        "maximum_term_rows_per_shard",
        "max_routing_rows_per_index",
        "maximum_routing_rows_per_index",
        "max_rows_per_vector_centroid",
        "maximum_rows_per_vector_centroid",
        "max_vector_shards_per_centroid",
        "maximum_vector_shards_per_centroid",
        "rows_per_shard",
        "pointers_per_row",
        "physical_row_bound",
        "physical_pointer_bound",
    }
)

AMBIGUOUS_4096_FIELD_NAMES: Final = frozenset(
    {
        "chunk_size",
        "chunks",
        "max_chunks",
        "max_tokens",
        "max_token_window",
        "model_token_ceiling",
        "token_limit",
        "token_window",
        "window_size",
        "context_window",
        "max_context",
        "embedding_window",
        "text_window",
        "n_ctx",
        "seq_len",
        "sequence_length",
    }
)

# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CID_V1_RE = re.compile(r"^b[a-z2-7]{20,}$")
_ENTRY_CID_RE = re.compile(
    r"^(?:b[a-z2-7]{20,}|sha256:[0-9a-f]{64}|[0-9a-f]{64})$"
)
# FederalRegister.gov retains historical two-character document series and
# identity-bearing correction/republication prefixes.  This is deliberately
# the same closed grammar as the LCR-049 source-policy boundary rather than a
# generic alphanumeric identifier.
_HISTORICAL_DOCUMENT_SERIES_PATTERN: Final = (
    r"(?:0[0-9]|20|9[2-9]|C[0-9]|E[13-9]|R[0-9]|X[019]|Z[4-9])"
)
_DOCUMENT_NUMBER_PATTERN: Final = (
    rf"(?:[CR][0-9]-[0-9]{{4}}-[0-9]{{4,6}}|"
    rf"(?:[0-9]{{4}}|{_HISTORICAL_DOCUMENT_SERIES_PATTERN})-[0-9]{{4,6}})"
)
# fr:<document_number>:<publication_date>[:qualifier...]
_LEGAL_ID_RE = re.compile(
    rf"^fr:({_DOCUMENT_NUMBER_PATTERN}):"
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?::.+)?$",
    re.IGNORECASE,
)
_DOCUMENT_NUMBER_RE = re.compile(rf"^{_DOCUMENT_NUMBER_PATTERN}$")
_PUBLICATION_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_YEAR_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_POSITIONAL_ID_RE = re.compile(
    r"^(?:row[-_ ]?\d+|row[-_ ]?N|document[-_ ]?index[-_ ]?\d+|idx[-_ ]?\d+|"
    r"pos[-_ ]?\d+|offset[-_ ]?\d+)$",
    re.IGNORECASE,
)
_MUTABLE_REVISION_RE = re.compile(
    r"^(?:latest|main|master|head|tip|trunk|default|current|live|prod|"
    r"production|staging|dev|develop|development|nightly|canary|"
    r"origin/.*|refs/.*)$",
    re.IGNORECASE,
)
_MUTABLE_TOKEN_IN_PATH_RE = re.compile(
    r"(?:^|[/@:])(?:latest|main|master|HEAD)(?:$|[/@:])",
)
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)

_CACHE_PATH_PARTS: Final = frozenset(
    {"__pycache__", ".cache", ".git", ".pytest_cache", ".mypy_cache"}
)

# Official Federal Register / GovInfo host allowlist for official URLs.
_OFFICIAL_URL_HOST_RE = re.compile(
    r"^https?://(?:www\.)?(?:federalregister\.gov|govinfo\.gov|"
    r"api\.federalregister\.gov|api\.govinfo\.gov)(?:/|$)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterReleaseSchemaError(ValueError):
    """Base error for Federal Register release schema contract failures."""


class PositionalIdentityError(FederalRegisterReleaseSchemaError):
    """Raised when durable identity is positional (``row-N``, index, etc.)."""


class MutableReferenceError(FederalRegisterReleaseSchemaError):
    """Raised when a model or release reference is mutable (``latest``, branch)."""


class AmbiguousBoundError(FederalRegisterReleaseSchemaError):
    """Raised when a 4,096 value is attached to an ambiguous/token field."""


class ArtifactPathError(FederalRegisterReleaseSchemaError):
    """Raised when an artifact path is absolute, traverses, or is unsafe."""


class InvalidDigestError(FederalRegisterReleaseSchemaError):
    """Raised when a digest/CID field is malformed."""


class MissingAdmissionProvenanceError(FederalRegisterReleaseSchemaError):
    """Raised when admission status or required provenance fields are absent."""


class PhysicalBoundError(FederalRegisterReleaseSchemaError):
    """Raised when a physical row/pointer bound is violated."""


class SchemaVersionError(FederalRegisterReleaseSchemaError):
    """Raised when schema_version / release profile is wrong."""


class SemanticFamilyClosureError(FederalRegisterReleaseSchemaError):
    """Raised when a release omits a required semantic family."""


class OfficialProvenanceError(FederalRegisterReleaseSchemaError):
    """Raised when official-source provenance is incomplete or non-official."""


class DocumentIdentityError(FederalRegisterReleaseSchemaError):
    """Raised when document-number / publication / correction identity is invalid."""


class TextAvailabilityError(FederalRegisterReleaseSchemaError):
    """Raised when text-availability disposition is inconsistent with body text."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ArtifactFamily(str, Enum):
    """Top-level artifact families in the v2 Federal Register release layout."""

    CORPUS = "corpus"
    BM25_DOCUMENTS = "bm25_documents"
    BM25_POSTINGS = "bm25_postings"
    VECTORS = "vectors"
    CENTROIDS = "centroids"
    GRAPH_NODES = "graph_nodes"
    GRAPH_EDGES = "graph_edges"
    GRAPH_ADJACENCY_OUT = "graph_adjacency_out"
    GRAPH_ADJACENCY_IN = "graph_adjacency_in"
    LOCATOR_INDEX = "locator_index"
    MANIFEST = "manifest"
    RECEIPT = "receipt"
    SOURCE_RECEIPT = "source_receipt"
    RECOVERY = "recovery"
    RELEASE_METADATA = "release_metadata"
    ROUTING_INDEX = "routing_index"
    REPORT = "report"
    PUBLICATION = "publication"
    ROLLBACK = "rollback"

    @classmethod
    def coerce(cls, value: Any) -> "ArtifactFamily":
        if isinstance(value, ArtifactFamily):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "bm25_docs": cls.BM25_DOCUMENTS,
            "bm25_document": cls.BM25_DOCUMENTS,
            "postings": cls.BM25_POSTINGS,
            "bm25_posting": cls.BM25_POSTINGS,
            "vector": cls.VECTORS,
            "centroid": cls.CENTROIDS,
            "vector_centroid": cls.CENTROIDS,
            "nodes": cls.GRAPH_NODES,
            "edges": cls.GRAPH_EDGES,
            "adjacency_out": cls.GRAPH_ADJACENCY_OUT,
            "adjacency_in": cls.GRAPH_ADJACENCY_IN,
            "out_adjacency": cls.GRAPH_ADJACENCY_OUT,
            "in_adjacency": cls.GRAPH_ADJACENCY_IN,
            "locator": cls.LOCATOR_INDEX,
            "locators": cls.LOCATOR_INDEX,
            "index": cls.ROUTING_INDEX,
            "routing": cls.ROUTING_INDEX,
            "scrape_receipt": cls.SOURCE_RECEIPT,
            "acquisition_receipt": cls.SOURCE_RECEIPT,
            "date_partition_receipt": cls.SOURCE_RECEIPT,
            "pub": cls.PUBLICATION,
            "rollback_receipt": cls.ROLLBACK,
        }
        if text in aliases:
            return aliases[text]
        for family in cls:
            if family.value == text or family.name.lower() == text:
                return family
        raise FederalRegisterReleaseSchemaError(f"unknown artifact family: {value!r}")


# Required default-config semantic families (closure set).
REQUIRED_SEMANTIC_FAMILIES: Final = frozenset(
    {
        ArtifactFamily.CORPUS,
        ArtifactFamily.BM25_DOCUMENTS,
        ArtifactFamily.BM25_POSTINGS,
        ArtifactFamily.VECTORS,
        ArtifactFamily.CENTROIDS,
        ArtifactFamily.GRAPH_NODES,
        ArtifactFamily.GRAPH_EDGES,
        ArtifactFamily.GRAPH_ADJACENCY_OUT,
        ArtifactFamily.GRAPH_ADJACENCY_IN,
        ArtifactFamily.LOCATOR_INDEX,
        ArtifactFamily.MANIFEST,
    }
)


class AdmissionStatus(str, Enum):
    """Admission disposition for one retrieval row or recovery record."""

    ADMITTED = "admitted"
    EXCLUDED = "excluded"
    QUARANTINED = "quarantined"
    RECOVERY = "recovery"
    PENDING = "pending"
    REJECTED = "rejected"

    @classmethod
    def coerce(cls, value: Any) -> "AdmissionStatus":
        if isinstance(value, AdmissionStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "include": cls.ADMITTED,
            "included": cls.ADMITTED,
            "admit": cls.ADMITTED,
            "exclude": cls.EXCLUDED,
            "quarantine": cls.QUARANTINED,
            "reject": cls.REJECTED,
        }
        if text in aliases:
            return aliases[text]
        for status in cls:
            if status.value == text or status.name.lower() == text:
                return status
        raise FederalRegisterReleaseSchemaError(f"unknown admission status: {value!r}")


class VerificationResult(str, Enum):
    """Checksum / identity verification outcome for provenance receipts."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"
    MISSING = "missing"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "VerificationResult":
        if isinstance(value, VerificationResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for result in cls:
            if result.value == text or result.name.lower() == text:
                return result
        raise FederalRegisterReleaseSchemaError(
            f"unknown verification result: {value!r}"
        )


class BoundKind(str, Enum):
    """Disambiguates physical storage bounds from model-token ceilings."""

    PHYSICAL_ROWS = "physical_rows"
    PHYSICAL_POINTERS = "physical_pointers"
    MODEL_TOKENS = "model_tokens"
    CENTROID_ROWS = "centroid_rows"
    CENTROID_SHARDS = "centroid_shards"


class SourceAuthorityClass(str, Enum):
    """Whether the acquisition source is official authority or quarantine."""

    OFFICIAL = "official"
    SECONDARY = "secondary"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "SourceAuthorityClass":
        if isinstance(value, SourceAuthorityClass):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "primary": cls.OFFICIAL,
            "federal_register": cls.OFFICIAL,
            "govinfo": cls.OFFICIAL,
            "nara": cls.OFFICIAL,
            "approved_exception": cls.EXCEPTION,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise FederalRegisterReleaseSchemaError(
            f"unknown source authority class: {value!r}"
        )


class DocumentType(str, Enum):
    """Federal Register document type (publication identity family)."""

    RULE = "rule"
    PROPOSED_RULE = "proposed_rule"
    NOTICE = "notice"
    PRESIDENTIAL_DOCUMENT = "presidential_document"
    CORRECTION = "correction"
    SUNSHINE_ACT_MEETING = "sunshine_act_meeting"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "DocumentType":
        if isinstance(value, DocumentType):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "rules": cls.RULE,
            "final_rule": cls.RULE,
            "proposed_rules": cls.PROPOSED_RULE,
            "proposed": cls.PROPOSED_RULE,
            "notices": cls.NOTICE,
            "presidential": cls.PRESIDENTIAL_DOCUMENT,
            "presidential_documents": cls.PRESIDENTIAL_DOCUMENT,
            "executive_order": cls.PRESIDENTIAL_DOCUMENT,
            "proclamation": cls.PRESIDENTIAL_DOCUMENT,
            "corrections": cls.CORRECTION,
            "sunshine": cls.SUNSHINE_ACT_MEETING,
            "sunshine_act": cls.SUNSHINE_ACT_MEETING,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DocumentIdentityError(f"unknown document type: {value!r}")


class TextAvailability(str, Enum):
    """Disposition of official full-text body for a Federal Register document.

    Metadata-only items must never masquerade as full text. A non-body
    disposition is allowed only after the attempt ledger proves every official
    alternative has no usable body.
    """

    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    HTML_BODY = "html_body"
    XML_BODY = "xml_body"
    PDF_BODY = "pdf_body"
    GOVINFO_BODY = "govinfo_body"
    METADATA_ONLY = "metadata_only"
    UNAVAILABLE = "unavailable"
    FAILED_FINAL = "failed_final"

    @classmethod
    def coerce(cls, value: Any) -> "TextAvailability":
        if isinstance(value, TextAvailability):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "full": cls.FULL_TEXT,
            "body": cls.FULL_TEXT,
            "fulltext": cls.FULL_TEXT,
            "abstract": cls.ABSTRACT_ONLY,
            "html": cls.HTML_BODY,
            "xml": cls.XML_BODY,
            "pdf": cls.PDF_BODY,
            "govinfo": cls.GOVINFO_BODY,
            "meta": cls.METADATA_ONLY,
            "metadata": cls.METADATA_ONLY,
            "missing": cls.UNAVAILABLE,
            "none": cls.UNAVAILABLE,
            "failed": cls.FAILED_FINAL,
            "failed_final": cls.FAILED_FINAL,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise TextAvailabilityError(f"unknown text availability: {value!r}")

    @property
    def has_usable_body(self) -> bool:
        return self in {
            TextAvailability.FULL_TEXT,
            TextAvailability.HTML_BODY,
            TextAvailability.XML_BODY,
            TextAvailability.PDF_BODY,
            TextAvailability.GOVINFO_BODY,
        }


class CorrectionRelation(str, Enum):
    """How this document relates to another via correction/withdrawal identity."""

    NONE = "none"
    CORRECTS = "corrects"
    CORRECTED_BY = "corrected_by"
    WITHDRAWS = "withdraws"
    WITHDRAWN_BY = "withdrawn_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"

    @classmethod
    def coerce(cls, value: Any) -> "CorrectionRelation":
        if isinstance(value, CorrectionRelation):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "": cls.NONE,
            "null": cls.NONE,
            "n/a": cls.NONE,
            "na": cls.NONE,
            "correction": cls.CORRECTS,
            "corrects_document": cls.CORRECTS,
            "is_corrected_by": cls.CORRECTED_BY,
            "withdrawal": cls.WITHDRAWS,
            "withdraws_document": cls.WITHDRAWS,
            "is_withdrawn_by": cls.WITHDRAWN_BY,
            "supersession": cls.SUPERSEDES,
            "is_superseded_by": cls.SUPERSEDED_BY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DocumentIdentityError(f"unknown correction relation: {value!r}")


# Required provenance fields on admitted corpus rows.
REQUIRED_PROVENANCE_FIELDS: Final = frozenset(
    {
        "source_cid",
        "release_point",
        "source_checksum",
        "verification_result",
        "acquisition_time",
        "official_source_url",
        "acquisition_receipt_id",
        "parser_version",
        "document_number",
        "publication_date",
        "document_type",
        "text_availability",
    }
)

REQUIRED_ADMISSION_FIELDS: Final = frozenset(
    {
        "admission_status",
        "admission_reason",
    }
)

REQUIRED_IDENTITY_FIELDS: Final = frozenset(
    {
        "entry_cid",
        "legal_id",
        "source_cid",
    }
)

# Body-bearing text dispositions that require non-empty text on admitted rows.
BODY_TEXT_AVAILABILITIES: Final = frozenset(
    {
        TextAvailability.FULL_TEXT,
        TextAvailability.HTML_BODY,
        TextAvailability.XML_BODY,
        TextAvailability.PDF_BODY,
        TextAvailability.GOVINFO_BODY,
    }
)

# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterReleaseSchemaError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterReleaseSchemaError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterReleaseSchemaError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterReleaseSchemaError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterReleaseSchemaError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number <= 0:
        raise FederalRegisterReleaseSchemaError(f"{name} must be a positive integer")
    return number


def canonical_json_dumps(payload: Mapping[str, Any]) -> str:
    """Return deterministic JSON text for fixtures and content addressing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def digest_mapping(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON encoding of *payload*."""

    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Digest / CID validation
# ---------------------------------------------------------------------------


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    """Normalize a SHA-256 digest to lowercase 64-char hex (no prefix)."""

    text = _require_non_empty_str(value, name).lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise InvalidDigestError(
            f"{name} must be a lowercase 64-char hex SHA-256 "
            f"(optionally prefixed with 'sha256:'), got {value!r}"
        )
    return text


def validate_digest(value: Any, *, name: str = "digest") -> str:
    """Accept SHA-256 (raw or ``sha256:``) or CIDv1 base32; return normalized form."""

    text = _require_non_empty_str(value, name).lower()
    if text.startswith("sha256:"):
        return f"sha256:{normalize_sha256(text, name=name)}"
    if _SHA256_HEX_RE.fullmatch(text):
        return text
    if _CID_V1_RE.fullmatch(text):
        return text
    raise InvalidDigestError(
        f"{name} must be SHA-256 hex, sha256:<hex>, or CIDv1 base32; got {value!r}"
    )


def validate_entry_cid(value: Any, *, name: str = "entry_cid") -> str:
    """Validate a retrieval primary key (CID or content digest)."""

    text = _require_non_empty_str(value, name)
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"{name} must not be a positional identity token: {value!r}"
        )
    lowered = text.lower()
    if not _ENTRY_CID_RE.fullmatch(lowered):
        if _MUTABLE_REVISION_RE.fullmatch(text):
            raise MutableReferenceError(
                f"{name} must not use a mutable reference: {value!r}"
            )
        raise InvalidDigestError(
            f"{name} must be a CIDv1, sha256:<hex>, or 64-hex digest; got {value!r}"
        )
    return lowered


def validate_document_number(value: Any, *, name: str = "document_number") -> str:
    """Validate an official Federal Register document-number shape."""

    text = _require_non_empty_str(value, name, maximum=32)
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"{name} must not be a positional identity token: {value!r}"
        )
    if not _DOCUMENT_NUMBER_RE.fullmatch(text):
        raise DocumentIdentityError(
            f"{name} must be an official Federal Register document number; "
            f"got {value!r}"
        )
    parts = text.split("-")
    year_token = parts[1] if len(parts) == 3 else parts[0]
    if len(year_token) == 4 and year_token.isdigit():
        year = int(year_token)
        if year < 1936 or year > 2100:
            raise DocumentIdentityError(
                f"{name} year out of plausible range: {value!r}"
            )
    return text


def validate_publication_date(value: Any, *, name: str = "publication_date") -> str:
    """Validate an ISO calendar publication date ``YYYY-MM-DD``."""

    text = _require_non_empty_str(value, name, maximum=32)
    if not _PUBLICATION_DATE_RE.fullmatch(text):
        raise DocumentIdentityError(
            f"{name} must be YYYY-MM-DD; got {value!r}"
        )
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    if year < 1936 or year > 2100:
        raise DocumentIdentityError(f"{name} year out of plausible range: {value!r}")
    if month < 1 or month > 12:
        raise DocumentIdentityError(f"{name} month out of range: {value!r}")
    if day < 1 or day > 31:
        raise DocumentIdentityError(f"{name} day out of range: {value!r}")
    return text


def validate_year_month(value: Any, *, name: str = "year_month") -> str:
    """Validate a publication partition key ``YYYY-MM``."""

    text = _require_non_empty_str(value, name, maximum=16)
    if not _YEAR_MONTH_RE.fullmatch(text):
        raise DocumentIdentityError(f"{name} must be YYYY-MM; got {value!r}")
    month = int(text[5:7])
    if month < 1 or month > 12:
        raise DocumentIdentityError(f"{name} month out of range: {value!r}")
    return text


def validate_official_url(value: Any, *, name: str = "official_source_url") -> str:
    """Require an absolute http(s) URL on an official FR/GovInfo host."""

    url = _require_non_empty_str(value, name, maximum=2048)
    if not url.lower().startswith(("http://", "https://")):
        raise OfficialProvenanceError(f"{name} must be an absolute http(s) URL")
    if not _OFFICIAL_URL_HOST_RE.match(url):
        raise OfficialProvenanceError(
            f"{name} must target federalregister.gov or govinfo.gov; got {value!r}"
        )
    return url


def validate_legal_id(value: Any, *, name: str = "legal_id") -> str:
    """Validate stable Federal Register publication identity shape.

    Shape: ``fr:<document_number>:<publication_date>[:qualifier...]`` where
    document_number uses the official modern, historical, correction, or
    republication grammar and publication_date is ``YYYY-MM-DD``.
    Positional labels are rejected. Document number and publication date form
    the durable publication identity independent of content version.
    """

    text = _require_non_empty_str(value, name)
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"{name} must not be a positional identity token: {value!r}"
        )
    if text.lower().startswith("row-") or text.lower().startswith("document_index"):
        raise PositionalIdentityError(
            f"{name} must not be a positional identity token: {value!r}"
        )
    match = _LEGAL_ID_RE.fullmatch(text)
    if not match:
        raise DocumentIdentityError(
            f"{name} must match fr:<document_number>:<publication_date>"
            f"[:qualifier...]; got {value!r}"
        )
    document_number = validate_document_number(match.group(1), name=f"{name}.document_number")
    publication_date = validate_publication_date(
        match.group(2), name=f"{name}.publication_date"
    )
    remainder = text.split(":", 3)
    if len(remainder) > 3:
        qualifier = remainder[3].lower()
        return f"fr:{document_number}:{publication_date}:{qualifier}"
    return f"fr:{document_number}:{publication_date}"


# ---------------------------------------------------------------------------
# Immutable model / release references
# ---------------------------------------------------------------------------


def is_immutable_revision(value: Any) -> bool:
    """Return True when *value* looks like an immutable revision pin."""

    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    if _MUTABLE_REVISION_RE.fullmatch(text):
        return False
    lowered = text.lower()
    if lowered.startswith("sha256:"):
        return bool(_SHA256_HEX_RE.fullmatch(lowered[7:]))
    if _GIT_SHA_RE.fullmatch(lowered):
        return True
    if _SHA256_HEX_RE.fullmatch(lowered):
        return True
    if _CID_V1_RE.fullmatch(lowered):
        return True
    return False


def require_immutable_revision(
    value: Any,
    *,
    name: str = "revision",
) -> str:
    """Require an immutable model/release revision pin."""

    text = _require_non_empty_str(value, name)
    if _MUTABLE_REVISION_RE.fullmatch(text):
        raise MutableReferenceError(
            f"{name} must be an immutable pin, not a mutable reference: {value!r}"
        )
    if _MUTABLE_TOKEN_IN_PATH_RE.search(text):
        raise MutableReferenceError(
            f"{name} embeds a mutable token and is not an immutable pin: {value!r}"
        )
    if not is_immutable_revision(text):
        raise MutableReferenceError(
            f"{name} must be a git SHA, SHA-256 digest, or CID; got {value!r}"
        )
    return text.strip()


def require_immutable_model_ref(
    *,
    model_id: Any,
    model_revision: Any,
    model_id_name: str = "model_id",
    model_revision_name: str = "model_revision",
) -> tuple[str, str]:
    """Require a pinned model identity: non-empty id + immutable revision."""

    model = _require_non_empty_str(model_id, model_id_name, maximum=512)
    if _MUTABLE_REVISION_RE.fullmatch(model) or model.lower() in {
        "latest",
        "default",
        "auto",
    }:
        raise MutableReferenceError(
            f"{model_id_name} must not be a mutable token: {model_id!r}"
        )
    revision = require_immutable_revision(model_revision, name=model_revision_name)
    return model, revision


# ---------------------------------------------------------------------------
# Artifact path validation
# ---------------------------------------------------------------------------


def normalize_relative_artifact_path(value: Any, *, name: str = "relative_path") -> str:
    """Normalize and validate a release-relative artifact path."""

    text = _require_non_empty_str(value, name, maximum=512)
    if "\\" in text:
        raise ArtifactPathError(f"{name} must use POSIX separators, got {value!r}")
    if text.startswith("/") or text.startswith("~"):
        raise ArtifactPathError(f"{name} must be relative, not absolute: {value!r}")
    if len(text) >= 2 and text[1] == ":":
        raise ArtifactPathError(f"{name} must not include a drive letter: {value!r}")
    if text.startswith("//") or text.startswith("\\\\"):
        raise ArtifactPathError(f"{name} must not be a UNC path: {value!r}")

    parsed = PurePosixPath(text)
    if parsed.is_absolute():
        raise ArtifactPathError(f"{name} must be relative, not absolute: {value!r}")
    if text != parsed.as_posix():
        raise ArtifactPathError(
            f"{name} must be a normalized POSIX path without redundant segments: "
            f"{value!r}"
        )
    if any(part in {"", ".", ".."} for part in parsed.parts):
        raise ArtifactPathError(
            f"{name} must not contain empty, '.', or '..' segments: {value!r}"
        )
    if any(part.casefold() in _CACHE_PATH_PARTS for part in parsed.parts):
        raise ArtifactPathError(
            f"{name} must not include cache/VCS path components: {value!r}"
        )
    return parsed.as_posix()


# ---------------------------------------------------------------------------
# Physical bound validation (disambiguates 4,096)
# ---------------------------------------------------------------------------


def validate_physical_row_count(
    value: Any,
    *,
    name: str = "row_count",
    maximum: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> int:
    """Require a non-negative row count within the physical shard bound."""

    count = _require_non_negative_int(value, name)
    if count > maximum:
        raise PhysicalBoundError(f"{name}={count} exceeds physical bound {maximum}")
    return count


def validate_physical_pointer_count(
    value: Any,
    *,
    name: str = "pointer_count",
    maximum: int = MAX_POSTING_POINTERS_PER_ROW,
) -> int:
    """Require a non-negative pointer count within the physical pointer bound."""

    count = _require_non_negative_int(value, name)
    if count > maximum:
        raise PhysicalBoundError(
            f"{name}={count} exceeds physical pointer bound {maximum}"
        )
    return count


def validate_bound_declaration(
    *,
    field_name: Any,
    value: Any,
    bound_kind: Any = None,
) -> tuple[str, int, BoundKind]:
    """Validate a named bound so 4,096 cannot attach to a token-window field."""

    name = _require_non_empty_str(field_name, "field_name", maximum=128).lower()
    number = _require_non_negative_int(value, name)

    kind: Optional[BoundKind]
    if bound_kind is None:
        kind = None
    elif isinstance(bound_kind, BoundKind):
        kind = bound_kind
    else:
        kind = BoundKind(str(bound_kind).strip().lower())

    if name in AMBIGUOUS_4096_FIELD_NAMES:
        if number == MAX_ROWS_PER_PHYSICAL_SHARD and kind is not BoundKind.MODEL_TOKENS:
            raise AmbiguousBoundError(
                f"field {name!r} with value {number} is ambiguous: "
                f"4,096 is the physical row/pointer bound. Use an explicit "
                f"physical field name or declare bound_kind="
                f"{BoundKind.MODEL_TOKENS.value!r}."
            )
        if kind is None:
            raise AmbiguousBoundError(
                f"field {name!r} is ambiguous without bound_kind; "
                f"declare model_tokens vs physical_rows explicitly"
            )
        if kind is not BoundKind.MODEL_TOKENS:
            raise AmbiguousBoundError(
                f"field {name!r} names a token/window concept but bound_kind "
                f"is {kind.value!r}"
            )
        return name, number, kind

    if name in PHYSICAL_BOUND_FIELD_NAMES:
        if kind is None:
            if "centroid" in name and "shard" in name:
                kind = BoundKind.CENTROID_SHARDS
            elif "centroid" in name:
                kind = BoundKind.CENTROID_ROWS
            elif "pointer" in name:
                kind = BoundKind.PHYSICAL_POINTERS
            else:
                kind = BoundKind.PHYSICAL_ROWS
        resolved = kind
        if resolved is BoundKind.MODEL_TOKENS:
            raise AmbiguousBoundError(
                f"field {name!r} is a physical bound and cannot use "
                f"bound_kind={BoundKind.MODEL_TOKENS.value!r}"
            )
        if resolved is BoundKind.PHYSICAL_POINTERS:
            if number > MAX_POSTING_POINTERS_PER_ROW:
                raise PhysicalBoundError(
                    f"{name}={number} exceeds pointer bound "
                    f"{MAX_POSTING_POINTERS_PER_ROW}"
                )
        elif resolved is BoundKind.CENTROID_ROWS:
            if number > MAX_ROWS_PER_VECTOR_CENTROID:
                raise PhysicalBoundError(
                    f"{name}={number} exceeds centroid row bound "
                    f"{MAX_ROWS_PER_VECTOR_CENTROID}"
                )
        elif resolved is BoundKind.CENTROID_SHARDS:
            if number > MAX_VECTOR_SHARDS_PER_CENTROID:
                raise PhysicalBoundError(
                    f"{name}={number} exceeds centroid shard bound "
                    f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
                )
        else:
            if number > MAX_ROWS_PER_PHYSICAL_SHARD:
                raise PhysicalBoundError(
                    f"{name}={number} exceeds physical row bound "
                    f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
                )
        return name, number, resolved

    if number == MAX_ROWS_PER_PHYSICAL_SHARD and kind is None:
        raise AmbiguousBoundError(
            f"field {name!r} with value 4096 is ambiguous without bound_kind; "
            f"name a physical bound field or declare model_tokens"
        )
    if kind is None:
        kind = BoundKind.PHYSICAL_ROWS
    return name, number, kind


def validate_centroid_capacity(
    *,
    row_count: Any,
    shard_count: Any,
) -> tuple[int, int]:
    """Enforce centroid capacity: ≤8192 rows and ≤2 physical shards."""

    rows = _require_non_negative_int(row_count, "row_count")
    shards = _require_non_negative_int(shard_count, "shard_count")
    if rows > MAX_ROWS_PER_VECTOR_CENTROID:
        raise PhysicalBoundError(
            f"centroid row_count={rows} exceeds {MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    if shards > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise PhysicalBoundError(
            f"centroid shard_count={shards} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    if shards > 0:
        max_via_shards = shards * MAX_ROWS_PER_PHYSICAL_SHARD
        if rows > max_via_shards:
            raise PhysicalBoundError(
                f"centroid row_count={rows} exceeds capacity of "
                f"{shards} shard(s) × {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
    return rows, shards


# ---------------------------------------------------------------------------
# Identity validation (durable vs release-local)
# ---------------------------------------------------------------------------


def reject_positional_durable_identity(
    value: Any,
    *,
    name: str = "identity",
) -> None:
    """Fail closed when *value* is a positional durable-identity token."""

    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"{name} must not use positional durable identity: {value!r}"
        )
    lowered = text.lower()
    if lowered.startswith("row-") and re.fullmatch(r"row-\d+", lowered):
        raise PositionalIdentityError(
            f"{name} must not use positional durable identity: {value!r}"
        )


def validate_document_index(
    value: Any,
    *,
    name: str = "document_index",
    allow_missing: bool = True,
) -> Optional[int]:
    """Validate release-local ``document_index`` (never durable identity)."""

    if value is None or value == "":
        if allow_missing:
            return None
        raise FederalRegisterReleaseSchemaError(f"{name} is required")
    if isinstance(value, str) and _POSITIONAL_ID_RE.fullmatch(value.strip()):
        raise PositionalIdentityError(
            f"{name} string form is not a valid release-local index: {value!r}"
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterReleaseSchemaError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterReleaseSchemaError(f"{name} must be >= 0")
    return value


def validate_durable_identity_fields(payload: Mapping[str, Any]) -> dict[str, str]:
    """Require ``entry_cid`` + ``legal_id`` + ``source_cid``; reject positional IDs."""

    if not isinstance(payload, Mapping):
        raise FederalRegisterReleaseSchemaError("identity payload must be a mapping")

    for key in ("entry_cid", "legal_id", "source_cid", "primary_key", "id", "row_id"):
        if key in payload:
            reject_positional_durable_identity(payload.get(key), name=key)

    has_entry = payload.get("entry_cid") not in (None, "")
    has_legal = payload.get("legal_id") not in (None, "")
    has_source = payload.get("source_cid") not in (None, "")
    if not has_entry or not has_legal or not has_source:
        for positional_key in (
            "document_index",
            "row_index",
            "row_number",
            "positional_id",
            "embedding_row",
        ):
            if payload.get(positional_key) not in (None, "") and not (
                has_entry and has_legal and has_source
            ):
                raise PositionalIdentityError(
                    f"durable identity requires entry_cid, legal_id, and "
                    f"source_cid; {positional_key} is release-local only"
                )
        missing = [
            name
            for name, present in (
                ("entry_cid", has_entry),
                ("legal_id", has_legal),
                ("source_cid", has_source),
            )
            if not present
        ]
        raise MissingAdmissionProvenanceError(
            f"missing required durable identity fields: {missing}"
        )

    entry_cid = validate_entry_cid(payload["entry_cid"])
    legal_id = validate_legal_id(payload["legal_id"])
    source_cid = validate_digest(payload["source_cid"], name="source_cid")
    validate_document_index(payload.get("document_index"))
    return {
        "entry_cid": entry_cid,
        "legal_id": legal_id,
        "source_cid": source_cid,
    }


def validate_correction_identity(
    *,
    correction_relation: Any,
    related_document_number: Any = None,
    document_type: Any = None,
) -> dict[str, Any]:
    """Validate publication/correction identity linkage.

    When a correction relation other than ``none`` is declared, a related
    document number is required. Correction document types must declare a
    non-``none`` relation.
    """

    relation = CorrectionRelation.coerce(correction_relation)
    doc_type = (
        DocumentType.coerce(document_type)
        if document_type not in (None, "")
        else None
    )
    related: Optional[str] = None
    if related_document_number not in (None, ""):
        related = validate_document_number(
            related_document_number, name="related_document_number"
        )

    if relation is CorrectionRelation.NONE:
        if related is not None:
            raise DocumentIdentityError(
                "related_document_number requires a non-none correction_relation"
            )
        if doc_type is DocumentType.CORRECTION:
            raise DocumentIdentityError(
                "document_type=correction requires a non-none correction_relation"
            )
    else:
        if related is None:
            raise DocumentIdentityError(
                f"correction_relation={relation.value!r} requires "
                f"related_document_number"
            )

    return {
        "correction_relation": relation.value,
        "related_document_number": related,
        "document_type": doc_type.value if doc_type is not None else None,
    }


def validate_text_availability_fields(
    *,
    text_availability: Any,
    text: Any = "",
    admission_status: Any = None,
) -> dict[str, Any]:
    """Validate text availability disposition against body text.

    Admitted rows with a body-bearing disposition require non-empty text.
    Metadata-only / unavailable / failed-final dispositions must not carry
    non-placeholder body text masquerading as full text.
    """

    availability = TextAvailability.coerce(text_availability)
    body = text if isinstance(text, str) else ""
    status = (
        AdmissionStatus.coerce(admission_status)
        if admission_status not in (None, "")
        else None
    )

    if status is AdmissionStatus.ADMITTED:
        if availability is TextAvailability.FAILED_FINAL:
            raise TextAvailabilityError(
                "admitted rows cannot use text_availability=failed_final; "
                "failed body acquisition remains unresolved"
            )
        if availability in BODY_TEXT_AVAILABILITIES and not body.strip():
            raise TextAvailabilityError(
                f"text_availability={availability.value!r} requires non-empty text "
                f"on admitted rows"
            )
        if availability is TextAvailability.METADATA_ONLY and body.strip():
            # Abstracts may still be stored separately; long body text is wrong.
            if len(body.strip()) > 600:
                raise TextAvailabilityError(
                    "metadata_only disposition must not carry full-body text"
                )

    return {
        "text_availability": availability.value,
        "has_usable_body": availability.has_usable_body,
    }


# ---------------------------------------------------------------------------
# Admission / provenance validation
# ---------------------------------------------------------------------------


def validate_admission_provenance_fields(
    payload: Mapping[str, Any],
    *,
    require_admitted_complete: bool = True,
) -> dict[str, Any]:
    """Require admission + official provenance fields for corpus rows.

    When ``admission_status`` is ``admitted``, all provenance fields listed in
    :data:`REQUIRED_PROVENANCE_FIELDS` are mandatory and the source authority
    class must be ``official`` (or an approved documented exception).
    """

    if not isinstance(payload, Mapping):
        raise FederalRegisterReleaseSchemaError("admission payload must be a mapping")

    missing_admission = [
        name
        for name in sorted(REQUIRED_ADMISSION_FIELDS)
        if payload.get(name) in (None, "")
    ]
    if missing_admission:
        raise MissingAdmissionProvenanceError(
            f"missing required admission fields: {missing_admission}"
        )

    status = AdmissionStatus.coerce(payload["admission_status"])
    reason = _require_non_empty_str(payload["admission_reason"], "admission_reason")

    result: dict[str, Any] = {
        "admission_status": status.value,
        "admission_reason": reason,
    }

    if require_admitted_complete and status is AdmissionStatus.ADMITTED:
        missing = [
            name
            for name in sorted(REQUIRED_PROVENANCE_FIELDS)
            if payload.get(name) in (None, "")
        ]
        if missing:
            raise MissingAdmissionProvenanceError(
                f"admitted row missing required provenance fields: {missing}"
            )
        result["source_cid"] = validate_digest(
            payload["source_cid"], name="source_cid"
        )
        result["release_point"] = _require_non_empty_str(
            payload["release_point"], "release_point", maximum=256
        )
        if _MUTABLE_REVISION_RE.fullmatch(result["release_point"]):
            raise MutableReferenceError(
                f"release_point must be an exact pin, not {result['release_point']!r}"
            )
        result["source_checksum"] = normalize_sha256(
            payload["source_checksum"], name="source_checksum"
        )
        result["verification_result"] = VerificationResult.coerce(
            payload["verification_result"]
        ).value
        result["acquisition_time"] = _require_non_empty_str(
            payload["acquisition_time"], "acquisition_time", maximum=64
        )
        result["official_source_url"] = validate_official_url(
            payload["official_source_url"]
        )
        # Optional secondary official URL (e.g. GovInfo package).
        if payload.get("official_pdf_url") not in (None, ""):
            result["official_pdf_url"] = validate_official_url(
                payload["official_pdf_url"], name="official_pdf_url"
            )
        if payload.get("official_html_url") not in (None, ""):
            result["official_html_url"] = validate_official_url(
                payload["official_html_url"], name="official_html_url"
            )
        if payload.get("official_xml_url") not in (None, ""):
            result["official_xml_url"] = validate_official_url(
                payload["official_xml_url"], name="official_xml_url"
            )
        # Optional official content hash (distinct from source_checksum when both set).
        if payload.get("official_content_hash") not in (None, ""):
            result["official_content_hash"] = normalize_sha256(
                payload["official_content_hash"], name="official_content_hash"
            )
        result["acquisition_receipt_id"] = _require_non_empty_str(
            payload["acquisition_receipt_id"],
            "acquisition_receipt_id",
            maximum=256,
        )
        result["parser_version"] = _require_non_empty_str(
            payload["parser_version"], "parser_version", maximum=128
        )
        result["document_number"] = validate_document_number(
            payload["document_number"]
        )
        result["publication_date"] = validate_publication_date(
            payload["publication_date"]
        )
        result["document_type"] = DocumentType.coerce(payload["document_type"]).value
        text_fields = validate_text_availability_fields(
            text_availability=payload["text_availability"],
            text=payload.get("text", ""),
            admission_status=status,
        )
        result["text_availability"] = text_fields["text_availability"]
        result["has_usable_body"] = text_fields["has_usable_body"]

        authority = payload.get("source_authority_class", SourceAuthorityClass.OFFICIAL)
        authority_class = SourceAuthorityClass.coerce(authority)
        if authority_class is SourceAuthorityClass.SECONDARY:
            raise OfficialProvenanceError(
                "admitted rows require official provenance; secondary sources "
                "must be quarantined"
            )
        if authority_class is SourceAuthorityClass.UNKNOWN:
            raise OfficialProvenanceError(
                "admitted rows require known official source authority"
            )
        result["source_authority_class"] = authority_class.value

        correction = validate_correction_identity(
            correction_relation=payload.get(
                "correction_relation", CorrectionRelation.NONE
            ),
            related_document_number=payload.get("related_document_number"),
            document_type=result["document_type"],
        )
        result["correction_relation"] = correction["correction_relation"]
        result["related_document_number"] = correction["related_document_number"]

    return result


# ---------------------------------------------------------------------------
# Semantic-family closure
# ---------------------------------------------------------------------------


def coerce_family_set(values: Iterable[Any]) -> frozenset[ArtifactFamily]:
    """Coerce an iterable of family names/enums into a frozenset."""

    return frozenset(ArtifactFamily.coerce(item) for item in values)


def validate_semantic_family_closure(
    present_families: Iterable[Any],
    *,
    required: Optional[Iterable[Any]] = None,
) -> dict[str, Any]:
    """Require every default semantic family to be present (closure).

    Recovery is intentionally *not* part of the required default set; it may
    exist as a separate quarantine configuration.
    """

    present = coerce_family_set(present_families)
    need = (
        coerce_family_set(required)
        if required is not None
        else REQUIRED_SEMANTIC_FAMILIES
    )
    missing = sorted(family.value for family in (need - present))
    if missing:
        raise SemanticFamilyClosureError(
            f"release missing required semantic families: {missing}"
        )
    return {
        "closed": True,
        "present": sorted(family.value for family in present),
        "required": sorted(family.value for family in need),
        "missing": [],
    }


# ---------------------------------------------------------------------------
# Record dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Descriptor for one release artifact (manifest entry)."""

    relative_path: str
    media_type: str
    sha256: str
    size_bytes: int
    schema_id: str
    family: ArtifactFamily
    row_count: int = 0
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    centroid_id: Optional[str] = None
    year_month: Optional[str] = None
    document_type: Optional[str] = None
    key_range: Optional[tuple[str, str]] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self,
            "media_type",
            _require_non_empty_str(self.media_type, "media_type", maximum=256),
        )
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self,
            "schema_id",
            _require_non_empty_str(self.schema_id, "schema_id", maximum=256),
        )
        family = ArtifactFamily.coerce(self.family)
        object.__setattr__(self, "family", family)
        if family in {
            ArtifactFamily.MANIFEST,
            ArtifactFamily.RECEIPT,
            ArtifactFamily.SOURCE_RECEIPT,
            ArtifactFamily.RELEASE_METADATA,
            ArtifactFamily.REPORT,
            ArtifactFamily.PUBLICATION,
            ArtifactFamily.ROLLBACK,
        }:
            rows = _require_non_negative_int(self.row_count, "row_count")
        else:
            rows = validate_physical_row_count(self.row_count)
        object.__setattr__(self, "row_count", rows)
        if self.first_key is not None:
            object.__setattr__(
                self, "first_key", _optional_str(self.first_key, "first_key")
            )
        if self.last_key is not None:
            object.__setattr__(
                self, "last_key", _optional_str(self.last_key, "last_key")
            )
        if self.centroid_id is not None:
            object.__setattr__(
                self,
                "centroid_id",
                _optional_str(self.centroid_id, "centroid_id"),
            )
        if self.year_month is not None:
            object.__setattr__(
                self, "year_month", validate_year_month(self.year_month)
            )
        if self.document_type is not None:
            object.__setattr__(
                self,
                "document_type",
                DocumentType.coerce(self.document_type).value,
            )
        if self.key_range is not None:
            if (
                not isinstance(self.key_range, (tuple, list))
                or len(self.key_range) != 2
            ):
                raise FederalRegisterReleaseSchemaError(
                    "key_range must be a (first, last) pair"
                )
            object.__setattr__(
                self,
                "key_range",
                (
                    _require_non_empty_str(self.key_range[0], "key_range[0]"),
                    _require_non_empty_str(self.key_range[1], "key_range[1]"),
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_type": self.document_type,
            "family": self.family.value,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_id": self.schema_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "year_month": self.year_month,
        }
        if self.centroid_id is not None:
            payload["centroid_id"] = self.centroid_id
        if self.key_range is not None:
            payload["key_range"] = list(self.key_range)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactDescriptor":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "artifact descriptor must be a mapping"
            )
        key_range = value.get("key_range")
        if isinstance(key_range, list):
            key_range = tuple(key_range)
        return cls(
            relative_path=value.get("relative_path", ""),
            media_type=value.get("media_type", ""),
            sha256=value.get("sha256", ""),
            size_bytes=value.get("size_bytes", 0),
            schema_id=value.get("schema_id") or value.get("schema_identifier", ""),
            family=value.get("family", ArtifactFamily.CORPUS),
            row_count=value.get("row_count", 0),
            first_key=value.get("first_key"),
            last_key=value.get("last_key"),
            centroid_id=value.get("centroid_id"),
            year_month=value.get("year_month"),
            document_type=value.get("document_type"),
            key_range=key_range,
        )


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """Canonical retrieval row for the v2 Federal Register corpus."""

    entry_cid: str
    legal_id: str
    source_cid: str
    document_number: str
    publication_date: str
    document_type: DocumentType
    admission_status: AdmissionStatus
    admission_reason: str
    release_point: str
    source_checksum: str
    verification_result: VerificationResult
    acquisition_time: str
    official_source_url: str
    acquisition_receipt_id: str
    parser_version: str
    text_availability: TextAvailability
    text: str = ""
    title: Optional[str] = None
    abstract: Optional[str] = None
    agencies: tuple[str, ...] = ()
    document_index: Optional[int] = None
    source_authority_class: SourceAuthorityClass = SourceAuthorityClass.OFFICIAL
    correction_relation: CorrectionRelation = CorrectionRelation.NONE
    related_document_number: Optional[str] = None
    official_pdf_url: Optional[str] = None
    official_html_url: Optional[str] = None
    official_xml_url: Optional[str] = None
    official_content_hash: Optional[str] = None
    year_month: Optional[str] = None
    observed_at: Optional[str] = None
    parent_path: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        identity = validate_durable_identity_fields(
            {
                "entry_cid": self.entry_cid,
                "legal_id": self.legal_id,
                "source_cid": self.source_cid,
                "document_index": self.document_index,
            }
        )
        object.__setattr__(self, "entry_cid", identity["entry_cid"])
        object.__setattr__(self, "legal_id", identity["legal_id"])
        object.__setattr__(self, "source_cid", identity["source_cid"])
        object.__setattr__(
            self,
            "document_index",
            validate_document_index(self.document_index),
        )
        admission = validate_admission_provenance_fields(
            {
                "admission_status": self.admission_status,
                "admission_reason": self.admission_reason,
                "source_cid": self.source_cid,
                "release_point": self.release_point,
                "source_checksum": self.source_checksum,
                "verification_result": self.verification_result,
                "acquisition_time": self.acquisition_time,
                "official_source_url": self.official_source_url,
                "official_pdf_url": self.official_pdf_url,
                "official_html_url": self.official_html_url,
                "official_xml_url": self.official_xml_url,
                "official_content_hash": self.official_content_hash,
                "acquisition_receipt_id": self.acquisition_receipt_id,
                "parser_version": self.parser_version,
                "document_number": self.document_number,
                "publication_date": self.publication_date,
                "document_type": self.document_type,
                "text_availability": self.text_availability,
                "text": self.text,
                "source_authority_class": self.source_authority_class,
                "correction_relation": self.correction_relation,
                "related_document_number": self.related_document_number,
            }
        )
        object.__setattr__(
            self,
            "admission_status",
            AdmissionStatus.coerce(admission["admission_status"]),
        )
        object.__setattr__(self, "admission_reason", admission["admission_reason"])
        if "source_cid" in admission:
            object.__setattr__(self, "source_cid", admission["source_cid"])
            object.__setattr__(self, "release_point", admission["release_point"])
            object.__setattr__(self, "source_checksum", admission["source_checksum"])
            object.__setattr__(
                self,
                "verification_result",
                VerificationResult.coerce(admission["verification_result"]),
            )
            object.__setattr__(
                self, "acquisition_time", admission["acquisition_time"]
            )
            object.__setattr__(
                self, "official_source_url", admission["official_source_url"]
            )
            if "official_pdf_url" in admission:
                object.__setattr__(
                    self, "official_pdf_url", admission["official_pdf_url"]
                )
            if "official_html_url" in admission:
                object.__setattr__(
                    self, "official_html_url", admission["official_html_url"]
                )
            if "official_xml_url" in admission:
                object.__setattr__(
                    self, "official_xml_url", admission["official_xml_url"]
                )
            if "official_content_hash" in admission:
                object.__setattr__(
                    self,
                    "official_content_hash",
                    admission["official_content_hash"],
                )
            object.__setattr__(
                self,
                "acquisition_receipt_id",
                admission["acquisition_receipt_id"],
            )
            object.__setattr__(self, "parser_version", admission["parser_version"])
            object.__setattr__(
                self, "document_number", admission["document_number"]
            )
            object.__setattr__(
                self, "publication_date", admission["publication_date"]
            )
            object.__setattr__(
                self,
                "document_type",
                DocumentType.coerce(admission["document_type"]),
            )
            object.__setattr__(
                self,
                "text_availability",
                TextAvailability.coerce(admission["text_availability"]),
            )
            object.__setattr__(
                self,
                "source_authority_class",
                SourceAuthorityClass.coerce(admission["source_authority_class"]),
            )
            object.__setattr__(
                self,
                "correction_relation",
                CorrectionRelation.coerce(admission["correction_relation"]),
            )
            object.__setattr__(
                self,
                "related_document_number",
                admission["related_document_number"],
            )
        else:
            object.__setattr__(
                self,
                "source_cid",
                validate_digest(self.source_cid, name="source_cid"),
            )
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
            object.__setattr__(
                self,
                "publication_date",
                validate_publication_date(self.publication_date),
            )
            object.__setattr__(
                self, "document_type", DocumentType.coerce(self.document_type)
            )
            object.__setattr__(
                self,
                "text_availability",
                TextAvailability.coerce(self.text_availability),
            )
            object.__setattr__(
                self,
                "official_source_url",
                validate_official_url(self.official_source_url)
                if self.official_source_url
                else self.official_source_url,
            )

        if not isinstance(self.text, str):
            raise FederalRegisterReleaseSchemaError("text must be a string")

        # legal_id document_number and publication_date must match fields.
        legal_parts = self.legal_id.split(":")
        legal_doc = legal_parts[1]
        legal_date = legal_parts[2]
        if legal_doc != self.document_number:
            raise DocumentIdentityError(
                f"legal_id document_number {legal_doc!r} does not match "
                f"document_number field {self.document_number!r}"
            )
        if legal_date != self.publication_date:
            raise DocumentIdentityError(
                f"legal_id publication_date {legal_date!r} does not match "
                f"publication_date field {self.publication_date!r}"
            )

        if self.year_month is not None:
            object.__setattr__(
                self, "year_month", validate_year_month(self.year_month)
            )
        else:
            object.__setattr__(self, "year_month", self.publication_date[:7])

        if not isinstance(self.agencies, (list, tuple)):
            raise FederalRegisterReleaseSchemaError("agencies must be a sequence")
        object.__setattr__(
            self,
            "agencies",
            tuple(
                _require_non_empty_str(item, f"agencies[{i}]", maximum=256)
                for i, item in enumerate(self.agencies)
            ),
        )
        if self.title is not None:
            object.__setattr__(self, "title", _optional_str(self.title, "title"))
        if self.abstract is not None:
            object.__setattr__(
                self, "abstract", _optional_str(self.abstract, "abstract")
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"corpus schema_version must be {SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "acquisition_receipt_id": self.acquisition_receipt_id,
            "acquisition_time": self.acquisition_time,
            "admission_reason": self.admission_reason,
            "admission_status": self.admission_status.value,
            "agencies": list(self.agencies),
            "correction_relation": self.correction_relation.value,
            "document_index": self.document_index,
            "document_number": self.document_number,
            "document_type": self.document_type.value,
            "entry_cid": self.entry_cid,
            "legal_id": self.legal_id,
            "observed_at": self.observed_at,
            "official_content_hash": self.official_content_hash,
            "official_html_url": self.official_html_url,
            "official_pdf_url": self.official_pdf_url,
            "official_source_url": self.official_source_url,
            "official_xml_url": self.official_xml_url,
            "parent_path": self.parent_path,
            "parser_version": self.parser_version,
            "publication_date": self.publication_date,
            "related_document_number": self.related_document_number,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "source_authority_class": self.source_authority_class.value,
            "source_checksum": self.source_checksum,
            "source_cid": self.source_cid,
            "text": self.text,
            "text_availability": self.text_availability.value,
            "title": self.title,
            "verification_result": self.verification_result.value,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CorpusRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("corpus record must be a mapping")
        agencies = value.get("agencies") or ()
        if isinstance(agencies, list):
            agencies = tuple(agencies)
        return cls(
            entry_cid=value.get("entry_cid", ""),
            legal_id=value.get("legal_id", ""),
            source_cid=value.get("source_cid", ""),
            document_number=value.get("document_number", ""),
            publication_date=value.get("publication_date", ""),
            document_type=value.get("document_type", ""),
            admission_status=value.get("admission_status", ""),
            admission_reason=value.get("admission_reason", ""),
            release_point=value.get("release_point", ""),
            source_checksum=value.get("source_checksum", ""),
            verification_result=value.get("verification_result", ""),
            acquisition_time=value.get("acquisition_time", ""),
            official_source_url=value.get("official_source_url", ""),
            acquisition_receipt_id=value.get("acquisition_receipt_id", ""),
            parser_version=value.get("parser_version", ""),
            text_availability=value.get("text_availability", ""),
            text=value.get("text", "") or "",
            title=value.get("title"),
            abstract=value.get("abstract"),
            agencies=agencies,
            document_index=value.get("document_index"),
            source_authority_class=value.get(
                "source_authority_class", SourceAuthorityClass.OFFICIAL
            ),
            correction_relation=value.get(
                "correction_relation", CorrectionRelation.NONE
            ),
            related_document_number=value.get("related_document_number"),
            official_pdf_url=value.get("official_pdf_url"),
            official_html_url=value.get("official_html_url"),
            official_xml_url=value.get("official_xml_url"),
            official_content_hash=value.get("official_content_hash"),
            year_month=value.get("year_month"),
            observed_at=value.get("observed_at"),
            parent_path=value.get("parent_path"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SourceReceiptRecord:
    """Per-date-partition official Federal Register acquisition receipt."""

    receipt_id: str
    year_month: str
    partition_start: str
    partition_end: str
    official_source_url: str
    release_point: str
    observation_time: str
    observation_cutoff: str
    source_authority_class: SourceAuthorityClass
    source_checksum: str
    verification_result: VerificationResult
    enumerated: int
    fetched: int
    duplicate: int
    excluded: int
    quarantined: int
    failed_final: int
    frontier_closed: bool
    relative_path: str
    schema_version: str = SCHEMA_VERSION
    api_total: Optional[int] = None
    page_cursors: tuple[str, ...] = ()
    response_hashes: tuple[str, ...] = ()
    document_numbers: tuple[str, ...] = ()
    body_text_dispositions: Mapping[str, int] = field(default_factory=dict)
    source_software_version: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_non_empty_str(self.receipt_id, "receipt_id"),
        )
        object.__setattr__(self, "year_month", validate_year_month(self.year_month))
        object.__setattr__(
            self,
            "partition_start",
            validate_publication_date(self.partition_start, name="partition_start"),
        )
        object.__setattr__(
            self,
            "partition_end",
            validate_publication_date(self.partition_end, name="partition_end"),
        )
        if self.partition_start > self.partition_end:
            raise FederalRegisterReleaseSchemaError(
                "partition_start must be <= partition_end"
            )
        url = validate_official_url(self.official_source_url)
        object.__setattr__(self, "official_source_url", url)
        release_point = _require_non_empty_str(self.release_point, "release_point")
        if _MUTABLE_REVISION_RE.fullmatch(release_point):
            raise MutableReferenceError(
                f"release_point must be exact, not mutable: {release_point!r}"
            )
        object.__setattr__(self, "release_point", release_point)
        object.__setattr__(
            self,
            "observation_time",
            _require_non_empty_str(self.observation_time, "observation_time"),
        )
        object.__setattr__(
            self,
            "observation_cutoff",
            _require_non_empty_str(self.observation_cutoff, "observation_cutoff"),
        )
        authority = SourceAuthorityClass.coerce(self.source_authority_class)
        if authority is SourceAuthorityClass.SECONDARY:
            raise OfficialProvenanceError(
                "source receipts for publication cohort require official "
                "(or approved exception) authority, not secondary"
            )
        object.__setattr__(self, "source_authority_class", authority)
        object.__setattr__(
            self,
            "source_checksum",
            normalize_sha256(self.source_checksum, name="source_checksum"),
        )
        object.__setattr__(
            self,
            "verification_result",
            VerificationResult.coerce(self.verification_result),
        )
        enumerated = _require_non_negative_int(self.enumerated, "enumerated")
        fetched = _require_non_negative_int(self.fetched, "fetched")
        duplicate = _require_non_negative_int(self.duplicate, "duplicate")
        excluded = _require_non_negative_int(self.excluded, "excluded")
        quarantined = _require_non_negative_int(self.quarantined, "quarantined")
        failed_final = _require_non_negative_int(self.failed_final, "failed_final")
        object.__setattr__(self, "enumerated", enumerated)
        object.__setattr__(self, "fetched", fetched)
        object.__setattr__(self, "duplicate", duplicate)
        object.__setattr__(self, "excluded", excluded)
        object.__setattr__(self, "quarantined", quarantined)
        object.__setattr__(self, "failed_final", failed_final)
        # enumerated = fetched + duplicate + excluded + quarantined + failed_final
        accounted = fetched + duplicate + excluded + quarantined + failed_final
        if enumerated != accounted:
            raise FederalRegisterReleaseSchemaError(
                f"source receipt reconciliation failed: enumerated={enumerated} "
                f"!= fetched+duplicate+excluded+quarantined+failed_final={accounted}"
            )
        if not isinstance(self.frontier_closed, bool):
            raise FederalRegisterReleaseSchemaError(
                "frontier_closed must be a boolean"
            )
        if self.frontier_closed and failed_final != 0:
            raise FederalRegisterReleaseSchemaError(
                "frontier_closed=true requires failed_final=0"
            )
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(
                self.relative_path, name="relative_path"
            ),
        )
        if self.api_total is not None:
            object.__setattr__(
                self, "api_total", _require_non_negative_int(self.api_total, "api_total")
            )
        if not isinstance(self.page_cursors, (list, tuple)):
            raise FederalRegisterReleaseSchemaError("page_cursors must be a sequence")
        object.__setattr__(
            self,
            "page_cursors",
            tuple(
                _require_non_empty_str(item, f"page_cursors[{i}]", maximum=512)
                for i, item in enumerate(self.page_cursors)
            ),
        )
        if not isinstance(self.response_hashes, (list, tuple)):
            raise FederalRegisterReleaseSchemaError(
                "response_hashes must be a sequence"
            )
        object.__setattr__(
            self,
            "response_hashes",
            tuple(
                normalize_sha256(item, name=f"response_hashes[{i}]")
                for i, item in enumerate(self.response_hashes)
            ),
        )
        if not isinstance(self.document_numbers, (list, tuple)):
            raise FederalRegisterReleaseSchemaError(
                "document_numbers must be a sequence"
            )
        object.__setattr__(
            self,
            "document_numbers",
            tuple(
                validate_document_number(item, name=f"document_numbers[{i}]")
                for i, item in enumerate(self.document_numbers)
            ),
        )
        if not isinstance(self.body_text_dispositions, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "body_text_dispositions must be a mapping"
            )
        dispositions: dict[str, int] = {}
        for key, count in self.body_text_dispositions.items():
            availability = TextAvailability.coerce(key)
            dispositions[availability.value] = _require_non_negative_int(
                count, f"body_text_dispositions[{key}]"
            )
        object.__setattr__(self, "body_text_dispositions", MappingProxyType(dispositions))
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_total": self.api_total,
            "body_text_dispositions": dict(self.body_text_dispositions),
            "document_numbers": list(self.document_numbers),
            "duplicate": self.duplicate,
            "enumerated": self.enumerated,
            "excluded": self.excluded,
            "failed_final": self.failed_final,
            "fetched": self.fetched,
            "frontier_closed": self.frontier_closed,
            "observation_cutoff": self.observation_cutoff,
            "observation_time": self.observation_time,
            "official_source_url": self.official_source_url,
            "page_cursors": list(self.page_cursors),
            "partition_end": self.partition_end,
            "partition_start": self.partition_start,
            "payload": dict(self.payload),
            "quarantined": self.quarantined,
            "receipt_id": self.receipt_id,
            "relative_path": self.relative_path,
            "release_point": self.release_point,
            "response_hashes": list(self.response_hashes),
            "schema_version": self.schema_version,
            "source_authority_class": self.source_authority_class.value,
            "source_checksum": self.source_checksum,
            "source_software_version": self.source_software_version,
            "verification_result": self.verification_result.value,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceReceiptRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "source receipt must be a mapping"
            )
        page_cursors = value.get("page_cursors") or ()
        response_hashes = value.get("response_hashes") or ()
        document_numbers = value.get("document_numbers") or ()
        if isinstance(page_cursors, list):
            page_cursors = tuple(page_cursors)
        if isinstance(response_hashes, list):
            response_hashes = tuple(response_hashes)
        if isinstance(document_numbers, list):
            document_numbers = tuple(document_numbers)
        return cls(
            receipt_id=value.get("receipt_id", ""),
            year_month=value.get("year_month", ""),
            partition_start=value.get("partition_start", ""),
            partition_end=value.get("partition_end", ""),
            official_source_url=value.get("official_source_url", ""),
            release_point=value.get("release_point", ""),
            observation_time=value.get("observation_time", ""),
            observation_cutoff=value.get(
                "observation_cutoff", DEFAULT_OBSERVATION_CUTOFF
            ),
            source_authority_class=value.get(
                "source_authority_class", SourceAuthorityClass.OFFICIAL
            ),
            source_checksum=value.get("source_checksum", ""),
            verification_result=value.get(
                "verification_result", VerificationResult.VERIFIED
            ),
            enumerated=value.get("enumerated", 0),
            fetched=value.get("fetched", 0),
            duplicate=value.get("duplicate", 0),
            excluded=value.get("excluded", 0),
            quarantined=value.get("quarantined", 0),
            failed_final=value.get("failed_final", 0),
            frontier_closed=value.get("frontier_closed", False),
            relative_path=value.get("relative_path", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            api_total=value.get("api_total"),
            page_cursors=page_cursors,
            response_hashes=response_hashes,
            document_numbers=document_numbers,
            body_text_dispositions=value.get("body_text_dispositions") or {},
            source_software_version=value.get("source_software_version"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class PostingRecord:
    """One BM25 posting-list cell (≤4,096 document pointers)."""

    term: str
    entry_cids: tuple[str, ...]
    term_shard_id: str
    schema_version: str = SCHEMA_VERSION
    document_frequencies: Optional[tuple[int, ...]] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "term", _require_non_empty_str(self.term, "term", maximum=1024)
        )
        object.__setattr__(
            self,
            "term_shard_id",
            _require_non_empty_str(self.term_shard_id, "term_shard_id"),
        )
        if not isinstance(self.entry_cids, (list, tuple)):
            raise FederalRegisterReleaseSchemaError("entry_cids must be a sequence")
        cids = tuple(
            validate_entry_cid(item, name=f"entry_cids[{index}]")
            for index, item in enumerate(self.entry_cids)
        )
        validate_physical_pointer_count(
            len(cids), name="entry_cids", maximum=MAX_POSTING_POINTERS_PER_ROW
        )
        object.__setattr__(self, "entry_cids", cids)
        if self.document_frequencies is not None:
            if not isinstance(self.document_frequencies, (list, tuple)):
                raise FederalRegisterReleaseSchemaError(
                    "document_frequencies must be a sequence"
                )
            if len(self.document_frequencies) != len(cids):
                raise FederalRegisterReleaseSchemaError(
                    "document_frequencies length must match entry_cids"
                )
            freqs = tuple(
                _require_positive_int(item, f"document_frequencies[{index}]")
                for index, item in enumerate(self.document_frequencies)
            )
            object.__setattr__(self, "document_frequencies", freqs)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "entry_cids": list(self.entry_cids),
            "schema_version": self.schema_version,
            "term": self.term,
            "term_shard_id": self.term_shard_id,
        }
        if self.document_frequencies is not None:
            payload["document_frequencies"] = list(self.document_frequencies)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PostingRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("posting record must be a mapping")
        freqs = value.get("document_frequencies")
        if isinstance(freqs, list):
            freqs = tuple(freqs)
        cids = value.get("entry_cids") or ()
        if isinstance(cids, list):
            cids = tuple(cids)
        return cls(
            term=value.get("term", ""),
            entry_cids=cids,
            term_shard_id=value.get("term_shard_id", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            document_frequencies=freqs,
        )


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One embedding row bound to an immutable model revision and entry_cid."""

    entry_cid: str
    vector_space_id: str
    model_id: str
    model_revision: str
    dimension: int
    embedding: tuple[float, ...]
    schema_version: str = SCHEMA_VERSION
    document_index: Optional[int] = None
    chunk_id: Optional[str] = None
    cluster_id: Optional[int] = None
    document_number: Optional[str] = None
    year_month: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_cid", validate_entry_cid(self.entry_cid))
        reject_positional_durable_identity(self.entry_cid, name="entry_cid")
        model_id, model_revision = require_immutable_model_ref(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "vector_space_id",
            _require_non_empty_str(self.vector_space_id, "vector_space_id"),
        )
        if _MUTABLE_REVISION_RE.fullmatch(self.vector_space_id):
            raise MutableReferenceError(
                f"vector_space_id must not be mutable: {self.vector_space_id!r}"
            )
        dim = _require_positive_int(self.dimension, "dimension")
        object.__setattr__(self, "dimension", dim)
        if not isinstance(self.embedding, (list, tuple)):
            raise FederalRegisterReleaseSchemaError(
                "embedding must be a sequence of floats"
            )
        if len(self.embedding) != dim:
            raise FederalRegisterReleaseSchemaError(
                f"embedding length {len(self.embedding)} != dimension {dim}"
            )
        values = []
        for index, item in enumerate(self.embedding):
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise FederalRegisterReleaseSchemaError(
                    f"embedding[{index}] must be a finite number"
                )
            number = float(item)
            if number != number or number in (float("inf"), float("-inf")):
                raise FederalRegisterReleaseSchemaError(
                    f"embedding[{index}] must be finite"
                )
            values.append(number)
        object.__setattr__(self, "embedding", tuple(values))
        object.__setattr__(
            self,
            "document_index",
            validate_document_index(self.document_index),
        )
        if self.chunk_id is not None:
            object.__setattr__(
                self, "chunk_id", _optional_str(self.chunk_id, "chunk_id")
            )
            reject_positional_durable_identity(self.chunk_id, name="chunk_id")
        if self.cluster_id is not None:
            object.__setattr__(
                self,
                "cluster_id",
                _require_non_negative_int(self.cluster_id, "cluster_id"),
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
        if self.year_month is not None:
            object.__setattr__(
                self, "year_month", validate_year_month(self.year_month)
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "cluster_id": self.cluster_id,
            "dimension": self.dimension,
            "document_index": self.document_index,
            "document_number": self.document_number,
            "embedding": list(self.embedding),
            "entry_cid": self.entry_cid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "schema_version": self.schema_version,
            "vector_space_id": self.vector_space_id,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VectorRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("vector record must be a mapping")
        embedding = value.get("embedding") or ()
        if isinstance(embedding, list):
            embedding = tuple(embedding)
        return cls(
            entry_cid=value.get("entry_cid", ""),
            vector_space_id=value.get("vector_space_id", ""),
            model_id=value.get("model_id", ""),
            model_revision=value.get("model_revision", ""),
            dimension=value.get("dimension", 0),
            embedding=embedding,
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            document_index=value.get("document_index"),
            chunk_id=value.get("chunk_id"),
            cluster_id=value.get("cluster_id"),
            document_number=value.get("document_number"),
            year_month=value.get("year_month"),
        )


@dataclass(frozen=True, slots=True)
class CentroidRecord:
    """Routing centroid for dense retrieval (≤8192 rows, ≤2 shards)."""

    centroid_id: str
    vector_space_id: str
    model_id: str
    model_revision: str
    dimension: int
    centroid: tuple[float, ...]
    row_count: int
    shard_count: int
    shard_descriptors: tuple[str, ...] = ()
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "centroid_id",
            _require_non_empty_str(self.centroid_id, "centroid_id"),
        )
        model_id, model_revision = require_immutable_model_ref(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "vector_space_id",
            _require_non_empty_str(self.vector_space_id, "vector_space_id"),
        )
        dim = _require_positive_int(self.dimension, "dimension")
        object.__setattr__(self, "dimension", dim)
        if not isinstance(self.centroid, (list, tuple)):
            raise FederalRegisterReleaseSchemaError(
                "centroid must be a sequence of floats"
            )
        if len(self.centroid) != dim:
            raise FederalRegisterReleaseSchemaError(
                f"centroid length {len(self.centroid)} != dimension {dim}"
            )
        values = tuple(float(x) for x in self.centroid)
        object.__setattr__(self, "centroid", values)
        rows, shards = validate_centroid_capacity(
            row_count=self.row_count, shard_count=self.shard_count
        )
        object.__setattr__(self, "row_count", rows)
        object.__setattr__(self, "shard_count", shards)
        if not isinstance(self.shard_descriptors, (list, tuple)):
            raise FederalRegisterReleaseSchemaError(
                "shard_descriptors must be a sequence"
            )
        descriptors = tuple(
            normalize_relative_artifact_path(
                item, name=f"shard_descriptors[{index}]"
            )
            for index, item in enumerate(self.shard_descriptors)
        )
        if descriptors and len(descriptors) != shards:
            raise FederalRegisterReleaseSchemaError(
                "shard_descriptors length must match shard_count"
            )
        object.__setattr__(self, "shard_descriptors", descriptors)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "centroid": list(self.centroid),
            "centroid_id": self.centroid_id,
            "dimension": self.dimension,
            "max_score": self.max_score,
            "min_score": self.min_score,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "shard_count": self.shard_count,
            "shard_descriptors": list(self.shard_descriptors),
            "vector_space_id": self.vector_space_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CentroidRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "centroid record must be a mapping"
            )
        centroid = value.get("centroid") or ()
        if isinstance(centroid, list):
            centroid = tuple(centroid)
        shards = value.get("shard_descriptors") or ()
        if isinstance(shards, list):
            shards = tuple(shards)
        return cls(
            centroid_id=value.get("centroid_id", ""),
            vector_space_id=value.get("vector_space_id", ""),
            model_id=value.get("model_id", ""),
            model_revision=value.get("model_revision", ""),
            dimension=value.get("dimension", 0),
            centroid=centroid,
            row_count=value.get("row_count", 0),
            shard_count=value.get("shard_count", 0),
            shard_descriptors=shards,
            min_score=value.get("min_score"),
            max_score=value.get("max_score"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class GraphNodeRecord:
    """One knowledge-graph node with deterministic node CID."""

    node_cid: str
    node_type: str
    schema_version: str = SCHEMA_VERSION
    legal_id: Optional[str] = None
    entry_cid: Optional[str] = None
    document_number: Optional[str] = None
    label: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_cid", validate_entry_cid(self.node_cid, name="node_cid")
        )
        object.__setattr__(
            self,
            "node_type",
            _require_non_empty_str(self.node_type, "node_type", maximum=128),
        )
        if self.legal_id is not None:
            object.__setattr__(self, "legal_id", validate_legal_id(self.legal_id))
        if self.entry_cid is not None:
            object.__setattr__(
                self, "entry_cid", validate_entry_cid(self.entry_cid)
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
        if self.label is not None:
            object.__setattr__(self, "label", _optional_str(self.label, "label"))
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "entry_cid": self.entry_cid,
            "label": self.label,
            "legal_id": self.legal_id,
            "node_cid": self.node_cid,
            "node_type": self.node_type,
            "payload": dict(self.payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphNodeRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("graph node must be a mapping")
        return cls(
            node_cid=value.get("node_cid", ""),
            node_type=value.get("node_type", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            legal_id=value.get("legal_id"),
            entry_cid=value.get("entry_cid"),
            document_number=value.get("document_number"),
            label=value.get("label"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class GraphEdgeRecord:
    """One knowledge-graph edge with deterministic edge CID."""

    edge_cid: str
    edge_type: str
    source_node_cid: str
    target_node_cid: str
    schema_version: str = SCHEMA_VERSION
    weight: Optional[float] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_cid", validate_entry_cid(self.edge_cid, name="edge_cid")
        )
        object.__setattr__(
            self,
            "edge_type",
            _require_non_empty_str(self.edge_type, "edge_type", maximum=128),
        )
        object.__setattr__(
            self,
            "source_node_cid",
            validate_entry_cid(self.source_node_cid, name="source_node_cid"),
        )
        object.__setattr__(
            self,
            "target_node_cid",
            validate_entry_cid(self.target_node_cid, name="target_node_cid"),
        )
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_cid": self.edge_cid,
            "edge_type": self.edge_type,
            "payload": dict(self.payload),
            "schema_version": self.schema_version,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
            "weight": self.weight,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphEdgeRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("graph edge must be a mapping")
        return cls(
            edge_cid=value.get("edge_cid", ""),
            edge_type=value.get("edge_type", ""),
            source_node_cid=value.get("source_node_cid", ""),
            target_node_cid=value.get("target_node_cid", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            weight=value.get("weight"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class AdjacencyRecord:
    """One adjacency page (≤4,096 edge pointers), in or out direction."""

    node_cid: str
    direction: str
    edge_cids: tuple[str, ...]
    page_index: int = 0
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_cid", validate_entry_cid(self.node_cid, name="node_cid")
        )
        direction = _require_non_empty_str(self.direction, "direction").lower()
        if direction not in {"in", "out", "incoming", "outgoing"}:
            raise FederalRegisterReleaseSchemaError(
                f"direction must be in/out/incoming/outgoing, got {self.direction!r}"
            )
        if direction in {"incoming", "in"}:
            direction = "in"
        else:
            direction = "out"
        object.__setattr__(self, "direction", direction)
        if not isinstance(self.edge_cids, (list, tuple)):
            raise FederalRegisterReleaseSchemaError("edge_cids must be a sequence")
        edges = tuple(
            validate_entry_cid(item, name=f"edge_cids[{index}]")
            for index, item in enumerate(self.edge_cids)
        )
        validate_physical_pointer_count(
            len(edges),
            name="edge_cids",
            maximum=MAX_ADJACENCY_POINTERS_PER_ROW,
        )
        object.__setattr__(self, "edge_cids", edges)
        object.__setattr__(
            self,
            "page_index",
            _require_non_negative_int(self.page_index, "page_index"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "edge_cids": list(self.edge_cids),
            "node_cid": self.node_cid,
            "page_index": self.page_index,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AdjacencyRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "adjacency record must be a mapping"
            )
        edges = value.get("edge_cids") or ()
        if isinstance(edges, list):
            edges = tuple(edges)
        return cls(
            node_cid=value.get("node_cid", ""),
            direction=value.get("direction", ""),
            edge_cids=edges,
            page_index=value.get("page_index", 0),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LocatorRecord:
    """Compact locator / routing row pointing at a relative artifact path."""

    locator_id: str
    relative_path: str
    sha256: str
    family: ArtifactFamily
    first_key: str
    last_key: str
    row_count: int
    schema_version: str = SCHEMA_VERSION
    size_bytes: int = 0
    year_month: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "locator_id",
            _require_non_empty_str(self.locator_id, "locator_id"),
        )
        reject_positional_durable_identity(self.locator_id, name="locator_id")
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
        object.__setattr__(self, "family", ArtifactFamily.coerce(self.family))
        object.__setattr__(
            self,
            "first_key",
            _require_non_empty_str(self.first_key, "first_key"),
        )
        object.__setattr__(
            self, "last_key", _require_non_empty_str(self.last_key, "last_key")
        )
        object.__setattr__(
            self, "row_count", validate_physical_row_count(self.row_count)
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        if self.year_month is not None:
            object.__setattr__(
                self, "year_month", validate_year_month(self.year_month)
            )
        if self.document_type is not None:
            object.__setattr__(
                self,
                "document_type",
                DocumentType.coerce(self.document_type).value,
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "document_type": self.document_type,
            "family": self.family.value,
            "first_key": self.first_key,
            "last_key": self.last_key,
            "locator_id": self.locator_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocatorRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "locator record must be a mapping"
            )
        return cls(
            locator_id=value.get("locator_id", ""),
            relative_path=value.get("relative_path", ""),
            sha256=value.get("sha256", ""),
            family=value.get("family", ArtifactFamily.LOCATOR_INDEX),
            first_key=value.get("first_key", ""),
            last_key=value.get("last_key", ""),
            row_count=value.get("row_count", 0),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            size_bytes=value.get("size_bytes", 0),
            year_month=value.get("year_month"),
            document_type=value.get("document_type"),
            document_number=value.get("document_number"),
        )


@dataclass(frozen=True, slots=True)
class ReceiptRecord:
    """Build receipt bound to digests and an exact release point."""

    receipt_id: str
    release_point: str
    manifest_digest: str
    schema_version: str = SCHEMA_VERSION
    source_revision: Optional[str] = None
    package_version: Optional[str] = None
    build_config_cid: Optional[str] = None
    acquired_at: Optional[str] = None
    observation_cutoff: Optional[str] = None
    verification_result: VerificationResult = VerificationResult.VERIFIED
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_non_empty_str(self.receipt_id, "receipt_id"),
        )
        release_point = _require_non_empty_str(self.release_point, "release_point")
        if _MUTABLE_REVISION_RE.fullmatch(release_point):
            raise MutableReferenceError(
                f"release_point must be exact, not mutable: {release_point!r}"
            )
        object.__setattr__(self, "release_point", release_point)
        object.__setattr__(
            self,
            "manifest_digest",
            validate_digest(self.manifest_digest, name="manifest_digest"),
        )
        if self.source_revision is not None:
            object.__setattr__(
                self,
                "source_revision",
                require_immutable_revision(
                    self.source_revision, name="source_revision"
                ),
            )
        if self.build_config_cid is not None:
            object.__setattr__(
                self,
                "build_config_cid",
                validate_digest(self.build_config_cid, name="build_config_cid"),
            )
        object.__setattr__(
            self,
            "verification_result",
            VerificationResult.coerce(self.verification_result),
        )
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquired_at": self.acquired_at,
            "build_config_cid": self.build_config_cid,
            "manifest_digest": self.manifest_digest,
            "observation_cutoff": self.observation_cutoff,
            "package_version": self.package_version,
            "payload": dict(self.payload),
            "receipt_id": self.receipt_id,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "verification_result": self.verification_result.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReceiptRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("receipt record must be a mapping")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            release_point=value.get("release_point", ""),
            manifest_digest=value.get("manifest_digest", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            source_revision=value.get("source_revision"),
            package_version=value.get("package_version"),
            build_config_cid=value.get("build_config_cid"),
            acquired_at=value.get("acquired_at"),
            observation_cutoff=value.get("observation_cutoff"),
            verification_result=value.get(
                "verification_result", VerificationResult.VERIFIED
            ),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    """Quarantined / recovery row that cannot enter canonical counts."""

    recovery_id: str
    reason: str
    schema_version: str = SCHEMA_VERSION
    source_path: Optional[str] = None
    raw_digest: Optional[str] = None
    admission_status: AdmissionStatus = AdmissionStatus.RECOVERY
    document_number: Optional[str] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "recovery_id",
            _require_non_empty_str(self.recovery_id, "recovery_id"),
        )
        reject_positional_durable_identity(self.recovery_id, name="recovery_id")
        object.__setattr__(
            self, "reason", _require_non_empty_str(self.reason, "reason")
        )
        status = AdmissionStatus.coerce(self.admission_status)
        if status is AdmissionStatus.ADMITTED:
            raise FederalRegisterReleaseSchemaError(
                "recovery records cannot have admission_status=admitted"
            )
        object.__setattr__(self, "admission_status", status)
        if self.source_path is not None:
            object.__setattr__(
                self,
                "source_path",
                normalize_relative_artifact_path(
                    self.source_path, name="source_path"
                ),
            )
        if self.raw_digest is not None:
            object.__setattr__(
                self,
                "raw_digest",
                validate_digest(self.raw_digest, name="raw_digest"),
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission_status": self.admission_status.value,
            "document_number": self.document_number,
            "payload": dict(self.payload),
            "raw_digest": self.raw_digest,
            "reason": self.reason,
            "recovery_id": self.recovery_id,
            "schema_version": self.schema_version,
            "source_path": self.source_path,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RecoveryRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "recovery record must be a mapping"
            )
        return cls(
            recovery_id=value.get("recovery_id", ""),
            reason=value.get("reason", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            source_path=value.get("source_path"),
            raw_digest=value.get("raw_digest"),
            admission_status=value.get(
                "admission_status", AdmissionStatus.RECOVERY
            ),
            document_number=value.get("document_number"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    """Immutable-Hub publication receipt for a verified Federal Register release."""

    publication_id: str
    dataset_repo_id: str
    public_revision: str
    previous_revision: str
    manifest_digest: str
    staging_revision: str
    published_at: str
    authorization_receipt_id: str
    schema_version: str = SCHEMA_VERSION
    additive_only: bool = True
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "publication_id",
            _require_non_empty_str(self.publication_id, "publication_id"),
        )
        repo = _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id")
        if not _DATASET_ID_RE.fullmatch(repo):
            raise FederalRegisterReleaseSchemaError(
                f"dataset_repo_id must look like org/name, got {repo!r}"
            )
        if repo != DEFAULT_DATASET_REPO_ID:
            raise FederalRegisterReleaseSchemaError(
                f"publication target must be {DEFAULT_DATASET_REPO_ID!r}, "
                f"got {repo!r}"
            )
        object.__setattr__(self, "dataset_repo_id", repo)
        object.__setattr__(
            self,
            "public_revision",
            require_immutable_revision(
                self.public_revision, name="public_revision"
            ),
        )
        object.__setattr__(
            self,
            "previous_revision",
            require_immutable_revision(
                self.previous_revision, name="previous_revision"
            ),
        )
        object.__setattr__(
            self,
            "staging_revision",
            require_immutable_revision(
                self.staging_revision, name="staging_revision"
            ),
        )
        object.__setattr__(
            self,
            "manifest_digest",
            validate_digest(self.manifest_digest, name="manifest_digest"),
        )
        object.__setattr__(
            self,
            "published_at",
            _require_non_empty_str(self.published_at, "published_at"),
        )
        object.__setattr__(
            self,
            "authorization_receipt_id",
            _require_non_empty_str(
                self.authorization_receipt_id, "authorization_receipt_id"
            ),
        )
        if not isinstance(self.additive_only, bool):
            raise FederalRegisterReleaseSchemaError("additive_only must be a boolean")
        if not self.additive_only:
            raise FederalRegisterReleaseSchemaError(
                "Federal Register publication must be additive_only=true"
            )
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "additive_only": self.additive_only,
            "authorization_receipt_id": self.authorization_receipt_id,
            "dataset_repo_id": self.dataset_repo_id,
            "manifest_digest": self.manifest_digest,
            "payload": dict(self.payload),
            "previous_revision": self.previous_revision,
            "public_revision": self.public_revision,
            "publication_id": self.publication_id,
            "published_at": self.published_at,
            "schema_version": self.schema_version,
            "staging_revision": self.staging_revision,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PublicationRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "publication record must be a mapping"
            )
        return cls(
            publication_id=value.get("publication_id", ""),
            dataset_repo_id=value.get(
                "dataset_repo_id", DEFAULT_DATASET_REPO_ID
            ),
            public_revision=value.get("public_revision", ""),
            previous_revision=value.get("previous_revision", ""),
            manifest_digest=value.get("manifest_digest", ""),
            staging_revision=value.get("staging_revision", ""),
            published_at=value.get("published_at", ""),
            authorization_receipt_id=value.get("authorization_receipt_id", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            additive_only=value.get("additive_only", True),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    """Rollback receipt that restores a prior immutable public pin."""

    rollback_id: str
    dataset_repo_id: str
    from_revision: str
    to_revision: str
    reason: str
    rolled_back_at: str
    manifest_digest: str
    schema_version: str = SCHEMA_VERSION
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rollback_id",
            _require_non_empty_str(self.rollback_id, "rollback_id"),
        )
        repo = _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id")
        if not _DATASET_ID_RE.fullmatch(repo):
            raise FederalRegisterReleaseSchemaError(
                f"dataset_repo_id must look like org/name, got {repo!r}"
            )
        object.__setattr__(self, "dataset_repo_id", repo)
        object.__setattr__(
            self,
            "from_revision",
            require_immutable_revision(self.from_revision, name="from_revision"),
        )
        object.__setattr__(
            self,
            "to_revision",
            require_immutable_revision(self.to_revision, name="to_revision"),
        )
        if self.from_revision == self.to_revision:
            raise FederalRegisterReleaseSchemaError(
                "rollback from_revision and to_revision must differ"
            )
        object.__setattr__(
            self, "reason", _require_non_empty_str(self.reason, "reason")
        )
        object.__setattr__(
            self,
            "rolled_back_at",
            _require_non_empty_str(self.rolled_back_at, "rolled_back_at"),
        )
        object.__setattr__(
            self,
            "manifest_digest",
            validate_digest(self.manifest_digest, name="manifest_digest"),
        )
        if not isinstance(self.payload, Mapping):
            raise FederalRegisterReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_repo_id": self.dataset_repo_id,
            "from_revision": self.from_revision,
            "manifest_digest": self.manifest_digest,
            "payload": dict(self.payload),
            "reason": self.reason,
            "rollback_id": self.rollback_id,
            "rolled_back_at": self.rolled_back_at,
            "schema_version": self.schema_version,
            "to_revision": self.to_revision,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RollbackRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "rollback record must be a mapping"
            )
        return cls(
            rollback_id=value.get("rollback_id", ""),
            dataset_repo_id=value.get(
                "dataset_repo_id", DEFAULT_DATASET_REPO_ID
            ),
            from_revision=value.get("from_revision", ""),
            to_revision=value.get("to_revision", ""),
            reason=value.get("reason", ""),
            rolled_back_at=value.get("rolled_back_at", ""),
            manifest_digest=value.get("manifest_digest", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Top-level v2 release manifest with pinned provenance and descriptors."""

    dataset_repo_id: str
    release_profile: str
    source_revision: str
    build_config_cid: str
    vector_space_id: str
    model_id: str
    model_revision: str
    tokenizer_id: str
    graph_ontology_version: str
    artifacts: tuple[ArtifactDescriptor, ...]
    schema_version: str = SCHEMA_VERSION
    package_version: str = "2"
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    max_rows_per_physical_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_posting_pointers_per_row: int = MAX_POSTING_POINTERS_PER_ROW
    max_adjacency_pointers_per_row: int = MAX_ADJACENCY_POINTERS_PER_ROW
    max_rows_per_vector_centroid: int = MAX_ROWS_PER_VECTOR_CENTROID
    max_vector_shards_per_centroid: int = MAX_VECTOR_SHARDS_PER_CENTROID
    determinism_seeds: Mapping[str, Any] = field(default_factory=dict)
    release_point: Optional[str] = None
    observation_cutoff: Optional[str] = None
    enforce_semantic_family_closure: bool = True

    def __post_init__(self) -> None:
        repo = _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id")
        if not _DATASET_ID_RE.fullmatch(repo):
            raise FederalRegisterReleaseSchemaError(
                f"dataset_repo_id must look like org/name, got {repo!r}"
            )
        object.__setattr__(self, "dataset_repo_id", repo)
        profile = _require_non_empty_str(self.release_profile, "release_profile")
        if profile != RELEASE_PROFILE:
            raise SchemaVersionError(
                f"release_profile must be {RELEASE_PROFILE!r}, got {profile!r}"
            )
        object.__setattr__(self, "release_profile", profile)
        object.__setattr__(
            self,
            "source_revision",
            require_immutable_revision(
                self.source_revision, name="source_revision"
            ),
        )
        object.__setattr__(
            self,
            "build_config_cid",
            validate_digest(self.build_config_cid, name="build_config_cid"),
        )
        model_id, model_revision = require_immutable_model_ref(
            model_id=self.model_id,
            model_revision=self.model_revision,
        )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", model_revision)
        object.__setattr__(
            self,
            "vector_space_id",
            _require_non_empty_str(self.vector_space_id, "vector_space_id"),
        )
        if _MUTABLE_REVISION_RE.fullmatch(self.vector_space_id):
            raise MutableReferenceError(
                f"vector_space_id must not be mutable: {self.vector_space_id!r}"
            )
        object.__setattr__(
            self,
            "tokenizer_id",
            _require_non_empty_str(self.tokenizer_id, "tokenizer_id"),
        )
        object.__setattr__(
            self,
            "graph_ontology_version",
            _require_non_empty_str(
                self.graph_ontology_version, "graph_ontology_version"
            ),
        )
        if not isinstance(self.artifacts, (list, tuple)):
            raise FederalRegisterReleaseSchemaError("artifacts must be a sequence")
        descriptors: list[ArtifactDescriptor] = []
        seen_paths: set[str] = set()
        for item in self.artifacts:
            if isinstance(item, ArtifactDescriptor):
                descriptor = item
            elif isinstance(item, Mapping):
                descriptor = ArtifactDescriptor.from_mapping(item)
            else:
                raise FederalRegisterReleaseSchemaError(
                    "artifacts entries must be ArtifactDescriptor or mapping"
                )
            if descriptor.relative_path in seen_paths:
                raise FederalRegisterReleaseSchemaError(
                    f"duplicate artifact path: {descriptor.relative_path!r}"
                )
            seen_paths.add(descriptor.relative_path)
            descriptors.append(descriptor)
        descriptors_sorted = tuple(
            sorted(descriptors, key=lambda item: item.relative_path)
        )
        object.__setattr__(self, "artifacts", descriptors_sorted)

        for field_name, value, default, kind in (
            (
                "max_rows_per_physical_shard",
                self.max_rows_per_physical_shard,
                MAX_ROWS_PER_PHYSICAL_SHARD,
                BoundKind.PHYSICAL_ROWS,
            ),
            (
                "max_posting_pointers_per_row",
                self.max_posting_pointers_per_row,
                MAX_POSTING_POINTERS_PER_ROW,
                BoundKind.PHYSICAL_POINTERS,
            ),
            (
                "max_adjacency_pointers_per_row",
                self.max_adjacency_pointers_per_row,
                MAX_ADJACENCY_POINTERS_PER_ROW,
                BoundKind.PHYSICAL_POINTERS,
            ),
            (
                "max_rows_per_vector_centroid",
                self.max_rows_per_vector_centroid,
                MAX_ROWS_PER_VECTOR_CENTROID,
                BoundKind.CENTROID_ROWS,
            ),
            (
                "max_vector_shards_per_centroid",
                self.max_vector_shards_per_centroid,
                MAX_VECTOR_SHARDS_PER_CENTROID,
                BoundKind.CENTROID_SHARDS,
            ),
        ):
            _, number, _ = validate_bound_declaration(
                field_name=field_name, value=value, bound_kind=kind
            )
            if number > default:
                raise PhysicalBoundError(
                    f"{field_name}={number} exceeds sealed maximum {default}"
                )
            object.__setattr__(self, field_name, number)

        if not isinstance(self.determinism_seeds, Mapping):
            raise FederalRegisterReleaseSchemaError(
                "determinism_seeds must be a mapping"
            )
        object.__setattr__(
            self,
            "determinism_seeds",
            MappingProxyType(dict(self.determinism_seeds)),
        )
        if self.release_point is not None:
            rp = _require_non_empty_str(self.release_point, "release_point")
            if _MUTABLE_REVISION_RE.fullmatch(rp):
                raise MutableReferenceError(
                    f"release_point must be exact, not mutable: {rp!r}"
                )
            object.__setattr__(self, "release_point", rp)
        if self.observation_cutoff is not None:
            object.__setattr__(
                self,
                "observation_cutoff",
                _require_non_empty_str(
                    self.observation_cutoff, "observation_cutoff"
                ),
            )

        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"manifest schema_version must be {SCHEMA_VERSION!r}, "
                f"got {self.schema_version!r}"
            )

        if self.enforce_semantic_family_closure:
            validate_semantic_family_closure(
                descriptor.family for descriptor in descriptors_sorted
            )

    @property
    def manifest_digest(self) -> str:
        """SHA-256 of the canonical manifest JSON (without self-digest)."""

        return digest_mapping(self.to_dict())

    def present_families(self) -> frozenset[ArtifactFamily]:
        return frozenset(item.family for item in self.artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "bm25_b": self.bm25_b,
            "bm25_k1": self.bm25_k1,
            "build_config_cid": self.build_config_cid,
            "dataset_repo_id": self.dataset_repo_id,
            "determinism_seeds": dict(self.determinism_seeds),
            "enforce_semantic_family_closure": self.enforce_semantic_family_closure,
            "graph_ontology_version": self.graph_ontology_version,
            "max_adjacency_pointers_per_row": self.max_adjacency_pointers_per_row,
            "max_posting_pointers_per_row": self.max_posting_pointers_per_row,
            "max_rows_per_physical_shard": self.max_rows_per_physical_shard,
            "max_rows_per_vector_centroid": self.max_rows_per_vector_centroid,
            "max_vector_shards_per_centroid": self.max_vector_shards_per_centroid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "observation_cutoff": self.observation_cutoff,
            "package_version": self.package_version,
            "release_point": self.release_point,
            "release_profile": self.release_profile,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "tokenizer_id": self.tokenizer_id,
            "vector_space_id": self.vector_space_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReleaseManifest":
        if not isinstance(value, Mapping):
            raise FederalRegisterReleaseSchemaError("manifest must be a mapping")
        artifacts = value.get("artifacts") or ()
        return cls(
            dataset_repo_id=value.get("dataset_repo_id", DEFAULT_DATASET_REPO_ID),
            release_profile=value.get("release_profile", RELEASE_PROFILE),
            source_revision=value.get("source_revision", ""),
            build_config_cid=value.get("build_config_cid", ""),
            vector_space_id=value.get("vector_space_id", ""),
            model_id=value.get("model_id", ""),
            model_revision=value.get("model_revision", ""),
            tokenizer_id=value.get("tokenizer_id", ""),
            graph_ontology_version=value.get("graph_ontology_version", ""),
            artifacts=tuple(artifacts),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            package_version=str(value.get("package_version", "2")),
            bm25_k1=float(value.get("bm25_k1", 1.2)),
            bm25_b=float(value.get("bm25_b", 0.75)),
            max_rows_per_physical_shard=value.get(
                "max_rows_per_physical_shard", MAX_ROWS_PER_PHYSICAL_SHARD
            ),
            max_posting_pointers_per_row=value.get(
                "max_posting_pointers_per_row", MAX_POSTING_POINTERS_PER_ROW
            ),
            max_adjacency_pointers_per_row=value.get(
                "max_adjacency_pointers_per_row", MAX_ADJACENCY_POINTERS_PER_ROW
            ),
            max_rows_per_vector_centroid=value.get(
                "max_rows_per_vector_centroid", MAX_ROWS_PER_VECTOR_CENTROID
            ),
            max_vector_shards_per_centroid=value.get(
                "max_vector_shards_per_centroid", MAX_VECTOR_SHARDS_PER_CENTROID
            ),
            determinism_seeds=value.get("determinism_seeds") or {},
            release_point=value.get("release_point"),
            observation_cutoff=value.get("observation_cutoff"),
            enforce_semantic_family_closure=bool(
                value.get("enforce_semantic_family_closure", True)
            ),
        )


# ---------------------------------------------------------------------------
# Composite validators / factory helpers
# ---------------------------------------------------------------------------


def validate_release_record(
    record_type: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate *payload* as the named record type; return ``to_dict()``."""

    kind = _require_non_empty_str(record_type, "record_type").lower().replace(
        "-", "_"
    )
    constructors = {
        "corpus": CorpusRecord.from_mapping,
        "source_receipt": SourceReceiptRecord.from_mapping,
        "posting": PostingRecord.from_mapping,
        "vector": VectorRecord.from_mapping,
        "centroid": CentroidRecord.from_mapping,
        "graph_node": GraphNodeRecord.from_mapping,
        "graph_edge": GraphEdgeRecord.from_mapping,
        "adjacency": AdjacencyRecord.from_mapping,
        "locator": LocatorRecord.from_mapping,
        "manifest": ReleaseManifest.from_mapping,
        "receipt": ReceiptRecord.from_mapping,
        "recovery": RecoveryRecord.from_mapping,
        "publication": PublicationRecord.from_mapping,
        "rollback": RollbackRecord.from_mapping,
        "artifact_descriptor": ArtifactDescriptor.from_mapping,
    }
    if kind not in constructors:
        raise FederalRegisterReleaseSchemaError(f"unknown record type: {record_type!r}")
    record = constructors[kind](payload)
    return record.to_dict()


def physical_bounds_policy() -> dict[str, int]:
    """Return the sealed physical-bound constants as a plain dict."""

    return {
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_posting_pointers_per_row": MAX_POSTING_POINTERS_PER_ROW,
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_routing_rows_per_index": MAX_ROUTING_ROWS_PER_INDEX,
        "max_term_rows_per_shard": MAX_TERM_ROWS_PER_SHARD,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
    }


def required_semantic_families() -> tuple[str, ...]:
    """Return the sorted required semantic-family names for default releases."""

    return tuple(sorted(family.value for family in REQUIRED_SEMANTIC_FAMILIES))


def _closed_family_artifacts() -> list[dict[str, Any]]:
    """Minimal descriptor set that satisfies semantic-family closure."""

    families_paths = [
        (
            ArtifactFamily.CORPUS,
            "data/corpus/year_month=2026-03/document_type=rule/part-000000.parquet",
        ),
        (
            ArtifactFamily.BM25_DOCUMENTS,
            "data/bm25/documents/year_month=2026-03/document_type=rule/part-000000.parquet",
        ),
        (ArtifactFamily.BM25_POSTINGS, "data/bm25/postings/part-000000.parquet"),
        (ArtifactFamily.VECTORS, "data/vectors/centroid-000-part-000000.parquet"),
        (ArtifactFamily.CENTROIDS, "data/vectors/centroids.parquet"),
        (ArtifactFamily.GRAPH_NODES, "data/graph/nodes/part-000000.parquet"),
        (ArtifactFamily.GRAPH_EDGES, "data/graph/edges/part-000000.parquet"),
        (
            ArtifactFamily.GRAPH_ADJACENCY_OUT,
            "data/graph/adjacency/out/part-000000.parquet",
        ),
        (
            ArtifactFamily.GRAPH_ADJACENCY_IN,
            "data/graph/adjacency/in/part-000000.parquet",
        ),
        (ArtifactFamily.LOCATOR_INDEX, "indexes/locators.parquet"),
        (ArtifactFamily.MANIFEST, "manifest.json"),
    ]
    artifacts: list[dict[str, Any]] = []
    for family, path in families_paths:
        artifacts.append(
            {
                "relative_path": path,
                "media_type": (
                    "application/json"
                    if family is ArtifactFamily.MANIFEST
                    else "application/vnd.apache.parquet"
                ),
                "sha256": content_sha256(path),
                "size_bytes": 1024 if family is not ArtifactFamily.MANIFEST else 256,
                "schema_id": f"federal-register-{family.value}-v2",
                "family": family.value,
                "row_count": 0 if family is ArtifactFamily.MANIFEST else 10,
                "year_month": "2026-03" if "year_month=" in path else None,
                "document_type": "rule" if "document_type=" in path else None,
            }
        )
    return artifacts


def example_corpus_payload(
    *,
    entry_cid: Optional[str] = None,
    document_number: str = "2026-04567",
    publication_date: str = "2026-03-15",
    document_type: str = "rule",
) -> dict[str, Any]:
    """Return a minimal valid admitted corpus row for tests and docs."""

    digest = entry_cid or content_sha256(
        f"example-entry:fr:{document_number}:{publication_date}"
    )
    source = content_sha256(f"example-source:fr:{document_number}:{publication_date}")
    content_hash = content_sha256(f"official-body:fr:{document_number}")
    return {
        "entry_cid": digest,
        "legal_id": f"fr:{document_number}:{publication_date}",
        "source_cid": source,
        "document_number": document_number,
        "publication_date": publication_date,
        "document_type": document_type,
        "admission_status": AdmissionStatus.ADMITTED.value,
        "admission_reason": "canonical official-source Federal Register row",
        "release_point": f"fr/cutoff/{DEFAULT_OBSERVATION_CUTOFF[:10]}",
        "source_checksum": source,
        "verification_result": VerificationResult.VERIFIED.value,
        "acquisition_time": "2026-08-10T12:05:00Z",
        "official_source_url": (
            f"https://www.federalregister.gov/documents/{publication_date[:4]}/"
            f"{publication_date[5:7]}/{publication_date[8:10]}/{document_number}"
        ),
        "official_html_url": (
            f"https://www.federalregister.gov/documents/{publication_date[:4]}/"
            f"{publication_date[5:7]}/{publication_date[8:10]}/{document_number}"
        ),
        "official_pdf_url": (
            f"https://www.govinfo.gov/content/pkg/FR-{publication_date}/pdf/"
            f"FR-{publication_date}.pdf"
        ),
        "official_content_hash": content_hash,
        "acquisition_receipt_id": f"fr-acquire-{publication_date[:7]}",
        "parser_version": "federal-register-parser/v2",
        "source_authority_class": SourceAuthorityClass.OFFICIAL.value,
        "text_availability": TextAvailability.FULL_TEXT.value,
        "text": (
            "Example Federal Register rule text for document "
            f"{document_number} published {publication_date}."
        ),
        "title": "Example Environmental Reporting Rule",
        "abstract": "Establishes reporting requirements for covered facilities.",
        "agencies": ["Environmental Protection Agency"],
        "correction_relation": CorrectionRelation.NONE.value,
        "document_index": 0,
        "year_month": publication_date[:7],
        "schema_version": SCHEMA_VERSION,
    }


def example_correction_corpus_payload() -> dict[str, Any]:
    """Return a minimal valid correction document corpus row."""

    payload = example_corpus_payload(
        document_number="2026-05001",
        publication_date="2026-04-01",
        document_type="correction",
    )
    payload["correction_relation"] = CorrectionRelation.CORRECTS.value
    payload["related_document_number"] = "2026-04567"
    payload["legal_id"] = "fr:2026-05001:2026-04-01:corrects:2026-04567"
    payload["title"] = "Correction to Example Environmental Reporting Rule"
    payload["text"] = (
        "This document corrects FR Doc. 2026-04567 published on March 15, 2026."
    )
    return payload


def example_source_receipt_payload(
    *,
    year_month: str = "2026-03",
) -> dict[str, Any]:
    """Return a minimal valid per-date-partition acquisition receipt."""

    checksum = content_sha256(f"source-receipt:fr:{year_month}")
    return {
        "receipt_id": f"fr-partition-{year_month}",
        "year_month": year_month,
        "partition_start": f"{year_month}-01",
        "partition_end": f"{year_month}-31" if year_month.endswith("-03") else f"{year_month}-28",
        "official_source_url": "https://www.federalregister.gov/api/v1/documents.json",
        "release_point": f"fr/cutoff/{DEFAULT_OBSERVATION_CUTOFF[:10]}",
        "observation_time": "2026-08-10T12:00:00Z",
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "source_authority_class": SourceAuthorityClass.OFFICIAL.value,
        "source_checksum": checksum,
        "verification_result": VerificationResult.VERIFIED.value,
        "enumerated": 100,
        "fetched": 94,
        "duplicate": 2,
        "excluded": 3,
        "quarantined": 1,
        "failed_final": 0,
        "frontier_closed": True,
        "relative_path": f"receipts/acquire/year_month-{year_month}.json",
        "api_total": 100,
        "page_cursors": ["page-1", "page-2"],
        "response_hashes": [checksum],
        "document_numbers": ["2026-04567", "2026-04568"],
        "body_text_dispositions": {
            TextAvailability.FULL_TEXT.value: 90,
            TextAvailability.METADATA_ONLY.value: 4,
            TextAvailability.ABSTRACT_ONLY.value: 0,
        },
        "schema_version": SCHEMA_VERSION,
    }


def example_manifest_payload(
    *,
    enforce_semantic_family_closure: bool = True,
) -> dict[str, Any]:
    """Return a minimal valid release manifest payload for tests and docs."""

    config_digest = content_sha256("federal-register-build-config-v2")
    model_rev = DEFAULT_EMBEDDING_MODEL_REVISION
    source_rev = PREVIOUS_PUBLIC_PIN
    return {
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "release_profile": RELEASE_PROFILE,
        "source_revision": source_rev,
        "build_config_cid": config_digest,
        "vector_space_id": f"gte-small@{model_rev}",
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": model_rev,
        "tokenizer_id": "federal-register-bm25-tokenizer/v1",
        "graph_ontology_version": "federal-register-graph-ontology/v1",
        "artifacts": _closed_family_artifacts(),
        "schema_version": SCHEMA_VERSION,
        "release_point": f"federal-register/v2/{DEFAULT_OBSERVATION_CUTOFF[:10]}",
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "determinism_seeds": {"kmeans": 42, "sample": 7},
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_posting_pointers_per_row": MAX_POSTING_POINTERS_PER_ROW,
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "enforce_semantic_family_closure": enforce_semantic_family_closure,
    }


def example_publication_payload() -> dict[str, Any]:
    """Return a minimal valid publication receipt payload."""

    return {
        "publication_id": "pub-federal-register-v2-001",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "public_revision": "a" * 40,
        "previous_revision": PREVIOUS_PUBLIC_PIN,
        "manifest_digest": content_sha256("manifest-fr-v2"),
        "staging_revision": "b" * 40,
        "published_at": "2026-08-10T18:00:00Z",
        "authorization_receipt_id": "auth-federal-register-v2-001",
        "additive_only": True,
        "schema_version": SCHEMA_VERSION,
    }


def example_rollback_payload() -> dict[str, Any]:
    """Return a minimal valid rollback receipt payload."""

    return {
        "rollback_id": "rollback-federal-register-001",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "from_revision": "a" * 40,
        "to_revision": PREVIOUS_PUBLIC_PIN,
        "reason": "canary failure; restore previous public pin",
        "rolled_back_at": "2026-08-10T19:00:00Z",
        "manifest_digest": content_sha256("manifest-fr-v2"),
        "schema_version": SCHEMA_VERSION,
    }


__all__ = [
    "ADR_PATH",
    "AMBIGUOUS_4096_FIELD_NAMES",
    "AdmissionStatus",
    "AdjacencyRecord",
    "AmbiguousBoundError",
    "ArtifactDescriptor",
    "ArtifactFamily",
    "ArtifactPathError",
    "BODY_TEXT_AVAILABILITIES",
    "BoundKind",
    "CentroidRecord",
    "CorpusRecord",
    "CorrectionRelation",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL_ID",
    "DEFAULT_EMBEDDING_MODEL_REVISION",
    "DEFAULT_OBSERVATION_CUTOFF",
    "DocumentIdentityError",
    "DocumentType",
    "FederalRegisterReleaseSchemaError",
    "GraphEdgeRecord",
    "GraphNodeRecord",
    "InvalidDigestError",
    "LocatorRecord",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_POSTING_POINTERS_PER_ROW",
    "MAX_ROUTING_ROWS_PER_INDEX",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_TERM_ROWS_PER_SHARD",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "MissingAdmissionProvenanceError",
    "MutableReferenceError",
    "OfficialProvenanceError",
    "PHYSICAL_BOUND_FIELD_NAMES",
    "PREVIOUS_PUBLIC_PIN",
    "PhysicalBoundError",
    "PositionalIdentityError",
    "PostingRecord",
    "PublicationRecord",
    "RELEASE_PROFILE",
    "REQUIRED_ADMISSION_FIELDS",
    "REQUIRED_IDENTITY_FIELDS",
    "REQUIRED_PROVENANCE_FIELDS",
    "REQUIRED_SEMANTIC_FAMILIES",
    "ReceiptRecord",
    "RecoveryRecord",
    "ReleaseManifest",
    "RollbackRecord",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "SemanticFamilyClosureError",
    "SourceAuthorityClass",
    "SourceReceiptRecord",
    "TASK_ID",
    "TextAvailability",
    "TextAvailabilityError",
    "VectorRecord",
    "VerificationResult",
    "canonical_json_dumps",
    "coerce_family_set",
    "content_sha256",
    "digest_mapping",
    "example_correction_corpus_payload",
    "example_corpus_payload",
    "example_manifest_payload",
    "example_publication_payload",
    "example_rollback_payload",
    "example_source_receipt_payload",
    "is_immutable_revision",
    "normalize_relative_artifact_path",
    "normalize_sha256",
    "physical_bounds_policy",
    "reject_positional_durable_identity",
    "require_immutable_model_ref",
    "require_immutable_revision",
    "required_semantic_families",
    "validate_admission_provenance_fields",
    "validate_bound_declaration",
    "validate_centroid_capacity",
    "validate_correction_identity",
    "validate_digest",
    "validate_document_index",
    "validate_document_number",
    "validate_durable_identity_fields",
    "validate_entry_cid",
    "validate_legal_id",
    "validate_official_url",
    "validate_physical_pointer_count",
    "validate_physical_row_count",
    "validate_publication_date",
    "validate_release_record",
    "validate_semantic_family_closure",
    "validate_text_availability_fields",
    "validate_year_month",
]
