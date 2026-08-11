"""Canonical Federal Register document identity and provenance (LCR-054).

This module owns the file-disjoint identity parser/normalizer used by the
``federal-register-ir-graphrag/v2`` release. It deliberately does **not**
depend on network I/O, Parquet, or acquisition entry points.

Design invariants
-----------------
* ``legal_id`` is a stable publication identity of the form
  ``fr:<document_number>:<publication_date>[:qualifier…]``, independent of
  content version (``entry_cid``) and release-local row index.
* ``entry_cid`` is the retrieval primary key; duplicate primary keys fail closed.
* ``source_cid`` addresses normalized official-source evidence (provenance).
* Distinct legal versions (corrections, withdrawals, republications on a
  different date, different document numbers) **never** collapse.
* Exact logical duplicates and duplicate source formats (html/pdf/xml of the
  same publication) reconcile with **order-independent, deterministic**
  dispositions so identity is stable across ordering and resume.
* Positional tokens (``row-N``, ``document_index``) and content CID alone are
  never durable merge keys.
* Unknown effective dates are preserved and never invented or used as the sole
  merge key.
* Identity construction rehashes supplied evidence but never authorizes corpus
  admission; the LCR-085 full-text gate owns official-body authorization.

The sealed collision fixture expands from a compact recipe that exercises
correction pairs, source-format duplicates, changed-text versions, publication-
date variants, content-CID-only and positional non-merges, and unknown
effective dates.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.ir_core.identity import cid_v1
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    AdmissionStatus,
    CorrectionRelation,
    DocumentType,
    SourceAuthorityClass,
    TextAvailability,
    VerificationResult,
    normalize_sha256,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_digest as schema_validate_digest,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_document_index as schema_validate_document_index,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_entry_cid as schema_validate_entry_cid,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_legal_id as schema_validate_legal_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_official_url as schema_validate_official_url,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_publication_date as schema_validate_publication_date,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    validate_year_month as schema_validate_year_month,
)

SCHEMA_VERSION = "federal-register-identity-v1"
FIXTURE_SCHEMA_VERSION = "federal-register-identity-collisions-v1"
TASK_ID = "LCR-054"

# Exact expanded row count of the sealed collision fixture.
KNOWN_COLLISION_ROW_COUNT = 370

LEGAL_ID_PREFIX = "fr"
DEFAULT_DOCUMENT_TYPE = DocumentType.NOTICE.value
DEFAULT_CORRECTION_RELATION = CorrectionRelation.NONE.value
DEFAULT_SOURCE_FORMAT = "html"

# Preferred source format when reconciling exact publication duplicates.
_SOURCE_FORMAT_PRIORITY: dict[str, int] = {
    "html": 0,
    "xml": 1,
    "pdf": 2,
    "govinfo": 3,
    "json": 4,
    "txt": 5,
    "unknown": 99,
}

# Keep this trust-boundary grammar byte-for-byte aligned with the accepted
# LCR-049/LCR-050 ADR.  Historical two-character series have short tails;
# modern/revision forms deliberately do not.  Revision prefixes are exactly
# one digit, including zero, and all alphabetic bytes are uppercase.
_HISTORICAL_DOCUMENT_SERIES_PATTERN = (
    r"(?:0[0-9]|20|9[2-9]|C[0-9]|E[13-9]|R[0-9]|X[019]|Z[4-9])"
)
_DOCUMENT_NUMBER_PATTERN = (
    rf"(?:[CR][0-9]-[0-9]{{4}}-[0-9]{{4,6}}|"
    rf"[0-9]{{4}}-[0-9]{{4,6}}|"
    rf"{_HISTORICAL_DOCUMENT_SERIES_PATTERN}-[0-9]{{1,6}})"
)
_DOCUMENT_NUMBER_RE = re.compile(rf"^{_DOCUMENT_NUMBER_PATTERN}$")
_PUBLICATION_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_YEAR_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_CHUNK_SUFFIX_RE = re.compile(r"#chunk=(?P<index>\d+)$")
_POSITIONAL_ID_RE = re.compile(
    r"^(?:row[-_ ]?\d+|row[-_ ]?N|document[-_ ]?index[-_ ]?\d+|idx[-_ ]?\d+|"
    r"pos[-_ ]?\d+|offset[-_ ]?\d+)$",
    re.IGNORECASE,
)
_QUALIFIER_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Qualifier keys that participate in legal_id construction (sorted).
_QUALIFIER_KEYS = (
    "edition",
    "granule",
    "part",
    "related",
    "rel",
    "type",
)

# Entry identity binds the complete canonical row.  Observation/acquisition
# clocks remain excluded only from representative-version ranking; if returned,
# their bytes still participate in ``entry_cid``.
PathLike = str | Path
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterIdentityError(ValueError):
    """Base error for Federal Register identity failures."""


class IdentityParseError(FederalRegisterIdentityError):
    """Raised when a document number, date, or legal_id cannot be parsed fully."""


class DuplicatePrimaryKeyError(FederalRegisterIdentityError):
    """Raised when duplicate primary keys (``entry_cid``) are detected."""


class CollisionFixtureError(FederalRegisterIdentityError):
    """Raised when the sealed collision fixture is malformed."""


class IdentityDispositionError(FederalRegisterIdentityError):
    """Raised when a merge or disposition cannot be resolved deterministically."""


class PositionalIdentityError(FederalRegisterIdentityError):
    """Raised when durable identity is positional (``row-N``, index, etc.)."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceFormat(str, Enum):
    """Official body / packaging format for source evidence."""

    HTML = "html"
    XML = "xml"
    PDF = "pdf"
    GOVINFO = "govinfo"
    JSON = "json"
    TXT = "txt"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> SourceFormat:
        if value is None or value == "":
            return cls.HTML
        if isinstance(value, SourceFormat):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "htm": cls.HTML,
            "text/html": cls.HTML,
            "application/xml": cls.XML,
            "text/xml": cls.XML,
            "application/pdf": cls.PDF,
            "govinfo_pdf": cls.GOVINFO,
            "govinfo_xml": cls.GOVINFO,
            "application/json": cls.JSON,
            "text": cls.TXT,
            "text/plain": cls.TXT,
            "full_text": cls.HTML,
            "html_body": cls.HTML,
            "xml_body": cls.XML,
            "pdf_body": cls.PDF,
            "govinfo_body": cls.GOVINFO,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        return cls.UNKNOWN


class IdentityDisposition(str, Enum):
    """Deterministic disposition for a logical-identity comparison or merge.

    These are explicit outcomes — never inferred from row position or content
    CID alone.
    """

    UNIQUE = "unique"
    DUPLICATE = "duplicate"
    DUPLICATE_SOURCE_FORMAT = "duplicate_source_format"
    CHANGED_TEXT_VERSION = "changed_text_version"
    DISTINCT_IDENTITY = "distinct_identity"
    CORRECTION_DISTINCT = "correction_distinct"
    REJECT_POSITIONAL_MERGE = "reject_positional_merge"
    REJECT_CONTENT_CID_ONLY_MERGE = "reject_content_cid_only_merge"
    KEEP_CURRENT = "keep_current"
    ARCHIVE_HISTORY = "archive_history"
    PRESERVE_UNKNOWN_EFFECTIVE_DATE = "preserve_unknown_effective_date"

    @classmethod
    def coerce(cls, value: Any) -> IdentityDisposition:
        if isinstance(value, IdentityDisposition):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dup": cls.DUPLICATE,
            "duplicate_logical": cls.DUPLICATE,
            "source_format": cls.DUPLICATE_SOURCE_FORMAT,
            "format_duplicate": cls.DUPLICATE_SOURCE_FORMAT,
            "changed_text": cls.CHANGED_TEXT_VERSION,
            "version": cls.CHANGED_TEXT_VERSION,
            "history": cls.ARCHIVE_HISTORY,
            "current": cls.KEEP_CURRENT,
            "positional": cls.REJECT_POSITIONAL_MERGE,
            "content_cid_only": cls.REJECT_CONTENT_CID_ONLY_MERGE,
            "cid_only": cls.REJECT_CONTENT_CID_ONLY_MERGE,
            "distinct": cls.DISTINCT_IDENTITY,
            "correction": cls.CORRECTION_DISTINCT,
            "unknown_effective_date": cls.PRESERVE_UNKNOWN_EFFECTIVE_DATE,
            "unknown_date": cls.PRESERVE_UNKNOWN_EFFECTIVE_DATE,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise IdentityDispositionError(f"unknown identity disposition: {value!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(
    value: Any,
    name: str,
    *,
    maximum: int | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterIdentityError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterIdentityError(f"{name} must not contain NUL")
    text = value.strip()
    if maximum is not None and len(text) > maximum:
        raise FederalRegisterIdentityError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _stable_hex(material: str, *, salt: str = "") -> str:
    payload = f"{salt}:{material}" if salt else material
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    """Return a deterministic JSON-safe projection used only for hashing.

    Corpus rows are JSON records, but fixture and caller probes may carry byte
    evidence.  Bytes are represented losslessly as lowercase hex instead of
    being coerced with ``str(bytes)`` (which is not a canonical byte binding).
    """

    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$bytes_hex": bytes(value).hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    raise FederalRegisterIdentityError(
        f"identity material contains unsupported value {type(value).__name__}"
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_cid(*, domain: str, payload: Mapping[str, Any]) -> str:
    """Return a real raw/sha2-256 CIDv1 for a domain-separated payload."""

    return cid_v1(
        _canonical_json_bytes(
            {
                "domain": domain,
                "identity_schema_version": SCHEMA_VERSION,
                "payload": payload,
            }
        )
    )


def _evidence_bytes(
    value: Any,
    *,
    name: str,
    allow_empty: bool = False,
) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value == "":
            return b"" if allow_empty else None
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return raw if raw or allow_empty else None
    raise FederalRegisterIdentityError(f"{name} must be text or bytes")


def _content_digest_tokens(data: bytes) -> tuple[str, str, str]:
    digest = hashlib.sha256(data).hexdigest()
    return digest, f"sha256:{digest}", cid_v1(data)


def _require_declared_digest_matches_bytes(
    value: Any,
    data: bytes,
    *,
    name: str,
) -> str:
    """Validate *value* and prove it addresses exactly *data*."""

    declared = schema_validate_digest(value, name=name)
    digest, labelled, content_cid = _content_digest_tokens(data)
    if declared not in {digest, labelled, content_cid}:
        raise FederalRegisterIdentityError(
            f"{name} does not match the independently recomputed content digest"
        )
    return declared


def normalize_document_number(value: Any) -> str:
    """Normalize an official Federal Register document number.

    Besides ``YYYY-NNNNN``, the official API emits correction/replacement
    numbers ``C<n>-YYYY-NNNNN`` and ``R<n>-YYYY-NNNNN``.  Those prefixes are
    durable identity and are never stripped or moved into a qualifier.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        raise IdentityParseError(
            "document_number must be a non-empty exact canonical string"
        )
    text = value
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"document_number must not be positional: {value!r}"
        )
    if not _DOCUMENT_NUMBER_RE.fullmatch(text):
        raise IdentityParseError(
            "document_number must be an exact canonical modern, historical, "
            f"or revision Federal Register number; got {value!r}"
        )
    parts = text.split("-")
    if len(parts) == 2 and len(parts[0]) == 4 and parts[0].isdigit():
        year = int(parts[0])
        if year < 1936 or year > 2100:
            raise IdentityParseError(f"document_number year out of range: {value!r}")
    elif len(parts) == 3:
        year = int(parts[1])
        if year < 1936 or year > 2100:
            raise IdentityParseError(f"document_number year out of range: {value!r}")
    return text


def _validate_legal_id_shape(value: Any) -> str:
    """Validate the local legal-ID shape, including official Cn-/Rn- IDs."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise IdentityParseError(
            "legal_id must be a non-empty string in exact canonical form"
        )
    parts = value.split(":")
    if len(parts) < 3 or parts[0] != LEGAL_ID_PREFIX:
        raise IdentityParseError(
            "legal_id must match fr:<document_number>:<publication_date>"
            f"[:qualifier...]; got {value!r}"
        )
    if normalize_document_number(parts[1]) != parts[1]:
        raise IdentityParseError("legal_id document number is not canonical")
    if normalize_publication_date(parts[2]) != parts[2]:
        raise IdentityParseError("legal_id publication date is not canonical")
    for segment in parts[3:]:
        if not segment or not re.fullmatch(r"[a-z0-9][A-Za-z0-9._=-]{0,127}", segment):
            raise IdentityParseError(
                f"legal_id qualifier segment is not canonical: {segment!r}"
            )
    return value


def normalize_publication_date(value: Any) -> str:
    """Normalize an official publication calendar date (``YYYY-MM-DD``)."""

    text = _require_non_empty_str(value, "publication_date")
    text = text.replace("/", "-").replace(".", "-")
    # Accept bare YYYYMMDD.
    if re.fullmatch(r"[0-9]{8}", text):
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        normalized = schema_validate_publication_date(text)
        # LCR-050's shape validator is intentionally lightweight.  Identity
        # normalization must additionally reject impossible calendar dates.
        date.fromisoformat(normalized)
        return normalized
    except Exception as exc:
        raise IdentityParseError(str(exc)) from exc


def normalize_year_month(value: Any, *, publication_date: str | None = None) -> str:
    """Normalize a partition key ``YYYY-MM`` (derived from publication date)."""

    if value is None or value == "":
        if publication_date is None or publication_date == "":
            raise IdentityParseError("year_month or publication_date required")
        pub = normalize_publication_date(publication_date)
        return pub[:7]
    text = _require_non_empty_str(value, "year_month")
    text = text.replace("/", "-")
    if re.fullmatch(r"[0-9]{6}", text):
        text = f"{text[0:4]}-{text[4:6]}"
    try:
        normalized = schema_validate_year_month(text)
        if publication_date not in (None, ""):
            expected = normalize_publication_date(publication_date)[:7]
            if normalized != expected:
                raise IdentityParseError(
                    f"year_month {normalized!r} does not match publication_date "
                    f"partition {expected!r}"
                )
        return normalized
    except Exception as exc:
        if isinstance(exc, IdentityParseError):
            raise
        raise IdentityParseError(str(exc)) from exc


def normalize_effective_date(value: Any) -> str | None:
    """Normalize an effective date, preserving unknown / missing values.

    Unknown tokens (``unknown``, ``n/a``, ``tbd``, empty) return ``None`` and
    are never invented from publication date.
    """

    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    text = str(value).strip().lower()
    if text in {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "tbd",
        "pending",
        "not_available",
        "not-available",
        "unavailable",
        "?",
    }:
        return None
    # Re-use publication date validation for well-formed calendar dates.
    return normalize_publication_date(value)


def normalize_source_format(value: Any) -> str:
    """Normalize a source-format label for non-authorizing display/ranking.

    Identity-producing paths use :func:`_require_canonical_source_format`
    instead: a convenience alias must never silently select provenance.
    """

    return SourceFormat.coerce(value).value


def _require_canonical_source_format(value: Any) -> str:
    """Require one explicit, exact source-format token for provenance."""

    if not isinstance(value, str) or not value:
        raise FederalRegisterIdentityError(
            "source_format must be an explicit supported string"
        )
    if value != value.strip().lower():
        raise FederalRegisterIdentityError(
            f"source_format must be an exact supported token, got {value!r}"
        )
    if value not in _SOURCE_FORMAT_PRIORITY or value == SourceFormat.UNKNOWN.value:
        raise FederalRegisterIdentityError(
            f"source_format must be an exact supported token, got {value!r}"
        )
    return value


def normalize_document_type(value: Any) -> str:
    """Normalize a Federal Register document type."""

    if value is None or value == "":
        raise IdentityParseError("document_type is required for legal identity")
    try:
        return DocumentType.coerce(value).value
    except Exception as exc:
        raise IdentityParseError(str(exc)) from exc


def normalize_correction_relation(value: Any) -> str:
    """Normalize a correction / withdrawal relation token."""

    if value is None or value == "":
        return DEFAULT_CORRECTION_RELATION
    try:
        return CorrectionRelation.coerce(value).value
    except Exception as exc:
        raise IdentityParseError(str(exc)) from exc


def _normalize_qualifier_value(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    raw = _require_non_empty_str(value, name)
    if not isinstance(value, str) or value != value.strip():
        raise IdentityParseError(f"{name} must have no surrounding whitespace")
    text = raw.lower()
    if not text or not _QUALIFIER_TOKEN_RE.fullmatch(text):
        raise IdentityParseError(
            f"{name} must match [a-z0-9][a-z0-9._-]{{0,63}}; got {value!r}"
        )
    return text


def _format_qualifiers(components: Mapping[str, str | None]) -> str:
    parts: list[str] = []
    for key in _QUALIFIER_KEYS:
        value = components.get(key)
        if value is None or value == "":
            continue
        if key == "rel" and value == DEFAULT_CORRECTION_RELATION:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return ""
    return ":" + ":".join(parts)


def source_format_priority(source_format: Any) -> int:
    """Return lower-is-better priority for source-format reconciliation."""

    fmt = normalize_source_format(source_format)
    return _SOURCE_FORMAT_PRIORITY.get(fmt, 50)


# ---------------------------------------------------------------------------
# Legal identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalIdentity:
    """Canonical publication identity for one Federal Register document.

    ``legal_id`` is publication-oriented and independent of content version.
    ``entry_cid`` / ``source_cid`` (when present on a row) are intentionally
    **not** part of this record.
    """

    document_number: str
    publication_date: str
    document_type: str
    correction_relation: str = DEFAULT_CORRECTION_RELATION
    related_document_number: str | None = None
    year_month: str | None = field(default=None, compare=False, hash=False)
    effective_date: str | None = field(default=None, compare=False, hash=False)
    edition: str | None = None
    granule: str | None = None
    part: str | None = None
    source_document_number: str | None = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_number", normalize_document_number(self.document_number)
        )
        object.__setattr__(
            self, "publication_date", normalize_publication_date(self.publication_date)
        )
        object.__setattr__(
            self, "document_type", normalize_document_type(self.document_type)
        )
        object.__setattr__(
            self,
            "correction_relation",
            normalize_correction_relation(self.correction_relation),
        )
        related = self.related_document_number
        if related is not None and related != "":
            object.__setattr__(
                self, "related_document_number", normalize_document_number(related)
            )
        else:
            object.__setattr__(self, "related_document_number", None)
        object.__setattr__(
            self,
            "year_month",
            normalize_year_month(
                self.year_month, publication_date=self.publication_date
            ),
        )
        object.__setattr__(
            self, "effective_date", normalize_effective_date(self.effective_date)
        )
        object.__setattr__(
            self, "edition", _normalize_qualifier_value(self.edition, "edition")
        )
        object.__setattr__(
            self, "granule", _normalize_qualifier_value(self.granule, "granule")
        )
        object.__setattr__(self, "part", _normalize_qualifier_value(self.part, "part"))

        # Correction identity rules (fail-closed).
        relation = CorrectionRelation.coerce(self.correction_relation)
        doc_type = DocumentType.coerce(self.document_type)
        if doc_type is DocumentType.CORRECTION and relation is CorrectionRelation.NONE:
            raise IdentityParseError(
                "document_type=correction requires a non-none correction_relation"
            )
        if relation is CorrectionRelation.NONE:
            if self.related_document_number is not None:
                raise IdentityParseError(
                    "related_document_number requires a non-none correction_relation"
                )
        else:
            if self.related_document_number is None:
                raise IdentityParseError(
                    f"correction_relation={relation.value!r} requires "
                    f"related_document_number"
                )
        if self.source_document_number is not None:
            object.__setattr__(
                self, "source_document_number", str(self.source_document_number)
            )

    @property
    def legal_id(self) -> str:
        """Return the stable publication-oriented legal identifier."""

        base = f"{LEGAL_ID_PREFIX}:{self.document_number}:{self.publication_date}"
        qualifiers: dict[str, str | None] = {
            "edition": self.edition,
            "granule": self.granule,
            "part": self.part,
            "related": None,
            "rel": None,
            "type": None,
        }
        # Document type is publication identity for every document.  It is
        # never optional presentation and no caller flag can suppress it.
        qualifiers["type"] = self.document_type
        # Correction, withdrawal, and supersession semantics are identity, not
        # optional presentation.  Every real relation and its exact target are
        # emitted; the default ``none`` relation is the only omitted token.
        if self.correction_relation != DEFAULT_CORRECTION_RELATION:
            qualifiers["rel"] = self.correction_relation
            if self.related_document_number:
                qualifiers["related"] = self.related_document_number
        return base + _format_qualifiers(qualifiers)

    @property
    def canonical_citation(self) -> str:
        """Return a compact human-readable Federal Register citation."""

        parts = [f"{self.document_number}", f"({self.publication_date})"]
        if self.document_type and self.document_type != DEFAULT_DOCUMENT_TYPE:
            parts.append(self.document_type.replace("_", " "))
        if self.correction_relation != DEFAULT_CORRECTION_RELATION:
            related = self.related_document_number or "?"
            parts.append(f"{self.correction_relation} {related}")
        if self.effective_date is not None:
            parts.append(f"eff. {self.effective_date}")
        return " ".join(parts)

    @property
    def parent_legal_id(self) -> str:
        """Return the deterministic chunk-parent identity (publication root)."""

        # Chunks always parent to the bare publication identity without part
        # qualifiers so multi-part bodies share one parent.
        if self.part is None and self.granule is None:
            return self.legal_id
        parent = LegalIdentity(
            document_number=self.document_number,
            publication_date=self.publication_date,
            document_type=self.document_type,
            correction_relation=self.correction_relation,
            related_document_number=self.related_document_number,
            year_month=self.year_month,
            effective_date=self.effective_date,
            edition=self.edition,
            granule=None,
            part=None,
        )
        return parent.legal_id

    def chunk_id(self, chunk_index: int) -> str:
        """Return a deterministic chunk identity under this parent."""

        if not isinstance(chunk_index, int) or chunk_index < 0:
            raise FederalRegisterIdentityError(
                "chunk_index must be a non-negative integer"
            )
        return f"{self.parent_legal_id}#chunk={chunk_index:04d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_citation": self.canonical_citation,
            "correction_relation": self.correction_relation,
            "document_number": self.document_number,
            "document_type": self.document_type,
            "edition": self.edition,
            "effective_date": self.effective_date,
            "granule": self.granule,
            "legal_id": self.legal_id,
            "parent_legal_id": self.parent_legal_id,
            "part": self.part,
            "publication_date": self.publication_date,
            "related_document_number": self.related_document_number,
            "schema_version": SCHEMA_VERSION,
            "source_document_number": self.source_document_number,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LegalIdentity:
        if not isinstance(value, Mapping):
            raise FederalRegisterIdentityError("identity payload must be a mapping")
        forbidden_flags = {
            "include_type_qualifier",
            "type_in_legal_id",
            "include_correction_qualifier",
            "correction_in_legal_id",
        }.intersection(value)
        if forbidden_flags:
            raise IdentityParseError(
                "legal identity qualifier inclusion is not caller-selectable: "
                f"{sorted(forbidden_flags)}"
            )

        def _field(canonical: str, *aliases: str) -> Any:
            present = [
                (name, value[name])
                for name in (canonical, *aliases)
                if name in value and value[name] not in (None, "")
            ]
            if not present:
                return None
            first = str(present[0][1]).strip()
            for name, candidate in present[1:]:
                if str(candidate).strip() != first:
                    raise IdentityParseError(
                        f"conflicting {canonical} aliases: "
                        f"{present[0][0]}={present[0][1]!r}, {name}={candidate!r}"
                    )
            return present[0][1]

        existing = value.get("legal_id")
        parsed: LegalIdentity | None = None
        asserted_document_number: str | None = None
        asserted_publication_date: str | None = None
        asserted_relation: str | None = None
        asserted_related: str | None = None
        canonical_assertion = False
        if existing not in (None, ""):
            if not isinstance(existing, str) or existing != existing.strip():
                raise IdentityParseError(
                    "legal_id must be a string in exact canonical form"
                )
            try:
                parsed = parse_legal_id(existing)
                canonical_assertion = True
            except IdentityParseError:
                # LCR-050's authoritative examples predate the closed current
                # qualifier grammar.  Accept exactly its bare publication
                # assertion and its closed ``:<relation>:<related-doc>`` form;
                # row fields still provide and must agree with type/relation
                # semantics before we emit the current canonical legal_id.
                parts = existing.split(":")
                if len(parts) not in {3, 5} or parts[0] != LEGAL_ID_PREFIX:
                    raise
                asserted_document_number = normalize_document_number(parts[1])
                asserted_publication_date = normalize_publication_date(parts[2])
                if len(parts) == 5:
                    relation_values = {
                        item.value
                        for item in CorrectionRelation
                        if item is not CorrectionRelation.NONE
                    }
                    if parts[3] not in relation_values:
                        raise
                    asserted_relation = parts[3]
                    asserted_related = normalize_document_number(parts[4])

        document_number = _field("document_number", "documentNumber", "doc_number")
        publication_date = _field(
            "publication_date", "publicationDate", "pub_date", "date"
        )
        related = _field(
            "related_document_number", "relatedDocumentNumber", "related_document"
        )
        asserted_doc = (
            parsed.document_number if parsed is not None else asserted_document_number
        )
        asserted_pub = (
            parsed.publication_date if parsed is not None else asserted_publication_date
        )
        if (
            document_number is not None
            and asserted_doc is not None
            and normalize_document_number(document_number) != asserted_doc
        ):
            raise IdentityParseError(
                "explicit legal_id document number does not match row identity"
            )
        if (
            publication_date is not None
            and asserted_pub is not None
            and normalize_publication_date(publication_date) != asserted_pub
        ):
            raise IdentityParseError(
                "explicit legal_id publication date does not match row identity"
            )
        document_number = document_number or asserted_doc
        publication_date = publication_date or asserted_pub
        if document_number is None or publication_date is None:
            raise IdentityParseError(
                "document_number and publication_date are required for identity"
            )

        document_type = _field("document_type", "type")
        correction_relation = _field("correction_relation", "relation")
        if document_type is None and parsed is None:
            raise IdentityParseError("document_type is required for legal identity")
        identity = cls(
            document_number=document_number,
            publication_date=publication_date,
            document_type=document_type
            if document_type is not None
            else parsed.document_type,
            correction_relation=correction_relation
            if correction_relation is not None
            else (
                parsed.correction_relation
                if parsed is not None
                else DEFAULT_CORRECTION_RELATION
            ),
            related_document_number=related
            if related is not None
            else (parsed.related_document_number if parsed is not None else None),
            year_month=value.get("year_month"),
            effective_date=value.get("effective_date"),
            edition=value.get("edition")
            if "edition" in value
            else (parsed.edition if parsed is not None else None),
            granule=_field("granule", "granule_id")
            if _field("granule", "granule_id") is not None
            else (parsed.granule if parsed is not None else None),
            part=value.get("part")
            if "part" in value
            else (parsed.part if parsed is not None else None),
            source_document_number=str(document_number),
        )
        if canonical_assertion and identity.legal_id != existing:
            raise IdentityParseError(
                f"explicit legal_id {existing!r} does not exactly match "
                f"canonical row identity {identity.legal_id!r}"
            )
        if asserted_relation is not None and (
            identity.correction_relation != asserted_relation
            or identity.related_document_number != asserted_related
        ):
            raise IdentityParseError(
                "legacy legal_id relation assertion does not match row identity"
            )
        return identity


def build_legal_id(
    document_number: Any,
    publication_date: Any,
    *,
    document_type: Any,
    correction_relation: Any = DEFAULT_CORRECTION_RELATION,
    related_document_number: Any = None,
    edition: Any = None,
    granule: Any = None,
    part: Any = None,
    qualifier: Any = None,
) -> str:
    """Build a stable ``legal_id`` from publication components.

    Free-form qualifiers are rejected.  The legal-id grammar is deliberately
    closed so a parser can never silently discard identity-bearing material.
    """

    identity = LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        document_type=document_type,
        correction_relation=correction_relation,
        related_document_number=related_document_number,
        edition=edition,
        granule=granule,
        part=part,
    )
    legal_id = identity.legal_id
    if qualifier is not None and str(qualifier).strip():
        raise IdentityParseError(
            "free-form legal_id qualifiers are not supported; use a closed "
            "structured qualifier"
        )
    # Ensure schema contract is satisfied.
    return _validate_legal_id_shape(legal_id)


def build_canonical_citation(
    document_number: Any,
    publication_date: Any,
    **kwargs: Any,
) -> str:
    """Build a compact human-readable Federal Register citation."""

    allowed = {
        "document_type",
        "correction_relation",
        "related_document_number",
        "effective_date",
        "edition",
        "granule",
        "part",
    }
    unknown = set(kwargs) - allowed
    if unknown:
        raise IdentityParseError(
            f"unsupported legal identity fields: {sorted(unknown)}"
        )
    return LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        **kwargs,
    ).canonical_citation


def build_chunk_parent_id(
    document_number: Any,
    publication_date: Any,
    **kwargs: Any,
) -> str:
    """Return the deterministic parent identity for semantic text chunks."""

    allowed = {
        "document_type",
        "correction_relation",
        "related_document_number",
        "edition",
        "granule",
        "part",
    }
    unknown = set(kwargs) - allowed
    if unknown:
        raise IdentityParseError(
            f"unsupported legal identity fields: {sorted(unknown)}"
        )
    return LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        **kwargs,
    ).parent_legal_id


def parse_chunk_id(chunk_id: str) -> tuple[str, int]:
    """Split ``{parent_legal_id}#chunk=NNNN`` into parent id and index."""

    text = _require_non_empty_str(chunk_id, "chunk_id")
    match = _CHUNK_SUFFIX_RE.search(text)
    if not match:
        raise IdentityParseError(f"not a chunk id: {chunk_id!r}")
    parent = text[: match.start()]
    return parent, int(match.group("index"))


def parse_legal_id(legal_id: str) -> LegalIdentity:
    """Parse a previously built ``legal_id`` back into components."""

    if not isinstance(legal_id, str) or legal_id != legal_id.strip():
        raise IdentityParseError(
            "legal_id must be a string in exact canonical form without whitespace"
        )
    text = _require_non_empty_str(legal_id, "legal_id")
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(f"legal_id must not be positional: {legal_id!r}")
    normalized = _validate_legal_id_shape(text)
    if text != normalized:
        raise IdentityParseError(
            f"legal_id must already be in exact canonical form: {normalized!r}"
        )
    parts = normalized.split(":")
    if len(parts) < 3 or parts[0].lower() != LEGAL_ID_PREFIX:
        raise IdentityParseError(
            f"legal_id must match fr:<document_number>:<publication_date>"
            f"[:qualifier...]; got {legal_id!r}"
        )
    document_number = parts[1]
    publication_date = parts[2]
    document_type: str | None = None
    correction_relation = DEFAULT_CORRECTION_RELATION
    related_document_number: str | None = None
    edition: str | None = None
    granule: str | None = None
    part: str | None = None
    seen_qualifiers: set[str] = set()
    for segment in parts[3:]:
        if "=" not in segment:
            raise IdentityParseError(
                f"free-form legal_id qualifier is not supported: {segment!r}"
            )
        key, value = segment.split("=", 1)
        key = key.lower()
        if key not in _QUALIFIER_KEYS:
            raise IdentityParseError(f"unknown legal_id qualifier key: {key!r}")
        if key in seen_qualifiers:
            raise IdentityParseError(f"duplicate legal_id qualifier key: {key!r}")
        seen_qualifiers.add(key)
        if not value:
            raise IdentityParseError(f"empty legal_id qualifier value for {key!r}")
        if key == "type":
            document_type = value
        elif key == "rel":
            correction_relation = value
        elif key == "related":
            related_document_number = value
        elif key == "edition":
            edition = value
        elif key == "granule":
            granule = value
        elif key == "part":
            part = value
    if document_type is None:
        raise IdentityParseError("legal_id must include exactly one type qualifier")
    identity = LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        document_type=document_type,
        correction_relation=correction_relation,
        related_document_number=related_document_number,
        edition=edition,
        granule=granule,
        part=part,
    )
    if identity.legal_id != normalized:
        raise IdentityParseError(
            f"legal_id is not canonical or omits mandatory relation identity; "
            f"expected {identity.legal_id!r}"
        )
    return identity


def identity_from_row(row: Mapping[str, Any]) -> LegalIdentity:
    """Build a :class:`LegalIdentity` from a corpus/fixture row mapping."""

    return LegalIdentity.from_mapping(row)


def legal_id_from_row(row: Mapping[str, Any]) -> str:
    """Return the canonical ``legal_id`` and reject any conflicting claim."""

    existing = row.get("legal_id")
    if existing not in (None, ""):
        if not isinstance(existing, str):
            raise IdentityParseError("legal_id must be a string")
        text = existing
        if text != text.strip():
            raise IdentityParseError("legal_id must have no surrounding whitespace")
        if _POSITIONAL_ID_RE.fullmatch(text):
            raise PositionalIdentityError(f"legal_id must not be positional: {text!r}")
        if not text.startswith(f"{LEGAL_ID_PREFIX}:"):
            raise IdentityParseError(
                f"explicit legal_id is not a canonical Federal Register ID: {text!r}"
            )
        # ``identity_from_row`` below accepts only the two exact legacy
        # LCR-050 assertion shapes in addition to the closed current grammar,
        # then rebuilds all semantics from structured row fields.
    return identity_from_row(row).legal_id


# ---------------------------------------------------------------------------
# Content / source / entry identity
# ---------------------------------------------------------------------------


def compute_source_cid(
    document_number: Any,
    publication_date: Any,
    *,
    source_format: Any = None,
    official_source_url: Any = None,
    source_checksum: Any = None,
    body: Any = None,
    source_bytes: Any = None,
) -> str:
    """Compute a deterministic ``source_cid`` for normalized official evidence.

    The CID is derived from independently observed bytes and an official URL.
    A declared checksum is accepted only when it matches those bytes.  It can
    never replace them or override a mismatch.
    """

    doc = normalize_document_number(document_number)
    pub = normalize_publication_date(publication_date)
    fmt = _require_canonical_source_format(source_format)
    url = schema_validate_official_url(official_source_url)
    observed = _evidence_bytes(
        source_bytes,
        name="source_bytes",
        allow_empty=True,
    )
    fallback_body = _evidence_bytes(body, name="body")
    if observed is not None and fallback_body is not None and observed != fallback_body:
        raise FederalRegisterIdentityError(
            "source_bytes and body encode different official source evidence"
        )
    if observed is None:
        observed = fallback_body
    if observed is None:
        raise FederalRegisterIdentityError(
            "source identity requires independently observed source/body bytes"
        )
    digest = hashlib.sha256(observed).hexdigest()
    if source_checksum not in (None, ""):
        declared = normalize_sha256(source_checksum, name="source_checksum")
        if declared != digest:
            raise FederalRegisterIdentityError(
                "source_checksum does not match independently recomputed source bytes"
            )
    return _canonical_cid(
        domain="federal-register-source",
        payload={
            "content_sha256": digest,
            "document_number": doc,
            "official_source_url": url,
            "publication_date": pub,
            "source_format": fmt,
        },
    )


def _compute_entry_cid_from_canonical_row(
    row: Mapping[str, Any],
    *,
    content: bytes,
    source_cid: str,
) -> str:
    """Private fixed-envelope entry identity primitive.

    Callers cannot select the envelope.  ``enrich_row_identity`` first
    canonicalizes every accepted representation, and this primitive projects
    one fixed set of release-row fields.
    """

    doc = normalize_document_number(row.get("document_number"))
    pub = normalize_publication_date(row.get("publication_date"))
    lid = parse_legal_id(row.get("legal_id")).legal_id
    if lid.split(":")[1:3] != [doc, pub]:
        raise IdentityParseError(
            "legal_id document number/publication date do not match entry fields"
        )
    normalized_source = schema_validate_digest(source_cid, name="source_cid")
    digest, _labelled, content_cid = _content_digest_tokens(content)
    # Bind the complete returned row, not a caller-selected or partial field
    # list.  ``entry_cid`` is the sole excluded fixed-point value; source and
    # content identities remain present both here and in their domain-specific
    # slots for explicit verification.
    outside_envelope = set(row) - _ENTRY_ENVELOPE_FIELDS - {"entry_cid"}
    if outside_envelope:
        raise FederalRegisterIdentityError(
            f"canonical row escaped fixed entry envelope: {sorted(outside_envelope)}"
        )
    canonical_row = {
        key: row[key] for key in sorted(_ENTRY_ENVELOPE_FIELDS) if key in row
    }
    return _canonical_cid(
        domain="federal-register-entry",
        payload={
            "canonical_row": canonical_row,
            "content_cid": content_cid,
            "content_sha256": digest,
            "document_number": doc,
            "legal_id": lid,
            "publication_date": pub,
            "source_cid": normalized_source,
        },
    )


def compute_entry_cid(row: Mapping[str, Any]) -> str:
    """Compute ``entry_cid`` from the one canonical Federal Register row shape."""

    if not isinstance(row, Mapping):
        raise FederalRegisterIdentityError("entry identity requires a row mapping")
    if "record_fields" in row:
        raise FederalRegisterIdentityError(
            "record_fields is not a caller-selectable entry identity envelope"
        )
    return enrich_row_identity(row)["entry_cid"]


def _row_content_bytes(row: Mapping[str, Any]) -> bytes:
    """Return canonical retrieval bytes and reject conflicting byte surfaces."""

    candidates: list[tuple[str, bytes]] = []
    for field_name in ("content_bytes", "body_bytes", "text"):
        if field_name not in row:
            continue
        raw = _evidence_bytes(
            row.get(field_name),
            name=field_name,
            allow_empty=True,
        )
        if raw is not None:
            candidates.append((field_name, raw))
    if not candidates:
        raise FederalRegisterIdentityError(
            "content identity requires text/content_bytes/body_bytes"
        )
    first_name, first = candidates[0]
    for name, candidate in candidates[1:]:
        if candidate != first:
            raise FederalRegisterIdentityError(
                f"conflicting canonical content bytes: {first_name} and {name}"
            )
    availability = None
    if row.get("text_availability") not in (None, ""):
        try:
            availability = TextAvailability.coerce(row["text_availability"]).value
        except Exception as exc:
            raise FederalRegisterIdentityError(str(exc)) from exc
    if not first and availability == TextAvailability.ABSTRACT_ONLY.value:
        abstract = _evidence_bytes(row.get("abstract"), name="abstract")
        if abstract is not None:
            return abstract
    if not first and availability in {
        TextAvailability.FULL_TEXT.value,
        *tuple(_TEXT_AVAILABILITY_SOURCE_FORMAT),
    }:
        raise FederalRegisterIdentityError(
            f"text_availability={availability!r} requires non-empty content bytes"
        )
    return first


def _validate_row_content_claims(row: Mapping[str, Any], content: bytes) -> None:
    for field_name in ("content_cid", "ipfs_cid"):
        if row.get(field_name) not in (None, ""):
            _require_declared_digest_matches_bytes(
                row[field_name], content, name=field_name
            )
    digest = hashlib.sha256(content).hexdigest()
    for field_name in ("content_sha256", "official_content_hash"):
        if row.get(field_name) not in (None, ""):
            declared = normalize_sha256(row[field_name], name=field_name)
            if declared != digest:
                raise FederalRegisterIdentityError(
                    f"{field_name} does not match canonical content bytes"
                )


def content_identity_from_row(row: Mapping[str, Any]) -> str:
    """Return the content-version identity for a row.

    Used to distinguish changed-text versions under the same ``legal_id``.
    The identity is always recomputed from body bytes. Declared content CIDs
    and hashes are only consistency claims; no declared digest can replace the
    bytes or override a mismatch.
    """

    content = _row_content_bytes(row)
    _validate_row_content_claims(row, content)
    return "sha256:" + hashlib.sha256(content).hexdigest()


def body_content_token(row: Mapping[str, Any]) -> str | None:
    """Return a body/content token that must not merge distinct legal identities."""

    content = _row_content_bytes(row)
    _validate_row_content_claims(row, content)
    return f"content:sha256:{hashlib.sha256(content).hexdigest()}"


def row_position_token(row: Mapping[str, Any]) -> str | None:
    """Return a positional index token if present (not durable identity)."""

    for field_name in ("document_index", "row_index", "row_id", "index", "offset"):
        value = row.get(field_name)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if field_name == "row_id" and not re.fullmatch(
            r"(?:row[-_]?)?\d+", text, re.IGNORECASE
        ):
            # Human fixture row_ids such as "seed-correction-original" are
            # not positions.
            continue
        if isinstance(value, int) or re.fullmatch(r"\d+", text):
            return f"row-{text}"
        if _POSITIONAL_ID_RE.fullmatch(text):
            return text.lower()
    return None


def _entry_cid_of(row: Mapping[str, Any]) -> str:
    value = row.get("entry_cid")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return ""


def _source_cid_of(row: Mapping[str, Any]) -> str:
    value = row.get("source_cid")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return ""


def _source_format_of(row: Mapping[str, Any]) -> str:
    return _require_canonical_source_format(row.get("source_format"))


def _effective_date_token(row: Mapping[str, Any]) -> str:
    """Return a sortable effective-date token; unknown sorts as empty string."""

    if "effective_date" not in row:
        return ""
    normalized = normalize_effective_date(row.get("effective_date"))
    return normalized or ""


def _stable_row_token(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(row)).hexdigest()


def _row_stability_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Order-independent stability key for resume-safe reconciliation."""

    return (
        legal_id_from_row(row),
        content_identity_from_row(row),
        f"{source_format_priority(_source_format_of(row)):02d}",
        _source_format_of(row),
        _entry_cid_of(row),
        _source_cid_of(row),
        _effective_date_token(row),
        _stable_row_token(row),
    )


# ---------------------------------------------------------------------------
# Pair classification and merge
# ---------------------------------------------------------------------------


def _has_correction_link(row: Mapping[str, Any]) -> bool:
    relation = normalize_correction_relation(
        row.get("correction_relation") or row.get("relation")
    )
    return relation != DEFAULT_CORRECTION_RELATION


def classify_identity_pair(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify two rows with an explicit deterministic disposition.

    Rules (fail-closed, ordered):
    1. Same legal_id + same content-version identity + same source format →
       ``duplicate``.
    2. Same legal_id + same content-version identity + different source format →
       ``duplicate_source_format``.
    3. Same legal_id + different content-version identity →
       ``changed_text_version``.
    4. Different legal_id linked by correction relation →
       ``correction_distinct``.
    5. Different legal_id + shared body content CID/text →
       ``reject_content_cid_only_merge``.
    6. Different legal_id + shared row position → ``reject_positional_merge``.
    7. Otherwise different legal_id → ``distinct_identity``.
    """

    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise FederalRegisterIdentityError("pair rows must be mappings")

    # Pair classification can cause destructive deduplication, so it uses the
    # same canonical byte/provenance validation as the batch resolver.
    left = enrich_row_identity(left)
    right = enrich_row_identity(right)

    left_legal = legal_id_from_row(left)
    right_legal = legal_id_from_row(right)
    left_version = content_identity_from_row(left)
    right_version = content_identity_from_row(right)
    left_body = body_content_token(left)
    right_body = body_content_token(right)
    left_pos = row_position_token(left)
    right_pos = row_position_token(right)
    left_fmt = _source_format_of(left)
    right_fmt = _source_format_of(right)

    if left_legal == right_legal:
        if left_version == right_version:
            if left_fmt == right_fmt:
                disposition = IdentityDisposition.DUPLICATE
            else:
                disposition = IdentityDisposition.DUPLICATE_SOURCE_FORMAT
        else:
            disposition = IdentityDisposition.CHANGED_TEXT_VERSION
        return {
            "disposition": disposition.value,
            "legal_id": left_legal,
            "left_content_id": left_version,
            "right_content_id": right_version,
            "left_source_format": left_fmt,
            "right_source_format": right_fmt,
            "same_legal_id": True,
            "same_content_id": left_version == right_version,
            "same_body_content": left_body is not None and left_body == right_body,
            "same_row_position": left_pos is not None and left_pos == right_pos,
            "same_source_format": left_fmt == right_fmt,
            "merge_allowed": disposition
            in {
                IdentityDisposition.DUPLICATE,
                IdentityDisposition.DUPLICATE_SOURCE_FORMAT,
            },
            "version_pair": disposition is IdentityDisposition.CHANGED_TEXT_VERSION,
        }

    # Correction linkage: a non-none relation on either side whose related
    # document number matches the other side's document number. Either side
    # may also declare document_type=correction with an explicit related target.
    left_related = left.get("related_document_number") or left.get("related_document")
    right_related = right.get("related_document_number") or right.get(
        "related_document"
    )
    left_doc = str(left.get("document_number") or "").strip()
    right_doc = str(right.get("document_number") or "").strip()
    correction_linked = False
    try:
        if (
            left_related
            and right_doc
            and normalize_document_number(left_related)
            == normalize_document_number(right_doc)
        ):
            correction_linked = True
        if (
            right_related
            and left_doc
            and normalize_document_number(right_related)
            == normalize_document_number(left_doc)
        ):
            correction_linked = True
    except FederalRegisterIdentityError:
        correction_linked = False
    # Fail-closed fallback: if either side carries a non-none correction
    # relation but targets could not be compared, still refuse merge under the
    # correction disposition when both rows are correction-flavored.
    if not correction_linked:
        left_is_corr = _has_correction_link(left) or (
            normalize_document_type(left.get("document_type"))
            == DocumentType.CORRECTION.value
        )
        right_is_corr = _has_correction_link(right) or (
            normalize_document_type(right.get("document_type"))
            == DocumentType.CORRECTION.value
        )
        if left_is_corr and right_is_corr:
            correction_linked = True

    same_position = left_pos is not None and left_pos == right_pos
    same_body = left_body is not None and left_body == right_body
    if correction_linked:
        disposition = IdentityDisposition.CORRECTION_DISTINCT
    elif same_body:
        disposition = IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE
    elif same_position:
        disposition = IdentityDisposition.REJECT_POSITIONAL_MERGE
    else:
        disposition = IdentityDisposition.DISTINCT_IDENTITY

    return {
        "disposition": disposition.value,
        "left_legal_id": left_legal,
        "right_legal_id": right_legal,
        "left_content_id": left_version,
        "right_content_id": right_version,
        "left_source_format": left_fmt,
        "right_source_format": right_fmt,
        "same_legal_id": False,
        "same_content_id": left_version == right_version,
        "same_body_content": same_body,
        "same_row_position": same_position,
        "same_source_format": left_fmt == right_fmt,
        "merge_allowed": False,
        "version_pair": False,
        "correction_linked": correction_linked,
    }


def resolve_version_dispositions(
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> dict[str, Any]:
    """Group rows by durable ``legal_id`` and assign deterministic dispositions.

    Reconciliation is **order-independent**: rows are sorted by a stability key
    before grouping so resume / reordered inputs yield identical current and
    history sets.

    * Repeated canonical entry CIDs are one observation and have no duplicate
      disposition. Distinct entry CIDs with identical content and source format
      are ``duplicate``; different source formats are
      ``duplicate_source_format`` (preferred format kept).
    * Differing content identities become one deterministic ``keep_current``
      plus ``archive_history``; acquisition clocks never claim legal currentness.
    * Unknown effective dates are preserved on retained rows and never filled.
    * Rows that only share content CID or only share row position across
      different legal_ids are **not** merged.
    """

    if isinstance(rows, Mapping):
        resumed = rows.get("all_rows")
        if not isinstance(resumed, Sequence) or isinstance(resumed, (str, bytes)):
            raise FederalRegisterIdentityError(
                "resume mapping must contain the prior full all_rows sequence"
            )
        input_rows: Sequence[Mapping[str, Any]] = resumed
    elif isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        input_rows = rows
    else:
        raise FederalRegisterIdentityError(
            "rows must be a sequence or a prior resolution mapping"
        )

    # Validate and canonicalize every observation before it can participate in
    # a merge.  Resolution operates on the canonical observation *set*: an
    # exact entry replay is not a second observation, regardless of whether it
    # occurred within one batch or across a checkpoint boundary.  Distinct
    # provenance, source packaging, or content produces a distinct fully bound
    # entry CID and remains available for disposition classification below.
    canonical_by_entry_cid: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(input_rows):
        if not isinstance(row, Mapping):
            raise FederalRegisterIdentityError(f"row {index} must be a mapping")
        canonical = enrich_row_identity(row)
        entry_cid = canonical["entry_cid"]
        previous = canonical_by_entry_cid.get(entry_cid)
        if previous is not None and previous != canonical:
            raise DuplicatePrimaryKeyError(
                f"entry_cid {entry_cid!r} has conflicting canonical rows"
            )
        canonical_by_entry_cid[entry_cid] = canonical
    canonical_rows = list(canonical_by_entry_cid.values())
    canonical_rows.sort(key=_row_stability_key)
    # Stable ordinals are assigned after canonical sorting.  They therefore do
    # not leak caller order into dispositions or duplicate references.
    material: list[tuple[int, Mapping[str, Any]]] = list(enumerate(canonical_rows))

    groups: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    order: list[str] = []
    for index, row in material:
        legal_id = legal_id_from_row(row)
        if legal_id not in groups:
            order.append(legal_id)
            groups[legal_id] = []
        groups[legal_id].append((index, row))

    # Sort legal_id groups for deterministic output order.
    order = sorted(order)

    current_rows: list[dict[str, Any]] = []
    history_by_key: dict[str, list[dict[str, Any]]] = {}
    source_variants_by_key: dict[str, list[dict[str, Any]]] = {}
    dispositions: list[dict[str, Any]] = []

    for legal_id in order:
        members = groups[legal_id]
        # Group by content identity; within content, prefer best source format.
        content_order: list[str] = []
        by_content: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
        for index, row in members:
            cid = content_identity_from_row(row)
            if cid not in by_content:
                content_order.append(cid)
                by_content[cid] = []
            by_content[cid].append((index, row))

        # Deterministic representative ranking.  Acquisition/publication clocks
        # are deliberately excluded: the ADR forbids treating acquisition time
        # as a legal-currentness claim.  Every non-representative version is
        # retained in full below.
        def _content_rank(
            cid: str,
            cohorts: Mapping[str, list[tuple[int, Mapping[str, Any]]]] = by_content,
        ) -> tuple[str, str, str]:
            cohort = cohorts[cid]
            best = min(
                cohort,
                key=lambda item: (
                    f"{source_format_priority(_source_format_of(item[1])):02d}",
                    _entry_cid_of(item[1]),
                ),
            )
            row = best[1]
            return (
                cid,
                _entry_cid_of(row),
                _stable_row_token(row),
            )

        content_order = sorted(content_order, key=_content_rank)

        history: list[dict[str, Any]] = []
        source_variants: list[dict[str, Any]] = []
        for content_index, cid in enumerate(content_order):
            cohort = sorted(
                by_content[cid],
                key=lambda item: (
                    f"{source_format_priority(_source_format_of(item[1])):02d}",
                    _source_format_of(item[1]),
                    _entry_cid_of(item[1]),
                    _source_cid_of(item[1]),
                ),
            )
            primary_index, primary_row = cohort[0]
            is_last = content_index == len(content_order) - 1
            if is_last:
                current = dict(primary_row)
                current["legal_id"] = legal_id
                current["logical_key"] = legal_id
                current["identity_disposition"] = IdentityDisposition.KEEP_CURRENT.value
                current["currentness_claim"] = False
                # Preserve unknown effective dates explicitly.
                if "effective_date" in primary_row:
                    current["effective_date"] = normalize_effective_date(
                        primary_row.get("effective_date")
                    )
                    if current["effective_date"] is None:
                        current["effective_date_status"] = (
                            IdentityDisposition.PRESERVE_UNKNOWN_EFFECTIVE_DATE.value
                        )
                current_rows.append(current)
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": primary_index,
                        "content_id": cid,
                        "entry_cid": _entry_cid_of(primary_row),
                        "row_token": _stable_row_token(primary_row),
                        "source_format": _source_format_of(primary_row),
                        "disposition": IdentityDisposition.KEEP_CURRENT.value,
                    }
                )
            else:
                hist_entry = dict(primary_row)
                hist_entry.update(
                    {
                        "logical_key": legal_id,
                        "legal_id": legal_id,
                        "content_id": cid,
                        "source_format": _source_format_of(primary_row),
                        "disposition": IdentityDisposition.ARCHIVE_HISTORY.value,
                        "currentness_claim": False,
                        "row_index": primary_index,
                        "row_token": _stable_row_token(primary_row),
                    }
                )
                if "effective_date" in primary_row:
                    hist_entry["effective_date"] = normalize_effective_date(
                        primary_row.get("effective_date")
                    )
                history.append(hist_entry)
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": primary_index,
                        "content_id": cid,
                        "entry_cid": _entry_cid_of(primary_row),
                        "row_token": _stable_row_token(primary_row),
                        "disposition": IdentityDisposition.CHANGED_TEXT_VERSION.value,
                    }
                )

            # Format / exact duplicates under the same content identity.
            for dup_index, dup_row in cohort[1:]:
                same_fmt = _source_format_of(dup_row) == _source_format_of(primary_row)
                dup_disposition = (
                    IdentityDisposition.DUPLICATE
                    if same_fmt
                    else IdentityDisposition.DUPLICATE_SOURCE_FORMAT
                )
                variant = dict(dup_row)
                variant.update(
                    {
                        "content_id": cid,
                        "disposition": dup_disposition.value,
                        "duplicate_of_entry_cid": _entry_cid_of(primary_row),
                        "preferred_source_format": _source_format_of(primary_row),
                        "row_index": dup_index,
                        "row_token": _stable_row_token(dup_row),
                    }
                )
                source_variants.append(variant)
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": dup_index,
                        "content_id": cid,
                        "entry_cid": _entry_cid_of(dup_row),
                        "row_token": _stable_row_token(dup_row),
                        "source_format": _source_format_of(dup_row),
                        "disposition": dup_disposition.value,
                        "duplicate_of_row_index": primary_index,
                        "preferred_source_format": _source_format_of(primary_row),
                    }
                )

        history_by_key[legal_id] = history
        source_variants_by_key[legal_id] = source_variants

    # Cross-identity illegal merge probes.
    reject_events: list[dict[str, Any]] = []
    body_to_legal: dict[str, set[str]] = {}
    position_to_legal: dict[str, set[str]] = {}
    for legal_id, members in groups.items():
        for _index, row in members:
            body = body_content_token(row)
            if body is not None:
                body_to_legal.setdefault(body, set()).add(legal_id)
            pos = row_position_token(row)
            if pos is not None:
                position_to_legal.setdefault(pos, set()).add(legal_id)

    for body, legal_ids in sorted(body_to_legal.items()):
        if len(legal_ids) > 1:
            reject_events.append(
                {
                    "disposition": (
                        IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
                    ),
                    "body_content_token": body,
                    "legal_ids": sorted(legal_ids),
                    "merge_allowed": False,
                }
            )
    for pos, legal_ids in sorted(position_to_legal.items()):
        if len(legal_ids) > 1:
            reject_events.append(
                {
                    "disposition": IdentityDisposition.REJECT_POSITIONAL_MERGE.value,
                    "row_position": pos,
                    "legal_ids": sorted(legal_ids),
                    "merge_allowed": False,
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "current_rows": current_rows,
        "all_rows": canonical_rows,
        "history_by_key": history_by_key,
        "source_variants_by_key": source_variants_by_key,
        "current_keys": list(order),
        "history_keys": [key for key in order if history_by_key.get(key)],
        "dispositions": dispositions,
        "reject_events": reject_events,
        "group_count": len(order),
        "current_count": len(current_rows),
        "duplicate_count": sum(
            1
            for d in dispositions
            if d["disposition"]
            in {
                IdentityDisposition.DUPLICATE.value,
                IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value,
            }
        ),
        "changed_text_count": sum(
            1
            for d in dispositions
            if d["disposition"] == IdentityDisposition.CHANGED_TEXT_VERSION.value
        ),
        "source_format_duplicate_count": sum(
            1
            for d in dispositions
            if d["disposition"] == IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value
        ),
    }


def merge_by_legal_identity(
    existing_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    new_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge rows by durable legal identity with explicit version dispositions.

    Content changes under the same ``legal_id`` replace the current row and
    archive the prior content identity. Content CID alone, source format alone
    across distinct documents, or row position alone never merges distinct
    legal identities. Exact entry-CID repeats are one canonical observation,
    making the result order- and checkpoint-independent for resume safety.
    """

    def _full_rows(
        value: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
        *,
        name: str,
    ) -> list[Mapping[str, Any]]:
        if value is None:
            return []
        if isinstance(value, Mapping):
            material = value.get("all_rows")
            if not isinstance(material, Sequence) or isinstance(material, (str, bytes)):
                raise FederalRegisterIdentityError(
                    f"{name} resume mapping requires full all_rows"
                )
            return list(material)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return list(value)
        raise FederalRegisterIdentityError(f"{name} must be rows or prior resolution")

    prior_rows = _full_rows(existing_rows, name="existing_rows")
    incoming_rows = _full_rows(new_rows, name="new_rows")
    # The resolver canonicalizes and deduplicates the combined observation set
    # by entry CID.  Consequently raw batches, resumed checkpoints, and replay
    # all have exactly the same semantics.
    return resolve_version_dispositions([*prior_rows, *incoming_rows])


def reject_positional_or_cid_only_merge(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Public helper: refuse merges that rely only on position or content CID."""

    result = classify_identity_pair(left, right)
    disposition = IdentityDisposition.coerce(result["disposition"])
    if disposition in {
        IdentityDisposition.REJECT_POSITIONAL_MERGE,
        IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE,
    }:
        return {**result, "merge_allowed": False}
    if disposition in {
        IdentityDisposition.DISTINCT_IDENTITY,
        IdentityDisposition.CORRECTION_DISTINCT,
    }:
        return {**result, "merge_allowed": False}
    if disposition is IdentityDisposition.CHANGED_TEXT_VERSION:
        return {**result, "merge_allowed": True, "merge_mode": "version_history"}
    if disposition is IdentityDisposition.DUPLICATE:
        return {**result, "merge_allowed": True, "merge_mode": "deduplicate"}
    if disposition is IdentityDisposition.DUPLICATE_SOURCE_FORMAT:
        return {
            **result,
            "merge_allowed": True,
            "merge_mode": "prefer_source_format",
            "preferred_source_format": min(
                (result.get("left_source_format"), result.get("right_source_format")),
                key=lambda fmt: source_format_priority(fmt or DEFAULT_SOURCE_FORMAT),
            ),
        }
    return result


def validate_primary_keys(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_field: str = "entry_cid",
) -> None:
    """Fail closed when duplicate primary keys are present."""

    if key_field != "entry_cid":
        raise FederalRegisterIdentityError(
            "entry_cid is the only durable primary key; key_field is not overridable"
        )
    seen: dict[str, int] = {}
    material: list[tuple[int, Mapping[str, Any], str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FederalRegisterIdentityError(f"row {index} must be a mapping")
        if key_field not in row or row[key_field] in (None, ""):
            raise FederalRegisterIdentityError(
                f"row {index} missing required primary key field {key_field!r}"
            )
        try:
            key = schema_validate_entry_cid(row[key_field], name=key_field)
        except Exception as exc:
            if _POSITIONAL_ID_RE.fullmatch(str(row[key_field]).strip()):
                raise PositionalIdentityError(
                    f"row {index} primary key must not be positional: "
                    f"{row[key_field]!r}"
                ) from exc
            raise FederalRegisterIdentityError(
                f"row {index} has invalid {key_field}: {row[key_field]!r}"
            ) from exc
        if key in seen:
            raise DuplicatePrimaryKeyError(
                f"duplicate primary key {key_field}={key!r} at rows "
                f"{seen[key]} and {index}"
            )
        seen[key] = index
        material.append((index, row, key))

    # Shape and uniqueness are insufficient for a content address.  Recompute
    # every entry from the row's canonical bytes and provenance evidence.
    for index, row, key in material:
        canonical = enrich_row_identity(row)
        if canonical["entry_cid"] != key:
            raise FederalRegisterIdentityError(
                f"row {index} entry_cid is not bound to canonical row bytes"
            )


def assert_legal_ids_distinguishable(
    rows: Iterable[Mapping[str, Any]],
    *,
    allow_version_collisions: bool = False,
) -> list[str]:
    """Return legal_ids for *rows*.

    By default requires every ``legal_id`` to be unique. When
    ``allow_version_collisions`` is true, identical legal_ids are permitted for
    changed-text versions and source-format duplicates.
    """

    if not isinstance(allow_version_collisions, bool):
        raise FederalRegisterIdentityError("allow_version_collisions must be boolean")
    legal_ids: list[str] = []
    seen: dict[str, tuple[int, str, tuple[Any, ...]]] = {}
    for index, row in enumerate(rows):
        canonical = enrich_row_identity(row)
        identity = identity_from_row(canonical)
        legal_id = identity.legal_id
        content_id = content_identity_from_row(canonical)
        semantic_identity = (
            identity.document_number,
            identity.publication_date,
            identity.document_type,
            identity.correction_relation,
            identity.related_document_number,
            identity.edition,
            identity.granule,
            identity.part,
        )
        if legal_id in seen:
            if not allow_version_collisions:
                prior_index, _prior_content, _prior_semantics = seen[legal_id]
                raise FederalRegisterIdentityError(
                    f"legal_id collision for {legal_id!r} at rows "
                    f"{prior_index} and {index}"
                )
            prior_index, _prior_content, prior_semantics = seen[legal_id]
            if semantic_identity != prior_semantics:
                raise FederalRegisterIdentityError(
                    f"legal_id {legal_id!r} aliases distinct publication semantics "
                    f"at rows {prior_index} and {index}"
                )
        else:
            seen[legal_id] = (index, content_id, semantic_identity)
        legal_ids.append(legal_id)
    return legal_ids


_ROW_ALIAS_FIELDS = frozenset(
    {
        "content_format",
        "date",
        "doc_number",
        "documentNumber",
        "format",
        "granule_id",
        "publicationDate",
        "pub_date",
        "relatedDocumentNumber",
        "related_document",
        "relation",
        "type",
    }
)
_CONTENT_ALIAS_FIELDS = ("content_bytes", "body_bytes")
_SOURCE_BYTE_FIELDS = ("source_bytes", "official_source_bytes", "artifact_bytes")
# Input is a closed contract.  The first group is the exact LCR-050
# ``CorpusRecord`` surface, the second is canonical/declared identity material,
# and the final three are sealed-fixture annotations retained for collision
# auditing.  No arbitrary extension map can alter returned row bytes outside
# the entry-CID envelope.
_CORPUS_RECORD_FIELDS = frozenset(
    {
        "abstract",
        "acquisition_receipt_id",
        "acquisition_time",
        "admission_reason",
        "admission_status",
        "agencies",
        "correction_relation",
        "document_index",
        "document_number",
        "document_type",
        "entry_cid",
        "legal_id",
        "observed_at",
        "official_content_hash",
        "official_html_url",
        "official_pdf_url",
        "official_source_url",
        "official_xml_url",
        "parent_path",
        "parser_version",
        "publication_date",
        "related_document_number",
        "release_point",
        "schema_version",
        "source_authority_class",
        "source_checksum",
        "source_cid",
        "text",
        "text_availability",
        "title",
        "verification_result",
        "year_month",
    }
)
_IDENTITY_INPUT_FIELDS = frozenset(
    {
        "body_bytes",
        "canonical_citation",
        "content_bytes",
        "content_cid",
        "content_sha256",
        "edition",
        "effective_date",
        "granule",
        "ipfs_cid",
        "parent_legal_id",
        "part",
        "source_format",
        *_SOURCE_BYTE_FIELDS,
    }
)
_FIXTURE_ANNOTATION_FIELDS = frozenset(
    {"collision_family", "expected_disposition", "row_id"}
)
_ALLOWED_ROW_FIELDS = (
    _CORPUS_RECORD_FIELDS
    | _IDENTITY_INPUT_FIELDS
    | _ROW_ALIAS_FIELDS
    | _FIXTURE_ANNOTATION_FIELDS
)
_ENTRY_ENVELOPE_FIELDS = (
    _CORPUS_RECORD_FIELDS
    | _FIXTURE_ANNOTATION_FIELDS
    | frozenset(
        {
            "canonical_citation",
            "content_cid",
            "content_sha256",
            "parent_legal_id",
            "source_format",
        }
    )
) - {"entry_cid"}
_OPTIONAL_CORPUS_FIELDS = (
    "abstract",
    "document_index",
    "observed_at",
    "official_html_url",
    "official_pdf_url",
    "official_xml_url",
    "parent_path",
    "related_document_number",
    "title",
)
_TEXT_AVAILABILITY_SOURCE_FORMAT = {
    TextAvailability.HTML_BODY.value: SourceFormat.HTML.value,
    TextAvailability.XML_BODY.value: SourceFormat.XML.value,
    TextAvailability.PDF_BODY.value: SourceFormat.PDF.value,
    TextAvailability.GOVINFO_BODY.value: SourceFormat.GOVINFO.value,
}
_NON_BODY_AVAILABILITY_SOURCE_FORMAT = {
    TextAvailability.ABSTRACT_ONLY.value: SourceFormat.JSON.value,
    TextAvailability.METADATA_ONLY.value: SourceFormat.JSON.value,
    TextAvailability.UNAVAILABLE.value: SourceFormat.JSON.value,
}
_SOURCE_FORMAT_TEXT_AVAILABILITY = {
    source_format: availability
    for availability, source_format in _TEXT_AVAILABILITY_SOURCE_FORMAT.items()
}


def _canonical_source_projection(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return retained ``(text_availability, source_format)`` projection.

    LCR-050 retains availability but not ``source_format``. Body-specific
    availability values recover their exact package format. Generic
    ``full_text`` is deterministically specialized from explicit/URL evidence.
    Non-body states address the retained official metadata projection as JSON
    and keep their authoritative availability unchanged.
    """

    explicit: list[tuple[str, str]] = []
    for name in ("source_format", "format", "content_format"):
        if name not in row:
            continue
        if row[name] in (None, ""):
            raise FederalRegisterIdentityError(f"{name} must not be explicitly empty")
        explicit.append((name, _require_canonical_source_format(row[name])))
    if len({value for _name, value in explicit}) > 1:
        raise FederalRegisterIdentityError(
            f"conflicting source format aliases: {explicit!r}"
        )

    availability: str | None = None
    if row.get("text_availability") not in (None, ""):
        try:
            availability = TextAvailability.coerce(row["text_availability"]).value
        except Exception as exc:
            raise FederalRegisterIdentityError(str(exc)) from exc
    derived: set[str] = set()
    if availability in _TEXT_AVAILABILITY_SOURCE_FORMAT:
        derived.add(_TEXT_AVAILABILITY_SOURCE_FORMAT[availability])
    if availability in _NON_BODY_AVAILABILITY_SOURCE_FORMAT:
        derived.add(_NON_BODY_AVAILABILITY_SOURCE_FORMAT[availability])

    official_source_url = row.get("official_source_url")
    if (
        availability not in _NON_BODY_AVAILABILITY_SOURCE_FORMAT
        and official_source_url not in (None, "")
    ):
        normalized_source_url = schema_validate_official_url(official_source_url)
        for field_name, source_format in (
            ("official_html_url", SourceFormat.HTML.value),
            ("official_xml_url", SourceFormat.XML.value),
            ("official_pdf_url", SourceFormat.PDF.value),
        ):
            if row.get(field_name) not in (None, ""):
                candidate = schema_validate_official_url(
                    row[field_name], name=field_name
                )
                if candidate == normalized_source_url:
                    derived.add(source_format)

    chosen = explicit[0][1] if explicit else None
    if (
        chosen is None
        and availability == TextAvailability.FULL_TEXT.value
        and not derived
    ):
        # LCR-050's generic FULL_TEXT does not retain packaging. Prefer exact
        # official URL matches above, then use a closed URL-shape projection.
        url_text = str(official_source_url or "").lower()
        if url_text.endswith(".pdf") or "/pdf/" in url_text:
            derived.add(SourceFormat.PDF.value)
        elif url_text.endswith((".xml", ".xml?")) or "/xml/" in url_text:
            derived.add(SourceFormat.XML.value)
        elif "govinfo.gov/" in url_text:
            derived.add(SourceFormat.GOVINFO.value)
        else:
            derived.add(SourceFormat.HTML.value)
    if chosen is not None and derived and derived != {chosen}:
        raise FederalRegisterIdentityError(
            "source_format conflicts with format-bound text/URL evidence"
        )
    if chosen is None:
        if len(derived) != 1:
            raise FederalRegisterIdentityError(
                "source_format must be explicit or uniquely recoverable from "
                "retained availability/URL evidence"
            )
        chosen = next(iter(derived))

    if availability in _NON_BODY_AVAILABILITY_SOURCE_FORMAT:
        return availability, chosen
    try:
        return _SOURCE_FORMAT_TEXT_AVAILABILITY[chosen], chosen
    except KeyError as exc:
        raise FederalRegisterIdentityError(
            f"source_format {chosen!r} has no retained LCR-050 body projection"
        ) from exc


def _row_source_bytes(row: Mapping[str, Any], content: bytes) -> bytes:
    candidates: list[tuple[str, bytes]] = []
    for field_name in _SOURCE_BYTE_FIELDS:
        raw = _evidence_bytes(
            row.get(field_name),
            name=field_name,
            allow_empty=True,
        )
        if raw is not None:
            candidates.append((field_name, raw))
    if not candidates:
        return content
    first_name, first = candidates[0]
    for name, candidate in candidates[1:]:
        if candidate != first:
            raise FederalRegisterIdentityError(
                f"conflicting source artifact bytes: {first_name} and {name}"
            )
    return first


def _canonical_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FederalRegisterIdentityError(
            "canonical retrieval text bytes must be valid UTF-8"
        ) from exc


def _canonicalize_release_values(out: dict[str, Any]) -> None:
    """Normalize representations retained by the LCR-050 corpus record."""

    if "source_authority_class" not in out:
        out["source_authority_class"] = SourceAuthorityClass.OFFICIAL.value
    enum_fields = (
        ("admission_status", AdmissionStatus),
        ("source_authority_class", SourceAuthorityClass),
        ("text_availability", TextAvailability),
        ("verification_result", VerificationResult),
    )
    for field_name, enum_type in enum_fields:
        if field_name not in out:
            continue
        if out[field_name] in (None, ""):
            raise FederalRegisterIdentityError(
                f"{field_name} must not be explicitly empty"
            )
        try:
            out[field_name] = enum_type.coerce(out[field_name]).value
        except Exception as exc:
            raise FederalRegisterIdentityError(str(exc)) from exc

    agencies = out.get("agencies", [])
    if agencies is None:
        agencies = []
    if not isinstance(agencies, (list, tuple)):
        raise FederalRegisterIdentityError("agencies must be a list or tuple")
    out["agencies"] = [
        _require_non_empty_str(item, f"agencies[{index}]", maximum=256)
        for index, item in enumerate(agencies)
    ]

    if "document_index" in out:
        try:
            out["document_index"] = schema_validate_document_index(
                out["document_index"]
            )
        except Exception as exc:
            raise FederalRegisterIdentityError(str(exc)) from exc

    for field_name in _OPTIONAL_CORPUS_FIELDS:
        if out.get(field_name) in (None, ""):
            out.pop(field_name, None)
    for field_name in ("abstract", "title"):
        if field_name in out:
            if out[field_name] == "":
                out.pop(field_name)
            else:
                out[field_name] = _require_non_empty_str(
                    out[field_name], field_name, maximum=4096
                )
    bounded_required_strings = {
        "acquisition_receipt_id": 256,
        "acquisition_time": 64,
        "admission_reason": 4096,
        "parser_version": 128,
        "release_point": 256,
    }
    for field_name, maximum in bounded_required_strings.items():
        if field_name not in out:
            continue
        out[field_name] = _require_non_empty_str(
            out[field_name], field_name, maximum=maximum
        )

    if "schema_version" in out and out["schema_version"] != RELEASE_SCHEMA_VERSION:
        raise FederalRegisterIdentityError(
            f"corpus row schema_version must be {RELEASE_SCHEMA_VERSION!r}"
        )
    out["schema_version"] = RELEASE_SCHEMA_VERSION


def enrich_row_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *row* with legal_id / entry_cid / source_cid filled.

    Existing identities and declared hashes are treated as untrusted claims:
    each is normalized and required to equal the value independently computed
    from canonical bytes.  Missing provenance evidence fails closed.
    """

    if not isinstance(row, Mapping):
        raise FederalRegisterIdentityError("row must be a mapping")
    if "record_fields" in row:
        raise FederalRegisterIdentityError(
            "record_fields is not a caller-selectable entry identity envelope"
        )
    unknown_fields = set(row) - _ALLOWED_ROW_FIELDS
    if unknown_fields:
        raise FederalRegisterIdentityError(
            f"unsupported corpus row fields: {sorted(unknown_fields)}"
        )
    out = dict(row)
    identity = identity_from_row(out)
    if any(
        value is not None
        for value in (identity.edition, identity.granule, identity.part)
    ):
        raise FederalRegisterIdentityError(
            "edition, granule, and part are not retained by LCR-050 CorpusRecord"
        )
    if identity.effective_date is not None:
        raise FederalRegisterIdentityError(
            "effective_date is not retained by LCR-050 CorpusRecord"
        )
    canonical_availability, source_format = _canonical_source_projection(out)
    out["text_availability"] = canonical_availability
    official_source_url = schema_validate_official_url(out.get("official_source_url"))
    content = _row_content_bytes(out)
    _validate_row_content_claims(out, content)
    source_bytes = _row_source_bytes(out, content)
    if source_bytes != content:
        raise FederalRegisterIdentityError(
            "distinct source artifact bytes are not retained by LCR-050 CorpusRecord"
        )

    declared_source_cid = out.get("source_cid")
    declared_entry_cid = out.get("entry_cid")
    for alias in _ROW_ALIAS_FIELDS:
        out.pop(alias, None)
    for alias in (*_CONTENT_ALIAS_FIELDS, "ipfs_cid"):
        out.pop(alias, None)
    for alias in _SOURCE_BYTE_FIELDS:
        out.pop(alias, None)
    out["text"] = _canonical_text(content)
    for field_name in ("edition", "effective_date", "granule", "part"):
        out.pop(field_name, None)

    out["document_number"] = identity.document_number
    out["publication_date"] = identity.publication_date
    out["year_month"] = identity.year_month
    out["document_type"] = identity.document_type
    out["correction_relation"] = identity.correction_relation
    if identity.related_document_number is not None:
        out["related_document_number"] = identity.related_document_number
    else:
        out.pop("related_document_number", None)
    out["source_format"] = source_format
    out["official_source_url"] = official_source_url
    for field_name in ("official_html_url", "official_pdf_url", "official_xml_url"):
        if out.get(field_name) not in (None, ""):
            out[field_name] = schema_validate_official_url(
                out[field_name], name=field_name
            )
    declared_citation = out.get("canonical_citation")
    if (
        declared_citation not in (None, "")
        and declared_citation != identity.canonical_citation
    ):
        raise FederalRegisterIdentityError(
            "canonical_citation does not match canonical legal identity"
        )
    declared_parent = out.get("parent_legal_id")
    if (
        declared_parent not in (None, "")
        and declared_parent != identity.parent_legal_id
    ):
        raise FederalRegisterIdentityError(
            "parent_legal_id does not match canonical legal identity"
        )
    out["legal_id"] = identity.legal_id
    out["canonical_citation"] = identity.canonical_citation
    out["parent_legal_id"] = identity.parent_legal_id

    computed_source = compute_source_cid(
        identity.document_number,
        identity.publication_date,
        source_format=source_format,
        official_source_url=official_source_url,
        source_checksum=out.get("source_checksum"),
        source_bytes=source_bytes,
    )
    if declared_source_cid not in (None, ""):
        declared_source = schema_validate_digest(declared_source_cid, name="source_cid")
        if declared_source != computed_source:
            raise FederalRegisterIdentityError(
                "source_cid does not match canonical source evidence"
            )
    out["source_cid"] = computed_source
    out["source_checksum"] = hashlib.sha256(source_bytes).hexdigest()

    content_cid = cid_v1(content)
    out["content_cid"] = content_cid
    content_digest = hashlib.sha256(content).hexdigest()
    out["content_sha256"] = content_digest
    out["official_content_hash"] = content_digest
    _canonicalize_release_values(out)
    computed_entry = _compute_entry_cid_from_canonical_row(
        out,
        content=content,
        source_cid=computed_source,
    )
    if declared_entry_cid not in (None, ""):
        declared_entry = schema_validate_entry_cid(declared_entry_cid)
        if declared_entry != computed_entry:
            raise FederalRegisterIdentityError(
                "entry_cid does not match canonical retrieval record"
            )
    out["entry_cid"] = computed_entry
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# Collision fixture
# ---------------------------------------------------------------------------


def default_collision_fixture_path() -> Path:
    """Return the repository path of the sealed collision fixture."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "federal_register_identity_collisions.json"
    )


def _synthetic_entry_cid(index: int, *, salt: str = "lcr-054") -> str:
    """Deterministic, schema-valid CIDv1 for pre-enrichment fixture labels."""

    return _canonical_cid(
        domain="federal-register-fixture-entry-label",
        payload={"index": index, "salt": salt},
    )


def _synthetic_source_cid(index: int, *, salt: str = "lcr-054") -> str:
    return _canonical_cid(
        domain="federal-register-fixture-source-label",
        payload={"index": index, "salt": salt},
    )


def _doc_number(year: int, serial: int) -> str:
    return f"{year}-{serial:05d}"


def _pub_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def expand_collision_fixture(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand a compact collision recipe into concrete row dicts."""

    if not isinstance(payload, Mapping):
        raise CollisionFixtureError("fixture payload must be a mapping")
    schema = payload.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise CollisionFixtureError(
            f"unsupported fixture schema_version {schema!r}; "
            f"expected {FIXTURE_SCHEMA_VERSION!r}"
        )
    expected = int(payload.get("expected_row_count", KNOWN_COLLISION_ROW_COUNT))
    if expected != KNOWN_COLLISION_ROW_COUNT:
        raise CollisionFixtureError(
            f"expected_row_count must be {KNOWN_COLLISION_ROW_COUNT}, got {expected}"
        )

    rows: list[dict[str, Any]] = []

    for raw in payload.get("seed_rows") or ():
        if not isinstance(raw, Mapping):
            raise CollisionFixtureError("seed_rows entries must be mappings")
        rows.append(dict(raw))

    for generator in payload.get("generators") or ():
        if not isinstance(generator, Mapping):
            raise CollisionFixtureError("generators entries must be mappings")
        kind = str(generator.get("kind") or "").strip()
        count = int(generator.get("count") or 0)
        if count < 0:
            raise CollisionFixtureError(f"generator count must be >= 0, got {count}")

        if kind == "correction_pairs":
            year = int(generator.get("year_start") or 2018)
            serial_start = int(generator.get("serial_start") or 10000)
            for pair_index in range(count):
                orig_serial = serial_start + pair_index * 2
                corr_serial = orig_serial + 1
                orig_doc = _doc_number(year + (pair_index // 200), orig_serial % 100000)
                corr_doc = _doc_number(year + (pair_index // 200), corr_serial % 100000)
                month = 1 + (pair_index % 12)
                day = 1 + (pair_index % 28)
                orig_date = _pub_date(year + (pair_index // 200), month, day)
                corr_date = _pub_date(
                    year + (pair_index // 200), month, min(day + 1, 28)
                )
                for local_index, (doc, pub, dtype, rel, related, text) in enumerate(
                    (
                        (
                            orig_doc,
                            orig_date,
                            "rule",
                            "none",
                            None,
                            f"original-body-{pair_index}",
                        ),
                        (
                            corr_doc,
                            corr_date,
                            "correction",
                            "corrects",
                            orig_doc,
                            f"correction-body-{pair_index}",
                        ),
                    )
                ):
                    global_index = len(rows)
                    row: dict[str, Any] = {
                        "row_id": f"corr-{pair_index:04d}-{local_index}",
                        "collision_family": f"corr-{pair_index:04d}",
                        "document_number": doc,
                        "publication_date": pub,
                        "document_type": dtype,
                        "correction_relation": rel,
                        "text": text,
                        "source_format": "html",
                        "entry_cid": _synthetic_entry_cid(global_index),
                        "source_cid": _synthetic_source_cid(global_index),
                        "expected_disposition": (
                            IdentityDisposition.CORRECTION_DISTINCT.value
                        ),
                    }
                    if related is not None:
                        row["related_document_number"] = related
                    rows.append(row)

        elif kind == "source_format_duplicates":
            formats = list(generator.get("formats") or ["html", "pdf", "xml"])
            year = int(generator.get("year_start") or 2019)
            serial_start = int(generator.get("serial_start") or 20000)
            for item_index in range(count):
                doc = _doc_number(year, (serial_start + item_index) % 100000)
                pub = _pub_date(year, 1 + (item_index % 12), 1 + (item_index % 28))
                shared_text = f"shared-official-body-{item_index}"
                for local_index, fmt in enumerate(formats):
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"fmt-{item_index:04d}-{local_index}",
                            "collision_family": f"fmt-{item_index:04d}",
                            "document_number": doc,
                            "publication_date": pub,
                            "document_type": "rule",
                            "correction_relation": "none",
                            "source_format": fmt,
                            "text": shared_text,
                            "entry_cid": _synthetic_entry_cid(
                                global_index, salt=f"lcr-054-fmt-{fmt}"
                            ),
                            "source_cid": _synthetic_source_cid(
                                global_index, salt=f"lcr-054-fmt-{fmt}"
                            ),
                            "expected_disposition": (
                                IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value
                            ),
                        }
                    )

        elif kind == "changed_text_versions":
            year = int(generator.get("year_start") or 2020)
            serial_start = int(generator.get("serial_start") or 30000)
            for pair_index in range(count):
                doc = _doc_number(year, (serial_start + pair_index) % 100000)
                pub = _pub_date(year, 3 + (pair_index % 9), 1 + (pair_index % 28))
                for local_index, text in enumerate(
                    (f"body-v1-{pair_index}", f"body-v2-{pair_index}")
                ):
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"version-{pair_index:04d}-{local_index}",
                            "collision_family": f"version-{pair_index:04d}",
                            "document_number": doc,
                            "publication_date": pub,
                            "document_type": "proposed_rule",
                            "correction_relation": "none",
                            "source_format": "html",
                            "text": text,
                            "acquisition_time": (f"{pub}T0{local_index}:00:00Z"),
                            "entry_cid": _synthetic_entry_cid(
                                global_index, salt=f"lcr-054-version-{local_index}"
                            ),
                            "source_cid": _synthetic_source_cid(
                                global_index, salt=f"lcr-054-version-{local_index}"
                            ),
                            "expected_disposition": (
                                IdentityDisposition.CHANGED_TEXT_VERSION.value
                                if local_index == 1
                                else IdentityDisposition.KEEP_CURRENT.value
                            ),
                        }
                    )

        elif kind == "publication_date_variants":
            # Same document number, different publication dates — must not collapse.
            year = int(generator.get("year_start") or 2021)
            serial_start = int(generator.get("serial_start") or 40000)
            for pair_index in range(count):
                doc = _doc_number(year, (serial_start + pair_index) % 100000)
                for local_index in range(2):
                    pub = _pub_date(
                        year,
                        1 + (pair_index % 6),
                        1 + local_index * 10 + (pair_index % 5),
                    )
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"pubdate-{pair_index:04d}-{local_index}",
                            "collision_family": f"pubdate-{pair_index:04d}",
                            "document_number": doc,
                            "publication_date": pub,
                            "document_type": "notice",
                            "correction_relation": "none",
                            "source_format": "html",
                            "text": f"republication-{pair_index}-{local_index}",
                            "entry_cid": _synthetic_entry_cid(global_index),
                            "source_cid": _synthetic_source_cid(global_index),
                            "expected_disposition": (
                                IdentityDisposition.DISTINCT_IDENTITY.value
                            ),
                        }
                    )

        elif kind == "content_cid_only_pairs":
            year = int(generator.get("year_start") or 2022)
            serial_start = int(generator.get("serial_start") or 50000)
            for pair_index in range(count):
                shared_cid = _stable_hex(
                    f"shared-content-{pair_index}", salt="lcr-054-shared"
                )
                for local_index in range(2):
                    doc = _doc_number(
                        year, (serial_start + pair_index * 2 + local_index) % 100000
                    )
                    pub = _pub_date(
                        year,
                        1 + (pair_index % 12),
                        1 + ((pair_index + local_index) % 28),
                    )
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"cid-only-{pair_index:04d}-{local_index}",
                            "collision_family": f"cid-only-{pair_index:04d}",
                            "document_number": doc,
                            "publication_date": pub,
                            "document_type": "notice",
                            "correction_relation": "none",
                            "source_format": "html",
                            "content_cid": shared_cid,
                            "text": f"shared-boilerplate-{pair_index}",
                            "entry_cid": _synthetic_entry_cid(global_index),
                            "source_cid": _synthetic_source_cid(global_index),
                            "expected_disposition": (
                                IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
                            ),
                        }
                    )

        elif kind == "positional_only_pairs":
            year = int(generator.get("year_start") or 2023)
            serial_start = int(generator.get("serial_start") or 60000)
            for pair_index in range(count):
                shared_index = 1000 + pair_index
                for local_index in range(2):
                    doc = _doc_number(
                        year, (serial_start + pair_index * 2 + local_index) % 100000
                    )
                    pub = _pub_date(
                        year,
                        1 + (pair_index % 12),
                        1 + ((pair_index + local_index) % 28),
                    )
                    global_index = len(rows)
                    rows.append(
                        {
                            "row_id": f"pos-only-{pair_index:04d}-{local_index}",
                            "collision_family": f"pos-only-{pair_index:04d}",
                            "document_number": doc,
                            "publication_date": pub,
                            "document_type": "rule",
                            "correction_relation": "none",
                            "source_format": "html",
                            "document_index": shared_index,
                            "text": f"distinct-body-{pair_index}-{local_index}",
                            "entry_cid": _synthetic_entry_cid(global_index),
                            "source_cid": _synthetic_source_cid(global_index),
                            "expected_disposition": (
                                IdentityDisposition.REJECT_POSITIONAL_MERGE.value
                            ),
                        }
                    )

        elif kind == "unknown_effective_dates":
            year = int(generator.get("year_start") or 2024)
            serial_start = int(generator.get("serial_start") or 70000)
            unknown_tokens = list(
                generator.get("unknown_tokens") or ["unknown", "n/a", "tbd", None, ""]
            )
            for item_index in range(count):
                doc = _doc_number(year, (serial_start + item_index) % 100000)
                pub = _pub_date(year, 1 + (item_index % 12), 1 + (item_index % 28))
                token = unknown_tokens[item_index % len(unknown_tokens)]
                global_index = len(rows)
                row = {
                    "row_id": f"unk-eff-{item_index:04d}",
                    "collision_family": f"unk-eff-{item_index:04d}",
                    "document_number": doc,
                    "publication_date": pub,
                    "document_type": "rule",
                    "correction_relation": "none",
                    "source_format": "html",
                    "effective_date": token,
                    "text": f"body-unknown-eff-{item_index}",
                    "entry_cid": _synthetic_entry_cid(global_index),
                    "source_cid": _synthetic_source_cid(global_index),
                    "expected_disposition": (
                        IdentityDisposition.PRESERVE_UNKNOWN_EFFECTIVE_DATE.value
                    ),
                }
                rows.append(row)

        elif kind == "document_type_variants":
            year = int(generator.get("year_start") or 2017)
            serial_start = int(generator.get("serial_start") or 80000)
            types = list(
                generator.get("types")
                or [
                    "rule",
                    "proposed_rule",
                    "notice",
                    "presidential_document",
                    "sunshine_act_meeting",
                ]
            )
            for item_index in range(count):
                doc = _doc_number(year, (serial_start + item_index) % 100000)
                pub = _pub_date(year, 1 + (item_index % 12), 1 + (item_index % 28))
                dtype = types[item_index % len(types)]
                global_index = len(rows)
                rows.append(
                    {
                        "row_id": f"dtype-{item_index:04d}",
                        "collision_family": f"dtype-{item_index:04d}",
                        "document_number": doc,
                        "publication_date": pub,
                        "document_type": dtype,
                        "correction_relation": "none",
                        "source_format": "html",
                        "text": f"body-type-{dtype}-{item_index}",
                        "entry_cid": _synthetic_entry_cid(global_index),
                        "source_cid": _synthetic_source_cid(global_index),
                    }
                )

        elif kind == "withdrawal_pairs":
            year = int(generator.get("year_start") or 2016)
            serial_start = int(generator.get("serial_start") or 90000)
            for pair_index in range(count):
                orig_doc = _doc_number(year, (serial_start + pair_index * 2) % 100000)
                wd_doc = _doc_number(year, (serial_start + pair_index * 2 + 1) % 100000)
                orig_date = _pub_date(
                    year, 2 + (pair_index % 10), 1 + (pair_index % 28)
                )
                wd_date = _pub_date(
                    year, 2 + (pair_index % 10), min(2 + (pair_index % 27), 28)
                )
                for local_index, (doc, pub, rel, related, text) in enumerate(
                    (
                        (
                            orig_doc,
                            orig_date,
                            "none",
                            None,
                            f"proposed-{pair_index}",
                        ),
                        (
                            wd_doc,
                            wd_date,
                            "withdraws",
                            orig_doc,
                            f"withdrawal-{pair_index}",
                        ),
                    )
                ):
                    global_index = len(rows)
                    row = {
                        "row_id": f"wd-{pair_index:04d}-{local_index}",
                        "collision_family": f"wd-{pair_index:04d}",
                        "document_number": doc,
                        "publication_date": pub,
                        "document_type": (
                            "proposed_rule" if local_index == 0 else "notice"
                        ),
                        "correction_relation": rel,
                        "source_format": "html",
                        "text": text,
                        "entry_cid": _synthetic_entry_cid(global_index),
                        "source_cid": _synthetic_source_cid(global_index),
                        "expected_disposition": (
                            IdentityDisposition.CORRECTION_DISTINCT.value
                        ),
                    }
                    if related is not None:
                        row["related_document_number"] = related
                    rows.append(row)

        else:
            raise CollisionFixtureError(f"unknown generator kind: {kind!r}")

    if len(rows) != expected:
        raise CollisionFixtureError(
            f"expanded fixture has {len(rows)} rows; expected {expected}"
        )

    for _index, row in enumerate(rows):
        # Generated labels are deliberately discarded: fixture identities are
        # recomputed from the same canonical bytes as production inputs.
        row.pop("entry_cid", None)
        row.pop("source_cid", None)
        # Legacy sealed recipes predate mandatory type/relation qualifiers.
        # Fixture expansion is non-authorizing and discards those old toggles;
        # public identity APIs reject them.
        row.pop("include_type_qualifier", None)
        row.pop("include_correction_qualifier", None)
        # The sealed recipe predates the LCR-050 CorpusRecord projection and
        # contains effective-date probes.  Effective date is not a retained
        # corpus column, so fixture expansion canonicalizes it away exactly as
        # a production unknown token is canonicalized away; known values are
        # exercised as public-path rejections in the unit matrix.
        row.pop("effective_date", None)
        pub = normalize_publication_date(row.get("publication_date"))
        doc = normalize_document_number(row.get("document_number"))
        row.setdefault(
            "official_source_url",
            (
                "https://www.federalregister.gov/documents/"
                f"{pub[0:4]}/{pub[5:7]}/{pub[8:10]}/{doc}"
            ),
        )
        content = _row_content_bytes(row)
        if "content_cid" in row:
            row["content_cid"] = cid_v1(content)
        row["source_checksum"] = hashlib.sha256(content).hexdigest()
        enriched = enrich_row_identity(row)
        row.clear()
        row.update(enriched)
        # Validate the complete durable identity against the LCR-050 contract.
        _validate_legal_id_shape(row["legal_id"])
        if not row["document_number"].startswith(("C", "R")):
            # LCR-050 currently covers the unprefixed domain.  Keep checking
            # that dependency while the upstream schema widens for official
            # correction/replacement numbers.
            schema_validate_legal_id(row["legal_id"])
        schema_validate_entry_cid(row["entry_cid"])
        schema_validate_digest(row["source_cid"], name="source_cid")

    validate_primary_keys(rows)
    return rows


def load_collision_fixture(
    path: PathLike | None = None,
) -> list[dict[str, Any]]:
    """Load and expand the sealed collision fixture."""

    fixture_path = Path(path) if path is not None else default_collision_fixture_path()
    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollisionFixtureError(
            f"cannot read collision fixture: {fixture_path}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollisionFixtureError(
            f"collision fixture is not valid JSON: {exc}"
        ) from exc
    return expand_collision_fixture(payload)


def load_collision_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    """Load the raw (unexpanded) collision fixture mapping."""

    fixture_path = Path(path) if path is not None else default_collision_fixture_path()
    try:
        raw = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollisionFixtureError(
            f"cannot read collision fixture: {fixture_path}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollisionFixtureError(
            f"collision fixture is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CollisionFixtureError("collision fixture root must be an object")
    return payload


def disposition_cases(payload: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return explicit pair-disposition cases from the sealed recipe."""

    if payload is None:
        payload = load_collision_fixture_payload()
    cases = payload.get("disposition_cases") or []
    if not isinstance(cases, list):
        raise CollisionFixtureError("disposition_cases must be a list")
    material: list[dict[str, Any]] = []
    for item in cases:
        if not isinstance(item, Mapping):
            raise CollisionFixtureError("disposition case must be a mapping")
        case = dict(item)
        for side in ("left", "right"):
            raw = case.get(side)
            if not isinstance(raw, Mapping):
                raise CollisionFixtureError(f"disposition case missing {side} row")
            row = dict(raw)
            row.pop("entry_cid", None)
            row.pop("source_cid", None)
            row.pop("include_type_qualifier", None)
            row.pop("include_correction_qualifier", None)
            row.setdefault("source_format", DEFAULT_SOURCE_FORMAT)
            pub = normalize_publication_date(row.get("publication_date"))
            doc = normalize_document_number(row.get("document_number"))
            row.setdefault(
                "official_source_url",
                (
                    "https://www.federalregister.gov/documents/"
                    f"{pub[0:4]}/{pub[5:7]}/{pub[8:10]}/{doc}"
                ),
            )
            content = _row_content_bytes(row)
            if "content_cid" in row:
                row["content_cid"] = cid_v1(content)
            row["source_checksum"] = hashlib.sha256(content).hexdigest()
            case[side] = enrich_row_identity(row)
        material.append(case)
    return material


def build_default_collision_fixture_payload() -> dict[str, Any]:
    """Return the sealed compact collision recipe (source of the JSON fixture).

    Row arithmetic (must equal :data:`KNOWN_COLLISION_ROW_COUNT` = 370)::

        seed_rows:                    16
        correction_pairs:          35 × 2 = 70
        source_format_duplicates:  25 × 3 = 75
        changed_text_versions:     25 × 2 = 50
        publication_date_variants: 20 × 2 = 40
        content_cid_only_pairs:    12 × 2 = 24
        positional_only_pairs:     12 × 2 = 24
        unknown_effective_dates:           21
        document_type_variants:            20
        withdrawal_pairs:          15 × 2 = 30
        ─────────────────────────────────────
        total:                            370
    """

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "expected_row_count": KNOWN_COLLISION_ROW_COUNT,
        "task_id": TASK_ID,
        "description": (
            "Compact recipe for Federal Register identity collisions and "
            "version dispositions. Correction/withdrawal pairs remain "
            "separately addressable. Source-format duplicates of the same "
            "publication reconcile deterministically (html preferred). "
            "Changed-text pairs share legal_id with different content. "
            "Publication-date variants of the same document number stay "
            "distinct. Content-CID-only and positional-only pairs must not "
            "merge. Unknown effective dates are preserved without invention."
        ),
        "disposition_cases": [
            {
                "case_id": "logical-duplicate",
                "expected_disposition": IdentityDisposition.DUPLICATE.value,
                "left": {
                    "document_number": "2020-12345",
                    "publication_date": "2020-06-15",
                    "document_type": "rule",
                    "source_format": "html",
                    "entry_cid": "a" * 64,
                    "text": "same body",
                },
                "right": {
                    "document_number": "2020-12345",
                    "publication_date": "2020-06-15",
                    "document_type": "rule",
                    "source_format": "html",
                    "entry_cid": "a" * 64,
                    "text": "same body",
                },
            },
            {
                "case_id": "source-format-duplicate",
                "expected_disposition": (
                    IdentityDisposition.DUPLICATE_SOURCE_FORMAT.value
                ),
                "left": {
                    "document_number": "2020-12345",
                    "publication_date": "2020-06-15",
                    "document_type": "rule",
                    "source_format": "html",
                    "entry_cid": "b" * 64,
                    "text": "official body",
                },
                "right": {
                    "document_number": "2020-12345",
                    "publication_date": "2020-06-15",
                    "document_type": "rule",
                    "source_format": "pdf",
                    "entry_cid": "c" * 64,
                    "text": "official body",
                },
            },
            {
                "case_id": "changed-text-version",
                "expected_disposition": (
                    IdentityDisposition.CHANGED_TEXT_VERSION.value
                ),
                "left": {
                    "document_number": "2021-05678",
                    "publication_date": "2021-03-01",
                    "document_type": "proposed_rule",
                    "source_format": "html",
                    "entry_cid": "d" * 64,
                    "text": "old body",
                },
                "right": {
                    "document_number": "2021-05678",
                    "publication_date": "2021-03-01",
                    "document_type": "proposed_rule",
                    "source_format": "html",
                    "entry_cid": "e" * 64,
                    "text": "new body",
                },
            },
            {
                "case_id": "correction-distinct",
                "expected_disposition": (IdentityDisposition.CORRECTION_DISTINCT.value),
                "left": {
                    "document_number": "2020-12345",
                    "publication_date": "2020-06-15",
                    "document_type": "rule",
                    "correction_relation": "none",
                    "entry_cid": "f" * 64,
                    "text": "original",
                },
                "right": {
                    "document_number": "2020-13000",
                    "publication_date": "2020-07-01",
                    "document_type": "correction",
                    "correction_relation": "corrects",
                    "related_document_number": "2020-12345",
                    "entry_cid": "1" * 64,
                    "text": "correction",
                    "include_type_qualifier": True,
                    "include_correction_qualifier": True,
                },
            },
            {
                "case_id": "content-cid-only-reject",
                "expected_disposition": (
                    IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value
                ),
                "left": {
                    "document_number": "2022-01000",
                    "publication_date": "2022-01-10",
                    "document_type": "notice",
                    "content_cid": "e" * 64,
                    "entry_cid": "2" * 64,
                    "text": "boilerplate",
                },
                "right": {
                    "document_number": "2022-02000",
                    "publication_date": "2022-02-10",
                    "document_type": "notice",
                    "content_cid": "e" * 64,
                    "entry_cid": "3" * 64,
                    "text": "boilerplate",
                },
            },
            {
                "case_id": "positional-only-reject",
                "expected_disposition": (
                    IdentityDisposition.REJECT_POSITIONAL_MERGE.value
                ),
                "left": {
                    "document_number": "2023-01000",
                    "publication_date": "2023-01-15",
                    "document_type": "rule",
                    "document_index": 42,
                    "entry_cid": "4" * 64,
                    "text": "alpha",
                },
                "right": {
                    "document_number": "2023-02000",
                    "publication_date": "2023-02-15",
                    "document_type": "rule",
                    "document_index": 42,
                    "entry_cid": "5" * 64,
                    "text": "beta",
                },
            },
            {
                "case_id": "publication-date-distinct",
                "expected_disposition": IdentityDisposition.DISTINCT_IDENTITY.value,
                "left": {
                    "document_number": "2021-04000",
                    "publication_date": "2021-01-05",
                    "document_type": "notice",
                    "entry_cid": "6" * 64,
                    "text": "first publication",
                },
                "right": {
                    "document_number": "2021-04000",
                    "publication_date": "2021-01-15",
                    "document_type": "notice",
                    "entry_cid": "7" * 64,
                    "text": "second publication",
                },
            },
        ],
        "generators": [
            {
                "kind": "correction_pairs",
                "count": 35,
                "year_start": 2018,
                "serial_start": 10000,
            },
            {
                "kind": "source_format_duplicates",
                "count": 25,
                "formats": ["html", "pdf", "xml"],
                "year_start": 2019,
                "serial_start": 20000,
            },
            {
                "kind": "changed_text_versions",
                "count": 25,
                "year_start": 2020,
                "serial_start": 30000,
            },
            {
                "kind": "publication_date_variants",
                "count": 20,
                "year_start": 2021,
                "serial_start": 40000,
            },
            {
                "kind": "content_cid_only_pairs",
                "count": 12,
                "year_start": 2022,
                "serial_start": 50000,
            },
            {
                "kind": "positional_only_pairs",
                "count": 12,
                "year_start": 2023,
                "serial_start": 60000,
            },
            {
                "kind": "unknown_effective_dates",
                "count": 21,
                "year_start": 2024,
                "serial_start": 70000,
                "unknown_tokens": ["unknown", "n/a", "tbd", None, ""],
            },
            {
                "kind": "document_type_variants",
                "count": 20,
                "year_start": 2017,
                "serial_start": 80000,
            },
            {
                "kind": "withdrawal_pairs",
                "count": 15,
                "year_start": 2016,
                "serial_start": 90000,
            },
        ],
        "seed_rows": [
            {
                "row_id": "seed-rule",
                "collision_family": "seed-basic",
                "document_number": "2020-12345",
                "publication_date": "2020-06-15",
                "document_type": "rule",
                "correction_relation": "none",
                "source_format": "html",
                "text": "EPA final rule body",
                "effective_date": "2020-07-15",
            },
            {
                "row_id": "seed-correction",
                "collision_family": "seed-basic",
                "document_number": "2020-13000",
                "publication_date": "2020-07-01",
                "document_type": "correction",
                "correction_relation": "corrects",
                "related_document_number": "2020-12345",
                "source_format": "html",
                "text": "EPA correction body",
                "include_type_qualifier": True,
                "include_correction_qualifier": True,
            },
            {
                "row_id": "seed-proposed",
                "collision_family": "seed-withdrawal",
                "document_number": "2022-05678",
                "publication_date": "2022-04-10",
                "document_type": "proposed_rule",
                "correction_relation": "none",
                "source_format": "html",
                "text": "DOT proposed rule",
                "effective_date": "unknown",
            },
            {
                "row_id": "seed-withdraw",
                "collision_family": "seed-withdrawal",
                "document_number": "2022-06000",
                "publication_date": "2022-05-01",
                "document_type": "notice",
                "correction_relation": "withdraws",
                "related_document_number": "2022-05678",
                "source_format": "html",
                "text": "DOT withdrawal notice",
            },
            {
                "row_id": "seed-fmt-html",
                "collision_family": "seed-format",
                "document_number": "2019-11111",
                "publication_date": "2019-03-20",
                "document_type": "rule",
                "source_format": "html",
                "text": "multi-format official body",
            },
            {
                "row_id": "seed-fmt-pdf",
                "collision_family": "seed-format",
                "document_number": "2019-11111",
                "publication_date": "2019-03-20",
                "document_type": "rule",
                "source_format": "pdf",
                "text": "multi-format official body",
            },
            {
                "row_id": "seed-fmt-xml",
                "collision_family": "seed-format",
                "document_number": "2019-11111",
                "publication_date": "2019-03-20",
                "document_type": "rule",
                "source_format": "xml",
                "text": "multi-format official body",
            },
            {
                "row_id": "seed-version-old",
                "collision_family": "seed-version",
                "document_number": "2021-22222",
                "publication_date": "2021-08-08",
                "document_type": "notice",
                "source_format": "html",
                "text": "version-one body",
                "acquisition_time": "2021-08-08T01:00:00Z",
            },
            {
                "row_id": "seed-version-new",
                "collision_family": "seed-version",
                "document_number": "2021-22222",
                "publication_date": "2021-08-08",
                "document_type": "notice",
                "source_format": "html",
                "text": "version-two body",
                "acquisition_time": "2021-08-08T02:00:00Z",
            },
            {
                "row_id": "seed-pubdate-a",
                "collision_family": "seed-pubdate",
                "document_number": "2018-33333",
                "publication_date": "2018-01-05",
                "document_type": "notice",
                "source_format": "html",
                "text": "first appearance",
            },
            {
                "row_id": "seed-pubdate-b",
                "collision_family": "seed-pubdate",
                "document_number": "2018-33333",
                "publication_date": "2018-01-15",
                "document_type": "notice",
                "source_format": "html",
                "text": "second appearance",
            },
            {
                "row_id": "seed-unknown-eff",
                "collision_family": "seed-unknown-eff",
                "document_number": "2024-44444",
                "publication_date": "2024-02-29",
                "document_type": "rule",
                "source_format": "html",
                "effective_date": "tbd",
                "text": "effective date not yet known",
            },
            {
                "row_id": "seed-presidential",
                "collision_family": "seed-types",
                "document_number": "2017-55555",
                "publication_date": "2017-01-20",
                "document_type": "presidential_document",
                "source_format": "html",
                "text": "executive order body",
            },
            {
                "row_id": "seed-sunshine",
                "collision_family": "seed-types",
                "document_number": "2017-55556",
                "publication_date": "2017-02-01",
                "document_type": "sunshine_act_meeting",
                "source_format": "html",
                "text": "sunshine meeting notice",
            },
            {
                "row_id": "seed-cid-a",
                "collision_family": "seed-cid-only",
                "document_number": "2022-66666",
                "publication_date": "2022-05-05",
                "document_type": "notice",
                "content_cid": (
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
                "text": "shared boilerplate",
                "source_format": "html",
            },
            {
                "row_id": "seed-cid-b",
                "collision_family": "seed-cid-only",
                "document_number": "2022-66667",
                "publication_date": "2022-05-06",
                "document_type": "notice",
                "content_cid": (
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
                "text": "shared boilerplate",
                "source_format": "html",
            },
        ],
    }


__all__ = [
    "DEFAULT_CORRECTION_RELATION",
    "DEFAULT_DOCUMENT_TYPE",
    "DEFAULT_SOURCE_FORMAT",
    "FIXTURE_SCHEMA_VERSION",
    "KNOWN_COLLISION_ROW_COUNT",
    "LEGAL_ID_PREFIX",
    "SCHEMA_VERSION",
    "TASK_ID",
    "CollisionFixtureError",
    "DuplicatePrimaryKeyError",
    "FederalRegisterIdentityError",
    "IdentityDisposition",
    "IdentityDispositionError",
    "IdentityParseError",
    "LegalIdentity",
    "PositionalIdentityError",
    "SourceFormat",
    "assert_legal_ids_distinguishable",
    "body_content_token",
    "build_canonical_citation",
    "build_chunk_parent_id",
    "build_default_collision_fixture_payload",
    "build_legal_id",
    "classify_identity_pair",
    "compute_entry_cid",
    "compute_source_cid",
    "content_identity_from_row",
    "default_collision_fixture_path",
    "disposition_cases",
    "enrich_row_identity",
    "expand_collision_fixture",
    "identity_from_row",
    "legal_id_from_row",
    "load_collision_fixture",
    "load_collision_fixture_payload",
    "merge_by_legal_identity",
    "normalize_correction_relation",
    "normalize_document_number",
    "normalize_document_type",
    "normalize_effective_date",
    "normalize_publication_date",
    "normalize_source_format",
    "normalize_year_month",
    "parse_chunk_id",
    "parse_legal_id",
    "reject_positional_or_cid_only_merge",
    "resolve_version_dispositions",
    "row_position_token",
    "source_format_priority",
    "validate_primary_keys",
]
