"""Patent authority contracts v2 — independent kind, tier, rendition, and acquisition gates.

Shared by live CFR, GovInfo, Federal Register, and USPTO guidance processors
(PATLAW-127 / PATLAW-G112). Design invariants:

* Authority *kind*, *tier*, and *rendition legal status* are independent fields.
  Statute, regulation, adjudicatory authority, guidance, editorial aid, and
  extracted candidates cannot collapse into one tier.
* Every parser input must carry an :class:`AcquisitionOutcome`; bytes alone
  are never admitted.
* Identity requires provider, source id, content digests, jurisdiction,
  edition/release point (never hard-coded ``latest``), package/granule ids,
  media type, signature/fixity evidence, and full temporal roles.
* Serialization is deterministic for content-addressed receipts and fixtures.
* No network I/O occurs on import or serialization.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Optional, Sequence

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    VerificationState,
    reject_hard_coded_latest,
)

SCHEMA_VERSION: Final = "patent-authority-contracts-v2"
ACQUISITION_OUTCOME_SCHEMA: Final = "patent-acquisition-outcome-v1"
PARSER_INPUT_SCHEMA: Final = "patent-parser-input-v1"
AUTHORITY_IDENTITY_SCHEMA: Final = "patent-authority-identity-v2"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LATEST_TOKEN_RE = re.compile(r"^\s*latest\s*$", re.IGNORECASE)
_CID_RE = re.compile(r"^(baf[a-z2-7]{50,}|sha256:[0-9a-f]{64})$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PatentAuthorityContractsV2Error(ValueError):
    """Base error for authority contract v2 violations."""


class MissingAcquisitionOutcomeError(PatentAuthorityContractsV2Error):
    """Raised when parser input lacks a required acquisition outcome."""


class AuthorityDimensionCollapseError(PatentAuthorityContractsV2Error):
    """Raised when kind/tier/rendition dimensions are collapsed or inconsistent."""


class MissingRequiredIdentityFieldError(PatentAuthorityContractsV2Error):
    """Raised when a required identity field is absent."""


# ---------------------------------------------------------------------------
# Independent authority dimensions (cannot collapse into one tier)
# ---------------------------------------------------------------------------


class AuthorityKind(str, Enum):
    """Closed set of legal authority kinds (independent of tier).

    Values align with source-authority policy ``authority_kinds`` while
    providing the six non-collapsible acceptance classes: statute, regulation,
    adjudicatory authority, guidance, editorial aid, extracted candidate.
    """

    ENACTED_STATUTE_AT_LARGE = "enacted_statute_at_large"
    CODIFIED_STATUTE = "codified_statute"
    PROMULGATED_REGULATION = "promulgated_regulation"
    BINDING_ADJUDICATORY_AUTHORITY = "binding_adjudicatory_authority"
    OFFICIAL_AGENCY_GUIDANCE = "official_agency_guidance"
    UNOFFICIAL_EDITORIAL_AID = "unofficial_editorial_aid"
    EXTRACTED_CANDIDATE = "extracted_candidate"

    @property
    def acceptance_class(self) -> str:
        """Coarse acceptance class used for non-collapse proofs."""

        return _KIND_TO_ACCEPTANCE_CLASS[self]


class RenditionLegalStatus(str, Enum):
    """Legal status of the retrieved rendition (independent of kind/tier)."""

    OFFICIAL_ELECTRONIC = "official_electronic"
    OFFICIAL_PRINT_EQUIVALENT = "official_print_equivalent"
    OFFICIAL_SOURCE_ARTIFACT = "official_source_artifact"
    UNOFFICIAL_EDITORIAL_PRESENTATION = "unofficial_editorial_presentation"
    DERIVED_MATERIALIZATION = "derived_materialization"
    CANDIDATE_ONLY = "candidate_only"


class TemporalRole(str, Enum):
    """Distinct temporal roles; must not be conflated."""

    EDITION = "edition"
    ENACTMENT = "enactment"
    DATE_ISSUED = "date_issued"
    PUBLICATION = "publication"
    EFFECTIVE = "effective"
    APPLICABILITY = "applicability"
    COMPLIANCE = "compliance"
    TERMINATION = "termination"
    MAILING_OR_NOTIFICATION = "mailing_or_notification"
    SUBMISSION = "submission"
    RECEIPT = "receipt"
    OFFICIAL_FILING = "official_filing"
    PROPOSED_RESPONSE = "proposed_response"
    UPSTREAM_LAST_MODIFIED = "upstream_last_modified"
    RETRIEVAL = "retrieval"


class AcquisitionOutcomeKind(str, Enum):
    """Terminal acquisition classification for one fetch attempt."""

    FETCHED = "fetched"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    TRUNCATED = "truncated"
    MISLABELED = "mislabeled"
    THROTTLED = "throttled"
    UNAVAILABLE = "unavailable"
    POLICY_REJECTED = "policy_rejected"
    SIZE_EXCEEDED = "size_exceeded"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    CANCELLED = "cancelled"


# Six non-collapsible acceptance classes from PATLAW-127 acceptance.
ACCEPTANCE_AUTHORITY_CLASSES: Final = frozenset(
    {
        "statute",
        "regulation",
        "adjudicatory_authority",
        "guidance",
        "editorial_aid",
        "extracted_candidate",
    }
)

_KIND_TO_ACCEPTANCE_CLASS: Final[Mapping[AuthorityKind, str]] = MappingProxyType(
    {
        AuthorityKind.ENACTED_STATUTE_AT_LARGE: "statute",
        AuthorityKind.CODIFIED_STATUTE: "statute",
        AuthorityKind.PROMULGATED_REGULATION: "regulation",
        AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY: "adjudicatory_authority",
        AuthorityKind.OFFICIAL_AGENCY_GUIDANCE: "guidance",
        AuthorityKind.UNOFFICIAL_EDITORIAL_AID: "editorial_aid",
        AuthorityKind.EXTRACTED_CANDIDATE: "extracted_candidate",
    }
)

# Recommended default tier per kind — never a substitute for the kind itself.
_DEFAULT_TIER_FOR_KIND: Final[Mapping[AuthorityKind, AuthorityTier]] = MappingProxyType(
    {
        AuthorityKind.ENACTED_STATUTE_AT_LARGE: AuthorityTier.OFFICIAL_BASE,
        AuthorityKind.CODIFIED_STATUTE: AuthorityTier.OFFICIAL_BASE,
        AuthorityKind.PROMULGATED_REGULATION: AuthorityTier.OFFICIAL_BASE,
        AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY: AuthorityTier.OFFICIAL_CHANGE,
        AuthorityKind.OFFICIAL_AGENCY_GUIDANCE: AuthorityTier.GUIDANCE,
        AuthorityKind.UNOFFICIAL_EDITORIAL_AID: AuthorityTier.UNOFFICIAL_CURRENT,
        AuthorityKind.EXTRACTED_CANDIDATE: AuthorityTier.CANDIDATE,
    }
)

# Compatible (not exclusive) tier sets per kind for soft validation.
_COMPATIBLE_TIERS: Final[Mapping[AuthorityKind, frozenset[AuthorityTier]]] = MappingProxyType(
    {
        AuthorityKind.ENACTED_STATUTE_AT_LARGE: frozenset(
            {AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE}
        ),
        AuthorityKind.CODIFIED_STATUTE: frozenset(
            {AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE}
        ),
        AuthorityKind.PROMULGATED_REGULATION: frozenset(
            {
                AuthorityTier.OFFICIAL_BASE,
                AuthorityTier.OFFICIAL_CHANGE,
                AuthorityTier.UNOFFICIAL_CURRENT,
            }
        ),
        AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY: frozenset(
            {AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE}
        ),
        AuthorityKind.OFFICIAL_AGENCY_GUIDANCE: frozenset({AuthorityTier.GUIDANCE}),
        AuthorityKind.UNOFFICIAL_EDITORIAL_AID: frozenset(
            {AuthorityTier.UNOFFICIAL_CURRENT, AuthorityTier.GUIDANCE}
        ),
        AuthorityKind.EXTRACTED_CANDIDATE: frozenset({AuthorityTier.CANDIDATE}),
    }
)

# Compatible rendition statuses per kind (soft validation).
_COMPATIBLE_RENDITIONS: Final[
    Mapping[AuthorityKind, frozenset[RenditionLegalStatus]]
] = MappingProxyType(
    {
        AuthorityKind.ENACTED_STATUTE_AT_LARGE: frozenset(
            {
                RenditionLegalStatus.OFFICIAL_ELECTRONIC,
                RenditionLegalStatus.OFFICIAL_PRINT_EQUIVALENT,
                RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
            }
        ),
        AuthorityKind.CODIFIED_STATUTE: frozenset(
            {
                RenditionLegalStatus.OFFICIAL_ELECTRONIC,
                RenditionLegalStatus.OFFICIAL_PRINT_EQUIVALENT,
                RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
            }
        ),
        AuthorityKind.PROMULGATED_REGULATION: frozenset(
            {
                RenditionLegalStatus.OFFICIAL_ELECTRONIC,
                RenditionLegalStatus.OFFICIAL_PRINT_EQUIVALENT,
                RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
                RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION,
            }
        ),
        AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY: frozenset(
            {
                RenditionLegalStatus.OFFICIAL_ELECTRONIC,
                RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
            }
        ),
        AuthorityKind.OFFICIAL_AGENCY_GUIDANCE: frozenset(
            {
                RenditionLegalStatus.OFFICIAL_ELECTRONIC,
                RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
                RenditionLegalStatus.DERIVED_MATERIALIZATION,
            }
        ),
        AuthorityKind.UNOFFICIAL_EDITORIAL_AID: frozenset(
            {
                RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION,
                RenditionLegalStatus.DERIVED_MATERIALIZATION,
            }
        ),
        AuthorityKind.EXTRACTED_CANDIDATE: frozenset(
            {RenditionLegalStatus.CANDIDATE_ONLY, RenditionLegalStatus.DERIVED_MATERIALIZATION}
        ),
    }
)

# Successful outcomes that may admit bytes to a parser (still require outcome object).
PARSER_ADMISSIBLE_OUTCOMES: Final = frozenset(
    {
        AcquisitionOutcomeKind.FETCHED,
        AcquisitionOutcomeKind.CHANGED,
        AcquisitionOutcomeKind.UNCHANGED,
    }
)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatentAuthorityContractsV2Error(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PatentAuthorityContractsV2Error(f"{name} must not contain NUL")
    return value.strip()


def _optional_str(value: Any, name: str) -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_sha256(value: Any, name: str = "sha256") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PatentAuthorityContractsV2Error(
            f"{name} must be a lowercase 64-char hex SHA-256"
        )
    return text


def _require_cid(value: Any, name: str = "cid") -> str:
    text = _require_non_empty_str(value, name).lower()
    if not _CID_RE.fullmatch(text):
        raise PatentAuthorityContractsV2Error(
            f"{name} must be a CIDv1 base32 (bafk…) or sha256:<hex> content address"
        )
    return text


def _parse_utc_datetime(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PatentAuthorityContractsV2Error(
                f"{name} must be an ISO-8601 datetime"
            ) from exc
    else:
        raise PatentAuthorityContractsV2Error(
            f"{name} must be a datetime or ISO-8601 string"
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
            raise PatentAuthorityContractsV2Error(f"{name} must be an ISO date") from exc
    raise PatentAuthorityContractsV2Error(f"{name} must be a date or ISO date string")


def _date_to_str(value: Optional[date]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _deep_sorted_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(value.keys(), key=lambda k: str(k)):
        item = value[key]
        if isinstance(item, Mapping):
            out[str(key)] = _deep_sorted_mapping(item)
        elif isinstance(item, (list, tuple)):
            out[str(key)] = [
                _deep_sorted_mapping(v) if isinstance(v, Mapping) else v for v in item
            ]
        else:
            out[str(key)] = item
    return out


def canonical_json_dumps(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON text for fixtures and content addressing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return canonical_json_dumps(payload).encode("utf-8")


def content_address_bytes(data: bytes) -> "ContentAddress":
    """Return SHA-256 + CID for *data* (stdlib + multiformats when available)."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise PatentAuthorityContractsV2Error("data must be bytes-like")
    raw = bytes(data)
    sha = hashlib.sha256(raw).hexdigest()
    cid: str
    try:
        from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

        cid = str(cid_for_bytes(raw))
    except Exception:  # noqa: BLE001 — fail soft to sha256 address
        cid = f"sha256:{sha}"
    return ContentAddress(sha256=sha, cid=cid, byte_size=len(raw))


def content_address_mapping(payload: Mapping[str, Any]) -> "ContentAddress":
    return content_address_bytes(canonical_json_bytes(payload))


def _coerce_enum(enum_cls: type[Enum], value: Any, *, name: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PatentAuthorityContractsV2Error(f"{name} is required")
    if isinstance(value, str):
        text = value.strip().lower().replace("-", "_")
        # Also try hyphenated policy forms.
        hyphen = value.strip().lower().replace("_", "-")
        for member in enum_cls:
            mv = member.value
            if mv == value.strip() or mv == text or mv == hyphen:
                return member
            if member.name.lower() == text:
                return member
            # value may use hyphens while member.value uses underscores or vice versa
            if mv.replace("-", "_") == text or mv.replace("_", "-") == hyphen:
                return member
        allowed = [m.value for m in enum_cls]
        raise PatentAuthorityContractsV2Error(
            f"unknown {name} {value!r}; expected one of {allowed}"
        )
    raise PatentAuthorityContractsV2Error(f"{name} is required")


def coerce_authority_kind(value: Any) -> AuthorityKind:
    return _coerce_enum(AuthorityKind, value, name="authority_kind")  # type: ignore[return-value]


def coerce_authority_tier(value: Any) -> AuthorityTier:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PatentAuthorityContractsV2Error("authority_tier is required")
    if isinstance(value, AuthorityTier):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("_", "-")
        for tier in AuthorityTier:
            if tier.value == normalized or tier.name.lower().replace("_", "-") == normalized:
                return tier
        raise PatentAuthorityContractsV2Error(
            f"unknown authority_tier {value!r}; expected one of "
            f"{[t.value for t in AuthorityTier]}"
        )
    raise PatentAuthorityContractsV2Error("authority_tier is required")


def coerce_rendition_legal_status(value: Any) -> RenditionLegalStatus:
    return _coerce_enum(  # type: ignore[return-value]
        RenditionLegalStatus, value, name="rendition_legal_status"
    )


def coerce_acquisition_outcome_kind(value: Any) -> AcquisitionOutcomeKind:
    return _coerce_enum(  # type: ignore[return-value]
        AcquisitionOutcomeKind, value, name="outcome_kind"
    )


def coerce_verification_state(value: Any) -> VerificationState:
    if value is None:
        return VerificationState.UNVERIFIED
    if isinstance(value, VerificationState):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        for state in VerificationState:
            if state.value == normalized or state.name.lower() == normalized:
                return state
    raise PatentAuthorityContractsV2Error(f"unknown verification_state: {value!r}")


def default_tier_for_kind(kind: AuthorityKind | str) -> AuthorityTier:
    """Return the recommended default tier for *kind* (kind remains independent)."""

    resolved = coerce_authority_kind(kind)
    return _DEFAULT_TIER_FOR_KIND[resolved]


def acceptance_class_for_kind(kind: AuthorityKind | str) -> str:
    return coerce_authority_kind(kind).acceptance_class


def assert_dimensions_independent(
    *,
    authority_kind: AuthorityKind | str,
    authority_tier: AuthorityTier | str,
    rendition_legal_status: RenditionLegalStatus | str,
    allow_incompatible: bool = False,
) -> tuple[AuthorityKind, AuthorityTier, RenditionLegalStatus]:
    """Validate that kind/tier/rendition are present and not collapsed.

    Collapsing means treating kind as interchangeable with tier (e.g. forcing
    every kind onto a single shared tier token) or assigning an incompatible
    tier/rendition that would erase kind semantics.
    """

    kind = coerce_authority_kind(authority_kind)
    tier = coerce_authority_tier(authority_tier)
    rendition = coerce_rendition_legal_status(rendition_legal_status)

    if not allow_incompatible:
        if tier not in _COMPATIBLE_TIERS[kind]:
            raise AuthorityDimensionCollapseError(
                f"authority_tier={tier.value!r} is incompatible with "
                f"authority_kind={kind.value!r}; kind and tier must remain "
                f"independent and kind-preserving (compatible tiers: "
                f"sorted({[t.value for t in _COMPATIBLE_TIERS[kind]]}))"
            )
        if rendition not in _COMPATIBLE_RENDITIONS[kind]:
            raise AuthorityDimensionCollapseError(
                f"rendition_legal_status={rendition.value!r} is incompatible "
                f"with authority_kind={kind.value!r}"
            )

    # Explicit non-collapse: guidance kind cannot be recorded as official-base
    # via "everything is official-base" collapse, etc. — already covered above.

    # Extracted candidates must never wear official renditions.
    if kind is AuthorityKind.EXTRACTED_CANDIDATE and rendition in {
        RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        RenditionLegalStatus.OFFICIAL_PRINT_EQUIVALENT,
        RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
    }:
        raise AuthorityDimensionCollapseError(
            "extracted_candidate cannot carry an official rendition legal status"
        )

    # Editorial aid cannot be labelled official-base tier.
    if (
        kind is AuthorityKind.UNOFFICIAL_EDITORIAL_AID
        and tier in {AuthorityTier.OFFICIAL_BASE, AuthorityTier.OFFICIAL_CHANGE}
    ):
        raise AuthorityDimensionCollapseError(
            "unofficial editorial aid cannot collapse into an official tier"
        )

    return kind, tier, rendition


def non_collapsible_acceptance_matrix() -> dict[str, dict[str, str]]:
    """Return one representative (kind, tier, rendition) per acceptance class.

    Used by tests to prove the six classes remain distinct under serialization.
    """

    representatives: dict[AuthorityKind, tuple[AuthorityTier, RenditionLegalStatus]] = {
        AuthorityKind.CODIFIED_STATUTE: (
            AuthorityTier.OFFICIAL_BASE,
            RenditionLegalStatus.OFFICIAL_SOURCE_ARTIFACT,
        ),
        AuthorityKind.PROMULGATED_REGULATION: (
            AuthorityTier.OFFICIAL_BASE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        ),
        AuthorityKind.BINDING_ADJUDICATORY_AUTHORITY: (
            AuthorityTier.OFFICIAL_CHANGE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        ),
        AuthorityKind.OFFICIAL_AGENCY_GUIDANCE: (
            AuthorityTier.GUIDANCE,
            RenditionLegalStatus.OFFICIAL_ELECTRONIC,
        ),
        AuthorityKind.UNOFFICIAL_EDITORIAL_AID: (
            AuthorityTier.UNOFFICIAL_CURRENT,
            RenditionLegalStatus.UNOFFICIAL_EDITORIAL_PRESENTATION,
        ),
        AuthorityKind.EXTRACTED_CANDIDATE: (
            AuthorityTier.CANDIDATE,
            RenditionLegalStatus.CANDIDATE_ONLY,
        ),
    }
    out: dict[str, dict[str, str]] = {}
    for kind, (tier, rendition) in representatives.items():
        assert_dimensions_independent(
            authority_kind=kind,
            authority_tier=tier,
            rendition_legal_status=rendition,
        )
        cls = kind.acceptance_class
        out[cls] = {
            "authority_kind": kind.value,
            "authority_tier": tier.value,
            "rendition_legal_status": rendition.value,
            "acceptance_class": cls,
        }
    if set(out) != ACCEPTANCE_AUTHORITY_CLASSES:
        raise PatentAuthorityContractsV2Error(
            f"acceptance matrix incomplete: {sorted(out)} != "
            f"{sorted(ACCEPTANCE_AUTHORITY_CLASSES)}"
        )
    return out


# ---------------------------------------------------------------------------
# Content address
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContentAddress:
    """Content-addressed identity for bytes or a canonical JSON payload."""

    sha256: str
    cid: str
    byte_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(self, "cid", _require_cid(self.cid, "cid"))
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool):
            raise PatentAuthorityContractsV2Error("byte_size must be an int")
        if self.byte_size < 0:
            raise PatentAuthorityContractsV2Error("byte_size must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": int(self.byte_size),
            "cid": self.cid,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContentAddress":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error("content address must be a mapping")
        return cls(
            sha256=value["sha256"],
            cid=value["cid"],
            byte_size=int(value["byte_size"]),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ContentAddress":
        return content_address_bytes(data)


# ---------------------------------------------------------------------------
# Identity components
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentPackageGranuleIds:
    """Document / package / granule identifiers for GovInfo-style sources."""

    document_id: Optional[str] = None
    package_id: Optional[str] = None
    granule_id: Optional[str] = None
    collection_code: Optional[str] = None
    title_number: Optional[str] = None
    part_or_section: Optional[str] = None

    def __post_init__(self) -> None:
        for name in (
            "document_id",
            "package_id",
            "granule_id",
            "collection_code",
            "title_number",
            "part_or_section",
        ):
            raw = getattr(self, name)
            if raw is not None:
                cleaned = _require_non_empty_str(raw, name)
                reject_hard_coded_latest(cleaned, field_name=name)
                object.__setattr__(self, name, cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_code": self.collection_code,
            "document_id": self.document_id,
            "granule_id": self.granule_id,
            "package_id": self.package_id,
            "part_or_section": self.part_or_section,
            "title_number": self.title_number,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "DocumentPackageGranuleIds":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "document_package_granule_ids must be a mapping"
            )
        known = {f.name for f in fields(cls)}
        return cls(**{k: value.get(k) for k in known})


@dataclass(frozen=True, slots=True)
class ReleasePointExclusions:
    """Edition/release-point identity plus explicit coverage exclusions.

    House OLRC / CFR release points must store exclusions alongside the
    release point so coverage is never generalized to a later cutoff.
    """

    edition_or_release_point: str
    exclusions: tuple[str, ...] = ()
    coverage_notes: Optional[str] = None

    def __post_init__(self) -> None:
        point = _require_non_empty_str(
            self.edition_or_release_point, "edition_or_release_point"
        )
        reject_hard_coded_latest(point, field_name="edition_or_release_point")
        if _LATEST_TOKEN_RE.fullmatch(point):
            raise HardCodedLatestEditionError(
                "edition_or_release_point must not be the hard-coded token 'latest'"
            )
        object.__setattr__(self, "edition_or_release_point", point)
        cleaned: list[str] = []
        for item in self.exclusions:
            text = _require_non_empty_str(item, "exclusions[]")
            reject_hard_coded_latest(text, field_name="exclusions[]")
            cleaned.append(text)
        object.__setattr__(self, "exclusions", tuple(cleaned))
        if self.coverage_notes is not None:
            object.__setattr__(
                self,
                "coverage_notes",
                _require_non_empty_str(self.coverage_notes, "coverage_notes"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_notes": self.coverage_notes,
            "edition_or_release_point": self.edition_or_release_point,
            "exclusions": list(self.exclusions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReleasePointExclusions":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "release_point_exclusions must be a mapping"
            )
        raw_excl = value.get("exclusions") or ()
        if not isinstance(raw_excl, (list, tuple)):
            raise PatentAuthorityContractsV2Error("exclusions must be a sequence")
        return cls(
            edition_or_release_point=value["edition_or_release_point"],
            exclusions=tuple(raw_excl),
            coverage_notes=value.get("coverage_notes"),
        )


@dataclass(frozen=True, slots=True)
class SignatureFixityEvidence:
    """Separate digital fixity/authentication evidence (not human print attestation)."""

    content_sha256: str
    content_cid: Optional[str] = None
    signature_present: bool = False
    signature_valid: Optional[bool] = None
    signature_algorithm: Optional[str] = None
    signature_evidence: Optional[str] = None
    media_signature: Optional[str] = None
    authenticated_by: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "content_sha256",
            _require_sha256(self.content_sha256, "content_sha256"),
        )
        if self.content_cid is not None:
            object.__setattr__(
                self, "content_cid", _require_cid(self.content_cid, "content_cid")
            )
        for name in (
            "signature_algorithm",
            "signature_evidence",
            "media_signature",
            "authenticated_by",
        ):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "authenticated_by": self.authenticated_by,
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "media_signature": self.media_signature,
            "signature_algorithm": self.signature_algorithm,
            "signature_evidence": self.signature_evidence,
            "signature_present": bool(self.signature_present),
            "signature_valid": self.signature_valid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignatureFixityEvidence":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "signature_or_fixity_evidence must be a mapping"
            )
        return cls(
            content_sha256=value["content_sha256"],
            content_cid=value.get("content_cid"),
            signature_present=bool(value.get("signature_present", False)),
            signature_valid=value.get("signature_valid"),
            signature_algorithm=value.get("signature_algorithm"),
            signature_evidence=value.get("signature_evidence"),
            media_signature=value.get("media_signature"),
            authenticated_by=value.get("authenticated_by"),
        )

    @classmethod
    def from_content_address(
        cls,
        address: ContentAddress,
        *,
        signature_present: bool = False,
        signature_valid: Optional[bool] = None,
        signature_algorithm: Optional[str] = None,
        signature_evidence: Optional[str] = None,
    ) -> "SignatureFixityEvidence":
        return cls(
            content_sha256=address.sha256,
            content_cid=address.cid,
            signature_present=signature_present,
            signature_valid=signature_valid,
            signature_algorithm=signature_algorithm,
            signature_evidence=signature_evidence,
        )


@dataclass(frozen=True, slots=True)
class TemporalRoleAssignment:
    """One dated (or datetime) assignment for a single temporal role."""

    role: TemporalRole
    value: Optional[str] = None  # ISO date or datetime string

    def __post_init__(self) -> None:
        if not isinstance(self.role, TemporalRole):
            object.__setattr__(
                self,
                "role",
                _coerce_enum(TemporalRole, self.role, name="role"),
            )
        if self.value is not None:
            text = _require_non_empty_str(self.value, "value")
            # Accept date or datetime.
            try:
                if "T" in text or text.endswith("Z") or "+" in text[10:]:
                    _parse_utc_datetime(text, name="value")
                else:
                    _parse_optional_date(text, name="value")
            except PatentAuthorityContractsV2Error:
                raise
            object.__setattr__(self, "value", text)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role.value, "value": self.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TemporalRoleAssignment":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "temporal role assignment must be a mapping"
            )
        return cls(role=value["role"], value=value.get("value"))


@dataclass(frozen=True, slots=True)
class TemporalRoleSet:
    """Full temporal-role contract; roles remain distinct keys."""

    assignments: Mapping[str, Optional[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.assignments, Mapping):
            raise PatentAuthorityContractsV2Error("assignments must be a mapping")
        normalized: dict[str, Optional[str]] = {}
        for key, value in self.assignments.items():
            role = _coerce_enum(TemporalRole, key, name="temporal_role")
            if value is None or value == "":
                normalized[role.value] = None
            else:
                text = _require_non_empty_str(value, f"temporal.{role.value}")
                # Validate shape.
                if "T" in text or text.endswith("Z"):
                    _parse_utc_datetime(text, name=f"temporal.{role.value}")
                else:
                    _parse_optional_date(text, name=f"temporal.{role.value}")
                normalized[role.value] = text
        object.__setattr__(self, "assignments", MappingProxyType(normalized))

    def get(self, role: TemporalRole | str) -> Optional[str]:
        resolved = (
            role if isinstance(role, TemporalRole) else _coerce_enum(TemporalRole, role, name="role")
        )
        return self.assignments.get(resolved.value)

    def with_role(
        self, role: TemporalRole | str, value: Optional[str]
    ) -> "TemporalRoleSet":
        resolved = (
            role if isinstance(role, TemporalRole) else _coerce_enum(TemporalRole, role, name="role")
        )
        updated = dict(self.assignments)
        updated[resolved.value] = value
        return TemporalRoleSet(assignments=updated)

    def require_roles(self, *roles: TemporalRole | str) -> None:
        missing = []
        for role in roles:
            resolved = (
                role
                if isinstance(role, TemporalRole)
                else _coerce_enum(TemporalRole, role, name="role")
            )
            if not self.assignments.get(resolved.value):
                missing.append(resolved.value)
        if missing:
            raise MissingRequiredIdentityFieldError(
                f"missing required temporal roles: {missing}"
            )

    def to_dict(self) -> dict[str, Any]:
        # Emit all known roles for contract completeness; absent -> null.
        out: dict[str, Any] = {}
        for role in TemporalRole:
            out[role.value] = self.assignments.get(role.value)
        return out

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "TemporalRoleSet":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error("temporal roles must be a mapping")
        return cls(assignments=dict(value))

    @classmethod
    def empty_with_retrieval(cls, retrieved_at: datetime | str) -> "TemporalRoleSet":
        dt = _parse_utc_datetime(retrieved_at, name="retrieved_at")
        return cls(assignments={TemporalRole.RETRIEVAL.value: _format_utc(dt)})


# ---------------------------------------------------------------------------
# Authority identity v2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorityIdentityV2:
    """Full independent identity required by source-authority policy v2.

    Required fields (policy ``required_identity_fields``):
    provider, source_id, artifact_sha256, source_url, retrieved_at,
    authority_kind, authority_tier, rendition_legal_status, jurisdiction,
    media_type, edition_or_release_point, release_point_exclusions,
    document_package_granule_ids, signature_or_fixity_evidence.
    """

    provider: str
    source_id: str
    artifact_sha256: str
    source_url: str
    retrieved_at: datetime
    authority_kind: AuthorityKind
    authority_tier: AuthorityTier
    rendition_legal_status: RenditionLegalStatus
    jurisdiction: str
    media_type: str
    release_point: ReleasePointExclusions
    document_ids: DocumentPackageGranuleIds
    fixity: SignatureFixityEvidence
    artifact_cid: Optional[str] = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    temporal: TemporalRoleSet = field(default_factory=TemporalRoleSet)
    title: Optional[str] = None
    citation: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", _require_non_empty_str(self.provider, "provider")
        )
        object.__setattr__(
            self, "source_id", _require_non_empty_str(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _require_sha256(self.artifact_sha256, "artifact_sha256"),
        )
        object.__setattr__(
            self, "source_url", _require_non_empty_str(self.source_url, "source_url")
        )
        object.__setattr__(
            self,
            "retrieved_at",
            _parse_utc_datetime(self.retrieved_at, name="retrieved_at"),
        )
        kind, tier, rendition = assert_dimensions_independent(
            authority_kind=self.authority_kind,
            authority_tier=self.authority_tier,
            rendition_legal_status=self.rendition_legal_status,
        )
        object.__setattr__(self, "authority_kind", kind)
        object.__setattr__(self, "authority_tier", tier)
        object.__setattr__(self, "rendition_legal_status", rendition)
        object.__setattr__(
            self,
            "jurisdiction",
            _require_non_empty_str(self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(
            self, "media_type", _require_non_empty_str(self.media_type, "media_type")
        )
        if not isinstance(self.release_point, ReleasePointExclusions):
            raise PatentAuthorityContractsV2Error(
                "release_point must be ReleasePointExclusions"
            )
        if not isinstance(self.document_ids, DocumentPackageGranuleIds):
            raise PatentAuthorityContractsV2Error(
                "document_ids must be DocumentPackageGranuleIds"
            )
        if not isinstance(self.fixity, SignatureFixityEvidence):
            raise PatentAuthorityContractsV2Error(
                "fixity must be SignatureFixityEvidence"
            )
        if self.fixity.content_sha256 != self.artifact_sha256:
            raise PatentAuthorityContractsV2Error(
                "fixity.content_sha256 must match artifact_sha256"
            )
        if self.artifact_cid is not None:
            object.__setattr__(
                self, "artifact_cid", _require_cid(self.artifact_cid, "artifact_cid")
            )
        object.__setattr__(
            self,
            "verification_state",
            coerce_verification_state(self.verification_state),
        )
        if not isinstance(self.temporal, TemporalRoleSet):
            raise PatentAuthorityContractsV2Error("temporal must be TemporalRoleSet")
        # Ensure retrieval role is populated.
        if not self.temporal.get(TemporalRole.RETRIEVAL):
            object.__setattr__(
                self,
                "temporal",
                self.temporal.with_role(
                    TemporalRole.RETRIEVAL, _format_utc(self.retrieved_at)
                ),
            )
        for name in ("title", "citation"):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityContractsV2Error("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def acceptance_class(self) -> str:
        return self.authority_kind.acceptance_class

    @property
    def edition_or_release_point(self) -> str:
        return self.release_point.edition_or_release_point

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_cid": self.artifact_cid,
            "artifact_sha256": self.artifact_sha256,
            "authority_kind": self.authority_kind.value,
            "authority_tier": self.authority_tier.value,
            "citation": self.citation,
            "document_package_granule_ids": self.document_ids.to_dict(),
            "jurisdiction": self.jurisdiction,
            "media_type": self.media_type,
            "metadata": _deep_sorted_mapping(self.metadata),
            "provider": self.provider,
            "release_point_exclusions": self.release_point.to_dict(),
            "rendition_legal_status": self.rendition_legal_status.value,
            "retrieved_at": _format_utc(self.retrieved_at),
            "schema_version": AUTHORITY_IDENTITY_SCHEMA,
            "signature_or_fixity_evidence": self.fixity.to_dict(),
            "source_id": self.source_id,
            "source_url": self.source_url,
            "temporal_roles": self.temporal.to_dict(),
            "title": self.title,
            "verification_state": self.verification_state.value,
        }

    def content_address(self) -> ContentAddress:
        return content_address_mapping(self.to_dict())

    def to_canonical_json(self) -> str:
        return canonical_json_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityIdentityV2":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "authority identity must be a mapping"
            )
        required = (
            "provider",
            "source_id",
            "artifact_sha256",
            "source_url",
            "retrieved_at",
            "authority_kind",
            "authority_tier",
            "rendition_legal_status",
            "jurisdiction",
            "media_type",
        )
        for key in required:
            if key not in value or value.get(key) in (None, ""):
                raise MissingRequiredIdentityFieldError(f"{key} is required")

        release_raw = value.get("release_point_exclusions") or value.get("release_point")
        if not isinstance(release_raw, Mapping):
            raise MissingRequiredIdentityFieldError(
                "release_point_exclusions is required"
            )
        fixity_raw = value.get("signature_or_fixity_evidence") or value.get("fixity")
        if not isinstance(fixity_raw, Mapping):
            raise MissingRequiredIdentityFieldError(
                "signature_or_fixity_evidence is required"
            )
        docs_raw = value.get("document_package_granule_ids") or value.get("document_ids")
        temporal_raw = value.get("temporal_roles") or value.get("temporal")

        return cls(
            provider=value["provider"],
            source_id=value["source_id"],
            artifact_sha256=value["artifact_sha256"],
            source_url=value["source_url"],
            retrieved_at=value["retrieved_at"],
            authority_kind=value["authority_kind"],
            authority_tier=value["authority_tier"],
            rendition_legal_status=value["rendition_legal_status"],
            jurisdiction=value["jurisdiction"],
            media_type=value["media_type"],
            release_point=ReleasePointExclusions.from_dict(release_raw),
            document_ids=DocumentPackageGranuleIds.from_dict(docs_raw),
            fixity=SignatureFixityEvidence.from_dict(fixity_raw),
            artifact_cid=value.get("artifact_cid"),
            verification_state=value.get(
                "verification_state", VerificationState.UNVERIFIED
            ),
            temporal=TemporalRoleSet.from_dict(temporal_raw),
            title=value.get("title"),
            citation=value.get("citation"),
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Acquisition outcome + receipt (content-addressed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcquisitionReceipt:
    """Immutable, content-addressed receipt for one legal-source acquisition.

    The receipt payload is hashed to produce :attr:`receipt_sha256` and
    :attr:`receipt_cid`. HTTP success alone is not source authenticity.
    """

    endpoint: str
    retrieved_at: datetime
    outcome_kind: AcquisitionOutcomeKind
    response_status: int
    sanitized_request: Mapping[str, Any] = field(default_factory=dict)
    content: Optional[ContentAddress] = None
    etag: Optional[str] = None
    upstream_last_modified: Optional[str] = None
    source_timestamp: Optional[str] = None
    media_type: Optional[str] = None
    declared_media_type: Optional[str] = None
    declared_content_length: Optional[int] = None
    retry_after_seconds: Optional[float] = None
    cache_hit: bool = False
    conditional_request: bool = False
    robots_metadata: Mapping[str, Any] = field(default_factory=dict)
    terms_metadata: Mapping[str, Any] = field(default_factory=dict)
    pagination: Mapping[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Populated in __post_init__ from canonical payload (excluding these fields).
    receipt_sha256: str = ""
    receipt_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "endpoint", _require_non_empty_str(self.endpoint, "endpoint")
        )
        object.__setattr__(
            self,
            "retrieved_at",
            _parse_utc_datetime(self.retrieved_at, name="retrieved_at"),
        )
        object.__setattr__(
            self,
            "outcome_kind",
            coerce_acquisition_outcome_kind(self.outcome_kind),
        )
        if not isinstance(self.response_status, int) or isinstance(
            self.response_status, bool
        ):
            raise PatentAuthorityContractsV2Error("response_status must be an int")
        if self.response_status < 0:
            raise PatentAuthorityContractsV2Error("response_status must be >= 0")
        if not isinstance(self.sanitized_request, Mapping):
            raise PatentAuthorityContractsV2Error("sanitized_request must be a mapping")
        object.__setattr__(self, "sanitized_request", dict(self.sanitized_request))
        if self.content is not None and not isinstance(self.content, ContentAddress):
            raise PatentAuthorityContractsV2Error("content must be ContentAddress")
        for name in (
            "etag",
            "upstream_last_modified",
            "source_timestamp",
            "media_type",
            "declared_media_type",
            "error_code",
            "error_message",
        ):
            raw = getattr(self, name)
            if raw is not None:
                object.__setattr__(self, name, _require_non_empty_str(raw, name))
        if self.declared_content_length is not None:
            if (
                not isinstance(self.declared_content_length, int)
                or isinstance(self.declared_content_length, bool)
                or self.declared_content_length < 0
            ):
                raise PatentAuthorityContractsV2Error(
                    "declared_content_length must be a non-negative int"
                )
        if self.retry_after_seconds is not None:
            try:
                delay = float(self.retry_after_seconds)
            except (TypeError, ValueError) as exc:
                raise PatentAuthorityContractsV2Error(
                    "retry_after_seconds must be a number"
                ) from exc
            if delay != delay or delay < 0:
                raise PatentAuthorityContractsV2Error(
                    "retry_after_seconds must be a non-negative finite number"
                )
            object.__setattr__(self, "retry_after_seconds", delay)
        for name in ("robots_metadata", "terms_metadata", "pagination", "metadata"):
            raw = getattr(self, name)
            if not isinstance(raw, Mapping):
                raise PatentAuthorityContractsV2Error(f"{name} must be a mapping")
            object.__setattr__(self, name, dict(raw))

        # Content-address the stable payload (exclude digest fields).
        payload = self._addressable_payload()
        address = content_address_mapping(payload)
        object.__setattr__(self, "receipt_sha256", address.sha256)
        object.__setattr__(self, "receipt_cid", address.cid)

    def _addressable_payload(self) -> dict[str, Any]:
        return {
            "cache_hit": bool(self.cache_hit),
            "conditional_request": bool(self.conditional_request),
            "content": None if self.content is None else self.content.to_dict(),
            "declared_content_length": self.declared_content_length,
            "declared_media_type": self.declared_media_type,
            "endpoint": self.endpoint,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "etag": self.etag,
            "media_type": self.media_type,
            "metadata": _deep_sorted_mapping(self.metadata),
            "outcome_kind": self.outcome_kind.value,
            "pagination": _deep_sorted_mapping(self.pagination),
            "response_status": int(self.response_status),
            "retrieved_at": _format_utc(self.retrieved_at),
            "retry_after_seconds": self.retry_after_seconds,
            "robots_metadata": _deep_sorted_mapping(self.robots_metadata),
            "sanitized_request": _deep_sorted_mapping(self.sanitized_request),
            "schema_version": ACQUISITION_OUTCOME_SCHEMA,
            "source_timestamp": self.source_timestamp,
            "terms_metadata": _deep_sorted_mapping(self.terms_metadata),
            "upstream_last_modified": self.upstream_last_modified,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._addressable_payload()
        payload["receipt_cid"] = self.receipt_cid
        payload["receipt_sha256"] = self.receipt_sha256
        return payload

    def content_address(self) -> ContentAddress:
        return ContentAddress(
            sha256=self.receipt_sha256,
            cid=self.receipt_cid,
            byte_size=len(canonical_json_bytes(self._addressable_payload())),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcquisitionReceipt":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "acquisition receipt must be a mapping"
            )
        content_raw = value.get("content")
        content = (
            None if content_raw is None else ContentAddress.from_dict(content_raw)
        )
        receipt = cls(
            endpoint=value["endpoint"],
            retrieved_at=value["retrieved_at"],
            outcome_kind=value["outcome_kind"],
            response_status=int(value["response_status"]),
            sanitized_request=value.get("sanitized_request") or {},
            content=content,
            etag=value.get("etag"),
            upstream_last_modified=value.get("upstream_last_modified"),
            source_timestamp=value.get("source_timestamp"),
            media_type=value.get("media_type"),
            declared_media_type=value.get("declared_media_type"),
            declared_content_length=value.get("declared_content_length"),
            retry_after_seconds=value.get("retry_after_seconds"),
            cache_hit=bool(value.get("cache_hit", False)),
            conditional_request=bool(value.get("conditional_request", False)),
            robots_metadata=value.get("robots_metadata") or {},
            terms_metadata=value.get("terms_metadata") or {},
            pagination=value.get("pagination") or {},
            error_code=value.get("error_code"),
            error_message=value.get("error_message"),
            metadata=value.get("metadata") or {},
        )
        # If digests were supplied, they must match recomputed values.
        expected_sha = value.get("receipt_sha256")
        expected_cid = value.get("receipt_cid")
        if expected_sha is not None and expected_sha != receipt.receipt_sha256:
            raise PatentAuthorityContractsV2Error(
                "receipt_sha256 does not match recomputed content address"
            )
        if expected_cid is not None and expected_cid != receipt.receipt_cid:
            raise PatentAuthorityContractsV2Error(
                "receipt_cid does not match recomputed content address"
            )
        return receipt


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    """Terminal acquisition result required before parser admission.

    Carries the immutable :class:`AcquisitionReceipt` and optional content
    bytes reference (content-address only — raw bytes may live in a store).
    """

    kind: AcquisitionOutcomeKind
    receipt: AcquisitionReceipt
    body: Optional[bytes] = None
    network_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", coerce_acquisition_outcome_kind(self.kind))
        if not isinstance(self.receipt, AcquisitionReceipt):
            raise PatentAuthorityContractsV2Error("receipt must be AcquisitionReceipt")
        if self.kind is not self.receipt.outcome_kind:
            raise PatentAuthorityContractsV2Error(
                f"outcome kind {self.kind.value!r} must match receipt "
                f"outcome_kind {self.receipt.outcome_kind.value!r}"
            )
        if self.body is not None:
            if not isinstance(self.body, (bytes, bytearray, memoryview)):
                raise PatentAuthorityContractsV2Error("body must be bytes-like")
            raw = bytes(self.body)
            object.__setattr__(self, "body", raw)
            if self.receipt.content is None:
                raise PatentAuthorityContractsV2Error(
                    "receipt.content is required when body bytes are present"
                )
            address = content_address_bytes(raw)
            if address.sha256 != self.receipt.content.sha256:
                raise PatentAuthorityContractsV2Error(
                    "body bytes do not match receipt content sha256"
                )
            if address.cid != self.receipt.content.cid:
                raise PatentAuthorityContractsV2Error(
                    "body bytes do not match receipt content cid"
                )
        object.__setattr__(self, "network_used", bool(self.network_used))

    @property
    def is_parser_admissible(self) -> bool:
        """True when outcome may feed a parser (still requires this object)."""

        if self.kind not in PARSER_ADMISSIBLE_OUTCOMES:
            return False
        if self.kind is AcquisitionOutcomeKind.UNCHANGED:
            # Unchanged may admit cached body when present.
            return self.body is not None or self.receipt.content is not None
        return self.body is not None and self.receipt.content is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_present": self.body is not None,
            "body_sha256": (
                None
                if self.body is None
                else content_address_bytes(self.body).sha256
            ),
            "kind": self.kind.value,
            "network_used": bool(self.network_used),
            "receipt": self.receipt.to_dict(),
            "schema_version": ACQUISITION_OUTCOME_SCHEMA,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        body: Optional[bytes] = None,
    ) -> "AcquisitionOutcome":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error(
                "acquisition outcome must be a mapping"
            )
        receipt_raw = value.get("receipt")
        if not isinstance(receipt_raw, Mapping):
            raise PatentAuthorityContractsV2Error("receipt is required")
        return cls(
            kind=value.get("kind") or receipt_raw.get("outcome_kind"),
            receipt=AcquisitionReceipt.from_dict(receipt_raw),
            body=body,
            network_used=bool(value.get("network_used", False)),
        )


# ---------------------------------------------------------------------------
# Parser input gate — fail closed without acquisition outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParserInputEnvelope:
    """Bytes admitted to a legal-source parser only with an acquisition outcome.

    Construction fails closed when:

    * no :class:`AcquisitionOutcome` is supplied;
    * the outcome kind is not parser-admissible;
    * body digests disagree with the receipt.
    """

    acquisition: AcquisitionOutcome
    authority: Optional[AuthorityIdentityV2] = None
    parser_name: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.acquisition is None:
            raise MissingAcquisitionOutcomeError(
                "parser input is never accepted without an acquisition outcome"
            )
        if not isinstance(self.acquisition, AcquisitionOutcome):
            raise MissingAcquisitionOutcomeError(
                "parser input is never accepted without an acquisition outcome"
            )
        if not self.acquisition.is_parser_admissible:
            raise MissingAcquisitionOutcomeError(
                f"acquisition outcome {self.acquisition.kind.value!r} is not "
                "parser-admissible; refuse bytes without a successful fetch/"
                "changed/unchanged outcome carrying content identity"
            )
        if self.authority is not None and not isinstance(
            self.authority, AuthorityIdentityV2
        ):
            raise PatentAuthorityContractsV2Error(
                "authority must be AuthorityIdentityV2 when provided"
            )
        if self.parser_name is not None:
            object.__setattr__(
                self,
                "parser_name",
                _require_non_empty_str(self.parser_name, "parser_name"),
            )
        if not isinstance(self.metadata, Mapping):
            raise PatentAuthorityContractsV2Error("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def body(self) -> Optional[bytes]:
        return self.acquisition.body

    @property
    def content_address(self) -> Optional[ContentAddress]:
        return self.acquisition.receipt.content

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition": self.acquisition.to_dict(),
            "authority": None if self.authority is None else self.authority.to_dict(),
            "metadata": _deep_sorted_mapping(self.metadata),
            "parser_name": self.parser_name,
            "schema_version": PARSER_INPUT_SCHEMA,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        body: Optional[bytes] = None,
    ) -> "ParserInputEnvelope":
        if not isinstance(value, Mapping):
            raise PatentAuthorityContractsV2Error("parser input must be a mapping")
        acq_raw = value.get("acquisition")
        if acq_raw is None:
            raise MissingAcquisitionOutcomeError(
                "parser input is never accepted without an acquisition outcome"
            )
        if not isinstance(acq_raw, Mapping):
            raise MissingAcquisitionOutcomeError(
                "parser input is never accepted without an acquisition outcome"
            )
        authority_raw = value.get("authority")
        return cls(
            acquisition=AcquisitionOutcome.from_dict(acq_raw, body=body),
            authority=(
                None
                if authority_raw is None
                else AuthorityIdentityV2.from_dict(authority_raw)
            ),
            parser_name=value.get("parser_name"),
            metadata=value.get("metadata") or {},
        )

    @classmethod
    def admit(
        cls,
        acquisition: AcquisitionOutcome | None,
        *,
        authority: Optional[AuthorityIdentityV2] = None,
        parser_name: Optional[str] = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ParserInputEnvelope":
        """Public factory that enforces the acquisition-outcome gate."""

        if acquisition is None:
            raise MissingAcquisitionOutcomeError(
                "parser input is never accepted without an acquisition outcome"
            )
        return cls(
            acquisition=acquisition,
            authority=authority,
            parser_name=parser_name,
            metadata=metadata or {},
        )


def require_acquisition_outcome(
    value: Any,
) -> AcquisitionOutcome:
    """Fail closed unless *value* is a usable :class:`AcquisitionOutcome`."""

    if value is None:
        raise MissingAcquisitionOutcomeError(
            "parser input is never accepted without an acquisition outcome"
        )
    if not isinstance(value, AcquisitionOutcome):
        raise MissingAcquisitionOutcomeError(
            "parser input is never accepted without an acquisition outcome"
        )
    if not value.is_parser_admissible:
        raise MissingAcquisitionOutcomeError(
            f"acquisition outcome {value.kind.value!r} is not parser-admissible"
        )
    return value


__all__ = [
    "ACCEPTANCE_AUTHORITY_CLASSES",
    "ACQUISITION_OUTCOME_SCHEMA",
    "AUTHORITY_IDENTITY_SCHEMA",
    "AcquisitionOutcome",
    "AcquisitionOutcomeKind",
    "AcquisitionReceipt",
    "AuthorityDimensionCollapseError",
    "AuthorityIdentityV2",
    "AuthorityKind",
    "AuthorityTier",
    "ContentAddress",
    "DocumentPackageGranuleIds",
    "HardCodedLatestEditionError",
    "MissingAcquisitionOutcomeError",
    "MissingRequiredIdentityFieldError",
    "PARSER_ADMISSIBLE_OUTCOMES",
    "PARSER_INPUT_SCHEMA",
    "ParserInputEnvelope",
    "PatentAuthorityContractsV2Error",
    "ReleasePointExclusions",
    "RenditionLegalStatus",
    "SCHEMA_VERSION",
    "SignatureFixityEvidence",
    "TemporalRole",
    "TemporalRoleAssignment",
    "TemporalRoleSet",
    "VerificationState",
    "acceptance_class_for_kind",
    "assert_dimensions_independent",
    "canonical_json_bytes",
    "canonical_json_dumps",
    "coerce_acquisition_outcome_kind",
    "coerce_authority_kind",
    "coerce_authority_tier",
    "coerce_rendition_legal_status",
    "coerce_verification_state",
    "content_address_bytes",
    "content_address_mapping",
    "default_tier_for_kind",
    "non_collapsible_acceptance_matrix",
    "reject_hard_coded_latest",
    "require_acquisition_outcome",
]
