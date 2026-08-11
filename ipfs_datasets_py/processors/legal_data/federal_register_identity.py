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

The sealed collision fixture expands from a compact recipe that exercises
correction pairs, source-format duplicates, changed-text versions, publication-
date variants, content-CID-only and positional non-merges, and unknown
effective dates.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    CorrectionRelation,
    DocumentType,
    validate_document_number as schema_validate_document_number,
    validate_legal_id as schema_validate_legal_id,
    validate_publication_date as schema_validate_publication_date,
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

_DOCUMENT_NUMBER_RE = re.compile(r"^[0-9]{4}-[0-9]{4,6}$")
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

PathLike = Union[str, Path]
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
    def coerce(cls, value: Any) -> "SourceFormat":
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
    def coerce(cls, value: Any) -> "IdentityDisposition":
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


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterIdentityError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterIdentityError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _stable_hex(material: str, *, salt: str = "") -> str:
    payload = f"{salt}:{material}" if salt else material
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_document_number(value: Any) -> str:
    """Normalize a Federal Register document number (``YYYY-NNNNN``)."""

    text = _require_non_empty_str(value, "document_number")
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(
            f"document_number must not be positional: {value!r}"
        )
    # Accept common spacing variants: "2020 - 12345" → "2020-12345".
    text = re.sub(r"\s+", "", text)
    if text.lower().startswith("fr-"):
        text = text[3:]
    if text.lower().startswith("document:"):
        text = text.split(":", 1)[1]
    # Strip leading zeros on the numeric suffix only when the whole suffix is
    # numeric and longer than required — FR numbers keep zero padding as-is
    # when already well-formed (YYYY-NNNNN with 4–6 digit suffix).
    if not _DOCUMENT_NUMBER_RE.fullmatch(text):
        # Try zero-padding a short numeric suffix: 2020-123 → 2020-0123
        match = re.fullmatch(r"([0-9]{4})-([0-9]{1,6})", text)
        if match:
            year, suffix = match.group(1), match.group(2)
            text = f"{year}-{suffix.zfill(4)}"
    try:
        return schema_validate_document_number(text)
    except Exception as exc:  # noqa: BLE001 - rewrap as identity error
        raise IdentityParseError(str(exc)) from exc


def normalize_publication_date(value: Any) -> str:
    """Normalize an official publication calendar date (``YYYY-MM-DD``)."""

    text = _require_non_empty_str(value, "publication_date")
    text = text.replace("/", "-").replace(".", "-")
    # Accept bare YYYYMMDD.
    if re.fullmatch(r"[0-9]{8}", text):
        text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return schema_validate_publication_date(text)
    except Exception as exc:  # noqa: BLE001
        raise IdentityParseError(str(exc)) from exc


def normalize_year_month(value: Any, *, publication_date: Optional[str] = None) -> str:
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
        return schema_validate_year_month(text)
    except Exception as exc:  # noqa: BLE001
        raise IdentityParseError(str(exc)) from exc


def normalize_effective_date(value: Any) -> Optional[str]:
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
    """Normalize an official source format token."""

    return SourceFormat.coerce(value).value


def normalize_document_type(value: Any) -> str:
    """Normalize a Federal Register document type."""

    if value is None or value == "":
        return DEFAULT_DOCUMENT_TYPE
    try:
        return DocumentType.coerce(value).value
    except Exception as exc:  # noqa: BLE001
        raise IdentityParseError(str(exc)) from exc


def normalize_correction_relation(value: Any) -> str:
    """Normalize a correction / withdrawal relation token."""

    if value is None or value == "":
        return DEFAULT_CORRECTION_RELATION
    try:
        return CorrectionRelation.coerce(value).value
    except Exception as exc:  # noqa: BLE001
        raise IdentityParseError(str(exc)) from exc


def _normalize_qualifier_value(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    text = _require_non_empty_str(value, name).lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9._-]", "", text)
    if not text or not _QUALIFIER_TOKEN_RE.fullmatch(text):
        raise IdentityParseError(
            f"{name} must match [a-z0-9][a-z0-9._-]{{0,63}}; got {value!r}"
        )
    return text


def _format_qualifiers(components: Mapping[str, Optional[str]]) -> str:
    parts: list[str] = []
    for key in _QUALIFIER_KEYS:
        value = components.get(key)
        if value is None or value == "":
            continue
        if key == "type" and value == DEFAULT_DOCUMENT_TYPE:
            # Default notice type is omitted for compact legal_id.
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
    document_type: str = DEFAULT_DOCUMENT_TYPE
    correction_relation: str = DEFAULT_CORRECTION_RELATION
    related_document_number: Optional[str] = None
    year_month: Optional[str] = None
    effective_date: Optional[str] = None
    source_format: str = DEFAULT_SOURCE_FORMAT
    edition: Optional[str] = None
    granule: Optional[str] = None
    part: Optional[str] = None
    include_type_qualifier: bool = field(default=False, compare=False, hash=False)
    include_correction_qualifier: bool = field(default=False, compare=False, hash=False)
    source_document_number: Optional[str] = field(
        default=None, compare=False, hash=False
    )

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
            normalize_year_month(self.year_month, publication_date=self.publication_date),
        )
        object.__setattr__(
            self, "effective_date", normalize_effective_date(self.effective_date)
        )
        object.__setattr__(
            self, "source_format", normalize_source_format(self.source_format)
        )
        object.__setattr__(self, "edition", _normalize_qualifier_value(self.edition, "edition"))
        object.__setattr__(self, "granule", _normalize_qualifier_value(self.granule, "granule"))
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
        qualifiers: dict[str, Optional[str]] = {
            "edition": self.edition,
            "granule": self.granule,
            "part": self.part,
            "related": None,
            "rel": None,
            "type": None,
        }
        if self.include_type_qualifier or (
            self.document_type
            not in {DEFAULT_DOCUMENT_TYPE, DocumentType.UNKNOWN.value}
            and self.document_type == DocumentType.CORRECTION.value
        ):
            # Always surface correction type when the document is a correction.
            if self.include_type_qualifier or self.document_type == DocumentType.CORRECTION.value:
                qualifiers["type"] = self.document_type
        if self.include_correction_qualifier and self.correction_relation != DEFAULT_CORRECTION_RELATION:
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
            source_format=self.source_format,
            edition=self.edition,
            granule=None,
            part=None,
            include_type_qualifier=self.include_type_qualifier,
            include_correction_qualifier=self.include_correction_qualifier,
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
            "source_format": self.source_format,
            "year_month": self.year_month,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegalIdentity":
        if not isinstance(value, Mapping):
            raise FederalRegisterIdentityError("identity payload must be a mapping")
        document_number = value.get("document_number")
        if document_number is None:
            document_number = value.get("documentNumber") or value.get("doc_number")
        publication_date = value.get("publication_date")
        if publication_date is None:
            publication_date = (
                value.get("publicationDate")
                or value.get("pub_date")
                or value.get("date")
            )
        related = value.get("related_document_number")
        if related is None:
            related = value.get("relatedDocumentNumber") or value.get("related_document")
        source_format = value.get("source_format")
        if source_format is None:
            source_format = value.get("format") or value.get("content_format")
        include_type = bool(
            value.get("include_type_qualifier")
            or value.get("type_in_legal_id")
            or (value.get("document_type") == DocumentType.CORRECTION.value)
        )
        include_correction = bool(
            value.get("include_correction_qualifier")
            or value.get("correction_in_legal_id")
        )
        # If an explicit legal_id is present with qualifiers, prefer parsing it.
        existing = value.get("legal_id")
        if isinstance(existing, str) and existing.strip().lower().startswith(
            f"{LEGAL_ID_PREFIX}:"
        ):
            try:
                parsed = parse_legal_id(existing.strip())
                # Overlay row fields that parse_legal_id may not carry.
                return LegalIdentity(
                    document_number=document_number or parsed.document_number,
                    publication_date=publication_date or parsed.publication_date,
                    document_type=value.get("document_type") or parsed.document_type,
                    correction_relation=value.get("correction_relation")
                    or parsed.correction_relation,
                    related_document_number=related or parsed.related_document_number,
                    year_month=value.get("year_month") or parsed.year_month,
                    effective_date=value.get("effective_date")
                    if "effective_date" in value
                    else parsed.effective_date,
                    source_format=source_format or parsed.source_format,
                    edition=value.get("edition") or parsed.edition,
                    granule=value.get("granule") or parsed.granule,
                    part=value.get("part") or parsed.part,
                    include_type_qualifier=include_type or parsed.include_type_qualifier,
                    include_correction_qualifier=(
                        include_correction or parsed.include_correction_qualifier
                    ),
                    source_document_number=str(document_number)
                    if document_number is not None
                    else parsed.source_document_number,
                )
            except FederalRegisterIdentityError:
                pass
        if document_number is None or publication_date is None:
            raise IdentityParseError(
                "document_number and publication_date are required for identity"
            )
        return cls(
            document_number=document_number,
            publication_date=publication_date,
            document_type=value.get("document_type") or value.get("type") or DEFAULT_DOCUMENT_TYPE,
            correction_relation=value.get("correction_relation")
            or value.get("relation")
            or DEFAULT_CORRECTION_RELATION,
            related_document_number=related,
            year_month=value.get("year_month"),
            effective_date=value.get("effective_date"),
            source_format=source_format or DEFAULT_SOURCE_FORMAT,
            edition=value.get("edition"),
            granule=value.get("granule") or value.get("granule_id"),
            part=value.get("part"),
            include_type_qualifier=include_type,
            include_correction_qualifier=include_correction,
            source_document_number=str(document_number),
        )


def build_legal_id(
    document_number: Any,
    publication_date: Any,
    *,
    document_type: Any = DEFAULT_DOCUMENT_TYPE,
    correction_relation: Any = DEFAULT_CORRECTION_RELATION,
    related_document_number: Any = None,
    edition: Any = None,
    granule: Any = None,
    part: Any = None,
    include_type_qualifier: bool = False,
    include_correction_qualifier: bool = False,
    qualifier: Any = None,
) -> str:
    """Build a stable ``legal_id`` from publication components.

    Optional free-form *qualifier* is appended as a single trailing segment
    (lower-cased) when no structured qualifiers are present.
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
        include_type_qualifier=include_type_qualifier,
        include_correction_qualifier=include_correction_qualifier,
    )
    legal_id = identity.legal_id
    if qualifier is not None and str(qualifier).strip():
        q = _normalize_qualifier_value(qualifier, "qualifier")
        if q and f"={q}" not in legal_id and f":{q}" not in legal_id:
            # Free-form qualifier as trailing segment (schema allows :.+).
            if legal_id.count(":") == 2:
                legal_id = f"{legal_id}:{q}"
            else:
                legal_id = f"{legal_id}:{q}"
    # Ensure schema contract is satisfied.
    return schema_validate_legal_id(legal_id)


def build_canonical_citation(
    document_number: Any,
    publication_date: Any,
    **kwargs: Any,
) -> str:
    """Build a compact human-readable Federal Register citation."""

    return LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        **{
            k: v
            for k, v in kwargs.items()
            if k
            in {
                "document_type",
                "correction_relation",
                "related_document_number",
                "effective_date",
                "source_format",
                "edition",
                "granule",
                "part",
            }
        },
    ).canonical_citation


def build_chunk_parent_id(
    document_number: Any,
    publication_date: Any,
    **kwargs: Any,
) -> str:
    """Return the deterministic parent identity for semantic text chunks."""

    return LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        **{
            k: v
            for k, v in kwargs.items()
            if k
            in {
                "document_type",
                "correction_relation",
                "related_document_number",
                "edition",
                "granule",
                "part",
                "include_type_qualifier",
                "include_correction_qualifier",
            }
        },
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

    text = _require_non_empty_str(legal_id, "legal_id")
    if _POSITIONAL_ID_RE.fullmatch(text):
        raise PositionalIdentityError(f"legal_id must not be positional: {legal_id!r}")
    normalized = schema_validate_legal_id(text)
    parts = normalized.split(":")
    if len(parts) < 3 or parts[0].lower() != LEGAL_ID_PREFIX:
        raise IdentityParseError(
            f"legal_id must match fr:<document_number>:<publication_date>"
            f"[:qualifier...]; got {legal_id!r}"
        )
    document_number = parts[1]
    publication_date = parts[2]
    document_type = DEFAULT_DOCUMENT_TYPE
    correction_relation = DEFAULT_CORRECTION_RELATION
    related_document_number: Optional[str] = None
    edition: Optional[str] = None
    granule: Optional[str] = None
    part: Optional[str] = None
    include_type = False
    include_correction = False
    for segment in parts[3:]:
        if "=" in segment:
            key, value = segment.split("=", 1)
            key = key.lower()
            if key == "type":
                document_type = value
                include_type = True
            elif key == "rel":
                correction_relation = value
                include_correction = True
            elif key == "related":
                related_document_number = value
                include_correction = True
            elif key == "edition":
                edition = value
            elif key == "granule":
                granule = value
            elif key == "part":
                part = value
            # Unknown key=value segments are ignored for round-trip fields.
        else:
            # Free-form trailing qualifier — store as granule if unset.
            if granule is None:
                granule = segment
    return LegalIdentity(
        document_number=document_number,
        publication_date=publication_date,
        document_type=document_type,
        correction_relation=correction_relation,
        related_document_number=related_document_number,
        edition=edition,
        granule=granule,
        part=part,
        include_type_qualifier=include_type,
        include_correction_qualifier=include_correction,
    )


def identity_from_row(row: Mapping[str, Any]) -> LegalIdentity:
    """Build a :class:`LegalIdentity` from a corpus/fixture row mapping."""

    return LegalIdentity.from_mapping(row)


def legal_id_from_row(row: Mapping[str, Any]) -> str:
    """Return ``legal_id`` for a row mapping (uses existing field when present)."""

    existing = row.get("legal_id")
    if isinstance(existing, str) and existing.strip():
        text = existing.strip()
        if _POSITIONAL_ID_RE.fullmatch(text):
            raise PositionalIdentityError(
                f"legal_id must not be positional: {text!r}"
            )
        if text.lower().startswith(f"{LEGAL_ID_PREFIX}:"):
            return parse_legal_id(text).legal_id
    return identity_from_row(row).legal_id


# ---------------------------------------------------------------------------
# Content / source / entry identity
# ---------------------------------------------------------------------------


def compute_source_cid(
    document_number: Any,
    publication_date: Any,
    *,
    source_format: Any = DEFAULT_SOURCE_FORMAT,
    official_source_url: Any = None,
    source_checksum: Any = None,
    body: Any = None,
) -> str:
    """Compute a deterministic ``source_cid`` for normalized official evidence.

    Prefers an explicit ``source_checksum`` / body digest when present so
    identical official bytes yield the same source address regardless of URL
    packaging variants. Format participates so html/pdf of different bytes
    remain distinct while same-bytes multi-URL packaging stays stable.
    """

    doc = normalize_document_number(document_number)
    pub = normalize_publication_date(publication_date)
    fmt = normalize_source_format(source_format)
    if source_checksum is not None and str(source_checksum).strip():
        checksum = str(source_checksum).strip().lower()
        if checksum.startswith("sha256:"):
            checksum = checksum[7:]
        material = f"fr-source|{doc}|{pub}|{fmt}|checksum:{checksum}"
    elif isinstance(body, (bytes, bytearray)):
        digest = hashlib.sha256(bytes(body)).hexdigest()
        material = f"fr-source|{doc}|{pub}|{fmt}|body:{digest}"
    elif isinstance(body, str) and body:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        material = f"fr-source|{doc}|{pub}|{fmt}|body:{digest}"
    else:
        url = str(official_source_url or "").strip().lower()
        material = f"fr-source|{doc}|{pub}|{fmt}|url:{url}"
    digest = _stable_hex(material, salt="lcr-054-source")
    return f"bafkreis{digest[:47]}"


def compute_entry_cid(
    document_number: Any,
    publication_date: Any,
    *,
    content_token: Any = None,
    text: Any = None,
    source_cid: Any = None,
    legal_id: Any = None,
) -> str:
    """Compute a deterministic ``entry_cid`` for a retrieval record.

    Content version participates so changed-text versions under the same
    ``legal_id`` receive distinct primary keys.
    """

    doc = normalize_document_number(document_number)
    pub = normalize_publication_date(publication_date)
    lid = str(legal_id or f"{LEGAL_ID_PREFIX}:{doc}:{pub}").strip().lower()
    if content_token is not None and str(content_token).strip():
        token = str(content_token).strip().lower()
    elif isinstance(text, str) and text.strip():
        token = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    elif source_cid is not None and str(source_cid).strip():
        token = str(source_cid).strip().lower()
    else:
        token = "empty"
    material = f"fr-entry|{lid}|{token}"
    digest = _stable_hex(material, salt="lcr-054-entry")
    return f"bafkreie{digest[:47]}"


def content_identity_from_row(row: Mapping[str, Any]) -> str:
    """Return the content-version identity for a row.

    Used to distinguish changed-text versions under the same ``legal_id``.
    Prefer body evidence (``content_cid``, then text digest) so two retrieval
    rows with different ``entry_cid`` values but identical body text are
    classified as logical duplicates. Fall back to ``source_cid`` / ``entry_cid``
    only when no body evidence is present.
    """

    for field_name in ("content_cid",):
        value = row.get(field_name)
        if (
            isinstance(value, str)
            and value.strip()
            and not _POSITIONAL_ID_RE.fullmatch(value.strip())
        ):
            return value.strip().lower()
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    for field_name in ("source_checksum", "official_content_hash"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            text_value = value.strip().lower()
            if text_value.startswith("sha256:"):
                return text_value
            if re.fullmatch(r"[0-9a-f]{64}", text_value):
                return f"sha256:{text_value}"
    for field_name in ("source_cid", "entry_cid", "ipfs_cid"):
        value = row.get(field_name)
        if (
            isinstance(value, str)
            and value.strip()
            and not _POSITIONAL_ID_RE.fullmatch(value.strip())
        ):
            return value.strip().lower()
    return "sha256:" + hashlib.sha256(b"").hexdigest()


def body_content_token(row: Mapping[str, Any]) -> Optional[str]:
    """Return a body/content token that must not merge distinct legal identities."""

    for field_name in ("content_cid", "ipfs_cid"):
        value = row.get(field_name)
        if (
            isinstance(value, str)
            and value.strip()
            and not _POSITIONAL_ID_RE.fullmatch(value.strip())
        ):
            return f"cid:{value.strip().lower()}"
    text = row.get("text")
    if isinstance(text, str) and text.strip():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"text:{digest}"
    for field_name in ("source_checksum", "official_content_hash"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            return f"checksum:{value.strip().lower()}"
    return None


def row_position_token(row: Mapping[str, Any]) -> Optional[str]:
    """Return a positional index token if present (not durable identity)."""

    for field_name in ("document_index", "row_index", "row_id", "index", "offset"):
        value = row.get(field_name)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if field_name == "row_id" and not re.fullmatch(
            r"(?:row[-_]?)?\d+", text, re.I
        ):
            # Human fixture row_ids such as "seed-correction-original" are not positions.
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
    value = row.get("source_format") or row.get("format") or row.get("content_format")
    if value is None or value == "":
        return DEFAULT_SOURCE_FORMAT
    return normalize_source_format(value)


def _effective_date_token(row: Mapping[str, Any]) -> str:
    """Return a sortable effective-date token; unknown sorts as empty string."""

    if "effective_date" not in row:
        return ""
    normalized = normalize_effective_date(row.get("effective_date"))
    return normalized or ""


def _acquisition_time_token(row: Mapping[str, Any]) -> str:
    value = row.get("acquisition_time") or row.get("acquired_at") or ""
    return str(value).strip()


def _row_stability_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Order-independent stability key for resume-safe reconciliation."""

    return (
        legal_id_from_row(row),
        content_identity_from_row(row),
        f"{source_format_priority(_source_format_of(row)):02d}",
        _source_format_of(row),
        _entry_cid_of(row),
        _source_cid_of(row),
        _acquisition_time_token(row),
        _effective_date_token(row),
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
    right_related = right.get("related_document_number") or right.get("related_document")
    left_doc = str(left.get("document_number") or "").strip()
    right_doc = str(right.get("document_number") or "").strip()
    correction_linked = False
    try:
        if left_related and right_doc and normalize_document_number(
            left_related
        ) == normalize_document_number(right_doc):
            correction_linked = True
        if right_related and left_doc and normalize_document_number(
            right_related
        ) == normalize_document_number(left_doc):
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
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group rows by durable ``legal_id`` and assign deterministic dispositions.

    Reconciliation is **order-independent**: rows are sorted by a stability key
    before grouping so resume / reordered inputs yield identical current and
    history sets.

    * Within a ``legal_id`` group, identical content identities with the same
      source format are ``duplicate``; identical content with different source
      formats are ``duplicate_source_format`` (preferred format kept).
    * Differing content identities become one ``keep_current`` (deterministic
      max by acquisition time / content id / entry_cid) plus ``archive_history``.
    * Unknown effective dates are preserved on retained rows and never filled.
    * Rows that only share content CID or only share row position across
      different legal_ids are **not** merged.
    """

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise FederalRegisterIdentityError("rows must be a sequence of mappings")

    # Materialize and sort for order-independent resume semantics.
    material: list[tuple[int, Mapping[str, Any]]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FederalRegisterIdentityError(f"row {index} must be a mapping")
        material.append((index, row))
    material.sort(key=lambda item: _row_stability_key(item[1]) + (f"{item[0]:08d}",))

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

        # Deterministic content version ranking: prefer later acquisition_time,
        # then lexicographically greater content id, then entry_cid. Unknown
        # effective dates do not invent ordering.
        def _content_rank(cid: str) -> tuple[str, str, str]:
            cohort = by_content[cid]
            best = min(
                cohort,
                key=lambda item: (
                    f"{source_format_priority(_source_format_of(item[1])):02d}",
                    _entry_cid_of(item[1]),
                ),
            )
            row = best[1]
            return (
                _acquisition_time_token(row),
                cid,
                _entry_cid_of(row),
            )

        content_order = sorted(content_order, key=_content_rank)

        history: list[dict[str, Any]] = []
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
                        "source_format": _source_format_of(primary_row),
                        "disposition": IdentityDisposition.KEEP_CURRENT.value,
                    }
                )
            else:
                hist_entry = {
                    "logical_key": legal_id,
                    "legal_id": legal_id,
                    "content_id": cid,
                    "entry_cid": str(
                        primary_row.get("entry_cid")
                        or primary_row.get("source_cid")
                        or primary_row.get("content_cid")
                        or cid
                    ),
                    "source_format": _source_format_of(primary_row),
                    "disposition": IdentityDisposition.ARCHIVE_HISTORY.value,
                    "row_index": primary_index,
                }
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
                dispositions.append(
                    {
                        "legal_id": legal_id,
                        "row_index": dup_index,
                        "content_id": cid,
                        "source_format": _source_format_of(dup_row),
                        "disposition": dup_disposition.value,
                        "duplicate_of_row_index": primary_index,
                        "preferred_source_format": _source_format_of(primary_row),
                    }
                )

        history_by_key[legal_id] = history

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
                    "disposition": IdentityDisposition.REJECT_CONTENT_CID_ONLY_MERGE.value,
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
        "history_by_key": history_by_key,
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
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge rows by durable legal identity with explicit version dispositions.

    Content changes under the same ``legal_id`` replace the current row and
    archive the prior content identity. Content CID alone, source format alone
    across distinct documents, or row position alone never merges distinct
    legal identities. Result is order-independent for resume safety.
    """

    combined: list[Mapping[str, Any]] = list(existing_rows or ())
    if new_rows:
        combined.extend(list(new_rows))
    return resolve_version_dispositions(combined)


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

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FederalRegisterIdentityError(f"row {index} must be a mapping")
        if key_field not in row or row[key_field] in (None, ""):
            raise FederalRegisterIdentityError(
                f"row {index} missing required primary key field {key_field!r}"
            )
        key = str(row[key_field]).strip()
        if not key:
            raise FederalRegisterIdentityError(f"row {index} has empty {key_field}")
        if _POSITIONAL_ID_RE.fullmatch(key):
            raise PositionalIdentityError(
                f"row {index} primary key must not be positional: {key!r}"
            )
        if key in seen:
            raise DuplicatePrimaryKeyError(
                f"duplicate primary key {key_field}={key!r} at rows "
                f"{seen[key]} and {index}"
            )
        seen[key] = index


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

    legal_ids: list[str] = []
    seen: dict[str, tuple[int, str]] = {}
    for index, row in enumerate(rows):
        legal_id = legal_id_from_row(row)
        content_id = content_identity_from_row(row)
        if legal_id in seen:
            if not allow_version_collisions:
                prior_index, _prior_content = seen[legal_id]
                raise FederalRegisterIdentityError(
                    f"legal_id collision for {legal_id!r} at rows "
                    f"{prior_index} and {index}"
                )
        else:
            seen[legal_id] = (index, content_id)
        legal_ids.append(legal_id)
    return legal_ids


def enrich_row_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *row* with legal_id / entry_cid / source_cid filled.

    Existing non-positional identity fields are preserved. Missing fields are
    computed deterministically from publication components and body evidence.
    """

    if not isinstance(row, Mapping):
        raise FederalRegisterIdentityError("row must be a mapping")
    out = dict(row)
    identity = identity_from_row(out)
    out["document_number"] = identity.document_number
    out["publication_date"] = identity.publication_date
    out["year_month"] = identity.year_month
    out["document_type"] = identity.document_type
    out["correction_relation"] = identity.correction_relation
    if identity.related_document_number is not None:
        out["related_document_number"] = identity.related_document_number
    out["source_format"] = identity.source_format
    if "effective_date" in row:
        out["effective_date"] = identity.effective_date
    out["legal_id"] = identity.legal_id
    out["canonical_citation"] = identity.canonical_citation
    out["parent_legal_id"] = identity.parent_legal_id

    if not out.get("source_cid"):
        out["source_cid"] = compute_source_cid(
            identity.document_number,
            identity.publication_date,
            source_format=identity.source_format,
            official_source_url=out.get("official_source_url"),
            source_checksum=out.get("source_checksum") or out.get("official_content_hash"),
            body=out.get("text"),
        )
    if not out.get("entry_cid"):
        out["entry_cid"] = compute_entry_cid(
            identity.document_number,
            identity.publication_date,
            text=out.get("text"),
            content_token=out.get("content_cid"),
            source_cid=out.get("source_cid"),
            legal_id=out["legal_id"],
        )
    return out


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
    """Deterministic fake entry_cid (CIDv1-shaped) for fixture rows."""

    digest = _stable_hex(f"{salt}:{index}", salt="entry")
    return f"bafkreie{digest[:47]}"


def _synthetic_source_cid(index: int, *, salt: str = "lcr-054") -> str:
    digest = _stable_hex(f"{salt}:{index}", salt="source")
    return f"bafkreis{digest[:47]}"


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
                        row["include_type_qualifier"] = True
                        row["include_correction_qualifier"] = True
                    rows.append(row)

        elif kind == "source_format_duplicates":
            formats = list(
                generator.get("formats") or ["html", "pdf", "xml"]
            )
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
                            "acquisition_time": (
                                f"{pub}T0{local_index}:00:00Z"
                            ),
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
                        year, 1 + (pair_index % 6), 1 + local_index * 10 + (pair_index % 5)
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
                        year, 1 + (pair_index % 12), 1 + ((pair_index + local_index) % 28)
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
                        year, 1 + (pair_index % 12), 1 + ((pair_index + local_index) % 28)
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
                generator.get("unknown_tokens")
                or ["unknown", "n/a", "tbd", None, ""]
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
                orig_doc = _doc_number(
                    year, (serial_start + pair_index * 2) % 100000
                )
                wd_doc = _doc_number(
                    year, (serial_start + pair_index * 2 + 1) % 100000
                )
                orig_date = _pub_date(year, 2 + (pair_index % 10), 1 + (pair_index % 28))
                wd_date = _pub_date(year, 2 + (pair_index % 10), min(2 + (pair_index % 27), 28))
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

    for index, row in enumerate(rows):
        if "entry_cid" not in row or not row["entry_cid"]:
            row["entry_cid"] = _synthetic_entry_cid(index)
        if "source_cid" not in row or not row["source_cid"]:
            row["source_cid"] = _synthetic_source_cid(index)
        identity = identity_from_row(row)
        row["legal_id"] = identity.legal_id
        row["canonical_citation"] = identity.canonical_citation
        row["parent_legal_id"] = identity.parent_legal_id
        row["document_number"] = identity.document_number
        row["publication_date"] = identity.publication_date
        row["year_month"] = identity.year_month
        row["document_type"] = identity.document_type
        row["source_format"] = identity.source_format
        if "effective_date" in row:
            row["normalized_effective_date"] = identity.effective_date
        # Validate legal_id against release schema contract.
        schema_validate_legal_id(row["legal_id"])

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
    return [dict(item) for item in cases if isinstance(item, Mapping)]


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
                "expected_disposition": (
                    IdentityDisposition.CORRECTION_DISTINCT.value
                ),
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
                "content_cid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "text": "shared boilerplate",
                "source_format": "html",
            },
            {
                "row_id": "seed-cid-b",
                "collision_family": "seed-cid-only",
                "document_number": "2022-66667",
                "publication_date": "2022-05-06",
                "document_type": "notice",
                "content_cid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "text": "shared boilerplate",
                "source_format": "html",
            },
        ],
    }


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "TASK_ID",
    "KNOWN_COLLISION_ROW_COUNT",
    "LEGAL_ID_PREFIX",
    "DEFAULT_DOCUMENT_TYPE",
    "DEFAULT_CORRECTION_RELATION",
    "DEFAULT_SOURCE_FORMAT",
    "FederalRegisterIdentityError",
    "IdentityParseError",
    "DuplicatePrimaryKeyError",
    "CollisionFixtureError",
    "IdentityDispositionError",
    "PositionalIdentityError",
    "SourceFormat",
    "IdentityDisposition",
    "LegalIdentity",
    "normalize_document_number",
    "normalize_publication_date",
    "normalize_year_month",
    "normalize_effective_date",
    "normalize_source_format",
    "normalize_document_type",
    "normalize_correction_relation",
    "source_format_priority",
    "build_legal_id",
    "build_canonical_citation",
    "build_chunk_parent_id",
    "parse_chunk_id",
    "parse_legal_id",
    "identity_from_row",
    "legal_id_from_row",
    "compute_source_cid",
    "compute_entry_cid",
    "content_identity_from_row",
    "body_content_token",
    "row_position_token",
    "classify_identity_pair",
    "resolve_version_dispositions",
    "merge_by_legal_identity",
    "reject_positional_or_cid_only_merge",
    "validate_primary_keys",
    "assert_legal_ids_distinguishable",
    "enrich_row_identity",
    "default_collision_fixture_path",
    "expand_collision_fixture",
    "load_collision_fixture",
    "load_collision_fixture_payload",
    "disposition_cases",
    "build_default_collision_fixture_payload",
]
