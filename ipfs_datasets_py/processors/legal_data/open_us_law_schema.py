"""Canonical Open US Law identity schema and configuration boundaries (OUL-005).

This module owns the fail-closed identity contract for the
``open-us-law-sparse-graphrag/v1`` release. It defines durable statute
identity fields, the exact-51 default configuration, and the explicit
non-default configurations that must never satisfy the default gate.

It deliberately does **not** implement acquisition, Parquet/Hub I/O, BM25,
embeddings, or publication callbacks. Downstream corpus and index builders
consume these contracts; this module performs no network I/O.

Design invariants
-----------------
* Default configuration is current exact-51 state/DC statutes only.
* Durable identity for those rows requires stable ``jurisdiction_code``,
  hierarchy, ``edition``, ``source_cid``, ``entry_cid``, and ``text_hash``.
* ``legal_id`` is citation-oriented and independent of release-local
  ``document_index``. Positional tokens such as ``row-N`` are rejected.
* Puerto Rico, federal US Code, constitutions, historical, recovery, and
  quarantine rows are explicit non-default configurations. They cannot be
  counted as default exact-51 coverage.
* Model and release pins must be immutable. Tokens such as ``latest`` or
  ``main`` are rejected.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-identity-schema-v1"
RELEASE_PROFILE: Final = "open-us-law-sparse-graphrag/v1"
TASK_ID: Final = "OUL-005"
ADR_PATH: Final = "docs/architecture/OPEN_US_LAW_REINDEX_PLAN.md"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/open-us-law-sparse-graphrag"
SOURCE_BUCKET: Final = "justicedao/open-us-law-bucket"
LEGAL_ID_PREFIX: Final = "oul"

DEFAULT_EMBEDDING_MODEL_ID: Final = "thenlper/gte-small"
DEFAULT_EMBEDDING_MODEL_REVISION: Final = (
    "17e1f347d17fe144873b1201da91788898c639cd"
)
DEFAULT_EMBEDDING_DIMENSION: Final = 384
DEFAULT_MODEL_TOKEN_CEILING: Final = 512

# ---------------------------------------------------------------------------
# Physical bounds (authoritative; never reuse as token ceilings)
# ---------------------------------------------------------------------------

MAX_ROWS_PER_PHYSICAL_SHARD: Final = 4096
MAX_POSTING_POINTERS_PER_ROW: Final = 4096
MAX_ADJACENCY_POINTERS_PER_ROW: Final = 4096
MAX_ROWS_PER_VECTOR_CENTROID: Final = 8192
MAX_VECTOR_SHARDS_PER_CENTROID: Final = 2
DEFAULT_CANDIDATE_CENTROIDS: Final = 4

# ---------------------------------------------------------------------------
# Exact-51 jurisdiction set (50 postal state codes + DC)
# ---------------------------------------------------------------------------

EXACT_51_JURISDICTION_CODES: Final = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
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
    "DC",
)
EXACT_51_JURISDICTIONS: Final = frozenset(EXACT_51_JURISDICTION_CODES)
EXPECTED_JURISDICTION_COUNT: Final = 51

# Known extra codes that exist in the seed bucket but are never default.
PUERTO_RICO_CODE: Final = "PR"
FEDERAL_JURISDICTION_CODE: Final = "US"
FEDERAL_JURISDICTION_ALIASES: Final = frozenset({"US", "USA", "FED", "FEDERAL"})
KNOWN_NON_DEFAULT_JURISDICTIONS: Final = frozenset(
    {PUERTO_RICO_CODE, FEDERAL_JURISDICTION_CODE}
)

JURISDICTION_NAMES: Final = MappingProxyType(
    {
        "AL": "Alabama",
        "AK": "Alaska",
        "AZ": "Arizona",
        "AR": "Arkansas",
        "CA": "California",
        "CO": "Colorado",
        "CT": "Connecticut",
        "DE": "Delaware",
        "DC": "District of Columbia",
        "FL": "Florida",
        "GA": "Georgia",
        "HI": "Hawaii",
        "ID": "Idaho",
        "IL": "Illinois",
        "IN": "Indiana",
        "IA": "Iowa",
        "KS": "Kansas",
        "KY": "Kentucky",
        "LA": "Louisiana",
        "ME": "Maine",
        "MD": "Maryland",
        "MA": "Massachusetts",
        "MI": "Michigan",
        "MN": "Minnesota",
        "MS": "Mississippi",
        "MO": "Missouri",
        "MT": "Montana",
        "NE": "Nebraska",
        "NV": "Nevada",
        "NH": "New Hampshire",
        "NJ": "New Jersey",
        "NM": "New Mexico",
        "NY": "New York",
        "NC": "North Carolina",
        "ND": "North Dakota",
        "OH": "Ohio",
        "OK": "Oklahoma",
        "OR": "Oregon",
        "PA": "Pennsylvania",
        "PR": "Puerto Rico",
        "RI": "Rhode Island",
        "SC": "South Carolina",
        "SD": "South Dakota",
        "TN": "Tennessee",
        "TX": "Texas",
        "US": "United States",
        "UT": "Utah",
        "VT": "Vermont",
        "VA": "Virginia",
        "WA": "Washington",
        "WV": "West Virginia",
        "WI": "Wisconsin",
        "WY": "Wyoming",
    }
)

# ---------------------------------------------------------------------------
# Configuration names
# ---------------------------------------------------------------------------

DEFAULT_CONFIGURATION: Final = "state_statutes_exact_51"
NON_DEFAULT_CONFIGURATION_NAMES: Final = (
    "federal_uscode",
    "puerto_rico",
    "constitutions",
    "historical",
    "recovery",
    "quarantine",
)
ALL_CONFIGURATION_NAMES: Final = (DEFAULT_CONFIGURATION,) + NON_DEFAULT_CONFIGURATION_NAMES

REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS: Final = (
    "jurisdiction_code",
    "hierarchy",
    "edition",
    "source_cid",
    "entry_cid",
    "text_hash",
)

REQUIRED_SERIALIZED_IDENTITY_FIELDS: Final = REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS + (
    "legal_id",
    "code_family",
    "configuration",
)

HIERARCHY_KEYS: Final = (
    "title",
    "chapter",
    "part",
    "article",
    "section",
    "subsection",
)

_FEDERAL_CODE_FAMILIES: Final = frozenset(
    {
        "usc",
        "uscode",
        "us-code",
        "united-states-code",
        "federal-uscode",
        "uscode-current",
    }
)
_CONSTITUTION_FAMILY_RE = re.compile(r"constitution", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Regular expressions
# ---------------------------------------------------------------------------

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CID_V1_RE = re.compile(r"^b[a-z2-7]{20,}$")
_ENTRY_CID_RE = re.compile(
    r"^(?:b[a-z2-7]{20,}|sha256:[0-9a-f]{64}|[0-9a-f]{64})$"
)
_CODE_FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_EDITION_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_QUALIFIER_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
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
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_LEADING_ZEROS_RE = re.compile(r"^0*(\d+)(.*)$")
_CHUNK_SUFFIX_RE = re.compile(r"#chunk=(?P<index>\d+)$")
_LEGAL_ID_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

_UNICODE_DASH_CHARS = (
    "\u2010",
    "\u2011",
    "\u2012",
    "\u2013",
    "\u2014",
    "\u2015",
    "\u2212",
    "\ufe58",
    "\ufe63",
    "\uff0d",
)
_DASH_TRANSLATION = str.maketrans({ch: "-" for ch in _UNICODE_DASH_CHARS})

_QUALIFIER_KEYS = (
    "edition",
    "granule",
    "note",
    "status",
    "subsection",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SCHEMA_RELATIVE_PATH: Final = "data/legal/open_us_law/release.schema.json"
RELEASE_SCHEMA_PATH: Final = _REPO_ROOT / RELEASE_SCHEMA_RELATIVE_PATH

JsonMapping = Mapping[str, Any]
PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawSchemaError(ValueError):
    """Base error for Open US Law identity and configuration failures."""


class PositionalIdentityError(OpenUsLawSchemaError):
    """Raised when durable identity is a positional token."""


class InvalidDigestError(OpenUsLawSchemaError):
    """Raised when a digest or CID field is malformed."""


class JurisdictionSetError(OpenUsLawSchemaError):
    """Raised when a jurisdiction is outside the allowed set for its role."""


class ConfigurationBoundaryError(OpenUsLawSchemaError):
    """Raised when a row is placed in the wrong release configuration."""


class Exact51GateError(OpenUsLawSchemaError):
    """Raised when non-default rows are used to satisfy the exact-51 gate."""


class MissingIdentityFieldError(OpenUsLawSchemaError):
    """Raised when a required identity field is absent."""


class MutableReferenceError(OpenUsLawSchemaError):
    """Raised when a pin uses a mutable token such as ``latest``."""


class ArtifactPathError(OpenUsLawSchemaError):
    """Raised when an artifact path is absolute, traverses, or is unsafe."""


class SchemaVersionError(OpenUsLawSchemaError):
    """Raised when schema_version or release profile is wrong."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReleaseConfiguration(str, Enum):
    """Named Hugging Face / release configurations."""

    STATE_STATUTES_EXACT_51 = "state_statutes_exact_51"
    FEDERAL_USCODE = "federal_uscode"
    PUERTO_RICO = "puerto_rico"
    CONSTITUTIONS = "constitutions"
    HISTORICAL = "historical"
    RECOVERY = "recovery"
    QUARANTINE = "quarantine"

    @classmethod
    def coerce(cls, value: Any) -> "ReleaseConfiguration":
        if isinstance(value, ReleaseConfiguration):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "default": cls.STATE_STATUTES_EXACT_51,
            "state_statutes": cls.STATE_STATUTES_EXACT_51,
            "exact_51": cls.STATE_STATUTES_EXACT_51,
            "exact51": cls.STATE_STATUTES_EXACT_51,
            "federal": cls.FEDERAL_USCODE,
            "federal_us_code": cls.FEDERAL_USCODE,
            "uscode": cls.FEDERAL_USCODE,
            "usc": cls.FEDERAL_USCODE,
            "pr": cls.PUERTO_RICO,
            "puerto-rico": cls.PUERTO_RICO,
            "constitution": cls.CONSTITUTIONS,
            "history": cls.HISTORICAL,
            "historical_rows": cls.HISTORICAL,
            "recover": cls.RECOVERY,
            "quarantined": cls.QUARANTINE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise ConfigurationBoundaryError(f"unknown release configuration: {value!r}")

    @property
    def is_default(self) -> bool:
        return self is ReleaseConfiguration.STATE_STATUTES_EXACT_51

    @property
    def satisfies_exact_51_gate(self) -> bool:
        return self is ReleaseConfiguration.STATE_STATUTES_EXACT_51

    @property
    def viewer_visible(self) -> bool:
        return self not in {
            ReleaseConfiguration.RECOVERY,
            ReleaseConfiguration.QUARANTINE,
        }

    @property
    def isolation_rank(self) -> int:
        return {
            ReleaseConfiguration.QUARANTINE: 3,
            ReleaseConfiguration.RECOVERY: 2,
            ReleaseConfiguration.HISTORICAL: 1,
        }.get(self, 0)


class DocumentKind(str, Enum):
    """Corpus family of a legal document (independent of configuration)."""

    STATUTE = "statute"
    FEDERAL = "federal"
    PUERTO_RICO = "puerto_rico"
    CONSTITUTION = "constitution"

    @classmethod
    def coerce(cls, value: Any) -> "DocumentKind":
        if isinstance(value, DocumentKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "state": cls.STATUTE,
            "state_statute": cls.STATUTE,
            "statutes": cls.STATUTE,
            "uscode": cls.FEDERAL,
            "usc": cls.FEDERAL,
            "federal_uscode": cls.FEDERAL,
            "pr": cls.PUERTO_RICO,
            "constitutions": cls.CONSTITUTION,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawSchemaError(f"unknown document kind: {value!r}")


class StatuteStatus(str, Enum):
    """Currency disposition of a statutory identity."""

    CURRENT = "current"
    HISTORICAL = "historical"
    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    RESERVED = "reserved"

    @classmethod
    def coerce(cls, value: Any) -> "StatuteStatus":
        if value is None or value == "":
            return cls.CURRENT
        if isinstance(value, StatuteStatus):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "in_force": cls.CURRENT,
            "effective": cls.CURRENT,
            "active": cls.CURRENT,
            "history": cls.HISTORICAL,
            "prior": cls.HISTORICAL,
            "repeal": cls.REPEALED,
            "supersede": cls.SUPERSEDED,
            "reserve": cls.RESERVED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawSchemaError(f"unknown statute status: {value!r}")

    @property
    def is_historical_configuration(self) -> bool:
        return self in {
            StatuteStatus.HISTORICAL,
            StatuteStatus.REPEALED,
            StatuteStatus.SUPERSEDED,
        }


class AdmissionStatus(str, Enum):
    """Admission disposition for one retrieval row."""

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
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawSchemaError(f"unknown admission status: {value!r}")


class SourceAuthorityClass(str, Enum):
    """Whether the acquisition source is official authority."""

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
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawSchemaError(f"unknown source authority class: {value!r}")


class VerificationResult(str, Enum):
    """Checksum / identity verification outcome."""

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
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenUsLawSchemaError(f"unknown verification result: {value!r}")


NON_DEFAULT_CONFIGURATIONS: Final = frozenset(
    {
        ReleaseConfiguration.FEDERAL_USCODE,
        ReleaseConfiguration.PUERTO_RICO,
        ReleaseConfiguration.CONSTITUTIONS,
        ReleaseConfiguration.HISTORICAL,
        ReleaseConfiguration.RECOVERY,
        ReleaseConfiguration.QUARANTINE,
    }
)
ISOLATION_CONFIGURATIONS: Final = frozenset(
    {
        ReleaseConfiguration.QUARANTINE,
        ReleaseConfiguration.RECOVERY,
        ReleaseConfiguration.HISTORICAL,
    }
)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawSchemaError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise OpenUsLawSchemaError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise OpenUsLawSchemaError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value", *, maximum: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, maximum=maximum)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawSchemaError(f"{name} must be an integer")
    if value < 0:
        raise OpenUsLawSchemaError(f"{name} must be >= 0")
    return value


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
    return content_sha256(canonical_json_dumps(payload))


def normalize_dash_chars(text: str) -> str:
    """Map Unicode dash/minus characters to ASCII hyphen-minus without truncation."""

    if not isinstance(text, str):
        raise OpenUsLawSchemaError("text must be a string")
    return unicodedata.normalize("NFKC", text).translate(_DASH_TRANSLATION)


def compute_text_hash(text: Any, *, name: str = "text") -> str:
    """Return the SHA-256 hex digest of NFC-normalized UTF-8 statute text."""

    raw = _require_non_empty_str(text, name, maximum=4_000_000)
    normalized = unicodedata.normalize("NFC", raw)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Digest / CID / pin validation
# ---------------------------------------------------------------------------


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise InvalidDigestError(
            f"{name} must be a lowercase 64-char hex SHA-256; got {value!r}"
        )
    return text


def validate_digest(value: Any, *, name: str = "digest") -> str:
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


def reject_positional_durable_identity(value: Any, *, name: str = "identity") -> None:
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"{name} must not use positional durable identity: {value!r}"
        )
    if text.lower().startswith("row-") and re.fullmatch(r"row-\d+", text.lower()):
        raise PositionalIdentityError(
            f"{name} must not use positional durable identity: {value!r}"
        )


def validate_entry_cid(value: Any, *, name: str = "entry_cid") -> str:
    text = _require_non_empty_str(value, name)
    reject_positional_durable_identity(text, name=name)
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


def validate_source_cid(value: Any, *, name: str = "source_cid") -> str:
    reject_positional_durable_identity(value, name=name)
    return validate_digest(value, name=name)


def validate_text_hash(value: Any, *, name: str = "text_hash") -> str:
    reject_positional_durable_identity(value, name=name)
    return normalize_sha256(value, name=name)


def validate_text_cid(value: Any, *, name: str = "text_cid") -> str:
    reject_positional_durable_identity(value, name=name)
    return validate_digest(value, name=name)


def is_immutable_revision(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    if _MUTABLE_REVISION_RE.fullmatch(text):
        return False
    lowered = text.lower()
    if lowered.startswith("sha256:"):
        return bool(_SHA256_HEX_RE.fullmatch(lowered[7:]))
    return bool(
        _GIT_SHA_RE.fullmatch(lowered)
        or _SHA256_HEX_RE.fullmatch(lowered)
        or _CID_V1_RE.fullmatch(lowered)
    )


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    text = _require_non_empty_str(value, name)
    if _MUTABLE_REVISION_RE.fullmatch(text) or not is_immutable_revision(text):
        raise MutableReferenceError(
            f"{name} must be a git SHA, SHA-256 digest, or CID; got {value!r}"
        )
    return text.strip()


def validate_document_index(
    value: Any,
    *,
    name: str = "document_index",
    allow_missing: bool = True,
) -> Optional[int]:
    if value is None or value == "":
        if allow_missing:
            return None
        raise OpenUsLawSchemaError(f"{name} is required")
    if isinstance(value, str) and _POSITIONAL_ID_RE.fullmatch(value.strip()):
        raise PositionalIdentityError(
            f"{name} string form is not a valid release-local index: {value!r}"
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenUsLawSchemaError(f"{name} must be an integer")
    if value < 0:
        raise OpenUsLawSchemaError(f"{name} must be >= 0")
    return value


# ---------------------------------------------------------------------------
# Jurisdiction / code family / edition / hierarchy
# ---------------------------------------------------------------------------


def _peek_jurisdiction_raw(payload: Mapping[str, Any]) -> Any:
    if payload.get("jurisdiction_code") not in (None, ""):
        return payload.get("jurisdiction_code")
    if payload.get("jurisdiction") not in (None, ""):
        return payload.get("jurisdiction")
    return payload.get("state_code") or payload.get("state")


def normalize_jurisdiction_code(
    value: Any,
    *,
    name: str = "jurisdiction_code",
    allow_non_default: bool = True,
) -> str:
    """Normalize a postal or federal jurisdiction code."""

    text = _require_non_empty_str(value, name, maximum=16).upper()
    if text in FEDERAL_JURISDICTION_ALIASES:
        text = FEDERAL_JURISDICTION_CODE
    if text in EXACT_51_JURISDICTIONS:
        return text
    if allow_non_default and text in KNOWN_NON_DEFAULT_JURISDICTIONS:
        return text
    if text in KNOWN_NON_DEFAULT_JURISDICTIONS:
        raise JurisdictionSetError(
            f"{name}={text!r} is a non-default jurisdiction and is not "
            f"admitted to the exact-51 set"
        )
    raise JurisdictionSetError(
        f"{name}={text!r} is not a recognized Open US Law jurisdiction"
    )


def validate_exact_51_jurisdiction(value: Any, *, name: str = "jurisdiction_code") -> str:
    return normalize_jurisdiction_code(value, name=name, allow_non_default=False)


def validate_jurisdiction_set(
    values: Any,
    *,
    name: str = "jurisdictions",
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise JurisdictionSetError(f"{name} must be a sequence of jurisdiction codes")
    codes = sorted(
        {
            validate_exact_51_jurisdiction(item, name=f"{name}[]")
            for item in values
        }
    )
    present = frozenset(codes)
    if present != EXACT_51_JURISDICTIONS:
        missing = sorted(EXACT_51_JURISDICTIONS - present)
        extra = sorted(present - EXACT_51_JURISDICTIONS)
        raise JurisdictionSetError(
            f"{name} must equal the exact 51-jurisdiction set; "
            f"missing={missing!r} extra={extra!r}"
        )
    return tuple(codes)


def normalize_code_family(value: Any, *, name: str = "code_family") -> str:
    text = _require_non_empty_str(value, name, maximum=128)
    text = normalize_dash_chars(text)
    text = text.strip().lower().replace(" ", "-").replace("/", "-")
    text = re.sub(r"_+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = re.sub(r"[^a-z0-9._-]", "", text)
    if not text or not _CODE_FAMILY_RE.fullmatch(text):
        raise OpenUsLawSchemaError(
            f"{name} must match [a-z0-9][a-z0-9._-]{{0,63}}; got {value!r}"
        )
    return text


def normalize_edition(value: Any, *, name: str = "edition") -> str:
    text = _require_non_empty_str(value, name, maximum=128)
    text = normalize_dash_chars(text).strip().lower().replace(" ", "-")
    text = re.sub(r"_+", "-", text)
    text = re.sub(r"-+", "-", text)
    if _MUTABLE_REVISION_RE.fullmatch(text):
        raise MutableReferenceError(
            f"{name} must be an exact edition pin, not {value!r}"
        )
    if not _EDITION_RE.fullmatch(text):
        raise OpenUsLawSchemaError(
            f"{name} must be a stable edition slug; got {value!r}"
        )
    return text


def normalize_section_token(section: Any, *, name: str = "section") -> str:
    """Normalize a section token without Unicode-dash truncation."""

    original = _require_non_empty_str(section, name, maximum=256)
    text = normalize_dash_chars(original).strip()
    text = text.lstrip("§").strip()
    text = re.sub(
        r"^(?:sec(?:tion)?\.?\s*)",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = text.rstrip(".,;:")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "", text)
    text = text.rstrip(".,;:")
    if not text:
        raise OpenUsLawSchemaError(f"{name} must be non-empty after normalization")
    parts: list[str] = []
    for piece in text.split("-"):
        if not piece:
            raise OpenUsLawSchemaError(f"malformed {name} range: {section!r}")
        match = _LEADING_ZEROS_RE.match(piece)
        if match:
            parts.append(f"{int(match.group(1))}{match.group(2)}")
        else:
            parts.append(piece)
    return "-".join(parts)


def _normalize_hierarchy_segment(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if name == "section":
        return normalize_section_token(value, name=name)
    text = _require_non_empty_str(value, name, maximum=128)
    text = normalize_dash_chars(text)
    text = text.lstrip("§").strip().rstrip(".,;:")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "", text)
    if not text:
        return None
    parts: list[str] = []
    for piece in text.split("-"):
        if not piece:
            raise OpenUsLawSchemaError(f"malformed {name} range: {value!r}")
        match = _LEADING_ZEROS_RE.match(piece)
        if match:
            parts.append(f"{int(match.group(1))}{match.group(2)}")
        else:
            parts.append(piece.lower() if not piece[:1].isdigit() else piece)
    return "-".join(parts)


@dataclass(frozen=True, slots=True)
class Hierarchy:
    """Stable title/chapter/section/subsection coordinates."""

    section: Optional[str] = None
    title: Optional[str] = None
    chapter: Optional[str] = None
    part: Optional[str] = None
    article: Optional[str] = None
    subsection: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "section", _normalize_hierarchy_segment(self.section, "section")
        )
        object.__setattr__(
            self, "title", _normalize_hierarchy_segment(self.title, "title")
        )
        object.__setattr__(
            self, "chapter", _normalize_hierarchy_segment(self.chapter, "chapter")
        )
        object.__setattr__(
            self, "part", _normalize_hierarchy_segment(self.part, "part")
        )
        object.__setattr__(
            self, "article", _normalize_hierarchy_segment(self.article, "article")
        )
        object.__setattr__(
            self,
            "subsection",
            _normalize_hierarchy_segment(self.subsection, "subsection"),
        )

    def path_segments(self) -> tuple[str, ...]:
        segments = [
            item
            for item in (self.title, self.chapter, self.part, self.article, self.section)
            if item
        ]
        return tuple(segments)

    def path(self) -> str:
        segments = self.path_segments()
        if not segments:
            raise OpenUsLawSchemaError("hierarchy path requires at least one segment")
        return ":".join(segments)

    def require_section(self) -> str:
        if not self.section:
            raise MissingIdentityFieldError("hierarchy.section is required")
        return self.section

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "article": self.article,
            "chapter": self.chapter,
            "part": self.part,
            "section": self.section,
            "subsection": self.subsection,
            "title": self.title,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "Hierarchy":
        if isinstance(value, Hierarchy):
            return value
        if isinstance(value, str):
            text = normalize_dash_chars(value).strip().strip(":")
            text = re.sub(r"\s+", "", text)
            if not text:
                raise OpenUsLawSchemaError("hierarchy path must be non-empty")
            pieces = [piece for piece in text.split(":") if piece]
            if not pieces:
                raise OpenUsLawSchemaError("hierarchy path must be non-empty")
            section = pieces[-1]
            title = pieces[0] if len(pieces) >= 2 else None
            chapter = pieces[1] if len(pieces) >= 3 else None
            part = pieces[2] if len(pieces) >= 4 else None
            article = pieces[3] if len(pieces) >= 5 else None
            if len(pieces) == 1:
                title = None
            return cls(
                section=section,
                title=title,
                chapter=chapter,
                part=part,
                article=article,
            )
        if not isinstance(value, Mapping):
            raise OpenUsLawSchemaError("hierarchy must be a mapping, path, or Hierarchy")
        section = value.get("section")
        if section is None:
            section = value.get("section_number") or value.get("sectionNumber")
        title = value.get("title")
        if title is None:
            title = value.get("title_number") or value.get("titleNumber")
        chapter = value.get("chapter")
        if chapter is None:
            chapter = value.get("chapter_number") or value.get("chapterNumber")
        return cls(
            section=section,
            title=title,
            chapter=chapter,
            part=value.get("part"),
            article=value.get("article"),
            subsection=value.get("subsection"),
        )


def normalize_hierarchy(value: Any) -> Hierarchy:
    return Hierarchy.from_mapping(value)


# ---------------------------------------------------------------------------
# legal_id
# ---------------------------------------------------------------------------


def _format_qualifiers(components: Mapping[str, Optional[str]]) -> str:
    parts: list[str] = []
    for key in _QUALIFIER_KEYS:
        value = components.get(key)
        if value is None or value == "":
            continue
        if key == "status" and value == StatuteStatus.CURRENT.value:
            continue
        if not _QUALIFIER_TOKEN_RE.fullmatch(value):
            raise OpenUsLawSchemaError(f"illegal legal_id qualifier {key}={value!r}")
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return ";" + ";".join(parts)


def build_legal_id(
    *,
    document_kind: Any,
    jurisdiction_code: Any,
    code_family: Any,
    hierarchy: Any,
    edition: Any,
    status: Any = StatuteStatus.CURRENT,
    subsection: Any = None,
    granule: Any = None,
    note: Any = None,
) -> str:
    """Build a stable ``oul:<kind>:<JJ>:<family>:<path>[;qualifiers]`` identifier."""

    kind = DocumentKind.coerce(document_kind).value
    jurisdiction = normalize_jurisdiction_code(jurisdiction_code)
    family = normalize_code_family(code_family)
    parsed = normalize_hierarchy(hierarchy)
    edition_slug = normalize_edition(edition)
    status_value = StatuteStatus.coerce(status).value
    subsection_value = parsed.subsection or _normalize_hierarchy_segment(
        subsection, "subsection"
    )
    path = parsed.path()
    qualifiers = _format_qualifiers(
        {
            "edition": edition_slug,
            "granule": _optional_str(granule, "granule", maximum=128),
            "note": _optional_str(note, "note", maximum=128),
            "status": status_value,
            "subsection": subsection_value,
        }
    )
    return f"{LEGAL_ID_PREFIX}:{kind}:{jurisdiction}:{family}:{path}{qualifiers}"


def parse_legal_id(legal_id: str) -> dict[str, Any]:
    """Parse a previously built Open US Law ``legal_id``."""

    text = _require_non_empty_str(legal_id, "legal_id")
    reject_positional_durable_identity(text, name="legal_id")
    if not text.lower().startswith(f"{LEGAL_ID_PREFIX}:"):
        raise OpenUsLawSchemaError(
            f"legal_id must start with '{LEGAL_ID_PREFIX}:'; got {legal_id!r}"
        )
    body = text[len(LEGAL_ID_PREFIX) + 1 :]
    if ";" in body:
        base, qual_text = body.split(";", 1)
        qualifiers: dict[str, str] = {}
        for part in qual_text.split(";"):
            if not part:
                continue
            if "=" not in part:
                raise OpenUsLawSchemaError(f"malformed legal_id qualifier: {part!r}")
            key, value = part.split("=", 1)
            qualifiers[key] = value
    else:
        base = body
        qualifiers = {}

    pieces = base.split(":")
    if len(pieces) < 4:
        raise OpenUsLawSchemaError(
            "legal_id base must be kind:jurisdiction:code_family:path…; "
            f"got {base!r}"
        )
    kind = DocumentKind.coerce(pieces[0]).value
    if not _LEGAL_ID_KIND_RE.fullmatch(kind):
        raise OpenUsLawSchemaError(f"illegal legal_id document kind: {pieces[0]!r}")
    jurisdiction = normalize_jurisdiction_code(pieces[1])
    code_family = normalize_code_family(pieces[2])
    hierarchy = Hierarchy.from_mapping(":".join(pieces[3:]))
    if qualifiers.get("subsection") and not hierarchy.subsection:
        hierarchy = Hierarchy(
            section=hierarchy.section,
            title=hierarchy.title,
            chapter=hierarchy.chapter,
            part=hierarchy.part,
            article=hierarchy.article,
            subsection=qualifiers.get("subsection"),
        )
    edition = normalize_edition(qualifiers["edition"]) if "edition" in qualifiers else None
    status = StatuteStatus.coerce(qualifiers.get("status", StatuteStatus.CURRENT))
    return {
        "document_kind": kind,
        "jurisdiction_code": jurisdiction,
        "code_family": code_family,
        "hierarchy": hierarchy,
        "edition": edition,
        "status": status.value,
        "subsection": hierarchy.subsection,
        "granule": qualifiers.get("granule"),
        "note": qualifiers.get("note"),
        "legal_id": build_legal_id(
            document_kind=kind,
            jurisdiction_code=jurisdiction,
            code_family=code_family,
            hierarchy=hierarchy,
            edition=edition or "unspecified",
            status=status,
            granule=qualifiers.get("granule"),
            note=qualifiers.get("note"),
        )
        if edition
        else f"{LEGAL_ID_PREFIX}:{kind}:{jurisdiction}:{code_family}:{hierarchy.path()}",
    }


def validate_legal_id(value: Any, *, name: str = "legal_id") -> str:
    parsed = parse_legal_id(_require_non_empty_str(value, name))
    if parsed.get("edition"):
        return build_legal_id(
            document_kind=parsed["document_kind"],
            jurisdiction_code=parsed["jurisdiction_code"],
            code_family=parsed["code_family"],
            hierarchy=parsed["hierarchy"],
            edition=parsed["edition"],
            status=parsed["status"],
            granule=parsed.get("granule"),
            note=parsed.get("note"),
        )
    return parsed["legal_id"]


# ---------------------------------------------------------------------------
# Configuration classification
# ---------------------------------------------------------------------------


def _optional_document_kind(payload: Mapping[str, Any]) -> Optional[DocumentKind]:
    raw = payload.get("document_kind")
    if raw in (None, ""):
        raw = payload.get("kind")
    if raw in (None, ""):
        return None
    text = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"historical", "history", "recovery", "quarantine", "quarantined"}:
        return None
    return DocumentKind.coerce(raw)


def _optional_status(payload: Mapping[str, Any]) -> StatuteStatus:
    raw = payload.get("status")
    if raw in (None, ""):
        raw = payload.get("statute_status")
    return StatuteStatus.coerce(raw)


def _optional_admission(payload: Mapping[str, Any]) -> Optional[AdmissionStatus]:
    raw = payload.get("admission_status")
    if raw in (None, ""):
        return None
    return AdmissionStatus.coerce(raw)


def _looks_like_constitution(payload: Mapping[str, Any]) -> bool:
    family = payload.get("code_family") or payload.get("codeFamily") or ""
    if isinstance(family, str) and family and _CONSTITUTION_FAMILY_RE.search(family):
        return True
    kind = payload.get("document_kind") or payload.get("kind") or ""
    if isinstance(kind, str) and "constitution" in kind.lower():
        return True
    return False


def _is_puerto_rico(payload: Mapping[str, Any]) -> bool:
    try:
        code = normalize_jurisdiction_code(
            _peek_jurisdiction_raw(payload), allow_non_default=True
        )
    except OpenUsLawSchemaError:
        code = ""
    if code == PUERTO_RICO_CODE:
        return True
    kind = payload.get("document_kind") or payload.get("kind") or ""
    return isinstance(kind, str) and kind.strip().lower().replace("-", "_") in {
        "pr",
        "puerto_rico",
        "puerto-rico",
    }


def _is_federal(payload: Mapping[str, Any]) -> bool:
    try:
        code = normalize_jurisdiction_code(
            _peek_jurisdiction_raw(payload), allow_non_default=True
        )
    except OpenUsLawSchemaError:
        code = ""
    if code == FEDERAL_JURISDICTION_CODE:
        return True
    family = payload.get("code_family") or payload.get("codeFamily") or ""
    if isinstance(family, str) and normalize_code_family(family) in _FEDERAL_CODE_FAMILIES:
        return True
    kind = payload.get("document_kind") or payload.get("kind") or ""
    return isinstance(kind, str) and kind.strip().lower().replace("-", "_") in {
        "federal",
        "uscode",
        "usc",
        "federal_uscode",
    }


def infer_configuration(payload: Mapping[str, Any]) -> ReleaseConfiguration:
    """Infer the tightest configuration from row identity fields.

    Explicit ``configuration`` is ignored here so operators cannot hide a
    Puerto Rico or federal row inside the default exact-51 set.
    """

    if not isinstance(payload, Mapping):
        raise OpenUsLawSchemaError("configuration payload must be a mapping")

    admission = _optional_admission(payload)
    if admission in {AdmissionStatus.QUARANTINED, AdmissionStatus.REJECTED}:
        return ReleaseConfiguration.QUARANTINE
    if admission is AdmissionStatus.RECOVERY:
        return ReleaseConfiguration.RECOVERY

    status = _optional_status(payload)
    if status.is_historical_configuration:
        return ReleaseConfiguration.HISTORICAL

    kind = _optional_document_kind(payload)
    if kind is DocumentKind.CONSTITUTION or _looks_like_constitution(payload):
        return ReleaseConfiguration.CONSTITUTIONS
    if kind is DocumentKind.PUERTO_RICO or _is_puerto_rico(payload):
        return ReleaseConfiguration.PUERTO_RICO
    if kind is DocumentKind.FEDERAL or _is_federal(payload):
        return ReleaseConfiguration.FEDERAL_USCODE

    raw_jurisdiction = _peek_jurisdiction_raw(payload)
    if raw_jurisdiction in (None, ""):
        raise ConfigurationBoundaryError(
            "cannot classify a row without jurisdiction_code"
        )
    jurisdiction = normalize_jurisdiction_code(
        raw_jurisdiction, allow_non_default=True
    )
    if jurisdiction == PUERTO_RICO_CODE:
        return ReleaseConfiguration.PUERTO_RICO
    if jurisdiction == FEDERAL_JURISDICTION_CODE:
        return ReleaseConfiguration.FEDERAL_USCODE
    if jurisdiction in EXACT_51_JURISDICTIONS:
        if kind in {None, DocumentKind.STATUTE}:
            return ReleaseConfiguration.STATE_STATUTES_EXACT_51
    raise ConfigurationBoundaryError(
        f"cannot classify row for jurisdiction={jurisdiction!r} kind={kind!r}"
    )


def classify_configuration(payload: Mapping[str, Any]) -> ReleaseConfiguration:
    """Return the authoritative configuration for a row.

    A row may be promoted into an isolation configuration (historical,
    recovery, quarantine). It may never be demoted into default, and it may
    never be moved across sibling corpus configurations (for example PR into
    federal, or an Oregon statute into federal).
    """

    inferred = infer_configuration(payload)
    explicit_raw = payload.get("configuration")
    if explicit_raw in (None, ""):
        return inferred
    declared = ReleaseConfiguration.coerce(explicit_raw)
    if declared is inferred:
        return declared
    if declared in ISOLATION_CONFIGURATIONS:
        if inferred in ISOLATION_CONFIGURATIONS:
            if declared.isolation_rank >= inferred.isolation_rank:
                return declared
        else:
            return declared
    raise ConfigurationBoundaryError(
        f"declared configuration {declared.value!r} is incompatible with "
        f"inferred configuration {inferred.value!r}"
    )


def configuration_satisfies_exact_51(value: Any) -> bool:
    return ReleaseConfiguration.coerce(value).satisfies_exact_51_gate


def default_configuration_policy() -> dict[str, Any]:
    return {
        "name": DEFAULT_CONFIGURATION,
        "default": True,
        "satisfies_exact_51_gate": True,
        "viewer_visible": True,
        "viewer_default_split": True,
        "required_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "required_jurisdiction_codes": list(EXACT_51_JURISDICTION_CODES),
        "required_identity_fields": list(REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS),
        "allowed_document_kinds": [DocumentKind.STATUTE.value],
        "allowed_statuses": [
            StatuteStatus.CURRENT.value,
            StatuteStatus.RESERVED.value,
        ],
        "forbidden_jurisdictions": sorted(KNOWN_NON_DEFAULT_JURISDICTIONS),
    }


def non_default_configuration_policy() -> dict[str, dict[str, Any]]:
    descriptions = {
        ReleaseConfiguration.FEDERAL_USCODE: (
            "Federal United States Code rows. Useful corpus; never default exact-51."
        ),
        ReleaseConfiguration.PUERTO_RICO: (
            "Puerto Rico statutory rows. Explicit non-default configuration."
        ),
        ReleaseConfiguration.CONSTITUTIONS: (
            "Federal, state, DC, and territorial constitution rows."
        ),
        ReleaseConfiguration.HISTORICAL: (
            "Superseded, repealed, or otherwise non-current statute versions."
        ),
        ReleaseConfiguration.RECOVERY: (
            "Recovery records that cannot enter canonical default counts."
        ),
        ReleaseConfiguration.QUARANTINE: (
            "Quarantined or rejected rows excluded from the Viewer default split."
        ),
    }
    return {
        config.value: {
            "name": config.value,
            "default": False,
            "satisfies_exact_51_gate": False,
            "viewer_visible": config.viewer_visible,
            "viewer_default_split": False,
            "description": descriptions[config],
        }
        for config in (
            ReleaseConfiguration.FEDERAL_USCODE,
            ReleaseConfiguration.PUERTO_RICO,
            ReleaseConfiguration.CONSTITUTIONS,
            ReleaseConfiguration.HISTORICAL,
            ReleaseConfiguration.RECOVERY,
            ReleaseConfiguration.QUARANTINE,
        )
    }


def configuration_boundary_policy() -> dict[str, Any]:
    return {
        "default_configuration": DEFAULT_CONFIGURATION,
        "non_default_configurations": list(NON_DEFAULT_CONFIGURATION_NAMES),
        "all_configurations": list(ALL_CONFIGURATION_NAMES),
        "default": default_configuration_policy(),
        "separate": non_default_configuration_policy(),
        "viewer_excludes_from_default": list(NON_DEFAULT_CONFIGURATION_NAMES),
        "viewer_hidden": [
            ReleaseConfiguration.RECOVERY.value,
            ReleaseConfiguration.QUARANTINE.value,
        ],
    }


def physical_bounds_policy() -> dict[str, int]:
    return {
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_posting_pointers_per_row": MAX_POSTING_POINTERS_PER_ROW,
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
        "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
        "model_token_ceiling": DEFAULT_MODEL_TOKEN_CEILING,
        "embedding_dimension": DEFAULT_EMBEDDING_DIMENSION,
    }


# ---------------------------------------------------------------------------
# Identity validation
# ---------------------------------------------------------------------------


def _missing_fields(payload: Mapping[str, Any], names: Sequence[str]) -> list[str]:
    missing: list[str] = []
    for name in names:
        if name == "jurisdiction_code":
            if _peek_jurisdiction_raw(payload) in (None, ""):
                missing.append(name)
            continue
        if name == "hierarchy":
            if payload.get("hierarchy") in (None, ""):
                has_section = payload.get("section") not in (None, "")
                if not has_section:
                    missing.append(name)
            continue
        if payload.get(name) in (None, ""):
            missing.append(name)
    return missing


def validate_default_statute_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Require stable default-statute identity fields and configuration."""

    if not isinstance(payload, Mapping):
        raise OpenUsLawSchemaError("identity payload must be a mapping")

    for key in ("entry_cid", "source_cid", "text_hash", "legal_id", "id", "row_id"):
        if key in payload:
            reject_positional_durable_identity(payload.get(key), name=key)

    missing = _missing_fields(payload, REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS)
    if missing:
        for positional_key in (
            "document_index",
            "row_index",
            "row_number",
            "positional_id",
        ):
            if payload.get(positional_key) not in (None, "") and missing:
                raise PositionalIdentityError(
                    "durable identity requires jurisdiction_code, hierarchy, "
                    f"edition, source_cid, entry_cid, and text_hash; "
                    f"{positional_key} is release-local only"
                )
        raise MissingIdentityFieldError(
            f"default state statute missing required identity fields: {missing}"
        )

    configuration = classify_configuration(payload)
    if configuration is not ReleaseConfiguration.STATE_STATUTES_EXACT_51:
        raise ConfigurationBoundaryError(
            "default statute identity is only valid for "
            f"{DEFAULT_CONFIGURATION}; classified as {configuration.value!r}"
        )

    jurisdiction = validate_exact_51_jurisdiction(_peek_jurisdiction_raw(payload))
    hierarchy_value = payload.get("hierarchy")
    if hierarchy_value in (None, ""):
        hierarchy_value = {
            key: payload.get(key)
            for key in HIERARCHY_KEYS
            if payload.get(key) not in (None, "")
        }
    hierarchy = normalize_hierarchy(hierarchy_value)
    hierarchy.require_section()
    edition = normalize_edition(payload.get("edition"))
    source_cid = validate_source_cid(payload.get("source_cid"))
    entry_cid = validate_entry_cid(payload.get("entry_cid"))
    text_hash = validate_text_hash(payload.get("text_hash"))
    if payload.get("text") not in (None, ""):
        expected = compute_text_hash(payload.get("text"))
        if expected != text_hash:
            raise InvalidDigestError(
                "text_hash does not match SHA-256 of provided text"
            )

    code_family_raw = payload.get("code_family") or payload.get("codeFamily")
    if code_family_raw in (None, ""):
        raise MissingIdentityFieldError("code_family is required on default statutes")
    code_family = normalize_code_family(code_family_raw)
    if _CONSTITUTION_FAMILY_RE.search(code_family) or code_family in _FEDERAL_CODE_FAMILIES:
        raise ConfigurationBoundaryError(
            f"code_family={code_family!r} cannot enter the default exact-51 set"
        )

    status = _optional_status(payload)
    if status.is_historical_configuration:
        raise ConfigurationBoundaryError(
            f"status={status.value!r} cannot enter the default exact-51 set"
        )
    kind = _optional_document_kind(payload) or DocumentKind.STATUTE
    if kind is not DocumentKind.STATUTE:
        raise ConfigurationBoundaryError(
            f"document_kind={kind.value!r} cannot enter the default exact-51 set"
        )

    legal_id_raw = payload.get("legal_id")
    legal_id = build_legal_id(
        document_kind=kind,
        jurisdiction_code=jurisdiction,
        code_family=code_family,
        hierarchy=hierarchy,
        edition=edition,
        status=status,
        granule=payload.get("granule"),
        note=payload.get("note"),
    )
    if legal_id_raw not in (None, ""):
        normalized_existing = validate_legal_id(legal_id_raw)
        if normalized_existing != legal_id:
            raise OpenUsLawSchemaError(
                f"legal_id {legal_id_raw!r} does not match reconstructed "
                f"identity {legal_id!r}"
            )

    text_cid = None
    if payload.get("text_cid") not in (None, ""):
        text_cid = validate_text_cid(payload.get("text_cid"))

    return {
        "code_family": code_family,
        "configuration": configuration.value,
        "document_index": validate_document_index(payload.get("document_index")),
        "document_kind": kind.value,
        "edition": edition,
        "entry_cid": entry_cid,
        "hierarchy": hierarchy.to_dict(),
        "jurisdiction_code": jurisdiction,
        "legal_id": legal_id,
        "satisfies_exact_51_gate": True,
        "source_cid": source_cid,
        "status": status.value,
        "text_cid": text_cid,
        "text_hash": text_hash,
    }


def validate_non_default_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a non-default row while still requiring durable CID/hash fields."""

    if not isinstance(payload, Mapping):
        raise OpenUsLawSchemaError("identity payload must be a mapping")
    configuration = classify_configuration(payload)
    if configuration is ReleaseConfiguration.STATE_STATUTES_EXACT_51:
        raise ConfigurationBoundaryError(
            "validate_non_default_identity cannot accept the default configuration"
        )

    for key in ("entry_cid", "source_cid", "text_hash", "legal_id"):
        if key in payload:
            reject_positional_durable_identity(payload.get(key), name=key)

    missing = [
        name
        for name in ("source_cid", "entry_cid", "text_hash")
        if payload.get(name) in (None, "")
    ]
    if missing:
        raise MissingIdentityFieldError(
            f"{configuration.value} row missing durable identity fields: {missing}"
        )

    jurisdiction = normalize_jurisdiction_code(
        _peek_jurisdiction_raw(payload), allow_non_default=True
    )
    if configuration is ReleaseConfiguration.PUERTO_RICO and jurisdiction != PUERTO_RICO_CODE:
        if not _is_puerto_rico(payload) and configuration is infer_configuration(payload):
            raise ConfigurationBoundaryError(
                "puerto_rico configuration requires jurisdiction_code=PR"
            )
    if configuration is ReleaseConfiguration.FEDERAL_USCODE:
        if jurisdiction not in {FEDERAL_JURISDICTION_CODE} and not _is_federal(payload):
            raise ConfigurationBoundaryError(
                "federal_uscode configuration requires a federal jurisdiction"
            )

    hierarchy_value = payload.get("hierarchy")
    if hierarchy_value in (None, ""):
        hierarchy_value = {
            key: payload.get(key)
            for key in HIERARCHY_KEYS
            if payload.get(key) not in (None, "")
        }
    hierarchy = (
        normalize_hierarchy(hierarchy_value)
        if hierarchy_value
        else Hierarchy(section=payload.get("section") or "0")
    )
    edition = normalize_edition(payload.get("edition") or "unspecified")
    source_cid = validate_source_cid(payload.get("source_cid"))
    entry_cid = validate_entry_cid(payload.get("entry_cid"))
    text_hash = validate_text_hash(payload.get("text_hash"))
    if payload.get("text") not in (None, ""):
        if compute_text_hash(payload.get("text")) != text_hash:
            raise InvalidDigestError(
                "text_hash does not match SHA-256 of provided text"
            )

    kind = _optional_document_kind(payload)
    if kind is None:
        if configuration is ReleaseConfiguration.CONSTITUTIONS:
            kind = DocumentKind.CONSTITUTION
        elif configuration is ReleaseConfiguration.PUERTO_RICO:
            kind = DocumentKind.PUERTO_RICO
        elif configuration is ReleaseConfiguration.FEDERAL_USCODE:
            kind = DocumentKind.FEDERAL
        else:
            kind = DocumentKind.STATUTE
    code_family = normalize_code_family(
        payload.get("code_family") or payload.get("codeFamily") or configuration.value
    )
    status = _optional_status(payload)
    legal_id = build_legal_id(
        document_kind=kind,
        jurisdiction_code=jurisdiction,
        code_family=code_family,
        hierarchy=hierarchy,
        edition=edition,
        status=status,
        granule=payload.get("granule"),
        note=payload.get("note"),
    )
    text_cid = None
    if payload.get("text_cid") not in (None, ""):
        text_cid = validate_text_cid(payload.get("text_cid"))
    return {
        "code_family": code_family,
        "configuration": configuration.value,
        "document_index": validate_document_index(payload.get("document_index")),
        "document_kind": kind.value,
        "edition": edition,
        "entry_cid": entry_cid,
        "hierarchy": hierarchy.to_dict(),
        "jurisdiction_code": jurisdiction,
        "legal_id": legal_id,
        "satisfies_exact_51_gate": False,
        "source_cid": source_cid,
        "status": status.value,
        "text_cid": text_cid,
        "text_hash": text_hash,
    }


def validate_corpus_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate any corpus identity row and bind it to one configuration."""

    configuration = classify_configuration(payload)
    if configuration is ReleaseConfiguration.STATE_STATUTES_EXACT_51:
        return validate_default_statute_identity(payload)
    return validate_non_default_identity(payload)


def partition_by_configuration(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    partitioned = {name: [] for name in ALL_CONFIGURATION_NAMES}
    for row in rows:
        validated = validate_corpus_identity(row)
        partitioned[validated["configuration"]].append(validated)
    return partitioned


def validate_exact_51_gate(
    rows: Iterable[Mapping[str, Any]],
    *,
    require_full_coverage: bool = False,
) -> dict[str, Any]:
    """Prove that only default current exact-51 statutes satisfy the gate.

    Non-default configurations may be present in *rows* but are ignored for
    coverage. A default-classified row from PR, federal, constitutions,
    historical, recovery, or quarantine fails closed.
    """

    default_rows: list[dict[str, Any]] = []
    non_default_counts: dict[str, int] = {
        name: 0 for name in NON_DEFAULT_CONFIGURATION_NAMES
    }
    seen_default_keys: set[str] = set()
    for row in rows:
        validated = validate_corpus_identity(row)
        config = validated["configuration"]
        if config == DEFAULT_CONFIGURATION:
            key = validated["entry_cid"]
            if key in seen_default_keys:
                raise Exact51GateError(f"duplicate default entry_cid: {key}")
            seen_default_keys.add(key)
            default_rows.append(validated)
        else:
            if configuration_satisfies_exact_51(config):
                raise Exact51GateError(
                    f"configuration {config!r} cannot both be non-default and "
                    f"satisfy the exact-51 gate"
                )
            non_default_counts[config] += 1

    jurisdictions = sorted({item["jurisdiction_code"] for item in default_rows})
    present = frozenset(jurisdictions)
    extra = sorted(present - EXACT_51_JURISDICTIONS)
    if extra:
        raise Exact51GateError(
            f"default configuration contains non-exact-51 jurisdictions: {extra!r}"
        )
    missing = sorted(EXACT_51_JURISDICTIONS - present)
    if require_full_coverage and missing:
        raise Exact51GateError(
            f"default configuration missing required jurisdictions: {missing!r}"
        )
    if require_full_coverage and present != EXACT_51_JURISDICTIONS:
        raise Exact51GateError("default configuration is not the exact 51-set")

    return {
        "closed": (not require_full_coverage) or present == EXACT_51_JURISDICTIONS,
        "default_configuration": DEFAULT_CONFIGURATION,
        "default_row_count": len(default_rows),
        "default_jurisdictions": jurisdictions,
        "missing_jurisdictions": missing,
        "extra_jurisdictions": extra,
        "non_default_counts": non_default_counts,
        "non_default_satisfies_gate": False,
    }


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatuteIdentity:
    """Durable identity for one Open US Law addressable unit."""

    jurisdiction_code: str
    code_family: str
    hierarchy: Hierarchy
    edition: str
    source_cid: str
    entry_cid: str
    text_hash: str
    document_kind: DocumentKind = DocumentKind.STATUTE
    status: StatuteStatus = StatuteStatus.CURRENT
    configuration: Optional[ReleaseConfiguration] = None
    text_cid: Optional[str] = None
    granule: Optional[str] = None
    note: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "jurisdiction_code",
            normalize_jurisdiction_code(self.jurisdiction_code),
        )
        object.__setattr__(self, "code_family", normalize_code_family(self.code_family))
        object.__setattr__(self, "hierarchy", normalize_hierarchy(self.hierarchy))
        object.__setattr__(self, "edition", normalize_edition(self.edition))
        object.__setattr__(self, "source_cid", validate_source_cid(self.source_cid))
        object.__setattr__(self, "entry_cid", validate_entry_cid(self.entry_cid))
        object.__setattr__(self, "text_hash", validate_text_hash(self.text_hash))
        object.__setattr__(self, "document_kind", DocumentKind.coerce(self.document_kind))
        object.__setattr__(self, "status", StatuteStatus.coerce(self.status))
        if self.text_cid is not None:
            object.__setattr__(self, "text_cid", validate_text_cid(self.text_cid))
        if self.granule is not None:
            object.__setattr__(self, "granule", _optional_str(self.granule, "granule"))
        if self.note is not None:
            object.__setattr__(self, "note", _optional_str(self.note, "note"))
        payload = self.to_classification_payload()
        resolved = (
            classify_configuration({**payload, "configuration": self.configuration})
            if self.configuration is not None
            else classify_configuration(payload)
        )
        object.__setattr__(self, "configuration", resolved)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )

    @property
    def legal_id(self) -> str:
        return build_legal_id(
            document_kind=self.document_kind,
            jurisdiction_code=self.jurisdiction_code,
            code_family=self.code_family,
            hierarchy=self.hierarchy,
            edition=self.edition,
            status=self.status,
            granule=self.granule,
            note=self.note,
        )

    def to_classification_payload(self) -> dict[str, Any]:
        return {
            "jurisdiction_code": self.jurisdiction_code,
            "code_family": self.code_family,
            "document_kind": self.document_kind.value
            if isinstance(self.document_kind, DocumentKind)
            else self.document_kind,
            "status": self.status.value
            if isinstance(self.status, StatuteStatus)
            else self.status,
            "hierarchy": self.hierarchy.to_dict()
            if isinstance(self.hierarchy, Hierarchy)
            else self.hierarchy,
            "edition": self.edition,
            "source_cid": self.source_cid,
            "entry_cid": self.entry_cid,
            "text_hash": self.text_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration
        assert isinstance(configuration, ReleaseConfiguration)
        return {
            "code_family": self.code_family,
            "configuration": configuration.value,
            "document_kind": self.document_kind.value,
            "edition": self.edition,
            "entry_cid": self.entry_cid,
            "granule": self.granule,
            "hierarchy": self.hierarchy.to_dict(),
            "jurisdiction_code": self.jurisdiction_code,
            "legal_id": self.legal_id,
            "note": self.note,
            "satisfies_exact_51_gate": configuration.satisfies_exact_51_gate,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "status": self.status.value,
            "text_cid": self.text_cid,
            "text_hash": self.text_hash,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StatuteIdentity":
        if not isinstance(value, Mapping):
            raise OpenUsLawSchemaError("statute identity must be a mapping")
        hierarchy = value.get("hierarchy")
        if hierarchy in (None, ""):
            hierarchy = {
                key: value.get(key)
                for key in HIERARCHY_KEYS
                if value.get(key) not in (None, "")
            }
        return cls(
            jurisdiction_code=_peek_jurisdiction_raw(value) or "",
            code_family=value.get("code_family") or value.get("codeFamily") or "",
            hierarchy=hierarchy,
            edition=value.get("edition") or "",
            source_cid=value.get("source_cid") or "",
            entry_cid=value.get("entry_cid") or "",
            text_hash=value.get("text_hash") or "",
            document_kind=value.get("document_kind")
            or value.get("kind")
            or DocumentKind.STATUTE,
            status=value.get("status") or StatuteStatus.CURRENT,
            configuration=value.get("configuration"),
            text_cid=value.get("text_cid"),
            granule=value.get("granule"),
            note=value.get("note"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ConfigurationDescriptor:
    """Release-level descriptor for one named configuration."""

    name: ReleaseConfiguration
    default: bool
    satisfies_exact_51_gate: bool
    viewer_visible: bool
    description: str
    relative_split: Optional[str] = None

    def __post_init__(self) -> None:
        name = ReleaseConfiguration.coerce(self.name)
        object.__setattr__(self, "name", name)
        if not isinstance(self.default, bool):
            raise OpenUsLawSchemaError("default must be a boolean")
        if not isinstance(self.satisfies_exact_51_gate, bool):
            raise OpenUsLawSchemaError("satisfies_exact_51_gate must be a boolean")
        if not isinstance(self.viewer_visible, bool):
            raise OpenUsLawSchemaError("viewer_visible must be a boolean")
        object.__setattr__(
            self,
            "description",
            _require_non_empty_str(self.description, "description", maximum=1024),
        )
        if name is ReleaseConfiguration.STATE_STATUTES_EXACT_51:
            if not self.default or not self.satisfies_exact_51_gate:
                raise ConfigurationBoundaryError(
                    "state_statutes_exact_51 must be the default exact-51 configuration"
                )
        else:
            if self.default:
                raise ConfigurationBoundaryError(
                    f"{name.value} must not be marked default"
                )
            if self.satisfies_exact_51_gate:
                raise Exact51GateError(
                    f"{name.value} must not satisfy the exact-51 gate"
                )
        if name in {
            ReleaseConfiguration.RECOVERY,
            ReleaseConfiguration.QUARANTINE,
        } and self.viewer_visible:
            raise ConfigurationBoundaryError(
                f"{name.value} must be excluded from Viewer-visible default surfaces"
            )
        if self.relative_split is not None:
            text = _require_non_empty_str(self.relative_split, "relative_split", maximum=256)
            if text.startswith("/") or ".." in text or "\\" in text:
                raise ArtifactPathError(
                    f"relative_split must be a confined POSIX path; got {text!r}"
                )
            object.__setattr__(self, "relative_split", text)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "default": self.default,
            "description": self.description,
            "name": self.name.value,
            "satisfies_exact_51_gate": self.satisfies_exact_51_gate,
            "viewer_visible": self.viewer_visible,
        }
        if self.relative_split is not None:
            payload["relative_split"] = self.relative_split
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConfigurationDescriptor":
        if not isinstance(value, Mapping):
            raise OpenUsLawSchemaError("configuration descriptor must be a mapping")
        name = ReleaseConfiguration.coerce(value.get("name") or value.get("configuration"))
        return cls(
            name=name,
            default=bool(value.get("default", name.is_default)),
            satisfies_exact_51_gate=bool(
                value.get("satisfies_exact_51_gate", name.satisfies_exact_51_gate)
            ),
            viewer_visible=bool(value.get("viewer_visible", name.viewer_visible)),
            description=value.get("description")
            or f"Open US Law configuration {name.value}",
            relative_split=value.get("relative_split"),
        )


def default_configuration_descriptors() -> tuple[ConfigurationDescriptor, ...]:
    default = default_configuration_policy()
    separate = non_default_configuration_policy()
    descriptors = [
        ConfigurationDescriptor(
            name=ReleaseConfiguration.STATE_STATUTES_EXACT_51,
            default=True,
            satisfies_exact_51_gate=True,
            viewer_visible=True,
            description=(
                "Current official statutes for exactly the 50 states plus DC."
            ),
            relative_split="configs/state_statutes_exact_51",
        )
    ]
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        item = separate[name]
        descriptors.append(
            ConfigurationDescriptor(
                name=ReleaseConfiguration.coerce(name),
                default=False,
                satisfies_exact_51_gate=False,
                viewer_visible=bool(item["viewer_visible"]),
                description=str(item["description"]),
                relative_split=f"configs/{name}",
            )
        )
    return tuple(descriptors)


@dataclass(frozen=True, slots=True)
class ReleaseIdentityManifest:
    """Release-level identity and configuration-boundary descriptor."""

    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    source_bucket: str = SOURCE_BUCKET
    release_profile: str = RELEASE_PROFILE
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    default_configuration: str = DEFAULT_CONFIGURATION
    jurisdictions: tuple[str, ...] = EXACT_51_JURISDICTION_CODES
    configurations: tuple[ConfigurationDescriptor, ...] = field(
        default_factory=default_configuration_descriptors
    )
    identity_fields: tuple[str, ...] = REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS
    model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    model_revision: str = DEFAULT_EMBEDDING_MODEL_REVISION
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    model_token_ceiling: int = DEFAULT_MODEL_TOKEN_CEILING
    max_rows_per_physical_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    extras_in_default_allowed: bool = False
    rows: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        repo = _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id")
        if not _DATASET_ID_RE.fullmatch(repo):
            raise OpenUsLawSchemaError(
                f"dataset_repo_id must look like org/name, got {repo!r}"
            )
        if repo != DEFAULT_DATASET_REPO_ID:
            raise OpenUsLawSchemaError(
                f"dataset_repo_id must be {DEFAULT_DATASET_REPO_ID!r}"
            )
        object.__setattr__(self, "dataset_repo_id", repo)
        bucket = _require_non_empty_str(self.source_bucket, "source_bucket")
        if bucket != SOURCE_BUCKET:
            raise OpenUsLawSchemaError(f"source_bucket must be {SOURCE_BUCKET!r}")
        object.__setattr__(self, "source_bucket", bucket)
        if self.release_profile != RELEASE_PROFILE:
            raise SchemaVersionError(
                f"release_profile must be {RELEASE_PROFILE!r}"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaVersionError(f"schema_version must be {SCHEMA_VERSION!r}")
        if self.task_id != TASK_ID:
            raise SchemaVersionError(f"task_id must be {TASK_ID!r}")
        if self.default_configuration != DEFAULT_CONFIGURATION:
            raise ConfigurationBoundaryError(
                f"default_configuration must be {DEFAULT_CONFIGURATION!r}"
            )
        if self.extras_in_default_allowed:
            raise Exact51GateError("extras_in_default_allowed must be false")
        object.__setattr__(
            self, "jurisdictions", validate_jurisdiction_set(self.jurisdictions)
        )
        descriptors = tuple(
            item
            if isinstance(item, ConfigurationDescriptor)
            else ConfigurationDescriptor.from_mapping(item)
            for item in self.configurations
        )
        present = {item.name for item in descriptors}
        required = {ReleaseConfiguration.coerce(name) for name in ALL_CONFIGURATION_NAMES}
        if present != required:
            raise ConfigurationBoundaryError(
                "release must declare every configuration exactly once; "
                f"missing={[item.value for item in sorted(required - present, key=lambda x: x.value)]} "
                f"extra={[item.value for item in sorted(present - required, key=lambda x: x.value)]}"
            )
        defaults = [item for item in descriptors if item.default]
        if len(defaults) != 1 or defaults[0].name is not ReleaseConfiguration.STATE_STATUTES_EXACT_51:
            raise ConfigurationBoundaryError(
                "exactly one default configuration is allowed: state_statutes_exact_51"
            )
        for item in descriptors:
            if item.name is not ReleaseConfiguration.STATE_STATUTES_EXACT_51:
                if item.satisfies_exact_51_gate:
                    raise Exact51GateError(
                        f"{item.name.value} must not satisfy the exact-51 gate"
                    )
        object.__setattr__(self, "configurations", descriptors)
        fields = tuple(self.identity_fields)
        if tuple(fields) != REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS:
            raise MissingIdentityFieldError(
                "identity_fields must be exactly "
                f"{list(REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS)}"
            )
        object.__setattr__(self, "identity_fields", fields)
        if self.model_id != DEFAULT_EMBEDDING_MODEL_ID:
            raise OpenUsLawSchemaError(
                f"model_id must be {DEFAULT_EMBEDDING_MODEL_ID!r}"
            )
        object.__setattr__(
            self,
            "model_revision",
            require_immutable_revision(self.model_revision, name="model_revision"),
        )
        if self.model_revision != DEFAULT_EMBEDDING_MODEL_REVISION:
            raise OpenUsLawSchemaError(
                "model_revision must be the pinned thenlper/gte-small revision"
            )
        if self.embedding_dimension != DEFAULT_EMBEDDING_DIMENSION:
            raise OpenUsLawSchemaError(
                f"embedding_dimension must be {DEFAULT_EMBEDDING_DIMENSION}"
            )
        if self.model_token_ceiling != DEFAULT_MODEL_TOKEN_CEILING:
            raise OpenUsLawSchemaError(
                f"model_token_ceiling must be {DEFAULT_MODEL_TOKEN_CEILING}"
            )
        if self.max_rows_per_physical_shard != MAX_ROWS_PER_PHYSICAL_SHARD:
            raise OpenUsLawSchemaError(
                f"max_rows_per_physical_shard must be {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        validated_rows = tuple(
            validate_corpus_identity(row) for row in (self.rows or ())
        )
        object.__setattr__(self, "rows", validated_rows)
        if validated_rows:
            validate_exact_51_gate(validated_rows, require_full_coverage=False)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "configurations": [item.to_dict() for item in self.configurations],
            "dataset_repo_id": self.dataset_repo_id,
            "default_configuration": self.default_configuration,
            "embedding_dimension": self.embedding_dimension,
            "extras_in_default_allowed": self.extras_in_default_allowed,
            "identity_fields": list(self.identity_fields),
            "jurisdictions": {
                "extras_in_default_allowed": False,
                "required_codes": list(self.jurisdictions),
                "required_count": EXPECTED_JURISDICTION_COUNT,
            },
            "max_rows_per_physical_shard": self.max_rows_per_physical_shard,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "model_token_ceiling": self.model_token_ceiling,
            "release_profile": self.release_profile,
            "schema_version": self.schema_version,
            "source_bucket": self.source_bucket,
            "task_id": self.task_id,
            "viewer": {
                "default_split": DEFAULT_CONFIGURATION,
                "excluded_from_default": list(NON_DEFAULT_CONFIGURATION_NAMES),
                "hidden_configurations": [
                    ReleaseConfiguration.RECOVERY.value,
                    ReleaseConfiguration.QUARANTINE.value,
                ],
            },
        }
        if self.rows:
            payload["rows"] = [dict(row) for row in self.rows]
        payload["manifest_digest"] = digest_mapping(
            {key: value for key, value in payload.items() if key != "manifest_digest"}
        )
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReleaseIdentityManifest":
        if not isinstance(value, Mapping):
            raise OpenUsLawSchemaError("release manifest must be a mapping")
        jurisdictions = value.get("jurisdictions")
        if isinstance(jurisdictions, Mapping):
            codes = jurisdictions.get("required_codes") or jurisdictions.get("codes")
        else:
            codes = jurisdictions
        configurations = value.get("configurations")
        if isinstance(configurations, Mapping):
            descriptors = []
            for name, item in configurations.items():
                if isinstance(item, Mapping):
                    payload = dict(item)
                    payload.setdefault("name", name)
                    descriptors.append(payload)
                else:
                    descriptors.append({"name": name})
        else:
            descriptors = configurations or default_configuration_descriptors()
        identity_fields = value.get("identity_fields")
        if isinstance(identity_fields, Mapping):
            identity_fields = identity_fields.get("required_for_default_statutes")
        return cls(
            dataset_repo_id=value.get("dataset_repo_id", DEFAULT_DATASET_REPO_ID),
            source_bucket=value.get("source_bucket", SOURCE_BUCKET),
            release_profile=value.get("release_profile", RELEASE_PROFILE),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            task_id=value.get("task_id", TASK_ID),
            default_configuration=value.get(
                "default_configuration", DEFAULT_CONFIGURATION
            ),
            jurisdictions=tuple(codes or EXACT_51_JURISDICTION_CODES),
            configurations=tuple(descriptors),
            identity_fields=tuple(
                identity_fields or REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS
            ),
            model_id=value.get("model_id", DEFAULT_EMBEDDING_MODEL_ID),
            model_revision=value.get(
                "model_revision", DEFAULT_EMBEDDING_MODEL_REVISION
            ),
            embedding_dimension=value.get(
                "embedding_dimension", DEFAULT_EMBEDDING_DIMENSION
            ),
            model_token_ceiling=value.get(
                "model_token_ceiling", DEFAULT_MODEL_TOKEN_CEILING
            ),
            max_rows_per_physical_shard=value.get(
                "max_rows_per_physical_shard", MAX_ROWS_PER_PHYSICAL_SHARD
            ),
            extras_in_default_allowed=bool(
                value.get("extras_in_default_allowed", False)
            ),
            rows=tuple(value.get("rows") or ()),
        )


def validate_release_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    record = ReleaseIdentityManifest.from_mapping(payload)
    encoded = record.to_dict()
    schema_errors = validate_against_release_schema(encoded)
    if schema_errors:
        raise OpenUsLawSchemaError(
            f"release manifest failed JSON Schema validation: {schema_errors[0]}"
        )
    return encoded


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------


def release_schema_path() -> Path:
    return RELEASE_SCHEMA_PATH


@lru_cache(maxsize=1)
def load_release_schema() -> dict[str, Any]:
    path = release_schema_path()
    if not path.is_file():
        raise OpenUsLawSchemaError(f"missing release schema at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OpenUsLawSchemaError("release schema must be a JSON object")
    return payload


def validate_against_release_schema(payload: Mapping[str, Any]) -> list[str]:
    """Return JSON Schema error strings; empty list means structurally valid."""

    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - validation env pins jsonschema
        raise OpenUsLawSchemaError(
            "jsonschema is required to validate release.schema.json"
        ) from exc

    validator = Draft202012Validator(load_release_schema())
    return [
        f"{list(error.absolute_path)}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


# ---------------------------------------------------------------------------
# Example payloads
# ---------------------------------------------------------------------------


def _example_cids(label: str) -> dict[str, str]:
    text = f"example-text:{label}"
    return {
        "entry_cid": content_sha256(f"example-entry:{label}"),
        "source_cid": content_sha256(f"example-source:{label}"),
        "text_hash": compute_text_hash(text),
        "text": text,
    }


def example_default_statute_payload(
    *,
    jurisdiction_code: str = "OR",
    section: str = "456",
    title: str = "123",
) -> dict[str, Any]:
    cids = _example_cids(f"{jurisdiction_code}:{title}:{section}")
    hierarchy = {"title": title, "chapter": None, "section": section, "subsection": None}
    payload = {
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": "ors" if jurisdiction_code == "OR" else "statutes",
        "configuration": DEFAULT_CONFIGURATION,
        "document_kind": DocumentKind.STATUTE.value,
        "edition": "2024-official",
        "hierarchy": hierarchy,
        "jurisdiction_code": jurisdiction_code,
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }
    payload["legal_id"] = build_legal_id(
        document_kind=DocumentKind.STATUTE,
        jurisdiction_code=jurisdiction_code,
        code_family=payload["code_family"],
        hierarchy=hierarchy,
        edition=payload["edition"],
    )
    return payload


def example_federal_payload() -> dict[str, Any]:
    cids = _example_cids("US:usc:18:1001")
    hierarchy = {"title": "18", "section": "1001"}
    return {
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": "usc",
        "configuration": ReleaseConfiguration.FEDERAL_USCODE.value,
        "document_kind": DocumentKind.FEDERAL.value,
        "edition": "2024-usc",
        "hierarchy": hierarchy,
        "jurisdiction_code": FEDERAL_JURISDICTION_CODE,
        "legal_id": build_legal_id(
            document_kind=DocumentKind.FEDERAL,
            jurisdiction_code=FEDERAL_JURISDICTION_CODE,
            code_family="usc",
            hierarchy=hierarchy,
            edition="2024-usc",
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }


def example_puerto_rico_payload() -> dict[str, Any]:
    cids = _example_cids("PR:lpr:1:1")
    hierarchy = {"title": "1", "section": "1"}
    return {
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": "laws-of-puerto-rico",
        "configuration": ReleaseConfiguration.PUERTO_RICO.value,
        "document_kind": DocumentKind.PUERTO_RICO.value,
        "edition": "2024-official",
        "hierarchy": hierarchy,
        "jurisdiction_code": PUERTO_RICO_CODE,
        "legal_id": build_legal_id(
            document_kind=DocumentKind.PUERTO_RICO,
            jurisdiction_code=PUERTO_RICO_CODE,
            code_family="laws-of-puerto-rico",
            hierarchy=hierarchy,
            edition="2024-official",
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }


def example_constitution_payload(*, jurisdiction_code: str = "US") -> dict[str, Any]:
    code = normalize_jurisdiction_code(jurisdiction_code, allow_non_default=True)
    family = "us-constitution" if code == "US" else f"{code.lower()}-constitution"
    cids = _example_cids(f"{code}:{family}:art1:s8")
    hierarchy = {"article": "1", "section": "8"}
    return {
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": family,
        "configuration": ReleaseConfiguration.CONSTITUTIONS.value,
        "document_kind": DocumentKind.CONSTITUTION.value,
        "edition": "2024-official",
        "hierarchy": hierarchy,
        "jurisdiction_code": code,
        "legal_id": build_legal_id(
            document_kind=DocumentKind.CONSTITUTION,
            jurisdiction_code=code,
            code_family=family,
            hierarchy=hierarchy,
            edition="2024-official",
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }


def example_historical_payload(*, jurisdiction_code: str = "OR") -> dict[str, Any]:
    cids = _example_cids(f"{jurisdiction_code}:hist:10:1")
    hierarchy = {"title": "10", "section": "1"}
    return {
        "admission_status": AdmissionStatus.ADMITTED.value,
        "code_family": "statutes",
        "configuration": ReleaseConfiguration.HISTORICAL.value,
        "document_kind": DocumentKind.STATUTE.value,
        "edition": "1999-official",
        "hierarchy": hierarchy,
        "jurisdiction_code": jurisdiction_code,
        "legal_id": build_legal_id(
            document_kind=DocumentKind.STATUTE,
            jurisdiction_code=jurisdiction_code,
            code_family="statutes",
            hierarchy=hierarchy,
            edition="1999-official",
            status=StatuteStatus.HISTORICAL,
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.HISTORICAL.value,
        **cids,
    }


def example_recovery_payload() -> dict[str, Any]:
    cids = _example_cids("recovery:OR:legacy")
    hierarchy = {"title": "1", "section": "1"}
    return {
        "admission_status": AdmissionStatus.RECOVERY.value,
        "code_family": "ors",
        "configuration": ReleaseConfiguration.RECOVERY.value,
        "document_kind": DocumentKind.STATUTE.value,
        "edition": "legacy-seed",
        "hierarchy": hierarchy,
        "jurisdiction_code": "OR",
        "legal_id": build_legal_id(
            document_kind=DocumentKind.STATUTE,
            jurisdiction_code="OR",
            code_family="ors",
            hierarchy=hierarchy,
            edition="legacy-seed",
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }


def example_quarantine_payload() -> dict[str, Any]:
    cids = _example_cids("quarantine:GA:contaminated")
    hierarchy = {"title": "1", "section": "1"}
    return {
        "admission_status": AdmissionStatus.QUARANTINED.value,
        "code_family": "official-code-of-georgia",
        "configuration": ReleaseConfiguration.QUARANTINE.value,
        "document_kind": DocumentKind.STATUTE.value,
        "edition": "2026-withdrawn",
        "hierarchy": hierarchy,
        "jurisdiction_code": "GA",
        "legal_id": build_legal_id(
            document_kind=DocumentKind.STATUTE,
            jurisdiction_code="GA",
            code_family="official-code-of-georgia",
            hierarchy=hierarchy,
            edition="2026-withdrawn",
        ),
        "schema_version": SCHEMA_VERSION,
        "status": StatuteStatus.CURRENT.value,
        **cids,
    }


def example_release_manifest(
    *,
    include_example_rows: bool = False,
    include_all_default_jurisdictions: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if include_all_default_jurisdictions:
        for code in EXACT_51_JURISDICTION_CODES:
            rows.append(
                example_default_statute_payload(
                    jurisdiction_code=code,
                    title="1",
                    section="1",
                )
            )
    if include_example_rows:
        rows.extend(
            [
                example_default_statute_payload(),
                example_federal_payload(),
                example_puerto_rico_payload(),
                example_constitution_payload(),
                example_historical_payload(),
                example_recovery_payload(),
                example_quarantine_payload(),
            ]
        )
    manifest = ReleaseIdentityManifest(rows=tuple(rows) if rows else ())
    return manifest.to_dict()


def example_mixed_rows() -> list[dict[str, Any]]:
    return [
        example_default_statute_payload(),
        example_federal_payload(),
        example_puerto_rico_payload(),
        example_constitution_payload(jurisdiction_code="OR"),
        example_historical_payload(),
        example_recovery_payload(),
        example_quarantine_payload(),
    ]


__all__ = [
    "ADR_PATH",
    "ALL_CONFIGURATION_NAMES",
    "AdmissionStatus",
    "ArtifactPathError",
    "ConfigurationBoundaryError",
    "ConfigurationDescriptor",
    "DEFAULT_CONFIGURATION",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL_ID",
    "DEFAULT_EMBEDDING_MODEL_REVISION",
    "DEFAULT_MODEL_TOKEN_CEILING",
    "DocumentKind",
    "EXACT_51_JURISDICTIONS",
    "EXACT_51_JURISDICTION_CODES",
    "EXPECTED_JURISDICTION_COUNT",
    "Exact51GateError",
    "FEDERAL_JURISDICTION_CODE",
    "Hierarchy",
    "ISOLATION_CONFIGURATIONS",
    "InvalidDigestError",
    "JURISDICTION_NAMES",
    "KNOWN_NON_DEFAULT_JURISDICTIONS",
    "LEGAL_ID_PREFIX",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_POSTING_POINTERS_PER_ROW",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "MissingIdentityFieldError",
    "MutableReferenceError",
    "NON_DEFAULT_CONFIGURATIONS",
    "NON_DEFAULT_CONFIGURATION_NAMES",
    "OpenUsLawSchemaError",
    "PUERTO_RICO_CODE",
    "PositionalIdentityError",
    "RELEASE_PROFILE",
    "RELEASE_SCHEMA_PATH",
    "RELEASE_SCHEMA_RELATIVE_PATH",
    "REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS",
    "REQUIRED_SERIALIZED_IDENTITY_FIELDS",
    "ReleaseConfiguration",
    "ReleaseIdentityManifest",
    "SCHEMA_VERSION",
    "SOURCE_BUCKET",
    "SchemaVersionError",
    "SourceAuthorityClass",
    "StatuteIdentity",
    "StatuteStatus",
    "TASK_ID",
    "VerificationResult",
    "build_legal_id",
    "canonical_json_dumps",
    "classify_configuration",
    "compute_text_hash",
    "configuration_boundary_policy",
    "configuration_satisfies_exact_51",
    "content_sha256",
    "default_configuration_descriptors",
    "default_configuration_policy",
    "digest_mapping",
    "example_constitution_payload",
    "example_default_statute_payload",
    "example_federal_payload",
    "example_historical_payload",
    "example_mixed_rows",
    "example_puerto_rico_payload",
    "example_quarantine_payload",
    "example_recovery_payload",
    "example_release_manifest",
    "infer_configuration",
    "is_immutable_revision",
    "load_release_schema",
    "non_default_configuration_policy",
    "normalize_code_family",
    "normalize_dash_chars",
    "normalize_edition",
    "normalize_hierarchy",
    "normalize_jurisdiction_code",
    "normalize_section_token",
    "normalize_sha256",
    "parse_legal_id",
    "partition_by_configuration",
    "physical_bounds_policy",
    "reject_positional_durable_identity",
    "release_schema_path",
    "require_immutable_revision",
    "validate_against_release_schema",
    "validate_corpus_identity",
    "validate_default_statute_identity",
    "validate_digest",
    "validate_document_index",
    "validate_entry_cid",
    "validate_exact_51_gate",
    "validate_exact_51_jurisdiction",
    "validate_jurisdiction_set",
    "validate_legal_id",
    "validate_non_default_identity",
    "validate_release_manifest",
    "validate_source_cid",
    "validate_text_hash",
]
