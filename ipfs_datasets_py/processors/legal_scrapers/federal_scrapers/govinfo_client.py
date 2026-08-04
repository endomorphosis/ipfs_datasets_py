"""GovInfo official package/granule client for Federal Register verification (PATLAW-014).

Binds official PDF/XML package and granule metadata plus digital signature
results from GovInfo. FederalRegister.gov discovery text is **not** admitted
as an official edition; that path lives in
:mod:`federal_register_change_processor` and is labeled unofficial.

Design invariants:

* Official artifact identity is distinct from any derived/unofficial presentation.
* HTTP success alone is not verification; signature and fixity results are
  recorded explicitly.
* Retry exhaustion, schema validation failures, and signature failures are
  typed outcomes (never silent).
* Package/granule identifiers are never the hard-coded token ``\"latest\"``.
* Live network I/O is opt-in; unit tests use recorded fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION as AUTHORITY_SCHEMA_VERSION,
    ArtifactIdentity,
    HardCodedLatestEditionError,
    IdentityRole,
    RetryCachePolicy,
    SourceReceipt,
    VerificationState,
    canonical_json_dumps,
    reject_hard_coded_latest,
)

SCHEMA_VERSION = "govinfo-client-v1"
FIXTURE_SCHEMA_VERSION = "govinfo-fixture-v1"

DEFAULT_PROVIDER = "govinfo"
DEFAULT_JURISDICTION = "US"
COLLECTION_FR = "FR"
GOVINFO_API_BASE = "https://api.govinfo.gov"
GOVINFO_CONTENT_BASE = "https://www.govinfo.gov/content/pkg"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_ID_RE = re.compile(
    r"^FR-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GovInfoError(ValueError):
    """Base error for GovInfo client failures."""


class GovInfoRetryError(GovInfoError):
    """Raised when retry/backoff is exhausted or circuit breaker opens.

    Explicit failure: callers must surface this rather than treating the
    request as an empty success.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_status: Optional[int] = None,
        retry_after: Optional[float] = None,
        error_code: str = "retry_exhausted",
    ) -> None:
        super().__init__(message)
        self.attempts = int(attempts)
        self.last_status = last_status
        self.retry_after = retry_after
        self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "error_code": self.error_code,
            "kind": "retry",
            "last_status": self.last_status,
            "message": str(self),
            "retry_after": self.retry_after,
        }


class GovInfoSchemaError(GovInfoError):
    """Raised when package/granule payload fails schema validation.

    Explicit failure: malformed upstream or fixture structure is never
    silently coerced into a verified official artifact.
    """

    def __init__(
        self,
        message: str,
        *,
        field_name: Optional[str] = None,
        error_code: str = "schema_invalid",
    ) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "field_name": self.field_name,
            "kind": "schema",
            "message": str(self),
        }


class GovInfoSignatureError(GovInfoError):
    """Raised when GPO/GovInfo authentication signature verification fails.

    Explicit failure: a missing or invalid signature is never recorded as
    ``verified`` without human review.
    """

    def __init__(
        self,
        message: str,
        *,
        signature_result: "SignatureResult",
        package_id: Optional[str] = None,
        granule_id: Optional[str] = None,
        error_code: str = "signature_failed",
    ) -> None:
        super().__init__(message)
        self.signature_result = signature_result
        self.package_id = package_id
        self.granule_id = granule_id
        self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "granule_id": self.granule_id,
            "kind": "signature",
            "message": str(self),
            "package_id": self.package_id,
            "signature_result": self.signature_result.value,
        }


class FixtureSchemaError(GovInfoSchemaError):
    """Raised when a fixture package is malformed."""

    def __init__(self, message: str, *, field_name: Optional[str] = None) -> None:
        super().__init__(message, field_name=field_name, error_code="fixture_schema_invalid")


class PackageNotFoundError(GovInfoError):
    """Raised when a requested package id is not present."""


class GranuleNotFoundError(GovInfoError):
    """Raised when a requested granule id is not present."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignatureResult(str, Enum):
    """Digital authentication / signature verification outcome."""

    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    NOT_CHECKED = "not_checked"
    ERROR = "error"

    @classmethod
    def coerce(cls, value: Any) -> "SignatureResult":
        if isinstance(value, SignatureResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "valid": cls.VALID,
            "verified": cls.VALID,
            "ok": cls.VALID,
            "pass": cls.VALID,
            "passed": cls.VALID,
            "invalid": cls.INVALID,
            "failed": cls.INVALID,
            "fail": cls.INVALID,
            "bad": cls.INVALID,
            "missing": cls.MISSING,
            "absent": cls.MISSING,
            "none": cls.MISSING,
            "unsupported": cls.UNSUPPORTED,
            "not_applicable": cls.UNSUPPORTED,
            "n_a": cls.UNSUPPORTED,
            "not_checked": cls.NOT_CHECKED,
            "unchecked": cls.NOT_CHECKED,
            "pending": cls.NOT_CHECKED,
            "error": cls.ERROR,
            "exception": cls.ERROR,
        }
        if text not in aliases:
            raise GovInfoSchemaError(
                f"unsupported signature_result: {value!r}",
                field_name="signature_result",
            )
        return aliases[text]


class GranuleFormat(str, Enum):
    """Supported GovInfo FR granule content formats."""

    PDF = "pdf"
    XML = "xml"
    HTML = "html"
    MODS = "mods"
    PREMIS = "premis"
    ZIP = "zip"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "GranuleFormat":
        if isinstance(value, GranuleFormat):
            return value
        text = str(value or "").strip().lower()
        aliases = {
            "pdf": cls.PDF,
            "application/pdf": cls.PDF,
            "xml": cls.XML,
            "application/xml": cls.XML,
            "text/xml": cls.XML,
            "html": cls.HTML,
            "htm": cls.HTML,
            "text/html": cls.HTML,
            "mods": cls.MODS,
            "application/mods+xml": cls.MODS,
            "premis": cls.PREMIS,
            "application/premis+xml": cls.PREMIS,
            "zip": cls.ZIP,
            "application/zip": cls.ZIP,
            "other": cls.OTHER,
        }
        if text not in aliases:
            raise GovInfoSchemaError(
                f"unsupported granule format: {value!r}", field_name="format"
            )
        return aliases[text]


class ResolutionStatus(str, Enum):
    """Outcome of package/granule resolution or verification."""

    RESOLVED = "resolved"
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    ERROR = "error"
    RETRY_FAILED = "retry_failed"
    SCHEMA_FAILED = "schema_failed"
    SIGNATURE_FAILED = "signature_failed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovInfoSchemaError(f"{name} must be a non-empty string", field_name=name)
    if "\x00" in value:
        raise GovInfoSchemaError(f"{name} must not contain NUL", field_name=name)
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise GovInfoSchemaError(
            f"{name} must be a lowercase 64-char hex SHA-256", field_name=name
        )
    return text


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
            raise GovInfoSchemaError(
                f"{name} must be ISO-8601 datetime", field_name=name
            ) from exc
    else:
        raise GovInfoSchemaError(
            f"{name} must be a datetime or ISO-8601 string", field_name=name
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_utc(dt: datetime) -> str:
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


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def normalize_package_id(package_id: Any) -> str:
    """Normalize a Federal Register GovInfo package id (e.g. ``FR-2024-03-15``)."""

    text = _require_non_empty_str(str(package_id), "package_id")
    reject_hard_coded_latest(text, field_name="package_id")
    upper = text.upper()
    # Accept bare date forms and expand to FR-YYYY-MM-DD.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", upper):
        upper = f"FR-{upper}"
    if not _PACKAGE_ID_RE.fullmatch(upper):
        # Allow non-daily package patterns (e.g. composite fixtures) but still
        # reject "latest".
        if "LATEST" in upper:
            raise HardCodedLatestEditionError(
                "package_id must not be the hard-coded token 'latest'"
            )
        return upper
    return upper


def normalize_granule_id(granule_id: Any) -> str:
    """Normalize a granule id (document number style, e.g. ``2024-05512``)."""

    text = _require_non_empty_str(str(granule_id), "granule_id")
    reject_hard_coded_latest(text, field_name="granule_id")
    return text.strip()


def govinfo_package_url(package_id: Any) -> str:
    pkg = normalize_package_id(package_id)
    return f"{GOVINFO_CONTENT_BASE}/{pkg}"


def govinfo_granule_pdf_url(*, package_id: Any, granule_id: Any) -> str:
    pkg = normalize_package_id(package_id)
    gran = normalize_granule_id(granule_id)
    return f"{GOVINFO_CONTENT_BASE}/{pkg}/pdf/{pkg}-{gran}.pdf"


def govinfo_granule_xml_url(*, package_id: Any, granule_id: Any) -> str:
    pkg = normalize_package_id(package_id)
    gran = normalize_granule_id(granule_id)
    return f"{GOVINFO_CONTENT_BASE}/{pkg}/xml/{pkg}-{gran}.xml"


def govinfo_api_package_summary_url(package_id: Any) -> str:
    pkg = normalize_package_id(package_id)
    return f"{GOVINFO_API_BASE}/packages/{pkg}/summary"


def _media_type_for_format(fmt: GranuleFormat) -> str:
    return {
        GranuleFormat.PDF: "application/pdf",
        GranuleFormat.XML: "application/xml",
        GranuleFormat.HTML: "text/html",
        GranuleFormat.MODS: "application/mods+xml",
        GranuleFormat.PREMIS: "application/premis+xml",
        GranuleFormat.ZIP: "application/zip",
        GranuleFormat.OTHER: "application/octet-stream",
    }[fmt]


def signature_result_to_verification_state(
    result: SignatureResult,
) -> VerificationState:
    """Map signature outcome to the shared authority verification state."""

    if result is SignatureResult.VALID:
        return VerificationState.VERIFIED
    if result is SignatureResult.INVALID:
        return VerificationState.CONFLICT
    if result is SignatureResult.MISSING:
        return VerificationState.INCONCLUSIVE
    if result is SignatureResult.ERROR:
        return VerificationState.HUMAN_REVIEW_REQUIRED
    return VerificationState.UNVERIFIED


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignatureEvidence:
    """GPO / GovInfo digital authentication evidence for one artifact."""

    result: SignatureResult
    algorithm: Optional[str] = None
    evidence: Optional[str] = None
    checked_at: Optional[datetime] = None
    signer: Optional[str] = None
    certificate_subject: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", SignatureResult.coerce(self.result))
        if self.algorithm is not None:
            object.__setattr__(
                self, "algorithm", _require_non_empty_str(self.algorithm, "algorithm")
            )
        if self.evidence is not None:
            object.__setattr__(
                self, "evidence", _require_non_empty_str(self.evidence, "evidence")
            )
        if self.checked_at is not None:
            object.__setattr__(
                self, "checked_at", _parse_utc(self.checked_at, name="checked_at")
            )
        if self.signer is not None:
            object.__setattr__(
                self, "signer", _require_non_empty_str(self.signer, "signer")
            )
        if self.certificate_subject is not None:
            object.__setattr__(
                self,
                "certificate_subject",
                _require_non_empty_str(self.certificate_subject, "certificate_subject"),
            )
        if not isinstance(self.metadata, Mapping):
            raise GovInfoSchemaError("metadata must be a mapping", field_name="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_valid(self) -> bool:
        return self.result is SignatureResult.VALID

    @property
    def is_failure(self) -> bool:
        return self.result in (
            SignatureResult.INVALID,
            SignatureResult.ERROR,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "certificate_subject": self.certificate_subject,
            "checked_at": None if self.checked_at is None else _format_utc(self.checked_at),
            "evidence": self.evidence,
            "metadata": _deep_sorted(self.metadata),
            "result": self.result.value,
            "signer": self.signer,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "SignatureEvidence":
        if not isinstance(value, Mapping):
            raise GovInfoSchemaError(
                "signature evidence must be a mapping", field_name="signature"
            )
        return cls(
            result=value.get("result", SignatureResult.NOT_CHECKED),
            algorithm=value.get("algorithm"),
            evidence=value.get("evidence") or value.get("signature_evidence"),
            checked_at=value.get("checked_at"),
            signer=value.get("signer"),
            certificate_subject=value.get("certificate_subject"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GranuleArtifact:
    """One content format for a GovInfo FR granule (PDF/XML/MODS/…)."""

    format: GranuleFormat
    artifact_sha256: str
    source_url: str
    media_type: Optional[str] = None
    byte_size: Optional[int] = None
    upstream_package_id: Optional[str] = None
    signature: Optional[SignatureEvidence] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "format", GranuleFormat.coerce(self.format))
        object.__setattr__(
            self,
            "artifact_sha256",
            _require_sha256(self.artifact_sha256, "artifact_sha256"),
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        if self.media_type is None:
            object.__setattr__(self, "media_type", _media_type_for_format(self.format))
        else:
            object.__setattr__(
                self, "media_type", _require_non_empty_str(self.media_type, "media_type")
            )
        if self.byte_size is not None:
            if not isinstance(self.byte_size, int) or self.byte_size < 0:
                raise GovInfoSchemaError(
                    "byte_size must be a non-negative int", field_name="byte_size"
                )
        if self.upstream_package_id is not None:
            object.__setattr__(
                self,
                "upstream_package_id",
                normalize_package_id(self.upstream_package_id),
            )
        if self.signature is not None and not isinstance(self.signature, SignatureEvidence):
            object.__setattr__(
                self, "signature", SignatureEvidence.from_dict(self.signature)  # type: ignore[arg-type]
            )
        if not isinstance(self.metadata, Mapping):
            raise GovInfoSchemaError("metadata must be a mapping", field_name="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_artifact_identity(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        source_id: str,
        role: IdentityRole = IdentityRole.OFFICIAL_ARTIFACT,
    ) -> ArtifactIdentity:
        return ArtifactIdentity(
            provider=provider,
            source_id=source_id,
            artifact_sha256=self.artifact_sha256,
            source_url=self.source_url,
            media_type=self.media_type,
            byte_size=self.byte_size,
            upstream_package_id=self.upstream_package_id,
            role=role,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "byte_size": self.byte_size,
            "format": self.format.value,
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "signature": None if self.signature is None else self.signature.to_dict(),
            "source_url": self.source_url,
            "upstream_package_id": self.upstream_package_id,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GranuleArtifact":
        if not isinstance(value, Mapping):
            raise GovInfoSchemaError(
                "granule artifact must be a mapping", field_name="formats"
            )
        sig_raw = value.get("signature")
        return cls(
            format=value.get("format", GranuleFormat.PDF),
            artifact_sha256=value["artifact_sha256"],
            source_url=value["source_url"],
            media_type=value.get("media_type"),
            byte_size=value.get("byte_size"),
            upstream_package_id=value.get("upstream_package_id")
            or value.get("package_id"),
            signature=None if sig_raw is None else SignatureEvidence.from_dict(sig_raw),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GovInfoGranule:
    """Official Federal Register granule under a daily package."""

    package_id: str
    granule_id: str
    title: Optional[str] = None
    citation: Optional[str] = None
    document_number: Optional[str] = None
    formats: Mapping[str, GranuleArtifact] = field(default_factory=dict)
    publication_date: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    signature: Optional[SignatureEvidence] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_id", normalize_package_id(self.package_id))
        object.__setattr__(self, "granule_id", normalize_granule_id(self.granule_id))
        if self.title is not None:
            object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        if self.citation is not None:
            object.__setattr__(
                self, "citation", _require_non_empty_str(self.citation, "citation")
            )
        if self.document_number is not None:
            object.__setattr__(
                self,
                "document_number",
                _require_non_empty_str(self.document_number, "document_number"),
            )
        else:
            object.__setattr__(self, "document_number", self.granule_id)
        fmt_map: dict[str, GranuleArtifact] = {}
        for key, raw in dict(self.formats or {}).items():
            if isinstance(raw, GranuleArtifact):
                art = raw
            elif isinstance(raw, Mapping):
                payload = dict(raw)
                payload.setdefault("format", key)
                payload.setdefault("upstream_package_id", self.package_id)
                art = GranuleArtifact.from_dict(payload)
            else:
                raise GovInfoSchemaError(
                    f"format entry {key!r} must be a mapping", field_name="formats"
                )
            fmt_map[art.format.value] = art
        object.__setattr__(self, "formats", fmt_map)
        if self.signature is not None and not isinstance(self.signature, SignatureEvidence):
            object.__setattr__(
                self, "signature", SignatureEvidence.from_dict(self.signature)  # type: ignore[arg-type]
            )
        if not isinstance(self.metadata, Mapping):
            raise GovInfoSchemaError("metadata must be a mapping", field_name="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def preferred_official_format(self) -> Optional[GranuleArtifact]:
        for key in (
            GranuleFormat.PDF.value,
            GranuleFormat.XML.value,
            GranuleFormat.MODS.value,
            GranuleFormat.HTML.value,
        ):
            if key in self.formats:
                return self.formats[key]
        if self.formats:
            return next(iter(self.formats.values()))
        return None

    def effective_signature(self) -> Optional[SignatureEvidence]:
        if self.signature is not None:
            return self.signature
        preferred = self.preferred_official_format
        if preferred is not None:
            return preferred.signature
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "document_number": self.document_number,
            "formats": {k: v.to_dict() for k, v in sorted(self.formats.items())},
            "granule_id": self.granule_id,
            "metadata": _deep_sorted(self.metadata),
            "package_id": self.package_id,
            "page_end": self.page_end,
            "page_start": self.page_start,
            "publication_date": self.publication_date,
            "signature": None if self.signature is None else self.signature.to_dict(),
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GovInfoGranule":
        if not isinstance(value, Mapping):
            raise GovInfoSchemaError("granule must be a mapping", field_name="granules")
        package_id = value.get("package_id") or value.get("packageId")
        granule_id = value.get("granule_id") or value.get("granuleId") or value.get(
            "document_number"
        )
        if not package_id or not granule_id:
            raise GovInfoSchemaError(
                "granule requires package_id and granule_id",
                field_name="granule_id",
            )
        sig_raw = value.get("signature")
        return cls(
            package_id=str(package_id),
            granule_id=str(granule_id),
            title=value.get("title"),
            citation=value.get("citation"),
            document_number=value.get("document_number") or value.get("documentNumber"),
            formats=value.get("formats") or {},
            publication_date=value.get("publication_date")
            or value.get("dateIssued")
            or value.get("date_issued"),
            page_start=value.get("page_start") or value.get("pageStart"),
            page_end=value.get("page_end") or value.get("pageEnd"),
            signature=None if sig_raw is None else SignatureEvidence.from_dict(sig_raw),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GovInfoPackage:
    """Official daily Federal Register package identity and granules."""

    package_id: str
    collection: str = COLLECTION_FR
    provider: str = DEFAULT_PROVIDER
    title: Optional[str] = None
    date_issued: Optional[str] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    granules: Mapping[str, GovInfoGranule] = field(default_factory=dict)
    signature: Optional[SignatureEvidence] = None
    retrieved_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_id", normalize_package_id(self.package_id))
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        if self.title is not None:
            object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        else:
            object.__setattr__(self, "source_url", govinfo_package_url(self.package_id))
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        gran_map: dict[str, GovInfoGranule] = {}
        for key, raw in dict(self.granules or {}).items():
            if isinstance(raw, GovInfoGranule):
                gran = raw
            elif isinstance(raw, Mapping):
                payload = dict(raw)
                payload.setdefault("package_id", self.package_id)
                payload.setdefault("granule_id", key)
                gran = GovInfoGranule.from_dict(payload)
            else:
                raise GovInfoSchemaError(
                    f"granule entry {key!r} must be a mapping", field_name="granules"
                )
            if gran.package_id != self.package_id:
                raise GovInfoSchemaError(
                    f"granule {gran.granule_id} package_id mismatch",
                    field_name="package_id",
                )
            gran_map[gran.granule_id] = gran
        object.__setattr__(self, "granules", gran_map)
        if self.signature is not None and not isinstance(self.signature, SignatureEvidence):
            object.__setattr__(
                self, "signature", SignatureEvidence.from_dict(self.signature)  # type: ignore[arg-type]
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise GovInfoSchemaError("metadata must be a mapping", field_name="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def get_granule(self, granule_id: Any) -> GovInfoGranule:
        key = normalize_granule_id(granule_id)
        try:
            return self.granules[key]
        except KeyError as exc:
            raise GranuleNotFoundError(
                f"granule {key!r} not found in package {self.package_id}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "content_sha256": self.content_sha256,
            "date_issued": self.date_issued,
            "granules": {k: v.to_dict() for k, v in sorted(self.granules.items())},
            "metadata": _deep_sorted(self.metadata),
            "package_id": self.package_id,
            "provider": self.provider,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "signature": None if self.signature is None else self.signature.to_dict(),
            "source_url": self.source_url,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "GovInfoPackage":
        if not isinstance(value, Mapping):
            raise GovInfoSchemaError("package must be a mapping", field_name="package")
        package_id = value.get("package_id") or value.get("packageId")
        if not package_id:
            raise GovInfoSchemaError(
                "package_id is required", field_name="package_id"
            )
        # Granules may arrive as a list or mapping.
        raw_granules = value.get("granules") or {}
        gran_map: dict[str, Any] = {}
        if isinstance(raw_granules, Mapping):
            gran_map = dict(raw_granules)
        elif isinstance(raw_granules, Sequence) and not isinstance(raw_granules, (str, bytes)):
            for item in raw_granules:
                if not isinstance(item, Mapping):
                    continue
                gid = item.get("granule_id") or item.get("granuleId") or item.get(
                    "document_number"
                )
                if gid:
                    gran_map[str(gid)] = item
        sig_raw = value.get("signature")
        return cls(
            package_id=str(package_id),
            collection=str(value.get("collection") or COLLECTION_FR),
            provider=str(value.get("provider") or DEFAULT_PROVIDER),
            title=value.get("title"),
            date_issued=value.get("date_issued") or value.get("dateIssued"),
            source_url=value.get("source_url") or value.get("packageLink"),
            content_sha256=value.get("content_sha256"),
            granules=gran_map,
            signature=None if sig_raw is None else SignatureEvidence.from_dict(sig_raw),
            retrieved_at=value.get("retrieved_at"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class GovInfoVerificationResult:
    """Result of verifying an official GovInfo package/granule artifact.

    Retry, schema, and signature failures are explicit status values with
    structured failure payloads — never silent success.
    """

    status: ResolutionStatus
    package_id: Optional[str] = None
    granule_id: Optional[str] = None
    package: Optional[GovInfoPackage] = None
    granule: Optional[GovInfoGranule] = None
    official_artifact: Optional[ArtifactIdentity] = None
    signature: Optional[SignatureEvidence] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    receipt: Optional[SourceReceipt] = None
    failure: Optional[Mapping[str, Any]] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        if not isinstance(self.verification_state, VerificationState):
            object.__setattr__(
                self, "verification_state", VerificationState(str(self.verification_state))
            )
        if self.failure is not None and not isinstance(self.failure, Mapping):
            raise GovInfoSchemaError("failure must be a mapping", field_name="failure")
        if self.failure is not None:
            object.__setattr__(self, "failure", dict(self.failure))
        if not isinstance(self.metadata, Mapping):
            raise GovInfoSchemaError("metadata must be a mapping", field_name="metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_verified(self) -> bool:
        return self.status is ResolutionStatus.VERIFIED

    @property
    def is_failure(self) -> bool:
        return self.status in (
            ResolutionStatus.ERROR,
            ResolutionStatus.RETRY_FAILED,
            ResolutionStatus.SCHEMA_FAILED,
            ResolutionStatus.SIGNATURE_FAILED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure": None if self.failure is None else _deep_sorted(self.failure),
            "granule": None if self.granule is None else self.granule.to_dict(),
            "granule_id": self.granule_id,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "official_artifact": (
                None
                if self.official_artifact is None
                else self.official_artifact.to_dict()
            ),
            "package": None if self.package is None else self.package.to_dict(),
            "package_id": self.package_id,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "signature": None if self.signature is None else self.signature.to_dict(),
            "status": self.status.value,
            "verification_state": self.verification_state.value,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Return the repository Federal Register fixture directory when present."""

    here = Path(__file__).resolve()
    candidates = [
        here.parents[4]
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "federal_register",
        Path.cwd()
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "federal_register",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise FixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def _build_receipt(
    *,
    endpoint: str,
    content_sha256_value: Optional[str],
    retrieved_at: Optional[datetime],
    upstream_id: Optional[str],
    response_status: int = 200,
    error_code: Optional[str] = None,
    retry_count: int = 0,
    media_type: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> SourceReceipt:
    return SourceReceipt(
        endpoint=endpoint,
        retrieved_at=retrieved_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        response_status=response_status,
        sanitized_request={"method": "GET", "path": endpoint},
        upstream_id=upstream_id,
        content_sha256=content_sha256_value,
        retry_count=retry_count,
        cache_hit=False,
        media_type=media_type or "application/json",
        error_code=error_code,
        metadata=dict(metadata or {"provider": DEFAULT_PROVIDER}),
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GovInfoClient:
    """Acquire and verify official GovInfo FR packages and granules.

    Primary path is fixture replay (recorded package/granule metadata and
    signature evidence). Live network discovery is deliberately not performed
    by default so tests and offline operators remain deterministic.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.retry_cache_policy = retry_cache_policy or RetryCachePolicy()
        # API key is never logged; held only for future live transport.
        self._api_key = api_key
        self._packages: dict[str, GovInfoPackage] = {}
        self._failure_fixtures: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Fixture load
    # ------------------------------------------------------------------

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            # Prefer standalone govinfo recipe, else shared FR change recipe.
            for name in (
                "govinfo_packages_recipe.json",
                "patent_rule_changes_recipe.json",
            ):
                candidate = target / name
                if candidate.is_file():
                    target = candidate
                    break
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks govinfo_packages_recipe.json "
                    "or patent_rule_changes_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {
            FIXTURE_SCHEMA_VERSION,
            SCHEMA_VERSION,
            "federal-register-change-fixture-v1",
            "federal-register-change-processor-v1",
        }:
            if not (
                str(schema).startswith("govinfo")
                or str(schema).startswith("federal-register")
            ):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        for name in (
            "govinfo_packages_recipe.json",
            "patent_rule_changes_recipe.json",
        ):
            recipe = self.fixture_dir / name
            if recipe.is_file():
                return recipe
        return self.fixture_dir

    def load_packages_from_payload(self, payload: JsonMapping) -> list[GovInfoPackage]:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")
        packages: list[GovInfoPackage] = []
        raw_packages = payload.get("govinfo_packages") or payload.get("packages") or []
        if isinstance(raw_packages, Mapping):
            iterable: Sequence[Any] = list(raw_packages.values())
        elif isinstance(raw_packages, Sequence) and not isinstance(
            raw_packages, (str, bytes)
        ):
            iterable = raw_packages
        else:
            iterable = []
        for item in iterable:
            if not isinstance(item, Mapping):
                continue
            try:
                pkg = GovInfoPackage.from_dict(item)
            except (GovInfoSchemaError, HardCodedLatestEditionError) as exc:
                # Surface schema failures explicitly via failure fixtures map.
                package_id = str(item.get("package_id") or item.get("packageId") or "unknown")
                self._failure_fixtures[f"schema:{package_id}"] = {
                    "kind": "schema",
                    "error_code": getattr(exc, "error_code", "schema_invalid"),
                    "message": str(exc),
                    "package_id": package_id,
                }
                continue
            packages.append(pkg)
            self._packages[pkg.package_id] = pkg

        # Optional explicit failure recipes for retry/schema/signature tests.
        for fail in payload.get("govinfo_failures") or payload.get("failures") or []:
            if not isinstance(fail, Mapping):
                continue
            key = str(
                fail.get("failure_id")
                or fail.get("id")
                or f"{fail.get('kind', 'error')}:{fail.get('package_id', 'unknown')}"
            )
            self._failure_fixtures[key] = dict(fail)
        return packages

    def acquire_from_fixture(
        self, path: PathLike | None = None
    ) -> list[GovInfoPackage]:
        payload = self.load_fixture_package(path)
        return self.load_packages_from_payload(payload)

    def get_package(self, package_id: Any) -> GovInfoPackage:
        key = normalize_package_id(package_id)
        if key not in self._packages:
            # Lazy load default fixtures once.
            if not self._packages:
                self.acquire_from_fixture()
        try:
            return self._packages[key]
        except KeyError as exc:
            raise PackageNotFoundError(f"package {key!r} not found") from exc

    def get_granule(self, *, package_id: Any, granule_id: Any) -> GovInfoGranule:
        return self.get_package(package_id).get_granule(granule_id)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_granule(
        self,
        *,
        package_id: Any,
        granule_id: Any,
        require_valid_signature: bool = True,
        preferred_formats: Sequence[str] | None = None,
    ) -> GovInfoVerificationResult:
        """Verify official package/granule metadata and signature when present.

        Returns an explicit failure result for retry/schema/signature problems
        rather than raising, so callers can record the outcome on the change
        record. Raising variants are available via :meth:`verify_granule_or_raise`.
        """

        # Explicit failure fixtures take precedence (retry / signature scenarios).
        failure_key_candidates = [
            f"signature:{package_id}:{granule_id}",
            f"retry:{package_id}",
            f"schema:{package_id}",
            str(package_id),
        ]
        for fk in failure_key_candidates:
            if fk in self._failure_fixtures:
                return self._result_from_failure_fixture(self._failure_fixtures[fk])

        try:
            package = self.get_package(package_id)
            granule = package.get_granule(granule_id)
        except PackageNotFoundError as exc:
            return GovInfoVerificationResult(
                status=ResolutionStatus.ERROR,
                package_id=str(package_id),
                granule_id=str(granule_id),
                verification_state=VerificationState.UNVERIFIED,
                failure={"kind": "error", "error_code": "package_not_found", "message": str(exc)},
                notes=str(exc),
            )
        except GranuleNotFoundError as exc:
            return GovInfoVerificationResult(
                status=ResolutionStatus.ERROR,
                package_id=str(package_id),
                granule_id=str(granule_id),
                package=self._packages.get(normalize_package_id(package_id)),
                verification_state=VerificationState.UNVERIFIED,
                failure={"kind": "error", "error_code": "granule_not_found", "message": str(exc)},
                notes=str(exc),
            )
        except GovInfoSchemaError as exc:
            return GovInfoVerificationResult(
                status=ResolutionStatus.SCHEMA_FAILED,
                package_id=str(package_id),
                granule_id=str(granule_id),
                verification_state=VerificationState.INCONCLUSIVE,
                failure=exc.to_dict(),
                notes=str(exc),
            )

        preferred = list(preferred_formats or ("pdf", "xml", "mods"))
        artifact: Optional[GranuleArtifact] = None
        for fmt in preferred:
            if fmt in granule.formats:
                artifact = granule.formats[fmt]
                break
        if artifact is None:
            artifact = granule.preferred_official_format

        if artifact is None:
            return GovInfoVerificationResult(
                status=ResolutionStatus.PARTIAL,
                package_id=package.package_id,
                granule_id=granule.granule_id,
                package=package,
                granule=granule,
                verification_state=VerificationState.INCONCLUSIVE,
                failure={
                    "kind": "schema",
                    "error_code": "missing_formats",
                    "message": "granule has no official content formats",
                },
                notes="Granule present but no PDF/XML/MODS artifact bound.",
            )

        # Signature: granule-level overrides format-level; package-level is fallback.
        signature = granule.effective_signature() or package.signature or artifact.signature
        if signature is None:
            signature = SignatureEvidence(result=SignatureResult.NOT_CHECKED)

        verification_state = signature_result_to_verification_state(signature.result)
        official = artifact.to_artifact_identity(
            provider=package.provider,
            source_id=f"govinfo:{package.package_id}:{granule.granule_id}:{artifact.format.value}",
            role=IdentityRole.OFFICIAL_ARTIFACT,
        )
        receipt = _build_receipt(
            endpoint=artifact.source_url,
            content_sha256_value=artifact.artifact_sha256,
            retrieved_at=package.retrieved_at,
            upstream_id=f"{package.package_id}/{granule.granule_id}",
            media_type=artifact.media_type,
            metadata={
                "provider": package.provider,
                "package_id": package.package_id,
                "granule_id": granule.granule_id,
                "authority_schema": AUTHORITY_SCHEMA_VERSION,
            },
        )

        if signature.is_failure or (
            require_valid_signature and signature.result is SignatureResult.MISSING
        ):
            return GovInfoVerificationResult(
                status=ResolutionStatus.SIGNATURE_FAILED,
                package_id=package.package_id,
                granule_id=granule.granule_id,
                package=package,
                granule=granule,
                official_artifact=official,
                signature=signature,
                verification_state=verification_state,
                receipt=receipt,
                failure={
                    "kind": "signature",
                    "error_code": "signature_failed",
                    "message": (
                        f"signature result {signature.result.value} for "
                        f"{package.package_id}/{granule.granule_id}"
                    ),
                    "signature_result": signature.result.value,
                    "package_id": package.package_id,
                    "granule_id": granule.granule_id,
                },
                notes=(
                    "Official artifact identity retained, but signature verification "
                    "failed; do not treat as verified official edition."
                ),
                metadata={"format": artifact.format.value},
            )

        if signature.result is SignatureResult.VALID:
            status = ResolutionStatus.VERIFIED
        else:
            status = ResolutionStatus.RESOLVED
            if verification_state is VerificationState.UNVERIFIED:
                verification_state = VerificationState.UNVERIFIED

        return GovInfoVerificationResult(
            status=status,
            package_id=package.package_id,
            granule_id=granule.granule_id,
            package=package,
            granule=granule,
            official_artifact=official,
            signature=signature,
            verification_state=verification_state,
            receipt=receipt,
            notes=(
                "Official GovInfo FR granule bound with package/granule metadata "
                "and signature result."
            ),
            metadata={
                "format": artifact.format.value,
                "signature_result": signature.result.value,
                "processor_schema": SCHEMA_VERSION,
            },
        )

    def verify_granule_or_raise(
        self,
        *,
        package_id: Any,
        granule_id: Any,
        require_valid_signature: bool = True,
    ) -> GovInfoVerificationResult:
        """Like :meth:`verify_granule` but raises typed errors on failure."""

        result = self.verify_granule(
            package_id=package_id,
            granule_id=granule_id,
            require_valid_signature=require_valid_signature,
        )
        if result.status is ResolutionStatus.RETRY_FAILED:
            fail = result.failure or {}
            raise GovInfoRetryError(
                str(fail.get("message") or result.notes or "retry exhausted"),
                attempts=int(fail.get("attempts") or 0),
                last_status=fail.get("last_status"),
                retry_after=fail.get("retry_after"),
                error_code=str(fail.get("error_code") or "retry_exhausted"),
            )
        if result.status is ResolutionStatus.SCHEMA_FAILED:
            fail = result.failure or {}
            raise GovInfoSchemaError(
                str(fail.get("message") or result.notes or "schema invalid"),
                field_name=fail.get("field_name"),
                error_code=str(fail.get("error_code") or "schema_invalid"),
            )
        if result.status is ResolutionStatus.SIGNATURE_FAILED:
            fail = result.failure or {}
            sig = result.signature or SignatureEvidence(result=SignatureResult.INVALID)
            raise GovInfoSignatureError(
                str(fail.get("message") or result.notes or "signature failed"),
                signature_result=sig.result,
                package_id=result.package_id,
                granule_id=result.granule_id,
                error_code=str(fail.get("error_code") or "signature_failed"),
            )
        return result

    def record_retry_failure(
        self,
        *,
        package_id: Any,
        attempts: int,
        last_status: Optional[int] = None,
        retry_after: Optional[float] = None,
        message: Optional[str] = None,
    ) -> GovInfoVerificationResult:
        """Build an explicit retry-exhausted failure result."""

        pkg = str(package_id)
        err = GovInfoRetryError(
            message
            or (
                f"GovInfo package {pkg} retrieval exhausted after {attempts} attempts "
                f"(last_status={last_status})"
            ),
            attempts=attempts,
            last_status=last_status,
            retry_after=retry_after,
        )
        return GovInfoVerificationResult(
            status=ResolutionStatus.RETRY_FAILED,
            package_id=pkg,
            verification_state=VerificationState.UNVERIFIED,
            failure=err.to_dict(),
            notes=str(err),
            receipt=_build_receipt(
                endpoint=govinfo_api_package_summary_url(pkg)
                if pkg.upper().startswith("FR-")
                else GOVINFO_API_BASE,
                content_sha256_value=None,
                retrieved_at=datetime.now(timezone.utc),
                upstream_id=pkg,
                response_status=int(last_status or 0),
                error_code=err.error_code,
                retry_count=attempts,
            ),
        )

    def record_schema_failure(
        self,
        *,
        message: str,
        package_id: Optional[str] = None,
        field_name: Optional[str] = None,
    ) -> GovInfoVerificationResult:
        err = GovInfoSchemaError(message, field_name=field_name)
        return GovInfoVerificationResult(
            status=ResolutionStatus.SCHEMA_FAILED,
            package_id=package_id,
            verification_state=VerificationState.INCONCLUSIVE,
            failure=err.to_dict(),
            notes=str(err),
        )

    def record_signature_failure(
        self,
        *,
        package_id: Any,
        granule_id: Any,
        signature_result: SignatureResult | str = SignatureResult.INVALID,
        message: Optional[str] = None,
    ) -> GovInfoVerificationResult:
        sig = SignatureEvidence(result=SignatureResult.coerce(signature_result))
        err = GovInfoSignatureError(
            message
            or f"signature {sig.result.value} for {package_id}/{granule_id}",
            signature_result=sig.result,
            package_id=str(package_id),
            granule_id=str(granule_id),
        )
        return GovInfoVerificationResult(
            status=ResolutionStatus.SIGNATURE_FAILED,
            package_id=str(package_id),
            granule_id=str(granule_id),
            signature=sig,
            verification_state=signature_result_to_verification_state(sig.result),
            failure=err.to_dict(),
            notes=str(err),
        )

    def _result_from_failure_fixture(
        self, fail: Mapping[str, Any]
    ) -> GovInfoVerificationResult:
        kind = str(fail.get("kind") or fail.get("error_kind") or "error").lower()
        package_id = fail.get("package_id")
        granule_id = fail.get("granule_id")
        message = str(fail.get("message") or fail.get("reason") or f"{kind} failure")
        if kind in ("retry", "retry_exhausted", "retry_failed"):
            return self.record_retry_failure(
                package_id=package_id or "unknown",
                attempts=int(fail.get("attempts") or fail.get("retry_count") or 0),
                last_status=fail.get("last_status"),
                retry_after=fail.get("retry_after"),
                message=message,
            )
        if kind in ("schema", "schema_invalid", "schema_failed"):
            return self.record_schema_failure(
                message=message,
                package_id=None if package_id is None else str(package_id),
                field_name=fail.get("field_name"),
            )
        if kind in ("signature", "signature_failed", "signature_invalid"):
            return self.record_signature_failure(
                package_id=package_id or "unknown",
                granule_id=granule_id or "unknown",
                signature_result=fail.get("signature_result")
                or fail.get("result")
                or SignatureResult.INVALID,
                message=message,
            )
        return GovInfoVerificationResult(
            status=ResolutionStatus.ERROR,
            package_id=None if package_id is None else str(package_id),
            granule_id=None if granule_id is None else str(granule_id),
            verification_state=VerificationState.UNVERIFIED,
            failure={"kind": kind, "error_code": fail.get("error_code") or kind, "message": message},
            notes=message,
        )


__all__ = [
    "COLLECTION_FR",
    "DEFAULT_PROVIDER",
    "FIXTURE_SCHEMA_VERSION",
    "GOVINFO_API_BASE",
    "GOVINFO_CONTENT_BASE",
    "SCHEMA_VERSION",
    "FixtureSchemaError",
    "GovInfoClient",
    "GovInfoError",
    "GovInfoGranule",
    "GovInfoPackage",
    "GovInfoRetryError",
    "GovInfoSchemaError",
    "GovInfoSignatureError",
    "GovInfoVerificationResult",
    "GranuleArtifact",
    "GranuleFormat",
    "GranuleNotFoundError",
    "PackageNotFoundError",
    "ResolutionStatus",
    "SignatureEvidence",
    "SignatureResult",
    "content_sha256",
    "default_fixture_dir",
    "govinfo_api_package_summary_url",
    "govinfo_granule_pdf_url",
    "govinfo_granule_xml_url",
    "govinfo_package_url",
    "load_json_fixture",
    "normalize_granule_id",
    "normalize_package_id",
    "signature_result_to_verification_state",
]
