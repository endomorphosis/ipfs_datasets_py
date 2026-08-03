"""Federal Register discovery and official-change processing (PATLAW-014).

Discovers USPTO rules and notices via the unofficial FederalRegister.gov API
representation, then binds official GovInfo PDF/XML package/granule metadata
and signature results when available.

Design invariants:

* Unofficial FR.gov discovery text is always labeled
  ``authority_tier=unofficial-current`` with
  ``IdentityRole.DERIVED_PRESENTATION``. It **never** masquerades as an
  official edition or GovInfo artifact.
* Proposed and withdrawn rules remain **nonbinding** (``is_binding=False``).
* Effective dates, compliance dates, and correction/withdrawal/delay edges
  survive deterministic fixture replay.
* Retry, schema, and signature failures from GovInfo verification are
  explicit typed outcomes (never silent success).
* Live network I/O is opt-in; unit tests use recorded fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION as AUTHORITY_SCHEMA_VERSION,
    AuthoritySourceRecord,
    AuthoritySourceRegistry,
    AuthorityTier,
    ArtifactIdentity,
    HardCodedLatestEditionError,
    IdentityRole,
    RetryCachePolicy,
    SourceReceipt,
    VerificationState,
    canonical_json_dumps,
    reject_hard_coded_latest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.govinfo_client import (
    FIXTURE_SCHEMA_VERSION as GOVINFO_FIXTURE_SCHEMA,
    SCHEMA_VERSION as GOVINFO_SCHEMA,
    GovInfoClient,
    GovInfoPackage,
    GovInfoRetryError,
    GovInfoSchemaError,
    GovInfoSignatureError,
    GovInfoVerificationResult,
    ResolutionStatus as GovInfoResolutionStatus,
    SignatureEvidence,
    SignatureResult,
    content_sha256 as govinfo_content_sha256,
    default_fixture_dir as govinfo_default_fixture_dir,
    normalize_granule_id,
    normalize_package_id,
)

SCHEMA_VERSION = "federal-register-change-processor-v1"
FIXTURE_SCHEMA_VERSION = "federal-register-change-fixture-v1"

DEFAULT_PROVIDER_DISCOVERY = "federalregister.gov"
DEFAULT_PROVIDER_OFFICIAL = "govinfo"
DEFAULT_JURISDICTION = "US"
COLLECTION_FR = "FR"
FEDERAL_REGISTER_API = "https://www.federalregister.gov/api/v1/documents.json"
FEDERAL_REGISTER_DOC_BASE = "https://www.federalregister.gov/documents"

# USPTO / Commerce patent-rule discovery defaults (documentation only).
DEFAULT_AGENCIES = ("patent-and-trademark-office", "commerce-department")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOC_NUMBER_RE = re.compile(r"^\d{4}-\d{4,6}$")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterChangeError(ValueError):
    """Base error for Federal Register change processing."""


class BindingElevationError(FederalRegisterChangeError):
    """Raised when code attempts to treat a nonbinding rule type as binding."""


class FixtureSchemaError(FederalRegisterChangeError):
    """Raised when a fixture package is malformed."""


class DocumentNotFoundError(FederalRegisterChangeError):
    """Raised when a requested document number is not present."""


class UnofficialMasqueradeError(FederalRegisterChangeError):
    """Raised when unofficial discovery text is presented as official edition."""


class ExplicitFailureError(FederalRegisterChangeError):
    """Base for explicit retry/schema/signature failure wrappers."""

    def __init__(self, message: str, *, failure: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.failure = dict(failure or {})


class RetryFailureError(ExplicitFailureError):
    """Explicit retry exhaustion from GovInfo verification."""


class SchemaFailureError(ExplicitFailureError):
    """Explicit schema validation failure."""


class SignatureFailureError(ExplicitFailureError):
    """Explicit signature verification failure."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResolutionStatus(str, Enum):
    """Outcome of discovery / change acquisition."""

    RESOLVED = "resolved"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ERROR = "error"
    RETRY_FAILED = "retry_failed"
    SCHEMA_FAILED = "schema_failed"
    SIGNATURE_FAILED = "signature_failed"


class RuleDocumentType(str, Enum):
    """Federal Register document / event kinds for patent rules."""

    PROPOSED_RULE = "proposed_rule"
    FINAL_RULE = "final_rule"
    INTERIM_FINAL_RULE = "interim_final_rule"
    INTERIM_RULE = "interim_rule"
    CORRECTION = "correction"
    WITHDRAWAL = "withdrawal"
    DELAY = "delay"
    DELAY_EFFECTIVE_DATE = "delay_effective_date"
    NOTICE = "notice"
    PRESIDENTIAL_DOCUMENT = "presidential_document"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "RuleDocumentType":
        if isinstance(value, RuleDocumentType):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "proposed_rule": cls.PROPOSED_RULE,
            "proposed": cls.PROPOSED_RULE,
            "prorule": cls.PROPOSED_RULE,
            "rule": cls.FINAL_RULE,
            "final_rule": cls.FINAL_RULE,
            "final": cls.FINAL_RULE,
            "interim_final_rule": cls.INTERIM_FINAL_RULE,
            "interim_final": cls.INTERIM_FINAL_RULE,
            "interim_rule": cls.INTERIM_RULE,
            "interim": cls.INTERIM_RULE,
            "correction": cls.CORRECTION,
            "correcting_amendment": cls.CORRECTION,
            "withdrawal": cls.WITHDRAWAL,
            "withdrawn": cls.WITHDRAWAL,
            "delay": cls.DELAY,
            "delay_effective_date": cls.DELAY_EFFECTIVE_DATE,
            "effective_date_delay": cls.DELAY_EFFECTIVE_DATE,
            "notice": cls.NOTICE,
            "presidential_document": cls.PRESIDENTIAL_DOCUMENT,
            "other": cls.OTHER,
        }
        if text not in aliases:
            raise FederalRegisterChangeError(f"unsupported document type: {value!r}")
        return aliases[text]


class ChangeRelation(str, Enum):
    """How one FR change document relates to another or to a base."""

    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    CORRECTS = "corrects"
    WITHDRAWS = "withdraws"
    STAYS = "stays"
    DELAYS_EFFECTIVE_DATE = "delays_effective_date"
    REINSTATES = "reinstates"
    RELATED = "related"

    @classmethod
    def coerce(cls, value: Any) -> "ChangeRelation":
        if isinstance(value, ChangeRelation):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for rel in cls:
            if rel.value == text or rel.name.lower() == text:
                return rel
        raise FederalRegisterChangeError(f"unsupported change relation: {value!r}")


# Document types that can never be binding.
_ALWAYS_NONBINDING = frozenset(
    {
        RuleDocumentType.PROPOSED_RULE,
        RuleDocumentType.WITHDRAWAL,
        RuleDocumentType.NOTICE,
        RuleDocumentType.PRESIDENTIAL_DOCUMENT,
        RuleDocumentType.OTHER,
    }
)

# Types that may be binding once effective (promulgated regulation / change).
_POTENTIALLY_BINDING = frozenset(
    {
        RuleDocumentType.FINAL_RULE,
        RuleDocumentType.INTERIM_FINAL_RULE,
        RuleDocumentType.INTERIM_RULE,
        RuleDocumentType.CORRECTION,
        RuleDocumentType.DELAY,
        RuleDocumentType.DELAY_EFFECTIVE_DATE,
    }
)


def is_binding_document_type(doc_type: RuleDocumentType | str) -> bool:
    """Return whether *doc_type* may ever be treated as binding law.

    Proposed and withdrawn rules are always nonbinding. Notices and pure
    presidential documents are also nonbinding for patent-rule purposes.
    """

    kind = RuleDocumentType.coerce(doc_type)
    return kind in _POTENTIALLY_BINDING and kind not in _ALWAYS_NONBINDING


def assert_not_masquerading_as_official(
    *,
    authority_tier: AuthorityTier,
    identity_role: IdentityRole | None = None,
    provider: str | None = None,
    is_official_edition: bool = False,
) -> None:
    """Fail closed when unofficial FR.gov text is labeled as official edition."""

    provider_l = (provider or "").lower()
    is_fr_gov = (
        "federalregister.gov" in provider_l
        or provider_l in ("federalregister", "fr_api", "fr-api")
    )
    if is_official_edition and (
        authority_tier is AuthorityTier.UNOFFICIAL_CURRENT or is_fr_gov
    ):
        raise UnofficialMasqueradeError(
            "FederalRegister.gov discovery text must not be labeled as an "
            "official edition; verify with GovInfo official PDF/XML instead"
        )
    if (
        authority_tier is AuthorityTier.UNOFFICIAL_CURRENT
        and identity_role is IdentityRole.OFFICIAL_ARTIFACT
    ):
        raise UnofficialMasqueradeError(
            "unofficial-current presentation cannot use official_artifact role"
        )
    if is_fr_gov and authority_tier in (
        AuthorityTier.OFFICIAL_BASE,
        AuthorityTier.OFFICIAL_CHANGE,
    ):
        raise UnofficialMasqueradeError(
            "federalregister.gov provider cannot carry official-base or "
            "official-change authority tier"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterChangeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterChangeError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise FederalRegisterChangeError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise FederalRegisterChangeError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise FederalRegisterChangeError(f"{name} must be a datetime or ISO-8601 string")
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


def _parse_optional_date(value: Any, *, name: str = "date") -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise FederalRegisterChangeError(f"{name} must be an ISO date") from exc
    raise FederalRegisterChangeError(f"{name} must be a date or ISO date string")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k]) for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    return govinfo_content_sha256(data)


def normalize_document_number(document_number: Any) -> str:
    """Normalize an FR document number (e.g. ``2024-05512``)."""

    text = _require_non_empty_str(str(document_number), "document_number")
    reject_hard_coded_latest(text, field_name="document_number")
    return text.strip()


def stable_rule_identity(
    *,
    document_number: Any,
    jurisdiction: str = DEFAULT_JURISDICTION,
) -> str:
    """Stable identity independent of discovery vs official packaging.

    Shape: ``fr:{jurisdiction}:{document_number}``
    """

    doc = normalize_document_number(document_number)
    jur = _require_non_empty_str(jurisdiction, "jurisdiction").lower()
    return f"fr:{jur}:{doc}"


def federal_register_html_url(document_number: Any) -> str:
    doc = normalize_document_number(document_number)
    # FR.gov uses publication date paths; document-number landing works via API.
    return f"{FEDERAL_REGISTER_DOC_BASE}/{doc}"


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChangeEdge:
    """Relation between FR change documents (corrects, withdraws, delays, …)."""

    relation: ChangeRelation
    source_document_number: str
    target_document_number: str
    effective_date: Optional[date] = None
    reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "relation", ChangeRelation.coerce(self.relation))
        object.__setattr__(
            self,
            "source_document_number",
            normalize_document_number(self.source_document_number),
        )
        object.__setattr__(
            self,
            "target_document_number",
            normalize_document_number(self.target_document_number),
        )
        if self.effective_date is not None:
            object.__setattr__(
                self,
                "effective_date",
                _parse_optional_date(self.effective_date, name="effective_date"),
            )
        if self.reason is not None:
            object.__setattr__(
                self, "reason", _require_non_empty_str(self.reason, "reason")
            )
        if not isinstance(self.metadata, Mapping):
            raise FederalRegisterChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_date": _date_to_str(self.effective_date),
            "metadata": _deep_sorted(self.metadata),
            "reason": self.reason,
            "relation": self.relation.value,
            "source_document_number": self.source_document_number,
            "target_document_number": self.target_document_number,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ChangeEdge":
        if not isinstance(value, Mapping):
            raise FederalRegisterChangeError("change edge must be a mapping")
        return cls(
            relation=ChangeRelation.coerce(value.get("relation", ChangeRelation.RELATED)),
            source_document_number=str(
                value.get("source_document_number")
                or value.get("source")
                or value.get("from")
                or ""
            ),
            target_document_number=str(
                value.get("target_document_number")
                or value.get("target")
                or value.get("to")
                or ""
            ),
            effective_date=value.get("effective_date"),
            reason=value.get("reason"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class DiscoveryDocument:
    """Unofficial FederalRegister.gov API discovery representation.

    Always ``authority_tier=unofficial-current`` and never an official edition.
    """

    document_number: str
    document_type: RuleDocumentType
    title: str
    publication_date: Optional[date] = None
    agencies: tuple[str, ...] = ()
    abstract: Optional[str] = None
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None  # FR.gov PDF link is still unofficial presentation
    citation: Optional[str] = None
    effective_on: Optional[date] = None
    comments_close_on: Optional[date] = None
    content_sha256: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    raw_type: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_number", normalize_document_number(self.document_number)
        )
        object.__setattr__(
            self, "document_type", RuleDocumentType.coerce(self.document_type)
        )
        object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        if self.publication_date is not None:
            object.__setattr__(
                self,
                "publication_date",
                _parse_optional_date(self.publication_date, name="publication_date"),
            )
        agencies = tuple(
            _require_non_empty_str(str(a), "agency")
            for a in (self.agencies or ())
            if a is not None and str(a).strip()
        )
        object.__setattr__(self, "agencies", agencies)
        if self.abstract is not None:
            object.__setattr__(
                self, "abstract", _require_non_empty_str(self.abstract, "abstract")
            )
        if self.html_url is not None:
            object.__setattr__(
                self, "html_url", _require_non_empty_str(self.html_url, "html_url")
            )
        else:
            object.__setattr__(
                self, "html_url", federal_register_html_url(self.document_number)
            )
        if self.pdf_url is not None:
            object.__setattr__(
                self, "pdf_url", _require_non_empty_str(self.pdf_url, "pdf_url")
            )
        if self.citation is not None:
            object.__setattr__(
                self, "citation", _require_non_empty_str(self.citation, "citation")
            )
        if self.effective_on is not None:
            object.__setattr__(
                self,
                "effective_on",
                _parse_optional_date(self.effective_on, name="effective_on"),
            )
        if self.comments_close_on is not None:
            object.__setattr__(
                self,
                "comments_close_on",
                _parse_optional_date(self.comments_close_on, name="comments_close_on"),
            )
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )
        if self.raw_type is not None:
            object.__setattr__(
                self, "raw_type", _require_non_empty_str(self.raw_type, "raw_type")
            )
        if not isinstance(self.metadata, Mapping):
            raise FederalRegisterChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def authority_tier(self) -> AuthorityTier:
        return AuthorityTier.UNOFFICIAL_CURRENT

    @property
    def is_official_edition(self) -> bool:
        return False

    @property
    def is_binding(self) -> bool:
        # Discovery never confers binding effect; only official changes may.
        return False

    @property
    def stable_id(self) -> str:
        return stable_rule_identity(document_number=self.document_number)

    def to_derived_presentation_identity(self) -> Optional[ArtifactIdentity]:
        if not self.content_sha256 or not self.html_url:
            return None
        return ArtifactIdentity(
            provider=DEFAULT_PROVIDER_DISCOVERY,
            source_id=f"fr-api:{self.document_number}",
            artifact_sha256=self.content_sha256,
            source_url=self.html_url,
            media_type="text/html",
            role=IdentityRole.DERIVED_PRESENTATION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract": self.abstract,
            "agencies": list(self.agencies),
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "comments_close_on": _date_to_str(self.comments_close_on),
            "content_sha256": self.content_sha256,
            "document_number": self.document_number,
            "document_type": self.document_type.value,
            "effective_on": _date_to_str(self.effective_on),
            "html_url": self.html_url,
            "is_binding": False,
            "is_official_edition": False,
            "metadata": _deep_sorted(self.metadata),
            "pdf_url": self.pdf_url,
            "publication_date": _date_to_str(self.publication_date),
            "raw_type": self.raw_type,
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "stable_id": self.stable_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "DiscoveryDocument":
        if not isinstance(value, Mapping):
            raise FederalRegisterChangeError("discovery document must be a mapping")
        doc_type = value.get("document_type") or value.get("type") or value.get("raw_type")
        agencies_raw = value.get("agencies") or []
        agencies: list[str] = []
        if isinstance(agencies_raw, Sequence) and not isinstance(agencies_raw, (str, bytes)):
            for a in agencies_raw:
                if isinstance(a, Mapping):
                    name = a.get("slug") or a.get("name") or a.get("raw_name")
                    if name:
                        agencies.append(str(name))
                else:
                    agencies.append(str(a))
        return cls(
            document_number=str(
                value.get("document_number") or value.get("document_number_id") or ""
            ),
            document_type=RuleDocumentType.coerce(doc_type or RuleDocumentType.OTHER),
            title=str(value.get("title") or value.get("html_title") or "Untitled"),
            publication_date=value.get("publication_date"),
            agencies=tuple(agencies),
            abstract=value.get("abstract"),
            html_url=value.get("html_url") or value.get("html_url_full"),
            pdf_url=value.get("pdf_url"),
            citation=value.get("citation"),
            effective_on=value.get("effective_on") or value.get("effective_date"),
            comments_close_on=value.get("comments_close_on"),
            content_sha256=value.get("content_sha256"),
            retrieved_at=value.get("retrieved_at"),
            raw_type=value.get("raw_type") or value.get("type"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RuleChangeRecord:
    """One patent-rule change with discovery + optional official GovInfo bind.

    Temporal fields (effective / compliance) and correction links are first-class
    so they survive deterministic replay.
    """

    document_number: str
    document_type: RuleDocumentType
    title: str
    publication_date: Optional[date] = None
    effective_date: Optional[date] = None
    compliance_date: Optional[date] = None
    termination_date: Optional[date] = None
    delayed_effective_date: Optional[date] = None
    agencies: tuple[str, ...] = ()
    citation: Optional[str] = None
    fr_citation: Optional[str] = None  # e.g. 89 FR 12345
    cfr_references: tuple[str, ...] = ()
    text_excerpt: Optional[str] = None
    discovery: Optional[DiscoveryDocument] = None
    govinfo_package_id: Optional[str] = None
    govinfo_granule_id: Optional[str] = None
    official_artifact: Optional[ArtifactIdentity] = None
    derived_presentation: Optional[ArtifactIdentity] = None
    signature: Optional[SignatureEvidence] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    verification_status: Optional[str] = None
    verification_failure: Optional[Mapping[str, Any]] = None
    is_binding: bool = False
    withdrawn: bool = False
    corrects: Optional[str] = None
    withdraws: Optional[str] = None
    delays: Optional[str] = None
    amends: Optional[str] = None
    relations: tuple[ChangeEdge, ...] = ()
    receipt: Optional[SourceReceipt] = None
    status: ResolutionStatus = ResolutionStatus.RESOLVED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_number", normalize_document_number(self.document_number)
        )
        object.__setattr__(
            self, "document_type", RuleDocumentType.coerce(self.document_type)
        )
        object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        for name in (
            "publication_date",
            "effective_date",
            "compliance_date",
            "termination_date",
            "delayed_effective_date",
        ):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(
                    self, name, _parse_optional_date(raw, name=name)
                )
        agencies = tuple(
            _require_non_empty_str(str(a), "agency")
            for a in (self.agencies or ())
            if a is not None and str(a).strip()
        )
        object.__setattr__(self, "agencies", agencies)
        for name in ("citation", "fr_citation", "text_excerpt"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))
        refs = tuple(
            _require_non_empty_str(str(r), "cfr_reference")
            for r in (self.cfr_references or ())
            if r is not None and str(r).strip()
        )
        object.__setattr__(self, "cfr_references", refs)
        if self.discovery is not None and not isinstance(self.discovery, DiscoveryDocument):
            object.__setattr__(
                self, "discovery", DiscoveryDocument.from_dict(self.discovery)  # type: ignore[arg-type]
            )
        if self.govinfo_package_id is not None:
            object.__setattr__(
                self, "govinfo_package_id", normalize_package_id(self.govinfo_package_id)
            )
        if self.govinfo_granule_id is not None:
            object.__setattr__(
                self, "govinfo_granule_id", normalize_granule_id(self.govinfo_granule_id)
            )
        if self.official_artifact is not None:
            if not isinstance(self.official_artifact, ArtifactIdentity):
                object.__setattr__(
                    self,
                    "official_artifact",
                    ArtifactIdentity.from_dict(self.official_artifact),  # type: ignore[arg-type]
                )
            if self.official_artifact.role is not IdentityRole.OFFICIAL_ARTIFACT:
                object.__setattr__(
                    self,
                    "official_artifact",
                    ArtifactIdentity(
                        provider=self.official_artifact.provider,
                        source_id=self.official_artifact.source_id,
                        artifact_sha256=self.official_artifact.artifact_sha256,
                        source_url=self.official_artifact.source_url,
                        media_type=self.official_artifact.media_type,
                        byte_size=self.official_artifact.byte_size,
                        upstream_package_id=self.official_artifact.upstream_package_id,
                        role=IdentityRole.OFFICIAL_ARTIFACT,
                    ),
                )
        if self.derived_presentation is not None:
            if not isinstance(self.derived_presentation, ArtifactIdentity):
                object.__setattr__(
                    self,
                    "derived_presentation",
                    ArtifactIdentity.from_dict(self.derived_presentation),  # type: ignore[arg-type]
                )
            # Force derived role so discovery cannot impersonate official.
            dp = self.derived_presentation
            if dp.role is not IdentityRole.DERIVED_PRESENTATION:
                object.__setattr__(
                    self,
                    "derived_presentation",
                    ArtifactIdentity(
                        provider=dp.provider,
                        source_id=dp.source_id,
                        artifact_sha256=dp.artifact_sha256,
                        source_url=dp.source_url,
                        media_type=dp.media_type,
                        byte_size=dp.byte_size,
                        upstream_package_id=dp.upstream_package_id,
                        role=IdentityRole.DERIVED_PRESENTATION,
                    ),
                )
            # Fail closed: FR.gov provider on derived is fine; official role is not.
            assert_not_masquerading_as_official(
                authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
                identity_role=IdentityRole.DERIVED_PRESENTATION,
                provider=dp.provider,
                is_official_edition=False,
            )
        if self.signature is not None and not isinstance(self.signature, SignatureEvidence):
            object.__setattr__(
                self, "signature", SignatureEvidence.from_dict(self.signature)  # type: ignore[arg-type]
            )
        if not isinstance(self.verification_state, VerificationState):
            object.__setattr__(
                self, "verification_state", VerificationState(str(self.verification_state))
            )
        if self.verification_failure is not None:
            if not isinstance(self.verification_failure, Mapping):
                raise FederalRegisterChangeError("verification_failure must be a mapping")
            object.__setattr__(self, "verification_failure", dict(self.verification_failure))
        for name in ("corrects", "withdraws", "delays", "amends"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, normalize_document_number(raw))
        rels: list[ChangeEdge] = []
        for edge in self.relations or ():
            if isinstance(edge, ChangeEdge):
                rels.append(edge)
            elif isinstance(edge, Mapping):
                rels.append(ChangeEdge.from_dict(edge))
            else:
                raise FederalRegisterChangeError("relations entries must be mappings")
        object.__setattr__(self, "relations", tuple(rels))
        if self.receipt is not None and not isinstance(self.receipt, SourceReceipt):
            object.__setattr__(
                self, "receipt", SourceReceipt.from_dict(self.receipt)  # type: ignore[arg-type]
            )
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))

        # Binding rules: proposed and withdrawn never bind.
        kind = self.document_type
        withdrawn_flag = bool(self.withdrawn) or kind is RuleDocumentType.WITHDRAWAL
        object.__setattr__(self, "withdrawn", withdrawn_flag)
        allowed_binding = is_binding_document_type(kind) and not withdrawn_flag
        if self.is_binding and not allowed_binding:
            raise BindingElevationError(
                f"{kind.value} documents (document_number={self.document_number}) "
                "must remain nonbinding"
            )
        if not allowed_binding:
            object.__setattr__(self, "is_binding", False)
        # If official artifact is present and type is potentially binding and not
        # withdrawn, honor the provided is_binding flag (default True for finals).
        elif self.official_artifact is not None and kind in (
            RuleDocumentType.FINAL_RULE,
            RuleDocumentType.INTERIM_FINAL_RULE,
            RuleDocumentType.INTERIM_RULE,
            RuleDocumentType.CORRECTION,
        ):
            # Default binding for official final/interim/correction when not set False.
            pass

        if not isinstance(self.metadata, Mapping):
            raise FederalRegisterChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def stable_id(self) -> str:
        return stable_rule_identity(document_number=self.document_number)

    @property
    def authority_tier(self) -> AuthorityTier:
        if self.official_artifact is not None:
            return AuthorityTier.OFFICIAL_CHANGE
        return AuthorityTier.UNOFFICIAL_CURRENT

    @property
    def is_official_edition(self) -> bool:
        return self.official_artifact is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agencies": list(self.agencies),
            "amends": self.amends,
            "authority_tier": self.authority_tier.value,
            "cfr_references": list(self.cfr_references),
            "citation": self.citation,
            "compliance_date": _date_to_str(self.compliance_date),
            "corrects": self.corrects,
            "delayed_effective_date": _date_to_str(self.delayed_effective_date),
            "delays": self.delays,
            "derived_presentation": (
                None
                if self.derived_presentation is None
                else self.derived_presentation.to_dict()
            ),
            "discovery": None if self.discovery is None else self.discovery.to_dict(),
            "document_number": self.document_number,
            "document_type": self.document_type.value,
            "effective_date": _date_to_str(self.effective_date),
            "fr_citation": self.fr_citation,
            "govinfo_granule_id": self.govinfo_granule_id,
            "govinfo_package_id": self.govinfo_package_id,
            "is_binding": bool(self.is_binding),
            "is_official_edition": self.is_official_edition,
            "metadata": _deep_sorted(self.metadata),
            "official_artifact": (
                None if self.official_artifact is None else self.official_artifact.to_dict()
            ),
            "publication_date": _date_to_str(self.publication_date),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "relations": [e.to_dict() for e in self.relations],
            "signature": None if self.signature is None else self.signature.to_dict(),
            "stable_id": self.stable_id,
            "status": self.status.value,
            "termination_date": _date_to_str(self.termination_date),
            "text_excerpt": self.text_excerpt,
            "title": self.title,
            "verification_failure": (
                None
                if self.verification_failure is None
                else _deep_sorted(self.verification_failure)
            ),
            "verification_state": self.verification_state.value,
            "verification_status": self.verification_status,
            "withdrawn": bool(self.withdrawn),
            "withdraws": self.withdraws,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "RuleChangeRecord":
        if not isinstance(value, Mapping):
            raise FederalRegisterChangeError("rule change record must be a mapping")
        discovery_raw = value.get("discovery")
        official_raw = value.get("official_artifact")
        derived_raw = value.get("derived_presentation")
        sig_raw = value.get("signature")
        receipt_raw = value.get("receipt")
        # Infer binding default for final rules with official artifacts.
        doc_type = RuleDocumentType.coerce(
            value.get("document_type") or value.get("type") or RuleDocumentType.OTHER
        )
        withdrawn = bool(value.get("withdrawn", False)) or doc_type is RuleDocumentType.WITHDRAWAL
        if "is_binding" in value:
            is_binding = bool(value["is_binding"])
        else:
            is_binding = (
                is_binding_document_type(doc_type)
                and not withdrawn
                and official_raw is not None
            )
        return cls(
            document_number=str(value.get("document_number") or ""),
            document_type=doc_type,
            title=str(value.get("title") or "Untitled"),
            publication_date=value.get("publication_date"),
            effective_date=value.get("effective_date") or value.get("effective_on"),
            compliance_date=value.get("compliance_date"),
            termination_date=value.get("termination_date"),
            delayed_effective_date=value.get("delayed_effective_date"),
            agencies=tuple(value.get("agencies") or ()),
            citation=value.get("citation"),
            fr_citation=value.get("fr_citation"),
            cfr_references=tuple(value.get("cfr_references") or ()),
            text_excerpt=value.get("text_excerpt"),
            discovery=None if discovery_raw is None else DiscoveryDocument.from_dict(discovery_raw),
            govinfo_package_id=value.get("govinfo_package_id"),
            govinfo_granule_id=value.get("govinfo_granule_id")
            or value.get("document_number"),
            official_artifact=(
                None if official_raw is None else ArtifactIdentity.from_dict(official_raw)
            ),
            derived_presentation=(
                None if derived_raw is None else ArtifactIdentity.from_dict(derived_raw)
            ),
            signature=None if sig_raw is None else SignatureEvidence.from_dict(sig_raw),
            verification_state=value.get(
                "verification_state", VerificationState.UNVERIFIED
            ),
            verification_status=value.get("verification_status"),
            verification_failure=value.get("verification_failure"),
            is_binding=is_binding,
            withdrawn=withdrawn,
            corrects=value.get("corrects"),
            withdraws=value.get("withdraws"),
            delays=value.get("delays"),
            amends=value.get("amends"),
            relations=tuple(value.get("relations") or ()),
            receipt=None if receipt_raw is None else SourceReceipt.from_dict(receipt_raw),
            status=ResolutionStatus(
                str(value.get("status") or ResolutionStatus.RESOLVED.value)
            ),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RuleChangeAcquisition:
    """Bundle of discovered patent-rule changes with official binds and edges."""

    status: ResolutionStatus
    records: Mapping[str, RuleChangeRecord]
    edges: tuple[ChangeEdge, ...] = ()
    govinfo_packages: Mapping[str, GovInfoPackage] = field(default_factory=dict)
    authority_sources: Mapping[str, AuthoritySourceRecord] = field(default_factory=dict)
    failures: tuple[Mapping[str, Any], ...] = ()
    receipt: Optional[SourceReceipt] = None
    notes: Optional[str] = None
    unknown_reason: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResolutionStatus):
            object.__setattr__(self, "status", ResolutionStatus(str(self.status)))
        object.__setattr__(self, "records", dict(self.records))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "govinfo_packages", dict(self.govinfo_packages))
        object.__setattr__(self, "authority_sources", dict(self.authority_sources))
        object.__setattr__(self, "failures", tuple(dict(f) for f in self.failures))
        if not isinstance(self.metadata, Mapping):
            raise FederalRegisterChangeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_unknown(self) -> bool:
        return self.status is ResolutionStatus.UNKNOWN

    def get_record(self, document_number: Any) -> RuleChangeRecord:
        key = normalize_document_number(document_number)
        try:
            return self.records[key]
        except KeyError as exc:
            raise DocumentNotFoundError(f"document {key!r} not found") from exc

    def binding_records(self) -> list[RuleChangeRecord]:
        return [r for r in self.records.values() if r.is_binding]

    def nonbinding_records(self) -> list[RuleChangeRecord]:
        return [r for r in self.records.values() if not r.is_binding]

    def proposed_rules(self) -> list[RuleChangeRecord]:
        return [
            r
            for r in self.records.values()
            if r.document_type is RuleDocumentType.PROPOSED_RULE
        ]

    def withdrawn_rules(self) -> list[RuleChangeRecord]:
        return [
            r
            for r in self.records.values()
            if r.withdrawn or r.document_type is RuleDocumentType.WITHDRAWAL
        ]

    def corrections(self) -> list[RuleChangeRecord]:
        return [
            r
            for r in self.records.values()
            if r.document_type is RuleDocumentType.CORRECTION or r.corrects
        ]

    def records_with_temporal_fields(self) -> list[RuleChangeRecord]:
        return [
            r
            for r in self.records.values()
            if r.effective_date is not None
            or r.compliance_date is not None
            or r.delayed_effective_date is not None
        ]

    def every_unofficial_is_not_official(self) -> bool:
        """Acceptance helper: no discovery text masquerades as official edition."""

        for record in self.records.values():
            if record.discovery is not None:
                if record.discovery.is_official_edition:
                    return False
                if record.discovery.authority_tier is not AuthorityTier.UNOFFICIAL_CURRENT:
                    return False
                if record.discovery.is_binding:
                    return False
            if record.derived_presentation is not None:
                if record.derived_presentation.role is not IdentityRole.DERIVED_PRESENTATION:
                    return False
                provider = record.derived_presentation.provider.lower()
                if "federalregister.gov" in provider or provider in (
                    "federalregister",
                    "fr_api",
                ):
                    if record.official_artifact is not None:
                        # Dual identity is fine only when official is GovInfo.
                        if record.official_artifact.provider.lower() in (
                            "federalregister.gov",
                            "federalregister",
                            "fr_api",
                        ):
                            return False
            if record.official_artifact is not None:
                if record.official_artifact.role is not IdentityRole.OFFICIAL_ARTIFACT:
                    return False
                if "federalregister.gov" in record.official_artifact.provider.lower():
                    return False
        return True

    def every_proposed_and_withdrawn_nonbinding(self) -> bool:
        for record in self.records.values():
            if record.document_type is RuleDocumentType.PROPOSED_RULE and record.is_binding:
                return False
            if (
                record.withdrawn or record.document_type is RuleDocumentType.WITHDRAWAL
            ) and record.is_binding:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_sources": {
                k: v.to_dict() for k, v in sorted(self.authority_sources.items())
            },
            "edges": [e.to_dict() for e in self.edges],
            "failures": [_deep_sorted(f) for f in self.failures],
            "govinfo_packages": {
                k: v.to_dict() for k, v in sorted(self.govinfo_packages.items())
            },
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "records": {k: v.to_dict() for k, v in sorted(self.records.items())},
            "schema_version": SCHEMA_VERSION,
            "status": self.status.value,
            "unknown_reason": self.unknown_reason,
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Return the repository Federal Register fixture directory when present."""

    return govinfo_default_fixture_dir()


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise FixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def _build_authority_source_for_record(
    record: RuleChangeRecord,
    *,
    receipt: SourceReceipt | None = None,
) -> AuthoritySourceRecord:
    tier = record.authority_tier
    # Guard: never let FR.gov discovery become official.
    if record.official_artifact is None:
        tier = AuthorityTier.UNOFFICIAL_CURRENT
    else:
        tier = AuthorityTier.OFFICIAL_CHANGE
        assert_not_masquerading_as_official(
            authority_tier=tier,
            identity_role=IdentityRole.OFFICIAL_ARTIFACT,
            provider=record.official_artifact.provider,
            is_official_edition=True,
        )

    sig = record.signature
    return AuthoritySourceRecord(
        source_key=f"fr-{record.document_number}",
        authority_tier=tier,
        collection=COLLECTION_FR,
        jurisdiction=DEFAULT_JURISDICTION,
        citation=record.citation or record.fr_citation or record.document_number,
        edition=record.govinfo_package_id,
        version=record.document_number,
        publication_date=record.publication_date,
        effective_start=record.effective_date or record.delayed_effective_date,
        effective_end=record.termination_date,
        official_artifact=record.official_artifact,
        derived_presentation=record.derived_presentation,
        receipt=receipt or record.receipt,
        verification_state=record.verification_state,
        signature_present=sig is not None and sig.result is not SignatureResult.MISSING,
        signature_valid=None if sig is None else sig.is_valid,
        signature_algorithm=None if sig is None else sig.algorithm,
        signature_evidence=None if sig is None else sig.evidence,
        notes=(
            f"FR {record.document_type.value} {record.document_number}; "
            f"binding={record.is_binding}; "
            f"official={record.is_official_edition}"
        ),
        metadata={
            "document_type": record.document_type.value,
            "is_binding": record.is_binding,
            "withdrawn": record.withdrawn,
            "compliance_date": _date_to_str(record.compliance_date),
            "effective_date": _date_to_str(record.effective_date),
            "delayed_effective_date": _date_to_str(record.delayed_effective_date),
            "corrects": record.corrects,
            "withdraws": record.withdraws,
            "delays": record.delays,
            "govinfo_package_id": record.govinfo_package_id,
            "govinfo_granule_id": record.govinfo_granule_id,
            "processor_schema": SCHEMA_VERSION,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "verification_status": record.verification_status,
            "verification_failure": record.verification_failure,
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class FederalRegisterChangeProcessor:
    """Discover USPTO FR rules/notices and bind official GovInfo artifacts.

    Primary path is fixture replay. Live network discovery is deliberately not
    performed by default so tests and offline operators remain deterministic.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        registry: AuthoritySourceRegistry | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
        govinfo_client: GovInfoClient | None = None,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.registry = (
            registry
            if registry is not None
            else AuthoritySourceRegistry(default_retry_cache_policy=retry_cache_policy)
        )
        self.govinfo = govinfo_client or GovInfoClient(
            fixture_dir=self.fixture_dir,
            retry_cache_policy=retry_cache_policy,
        )
        self._acquisitions: list[RuleChangeAcquisition] = []

    # ------------------------------------------------------------------
    # Fixture acquisition
    # ------------------------------------------------------------------

    def load_fixture_package(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_package_path()
        if target.is_dir():
            recipe = target / "patent_rule_changes_recipe.json"
            if recipe.is_file():
                target = recipe
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks patent_rule_changes_recipe.json"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and schema not in {
            FIXTURE_SCHEMA_VERSION,
            SCHEMA_VERSION,
            GOVINFO_FIXTURE_SCHEMA,
            GOVINFO_SCHEMA,
        }:
            if not (
                str(schema).startswith("federal-register")
                or str(schema).startswith("govinfo")
            ):
                raise FixtureSchemaError(
                    f"unsupported fixture schema_version {schema!r} in {target}"
                )
        return payload

    def _default_package_path(self) -> Path:
        recipe = self.fixture_dir / "patent_rule_changes_recipe.json"
        if recipe.is_file():
            return recipe
        return self.fixture_dir

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        register: bool = True,
        bind_govinfo: bool = True,
    ) -> RuleChangeAcquisition:
        payload = self.load_fixture_package(path)
        return self.acquire_from_payload(
            payload, register=register, bind_govinfo=bind_govinfo
        )

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        register: bool = True,
        bind_govinfo: bool = True,
    ) -> RuleChangeAcquisition:
        if not isinstance(payload, Mapping):
            raise FixtureSchemaError("payload must be a mapping")

        # Load GovInfo packages first (shared recipe or nested).
        packages = self.govinfo.load_packages_from_payload(payload)
        package_map = {p.package_id: p for p in packages}

        discovery_raw = (
            payload.get("discovery")
            or payload.get("documents")
            or payload.get("results")
            or []
        )
        if not discovery_raw and not payload.get("records"):
            return RuleChangeAcquisition(
                status=ResolutionStatus.UNKNOWN,
                records={},
                edges=(),
                govinfo_packages=package_map,
                notes="No discovery documents or change records present.",
                unknown_reason="missing discovery data",
                metadata={"schema_version": payload.get("schema_version")},
            )

        # Parse discovery documents (unofficial).
        discovery_by_doc: dict[str, DiscoveryDocument] = {}
        if isinstance(discovery_raw, Sequence) and not isinstance(
            discovery_raw, (str, bytes)
        ):
            for item in discovery_raw:
                if not isinstance(item, Mapping):
                    continue
                try:
                    disc = DiscoveryDocument.from_dict(item)
                except (FederalRegisterChangeError, HardCodedLatestEditionError):
                    continue
                discovery_by_doc[disc.document_number] = disc

        # Parse full change records when provided; else build from discovery.
        records: dict[str, RuleChangeRecord] = {}
        raw_records = payload.get("records") or payload.get("changes") or []
        if isinstance(raw_records, Sequence) and not isinstance(
            raw_records, (str, bytes)
        ):
            for item in raw_records:
                if not isinstance(item, Mapping):
                    continue
                item = dict(item)
                doc_num = str(item.get("document_number") or "")
                if doc_num and doc_num in discovery_by_doc and "discovery" not in item:
                    item["discovery"] = discovery_by_doc[doc_num].to_dict()
                try:
                    record = RuleChangeRecord.from_dict(item)
                except BindingElevationError:
                    raise
                except (FederalRegisterChangeError, HardCodedLatestEditionError):
                    continue
                records[record.document_number] = record

        # Ensure every discovery doc has a record (discovery-only path).
        for disc in discovery_by_doc.values():
            if disc.document_number in records:
                # Merge discovery onto existing record if missing.
                existing = records[disc.document_number]
                if existing.discovery is None:
                    records[disc.document_number] = RuleChangeRecord.from_dict(
                        {
                            **existing.to_dict(),
                            "discovery": disc.to_dict(),
                            "derived_presentation": (
                                None
                                if disc.to_derived_presentation_identity() is None
                                else disc.to_derived_presentation_identity().to_dict()
                            ),
                        }
                    )
                continue
            derived = disc.to_derived_presentation_identity()
            records[disc.document_number] = RuleChangeRecord(
                document_number=disc.document_number,
                document_type=disc.document_type,
                title=disc.title,
                publication_date=disc.publication_date,
                effective_date=disc.effective_on,
                agencies=disc.agencies,
                citation=disc.citation,
                discovery=disc,
                derived_presentation=derived,
                is_binding=False,
                status=ResolutionStatus.RESOLVED,
            )

        # Parse explicit edges.
        edges: list[ChangeEdge] = []
        for raw_edge in payload.get("edges") or payload.get("relations") or []:
            if not isinstance(raw_edge, Mapping):
                continue
            edges.append(ChangeEdge.from_dict(raw_edge))

        # Derive edges from record fields when not listed.
        seen_edge_keys: set[tuple[str, str, str]] = {
            (e.relation.value, e.source_document_number, e.target_document_number)
            for e in edges
        }
        for record in list(records.values()):
            for relation, target in (
                (ChangeRelation.CORRECTS, record.corrects),
                (ChangeRelation.WITHDRAWS, record.withdraws),
                (ChangeRelation.DELAYS_EFFECTIVE_DATE, record.delays),
                (ChangeRelation.AMENDS, record.amends),
            ):
                if not target:
                    continue
                key = (relation.value, record.document_number, target)
                if key in seen_edge_keys:
                    continue
                edges.append(
                    ChangeEdge(
                        relation=relation,
                        source_document_number=record.document_number,
                        target_document_number=target,
                        effective_date=record.effective_date
                        or record.delayed_effective_date
                        or record.publication_date,
                    )
                )
                seen_edge_keys.add(key)

        # Bind GovInfo official artifacts.
        failures: list[dict[str, Any]] = []
        if bind_govinfo:
            records = self._bind_govinfo(records, failures=failures)

        # Authority sources.
        authority_sources: dict[str, AuthoritySourceRecord] = {}
        for record in records.values():
            auth = _build_authority_source_for_record(record)
            authority_sources[auth.source_key] = auth
            if register:
                self.registry.register(auth, overwrite=True)

        status = ResolutionStatus.RESOLVED
        if failures and not records:
            # Prefer the most specific failure status.
            kinds = {str(f.get("kind")) for f in failures}
            if "retry" in kinds:
                status = ResolutionStatus.RETRY_FAILED
            elif "signature" in kinds:
                status = ResolutionStatus.SIGNATURE_FAILED
            elif "schema" in kinds:
                status = ResolutionStatus.SCHEMA_FAILED
            else:
                status = ResolutionStatus.ERROR
        elif failures:
            status = ResolutionStatus.PARTIAL
        elif not records:
            status = ResolutionStatus.UNKNOWN

        acquisition = RuleChangeAcquisition(
            status=status,
            records=records,
            edges=tuple(edges),
            govinfo_packages=package_map,
            authority_sources=authority_sources,
            failures=tuple(failures),
            notes=payload.get("notes"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "record_count": len(records),
                "edge_count": len(edges),
                "failure_count": len(failures),
                "package_count": len(package_map),
            },
        )
        self._acquisitions.append(acquisition)
        return acquisition

    def _bind_govinfo(
        self,
        records: Mapping[str, RuleChangeRecord],
        *,
        failures: list[dict[str, Any]],
    ) -> dict[str, RuleChangeRecord]:
        updated: dict[str, RuleChangeRecord] = {}
        for doc_num, record in records.items():
            package_id = record.govinfo_package_id
            granule_id = record.govinfo_granule_id or record.document_number
            if not package_id:
                # No official bind requested; keep discovery-only (unofficial).
                updated[doc_num] = record
                continue

            result = self.govinfo.verify_granule(
                package_id=package_id,
                granule_id=granule_id,
                require_valid_signature=False,
            )
            if result.is_failure:
                failures.append(
                    dict(result.failure or {"kind": "error", "message": result.notes})
                )
                # Keep record but attach explicit failure; do not claim verified.
                payload = record.to_dict()
                payload["verification_status"] = result.status.value
                payload["verification_failure"] = result.failure
                payload["verification_state"] = result.verification_state.value
                payload["status"] = (
                    ResolutionStatus.SIGNATURE_FAILED.value
                    if result.status is GovInfoResolutionStatus.SIGNATURE_FAILED
                    else ResolutionStatus.PARTIAL.value
                    if result.status is GovInfoResolutionStatus.PARTIAL
                    else ResolutionStatus.ERROR.value
                    if result.status is GovInfoResolutionStatus.ERROR
                    else ResolutionStatus.RETRY_FAILED.value
                    if result.status is GovInfoResolutionStatus.RETRY_FAILED
                    else ResolutionStatus.SCHEMA_FAILED.value
                    if result.status is GovInfoResolutionStatus.SCHEMA_FAILED
                    else ResolutionStatus.PARTIAL.value
                )
                # Official artifact identity may still be present on signature fail.
                if result.official_artifact is not None:
                    payload["official_artifact"] = result.official_artifact.to_dict()
                if result.signature is not None:
                    payload["signature"] = result.signature.to_dict()
                if result.receipt is not None:
                    payload["receipt"] = result.receipt.to_dict()
                # Binding requires successful official bind for finals; on failure
                # keep nonbinding until verified.
                if result.status is not GovInfoResolutionStatus.VERIFIED:
                    # Signature-failed with official bytes: still official-change
                    # identity, but is_binding only if type allows and we had
                    # intended binding — keep type rules, do not elevate proposed.
                    pass
                updated[doc_num] = RuleChangeRecord.from_dict(payload)
                continue

            payload = record.to_dict()
            payload["govinfo_package_id"] = result.package_id
            payload["govinfo_granule_id"] = result.granule_id
            payload["verification_status"] = result.status.value
            payload["verification_state"] = result.verification_state.value
            payload["verification_failure"] = None
            if result.official_artifact is not None:
                payload["official_artifact"] = result.official_artifact.to_dict()
            if result.signature is not None:
                payload["signature"] = result.signature.to_dict()
            if result.receipt is not None:
                payload["receipt"] = result.receipt.to_dict()
            # Ensure derived presentation from discovery remains separate.
            if record.discovery is not None:
                derived = record.discovery.to_derived_presentation_identity()
                if derived is not None:
                    payload["derived_presentation"] = derived.to_dict()
            # Binding: only potentially binding types with official artifact.
            kind = record.document_type
            if (
                is_binding_document_type(kind)
                and not record.withdrawn
                and result.official_artifact is not None
            ):
                if kind in (
                    RuleDocumentType.FINAL_RULE,
                    RuleDocumentType.INTERIM_FINAL_RULE,
                    RuleDocumentType.INTERIM_RULE,
                    RuleDocumentType.CORRECTION,
                ):
                    payload["is_binding"] = True
            else:
                payload["is_binding"] = False
            updated[doc_num] = RuleChangeRecord.from_dict(payload)
        return updated

    def acquire_unknown(
        self, *, reason: str = "missing discovery data"
    ) -> RuleChangeAcquisition:
        return RuleChangeAcquisition(
            status=ResolutionStatus.UNKNOWN,
            records={},
            edges=(),
            notes="Federal Register discovery unavailable.",
            unknown_reason=reason,
        )

    # ------------------------------------------------------------------
    # Explicit failure helpers (retry / schema / signature)
    # ------------------------------------------------------------------

    def explicit_retry_failure(
        self,
        *,
        package_id: str,
        attempts: int,
        last_status: Optional[int] = None,
        message: Optional[str] = None,
    ) -> GovInfoVerificationResult:
        return self.govinfo.record_retry_failure(
            package_id=package_id,
            attempts=attempts,
            last_status=last_status,
            message=message,
        )

    def explicit_schema_failure(
        self, *, message: str, package_id: Optional[str] = None, field_name: Optional[str] = None
    ) -> GovInfoVerificationResult:
        return self.govinfo.record_schema_failure(
            message=message, package_id=package_id, field_name=field_name
        )

    def explicit_signature_failure(
        self,
        *,
        package_id: str,
        granule_id: str,
        signature_result: SignatureResult | str = SignatureResult.INVALID,
        message: Optional[str] = None,
    ) -> GovInfoVerificationResult:
        return self.govinfo.record_signature_failure(
            package_id=package_id,
            granule_id=granule_id,
            signature_result=signature_result,
            message=message,
        )

    def raise_for_verification_failure(
        self, result: GovInfoVerificationResult
    ) -> None:
        """Raise typed errors for explicit retry/schema/signature failures."""

        if result.status is GovInfoResolutionStatus.RETRY_FAILED:
            fail = result.failure or {}
            raise RetryFailureError(
                str(fail.get("message") or result.notes or "retry failed"),
                failure=fail,
            )
        if result.status is GovInfoResolutionStatus.SCHEMA_FAILED:
            fail = result.failure or {}
            raise SchemaFailureError(
                str(fail.get("message") or result.notes or "schema failed"),
                failure=fail,
            )
        if result.status is GovInfoResolutionStatus.SIGNATURE_FAILED:
            fail = result.failure or {}
            raise SignatureFailureError(
                str(fail.get("message") or result.notes or "signature failed"),
                failure=fail,
            )

    # ------------------------------------------------------------------
    # Acceptance / query helpers
    # ------------------------------------------------------------------

    def list_document_numbers(
        self, acquisition: RuleChangeAcquisition | None = None
    ) -> list[str]:
        acq = acquisition if acquisition is not None else (
            self._acquisitions[-1] if self._acquisitions else None
        )
        if acq is None:
            return []
        return sorted(acq.records.keys())

    def replay_preserves_temporal_fields(
        self,
        path: PathLike | None = None,
    ) -> bool:
        """Return True when two fixture replays yield identical temporal fields."""

        a = self.acquire_from_fixture(path, register=False)
        b = self.acquire_from_fixture(path, register=False)
        if set(a.records) != set(b.records):
            return False
        for doc in a.records:
            ra, rb = a.records[doc], b.records[doc]
            if (
                ra.effective_date != rb.effective_date
                or ra.compliance_date != rb.compliance_date
                or ra.delayed_effective_date != rb.delayed_effective_date
                or ra.corrects != rb.corrects
                or ra.withdraws != rb.withdraws
                or ra.delays != rb.delays
            ):
                return False
        # Edges must also match.
        a_edges = {(e.relation.value, e.source_document_number, e.target_document_number,
                    _date_to_str(e.effective_date)) for e in a.edges}
        b_edges = {(e.relation.value, e.source_document_number, e.target_document_number,
                    _date_to_str(e.effective_date)) for e in b.edges}
        return a_edges == b_edges


# ---------------------------------------------------------------------------
# Fixture recipe builders
# ---------------------------------------------------------------------------


def build_patent_rule_changes_fixture_recipe() -> dict[str, Any]:
    """Compact USPTO FR discovery + GovInfo verification recipe.

    Prefer this generator over bulk golden dumps.
    """

    # Document numbers and package for a coherent mini timeline:
    # 1. proposed rule 2023-10001
    # 2. final rule 2024-05512 (effective + compliance)
    # 3. correction 2024-06001 correcting final
    # 4. withdrawal 2024-07001 withdrawing a different proposed 2023-10002
    # 5. delay 2024-08001 delaying effective date of final
    # 6. interim final 2024-09001

    package_id = "FR-2024-03-15"
    package_sha = content_sha256(f"govinfo|{package_id}|package")

    def _granule(
        doc: str,
        *,
        title: str,
        citation: str,
        sig_result: str = "valid",
    ) -> dict[str, Any]:
        pdf_sha = content_sha256(f"{package_id}|{doc}|pdf")
        xml_sha = content_sha256(f"{package_id}|{doc}|xml")
        return {
            "package_id": package_id,
            "granule_id": doc,
            "document_number": doc,
            "title": title,
            "citation": citation,
            "publication_date": "2024-03-15",
            "signature": {
                "result": sig_result,
                "algorithm": "GPO-PAdES",
                "evidence": f"sig:{package_id}:{doc}",
                "checked_at": "2024-03-16T12:00:00Z",
                "signer": "U.S. Government Publishing Office",
            },
            "formats": {
                "pdf": {
                    "format": "pdf",
                    "artifact_sha256": pdf_sha,
                    "source_url": (
                        f"https://www.govinfo.gov/content/pkg/{package_id}/pdf/"
                        f"{package_id}-{doc}.pdf"
                    ),
                    "byte_size": 12000 + int(doc[-3:]),
                    "upstream_package_id": package_id,
                    "media_type": "application/pdf",
                },
                "xml": {
                    "format": "xml",
                    "artifact_sha256": xml_sha,
                    "source_url": (
                        f"https://www.govinfo.gov/content/pkg/{package_id}/xml/"
                        f"{package_id}-{doc}.xml"
                    ),
                    "byte_size": 8000 + int(doc[-3:]),
                    "upstream_package_id": package_id,
                    "media_type": "application/xml",
                },
            },
        }

    granules = {
        "2024-05512": _granule(
            "2024-05512",
            title="Setting and Adjusting Patent Fees During Fiscal Year 2025",
            citation="89 FR 20100",
        ),
        "2024-06001": _granule(
            "2024-06001",
            title="Setting and Adjusting Patent Fees; Correction",
            citation="89 FR 20500",
        ),
        "2024-07001": _granule(
            "2024-07001",
            title="Withdrawal of Proposed Rule on Terminal Disclaimer Practice",
            citation="89 FR 21000",
        ),
        "2024-08001": _granule(
            "2024-08001",
            title="Setting and Adjusting Patent Fees; Delay of Effective Date",
            citation="89 FR 21500",
        ),
        "2024-09001": _granule(
            "2024-09001",
            title="Interim Final Rule on Electronic Filing Requirements",
            citation="89 FR 22000",
        ),
    }

    discovery = [
        {
            "document_number": "2023-10001",
            "document_type": "proposed_rule",
            "raw_type": "Proposed Rule",
            "title": "Terminal Disclaimer Practice To Obviate Nonstatutory Double Patenting",
            "publication_date": "2023-05-10",
            "agencies": ["patent-and-trademark-office"],
            "abstract": "USPTO proposes changes to terminal disclaimer practice.",
            "html_url": "https://www.federalregister.gov/documents/2023/05/10/2023-10001",
            "citation": "88 FR 30000",
            "comments_close_on": "2023-07-10",
            "content_sha256": content_sha256("fr-api|2023-10001|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2023-10002",
            "document_type": "proposed_rule",
            "raw_type": "Proposed Rule",
            "title": "Proposed Rule Later Withdrawn — Terminal Disclaimer Alternate Track",
            "publication_date": "2023-06-01",
            "agencies": ["patent-and-trademark-office"],
            "abstract": "Alternate proposal subsequently withdrawn.",
            "html_url": "https://www.federalregister.gov/documents/2023/06/01/2023-10002",
            "citation": "88 FR 31000",
            "content_sha256": content_sha256("fr-api|2023-10002|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2024-05512",
            "document_type": "final_rule",
            "raw_type": "Rule",
            "title": "Setting and Adjusting Patent Fees During Fiscal Year 2025",
            "publication_date": "2024-03-15",
            "agencies": ["patent-and-trademark-office", "commerce-department"],
            "abstract": "Final rule setting patent fees for FY2025.",
            "html_url": "https://www.federalregister.gov/documents/2024/03/15/2024-05512",
            "citation": "89 FR 20100",
            "effective_on": "2024-05-01",
            "content_sha256": content_sha256("fr-api|2024-05512|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2024-06001",
            "document_type": "correction",
            "raw_type": "Correction",
            "title": "Setting and Adjusting Patent Fees; Correction",
            "publication_date": "2024-03-22",
            "agencies": ["patent-and-trademark-office"],
            "html_url": "https://www.federalregister.gov/documents/2024/03/22/2024-06001",
            "citation": "89 FR 20500",
            "content_sha256": content_sha256("fr-api|2024-06001|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2024-07001",
            "document_type": "withdrawal",
            "raw_type": "Proposed Rule",
            "title": "Withdrawal of Proposed Rule on Terminal Disclaimer Practice",
            "publication_date": "2024-04-01",
            "agencies": ["patent-and-trademark-office"],
            "html_url": "https://www.federalregister.gov/documents/2024/04/01/2024-07001",
            "citation": "89 FR 21000",
            "content_sha256": content_sha256("fr-api|2024-07001|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2024-08001",
            "document_type": "delay_effective_date",
            "raw_type": "Rule",
            "title": "Setting and Adjusting Patent Fees; Delay of Effective Date",
            "publication_date": "2024-04-10",
            "agencies": ["patent-and-trademark-office"],
            "html_url": "https://www.federalregister.gov/documents/2024/04/10/2024-08001",
            "citation": "89 FR 21500",
            "content_sha256": content_sha256("fr-api|2024-08001|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
        {
            "document_number": "2024-09001",
            "document_type": "interim_final_rule",
            "raw_type": "Rule",
            "title": "Interim Final Rule on Electronic Filing Requirements",
            "publication_date": "2024-04-20",
            "agencies": ["patent-and-trademark-office"],
            "html_url": "https://www.federalregister.gov/documents/2024/04/20/2024-09001",
            "citation": "89 FR 22000",
            "effective_on": "2024-04-20",
            "content_sha256": content_sha256("fr-api|2024-09001|html"),
            "retrieved_at": "2024-06-01T10:00:00Z",
        },
    ]

    records = [
        {
            "document_number": "2023-10001",
            "document_type": "proposed_rule",
            "title": "Terminal Disclaimer Practice To Obviate Nonstatutory Double Patenting",
            "publication_date": "2023-05-10",
            "agencies": ["patent-and-trademark-office"],
            "citation": "88 FR 30000",
            "fr_citation": "88 FR 30000",
            "cfr_references": ["37 CFR 1.321"],
            "text_excerpt": "The USPTO proposes to revise terminal disclaimer practice...",
            "is_binding": False,
            # No govinfo bind for pure proposed (optional); discovery only.
        },
        {
            "document_number": "2023-10002",
            "document_type": "proposed_rule",
            "title": "Proposed Rule Later Withdrawn — Terminal Disclaimer Alternate Track",
            "publication_date": "2023-06-01",
            "agencies": ["patent-and-trademark-office"],
            "citation": "88 FR 31000",
            "fr_citation": "88 FR 31000",
            "is_binding": False,
            "withdrawn": True,
        },
        {
            "document_number": "2024-05512",
            "document_type": "final_rule",
            "title": "Setting and Adjusting Patent Fees During Fiscal Year 2025",
            "publication_date": "2024-03-15",
            "effective_date": "2024-05-01",
            "compliance_date": "2024-06-01",
            "agencies": ["patent-and-trademark-office", "commerce-department"],
            "citation": "89 FR 20100",
            "fr_citation": "89 FR 20100",
            "cfr_references": ["37 CFR 1.16", "37 CFR 1.17", "37 CFR 1.18"],
            "text_excerpt": "The USPTO sets and adjusts patent fees for fiscal year 2025...",
            "govinfo_package_id": package_id,
            "govinfo_granule_id": "2024-05512",
            "is_binding": True,
        },
        {
            "document_number": "2024-06001",
            "document_type": "correction",
            "title": "Setting and Adjusting Patent Fees; Correction",
            "publication_date": "2024-03-22",
            "effective_date": "2024-05-01",
            "agencies": ["patent-and-trademark-office"],
            "citation": "89 FR 20500",
            "fr_citation": "89 FR 20500",
            "text_excerpt": "This document corrects a fee table typographical error...",
            "govinfo_package_id": package_id,
            "govinfo_granule_id": "2024-06001",
            "corrects": "2024-05512",
            "is_binding": True,
        },
        {
            "document_number": "2024-07001",
            "document_type": "withdrawal",
            "title": "Withdrawal of Proposed Rule on Terminal Disclaimer Practice",
            "publication_date": "2024-04-01",
            "agencies": ["patent-and-trademark-office"],
            "citation": "89 FR 21000",
            "fr_citation": "89 FR 21000",
            "govinfo_package_id": package_id,
            "govinfo_granule_id": "2024-07001",
            "withdraws": "2023-10002",
            "is_binding": False,
            "withdrawn": True,
        },
        {
            "document_number": "2024-08001",
            "document_type": "delay_effective_date",
            "title": "Setting and Adjusting Patent Fees; Delay of Effective Date",
            "publication_date": "2024-04-10",
            "delayed_effective_date": "2024-07-01",
            "agencies": ["patent-and-trademark-office"],
            "citation": "89 FR 21500",
            "fr_citation": "89 FR 21500",
            "govinfo_package_id": package_id,
            "govinfo_granule_id": "2024-08001",
            "delays": "2024-05512",
            "is_binding": False,  # delay event itself; effective date change is the effect
        },
        {
            "document_number": "2024-09001",
            "document_type": "interim_final_rule",
            "title": "Interim Final Rule on Electronic Filing Requirements",
            "publication_date": "2024-04-20",
            "effective_date": "2024-04-20",
            "compliance_date": "2024-05-20",
            "agencies": ["patent-and-trademark-office"],
            "citation": "89 FR 22000",
            "fr_citation": "89 FR 22000",
            "cfr_references": ["37 CFR 1.6"],
            "govinfo_package_id": package_id,
            "govinfo_granule_id": "2024-09001",
            "is_binding": True,
        },
    ]

    edges = [
        {
            "relation": "corrects",
            "source_document_number": "2024-06001",
            "target_document_number": "2024-05512",
            "effective_date": "2024-05-01",
            "reason": "Corrects fee table typographical error in final rule.",
        },
        {
            "relation": "withdraws",
            "source_document_number": "2024-07001",
            "target_document_number": "2023-10002",
            "effective_date": "2024-04-01",
            "reason": "Withdraws proposed rule; proposal remains nonbinding.",
        },
        {
            "relation": "delays_effective_date",
            "source_document_number": "2024-08001",
            "target_document_number": "2024-05512",
            "effective_date": "2024-07-01",
            "reason": "Delays effective date of final fee rule to 2024-07-01.",
        },
    ]

    # Explicit failure fixtures for retry/schema/signature acceptance tests.
    failures = [
        {
            "failure_id": "retry:FR-2099-01-01",
            "kind": "retry",
            "package_id": "FR-2099-01-01",
            "attempts": 5,
            "last_status": 429,
            "retry_after": 120.0,
            "message": "GovInfo API returned 429; retry exhausted after 5 attempts.",
        },
        {
            "failure_id": "schema:FR-BAD-PACKAGE",
            "kind": "schema",
            "package_id": "FR-BAD-PACKAGE",
            "field_name": "package_id",
            "message": "package payload missing required package_id field.",
        },
        {
            "failure_id": "signature:FR-2024-03-15:2024-99999",
            "kind": "signature",
            "package_id": package_id,
            "granule_id": "2024-99999",
            "signature_result": "invalid",
            "message": "GPO signature invalid for granule 2024-99999.",
        },
    ]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "uspto-patent-rule-changes-2024",
        "notes": (
            "Compact USPTO Federal Register discovery + GovInfo official bind recipe. "
            "Unofficial FR.gov discovery is labeled unofficial-current; official "
            "PDF/XML come from GovInfo packages/granules with signature results. "
            "Proposed and withdrawn rules remain nonbinding. Effective/compliance "
            "dates and correction/withdrawal/delay edges survive replay. "
            "Retry/schema/signature failures are explicit fixtures."
        ),
        "discovery": discovery,
        "records": records,
        "edges": edges,
        "govinfo_packages": [
            {
                "package_id": package_id,
                "collection": "FR",
                "provider": "govinfo",
                "title": "Federal Register Vol. 89, No. 52",
                "date_issued": "2024-03-15",
                "source_url": f"https://www.govinfo.gov/content/pkg/{package_id}",
                "content_sha256": package_sha,
                "retrieved_at": "2024-03-16T12:00:00Z",
                "signature": {
                    "result": "valid",
                    "algorithm": "GPO-PAdES",
                    "evidence": f"sig:{package_id}:package",
                    "checked_at": "2024-03-16T12:00:00Z",
                    "signer": "U.S. Government Publishing Office",
                },
                "granules": granules,
            }
        ],
        "govinfo_failures": failures,
    }


def build_missing_discovery_fixture() -> dict[str, Any]:
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "fr-missing-discovery",
        "notes": "Discovery deliberately omitted for unknown-status tests.",
        "discovery": [],
        "records": [],
        "edges": [],
        "govinfo_packages": [],
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize default patent-rule change fixtures."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    recipe = build_patent_rule_changes_fixture_recipe()
    recipe_path = root / "patent_rule_changes_recipe.json"
    recipe_path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    missing = build_missing_discovery_fixture()
    missing_path = root / "patent_rule_missing_discovery.json"
    missing_path.write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Federal Register / patent rule change fixtures\n\n"
            "Compact recipes for PATLAW-014. Prefer `patent_rule_changes_recipe.json` "
            "over bulk golden dumps. Unofficial FederalRegister.gov discovery is "
            "never an official edition; official PDF/XML come from GovInfo. "
            "Proposed/withdrawn rules remain nonbinding. Effective/compliance dates "
            "and corrections survive replay. Retry/schema/signature failures are "
            "explicit.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_FR",
    "DEFAULT_AGENCIES",
    "DEFAULT_PROVIDER_DISCOVERY",
    "DEFAULT_PROVIDER_OFFICIAL",
    "FIXTURE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "BindingElevationError",
    "ChangeEdge",
    "ChangeRelation",
    "DiscoveryDocument",
    "DocumentNotFoundError",
    "ExplicitFailureError",
    "FederalRegisterChangeError",
    "FederalRegisterChangeProcessor",
    "FixtureSchemaError",
    "ResolutionStatus",
    "RetryFailureError",
    "RuleChangeAcquisition",
    "RuleChangeRecord",
    "RuleDocumentType",
    "SchemaFailureError",
    "SignatureFailureError",
    "UnofficialMasqueradeError",
    "assert_not_masquerading_as_official",
    "build_missing_discovery_fixture",
    "build_patent_rule_changes_fixture_recipe",
    "content_sha256",
    "default_fixture_dir",
    "federal_register_html_url",
    "is_binding_document_type",
    "load_json_fixture",
    "normalize_document_number",
    "stable_rule_identity",
    "write_default_fixtures",
]
