"""Public patent-law and regulations corpus materializer (PATLAW-170).

Materializes a deterministic, content-addressed public-official projection
covering eCFR/CFR, U.S. Code / Public Law / Federal Register, and MPEP /
examination guidance. The projection is suitable as the corpus root for
BM25, vector, and knowledge-graph index builders (PATLAW-171..173).

Design invariants
-----------------
* Repeat materializations for identical source roots are content-address stable.
* Private, mixed, unknown, or unreviewed inputs fail **closed** before any
  filesystem staging or CID publication.
* Unreviewed AI-derived text cannot enter as authoritative law.
* Manifests bind source roots, document counts, and CIDs needed by downstream
  index builders (corpus root + per-document / per-source joins).
* No network I/O on import or fixture replay; live acquisition is owned by
  PATLAW-128 / 131 / 132 processors.
* Default mode is dry-run (in-memory only); explicit ``stage=True`` writes
  local artifacts only — never Hub upload.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ....logic.ir_core.identity import cid_v1_from_digest
from .release_policy import (
    PRIVATE_CLASSIFICATIONS,
    PUBLIC_CLASSIFICATIONS,
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
    is_private_classification,
)
from .retrieval_contracts import (
    AuthorityClaim,
    DisclosureClass,
    claims_source_authority,
    is_private_disclosure,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.public_legal_corpus.v1"
INTERFACE: Final = "PublicLegalCorpusMaterializer@1"
PRODUCER: Final = "producer:public-legal-corpus-materializer"
CONFIG_ID: Final = "config:public-legal-corpus/v1"
TASK_ID: Final = "PATLAW-170"
GOAL_ID: Final = "PATLAW-G211"
CODE_VERSION: Final = "1.0.0"

MANIFEST_FILENAME: Final = "public-legal-corpus.manifest.json"
DOCUMENTS_FILENAME: Final = "documents.jsonl"
SOURCE_RECEIPTS_FILENAME: Final = "source-receipts.json"
CORPUS_ROOT_FILENAME: Final = "corpus-root.json"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

# Official public-law / regulation families for Hub corpus materialization.
SOURCE_FAMILIES: Final[tuple[str, ...]] = (
    "ecfr",
    "cfr",
    "uscode",
    "public_law",
    "federal_register",
    "mpep",
    "guidance",
)
SOURCE_FAMILY_SET: Final[frozenset[str]] = frozenset(SOURCE_FAMILIES)

# Authority kinds allowed on public legal corpus rows (independent of family).
AUTHORITY_KINDS: Final[frozenset[str]] = frozenset(
    {
        "statute",
        "regulation",
        "guidance",
        "editorial_aid",
        "public_law",
        "federal_register",
    }
)

# Family → default authority kind when the row omits one.
_FAMILY_DEFAULT_AUTHORITY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ecfr": "regulation",
        "cfr": "regulation",
        "uscode": "statute",
        "public_law": "public_law",
        "federal_register": "federal_register",
        "mpep": "guidance",
        "guidance": "guidance",
    }
)

PUBLIC_CLASSIFICATION_SET: Final[frozenset[str]] = frozenset(PUBLIC_CLASSIFICATIONS)
PRIVATE_CLASSIFICATION_SET: Final[frozenset[str]] = frozenset(PRIVATE_CLASSIFICATIONS)

# Fields stripped from content digests so wall-clock metadata cannot drift CIDs.
_NON_CONTENT_MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "staged_at_utc",
        "notes",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicLegalCorpusError(ValueError):
    """Base error for public legal corpus materialization."""

    code: str = "public_legal_corpus_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class PrivateOrMixedInputError(PublicLegalCorpusError):
    """Raised when private, mixed, or unknown disclosure material is present."""

    code = "private_or_mixed_input"


class UnreviewedRightsError(PublicLegalCorpusError):
    """Raised when a document lacks a reviewed rights/redistribution grant."""

    code = "unreviewed_rights"


class MissingSourceReceiptError(PublicLegalCorpusError):
    """Raised when source lineage or current-through binding is incomplete."""

    code = "missing_source_receipt"


class CorpusIntegrityError(PublicLegalCorpusError):
    """Raised when counts, digests, or CIDs fail integrity checks."""

    code = "corpus_integrity"


class SchemaValidationError(PublicLegalCorpusError):
    """Raised when a document or root descriptor fails structural validation."""

    code = "schema_validation"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceFamily(str, Enum):
    """Closed set of public patent-law / regulation source families."""

    ECFR = "ecfr"
    CFR = "cfr"
    USCODE = "uscode"
    PUBLIC_LAW = "public_law"
    FEDERAL_REGISTER = "federal_register"
    MPEP = "mpep"
    GUIDANCE = "guidance"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFamily":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "e_cfr": "ecfr",
            "title_37": "cfr",
            "usc": "uscode",
            "us_code": "uscode",
            "plaw": "public_law",
            "pub_law": "public_law",
            "fr": "federal_register",
            "fed_reg": "federal_register",
            "uspto_guidance": "guidance",
            "examination_guidance": "guidance",
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError as exc:
            raise SchemaValidationError(
                f"unsupported source family: {value!r}; "
                f"expected one of {', '.join(SOURCE_FAMILIES)}"
            ) from exc


class MaterializationMode(str, Enum):
    """How materialization is executed."""

    DRY_RUN = "dry_run"
    STAGE = "stage"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing and equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid_of(value: Any) -> str:
    """CIDv1 (dag-pb / sha2-256) of the canonical JSON encoding of *value*."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).digest()
    return cid_v1_from_digest(digest)


def content_cid_of_bytes(payload: bytes) -> str:
    """CIDv1 of raw *payload* bytes."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return cid_v1_from_digest(hashlib.sha256(bytes(payload)).digest())


def _require_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise SchemaValidationError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise SchemaValidationError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if value is None or value == "":
        return ""
    return _require_str(value, name, maximum=maximum)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_str(value, name, maximum=64).lower()
    if not _SHA256_RE.fullmatch(text):
        raise SchemaValidationError(
            f"{name} must be a lowercase 64-char hex SHA-256"
        )
    return text


def _require_cid(value: Any, name: str = "cid") -> str:
    text = _require_str(value, name, maximum=256)
    if not _CID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} is not a valid CIDv1: {text!r}")
    return text


def _require_record_id(value: Any, name: str = "record_id") -> str:
    text = _require_str(value, name, maximum=256)
    if not _RECORD_ID_RE.fullmatch(text):
        raise SchemaValidationError(f"{name} is not a valid identifier: {text!r}")
    return text


def _require_date_or_utc(value: Any, name: str) -> str:
    text = _require_str(value, name, maximum=64)
    if not (_DATE_RE.fullmatch(text) or _RFC3339_UTC_RE.fullmatch(text)):
        raise SchemaValidationError(
            f"{name} must be YYYY-MM-DD or RFC3339 UTC, got {text!r}"
        )
    return text


def _coerce_classification(value: Any) -> str:
    if isinstance(value, DisclosureClass):
        return value.value
    if isinstance(value, Enum):
        return str(value.value)
    text = _require_str(value, "classification", maximum=64).lower().replace("-", "_")
    # Align disclosure and release-policy naming.
    aliases = {
        "public": "public_official",
        "official": "public_official",
        "public_official_record": "public_official",
    }
    text = aliases.get(text, text)
    if text not in PUBLIC_CLASSIFICATION_SET | PRIVATE_CLASSIFICATION_SET | {
        "unknown"
    }:
        raise SchemaValidationError(f"unknown classification: {value!r}")
    return text


def _coerce_authority_claim(value: Any) -> AuthorityClaim:
    if isinstance(value, AuthorityClaim):
        return value
    text = str(value or AuthorityClaim.SOURCE_BOUND.value).strip().lower()
    try:
        return AuthorityClaim(text)
    except ValueError as exc:
        raise SchemaValidationError(f"invalid authority_claim: {value!r}") from exc


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass
    return path


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if tmp.exists():
                tmp.unlink()
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _safe_relative_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path or path.startswith("/") or path.endswith("/"):
        raise SchemaValidationError(f"invalid relative path: {value!r}")
    parts = tuple(part for part in PurePosixPath(path).parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise SchemaValidationError(f"unsafe relative path: {value!r}")
    return "/".join(parts)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRootBinding:
    """One pinned public source root contributing documents to the corpus.

    Bindings are content-addressed from their stable identity fields so that
    the same logical root always yields the same ``root_cid``.
    """

    source_id: str
    family: SourceFamily
    current_through: str
    official_edition_cutoff: str
    source_uri: str
    source_revision: str
    license_expression: str = "public-domain-US-government"
    root_sha256: str = ""
    root_cid: str = ""
    document_count: int = 0
    gaps: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        source_id = _require_str(self.source_id, "source_id", maximum=256)
        family = (
            self.family
            if isinstance(self.family, SourceFamily)
            else SourceFamily.coerce(self.family)
        )
        current = _require_date_or_utc(self.current_through, "current_through")
        cutoff = _require_date_or_utc(
            self.official_edition_cutoff, "official_edition_cutoff"
        )
        uri = _require_str(self.source_uri, "source_uri", maximum=2048)
        if not (
            uri.startswith("https://")
            or uri.startswith("govinfo://")
            or uri.startswith("uspto://")
            or uri.startswith("ipfs://")
            or uri.startswith("ecfr://")
            or uri.startswith("fixture://")
        ):
            raise SchemaValidationError(
                "source_uri must use https://, govinfo://, uspto://, "
                "ipfs://, ecfr://, or fixture://"
            )
        revision = _require_str(self.source_revision, "source_revision", maximum=256)
        if re.fullmatch(r"\s*latest\s*", revision, flags=re.IGNORECASE):
            raise SchemaValidationError(
                "source_revision must not be the hard-coded token 'latest'"
            )
        license_expression = _require_str(
            self.license_expression, "license_expression", maximum=256
        )
        gaps = tuple(
            _require_str(item, "gaps[]", maximum=512)
            for item in (self.gaps or ())
            if str(item).strip()
        )
        notes = _optional_str(self.notes, "notes", maximum=2048)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "current_through", current)
        object.__setattr__(self, "official_edition_cutoff", cutoff)
        object.__setattr__(self, "source_uri", uri)
        object.__setattr__(self, "source_revision", revision)
        object.__setattr__(self, "license_expression", license_expression)
        object.__setattr__(self, "gaps", gaps)
        object.__setattr__(self, "notes", notes)
        if type(self.document_count) is not int or self.document_count < 0:
            raise SchemaValidationError("document_count must be a non-negative int")

        identity = self._identity_payload()
        digest = content_digest_of(identity)
        cid = content_cid_of(identity)
        if self.root_sha256 and self.root_sha256 != digest:
            raise CorpusIntegrityError(
                f"root_sha256 mismatch for source_id={source_id!r}"
            )
        if self.root_cid and self.root_cid != cid:
            raise CorpusIntegrityError(
                f"root_cid mismatch for source_id={source_id!r}"
            )
        object.__setattr__(self, "root_sha256", digest)
        object.__setattr__(self, "root_cid", cid)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "current_through": self.current_through,
            "family": self.family.value
            if isinstance(self.family, SourceFamily)
            else str(self.family),
            "gaps": list(self.gaps),
            "license_expression": self.license_expression,
            "official_edition_cutoff": self.official_edition_cutoff,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
        }

    def with_document_count(self, count: int) -> "SourceRootBinding":
        if type(count) is not int or count < 0:
            raise SchemaValidationError("document_count must be a non-negative int")
        return SourceRootBinding(
            source_id=self.source_id,
            family=self.family,
            current_through=self.current_through,
            official_edition_cutoff=self.official_edition_cutoff,
            source_uri=self.source_uri,
            source_revision=self.source_revision,
            license_expression=self.license_expression,
            document_count=count,
            gaps=self.gaps,
            notes=self.notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_through": self.current_through,
            "document_count": self.document_count,
            "family": self.family.value,
            "gaps": list(self.gaps),
            "license_expression": self.license_expression,
            "notes": self.notes,
            "official_edition_cutoff": self.official_edition_cutoff,
            "root_cid": self.root_cid,
            "root_sha256": self.root_sha256,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceRootBinding":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("source root must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            family=SourceFamily.coerce(value.get("family", "")),
            current_through=value.get("current_through", ""),
            official_edition_cutoff=value.get(
                "official_edition_cutoff", value.get("current_through", "")
            ),
            source_uri=value.get("source_uri", ""),
            source_revision=value.get("source_revision", ""),
            license_expression=value.get(
                "license_expression", "public-domain-US-government"
            ),
            root_sha256=str(value.get("root_sha256") or ""),
            root_cid=str(value.get("root_cid") or ""),
            document_count=int(value.get("document_count") or 0),
            gaps=tuple(value.get("gaps") or ()),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalDocument:
    """One admitted public legal document projected into the corpus."""

    record_id: str
    family: SourceFamily
    classification: str
    text: str
    citation: str
    source_lineage: SourceLineage
    rights_review: RightsReview
    source_root_id: str
    current_through: str
    authority_kind: str = ""
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND
    title: str = ""
    section_id: str = ""
    effective_start: str = ""
    effective_end: str = ""
    media_type: str = "text/plain"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # AI-derived fields are retained only as non-authoritative candidates.
    ai_derived: Mapping[str, Any] = field(default_factory=dict)
    document_sha256: str = ""
    document_cid: str = ""
    source_cid: str = ""

    def __post_init__(self) -> None:
        record_id = _require_record_id(self.record_id)
        family = (
            self.family
            if isinstance(self.family, SourceFamily)
            else SourceFamily.coerce(self.family)
        )
        classification = _coerce_classification(self.classification)
        if classification not in PUBLIC_CLASSIFICATION_SET:
            raise PrivateOrMixedInputError(
                f"document {record_id!r} classification {classification!r} "
                "is not public; private/mixed/unknown inputs fail closed"
            )
        if is_private_classification(classification) or is_private_disclosure(
            classification
        ):
            raise PrivateOrMixedInputError(
                f"document {record_id!r} is private and cannot enter the "
                "public legal corpus"
            )
        text = self.text if isinstance(self.text, str) else ""
        if "\x00" in text:
            raise SchemaValidationError(f"document {record_id!r} text contains NUL")
        if not text.strip():
            raise SchemaValidationError(f"document {record_id!r} text is empty")
        if len(text) > 8_000_000:
            raise SchemaValidationError(
                f"document {record_id!r} text exceeds 8 MiB character limit"
            )
        citation = _require_str(self.citation, "citation", maximum=1024)
        if not isinstance(self.source_lineage, SourceLineage):
            raise SchemaValidationError("source_lineage must be SourceLineage")
        if not isinstance(self.rights_review, RightsReview):
            raise SchemaValidationError("rights_review must be RightsReview")
        if not self.rights_review.reviewed_for_release:
            raise UnreviewedRightsError(
                f"document {record_id!r} lacks reviewed redistribution rights"
            )
        source_root_id = _require_str(self.source_root_id, "source_root_id", maximum=256)
        current_through = _require_date_or_utc(self.current_through, "current_through")
        authority_kind = str(self.authority_kind or "").strip()
        if not authority_kind:
            authority_kind = _FAMILY_DEFAULT_AUTHORITY[family.value]
        if authority_kind not in AUTHORITY_KINDS:
            raise SchemaValidationError(
                f"unsupported authority_kind: {authority_kind!r}"
            )
        claim = _coerce_authority_claim(self.authority_claim)
        # AI-derived payloads may ride along only when authority_claim is not
        # source_bound; source-bound rows may not embed unreviewed AI as law.
        ai_payload = dict(self.ai_derived or {})
        if ai_payload and claims_source_authority(claim):
            raise PublicLegalCorpusError(
                f"document {record_id!r}: AI-derived fields cannot be "
                "source_bound authoritative law; set authority_claim to "
                "review_only or none, or omit ai_derived",
                code="ai_as_authoritative_law",
            )
        # Guidance / MPEP is never statute or regulation.
        if family in {SourceFamily.MPEP, SourceFamily.GUIDANCE}:
            if authority_kind in {"statute", "regulation", "public_law"}:
                raise SchemaValidationError(
                    f"document {record_id!r}: family {family.value} cannot "
                    f"claim authority_kind={authority_kind!r}"
                )
            if claim is AuthorityClaim.SOURCE_BOUND and authority_kind != "guidance":
                # Still allow source_bound for official guidance text itself.
                pass

        title = _optional_str(self.title, "title", maximum=1024)
        section_id = _optional_str(self.section_id, "section_id", maximum=256)
        effective_start = _optional_str(self.effective_start, "effective_start", maximum=64)
        effective_end = _optional_str(self.effective_end, "effective_end", maximum=64)
        if effective_start and not (
            _DATE_RE.fullmatch(effective_start)
            or _RFC3339_UTC_RE.fullmatch(effective_start)
        ):
            raise SchemaValidationError(
                f"effective_start must be YYYY-MM-DD or RFC3339 UTC: {effective_start!r}"
            )
        if effective_end and not (
            _DATE_RE.fullmatch(effective_end)
            or _RFC3339_UTC_RE.fullmatch(effective_end)
        ):
            raise SchemaValidationError(
                f"effective_end must be YYYY-MM-DD or RFC3339 UTC: {effective_end!r}"
            )
        media_type = _require_str(self.media_type or "text/plain", "media_type", maximum=128)
        metadata = MappingProxyType(dict(self.metadata or {}))
        ai_frozen = MappingProxyType(ai_payload)

        content = self._content_payload(
            record_id=record_id,
            family=family,
            classification=classification,
            text=text,
            citation=citation,
            source_lineage=self.source_lineage,
            rights_review=self.rights_review,
            source_root_id=source_root_id,
            current_through=current_through,
            authority_kind=authority_kind,
            authority_claim=claim,
            title=title,
            section_id=section_id,
            effective_start=effective_start,
            effective_end=effective_end,
            media_type=media_type,
            metadata=dict(metadata),
            ai_derived=dict(ai_frozen),
        )
        digest = content_digest_of(content)
        cid = content_cid_of(content)
        source_cid = content_cid_of(
            {
                "source_id": self.source_lineage.source_id,
                "source_revision": self.source_lineage.source_revision,
                "source_sha256": self.source_lineage.source_sha256,
                "source_uri": self.source_lineage.source_uri,
            }
        )
        if self.document_sha256 and self.document_sha256 != digest:
            raise CorpusIntegrityError(
                f"document_sha256 mismatch for record_id={record_id!r}"
            )
        if self.document_cid and self.document_cid != cid:
            raise CorpusIntegrityError(
                f"document_cid mismatch for record_id={record_id!r}"
            )
        if self.source_cid and self.source_cid != source_cid:
            raise CorpusIntegrityError(
                f"source_cid mismatch for record_id={record_id!r}"
            )

        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "citation", citation)
        object.__setattr__(self, "source_root_id", source_root_id)
        object.__setattr__(self, "current_through", current_through)
        object.__setattr__(self, "authority_kind", authority_kind)
        object.__setattr__(self, "authority_claim", claim)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "section_id", section_id)
        object.__setattr__(self, "effective_start", effective_start)
        object.__setattr__(self, "effective_end", effective_end)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "ai_derived", ai_frozen)
        object.__setattr__(self, "document_sha256", digest)
        object.__setattr__(self, "document_cid", cid)
        object.__setattr__(self, "source_cid", source_cid)

    @staticmethod
    def _content_payload(
        *,
        record_id: str,
        family: SourceFamily,
        classification: str,
        text: str,
        citation: str,
        source_lineage: SourceLineage,
        rights_review: RightsReview,
        source_root_id: str,
        current_through: str,
        authority_kind: str,
        authority_claim: AuthorityClaim,
        title: str,
        section_id: str,
        effective_start: str,
        effective_end: str,
        media_type: str,
        metadata: dict[str, Any],
        ai_derived: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ai_derived": ai_derived,
            "authority_claim": authority_claim.value,
            "authority_kind": authority_kind,
            "citation": citation,
            "classification": classification,
            "current_through": current_through,
            "effective_end": effective_end,
            "effective_start": effective_start,
            "family": family.value,
            "media_type": media_type,
            "metadata": metadata,
            "record_id": record_id,
            "rights_review": rights_review.to_dict(),
            "section_id": section_id,
            "source_lineage": source_lineage.to_dict(),
            "source_root_id": source_root_id,
            "text": text,
            "title": title,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_derived": dict(self.ai_derived),
            "authority_claim": self.authority_claim.value,
            "authority_kind": self.authority_kind,
            "citation": self.citation,
            "classification": self.classification,
            "current_through": self.current_through,
            "document_cid": self.document_cid,
            "document_sha256": self.document_sha256,
            "effective_end": self.effective_end,
            "effective_start": self.effective_start,
            "family": self.family.value,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
            "record_id": self.record_id,
            "rights_review": self.rights_review.to_dict(),
            "section_id": self.section_id,
            "source_cid": self.source_cid,
            "source_lineage": self.source_lineage.to_dict(),
            "source_root_id": self.source_root_id,
            "text": self.text,
            "title": self.title,
        }

    def to_index_join(self) -> dict[str, Any]:
        """Compact join record for BM25 / vector / graph builders."""
        return {
            "authority_claim": self.authority_claim.value,
            "authority_kind": self.authority_kind,
            "citation": self.citation,
            "classification": self.classification,
            "document_cid": self.document_cid,
            "document_sha256": self.document_sha256,
            "family": self.family.value,
            "record_id": self.record_id,
            "source_cid": self.source_cid,
            "source_root_id": self.source_root_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        default_source_root_id: str = "",
        default_current_through: str = "",
    ) -> "PublicLegalDocument":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("document must be a mapping")
        lineage_raw = value.get("source_lineage")
        if not isinstance(lineage_raw, Mapping):
            raise MissingSourceReceiptError("document requires source_lineage")
        rights_raw = value.get("rights_review")
        if not isinstance(rights_raw, Mapping):
            raise UnreviewedRightsError("document requires rights_review")
        family = SourceFamily.coerce(value.get("family") or value.get("source_family"))
        source_root_id = str(
            value.get("source_root_id")
            or value.get("source_id")
            or default_source_root_id
            or lineage_raw.get("source_id")
            or ""
        )
        current_through = str(
            value.get("current_through") or default_current_through or ""
        )
        text = value.get("text")
        if text is None:
            fields = value.get("fields")
            if isinstance(fields, Mapping):
                auth = fields.get("authoritative")
                if isinstance(auth, Mapping) and "text" in auth:
                    text = auth.get("text")
            if text is None:
                text = value.get("body") or value.get("body_text") or ""
        citation = value.get("citation")
        if not citation and isinstance(value.get("metadata"), Mapping):
            citation = value["metadata"].get("citation")
        if not citation:
            citation = str(value.get("record_id") or "unknown")
        return cls(
            record_id=str(value.get("record_id") or value.get("document_id") or ""),
            family=family,
            classification=str(value.get("classification") or "public_official"),
            text=str(text or ""),
            citation=str(citation),
            source_lineage=SourceLineage.from_dict(lineage_raw),
            rights_review=RightsReview.from_dict(rights_raw),
            source_root_id=source_root_id,
            current_through=current_through,
            authority_kind=str(value.get("authority_kind") or ""),
            authority_claim=_coerce_authority_claim(
                value.get("authority_claim", AuthorityClaim.SOURCE_BOUND.value)
            ),
            title=str(value.get("title") or ""),
            section_id=str(value.get("section_id") or ""),
            effective_start=str(value.get("effective_start") or ""),
            effective_end=str(value.get("effective_end") or ""),
            media_type=str(value.get("media_type") or "text/plain"),
            metadata=dict(value.get("metadata") or {}),
            ai_derived=dict(value.get("ai_derived") or {}),
            document_sha256=str(value.get("document_sha256") or ""),
            document_cid=str(value.get("document_cid") or ""),
            source_cid=str(value.get("source_cid") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalCorpusCounts:
    """Aggregate counts bound into the corpus manifest."""

    total_documents: int
    by_family: Mapping[str, int]
    by_authority_kind: Mapping[str, int]
    by_source_root: Mapping[str, int]
    source_root_count: int

    def __post_init__(self) -> None:
        if type(self.total_documents) is not int or self.total_documents < 0:
            raise SchemaValidationError("total_documents must be non-negative int")
        if type(self.source_root_count) is not int or self.source_root_count < 0:
            raise SchemaValidationError("source_root_count must be non-negative int")
        object.__setattr__(
            self, "by_family", MappingProxyType(dict(self.by_family or {}))
        )
        object.__setattr__(
            self,
            "by_authority_kind",
            MappingProxyType(dict(self.by_authority_kind or {})),
        )
        object.__setattr__(
            self,
            "by_source_root",
            MappingProxyType(dict(self.by_source_root or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_authority_kind": dict(self.by_authority_kind),
            "by_family": dict(self.by_family),
            "by_source_root": dict(self.by_source_root),
            "source_root_count": self.source_root_count,
            "total_documents": self.total_documents,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalCorpusCounts":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("counts must be a mapping")
        return cls(
            total_documents=int(value.get("total_documents") or 0),
            by_family=dict(value.get("by_family") or {}),
            by_authority_kind=dict(value.get("by_authority_kind") or {}),
            by_source_root=dict(value.get("by_source_root") or {}),
            source_root_count=int(value.get("source_root_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalCorpusManifest:
    """Content-addressed manifest binding source roots, counts, and CIDs.

    Downstream BM25 / vector / graph builders consume:
    * ``corpus_root_cid`` / ``corpus_digest_sha256`` as the corpus pin;
    * ``source_roots`` for rights / current-through receipts;
    * ``document_joins`` for orphan-free index source joins;
    * ``counts`` for parity checks.
    """

    schema_version: str
    interface: str
    task_id: str
    goal_id: str
    producer: str
    config_id: str
    code_version: str
    partition: str
    corpus_root_cid: str
    corpus_digest_sha256: str
    source_roots: tuple[SourceRootBinding, ...]
    counts: PublicLegalCorpusCounts
    document_joins: tuple[Mapping[str, Any], ...]
    rights_summary: Mapping[str, Any]
    builder_bindings: Mapping[str, Any]
    mode: str = MaterializationMode.DRY_RUN.value
    staged_at_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"unsupported schema_version: {self.schema_version!r}"
            )
        if self.interface != INTERFACE:
            raise SchemaValidationError(f"unsupported interface: {self.interface!r}")
        if self.task_id != TASK_ID:
            raise SchemaValidationError(f"task_id must be {TASK_ID}")
        if self.goal_id != GOAL_ID:
            raise SchemaValidationError(f"goal_id must be {GOAL_ID}")
        if self.partition != "public":
            raise PrivateOrMixedInputError(
                f"partition must be 'public', got {self.partition!r}"
            )
        if not self.source_roots:
            raise MissingSourceReceiptError("manifest requires at least one source root")
        if self.counts.total_documents != len(self.document_joins):
            raise CorpusIntegrityError(
                "counts.total_documents does not match document_joins length"
            )
        if self.counts.source_root_count != len(self.source_roots):
            raise CorpusIntegrityError(
                "counts.source_root_count does not match source_roots length"
            )
        object.__setattr__(
            self,
            "document_joins",
            tuple(MappingProxyType(dict(item)) for item in self.document_joins),
        )
        object.__setattr__(
            self, "rights_summary", MappingProxyType(dict(self.rights_summary or {}))
        )
        object.__setattr__(
            self,
            "builder_bindings",
            MappingProxyType(dict(self.builder_bindings or {})),
        )
        # Verify content address matches body (excluding non-content keys).
        body = self._content_body()
        digest = content_digest_of(body)
        cid = content_cid_of(body)
        if self.corpus_digest_sha256 and self.corpus_digest_sha256 != digest:
            raise CorpusIntegrityError("corpus_digest_sha256 mismatch")
        if self.corpus_root_cid and self.corpus_root_cid != cid:
            raise CorpusIntegrityError("corpus_root_cid mismatch")
        object.__setattr__(self, "corpus_digest_sha256", digest)
        object.__setattr__(self, "corpus_root_cid", cid)

    def _content_body(self) -> dict[str, Any]:
        # Mode / staging timestamps are intentionally excluded so dry-run and
        # staged materializations of the same roots remain content-address stable.
        return {
            "builder_bindings": dict(self.builder_bindings),
            "code_version": self.code_version,
            "config_id": self.config_id,
            "counts": self.counts.to_dict(),
            "document_joins": [dict(item) for item in self.document_joins],
            "goal_id": self.goal_id,
            "interface": self.interface,
            "partition": self.partition,
            "producer": self.producer,
            "rights_summary": dict(self.rights_summary),
            "schema_version": self.schema_version,
            "source_roots": [root.to_dict() for root in self.source_roots],
            "task_id": self.task_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._content_body()
        payload["corpus_digest_sha256"] = self.corpus_digest_sha256
        payload["corpus_root_cid"] = self.corpus_root_cid
        payload["mode"] = self.mode
        if self.staged_at_utc:
            payload["staged_at_utc"] = self.staged_at_utc
        if self.notes:
            payload["notes"] = self.notes
        return payload

    def to_canonical_bytes(self) -> bytes:
        return canonical_json(self.to_dict()).encode("utf-8")

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalCorpusManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        roots = tuple(
            SourceRootBinding.from_dict(item)
            for item in (value.get("source_roots") or [])
        )
        joins = tuple(dict(item) for item in (value.get("document_joins") or []))
        counts_raw = value.get("counts") or {}
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            partition=str(value.get("partition") or "public"),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            corpus_digest_sha256=str(value.get("corpus_digest_sha256") or ""),
            source_roots=roots,
            counts=PublicLegalCorpusCounts.from_dict(counts_raw),
            document_joins=joins,
            rights_summary=dict(value.get("rights_summary") or {}),
            builder_bindings=dict(value.get("builder_bindings") or {}),
            mode=str(value.get("mode") or MaterializationMode.DRY_RUN.value),
            staged_at_utc=str(value.get("staged_at_utc") or ""),
            notes=str(value.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalCorpusMaterialization:
    """Full materialization result: admitted documents + binding manifest."""

    documents: tuple[PublicLegalDocument, ...]
    manifest: PublicLegalCorpusManifest
    mode: MaterializationMode = MaterializationMode.DRY_RUN
    output_dir: Optional[str] = None

    def __post_init__(self) -> None:
        if len(self.documents) != self.manifest.counts.total_documents:
            raise CorpusIntegrityError(
                "document count does not match manifest counts"
            )
        doc_cids = {doc.document_cid for doc in self.documents}
        join_cids = {
            str(item.get("document_cid") or "") for item in self.manifest.document_joins
        }
        if doc_cids != join_cids:
            raise CorpusIntegrityError(
                "document CIDs do not match manifest document_joins"
            )

    @property
    def corpus_root_cid(self) -> str:
        return self.manifest.corpus_root_cid

    @property
    def corpus_digest_sha256(self) -> str:
        return self.manifest.corpus_digest_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_root_cid": self.corpus_root_cid,
            "documents": [doc.to_dict() for doc in self.documents],
            "manifest": self.manifest.to_dict(),
            "mode": self.mode.value
            if isinstance(self.mode, MaterializationMode)
            else str(self.mode),
            "output_dir": self.output_dir,
        }

    def to_canonical_bytes(self) -> bytes:
        # Content address excludes output_dir and mode presentation noise —
        # stability is defined over documents + manifest content body.
        manifest_body = self.manifest._content_body()
        manifest_body["corpus_digest_sha256"] = self.manifest.corpus_digest_sha256
        manifest_body["corpus_root_cid"] = self.manifest.corpus_root_cid
        payload = {
            "documents": [doc.to_dict() for doc in self.documents],
            "manifest": manifest_body,
        }
        return canonical_json(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Admission / privacy gates (fail-closed)
# ---------------------------------------------------------------------------


def _reject_private_or_mixed_batch(
    classifications: Sequence[str],
    *,
    context: str,
) -> None:
    if not classifications:
        raise SchemaValidationError(f"{context}: empty classification set")
    unique = sorted({str(item) for item in classifications})
    private_hits = [
        item
        for item in unique
        if item in PRIVATE_CLASSIFICATION_SET
        or item == "unknown"
        or is_private_classification(item)
        or (item not in PUBLIC_CLASSIFICATION_SET)
    ]
    if private_hits:
        raise PrivateOrMixedInputError(
            f"{context}: private/unknown classifications fail closed: "
            f"{', '.join(private_hits)}"
        )
    public_hits = [item for item in unique if item in PUBLIC_CLASSIFICATION_SET]
    if not public_hits:
        raise PrivateOrMixedInputError(
            f"{context}: no public classifications present"
        )
    # Mixed public + private already covered; mixed public_official + unknown too.
    # Also reject heterogeneous "mixed" token if ever supplied as a classification.
    if any(item == "mixed" for item in unique):
        raise PrivateOrMixedInputError(f"{context}: mixed classification fails closed")


def assert_public_only_documents(documents: Sequence[PublicLegalDocument]) -> None:
    """Fail closed if the batch is not strictly public."""
    _reject_private_or_mixed_batch(
        [doc.classification for doc in documents],
        context="document batch",
    )


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


@dataclass
class PublicLegalCorpusMaterializer:
    """Materialize a deterministic public patent-law / regulations corpus.

    Parameters
    ----------
    require_all_families:
        When True, every :data:`SOURCE_FAMILIES` member must appear in the
        admitted source roots (strict Hub completeness). Defaults to False so
        CI fixtures may cover a subset.
    """

    require_all_families: bool = False
    code_version: str = CODE_VERSION

    def materialize(
        self,
        *,
        source_roots: Sequence[SourceRootBinding | Mapping[str, Any]],
        documents: Sequence[PublicLegalDocument | Mapping[str, Any]],
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> PublicLegalCorpusMaterialization:
        """Materialize the public corpus from pinned roots and documents.

        Private / mixed / unreviewed inputs raise before any filesystem write.
        """
        roots = self._normalize_roots(source_roots)
        if not roots:
            raise MissingSourceReceiptError("at least one source root is required")
        root_by_id = {root.source_id: root for root in roots}
        if len(root_by_id) != len(roots):
            raise SchemaValidationError("duplicate source_id in source_roots")

        if self.require_all_families:
            present = {root.family for root in roots}
            missing = [fam for fam in SourceFamily if fam not in present]
            if missing:
                raise MissingSourceReceiptError(
                    "require_all_families: missing families "
                    + ", ".join(m.value for m in missing)
                )

        admitted = self._admit_documents(documents, root_by_id=root_by_id)
        if not admitted:
            raise SchemaValidationError("at least one document is required")
        assert_public_only_documents(admitted)

        # Stable order for content addressing.
        admitted = tuple(sorted(admitted, key=lambda d: d.record_id))
        record_ids = [doc.record_id for doc in admitted]
        if len(record_ids) != len(set(record_ids)):
            raise SchemaValidationError("duplicate record_id in documents")

        # Recount documents per root and rebind.
        per_root = Counter(doc.source_root_id for doc in admitted)
        bound_roots = tuple(
            sorted(
                (
                    root_by_id[source_id].with_document_count(per_root[source_id])
                    for source_id in root_by_id
                    if per_root.get(source_id, 0) > 0
                    or source_id in {doc.source_root_id for doc in admitted}
                ),
                key=lambda r: r.source_id,
            )
        )
        # Roots with zero documents are dropped from the binding (fail closed
        # if a document references an unknown root — already checked).
        # Keep only roots that contributed at least one document.
        bound_roots = tuple(r for r in bound_roots if r.document_count > 0)
        if not bound_roots:
            raise MissingSourceReceiptError("no source roots contributed documents")

        # Orphan documents referencing dropped roots should already be impossible.
        bound_ids = {r.source_id for r in bound_roots}
        for doc in admitted:
            if doc.source_root_id not in bound_ids:
                raise MissingSourceReceiptError(
                    f"document {doc.record_id!r} references unknown source root "
                    f"{doc.source_root_id!r}"
                )

        counts = self._build_counts(admitted, bound_roots)
        joins = tuple(doc.to_index_join() for doc in admitted)
        rights_summary = self._rights_summary(admitted, bound_roots)
        builder_bindings = self._builder_bindings(admitted, bound_roots, counts)

        mode = MaterializationMode.STAGE if stage else MaterializationMode.DRY_RUN
        # Build manifest without digest first, then re-construct with pins.
        provisional = PublicLegalCorpusManifest(
            schema_version=SCHEMA_VERSION,
            interface=INTERFACE,
            task_id=TASK_ID,
            goal_id=GOAL_ID,
            producer=PRODUCER,
            config_id=CONFIG_ID,
            code_version=self.code_version,
            partition="public",
            corpus_root_cid="",
            corpus_digest_sha256="",
            source_roots=bound_roots,
            counts=counts,
            document_joins=joins,
            rights_summary=rights_summary,
            builder_bindings=builder_bindings,
            mode=mode.value,
            notes=str(notes or ""),
        )

        result = PublicLegalCorpusMaterialization(
            documents=admitted,
            manifest=provisional,
            mode=mode,
            output_dir=None,
        )

        if stage:
            if output_dir is None:
                raise PublicLegalCorpusError(
                    "output_dir is required when stage=True",
                    code="missing_output_dir",
                )
            written = self.stage(result, output_dir=output_dir)
            return written
        return result

    def materialize_from_recipe(
        self,
        recipe: Mapping[str, Any],
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
    ) -> PublicLegalCorpusMaterialization:
        """Materialize from a compact in-memory / on-disk recipe mapping."""
        if not isinstance(recipe, Mapping):
            raise SchemaValidationError("recipe must be a mapping")
        roots = recipe.get("source_roots") or []
        docs = recipe.get("documents") or recipe.get("records") or []
        notes = str(recipe.get("notes") or "")
        return self.materialize(
            source_roots=list(roots),
            documents=list(docs),
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def materialize_from_paths(
        self,
        *,
        roots_path: PathLike,
        documents_path: PathLike,
        stage: bool = False,
        output_dir: PathLike | None = None,
    ) -> PublicLegalCorpusMaterialization:
        """Load JSON source roots + documents and materialize."""
        roots = _load_json_list(Path(roots_path), label="source_roots")
        docs = _load_json_list(Path(documents_path), label="documents")
        return self.materialize(
            source_roots=roots,
            documents=docs,
            stage=stage,
            output_dir=output_dir,
        )

    def stage(
        self,
        materialization: PublicLegalCorpusMaterialization,
        *,
        output_dir: PathLike,
    ) -> PublicLegalCorpusMaterialization:
        """Write corpus artifacts to *output_dir* atomically."""
        # Re-check privacy before any write.
        assert_public_only_documents(materialization.documents)

        root = Path(output_dir)
        _ensure_dir(root)

        manifest_payload = materialization.manifest.to_dict()
        documents_lines = [
            canonical_json(doc.to_dict()) for doc in materialization.documents
        ]
        documents_blob = ("\n".join(documents_lines) + "\n").encode("utf-8")
        source_receipts = {
            "schema_version": SCHEMA_VERSION,
            "source_roots": [r.to_dict() for r in materialization.manifest.source_roots],
            "rights_summary": dict(materialization.manifest.rights_summary),
        }
        corpus_root = {
            "builder_bindings": dict(materialization.manifest.builder_bindings),
            "corpus_digest_sha256": materialization.corpus_digest_sha256,
            "corpus_root_cid": materialization.corpus_root_cid,
            "counts": materialization.manifest.counts.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }

        _atomic_write_text(
            root / MANIFEST_FILENAME, canonical_json(manifest_payload) + "\n"
        )
        _atomic_write_bytes(root / DOCUMENTS_FILENAME, documents_blob)
        _atomic_write_text(
            root / SOURCE_RECEIPTS_FILENAME, canonical_json(source_receipts) + "\n"
        )
        _atomic_write_text(
            root / CORPUS_ROOT_FILENAME, canonical_json(corpus_root) + "\n"
        )

        return PublicLegalCorpusMaterialization(
            documents=materialization.documents,
            manifest=materialization.manifest,
            mode=MaterializationMode.STAGE,
            output_dir=str(root.resolve()),
        )

    # -- internals ---------------------------------------------------------

    def _normalize_roots(
        self, source_roots: Sequence[SourceRootBinding | Mapping[str, Any]]
    ) -> tuple[SourceRootBinding, ...]:
        out: list[SourceRootBinding] = []
        for index, item in enumerate(source_roots):
            if isinstance(item, SourceRootBinding):
                out.append(item)
            elif isinstance(item, Mapping):
                try:
                    out.append(SourceRootBinding.from_dict(item))
                except PublicLegalCorpusError:
                    raise
                except Exception as exc:
                    raise SchemaValidationError(
                        f"source_roots[{index}] is invalid: {exc}"
                    ) from exc
            else:
                raise SchemaValidationError(
                    f"source_roots[{index}] must be SourceRootBinding or mapping"
                )
        return tuple(out)

    def _admit_documents(
        self,
        documents: Sequence[PublicLegalDocument | Mapping[str, Any]],
        *,
        root_by_id: Mapping[str, SourceRootBinding],
    ) -> tuple[PublicLegalDocument, ...]:
        admitted: list[PublicLegalDocument] = []
        classifications: list[str] = []
        for index, item in enumerate(documents):
            if isinstance(item, PublicLegalDocument):
                doc = item
            elif isinstance(item, Mapping):
                # Pre-scan classification for fail-closed before full parse.
                raw_class = str(item.get("classification") or "public_official")
                try:
                    coerced = _coerce_classification(raw_class)
                except SchemaValidationError as exc:
                    raise PrivateOrMixedInputError(
                        f"documents[{index}]: {exc}"
                    ) from exc
                if coerced not in PUBLIC_CLASSIFICATION_SET:
                    raise PrivateOrMixedInputError(
                        f"documents[{index}]: classification {coerced!r} "
                        "fails closed for public legal corpus"
                    )
                source_root_id = str(
                    item.get("source_root_id")
                    or item.get("source_id")
                    or ""
                )
                default_through = ""
                if source_root_id and source_root_id in root_by_id:
                    default_through = root_by_id[source_root_id].current_through
                try:
                    doc = PublicLegalDocument.from_dict(
                        item,
                        default_source_root_id=source_root_id,
                        default_current_through=default_through,
                    )
                except PrivateOrMixedInputError:
                    raise
                except UnreviewedRightsError:
                    raise
                except PublicLegalCorpusError:
                    raise
                except Exception as exc:
                    raise SchemaValidationError(
                        f"documents[{index}] is invalid: {exc}"
                    ) from exc
            else:
                raise SchemaValidationError(
                    f"documents[{index}] must be PublicLegalDocument or mapping"
                )

            if doc.source_root_id not in root_by_id:
                raise MissingSourceReceiptError(
                    f"document {doc.record_id!r} references unknown source root "
                    f"{doc.source_root_id!r}"
                )
            root = root_by_id[doc.source_root_id]
            if doc.family != root.family:
                raise SchemaValidationError(
                    f"document {doc.record_id!r} family {doc.family.value} "
                    f"does not match source root family {root.family.value}"
                )
            classifications.append(doc.classification)
            admitted.append(doc)

        _reject_private_or_mixed_batch(classifications, context="admission")
        return tuple(admitted)

    def _build_counts(
        self,
        documents: Sequence[PublicLegalDocument],
        roots: Sequence[SourceRootBinding],
    ) -> PublicLegalCorpusCounts:
        by_family = Counter(doc.family.value for doc in documents)
        by_kind = Counter(doc.authority_kind for doc in documents)
        by_root = Counter(doc.source_root_id for doc in documents)
        return PublicLegalCorpusCounts(
            total_documents=len(documents),
            by_family=dict(sorted(by_family.items())),
            by_authority_kind=dict(sorted(by_kind.items())),
            by_source_root=dict(sorted(by_root.items())),
            source_root_count=len(roots),
        )

    def _rights_summary(
        self,
        documents: Sequence[PublicLegalDocument],
        roots: Sequence[SourceRootBinding],
    ) -> dict[str, Any]:
        licenses = sorted({doc.rights_review.license_expression for doc in documents})
        reviewers = sorted({doc.rights_review.reviewed_by for doc in documents})
        return {
            "all_redistribution_allowed": all(
                doc.rights_review.redistribution_allowed for doc in documents
            ),
            "all_reviewed": all(
                doc.rights_review.review_status is RightsReviewStatus.REVIEWED
                for doc in documents
            ),
            "license_expressions": licenses,
            "partition": "public",
            "reviewed_by": reviewers,
            "source_root_licenses": sorted(
                {root.license_expression for root in roots}
            ),
        }

    def _builder_bindings(
        self,
        documents: Sequence[PublicLegalDocument],
        roots: Sequence[SourceRootBinding],
        counts: PublicLegalCorpusCounts,
    ) -> dict[str, Any]:
        """Fields BM25 / vector / graph builders need to pin the corpus root."""
        source_manifest_body = {
            "source_roots": [r.to_dict() for r in roots],
            "task_id": TASK_ID,
        }
        source_manifest_cid = content_cid_of(source_manifest_body)
        return {
            "bm25": {
                "join_fields": ["document_cid", "source_cid", "record_id"],
                "required_partition": "public",
            },
            "graph": {
                "join_fields": ["document_cid", "source_cid", "record_id"],
                "required_partition": "public",
            },
            "record_count": counts.total_documents,
            "source_manifest_cid": source_manifest_cid,
            "source_root_cids": {
                root.source_id: root.root_cid for root in roots
            },
            "vector": {
                "join_fields": ["document_cid", "source_cid", "record_id"],
                "required_partition": "public",
            },
        }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path, *, label: str) -> list[Mapping[str, Any]]:
    if not path.is_file():
        raise PublicLegalCorpusError(f"{label} file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise PublicLegalCorpusError(f"{label} file is empty: {path}")
    if path.suffix.lower() == ".ndjson" or (
        not text.startswith("[") and not text.startswith("{")
    ):
        rows: list[Mapping[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PublicLegalCorpusError(
                    f"{label} invalid NDJSON on line {line_no}: {exc}"
                ) from exc
            if not isinstance(value, Mapping):
                raise PublicLegalCorpusError(
                    f"{label} NDJSON line {line_no} must be an object"
                )
            rows.append(value)
        return rows
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PublicLegalCorpusError(f"{label} invalid JSON: {exc}") from exc
    if isinstance(payload, Mapping):
        if label == "source_roots" and "source_roots" in payload:
            payload = payload["source_roots"]
        elif "documents" in payload:
            payload = payload["documents"]
        elif "records" in payload:
            payload = payload["records"]
        else:
            # Single object → one-element list.
            return [payload]
    if not isinstance(payload, list):
        raise PublicLegalCorpusError(f"{label} must be a JSON array")
    rows = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise PublicLegalCorpusError(f"{label}[{index}] must be an object")
        rows.append(item)
    return rows


def load_manifest(path: PathLike) -> PublicLegalCorpusManifest:
    """Load and validate a staged public legal corpus manifest."""
    target = Path(path)
    if not target.is_file():
        raise PublicLegalCorpusError(f"manifest not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublicLegalCorpusError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicLegalCorpusError("manifest must be a JSON object")
    return PublicLegalCorpusManifest.from_dict(payload)


def validate_materialization(
    materialization: PublicLegalCorpusMaterialization,
) -> dict[str, Any]:
    """Return a structured validation receipt for a materialization result."""
    manifest = materialization.manifest
    docs = materialization.documents
    assert_public_only_documents(docs)
    # Recompute digests to prove stability.
    again = PublicLegalCorpusMaterializer().materialize(
        source_roots=list(manifest.source_roots),
        documents=[doc.to_dict() for doc in docs],
        stage=False,
    )
    stable = (
        again.corpus_root_cid == materialization.corpus_root_cid
        and again.corpus_digest_sha256 == materialization.corpus_digest_sha256
        and again.to_canonical_bytes() == materialization.to_canonical_bytes()
    )
    if not stable:
        raise CorpusIntegrityError("repeat materialization is not content-address stable")
    return {
        "corpus_digest_sha256": materialization.corpus_digest_sha256,
        "corpus_root_cid": materialization.corpus_root_cid,
        "document_count": len(docs),
        "ok": True,
        "partition": "public",
        "source_root_count": len(manifest.source_roots),
        "stable": True,
        "task_id": TASK_ID,
    }


def materializations_are_byte_identical(
    left: PublicLegalCorpusMaterialization,
    right: PublicLegalCorpusMaterialization,
) -> bool:
    """Return True when two materializations share identical content bytes."""
    return left.to_canonical_bytes() == right.to_canonical_bytes()


def build_public_legal_corpus(
    *,
    source_roots: Sequence[SourceRootBinding | Mapping[str, Any]],
    documents: Sequence[PublicLegalDocument | Mapping[str, Any]],
    stage: bool = False,
    output_dir: PathLike | None = None,
    require_all_families: bool = False,
    notes: str = "",
) -> PublicLegalCorpusMaterialization:
    """Module-level convenience wrapper for :class:`PublicLegalCorpusMaterializer`."""
    return PublicLegalCorpusMaterializer(
        require_all_families=require_all_families
    ).materialize(
        source_roots=source_roots,
        documents=documents,
        stage=stage,
        output_dir=output_dir,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Compact default fixture recipe (for CI when live sources are unavailable)
# ---------------------------------------------------------------------------


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_default_public_legal_recipe() -> dict[str, Any]:
    """Return a compact multi-family public fixture recipe for CI replay."""
    rights = {
        "license_expression": "public-domain-US-government",
        "notes": "US government work; fixture for PATLAW-170 CI",
        "redistribution_allowed": True,
        "review_status": "reviewed",
        "reviewed_at": "2026-08-01T00:00:00Z",
        "reviewed_by": "patent-legal-governance",
    }

    def lineage(
        source_id: str,
        revision: str,
        uri: str,
        body: str,
    ) -> dict[str, Any]:
        return {
            "authority": "official",
            "source_id": source_id,
            "source_revision": revision,
            "source_sha256": _sha_text(body),
            "source_uri": uri,
        }

    roots = [
        {
            "source_id": "ecfr-title37-2024",
            "family": "ecfr",
            "current_through": "2024-06-01",
            "official_edition_cutoff": "2024-06-01",
            "source_uri": "https://www.ecfr.gov/current/title-37",
            "source_revision": "ecfr-2024-06-01-title37",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
        {
            "source_id": "cfr-title37-2023",
            "family": "cfr",
            "current_through": "2023-07-01",
            "official_edition_cutoff": "2023-07-01",
            "source_uri": "https://www.govinfo.gov/app/collection/cfr",
            "source_revision": "cfr-2023-title37",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
        {
            "source_id": "uscode-title35-2023",
            "family": "uscode",
            "current_through": "2023-12-31",
            "official_edition_cutoff": "2023-12-31",
            "source_uri": "https://www.govinfo.gov/app/details/USCODE-2023-title35",
            "source_revision": "govinfo-2023-title35",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
        {
            "source_id": "plaw-118-100",
            "family": "public_law",
            "current_through": "2024-04-01",
            "official_edition_cutoff": "2024-04-01",
            "source_uri": "https://www.govinfo.gov/app/details/PLAW-118publ100",
            "source_revision": "plaw-118-100",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
        {
            "source_id": "fr-2024-patent-rules",
            "family": "federal_register",
            "current_through": "2024-05-15",
            "official_edition_cutoff": "2024-05-15",
            "source_uri": "https://www.federalregister.gov/",
            "source_revision": "fr-2024-05-15-patent",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
        {
            "source_id": "mpep-e9r10-2024",
            "family": "mpep",
            "current_through": "2024-02-01",
            "official_edition_cutoff": "2024-02-01",
            "source_uri": "https://www.uspto.gov/web/offices/pac/mpep/",
            "source_revision": "mpep-9th-rev-10-2024",
            "license_expression": "public-domain-US-government",
            "gaps": ["adjudicatory coverage out of scope"],
        },
        {
            "source_id": "uspto-exam-guidance-2024",
            "family": "guidance",
            "current_through": "2024-03-01",
            "official_edition_cutoff": "2024-03-01",
            "source_uri": "https://www.uspto.gov/patents/laws",
            "source_revision": "uspto-guidance-2024-03",
            "license_expression": "public-domain-US-government",
            "gaps": [],
        },
    ]

    documents = [
        {
            "record_id": "ecfr:37:1.56",
            "family": "ecfr",
            "source_root_id": "ecfr-title37-2024",
            "classification": "public_official",
            "citation": "37 C.F.R. § 1.56",
            "title": "Duty to disclose information material to patentability",
            "section_id": "1.56",
            "text": (
                "Each individual associated with the filing and prosecution of a "
                "patent application has a duty of candor and good faith in dealing "
                "with the Office, which includes a duty to disclose to the Office "
                "all information known to that individual to be material to "
                "patentability as defined in this section."
            ),
            "authority_kind": "regulation",
            "authority_claim": "source_bound",
            "current_through": "2024-06-01",
            "effective_start": "2022-01-01",
            "source_lineage": lineage(
                "ecfr/title37/1.56",
                "ecfr-2024-06-01",
                "https://www.ecfr.gov/current/title-37/section-1.56",
                "ecfr-37-1.56-2024",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "cfr:37:1.56-2023",
            "family": "cfr",
            "source_root_id": "cfr-title37-2023",
            "classification": "public_official",
            "citation": "37 C.F.R. § 1.56 (2023 annual)",
            "title": "Duty to disclose (annual CFR)",
            "section_id": "1.56",
            "text": (
                "Annual CFR Title 37 § 1.56 baseline text for duty of candor "
                "and disclosure material to patentability (2023 edition)."
            ),
            "authority_kind": "regulation",
            "authority_claim": "source_bound",
            "current_through": "2023-07-01",
            "source_lineage": lineage(
                "govinfo/cfr/title37/1.56",
                "cfr-2023",
                "https://www.govinfo.gov/content/pkg/CFR-2023-title37-vol1/xml/CFR-2023-title37-vol1-sec1-56.xml",
                "cfr-37-1.56-2023",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "usc:35:101",
            "family": "uscode",
            "source_root_id": "uscode-title35-2023",
            "classification": "public_official",
            "citation": "35 U.S.C. § 101",
            "title": "Inventions patentable",
            "section_id": "101",
            "text": (
                "Whoever invents or discovers any new and useful process, machine, "
                "manufacture, or composition of matter, or any new and useful "
                "improvement thereof, may obtain a patent therefor, subject to the "
                "conditions and requirements of this title."
            ),
            "authority_kind": "statute",
            "authority_claim": "source_bound",
            "current_through": "2023-12-31",
            "source_lineage": lineage(
                "govinfo/uscode/title35/101",
                "govinfo-2023-title35",
                "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/xml/USCODE-2023-title35-partII-chap10-sec101.xml",
                "usc-35-101-2023",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "usc:35:102",
            "family": "uscode",
            "source_root_id": "uscode-title35-2023",
            "classification": "public_official",
            "citation": "35 U.S.C. § 102",
            "title": "Conditions for patentability; novelty",
            "section_id": "102",
            "text": (
                "A person shall be entitled to a patent unless the claimed invention "
                "was patented, described in a printed publication, or in public use, "
                "on sale, or otherwise available to the public before the effective "
                "filing date of the claimed invention."
            ),
            "authority_kind": "statute",
            "authority_claim": "source_bound",
            "current_through": "2023-12-31",
            "source_lineage": lineage(
                "govinfo/uscode/title35/102",
                "govinfo-2023-title35",
                "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/xml/USCODE-2023-title35-partII-chap10-sec102.xml",
                "usc-35-102-2023",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "plaw:118-100",
            "family": "public_law",
            "source_root_id": "plaw-118-100",
            "classification": "public_official",
            "citation": "Pub. L. 118-100",
            "title": "Public Law 118-100 (fixture excerpt)",
            "text": (
                "Public Law 118-100 fixture excerpt for patent-fee and Title 35 "
                "cross-reference materialization tests."
            ),
            "authority_kind": "public_law",
            "authority_claim": "source_bound",
            "current_through": "2024-04-01",
            "source_lineage": lineage(
                "govinfo/plaw/118-100",
                "plaw-118-100",
                "https://www.govinfo.gov/content/pkg/PLAW-118publ100/pdf/PLAW-118publ100.pdf",
                "plaw-118-100-body",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "fr:2024-patent-rule-change",
            "family": "federal_register",
            "source_root_id": "fr-2024-patent-rules",
            "classification": "public_official",
            "citation": "89 Fed. Reg. 12345 (May 15, 2024)",
            "title": "Patent rule change notice (fixture)",
            "text": (
                "Federal Register notice fixture describing proposed adjustments "
                "to patent examination practice and fee schedules."
            ),
            "authority_kind": "federal_register",
            "authority_claim": "source_bound",
            "current_through": "2024-05-15",
            "source_lineage": lineage(
                "fr/2024/patent-rule-change",
                "fr-2024-05-15",
                "https://www.federalregister.gov/documents/2024/05/15/patent-rule",
                "fr-2024-patent-rule",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "mpep:2106",
            "family": "mpep",
            "source_root_id": "mpep-e9r10-2024",
            "classification": "public_official",
            "citation": "MPEP § 2106",
            "title": "Patent Subject Matter Eligibility",
            "section_id": "2106",
            "text": (
                "MPEP § 2106 provides examination guidance on patent subject matter "
                "eligibility under 35 U.S.C. § 101. Guidance is non-binding and does "
                "not have the force of law."
            ),
            "authority_kind": "guidance",
            "authority_claim": "source_bound",
            "current_through": "2024-02-01",
            "source_lineage": lineage(
                "uspto/mpep/2106",
                "mpep-9th-rev-10-2024",
                "https://www.uspto.gov/web/offices/pac/mpep/s2106.html",
                "mpep-2106-2024",
            ),
            "rights_review": rights,
        },
        {
            "record_id": "guidance:subject-matter-eligibility-2024",
            "family": "guidance",
            "source_root_id": "uspto-exam-guidance-2024",
            "classification": "public_official",
            "citation": "USPTO Subject Matter Eligibility Guidance (2024)",
            "title": "Subject Matter Eligibility Guidance",
            "text": (
                "USPTO examination guidance memorandum on subject matter eligibility "
                "examples and examiner instructions (non-binding)."
            ),
            "authority_kind": "guidance",
            "authority_claim": "source_bound",
            "current_through": "2024-03-01",
            "source_lineage": lineage(
                "uspto/guidance/sme-2024",
                "uspto-guidance-2024-03",
                "https://www.uspto.gov/patents/laws/examination-policy",
                "uspto-sme-guidance-2024",
            ),
            "rights_review": rights,
        },
    ]

    return {
        "notes": "PATLAW-170 compact public legal corpus fixture recipe",
        "recipe_id": "patlaw-170-public-legal-corpus",
        "schema_version": SCHEMA_VERSION,
        "source_roots": roots,
        "documents": documents,
        "expected": {
            "families": list(SOURCE_FAMILIES),
            "min_documents": 8,
            "partition": "public",
            "task_id": TASK_ID,
        },
    }


__all__ = [
    "AUTHORITY_KINDS",
    "CODE_VERSION",
    "CONFIG_ID",
    "CORPUS_ROOT_FILENAME",
    "DOCUMENTS_FILENAME",
    "GOAL_ID",
    "INTERFACE",
    "MANIFEST_FILENAME",
    "PRODUCER",
    "SCHEMA_VERSION",
    "SOURCE_FAMILIES",
    "SOURCE_RECEIPTS_FILENAME",
    "TASK_ID",
    "AuthorityClaim",
    "CorpusIntegrityError",
    "MaterializationMode",
    "MissingSourceReceiptError",
    "PrivateOrMixedInputError",
    "PublicLegalCorpusCounts",
    "PublicLegalCorpusError",
    "PublicLegalCorpusManifest",
    "PublicLegalCorpusMaterialization",
    "PublicLegalCorpusMaterializer",
    "PublicLegalDocument",
    "SchemaValidationError",
    "SourceFamily",
    "SourceRootBinding",
    "UnreviewedRightsError",
    "assert_public_only_documents",
    "build_default_public_legal_recipe",
    "build_public_legal_corpus",
    "canonical_json",
    "content_cid_of",
    "content_digest_of",
    "load_manifest",
    "materializations_are_byte_identical",
    "validate_materialization",
]
