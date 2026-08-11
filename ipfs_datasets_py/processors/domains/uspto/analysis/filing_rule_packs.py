"""Versioned baseline filing-obligation rule packs (PATLAW-137).

Defines reviewed, content-addressed obligation packs for USPTO utility,
design (37 C.F.R. 1.151–1.155), and plant (37 C.F.R. 1.161–1.167) filing and
office-action response components.

Design invariants
-----------------
* Packs are **decision-support inputs**, not legal advice or self-updating
  conclusions. No pack files, signs, pays, or alters a docket.
* A pack **cannot become active** until (1) every declared source digest is
  recorded and (2) a natural-person human approval is recorded.
* Provisional, PCT national-stage, reissue, continuation, divisional, and CIP
  application types have an **explicit reviewed profile** or return
  ``out_of_scope`` / ``unknown`` — utility rules are never silently reused.
* Unsupported scenarios surface as **coverage gaps**, never fabricated rules.
* Rules always identify: jurisdiction, application type, scenario,
  applicability / effective interval, required evidence, exceptions,
  citations, reviewer / version, and tests.
* Silent rule updates are forbidden; new content creates a new pack version.

Conflict policy (PATLAW-137): own baseline rule-pack contracts only; do not
encode matter-specific legal strategy or claim exhaustive coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ReviewState,
    canonical_json,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

FILING_RULE_PACKS_SCHEMA_VERSION: Final = "uspto.filing-rule-packs.v1"
FILING_RULE_PACKS_INTERFACE: Final = "FilingRulePacks@1"
BASELINE_PACK_ID: Final = "uspto.baseline-filing-obligations"
BASELINE_PACK_VERSION: Final = "1.0.0"
BASELINE_FIXTURE_RELATIVE: Final = (
    "tests/fixtures/uspto/filing_rules/baseline_rules.json"
)

OUTPUT_KIND_FILING_OBLIGATION_PACK: Final = "filing_obligation_pack"

REVIEW_ONLY_PACK_DISCLAIMER: Final = (
    "This filing-obligation pack is a reviewed, versioned decision-support "
    "input. It is not legal advice, not a completeness certification, and "
    "does not authorize filing, payment, signature, or docket mutation. "
    "Form instructions are not controlling law. Named human review is "
    "required before any export or assurance disposition."
)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_SEMVER_RE = re.compile(r"\A\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?\Z")

# Application types that MUST have an explicit profile (never silent utility reuse).
SPECIAL_APPLICATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "provisional",
        "pct_national_stage",
        "reissue",
        "continuation",
        "divisional",
        "cip",
    }
)

SUPPORTED_BASELINE_APPLICATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "utility",
        "design",
        "plant",
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Jurisdiction(str, Enum):
    """Legal jurisdiction for a filing-obligation rule."""

    US_USPTO = "us_uspto"
    UNKNOWN = "unknown"


class ApplicationType(str, Enum):
    """Application-type profile key (broader than package-semantics v2)."""

    UTILITY = "utility"
    DESIGN = "design"
    PLANT = "plant"
    PROVISIONAL = "provisional"
    PCT_NATIONAL_STAGE = "pct_national_stage"
    REISSUE = "reissue"
    CONTINUATION = "continuation"
    DIVISIONAL = "divisional"
    CIP = "cip"
    UNKNOWN = "unknown"


class FilingScenario(str, Enum):
    """Filing / prosecution scenario a rule applies to."""

    NEW_APPLICATION = "new_application"
    OFFICE_ACTION_RESPONSE = "office_action_response"
    AFTER_FINAL_RESPONSE = "after_final_response"
    AMENDMENT = "amendment"
    INFORMATION_DISCLOSURE = "information_disclosure"
    ISSUE_FEE = "issue_fee"
    MISSING_PARTS = "missing_parts"
    CONTINUATION_FILING = "continuation_filing"
    DIVISIONAL_FILING = "divisional_filing"
    CIP_FILING = "cip_filing"
    REISSUE_FILING = "reissue_filing"
    PCT_NATIONAL_STAGE_ENTRY = "pct_national_stage_entry"
    PROVISIONAL_FILING = "provisional_filing"
    UNKNOWN = "unknown"


class ProfileCoverage(str, Enum):
    """Whether an application type has a reviewed obligation profile."""

    SUPPORTED = "supported"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


class PackStatus(str, Enum):
    """Lifecycle status of a filing-obligation pack.

    ``active`` is reachable only after source digests **and** human approval
    are recorded (fail-closed activation gate).
    """

    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class LegalRegime(str, Enum):
    AIA = "aia"
    PRE_AIA = "pre_aia"
    ANY = "any"
    UNKNOWN = "unknown"


class EntityStatus(str, Enum):
    MICRO = "micro"
    SMALL = "small"
    UNDISCOUNTED = "undiscounted"
    ANY = "any"
    UNKNOWN = "unknown"


class ProsecutionStage(str, Enum):
    FILING = "filing"
    PRE_EXAMINATION = "pre_examination"
    EXAMINATION = "examination"
    FINAL = "final"
    AFTER_FINAL = "after_final"
    ALLOWANCE = "allowance"
    ISSUE = "issue"
    ANY = "any"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    """Kinds of required evidence for an obligation."""

    SPECIFICATION = "specification"
    CLAIMS = "claims"
    DRAWINGS = "drawings"
    ADS = "ads"
    BENEFIT_CLAIM = "benefit_claim"
    OATH_DECLARATION = "oath_declaration"
    SIGNATURE_PRESENCE = "signature_presence"
    CERTIFICATION = "certification"
    FEE = "fee"
    FORM = "form"
    SEQUENCE_LISTING = "sequence_listing"
    ATTACHMENT = "attachment"
    IDENTIFIER = "identifier"
    CLAIM_AMENDMENT = "claim_amendment"
    REMARKS = "remarks"
    OTHER = "other"
    UNKNOWN = "unknown"


class ActivationBlockReason(str, Enum):
    """Why a pack cannot transition to ``active``."""

    MISSING_SOURCE_DIGESTS = "missing_source_digests"
    MISSING_HUMAN_APPROVAL = "missing_human_approval"
    EMPTY_RULES = "empty_rules"
    INVALID_STATUS_TRANSITION = "invalid_status_transition"
    MISSING_SPECIAL_PROFILES = "missing_special_profiles"
    PACK_REJECTED = "pack_rejected"
    PACK_SUPERSEDED = "pack_superseded"


class RulePackReasonCode(str, Enum):
    PACK_LOADED = "pack_loaded"
    PACK_DIGEST_COMPUTED = "pack_digest_computed"
    ACTIVATION_ALLOWED = "activation_allowed"
    ACTIVATION_BLOCKED = "activation_blocked"
    SOURCE_DIGESTS_RECORDED = "source_digests_recorded"
    HUMAN_APPROVAL_RECORDED = "human_approval_recorded"
    PROFILE_SUPPORTED = "profile_supported"
    PROFILE_OUT_OF_SCOPE = "profile_out_of_scope"
    PROFILE_UNKNOWN = "profile_unknown"
    COVERAGE_GAP = "coverage_gap"
    RULE_MATCHED = "rule_matched"
    REVIEW_ONLY = "review_only"
    NOT_LEGAL_ADVICE = "not_legal_advice"
    NOT_EXHAUSTIVE = "not_exhaustive"
    FORM_INSTRUCTIONS_NOT_CONTROLLING = "form_instructions_not_controlling"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class FilingRulePackError(ValueError):
    """Bounded filing rule-pack failure."""

    def __init__(
        self, message: str, *, code: str = "filing_rule_pack_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class PackActivationError(FilingRulePackError):
    """Raised when a pack cannot become active."""

    def __init__(
        self,
        message: str,
        *,
        block_reasons: Sequence[str] = (),
        code: str = "pack_activation_blocked",
    ) -> None:
        super().__init__(message, code=code)
        self.block_reasons = tuple(block_reasons)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _digest(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _digest_or_none(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    for member in enum_cls:
        if (
            member.value == text
            or member.name == text
            or member.name.lower() == text.lower()
        ):
            return member
    raise ValueError(f"{field} has unknown value: {value!r}")


def _optional_enum(
    enum_cls: type[Enum], value: Any, field: str, *, default: Enum
) -> Enum:
    if value is None:
        return default
    return _coerce_enum(enum_cls, value, field)


def _iso_date(value: date | str | None, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = _optional_str(value, field, max_len=32)
    if text is None:
        return None
    if not _ISO_DATE_RE.match(text):
        # Accept full ISO datetime by taking date part.
        if "T" in text:
            text = text.split("T", 1)[0]
        if not _ISO_DATE_RE.match(text):
            raise ValueError(f"{field} is not an ISO date: {text!r}")
    # Validate calendar date.
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid calendar date: {text!r}") from exc
    return text


def _parse_date(value: date | str | None, field: str) -> date | None:
    iso = _iso_date(value, field)
    if iso is None:
        return None
    return date.fromisoformat(iso)


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    out: list[str] = []
    for i, item in enumerate(value):
        if i >= max_items:
            break
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if text:
            out.append(text[:512])
    return tuple(out)


def _semver(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _SEMVER_RE.match(text):
        raise ValueError(f"{field} must be semver (e.g. 1.0.0), got {text!r}")
    return text


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectiveInterval:
    """Applicability / effective interval for a rule or pack."""

    effective_from: str | None
    effective_to: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effective_from", _iso_date(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self, "effective_to", _iso_date(self.effective_to, "effective_to")
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )
        start = _parse_date(self.effective_from, "effective_from")
        end = _parse_date(self.effective_to, "effective_to")
        if start is not None and end is not None and end < start:
            raise ValueError("effective_to must be on or after effective_from")

    def contains(self, as_of: date | str | None) -> bool:
        """True when *as_of* falls inside this interval (open end allowed)."""
        if as_of is None:
            return self.effective_from is None and self.effective_to is None
        d = _parse_date(as_of, "as_of")
        if d is None:
            return False
        start = _parse_date(self.effective_from, "effective_from")
        end = _parse_date(self.effective_to, "effective_to")
        if start is not None and d < start:
            return False
        if end is not None and d > end:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "EffectiveInterval":
        if value is None:
            return cls(effective_from=None, effective_to=None)
        if not isinstance(value, Mapping):
            raise TypeError("EffectiveInterval must be a mapping")
        return cls(
            effective_from=value.get("effective_from"),
            effective_to=value.get("effective_to"),
            notes=value.get("notes"),
        )

    @classmethod
    def open_ended(cls, effective_from: str | None = "2013-03-16") -> "EffectiveInterval":
        """AIA-era open-ended default used by baseline packs."""
        return cls(effective_from=effective_from, effective_to=None)


@dataclass(frozen=True, slots=True)
class SourceDigestRecord:
    """Immutable source-digest binding for pack activation."""

    source_id: str
    source_digest: str
    authority_citation: str | None = None
    source_url: str | None = None
    provider: str | None = None
    retrieved_at: str | None = None
    as_of: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self,
            "authority_citation",
            _optional_str(self.authority_citation, "authority_citation", max_len=256),
        )
        object.__setattr__(
            self, "source_url", _optional_str(self.source_url, "source_url", max_len=1024)
        )
        object.__setattr__(
            self, "provider", _optional_str(self.provider, "provider", max_len=128)
        )
        object.__setattr__(
            self,
            "retrieved_at",
            _optional_str(self.retrieved_at, "retrieved_at", max_len=64),
        )
        object.__setattr__(self, "as_of", _iso_date(self.as_of, "as_of"))
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "authority_citation": self.authority_citation,
            "notes": self.notes,
            "provider": self.provider,
            "retrieved_at": self.retrieved_at,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceDigestRecord":
        if not isinstance(value, Mapping):
            raise TypeError("SourceDigestRecord must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            source_digest=value.get("source_digest", ""),
            authority_citation=value.get("authority_citation"),
            source_url=value.get("source_url"),
            provider=value.get("provider"),
            retrieved_at=value.get("retrieved_at"),
            as_of=value.get("as_of"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class HumanApprovalRecord:
    """Natural-person approval required before pack activation."""

    reviewer_id: str
    approved_at: str
    pack_version: str
    approval_digest: str | None = None
    notes: str | None = None
    review_state: ReviewState | str = ReviewState.COMPLETE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id")
        )
        approved = _require_str(self.approved_at, "approved_at", max_len=64)
        object.__setattr__(self, "approved_at", approved)
        object.__setattr__(
            self, "pack_version", _semver(self.pack_version, "pack_version")
        )
        object.__setattr__(
            self,
            "approval_digest",
            _digest_or_none(self.approval_digest, "approval_digest"),
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )

    @property
    def is_complete(self) -> bool:
        return self.review_state is ReviewState.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_digest": self.approval_digest,
            "approved_at": self.approved_at,
            "notes": self.notes,
            "pack_version": self.pack_version,
            "review_state": (
                self.review_state.value
                if isinstance(self.review_state, ReviewState)
                else str(self.review_state)
            ),
            "reviewer_id": self.reviewer_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanApprovalRecord":
        if not isinstance(value, Mapping):
            raise TypeError("HumanApprovalRecord must be a mapping")
        return cls(
            reviewer_id=value.get("reviewer_id", ""),
            approved_at=value.get("approved_at", ""),
            pack_version=value.get("pack_version", ""),
            approval_digest=value.get("approval_digest"),
            notes=value.get("notes"),
            review_state=value.get("review_state", ReviewState.COMPLETE.value),
        )


@dataclass(frozen=True, slots=True)
class RequiredEvidence:
    """Evidence required to satisfy an obligation (decision-support only)."""

    evidence_kind: EvidenceKind | str
    description: str
    mandatory: bool = True
    conditional_on: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_kind",
            _coerce_enum(EvidenceKind, self.evidence_kind, "evidence_kind"),
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=1024),
        )
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be bool")
        object.__setattr__(
            self,
            "conditional_on",
            _optional_str(self.conditional_on, "conditional_on", max_len=256),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "conditional_on": self.conditional_on,
            "description": self.description,
            "evidence_kind": (
                self.evidence_kind.value
                if isinstance(self.evidence_kind, EvidenceKind)
                else str(self.evidence_kind)
            ),
            "mandatory": self.mandatory,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequiredEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("RequiredEvidence must be a mapping")
        return cls(
            evidence_kind=value.get("evidence_kind", EvidenceKind.UNKNOWN.value),
            description=value.get("description", ""),
            mandatory=bool(value.get("mandatory", True)),
            conditional_on=value.get("conditional_on"),
        )


@dataclass(frozen=True, slots=True)
class RuleException:
    """Conditional exception to an obligation."""

    exception_id: str
    description: str
    condition: str
    authority_citation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exception_id", _identifier(self.exception_id, "exception_id")
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=1024),
        )
        object.__setattr__(
            self, "condition", _require_str(self.condition, "condition", max_len=512)
        )
        object.__setattr__(
            self,
            "authority_citation",
            _optional_str(self.authority_citation, "authority_citation", max_len=256),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_citation": self.authority_citation,
            "condition": self.condition,
            "description": self.description,
            "exception_id": self.exception_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleException":
        if not isinstance(value, Mapping):
            raise TypeError("RuleException must be a mapping")
        return cls(
            exception_id=value.get("exception_id", ""),
            description=value.get("description", ""),
            condition=value.get("condition", ""),
            authority_citation=value.get("authority_citation"),
        )


@dataclass(frozen=True, slots=True)
class RuleCitation:
    """Exact authority or guidance citation for a rule."""

    citation: str
    citation_kind: str = "regulation"
    source_id: str | None = None
    source_digest: str | None = None
    is_controlling: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "citation", _require_str(self.citation, "citation", max_len=256)
        )
        object.__setattr__(
            self,
            "citation_kind",
            _require_str(self.citation_kind, "citation_kind", max_len=64),
        )
        object.__setattr__(
            self, "source_id", _optional_identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "source_digest", _digest_or_none(self.source_digest, "source_digest")
        )
        if not isinstance(self.is_controlling, bool):
            raise TypeError("is_controlling must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "citation_kind": self.citation_kind,
            "is_controlling": self.is_controlling,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | str) -> "RuleCitation":
        if isinstance(value, str):
            return cls(citation=value)
        if not isinstance(value, Mapping):
            raise TypeError("RuleCitation must be a mapping or str")
        return cls(
            citation=value.get("citation", ""),
            citation_kind=value.get("citation_kind", "regulation"),
            source_id=value.get("source_id"),
            source_digest=value.get("source_digest"),
            is_controlling=bool(value.get("is_controlling", True)),
        )


@dataclass(frozen=True, slots=True)
class RuleTestCase:
    """Deterministic test attached to a rule (acceptance field)."""

    test_id: str
    description: str
    expect_applicable: bool = True
    expect_coverage: str = "matched"
    fixture_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_id", _identifier(self.test_id, "test_id"))
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=512),
        )
        if not isinstance(self.expect_applicable, bool):
            raise TypeError("expect_applicable must be bool")
        object.__setattr__(
            self,
            "expect_coverage",
            _require_str(self.expect_coverage, "expect_coverage", max_len=64),
        )
        object.__setattr__(
            self,
            "fixture_hints",
            _tuple_of_str(self.fixture_hints, "fixture_hints", max_items=32),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "expect_applicable": self.expect_applicable,
            "expect_coverage": self.expect_coverage,
            "fixture_hints": list(self.fixture_hints),
            "test_id": self.test_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleTestCase":
        if not isinstance(value, Mapping):
            raise TypeError("RuleTestCase must be a mapping")
        return cls(
            test_id=value.get("test_id", ""),
            description=value.get("description", ""),
            expect_applicable=bool(value.get("expect_applicable", True)),
            expect_coverage=value.get("expect_coverage", "matched"),
            fixture_hints=tuple(value.get("fixture_hints") or ()),
        )


@dataclass(frozen=True, slots=True)
class ApplicationTypeProfile:
    """Explicit reviewed profile for an application type.

    Special types (provisional, PCT national-stage, reissue, continuation,
    divisional, CIP) must appear with ``supported``, ``out_of_scope``, or
    ``unknown`` — never silent utility reuse.
    """

    application_type: ApplicationType | str
    coverage: ProfileCoverage | str
    pack_version: str
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None
    scenarios_in_scope: tuple[str, ...] = ()
    authority_citations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "application_type",
            _coerce_enum(ApplicationType, self.application_type, "application_type"),
        )
        object.__setattr__(
            self, "coverage", _coerce_enum(ProfileCoverage, self.coverage, "coverage")
        )
        object.__setattr__(
            self, "pack_version", _semver(self.pack_version, "pack_version")
        )
        object.__setattr__(
            self, "reviewer_id", _optional_identifier(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self, "reviewed_at", _optional_str(self.reviewed_at, "reviewed_at", max_len=64)
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=1024)
        )
        object.__setattr__(
            self,
            "scenarios_in_scope",
            _tuple_of_str(self.scenarios_in_scope, "scenarios_in_scope", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_citations",
            _tuple_of_str(self.authority_citations, "authority_citations", max_items=64),
        )

    @property
    def is_supported(self) -> bool:
        return self.coverage is ProfileCoverage.SUPPORTED

    @property
    def is_out_of_scope(self) -> bool:
        return self.coverage is ProfileCoverage.OUT_OF_SCOPE

    @property
    def is_unknown(self) -> bool:
        return self.coverage is ProfileCoverage.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "authority_citations": list(self.authority_citations),
            "coverage": (
                self.coverage.value
                if isinstance(self.coverage, ProfileCoverage)
                else str(self.coverage)
            ),
            "notes": self.notes,
            "pack_version": self.pack_version,
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
            "scenarios_in_scope": list(self.scenarios_in_scope),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationTypeProfile":
        if not isinstance(value, Mapping):
            raise TypeError("ApplicationTypeProfile must be a mapping")
        return cls(
            application_type=value.get("application_type", ApplicationType.UNKNOWN.value),
            coverage=value.get("coverage", ProfileCoverage.UNKNOWN.value),
            pack_version=value.get("pack_version", "0.0.0"),
            reviewer_id=value.get("reviewer_id"),
            reviewed_at=value.get("reviewed_at"),
            notes=value.get("notes"),
            scenarios_in_scope=tuple(value.get("scenarios_in_scope") or ()),
            authority_citations=tuple(value.get("authority_citations") or ()),
        )


@dataclass(frozen=True, slots=True)
class FilingObligationRule:
    """Single reviewed filing obligation with full acceptance fields.

    Every rule identifies jurisdiction, application type, scenario,
    applicability / effective interval, required evidence, exceptions,
    citations, reviewer / version, and tests.
    """

    rule_id: str
    version: str
    jurisdiction: Jurisdiction | str
    application_type: ApplicationType | str
    scenario: FilingScenario | str
    title: str
    description: str
    effective_interval: EffectiveInterval
    required_evidence: tuple[RequiredEvidence, ...]
    exceptions: tuple[RuleException, ...]
    citations: tuple[RuleCitation, ...]
    reviewer_id: str
    reviewed_at: str
    tests: tuple[RuleTestCase, ...]
    legal_regime: LegalRegime | str = LegalRegime.ANY
    entity_status: EntityStatus | str = EntityStatus.ANY
    prosecution_stage: ProsecutionStage | str = ProsecutionStage.ANY
    component: str | None = None
    guidance_citations: tuple[RuleCitation, ...] = ()
    notes: str | None = None
    mandatory: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "version", _semver(self.version, "version"))
        object.__setattr__(
            self,
            "jurisdiction",
            _coerce_enum(Jurisdiction, self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(
            self,
            "application_type",
            _coerce_enum(ApplicationType, self.application_type, "application_type"),
        )
        object.__setattr__(
            self, "scenario", _coerce_enum(FilingScenario, self.scenario, "scenario")
        )
        object.__setattr__(
            self, "title", _require_str(self.title, "title", max_len=256)
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=2048),
        )
        if not isinstance(self.effective_interval, EffectiveInterval):
            if isinstance(self.effective_interval, Mapping):
                object.__setattr__(
                    self,
                    "effective_interval",
                    EffectiveInterval.from_dict(self.effective_interval),
                )
            else:
                raise TypeError("effective_interval must be EffectiveInterval")
        evidence = tuple(
            e if isinstance(e, RequiredEvidence) else RequiredEvidence.from_dict(e)
            for e in (self.required_evidence or ())
        )
        object.__setattr__(self, "required_evidence", evidence)
        exceptions = tuple(
            e if isinstance(e, RuleException) else RuleException.from_dict(e)
            for e in (self.exceptions or ())
        )
        object.__setattr__(self, "exceptions", exceptions)
        citations = tuple(
            c if isinstance(c, RuleCitation) else RuleCitation.from_dict(c)
            for c in (self.citations or ())
        )
        if not citations:
            raise ValueError(f"rule {self.rule_id} must have at least one citation")
        object.__setattr__(self, "citations", citations)
        object.__setattr__(
            self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self, "reviewed_at", _require_str(self.reviewed_at, "reviewed_at", max_len=64)
        )
        tests = tuple(
            t if isinstance(t, RuleTestCase) else RuleTestCase.from_dict(t)
            for t in (self.tests or ())
        )
        if not tests:
            raise ValueError(f"rule {self.rule_id} must have at least one test")
        object.__setattr__(self, "tests", tests)
        object.__setattr__(
            self,
            "legal_regime",
            _coerce_enum(LegalRegime, self.legal_regime, "legal_regime"),
        )
        object.__setattr__(
            self,
            "entity_status",
            _coerce_enum(EntityStatus, self.entity_status, "entity_status"),
        )
        object.__setattr__(
            self,
            "prosecution_stage",
            _coerce_enum(ProsecutionStage, self.prosecution_stage, "prosecution_stage"),
        )
        object.__setattr__(
            self, "component", _optional_str(self.component, "component", max_len=128)
        )
        guidance = tuple(
            c if isinstance(c, RuleCitation) else RuleCitation.from_dict(c)
            for c in (self.guidance_citations or ())
        )
        object.__setattr__(self, "guidance_citations", guidance)
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=1024)
        )
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be bool")

    def matches_keys(
        self,
        *,
        application_type: ApplicationType | str,
        scenario: FilingScenario | str,
        legal_regime: LegalRegime | str | None = None,
        entity_status: EntityStatus | str | None = None,
        prosecution_stage: ProsecutionStage | str | None = None,
        as_of: date | str | None = None,
    ) -> bool:
        """Deterministic key match (no silent cross-type reuse)."""
        app = _coerce_enum(ApplicationType, application_type, "application_type")
        scen = _coerce_enum(FilingScenario, scenario, "scenario")
        if self.application_type is not app:
            return False
        if self.scenario is not scen:
            return False
        if as_of is not None and not self.effective_interval.contains(as_of):
            return False
        if legal_regime is not None:
            reg = _coerce_enum(LegalRegime, legal_regime, "legal_regime")
            if (
                self.legal_regime is not LegalRegime.ANY
                and self.legal_regime is not LegalRegime.UNKNOWN
                and reg is not LegalRegime.ANY
                and reg is not LegalRegime.UNKNOWN
                and self.legal_regime is not reg
            ):
                return False
        if entity_status is not None:
            ent = _coerce_enum(EntityStatus, entity_status, "entity_status")
            if (
                self.entity_status is not EntityStatus.ANY
                and self.entity_status is not EntityStatus.UNKNOWN
                and ent is not EntityStatus.ANY
                and ent is not EntityStatus.UNKNOWN
                and self.entity_status is not ent
            ):
                return False
        if prosecution_stage is not None:
            stage = _coerce_enum(
                ProsecutionStage, prosecution_stage, "prosecution_stage"
            )
            if (
                self.prosecution_stage is not ProsecutionStage.ANY
                and self.prosecution_stage is not ProsecutionStage.UNKNOWN
                and stage is not ProsecutionStage.ANY
                and stage is not ProsecutionStage.UNKNOWN
                and self.prosecution_stage is not stage
            ):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "citations": [c.to_dict() for c in self.citations],
            "component": self.component,
            "description": self.description,
            "effective_interval": self.effective_interval.to_dict(),
            "entity_status": (
                self.entity_status.value
                if isinstance(self.entity_status, EntityStatus)
                else str(self.entity_status)
            ),
            "exceptions": [e.to_dict() for e in self.exceptions],
            "guidance_citations": [c.to_dict() for c in self.guidance_citations],
            "jurisdiction": (
                self.jurisdiction.value
                if isinstance(self.jurisdiction, Jurisdiction)
                else str(self.jurisdiction)
            ),
            "legal_regime": (
                self.legal_regime.value
                if isinstance(self.legal_regime, LegalRegime)
                else str(self.legal_regime)
            ),
            "mandatory": self.mandatory,
            "notes": self.notes,
            "prosecution_stage": (
                self.prosecution_stage.value
                if isinstance(self.prosecution_stage, ProsecutionStage)
                else str(self.prosecution_stage)
            ),
            "required_evidence": [e.to_dict() for e in self.required_evidence],
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
            "rule_id": self.rule_id,
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
            "tests": [t.to_dict() for t in self.tests],
            "title": self.title,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingObligationRule":
        if not isinstance(value, Mapping):
            raise TypeError("FilingObligationRule must be a mapping")
        return cls(
            rule_id=value.get("rule_id", ""),
            version=value.get("version", "0.0.0"),
            jurisdiction=value.get("jurisdiction", Jurisdiction.US_USPTO.value),
            application_type=value.get(
                "application_type", ApplicationType.UNKNOWN.value
            ),
            scenario=value.get("scenario", FilingScenario.UNKNOWN.value),
            title=value.get("title", ""),
            description=value.get("description", ""),
            effective_interval=EffectiveInterval.from_dict(
                value.get("effective_interval")
            ),
            required_evidence=tuple(value.get("required_evidence") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            citations=tuple(value.get("citations") or ()),
            reviewer_id=value.get("reviewer_id", ""),
            reviewed_at=value.get("reviewed_at", ""),
            tests=tuple(value.get("tests") or ()),
            legal_regime=value.get("legal_regime", LegalRegime.ANY.value),
            entity_status=value.get("entity_status", EntityStatus.ANY.value),
            prosecution_stage=value.get(
                "prosecution_stage", ProsecutionStage.ANY.value
            ),
            component=value.get("component"),
            guidance_citations=tuple(value.get("guidance_citations") or ()),
            notes=value.get("notes"),
            mandatory=bool(value.get("mandatory", True)),
        )


# ---------------------------------------------------------------------------
# Pack record + activation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilingObligationPack:
    """Versioned collection of reviewed filing obligations.

    Activation is fail-closed: ``status`` may be set to ``active`` only when
    :meth:`activation_block_reasons` is empty (source digests + human approval
    present, rules non-empty, special profiles explicit).
    """

    pack_id: str
    version: str
    status: PackStatus | str
    jurisdiction: Jurisdiction | str
    title: str
    rules: tuple[FilingObligationRule, ...]
    profiles: tuple[ApplicationTypeProfile, ...]
    source_digests: tuple[SourceDigestRecord, ...]
    human_approval: HumanApprovalRecord | None
    effective_interval: EffectiveInterval
    schema_version: str = FILING_RULE_PACKS_SCHEMA_VERSION
    disclaimer: str = REVIEW_ONLY_PACK_DISCLAIMER
    supersedes_pack_id: str | None = None
    notes: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "pack_id", _identifier(self.pack_id, "pack_id"))
        object.__setattr__(self, "version", _semver(self.version, "version"))
        object.__setattr__(
            self, "status", _coerce_enum(PackStatus, self.status, "status")
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _coerce_enum(Jurisdiction, self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(
            self, "title", _require_str(self.title, "title", max_len=256)
        )
        rules = tuple(
            r if isinstance(r, FilingObligationRule) else FilingObligationRule.from_dict(r)
            for r in (self.rules or ())
        )
        # Stable order by rule_id.
        object.__setattr__(
            self, "rules", tuple(sorted(rules, key=lambda r: r.rule_id))
        )
        profiles = tuple(
            p
            if isinstance(p, ApplicationTypeProfile)
            else ApplicationTypeProfile.from_dict(p)
            for p in (self.profiles or ())
        )
        object.__setattr__(
            self,
            "profiles",
            tuple(
                sorted(
                    profiles,
                    key=lambda p: (
                        p.application_type.value
                        if isinstance(p.application_type, ApplicationType)
                        else str(p.application_type)
                    ),
                )
            ),
        )
        digests = tuple(
            d if isinstance(d, SourceDigestRecord) else SourceDigestRecord.from_dict(d)
            for d in (self.source_digests or ())
        )
        object.__setattr__(
            self,
            "source_digests",
            tuple(sorted(digests, key=lambda d: d.source_id)),
        )
        if self.human_approval is not None and not isinstance(
            self.human_approval, HumanApprovalRecord
        ):
            if isinstance(self.human_approval, Mapping):
                object.__setattr__(
                    self,
                    "human_approval",
                    HumanApprovalRecord.from_dict(self.human_approval),
                )
            else:
                raise TypeError("human_approval must be HumanApprovalRecord or None")
        if not isinstance(self.effective_interval, EffectiveInterval):
            if isinstance(self.effective_interval, Mapping):
                object.__setattr__(
                    self,
                    "effective_interval",
                    EffectiveInterval.from_dict(self.effective_interval),
                )
            else:
                raise TypeError("effective_interval must be EffectiveInterval")
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        object.__setattr__(
            self,
            "supersedes_pack_id",
            _optional_identifier(self.supersedes_pack_id, "supersedes_pack_id"),
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=2048)
        )
        object.__setattr__(
            self, "created_at", _optional_str(self.created_at, "created_at", max_len=64)
        )
        # Fail-closed: cannot claim active without gates.
        if self.status is PackStatus.ACTIVE:
            blocks = self.activation_block_reasons()
            if blocks:
                raise PackActivationError(
                    "pack marked active without satisfying activation gates: "
                    + ", ".join(blocks),
                    block_reasons=blocks,
                )

    def profile_for(
        self, application_type: ApplicationType | str
    ) -> ApplicationTypeProfile | None:
        app = _coerce_enum(ApplicationType, application_type, "application_type")
        for profile in self.profiles:
            if profile.application_type is app:
                return profile
        return None

    def has_source_digests(self) -> bool:
        return bool(self.source_digests) and all(
            bool(d.source_digest) for d in self.source_digests
        )

    def has_human_approval(self) -> bool:
        return (
            self.human_approval is not None
            and self.human_approval.is_complete
            and self.human_approval.pack_version == self.version
        )

    def special_profile_gaps(self) -> tuple[str, ...]:
        """Return special application types missing an explicit profile."""
        present = {
            p.application_type.value
            if isinstance(p.application_type, ApplicationType)
            else str(p.application_type)
            for p in self.profiles
        }
        missing = sorted(SPECIAL_APPLICATION_TYPES - present)
        return tuple(missing)

    def activation_block_reasons(self) -> tuple[str, ...]:
        """Reasons this pack cannot become active (empty ⇒ activatable)."""
        reasons: list[str] = []
        if self.status is PackStatus.REJECTED:
            reasons.append(ActivationBlockReason.PACK_REJECTED.value)
        if self.status is PackStatus.SUPERSEDED:
            reasons.append(ActivationBlockReason.PACK_SUPERSEDED.value)
        if not self.rules:
            reasons.append(ActivationBlockReason.EMPTY_RULES.value)
        if not self.has_source_digests():
            reasons.append(ActivationBlockReason.MISSING_SOURCE_DIGESTS.value)
        if not self.has_human_approval():
            reasons.append(ActivationBlockReason.MISSING_HUMAN_APPROVAL.value)
        gaps = self.special_profile_gaps()
        if gaps:
            reasons.append(ActivationBlockReason.MISSING_SPECIAL_PROFILES.value)
        return tuple(reasons)

    def can_activate(self) -> bool:
        return not self.activation_block_reasons()

    def content_digest(self) -> str:
        """Stable digest of pack content (excludes runtime status churn only
        when serializing full pack — includes status for audit binding)."""
        payload = self.to_dict()
        return sha256_hex(canonical_json(payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "disclaimer": self.disclaimer,
            "effective_interval": self.effective_interval.to_dict(),
            "human_approval": (
                self.human_approval.to_dict() if self.human_approval else None
            ),
            "jurisdiction": (
                self.jurisdiction.value
                if isinstance(self.jurisdiction, Jurisdiction)
                else str(self.jurisdiction)
            ),
            "notes": self.notes,
            "output_kind": OUTPUT_KIND_FILING_OBLIGATION_PACK,
            "pack_id": self.pack_id,
            "profiles": [p.to_dict() for p in self.profiles],
            "rules": [r.to_dict() for r in self.rules],
            "schema_version": self.schema_version,
            "source_digests": [d.to_dict() for d in self.source_digests],
            "status": (
                self.status.value if isinstance(self.status, PackStatus) else str(self.status)
            ),
            "supersedes_pack_id": self.supersedes_pack_id,
            "title": self.title,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingObligationPack":
        if not isinstance(value, Mapping):
            raise TypeError("FilingObligationPack must be a mapping")
        return cls(
            pack_id=value.get("pack_id", ""),
            version=value.get("version", "0.0.0"),
            status=value.get("status", PackStatus.DRAFT.value),
            jurisdiction=value.get("jurisdiction", Jurisdiction.US_USPTO.value),
            title=value.get("title", ""),
            rules=tuple(value.get("rules") or ()),
            profiles=tuple(value.get("profiles") or ()),
            source_digests=tuple(value.get("source_digests") or ()),
            human_approval=value.get("human_approval"),
            effective_interval=EffectiveInterval.from_dict(
                value.get("effective_interval")
            ),
            schema_version=value.get(
                "schema_version", FILING_RULE_PACKS_SCHEMA_VERSION
            ),
            disclaimer=value.get("disclaimer", REVIEW_ONLY_PACK_DISCLAIMER),
            supersedes_pack_id=value.get("supersedes_pack_id"),
            notes=value.get("notes"),
            created_at=value.get("created_at"),
        )


def activate_pack(pack: FilingObligationPack) -> FilingObligationPack:
    """Return a copy of *pack* with ``status=active`` if gates pass.

    Raises :class:`PackActivationError` when source digests or human approval
    are missing, special profiles are incomplete, or rules are empty.
    """
    if not isinstance(pack, FilingObligationPack):
        raise TypeError("pack must be FilingObligationPack")
    if pack.status is PackStatus.ACTIVE:
        return pack
    blocks = pack.activation_block_reasons()
    if blocks:
        raise PackActivationError(
            "cannot activate pack: " + ", ".join(blocks),
            block_reasons=blocks,
        )
    return FilingObligationPack(
        pack_id=pack.pack_id,
        version=pack.version,
        status=PackStatus.ACTIVE,
        jurisdiction=pack.jurisdiction,
        title=pack.title,
        rules=pack.rules,
        profiles=pack.profiles,
        source_digests=pack.source_digests,
        human_approval=pack.human_approval,
        effective_interval=pack.effective_interval,
        schema_version=pack.schema_version,
        disclaimer=pack.disclaimer,
        supersedes_pack_id=pack.supersedes_pack_id,
        notes=pack.notes,
        created_at=pack.created_at,
    )


def with_source_digests(
    pack: FilingObligationPack,
    digests: Sequence[SourceDigestRecord | Mapping[str, Any]],
) -> FilingObligationPack:
    """Return a pack copy with *digests* recorded (status demoted if was active)."""
    records = tuple(
        d if isinstance(d, SourceDigestRecord) else SourceDigestRecord.from_dict(d)
        for d in digests
    )
    status = pack.status
    if status is PackStatus.ACTIVE:
        # Digests changed — require re-approval path via draft/reviewed.
        status = PackStatus.REVIEWED
    return FilingObligationPack(
        pack_id=pack.pack_id,
        version=pack.version,
        status=status if status is not PackStatus.ACTIVE else PackStatus.REVIEWED,
        jurisdiction=pack.jurisdiction,
        title=pack.title,
        rules=pack.rules,
        profiles=pack.profiles,
        source_digests=records,
        human_approval=pack.human_approval,
        effective_interval=pack.effective_interval,
        schema_version=pack.schema_version,
        disclaimer=pack.disclaimer,
        supersedes_pack_id=pack.supersedes_pack_id,
        notes=pack.notes,
        created_at=pack.created_at,
    )


def with_human_approval(
    pack: FilingObligationPack,
    approval: HumanApprovalRecord | Mapping[str, Any],
) -> FilingObligationPack:
    """Return a pack copy with human approval recorded."""
    rec = (
        approval
        if isinstance(approval, HumanApprovalRecord)
        else HumanApprovalRecord.from_dict(approval)
    )
    status = pack.status
    if status is PackStatus.DRAFT and rec.is_complete:
        status = PackStatus.REVIEWED
    return FilingObligationPack(
        pack_id=pack.pack_id,
        version=pack.version,
        status=status,
        jurisdiction=pack.jurisdiction,
        title=pack.title,
        rules=pack.rules,
        profiles=pack.profiles,
        source_digests=pack.source_digests,
        human_approval=rec,
        effective_interval=pack.effective_interval,
        schema_version=pack.schema_version,
        disclaimer=pack.disclaimer,
        supersedes_pack_id=pack.supersedes_pack_id,
        notes=pack.notes,
        created_at=pack.created_at,
    )


# ---------------------------------------------------------------------------
# Loading baseline fixture
# ---------------------------------------------------------------------------


def resolve_baseline_fixture_path(
    explicit: str | Path | None = None,
) -> Path:
    """Locate ``baseline_rules.json`` relative to known roots."""
    if explicit is not None:
        path = Path(explicit)
        if path.is_file():
            return path
        raise FilingRulePackError(
            f"baseline fixture not found: {path}",
            code="baseline_fixture_missing",
        )
    here = Path(__file__).resolve()
    candidates = [
        # analysis/uspto/domains/processors/ipfs_datasets_py/<repo>
        here.parents[5] / BASELINE_FIXTURE_RELATIVE,
        Path.cwd() / BASELINE_FIXTURE_RELATIVE,
        Path(BASELINE_FIXTURE_RELATIVE),
    ]
    # Walk parents for monorepo / worktree layouts.
    for parent in [here, *here.parents]:
        candidates.append(parent / BASELINE_FIXTURE_RELATIVE)
    seen: set[str] = set()
    for cand in candidates:
        key = str(cand.resolve()) if cand.exists() else str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    raise FilingRulePackError(
        f"baseline fixture not found; tried {BASELINE_FIXTURE_RELATIVE}",
        code="baseline_fixture_missing",
    )


def load_baseline_rules(
    path: str | Path | None = None,
) -> FilingObligationPack:
    """Load and validate the baseline filing-obligation pack fixture."""
    fixture_path = resolve_baseline_fixture_path(path)
    raw = fixture_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FilingRulePackError(
            f"baseline fixture is not valid JSON: {exc}",
            code="baseline_fixture_invalid_json",
        ) from exc
    if not isinstance(data, Mapping):
        raise FilingRulePackError(
            "baseline fixture root must be an object",
            code="baseline_fixture_invalid_root",
        )
    # Support either a bare pack object or a wrapper with "pack".
    pack_data = data.get("pack") if "pack" in data else data
    if not isinstance(pack_data, Mapping):
        raise FilingRulePackError(
            "baseline fixture pack must be an object",
            code="baseline_fixture_invalid_pack",
        )
    return FilingObligationPack.from_dict(pack_data)


def load_pack_from_mapping(value: Mapping[str, Any]) -> FilingObligationPack:
    """Validate and construct a pack from an arbitrary mapping."""
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    return FilingObligationPack.from_dict(value)


def list_rule_ids(pack: FilingObligationPack) -> tuple[str, ...]:
    return tuple(r.rule_id for r in pack.rules)


def rules_for_application_type(
    pack: FilingObligationPack,
    application_type: ApplicationType | str,
) -> tuple[FilingObligationRule, ...]:
    app = _coerce_enum(ApplicationType, application_type, "application_type")
    return tuple(r for r in pack.rules if r.application_type is app)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "BASELINE_FIXTURE_RELATIVE",
    "BASELINE_PACK_ID",
    "BASELINE_PACK_VERSION",
    "ActivationBlockReason",
    "ApplicationType",
    "ApplicationTypeProfile",
    "EffectiveInterval",
    "EntityStatus",
    "EvidenceKind",
    "FILING_RULE_PACKS_INTERFACE",
    "FILING_RULE_PACKS_SCHEMA_VERSION",
    "FilingObligationPack",
    "FilingObligationRule",
    "FilingRulePackError",
    "FilingScenario",
    "HumanApprovalRecord",
    "Jurisdiction",
    "LegalRegime",
    "OUTPUT_KIND_FILING_OBLIGATION_PACK",
    "PackActivationError",
    "PackStatus",
    "ProfileCoverage",
    "ProsecutionStage",
    "REVIEW_ONLY_PACK_DISCLAIMER",
    "RequiredEvidence",
    "RuleCitation",
    "RuleException",
    "RulePackReasonCode",
    "RuleTestCase",
    "SPECIAL_APPLICATION_TYPES",
    "SUPPORTED_BASELINE_APPLICATION_TYPES",
    "SourceDigestRecord",
    "activate_pack",
    "list_rule_ids",
    "load_baseline_rules",
    "load_pack_from_mapping",
    "resolve_baseline_fixture_path",
    "rules_for_application_type",
    "sha256_hex",
    "with_human_approval",
    "with_source_digests",
]
