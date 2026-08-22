"""State-law Sparse GraphRAG v2 release schema and identity contract (LCR-004).

This module owns the versioned release-level dataclasses and fail-closed
validators for the ``state-laws-ir-graphrag/v2`` state-law release. It defines
corpus, source-receipt, admission, posting, vector, centroid, graph,
adjacency, locator, descriptor, manifest, publication, and rollback records.

It deliberately does **not** reimplement scraper acquisition, official-source
catalog resolution, or Parquet/Hub I/O. Downstream writers and builders
consume these contracts; this module performs no network I/O.

Design invariants
-----------------
* Durable identity is ``entry_cid`` (primary key) plus ``legal_id``
  (jurisdiction/code/title/chapter/section/subsection) plus ``source_cid``
  (normalized official-source evidence). Positional labels such as
  ``row-N`` or release-local ``document_index`` are **not** durable identity.
* Official provenance is mandatory on admitted rows: release/as-of pin,
  source checksum, verification result, acquisition time, official URL,
  acquisition receipt id, and parser version.
* Model and release references must be immutable (Hub commit SHA, SHA-256,
  or CID). Tokens such as ``latest``, ``main``, or ``HEAD`` are rejected.
* The integer ``4,096`` means physical rows/pointers per retrieval unit.
  Model-token ceilings use separate, explicitly named fields.
* Artifact paths are relative, POSIX, and confined to the release root.
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
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-sparse-graphrag-release-schema-v2"
RELEASE_PROFILE: Final = "state-laws-ir-graphrag/v2"
ADR_PATH: Final = "docs/architecture/legal_corpora_reindex_schema.md"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
PREVIOUS_PUBLIC_PIN: Final = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
DEFAULT_EMBEDDING_MODEL_ID: Final = "thenlper/gte-small"
DEFAULT_EMBEDDING_MODEL_REVISION: Final = (
    "17e1f347d17fe144873b1201da91788898c639cd"
)
DEFAULT_EMBEDDING_DIMENSION: Final = 384
TASK_ID: Final = "LCR-004"
SOURCE_RIGHTS_RECEIPT_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)

# Exact jurisdiction set: 50 postal state codes + DC (no extras, no omissions).
CANONICAL_JURISDICTIONS: Final = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)
EXPECTED_JURISDICTION_COUNT: Final = 51

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
_SHA256_PREFIXED_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CID_V1_RE = re.compile(r"^b[a-z2-7]{20,}$")
_ENTRY_CID_RE = re.compile(
    r"^(?:b[a-z2-7]{20,}|sha256:[0-9a-f]{64}|[0-9a-f]{64})$"
)
# state:<jurisdiction>:<code_family>:<path...>
_LEGAL_ID_RE = re.compile(
    r"^state:([a-z]{2}):([a-z0-9][a-z0-9._-]{0,63}):.+$",
    re.IGNORECASE,
)
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

JsonMapping = Mapping[str, Any]
PathLike = Union[str, PurePosixPath]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsReleaseSchemaError(ValueError):
    """Base error for state-law release schema contract failures."""


class SourceRightsBindingError(StateLawsReleaseSchemaError):
    """Raised when a candidate manifest omits or mismatches source-rights evidence."""


class PositionalIdentityError(StateLawsReleaseSchemaError):
    """Raised when durable identity is positional (``row-N``, index, etc.)."""


class MutableReferenceError(StateLawsReleaseSchemaError):
    """Raised when a model or release reference is mutable (``latest``, branch)."""


class AmbiguousBoundError(StateLawsReleaseSchemaError):
    """Raised when a 4,096 value is attached to an ambiguous/token field."""


class ArtifactPathError(StateLawsReleaseSchemaError):
    """Raised when an artifact path is absolute, traverses, or is unsafe."""


class InvalidDigestError(StateLawsReleaseSchemaError):
    """Raised when a digest/CID field is malformed."""


class MissingAdmissionProvenanceError(StateLawsReleaseSchemaError):
    """Raised when admission status or required provenance fields are absent."""


class PhysicalBoundError(StateLawsReleaseSchemaError):
    """Raised when a physical row/pointer bound is violated."""


class SchemaVersionError(StateLawsReleaseSchemaError):
    """Raised when schema_version / release profile is wrong."""


class SemanticFamilyClosureError(StateLawsReleaseSchemaError):
    """Raised when a release omits a required semantic family."""


class JurisdictionSetError(StateLawsReleaseSchemaError):
    """Raised when the jurisdiction set is not exactly the 51-code constant."""


class OfficialProvenanceError(StateLawsReleaseSchemaError):
    """Raised when official-source provenance is incomplete or non-official."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ArtifactFamily(str, Enum):
    """Top-level artifact families in the v2 state-law release layout."""

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
            "pub": cls.PUBLICATION,
            "rollback_receipt": cls.ROLLBACK,
        }
        if text in aliases:
            return aliases[text]
        for family in cls:
            if family.value == text or family.name.lower() == text:
                return family
        raise StateLawsReleaseSchemaError(f"unknown artifact family: {value!r}")


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
        raise StateLawsReleaseSchemaError(f"unknown admission status: {value!r}")


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
        raise StateLawsReleaseSchemaError(f"unknown verification result: {value!r}")


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
            "legislature": cls.OFFICIAL,
            "code_publisher": cls.OFFICIAL,
            "reviser": cls.OFFICIAL,
            "dc_council": cls.OFFICIAL,
            "approved_exception": cls.EXCEPTION,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise StateLawsReleaseSchemaError(f"unknown source authority class: {value!r}")


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
        "jurisdiction",
        "code_family",
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

# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsReleaseSchemaError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise StateLawsReleaseSchemaError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise StateLawsReleaseSchemaError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsReleaseSchemaError(f"{name} must be an integer")
    if value < 0:
        raise StateLawsReleaseSchemaError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number <= 0:
        raise StateLawsReleaseSchemaError(f"{name} must be a positive integer")
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


def validate_jurisdiction(value: Any, *, name: str = "jurisdiction") -> str:
    """Validate a postal jurisdiction code against the exact 51-set."""

    text = _require_non_empty_str(value, name, maximum=8).upper()
    if text not in CANONICAL_JURISDICTIONS:
        raise JurisdictionSetError(
            f"{name}={text!r} is not in the exact 51-jurisdiction set "
            f"(50 states + DC)"
        )
    return text


def validate_jurisdiction_set(values: Any, *, name: str = "jurisdictions") -> tuple[str, ...]:
    """Require the exact 51-jurisdiction set (no missing, no extra)."""

    if not isinstance(values, (list, tuple, set, frozenset)):
        raise JurisdictionSetError(f"{name} must be a sequence of jurisdiction codes")
    codes = sorted({validate_jurisdiction(item, name=f"{name}[]") for item in values})
    present = frozenset(codes)
    if present != CANONICAL_JURISDICTIONS:
        missing = sorted(CANONICAL_JURISDICTIONS - present)
        extra = sorted(present - CANONICAL_JURISDICTIONS)
        raise JurisdictionSetError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    return tuple(codes)


def validate_legal_id(value: Any, *, name: str = "legal_id") -> str:
    """Validate stable state-law citation identity shape.

    Shape: ``state:<jurisdiction>:<code_family>:<path...>`` where jurisdiction
    is a postal code from the exact 51-set. Positional labels are rejected.
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
        raise StateLawsReleaseSchemaError(
            f"{name} must match state:<jurisdiction>:<code_family>:<path>; "
            f"got {value!r}"
        )
    jurisdiction = match.group(1).upper()
    if jurisdiction not in CANONICAL_JURISDICTIONS:
        raise JurisdictionSetError(
            f"{name} jurisdiction {jurisdiction!r} is not in the exact 51-set"
        )
    # Normalize jurisdiction segment to uppercase.
    parts = text.split(":", 3)
    return f"state:{jurisdiction}:{parts[2].lower()}:{parts[3]}"


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
        raise StateLawsReleaseSchemaError(f"{name} is required")
    if isinstance(value, str) and _POSITIONAL_ID_RE.fullmatch(value.strip()):
        raise PositionalIdentityError(
            f"{name} string form is not a valid release-local index: {value!r}"
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateLawsReleaseSchemaError(f"{name} must be an integer")
    if value < 0:
        raise StateLawsReleaseSchemaError(f"{name} must be >= 0")
    return value


def validate_durable_identity_fields(payload: Mapping[str, Any]) -> dict[str, str]:
    """Require ``entry_cid`` + ``legal_id`` + ``source_cid``; reject positional IDs."""

    if not isinstance(payload, Mapping):
        raise StateLawsReleaseSchemaError("identity payload must be a mapping")

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
        raise StateLawsReleaseSchemaError("admission payload must be a mapping")

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
        result["official_source_url"] = _require_non_empty_str(
            payload["official_source_url"], "official_source_url", maximum=2048
        )
        if not result["official_source_url"].lower().startswith(
            ("http://", "https://")
        ):
            raise OfficialProvenanceError(
                "official_source_url must be an absolute http(s) URL"
            )
        result["acquisition_receipt_id"] = _require_non_empty_str(
            payload["acquisition_receipt_id"],
            "acquisition_receipt_id",
            maximum=256,
        )
        result["parser_version"] = _require_non_empty_str(
            payload["parser_version"], "parser_version", maximum=128
        )
        result["jurisdiction"] = validate_jurisdiction(payload["jurisdiction"])
        result["code_family"] = _require_non_empty_str(
            payload["code_family"], "code_family", maximum=128
        ).lower()

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
    jurisdiction: Optional[str] = None
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
        if self.jurisdiction is not None:
            object.__setattr__(
                self,
                "jurisdiction",
                validate_jurisdiction(self.jurisdiction),
            )
        if self.key_range is not None:
            if (
                not isinstance(self.key_range, (tuple, list))
                or len(self.key_range) != 2
            ):
                raise StateLawsReleaseSchemaError(
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
            "family": self.family.value,
            "first_key": self.first_key,
            "jurisdiction": self.jurisdiction,
            "last_key": self.last_key,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_id": self.schema_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.centroid_id is not None:
            payload["centroid_id"] = self.centroid_id
        if self.key_range is not None:
            payload["key_range"] = list(self.key_range)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactDescriptor":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("artifact descriptor must be a mapping")
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
            jurisdiction=value.get("jurisdiction"),
            key_range=key_range,
        )


@dataclass(frozen=True, slots=True)
class CorpusRecord:
    """Canonical retrieval row for the v2 state-law corpus."""

    entry_cid: str
    legal_id: str
    source_cid: str
    jurisdiction: str
    code_family: str
    section: str
    admission_status: AdmissionStatus
    admission_reason: str
    release_point: str
    source_checksum: str
    verification_result: VerificationResult
    acquisition_time: str
    official_source_url: str
    acquisition_receipt_id: str
    parser_version: str
    text: str = ""
    title: Optional[str] = None
    chapter: Optional[str] = None
    subsection: Optional[str] = None
    document_index: Optional[int] = None
    source_authority_class: SourceAuthorityClass = SourceAuthorityClass.OFFICIAL
    edition_as_of: Optional[str] = None
    effective_date: Optional[str] = None
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
                "acquisition_receipt_id": self.acquisition_receipt_id,
                "parser_version": self.parser_version,
                "jurisdiction": self.jurisdiction,
                "code_family": self.code_family,
                "source_authority_class": self.source_authority_class,
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
            object.__setattr__(
                self,
                "acquisition_receipt_id",
                admission["acquisition_receipt_id"],
            )
            object.__setattr__(self, "parser_version", admission["parser_version"])
            object.__setattr__(self, "jurisdiction", admission["jurisdiction"])
            object.__setattr__(self, "code_family", admission["code_family"])
            object.__setattr__(
                self,
                "source_authority_class",
                SourceAuthorityClass.coerce(admission["source_authority_class"]),
            )
        else:
            object.__setattr__(
                self,
                "source_cid",
                validate_digest(self.source_cid, name="source_cid"),
            )
            object.__setattr__(
                self,
                "jurisdiction",
                validate_jurisdiction(self.jurisdiction),
            )
            object.__setattr__(
                self,
                "code_family",
                _require_non_empty_str(self.code_family, "code_family").lower(),
            )
        object.__setattr__(
            self,
            "section",
            _require_non_empty_str(self.section, "section", maximum=256),
        )
        if not isinstance(self.text, str):
            raise StateLawsReleaseSchemaError("text must be a string")
        # Legal_id jurisdiction must match the jurisdiction field.
        legal_jurisdiction = self.legal_id.split(":", 2)[1]
        if legal_jurisdiction != self.jurisdiction:
            raise StateLawsReleaseSchemaError(
                f"legal_id jurisdiction {legal_jurisdiction!r} does not match "
                f"jurisdiction field {self.jurisdiction!r}"
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
            "acquisition_receipt_id": self.acquisition_receipt_id,
            "acquisition_time": self.acquisition_time,
            "admission_reason": self.admission_reason,
            "admission_status": self.admission_status.value,
            "chapter": self.chapter,
            "code_family": self.code_family,
            "document_index": self.document_index,
            "edition_as_of": self.edition_as_of,
            "effective_date": self.effective_date,
            "entry_cid": self.entry_cid,
            "jurisdiction": self.jurisdiction,
            "legal_id": self.legal_id,
            "observed_at": self.observed_at,
            "official_source_url": self.official_source_url,
            "parent_path": self.parent_path,
            "parser_version": self.parser_version,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "section": self.section,
            "source_authority_class": self.source_authority_class.value,
            "source_checksum": self.source_checksum,
            "source_cid": self.source_cid,
            "subsection": self.subsection,
            "text": self.text,
            "title": self.title,
            "verification_result": self.verification_result.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CorpusRecord":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("corpus record must be a mapping")
        return cls(
            entry_cid=value.get("entry_cid", ""),
            legal_id=value.get("legal_id", ""),
            source_cid=value.get("source_cid", ""),
            jurisdiction=value.get("jurisdiction", ""),
            code_family=value.get("code_family", ""),
            section=value.get("section", ""),
            admission_status=value.get("admission_status", ""),
            admission_reason=value.get("admission_reason", ""),
            release_point=value.get("release_point", ""),
            source_checksum=value.get("source_checksum", ""),
            verification_result=value.get("verification_result", ""),
            acquisition_time=value.get("acquisition_time", ""),
            official_source_url=value.get("official_source_url", ""),
            acquisition_receipt_id=value.get("acquisition_receipt_id", ""),
            parser_version=value.get("parser_version", ""),
            text=value.get("text", "") or "",
            title=value.get("title"),
            chapter=value.get("chapter"),
            subsection=value.get("subsection"),
            document_index=value.get("document_index"),
            source_authority_class=value.get(
                "source_authority_class", SourceAuthorityClass.OFFICIAL
            ),
            edition_as_of=value.get("edition_as_of"),
            effective_date=value.get("effective_date"),
            observed_at=value.get("observed_at"),
            parent_path=value.get("parent_path"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SourceReceiptRecord:
    """Per-jurisdiction official-source scrape / acquisition receipt."""

    receipt_id: str
    jurisdiction: str
    official_source_url: str
    release_point: str
    observation_time: str
    source_authority_class: SourceAuthorityClass
    source_checksum: str
    verification_result: VerificationResult
    discovered: int
    fetched: int
    excluded: int
    quarantined: int
    failed_final: int
    frontier_closed: bool
    relative_path: str
    schema_version: str = SCHEMA_VERSION
    duplicates: int = 0
    source_software_version: Optional[str] = None
    start_urls: tuple[str, ...] = ()
    content_hashes: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_non_empty_str(self.receipt_id, "receipt_id"),
        )
        object.__setattr__(
            self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
        )
        url = _require_non_empty_str(
            self.official_source_url, "official_source_url", maximum=2048
        )
        if not url.lower().startswith(("http://", "https://")):
            raise OfficialProvenanceError(
                "official_source_url must be an absolute http(s) URL"
            )
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
        discovered = _require_non_negative_int(self.discovered, "discovered")
        fetched = _require_non_negative_int(self.fetched, "fetched")
        excluded = _require_non_negative_int(self.excluded, "excluded")
        quarantined = _require_non_negative_int(self.quarantined, "quarantined")
        failed_final = _require_non_negative_int(self.failed_final, "failed_final")
        duplicates = _require_non_negative_int(self.duplicates, "duplicates")
        object.__setattr__(self, "discovered", discovered)
        object.__setattr__(self, "fetched", fetched)
        object.__setattr__(self, "excluded", excluded)
        object.__setattr__(self, "quarantined", quarantined)
        object.__setattr__(self, "failed_final", failed_final)
        object.__setattr__(self, "duplicates", duplicates)
        # discovered = fetched + excluded + quarantined + failed_final
        # (duplicates tracked separately)
        accounted = fetched + excluded + quarantined + failed_final
        if discovered != accounted:
            raise StateLawsReleaseSchemaError(
                f"source receipt reconciliation failed: discovered={discovered} "
                f"!= fetched+excluded+quarantined+failed_final={accounted}"
            )
        if not isinstance(self.frontier_closed, bool):
            raise StateLawsReleaseSchemaError("frontier_closed must be a boolean")
        if self.frontier_closed and failed_final != 0:
            raise StateLawsReleaseSchemaError(
                "frontier_closed=true requires failed_final=0"
            )
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(
                self.relative_path, name="relative_path"
            ),
        )
        if not isinstance(self.start_urls, (list, tuple)):
            raise StateLawsReleaseSchemaError("start_urls must be a sequence")
        object.__setattr__(
            self,
            "start_urls",
            tuple(
                _require_non_empty_str(item, f"start_urls[{i}]", maximum=2048)
                for i, item in enumerate(self.start_urls)
            ),
        )
        if not isinstance(self.content_hashes, (list, tuple)):
            raise StateLawsReleaseSchemaError("content_hashes must be a sequence")
        object.__setattr__(
            self,
            "content_hashes",
            tuple(
                normalize_sha256(item, name=f"content_hashes[{i}]")
                for i, item in enumerate(self.content_hashes)
            ),
        )
        if not isinstance(self.payload, Mapping):
            raise StateLawsReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_hashes": list(self.content_hashes),
            "discovered": self.discovered,
            "duplicates": self.duplicates,
            "excluded": self.excluded,
            "failed_final": self.failed_final,
            "fetched": self.fetched,
            "frontier_closed": self.frontier_closed,
            "jurisdiction": self.jurisdiction,
            "observation_time": self.observation_time,
            "official_source_url": self.official_source_url,
            "payload": dict(self.payload),
            "quarantined": self.quarantined,
            "receipt_id": self.receipt_id,
            "relative_path": self.relative_path,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "source_authority_class": self.source_authority_class.value,
            "source_checksum": self.source_checksum,
            "source_software_version": self.source_software_version,
            "start_urls": list(self.start_urls),
            "verification_result": self.verification_result.value,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceReceiptRecord":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("source receipt must be a mapping")
        start_urls = value.get("start_urls") or ()
        content_hashes = value.get("content_hashes") or ()
        if isinstance(start_urls, list):
            start_urls = tuple(start_urls)
        if isinstance(content_hashes, list):
            content_hashes = tuple(content_hashes)
        return cls(
            receipt_id=value.get("receipt_id", ""),
            jurisdiction=value.get("jurisdiction", ""),
            official_source_url=value.get("official_source_url", ""),
            release_point=value.get("release_point", ""),
            observation_time=value.get("observation_time", ""),
            source_authority_class=value.get(
                "source_authority_class", SourceAuthorityClass.OFFICIAL
            ),
            source_checksum=value.get("source_checksum", ""),
            verification_result=value.get(
                "verification_result", VerificationResult.VERIFIED
            ),
            discovered=value.get("discovered", 0),
            fetched=value.get("fetched", 0),
            excluded=value.get("excluded", 0),
            quarantined=value.get("quarantined", 0),
            failed_final=value.get("failed_final", 0),
            frontier_closed=value.get("frontier_closed", False),
            relative_path=value.get("relative_path", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            duplicates=value.get("duplicates", 0),
            source_software_version=value.get("source_software_version"),
            start_urls=start_urls,
            content_hashes=content_hashes,
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
            raise StateLawsReleaseSchemaError("entry_cids must be a sequence")
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
                raise StateLawsReleaseSchemaError(
                    "document_frequencies must be a sequence"
                )
            if len(self.document_frequencies) != len(cids):
                raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("posting record must be a mapping")
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
    jurisdiction: Optional[str] = None

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
            raise StateLawsReleaseSchemaError(
                "embedding must be a sequence of floats"
            )
        if len(self.embedding) != dim:
            raise StateLawsReleaseSchemaError(
                f"embedding length {len(self.embedding)} != dimension {dim}"
            )
        values = []
        for index, item in enumerate(self.embedding):
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise StateLawsReleaseSchemaError(
                    f"embedding[{index}] must be a finite number"
                )
            number = float(item)
            if number != number or number in (float("inf"), float("-inf")):
                raise StateLawsReleaseSchemaError(
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
        if self.jurisdiction is not None:
            object.__setattr__(
                self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
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
            "embedding": list(self.embedding),
            "entry_cid": self.entry_cid,
            "jurisdiction": self.jurisdiction,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "schema_version": self.schema_version,
            "vector_space_id": self.vector_space_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VectorRecord":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("vector record must be a mapping")
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
            jurisdiction=value.get("jurisdiction"),
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
            raise StateLawsReleaseSchemaError(
                "centroid must be a sequence of floats"
            )
        if len(self.centroid) != dim:
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("shard_descriptors must be a sequence")
        descriptors = tuple(
            normalize_relative_artifact_path(
                item, name=f"shard_descriptors[{index}]"
            )
            for index, item in enumerate(self.shard_descriptors)
        )
        if descriptors and len(descriptors) != shards:
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("centroid record must be a mapping")
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
    jurisdiction: Optional[str] = None
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
        if self.jurisdiction is not None:
            object.__setattr__(
                self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
            )
        if self.label is not None:
            object.__setattr__(self, "label", _optional_str(self.label, "label"))
        if not isinstance(self.payload, Mapping):
            raise StateLawsReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_cid": self.entry_cid,
            "jurisdiction": self.jurisdiction,
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
            raise StateLawsReleaseSchemaError("graph node must be a mapping")
        return cls(
            node_cid=value.get("node_cid", ""),
            node_type=value.get("node_type", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            legal_id=value.get("legal_id"),
            entry_cid=value.get("entry_cid"),
            jurisdiction=value.get("jurisdiction"),
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
            raise StateLawsReleaseSchemaError("payload must be a mapping")
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
            raise StateLawsReleaseSchemaError("graph edge must be a mapping")
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
            raise StateLawsReleaseSchemaError(
                f"direction must be in/out/incoming/outgoing, got {self.direction!r}"
            )
        if direction in {"incoming", "in"}:
            direction = "in"
        else:
            direction = "out"
        object.__setattr__(self, "direction", direction)
        if not isinstance(self.edge_cids, (list, tuple)):
            raise StateLawsReleaseSchemaError("edge_cids must be a sequence")
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
            raise StateLawsReleaseSchemaError("adjacency record must be a mapping")
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
    jurisdiction: Optional[str] = None

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
        if self.jurisdiction is not None:
            object.__setattr__(
                self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "first_key": self.first_key,
            "jurisdiction": self.jurisdiction,
            "last_key": self.last_key,
            "locator_id": self.locator_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LocatorRecord":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("locator record must be a mapping")
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
            jurisdiction=value.get("jurisdiction"),
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
            raise StateLawsReleaseSchemaError("payload must be a mapping")
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
            raise StateLawsReleaseSchemaError("receipt record must be a mapping")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            release_point=value.get("release_point", ""),
            manifest_digest=value.get("manifest_digest", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            source_revision=value.get("source_revision"),
            package_version=value.get("package_version"),
            build_config_cid=value.get("build_config_cid"),
            acquired_at=value.get("acquired_at"),
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
    jurisdiction: Optional[str] = None
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
            raise StateLawsReleaseSchemaError(
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
        if self.jurisdiction is not None:
            object.__setattr__(
                self, "jurisdiction", validate_jurisdiction(self.jurisdiction)
            )
        if not isinstance(self.payload, Mapping):
            raise StateLawsReleaseSchemaError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission_status": self.admission_status.value,
            "jurisdiction": self.jurisdiction,
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
            raise StateLawsReleaseSchemaError("recovery record must be a mapping")
        return cls(
            recovery_id=value.get("recovery_id", ""),
            reason=value.get("reason", ""),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            source_path=value.get("source_path"),
            raw_digest=value.get("raw_digest"),
            admission_status=value.get(
                "admission_status", AdmissionStatus.RECOVERY
            ),
            jurisdiction=value.get("jurisdiction"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    """Immutable-Hub publication receipt for a verified state-law release."""

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
            raise StateLawsReleaseSchemaError(
                f"dataset_repo_id must look like org/name, got {repo!r}"
            )
        if repo != DEFAULT_DATASET_REPO_ID:
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("additive_only must be a boolean")
        if not self.additive_only:
            raise StateLawsReleaseSchemaError(
                "state-law publication must be additive_only=true"
            )
        if not isinstance(self.payload, Mapping):
            raise StateLawsReleaseSchemaError("payload must be a mapping")
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
            raise StateLawsReleaseSchemaError("publication record must be a mapping")
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
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("payload must be a mapping")
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
            raise StateLawsReleaseSchemaError("rollback record must be a mapping")
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
    jurisdictions: tuple[str, ...] = ()
    enforce_semantic_family_closure: bool = True
    source_rights_receipt_path: str = SOURCE_RIGHTS_RECEIPT_RELPATH
    source_rights_receipt_digest: str = ""
    source_rights_catalog_digest: str = ""
    admitted_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        repo = _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id")
        if not _DATASET_ID_RE.fullmatch(repo):
            raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("artifacts must be a sequence")
        descriptors: list[ArtifactDescriptor] = []
        seen_paths: set[str] = set()
        for item in self.artifacts:
            if isinstance(item, ArtifactDescriptor):
                descriptor = item
            elif isinstance(item, Mapping):
                descriptor = ArtifactDescriptor.from_mapping(item)
            else:
                raise StateLawsReleaseSchemaError(
                    "artifacts entries must be ArtifactDescriptor or mapping"
                )
            if descriptor.relative_path in seen_paths:
                raise StateLawsReleaseSchemaError(
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
            raise StateLawsReleaseSchemaError("determinism_seeds must be a mapping")
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

        if self.jurisdictions:
            object.__setattr__(
                self,
                "jurisdictions",
                validate_jurisdiction_set(
                    self.jurisdictions, name="jurisdictions"
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
            "jurisdictions": list(self.jurisdictions),
            "max_adjacency_pointers_per_row": self.max_adjacency_pointers_per_row,
            "max_posting_pointers_per_row": self.max_posting_pointers_per_row,
            "max_rows_per_physical_shard": self.max_rows_per_physical_shard,
            "max_rows_per_vector_centroid": self.max_rows_per_vector_centroid,
            "max_vector_shards_per_centroid": self.max_vector_shards_per_centroid,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "package_version": self.package_version,
            "release_point": self.release_point,
            "release_profile": self.release_profile,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "source_rights_catalog_digest": self.source_rights_catalog_digest,
            "source_rights_receipt_digest": self.source_rights_receipt_digest,
            "source_rights_receipt_path": self.source_rights_receipt_path,
            "admitted_source_ids": list(self.admitted_source_ids),
            "tokenizer_id": self.tokenizer_id,
            "vector_space_id": self.vector_space_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReleaseManifest":
        if not isinstance(value, Mapping):
            raise StateLawsReleaseSchemaError("manifest must be a mapping")
        artifacts = value.get("artifacts") or ()
        jurisdictions = value.get("jurisdictions") or ()
        if isinstance(jurisdictions, list):
            jurisdictions = tuple(jurisdictions)
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
            jurisdictions=jurisdictions,
            enforce_semantic_family_closure=bool(
                value.get("enforce_semantic_family_closure", True)
            ),
            source_rights_receipt_path=str(
                value.get("source_rights_receipt_path")
                or SOURCE_RIGHTS_RECEIPT_RELPATH
            ),
            source_rights_receipt_digest=str(
                value.get("source_rights_receipt_digest") or ""
            ),
            source_rights_catalog_digest=str(
                value.get("source_rights_catalog_digest") or ""
            ),
            admitted_source_ids=tuple(
                str(item)
                for item in (value.get("admitted_source_ids") or ())
                if str(item).strip()
            ),
        )


# ---------------------------------------------------------------------------
# Composite validators / factory helpers
# ---------------------------------------------------------------------------


def require_source_rights_binding(
    manifest: Mapping[str, Any] | ReleaseManifest,
    *,
    receipt_digest: str,
    catalog_digest: str = "",
    dataset_card_text: str = "",
) -> None:
    """Fail closed when a candidate does not bind the current rights receipt."""

    payload = (
        manifest.to_dict()
        if isinstance(manifest, ReleaseManifest)
        else dict(manifest)
    )
    bound = str(payload.get("source_rights_receipt_digest") or "").strip()
    expected = validate_digest(receipt_digest, name="source_rights_receipt_digest")
    if not bound:
        raise SourceRightsBindingError(
            "candidate manifest does not bind source_rights_receipt_digest"
        )
    if validate_digest(bound, name="manifest.source_rights_receipt_digest") != expected:
        raise SourceRightsBindingError(
            "candidate manifest source-rights digest does not match the receipt"
        )
    path = str(payload.get("source_rights_receipt_path") or "").strip()
    if path and path != SOURCE_RIGHTS_RECEIPT_RELPATH:
        raise SourceRightsBindingError(
            f"source-rights receipt path must be {SOURCE_RIGHTS_RECEIPT_RELPATH}"
        )
    catalog_bound = str(payload.get("source_rights_catalog_digest") or "").strip()
    if catalog_digest and catalog_bound and catalog_bound != catalog_digest:
        raise SourceRightsBindingError(
            "candidate catalog digest does not match the source-rights receipt"
        )
    if dataset_card_text and expected not in dataset_card_text:
        raise SourceRightsBindingError(
            "dataset card does not bind the source-rights receipt digest"
        )


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
        raise StateLawsReleaseSchemaError(f"unknown record type: {record_type!r}")
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
        (ArtifactFamily.CORPUS, "data/corpus/jurisdiction=OR/part-000000.parquet"),
        (
            ArtifactFamily.BM25_DOCUMENTS,
            "data/bm25/documents/jurisdiction=OR/part-000000.parquet",
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
                "schema_id": f"state-laws-{family.value}-v2",
                "family": family.value,
                "row_count": 0 if family is ArtifactFamily.MANIFEST else 10,
                "jurisdiction": "OR" if "jurisdiction=" in path else None,
            }
        )
    return artifacts


def example_corpus_payload(
    *,
    entry_cid: Optional[str] = None,
    legal_id: str = "state:or:ors:123:456",
    jurisdiction: str = "OR",
) -> dict[str, Any]:
    """Return a minimal valid admitted corpus row for tests and docs."""

    digest = entry_cid or content_sha256("example-entry:or:ors:123:456")
    source = content_sha256("example-source:or:ors:123:456")
    return {
        "entry_cid": digest,
        "legal_id": legal_id,
        "source_cid": source,
        "jurisdiction": jurisdiction,
        "code_family": "ors",
        "section": "456",
        "title": "123",
        "admission_status": AdmissionStatus.ADMITTED.value,
        "admission_reason": "canonical official-source row",
        "release_point": "or/ors/2024-edition",
        "source_checksum": source,
        "verification_result": VerificationResult.VERIFIED.value,
        "acquisition_time": "2026-08-10T12:05:00Z",
        "official_source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors123.html",
        "acquisition_receipt_id": "scrape-or-2026-08-10",
        "parser_version": "state-laws-parser/v2",
        "source_authority_class": SourceAuthorityClass.OFFICIAL.value,
        "text": "Example statute text for ORS 123.456.",
        "document_index": 0,
        "schema_version": SCHEMA_VERSION,
    }


def example_source_receipt_payload(
    *,
    jurisdiction: str = "OR",
) -> dict[str, Any]:
    """Return a minimal valid official-source scrape receipt."""

    checksum = content_sha256(f"source-receipt:{jurisdiction}")
    return {
        "receipt_id": f"scrape-{jurisdiction.lower()}-2026-08-10",
        "jurisdiction": jurisdiction,
        "official_source_url": "https://www.oregonlegislature.gov/",
        "release_point": "or/ors/2024-edition",
        "observation_time": "2026-08-10T12:00:00Z",
        "source_authority_class": SourceAuthorityClass.OFFICIAL.value,
        "source_checksum": checksum,
        "verification_result": VerificationResult.VERIFIED.value,
        "discovered": 100,
        "fetched": 95,
        "excluded": 3,
        "quarantined": 2,
        "failed_final": 0,
        "duplicates": 1,
        "frontier_closed": True,
        "relative_path": f"receipts/scrape/jurisdiction-{jurisdiction}.json",
        "start_urls": ["https://www.oregonlegislature.gov/"],
        "content_hashes": [checksum],
        "schema_version": SCHEMA_VERSION,
    }


def example_manifest_payload(
    *,
    enforce_semantic_family_closure: bool = True,
    include_all_jurisdictions: bool = False,
) -> dict[str, Any]:
    """Return a minimal valid release manifest payload for tests and docs."""

    config_digest = content_sha256("state-laws-build-config-v2")
    model_rev = DEFAULT_EMBEDDING_MODEL_REVISION
    source_rev = PREVIOUS_PUBLIC_PIN
    payload: dict[str, Any] = {
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "release_profile": RELEASE_PROFILE,
        "source_revision": source_rev,
        "build_config_cid": config_digest,
        "vector_space_id": f"gte-small@{model_rev}",
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": model_rev,
        "tokenizer_id": "state-laws-bm25-tokenizer/v1",
        "graph_ontology_version": "state-laws-graph-ontology/v1",
        "artifacts": _closed_family_artifacts(),
        "schema_version": SCHEMA_VERSION,
        "release_point": "state-laws/v2/2026-08-10",
        "determinism_seeds": {"kmeans": 42, "sample": 7},
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_posting_pointers_per_row": MAX_POSTING_POINTERS_PER_ROW,
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "enforce_semantic_family_closure": enforce_semantic_family_closure,
    }
    if include_all_jurisdictions:
        payload["jurisdictions"] = sorted(CANONICAL_JURISDICTIONS)
    return payload


def example_publication_payload() -> dict[str, Any]:
    """Return a minimal valid publication receipt payload."""

    return {
        "publication_id": "pub-state-laws-v2-001",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "public_revision": "a" * 40,
        "previous_revision": PREVIOUS_PUBLIC_PIN,
        "manifest_digest": content_sha256("manifest-v2"),
        "staging_revision": "b" * 40,
        "published_at": "2026-08-10T18:00:00Z",
        "authorization_receipt_id": "auth-state-laws-v2-001",
        "additive_only": True,
        "schema_version": SCHEMA_VERSION,
    }


def example_rollback_payload() -> dict[str, Any]:
    """Return a minimal valid rollback receipt payload."""

    return {
        "rollback_id": "rollback-state-laws-001",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "from_revision": "a" * 40,
        "to_revision": PREVIOUS_PUBLIC_PIN,
        "reason": "canary failure; restore previous public pin",
        "rolled_back_at": "2026-08-10T19:00:00Z",
        "manifest_digest": content_sha256("manifest-v2"),
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
    "BoundKind",
    "CANONICAL_JURISDICTIONS",
    "CentroidRecord",
    "CorpusRecord",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL_ID",
    "DEFAULT_EMBEDDING_MODEL_REVISION",
    "EXPECTED_JURISDICTION_COUNT",
    "GraphEdgeRecord",
    "GraphNodeRecord",
    "InvalidDigestError",
    "JurisdictionSetError",
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
    "StateLawsReleaseSchemaError",
    "TASK_ID",
    "VectorRecord",
    "VerificationResult",
    "canonical_json_dumps",
    "coerce_family_set",
    "content_sha256",
    "digest_mapping",
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
    "validate_digest",
    "validate_document_index",
    "validate_durable_identity_fields",
    "validate_entry_cid",
    "validate_jurisdiction",
    "validate_jurisdiction_set",
    "validate_legal_id",
    "validate_physical_pointer_count",
    "validate_physical_row_count",
    "validate_release_record",
    "validate_semantic_family_closure",
]
