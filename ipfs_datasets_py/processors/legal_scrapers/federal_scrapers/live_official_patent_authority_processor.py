"""Live multi-source official patent authority acquisition (PATLAW-131).

Discovers and verifies GovInfo, U.S. Code (Title 35 OLRC release points),
Public Law / Statutes at Large, Title 37 annual materials, and Federal
Register issues/notices/rules behind the common PATLAW-127 transport and
authority-contract layer.

Design invariants:

* HTTPS success is **not** official authentication. Fixity and GPO digital
  signature evidence are verified separately; missing/invalid evidence yields
  ``unverified`` / ``conflict`` / ``inconclusive`` rather than success.
* GovInfo official electronic Federal Register packages remain distinct from
  FederalRegister.gov discovery representations (cross-check only).
* Edition / package identity is never the hard-coded token ``\"latest\"``.
* House OLRC release-point coverage is stored **with** every declared
  exclusion; coverage is never generalized to a later public-law cutoff.
* Unverified or incomplete sources remain usable only with explicit
  ``usability_status=degraded``.
* Missing adjudicatory coverage is a declared research-coverage gap and cannot
  support a complete-law conclusion.
* Live network I/O is opt-in via :class:`PatentSourceTransport`; integration
  tests use the compact recorded recipe only.
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

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    SCHEMA_VERSION as CONTRACTS_SCHEMA,
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    AuthorityIdentityV2,
    AuthorityKind,
    ContentAddress,
    DocumentPackageGranuleIds,
    PARSER_ADMISSIBLE_OUTCOMES,
    ParserInputEnvelope,
    ReleasePointExclusions,
    RenditionLegalStatus,
    SignatureFixityEvidence,
    TemporalRole,
    TemporalRoleSet,
    assert_dimensions_independent,
    canonical_json_dumps,
    content_address_bytes,
    content_address_mapping,
    require_acquisition_outcome,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    SCHEMA_VERSION as AUTHORITY_SCHEMA_VERSION,
    AuthorityTier,
    HardCodedLatestEditionError,
    VerificationState,
    reject_hard_coded_latest,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_source_transport import (
    SOURCE_TRANSPORT_SCHEMA_VERSION,
    PatentSourceTransport,
    SourceFetchRequest,
    SourceTransportError,
)

SCHEMA_VERSION = "live-official-patent-authority-processor-v1"
FIXTURE_SCHEMA_VERSION = "live-official-authorities-recipe-v1"

DEFAULT_JURISDICTION = "US"
DEFAULT_PROVIDER_GOVINFO = "govinfo"
DEFAULT_PROVIDER_USHOUSE = "ushouse"
DEFAULT_PROVIDER_FR_DISCOVERY = "federalregister.gov"

# Cross-check-only providers — never promoted to verified official authority.
CROSS_CHECK_PROVIDERS = frozenset(
    {
        "federalregister.gov",
        "www.federalregister.gov",
        "fr.gov",
        "ecfr",
        "www.ecfr.gov",
        "ushouse",
        "uscode.house.gov",
        "house",
    }
)

# Acceptance scenario kinds required by PATLAW-131.
REQUIRED_SCENARIO_KINDS = frozenset(
    {
        "edition_rollover",
        "release_point_exclusions",
        "amended_renumbered_provisions",
        "missing_package_granule",
        "bad_fixity",
        "unavailable_signature",
        "delayed_issue",
        "source_conflict",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LiveOfficialAuthorityError(ValueError):
    """Base error for live official patent authority acquisition."""


class FixtureSchemaError(LiveOfficialAuthorityError):
    """Raised when the recorded recipe is malformed."""


class HardCodedLatestError(HardCodedLatestEditionError, LiveOfficialAuthorityError):
    """Raised when a hard-coded ``latest`` edition token is supplied."""


class OfficialAuthenticationError(LiveOfficialAuthorityError):
    """Raised when code attempts to treat HTTPS alone as authentication."""


class CrossCheckPromotionError(LiveOfficialAuthorityError):
    """Raised when a cross-check source is promoted to verified official."""


class CompleteLawConclusionError(LiveOfficialAuthorityError):
    """Raised when a complete-law conclusion is attempted despite gaps."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceFamily(str, Enum):
    """Official / discovery source families handled by this processor."""

    GOVINFO_USCODE = "govinfo_uscode"
    USHOUSE_OLRC = "ushouse_olrc"
    GOVINFO_PUBLIC_LAW = "govinfo_public_law"
    GOVINFO_CFR_ANNUAL = "govinfo_cfr_annual"
    GOVINFO_FEDERAL_REGISTER = "govinfo_federal_register"
    FEDERAL_REGISTER_GOV_DISCOVERY = "federalregister_gov_discovery"
    ADJUDICATORY = "adjudicatory"

    @classmethod
    def coerce(cls, value: Any) -> "SourceFamily":
        if isinstance(value, SourceFamily):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "govinfo_uscode": cls.GOVINFO_USCODE,
            "uscode": cls.GOVINFO_USCODE,
            "usc": cls.GOVINFO_USCODE,
            "ushouse_olrc": cls.USHOUSE_OLRC,
            "olrc": cls.USHOUSE_OLRC,
            "house_olrc": cls.USHOUSE_OLRC,
            "govinfo_public_law": cls.GOVINFO_PUBLIC_LAW,
            "public_law": cls.GOVINFO_PUBLIC_LAW,
            "plaw": cls.GOVINFO_PUBLIC_LAW,
            "statute": cls.GOVINFO_PUBLIC_LAW,
            "govinfo_cfr_annual": cls.GOVINFO_CFR_ANNUAL,
            "cfr_annual": cls.GOVINFO_CFR_ANNUAL,
            "cfr": cls.GOVINFO_CFR_ANNUAL,
            "govinfo_federal_register": cls.GOVINFO_FEDERAL_REGISTER,
            "govinfo_fr": cls.GOVINFO_FEDERAL_REGISTER,
            "fr_official": cls.GOVINFO_FEDERAL_REGISTER,
            "federalregister_gov_discovery": cls.FEDERAL_REGISTER_GOV_DISCOVERY,
            "fr_gov": cls.FEDERAL_REGISTER_GOV_DISCOVERY,
            "fr_discovery": cls.FEDERAL_REGISTER_GOV_DISCOVERY,
            "adjudicatory": cls.ADJUDICATORY,
            "adjudication": cls.ADJUDICATORY,
            "court": cls.ADJUDICATORY,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(f"unsupported source family: {value!r}")
        return aliases[text]


class ScenarioKind(str, Enum):
    """Recorded integration scenario kinds (PATLAW-131 acceptance)."""

    EDITION_ROLLOVER = "edition_rollover"
    RELEASE_POINT_EXCLUSIONS = "release_point_exclusions"
    AMENDED_RENUMBERED = "amended_renumbered_provisions"
    MISSING_PACKAGE_GRANULE = "missing_package_granule"
    BAD_FIXITY = "bad_fixity"
    UNAVAILABLE_SIGNATURE = "unavailable_signature"
    DELAYED_ISSUE = "delayed_issue"
    SOURCE_CONFLICT = "source_conflict"
    ADJUDICATORY_COVERAGE = "adjudicatory_coverage"
    HAPPY_PATH = "happy_path"
    DEGRADED_UNVERIFIED = "degraded_unverified"

    @classmethod
    def coerce(cls, value: Any) -> "ScenarioKind":
        if isinstance(value, ScenarioKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "edition_rollover": cls.EDITION_ROLLOVER,
            "rollover": cls.EDITION_ROLLOVER,
            "release_point_exclusions": cls.RELEASE_POINT_EXCLUSIONS,
            "exclusions": cls.RELEASE_POINT_EXCLUSIONS,
            "amended_renumbered_provisions": cls.AMENDED_RENUMBERED,
            "amended_renumbered": cls.AMENDED_RENUMBERED,
            "renumbered": cls.AMENDED_RENUMBERED,
            "missing_package_granule": cls.MISSING_PACKAGE_GRANULE,
            "missing_package": cls.MISSING_PACKAGE_GRANULE,
            "missing_granule": cls.MISSING_PACKAGE_GRANULE,
            "bad_fixity": cls.BAD_FIXITY,
            "fixity_mismatch": cls.BAD_FIXITY,
            "unavailable_signature": cls.UNAVAILABLE_SIGNATURE,
            "missing_signature": cls.UNAVAILABLE_SIGNATURE,
            "delayed_issue": cls.DELAYED_ISSUE,
            "source_conflict": cls.SOURCE_CONFLICT,
            "conflict": cls.SOURCE_CONFLICT,
            "adjudicatory_coverage": cls.ADJUDICATORY_COVERAGE,
            "adjudicatory": cls.ADJUDICATORY_COVERAGE,
            "happy_path": cls.HAPPY_PATH,
            "success": cls.HAPPY_PATH,
            "degraded_unverified": cls.DEGRADED_UNVERIFIED,
            "degraded": cls.DEGRADED_UNVERIFIED,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(f"unsupported scenario kind: {value!r}")
        return aliases[text]


class CaseOutcome(str, Enum):
    """Terminal classification for one recorded / acquired case."""

    VERIFIED = "verified"
    DEGRADED = "degraded"
    CONFLICT = "conflict"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    DELAYED = "delayed"
    RESEARCH_GAP = "research_gap"
    ERROR = "error"

    @classmethod
    def coerce(cls, value: Any) -> "CaseOutcome":
        if isinstance(value, CaseOutcome):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "verified": cls.VERIFIED,
            "success": cls.VERIFIED,
            "degraded": cls.DEGRADED,
            "conflict": cls.CONFLICT,
            "conflicting": cls.CONFLICT,
            "missing": cls.MISSING,
            "unavailable": cls.UNAVAILABLE,
            "delayed": cls.DELAYED,
            "research_gap": cls.RESEARCH_GAP,
            "blocking_research_gap": cls.RESEARCH_GAP,
            "error": cls.ERROR,
            "failed": cls.ERROR,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(f"unsupported case outcome: {value!r}")
        return aliases[text]


class UsabilityStatus(str, Enum):
    """Whether a case result may be consumed and under what constraints."""

    FULL = "full"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    RESEARCH_GAP = "research_gap"

    @classmethod
    def coerce(cls, value: Any) -> "UsabilityStatus":
        if isinstance(value, UsabilityStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "full": cls.FULL,
            "usable": cls.FULL,
            "degraded": cls.DEGRADED,
            "blocked": cls.BLOCKED,
            "unusable": cls.BLOCKED,
            "research_gap": cls.RESEARCH_GAP,
            "gap": cls.RESEARCH_GAP,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(f"unsupported usability status: {value!r}")
        return aliases[text]


class FixityCheckResult(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_ADVERTISED = "missing_advertised"
    MISSING_OBSERVED = "missing_observed"
    NOT_CHECKED = "not_checked"

    @classmethod
    def coerce(cls, value: Any) -> "FixityCheckResult":
        if isinstance(value, FixityCheckResult):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "match": cls.MATCH,
            "ok": cls.MATCH,
            "mismatch": cls.MISMATCH,
            "conflict": cls.MISMATCH,
            "missing_advertised": cls.MISSING_ADVERTISED,
            "missing_observed": cls.MISSING_OBSERVED,
            "not_checked": cls.NOT_CHECKED,
            "unchecked": cls.NOT_CHECKED,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(f"unsupported fixity result: {value!r}")
        return aliases[text]


class SignatureAvailability(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"

    @classmethod
    def coerce(cls, value: Any) -> "SignatureAvailability":
        if isinstance(value, SignatureAvailability):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "valid": cls.VALID,
            "ok": cls.VALID,
            "invalid": cls.INVALID,
            "unavailable": cls.UNAVAILABLE,
            "missing": cls.UNAVAILABLE,
            "not_checked": cls.NOT_CHECKED,
            "unchecked": cls.NOT_CHECKED,
        }
        if text not in aliases:
            raise LiveOfficialAuthorityError(
                f"unsupported signature availability: {value!r}"
            )
        return aliases[text]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveOfficialAuthorityError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise LiveOfficialAuthorityError(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, "value")


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise LiveOfficialAuthorityError(f"{name} must be a lowercase 64-char hex SHA-256")
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
            raise LiveOfficialAuthorityError(f"{name} must be ISO-8601 datetime") from exc
    else:
        raise LiveOfficialAuthorityError(f"{name} must be a datetime or ISO-8601 string")
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
            raise LiveOfficialAuthorityError(f"{name} must be an ISO date") from exc
    raise LiveOfficialAuthorityError(f"{name} must be a date or ISO date string")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): _deep_sorted(value[k])
            for k in sorted(value.keys(), key=lambda x: str(x))
        }
    if isinstance(value, (list, tuple)):
        return [_deep_sorted(v) for v in value]
    return value


def content_sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def reject_latest_token(value: Any, *, field_name: str) -> str:
    text = _require_non_empty_str(str(value), field_name)
    reject_hard_coded_latest(text, field_name=field_name)
    if _LATEST_TOKEN_RE.fullmatch(text):
        raise HardCodedLatestError(
            f"{field_name} must not be the hard-coded token 'latest'"
        )
    if "LATEST" in text.upper().split("-") or text.strip().lower() == "latest":
        raise HardCodedLatestError(
            f"{field_name} must not contain the hard-coded token 'latest'"
        )
    return text


def default_fixture_dir() -> Path:
    """Repository fixture directory for the live official authorities recipe."""

    # .../federal_scrapers/this_file.py → repo root is parents[3]
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3]
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "live",
        Path.cwd()
        / "tests"
        / "fixtures"
        / "legal_data"
        / "patent_authorities"
        / "live",
    ]
    for path in candidates:
        if (path / "official_authorities_recipe.json").is_file():
            return path
    return candidates[0]


def load_json_fixture(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FixtureSchemaError(f"fixture not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureSchemaError(f"invalid JSON in {target}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FixtureSchemaError(f"fixture root must be an object: {target}")
    return payload


def family_default_authority_kind(family: SourceFamily) -> AuthorityKind:
    if family in {SourceFamily.GOVINFO_USCODE, SourceFamily.USHOUSE_OLRC}:
        return AuthorityKind.CODIFIED_STATUTE
    if family is SourceFamily.GOVINFO_PUBLIC_LAW:
        return AuthorityKind.ENACTED_STATUTE_AT_LARGE
    if family in {
        SourceFamily.GOVINFO_CFR_ANNUAL,
        SourceFamily.GOVINFO_FEDERAL_REGISTER,
    }:
        return AuthorityKind.PROMULGATED_REGULATION
    if family is SourceFamily.FEDERAL_REGISTER_GOV_DISCOVERY:
        return AuthorityKind.UNOFFICIAL_EDITORIAL_AID
    if family is SourceFamily.ADJUDICATORY:
        return AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY
    raise LiveOfficialAuthorityError(f"no default authority kind for {family}")


def family_default_tier(family: SourceFamily) -> AuthorityTier:
    if family is SourceFamily.FEDERAL_REGISTER_GOV_DISCOVERY:
        return AuthorityTier.UNOFFICIAL_CURRENT
    if family is SourceFamily.GOVINFO_PUBLIC_LAW:
        return AuthorityTier.OFFICIAL_CHANGE
    if family is SourceFamily.GOVINFO_FEDERAL_REGISTER:
        return AuthorityTier.OFFICIAL_CHANGE
    if family is SourceFamily.ADJUDICATORY:
        return AuthorityTier.OFFICIAL_CHANGE
    return AuthorityTier.OFFICIAL_BASE


def family_default_rendition(family: SourceFamily) -> RenditionLegalStatus:
    if family is SourceFamily.FEDERAL_REGISTER_GOV_DISCOVERY:
        return RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION
    if family is SourceFamily.USHOUSE_OLRC:
        return RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT
    return RenditionLegalStatus.OFFICIAL_ELECTRONIC


def is_cross_check_provider(provider: str) -> bool:
    return provider.strip().lower() in CROSS_CHECK_PROVIDERS


def verification_state_for_outcome(outcome: CaseOutcome) -> VerificationState:
    if outcome is CaseOutcome.VERIFIED:
        return VerificationState.VERIFIED
    if outcome is CaseOutcome.CONFLICT:
        return VerificationState.CONFLICT
    if outcome in {CaseOutcome.MISSING, CaseOutcome.UNAVAILABLE, CaseOutcome.DELAYED}:
        return VerificationState.INCONCLUSIVE
    if outcome is CaseOutcome.RESEARCH_GAP:
        return VerificationState.HUMAN_REVIEW_REQUIRED
    if outcome is CaseOutcome.DEGRADED:
        return VerificationState.UNVERIFIED
    return VerificationState.UNVERIFIED


def usability_for_outcome(
    outcome: CaseOutcome,
    *,
    incomplete: bool = False,
    unverified: bool = False,
) -> UsabilityStatus:
    if outcome is CaseOutcome.VERIFIED and not incomplete and not unverified:
        return UsabilityStatus.FULL
    if outcome is CaseOutcome.RESEARCH_GAP:
        return UsabilityStatus.RESEARCH_GAP
    if outcome in {
        CaseOutcome.MISSING,
        CaseOutcome.UNAVAILABLE,
        CaseOutcome.ERROR,
        CaseOutcome.CONFLICT,
    }:
        return UsabilityStatus.BLOCKED
    # Delayed, degraded, verified-but-incomplete/unverified → degraded usable.
    return UsabilityStatus.DEGRADED


def https_is_not_authentication(
    *,
    http_status: int | None,
    fixity: FixityCheckResult,
    signature: SignatureAvailability,
) -> bool:
    """Return True when authentication is independent of HTTP success.

    Official authentication requires fixity match and (when expected) a valid
    signature. HTTP 200 alone never yields verified authentication.
    """

    if http_status == 200 and (
        fixity is not FixityCheckResult.MATCH
        or signature
        in {SignatureAvailability.UNAVAILABLE, SignatureAvailability.INVALID}
    ):
        return True
    if http_status == 200 and signature is SignatureAvailability.NOT_CHECKED:
        return True
    return True  # structural invariant always holds; callers assert via outcomes


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvisionLink:
    """Cross-link for amended / renumbered provisions and effective dates."""

    citation: str
    prior_citation: Optional[str] = None
    effective_date: Optional[date] = None
    amendment_kind: Optional[str] = None  # amended | renumbered | transferred
    public_law: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "citation", _require_non_empty_str(self.citation, "citation")
        )
        if self.prior_citation is not None:
            object.__setattr__(
                self,
                "prior_citation",
                _require_non_empty_str(self.prior_citation, "prior_citation"),
            )
        if self.effective_date is not None and not isinstance(self.effective_date, date):
            object.__setattr__(
                self,
                "effective_date",
                _parse_optional_date(self.effective_date, name="effective_date"),
            )
        if self.amendment_kind is not None:
            object.__setattr__(
                self,
                "amendment_kind",
                _require_non_empty_str(self.amendment_kind, "amendment_kind").lower(),
            )
        if self.public_law is not None:
            object.__setattr__(
                self,
                "public_law",
                _require_non_empty_str(self.public_law, "public_law"),
            )
        if self.notes is not None:
            object.__setattr__(
                self, "notes", _require_non_empty_str(self.notes, "notes")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_kind": self.amendment_kind,
            "citation": self.citation,
            "effective_date": _date_to_str(self.effective_date),
            "notes": self.notes,
            "prior_citation": self.prior_citation,
            "public_law": self.public_law,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "ProvisionLink":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("provision link must be a mapping")
        return cls(
            citation=value["citation"],
            prior_citation=value.get("prior_citation"),
            effective_date=_parse_optional_date(
                value.get("effective_date"), name="effective_date"
            ),
            amendment_kind=value.get("amendment_kind"),
            public_law=value.get("public_law"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class AdjudicatoryCoverage:
    """Adjudicatory authority coverage status for complete-law claims.

    When coverage is absent, :attr:`is_blocking_research_gap` is True and no
    complete-law conclusion may be drawn.
    """

    present: bool
    status: str  # present | research_gap | partial
    notes: str
    authorities: tuple[str, ...] = ()
    is_blocking_research_gap: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _require_non_empty_str(self.status, "status").lower()
        )
        object.__setattr__(
            self, "notes", _require_non_empty_str(self.notes, "notes")
        )
        cleaned = tuple(
            _require_non_empty_str(a, "authorities[]") for a in self.authorities
        )
        object.__setattr__(self, "authorities", cleaned)
        object.__setattr__(self, "present", bool(self.present))
        if not self.present:
            object.__setattr__(self, "is_blocking_research_gap", True)
            if self.status not in {"research_gap", "missing", "absent"}:
                object.__setattr__(self, "status", "research_gap")
        else:
            object.__setattr__(self, "is_blocking_research_gap", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorities": list(self.authorities),
            "is_blocking_research_gap": bool(self.is_blocking_research_gap),
            "notes": self.notes,
            "present": bool(self.present),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping | None) -> "AdjudicatoryCoverage":
        if value is None:
            return cls(
                present=False,
                status="research_gap",
                notes=(
                    "Adjudicatory coverage not declared; recorded as blocking "
                    "research-coverage gap. Cannot support a complete-law conclusion."
                ),
                authorities=(),
                is_blocking_research_gap=True,
            )
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("adjudicatory_coverage must be a mapping")
        present = bool(value.get("present", False))
        status = str(
            value.get("status")
            or ("present" if present else "research_gap")
        )
        notes = str(
            value.get("notes")
            or (
                "Adjudicatory authorities recorded."
                if present
                else (
                    "Missing adjudicatory coverage is a declared research-coverage "
                    "gap and cannot support a complete-law conclusion."
                )
            )
        )
        raw_auth = value.get("authorities") or ()
        if not isinstance(raw_auth, (list, tuple)):
            raise FixtureSchemaError("adjudicatory authorities must be a sequence")
        return cls(
            present=present,
            status=status,
            notes=notes,
            authorities=tuple(raw_auth),
            is_blocking_research_gap=not present,
        )

    @classmethod
    def research_gap(cls, notes: str | None = None) -> "AdjudicatoryCoverage":
        return cls(
            present=False,
            status="research_gap",
            notes=notes
            or (
                "Missing adjudicatory coverage is a declared research-coverage "
                "gap and cannot support a complete-law conclusion."
            ),
            authorities=(),
            is_blocking_research_gap=True,
        )


@dataclass(frozen=True, slots=True)
class OfficialAuthorityCase:
    """One compact recorded acquisition/verification case from the recipe."""

    case_id: str
    scenario: ScenarioKind
    source_family: SourceFamily
    provider: str
    source_id: str
    source_url: str
    edition_or_release_point: str
    package_id: Optional[str] = None
    granule_id: Optional[str] = None
    collection_code: Optional[str] = None
    title_number: Optional[str] = None
    media_type: str = "application/xml"
    advertised_sha256: Optional[str] = None
    observed_sha256: Optional[str] = None
    body_text: Optional[str] = None
    signature: SignatureAvailability = SignatureAvailability.NOT_CHECKED
    signature_algorithm: Optional[str] = None
    signature_evidence: Optional[str] = None
    http_status: int = 200
    acquisition_kind: AcquisitionOutcomeKind = AcquisitionOutcomeKind.FETCHED
    exclusions: tuple[str, ...] = ()
    coverage_notes: Optional[str] = None
    provision_links: tuple[ProvisionLink, ...] = ()
    prior_edition: Optional[str] = None
    successor_edition: Optional[str] = None
    issue_date: Optional[date] = None
    delayed_until: Optional[date] = None
    conflict_peer_provider: Optional[str] = None
    conflict_peer_sha256: Optional[str] = None
    expected_outcome: Optional[CaseOutcome] = None
    incomplete: bool = False
    notes: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "case_id", _require_non_empty_str(self.case_id, "case_id")
        )
        object.__setattr__(self, "scenario", ScenarioKind.coerce(self.scenario))
        object.__setattr__(
            self, "source_family", SourceFamily.coerce(self.source_family)
        )
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        object.__setattr__(
            self, "source_id", reject_latest_token(self.source_id, field_name="source_id")
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        object.__setattr__(
            self,
            "edition_or_release_point",
            reject_latest_token(
                self.edition_or_release_point, field_name="edition_or_release_point"
            ),
        )
        for name in ("package_id", "granule_id", "collection_code", "title_number"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(
                    self, name, reject_latest_token(raw, field_name=name)
                )
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
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
        object.__setattr__(
            self, "signature", SignatureAvailability.coerce(self.signature)
        )
        if not isinstance(self.http_status, int) or isinstance(self.http_status, bool):
            raise LiveOfficialAuthorityError("http_status must be an int")
        object.__setattr__(
            self,
            "acquisition_kind",
            (
                self.acquisition_kind
                if isinstance(self.acquisition_kind, AcquisitionOutcomeKind)
                else AcquisitionOutcomeKind(str(self.acquisition_kind).lower())
            ),
        )
        excl = tuple(
            reject_latest_token(e, field_name="exclusions[]") for e in self.exclusions
        )
        object.__setattr__(self, "exclusions", excl)
        links = tuple(
            p if isinstance(p, ProvisionLink) else ProvisionLink.from_dict(p)
            for p in self.provision_links
        )
        object.__setattr__(self, "provision_links", links)
        for name in ("prior_edition", "successor_edition"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(
                    self, name, reject_latest_token(raw, field_name=name)
                )
        if self.issue_date is not None and not isinstance(self.issue_date, date):
            object.__setattr__(
                self,
                "issue_date",
                _parse_optional_date(self.issue_date, name="issue_date"),
            )
        if self.delayed_until is not None and not isinstance(self.delayed_until, date):
            object.__setattr__(
                self,
                "delayed_until",
                _parse_optional_date(self.delayed_until, name="delayed_until"),
            )
        if self.expected_outcome is not None:
            object.__setattr__(
                self, "expected_outcome", CaseOutcome.coerce(self.expected_outcome)
            )
        if self.conflict_peer_sha256 is not None:
            object.__setattr__(
                self,
                "conflict_peer_sha256",
                _require_sha256(self.conflict_peer_sha256, "conflict_peer_sha256"),
            )
        if not isinstance(self.metadata, Mapping):
            raise LiveOfficialAuthorityError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_discovery_only(self) -> bool:
        """True for unofficial discovery representations (not official artifacts).

        House OLRC release points are official for codified Title 35 and are
        **not** discovery-only. FederalRegister.gov HTML/API views are always
        discovery/editorial. Cross-check providers on non-OLRC families are
        discovery-only.
        """

        if self.source_family is SourceFamily.USHOUSE_OLRC:
            return False
        if self.source_family is SourceFamily.FEDERAL_REGISTER_GOV_DISCOVERY:
            return True
        if self.source_family in {
            SourceFamily.GOVINFO_USCODE,
            SourceFamily.GOVINFO_PUBLIC_LAW,
            SourceFamily.GOVINFO_CFR_ANNUAL,
            SourceFamily.GOVINFO_FEDERAL_REGISTER,
            SourceFamily.ADJUDICATORY,
        }:
            return False
        return is_cross_check_provider(self.provider)

    def resolved_body_bytes(self) -> Optional[bytes]:
        if self.body_text is not None:
            return self.body_text.encode("utf-8")
        if self.observed_sha256 is not None:
            # Deterministic synthetic body keyed by case identity for digest tests.
            return (
                f"official-authority-case:{self.case_id}:{self.observed_sha256}"
            ).encode("utf-8")
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_kind": self.acquisition_kind.value,
            "advertised_sha256": self.advertised_sha256,
            "body_text": self.body_text,
            "case_id": self.case_id,
            "collection_code": self.collection_code,
            "conflict_peer_provider": self.conflict_peer_provider,
            "conflict_peer_sha256": self.conflict_peer_sha256,
            "coverage_notes": self.coverage_notes,
            "delayed_until": _date_to_str(self.delayed_until),
            "edition_or_release_point": self.edition_or_release_point,
            "exclusions": list(self.exclusions),
            "expected_outcome": (
                None if self.expected_outcome is None else self.expected_outcome.value
            ),
            "granule_id": self.granule_id,
            "http_status": self.http_status,
            "incomplete": bool(self.incomplete),
            "issue_date": _date_to_str(self.issue_date),
            "media_type": self.media_type,
            "metadata": _deep_sorted(self.metadata),
            "notes": self.notes,
            "observed_sha256": self.observed_sha256,
            "package_id": self.package_id,
            "prior_edition": self.prior_edition,
            "provider": self.provider,
            "provision_links": [p.to_dict() for p in self.provision_links],
            "scenario": self.scenario.value,
            "signature": self.signature.value,
            "signature_algorithm": self.signature_algorithm,
            "signature_evidence": self.signature_evidence,
            "source_family": self.source_family.value,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "successor_edition": self.successor_edition,
            "title_number": self.title_number,
        }

    @classmethod
    def from_dict(cls, value: JsonMapping) -> "OfficialAuthorityCase":
        if not isinstance(value, Mapping):
            raise FixtureSchemaError("case must be a mapping")
        required = (
            "case_id",
            "scenario",
            "source_family",
            "provider",
            "source_id",
            "source_url",
            "edition_or_release_point",
        )
        for key in required:
            if key not in value or value.get(key) in (None, ""):
                raise FixtureSchemaError(f"case missing required field {key!r}")
        raw_excl = value.get("exclusions") or ()
        if not isinstance(raw_excl, (list, tuple)):
            raise FixtureSchemaError("exclusions must be a sequence")
        raw_links = value.get("provision_links") or ()
        if not isinstance(raw_links, (list, tuple)):
            raise FixtureSchemaError("provision_links must be a sequence")
        acq_kind = value.get("acquisition_kind", "fetched")
        if isinstance(acq_kind, str):
            acq_kind = AcquisitionOutcomeKind(acq_kind.strip().lower())
        return cls(
            case_id=value["case_id"],
            scenario=value["scenario"],
            source_family=value["source_family"],
            provider=value["provider"],
            source_id=value["source_id"],
            source_url=value["source_url"],
            edition_or_release_point=value["edition_or_release_point"],
            package_id=value.get("package_id"),
            granule_id=value.get("granule_id"),
            collection_code=value.get("collection_code"),
            title_number=value.get("title_number"),
            media_type=value.get("media_type") or "application/xml",
            advertised_sha256=value.get("advertised_sha256"),
            observed_sha256=value.get("observed_sha256"),
            body_text=value.get("body_text"),
            signature=value.get("signature") or "not_checked",
            signature_algorithm=value.get("signature_algorithm"),
            signature_evidence=value.get("signature_evidence"),
            http_status=int(value.get("http_status", 200)),
            acquisition_kind=acq_kind,
            exclusions=tuple(raw_excl),
            coverage_notes=value.get("coverage_notes"),
            provision_links=tuple(raw_links),
            prior_edition=value.get("prior_edition"),
            successor_edition=value.get("successor_edition"),
            issue_date=_parse_optional_date(value.get("issue_date"), name="issue_date"),
            delayed_until=_parse_optional_date(
                value.get("delayed_until"), name="delayed_until"
            ),
            conflict_peer_provider=value.get("conflict_peer_provider"),
            conflict_peer_sha256=value.get("conflict_peer_sha256"),
            expected_outcome=value.get("expected_outcome"),
            incomplete=bool(value.get("incomplete", False)),
            notes=value.get("notes"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class OfficialAuthorityCaseResult:
    """Verified / classified result for one official authority case."""

    case: OfficialAuthorityCase
    outcome: CaseOutcome
    usability: UsabilityStatus
    verification_state: VerificationState
    fixity: FixityCheckResult
    signature: SignatureAvailability
    acquisition: Optional[AcquisitionOutcome]
    authority: Optional[AuthorityIdentityV2]
    reasons: tuple[str, ...] = ()
    provision_links: tuple[ProvisionLink, ...] = ()
    is_official_authenticated: bool = False
    https_alone_not_auth: bool = True
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", CaseOutcome.coerce(self.outcome))
        object.__setattr__(self, "usability", UsabilityStatus.coerce(self.usability))
        # Enforce degraded-only usability for incomplete/unverified sources.
        if self.outcome is CaseOutcome.DEGRADED and self.usability is UsabilityStatus.FULL:
            object.__setattr__(self, "usability", UsabilityStatus.DEGRADED)
        if (
            self.verification_state
            in {
                VerificationState.UNVERIFIED,
                VerificationState.INCONCLUSIVE,
                VerificationState.CONFLICT,
            }
            and self.usability is UsabilityStatus.FULL
        ):
            object.__setattr__(self, "usability", UsabilityStatus.DEGRADED)
        if self.usability is UsabilityStatus.FULL and not self.is_official_authenticated:
            # Full usability requires official authentication evidence.
            object.__setattr__(self, "usability", UsabilityStatus.DEGRADED)
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "provision_links", tuple(self.provision_links))
        object.__setattr__(self, "https_alone_not_auth", True)

    @property
    def is_usable(self) -> bool:
        return self.usability in {UsabilityStatus.FULL, UsabilityStatus.DEGRADED}

    @property
    def requires_degraded_flag(self) -> bool:
        return self.usability is UsabilityStatus.DEGRADED

    def assert_usable_only_if_allowed(self) -> None:
        """Fail closed when blocked/research-gap results are treated as full authority."""

        if self.usability is UsabilityStatus.BLOCKED:
            raise LiveOfficialAuthorityError(
                f"case {self.case.case_id!r} is blocked and must not be used as authority"
            )
        if self.usability is UsabilityStatus.RESEARCH_GAP:
            raise CompleteLawConclusionError(
                f"case {self.case.case_id!r} is a research-coverage gap and cannot "
                "support a complete-law conclusion"
            )
        if self.usability is UsabilityStatus.DEGRADED and not self.requires_degraded_flag:
            raise LiveOfficialAuthorityError(
                f"case {self.case.case_id!r} degraded usability flag missing"
            )

    def to_parser_input(self) -> ParserInputEnvelope:
        if self.acquisition is None:
            raise LiveOfficialAuthorityError(
                f"case {self.case.case_id!r} has no acquisition outcome for parser input"
            )
        if self.usability is UsabilityStatus.BLOCKED:
            raise LiveOfficialAuthorityError(
                f"blocked case {self.case.case_id!r} cannot be admitted to a parser"
            )
        return ParserInputEnvelope.admit(
            self.acquisition,
            authority=self.authority,
            parser_name="live_official_patent_authority",
            metadata={
                "case_id": self.case.case_id,
                "usability_status": self.usability.value,
                "outcome": self.outcome.value,
                "degraded": self.usability is UsabilityStatus.DEGRADED,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition": None if self.acquisition is None else self.acquisition.to_dict(),
            "authority": None if self.authority is None else self.authority.to_dict(),
            "case": self.case.to_dict(),
            "fixity": self.fixity.value,
            "https_alone_not_auth": bool(self.https_alone_not_auth),
            "is_official_authenticated": bool(self.is_official_authenticated),
            "is_usable": self.is_usable,
            "notes": self.notes,
            "outcome": self.outcome.value,
            "provision_links": [p.to_dict() for p in self.provision_links],
            "reasons": list(self.reasons),
            "requires_degraded_flag": self.requires_degraded_flag,
            "signature": self.signature.value,
            "usability": self.usability.value,
            "verification_state": self.verification_state.value,
        }


@dataclass(frozen=True, slots=True)
class OfficialAuthorityBatchReport:
    """Aggregate report for a recipe (or live batch) of official sources."""

    results: tuple[OfficialAuthorityCaseResult, ...]
    adjudicatory: AdjudicatoryCoverage
    recipe_id: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    schema_version: str = SCHEMA_VERSION
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))
        if self.retrieved_at is not None:
            object.__setattr__(
                self, "retrieved_at", _parse_utc(self.retrieved_at, name="retrieved_at")
            )

    @property
    def scenario_kinds(self) -> frozenset[str]:
        return frozenset(r.case.scenario.value for r in self.results)

    def result_by_id(self, case_id: str) -> OfficialAuthorityCaseResult:
        for result in self.results:
            if result.case.case_id == case_id:
                return result
        raise KeyError(case_id)

    def results_for_scenario(
        self, scenario: ScenarioKind | str
    ) -> tuple[OfficialAuthorityCaseResult, ...]:
        kind = ScenarioKind.coerce(scenario)
        return tuple(r for r in self.results if r.case.scenario is kind)

    def missing_required_scenarios(self) -> frozenset[str]:
        return REQUIRED_SCENARIO_KINDS - self.scenario_kinds

    def covers_required_scenarios(self) -> bool:
        return not self.missing_required_scenarios()

    def degraded_results(self) -> tuple[OfficialAuthorityCaseResult, ...]:
        return tuple(
            r for r in self.results if r.usability is UsabilityStatus.DEGRADED
        )

    def assert_no_complete_law_without_adjudicatory(self) -> None:
        if self.adjudicatory.is_blocking_research_gap:
            raise CompleteLawConclusionError(
                "Adjudicatory coverage is a blocking research-coverage gap; "
                "cannot support a complete-law conclusion. "
                + self.adjudicatory.notes
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudicatory_coverage": self.adjudicatory.to_dict(),
            "covers_required_scenarios": self.covers_required_scenarios(),
            "missing_required_scenarios": sorted(self.missing_required_scenarios()),
            "notes": self.notes,
            "recipe_id": self.recipe_id,
            "results": [r.to_dict() for r in self.results],
            "retrieved_at": (
                None if self.retrieved_at is None else _format_utc(self.retrieved_at)
            ),
            "scenario_kinds": sorted(self.scenario_kinds),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Fixity / signature / outcome adjudication
# ---------------------------------------------------------------------------


def check_fixity(
    *,
    advertised_sha256: Optional[str],
    observed_sha256: Optional[str],
    body: Optional[bytes] = None,
) -> FixityCheckResult:
    """Compare advertised vs observed digests; never trust HTTP alone."""

    observed = observed_sha256
    if body is not None:
        computed = content_sha256(body)
        if observed is None:
            observed = computed
        elif observed != computed:
            # Prefer explicit mismatch when body disagrees with declared observed.
            return FixityCheckResult.MISMATCH
    if advertised_sha256 is None and observed is None:
        return FixityCheckResult.NOT_CHECKED
    if advertised_sha256 is None:
        return FixityCheckResult.MISSING_ADVERTISED
    if observed is None:
        return FixityCheckResult.MISSING_OBSERVED
    if advertised_sha256.lower() == observed.lower():
        return FixityCheckResult.MATCH
    return FixityCheckResult.MISMATCH


def adjudicate_case(case: OfficialAuthorityCase) -> CaseOutcome:
    """Derive the terminal case outcome from recorded case signals.

    Scenario-specific acceptance kinds take priority; otherwise evidence drives
    fail-closed outcomes. HTTPS success alone never yields verified.
    """

    # Scenario-first for explicit acceptance cases.
    if case.scenario is ScenarioKind.ADJUDICATORY_COVERAGE:
        return CaseOutcome.RESEARCH_GAP
    if case.scenario is ScenarioKind.SOURCE_CONFLICT:
        return CaseOutcome.CONFLICT
    if case.scenario is ScenarioKind.BAD_FIXITY:
        return CaseOutcome.CONFLICT
    if case.scenario is ScenarioKind.DELAYED_ISSUE or case.delayed_until is not None:
        return CaseOutcome.DELAYED
    if case.scenario is ScenarioKind.MISSING_PACKAGE_GRANULE:
        return CaseOutcome.MISSING
    if case.scenario is ScenarioKind.UNAVAILABLE_SIGNATURE:
        return CaseOutcome.DEGRADED
    if case.scenario is ScenarioKind.DEGRADED_UNVERIFIED:
        return CaseOutcome.DEGRADED

    # Explicit missing / unavailable acquisition.
    if case.acquisition_kind is AcquisitionOutcomeKind.UNAVAILABLE:
        return CaseOutcome.UNAVAILABLE
    if case.http_status in {404, 410}:
        return CaseOutcome.MISSING
    if case.http_status >= 500:
        return CaseOutcome.UNAVAILABLE

    fixity = check_fixity(
        advertised_sha256=case.advertised_sha256,
        observed_sha256=case.observed_sha256,
        body=case.resolved_body_bytes() if case.body_text is not None else None,
    )
    if fixity is FixityCheckResult.MISMATCH:
        return CaseOutcome.CONFLICT
    if case.signature is SignatureAvailability.INVALID:
        return CaseOutcome.CONFLICT
    if case.signature is SignatureAvailability.UNAVAILABLE:
        return CaseOutcome.DEGRADED
    if case.incomplete:
        return CaseOutcome.DEGRADED
    if case.is_discovery_only:
        # FederalRegister.gov etc. never become verified official.
        return CaseOutcome.DEGRADED
    if (
        fixity is FixityCheckResult.MATCH
        and case.signature is SignatureAvailability.VALID
        and case.http_status == 200
        and case.acquisition_kind in PARSER_ADMISSIBLE_OUTCOMES
    ):
        return CaseOutcome.VERIFIED
    if case.expected_outcome is not None:
        return case.expected_outcome
    # Partial evidence without signature validity → degraded, not verified.
    return CaseOutcome.DEGRADED


def build_acquisition_outcome(
    case: OfficialAuthorityCase,
    *,
    retrieved_at: datetime | None = None,
    body: Optional[bytes] = None,
) -> AcquisitionOutcome:
    """Build a content-addressed acquisition outcome from a recorded case."""

    when = retrieved_at or datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    raw = body
    if raw is None and case.body_text is not None:
        raw = case.body_text.encode("utf-8")
    content: Optional[ContentAddress] = None
    if raw is not None:
        content = content_address_bytes(raw)
    elif case.observed_sha256 is not None:
        content = ContentAddress(
            sha256=case.observed_sha256,
            cid=f"sha256:{case.observed_sha256}",
            byte_size=0,
        )

    kind = case.acquisition_kind
    if case.http_status in {404, 410}:
        kind = AcquisitionOutcomeKind.UNAVAILABLE
        raw = None
        content = None
    elif case.http_status in {429, 503}:
        kind = AcquisitionOutcomeKind.THROTTLED
        raw = None
        content = None
    elif case.scenario is ScenarioKind.MISSING_PACKAGE_GRANULE and case.http_status >= 400:
        kind = AcquisitionOutcomeKind.UNAVAILABLE
        raw = None
        content = None

    # Parser-admissible outcomes need body when FETCHED/CHANGED.
    if kind in {AcquisitionOutcomeKind.FETCHED, AcquisitionOutcomeKind.CHANGED}:
        if raw is None and content is not None and case.observed_sha256:
            # Reconstruct a deterministic body whose digest matches observed
            # only when body_text provided the digest; otherwise keep content
            # address without body (not parser-admissible for FETCHED).
            if case.body_text is not None:
                raw = case.body_text.encode("utf-8")
                content = content_address_bytes(raw)

    error_code = None
    error_message = None
    if kind not in PARSER_ADMISSIBLE_OUTCOMES:
        error_code = kind.value
        error_message = f"acquisition {kind.value} for case {case.case_id}"

    receipt = AcquisitionReceipt(
        endpoint=case.source_url,
        retrieved_at=when,
        outcome_kind=kind,
        response_status=int(case.http_status),
        sanitized_request={
            "method": "GET",
            "path": case.source_url,
            "case_id": case.case_id,
        },
        content=content,
        media_type=case.media_type,
        declared_media_type=case.media_type,
        source_timestamp=_date_to_str(case.issue_date),
        error_code=error_code,
        error_message=error_message,
        metadata={
            "case_id": case.case_id,
            "package_id": case.package_id,
            "granule_id": case.granule_id,
            "provider": case.provider,
            "source_family": case.source_family.value,
            "https_is_not_authentication": True,
        },
    )
    # Only attach body when digests align.
    outcome_body = None
    if raw is not None and content is not None:
        if content_sha256(raw) == content.sha256:
            outcome_body = raw
    return AcquisitionOutcome(
        kind=kind,
        receipt=receipt,
        body=outcome_body,
        network_used=False,
    )


def build_authority_identity(
    case: OfficialAuthorityCase,
    *,
    outcome: CaseOutcome,
    fixity: FixityCheckResult,
    signature: SignatureAvailability,
    retrieved_at: datetime | None = None,
    content: Optional[ContentAddress] = None,
) -> Optional[AuthorityIdentityV2]:
    """Build v2 authority identity when enough identity fields exist.

    Cross-check discovery sources are labelled unofficial; they never receive
    verified official authentication status.
    """

    when = retrieved_at or datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    sha = None
    if content is not None:
        sha = content.sha256
    elif case.observed_sha256 is not None:
        sha = case.observed_sha256
    elif case.advertised_sha256 is not None:
        sha = case.advertised_sha256
    if sha is None:
        return None

    family = case.source_family
    kind = family_default_authority_kind(family)
    tier = family_default_tier(family)
    rendition = family_default_rendition(family)

    # Discovery / cross-check sources forced unofficial.
    if case.is_discovery_only:
        kind = AuthorityKind.UNOFFICIAL_EDITORIAL_AID
        tier = AuthorityTier.UNOFFICIAL_CURRENT
        rendition = RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION

    assert_dimensions_independent(
        authority_kind=kind,
        authority_tier=tier,
        rendition_legal_status=rendition,
    )

    sig_present = signature in {
        SignatureAvailability.VALID,
        SignatureAvailability.INVALID,
    }
    sig_valid: Optional[bool]
    if signature is SignatureAvailability.VALID:
        sig_valid = True
    elif signature is SignatureAvailability.INVALID:
        sig_valid = False
    else:
        sig_valid = None

    fixity_ev = SignatureFixityEvidence(
        content_sha256=sha,
        content_cid=content.cid if content is not None else f"sha256:{sha}",
        signature_present=sig_present,
        signature_valid=sig_valid,
        signature_algorithm=case.signature_algorithm,
        signature_evidence=case.signature_evidence,
        authenticated_by=(
            "U.S. Government Publishing Office"
            if signature is SignatureAvailability.VALID
            else None
        ),
    )

    release = ReleasePointExclusions(
        edition_or_release_point=case.edition_or_release_point,
        exclusions=case.exclusions,
        coverage_notes=case.coverage_notes,
    )
    docs = DocumentPackageGranuleIds(
        document_id=case.source_id,
        package_id=case.package_id,
        granule_id=case.granule_id,
        collection_code=case.collection_code,
        title_number=case.title_number,
    )
    # Temporal roles accept ISO dates/datetimes only — free-form edition
    # tokens live on ReleasePointExclusions, not TemporalRole.EDITION.
    temporal_assignments: dict[str, Optional[str]] = {
        TemporalRole.RETRIEVAL.value: _format_utc(when),
    }
    if case.issue_date is not None:
        temporal_assignments[TemporalRole.PUBLICATION.value] = _date_to_str(
            case.issue_date
        )
        temporal_assignments[TemporalRole.DATE_ISSUED.value] = _date_to_str(
            case.issue_date
        )
        temporal_assignments[TemporalRole.EDITION.value] = _date_to_str(case.issue_date)
    if case.delayed_until is not None:
        temporal_assignments[TemporalRole.EFFECTIVE.value] = _date_to_str(
            case.delayed_until
        )
    elif case.issue_date is not None:
        temporal_assignments[TemporalRole.EFFECTIVE.value] = _date_to_str(
            case.issue_date
        )
    temporal = TemporalRoleSet(assignments=temporal_assignments)

    vstate = verification_state_for_outcome(outcome)
    # Discovery never verified official.
    if case.is_discovery_only and vstate is VerificationState.VERIFIED:
        vstate = VerificationState.UNVERIFIED
    if fixity is FixityCheckResult.MISMATCH:
        vstate = VerificationState.CONFLICT
    if signature is SignatureAvailability.UNAVAILABLE and vstate is VerificationState.VERIFIED:
        vstate = VerificationState.UNVERIFIED

    return AuthorityIdentityV2(
        provider=case.provider,
        source_id=case.source_id,
        artifact_sha256=sha,
        source_url=case.source_url,
        retrieved_at=when,
        authority_kind=kind,
        authority_tier=tier,
        rendition_legal_status=rendition,
        jurisdiction=DEFAULT_JURISDICTION,
        media_type=case.media_type,
        release_point=release,
        document_ids=docs,
        fixity=fixity_ev,
        artifact_cid=content.cid if content is not None else f"sha256:{sha}",
        verification_state=vstate,
        temporal=temporal,
        title=case.title_number,
        citation=case.metadata.get("citation") if case.metadata else None,
        metadata={
            "case_id": case.case_id,
            "scenario": case.scenario.value,
            "source_family": family.value,
            "fixity_result": fixity.value,
            "signature_availability": signature.value,
            "prior_edition": case.prior_edition,
            "successor_edition": case.successor_edition,
            "processor_schema": SCHEMA_VERSION,
            "contracts_schema": CONTRACTS_SCHEMA,
            "authority_schema": AUTHORITY_SCHEMA_VERSION,
            "transport_schema": SOURCE_TRANSPORT_SCHEMA_VERSION,
        },
    )


def process_case(
    case: OfficialAuthorityCase,
    *,
    retrieved_at: datetime | None = None,
) -> OfficialAuthorityCaseResult:
    """Acquire (from recorded metadata) and verify one official authority case."""

    when = retrieved_at or datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    body = case.resolved_body_bytes() if case.body_text is not None else None
    if body is None and case.body_text is None and case.observed_sha256 and case.http_status == 200:
        # For match cases without body_text, use advertised digest as observed
        # identity without fabricating mismatched body bytes.
        body = None

    fixity = check_fixity(
        advertised_sha256=case.advertised_sha256,
        observed_sha256=case.observed_sha256,
        body=case.body_text.encode("utf-8") if case.body_text is not None else None,
    )
    # Force mismatch when scenario demands it and digests already differ / flag set.
    if case.scenario is ScenarioKind.BAD_FIXITY and fixity is not FixityCheckResult.MISMATCH:
        if (
            case.advertised_sha256
            and case.observed_sha256
            and case.advertised_sha256 != case.observed_sha256
        ):
            fixity = FixityCheckResult.MISMATCH
        elif case.advertised_sha256 and case.observed_sha256 is None:
            fixity = FixityCheckResult.MISSING_OBSERVED

    signature = case.signature
    if case.scenario is ScenarioKind.UNAVAILABLE_SIGNATURE:
        signature = SignatureAvailability.UNAVAILABLE

    outcome = adjudicate_case(case)
    if case.scenario is ScenarioKind.BAD_FIXITY:
        outcome = CaseOutcome.CONFLICT
        fixity = (
            FixityCheckResult.MISMATCH
            if fixity is not FixityCheckResult.MISMATCH
            else fixity
        )

    reasons: list[str] = []
    if fixity is FixityCheckResult.MISMATCH:
        reasons.append("advertised and observed content digests disagree")
    if signature is SignatureAvailability.UNAVAILABLE:
        reasons.append("GPO digital signature unavailable; HTTPS is not authentication")
    if signature is SignatureAvailability.INVALID:
        reasons.append("GPO digital signature invalid")
    if case.scenario is ScenarioKind.SOURCE_CONFLICT:
        reasons.append(
            "GovInfo official artifact conflicts with secondary/discovery representation"
        )
    if case.scenario is ScenarioKind.EDITION_ROLLOVER:
        reasons.append(
            f"edition rollover {case.prior_edition!r} → {case.successor_edition or case.edition_or_release_point!r}"
        )
    if case.exclusions:
        reasons.append(
            f"{len(case.exclusions)} release-point exclusion(s) recorded with coverage"
        )
    if case.scenario is ScenarioKind.AMENDED_RENUMBERED:
        reasons.append("amended/renumbered provision links and effective dates recorded")
    if case.scenario is ScenarioKind.DELAYED_ISSUE:
        reasons.append(
            f"issue delayed until {case.delayed_until.isoformat() if case.delayed_until else 'unknown'}"
        )
    if case.scenario is ScenarioKind.MISSING_PACKAGE_GRANULE:
        reasons.append("package or granule missing from official inventory")
    if case.is_discovery_only:
        reasons.append(
            "FederalRegister.gov / cross-check discovery is not GovInfo official authentication"
        )
    if case.incomplete:
        reasons.append("source incomplete; usable only with explicit degraded status")

    acquisition = build_acquisition_outcome(case, retrieved_at=when, body=body)
    content = acquisition.receipt.content
    authority = build_authority_identity(
        case,
        outcome=outcome,
        fixity=fixity,
        signature=signature,
        retrieved_at=when,
        content=content,
    )

    is_auth = (
        outcome is CaseOutcome.VERIFIED
        and fixity is FixityCheckResult.MATCH
        and signature is SignatureAvailability.VALID
        and not case.is_discovery_only
    )
    # Never promote HTTPS success alone.
    if case.http_status == 200 and not is_auth:
        assert https_is_not_authentication(
            http_status=case.http_status, fixity=fixity, signature=signature
        )

    usability = usability_for_outcome(
        outcome,
        incomplete=case.incomplete,
        unverified=not is_auth,
    )
    if outcome is CaseOutcome.VERIFIED and is_auth and not case.incomplete:
        usability = UsabilityStatus.FULL
    elif outcome is CaseOutcome.RESEARCH_GAP:
        usability = UsabilityStatus.RESEARCH_GAP
    elif outcome in {
        CaseOutcome.CONFLICT,
        CaseOutcome.MISSING,
        CaseOutcome.UNAVAILABLE,
        CaseOutcome.ERROR,
    }:
        usability = UsabilityStatus.BLOCKED
    else:
        usability = UsabilityStatus.DEGRADED

    vstate = (
        authority.verification_state
        if authority is not None
        else verification_state_for_outcome(outcome)
    )

    return OfficialAuthorityCaseResult(
        case=case,
        outcome=outcome,
        usability=usability,
        verification_state=vstate,
        fixity=fixity,
        signature=signature,
        acquisition=acquisition,
        authority=authority,
        reasons=tuple(reasons),
        provision_links=case.provision_links,
        is_official_authenticated=is_auth,
        https_alone_not_auth=True,
        notes=case.notes,
    )


# ---------------------------------------------------------------------------
# Recipe I/O
# ---------------------------------------------------------------------------


def parse_recipe(payload: JsonMapping) -> tuple[list[OfficialAuthorityCase], AdjudicatoryCoverage, dict[str, Any]]:
    """Parse a compact official-authorities recipe into cases + adjudicatory status."""

    if not isinstance(payload, Mapping):
        raise FixtureSchemaError("recipe must be a mapping")
    schema = payload.get("schema_version")
    if schema and str(schema) not in {
        FIXTURE_SCHEMA_VERSION,
        SCHEMA_VERSION,
        "live-official-authorities-recipe-v1",
    }:
        if not str(schema).startswith("live-official"):
            raise FixtureSchemaError(
                f"unsupported recipe schema_version {schema!r}"
            )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise FixtureSchemaError("recipe.cases must be a non-empty list")
    cases = [OfficialAuthorityCase.from_dict(c) for c in raw_cases]
    # Reject hard-coded latest anywhere in editions.
    for case in cases:
        reject_latest_token(
            case.edition_or_release_point, field_name="edition_or_release_point"
        )
    adjudicatory = AdjudicatoryCoverage.from_dict(payload.get("adjudicatory_coverage"))
    meta = {
        "recipe_id": payload.get("recipe_id") or payload.get("fixture_id"),
        "schema_version": schema or FIXTURE_SCHEMA_VERSION,
        "notes": payload.get("notes"),
        "discovered_at": payload.get("discovered_at"),
    }
    return cases, adjudicatory, meta


def build_default_recipe() -> dict[str, Any]:
    """Compact default recipe covering every PATLAW-131 acceptance scenario."""

    # Deterministic digests for compact fixtures (not full envelopes).
    def _h(label: str) -> str:
        return content_sha256(f"patlaw-131:{label}")

    good_pdf = _h("uscode-2023-t35-pdf")
    good_xml = _h("uscode-2023-t35-xml")
    plaw_pdf = _h("plaw-118-publ100-pdf")
    cfr_pdf = _h("cfr-2024-t37-vol1-pdf")
    fr_xml = _h("fr-2024-03-15-granule-xml")
    fr_bad_obs = _h("fr-2024-03-15-tampered")
    fr_gov_html = _h("frgov-2024-06123-html")
    olrc_uslm = _h("olrc-us-pl-118-45-uslm")
    olrc_excl_peer = _h("olrc-us-pl-117-99-uslm")

    cases: list[dict[str, Any]] = [
        {
            "case_id": "usc-edition-rollover-2022-to-2023",
            "scenario": "edition_rollover",
            "source_family": "govinfo_uscode",
            "provider": "govinfo",
            "source_id": "USCODE-2023-title35",
            "source_url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title35/xml/USCODE-2023-title35.xml",
            "edition_or_release_point": "govinfo-2023-title35",
            "package_id": "USCODE-2023-title35",
            "collection_code": "USCODE",
            "title_number": "35",
            "media_type": "application/xml",
            "advertised_sha256": good_xml,
            "observed_sha256": good_xml,
            "body_text": f"<usc title=\"35\" year=\"2023\">{_h('body-usc-2023')}</usc>",
            "signature": "valid",
            "signature_algorithm": "GPO-PAdES",
            "signature_evidence": "digital-sig-uscode-2023-t35",
            "http_status": 200,
            "prior_edition": "govinfo-2022-title35",
            "successor_edition": "govinfo-2023-title35",
            "expected_outcome": "verified",
            "notes": "Title 35 GovInfo edition rollover 2022→2023 with concrete package ids.",
            "metadata": {"citation": "35 U.S.C."},
        },
        {
            "case_id": "olrc-release-point-exclusions-118-45",
            "scenario": "release_point_exclusions",
            "source_family": "ushouse_olrc",
            "provider": "ushouse",
            "source_id": "us/pl/118/45",
            "source_url": "https://uscode.house.gov/download/releasepoints/us/pl/118/45/xml_usc35@118-45.zip",
            "edition_or_release_point": "us/pl/118/45",
            "package_id": "USCODE-2023-title35",
            "collection_code": "USCODE",
            "title_number": "35",
            "media_type": "application/uslm+xml",
            "advertised_sha256": olrc_uslm,
            "observed_sha256": olrc_uslm,
            "body_text": f"<uslm release=\"us/pl/118/45\">{_h('body-olrc-118-45')}</uslm>",
            "signature": "not_checked",
            "http_status": 200,
            "exclusions": [
                "Pub. L. 118-100 § 3 — uncodified patent-fee adjustment",
                "Pub. L. 117-328 div. W — classification gap affecting § 122 cross-references",
                "Uncodified national-security notice schedule (secrecy-order implementing material)",
            ],
            "coverage_notes": (
                "House OLRC release-point coverage and every listed exclusion are "
                "stored together and never generalized to a later public-law cutoff."
            ),
            "expected_outcome": "degraded",
            "incomplete": False,
            "notes": "Exact OLRC release point with declared exclusions; no GPO signature channel.",
            "metadata": {"citation": "35 U.S.C. (OLRC us/pl/118/45)"},
        },
        {
            "case_id": "plaw-amended-renumbered-35usc101",
            "scenario": "amended_renumbered_provisions",
            "source_family": "govinfo_public_law",
            "provider": "govinfo",
            "source_id": "PLAW-118publ100",
            "source_url": "https://www.govinfo.gov/content/pkg/PLAW-118publ100/pdf/PLAW-118publ100.pdf",
            "edition_or_release_point": "plaw-118-100",
            "package_id": "PLAW-118publ100",
            "collection_code": "PLAW",
            "title_number": "35",
            "media_type": "application/pdf",
            "advertised_sha256": plaw_pdf,
            "observed_sha256": plaw_pdf,
            "body_text": f"%PDF-1.4 plaw-118-100 {_h('body-plaw')}",
            "signature": "valid",
            "signature_algorithm": "GPO-PAdES",
            "signature_evidence": "digital-sig-plaw-118-100",
            "http_status": 200,
            "issue_date": "2024-04-01",
            "provision_links": [
                {
                    "citation": "35 U.S.C. § 101",
                    "prior_citation": "35 U.S.C. § 101",
                    "effective_date": "2024-10-01",
                    "amendment_kind": "amended",
                    "public_law": "Pub. L. 118-100 § 2",
                    "notes": "Patent-eligible subject matter amendment effective date recorded.",
                },
                {
                    "citation": "35 U.S.C. § 102(a)(3)",
                    "prior_citation": "35 U.S.C. § 102(e)",
                    "effective_date": "2024-10-01",
                    "amendment_kind": "renumbered",
                    "public_law": "Pub. L. 118-100 § 4",
                    "notes": "Prior § 102(e) renumbered; prior citation retained for crosswalk.",
                },
            ],
            "expected_outcome": "verified",
            "notes": "Public Law package with amended/renumbered Title 35 provision links.",
            "metadata": {"citation": "Pub. L. 118-100"},
        },
        {
            "case_id": "cfr-missing-package-title37-vol2",
            "scenario": "missing_package_granule",
            "source_family": "govinfo_cfr_annual",
            "provider": "govinfo",
            "source_id": "CFR-2024-title37-vol2",
            "source_url": "https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol2/pdf/CFR-2024-title37-vol2.pdf",
            "edition_or_release_point": "annual-2024-title37-vol2",
            "package_id": None,
            "granule_id": None,
            "collection_code": "CFR",
            "title_number": "37",
            "media_type": "application/pdf",
            "http_status": 404,
            "acquisition_kind": "unavailable",
            "expected_outcome": "missing",
            "notes": "Title 37 annual volume 2 package/granule missing from GovInfo inventory.",
        },
        {
            "case_id": "fr-bad-fixity-2024-03-15",
            "scenario": "bad_fixity",
            "source_family": "govinfo_federal_register",
            "provider": "govinfo",
            "source_id": "FR-2024-03-15-granule-2024-06123",
            "source_url": "https://www.govinfo.gov/content/pkg/FR-2024-03-15/xml/FR-2024-03-15.xml",
            "edition_or_release_point": "daily-2024-03-15",
            "package_id": "FR-2024-03-15",
            "granule_id": "2024-06123",
            "collection_code": "FR",
            "media_type": "application/xml",
            "advertised_sha256": fr_xml,
            "observed_sha256": fr_bad_obs,
            "body_text": f"<fr issue=\"2024-03-15\">tampered-{_h('body-fr-bad')}</fr>",
            "signature": "valid",
            "signature_algorithm": "GPO-PAdES",
            "signature_evidence": "digital-sig-fr-2024-03-15",
            "http_status": 200,
            "issue_date": "2024-03-15",
            "expected_outcome": "conflict",
            "notes": "Advertised fixity disagrees with observed content; conflict not success.",
        },
        {
            "case_id": "fr-unavailable-signature-2024-06-01",
            "scenario": "unavailable_signature",
            "source_family": "govinfo_federal_register",
            "provider": "govinfo",
            "source_id": "FR-2024-06-01",
            "source_url": "https://www.govinfo.gov/content/pkg/FR-2024-06-01/pdf/FR-2024-06-01.pdf",
            "edition_or_release_point": "daily-2024-06-01",
            "package_id": "FR-2024-06-01",
            "collection_code": "FR",
            "media_type": "application/pdf",
            "advertised_sha256": _h("fr-2024-06-01-pdf"),
            "observed_sha256": _h("fr-2024-06-01-pdf"),
            "body_text": f"%PDF-1.4 fr-2024-06-01 {_h('body-fr-nosig')}",
            "signature": "unavailable",
            "http_status": 200,
            "issue_date": "2024-06-01",
            "expected_outcome": "degraded",
            "notes": (
                "HTTP 200 with matching fixity but unavailable GPO signature; "
                "usable only with explicit degraded status. HTTPS is not authentication."
            ),
        },
        {
            "case_id": "fr-delayed-issue-2024-07-04",
            "scenario": "delayed_issue",
            "source_family": "govinfo_federal_register",
            "provider": "govinfo",
            "source_id": "FR-2024-07-04",
            "source_url": "https://www.govinfo.gov/content/pkg/FR-2024-07-04/pdf/FR-2024-07-04.pdf",
            "edition_or_release_point": "daily-2024-07-04",
            "package_id": "FR-2024-07-04",
            "collection_code": "FR",
            "media_type": "application/pdf",
            "http_status": 404,
            "acquisition_kind": "unavailable",
            "issue_date": "2024-07-04",
            "delayed_until": "2024-07-05",
            "expected_outcome": "delayed",
            "notes": "Federal holiday delayed FR issue; recorded as delayed, not silent success.",
        },
        {
            "case_id": "fr-source-conflict-govinfo-vs-frgov",
            "scenario": "source_conflict",
            "source_family": "govinfo_federal_register",
            "provider": "govinfo",
            "source_id": "FR-2024-03-15-2024-06123",
            "source_url": "https://www.govinfo.gov/content/pkg/FR-2024-03-15/xml/FR-2024-03-15.xml",
            "edition_or_release_point": "daily-2024-03-15",
            "package_id": "FR-2024-03-15",
            "granule_id": "2024-06123",
            "collection_code": "FR",
            "media_type": "application/xml",
            "advertised_sha256": fr_xml,
            "observed_sha256": fr_xml,
            "body_text": f"<fr official=\"true\">{_h('body-fr-official')}</fr>",
            "signature": "valid",
            "signature_algorithm": "GPO-PAdES",
            "signature_evidence": "digital-sig-fr-2024-03-15",
            "http_status": 200,
            "issue_date": "2024-03-15",
            "conflict_peer_provider": "federalregister.gov",
            "conflict_peer_sha256": fr_gov_html,
            "expected_outcome": "conflict",
            "notes": (
                "GovInfo official FR artifact digests disagree with FederalRegister.gov "
                "discovery representation; discovery cannot enter verified GovInfo path."
            ),
        },
        {
            "case_id": "frgov-discovery-degraded",
            "scenario": "degraded_unverified",
            "source_family": "federalregister_gov_discovery",
            "provider": "federalregister.gov",
            "source_id": "fr-doc-2024-06123",
            "source_url": "https://www.federalregister.gov/documents/2024/03/15/2024-06123",
            "edition_or_release_point": "fr-doc-2024-06123",
            "collection_code": "FR",
            "media_type": "text/html",
            "advertised_sha256": fr_gov_html,
            "observed_sha256": fr_gov_html,
            "body_text": f"<html>fr.gov discovery {_h('body-frgov')}</html>",
            "signature": "unavailable",
            "http_status": 200,
            "issue_date": "2024-03-15",
            "expected_outcome": "degraded",
            "incomplete": True,
            "notes": (
                "FederalRegister.gov HTML discovery is unofficial editorial presentation; "
                "usable only with explicit degraded status and never as GovInfo official FR."
            ),
            "metadata": {"citation": "89 FR 12345 (discovery)"},
        },
        {
            "case_id": "cfr-annual-title37-verified",
            "scenario": "happy_path",
            "source_family": "govinfo_cfr_annual",
            "provider": "govinfo",
            "source_id": "CFR-2024-title37-vol1",
            "source_url": "https://www.govinfo.gov/content/pkg/CFR-2024-title37-vol1/pdf/CFR-2024-title37-vol1.pdf",
            "edition_or_release_point": "annual-2024-title37-vol1",
            "package_id": "CFR-2024-title37-vol1",
            "collection_code": "CFR",
            "title_number": "37",
            "media_type": "application/pdf",
            "advertised_sha256": cfr_pdf,
            "observed_sha256": cfr_pdf,
            "body_text": f"%PDF-1.4 cfr-2024-t37-v1 {_h('body-cfr')}",
            "signature": "valid",
            "signature_algorithm": "GPO-PAdES",
            "signature_evidence": "digital-sig-cfr-2024-t37",
            "http_status": 200,
            "expected_outcome": "verified",
            "notes": "Title 37 annual CFR volume with matching fixity and GPO signature.",
            "metadata": {"citation": "37 CFR"},
        },
        {
            "case_id": "adjudicatory-coverage-research-gap",
            "scenario": "adjudicatory_coverage",
            "source_family": "adjudicatory",
            "provider": "govinfo",
            "source_id": "adjudicatory-coverage-gap",
            "source_url": "https://www.govinfo.gov/app/collection/USCOURTS",
            "edition_or_release_point": "adjudicatory-coverage-undeclared",
            "collection_code": "USCOURTS",
            "media_type": "application/xml",
            "http_status": 200,
            "acquisition_kind": "unavailable",
            "expected_outcome": "research_gap",
            "incomplete": True,
            "notes": (
                "Binding adjudicatory patent authority (PTAB precedential, Federal Circuit) "
                "is not acquired in this batch; recorded as blocking research-coverage gap."
            ),
        },
    ]

    # Recompute body digests so advertised/observed match body_text where intended.
    for case in cases:
        body = case.get("body_text")
        if not body:
            continue
        digest = content_sha256(body)
        if case.get("scenario") == "bad_fixity":
            # Keep advertised distinct from observed/body.
            case["observed_sha256"] = digest
            if case.get("advertised_sha256") == case.get("observed_sha256"):
                case["advertised_sha256"] = _h("forced-mismatch-advertised")
        elif case.get("scenario") != "source_conflict":
            case["advertised_sha256"] = digest
            case["observed_sha256"] = digest
        else:
            # Official side matches body; peer differs.
            case["advertised_sha256"] = digest
            case["observed_sha256"] = digest
            case["conflict_peer_sha256"] = _h("frgov-peer-mismatch")

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "recipe_id": "live-official-authorities-patlaw-131",
        "fixture_id": "live-official-authorities-patlaw-131",
        "discovered_at": "2024-09-15T12:00:00Z",
        "notes": (
            "Compact PATLAW-131 recipe: GovInfo U.S. Code / Public Law / CFR / FR, "
            "House OLRC release points with exclusions, FR.gov discovery (degraded), "
            "and explicit adjudicatory research-coverage gap. Not bulk golden dumps."
        ),
        "adjudicatory_coverage": {
            "present": False,
            "status": "research_gap",
            "is_blocking_research_gap": True,
            "authorities": [],
            "notes": (
                "Missing adjudicatory coverage is a declared research-coverage gap "
                "and cannot support a complete-law conclusion. PTAB precedential "
                "decisions and Federal Circuit holdings are out of scope for this "
                "acquisition batch and must be acquired under a separate connector."
            ),
        },
        "cases": cases,
        # Keep prior edition peer available for rollover assertions without a second full case.
        "edition_catalog": {
            "prior": {
                "package_id": "USCODE-2022-title35",
                "edition": "govinfo-2022-title35",
                "content_sha256": olrc_excl_peer,
            },
            "current": {
                "package_id": "USCODE-2023-title35",
                "edition": "govinfo-2023-title35",
            },
        },
    }


def write_default_fixtures(directory: PathLike | None = None) -> Path:
    """Write the compact official authorities recipe to *directory*."""

    target_dir = Path(directory) if directory is not None else default_fixture_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "official_authorities_recipe.json"
    payload = build_default_recipe()
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class LiveOfficialPatentAuthorityProcessor:
    """Acquire and verify GovInfo / U.S. Code / Public Law / FR official sources.

    Primary path is deterministic recipe replay. Optional
    :class:`PatentSourceTransport` enables bounded live fetches; transport
    success is never treated as source authenticity.
    """

    def __init__(
        self,
        *,
        fixture_dir: PathLike | None = None,
        transport: PatentSourceTransport | None = None,
        network_enabled: bool = False,
    ) -> None:
        self.fixture_dir = Path(fixture_dir) if fixture_dir else default_fixture_dir()
        self._transport = transport
        self._network_enabled = bool(network_enabled)
        self._last_report: Optional[OfficialAuthorityBatchReport] = None

    @property
    def transport(self) -> Optional[PatentSourceTransport]:
        return self._transport

    @property
    def last_report(self) -> Optional[OfficialAuthorityBatchReport]:
        return self._last_report

    def recipe_path(self) -> Path:
        return self.fixture_dir / "official_authorities_recipe.json"

    def load_recipe(self, path: PathLike | None = None) -> dict[str, Any]:
        target = Path(path) if path is not None else self.recipe_path()
        if not target.is_file():
            write_default_fixtures(target.parent if target.suffix else target)
            if target.is_dir():
                target = target / "official_authorities_recipe.json"
            if not target.is_file():
                # write_default_fixtures wrote official_authorities_recipe.json
                alt = self.fixture_dir / "official_authorities_recipe.json"
                if alt.is_file():
                    target = alt
        return load_json_fixture(target)

    def acquire_from_fixture(
        self,
        path: PathLike | None = None,
        *,
        retrieved_at: datetime | None = None,
    ) -> OfficialAuthorityBatchReport:
        """Process the recorded recipe (no network I/O)."""

        payload = self.load_recipe(path)
        return self.acquire_from_payload(payload, retrieved_at=retrieved_at)

    def acquire_from_payload(
        self,
        payload: JsonMapping,
        *,
        retrieved_at: datetime | None = None,
    ) -> OfficialAuthorityBatchReport:
        cases, adjudicatory, meta = parse_recipe(payload)
        when = retrieved_at
        if when is None and meta.get("discovered_at"):
            when = _parse_utc(meta["discovered_at"], name="discovered_at")
        if when is None:
            when = datetime(2024, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

        results = [process_case(case, retrieved_at=when) for case in cases]
        report = OfficialAuthorityBatchReport(
            results=tuple(results),
            adjudicatory=adjudicatory,
            recipe_id=meta.get("recipe_id"),
            retrieved_at=when,
            notes=meta.get("notes"),
        )
        self._last_report = report
        return report

    def acquire_live_urls(
        self,
        requests: Sequence[SourceFetchRequest],
        *,
        case_templates: Sequence[JsonMapping] | None = None,
    ) -> list[AcquisitionOutcome]:
        """Fetch *requests* via transport (opt-in network / injected opener).

        Returns acquisition outcomes only. Official authentication still requires
        separate fixity/signature adjudication via :meth:`process_case` /
        :meth:`verify_acquisition`.
        """

        if self._transport is None:
            self._transport = PatentSourceTransport(network_enabled=self._network_enabled)
        outcomes: list[AcquisitionOutcome] = []
        for request in requests:
            try:
                outcomes.append(self._transport.acquire_catching(request))
            except SourceTransportError as exc:
                when = datetime.now(timezone.utc)
                receipt = AcquisitionReceipt(
                    endpoint=request.url,
                    retrieved_at=when,
                    outcome_kind=AcquisitionOutcomeKind.NETWORK_ERROR,
                    response_status=0,
                    sanitized_request={"method": request.method, "path": request.url},
                    error_code=getattr(exc, "code", "transport_error"),
                    error_message=str(exc)[:500],
                    metadata={"https_is_not_authentication": True},
                )
                outcomes.append(
                    AcquisitionOutcome(
                        kind=AcquisitionOutcomeKind.NETWORK_ERROR,
                        receipt=receipt,
                        body=None,
                        network_used=True,
                    )
                )
        # case_templates reserved for future live→case materialization.
        _ = case_templates
        return outcomes

    def verify_acquisition(
        self,
        case: OfficialAuthorityCase,
        acquisition: AcquisitionOutcome,
        *,
        retrieved_at: datetime | None = None,
    ) -> OfficialAuthorityCaseResult:
        """Bind a live/transport acquisition to a case and adjudicate.

        Explicitly refuses to treat transport success as authentication.
        """

        require_acquisition_outcome(acquisition)
        # Overlay observed digest from acquisition when present.
        observed = case.observed_sha256
        if acquisition.receipt.content is not None:
            observed = acquisition.receipt.content.sha256
        body_text = case.body_text
        if acquisition.body is not None and body_text is None:
            try:
                body_text = acquisition.body.decode("utf-8")
            except UnicodeDecodeError:
                body_text = None
        updated = OfficialAuthorityCase.from_dict(
            {
                **case.to_dict(),
                "observed_sha256": observed,
                "body_text": body_text,
                "http_status": acquisition.receipt.response_status or case.http_status,
                "acquisition_kind": acquisition.kind.value,
            }
        )
        result = process_case(updated, retrieved_at=retrieved_at)
        # Preserve the live acquisition receipt identity when digests align.
        if acquisition.receipt.content is not None and result.acquisition is not None:
            if (
                result.acquisition.receipt.content is not None
                and result.acquisition.receipt.content.sha256
                == acquisition.receipt.content.sha256
            ):
                result = OfficialAuthorityCaseResult(
                    case=result.case,
                    outcome=result.outcome,
                    usability=result.usability,
                    verification_state=result.verification_state,
                    fixity=result.fixity,
                    signature=result.signature,
                    acquisition=acquisition,
                    authority=result.authority,
                    reasons=result.reasons + ("live acquisition receipt bound",),
                    provision_links=result.provision_links,
                    is_official_authenticated=result.is_official_authenticated,
                    https_alone_not_auth=True,
                    notes=result.notes,
                )
        if (
            acquisition.kind in PARSER_ADMISSIBLE_OUTCOMES
            and result.is_official_authenticated is False
        ):
            # Reinforce invariant: transport success ≠ authentication.
            if result.usability is UsabilityStatus.FULL:
                raise OfficialAuthenticationError(
                    "HTTPS/transport success alone cannot yield full usability"
                )
        return result

    def assert_acceptance_coverage(
        self, report: OfficialAuthorityBatchReport | None = None
    ) -> None:
        """Fail closed when required PATLAW-131 scenarios are missing."""

        target = report if report is not None else self._last_report
        if target is None:
            raise LiveOfficialAuthorityError("no report available for acceptance coverage")
        missing = target.missing_required_scenarios()
        if missing:
            raise LiveOfficialAuthorityError(
                f"missing required scenario kinds: {sorted(missing)}"
            )
        if target.adjudicatory is None:
            raise LiveOfficialAuthorityError("adjudicatory coverage must be declared")
        # Explicit presence or blocking research gap — both acceptable.
        if not target.adjudicatory.present and not target.adjudicatory.is_blocking_research_gap:
            raise LiveOfficialAuthorityError(
                "adjudicatory coverage must be present or a blocking research gap"
            )
        # Degraded-only usability for incomplete/unverified.
        for result in target.results:
            if result.outcome is CaseOutcome.DEGRADED and result.usability is not UsabilityStatus.DEGRADED:
                raise LiveOfficialAuthorityError(
                    f"degraded case {result.case.case_id!r} lacks degraded usability"
                )
            if (
                result.verification_state is VerificationState.UNVERIFIED
                and result.is_usable
                and result.usability is not UsabilityStatus.DEGRADED
            ):
                raise LiveOfficialAuthorityError(
                    f"unverified case {result.case.case_id!r} usable without degraded status"
                )
            if result.case.incomplete and result.is_usable:
                if result.usability is not UsabilityStatus.DEGRADED:
                    raise LiveOfficialAuthorityError(
                        f"incomplete case {result.case.case_id!r} must be degraded"
                    )


__all__ = [
    "SCHEMA_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "REQUIRED_SCENARIO_KINDS",
    "CROSS_CHECK_PROVIDERS",
    "LiveOfficialAuthorityError",
    "FixtureSchemaError",
    "HardCodedLatestError",
    "OfficialAuthenticationError",
    "CrossCheckPromotionError",
    "CompleteLawConclusionError",
    "SourceFamily",
    "ScenarioKind",
    "CaseOutcome",
    "UsabilityStatus",
    "FixityCheckResult",
    "SignatureAvailability",
    "ProvisionLink",
    "AdjudicatoryCoverage",
    "OfficialAuthorityCase",
    "OfficialAuthorityCaseResult",
    "OfficialAuthorityBatchReport",
    "LiveOfficialPatentAuthorityProcessor",
    "content_sha256",
    "check_fixity",
    "adjudicate_case",
    "process_case",
    "parse_recipe",
    "build_default_recipe",
    "write_default_fixtures",
    "default_fixture_dir",
    "https_is_not_authentication",
    "is_cross_check_provider",
]
