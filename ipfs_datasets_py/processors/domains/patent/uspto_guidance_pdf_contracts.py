"""USPTO guidance PDF inventory and extraction contracts (PATLAW-184 / PATLAW-G217).

Defines the serialization and validation boundary for a **pinned** inventory of
official USPTO examination guidance PDFs (and equivalent official guidance
artifacts). Every admitted PDF binds URI, SHA-256 of the PDF bytes, publication
date / cutoff, page metadata, rights review, and a deterministic text-extraction
contract for identical bytes.

Design invariants
-----------------
* Guidance document identity requires concrete ``document_id`` **and**
  ``version`` pins (or an equivalent dated edition token). The hard-coded
  token ``\"latest\"`` is always rejected; unpinned latest-guidance selection
  fails closed.
* Every inventory record binds ``uri``, ``sha256``, ``publication_date``,
  ``cutoff``, and ``rights_review``. Missing any of these fails closed.
* Guidance is always non-binding (``authority_tier=guidance``,
  ``is_binding=false``). Guidance PDFs never elevate to statute or regulation.
* Text extraction for identical PDF bytes is deterministic: same bytes + same
  extraction profile yield the same ``text_sha256``.
* Superseded editions are retained as evidence (never silently deleted or
  silently replaced by an unpinned "latest" pointer).
* No network I/O; this module is pure contracts and offline validation.
  Acquisition lives in PATLAW-185.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Iterator, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.processors.domains.patent.release_policy import (
    PUBLIC_CLASSIFICATIONS,
    RightsReview,
    RightsReviewStatus,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    reject_hard_coded_latest,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.uspto_guidance_pdfs.v1"
INTERFACE: Final = "UsptoGuidancePdfInventory@1"
PRODUCER: Final = "producer:uspto-guidance-pdf-inventory"
CONFIG_ID: Final = "config:uspto-guidance-pdfs/v1"
TASK_ID: Final = "PATLAW-184"
GOAL_ID: Final = "PATLAW-G217"
CODE_VERSION: Final = "1.0.0"

MANIFEST_FILENAME: Final = "uspto-guidance-pdfs.manifest.json"
MANIFEST_SCHEMA_FILENAME: Final = "uspto_guidance_pdfs.manifest.schema.json"

AUTHORITY_TIER_GUIDANCE: Final = AuthorityTier.GUIDANCE.value  # "guidance"
DEFAULT_PARTITION: Final = "public"
DEFAULT_PROVIDER: Final = "uspto"
DEFAULT_JURISDICTION: Final = "US"
DEFAULT_MEDIA_TYPE: Final = "application/pdf"
DEFAULT_CLASSIFICATION: Final = "public_official"
DEFAULT_LICENSE: Final = "US-Gov-Work"
DEFAULT_EXTRACTION_METHOD: Final = "pdf-text-v1"
DEFAULT_NORMALIZATION_PROFILE: Final = "unicode-nfc-ws-collapse-v1"

MANIFEST_SCHEMA_RELPATH: Final = (
    "data/release/patent_legal_intelligence/uspto_guidance_pdfs.manifest.schema.json"
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_NONEMPTY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_URI_RE = re.compile(r"^(https://|uspto://|ipfs://|hf://)")
_WS_RE = re.compile(r"\s+")

PUBLIC_CLASSIFICATION_SET: Final[frozenset[str]] = frozenset(PUBLIC_CLASSIFICATIONS)

# ---------------------------------------------------------------------------
# Representative guidance document catalog (compact offline fixture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsptoGuidanceDocumentSpec:
    """Static catalog entry for one known USPTO guidance PDF series."""

    document_id: str
    version: str
    title: str
    topic: str
    publication_date: str
    cutoff: str
    uri: str
    page_count: int


# Real-ish official USPTO examination guidance PDFs used by the compact
# offline fixture. URIs are stable official paths; digests are fixture seeds
# (not live file digests). Acquisition (PATLAW-185) rebinds real digests.
REQUIRED_GUIDANCE_DOCUMENTS: Final[tuple[UsptoGuidanceDocumentSpec, ...]] = (
    UsptoGuidanceDocumentSpec(
        document_id="sme-2019-peg",
        version="2019-01-07",
        title=(
            "2019 Revised Patent Subject Matter Eligibility Guidance "
            "(2019 PEG)"
        ),
        topic="subject_matter_eligibility",
        publication_date="2019-01-07",
        cutoff="2019-01-07",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "peg_oct_2019_update.pdf"
        ),
        page_count=22,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="sme-2019-peg-october-update",
        version="2019-10-17",
        title="October 2019 Update: Subject Matter Eligibility",
        topic="subject_matter_eligibility",
        publication_date="2019-10-17",
        cutoff="2019-10-17",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "peg_oct_2019_update.pdf"
        ),
        page_count=22,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="sme-2024-ai-examples",
        version="2024-07-17",
        title=(
            "2024 Guidance Update on Patent Subject Matter Eligibility, "
            "Including on Artificial Intelligence"
        ),
        topic="subject_matter_eligibility",
        publication_date="2024-07-17",
        cutoff="2024-07-17",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "2024-AI-Subject-Matter-Eligibility-Guidance.pdf"
        ),
        page_count=28,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="obviousness-kyr-2024",
        version="2024-02-27",
        title="Updated Guidance for Making a Proper Determination of Obviousness",
        topic="obviousness",
        publication_date="2024-02-27",
        cutoff="2024-02-27",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "updated_obviousness_guidance.pdf"
        ),
        page_count=12,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="enablement-2024",
        version="2024-01-10",
        title="Guidelines for Assessing Enablement in Utility Applications",
        topic="enablement",
        publication_date="2024-01-10",
        cutoff="2024-01-10",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "enablement_guidelines.pdf"
        ),
        page_count=10,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="written-description-2024",
        version="2024-03-01",
        title="Guidelines for Examination of Patent Applications Under 35 U.S.C. 112(a)",
        topic="written_description",
        publication_date="2024-03-01",
        cutoff="2024-03-01",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "written_description_guidelines.pdf"
        ),
        page_count=14,
    ),
    UsptoGuidanceDocumentSpec(
        document_id="exam-guide-1-23",
        version="2023-03-15",
        title="Examination Guide 1-23 — Subject Matter Eligibility Examples",
        topic="subject_matter_eligibility",
        publication_date="2023-03-15",
        cutoff="2023-03-15",
        uri=(
            "https://www.uspto.gov/sites/default/files/documents/"
            "exam_guide_1-23.pdf"
        ),
        page_count=18,
    ),
)

REQUIRED_DOCUMENT_IDS: Final[frozenset[str]] = frozenset(
    d.document_id for d in REQUIRED_GUIDANCE_DOCUMENTS
)
REQUIRED_DOCUMENT_BY_ID: Final[Mapping[str, UsptoGuidanceDocumentSpec]] = MappingProxyType(
    {d.document_id: d for d in REQUIRED_GUIDANCE_DOCUMENTS}
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UsptoGuidancePdfError(ValueError):
    """Base error for USPTO guidance PDF contract violations."""

    code: str = "uspto_guidance_pdf_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class GuidancePinError(UsptoGuidancePdfError):
    """Raised when document_id/version pins are missing, empty, or unpinned."""

    code = "guidance_pin_error"


class UnpinnedLatestSelectionError(UsptoGuidancePdfError):
    """Raised when inventory selection uses the hard-coded token ``latest``."""

    code = "unpinned_latest_selection"


class MissingCutoffError(UsptoGuidancePdfError):
    """Raised when a required cutoff / publication date is missing."""

    code = "missing_cutoff"


class BindingElevationError(UsptoGuidancePdfError):
    """Raised when guidance is elevated to binding law."""

    code = "binding_elevation"


class UnreviewedRightsError(UsptoGuidancePdfError):
    """Raised when rights review is missing or fails public admission."""

    code = "unreviewed_rights"


class ExtractionDeterminismError(UsptoGuidancePdfError):
    """Raised when text extraction is non-deterministic or profile-mismatched."""

    code = "extraction_determinism"


class SchemaValidationError(UsptoGuidancePdfError):
    """Raised when a manifest fails structural or schema validation."""

    code = "schema_validation"


class IncompleteInventoryError(UsptoGuidancePdfError):
    """Raised when inventory is empty or fails required coverage."""

    code = "incomplete_inventory"


class PrivateOrNonPublicError(UsptoGuidancePdfError):
    """Raised when classification/partition is not public-only."""

    code = "private_or_non_public"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InventoryEntryStatus(str, Enum):
    """Whether PDF bytes are present or recorded as an explicit gap."""

    PRESENT = "present"
    GAP = "gap"

    @classmethod
    def coerce(cls, value: Any) -> "InventoryEntryStatus":
        if isinstance(value, InventoryEntryStatus):
            return value
        text = str(value or "").strip().lower()
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise UsptoGuidancePdfError(f"unsupported inventory entry status: {value!r}")


class GapKind(str, Enum):
    """Explicit inventory / acquisition gap kinds."""

    UNAVAILABLE = "unavailable"
    CONTENT_CHANGED = "content_changed"
    DELAYED_INVENTORY = "delayed_inventory"
    HASH_MISMATCH = "hash_mismatch"
    RETRIEVAL_FAILED = "retrieval_failed"
    RIGHTS_FAILED = "rights_failed"
    EXTRACTION_FAILED = "extraction_failed"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GapKind":
        if isinstance(value, GapKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        return cls.OTHER


class SupersessionRelation(str, Enum):
    """How later guidance relates to earlier guidance PDFs."""

    SUPERSEDES = "supersedes"
    PARTIALLY_SUPERSEDES = "partially_supersedes"
    CLARIFIES = "clarifies"
    WITHDRAWS = "withdraws"
    RESTORES = "restores"
    UPDATES = "updates"

    @classmethod
    def coerce(cls, value: Any) -> "SupersessionRelation":
        if isinstance(value, SupersessionRelation):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        raise UsptoGuidancePdfError(f"unsupported supersession relation: {value!r}")


class GuidanceTopic(str, Enum):
    """Closed topic tags for USPTO examination guidance PDFs."""

    SUBJECT_MATTER_ELIGIBILITY = "subject_matter_eligibility"
    OBVIOUSNESS = "obviousness"
    ENABLEMENT = "enablement"
    WRITTEN_DESCRIPTION = "written_description"
    INDEFINITENESS = "indefiniteness"
    MEANS_PLUS_FUNCTION = "means_plus_function"
    PRIOR_ART = "prior_art"
    EXAMINATION = "examination"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GuidanceTopic":
        if isinstance(value, GuidanceTopic):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == text or member.name.lower() == text:
                return member
        return cls.OTHER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsptoGuidancePdfError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise UsptoGuidancePdfError(f"{name} must not contain NUL")
    if len(text) > max_len:
        raise UsptoGuidancePdfError(f"{name} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, name: str = "value", *, max_len: int = 4096) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name, max_len=max_len)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise UsptoGuidancePdfError(f"{name} must be a lowercase 64-char hex SHA-256")
    return text


def _optional_sha256(value: Any, name: str = "sha256") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_sha256(value, name)


def _optional_cid(value: Any, name: str = "cid") -> Optional[str]:
    text = _optional_str(value, name, max_len=256)
    if text is None:
        return None
    if not _CID_RE.fullmatch(text):
        raise UsptoGuidancePdfError(f"{name} must be a CIDv1 base32 token")
    return text


def _require_cid(value: Any, name: str = "cid") -> str:
    text = _require_non_empty_str(value, name, max_len=256)
    if not _CID_RE.fullmatch(text):
        raise UsptoGuidancePdfError(f"{name} must be a CIDv1 base32 token")
    return text


def _parse_required_date(value: Any, *, name: str = "cutoff") -> date:
    if value is None or value == "":
        raise MissingCutoffError(
            f"{name} is required on every guidance pin / inventory record"
        )
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()[:10]
        if not _DATE_RE.fullmatch(text):
            raise UsptoGuidancePdfError(f"{name} must be an ISO date (YYYY-MM-DD)")
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise UsptoGuidancePdfError(f"{name} must be an ISO date") from exc
    raise UsptoGuidancePdfError(f"{name} must be a date or ISO date string")


def _parse_optional_date(value: Any, *, name: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    return _parse_required_date(value, name=name)


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _parse_utc(value: Any, *, name: str = "retrieved_at") -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise UsptoGuidancePdfError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise UsptoGuidancePdfError(f"{name} must be a datetime or ISO-8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    normalized = dt.astimezone(timezone.utc).replace(
        microsecond=(dt.microsecond // 1000) * 1000
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def _omit_none(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is ``None`` (JSON Schema optional fields)."""
    return {k: v for k, v in payload.items() if v is not None}


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for contract round-trip equality."""
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


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def cid_from_digest(digest: str, *, prefix: str = "baguqeera") -> str:
    """Deterministic CIDv1 (base32) derived from a SHA-256 hex digest."""
    del prefix  # retained for API compatibility with other patent contracts
    text = _require_sha256(digest, "digest")
    return cid_v1_from_digest(bytes.fromhex(text))


def default_manifest_schema_path() -> Path:
    """Return the on-disk path to ``uspto_guidance_pdfs.manifest.schema.json``."""
    repo_root = Path(__file__).resolve().parents[4]
    return (
        repo_root
        / "data"
        / "release"
        / "patent_legal_intelligence"
        / MANIFEST_SCHEMA_FILENAME
    )


def load_manifest_schema(*, path: PathLike | None = None) -> dict[str, Any]:
    """Load the release JSON Schema for the USPTO guidance PDF inventory."""
    schema_path = Path(path) if path is not None else default_manifest_schema_path()
    if not schema_path.is_file():
        raise SchemaValidationError(f"manifest schema not found: {schema_path}")
    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SchemaValidationError("manifest schema root must be an object")
    return raw


def reject_unpinned_latest(value: Any, *, field_name: str) -> str:
    """Reject hard-coded ``latest`` tokens on guidance selection fields.

    Wraps :func:`reject_hard_coded_latest` and raises
    :class:`UnpinnedLatestSelectionError` so callers can distinguish unpinned
    selection from other pin errors.
    """
    text = _require_non_empty_str(str(value), field_name, max_len=256)
    try:
        reject_hard_coded_latest(text, field_name=field_name)
    except HardCodedLatestEditionError as exc:
        raise UnpinnedLatestSelectionError(str(exc)) from exc
    if _LATEST_TOKEN_RE.fullmatch(text):
        raise UnpinnedLatestSelectionError(
            f"{field_name} must not be the hard-coded token 'latest'; "
            "pin a concrete document_id/version/publication date"
        )
    return text


def assert_guidance_not_elevated(
    *,
    authority_tier: Any = AUTHORITY_TIER_GUIDANCE,
    is_binding: Any = False,
    elevates_to_law: Any = False,
    label: str = "record",
) -> None:
    """Fail closed when guidance is elevated to binding law."""
    tier = str(authority_tier or "").strip().lower()
    if tier and tier != AUTHORITY_TIER_GUIDANCE:
        raise BindingElevationError(
            f"{label}: authority_tier must be 'guidance' (got {authority_tier!r}); "
            "guidance PDFs never elevate to statute or regulation"
        )
    if is_binding is True:
        raise BindingElevationError(
            f"{label}: is_binding must be false; guidance never elevates to binding law"
        )
    if elevates_to_law is True:
        raise BindingElevationError(
            f"{label}: elevates_to_law must be false; supersession retains guidance tier"
        )


def assert_rights_reviewed_for_public(
    rights: RightsReview | Mapping[str, Any] | None,
    *,
    label: str = "record",
    require_reviewed: bool = True,
) -> RightsReview:
    """Require a rights review suitable for public corpus admission."""
    if rights is None:
        raise UnreviewedRightsError(f"{label}: rights_review is required")
    if isinstance(rights, RightsReview):
        review = rights
    elif isinstance(rights, Mapping):
        try:
            review = RightsReview.from_dict(rights)
        except Exception as exc:
            raise UnreviewedRightsError(
                f"{label}: rights_review is invalid: {exc}"
            ) from exc
    else:
        raise UnreviewedRightsError(f"{label}: rights_review must be a mapping or RightsReview")
    if require_reviewed and not review.reviewed_for_release:
        raise UnreviewedRightsError(
            f"{label}: rights_review must be reviewed with redistribution_allowed=true "
            f"(status={review.review_status.value!r})"
        )
    return review


def validate_uri(value: Any, *, name: str = "uri") -> str:
    """Validate an official guidance PDF URI (https/uspto/ipfs/hf)."""
    text = _require_non_empty_str(value, name, max_len=2048)
    if not _URI_RE.match(text):
        raise UsptoGuidancePdfError(
            f"{name} must use https://, uspto://, ipfs://, or hf:// (got {text!r})"
        )
    # Reject unpinned "latest" path segments as selection tokens.
    for segment in text.split("/"):
        if _LATEST_TOKEN_RE.fullmatch(segment):
            raise UnpinnedLatestSelectionError(
                f"{name} must not embed the hard-coded path token 'latest'"
            )
    return text


def normalize_extracted_text(
    text: str,
    *,
    profile: str = DEFAULT_NORMALIZATION_PROFILE,
) -> str:
    """Normalize extracted PDF text for deterministic digests.

    Profile ``unicode-nfc-ws-collapse-v1``:
    * Unicode NFC normalization
    * Convert CR/LF/tab runs to single spaces
    * Strip leading/trailing whitespace
    """
    if not isinstance(text, str):
        raise ExtractionDeterminismError("extracted text must be a string")
    profile_s = reject_unpinned_latest(profile, field_name="normalization_profile")
    if profile_s != DEFAULT_NORMALIZATION_PROFILE:
        # Future profiles may be added; unknown profiles fail closed so digests
        # cannot silently drift across extractor upgrades.
        raise ExtractionDeterminismError(
            f"unsupported normalization_profile: {profile_s!r}; "
            f"expected {DEFAULT_NORMALIZATION_PROFILE!r}"
        )
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WS_RE.sub(" ", normalized)
    return normalized.strip()


def deterministic_text_digest(
    text: str,
    *,
    profile: str = DEFAULT_NORMALIZATION_PROFILE,
) -> str:
    """SHA-256 of normalized extracted text (deterministic for identical text)."""
    return content_sha256(normalize_extracted_text(text, profile=profile))


def validate_extraction_determinism(
    *,
    pdf_bytes: bytes | str,
    text_a: str,
    text_b: str,
    profile: str = DEFAULT_NORMALIZATION_PROFILE,
) -> str:
    """Assert two extraction passes over the same PDF bytes yield one digest.

    Returns the shared ``text_sha256``. Raises
    :class:`ExtractionDeterminismError` on mismatch.
    """
    # pdf_bytes identity is advisory here (contracts layer has no PDF parser);
    # both texts must digest equal under the pinned normalization profile.
    del pdf_bytes
    dig_a = deterministic_text_digest(text_a, profile=profile)
    dig_b = deterministic_text_digest(text_b, profile=profile)
    if dig_a != dig_b:
        raise ExtractionDeterminismError(
            "text extraction is non-deterministic for identical PDF bytes: "
            f"{dig_a} != {dig_b}"
        )
    return dig_a


# ---------------------------------------------------------------------------
# Pin / identity
# ---------------------------------------------------------------------------


def parse_guidance_document_version(
    *,
    document_id: Any,
    version: Any,
) -> tuple[str, str]:
    """Validate concrete guidance document_id + version (never ``latest``)."""
    if document_id is None or (isinstance(document_id, str) and not document_id.strip()):
        raise GuidancePinError(
            "document_id pin is required (concrete document id, never 'latest')"
        )
    if version is None or (isinstance(version, str) and not version.strip()):
        raise GuidancePinError(
            "version pin is required (concrete version/date, never 'latest')"
        )
    try:
        doc_id = reject_unpinned_latest(str(document_id), field_name="document_id")
        ver = reject_unpinned_latest(str(version), field_name="version")
    except UnpinnedLatestSelectionError as exc:
        raise GuidancePinError(str(exc)) from exc
    doc_id = _require_non_empty_str(doc_id, "document_id", max_len=128)
    ver = _require_non_empty_str(ver, "version", max_len=64)
    if not _NONEMPTY_ID_RE.fullmatch(doc_id):
        raise GuidancePinError(f"document_id is not a valid identifier: {doc_id!r}")
    return doc_id, ver


def stable_guidance_pdf_identity(
    *,
    document_id: Any,
    version: Any,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> str:
    """Stable content identity for one pinned guidance PDF edition."""
    doc_id, ver = parse_guidance_document_version(
        document_id=document_id, version=version
    )
    jur = _require_non_empty_str(jurisdiction, "jurisdiction", max_len=16).lower()
    return f"uspto-guidance:{jur}:{doc_id}:v{ver}"


def default_public_rights_review(
    *,
    reviewed_by: str = "patlaw-184-fixture",
    reviewed_at: str = "2024-07-17T00:00:00Z",
    license_expression: str = DEFAULT_LICENSE,
    notes: str = "US government work; public official USPTO guidance PDF",
) -> RightsReview:
    """Build a reviewed public rights record suitable for fixture admission."""
    return RightsReview(
        license_expression=license_expression,
        review_status=RightsReviewStatus.REVIEWED,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        redistribution_allowed=True,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsptoGuidanceDocumentPin:
    """Concrete guidance document identity with cutoff date.

    Both ``document_id`` and ``version`` are required. The unpinned token
    ``\"latest\"`` is always rejected.
    """

    document_id: str
    version: str
    cutoff: date
    provider: str = DEFAULT_PROVIDER
    publication_date: Optional[date] = None
    title: Optional[str] = None
    topic: Optional[str] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        doc_id, ver = parse_guidance_document_version(
            document_id=self.document_id, version=self.version
        )
        object.__setattr__(self, "document_id", doc_id)
        object.__setattr__(self, "version", ver)
        object.__setattr__(self, "cutoff", _parse_required_date(self.cutoff, name="cutoff"))
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider", max_len=64)
        )
        reject_unpinned_latest(self.provider, field_name="provider")
        if self.publication_date is not None:
            object.__setattr__(
                self,
                "publication_date",
                _parse_required_date(self.publication_date, name="publication_date"),
            )
        if self.title is not None:
            object.__setattr__(
                self, "title", _require_non_empty_str(self.title, "title", max_len=512)
            )
        if self.topic is not None:
            topic_v = GuidanceTopic.coerce(self.topic)
            object.__setattr__(self, "topic", topic_v.value)
        if self.source_url is not None:
            object.__setattr__(self, "source_url", validate_uri(self.source_url, name="source_url"))
        if self.content_sha256 is not None:
            object.__setattr__(
                self, "content_sha256", _require_sha256(self.content_sha256, "content_sha256")
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes", max_len=4096)
            )
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def pin_key(self) -> str:
        """Stable document/version identity token (never ``latest``)."""
        return f"{self.document_id}-v{self.version}"

    @property
    def stable_identity(self) -> str:
        return stable_guidance_pdf_identity(
            document_id=self.document_id, version=self.version
        )

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "content_sha256": self.content_sha256,
                "cutoff": _date_to_str(self.cutoff),
                "document_id": self.document_id,
                "metadata": _deep_sorted(self.metadata) or None,
                "notes": self.notes,
                "pin_key": self.pin_key,
                "provider": self.provider,
                "publication_date": _date_to_str(self.publication_date),
                "retrieved_at": _format_utc(self.retrieved_at),
                "source_url": self.source_url,
                "title": self.title,
                "topic": self.topic,
                "version": self.version,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidanceDocumentPin":
        if not isinstance(value, Mapping):
            raise GuidancePinError("document pin must be a mapping")
        if value.get("cutoff") in (None, ""):
            raise MissingCutoffError("cutoff is required on every guidance document pin")
        if value.get("document_id") in (None, "") and value.get("pin_key") in (None, ""):
            raise GuidancePinError("document_id pin is required")
        if value.get("version") in (None, ""):
            raise GuidancePinError("version pin is required")
        document_id = value.get("document_id") or ""
        if not document_id and value.get("pin_key"):
            document_id = str(value.get("pin_key"))
        return cls(
            document_id=str(document_id),
            version=str(value.get("version") or ""),
            cutoff=value["cutoff"],
            provider=str(value.get("provider") or DEFAULT_PROVIDER),
            publication_date=value.get("publication_date"),
            title=value.get("title"),
            topic=value.get("topic"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class PdfTextExtractionContract:
    """Deterministic text-extraction binding for one PDF.

    Identical PDF bytes + the same method/profile must produce the same
    ``text_sha256``. Acquisition (PATLAW-185) populates these fields after
    offline extraction.
    """

    method: str
    text_sha256: str
    page_count: int
    normalization_profile: str = DEFAULT_NORMALIZATION_PROFILE
    extractor_version: str = "1.0.0"
    char_count: Optional[int] = None
    media_type: str = "text/plain"
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        method = reject_unpinned_latest(self.method, field_name="method")
        object.__setattr__(
            self, "method", _require_non_empty_str(method, "method", max_len=64)
        )
        profile = reject_unpinned_latest(
            self.normalization_profile, field_name="normalization_profile"
        )
        object.__setattr__(
            self,
            "normalization_profile",
            _require_non_empty_str(profile, "normalization_profile", max_len=128),
        )
        object.__setattr__(
            self, "text_sha256", _require_sha256(self.text_sha256, "text_sha256")
        )
        if not isinstance(self.page_count, int) or isinstance(self.page_count, bool):
            raise ExtractionDeterminismError("page_count must be a non-negative integer")
        if self.page_count < 0:
            raise ExtractionDeterminismError("page_count must be >= 0")
        object.__setattr__(
            self,
            "extractor_version",
            reject_unpinned_latest(
                _require_non_empty_str(
                    self.extractor_version, "extractor_version", max_len=64
                ),
                field_name="extractor_version",
            ),
        )
        if self.char_count is not None:
            if not isinstance(self.char_count, int) or isinstance(self.char_count, bool):
                raise ExtractionDeterminismError("char_count must be a non-negative integer")
            if self.char_count < 0:
                raise ExtractionDeterminismError("char_count must be >= 0")
        object.__setattr__(
            self,
            "media_type",
            _require_non_empty_str(self.media_type, "media_type", max_len=128),
        )
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes", max_len=2048)
            )
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "char_count": self.char_count,
                "extractor_version": self.extractor_version,
                "media_type": self.media_type,
                "metadata": _deep_sorted(self.metadata) or None,
                "method": self.method,
                "normalization_profile": self.normalization_profile,
                "notes": self.notes,
                "page_count": self.page_count,
                "text_sha256": self.text_sha256,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "PdfTextExtractionContract":
        if not isinstance(value, Mapping):
            raise ExtractionDeterminismError("extraction contract must be a mapping")
        return cls(
            method=str(value.get("method") or DEFAULT_EXTRACTION_METHOD),
            text_sha256=str(value.get("text_sha256") or ""),
            page_count=int(value.get("page_count") if value.get("page_count") is not None else -1),
            normalization_profile=str(
                value.get("normalization_profile") or DEFAULT_NORMALIZATION_PROFILE
            ),
            extractor_version=str(value.get("extractor_version") or "1.0.0"),
            char_count=(
                int(value["char_count"])
                if value.get("char_count") is not None
                else None
            ),
            media_type=str(value.get("media_type") or "text/plain"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def from_extracted_text(
        cls,
        text: str,
        *,
        page_count: int,
        method: str = DEFAULT_EXTRACTION_METHOD,
        profile: str = DEFAULT_NORMALIZATION_PROFILE,
        extractor_version: str = "1.0.0",
        notes: Optional[str] = None,
    ) -> "PdfTextExtractionContract":
        """Build a contract from raw extracted text (normalized + digested)."""
        normalized = normalize_extracted_text(text, profile=profile)
        return cls(
            method=method,
            text_sha256=content_sha256(normalized),
            page_count=page_count,
            normalization_profile=profile,
            extractor_version=extractor_version,
            char_count=len(normalized),
            notes=notes,
        )


@dataclass(frozen=True, slots=True)
class UsptoGuidancePdfInventoryEntry:
    """One pinned USPTO guidance PDF in the discovery inventory.

    Required bindings for acceptance: ``uri``, ``sha256``, ``publication_date``,
    ``cutoff``, and ``rights_review``. Always guidance-tier and non-binding.
    """

    entry_id: str
    document_id: str
    version: str
    uri: str
    sha256: str
    publication_date: date
    cutoff: date
    rights_review: RightsReview
    page_count: int
    status: InventoryEntryStatus = InventoryEntryStatus.PRESENT
    title: Optional[str] = None
    topic: str = GuidanceTopic.OTHER.value
    size_bytes: Optional[int] = None
    media_type: str = DEFAULT_MEDIA_TYPE
    content_cid: Optional[str] = None
    classification: str = DEFAULT_CLASSIFICATION
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    extraction: Optional[PdfTextExtractionContract] = None
    gap_reason: Optional[str] = None
    source_span: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_id", _require_non_empty_str(self.entry_id, "entry_id", max_len=256)
        )
        if not _NONEMPTY_ID_RE.fullmatch(self.entry_id):
            raise UsptoGuidancePdfError(
                f"entry_id is not a valid identifier: {self.entry_id!r}"
            )
        doc_id, ver = parse_guidance_document_version(
            document_id=self.document_id, version=self.version
        )
        object.__setattr__(self, "document_id", doc_id)
        object.__setattr__(self, "version", ver)
        object.__setattr__(self, "uri", validate_uri(self.uri, name="uri"))
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "publication_date",
            _parse_required_date(self.publication_date, name="publication_date"),
        )
        object.__setattr__(
            self, "cutoff", _parse_required_date(self.cutoff, name="cutoff")
        )

        status_v = InventoryEntryStatus.coerce(self.status)
        object.__setattr__(self, "status", status_v)

        review = assert_rights_reviewed_for_public(
            self.rights_review,
            label=f"entry {self.entry_id}",
            require_reviewed=(status_v is InventoryEntryStatus.PRESENT),
        )
        object.__setattr__(self, "rights_review", review)

        if not isinstance(self.page_count, int) or isinstance(self.page_count, bool):
            raise UsptoGuidancePdfError("page_count must be a non-negative integer")
        if self.page_count < 0:
            raise UsptoGuidancePdfError("page_count must be >= 0")
        if status_v is InventoryEntryStatus.PRESENT and self.page_count < 1:
            raise UsptoGuidancePdfError(
                f"entry {self.entry_id!r}: present PDFs require page_count >= 1"
            )

        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label=f"entry {self.entry_id}",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)

        classification = _require_non_empty_str(
            self.classification, "classification", max_len=64
        ).lower().replace("-", "_")
        if classification not in PUBLIC_CLASSIFICATION_SET:
            raise PrivateOrNonPublicError(
                f"entry {self.entry_id!r}: classification {classification!r} "
                f"is not public; non-public packages fail closed"
            )
        object.__setattr__(self, "classification", classification)

        object.__setattr__(self, "topic", GuidanceTopic.coerce(self.topic).value)
        object.__setattr__(
            self,
            "media_type",
            _require_non_empty_str(self.media_type, "media_type", max_len=128),
        )
        if self.media_type not in (DEFAULT_MEDIA_TYPE, "application/pdf"):
            # Allow exact application/pdf only for this inventory.
            if self.media_type != "application/pdf":
                raise UsptoGuidancePdfError(
                    f"entry {self.entry_id!r}: media_type must be application/pdf"
                )

        if self.title is not None:
            object.__setattr__(
                self, "title", _require_non_empty_str(self.title, "title", max_len=512)
            )
        if self.size_bytes is not None:
            if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
                raise UsptoGuidancePdfError("size_bytes must be a non-negative integer")
            if self.size_bytes < 0:
                raise UsptoGuidancePdfError("size_bytes must be >= 0")
        if self.content_cid is not None:
            object.__setattr__(
                self, "content_cid", _optional_cid(self.content_cid, "content_cid")
            )

        extraction = self.extraction
        if extraction is not None and not isinstance(extraction, PdfTextExtractionContract):
            if isinstance(extraction, Mapping):
                extraction = PdfTextExtractionContract.from_dict(extraction)
            else:
                raise ExtractionDeterminismError(
                    f"entry {self.entry_id!r}: extraction must be a mapping or "
                    "PdfTextExtractionContract"
                )
            object.__setattr__(self, "extraction", extraction)
        if (
            status_v is InventoryEntryStatus.PRESENT
            and extraction is not None
            and extraction.page_count != self.page_count
        ):
            raise ExtractionDeterminismError(
                f"entry {self.entry_id!r}: extraction.page_count "
                f"({extraction.page_count}) must match inventory page_count "
                f"({self.page_count})"
            )

        if status_v is InventoryEntryStatus.GAP:
            if not self.gap_reason:
                raise UsptoGuidancePdfError(
                    f"entry {self.entry_id!r}: gap status requires gap_reason"
                )
            object.__setattr__(
                self,
                "gap_reason",
                _require_non_empty_str(self.gap_reason, "gap_reason", max_len=2048),
            )
        elif self.gap_reason is not None:
            object.__setattr__(
                self,
                "gap_reason",
                _require_non_empty_str(self.gap_reason, "gap_reason", max_len=2048),
            )

        if self.source_span is not None:
            object.__setattr__(
                self,
                "source_span",
                _require_non_empty_str(self.source_span, "source_span", max_len=256),
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def pin_key(self) -> str:
        return f"{self.document_id}-v{self.version}"

    @property
    def stable_identity(self) -> str:
        return stable_guidance_pdf_identity(
            document_id=self.document_id, version=self.version
        )

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "classification": self.classification,
                "content_cid": self.content_cid,
                "cutoff": _date_to_str(self.cutoff),
                "document_id": self.document_id,
                "entry_id": self.entry_id,
                "extraction": self.extraction.to_dict() if self.extraction else None,
                "gap_reason": self.gap_reason,
                "is_binding": False,
                "media_type": self.media_type,
                "metadata": _deep_sorted(self.metadata) or None,
                "page_count": self.page_count,
                "publication_date": _date_to_str(self.publication_date),
                "retrieved_at": _format_utc(self.retrieved_at),
                "rights_review": self.rights_review.to_dict(),
                "sha256": self.sha256,
                "size_bytes": self.size_bytes,
                "source_span": self.source_span,
                "status": self.status.value,
                "title": self.title,
                "topic": self.topic,
                "uri": self.uri,
                "version": self.version,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidancePdfInventoryEntry":
        if not isinstance(value, Mapping):
            raise UsptoGuidancePdfError("inventory entry must be a mapping")
        rights_raw = value.get("rights_review")
        if rights_raw is None:
            raise UnreviewedRightsError("rights_review is required on every inventory entry")
        extraction_raw = value.get("extraction")
        extraction: Optional[PdfTextExtractionContract] = None
        if extraction_raw is not None:
            extraction = PdfTextExtractionContract.from_dict(extraction_raw)
        # Accept sha256 under either key used by adjacent contracts.
        digest = value.get("sha256") or value.get("content_sha256") or ""
        return cls(
            entry_id=str(value.get("entry_id") or value.get("id") or ""),
            document_id=str(value.get("document_id") or ""),
            version=str(value.get("version") or ""),
            uri=str(value.get("uri") or value.get("source_url") or ""),
            sha256=str(digest),
            publication_date=value.get("publication_date") or "",
            cutoff=value.get("cutoff") or "",
            rights_review=RightsReview.from_dict(rights_raw),  # type: ignore[arg-type]
            page_count=int(value.get("page_count") if value.get("page_count") is not None else 0),
            status=InventoryEntryStatus.coerce(
                value.get("status", InventoryEntryStatus.PRESENT)
            ),
            title=value.get("title"),
            topic=str(value.get("topic") or GuidanceTopic.OTHER.value),
            size_bytes=(
                int(value["size_bytes"]) if value.get("size_bytes") is not None else None
            ),
            media_type=str(value.get("media_type") or DEFAULT_MEDIA_TYPE),
            content_cid=value.get("content_cid"),
            classification=str(value.get("classification") or DEFAULT_CLASSIFICATION),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            extraction=extraction,
            gap_reason=value.get("gap_reason"),
            source_span=value.get("source_span"),
            retrieved_at=value.get("retrieved_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UsptoGuidanceInventoryGap:
    """Explicit gap when a guidance PDF unit is incomplete."""

    gap_id: str
    kind: GapKind
    document_id: str
    reason: str
    version: Optional[str] = None
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    expected_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    uri: Optional[str] = None
    detected_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "gap_id", _require_non_empty_str(self.gap_id, "gap_id", max_len=256)
        )
        object.__setattr__(self, "kind", GapKind.coerce(self.kind))
        doc_id = reject_unpinned_latest(
            _require_non_empty_str(self.document_id, "document_id", max_len=128),
            field_name="document_id",
        )
        object.__setattr__(self, "document_id", doc_id)
        object.__setattr__(
            self, "reason", _require_non_empty_str(self.reason, "reason", max_len=2048)
        )
        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=False,
            elevates_to_law=False,
            label=f"gap {self.gap_id}",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        if self.version is not None:
            object.__setattr__(
                self,
                "version",
                reject_unpinned_latest(
                    _require_non_empty_str(self.version, "version", max_len=64),
                    field_name="version",
                ),
            )
        if self.expected_sha256 is not None:
            object.__setattr__(
                self,
                "expected_sha256",
                _require_sha256(self.expected_sha256, "expected_sha256"),
            )
        if self.observed_sha256 is not None:
            object.__setattr__(
                self,
                "observed_sha256",
                _require_sha256(self.observed_sha256, "observed_sha256"),
            )
        if self.uri is not None:
            object.__setattr__(self, "uri", validate_uri(self.uri, name="uri"))
        if self.detected_at is not None:
            object.__setattr__(
                self, "detected_at", _parse_utc(self.detected_at, name="detected_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "detected_at": _format_utc(self.detected_at),
                "document_id": self.document_id,
                "expected_sha256": self.expected_sha256,
                "gap_id": self.gap_id,
                "kind": self.kind.value,
                "metadata": _deep_sorted(self.metadata) or None,
                "observed_sha256": self.observed_sha256,
                "reason": self.reason,
                "uri": self.uri,
                "version": self.version,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidanceInventoryGap":
        if not isinstance(value, Mapping):
            raise UsptoGuidancePdfError("gap must be a mapping")
        return cls(
            gap_id=str(value.get("gap_id") or value.get("id") or ""),
            kind=GapKind.coerce(value.get("kind", GapKind.OTHER)),
            document_id=str(value.get("document_id") or ""),
            reason=str(value.get("reason") or ""),
            version=value.get("version"),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            expected_sha256=value.get("expected_sha256"),
            observed_sha256=value.get("observed_sha256"),
            uri=value.get("uri") or value.get("source_url"),
            detected_at=value.get("detected_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UsptoGuidanceSupersessionRecord:
    """Supersession edge between guidance PDF editions.

    Prior editions remain as evidence. Both endpoints remain guidance-tier;
    supersession never elevates guidance to binding law.
    """

    successor_id: str
    predecessor_id: str
    relation: SupersessionRelation = SupersessionRelation.SUPERSEDES
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    remains_guidance: bool = True
    elevates_to_law: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "successor_id",
            _require_non_empty_str(self.successor_id, "successor_id", max_len=256),
        )
        object.__setattr__(
            self,
            "predecessor_id",
            _require_non_empty_str(self.predecessor_id, "predecessor_id", max_len=256),
        )
        reject_unpinned_latest(self.successor_id, field_name="successor_id")
        reject_unpinned_latest(self.predecessor_id, field_name="predecessor_id")
        object.__setattr__(self, "relation", SupersessionRelation.coerce(self.relation))
        if self.effective_date is not None:
            object.__setattr__(
                self,
                "effective_date",
                _parse_required_date(self.effective_date, name="effective_date"),
            )
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _require_non_empty_str(self.reason, "reason", max_len=2048)
            )
        if self.remains_guidance is not True:
            raise BindingElevationError(
                "supersession remains_guidance must be true; prior editions stay guidance"
            )
        assert_guidance_not_elevated(
            elevates_to_law=self.elevates_to_law,
            label="supersession",
        )
        object.__setattr__(self, "remains_guidance", True)
        object.__setattr__(self, "elevates_to_law", False)
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "effective_date": _date_to_str(self.effective_date),
                "elevates_to_law": False,
                "metadata": _deep_sorted(self.metadata) or None,
                "predecessor_id": self.predecessor_id,
                "reason": self.reason,
                "relation": self.relation.value,
                "remains_guidance": True,
                "successor_id": self.successor_id,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidanceSupersessionRecord":
        if not isinstance(value, Mapping):
            raise UsptoGuidancePdfError("supersession must be a mapping")
        return cls(
            successor_id=str(value.get("successor_id") or ""),
            predecessor_id=str(value.get("predecessor_id") or ""),
            relation=SupersessionRelation.coerce(
                value.get("relation", SupersessionRelation.SUPERSEDES)
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
            remains_guidance=bool(value.get("remains_guidance", True)),
            elevates_to_law=bool(value.get("elevates_to_law", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UsptoGuidancePdfInventoryCounts:
    """Tallies for a guidance PDF inventory manifest."""

    documents_required: int
    documents_present: int
    gap_entries: int
    page_total: int
    supersession_edges: int
    with_extraction: int

    def __post_init__(self) -> None:
        for name in (
            "documents_required",
            "documents_present",
            "gap_entries",
            "page_total",
            "supersession_edges",
            "with_extraction",
        ):
            val = getattr(self, name)
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise SchemaValidationError(f"counts.{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents_present": self.documents_present,
            "documents_required": self.documents_required,
            "gap_entries": self.gap_entries,
            "page_total": self.page_total,
            "supersession_edges": self.supersession_edges,
            "with_extraction": self.with_extraction,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidancePdfInventoryCounts":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("counts must be a mapping")
        return cls(
            documents_required=int(value.get("documents_required") or 0),
            documents_present=int(value.get("documents_present") or 0),
            gap_entries=int(value.get("gap_entries") or 0),
            page_total=int(value.get("page_total") or 0),
            supersession_edges=int(value.get("supersession_edges") or 0),
            with_extraction=int(value.get("with_extraction") or 0),
        )


def compute_counts(
    inventory: Sequence[UsptoGuidancePdfInventoryEntry],
    *,
    supersessions: Sequence[UsptoGuidanceSupersessionRecord] = (),
    gaps: Sequence[UsptoGuidanceInventoryGap] = (),
    documents_required: int | None = None,
) -> UsptoGuidancePdfInventoryCounts:
    """Compute inventory tallies from entries + supersession/gap edges."""
    present = [e for e in inventory if e.status is InventoryEntryStatus.PRESENT]
    gap_entries = [e for e in inventory if e.status is InventoryEntryStatus.GAP]
    required = (
        documents_required
        if documents_required is not None
        else max(len(REQUIRED_GUIDANCE_DOCUMENTS), len(inventory))
    )
    return UsptoGuidancePdfInventoryCounts(
        documents_required=required,
        documents_present=len(present),
        gap_entries=len(gap_entries) + len(tuple(gaps)),
        page_total=sum(e.page_count for e in present),
        supersession_edges=len(tuple(supersessions)),
        with_extraction=sum(1 for e in present if e.extraction is not None),
    )


def validate_inventory_nonempty(
    inventory: Sequence[UsptoGuidancePdfInventoryEntry],
) -> None:
    """Fail closed on empty inventories."""
    if not inventory:
        raise IncompleteInventoryError(
            "inventory must be a non-empty array of pinned guidance PDFs"
        )


def validate_required_bindings(entry: UsptoGuidancePdfInventoryEntry) -> None:
    """Assert URI, sha256, publication/cutoff, and rights review are bound."""
    if not entry.uri:
        raise SchemaValidationError(f"entry {entry.entry_id!r}: uri is required")
    if not entry.sha256:
        raise SchemaValidationError(f"entry {entry.entry_id!r}: sha256 is required")
    if entry.publication_date is None:
        raise MissingCutoffError(
            f"entry {entry.entry_id!r}: publication_date is required"
        )
    if entry.cutoff is None:
        raise MissingCutoffError(f"entry {entry.entry_id!r}: cutoff is required")
    assert_rights_reviewed_for_public(
        entry.rights_review,
        label=f"entry {entry.entry_id}",
        require_reviewed=(entry.status is InventoryEntryStatus.PRESENT),
    )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsptoGuidancePdfInventoryManifest:
    """Top-level content-addressed inventory of pinned USPTO guidance PDFs."""

    edition_pin: UsptoGuidanceDocumentPin
    inventory: tuple[UsptoGuidancePdfInventoryEntry, ...]
    counts: UsptoGuidancePdfInventoryCounts
    inventory_digest_sha256: str
    package_digest_sha256: str
    package_root_cid: str
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    producer: str = PRODUCER
    config_id: str = CONFIG_ID
    code_version: str = CODE_VERSION
    authority_tier: str = AUTHORITY_TIER_GUIDANCE
    is_binding: bool = False
    supersessions: tuple[UsptoGuidanceSupersessionRecord, ...] = ()
    gaps: tuple[UsptoGuidanceInventoryGap, ...] = ()
    partition: str = DEFAULT_PARTITION
    mode: str = "dry_run"
    staged_at_utc: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.edition_pin, UsptoGuidanceDocumentPin):
            raise GuidancePinError("edition_pin must be UsptoGuidanceDocumentPin")
        inv = tuple(self.inventory)
        validate_inventory_nonempty(inv)
        object.__setattr__(self, "inventory", inv)
        for entry in inv:
            validate_required_bindings(entry)

        assert_guidance_not_elevated(
            authority_tier=self.authority_tier,
            is_binding=self.is_binding,
            elevates_to_law=False,
            label="manifest",
        )
        object.__setattr__(self, "authority_tier", AUTHORITY_TIER_GUIDANCE)
        object.__setattr__(self, "is_binding", False)

        if self.partition != DEFAULT_PARTITION:
            raise PrivateOrNonPublicError(
                f"partition must be 'public' (got {self.partition!r})"
            )
        mode = _require_non_empty_str(self.mode, "mode", max_len=32)
        if mode not in ("dry_run", "stage", "acquire"):
            raise SchemaValidationError(f"unsupported mode: {mode!r}")
        object.__setattr__(self, "mode", mode)

        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaValidationError(
                f"schema_version must be {SCHEMA_VERSION!r} (got {self.schema_version!r})"
            )
        object.__setattr__(
            self, "interface", _require_non_empty_str(self.interface, "interface", max_len=128)
        )
        if self.interface != INTERFACE:
            raise SchemaValidationError(
                f"interface must be {INTERFACE!r} (got {self.interface!r})"
            )
        object.__setattr__(
            self, "task_id", _require_non_empty_str(self.task_id, "task_id", max_len=64)
        )
        if self.task_id != TASK_ID:
            raise SchemaValidationError(f"task_id must be {TASK_ID!r}")
        object.__setattr__(
            self, "goal_id", _require_non_empty_str(self.goal_id, "goal_id", max_len=64)
        )
        if self.goal_id != GOAL_ID:
            raise SchemaValidationError(f"goal_id must be {GOAL_ID!r}")
        object.__setattr__(
            self, "producer", _require_non_empty_str(self.producer, "producer", max_len=128)
        )
        object.__setattr__(
            self, "config_id", _require_non_empty_str(self.config_id, "config_id", max_len=128)
        )
        object.__setattr__(
            self,
            "code_version",
            _require_non_empty_str(self.code_version, "code_version", max_len=64),
        )

        object.__setattr__(
            self,
            "inventory_digest_sha256",
            _require_sha256(self.inventory_digest_sha256, "inventory_digest_sha256"),
        )
        object.__setattr__(
            self,
            "package_digest_sha256",
            _require_sha256(self.package_digest_sha256, "package_digest_sha256"),
        )
        object.__setattr__(
            self, "package_root_cid", _require_cid(self.package_root_cid, "package_root_cid")
        )

        supers = tuple(self.supersessions)
        gap_t = tuple(self.gaps)
        object.__setattr__(self, "supersessions", supers)
        object.__setattr__(self, "gaps", gap_t)

        if not isinstance(self.counts, UsptoGuidancePdfInventoryCounts):
            raise SchemaValidationError("counts must be UsptoGuidancePdfInventoryCounts")
        expected = compute_counts(
            inv,
            supersessions=supers,
            gaps=gap_t,
            documents_required=self.counts.documents_required,
        )
        # Allow documents_required from the built counts; verify present/pages.
        if self.counts.documents_present != expected.documents_present:
            raise SchemaValidationError(
                "counts.documents_present does not match inventory"
            )
        if self.counts.page_total != expected.page_total:
            raise SchemaValidationError("counts.page_total does not match inventory")
        if self.counts.with_extraction != expected.with_extraction:
            raise SchemaValidationError(
                "counts.with_extraction does not match inventory"
            )

        if self.staged_at_utc is not None:
            # Validate format via parse round-trip.
            _parse_utc(self.staged_at_utc, name="staged_at_utc")
            object.__setattr__(
                self,
                "staged_at_utc",
                _format_utc(_parse_utc(self.staged_at_utc, name="staged_at_utc")),
            )
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes", max_len=4096)
            )
        if not isinstance(self.metadata, Mapping):
            raise UsptoGuidancePdfError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

        inv_digest = content_digest_of([e.to_dict() for e in inv])
        if inv_digest != self.inventory_digest_sha256:
            raise SchemaValidationError(
                "inventory_digest_sha256 does not match canonical inventory payload"
            )

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "authority_tier": AUTHORITY_TIER_GUIDANCE,
                "code_version": self.code_version,
                "config_id": self.config_id,
                "counts": self.counts.to_dict(),
                "edition_pin": self.edition_pin.to_dict(),
                "gaps": [g.to_dict() for g in self.gaps] or None,
                "goal_id": self.goal_id,
                "interface": self.interface,
                "inventory": [e.to_dict() for e in self.inventory],
                "inventory_digest_sha256": self.inventory_digest_sha256,
                "is_binding": False,
                "metadata": _deep_sorted(self.metadata) or None,
                "mode": self.mode,
                "notes": self.notes,
                "package_digest_sha256": self.package_digest_sha256,
                "package_root_cid": self.package_root_cid,
                "partition": self.partition,
                "producer": self.producer,
                "schema_version": self.schema_version,
                "staged_at_utc": self.staged_at_utc,
                "supersessions": [s.to_dict() for s in self.supersessions] or None,
                "task_id": self.task_id,
            }
        )

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "UsptoGuidancePdfInventoryManifest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("manifest must be a mapping")
        pin_raw = value.get("edition_pin") or value.get("document_pin")
        if not isinstance(pin_raw, Mapping):
            raise GuidancePinError("edition_pin is required and must be a mapping")
        inv_raw = value.get("inventory")
        if not isinstance(inv_raw, list) or not inv_raw:
            raise IncompleteInventoryError(
                "inventory must be a non-empty array of pinned guidance PDFs"
            )
        inventory = tuple(UsptoGuidancePdfInventoryEntry.from_dict(e) for e in inv_raw)
        supersessions = tuple(
            UsptoGuidanceSupersessionRecord.from_dict(s)
            for s in (value.get("supersessions") or [])
        )
        gaps = tuple(
            UsptoGuidanceInventoryGap.from_dict(g) for g in (value.get("gaps") or [])
        )
        counts_raw = value.get("counts")
        if isinstance(counts_raw, Mapping):
            counts = UsptoGuidancePdfInventoryCounts.from_dict(counts_raw)
        else:
            counts = compute_counts(
                inventory, supersessions=supersessions, gaps=gaps
            )
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            edition_pin=UsptoGuidanceDocumentPin.from_dict(pin_raw),
            inventory=inventory,
            counts=counts,
            inventory_digest_sha256=str(value.get("inventory_digest_sha256") or ""),
            package_digest_sha256=str(value.get("package_digest_sha256") or ""),
            package_root_cid=str(value.get("package_root_cid") or ""),
            authority_tier=str(value.get("authority_tier") or AUTHORITY_TIER_GUIDANCE),
            is_binding=bool(value.get("is_binding", False)),
            supersessions=supersessions,
            gaps=gaps,
            partition=str(value.get("partition") or DEFAULT_PARTITION),
            mode=str(value.get("mode") or "dry_run"),
            staged_at_utc=value.get("staged_at_utc"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


def build_uspto_guidance_pdf_manifest(
    *,
    edition_pin: UsptoGuidanceDocumentPin,
    inventory: Sequence[UsptoGuidancePdfInventoryEntry],
    supersessions: Sequence[UsptoGuidanceSupersessionRecord] = (),
    gaps: Sequence[UsptoGuidanceInventoryGap] = (),
    mode: str = "dry_run",
    notes: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    staged_at_utc: Optional[str] = None,
    documents_required: int | None = None,
) -> UsptoGuidancePdfInventoryManifest:
    """Build a validated guidance PDF inventory with content digests."""
    inv = tuple(inventory)
    supers = tuple(supersessions)
    gap_t = tuple(gaps)
    counts = compute_counts(
        inv,
        supersessions=supers,
        gaps=gap_t,
        documents_required=documents_required,
    )
    inv_digest = content_digest_of([e.to_dict() for e in inv])
    package_payload = {
        "edition_pin": edition_pin.to_dict(),
        "inventory_digest_sha256": inv_digest,
        "counts": counts.to_dict(),
        "supersessions": [s.to_dict() for s in supers],
        "gaps": [g.to_dict() for g in gap_t],
    }
    package_digest = content_digest_of(package_payload)
    return UsptoGuidancePdfInventoryManifest(
        edition_pin=edition_pin,
        inventory=inv,
        counts=counts,
        inventory_digest_sha256=inv_digest,
        package_digest_sha256=package_digest,
        package_root_cid=cid_from_digest(package_digest),
        supersessions=supers,
        gaps=gap_t,
        mode=mode,
        notes=notes,
        metadata=dict(metadata or {}),
        staged_at_utc=staged_at_utc,
    )


def build_compact_guidance_pdf_fixture(
    *,
    include_extraction: bool = True,
    include_supersession: bool = True,
    inventory_cutoff: str | date = "2024-07-17",
) -> dict[str, Any]:
    """Build a compact offline inventory covering required guidance PDFs.

    Suitable for unit tests and dry-runs; not a substitute for live acquisition
    (PATLAW-185).
    """
    cutoff_d = (
        inventory_cutoff
        if isinstance(inventory_cutoff, date)
        else date.fromisoformat(str(inventory_cutoff)[:10])
    )
    # Inventory-level pin records the as-of selection for the whole package;
    # individual entries carry their own document_id/version pins.
    pin = UsptoGuidanceDocumentPin(
        document_id="uspto-guidance-inventory",
        version=cutoff_d.isoformat(),
        cutoff=cutoff_d,
        provider=DEFAULT_PROVIDER,
        publication_date=cutoff_d,
        title="USPTO examination guidance PDF inventory (compact fixture)",
        topic=GuidanceTopic.EXAMINATION.value,
        source_url="https://www.uspto.gov/patents/laws/examination-policy",
        notes=(
            f"Pinned inventory as-of {cutoff_d.isoformat()}; "
            "never selects unpinned 'latest' guidance"
        ),
    )
    rights = default_public_rights_review(
        reviewed_at=f"{cutoff_d.isoformat()}T00:00:00Z",
    )
    inventory: list[UsptoGuidancePdfInventoryEntry] = []
    for spec in REQUIRED_GUIDANCE_DOCUMENTS:
        body = f"fixture-pdf:{spec.document_id}:v{spec.version}:{spec.uri}"
        digest = content_sha256(body)
        extraction: Optional[PdfTextExtractionContract] = None
        if include_extraction:
            sample_text = (
                f"{spec.title}\n\nFixture extracted text for {spec.document_id} "
                f"version {spec.version}. Guidance only; not binding law."
            )
            extraction = PdfTextExtractionContract.from_extracted_text(
                sample_text,
                page_count=spec.page_count,
                method=DEFAULT_EXTRACTION_METHOD,
                notes="Deterministic fixture extraction; not live PDF parse.",
            )
        inventory.append(
            UsptoGuidancePdfInventoryEntry(
                entry_id=f"pdf-{spec.document_id}-v{spec.version}",
                document_id=spec.document_id,
                version=spec.version,
                uri=spec.uri,
                sha256=digest,
                publication_date=date.fromisoformat(spec.publication_date),
                cutoff=date.fromisoformat(spec.cutoff),
                rights_review=rights,
                page_count=spec.page_count,
                status=InventoryEntryStatus.PRESENT,
                title=spec.title,
                topic=spec.topic,
                size_bytes=max(spec.page_count * 40_000, 8_000),
                content_cid=cid_from_digest(digest),
                extraction=extraction,
                source_span=f"pdf:pages:1-{spec.page_count}",
            )
        )

    supersessions: list[UsptoGuidanceSupersessionRecord] = []
    if include_supersession:
        supersessions.append(
            UsptoGuidanceSupersessionRecord(
                successor_id="pdf-sme-2024-ai-examples-v2024-07-17",
                predecessor_id="pdf-sme-2019-peg-october-update-v2019-10-17",
                relation=SupersessionRelation.UPDATES,
                effective_date=date(2024, 7, 17),
                reason=(
                    "2024 AI SME guidance updates the 2019 PEG October update for "
                    "listed AI examples; prior PDF retained as evidence. Both remain "
                    "guidance, not law."
                ),
            )
        )
        supersessions.append(
            UsptoGuidanceSupersessionRecord(
                successor_id="pdf-exam-guide-1-23-v2023-03-15",
                predecessor_id="pdf-sme-2019-peg-v2019-01-07",
                relation=SupersessionRelation.CLARIFIES,
                effective_date=date(2023, 3, 15),
                reason=(
                    "Examination Guide 1-23 clarifies SME examples relative to the "
                    "2019 PEG; prior edition retained."
                ),
            )
        )

    manifest = build_uspto_guidance_pdf_manifest(
        edition_pin=pin,
        inventory=inventory,
        supersessions=supersessions,
        mode="dry_run",
        notes=(
            "Compact USPTO guidance PDF inventory fixture for PATLAW-184. "
            "Each entry binds URI, sha256, publication date/cutoff, and rights "
            "review. Unpinned 'latest' selection is forbidden. Guidance only; "
            "never binding law."
        ),
        documents_required=len(REQUIRED_GUIDANCE_DOCUMENTS),
    )
    return manifest.to_dict()


def validate_manifest_dict(value: JsonMapping) -> UsptoGuidancePdfInventoryManifest:
    """Validate a mapping as a USPTO guidance PDF inventory manifest."""
    return UsptoGuidancePdfInventoryManifest.from_dict(value)


def validate_manifest_against_json_schema(
    value: JsonMapping,
    *,
    schema: Mapping[str, Any] | None = None,
) -> None:
    """Validate *value* against the release JSON Schema when jsonschema is present.

    Raises SchemaValidationError on failure. If jsonschema is not installed,
    performs Python-side validation only (still fail-closed on contract errors).
    """
    validate_manifest_dict(value)
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return
    schema_obj = schema if schema is not None else load_manifest_schema()
    try:
        jsonschema.Draft202012Validator.check_schema(schema_obj)
        validator = jsonschema.Draft202012Validator(schema_obj)
        errors = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
    except Exception as exc:  # pragma: no cover
        raise SchemaValidationError(f"jsonschema validation failed: {exc}") from exc
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise SchemaValidationError(
            f"manifest fails JSON Schema at {path}: {first.message}"
        )


def iter_required_document_ids() -> Iterator[str]:
    """Yield required guidance document ids in catalog order."""
    for spec in REQUIRED_GUIDANCE_DOCUMENTS:
        yield spec.document_id


def uspto_guidance_source_url(*, document_id: Any | None = None) -> str:
    """Documentation default for USPTO examination guidance landing pages."""
    if document_id is None:
        return "https://www.uspto.gov/patents/laws/examination-policy"
    doc_id = reject_unpinned_latest(str(document_id), field_name="document_id")
    spec = REQUIRED_DOCUMENT_BY_ID.get(doc_id)
    if spec is not None:
        return spec.uri
    return "https://www.uspto.gov/patents/laws/examination-policy"


__all__ = [
    "AUTHORITY_TIER_GUIDANCE",
    "CODE_VERSION",
    "CONFIG_ID",
    "DEFAULT_CLASSIFICATION",
    "DEFAULT_EXTRACTION_METHOD",
    "DEFAULT_LICENSE",
    "DEFAULT_MEDIA_TYPE",
    "DEFAULT_NORMALIZATION_PROFILE",
    "DEFAULT_PARTITION",
    "DEFAULT_PROVIDER",
    "GOAL_ID",
    "INTERFACE",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_FILENAME",
    "MANIFEST_SCHEMA_RELPATH",
    "PRODUCER",
    "REQUIRED_DOCUMENT_BY_ID",
    "REQUIRED_DOCUMENT_IDS",
    "REQUIRED_GUIDANCE_DOCUMENTS",
    "SCHEMA_VERSION",
    "TASK_ID",
    "BindingElevationError",
    "ExtractionDeterminismError",
    "GapKind",
    "GuidancePinError",
    "GuidanceTopic",
    "IncompleteInventoryError",
    "InventoryEntryStatus",
    "MissingCutoffError",
    "PdfTextExtractionContract",
    "PrivateOrNonPublicError",
    "SchemaValidationError",
    "SupersessionRelation",
    "UnpinnedLatestSelectionError",
    "UnreviewedRightsError",
    "UsptoGuidanceDocumentPin",
    "UsptoGuidanceDocumentSpec",
    "UsptoGuidanceInventoryGap",
    "UsptoGuidancePdfError",
    "UsptoGuidancePdfInventoryCounts",
    "UsptoGuidancePdfInventoryEntry",
    "UsptoGuidancePdfInventoryManifest",
    "UsptoGuidanceSupersessionRecord",
    "assert_guidance_not_elevated",
    "assert_rights_reviewed_for_public",
    "build_compact_guidance_pdf_fixture",
    "build_uspto_guidance_pdf_manifest",
    "canonical_json",
    "cid_from_digest",
    "compute_counts",
    "content_digest_of",
    "content_sha256",
    "default_manifest_schema_path",
    "default_public_rights_review",
    "deterministic_text_digest",
    "iter_required_document_ids",
    "load_manifest_schema",
    "normalize_extracted_text",
    "parse_guidance_document_version",
    "reject_unpinned_latest",
    "stable_guidance_pdf_identity",
    "uspto_guidance_source_url",
    "validate_extraction_determinism",
    "validate_inventory_nonempty",
    "validate_manifest_against_json_schema",
    "validate_manifest_dict",
    "validate_required_bindings",
    "validate_uri",
]
