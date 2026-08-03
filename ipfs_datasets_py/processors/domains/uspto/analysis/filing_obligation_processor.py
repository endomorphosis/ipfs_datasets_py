"""Filing-obligation processor for versioned rule packs (PATLAW-137).

Compiles reviewed baseline obligation packs against a matter filing context
and returns matched obligations, application-type profile disposition, and
explicit coverage gaps for unsupported scenarios.

Design invariants
-----------------
* **Review-only / decision-support**: never legal advice, filing authority,
  payment, signature certification, or docket mutation.
* **No silent utility reuse**: provisional, PCT national-stage, reissue,
  continuation, divisional, and CIP either match an explicit reviewed profile
  or return ``out_of_scope`` / ``unknown``.
* **Coverage gaps** are first-class results for unsupported scenarios.
* Only **active** packs (source digests + human approval recorded) may drive
  authoritative matching; draft/reviewed packs yield a blocked disposition.
* Form instructions are never treated as controlling law.
* Output is deterministic and versioned.

Conflict policy (PATLAW-137): own processor surface only; do not encode
matter-specific legal strategy or claim exhaustive coverage.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.filing_rule_packs import (
    BASELINE_FIXTURE_RELATIVE,
    BASELINE_PACK_ID,
    FILING_RULE_PACKS_SCHEMA_VERSION,
    REVIEW_ONLY_PACK_DISCLAIMER,
    ApplicationType,
    ApplicationTypeProfile,
    EffectiveInterval,
    EntityStatus,
    FilingObligationPack,
    FilingObligationRule,
    FilingRulePackError,
    FilingScenario,
    Jurisdiction,
    LegalRegime,
    PackStatus,
    ProfileCoverage,
    ProsecutionStage,
    RulePackReasonCode,
    SPECIAL_APPLICATION_TYPES,
    activate_pack,
    load_baseline_rules,
    resolve_baseline_fixture_path,
    sha256_hex,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

FILING_OBLIGATION_SCHEMA_VERSION: Final = "uspto.filing-obligation-processor.v1"
FILING_OBLIGATION_INTERFACE: Final = "FilingObligationProcessor@1"
FILING_OBLIGATION_RULESET_VERSION: Final = "filing-obligation-rules@1"

OUTPUT_KIND_FILING_OBLIGATION_RESULT: Final = "filing_obligation_resolution"

REVIEW_ONLY_OBLIGATION_DISCLAIMER: Final = (
    "This filing-obligation resolution is a review-only decision-support "
    "result. It is not legal advice, not a completeness certification, and "
    "does not authorize filing, payment, signature, or docket mutation. "
    "Coverage is not exhaustive. Form instructions are not controlling law. "
    "Named human review is required before any export or assurance disposition."
)

DEFAULT_MAX_MATCHED: Final = 4096
DEFAULT_MAX_GAPS: Final = 512

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ObligationResolutionStatus(str, Enum):
    """Top-level disposition of an obligation resolution."""

    MATCHED = "matched"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"
    COVERAGE_GAP = "coverage_gap"
    PACK_NOT_ACTIVE = "pack_not_active"
    EMPTY = "empty"
    REVIEW = "review"


class CoverageGapKind(str, Enum):
    """Why a scenario could not be fully resolved from the pack."""

    UNSUPPORTED_APPLICATION_TYPE = "unsupported_application_type"
    UNSUPPORTED_SCENARIO = "unsupported_scenario"
    PROFILE_OUT_OF_SCOPE = "profile_out_of_scope"
    PROFILE_UNKNOWN = "profile_unknown"
    NO_MATCHING_RULES = "no_matching_rules"
    EFFECTIVE_INTERVAL_MISS = "effective_interval_miss"
    REGIME_MISMATCH = "regime_mismatch"
    ENTITY_MISMATCH = "entity_mismatch"
    STAGE_MISMATCH = "stage_mismatch"
    PACK_NOT_ACTIVE = "pack_not_active"
    MISSING_SPECIAL_PROFILE = "missing_special_profile"
    UNKNOWN = "unknown"


class ObligationReasonCode(str, Enum):
    RESOLVED = "resolved"
    REVIEW_ONLY = "review_only"
    NOT_LEGAL_ADVICE = "not_legal_advice"
    NOT_EXHAUSTIVE = "not_exhaustive"
    FORM_INSTRUCTIONS_NOT_CONTROLLING = "form_instructions_not_controlling"
    PACK_ACTIVE = "pack_active"
    PACK_NOT_ACTIVE = "pack_not_active"
    PROFILE_SUPPORTED = "profile_supported"
    PROFILE_OUT_OF_SCOPE = "profile_out_of_scope"
    PROFILE_UNKNOWN = "profile_unknown"
    RULES_MATCHED = "rules_matched"
    COVERAGE_GAP = "coverage_gap"
    SPECIAL_TYPE_EXPLICIT = "special_type_explicit"
    NO_SILENT_UTILITY_REUSE = "no_silent_utility_reuse"
    BASELINE_LOADED = "baseline_loaded"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class FilingObligationProcessorError(ValueError):
    """Bounded filing-obligation processor failure."""

    def __init__(
        self, message: str, *, code: str = "filing_obligation_processor_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


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


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    return _coerce_enum(  # type: ignore[return-value]
        DisclosureClassification, value, "classification"
    )


def _iso_date(value: date | str | None, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = _optional_str(value, field, max_len=32)
    if text is None:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} is not an ISO date: {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid calendar date: {text!r}") from exc
    return text


def _default_id_factory() -> Callable[[], str]:
    def _ids() -> str:
        return f"fob:{uuid.uuid4().hex[:16]}"

    return _ids


# ---------------------------------------------------------------------------
# Request / gap / result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilingObligationRequest:
    """Matter context used to resolve filing obligations from a pack."""

    request_id: str
    application_type: ApplicationType | str
    scenario: FilingScenario | str
    filing_date: str | None = None
    as_of: str | None = None
    legal_regime: LegalRegime | str = LegalRegime.AIA
    entity_status: EntityStatus | str = EntityStatus.UNDISCOUNTED
    prosecution_stage: ProsecutionStage | str = ProsecutionStage.FILING
    jurisdiction: Jurisdiction | str = Jurisdiction.US_USPTO
    matter_id: str | None = None
    classification: DisclosureClassification | str = (
        DisclosureClassification.PUBLIC_USER
    )
    pack: FilingObligationPack | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
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
            self, "filing_date", _iso_date(self.filing_date, "filing_date")
        )
        object.__setattr__(self, "as_of", _iso_date(self.as_of, "as_of"))
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
            _coerce_enum(
                ProsecutionStage, self.prosecution_stage, "prosecution_stage"
            ),
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _coerce_enum(Jurisdiction, self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.pack is not None and not isinstance(self.pack, FilingObligationPack):
            if isinstance(self.pack, Mapping):
                object.__setattr__(
                    self, "pack", FilingObligationPack.from_dict(self.pack)
                )
            else:
                raise TypeError("pack must be FilingObligationPack or None")
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )

    @property
    def effective_as_of(self) -> str | None:
        """Date used for interval matching (prefer as_of, else filing_date)."""
        return self.as_of or self.filing_date

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "as_of": self.as_of,
            "classification": (
                self.classification.value
                if isinstance(self.classification, DisclosureClassification)
                else str(self.classification)
            ),
            "entity_status": (
                self.entity_status.value
                if isinstance(self.entity_status, EntityStatus)
                else str(self.entity_status)
            ),
            "filing_date": self.filing_date,
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
            "matter_id": self.matter_id,
            "notes": self.notes,
            "pack_id": self.pack.pack_id if self.pack is not None else None,
            "pack_version": self.pack.version if self.pack is not None else None,
            "prosecution_stage": (
                self.prosecution_stage.value
                if isinstance(self.prosecution_stage, ProsecutionStage)
                else str(self.prosecution_stage)
            ),
            "request_id": self.request_id,
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingObligationRequest":
        if not isinstance(value, Mapping):
            raise TypeError("FilingObligationRequest must be a mapping")
        pack = value.get("pack")
        return cls(
            request_id=value.get("request_id", ""),
            application_type=value.get(
                "application_type", ApplicationType.UNKNOWN.value
            ),
            scenario=value.get("scenario", FilingScenario.UNKNOWN.value),
            filing_date=value.get("filing_date"),
            as_of=value.get("as_of"),
            legal_regime=value.get("legal_regime", LegalRegime.AIA.value),
            entity_status=value.get(
                "entity_status", EntityStatus.UNDISCOUNTED.value
            ),
            prosecution_stage=value.get(
                "prosecution_stage", ProsecutionStage.FILING.value
            ),
            jurisdiction=value.get("jurisdiction", Jurisdiction.US_USPTO.value),
            matter_id=value.get("matter_id"),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            pack=pack,
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """Explicit gap when a scenario is unsupported or out of profile scope."""

    gap_id: str
    kind: CoverageGapKind | str
    application_type: ApplicationType | str
    scenario: FilingScenario | str
    description: str
    profile_coverage: ProfileCoverage | str | None = None
    related_rule_ids: tuple[str, ...] = ()
    blocking: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(CoverageGapKind, self.kind, "kind")
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
            self,
            "description",
            _require_str(self.description, "description", max_len=1024),
        )
        if self.profile_coverage is not None:
            object.__setattr__(
                self,
                "profile_coverage",
                _coerce_enum(
                    ProfileCoverage, self.profile_coverage, "profile_coverage"
                ),
            )
        related: list[str] = []
        for item in self.related_rule_ids or ():
            related.append(_identifier(item, "related_rule_ids item"))
        object.__setattr__(self, "related_rule_ids", tuple(related))
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "blocking": self.blocking,
            "description": self.description,
            "gap_id": self.gap_id,
            "kind": (
                self.kind.value if isinstance(self.kind, CoverageGapKind) else str(self.kind)
            ),
            "profile_coverage": (
                self.profile_coverage.value
                if isinstance(self.profile_coverage, ProfileCoverage)
                else self.profile_coverage
            ),
            "related_rule_ids": list(self.related_rule_ids),
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        if not isinstance(value, Mapping):
            raise TypeError("CoverageGap must be a mapping")
        return cls(
            gap_id=value.get("gap_id", ""),
            kind=value.get("kind", CoverageGapKind.UNKNOWN.value),
            application_type=value.get(
                "application_type", ApplicationType.UNKNOWN.value
            ),
            scenario=value.get("scenario", FilingScenario.UNKNOWN.value),
            description=value.get("description", ""),
            profile_coverage=value.get("profile_coverage"),
            related_rule_ids=tuple(value.get("related_rule_ids") or ()),
            blocking=bool(value.get("blocking", True)),
        )


@dataclass(frozen=True, slots=True)
class MatchedObligation:
    """A pack rule matched to the request context."""

    match_id: str
    rule: FilingObligationRule
    match_rank: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "match_id", _identifier(self.match_id, "match_id"))
        if not isinstance(self.rule, FilingObligationRule):
            if isinstance(self.rule, Mapping):
                object.__setattr__(
                    self, "rule", FilingObligationRule.from_dict(self.rule)
                )
            else:
                raise TypeError("rule must be FilingObligationRule")
        if not isinstance(self.match_rank, int) or isinstance(self.match_rank, bool):
            raise TypeError("match_rank must be int")
        if self.match_rank < 0:
            raise ValueError("match_rank must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "match_rank": self.match_rank,
            "rule": self.rule.to_dict(),
            "rule_id": self.rule.rule_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatchedObligation":
        if not isinstance(value, Mapping):
            raise TypeError("MatchedObligation must be a mapping")
        rule = value.get("rule")
        if rule is None:
            raise ValueError("MatchedObligation.rule is required")
        return cls(
            match_id=value.get("match_id", ""),
            rule=rule,
            match_rank=int(value.get("match_rank", 0)),
        )


@dataclass(frozen=True, slots=True)
class FilingObligationResult:
    """Versioned result of resolving filing obligations for a request."""

    schema_version: str
    result_id: str
    request_id: str
    status: ObligationResolutionStatus | str
    pack_id: str
    pack_version: str
    pack_status: PackStatus | str
    pack_content_digest: str
    application_type: ApplicationType | str
    scenario: FilingScenario | str
    profile: ApplicationTypeProfile | None
    matched_obligations: tuple[MatchedObligation, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    reason_codes: tuple[str, ...]
    is_review_only: bool = True
    is_exhaustive: bool = False
    is_legal_advice: bool = False
    output_kind: str = OUTPUT_KIND_FILING_OBLIGATION_RESULT
    disclaimer: str = REVIEW_ONLY_OBLIGATION_DISCLAIMER
    review_state: ReviewState | str = ReviewState.REQUIRED
    classification: DisclosureClassification | str = (
        DisclosureClassification.PUBLIC_USER
    )
    matter_id: str | None = None
    ruleset_version: str = FILING_OBLIGATION_RULESET_VERSION
    contracts_schema_version: str = CONTRACTS_SCHEMA_VERSION
    interface: str = FILING_OBLIGATION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self, "result_id", _identifier(self.result_id, "result_id")
        )
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(ObligationResolutionStatus, self.status, "status"),
        )
        object.__setattr__(self, "pack_id", _identifier(self.pack_id, "pack_id"))
        object.__setattr__(
            self, "pack_version", _require_str(self.pack_version, "pack_version", max_len=64)
        )
        object.__setattr__(
            self, "pack_status", _coerce_enum(PackStatus, self.pack_status, "pack_status")
        )
        digest = _require_str(self.pack_content_digest, "pack_content_digest", max_len=64)
        digest = digest.lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("pack_content_digest must be sha256 hex")
        object.__setattr__(self, "pack_content_digest", digest)
        object.__setattr__(
            self,
            "application_type",
            _coerce_enum(ApplicationType, self.application_type, "application_type"),
        )
        object.__setattr__(
            self, "scenario", _coerce_enum(FilingScenario, self.scenario, "scenario")
        )
        if self.profile is not None and not isinstance(
            self.profile, ApplicationTypeProfile
        ):
            if isinstance(self.profile, Mapping):
                object.__setattr__(
                    self, "profile", ApplicationTypeProfile.from_dict(self.profile)
                )
            else:
                raise TypeError("profile must be ApplicationTypeProfile or None")
        matches = tuple(
            m if isinstance(m, MatchedObligation) else MatchedObligation.from_dict(m)
            for m in (self.matched_obligations or ())
        )
        object.__setattr__(self, "matched_obligations", matches)
        gaps = tuple(
            g if isinstance(g, CoverageGap) else CoverageGap.from_dict(g)
            for g in (self.coverage_gaps or ())
        )
        object.__setattr__(self, "coverage_gaps", gaps)
        codes: list[str] = []
        for c in self.reason_codes or ():
            text = str(c).strip()
            if text and text not in codes:
                codes.append(text[:128])
        object.__setattr__(self, "reason_codes", tuple(codes))
        for flag_name in ("is_review_only", "is_exhaustive", "is_legal_advice"):
            flag = getattr(self, flag_name)
            if not isinstance(flag, bool):
                raise TypeError(f"{flag_name} must be bool")
        # Invariants: never claim legal advice or exhaustiveness.
        if self.is_legal_advice:
            raise ValueError("is_legal_advice must be False")
        if self.is_exhaustive:
            raise ValueError("is_exhaustive must be False (coverage is never exhaustive)")
        if not self.is_review_only:
            raise ValueError("is_review_only must be True")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        object.__setattr__(
            self, "disclaimer", _require_str(self.disclaimer, "disclaimer", max_len=2048)
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        object.__setattr__(
            self,
            "contracts_schema_version",
            _require_str(
                self.contracts_schema_version, "contracts_schema_version", max_len=64
            ),
        )
        object.__setattr__(
            self, "interface", _require_str(self.interface, "interface", max_len=128)
        )

    @property
    def has_coverage_gaps(self) -> bool:
        return bool(self.coverage_gaps)

    @property
    def matched_rule_ids(self) -> tuple[str, ...]:
        return tuple(m.rule.rule_id for m in self.matched_obligations)

    def content_digest(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "classification": (
                self.classification.value
                if isinstance(self.classification, DisclosureClassification)
                else str(self.classification)
            ),
            "contracts_schema_version": self.contracts_schema_version,
            "coverage_gaps": [g.to_dict() for g in self.coverage_gaps],
            "disclaimer": self.disclaimer,
            "has_coverage_gaps": self.has_coverage_gaps,
            "interface": self.interface,
            "is_exhaustive": self.is_exhaustive,
            "is_legal_advice": self.is_legal_advice,
            "is_review_only": self.is_review_only,
            "matched_obligations": [m.to_dict() for m in self.matched_obligations],
            "matched_rule_ids": list(self.matched_rule_ids),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "pack_content_digest": self.pack_content_digest,
            "pack_id": self.pack_id,
            "pack_status": (
                self.pack_status.value
                if isinstance(self.pack_status, PackStatus)
                else str(self.pack_status)
            ),
            "pack_version": self.pack_version,
            "profile": self.profile.to_dict() if self.profile else None,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "result_id": self.result_id,
            "review_state": (
                self.review_state.value
                if isinstance(self.review_state, ReviewState)
                else str(self.review_state)
            ),
            "ruleset_version": self.ruleset_version,
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, ObligationResolutionStatus)
                else str(self.status)
            ),
        }

    def public_projection(self) -> dict[str, Any]:
        """Redacted public view (no full rule bodies)."""
        return {
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "coverage_gap_kinds": [
                g.kind.value if isinstance(g.kind, CoverageGapKind) else str(g.kind)
                for g in self.coverage_gaps
            ],
            "has_coverage_gaps": self.has_coverage_gaps,
            "is_exhaustive": False,
            "is_legal_advice": False,
            "is_review_only": True,
            "matched_count": len(self.matched_obligations),
            "matched_rule_ids": list(self.matched_rule_ids),
            "output_kind": self.output_kind,
            "pack_id": self.pack_id,
            "pack_status": (
                self.pack_status.value
                if isinstance(self.pack_status, PackStatus)
                else str(self.pack_status)
            ),
            "pack_version": self.pack_version,
            "profile_coverage": (
                self.profile.coverage.value
                if self.profile is not None
                and isinstance(self.profile.coverage, ProfileCoverage)
                else (
                    self.profile.coverage
                    if self.profile is not None
                    else None
                )
            ),
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "result_id": self.result_id,
            "review_state": (
                self.review_state.value
                if isinstance(self.review_state, ReviewState)
                else str(self.review_state)
            ),
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
            "status": (
                self.status.value
                if isinstance(self.status, ObligationResolutionStatus)
                else str(self.status)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FilingObligationResult":
        if not isinstance(value, Mapping):
            raise TypeError("FilingObligationResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", FILING_OBLIGATION_SCHEMA_VERSION
            ),
            result_id=value.get("result_id", ""),
            request_id=value.get("request_id", ""),
            status=value.get("status", ObligationResolutionStatus.UNKNOWN.value),
            pack_id=value.get("pack_id", ""),
            pack_version=value.get("pack_version", "0.0.0"),
            pack_status=value.get("pack_status", PackStatus.DRAFT.value),
            pack_content_digest=value.get("pack_content_digest", "0" * 64),
            application_type=value.get(
                "application_type", ApplicationType.UNKNOWN.value
            ),
            scenario=value.get("scenario", FilingScenario.UNKNOWN.value),
            profile=value.get("profile"),
            matched_obligations=tuple(value.get("matched_obligations") or ()),
            coverage_gaps=tuple(value.get("coverage_gaps") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            is_review_only=bool(value.get("is_review_only", True)),
            is_exhaustive=bool(value.get("is_exhaustive", False)),
            is_legal_advice=bool(value.get("is_legal_advice", False)),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_FILING_OBLIGATION_RESULT
            ),
            disclaimer=value.get("disclaimer", REVIEW_ONLY_OBLIGATION_DISCLAIMER),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            matter_id=value.get("matter_id"),
            ruleset_version=value.get(
                "ruleset_version", FILING_OBLIGATION_RULESET_VERSION
            ),
            contracts_schema_version=value.get(
                "contracts_schema_version", CONTRACTS_SCHEMA_VERSION
            ),
            interface=value.get("interface", FILING_OBLIGATION_INTERFACE),
        )


# ---------------------------------------------------------------------------
# Resolution core
# ---------------------------------------------------------------------------


def _app_value(app: ApplicationType | str) -> str:
    if isinstance(app, ApplicationType):
        return app.value
    return str(app)


def match_rules(
    pack: FilingObligationPack,
    request: FilingObligationRequest,
    *,
    max_matched: int = DEFAULT_MAX_MATCHED,
) -> tuple[FilingObligationRule, ...]:
    """Return pack rules matching the request keys (deterministic order)."""
    if max_matched < 1:
        raise ValueError("max_matched must be >= 1")
    as_of = request.effective_as_of
    matched: list[FilingObligationRule] = []
    for rule in pack.rules:
        if rule.jurisdiction is not request.jurisdiction:
            # Allow unknown jurisdiction on either side only if both unknown.
            if not (
                rule.jurisdiction is Jurisdiction.UNKNOWN
                or request.jurisdiction is Jurisdiction.UNKNOWN
            ):
                continue
        if rule.matches_keys(
            application_type=request.application_type,
            scenario=request.scenario,
            legal_regime=request.legal_regime,
            entity_status=request.entity_status,
            prosecution_stage=request.prosecution_stage,
            as_of=as_of,
        ):
            matched.append(rule)
            if len(matched) >= max_matched:
                break
    return tuple(matched)


def resolve_filing_obligations(
    request: FilingObligationRequest,
    *,
    pack: FilingObligationPack | None = None,
    id_factory: Callable[[], str] | None = None,
    max_matched: int = DEFAULT_MAX_MATCHED,
    max_gaps: int = DEFAULT_MAX_GAPS,
    require_active_pack: bool = True,
) -> FilingObligationResult:
    """Resolve filing obligations for *request* against a versioned pack.

    If *pack* is omitted, uses ``request.pack`` or loads the baseline fixture.
    When *require_active_pack* is True (default), a non-active pack yields
    ``pack_not_active`` status and a coverage gap rather than silent matches.
    """
    ids = id_factory or _default_id_factory()
    resolved_pack = pack or request.pack
    reasons: list[str] = [
        ObligationReasonCode.REVIEW_ONLY.value,
        ObligationReasonCode.NOT_LEGAL_ADVICE.value,
        ObligationReasonCode.NOT_EXHAUSTIVE.value,
        ObligationReasonCode.FORM_INSTRUCTIONS_NOT_CONTROLLING.value,
        ObligationReasonCode.HUMAN_REVIEW_REQUIRED.value,
    ]

    if resolved_pack is None:
        resolved_pack = load_baseline_rules()
        reasons.append(ObligationReasonCode.BASELINE_LOADED.value)

    if not isinstance(resolved_pack, FilingObligationPack):
        raise TypeError("pack must be FilingObligationPack")

    app = request.application_type
    if not isinstance(app, ApplicationType):
        app = _coerce_enum(ApplicationType, app, "application_type")  # type: ignore[assignment]
    scen = request.scenario
    if not isinstance(scen, FilingScenario):
        scen = _coerce_enum(FilingScenario, scen, "scenario")  # type: ignore[assignment]

    app_s = _app_value(app)
    is_special = app_s in SPECIAL_APPLICATION_TYPES
    if is_special:
        reasons.append(ObligationReasonCode.SPECIAL_TYPE_EXPLICIT.value)
        reasons.append(ObligationReasonCode.NO_SILENT_UTILITY_REUSE.value)

    profile = resolved_pack.profile_for(app)
    pack_status = resolved_pack.status
    pack_digest = resolved_pack.content_digest()
    gaps: list[CoverageGap] = []
    matched: list[MatchedObligation] = []

    # --- Pack activation gate ---
    pack_active = pack_status is PackStatus.ACTIVE
    if require_active_pack and not pack_active:
        reasons.append(ObligationReasonCode.PACK_NOT_ACTIVE.value)
        gaps.append(
            CoverageGap(
                gap_id=ids(),
                kind=CoverageGapKind.PACK_NOT_ACTIVE,
                application_type=app,
                scenario=scen,
                description=(
                    f"Pack {resolved_pack.pack_id}@{resolved_pack.version} is "
                    f"not active (status={pack_status.value if isinstance(pack_status, PackStatus) else pack_status}). "
                    "A pack cannot drive obligation matching until source digests "
                    "and human approval are recorded and the pack is activated."
                ),
                profile_coverage=profile.coverage if profile else None,
                blocking=True,
            )
        )
        status = ObligationResolutionStatus.PACK_NOT_ACTIVE
        return FilingObligationResult(
            schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
            result_id=ids(),
            request_id=request.request_id,
            status=status,
            pack_id=resolved_pack.pack_id,
            pack_version=resolved_pack.version,
            pack_status=pack_status,
            pack_content_digest=pack_digest,
            application_type=app,
            scenario=scen,
            profile=profile,
            matched_obligations=(),
            coverage_gaps=tuple(gaps[:max_gaps]),
            reason_codes=tuple(dict.fromkeys(reasons)),
            classification=request.classification,
            matter_id=request.matter_id,
        )

    reasons.append(ObligationReasonCode.PACK_ACTIVE.value)

    # --- Profile disposition ---
    if profile is None:
        if is_special:
            # Special types without explicit profile → unknown (never utility reuse).
            reasons.append(ObligationReasonCode.PROFILE_UNKNOWN.value)
            gaps.append(
                CoverageGap(
                    gap_id=ids(),
                    kind=CoverageGapKind.MISSING_SPECIAL_PROFILE,
                    application_type=app,
                    scenario=scen,
                    description=(
                        f"Application type {app_s} requires an explicit reviewed "
                        "profile (supported, out_of_scope, or unknown). Utility "
                        "rules are never silently reused."
                    ),
                    profile_coverage=ProfileCoverage.UNKNOWN,
                    blocking=True,
                )
            )
            status = ObligationResolutionStatus.UNKNOWN
            return FilingObligationResult(
                schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
                result_id=ids(),
                request_id=request.request_id,
                status=status,
                pack_id=resolved_pack.pack_id,
                pack_version=resolved_pack.version,
                pack_status=pack_status,
                pack_content_digest=pack_digest,
                application_type=app,
                scenario=scen,
                profile=None,
                matched_obligations=(),
                coverage_gaps=tuple(gaps[:max_gaps]),
                reason_codes=tuple(dict.fromkeys(reasons)),
                classification=request.classification,
                matter_id=request.matter_id,
            )
        # Non-special without profile: still a coverage gap (unsupported type).
        reasons.append(ObligationReasonCode.PROFILE_UNKNOWN.value)
        reasons.append(ObligationReasonCode.COVERAGE_GAP.value)
        gaps.append(
            CoverageGap(
                gap_id=ids(),
                kind=CoverageGapKind.UNSUPPORTED_APPLICATION_TYPE,
                application_type=app,
                scenario=scen,
                description=(
                    f"No reviewed application-type profile for {app_s} in pack "
                    f"{resolved_pack.pack_id}@{resolved_pack.version}."
                ),
                profile_coverage=ProfileCoverage.UNKNOWN,
                blocking=True,
            )
        )
        status = ObligationResolutionStatus.COVERAGE_GAP
        return FilingObligationResult(
            schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
            result_id=ids(),
            request_id=request.request_id,
            status=status,
            pack_id=resolved_pack.pack_id,
            pack_version=resolved_pack.version,
            pack_status=pack_status,
            pack_content_digest=pack_digest,
            application_type=app,
            scenario=scen,
            profile=None,
            matched_obligations=(),
            coverage_gaps=tuple(gaps[:max_gaps]),
            reason_codes=tuple(dict.fromkeys(reasons)),
            classification=request.classification,
            matter_id=request.matter_id,
        )

    if profile.coverage is ProfileCoverage.OUT_OF_SCOPE:
        reasons.append(ObligationReasonCode.PROFILE_OUT_OF_SCOPE.value)
        gaps.append(
            CoverageGap(
                gap_id=ids(),
                kind=CoverageGapKind.PROFILE_OUT_OF_SCOPE,
                application_type=app,
                scenario=scen,
                description=(
                    profile.notes
                    or (
                        f"Application type {app_s} is explicitly out of scope for "
                        f"pack {resolved_pack.pack_id}@{resolved_pack.version}."
                    )
                ),
                profile_coverage=ProfileCoverage.OUT_OF_SCOPE,
                blocking=True,
            )
        )
        return FilingObligationResult(
            schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
            result_id=ids(),
            request_id=request.request_id,
            status=ObligationResolutionStatus.OUT_OF_SCOPE,
            pack_id=resolved_pack.pack_id,
            pack_version=resolved_pack.version,
            pack_status=pack_status,
            pack_content_digest=pack_digest,
            application_type=app,
            scenario=scen,
            profile=profile,
            matched_obligations=(),
            coverage_gaps=tuple(gaps[:max_gaps]),
            reason_codes=tuple(dict.fromkeys(reasons)),
            classification=request.classification,
            matter_id=request.matter_id,
        )

    if profile.coverage is ProfileCoverage.UNKNOWN:
        reasons.append(ObligationReasonCode.PROFILE_UNKNOWN.value)
        gaps.append(
            CoverageGap(
                gap_id=ids(),
                kind=CoverageGapKind.PROFILE_UNKNOWN,
                application_type=app,
                scenario=scen,
                description=(
                    profile.notes
                    or (
                        f"Application type {app_s} profile is unknown for pack "
                        f"{resolved_pack.pack_id}@{resolved_pack.version}."
                    )
                ),
                profile_coverage=ProfileCoverage.UNKNOWN,
                blocking=True,
            )
        )
        return FilingObligationResult(
            schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
            result_id=ids(),
            request_id=request.request_id,
            status=ObligationResolutionStatus.UNKNOWN,
            pack_id=resolved_pack.pack_id,
            pack_version=resolved_pack.version,
            pack_status=pack_status,
            pack_content_digest=pack_digest,
            application_type=app,
            scenario=scen,
            profile=profile,
            matched_obligations=(),
            coverage_gaps=tuple(gaps[:max_gaps]),
            reason_codes=tuple(dict.fromkeys(reasons)),
            classification=request.classification,
            matter_id=request.matter_id,
        )

    # Supported profile — match rules.
    reasons.append(ObligationReasonCode.PROFILE_SUPPORTED.value)
    if profile.scenarios_in_scope:
        scen_s = scen.value if isinstance(scen, FilingScenario) else str(scen)
        if scen_s not in profile.scenarios_in_scope:
            reasons.append(ObligationReasonCode.COVERAGE_GAP.value)
            gaps.append(
                CoverageGap(
                    gap_id=ids(),
                    kind=CoverageGapKind.UNSUPPORTED_SCENARIO,
                    application_type=app,
                    scenario=scen,
                    description=(
                        f"Scenario {scen_s} is not in the reviewed in-scope "
                        f"scenarios for application type {app_s}: "
                        f"{', '.join(profile.scenarios_in_scope)}."
                    ),
                    profile_coverage=ProfileCoverage.SUPPORTED,
                    blocking=True,
                )
            )
            return FilingObligationResult(
                schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
                result_id=ids(),
                request_id=request.request_id,
                status=ObligationResolutionStatus.COVERAGE_GAP,
                pack_id=resolved_pack.pack_id,
                pack_version=resolved_pack.version,
                pack_status=pack_status,
                pack_content_digest=pack_digest,
                application_type=app,
                scenario=scen,
                profile=profile,
                matched_obligations=(),
                coverage_gaps=tuple(gaps[:max_gaps]),
                reason_codes=tuple(dict.fromkeys(reasons)),
                classification=request.classification,
                matter_id=request.matter_id,
            )

    rules = match_rules(resolved_pack, request, max_matched=max_matched)
    for rank, rule in enumerate(rules):
        matched.append(
            MatchedObligation(match_id=ids(), rule=rule, match_rank=rank)
        )

    if not matched:
        reasons.append(ObligationReasonCode.COVERAGE_GAP.value)
        gaps.append(
            CoverageGap(
                gap_id=ids(),
                kind=CoverageGapKind.NO_MATCHING_RULES,
                application_type=app,
                scenario=scen,
                description=(
                    f"No obligation rules match application_type={app_s}, "
                    f"scenario={scen.value if isinstance(scen, FilingScenario) else scen}, "
                    f"as_of={request.effective_as_of!r}, "
                    f"regime={request.legal_regime.value if isinstance(request.legal_regime, LegalRegime) else request.legal_regime}, "
                    f"entity={request.entity_status.value if isinstance(request.entity_status, EntityStatus) else request.entity_status}, "
                    f"stage={request.prosecution_stage.value if isinstance(request.prosecution_stage, ProsecutionStage) else request.prosecution_stage}."
                ),
                profile_coverage=ProfileCoverage.SUPPORTED,
                blocking=True,
            )
        )
        status = ObligationResolutionStatus.COVERAGE_GAP
    else:
        reasons.append(ObligationReasonCode.RULES_MATCHED.value)
        reasons.append(ObligationReasonCode.RESOLVED.value)
        status = ObligationResolutionStatus.MATCHED

    return FilingObligationResult(
        schema_version=FILING_OBLIGATION_SCHEMA_VERSION,
        result_id=ids(),
        request_id=request.request_id,
        status=status,
        pack_id=resolved_pack.pack_id,
        pack_version=resolved_pack.version,
        pack_status=pack_status,
        pack_content_digest=pack_digest,
        application_type=app,
        scenario=scen,
        profile=profile,
        matched_obligations=tuple(matched),
        coverage_gaps=tuple(gaps[:max_gaps]),
        reason_codes=tuple(dict.fromkeys(reasons)),
        classification=request.classification,
        matter_id=request.matter_id,
    )


# ---------------------------------------------------------------------------
# Processor class
# ---------------------------------------------------------------------------


class FilingObligationProcessor:
    """Resolve filing obligations from versioned, activated rule packs."""

    schema_version: Final = FILING_OBLIGATION_SCHEMA_VERSION
    interface: Final = FILING_OBLIGATION_INTERFACE
    ruleset_version: Final = FILING_OBLIGATION_RULESET_VERSION

    def __init__(
        self,
        *,
        pack: FilingObligationPack | None = None,
        baseline_path: str | Path | None = None,
        id_factory: Callable[[], str] | None = None,
        require_active_pack: bool = True,
        max_matched: int = DEFAULT_MAX_MATCHED,
        max_gaps: int = DEFAULT_MAX_GAPS,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory()
        self._require_active_pack = bool(require_active_pack)
        self._max_matched = int(max_matched)
        self._max_gaps = int(max_gaps)
        if pack is not None:
            self._pack = pack
        elif baseline_path is not None:
            self._pack = load_baseline_rules(baseline_path)
        else:
            try:
                self._pack = load_baseline_rules()
            except FilingRulePackError:
                self._pack = None

    @property
    def pack(self) -> FilingObligationPack | None:
        return self._pack

    def load_baseline(self, path: str | Path | None = None) -> FilingObligationPack:
        self._pack = load_baseline_rules(path)
        return self._pack

    def set_pack(self, pack: FilingObligationPack) -> None:
        if not isinstance(pack, FilingObligationPack):
            raise TypeError("pack must be FilingObligationPack")
        self._pack = pack

    def activate_loaded_pack(self) -> FilingObligationPack:
        """Activate the loaded pack if gates pass; raise otherwise."""
        if self._pack is None:
            raise FilingObligationProcessorError(
                "no pack loaded", code="no_pack_loaded"
            )
        self._pack = activate_pack(self._pack)
        return self._pack

    def process(
        self, request: FilingObligationRequest | Mapping[str, Any]
    ) -> FilingObligationResult:
        if isinstance(request, Mapping):
            request = FilingObligationRequest.from_dict(request)
        if not isinstance(request, FilingObligationRequest):
            raise TypeError("request must be FilingObligationRequest")
        pack = request.pack or self._pack
        return resolve_filing_obligations(
            request,
            pack=pack,
            id_factory=self._id_factory,
            max_matched=self._max_matched,
            max_gaps=self._max_gaps,
            require_active_pack=self._require_active_pack,
        )

    def resolve(
        self,
        *,
        request_id: str,
        application_type: ApplicationType | str,
        scenario: FilingScenario | str,
        filing_date: str | None = None,
        as_of: str | None = None,
        legal_regime: LegalRegime | str = LegalRegime.AIA,
        entity_status: EntityStatus | str = EntityStatus.UNDISCOUNTED,
        prosecution_stage: ProsecutionStage | str = ProsecutionStage.FILING,
        matter_id: str | None = None,
        classification: DisclosureClassification | str = (
            DisclosureClassification.PUBLIC_USER
        ),
    ) -> FilingObligationResult:
        """Convenience wrapper building a request then processing it."""
        req = FilingObligationRequest(
            request_id=request_id,
            application_type=application_type,
            scenario=scenario,
            filing_date=filing_date,
            as_of=as_of,
            legal_regime=legal_regime,
            entity_status=entity_status,
            prosecution_stage=prosecution_stage,
            matter_id=matter_id,
            classification=classification,
            pack=self._pack,
        )
        return self.process(req)


def build_request_from_mapping(
    value: Mapping[str, Any],
    *,
    pack: FilingObligationPack | None = None,
) -> FilingObligationRequest:
    """Build a request from a compact recipe/mapping case."""
    if not isinstance(value, Mapping):
        raise TypeError("value must be a mapping")
    data = dict(value)
    if pack is not None and "pack" not in data:
        data["pack"] = pack
    return FilingObligationRequest.from_dict(data)


def ensure_active_baseline(
    path: str | Path | None = None,
) -> FilingObligationPack:
    """Load baseline fixture and return it only if already active.

    Does **not** silently activate; activation requires recorded digests and
    human approval already present in the fixture (or via :func:`activate_pack`).
    """
    pack = load_baseline_rules(path)
    if pack.status is not PackStatus.ACTIVE:
        blocks = pack.activation_block_reasons()
        raise FilingObligationProcessorError(
            "baseline pack is not active: " + ", ".join(blocks or ("status",)),
            code="baseline_not_active",
        )
    return pack


__all__ = [
    "BASELINE_FIXTURE_RELATIVE",
    "BASELINE_PACK_ID",
    "CoverageGap",
    "CoverageGapKind",
    "DEFAULT_MAX_GAPS",
    "DEFAULT_MAX_MATCHED",
    "FILING_OBLIGATION_INTERFACE",
    "FILING_OBLIGATION_RULESET_VERSION",
    "FILING_OBLIGATION_SCHEMA_VERSION",
    "FilingObligationProcessor",
    "FilingObligationProcessorError",
    "FilingObligationRequest",
    "FilingObligationResult",
    "MatchedObligation",
    "OUTPUT_KIND_FILING_OBLIGATION_RESULT",
    "ObligationReasonCode",
    "ObligationResolutionStatus",
    "REVIEW_ONLY_OBLIGATION_DISCLAIMER",
    "build_request_from_mapping",
    "ensure_active_baseline",
    "match_rules",
    "resolve_filing_obligations",
    "sha256_hex",
]
