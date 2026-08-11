"""Compile government instructions into typed requirements (PATLAW-040).

Takes office-action candidates (PATLAW-032) and optional as-of authority
(PATLAW-016 / PATLAW-017) and produces typed requirement predicates.

Design invariants
-----------------
* The compiler **never drops uncompiled text** — residual / unsupported
  language is retained as explicit :class:`UncompiledClause` records.
* Every **admitted** predicate has an instruction span and resolved
  authority/applicability *state* (states may be ``unknown``).
* Missing or ambiguous authority resolution yields ``unknown``, never a
  fabricated governing source.
* Output is deterministic and versioned (stable IDs, sorted keys, schema /
  ruleset versions).
* Authority graph and office-action records are immutable inputs; this module
  owns typed requirement compilation only.

Document body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ExtractedSpan,
    GovernmentRequirement,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    OFFICE_ACTION_SCHEMA_VERSION,
    ActionLifecycleRecord,
    ActionLifecycleStatus,
    AnalysisCandidate,
    CandidateKind,
    CandidateOrigin,
    EvidenceLayer,
    OfficeActionResult,
)
from ipfs_datasets_py.processors.legal_data.patent_citation_resolver import (
    CitationMatchKind,
    CitationResolutionResult,
    PatentCitationResolver,
    parse_patent_citations,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_registry import (
    PatentTemporalAuthorityGraph,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

REQUIREMENT_PROCESSOR_SCHEMA_VERSION: Final = "uspto.requirement-processor.v1"
REQUIREMENT_PROCESSOR_INTERFACE: Final = "RequirementProcessor@1"
REQUIREMENT_COMPILER_RULESET_VERSION: Final = "requirement-compiler-rules@1"

DEFAULT_MAX_PREDICATES: Final = 4096
DEFAULT_MAX_UNCOMPILED: Final = 512
DEFAULT_MAX_SURFACE: Final = 8000

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# Composition / structure cues (deterministic surface patterns).
_CONDITIONAL_RE = re.compile(
    r"(?i)\b(?:"
    r"if\b|when\b|whenever\b|unless\b|provided\s+that\b|"
    r"subject\s+to\b|contingent\s+upon\b|on\s+condition\s+that\b|"
    r"in\s+the\s+event\b|only\s+if\b"
    r")"
)
_DISJUNCTIVE_RE = re.compile(
    r"(?i)\b(?:"
    r"either\b.{1,120}?\bor\b|"
    r"in\s+the\s+alternative\b|alternatively\b|"
    r"applicant\s+may\s+(?:either|choose|elect)\b"
    r")"
)
_CONJUNCTIVE_RE = re.compile(
    r"(?i)\b(?:"
    r"both\b.{1,80}?\band\b|"
    r"each\s+of\b|"
    r"all\s+of\s+the\s+following\b|"
    r"must\s+(?:also|further)\b|"
    r"in\s+addition(?:\s+to)?\b"
    r")"
)
_DATE_RULE_RE = re.compile(
    r"(?i)\b(?P<period>\d+)\s*(?P<unit>months?|days?)\b"
)
_FEE_CUE_RE = re.compile(r"(?i)\b(?:fee|fees|37\s*c\.?f\.?r\.?\s*§?\s*1\.16)\b")
_FORM_CUE_RE = re.compile(
    r"(?i)\b(?:form\s+(?:PTO|SB|AIA)[-/]?\w+|IDS|information\s+disclosure)\b"
)

# Candidate kinds that may become admitted instruction predicates.
_INSTRUCTION_KINDS: Final[frozenset[CandidateKind]] = frozenset(
    {
        CandidateKind.REJECTION,
        CandidateKind.OBJECTION,
        CandidateKind.INFORMALITY,
        CandidateKind.RESPONSE_INSTRUCTION,
        CandidateKind.FEE,
        CandidateKind.FORM,
        CandidateKind.FORM_PARAGRAPH,
    }
)

# Kinds retained as uncompiled when not compiled into structure.
_ALWAYS_UNCOMPILED_KINDS: Final[frozenset[CandidateKind]] = frozenset(
    {
        CandidateKind.UNCOMPILED_LANGUAGE,
    }
)

# Contextual kinds that feed composition / exceptions but are not admitted alone
# when they lack requirement_type and instruction force.
_CONTEXT_KINDS: Final[frozenset[CandidateKind]] = frozenset(
    {
        CandidateKind.ALTERNATIVE,
        CandidateKind.EXCEPTION,
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RequirementComposition(str, Enum):
    """Logical structure of a compiled requirement."""

    ATOMIC = "atomic"
    CONDITIONAL = "conditional"
    ALTERNATIVE = "alternative"
    CONJUNCTIVE = "conjunctive"
    DISJUNCTIVE = "disjunctive"


class RequirementScope(str, Enum):
    """Who / what the requirement applies to."""

    CLAIM_SPECIFIC = "claim_specific"
    DOCUMENT = "document"
    FORM = "form"
    FEE = "fee"
    RESPONSE = "response"
    GENERAL = "general"
    UNKNOWN = "unknown"


class AuthorityResolutionState(str, Enum):
    """Resolved authority state for an admitted predicate.

    Missing or ambiguous authority is always ``unknown`` (fail-closed).
    ``not_applicable`` is used only when no legal source is cited.
    """

    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"


class ApplicabilityState(str, Enum):
    """Applicability of a requirement to the current matter/action."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class PredicateAdmissionState(str, Enum):
    ADMITTED = "admitted"
    UNCOMPILED = "uncompiled"
    REJECTED = "rejected"


class CompilationDisposition(str, Enum):
    COMPILED = "compiled"
    REVIEW = "review"
    UNKNOWN = "unknown"
    EMPTY = "empty"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class RequirementReasonCode(str, Enum):
    PREDICATES_ADMITTED = "predicates_admitted"
    UNCOMPILED_RETAINED = "uncompiled_retained"
    AUTHORITY_RESOLVED = "authority_resolved"
    AUTHORITY_UNKNOWN = "authority_unknown"
    AUTHORITY_AMBIGUOUS = "authority_ambiguous"
    AUTHORITY_NOT_APPLICABLE = "authority_not_applicable"
    APPLICABILITY_CONDITIONAL = "applicability_conditional"
    APPLICABILITY_NOT_APPLICABLE = "applicability_not_applicable"
    LIFECYCLE_INACTIVE = "lifecycle_inactive"
    MISSING_SPAN = "missing_span"
    UNVERIFIED_HELD = "unverified_held"
    MODEL_CANDIDATE_HELD = "model_candidate_held"
    COMPOSITION_ALTERNATIVE = "composition_alternative"
    COMPOSITION_CONDITIONAL = "composition_conditional"
    COMPOSITION_CONJUNCTIVE = "composition_conjunctive"
    COMPOSITION_DISJUNCTIVE = "composition_disjunctive"
    EMPTY_INPUT = "empty_input"
    QUARANTINED = "quarantined"
    PREDICATE_LIMIT = "predicate_limit"
    UNCOMPILED_LIMIT = "uncompiled_limit"
    GOVERNMENT_REQUIREMENTS_EMITTED = "government_requirements_emitted"
    NO_AUTHORITY_GRAPH = "no_authority_graph"
    SPAN_VALIDATED = "span_validated"


class RequirementCompilationError(ValueError):
    """Raised for invalid compilation inputs (never logs document body)."""

    def __init__(self, message: str, *, code: str = "requirement_compilation_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text))


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


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be float or None") from exc
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{field} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    for member in enum_cls:
        if member.value == text or member.name == text or member.name.lower() == text.lower():
            return member
    raise ValueError(f"{field} has unknown value: {value!r}")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    return _coerce_enum(  # type: ignore[return-value]
        DisclosureClassification, value, "classification"
    )


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


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 32
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    out: dict[str, str] = {}
    for i, (k, v) in enumerate(sorted(value.items(), key=lambda kv: str(kv[0]))):
        if i >= max_items:
            break
        key = str(k).strip()
        if not key:
            continue
        if not isinstance(v, str):
            v = str(v)
        out[key[:128]] = v.strip()[:512]
    return MappingProxyType(out)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    max_predicates: int = DEFAULT_MAX_PREDICATES
    max_uncompiled: int = DEFAULT_MAX_UNCOMPILED
    max_surface: int = DEFAULT_MAX_SURFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_predicates", _nonneg_int(self.max_predicates, "max_predicates")
        )
        object.__setattr__(
            self, "max_uncompiled", _nonneg_int(self.max_uncompiled, "max_uncompiled")
        )
        object.__setattr__(
            self, "max_surface", _nonneg_int(self.max_surface, "max_surface")
        )
        if self.max_predicates == 0:
            object.__setattr__(self, "max_predicates", DEFAULT_MAX_PREDICATES)
        if self.max_uncompiled == 0:
            object.__setattr__(self, "max_uncompiled", DEFAULT_MAX_UNCOMPILED)
        if self.max_surface == 0:
            object.__setattr__(self, "max_surface", DEFAULT_MAX_SURFACE)


@dataclass(frozen=True, slots=True)
class AuthorityBinding:
    """Resolved authority state for one admitted predicate."""

    state: AuthorityResolutionState
    citation_surfaces: tuple[str, ...]
    citation_keys: tuple[str, ...]
    selected_node_ids: tuple[str, ...]
    selected_versions: tuple[str, ...]
    match_kinds: tuple[str, ...]
    authority_tiers: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state",
            _coerce_enum(AuthorityResolutionState, self.state, "state"),
        )
        object.__setattr__(
            self,
            "citation_surfaces",
            _tuple_of_str(self.citation_surfaces, "citation_surfaces", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "selected_node_ids",
            _tuple_of_str(self.selected_node_ids, "selected_node_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "selected_versions",
            _tuple_of_str(self.selected_versions, "selected_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "match_kinds",
            _tuple_of_str(self.match_kinds, "match_kinds", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_tiers",
            _tuple_of_str(self.authority_tiers, "authority_tiers", max_items=64),
        )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=32)
        )

    @property
    def is_unknown(self) -> bool:
        return self.state in (
            AuthorityResolutionState.UNKNOWN,
            AuthorityResolutionState.AMBIGUOUS,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_tiers": list(self.authority_tiers),
            "citation_keys": list(self.citation_keys),
            "citation_surfaces": list(self.citation_surfaces),
            "match_kinds": list(self.match_kinds),
            "reasons": list(self.reasons),
            "selected_node_ids": list(self.selected_node_ids),
            "selected_versions": list(self.selected_versions),
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityBinding":
        if not isinstance(value, Mapping):
            raise TypeError("AuthorityBinding must be a mapping")
        return cls(
            state=value.get("state", AuthorityResolutionState.UNKNOWN.value),
            citation_surfaces=tuple(value.get("citation_surfaces") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            selected_node_ids=tuple(value.get("selected_node_ids") or ()),
            selected_versions=tuple(value.get("selected_versions") or ()),
            match_kinds=tuple(value.get("match_kinds") or ()),
            authority_tiers=tuple(value.get("authority_tiers") or ()),
            reasons=tuple(value.get("reasons") or ()),
        )


@dataclass(frozen=True, slots=True)
class ApplicabilityBinding:
    """Applicability state for one admitted predicate."""

    state: ApplicabilityState
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    lifecycle_status: str | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state",
            _coerce_enum(ApplicabilityState, self.state, "state"),
        )
        object.__setattr__(
            self,
            "conditions",
            _tuple_of_str(self.conditions, "conditions", max_items=64),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=64),
        )
        object.__setattr__(
            self,
            "lifecycle_status",
            _optional_str(self.lifecycle_status, "lifecycle_status", max_len=64),
        )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "lifecycle_status": self.lifecycle_status,
            "reasons": list(self.reasons),
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicabilityBinding":
        if not isinstance(value, Mapping):
            raise TypeError("ApplicabilityBinding must be a mapping")
        return cls(
            state=value.get("state", ApplicabilityState.UNKNOWN.value),
            conditions=tuple(value.get("conditions") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            lifecycle_status=value.get("lifecycle_status"),
            reasons=tuple(value.get("reasons") or ()),
        )


@dataclass(frozen=True, slots=True)
class CompiledPredicate:
    """Admitted typed requirement predicate with span + authority/applicability."""

    schema_version: str
    predicate_id: str
    source_candidate_id: str | None
    source_span_id: str
    instruction_text_digest: str
    surface_text: str
    composition: RequirementComposition
    scope: RequirementScope
    requirement_type: str
    affected_claims: tuple[str, ...]
    legal_citations: tuple[str, ...]
    child_predicate_ids: tuple[str, ...]
    authority: AuthorityBinding
    applicability: ApplicabilityBinding
    proposed_date_rule: str | None
    parser_confidence: float | None
    review_state: ReviewState
    classification: DisclosureClassification
    admission: PredicateAdmissionState
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REQUIREMENT_PROCESSOR_SCHEMA_VERSION:
            raise ValueError(
                "CompiledPredicate.schema_version must be "
                f"{REQUIREMENT_PROCESSOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "predicate_id", _identifier(self.predicate_id, "predicate_id")
        )
        object.__setattr__(
            self,
            "source_candidate_id",
            _optional_identifier(self.source_candidate_id, "source_candidate_id"),
        )
        # Every admitted predicate MUST have an instruction span.
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        object.__setattr__(
            self,
            "instruction_text_digest",
            _sha256_hex_field(self.instruction_text_digest, "instruction_text_digest"),
        )
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > DEFAULT_MAX_SURFACE:
            object.__setattr__(self, "surface_text", self.surface_text[:DEFAULT_MAX_SURFACE])
        object.__setattr__(
            self,
            "composition",
            _coerce_enum(RequirementComposition, self.composition, "composition"),
        )
        object.__setattr__(
            self, "scope", _coerce_enum(RequirementScope, self.scope, "scope")
        )
        object.__setattr__(
            self,
            "requirement_type",
            _require_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=64),
        )
        object.__setattr__(
            self,
            "child_predicate_ids",
            _tuple_of_str(
                self.child_predicate_ids, "child_predicate_ids", max_items=128
            ),
        )
        if not isinstance(self.authority, AuthorityBinding):
            raise TypeError("authority must be AuthorityBinding")
        if not isinstance(self.applicability, ApplicabilityBinding):
            raise TypeError("applicability must be ApplicabilityBinding")
        object.__setattr__(
            self,
            "proposed_date_rule",
            _optional_str(self.proposed_date_rule, "proposed_date_rule", max_len=256),
        )
        object.__setattr__(
            self,
            "parser_confidence",
            _optional_float_01(self.parser_confidence, "parser_confidence"),
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
            self,
            "admission",
            _coerce_enum(PredicateAdmissionState, self.admission, "admission"),
        )
        if self.admission is not PredicateAdmissionState.ADMITTED:
            raise ValueError(
                "CompiledPredicate.admission must be admitted "
                f"(got {self.admission.value})"
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_government_requirement(self) -> GovernmentRequirement:
        """Project to the shared :class:`GovernmentRequirement` contract."""
        applicability = list(self.applicability.conditions)
        if self.composition is not RequirementComposition.ATOMIC:
            applicability.append(f"composition:{self.composition.value}")
        applicability.append(f"authority_state:{self.authority.state.value}")
        applicability.append(f"applicability_state:{self.applicability.state.value}")
        return GovernmentRequirement(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            requirement_id=self.predicate_id,
            instruction_text_digest=self.instruction_text_digest,
            source_span_id=self.source_span_id,
            requirement_type=self.requirement_type,
            affected_claims=self.affected_claims,
            legal_citations=self.legal_citations,
            applicability_conditions=tuple(applicability),
            proposed_date_rule=self.proposed_date_rule,
            exceptions=self.applicability.exceptions,
            parser_confidence=self.parser_confidence,
            review_state=self.review_state,
            classification=self.classification,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value,
            "affected_claims": list(self.affected_claims),
            "applicability": self.applicability.to_dict(),
            "authority": self.authority.to_dict(),
            "child_predicate_ids": list(self.child_predicate_ids),
            "classification": self.classification.value,
            "composition": self.composition.value,
            "instruction_text_digest": self.instruction_text_digest,
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "parser_confidence": self.parser_confidence,
            "predicate_id": self.predicate_id,
            "proposed_date_rule": self.proposed_date_rule,
            "requirement_type": self.requirement_type,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "scope": self.scope.value,
            "source_candidate_id": self.source_candidate_id,
            "source_span_id": self.source_span_id,
            "surface_text": self.surface_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompiledPredicate":
        if not isinstance(value, Mapping):
            raise TypeError("CompiledPredicate must be a mapping")
        auth_raw = value.get("authority") or {}
        app_raw = value.get("applicability") or {}
        return cls(
            schema_version=value.get(
                "schema_version", REQUIREMENT_PROCESSOR_SCHEMA_VERSION
            ),
            predicate_id=value.get("predicate_id", ""),
            source_candidate_id=value.get("source_candidate_id"),
            source_span_id=value.get("source_span_id", ""),
            instruction_text_digest=value.get("instruction_text_digest", ""),
            surface_text=str(value.get("surface_text") or ""),
            composition=value.get("composition", RequirementComposition.ATOMIC.value),
            scope=value.get("scope", RequirementScope.UNKNOWN.value),
            requirement_type=value.get("requirement_type", ""),
            affected_claims=tuple(value.get("affected_claims") or ()),
            legal_citations=tuple(value.get("legal_citations") or ()),
            child_predicate_ids=tuple(value.get("child_predicate_ids") or ()),
            authority=AuthorityBinding.from_dict(auth_raw),
            applicability=ApplicabilityBinding.from_dict(app_raw),
            proposed_date_rule=value.get("proposed_date_rule"),
            parser_confidence=value.get("parser_confidence"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            admission=value.get("admission", PredicateAdmissionState.ADMITTED.value),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class UncompiledClause:
    """Unsupported instruction language retained rather than dropped."""

    schema_version: str
    clause_id: str
    source_candidate_id: str | None
    source_span_id: str
    instruction_text_digest: str
    surface_text: str
    reason: str
    review_state: ReviewState
    classification: DisclosureClassification
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REQUIREMENT_PROCESSOR_SCHEMA_VERSION:
            raise ValueError(
                "UncompiledClause.schema_version must be "
                f"{REQUIREMENT_PROCESSOR_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "clause_id", _identifier(self.clause_id, "clause_id"))
        object.__setattr__(
            self,
            "source_candidate_id",
            _optional_identifier(self.source_candidate_id, "source_candidate_id"),
        )
        object.__setattr__(
            self, "source_span_id", _identifier(self.source_span_id, "source_span_id")
        )
        object.__setattr__(
            self,
            "instruction_text_digest",
            _sha256_hex_field(self.instruction_text_digest, "instruction_text_digest"),
        )
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > DEFAULT_MAX_SURFACE:
            object.__setattr__(self, "surface_text", self.surface_text[:DEFAULT_MAX_SURFACE])
        object.__setattr__(
            self, "reason", _require_str(self.reason, "reason", max_len=256)
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
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "clause_id": self.clause_id,
            "instruction_text_digest": self.instruction_text_digest,
            "labels": dict(self.labels),
            "reason": self.reason,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_candidate_id": self.source_candidate_id,
            "source_span_id": self.source_span_id,
            "surface_text": self.surface_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UncompiledClause":
        if not isinstance(value, Mapping):
            raise TypeError("UncompiledClause must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", REQUIREMENT_PROCESSOR_SCHEMA_VERSION
            ),
            clause_id=value.get("clause_id", ""),
            source_candidate_id=value.get("source_candidate_id"),
            source_span_id=value.get("source_span_id", ""),
            instruction_text_digest=value.get("instruction_text_digest", ""),
            surface_text=str(value.get("surface_text") or ""),
            reason=value.get("reason", "unsupported_language"),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RequirementCompilationInput:
    """Input packet for requirement compilation.

    Prefer supplying a full :class:`OfficeActionResult`. Direct candidates are
    accepted for unit tests and composition with other extractors.
    """

    artifact_id: str
    candidates: tuple[AnalysisCandidate, ...] = ()
    spans: tuple[ExtractedSpan, ...] = ()
    lifecycle: tuple[ActionLifecycleRecord, ...] = ()
    office_action: OfficeActionResult | None = None
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    mailing_date: str | None = None
    analysis_id: str | None = None
    as_of: str | date | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if self.office_action is not None and not isinstance(
            self.office_action, OfficeActionResult
        ):
            raise TypeError("office_action must be OfficeActionResult or None")
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.spans, tuple):
            object.__setattr__(self, "spans", tuple(self.spans))
        if not isinstance(self.lifecycle, tuple):
            object.__setattr__(self, "lifecycle", tuple(self.lifecycle))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "analysis_id",
            _optional_identifier(self.analysis_id, "analysis_id"),
        )
        if isinstance(self.as_of, date):
            object.__setattr__(self, "as_of", self.as_of.isoformat())
        else:
            object.__setattr__(
                self, "as_of", _optional_str(self.as_of, "as_of", max_len=32)
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )


@dataclass(frozen=True, slots=True)
class RequirementCompilationResult:
    """Deterministic, versioned requirement compilation outcome."""

    schema_version: str
    compilation_id: str
    source_analysis_id: str | None
    source_artifact_id: str
    disposition: CompilationDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    predicates: tuple[CompiledPredicate, ...]
    uncompiled: tuple[UncompiledClause, ...]
    government_requirements: tuple[GovernmentRequirement, ...]
    ruleset_versions: Mapping[str, str]
    authority_graph_id: str | None
    as_of: str | None
    labels: Mapping[str, str]
    text_digest: str
    retained: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REQUIREMENT_PROCESSOR_SCHEMA_VERSION:
            raise ValueError(
                "RequirementCompilationResult.schema_version must be "
                f"{REQUIREMENT_PROCESSOR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "compilation_id", _identifier(self.compilation_id, "compilation_id")
        )
        object.__setattr__(
            self,
            "source_analysis_id",
            _optional_identifier(self.source_analysis_id, "source_analysis_id"),
        )
        object.__setattr__(
            self,
            "source_artifact_id",
            _identifier(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(CompilationDisposition, self.disposition, "disposition"),
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
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.predicates, tuple):
            object.__setattr__(self, "predicates", tuple(self.predicates))
        if not isinstance(self.uncompiled, tuple):
            object.__setattr__(self, "uncompiled", tuple(self.uncompiled))
        if not isinstance(self.government_requirements, tuple):
            object.__setattr__(
                self, "government_requirements", tuple(self.government_requirements)
            )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "authority_graph_id",
            _optional_identifier(self.authority_graph_id, "authority_graph_id"),
        )
        object.__setattr__(
            self, "as_of", _optional_str(self.as_of, "as_of", max_len=32)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        digest = _require_str(self.text_digest, "text_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        object.__setattr__(self, "retained", bool(self.retained))

        # Fail-closed invariant: every admitted predicate has span + states.
        for pred in self.predicates:
            if not isinstance(pred, CompiledPredicate):
                raise TypeError("predicates must be CompiledPredicate instances")
            if not pred.source_span_id:
                raise ValueError("admitted predicate missing source_span_id")
            if not isinstance(pred.authority, AuthorityBinding):
                raise ValueError("admitted predicate missing authority binding")
            if not isinstance(pred.applicability, ApplicabilityBinding):
                raise ValueError("admitted predicate missing applicability binding")

    @property
    def requires_review(self) -> bool:
        return self.review_state in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ) or self.disposition in (
            CompilationDisposition.REVIEW,
            CompilationDisposition.UNKNOWN,
            CompilationDisposition.QUARANTINE,
        )

    def predicates_by_composition(
        self, composition: RequirementComposition | str
    ) -> tuple[CompiledPredicate, ...]:
        comp = _coerce_enum(RequirementComposition, composition, "composition")
        return tuple(p for p in self.predicates if p.composition is comp)

    def predicates_by_scope(
        self, scope: RequirementScope | str
    ) -> tuple[CompiledPredicate, ...]:
        sc = _coerce_enum(RequirementScope, scope, "scope")
        return tuple(p for p in self.predicates if p.scope is sc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "authority_graph_id": self.authority_graph_id,
            "classification": self.classification.value,
            "compilation_id": self.compilation_id,
            "disposition": self.disposition.value,
            "government_requirements": [
                r.to_dict() for r in self.government_requirements
            ],
            "labels": dict(self.labels),
            "predicates": [p.to_dict() for p in self.predicates],
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "source_analysis_id": self.source_analysis_id,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "uncompiled": [u.to_dict() for u in self.uncompiled],
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Projection without surface text (no document body leakage)."""
        return {
            "as_of": self.as_of,
            "authority_graph_id": self.authority_graph_id,
            "classification": self.classification.value,
            "compilation_id": self.compilation_id,
            "disposition": self.disposition.value,
            "government_requirement_ids": [
                r.requirement_id for r in self.government_requirements
            ],
            "predicate_count": len(self.predicates),
            "predicate_ids": [p.predicate_id for p in self.predicates],
            "reason_codes": list(self.reason_codes),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "source_analysis_id": self.source_analysis_id,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "uncompiled_count": len(self.uncompiled),
            "uncompiled_ids": [u.clause_id for u in self.uncompiled],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementCompilationResult":
        if not isinstance(value, Mapping):
            raise TypeError("RequirementCompilationResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", REQUIREMENT_PROCESSOR_SCHEMA_VERSION
            ),
            compilation_id=value.get("compilation_id", ""),
            source_analysis_id=value.get("source_analysis_id"),
            source_artifact_id=value.get("source_artifact_id", ""),
            disposition=value.get("disposition", CompilationDisposition.UNKNOWN.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            predicates=tuple(
                CompiledPredicate.from_dict(p)
                for p in (value.get("predicates") or ())
            ),
            uncompiled=tuple(
                UncompiledClause.from_dict(u)
                for u in (value.get("uncompiled") or ())
            ),
            government_requirements=tuple(
                GovernmentRequirement.from_dict(r)
                for r in (value.get("government_requirements") or ())
            ),
            ruleset_versions=value.get("ruleset_versions") or {},
            authority_graph_id=value.get("authority_graph_id"),
            as_of=value.get("as_of"),
            labels=value.get("labels") or {},
            text_digest=value.get("text_digest", sha256_hex("")),
            retained=bool(value.get("retained", True)),
        )


# ---------------------------------------------------------------------------
# Pure classification helpers (exported for unit tests)
# ---------------------------------------------------------------------------


def detect_composition(
    surface: str,
    *,
    alternatives: Sequence[str] = (),
    exceptions: Sequence[str] = (),
    labels: Mapping[str, str] | None = None,
) -> RequirementComposition:
    """Deterministically detect logical composition from surface cues."""
    labels = labels or {}
    explicit = (labels.get("composition") or labels.get("requirement_composition") or "").strip().lower()
    if explicit:
        for member in RequirementComposition:
            if member.value == explicit:
                return member

    if alternatives:
        return RequirementComposition.ALTERNATIVE

    text = surface or ""
    if _DISJUNCTIVE_RE.search(text):
        # "either...or" / "in the alternative" → disjunctive/alternative.
        if re.search(r"(?i)\beither\b", text):
            return RequirementComposition.DISJUNCTIVE
        return RequirementComposition.ALTERNATIVE
    if _CONDITIONAL_RE.search(text) or exceptions:
        # Exceptions alone still mark conditional applicability structure.
        if _CONDITIONAL_RE.search(text):
            return RequirementComposition.CONDITIONAL
        # bare exception list without conditional cue stays atomic unless
        # alternatives already handled above.
    if _CONDITIONAL_RE.search(text):
        return RequirementComposition.CONDITIONAL
    if _CONJUNCTIVE_RE.search(text):
        return RequirementComposition.CONJUNCTIVE
    return RequirementComposition.ATOMIC


def detect_scope(
    kind: CandidateKind | str,
    *,
    claim_tokens: Sequence[str] = (),
    surface: str = "",
    requirement_type: str | None = None,
) -> RequirementScope:
    """Map candidate kind / claims / cues to a requirement scope."""
    if not isinstance(kind, CandidateKind):
        kind = _coerce_enum(CandidateKind, kind, "kind")  # type: ignore[assignment]
    assert isinstance(kind, CandidateKind)

    if kind is CandidateKind.FEE or _FEE_CUE_RE.search(surface or ""):
        return RequirementScope.FEE
    if kind is CandidateKind.FORM or (
        requirement_type and "form" in requirement_type.lower()
    ) or _FORM_CUE_RE.search(surface or ""):
        return RequirementScope.FORM
    if kind is CandidateKind.RESPONSE_INSTRUCTION:
        return RequirementScope.RESPONSE
    if claim_tokens:
        return RequirementScope.CLAIM_SPECIFIC
    if kind in (
        CandidateKind.REJECTION,
        CandidateKind.OBJECTION,
        CandidateKind.INFORMALITY,
    ):
        # Claim-oriented kinds without tokens remain document-level with review.
        return RequirementScope.DOCUMENT
    if kind is CandidateKind.FORM_PARAGRAPH:
        return RequirementScope.DOCUMENT
    return RequirementScope.GENERAL


def propose_date_rule(
    kind: CandidateKind | str,
    *,
    surface: str = "",
    labels: Mapping[str, str] | None = None,
) -> str | None:
    """Extract a proposed date-rule identifier (candidate, not docket order)."""
    labels = labels or {}
    if labels.get("response_period"):
        period = labels["response_period"].strip().lower().replace(" ", "_")
        return f"response_period:{period}"
    if not isinstance(kind, CandidateKind):
        kind = _coerce_enum(CandidateKind, kind, "kind")  # type: ignore[assignment]
    assert isinstance(kind, CandidateKind)
    if kind is CandidateKind.RESPONSE_INSTRUCTION:
        m = _DATE_RULE_RE.search(surface or "")
        if m:
            return f"period_{m.group('period')}_{m.group('unit').lower()}"
        return "37_cfr_1.134_non_final_response"
    return None


def lifecycle_primary_inactive(
    lifecycle: Sequence[ActionLifecycleRecord],
) -> tuple[bool, str | None]:
    """Return whether the primary action lifecycle is inactive, plus status."""
    if not lifecycle:
        return False, None
    statuses = {r.status for r in lifecycle}
    # A reissued/active OA may list a rescinded predecessor.
    if ActionLifecycleStatus.REISSUED in statuses or ActionLifecycleStatus.ACTIVE in statuses:
        active = next(
            (
                r
                for r in lifecycle
                if r.status
                in (ActionLifecycleStatus.ACTIVE, ActionLifecycleStatus.REISSUED)
            ),
            lifecycle[0],
        )
        return False, active.status.value
    inactive_statuses = {
        ActionLifecycleStatus.RESCINDED,
        ActionLifecycleStatus.SUPERSEDED,
        ActionLifecycleStatus.WITHDRAWN,
    }
    if statuses and statuses <= inactive_statuses | {ActionLifecycleStatus.UNKNOWN}:
        for r in lifecycle:
            if r.status in inactive_statuses:
                return True, r.status.value
    # Prefer first record's status for annotation.
    return False, lifecycle[0].status.value


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class RequirementProcessor:
    """Compile office-action candidates into typed, span-bound requirements.

    Parameters
    ----------
    graph:
        Optional temporal authority graph for as-of citation resolution.
    citation_resolver:
        Optional preconfigured :class:`PatentCitationResolver`. When both
        graph and resolver are supplied, ``graph`` is used for resolution
        unless the resolver already carries a graph.
    id_factory:
        Deterministic ID factory for tests.
    bounds:
        Safety bounds on output size.
    admit_unverified:
        When False (default), only verified-layer instruction candidates are
        admitted as predicates. Uncompiled language is still retained.
    """

    def __init__(
        self,
        *,
        graph: PatentTemporalAuthorityGraph | None = None,
        citation_resolver: PatentCitationResolver | None = None,
        id_factory: Callable[[], str] | None = None,
        bounds: AnalysisBounds | None = None,
        admit_unverified: bool = False,
    ) -> None:
        self.graph = graph
        if citation_resolver is not None:
            self.resolver = citation_resolver
        else:
            self.resolver = PatentCitationResolver(graph=graph)
        self._id_factory = id_factory or (lambda: f"reqcomp:{uuid.uuid4().hex[:12]}")
        self.bounds = bounds or AnalysisBounds()
        self.admit_unverified = bool(admit_unverified)

    # -- public API ---------------------------------------------------------

    def compile(
        self,
        value: (
            RequirementCompilationInput
            | OfficeActionResult
            | Mapping[str, Any]
            | None
        ) = None,
        /,
        **kwargs: Any,
    ) -> RequirementCompilationResult:
        """Compile requirements from an office-action result or input packet."""
        inp = self._coerce_input(value, **kwargs)
        return self._compile(inp)

    def compile_many(
        self, values: Sequence[Any]
    ) -> tuple[RequirementCompilationResult, ...]:
        return tuple(self.compile(v) for v in values)

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: Any,
        **kwargs: Any,
    ) -> RequirementCompilationInput:
        if value is None and not kwargs:
            raise RequirementCompilationError(
                "compilation input is required", code="missing_input"
            )
        if isinstance(value, RequirementCompilationInput):
            return value
        if isinstance(value, OfficeActionResult):
            return RequirementCompilationInput(
                artifact_id=value.artifact_id,
                candidates=value.candidates,
                spans=value.spans,
                lifecycle=value.lifecycle,
                office_action=value,
                classification=value.classification,
                mailing_date=value.mailing_date,
                analysis_id=value.analysis_id,
                as_of=kwargs.get("as_of") or value.mailing_date,
                labels=dict(value.labels),
            )
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.update(kwargs)
            oa = merged.get("office_action")
            if isinstance(oa, Mapping):
                oa = OfficeActionResult.from_dict(oa)
                merged["office_action"] = oa
            candidates = merged.get("candidates") or ()
            if candidates and isinstance(candidates[0], Mapping):
                candidates = tuple(AnalysisCandidate.from_dict(c) for c in candidates)
            spans = merged.get("spans") or ()
            if spans and isinstance(spans[0], Mapping):
                spans = tuple(ExtractedSpan.from_dict(s) for s in spans)
            lifecycle = merged.get("lifecycle") or ()
            if lifecycle and isinstance(lifecycle[0], Mapping):
                lifecycle = tuple(
                    ActionLifecycleRecord.from_dict(r) for r in lifecycle
                )
            if oa is not None and isinstance(oa, OfficeActionResult):
                return RequirementCompilationInput(
                    artifact_id=merged.get("artifact_id") or oa.artifact_id,
                    candidates=tuple(candidates) or oa.candidates,
                    spans=tuple(spans) or oa.spans,
                    lifecycle=tuple(lifecycle) or oa.lifecycle,
                    office_action=oa,
                    classification=merged.get("classification", oa.classification),
                    mailing_date=merged.get("mailing_date", oa.mailing_date),
                    analysis_id=merged.get("analysis_id", oa.analysis_id),
                    as_of=merged.get("as_of") or oa.mailing_date,
                    labels=merged.get("labels") or dict(oa.labels),
                )
            return RequirementCompilationInput(
                artifact_id=merged.get("artifact_id", "artifact:unknown"),
                candidates=tuple(candidates),
                spans=tuple(spans),
                lifecycle=tuple(lifecycle),
                classification=merged.get(
                    "classification", DisclosureClassification.UNKNOWN
                ),
                mailing_date=merged.get("mailing_date"),
                analysis_id=merged.get("analysis_id"),
                as_of=merged.get("as_of"),
                labels=merged.get("labels") or {},
            )
        if kwargs:
            return self._coerce_input(kwargs)
        raise RequirementCompilationError(
            f"unsupported compilation input type: {type(value).__name__}",
            code="invalid_input_type",
        )

    # -- core compile -------------------------------------------------------

    def _compile(self, inp: RequirementCompilationInput) -> RequirementCompilationResult:
        compilation_id = self._id_factory()
        reason_codes: list[str] = []
        warnings: list[str] = []

        classification = inp.classification
        if inp.office_action is not None:
            classification = inp.office_action.classification

        if requires_quarantine(classification):
            reason_codes.append(RequirementReasonCode.QUARANTINED.value)
            return self._terminal(
                compilation_id=compilation_id,
                inp=inp,
                disposition=CompilationDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=warnings,
                classification=classification,
            )

        candidates = list(inp.candidates)
        spans = list(inp.spans)
        lifecycle = list(inp.lifecycle)
        if inp.office_action is not None:
            if not candidates:
                candidates = list(inp.office_action.candidates)
            if not spans:
                spans = list(inp.office_action.spans)
            if not lifecycle:
                lifecycle = list(inp.office_action.lifecycle)

        span_ids = {s.span_id for s in spans}
        as_of = inp.as_of or inp.mailing_date
        graph = self.graph or getattr(self.resolver, "graph", None)
        graph_id = getattr(graph, "graph_id", None) if graph is not None else None
        if graph is None:
            reason_codes.append(RequirementReasonCode.NO_AUTHORITY_GRAPH.value)

        inactive, lifecycle_status = lifecycle_primary_inactive(lifecycle)
        if inactive:
            reason_codes.append(RequirementReasonCode.LIFECYCLE_INACTIVE.value)

        # Collect context (alternatives / exceptions) for composition enrichment.
        alt_surfaces = [
            c.surface_text
            for c in candidates
            if c.kind is CandidateKind.ALTERNATIVE and c.surface_text
        ]
        exc_surfaces = [
            c.surface_text
            for c in candidates
            if c.kind is CandidateKind.EXCEPTION and c.surface_text
        ]

        predicates: list[CompiledPredicate] = []
        uncompiled: list[UncompiledClause] = []
        pred_seq = 0
        unc_seq = 0

        # Stable processing order: preserve input order.
        for cand in candidates:
            # --- uncompiled path (never drop) ---
            if cand.kind in _ALWAYS_UNCOMPILED_KINDS or (
                cand.requirement_type == "uncompiled"
            ):
                unc_seq += 1
                clause = self._make_uncompiled(
                    compilation_id=compilation_id,
                    seq=unc_seq,
                    cand=cand,
                    span_ids=span_ids,
                    classification=classification,
                    reason="uncompiled_language",
                )
                if clause is not None:
                    uncompiled.append(clause)
                    reason_codes.append(RequirementReasonCode.UNCOMPILED_RETAINED.value)
                continue

            # Context-only kinds: retained as uncompiled notes if they carry
            # surface text not already folded into a parent; otherwise skip
            # (they enrich nearby instruction candidates).
            if cand.kind in _CONTEXT_KINDS:
                # Folded into instruction candidates; still retain residual if
                # the surface is not empty and no instruction candidates exist.
                continue

            # Non-instruction structural kinds (claim ranges, sections, etc.)
            if cand.kind not in _INSTRUCTION_KINDS:
                # Prior-art / citations without instruction force → uncompiled
                # only when they look like free-form demands; otherwise skip.
                if cand.kind in (
                    CandidateKind.CITATION,
                    CandidateKind.PRIOR_ART,
                    CandidateKind.CLAIM_RANGE,
                    CandidateKind.SECTION,
                    CandidateKind.LIFECYCLE,
                    CandidateKind.OTHER,
                ):
                    continue
                # Unknown future kinds: retain as uncompiled (never drop).
                unc_seq += 1
                clause = self._make_uncompiled(
                    compilation_id=compilation_id,
                    seq=unc_seq,
                    cand=cand,
                    span_ids=span_ids,
                    classification=classification,
                    reason=f"unsupported_kind:{cand.kind.value}",
                )
                if clause is not None:
                    uncompiled.append(clause)
                    reason_codes.append(RequirementReasonCode.UNCOMPILED_RETAINED.value)
                continue

            # --- admission gate ---
            if not self._is_admissible(cand):
                if cand.origin is CandidateOrigin.MODEL:
                    reason_codes.append(RequirementReasonCode.MODEL_CANDIDATE_HELD.value)
                else:
                    reason_codes.append(RequirementReasonCode.UNVERIFIED_HELD.value)
                # Hold unverified instruction text as uncompiled so nothing drops.
                unc_seq += 1
                clause = self._make_uncompiled(
                    compilation_id=compilation_id,
                    seq=unc_seq,
                    cand=cand,
                    span_ids=span_ids,
                    classification=classification,
                    reason=(
                        "model_candidate_unverified"
                        if cand.origin is CandidateOrigin.MODEL
                        else "unverified_instruction"
                    ),
                )
                if clause is not None:
                    uncompiled.append(clause)
                    reason_codes.append(RequirementReasonCode.UNCOMPILED_RETAINED.value)
                continue

            if not cand.source_span_id or (
                span_ids and cand.source_span_id not in span_ids
            ):
                # Missing / unknown span → cannot admit; retain as uncompiled
                # with best-effort span or reject to uncompiled with reason.
                reason_codes.append(RequirementReasonCode.MISSING_SPAN.value)
                if cand.source_span_id:
                    unc_seq += 1
                    clause = self._make_uncompiled(
                        compilation_id=compilation_id,
                        seq=unc_seq,
                        cand=cand,
                        span_ids=span_ids,
                        classification=classification,
                        reason="span_not_in_index",
                        force_span=cand.source_span_id,
                    )
                    if clause is not None:
                        uncompiled.append(clause)
                        reason_codes.append(
                            RequirementReasonCode.UNCOMPILED_RETAINED.value
                        )
                continue

            reason_codes.append(RequirementReasonCode.SPAN_VALIDATED.value)

            # Merge contextual alternatives/exceptions into this candidate.
            merged_alts = tuple(
                dict.fromkeys(
                    list(cand.alternatives)
                    + [
                        a
                        for a in alt_surfaces
                        if a and a != cand.surface_text
                    ][:8]
                )
            )
            merged_excs = tuple(
                dict.fromkeys(
                    list(cand.exceptions)
                    + [
                        e
                        for e in exc_surfaces
                        if e and e != cand.surface_text
                    ][:8]
                )
            )

            pred_seq += 1
            child_ids: list[str] = []

            # Emit child predicates for alternative branches when present.
            composition = detect_composition(
                cand.surface_text,
                alternatives=merged_alts,
                exceptions=merged_excs,
                labels=cand.labels,
            )
            if composition is RequirementComposition.ALTERNATIVE and merged_alts:
                reason_codes.append(
                    RequirementReasonCode.COMPOSITION_ALTERNATIVE.value
                )
            elif composition is RequirementComposition.DISJUNCTIVE:
                reason_codes.append(
                    RequirementReasonCode.COMPOSITION_DISJUNCTIVE.value
                )
            elif composition is RequirementComposition.CONDITIONAL:
                reason_codes.append(
                    RequirementReasonCode.COMPOSITION_CONDITIONAL.value
                )
            elif composition is RequirementComposition.CONJUNCTIVE:
                reason_codes.append(
                    RequirementReasonCode.COMPOSITION_CONJUNCTIVE.value
                )

            if merged_alts and composition in (
                RequirementComposition.ALTERNATIVE,
                RequirementComposition.DISJUNCTIVE,
            ):
                for i, alt in enumerate(merged_alts[:16]):
                    # Children get sub-ids under parent.
                    child_id = f"pred:{compilation_id}:{pred_seq:04d}:alt:{i+1:02d}"
                    child_ids.append(child_id)
                    child_auth = self._resolve_authority(
                        legal_citations=(),
                        citation_keys=(),
                        surface=alt,
                        as_of=as_of,
                        graph=graph,
                        reason_codes=reason_codes,
                    )
                    child_app = self._resolve_applicability(
                        cand=cand,
                        composition=RequirementComposition.ATOMIC,
                        merged_alts=(),
                        merged_excs=(),
                        inactive=inactive,
                        lifecycle_status=lifecycle_status,
                        reason_codes=reason_codes,
                        branch_label=f"alternative_branch:{i+1}",
                    )
                    predicates.append(
                        CompiledPredicate(
                            schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
                            predicate_id=child_id,
                            source_candidate_id=cand.candidate_id,
                            source_span_id=cand.source_span_id,
                            instruction_text_digest=_text_digest(alt),
                            surface_text=alt[: self.bounds.max_surface],
                            composition=RequirementComposition.ATOMIC,
                            scope=detect_scope(
                                cand.kind,
                                claim_tokens=cand.claim_tokens,
                                surface=alt,
                                requirement_type=cand.requirement_type,
                            ),
                            requirement_type=(
                                cand.requirement_type
                                or f"{cand.kind.value}_alternative"
                            ),
                            affected_claims=cand.claim_tokens,
                            legal_citations=(),
                            child_predicate_ids=(),
                            authority=child_auth,
                            applicability=child_app,
                            proposed_date_rule=None,
                            parser_confidence=cand.confidence,
                            review_state=ReviewState.PENDING,
                            classification=classification,
                            admission=PredicateAdmissionState.ADMITTED,
                            labels={
                                **dict(cand.labels),
                                "branch": f"alternative:{i+1}",
                                "parent_seq": f"{pred_seq:04d}",
                            },
                        )
                    )

            authority = self._resolve_authority(
                legal_citations=cand.legal_citations,
                citation_keys=cand.citation_keys,
                surface=cand.surface_text,
                as_of=as_of,
                graph=graph,
                reason_codes=reason_codes,
            )
            applicability = self._resolve_applicability(
                cand=cand,
                composition=composition,
                merged_alts=merged_alts,
                merged_excs=merged_excs,
                inactive=inactive,
                lifecycle_status=lifecycle_status,
                reason_codes=reason_codes,
            )

            review = cand.review_state
            if authority.is_unknown:
                review = ReviewState.REQUIRED
            if applicability.state is ApplicabilityState.UNKNOWN:
                review = ReviewState.REQUIRED
            if inactive:
                review = ReviewState.REQUIRED

            scope = detect_scope(
                cand.kind,
                claim_tokens=cand.claim_tokens,
                surface=cand.surface_text,
                requirement_type=cand.requirement_type,
            )
            req_type = cand.requirement_type or cand.kind.value
            date_rule = propose_date_rule(
                cand.kind, surface=cand.surface_text, labels=cand.labels
            )

            predicates.append(
                CompiledPredicate(
                    schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
                    predicate_id=f"pred:{compilation_id}:{pred_seq:04d}",
                    source_candidate_id=cand.candidate_id,
                    source_span_id=cand.source_span_id,
                    instruction_text_digest=cand.text_digest or _text_digest(
                        cand.surface_text
                    ),
                    surface_text=(cand.surface_text or "")[: self.bounds.max_surface],
                    composition=composition,
                    scope=scope,
                    requirement_type=req_type,
                    affected_claims=cand.claim_tokens,
                    legal_citations=cand.legal_citations,
                    child_predicate_ids=tuple(child_ids),
                    authority=authority,
                    applicability=applicability,
                    proposed_date_rule=date_rule,
                    parser_confidence=cand.confidence,
                    review_state=review,
                    classification=classification,
                    admission=PredicateAdmissionState.ADMITTED,
                    labels=dict(cand.labels),
                )
            )
            reason_codes.append(RequirementReasonCode.PREDICATES_ADMITTED.value)

            if len(predicates) >= self.bounds.max_predicates:
                reason_codes.append(RequirementReasonCode.PREDICATE_LIMIT.value)
                warnings.append("predicate list truncated to analysis bounds")
                break

            if len(uncompiled) >= self.bounds.max_uncompiled:
                reason_codes.append(RequirementReasonCode.UNCOMPILED_LIMIT.value)
                warnings.append("uncompiled list truncated to analysis bounds")

        # Any leftover ALTERNATIVE/EXCEPTION context not folded: retain.
        instruction_admitted = bool(predicates)
        if not instruction_admitted:
            for cand in candidates:
                if cand.kind in _CONTEXT_KINDS and cand.surface_text:
                    unc_seq += 1
                    clause = self._make_uncompiled(
                        compilation_id=compilation_id,
                        seq=unc_seq,
                        cand=cand,
                        span_ids=span_ids,
                        classification=classification,
                        reason=f"context_without_parent:{cand.kind.value}",
                    )
                    if clause is not None:
                        uncompiled.append(clause)
                        reason_codes.append(
                            RequirementReasonCode.UNCOMPILED_RETAINED.value
                        )

        # Bounds on uncompiled after loop.
        if len(uncompiled) > self.bounds.max_uncompiled:
            uncompiled = uncompiled[: self.bounds.max_uncompiled]
            reason_codes.append(RequirementReasonCode.UNCOMPILED_LIMIT.value)
            warnings.append("uncompiled list truncated to analysis bounds")

        gov_reqs = tuple(p.to_government_requirement() for p in predicates)
        if gov_reqs:
            reason_codes.append(
                RequirementReasonCode.GOVERNMENT_REQUIREMENTS_EMITTED.value
            )

        # Deduplicate reason codes, preserve order.
        reason_codes = list(dict.fromkeys(reason_codes))
        warnings = list(dict.fromkeys(warnings))

        disposition, review_state = self._disposition(
            predicates=predicates,
            uncompiled=uncompiled,
            reason_codes=reason_codes,
            classification=classification,
            inactive=inactive,
        )

        text_digest = self._content_digest(predicates, uncompiled)

        return RequirementCompilationResult(
            schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
            compilation_id=compilation_id,
            source_analysis_id=inp.analysis_id
            or (
                inp.office_action.analysis_id
                if inp.office_action is not None
                else None
            ),
            source_artifact_id=inp.artifact_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(warnings),
            predicates=tuple(predicates),
            uncompiled=tuple(uncompiled),
            government_requirements=gov_reqs,
            ruleset_versions={
                "requirement_compiler": REQUIREMENT_COMPILER_RULESET_VERSION,
                "requirement_processor": REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
                "office_action": OFFICE_ACTION_SCHEMA_VERSION,
            },
            authority_graph_id=graph_id,
            as_of=as_of if isinstance(as_of, str) else (
                as_of.isoformat() if isinstance(as_of, date) else None
            ),
            labels=dict(inp.labels),
            text_digest=text_digest,
            retained=True,
        )

    # -- admission / authority / applicability ------------------------------

    def _is_admissible(self, cand: AnalysisCandidate) -> bool:
        if self.admit_unverified:
            return True
        if cand.layer is EvidenceLayer.VERIFIED:
            return True
        # Deterministic layer without verification: not admitted by default.
        return False

    def _resolve_authority(
        self,
        *,
        legal_citations: Sequence[str],
        citation_keys: Sequence[str],
        surface: str,
        as_of: str | date | None,
        graph: PatentTemporalAuthorityGraph | None,
        reason_codes: list[str],
    ) -> AuthorityBinding:
        surfaces: list[str] = list(legal_citations)
        if not surfaces and surface:
            # Parse citations out of the instruction surface as a fallback.
            try:
                parsed = parse_patent_citations(surface)
                for p in parsed:
                    if p.surface:
                        surfaces.append(p.surface)
                    elif p.citation_key:
                        surfaces.append(p.citation_key)
            except Exception:
                pass

        if not surfaces and not citation_keys:
            reason_codes.append(RequirementReasonCode.AUTHORITY_NOT_APPLICABLE.value)
            return AuthorityBinding(
                state=AuthorityResolutionState.NOT_APPLICABLE,
                citation_surfaces=(),
                citation_keys=(),
                selected_node_ids=(),
                selected_versions=(),
                match_kinds=(),
                authority_tiers=(),
                reasons=("no_legal_citations",),
            )

        if graph is None and not surfaces:
            reason_codes.append(RequirementReasonCode.AUTHORITY_UNKNOWN.value)
            return AuthorityBinding(
                state=AuthorityResolutionState.UNKNOWN,
                citation_surfaces=tuple(surfaces),
                citation_keys=tuple(citation_keys),
                selected_node_ids=(),
                selected_versions=(),
                match_kinds=(),
                authority_tiers=(),
                reasons=("no_authority_graph", "no_resolvable_surface"),
            )

        results: list[CitationResolutionResult] = []
        match_kinds: list[str] = []
        keys: list[str] = []
        node_ids: list[str] = []
        versions: list[str] = []
        tiers: list[str] = []
        reasons: list[str] = []
        out_surfaces: list[str] = []

        resolve_targets: list[str] = list(surfaces) if surfaces else list(citation_keys)

        for target in resolve_targets[:32]:
            try:
                result = self.resolver.resolve(
                    target,
                    as_of=as_of,
                    graph=graph,
                )
            except Exception as exc:
                reasons.append(f"resolve_error:{type(exc).__name__}")
                match_kinds.append(CitationMatchKind.UNRESOLVED.value)
                out_surfaces.append(target)
                continue
            results.append(result)
            out_surfaces.append(target)
            match_kinds.append(result.match_kind.value)
            if result.selected_citation_key:
                keys.append(result.selected_citation_key)
            elif result.parsed.citation_key:
                keys.append(result.parsed.citation_key)
            if result.selected_node_id:
                node_ids.append(result.selected_node_id)
            ver = result.selected_version or result.selected_edition
            if ver:
                versions.append(ver)
            if result.authority_tier is not None:
                tiers.append(result.authority_tier.value)
            for d in result.diagnostics:
                if d.code is not None:
                    reasons.append(str(d.code.value if hasattr(d.code, "value") else d.code))

        # Aggregate state — missing/ambiguous → unknown (acceptance).
        if not results:
            reason_codes.append(RequirementReasonCode.AUTHORITY_UNKNOWN.value)
            return AuthorityBinding(
                state=AuthorityResolutionState.UNKNOWN,
                citation_surfaces=tuple(dict.fromkeys(out_surfaces)),
                citation_keys=tuple(dict.fromkeys(keys or citation_keys)),
                selected_node_ids=(),
                selected_versions=(),
                match_kinds=tuple(match_kinds),
                authority_tiers=(),
                reasons=tuple(dict.fromkeys(reasons + ["no_resolution_results"])),
            )

        any_ambiguous = any(
            r.match_kind is CitationMatchKind.AMBIGUOUS for r in results
        )
        any_unresolved = any(
            r.match_kind is CitationMatchKind.UNRESOLVED for r in results
        )
        all_exact = all(r.match_kind is CitationMatchKind.EXACT for r in results)
        all_have_source = all(
            r.selected_node_id is not None
            and (r.selected_version is not None or r.selected_edition is not None)
            for r in results
        )

        if any_ambiguous:
            state = AuthorityResolutionState.AMBIGUOUS
            # Acceptance: missing/ambiguous authority yields unknown.
            # Surface the ambiguity distinctly, but treat as unknown for
            # fail-closed consumers via ``is_unknown``.
            reason_codes.append(RequirementReasonCode.AUTHORITY_AMBIGUOUS.value)
            reasons.append("ambiguous_authority")
        elif any_unresolved or not all_have_source:
            state = AuthorityResolutionState.UNKNOWN
            reason_codes.append(RequirementReasonCode.AUTHORITY_UNKNOWN.value)
            if graph is None:
                reasons.append("no_authority_graph")
            if any_unresolved:
                reasons.append("unresolved_citation")
            if not all_have_source:
                reasons.append("missing_source_or_version")
        elif all_exact and all_have_source:
            state = AuthorityResolutionState.RESOLVED
            reason_codes.append(RequirementReasonCode.AUTHORITY_RESOLVED.value)
        else:
            state = AuthorityResolutionState.UNKNOWN
            reason_codes.append(RequirementReasonCode.AUTHORITY_UNKNOWN.value)
            reasons.append("incomplete_resolution")

        return AuthorityBinding(
            state=state,
            citation_surfaces=tuple(dict.fromkeys(out_surfaces)),
            citation_keys=tuple(dict.fromkeys(keys)),
            selected_node_ids=tuple(dict.fromkeys(node_ids)),
            selected_versions=tuple(dict.fromkeys(versions)),
            match_kinds=tuple(match_kinds),
            authority_tiers=tuple(dict.fromkeys(tiers)),
            reasons=tuple(dict.fromkeys(reasons))[:32],
        )

    def _resolve_applicability(
        self,
        *,
        cand: AnalysisCandidate,
        composition: RequirementComposition,
        merged_alts: Sequence[str],
        merged_excs: Sequence[str],
        inactive: bool,
        lifecycle_status: str | None,
        reason_codes: list[str],
        branch_label: str | None = None,
    ) -> ApplicabilityBinding:
        conditions: list[str] = []
        exceptions: list[str] = list(merged_excs)
        reasons: list[str] = []

        if branch_label:
            conditions.append(branch_label)

        if inactive:
            conditions.append("action_lifecycle_inactive")
            exceptions.append("rescinded_or_superseded_action")
            reasons.append("lifecycle_inactive")
            reason_codes.append(
                RequirementReasonCode.APPLICABILITY_NOT_APPLICABLE.value
            )
            return ApplicabilityBinding(
                state=ApplicabilityState.NOT_APPLICABLE,
                conditions=tuple(conditions),
                exceptions=tuple(dict.fromkeys(exceptions)),
                lifecycle_status=lifecycle_status,
                reasons=tuple(reasons),
            )

        for alt in merged_alts:
            conditions.append(f"alternative:{_text_digest(alt)[:12]}")

        if composition is RequirementComposition.CONDITIONAL:
            conditions.append("composition:conditional")
            reason_codes.append(
                RequirementReasonCode.APPLICABILITY_CONDITIONAL.value
            )
            # Extract a short condition cue from surface when present.
            m = _CONDITIONAL_RE.search(cand.surface_text or "")
            if m:
                # Capture a bounded window after the cue for the condition.
                start = m.start()
                window = _normalize_ws(cand.surface_text[start : start + 120])
                if window:
                    conditions.append(f"condition_cue:{_text_digest(window)[:12]}")
            state = ApplicabilityState.CONDITIONAL
            reasons.append("conditional_composition")
        elif composition in (
            RequirementComposition.ALTERNATIVE,
            RequirementComposition.DISJUNCTIVE,
        ):
            conditions.append(f"composition:{composition.value}")
            state = ApplicabilityState.CONDITIONAL
            reasons.append("alternative_composition")
            reason_codes.append(
                RequirementReasonCode.APPLICABILITY_CONDITIONAL.value
            )
        elif exceptions:
            state = ApplicabilityState.CONDITIONAL
            conditions.append("has_exceptions")
            reasons.append("exceptions_present")
            reason_codes.append(
                RequirementReasonCode.APPLICABILITY_CONDITIONAL.value
            )
        else:
            state = ApplicabilityState.APPLICABLE
            reasons.append("default_applicable")

        if lifecycle_status:
            conditions.append(f"lifecycle:{lifecycle_status}")

        return ApplicabilityBinding(
            state=state,
            conditions=tuple(dict.fromkeys(conditions)),
            exceptions=tuple(dict.fromkeys(exceptions)),
            lifecycle_status=lifecycle_status,
            reasons=tuple(reasons),
        )

    def _make_uncompiled(
        self,
        *,
        compilation_id: str,
        seq: int,
        cand: AnalysisCandidate,
        span_ids: set[str],
        classification: DisclosureClassification,
        reason: str,
        force_span: str | None = None,
    ) -> UncompiledClause | None:
        span_id = force_span or cand.source_span_id
        if not span_id:
            # Absolute last resort: cannot retain without a span id; invent a
            # stable residual id only when the candidate itself is span-less
            # so text is still not dropped from the compilation record set.
            span_id = f"span:missing:{compilation_id}:{seq:04d}"
        surface = (cand.surface_text or "")[: self.bounds.max_surface]
        digest = cand.text_digest if cand.text_digest and _SHA256_RE.match(
            cand.text_digest
        ) else _text_digest(surface or cand.candidate_id)
        return UncompiledClause(
            schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
            clause_id=f"unc:{compilation_id}:{seq:04d}",
            source_candidate_id=cand.candidate_id,
            source_span_id=span_id,
            instruction_text_digest=digest,
            surface_text=surface,
            reason=reason,
            review_state=ReviewState.REQUIRED,
            classification=classification,
            labels={
                "kind": cand.kind.value,
                "layer": cand.layer.value,
                "origin": cand.origin.value,
            },
        )

    def _disposition(
        self,
        *,
        predicates: Sequence[CompiledPredicate],
        uncompiled: Sequence[UncompiledClause],
        reason_codes: Sequence[str],
        classification: DisclosureClassification,
        inactive: bool,
    ) -> tuple[CompilationDisposition, ReviewState]:
        if requires_quarantine(classification):
            return CompilationDisposition.QUARANTINE, ReviewState.REQUIRED
        if not predicates and not uncompiled:
            return CompilationDisposition.EMPTY, ReviewState.PENDING
        if not predicates and uncompiled:
            return CompilationDisposition.REVIEW, ReviewState.REQUIRED
        if inactive:
            return CompilationDisposition.REVIEW, ReviewState.REQUIRED
        if uncompiled:
            return CompilationDisposition.REVIEW, ReviewState.REQUIRED
        if any(p.authority.is_unknown for p in predicates):
            return CompilationDisposition.REVIEW, ReviewState.REQUIRED
        if any(
            p.applicability.state is ApplicabilityState.UNKNOWN for p in predicates
        ):
            return CompilationDisposition.REVIEW, ReviewState.PENDING
        if any(
            p.review_state is ReviewState.REQUIRED for p in predicates
        ):
            return CompilationDisposition.REVIEW, ReviewState.REQUIRED
        return CompilationDisposition.COMPILED, ReviewState.NOT_REQUIRED

    def _content_digest(
        self,
        predicates: Sequence[CompiledPredicate],
        uncompiled: Sequence[UncompiledClause],
    ) -> str:
        payload = {
            "predicates": [p.instruction_text_digest for p in predicates],
            "uncompiled": [u.instruction_text_digest for u in uncompiled],
            "schema": REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
            "ruleset": REQUIREMENT_COMPILER_RULESET_VERSION,
        }
        return sha256_hex(canonical_json(payload))

    def _terminal(
        self,
        *,
        compilation_id: str,
        inp: RequirementCompilationInput,
        disposition: CompilationDisposition,
        review_state: ReviewState,
        reason_codes: Sequence[str],
        warnings: Sequence[str],
        classification: DisclosureClassification,
    ) -> RequirementCompilationResult:
        return RequirementCompilationResult(
            schema_version=REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
            compilation_id=compilation_id,
            source_analysis_id=inp.analysis_id,
            source_artifact_id=inp.artifact_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(reason_codes),
            warnings=tuple(warnings),
            predicates=(),
            uncompiled=(),
            government_requirements=(),
            ruleset_versions={
                "requirement_compiler": REQUIREMENT_COMPILER_RULESET_VERSION,
                "requirement_processor": REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            authority_graph_id=None,
            as_of=inp.as_of if isinstance(inp.as_of, str) else None,
            labels=dict(inp.labels),
            text_digest=sha256_hex(""),
            retained=disposition is not CompilationDisposition.REJECTED,
        )


def compile_requirements(
    value: RequirementCompilationInput | OfficeActionResult | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> RequirementCompilationResult:
    """Module-level convenience wrapper around :class:`RequirementProcessor`."""
    graph = kwargs.pop("graph", None)
    citation_resolver = kwargs.pop("citation_resolver", None)
    id_factory = kwargs.pop("id_factory", None)
    bounds = kwargs.pop("bounds", None)
    admit_unverified = kwargs.pop("admit_unverified", False)
    return RequirementProcessor(
        graph=graph,
        citation_resolver=citation_resolver,
        id_factory=id_factory,
        bounds=bounds,
        admit_unverified=admit_unverified,
    ).compile(value, **kwargs)


__all__ = [
    "REQUIREMENT_COMPILER_RULESET_VERSION",
    "REQUIREMENT_PROCESSOR_INTERFACE",
    "REQUIREMENT_PROCESSOR_SCHEMA_VERSION",
    "AnalysisBounds",
    "ApplicabilityBinding",
    "ApplicabilityState",
    "AuthorityBinding",
    "AuthorityResolutionState",
    "CompilationDisposition",
    "CompiledPredicate",
    "PredicateAdmissionState",
    "RequirementCompilationError",
    "RequirementCompilationInput",
    "RequirementCompilationResult",
    "RequirementComposition",
    "RequirementProcessor",
    "RequirementReasonCode",
    "RequirementScope",
    "UncompiledClause",
    "compile_requirements",
    "detect_composition",
    "detect_scope",
    "lifecycle_primary_inactive",
    "propose_date_rule",
    "sha256_hex",
]
