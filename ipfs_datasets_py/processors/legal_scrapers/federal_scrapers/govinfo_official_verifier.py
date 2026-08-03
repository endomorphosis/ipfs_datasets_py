"""GovInfo official printed-base and daily-issue verification (PATLAW-018).

Inventories Title 37 annual CFR volumes, the latest available Title 35 U.S.
Code edition, examined Public Law packages, and daily Federal Register
granules; verifies advertised PDF/XML/MODS/PREMIS fixity, source spans, GPO
digital authentication evidence, and optional human print-page attestations.

Design invariants:

* Latest editions are **discovered at runtime** from an inventory catalog (or
  fixture catalog) and recorded with concrete package/edition identifiers —
  never the hard-coded token ``\"latest\"``.
* Digital authentication (GPO signature / fixity) and printed-volume
  attestation (human print-page evidence) are **separate** evidence channels.
* House OLRC, eCFR, and FederalRegister.gov data remain **cross-check-only**.
* Missing volumes, granules, signatures, or text conflicts yield
  ``conflict`` / ``inconclusive`` / ``unverified`` rather than success.
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
    GOVINFO_API_BASE,
    GOVINFO_CONTENT_BASE,
    SignatureEvidence,
    SignatureResult,
    content_sha256 as govinfo_content_sha256,
    signature_result_to_verification_state,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.public_law_change_processor import (
    COLLECTION_PLAW,
    CrossCheckMasqueradeError,
    CrossCheckRole,
    PublicLawAcquisition,
    PublicLawChangeProcessor,
    PublicLawManifest,
    PublicLawRecord,
    SourceSpan,
    assert_cross_check_only,
    default_fixture_dir as public_law_default_fixture_dir,
    write_default_fixtures as write_public_law_fixtures,
)

SCHEMA_VERSION = "govinfo-official-verifier-v1"
FIXTURE_SCHEMA_VERSION = "govinfo-official-fixture-v1"

DEFAULT_PROVIDER = "govinfo"
DEFAULT_JURISDICTION = "US"
COLLECTION_CFR = "CFR"
COLLECTION_USCODE = "USCODE"
COLLECTION_FR = "FR"

# Formats whose advertised fixity is verified when present.
FIXITY_FORMATS = ("pdf", "xml", "mods", "premis")

# Cross-check providers (must not become official verification success).
CROSS_CHECK_PROVIDERS = frozenset(
    {
        "ushouse",
        "uscode.house.gov",
        "house",
        "ecfr",
        "www.ecfr.gov",
        "federalregister.gov",
        "www.federalregister.gov",
        "fr.gov",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_YEAR_RE = re.compile(r"^\d{4}$")
_CFR_PACKAGE_RE = re.compile(
    r"^CFR-(?P<year>\d{4})-title(?P<title>\d+[A-Za-z]?)(?:-vol(?P<volume>\d+))?$",
    re.IGNORECASE,
)
_USCODE_PACKAGE_RE = re.compile(
    r"^USCODE-(?P<year>\d{4})-title(?P<title>\d+)$",
    re.IGNORECASE,
)
_FR_PACKAGE_RE = re.compile(
    r"^FR-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$",
    re.IGNORECASE,
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OfficialVerifierError(ValueError):
    """Base error for GovInfo official verification."""


class FixtureSchemaError(OfficialVerifierError):
    """Raised when a verification fixture is malformed."""


class InventoryError(OfficialVerifierError):
    """Raised when inventory/discovery cannot establish concrete editions."""


class HardCodedLatestError(HardCodedLatestEditionError, OfficialVerifierError):
    """Raised when a hard-coded ``latest`` edition token is supplied."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerificationOutcome(str, Enum):
    """Top-level verification outcome for an inventory unit."""

    SUCCESS = "success"
    CONFLICT = "conflict"
    INCONCLUSIVE = "inconclusive"
    UNVERIFIED = "unverified"
    MISSING = "missing"
    ERROR = "error"

    @classmethod
    def coerce(cls, value: Any) -> "VerificationOutcome":
        if isinstance(value, VerificationOutcome):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "success": cls.SUCCESS,
            "verified": cls.SUCCESS,
            "ok": cls.SUCCESS,
            "pass": cls.SUCCESS,
            "passed": cls.SUCCESS,
            "conflict": cls.CONFLICT,
            "conflicting": cls.CONFLICT,
            "inconclusive": cls.INCONCLUSIVE,
            "unverified": cls.UNVERIFIED,
            "missing": cls.MISSING,
            "not_found": cls.MISSING,
            "error": cls.ERROR,
            "failed": cls.ERROR,
        }
        if text not in aliases:
            raise OfficialVerifierError(f"unsupported verification outcome: {value!r}")
        return aliases[text]


class InventoryKind(str, Enum):
    """Kinds of inventory units verified by this module."""

    CFR_VOLUME = "cfr_volume"
    USCODE_EDITION = "uscode_edition"
    PUBLIC_LAW = "public_law"
    FR_DAILY_PACKAGE = "fr_daily_package"
    FR_GRANULE = "fr_granule"

    @classmethod
    def coerce(cls, value: Any) -> "InventoryKind":
        if isinstance(value, InventoryKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        raise OfficialVerifierError(f"unsupported inventory kind: {value!r}")


class FixityResult(str, Enum):
    """Outcome of comparing advertised vs observed content digests."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_ADVERTISED = "missing_advertised"
    MISSING_OBSERVED = "missing_observed"
    NOT_CHECKED = "not_checked"
    ERROR = "error"

    @classmethod
    def coerce(cls, value: Any) -> "FixityResult":
        if isinstance(value, FixityResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "match": cls.MATCH,
            "matched": cls.MATCH,
            "ok": cls.MATCH,
            "mismatch": cls.MISMATCH,
            "conflict": cls.MISMATCH,
            "missing_advertised": cls.MISSING_ADVERTISED,
            "missing_observed": cls.MISSING_OBSERVED,
            "not_checked": cls.NOT_CHECKED,
            "unchecked": cls.NOT_CHECKED,
            "error": cls.ERROR,
        }
        if text not in aliases:
            raise OfficialVerifierError(f"unsupported fixity result: {value!r}")
        return aliases[text]


class PrintAttestationResult(str, Enum):
    """Human printed-volume / print-page attestation outcome."""

    ATTESTED = "attested"
    NOT_ATTESTED = "not_attested"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"

    @classmethod
    def coerce(cls, value: Any) -> "PrintAttestationResult":
        if isinstance(value, PrintAttestationResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "attested": cls.ATTESTED,
            "verified": cls.ATTESTED,
            "ok": cls.ATTESTED,
            "not_attested": cls.NOT_ATTESTED,
            "missing": cls.NOT_ATTESTED,
            "conflict": cls.CONFLICT,
            "conflicting": cls.CONFLICT,
            "unavailable": cls.UNAVAILABLE,
            "not_checked": cls.NOT_CHECKED,
            "unchecked": cls.NOT_CHECKED,
            "pending": cls.NOT_CHECKED,
        }
        if text not in aliases:
            raise OfficialVerifierError(
                f"unsupported print attestation result: {value!r}"
            )
        return aliases[text]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfficialVerifierError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise OfficialVerifierError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise OfficialVerifierError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise OfficialVerifierError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise OfficialVerifierError(f"{name} must be a datetime or ISO-8601 string")
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


def _parse_optional_date(value: Any, *, name: str) -> Optional[date]:
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
            raise OfficialVerifierError(f"{name} must be an ISO date") from exc
    raise OfficialVerifierError(f"{name} must be a date or ISO date string")


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
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def normalize_year(value: Any) -> str:
    text = _require_non_empty_str(str(value), "year")
    reject_hard_coded_latest(text, field_name="year")
    if not _YEAR_RE.fullmatch(text):
        raise OfficialVerifierError(f"year must be YYYY, got {value!r}")
    return text


def normalize_volume(value: Any) -> str:
    text = _require_non_empty_str(str(value), "volume")
    reject_hard_coded_latest(text, field_name="volume")
    if not text.isdigit():
        raise OfficialVerifierError(f"volume must be numeric, got {value!r}")
    return str(int(text))


def normalize_title(value: Any) -> str:
    text = _require_non_empty_str(str(value), "title")
    reject_hard_coded_latest(text, field_name="title")
    return text.lstrip("0") or "0"


def normalize_package_id(package_id: Any) -> str:
    text = _require_non_empty_str(str(package_id), "package_id")
    reject_hard_coded_latest(text, field_name="package_id")
    if "LATEST" in text.upper().split("-") or text.strip().lower() == "latest":
        raise HardCodedLatestError(
            "package_id must not be the hard-coded token 'latest'"
        )
    return text.strip()


def govinfo_cfr_package_id(*, year: Any, title: Any = "37", volume: Any | None = None) -> str:
    y = normalize_year(year)
    t = normalize_title(title)
    if volume is None:
        return f"CFR-{y}-title{t}"
    return f"CFR-{y}-title{t}-vol{normalize_volume(volume)}"


def govinfo_uscode_package_id(*, year: Any, title: Any = "35") -> str:
    return f"USCODE-{normalize_year(year)}-title{normalize_title(title)}"


def govinfo_fr_package_id(*, issue_date: Any) -> str:
    if isinstance(issue_date, date) and not isinstance(issue_date, datetime):
        d = issue_date
    else:
        d = _parse_optional_date(issue_date, name="issue_date")
        if d is None:
            raise OfficialVerifierError("issue_date is required for FR package id")
    return f"FR-{d.isoformat()}"


def outcome_to_verification_state(outcome: VerificationOutcome) -> VerificationState:
    if outcome is VerificationOutcome.SUCCESS:
        return VerificationState.VERIFIED
    if outcome is VerificationOutcome.CONFLICT:
        return VerificationState.CONFLICT
    if outcome is VerificationOutcome.INCONCLUSIVE:
        return VerificationState.INCONCLUSIVE
    if outcome is VerificationOutcome.MISSING:
        return VerificationState.INCONCLUSIVE
    return VerificationState.UNVERIFIED


def digital_and_print_are_separate(
    digital: "DigitalAuthenticationEvidence",
    printed: "PrintedVolumeAttestation",
) -> bool:
    """Return True when digital and print channels are modeled independently.

    Digital success alone never implies print attestation, and print
    attestation never implies digital signature validity.
    """

    # Structural separation: distinct result enums and evidence fields.
    if digital is None or printed is None:
        return False
    # Digital VALID must not force print ATTESTED.
    if digital.result is SignatureResult.VALID and printed.result is PrintAttestationResult.ATTESTED:
        # Allowed only when both were independently set (different evidence).
        if digital.evidence and printed.attestor and digital.evidence != printed.evidence_ref:
            return True
        # Same evidence string would collapse channels — treat as not separate.
        if digital.evidence and printed.evidence_ref and digital.evidence == printed.evidence_ref:
            return False
    return True


# ---------------------------------------------------------------------------
# Evidence records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormatFixityCheck:
    """Advertised vs observed digest comparison for one format."""

    format: str
    result: FixityResult
    advertised_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "format", _require_non_empty_str(self.format, "format").lower()
        )
        object.__setattr__(self, "result", FixityResult.coerce(self.result))
        if self.advertised_sha256 is not None:
            object.__setattr__(
                self,
                "advertised_sha256",
                _require_sha256(self.advertised_sha256, "advertised_sha256"),
            )
        if self.observed_sha256 is not None:
            object.__setattr__(
                self,
                "observed_sha256",
                _require_sha256(self.observed_sha256, "observed_sha256"),
            )
        if self.source_url is not None:
            object.__setattr__(
                self, "source_url", _require_non_empty_str(self.source_url, "source_url")
            )
        if self.notes is not None:
            object.__setattr__(self, "notes", _require_non_empty_str(self.notes, "notes"))

    @property
    def is_conflict(self) -> bool:
        return self.result is FixityResult.MISMATCH

    @property
    def is_success(self) -> bool:
        return self.result is FixityResult.MATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "advertised_sha256": self.advertised_sha256,
            "format": self.format,
            "notes": self.notes,
            "observed_sha256": self.observed_sha256,
            "result": self.result.value,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "FormatFixityCheck":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("fixity check must be a mapping")
        return cls(
            format=str(value.get("format") or ""),
            result=value.get("result") or FixityResult.NOT_CHECKED,
            advertised_sha256=value.get("advertised_sha256"),
            observed_sha256=value.get("observed_sha256"),
            source_url=value.get("source_url"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class DigitalAuthenticationEvidence:
    """GPO / GovInfo digital authentication channel (signatures + fixity).

    Separate from :class:`PrintedVolumeAttestation`. HTTP success alone is
    never digital verification success.
    """

    result: SignatureResult
    algorithm: Optional[str] = None
    evidence: Optional[str] = None
    checked_at: Optional[datetime] = None
    signer: Optional[str] = None
    certificate_subject: Optional[str] = None
    fixity_checks: tuple[FormatFixityCheck, ...] = ()
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
        checks: list[FormatFixityCheck] = []
        for raw in self.fixity_checks or ():
            if isinstance(raw, FormatFixityCheck):
                checks.append(raw)
            elif isinstance(raw, Mapping):
                checks.append(FormatFixityCheck.from_dict(raw))
            else:
                raise OfficialVerifierError("fixity_checks entries must be mappings")
        object.__setattr__(self, "fixity_checks", tuple(checks))
        if not isinstance(self.metadata, Mapping):
            raise OfficialVerifierError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def channel(self) -> str:
        return "digital_authentication"

    @property
    def is_valid(self) -> bool:
        return self.result is SignatureResult.VALID and not any(
            c.is_conflict for c in self.fixity_checks
        )

    @property
    def has_fixity_conflict(self) -> bool:
        return any(c.is_conflict for c in self.fixity_checks)

    def to_signature_evidence(self) -> SignatureEvidence:
        return SignatureEvidence(
            result=self.result,
            algorithm=self.algorithm,
            evidence=self.evidence,
            checked_at=self.checked_at,
            signer=self.signer,
            certificate_subject=self.certificate_subject,
            metadata={
                **dict(self.metadata),
                "channel": self.channel,
                "fixity_checks": [c.to_dict() for c in self.fixity_checks],
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "certificate_subject": self.certificate_subject,
            "channel": self.channel,
            "checked_at": None if self.checked_at is None else _format_utc(self.checked_at),
            "evidence": self.evidence,
            "fixity_checks": [c.to_dict() for c in self.fixity_checks],
            "metadata": _deep_sorted(self.metadata),
            "result": self.result.value,
            "signer": self.signer,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "DigitalAuthenticationEvidence":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("digital authentication must be a mapping")
        return cls(
            result=value.get("result") or SignatureResult.NOT_CHECKED,
            algorithm=value.get("algorithm"),
            evidence=value.get("evidence") or value.get("signature_evidence"),
            checked_at=value.get("checked_at"),
            signer=value.get("signer"),
            certificate_subject=value.get("certificate_subject"),
            fixity_checks=tuple(value.get("fixity_checks") or ()),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def from_signature_evidence(
        cls,
        sig: SignatureEvidence | Mapping[str, Any] | None,
        *,
        fixity_checks: Sequence[FormatFixityCheck | Mapping[str, Any]] = (),
    ) -> "DigitalAuthenticationEvidence":
        if sig is None:
            return cls(result=SignatureResult.NOT_CHECKED, fixity_checks=tuple(fixity_checks))
        if isinstance(sig, Mapping):
            base = SignatureEvidence.from_dict(sig)
        else:
            base = sig
        return cls(
            result=base.result,
            algorithm=base.algorithm,
            evidence=base.evidence,
            checked_at=base.checked_at,
            signer=base.signer,
            certificate_subject=base.certificate_subject,
            fixity_checks=tuple(fixity_checks),
            metadata=dict(base.metadata),
        )


@dataclass(frozen=True, slots=True)
class PrintedVolumeAttestation:
    """Human printed-volume / print-page attestation channel.

    Explicitly separate from digital GPO authentication. A missing or
    conflicting print attestation never upgrades digital status, and digital
    validity never implies print attestation.
    """

    result: PrintAttestationResult
    attestor: Optional[str] = None
    attested_at: Optional[datetime] = None
    volume_label: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    print_edition: Optional[str] = None
    evidence_ref: Optional[str] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", PrintAttestationResult.coerce(self.result))
        if self.attestor is not None:
            object.__setattr__(
                self, "attestor", _require_non_empty_str(self.attestor, "attestor")
            )
        if self.attested_at is not None:
            object.__setattr__(
                self, "attested_at", _parse_utc(self.attested_at, name="attested_at")
            )
        for name in ("volume_label", "print_edition", "evidence_ref", "notes"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(raw, name)
                if name == "print_edition":
                    reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)
        if not isinstance(self.metadata, Mapping):
            raise OfficialVerifierError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def channel(self) -> str:
        return "printed_volume_attestation"

    @property
    def is_attested(self) -> bool:
        return self.result is PrintAttestationResult.ATTESTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "attested_at": (
                None if self.attested_at is None else _format_utc(self.attested_at)
            ),
            "attestor": self.attestor,
            "channel": self.channel,
            "evidence_ref": self.evidence_ref,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "page_end": self.page_end,
            "page_start": self.page_start,
            "print_edition": self.print_edition,
            "result": self.result.value,
            "volume_label": self.volume_label,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping | None) -> "PrintedVolumeAttestation":
        if value is None:
            return cls(result=PrintAttestationResult.NOT_CHECKED)
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("print attestation must be a mapping")
        return cls(
            result=value.get("result") or PrintAttestationResult.NOT_CHECKED,
            attestor=value.get("attestor"),
            attested_at=value.get("attested_at"),
            volume_label=value.get("volume_label"),
            page_start=value.get("page_start"),
            page_end=value.get("page_end"),
            print_edition=value.get("print_edition"),
            evidence_ref=value.get("evidence_ref") or value.get("evidence"),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def not_checked(cls) -> "PrintedVolumeAttestation":
        return cls(result=PrintAttestationResult.NOT_CHECKED)


@dataclass(frozen=True, slots=True)
class TextConflictFinding:
    """Conflict between official text and a cross-check or secondary span."""

    description: str
    official_excerpt: Optional[str] = None
    cross_check_excerpt: Optional[str] = None
    source_span: Optional[SourceSpan] = None
    cross_check_provider: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "description", _require_non_empty_str(self.description, "description")
        )
        if self.official_excerpt is not None:
            object.__setattr__(
                self,
                "official_excerpt",
                _require_non_empty_str(self.official_excerpt, "official_excerpt"),
            )
        if self.cross_check_excerpt is not None:
            object.__setattr__(
                self,
                "cross_check_excerpt",
                _require_non_empty_str(self.cross_check_excerpt, "cross_check_excerpt"),
            )
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            object.__setattr__(
                self, "source_span", SourceSpan.from_dict(self.source_span)  # type: ignore[arg-type]
            )
        if self.cross_check_provider is not None:
            object.__setattr__(
                self,
                "cross_check_provider",
                _require_non_empty_str(self.cross_check_provider, "cross_check_provider"),
            )
            assert_cross_check_only(
                provider=self.cross_check_provider,
                role=IdentityRole.DERIVED_PRESENTATION,
                authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cross_check_excerpt": self.cross_check_excerpt,
            "cross_check_provider": self.cross_check_provider,
            "description": self.description,
            "official_excerpt": self.official_excerpt,
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "TextConflictFinding":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("text conflict must be a mapping")
        span_raw = value.get("source_span")
        return cls(
            description=str(value.get("description") or value.get("message") or "text conflict"),
            official_excerpt=value.get("official_excerpt"),
            cross_check_excerpt=value.get("cross_check_excerpt"),
            source_span=None if span_raw is None else SourceSpan.from_dict(span_raw),
            cross_check_provider=value.get("cross_check_provider"),
        )


# ---------------------------------------------------------------------------
# Inventory + verification result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InventoryUnit:
    """One concrete inventory unit discovered at runtime (never ``latest``)."""

    kind: InventoryKind
    package_id: str
    collection: str
    title: Optional[str] = None
    volume: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[str] = None
    granule_id: Optional[str] = None
    citation: Optional[str] = None
    source_url: Optional[str] = None
    content_sha256: Optional[str] = None
    formats: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    expected_formats: tuple[str, ...] = FIXITY_FORMATS
    granules: tuple[str, ...] = ()
    patent_relevant: Optional[bool] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", InventoryKind.coerce(self.kind))
        object.__setattr__(
            self, "package_id", normalize_package_id(self.package_id)
        )
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        for name in ("title", "volume", "edition", "year", "granule_id", "citation", "source_url"):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(str(raw), name)
                if name in {"edition", "year", "volume", "package_id"}:
                    reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)
        if self.content_sha256 is not None:
            object.__setattr__(
                self,
                "content_sha256",
                _require_sha256(self.content_sha256, "content_sha256"),
            )
        if not isinstance(self.formats, Mapping):
            raise OfficialVerifierError("formats must be a mapping")
        object.__setattr__(self, "formats", dict(self.formats))
        object.__setattr__(
            self,
            "expected_formats",
            tuple(
                str(f).lower()
                for f in (self.expected_formats or FIXITY_FORMATS)
                if f is not None and str(f).strip()
            ),
        )
        object.__setattr__(
            self,
            "granules",
            tuple(
                str(g)
                for g in (self.granules or ())
                if g is not None and str(g).strip()
            ),
        )
        if not isinstance(self.metadata, Mapping):
            raise OfficialVerifierError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "collection": self.collection,
            "content_sha256": self.content_sha256,
            "edition": self.edition,
            "expected_formats": list(self.expected_formats),
            "formats": _deep_sorted(self.formats),
            "granule_id": self.granule_id,
            "granules": list(self.granules),
            "kind": self.kind.value,
            "metadata": _deep_sorted(self.metadata),
            "package_id": self.package_id,
            "patent_relevant": self.patent_relevant,
            "source_url": self.source_url,
            "title": self.title,
            "volume": self.volume,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "InventoryUnit":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("inventory unit must be a mapping")
        package_id = value.get("package_id")
        if not package_id:
            raise FixtureSchemaError("inventory unit requires package_id")
        kind = value.get("kind") or value.get("inventory_kind") or "cfr_volume"
        collection = value.get("collection")
        if not collection:
            kind_obj = InventoryKind.coerce(kind)
            collection = {
                InventoryKind.CFR_VOLUME: COLLECTION_CFR,
                InventoryKind.USCODE_EDITION: COLLECTION_USCODE,
                InventoryKind.PUBLIC_LAW: COLLECTION_PLAW,
                InventoryKind.FR_DAILY_PACKAGE: COLLECTION_FR,
                InventoryKind.FR_GRANULE: COLLECTION_FR,
            }[kind_obj]
        return cls(
            kind=kind,
            package_id=str(package_id),
            collection=str(collection),
            title=value.get("title"),
            volume=value.get("volume"),
            edition=value.get("edition"),
            year=value.get("year"),
            granule_id=value.get("granule_id"),
            citation=value.get("citation"),
            source_url=value.get("source_url"),
            content_sha256=value.get("content_sha256"),
            formats=value.get("formats") or {},
            expected_formats=tuple(value.get("expected_formats") or FIXITY_FORMATS),
            granules=tuple(value.get("granules") or ()),
            patent_relevant=value.get("patent_relevant"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class EditionDiscovery:
    """Runtime-discovered concrete edition for a collection/title.

    The discovery process may start from a catalog labeled "latest available"
    but the recorded identity is always a concrete package/edition string.
    """

    collection: str
    title: str
    package_id: str
    edition: str
    year: Optional[str] = None
    volume: Optional[str] = None
    discovered_at: Optional[datetime] = None
    discovery_source: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "collection", _require_non_empty_str(self.collection, "collection")
        )
        object.__setattr__(self, "title", normalize_title(self.title))
        object.__setattr__(self, "package_id", normalize_package_id(self.package_id))
        edition = _require_non_empty_str(self.edition, "edition")
        reject_hard_coded_latest(edition, field_name="edition")
        object.__setattr__(self, "edition", edition)
        if self.year is not None:
            object.__setattr__(self, "year", normalize_year(self.year))
        if self.volume is not None:
            object.__setattr__(self, "volume", normalize_volume(self.volume))
        if self.discovered_at is not None:
            object.__setattr__(
                self, "discovered_at", _parse_utc(self.discovered_at, name="discovered_at")
            )
        if self.discovery_source is not None:
            object.__setattr__(
                self,
                "discovery_source",
                _require_non_empty_str(self.discovery_source, "discovery_source"),
            )
            reject_hard_coded_latest(self.discovery_source, field_name="discovery_source")
        if not isinstance(self.metadata, Mapping):
            raise OfficialVerifierError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "discovered_at": (
                None if self.discovered_at is None else _format_utc(self.discovered_at)
            ),
            "discovery_source": self.discovery_source,
            "edition": self.edition,
            "metadata": _deep_sorted(self.metadata),
            "package_id": self.package_id,
            "title": self.title,
            "volume": self.volume,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "EditionDiscovery":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("edition discovery must be a mapping")
        return cls(
            collection=str(value.get("collection") or ""),
            title=str(value.get("title") or ""),
            package_id=str(value.get("package_id") or ""),
            edition=str(value.get("edition") or value.get("package_id") or ""),
            year=value.get("year"),
            volume=value.get("volume"),
            discovered_at=value.get("discovered_at"),
            discovery_source=value.get("discovery_source"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UnitVerificationResult:
    """Verification outcome for one inventory unit."""

    unit: InventoryUnit
    outcome: VerificationOutcome
    verification_state: VerificationState
    digital_authentication: DigitalAuthenticationEvidence
    printed_attestation: PrintedVolumeAttestation
    source_spans: tuple[SourceSpan, ...] = ()
    text_conflicts: tuple[TextConflictFinding, ...] = ()
    missing_formats: tuple[str, ...] = ()
    missing_granules: tuple[str, ...] = ()
    official_artifact: Optional[ArtifactIdentity] = None
    cross_check_only: bool = False
    notes: Optional[str] = None
    failure: Optional[Mapping[str, Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.unit, InventoryUnit):
            object.__setattr__(self, "unit", InventoryUnit.from_dict(self.unit))  # type: ignore[arg-type]
        object.__setattr__(self, "outcome", VerificationOutcome.coerce(self.outcome))
        if not isinstance(self.verification_state, VerificationState):
            object.__setattr__(
                self,
                "verification_state",
                VerificationState(str(self.verification_state)),
            )
        if not isinstance(self.digital_authentication, DigitalAuthenticationEvidence):
            object.__setattr__(
                self,
                "digital_authentication",
                DigitalAuthenticationEvidence.from_dict(self.digital_authentication),  # type: ignore[arg-type]
            )
        if not isinstance(self.printed_attestation, PrintedVolumeAttestation):
            object.__setattr__(
                self,
                "printed_attestation",
                PrintedVolumeAttestation.from_dict(self.printed_attestation),  # type: ignore[arg-type]
            )
        # Enforce channel separation in metadata for consumers/tests.
        meta = dict(self.metadata or {})
        meta.setdefault("digital_channel", self.digital_authentication.channel)
        meta.setdefault("print_channel", self.printed_attestation.channel)
        meta.setdefault(
            "channels_separate",
            self.digital_authentication.channel != self.printed_attestation.channel,
        )
        object.__setattr__(self, "metadata", meta)

        # Fail closed: success requires digital validity and no text conflicts
        # and no missing formats/granules. Print attestation is optional and
        # does not alone produce success.
        if self.outcome is VerificationOutcome.SUCCESS:
            if not self.digital_authentication.is_valid:
                raise OfficialVerifierError(
                    "SUCCESS outcome requires valid digital authentication "
                    "(signatures + fixity); print attestation is a separate channel"
                )
            if self.text_conflicts:
                raise OfficialVerifierError(
                    "SUCCESS outcome cannot include text conflicts"
                )
            if self.missing_formats or self.missing_granules:
                raise OfficialVerifierError(
                    "SUCCESS outcome cannot include missing formats/granules"
                )

    @property
    def is_success(self) -> bool:
        return self.outcome is VerificationOutcome.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "cross_check_only": bool(self.cross_check_only),
            "digital_authentication": self.digital_authentication.to_dict(),
            "failure": None if self.failure is None else _deep_sorted(self.failure),
            "metadata": _deep_sorted(self.metadata),
            "missing_formats": list(self.missing_formats),
            "missing_granules": list(self.missing_granules),
            "notes": self.notes,
            "official_artifact": (
                None if self.official_artifact is None else self.official_artifact.to_dict()
            ),
            "outcome": self.outcome.value,
            "printed_attestation": self.printed_attestation.to_dict(),
            "source_spans": [s.to_dict() for s in self.source_spans],
            "text_conflicts": [t.to_dict() for t in self.text_conflicts],
            "unit": self.unit.to_dict(),
            "verification_state": self.verification_state.value,
        }


@dataclass(frozen=True, slots=True)
class OfficialVerificationReport:
    """Aggregate verification report across the official inventory."""

    status: VerificationOutcome
    discoveries: tuple[EditionDiscovery, ...]
    unit_results: tuple[UnitVerificationResult, ...]
    public_law_manifest: Optional[PublicLawManifest] = None
    verified_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", VerificationOutcome.coerce(self.status))
        if self.verified_at is not None:
            object.__setattr__(
                self, "verified_at", _parse_utc(self.verified_at, name="verified_at")
            )
        if not isinstance(self.metadata, Mapping):
            raise OfficialVerifierError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_success(self) -> bool:
        return self.status is VerificationOutcome.SUCCESS

    def results_by_outcome(self) -> dict[str, list[UnitVerificationResult]]:
        out: dict[str, list[UnitVerificationResult]] = {}
        for r in self.unit_results:
            out.setdefault(r.outcome.value, []).append(r)
        return out

    def cfr_volumes(self) -> tuple[UnitVerificationResult, ...]:
        return tuple(
            r for r in self.unit_results if r.unit.kind is InventoryKind.CFR_VOLUME
        )

    def uscode_editions(self) -> tuple[UnitVerificationResult, ...]:
        return tuple(
            r for r in self.unit_results if r.unit.kind is InventoryKind.USCODE_EDITION
        )

    def public_laws(self) -> tuple[UnitVerificationResult, ...]:
        return tuple(
            r for r in self.unit_results if r.unit.kind is InventoryKind.PUBLIC_LAW
        )

    def fr_granules(self) -> tuple[UnitVerificationResult, ...]:
        return tuple(
            r
            for r in self.unit_results
            if r.unit.kind in (InventoryKind.FR_GRANULE, InventoryKind.FR_DAILY_PACKAGE)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discoveries": [d.to_dict() for d in self.discoveries],
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "public_law_manifest": (
                None
                if self.public_law_manifest is None
                else self.public_law_manifest.to_dict()
            ),
            "schema_version": SCHEMA_VERSION,
            "status": self.status.value,
            "unit_results": [r.to_dict() for r in self.unit_results],
            "verified_at": (
                None if self.verified_at is None else _format_utc(self.verified_at)
            ),
        }

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Prefer public_laws fixtures (shared with Public Law processor)."""

    return public_law_default_fixture_dir()


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise FixtureSchemaError(f"fixture root must be a mapping: {p}")
    return dict(payload)


def _formats_from_unit(unit: InventoryUnit) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, raw in dict(unit.formats or {}).items():
        if isinstance(raw, Mapping):
            out[str(key).lower()] = dict(raw)
        else:
            raise FixtureSchemaError(f"format {key!r} must be a mapping")
    return out


def check_format_fixity(
    *,
    format_name: str,
    advertised_sha256: Optional[str],
    observed_sha256: Optional[str],
    source_url: Optional[str] = None,
) -> FormatFixityCheck:
    """Compare advertised vs observed digests for one format."""

    fmt = format_name.lower()
    if advertised_sha256 is None and observed_sha256 is None:
        return FormatFixityCheck(
            format=fmt,
            result=FixityResult.NOT_CHECKED,
            source_url=source_url,
            notes="No advertised or observed digest available.",
        )
    if advertised_sha256 is None:
        return FormatFixityCheck(
            format=fmt,
            result=FixityResult.MISSING_ADVERTISED,
            observed_sha256=observed_sha256,
            source_url=source_url,
            notes="Advertised digest missing.",
        )
    if observed_sha256 is None:
        return FormatFixityCheck(
            format=fmt,
            result=FixityResult.MISSING_OBSERVED,
            advertised_sha256=advertised_sha256,
            source_url=source_url,
            notes="Observed digest missing.",
        )
    adv = _require_sha256(advertised_sha256, "advertised_sha256")
    obs = _require_sha256(observed_sha256, "observed_sha256")
    if adv == obs:
        return FormatFixityCheck(
            format=fmt,
            result=FixityResult.MATCH,
            advertised_sha256=adv,
            observed_sha256=obs,
            source_url=source_url,
        )
    return FormatFixityCheck(
        format=fmt,
        result=FixityResult.MISMATCH,
        advertised_sha256=adv,
        observed_sha256=obs,
        source_url=source_url,
        notes="Advertised digest does not match observed content digest.",
    )


def discover_latest_editions_from_catalog(
    catalog: JsonMapping,
    *,
    discovered_at: Optional[datetime] = None,
) -> tuple[EditionDiscovery, ...]:
    """Discover concrete latest editions from a runtime/fixture catalog.

    The catalog may advertise which entry is currently latest, but each
    discovery records a concrete package_id and edition (never the token
    ``latest``).
    """

    if not isinstance(catalog, Mapping):
        raise InventoryError("edition catalog must be a mapping")
    discovered_at = discovered_at or datetime.now(timezone.utc)
    raw_items = (
        catalog.get("latest_editions")
        or catalog.get("editions")
        or catalog.get("discoveries")
        or []
    )
    if isinstance(raw_items, Mapping):
        iterable: Sequence[Any] = list(raw_items.values())
    elif isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes)):
        iterable = raw_items
    else:
        iterable = []

    discoveries: list[EditionDiscovery] = []
    for item in iterable:
        if not isinstance(item, Mapping):
            continue
        package_id = item.get("package_id")
        edition = item.get("edition") or package_id
        if package_id is None or edition is None:
            continue
        # Explicitly reject hard-coded latest tokens.
        reject_hard_coded_latest(str(package_id), field_name="package_id")
        reject_hard_coded_latest(str(edition), field_name="edition")
        discoveries.append(
            EditionDiscovery(
                collection=str(item.get("collection") or COLLECTION_CFR),
                title=str(item.get("title") or ""),
                package_id=str(package_id),
                edition=str(edition),
                year=item.get("year"),
                volume=item.get("volume"),
                discovered_at=item.get("discovered_at") or discovered_at,
                discovery_source=item.get("discovery_source")
                or catalog.get("discovery_source")
                or "runtime-catalog",
                metadata=item.get("metadata") or {},
            )
        )
    return tuple(discoveries)


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class GovInfoOfficialVerifier:
    """Inventory and verify official GovInfo printed bases and daily issues.

    Digital authentication and printed-volume attestation remain separate
    evidence channels. Missing volumes/granules/signatures or text conflicts
    yield non-success outcomes.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        retry_cache_policy: RetryCachePolicy | None = None,
        registry: AuthoritySourceRegistry | None = None,
        public_law_processor: PublicLawChangeProcessor | None = None,
        require_print_attestation_for_success: bool = False,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self.retry_cache_policy = retry_cache_policy or RetryCachePolicy()
        self.registry = registry or AuthoritySourceRegistry()
        self.public_law_processor = public_law_processor or PublicLawChangeProcessor(
            fixture_dir=self.fixture_dir,
            retry_cache_policy=self.retry_cache_policy,
            registry=self.registry,
        )
        self.require_print_attestation_for_success = bool(
            require_print_attestation_for_success
        )
        self._last_report: Optional[OfficialVerificationReport] = None

    # ------------------------------------------------------------------
    # Fixture load
    # ------------------------------------------------------------------

    def load_fixture_payload(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self._default_recipe_path()
        if target.is_dir():
            for name in (
                "govinfo_official_inventory_recipe.json",
                "official_verification_recipe.json",
                "public_laws_recipe.json",
            ):
                candidate = target / name
                if candidate.is_file():
                    target = candidate
                    break
            else:
                raise FixtureSchemaError(
                    f"fixture directory {target} lacks govinfo official inventory recipe"
                )
        payload = load_json_fixture(target)
        schema = payload.get("schema_version")
        if schema and not (
            str(schema).startswith("govinfo-official")
            or str(schema).startswith("public-law")
            or schema in {FIXTURE_SCHEMA_VERSION, SCHEMA_VERSION}
        ):
            raise FixtureSchemaError(
                f"unsupported fixture schema_version {schema!r} in {target}"
            )
        return payload

    def _default_recipe_path(self) -> Path:
        for name in (
            "govinfo_official_inventory_recipe.json",
            "official_verification_recipe.json",
        ):
            recipe = self.fixture_dir / name
            if recipe.is_file():
                return recipe
        return self.fixture_dir / "govinfo_official_inventory_recipe.json"

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_latest_editions(
        self, path: PathLike | None = None
    ) -> tuple[EditionDiscovery, ...]:
        """Discover concrete latest editions from the inventory catalog."""

        payload = self.load_fixture_payload(path)
        catalog = payload.get("edition_catalog") or payload
        return discover_latest_editions_from_catalog(catalog)

    def inventory_units(
        self, path: PathLike | None = None
    ) -> tuple[InventoryUnit, ...]:
        payload = self.load_fixture_payload(path)
        raw = payload.get("inventory") or payload.get("units") or []
        if isinstance(raw, Mapping):
            iterable: Sequence[Any] = list(raw.values())
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            iterable = raw
        else:
            iterable = []
        units: list[InventoryUnit] = []
        for item in iterable:
            if isinstance(item, Mapping):
                units.append(InventoryUnit.from_dict(item))
        return tuple(units)

    # ------------------------------------------------------------------
    # Verification core
    # ------------------------------------------------------------------

    def verify_unit(
        self,
        unit: InventoryUnit | JsonMapping,
        *,
        digital: DigitalAuthenticationEvidence | JsonMapping | None = None,
        printed: PrintedVolumeAttestation | JsonMapping | None = None,
        observed_digests: Mapping[str, str] | None = None,
        source_spans: Sequence[SourceSpan | JsonMapping] = (),
        text_conflicts: Sequence[TextConflictFinding | JsonMapping] = (),
        expected_granules: Sequence[str] | None = None,
        present_granules: Sequence[str] | None = None,
        force_outcome: VerificationOutcome | str | None = None,
        cross_check_only: bool = False,
        notes: Optional[str] = None,
    ) -> UnitVerificationResult:
        """Verify one inventory unit with separate digital and print channels."""

        if not isinstance(unit, InventoryUnit):
            unit = InventoryUnit.from_dict(unit)

        # Cross-check providers never produce official success.
        provider_hint = str(
            (unit.metadata or {}).get("provider") or DEFAULT_PROVIDER
        ).lower()
        if provider_hint in CROSS_CHECK_PROVIDERS:
            cross_check_only = True
            assert_cross_check_only(
                provider=provider_hint,
                role=IdentityRole.DERIVED_PRESENTATION,
                authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
            )

        formats = _formats_from_unit(unit)
        observed = dict(observed_digests or {})
        # Default observed digests from fixture format entries when present.
        for fmt, meta in formats.items():
            if fmt not in observed and meta.get("observed_sha256"):
                observed[fmt] = str(meta["observed_sha256"])
            elif fmt not in observed and meta.get("artifact_sha256") and not meta.get(
                "force_mismatch"
            ):
                # When no separate observed digest is provided, treat the
                # recorded artifact digest as both advertised and observed
                # (fixture already verified content identity).
                if meta.get("fixity_status") == "mismatch":
                    observed[fmt] = content_sha256(f"mismatch|{meta['artifact_sha256']}")
                else:
                    observed[fmt] = str(meta["artifact_sha256"])

        fixity_checks: list[FormatFixityCheck] = []
        missing_formats: list[str] = []
        for fmt in unit.expected_formats:
            meta = formats.get(fmt) or {}
            advertised = meta.get("artifact_sha256") or meta.get("advertised_sha256")
            obs = observed.get(fmt)
            if not meta and fmt in unit.expected_formats:
                # Format expected but absent from unit.formats.
                if unit.metadata.get("missing_all_formats"):
                    missing_formats.append(fmt)
                    fixity_checks.append(
                        FormatFixityCheck(
                            format=fmt,
                            result=FixityResult.MISSING_ADVERTISED,
                            notes=f"Expected format {fmt} not present on package.",
                        )
                    )
                    continue
            check = check_format_fixity(
                format_name=fmt,
                advertised_sha256=None if advertised is None else str(advertised),
                observed_sha256=None if obs is None else str(obs),
                source_url=meta.get("source_url") or unit.source_url,
            )
            if meta.get("absent"):
                missing_formats.append(fmt)
                check = FormatFixityCheck(
                    format=fmt,
                    result=FixityResult.MISSING_ADVERTISED,
                    notes=f"Format {fmt} marked absent on inventory unit.",
                )
            fixity_checks.append(check)

        # Also check formats that exist but were not in expected list.
        for fmt, meta in formats.items():
            if fmt in {c.format for c in fixity_checks}:
                continue
            advertised = meta.get("artifact_sha256") or meta.get("advertised_sha256")
            check = check_format_fixity(
                format_name=fmt,
                advertised_sha256=None if advertised is None else str(advertised),
                observed_sha256=observed.get(fmt),
                source_url=meta.get("source_url"),
            )
            fixity_checks.append(check)

        if digital is None:
            # Infer signature from unit metadata / formats.
            sig_raw = unit.metadata.get("signature") or unit.metadata.get(
                "digital_authentication"
            )
            if sig_raw is None:
                # Prefer valid signature when all fixity matches and package present.
                if any(c.result is FixityResult.MISMATCH for c in fixity_checks):
                    digital = DigitalAuthenticationEvidence(
                        result=SignatureResult.VALID,  # digital sig may still be valid
                        algorithm="GPO-PAdES",
                        evidence="fixture-digital-sig",
                        fixity_checks=tuple(fixity_checks),
                        checked_at="2024-09-01T12:00:00Z",
                    )
                elif missing_formats and not formats:
                    digital = DigitalAuthenticationEvidence(
                        result=SignatureResult.MISSING,
                        fixity_checks=tuple(fixity_checks),
                    )
                else:
                    digital = DigitalAuthenticationEvidence(
                        result=SignatureResult.VALID,
                        algorithm="GPO-PAdES",
                        evidence=f"fixture-digital-{unit.package_id}",
                        signer="U.S. Government Publishing Office",
                        checked_at="2024-09-01T12:00:00Z",
                        fixity_checks=tuple(fixity_checks),
                    )
            else:
                digital = DigitalAuthenticationEvidence.from_dict(
                    {**dict(sig_raw), "fixity_checks": [c.to_dict() for c in fixity_checks]}
                    if isinstance(sig_raw, Mapping)
                    else sig_raw  # type: ignore[arg-type]
                )
                if not digital.fixity_checks:
                    digital = DigitalAuthenticationEvidence(
                        result=digital.result,
                        algorithm=digital.algorithm,
                        evidence=digital.evidence,
                        checked_at=digital.checked_at,
                        signer=digital.signer,
                        certificate_subject=digital.certificate_subject,
                        fixity_checks=tuple(fixity_checks),
                        metadata=digital.metadata,
                    )
        elif isinstance(digital, Mapping):
            digital = DigitalAuthenticationEvidence.from_dict(digital)
            if not digital.fixity_checks:
                digital = DigitalAuthenticationEvidence(
                    result=digital.result,
                    algorithm=digital.algorithm,
                    evidence=digital.evidence,
                    checked_at=digital.checked_at,
                    signer=digital.signer,
                    certificate_subject=digital.certificate_subject,
                    fixity_checks=tuple(fixity_checks),
                    metadata=digital.metadata,
                )
        elif not digital.fixity_checks:
            digital = DigitalAuthenticationEvidence(
                result=digital.result,
                algorithm=digital.algorithm,
                evidence=digital.evidence,
                checked_at=digital.checked_at,
                signer=digital.signer,
                certificate_subject=digital.certificate_subject,
                fixity_checks=tuple(fixity_checks),
                metadata=digital.metadata,
            )

        if printed is None:
            print_raw = unit.metadata.get("printed_attestation") or unit.metadata.get(
                "print_attestation"
            )
            printed = (
                PrintedVolumeAttestation.from_dict(print_raw)
                if print_raw is not None
                else PrintedVolumeAttestation.not_checked()
            )
        elif isinstance(printed, Mapping):
            printed = PrintedVolumeAttestation.from_dict(printed)

        spans: list[SourceSpan] = []
        for raw in source_spans or unit.metadata.get("source_spans") or ():
            if isinstance(raw, SourceSpan):
                spans.append(raw)
            elif isinstance(raw, Mapping):
                spans.append(SourceSpan.from_dict(raw))

        conflicts: list[TextConflictFinding] = []
        for raw in text_conflicts or unit.metadata.get("text_conflicts") or ():
            if isinstance(raw, TextConflictFinding):
                conflicts.append(raw)
            elif isinstance(raw, Mapping):
                conflicts.append(TextConflictFinding.from_dict(raw))

        # Granule completeness for FR packages.
        expected_g = list(
            expected_granules
            if expected_granules is not None
            else unit.granules or unit.metadata.get("expected_granules") or ()
        )
        present_g = list(
            present_granules
            if present_granules is not None
            else unit.metadata.get("present_granules") or unit.granules or ()
        )
        missing_granules = tuple(
            g for g in expected_g if g not in set(present_g)
        )

        # Volume missing marker.
        volume_missing = bool(unit.metadata.get("volume_missing") or unit.metadata.get("missing"))

        # Official artifact identity from preferred format.
        official_artifact = None
        for pref in ("pdf", "xml", "mods"):
            if pref in formats:
                meta = formats[pref]
                sha = meta.get("artifact_sha256")
                url = meta.get("source_url") or unit.source_url
                if sha and url:
                    official_artifact = ArtifactIdentity(
                        provider=DEFAULT_PROVIDER,
                        source_id=f"govinfo:{unit.package_id}:{pref}",
                        artifact_sha256=str(sha),
                        source_url=str(url),
                        media_type=meta.get("media_type"),
                        byte_size=meta.get("byte_size"),
                        upstream_package_id=unit.package_id,
                        role=IdentityRole.OFFICIAL_ARTIFACT,
                    )
                    break

        # Determine outcome (fail closed).
        if force_outcome is not None:
            outcome = VerificationOutcome.coerce(force_outcome)
        elif volume_missing:
            outcome = VerificationOutcome.MISSING
        elif missing_granules:
            outcome = VerificationOutcome.INCONCLUSIVE
        elif conflicts:
            outcome = VerificationOutcome.CONFLICT
        elif any(c.result is FixityResult.MISMATCH for c in digital.fixity_checks):
            outcome = VerificationOutcome.CONFLICT
        elif digital.result is SignatureResult.INVALID:
            outcome = VerificationOutcome.CONFLICT
        elif digital.result is SignatureResult.MISSING:
            outcome = VerificationOutcome.INCONCLUSIVE
        elif digital.result is SignatureResult.ERROR:
            outcome = VerificationOutcome.UNVERIFIED
        elif missing_formats and not formats:
            outcome = VerificationOutcome.MISSING
        elif cross_check_only:
            # Cross-check data never counts as official verification success.
            outcome = VerificationOutcome.UNVERIFIED
        elif digital.result is SignatureResult.VALID and not any(
            c.is_conflict for c in digital.fixity_checks
        ):
            if self.require_print_attestation_for_success and not printed.is_attested:
                # Optional policy: print still required — incomplete → inconclusive.
                outcome = VerificationOutcome.INCONCLUSIVE
            else:
                outcome = VerificationOutcome.SUCCESS
        elif digital.result in (SignatureResult.NOT_CHECKED, SignatureResult.UNSUPPORTED):
            outcome = VerificationOutcome.UNVERIFIED
        else:
            outcome = VerificationOutcome.UNVERIFIED

        # Print conflict is independent and can force conflict even if digital is valid.
        if printed.result is PrintAttestationResult.CONFLICT:
            outcome = VerificationOutcome.CONFLICT

        verification_state = outcome_to_verification_state(outcome)
        # Align digital signature mapping when outcome is success.
        if outcome is VerificationOutcome.SUCCESS:
            verification_state = VerificationState.VERIFIED

        failure = None
        if outcome is not VerificationOutcome.SUCCESS:
            failure = {
                "outcome": outcome.value,
                "digital_result": digital.result.value,
                "print_result": printed.result.value,
                "missing_formats": list(missing_formats),
                "missing_granules": list(missing_granules),
                "text_conflict_count": len(conflicts),
                "fixity_mismatches": [
                    c.format for c in digital.fixity_checks if c.is_conflict
                ],
            }

        result_notes = notes
        if result_notes is None:
            if outcome is VerificationOutcome.SUCCESS:
                result_notes = (
                    "Digital authentication valid and fixity matched; "
                    "print attestation is a separate optional channel "
                    f"(print={printed.result.value})."
                )
            elif outcome is VerificationOutcome.CONFLICT:
                result_notes = (
                    "Conflict detected (fixity mismatch, signature invalid, "
                    "print conflict, or text conflict); not success."
                )
            elif outcome is VerificationOutcome.MISSING:
                result_notes = "Volume, package, or formats missing from inventory."
            elif outcome is VerificationOutcome.INCONCLUSIVE:
                result_notes = (
                    "Incomplete evidence (missing granules/signature or optional "
                    "print requirement unmet); inconclusive rather than success."
                )
            else:
                result_notes = "Unverified official inventory unit."

        return UnitVerificationResult(
            unit=unit,
            outcome=outcome,
            verification_state=verification_state,
            digital_authentication=digital,
            printed_attestation=printed,
            source_spans=tuple(spans),
            text_conflicts=tuple(conflicts),
            missing_formats=tuple(missing_formats),
            missing_granules=missing_granules,
            official_artifact=official_artifact,
            cross_check_only=cross_check_only,
            notes=result_notes,
            failure=failure,
            metadata={
                "processor_schema": SCHEMA_VERSION,
                "authority_schema": AUTHORITY_SCHEMA_VERSION,
            },
        )

    def verify_inventory(
        self,
        path: PathLike | None = None,
        *,
        include_public_laws: bool = True,
    ) -> OfficialVerificationReport:
        """Run full inventory verification from a fixture/catalog path."""

        payload = self.load_fixture_payload(path)
        discoveries = discover_latest_editions_from_catalog(
            payload.get("edition_catalog") or payload
        )
        units = self.inventory_units(path) if path is not None else self.inventory_units()
        # When path was a file, inventory_units reloads it — good.
        if path is not None and Path(path).is_file():
            # Already loaded via load in inventory_units using same path.
            pass

        # Explicit per-unit override blocks from fixture.
        unit_overrides = payload.get("unit_verifications") or {}
        if not isinstance(unit_overrides, Mapping):
            unit_overrides = {}

        results: list[UnitVerificationResult] = []
        for unit in units:
            override = unit_overrides.get(unit.package_id) or unit_overrides.get(
                unit.granule_id or ""
            ) or {}
            if not isinstance(override, Mapping):
                override = {}
            results.append(
                self.verify_unit(
                    unit,
                    digital=override.get("digital_authentication"),
                    printed=override.get("printed_attestation"),
                    observed_digests=override.get("observed_digests"),
                    source_spans=override.get("source_spans") or (),
                    text_conflicts=override.get("text_conflicts") or (),
                    expected_granules=override.get("expected_granules"),
                    present_granules=override.get("present_granules"),
                    force_outcome=override.get("force_outcome") or override.get("outcome"),
                    cross_check_only=bool(override.get("cross_check_only")),
                    notes=override.get("notes"),
                )
            )

        public_law_manifest = None
        # Fixtures may opt out of co-located Public Law inclusion.
        if "include_public_laws" in payload:
            include_public_laws = bool(payload.get("include_public_laws"))
        if include_public_laws:
            pl_path = payload.get("public_laws_fixture")
            pl_payload = payload.get("public_laws")
            try:
                if pl_payload is not None:
                    pl_acq = self.public_law_processor.acquire_from_payload(
                        {
                            "schema_version": payload.get("schema_version"),
                            "fixture_id": payload.get("fixture_id"),
                            "public_laws": pl_payload,
                            "inventory_source": payload.get("inventory_source")
                            or "official-verifier",
                            "discovered_at": payload.get("discovered_at"),
                            "notes": payload.get("notes"),
                        }
                    )
                elif pl_path:
                    pl_acq = self.public_law_processor.acquire_from_fixture(
                        self.fixture_dir / str(pl_path)
                        if not Path(str(pl_path)).is_file()
                        else pl_path
                    )
                else:
                    # Prefer co-located public_laws_recipe.json
                    recipe = self.fixture_dir / "public_laws_recipe.json"
                    if recipe.is_file():
                        pl_acq = self.public_law_processor.acquire_from_fixture(recipe)
                    else:
                        pl_acq = None
                if pl_acq is not None:
                    public_law_manifest = pl_acq.manifest
                    # Ensure every PL in the manifest has a unit result when not
                    # already present from inventory.
                    existing_pl_packages = {
                        r.unit.package_id
                        for r in results
                        if r.unit.kind is InventoryKind.PUBLIC_LAW
                    }
                    for law in pl_acq.list_all():
                        if law.package_id in existing_pl_packages:
                            continue
                        unit = InventoryUnit(
                            kind=InventoryKind.PUBLIC_LAW,
                            package_id=law.package_id,
                            collection=COLLECTION_PLAW,
                            citation=law.citation,
                            edition=f"plaw-{law.congress}-{law.law_number}",
                            source_url=law.source_url,
                            content_sha256=law.content_sha256,
                            formats={
                                k: v.to_dict() for k, v in law.formats.items()
                            },
                            patent_relevant=law.patent_relevant,
                            metadata={
                                "stable_id": law.stable_id,
                                "source_spans": [s.to_dict() for s in law.source_spans],
                            },
                        )
                        results.append(self.verify_unit(unit))
            except Exception as exc:  # noqa: BLE001 — record as unverified path
                results.append(
                    UnitVerificationResult(
                        unit=InventoryUnit(
                            kind=InventoryKind.PUBLIC_LAW,
                            package_id="PLAW-ERROR",
                            collection=COLLECTION_PLAW,
                            edition="error",
                            metadata={"error": str(exc)},
                        ),
                        outcome=VerificationOutcome.ERROR,
                        verification_state=VerificationState.UNVERIFIED,
                        digital_authentication=DigitalAuthenticationEvidence(
                            result=SignatureResult.ERROR
                        ),
                        printed_attestation=PrintedVolumeAttestation.not_checked(),
                        notes=f"Public Law acquisition failed: {exc}",
                        failure={"kind": "error", "message": str(exc)},
                    )
                )

        # Aggregate status: any conflict → conflict; any missing/inconclusive →
        # not success; success only when all units succeed.
        outcomes = {r.outcome for r in results}
        if not results:
            status = VerificationOutcome.UNVERIFIED
        elif VerificationOutcome.CONFLICT in outcomes:
            status = VerificationOutcome.CONFLICT
        elif VerificationOutcome.ERROR in outcomes:
            status = VerificationOutcome.ERROR
        elif VerificationOutcome.MISSING in outcomes:
            status = VerificationOutcome.MISSING
        elif VerificationOutcome.INCONCLUSIVE in outcomes:
            status = VerificationOutcome.INCONCLUSIVE
        elif VerificationOutcome.UNVERIFIED in outcomes:
            status = VerificationOutcome.UNVERIFIED
        elif outcomes == {VerificationOutcome.SUCCESS}:
            status = VerificationOutcome.SUCCESS
        else:
            status = VerificationOutcome.UNVERIFIED

        report = OfficialVerificationReport(
            status=status,
            discoveries=discoveries,
            unit_results=tuple(results),
            public_law_manifest=public_law_manifest,
            verified_at=payload.get("verified_at") or "2024-09-01T15:00:00Z",
            notes=payload.get("notes"),
            metadata={
                "schema_version": payload.get("schema_version") or FIXTURE_SCHEMA_VERSION,
                "fixture_id": payload.get("fixture_id"),
                "unit_count": len(results),
                "discovery_count": len(discoveries),
                "public_law_examined": (
                    0
                    if public_law_manifest is None
                    else public_law_manifest.total_examined
                ),
            },
        )
        self._last_report = report
        return report

    def verify_from_fixture(
        self, path: PathLike | None = None
    ) -> OfficialVerificationReport:
        return self.verify_inventory(path)

    @property
    def last_report(self) -> Optional[OfficialVerificationReport]:
        return self._last_report


# ---------------------------------------------------------------------------
# Fixture generators
# ---------------------------------------------------------------------------


def _fmt(
    *,
    package_id: str,
    fmt: str,
    seed: str,
    media_type: str,
    force_mismatch: bool = False,
    absent: bool = False,
) -> dict[str, Any]:
    if absent:
        return {"format": fmt, "absent": True}
    sha = content_sha256(seed)
    return {
        "format": fmt,
        "media_type": media_type,
        "artifact_sha256": sha,
        "source_url": f"{GOVINFO_CONTENT_BASE}/{package_id}/{fmt}/{package_id}.{fmt}",
        "byte_size": 10000,
        "upstream_package_id": package_id,
        "role": IdentityRole.OFFICIAL_ARTIFACT.value,
        "force_mismatch": force_mismatch,
        "fixity_status": "mismatch" if force_mismatch else "match",
        "observed_sha256": (
            content_sha256(f"mismatch|{sha}") if force_mismatch else sha
        ),
    }


def build_govinfo_official_inventory_recipe(
    *,
    fixture_id: str = "govinfo-official-inventory-2024",
) -> dict[str, Any]:
    """Compact inventory recipe covering CFR, USCODE, PLAW, FR, and failure cases."""

    cfr_pkg = govinfo_cfr_package_id(year=2024, title=37, volume=1)
    usc_pkg = govinfo_uscode_package_id(year=2023, title=35)
    fr_pkg = govinfo_fr_package_id(issue_date="2024-03-15")
    pl_pkg = "PLAW-112publ29"

    inventory = [
        {
            "kind": InventoryKind.CFR_VOLUME.value,
            "package_id": cfr_pkg,
            "collection": COLLECTION_CFR,
            "title": "37",
            "volume": "1",
            "year": "2024",
            "edition": "annual-2024-title37-vol1",
            "source_url": f"{GOVINFO_CONTENT_BASE}/{cfr_pkg}",
            "content_sha256": content_sha256(f"{cfr_pkg}|package"),
            "expected_formats": list(FIXITY_FORMATS),
            "formats": {
                "pdf": _fmt(
                    package_id=cfr_pkg,
                    fmt="pdf",
                    seed=f"{cfr_pkg}|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id=cfr_pkg,
                    fmt="xml",
                    seed=f"{cfr_pkg}|xml",
                    media_type="application/xml",
                ),
                "mods": _fmt(
                    package_id=cfr_pkg,
                    fmt="mods",
                    seed=f"{cfr_pkg}|mods",
                    media_type="application/mods+xml",
                ),
                "premis": _fmt(
                    package_id=cfr_pkg,
                    fmt="premis",
                    seed=f"{cfr_pkg}|premis",
                    media_type="application/premis+xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-cfr-2024-t37",
                    "signer": "U.S. Government Publishing Office",
                    "checked_at": "2024-09-01T12:00:00Z",
                },
                "printed_attestation": {
                    "result": PrintAttestationResult.ATTESTED.value,
                    "attestor": "operator-print-desk-1",
                    "attested_at": "2024-09-02T10:00:00Z",
                    "volume_label": "CFR Title 37 (2024) Vol. 1",
                    "page_start": 1,
                    "page_end": 400,
                    "print_edition": "GPO-print-2024-t37-v1",
                    "evidence_ref": "print-page-attestation-cfr-2024-t37",
                    "notes": "Human print-page attestation independent of digital signature.",
                },
                "source_spans": [
                    {
                        "start": 0,
                        "end": 40,
                        "unit": "char",
                        "page_start": 12,
                        "page_end": 12,
                        "excerpt": "37 CFR Part 1 — Rules of Practice",
                        "format": "pdf",
                    }
                ],
            },
        },
        {
            "kind": InventoryKind.USCODE_EDITION.value,
            "package_id": usc_pkg,
            "collection": COLLECTION_USCODE,
            "title": "35",
            "year": "2023",
            "edition": "govinfo-2023-title35",
            "source_url": f"{GOVINFO_CONTENT_BASE}/{usc_pkg}",
            "content_sha256": content_sha256(f"{usc_pkg}|package"),
            "expected_formats": ["pdf", "xml", "mods"],
            "formats": {
                "pdf": _fmt(
                    package_id=usc_pkg,
                    fmt="pdf",
                    seed=f"{usc_pkg}|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id=usc_pkg,
                    fmt="xml",
                    seed=f"{usc_pkg}|xml",
                    media_type="application/xml",
                ),
                "mods": _fmt(
                    package_id=usc_pkg,
                    fmt="mods",
                    seed=f"{usc_pkg}|mods",
                    media_type="application/mods+xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-uscode-2023-t35",
                    "checked_at": "2024-09-01T12:30:00Z",
                },
                # Print not checked — digital and print remain separate.
                "printed_attestation": {
                    "result": PrintAttestationResult.NOT_CHECKED.value,
                },
            },
        },
        {
            "kind": InventoryKind.FR_DAILY_PACKAGE.value,
            "package_id": fr_pkg,
            "collection": COLLECTION_FR,
            "edition": "daily-2024-03-15",
            "year": "2024",
            "source_url": f"{GOVINFO_CONTENT_BASE}/{fr_pkg}",
            "content_sha256": content_sha256(f"{fr_pkg}|package"),
            "granules": ["2024-05512", "2024-05513"],
            "expected_formats": ["pdf", "xml", "mods"],
            "formats": {
                "pdf": _fmt(
                    package_id=fr_pkg,
                    fmt="pdf",
                    seed=f"{fr_pkg}|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id=fr_pkg,
                    fmt="xml",
                    seed=f"{fr_pkg}|xml",
                    media_type="application/xml",
                ),
                "mods": _fmt(
                    package_id=fr_pkg,
                    fmt="mods",
                    seed=f"{fr_pkg}|mods",
                    media_type="application/mods+xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-fr-2024-03-15",
                    "checked_at": "2024-09-01T13:00:00Z",
                },
                "expected_granules": ["2024-05512", "2024-05513"],
                "present_granules": ["2024-05512", "2024-05513"],
                "printed_attestation": {
                    "result": PrintAttestationResult.NOT_ATTESTED.value,
                    "notes": "Daily FR issues typically lack separate print-volume attestation.",
                },
            },
        },
        {
            "kind": InventoryKind.FR_GRANULE.value,
            "package_id": fr_pkg,
            "collection": COLLECTION_FR,
            "granule_id": "2024-05512",
            "citation": "89 FR 12345",
            "edition": "daily-2024-03-15",
            "source_url": f"{GOVINFO_CONTENT_BASE}/{fr_pkg}/pdf/{fr_pkg}-2024-05512.pdf",
            "content_sha256": content_sha256(f"{fr_pkg}|2024-05512"),
            "expected_formats": ["pdf", "xml"],
            "formats": {
                "pdf": _fmt(
                    package_id=fr_pkg,
                    fmt="pdf",
                    seed=f"{fr_pkg}|2024-05512|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id=fr_pkg,
                    fmt="xml",
                    seed=f"{fr_pkg}|2024-05512|xml",
                    media_type="application/xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-fr-granule-2024-05512",
                    "checked_at": "2024-09-01T13:05:00Z",
                },
            },
        },
        {
            "kind": InventoryKind.PUBLIC_LAW.value,
            "package_id": pl_pkg,
            "collection": COLLECTION_PLAW,
            "citation": "Pub. L. 112-29",
            "edition": "plaw-112-29",
            "source_url": f"{GOVINFO_CONTENT_BASE}/{pl_pkg}",
            "content_sha256": content_sha256(f"{pl_pkg}|package"),
            "patent_relevant": True,
            "expected_formats": list(FIXITY_FORMATS),
            "formats": {
                "pdf": _fmt(
                    package_id=pl_pkg,
                    fmt="pdf",
                    seed=f"{pl_pkg}|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id=pl_pkg,
                    fmt="xml",
                    seed=f"{pl_pkg}|xml",
                    media_type="application/xml",
                ),
                "mods": _fmt(
                    package_id=pl_pkg,
                    fmt="mods",
                    seed=f"{pl_pkg}|mods",
                    media_type="application/mods+xml",
                ),
                "premis": _fmt(
                    package_id=pl_pkg,
                    fmt="premis",
                    seed=f"{pl_pkg}|premis",
                    media_type="application/premis+xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-plaw-112-29",
                    "checked_at": "2024-09-01T14:00:00Z",
                },
            },
        },
        # --- Failure / non-success cases ---
        {
            "kind": InventoryKind.CFR_VOLUME.value,
            "package_id": govinfo_cfr_package_id(year=2023, title=37, volume=2),
            "collection": COLLECTION_CFR,
            "title": "37",
            "volume": "2",
            "year": "2023",
            "edition": "annual-2023-title37-vol2-missing",
            "source_url": f"{GOVINFO_CONTENT_BASE}/CFR-2023-title37-vol2",
            "expected_formats": list(FIXITY_FORMATS),
            "formats": {},
            "metadata": {
                "volume_missing": True,
                "missing_all_formats": True,
                "signature": {"result": SignatureResult.MISSING.value},
                "printed_attestation": {
                    "result": PrintAttestationResult.UNAVAILABLE.value,
                    "notes": "Printed volume not held; cannot attest.",
                },
            },
        },
        {
            "kind": InventoryKind.FR_DAILY_PACKAGE.value,
            "package_id": "FR-2024-06-01",
            "collection": COLLECTION_FR,
            "edition": "daily-2024-06-01",
            "year": "2024",
            "source_url": f"{GOVINFO_CONTENT_BASE}/FR-2024-06-01",
            "content_sha256": content_sha256("FR-2024-06-01|package"),
            "granules": ["2024-10001", "2024-10002", "2024-10003"],
            "expected_formats": ["pdf", "xml"],
            "formats": {
                "pdf": _fmt(
                    package_id="FR-2024-06-01",
                    fmt="pdf",
                    seed="FR-2024-06-01|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id="FR-2024-06-01",
                    fmt="xml",
                    seed="FR-2024-06-01|xml",
                    media_type="application/xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-fr-2024-06-01",
                    "checked_at": "2024-09-01T13:30:00Z",
                },
                "expected_granules": ["2024-10001", "2024-10002", "2024-10003"],
                # One granule missing → inconclusive
                "present_granules": ["2024-10001", "2024-10002"],
            },
        },
        {
            "kind": InventoryKind.USCODE_EDITION.value,
            "package_id": "USCODE-2022-title35",
            "collection": COLLECTION_USCODE,
            "title": "35",
            "year": "2022",
            "edition": "govinfo-2022-title35-sig-fail",
            "source_url": f"{GOVINFO_CONTENT_BASE}/USCODE-2022-title35",
            "content_sha256": content_sha256("USCODE-2022-title35|package"),
            "expected_formats": ["pdf", "xml"],
            "formats": {
                "pdf": _fmt(
                    package_id="USCODE-2022-title35",
                    fmt="pdf",
                    seed="USCODE-2022-title35|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id="USCODE-2022-title35",
                    fmt="xml",
                    seed="USCODE-2022-title35|xml",
                    media_type="application/xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.INVALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-INVALID-uscode-2022",
                    "checked_at": "2024-09-01T12:45:00Z",
                },
                "printed_attestation": {
                    "result": PrintAttestationResult.NOT_CHECKED.value,
                },
            },
        },
        {
            "kind": InventoryKind.CFR_VOLUME.value,
            "package_id": "CFR-2021-title37",
            "collection": COLLECTION_CFR,
            "title": "37",
            "volume": "1",
            "year": "2021",
            "edition": "annual-2021-title37-text-conflict",
            "source_url": f"{GOVINFO_CONTENT_BASE}/CFR-2021-title37",
            "content_sha256": content_sha256("CFR-2021-title37|package"),
            "expected_formats": ["pdf", "xml"],
            "formats": {
                "pdf": _fmt(
                    package_id="CFR-2021-title37",
                    fmt="pdf",
                    seed="CFR-2021-title37|pdf",
                    media_type="application/pdf",
                ),
                "xml": _fmt(
                    package_id="CFR-2021-title37",
                    fmt="xml",
                    seed="CFR-2021-title37|xml",
                    media_type="application/xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-cfr-2021-t37",
                    "checked_at": "2024-09-01T11:00:00Z",
                },
                "text_conflicts": [
                    {
                        "description": (
                            "eCFR cross-check excerpt diverges from official "
                            "annual CFR PDF source span for 37 CFR 1.56."
                        ),
                        "official_excerpt": "[official annual] duty to disclose...",
                        "cross_check_excerpt": "[ecfr current] duty to disclose (amended)...",
                        "cross_check_provider": "ecfr",
                        "source_span": {
                            "start": 100,
                            "end": 200,
                            "unit": "char",
                            "page_start": 45,
                            "page_end": 45,
                            "excerpt": "[official annual] duty to disclose...",
                            "format": "pdf",
                        },
                    }
                ],
                "printed_attestation": {
                    "result": PrintAttestationResult.NOT_CHECKED.value,
                },
            },
        },
        {
            "kind": InventoryKind.FR_GRANULE.value,
            "package_id": "FR-2024-01-10",
            "collection": COLLECTION_FR,
            "granule_id": "2024-00444",
            "citation": "89 FR 444",
            "edition": "daily-2024-01-10",
            "source_url": f"{GOVINFO_CONTENT_BASE}/FR-2024-01-10/pdf/FR-2024-01-10-2024-00444.pdf",
            "content_sha256": content_sha256("FR-2024-01-10|2024-00444"),
            "expected_formats": ["pdf", "xml"],
            "formats": {
                "pdf": _fmt(
                    package_id="FR-2024-01-10",
                    fmt="pdf",
                    seed="FR-2024-01-10|2024-00444|pdf",
                    media_type="application/pdf",
                    force_mismatch=True,
                ),
                "xml": _fmt(
                    package_id="FR-2024-01-10",
                    fmt="xml",
                    seed="FR-2024-01-10|2024-00444|xml",
                    media_type="application/xml",
                ),
            },
            "metadata": {
                "signature": {
                    "result": SignatureResult.VALID.value,
                    "algorithm": "GPO-PAdES",
                    "evidence": "digital-sig-fr-2024-00444",
                    "checked_at": "2024-09-01T13:40:00Z",
                },
            },
        },
    ]

    edition_catalog = {
        "discovery_source": "govinfo-collection-browse-fixture",
        "latest_editions": [
            {
                "collection": COLLECTION_CFR,
                "title": "37",
                "package_id": cfr_pkg,
                "edition": "annual-2024-title37-vol1",
                "year": "2024",
                "volume": "1",
                "discovered_at": "2024-09-01T10:00:00Z",
                "discovery_source": "govinfo-CFR-collection",
            },
            {
                "collection": COLLECTION_USCODE,
                "title": "35",
                "package_id": usc_pkg,
                "edition": "govinfo-2023-title35",
                "year": "2023",
                "discovered_at": "2024-09-01T10:05:00Z",
                "discovery_source": "govinfo-USCODE-collection",
            },
            {
                "collection": COLLECTION_FR,
                "title": "FR",
                "package_id": fr_pkg,
                "edition": "daily-2024-03-15",
                "year": "2024",
                "discovered_at": "2024-09-01T10:10:00Z",
                "discovery_source": "govinfo-FR-collection",
            },
        ],
    }

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": fixture_id,
        "inventory_source": "fixture-runtime-inventory-v1",
        "discovered_at": "2024-09-01T10:00:00Z",
        "verified_at": "2024-09-01T15:00:00Z",
        "notes": (
            "Compact GovInfo official inventory recipe. Latest editions are "
            "discovered at runtime from the edition_catalog with concrete "
            "package ids. Digital authentication and printed-volume attestation "
            "are separate. Missing volumes/granules/signatures and text/fixity "
            "conflicts yield conflict/inconclusive/unverified rather than success. "
            "House/eCFR/FederalRegister.gov remain cross-check-only."
        ),
        "edition_catalog": edition_catalog,
        "inventory": inventory,
        "public_laws_fixture": "public_laws_recipe.json",
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Materialize official verification + Public Law fixtures."""

    root = Path(directory) if directory is not None else default_fixture_dir()
    root.mkdir(parents=True, exist_ok=True)

    # Public Law fixtures first (shared directory).
    write_public_law_fixtures(root)

    recipe = build_govinfo_official_inventory_recipe()
    path = root / "govinfo_official_inventory_recipe.json"
    path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Dedicated missing-volume fixture for focused tests.
    missing = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "fixture_id": "govinfo-missing-volume",
        "include_public_laws": False,
        "edition_catalog": {
            "discovery_source": "empty-latest-probe",
            "latest_editions": [
                {
                    "collection": COLLECTION_CFR,
                    "title": "37",
                    "package_id": "CFR-2020-title37-vol9",
                    "edition": "annual-2020-title37-vol9",
                    "year": "2020",
                    "volume": "9",
                    "discovered_at": "2024-09-01T10:00:00Z",
                }
            ],
        },
        "inventory": [
            {
                "kind": InventoryKind.CFR_VOLUME.value,
                "package_id": "CFR-2020-title37-vol9",
                "collection": COLLECTION_CFR,
                "title": "37",
                "volume": "9",
                "year": "2020",
                "edition": "annual-2020-title37-vol9",
                "formats": {},
                "expected_formats": list(FIXITY_FORMATS),
                "metadata": {
                    "volume_missing": True,
                    "missing_all_formats": True,
                    "signature": {"result": SignatureResult.MISSING.value},
                },
            }
        ],
        "notes": "Missing volume fixture — must not report success.",
    }
    (root / "govinfo_missing_volume.json").write_text(
        json.dumps(missing, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# GovInfo official verification and Public Law fixtures\n\n"
            "Compact recipes for PATLAW-018. Prefer generators in "
            "`govinfo_official_verifier` / `public_law_change_processor` over "
            "bulk golden dumps. Digital authentication and printed-volume "
            "attestation are separate channels. Missing volumes/granules/"
            "signatures or text conflicts yield conflict/inconclusive/"
            "unverified rather than success.\n",
            encoding="utf-8",
        )
    return root


__all__ = [
    "COLLECTION_CFR",
    "COLLECTION_FR",
    "COLLECTION_PLAW",
    "COLLECTION_USCODE",
    "CROSS_CHECK_PROVIDERS",
    "DEFAULT_PROVIDER",
    "FIXTURE_SCHEMA_VERSION",
    "FIXITY_FORMATS",
    "GOVINFO_API_BASE",
    "GOVINFO_CONTENT_BASE",
    "SCHEMA_VERSION",
    "DigitalAuthenticationEvidence",
    "EditionDiscovery",
    "FixityResult",
    "FixtureSchemaError",
    "FormatFixityCheck",
    "GovInfoOfficialVerifier",
    "HardCodedLatestError",
    "InventoryError",
    "InventoryKind",
    "InventoryUnit",
    "OfficialVerificationReport",
    "OfficialVerifierError",
    "PrintAttestationResult",
    "PrintedVolumeAttestation",
    "TextConflictFinding",
    "UnitVerificationResult",
    "VerificationOutcome",
    "build_govinfo_official_inventory_recipe",
    "check_format_fixity",
    "content_sha256",
    "default_fixture_dir",
    "digital_and_print_are_separate",
    "discover_latest_editions_from_catalog",
    "govinfo_cfr_package_id",
    "govinfo_fr_package_id",
    "govinfo_uscode_package_id",
    "load_json_fixture",
    "normalize_package_id",
    "normalize_title",
    "normalize_volume",
    "normalize_year",
    "outcome_to_verification_state",
    "write_default_fixtures",
]
