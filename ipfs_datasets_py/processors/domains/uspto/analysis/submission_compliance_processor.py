"""Fail-closed submission compliance analysis (PATLAW-042).

Aggregates typed government requirements (PATLAW-040) against exact submission
evidence/counter-evidence (PATLAW-041) and applicable authority into
per-requirement assessments and a package-level compliance result.

Design invariants
-----------------
* Outcomes are deliberately fail closed:
  - ``satisfied``: all necessary predicates have validated evidence and no
    unresolved contradiction;
  - ``unsatisfied``: at least one necessary predicate is demonstrably absent
    or contradicted;
  - ``unknown``: source, extraction, authority, applicability, semantics, or
    proof is incomplete; and
  - ``not_applicable``: an explicit, source-supported applicability rule
    excludes the requirement.
* Absent requirements, empty evidence, parser/proof errors, skipped proofs,
  timeouts, unsupported semantics, contradictions, or missing authority can
  **never** produce an overall pass.
* The top-level package result remains ``unknown`` (and ``overall_pass`` is
  False) if any **mandatory** assessment is ``unknown``.
* Every assessment explanation cites all source spans and artifact content
  versions used in the decision.
* This module owns compliance orchestration only; it consumes requirements,
  evidence, SupportMap, and the generic form verifier without mutating them.
* Document body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AssessmentStatus,
    DisclosureClassification,
    ExtractedSpan,
    GovernmentRequirement,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    REQUIREMENT_COMPILER_RULESET_VERSION,
    REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
    ApplicabilityState,
    AuthorityBinding,
    AuthorityResolutionState,
    CompiledPredicate,
    RequirementCompilationResult,
    RequirementComposition,
    RequirementScope,
    UncompiledClause,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_evidence import (
    PARSER_VERSION as EVIDENCE_PARSER_VERSION,
    SUBMISSION_EVIDENCE_SCHEMA_VERSION,
    AdmittedSubmissionFact,
    EvidenceDisposition,
    EvidenceEdge,
    PatentSupportMapAdapter,
    SubmissionEvidenceMap,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.submission_processor import (
    SubmissionFactType,
)
from ipfs_datasets_py.processors.legal_data.support_map import MotionSupportMap

# Optional generic verifier (PATLAW-005). Import is soft so unit tests can
# inject receipts without requiring prover backends at import time.
try:
    from ipfs_datasets_py.processors.form_requirements_verifier import (
        FormRequirementsVerifier,
        STATUS_REVIEW_REQUIRED as FORM_STATUS_REVIEW_REQUIRED,
        STATUS_SATISFIED as FORM_STATUS_SATISFIED,
        STATUS_UNKNOWN as FORM_STATUS_UNKNOWN,
        STATUS_VIOLATED as FORM_STATUS_VIOLATED,
        VerificationReport,
    )
except Exception:  # pragma: no cover - environment without form verifier
    FormRequirementsVerifier = None  # type: ignore[misc, assignment]
    FORM_STATUS_SATISFIED = "satisfied"
    FORM_STATUS_VIOLATED = "violated"
    FORM_STATUS_UNKNOWN = "unknown"
    FORM_STATUS_REVIEW_REQUIRED = "review_required"
    VerificationReport = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

SUBMISSION_COMPLIANCE_SCHEMA_VERSION: Final = "uspto.submission-compliance.v1"
SUBMISSION_COMPLIANCE_INTERFACE: Final = "SubmissionComplianceProcessor@1"
COMPLIANCE_RULESET_VERSION: Final = "submission-compliance-rules@1"
PARSER_VERSION: Final = "patlaw-042.submission-compliance.v1"

DEFAULT_MAX_ASSESSMENTS: Final = 4096
DEFAULT_MAX_REVIEWER_ACTIONS: Final = 512
DEFAULT_MAX_CITATIONS: Final = 256

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# Scope / requirement_type → admissible submission fact types.
_SCOPE_FACT_TYPES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        RequirementScope.FEE.value: frozenset(
            {
                SubmissionFactType.FEE_PRESENCE.value,
                SubmissionFactType.PAYMENT_RECEIPT.value,
            }
        ),
        RequirementScope.FORM.value: frozenset({SubmissionFactType.FORM.value}),
        RequirementScope.RESPONSE.value: frozenset(
            {
                SubmissionFactType.REMARKS.value,
                SubmissionFactType.AMENDMENT_INSTRUCTION.value,
                SubmissionFactType.DECLARATION.value,
            }
        ),
        RequirementScope.CLAIM_SPECIFIC.value: frozenset(
            {
                SubmissionFactType.CLAIM.value,
                SubmissionFactType.CURRENT_CLAIM.value,
                SubmissionFactType.AMENDMENT_INSTRUCTION.value,
            }
        ),
        RequirementScope.DOCUMENT.value: frozenset(
            {
                SubmissionFactType.DOCUMENT_DESCRIPTION.value,
                SubmissionFactType.ATTACHMENT.value,
                SubmissionFactType.APPLICATION_METADATA.value,
                SubmissionFactType.ACKNOWLEDGEMENT_IDENTIFIER.value,
            }
        ),
        RequirementScope.GENERAL.value: frozenset(
            {ft.value for ft in SubmissionFactType if ft is not SubmissionFactType.UNSUPPORTED}
        ),
        RequirementScope.UNKNOWN.value: frozenset(),
    }
)

_REQUIREMENT_TYPE_FACT_HINTS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "fee": frozenset(
            {
                SubmissionFactType.FEE_PRESENCE.value,
                SubmissionFactType.PAYMENT_RECEIPT.value,
            }
        ),
        "form": frozenset({SubmissionFactType.FORM.value}),
        "signature": frozenset({SubmissionFactType.SIGNATURE_PRESENCE.value}),
        "declaration": frozenset({SubmissionFactType.DECLARATION.value}),
        "amendment": frozenset(
            {
                SubmissionFactType.AMENDMENT_INSTRUCTION.value,
                SubmissionFactType.CURRENT_CLAIM.value,
                SubmissionFactType.CLAIM.value,
            }
        ),
        "claim": frozenset(
            {
                SubmissionFactType.CLAIM.value,
                SubmissionFactType.CURRENT_CLAIM.value,
            }
        ),
        "response": frozenset(
            {
                SubmissionFactType.REMARKS.value,
                SubmissionFactType.AMENDMENT_INSTRUCTION.value,
            }
        ),
        "rejection": frozenset(
            {
                SubmissionFactType.REMARKS.value,
                SubmissionFactType.AMENDMENT_INSTRUCTION.value,
                SubmissionFactType.CURRENT_CLAIM.value,
                SubmissionFactType.CLAIM.value,
            }
        ),
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ComplianceStatus(str, Enum):
    """Per-requirement or package-level compliance outcome."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ProofExecutionStatus(str, Enum):
    """Proof / semantic-check execution receipt status (fail-closed)."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNSUPPORTED = "unsupported"
    SKIPPED = "skipped"


class ComplianceDisposition(str, Enum):
    """Top-level pipeline disposition."""

    ASSESSED = "assessed"
    EMPTY = "empty"
    PARTIAL = "partial"
    REVIEW = "review"
    UNKNOWN = "unknown"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class ComplianceReasonCode(str, Enum):
    """Machine-readable fail-closed / informational reason codes."""

    NO_REQUIREMENTS = "no_requirements"
    NO_EVIDENCE = "no_evidence"
    EMPTY_PACKAGE = "empty_package"
    PREDICATES_ASSESSED = "predicates_assessed"
    ALL_SATISFIED = "all_satisfied"
    MANDATORY_UNKNOWN = "mandatory_unknown"
    MANDATORY_UNSATISFIED = "mandatory_unsatisfied"
    MISSING_AUTHORITY = "missing_authority"
    AUTHORITY_AMBIGUOUS = "authority_ambiguous"
    AUTHORITY_RESOLVED = "authority_resolved"
    APPLICABILITY_NOT_APPLICABLE = "applicability_not_applicable"
    APPLICABILITY_UNKNOWN = "applicability_unknown"
    APPLICABILITY_CONDITIONAL = "applicability_conditional"
    EVIDENCE_SUPPORT = "evidence_support"
    EVIDENCE_ABSENT = "evidence_absent"
    EVIDENCE_COUNTER = "evidence_counter"
    CONTRADICTION = "contradiction"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"
    PROOF_SUCCESS = "proof_success"
    PROOF_FAILURE = "proof_failure"
    PROOF_TIMEOUT = "proof_timeout"
    PROOF_ERROR = "proof_error"
    PROOF_UNSUPPORTED = "proof_unsupported"
    PROOF_SKIPPED = "proof_skipped"
    UNCOMPILED_RETAINED = "uncompiled_retained"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    COMPOSITION_ALTERNATIVE = "composition_alternative"
    COMPOSITION_CONDITIONAL = "composition_conditional"
    COMPOSITION_CONJUNCTIVE = "composition_conjunctive"
    COMPOSITION_DISJUNCTIVE = "composition_disjunctive"
    FORM_VERIFIER_PASS = "form_verifier_pass"
    FORM_VERIFIER_FAIL = "form_verifier_fail"
    FORM_VERIFIER_UNKNOWN = "form_verifier_unknown"
    FORM_VERIFIER_EMPTY = "form_verifier_empty"
    QUARANTINED = "quarantined"
    REVIEW_REQUIRED = "review_required"
    EDGE_ROUND_TRIP_FAILED = "edge_round_trip_failed"
    CITATIONS_EMITTED = "citations_emitted"
    SUPPORT_MAP_CONSULTED = "support_map_consulted"
    OVERALL_PASS = "overall_pass"
    OVERALL_FAIL_CLOSED = "overall_fail_closed"


class ReviewerActionKind(str, Enum):
    """Typed human-review obligation produced by compliance aggregation."""

    REVIEW_EVIDENCE = "review_evidence"
    RESOLVE_AUTHORITY = "resolve_authority"
    RESOLVE_CONTRADICTION = "resolve_contradiction"
    COMPILE_REQUIREMENT = "compile_requirement"
    CONFIRM_NOT_APPLICABLE = "confirm_not_applicable"
    RESOLVE_PROOF = "resolve_proof"
    RESOLVE_APPLICABILITY = "resolve_applicability"
    SUPPLY_EVIDENCE = "supply_evidence"
    REVIEW_PACKAGE = "review_package"
    NONE = "none"


class CitationRole(str, Enum):
    """Role of a cited source span / version in an assessment explanation."""

    REQUIREMENT = "requirement"
    SUPPORT = "support"
    COUNTER = "counter"
    AUTHORITY = "authority"
    UNCOMPILED = "uncompiled"
    FORM_FIELD = "form_field"


class SubmissionComplianceError(ValueError):
    """Bounded compliance failure with a stable machine-readable code."""

    def __init__(
        self, message: str, *, code: str = "submission_compliance_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


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
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _require_sha256(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be sha256 hex")
    return lowered


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    f = float(value)
    if f < 0.0 or f > 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    items = tuple(_require_str(str(v), field, max_len=512) for v in value)
    if len(items) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return items


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 256,
    max_value_len: int = 4096,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for k, v in value.items():
        key = _require_str(str(k), f"{field}.key", max_len=256)
        val = _require_str(str(v), f"{field}.value", max_len=max_value_len)
        out[key] = val
    return MappingProxyType(out)


def _default_id_factory() -> str:
    return uuid.uuid4().hex


def compliance_status_to_assessment(status: ComplianceStatus) -> AssessmentStatus:
    """Project package/requirement status onto the shared AssessmentStatus."""
    if status is ComplianceStatus.SATISFIED:
        return AssessmentStatus.SATISFIED
    if status is ComplianceStatus.UNSATISFIED:
        return AssessmentStatus.UNSATISFIED
    return AssessmentStatus.UNKNOWN


def proof_status_blocks_pass(status: ProofExecutionStatus) -> bool:
    """True when a proof receipt must not contribute to overall_pass."""
    return status is not ProofExecutionStatus.SUCCESS


def proof_status_to_compliance(
    status: ProofExecutionStatus,
) -> ComplianceStatus:
    """Map a proof receipt onto a compliance status (fail-closed)."""
    if status is ProofExecutionStatus.SUCCESS:
        return ComplianceStatus.SATISFIED
    if status is ProofExecutionStatus.FAILURE:
        return ComplianceStatus.UNSATISFIED
    return ComplianceStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCitation:
    """Exact source span + artifact content version cited by an explanation."""

    citation_id: str
    role: CitationRole
    span_id: str | None
    artifact_id: str | None
    content_sha256: str | None
    version_label: str | None
    authority_node_id: str | None
    authority_version: str | None
    fact_id: str | None
    edge_id: str | None
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "citation_id", _identifier(self.citation_id, "citation_id")
        )
        object.__setattr__(
            self, "role", _coerce_enum(CitationRole, self.role, "role")
        )
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "version_label",
            _optional_str(self.version_label, "version_label", max_len=128),
        )
        object.__setattr__(
            self,
            "authority_node_id",
            _optional_identifier(self.authority_node_id, "authority_node_id"),
        )
        object.__setattr__(
            self,
            "authority_version",
            _optional_str(self.authority_version, "authority_version", max_len=128),
        )
        object.__setattr__(
            self, "fact_id", _optional_identifier(self.fact_id, "fact_id")
        )
        object.__setattr__(
            self, "edge_id", _optional_identifier(self.edge_id, "edge_id")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_node_id": self.authority_node_id,
            "authority_version": self.authority_version,
            "citation_id": self.citation_id,
            "content_sha256": self.content_sha256,
            "edge_id": self.edge_id,
            "fact_id": self.fact_id,
            "labels": dict(self.labels),
            "role": self.role.value,
            "span_id": self.span_id,
            "version_label": self.version_label,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceCitation":
        if not isinstance(value, Mapping):
            raise TypeError("SourceCitation must be a mapping")
        return cls(
            citation_id=value.get("citation_id", ""),
            role=value.get("role", CitationRole.REQUIREMENT.value),
            span_id=value.get("span_id"),
            artifact_id=value.get("artifact_id"),
            content_sha256=value.get("content_sha256"),
            version_label=value.get("version_label"),
            authority_node_id=value.get("authority_node_id"),
            authority_version=value.get("authority_version"),
            fact_id=value.get("fact_id"),
            edge_id=value.get("edge_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofExecutionReceipt:
    """Deterministic receipt of a proof / semantic check for one requirement."""

    receipt_id: str
    requirement_id: str
    status: ProofExecutionStatus
    prover: str
    statement_digest: str
    proof_output_digest: str | None
    execution_time_ms: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "requirement_id",
            _identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(ProofExecutionStatus, self.status, "status"),
        )
        object.__setattr__(
            self, "prover", _require_str(self.prover, "prover", max_len=64)
        )
        object.__setattr__(
            self,
            "statement_digest",
            _require_sha256(self.statement_digest, "statement_digest"),
        )
        object.__setattr__(
            self,
            "proof_output_digest",
            _optional_sha256(self.proof_output_digest, "proof_output_digest"),
        )
        object.__setattr__(
            self,
            "execution_time_ms",
            _nonneg_int(self.execution_time_ms, "execution_time_ms"),
        )
        object.__setattr__(
            self, "errors", _tuple_of_str(self.errors, "errors", max_items=32)
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=32)
        )
        object.__setattr__(
            self,
            "metadata",
            _frozen_str_map(self.metadata, "metadata", max_items=32),
        )

    @property
    def blocks_pass(self) -> bool:
        return proof_status_blocks_pass(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "errors": list(self.errors),
            "execution_time_ms": self.execution_time_ms,
            "metadata": dict(self.metadata),
            "proof_output_digest": self.proof_output_digest,
            "prover": self.prover,
            "receipt_id": self.receipt_id,
            "requirement_id": self.requirement_id,
            "statement_digest": self.statement_digest,
            "status": self.status.value,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofExecutionReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("ProofExecutionReceipt must be a mapping")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            requirement_id=value.get("requirement_id", ""),
            status=value.get("status", ProofExecutionStatus.ERROR.value),
            prover=value.get("prover", "unknown"),
            statement_digest=value.get("statement_digest", "0" * 64),
            proof_output_digest=value.get("proof_output_digest"),
            execution_time_ms=int(value.get("execution_time_ms") or 0),
            errors=tuple(value.get("errors") or ()),
            warnings=tuple(value.get("warnings") or ()),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    """Authority state snapshot embedded in a requirement assessment."""

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

    @classmethod
    def from_binding(cls, binding: AuthorityBinding) -> "AuthoritySnapshot":
        return cls(
            state=binding.state,
            citation_surfaces=binding.citation_surfaces,
            citation_keys=binding.citation_keys,
            selected_node_ids=binding.selected_node_ids,
            selected_versions=binding.selected_versions,
            match_kinds=binding.match_kinds,
            authority_tiers=binding.authority_tiers,
            reasons=binding.reasons,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritySnapshot":
        if not isinstance(value, Mapping):
            raise TypeError("AuthoritySnapshot must be a mapping")
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
class ReviewerAction:
    """Named human-review obligation required before any overall pass claim."""

    action_id: str
    kind: ReviewerActionKind
    requirement_id: str | None
    reason_codes: tuple[str, ...]
    priority: int
    message: str
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", _identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(ReviewerActionKind, self.kind, "kind")
        )
        object.__setattr__(
            self,
            "requirement_id",
            _optional_identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        object.__setattr__(self, "priority", _nonneg_int(self.priority, "priority"))
        # Message is identifier-safe narrative only (no document body).
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=512)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "message": self.message,
            "priority": self.priority,
            "reason_codes": list(self.reason_codes),
            "requirement_id": self.requirement_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerAction":
        if not isinstance(value, Mapping):
            raise TypeError("ReviewerAction must be a mapping")
        return cls(
            action_id=value.get("action_id", ""),
            kind=value.get("kind", ReviewerActionKind.REVIEW_PACKAGE.value),
            requirement_id=value.get("requirement_id"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            priority=int(value.get("priority") or 0),
            message=value.get("message", "review_required"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RequirementAssessment:
    """Fail-closed assessment of one government requirement / predicate.

    Aligns with the plan's ``RequirementAssessment`` contract: status,
    evidence and counter-evidence spans, authority snapshot, proof result,
    confidence, reasons, and required human action. Explanations cite every
    source span and version used.
    """

    schema_version: str
    assessment_id: str
    requirement_id: str
    status: ComplianceStatus
    mandatory: bool
    instruction_span_id: str | None
    instruction_text_digest: str | None
    requirement_type: str
    scope: str
    composition: str
    affected_claims: tuple[str, ...]
    support_span_ids: tuple[str, ...]
    counter_span_ids: tuple[str, ...]
    support_fact_ids: tuple[str, ...]
    counter_fact_ids: tuple[str, ...]
    support_edge_ids: tuple[str, ...]
    counter_edge_ids: tuple[str, ...]
    authority: AuthoritySnapshot
    applicability_state: ApplicabilityState
    proof_receipt_id: str | None
    proof_status: ProofExecutionStatus | None
    confidence: float | None
    reason_codes: tuple[str, ...]
    citations: tuple[SourceCitation, ...]
    reviewer_action: ReviewerAction | None
    review_state: ReviewState
    classification: DisclosureClassification
    labels: Mapping[str, str]
    explanation: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SUBMISSION_COMPLIANCE_SCHEMA_VERSION:
            raise ValueError(
                "RequirementAssessment.schema_version must be "
                f"{SUBMISSION_COMPLIANCE_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "assessment_id", _identifier(self.assessment_id, "assessment_id")
        )
        object.__setattr__(
            self,
            "requirement_id",
            _identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self, "status", _coerce_enum(ComplianceStatus, self.status, "status")
        )
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be bool")
        object.__setattr__(
            self,
            "instruction_span_id",
            _optional_identifier(self.instruction_span_id, "instruction_span_id"),
        )
        object.__setattr__(
            self,
            "instruction_text_digest",
            _optional_sha256(self.instruction_text_digest, "instruction_text_digest"),
        )
        object.__setattr__(
            self,
            "requirement_type",
            _require_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self, "scope", _require_str(self.scope, "scope", max_len=64)
        )
        object.__setattr__(
            self,
            "composition",
            _require_str(self.composition, "composition", max_len=64),
        )
        object.__setattr__(
            self,
            "affected_claims",
            _tuple_of_str(self.affected_claims, "affected_claims", max_items=256),
        )
        for attr in (
            "support_span_ids",
            "counter_span_ids",
            "support_fact_ids",
            "counter_fact_ids",
            "support_edge_ids",
            "counter_edge_ids",
        ):
            object.__setattr__(
                self, attr, _tuple_of_str(getattr(self, attr), attr, max_items=256)
            )
        if not isinstance(self.authority, AuthoritySnapshot):
            raise TypeError("authority must be AuthoritySnapshot")
        object.__setattr__(
            self,
            "applicability_state",
            _coerce_enum(
                ApplicabilityState, self.applicability_state, "applicability_state"
            ),
        )
        object.__setattr__(
            self,
            "proof_receipt_id",
            _optional_identifier(self.proof_receipt_id, "proof_receipt_id"),
        )
        if self.proof_status is not None:
            object.__setattr__(
                self,
                "proof_status",
                _coerce_enum(ProofExecutionStatus, self.proof_status, "proof_status"),
            )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        if not isinstance(self.citations, tuple):
            object.__setattr__(self, "citations", tuple(self.citations))
        for cite in self.citations:
            if not isinstance(cite, SourceCitation):
                raise TypeError("citations must be SourceCitation instances")
        if self.reviewer_action is not None and not isinstance(
            self.reviewer_action, ReviewerAction
        ):
            raise TypeError("reviewer_action must be ReviewerAction or None")
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
        object.__setattr__(
            self,
            "explanation",
            _require_str(self.explanation, "explanation", max_len=2048),
        )

    @property
    def blocks_overall_pass(self) -> bool:
        """Mandatory items that are not satisfied block overall_pass."""
        if not self.mandatory:
            return False
        if self.status is ComplianceStatus.NOT_APPLICABLE:
            return False
        return self.status is not ComplianceStatus.SATISFIED

    def to_assessment_status(self) -> AssessmentStatus:
        return compliance_status_to_assessment(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_claims": list(self.affected_claims),
            "applicability_state": self.applicability_state.value,
            "assessment_id": self.assessment_id,
            "authority": self.authority.to_dict(),
            "citations": [c.to_dict() for c in self.citations],
            "classification": self.classification.value,
            "composition": self.composition,
            "confidence": self.confidence,
            "counter_edge_ids": list(self.counter_edge_ids),
            "counter_fact_ids": list(self.counter_fact_ids),
            "counter_span_ids": list(self.counter_span_ids),
            "explanation": self.explanation,
            "instruction_span_id": self.instruction_span_id,
            "instruction_text_digest": self.instruction_text_digest,
            "labels": dict(self.labels),
            "mandatory": self.mandatory,
            "proof_receipt_id": self.proof_receipt_id,
            "proof_status": (
                self.proof_status.value if self.proof_status is not None else None
            ),
            "reason_codes": list(self.reason_codes),
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "review_state": self.review_state.value,
            "reviewer_action": (
                self.reviewer_action.to_dict() if self.reviewer_action else None
            ),
            "schema_version": self.schema_version,
            "scope": self.scope,
            "status": self.status.value,
            "support_edge_ids": list(self.support_edge_ids),
            "support_fact_ids": list(self.support_fact_ids),
            "support_span_ids": list(self.support_span_ids),
        }

    def public_projection(self) -> dict[str, Any]:
        """Public view: identifiers, statuses, citations; no surface text."""
        return {
            "assessment_id": self.assessment_id,
            "authority_state": self.authority.state.value,
            "authority_versions": list(self.authority.selected_versions),
            "citation_count": len(self.citations),
            "citation_ids": [c.citation_id for c in self.citations],
            "classification": self.classification.value,
            "confidence": self.confidence,
            "counter_span_ids": list(self.counter_span_ids),
            "mandatory": self.mandatory,
            "proof_receipt_id": self.proof_receipt_id,
            "proof_status": (
                self.proof_status.value if self.proof_status is not None else None
            ),
            "reason_codes": list(self.reason_codes),
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "review_state": self.review_state.value,
            "reviewer_action_kind": (
                self.reviewer_action.kind.value if self.reviewer_action else None
            ),
            "scope": self.scope,
            "status": self.status.value,
            "support_span_ids": list(self.support_span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequirementAssessment":
        if not isinstance(value, Mapping):
            raise TypeError("RequirementAssessment must be a mapping")
        action_raw = value.get("reviewer_action")
        proof_status = value.get("proof_status")
        return cls(
            schema_version=value.get(
                "schema_version", SUBMISSION_COMPLIANCE_SCHEMA_VERSION
            ),
            assessment_id=value.get("assessment_id", ""),
            requirement_id=value.get("requirement_id", ""),
            status=value.get("status", ComplianceStatus.UNKNOWN.value),
            mandatory=bool(value.get("mandatory", True)),
            instruction_span_id=value.get("instruction_span_id"),
            instruction_text_digest=value.get("instruction_text_digest"),
            requirement_type=value.get("requirement_type", "unknown"),
            scope=value.get("scope", RequirementScope.UNKNOWN.value),
            composition=value.get("composition", RequirementComposition.ATOMIC.value),
            affected_claims=tuple(value.get("affected_claims") or ()),
            support_span_ids=tuple(value.get("support_span_ids") or ()),
            counter_span_ids=tuple(value.get("counter_span_ids") or ()),
            support_fact_ids=tuple(value.get("support_fact_ids") or ()),
            counter_fact_ids=tuple(value.get("counter_fact_ids") or ()),
            support_edge_ids=tuple(value.get("support_edge_ids") or ()),
            counter_edge_ids=tuple(value.get("counter_edge_ids") or ()),
            authority=AuthoritySnapshot.from_dict(value.get("authority") or {}),
            applicability_state=value.get(
                "applicability_state", ApplicabilityState.UNKNOWN.value
            ),
            proof_receipt_id=value.get("proof_receipt_id"),
            proof_status=proof_status,
            confidence=value.get("confidence"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            citations=tuple(
                SourceCitation.from_dict(c) for c in (value.get("citations") or ())
            ),
            reviewer_action=(
                ReviewerAction.from_dict(action_raw) if action_raw else None
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
            explanation=value.get("explanation", "no_explanation"),
        )


@dataclass(frozen=True, slots=True)
class SubmissionComplianceInput:
    """Inputs for compliance aggregation (immutable snapshot)."""

    package_id: str
    requirements: RequirementCompilationResult | None = None
    evidence: SubmissionEvidenceMap | None = None
    predicates: Sequence[CompiledPredicate] = ()
    government_requirements: Sequence[GovernmentRequirement] = ()
    uncompiled: Sequence[UncompiledClause] = ()
    form_values: Mapping[str, Any] | None = None
    form_rule_set: Any | None = None
    form_id: str | None = None
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER
    labels: Mapping[str, str] = MappingProxyType({})
    matter_id: str | None = None
    analysis_id: str | None = None
    # Optional injected proof outcomes keyed by requirement_id for tests /
    # external provers. Values are ProofExecutionStatus | str | Mapping.
    proof_overrides: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        if self.requirements is not None and not isinstance(
            self.requirements, RequirementCompilationResult
        ):
            raise TypeError(
                "requirements must be RequirementCompilationResult or None"
            )
        if self.evidence is not None and not isinstance(
            self.evidence, SubmissionEvidenceMap
        ):
            raise TypeError("evidence must be SubmissionEvidenceMap or None")
        object.__setattr__(self, "predicates", tuple(self.predicates or ()))
        object.__setattr__(
            self,
            "government_requirements",
            tuple(self.government_requirements or ()),
        )
        object.__setattr__(self, "uncompiled", tuple(self.uncompiled or ()))
        if self.form_values is not None and not isinstance(self.form_values, Mapping):
            raise TypeError("form_values must be a mapping or None")
        object.__setattr__(
            self, "form_id", _optional_identifier(self.form_id, "form_id")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        # Freeze proof overrides as a plain dict of str→str/status for safety.
        if self.proof_overrides is None:
            object.__setattr__(self, "proof_overrides", MappingProxyType({}))
        elif not isinstance(self.proof_overrides, Mapping):
            raise TypeError("proof_overrides must be a mapping")
        else:
            frozen: dict[str, Any] = {}
            for k, v in self.proof_overrides.items():
                frozen[_identifier(str(k), "proof_overrides.key")] = v
            object.__setattr__(self, "proof_overrides", MappingProxyType(frozen))


@dataclass(frozen=True, slots=True)
class SubmissionComplianceResult:
    """Package-level fail-closed compliance outcome."""

    schema_version: str
    result_id: str
    package_id: str
    disposition: ComplianceDisposition
    overall_status: ComplianceStatus
    overall_pass: bool
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    assessments: tuple[RequirementAssessment, ...]
    proof_receipts: tuple[ProofExecutionReceipt, ...]
    reviewer_actions: tuple[ReviewerAction, ...]
    ruleset_versions: Mapping[str, str]
    parser_versions: Mapping[str, str]
    labels: Mapping[str, str]
    matter_id: str | None = None
    analysis_id: str | None = None
    requirements_compilation_id: str | None = None
    evidence_map_id: str | None = None
    support_map_entry_count: int = 0
    mandatory_unknown_count: int = 0
    mandatory_unsatisfied_count: int = 0
    mandatory_satisfied_count: int = 0
    not_applicable_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SUBMISSION_COMPLIANCE_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionComplianceResult.schema_version must be "
                f"{SUBMISSION_COMPLIANCE_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "result_id", _identifier(self.result_id, "result_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ComplianceDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "overall_status",
            _coerce_enum(ComplianceStatus, self.overall_status, "overall_status"),
        )
        if not isinstance(self.overall_pass, bool):
            raise TypeError("overall_pass must be bool")
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
        for attr in ("assessments", "proof_receipts", "reviewer_actions"):
            val = getattr(self, attr)
            if not isinstance(val, tuple):
                object.__setattr__(self, attr, tuple(val))
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "parser_versions",
            _frozen_str_map(self.parser_versions, "parser_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self,
            "requirements_compilation_id",
            _optional_identifier(
                self.requirements_compilation_id, "requirements_compilation_id"
            ),
        )
        object.__setattr__(
            self,
            "evidence_map_id",
            _optional_identifier(self.evidence_map_id, "evidence_map_id"),
        )
        for attr in (
            "support_map_entry_count",
            "mandatory_unknown_count",
            "mandatory_unsatisfied_count",
            "mandatory_satisfied_count",
            "not_applicable_count",
        ):
            object.__setattr__(self, attr, _nonneg_int(getattr(self, attr), attr))

        # Fail-closed structural invariants.
        if self.overall_pass:
            if self.overall_status is not ComplianceStatus.SATISFIED:
                raise ValueError(
                    "overall_pass requires overall_status=satisfied"
                )
            if self.mandatory_unknown_count > 0:
                raise ValueError(
                    "overall_pass cannot be True with mandatory unknowns"
                )
            if self.mandatory_unsatisfied_count > 0:
                raise ValueError(
                    "overall_pass cannot be True with mandatory unsatisfied"
                )
            if self.mandatory_satisfied_count == 0:
                raise ValueError(
                    "overall_pass requires at least one mandatory satisfied"
                )
            if any(a.blocks_overall_pass for a in self.assessments):
                raise ValueError(
                    "overall_pass cannot be True when any mandatory assessment blocks"
                )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return self.review_state in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ) or self.disposition in (
            ComplianceDisposition.REVIEW,
            ComplianceDisposition.UNKNOWN,
            ComplianceDisposition.QUARANTINE,
            ComplianceDisposition.EMPTY,
        )

    def assessment_by_requirement(
        self, requirement_id: str
    ) -> RequirementAssessment | None:
        for a in self.assessments:
            if a.requirement_id == requirement_id:
                return a
        return None

    def proof_receipt_by_id(
        self, receipt_id: str
    ) -> ProofExecutionReceipt | None:
        for r in self.proof_receipts:
            if r.receipt_id == receipt_id:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "assessments": [a.to_dict() for a in self.assessments],
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "evidence_map_id": self.evidence_map_id,
            "labels": dict(self.labels),
            "mandatory_satisfied_count": self.mandatory_satisfied_count,
            "mandatory_unknown_count": self.mandatory_unknown_count,
            "mandatory_unsatisfied_count": self.mandatory_unsatisfied_count,
            "matter_id": self.matter_id,
            "not_applicable_count": self.not_applicable_count,
            "overall_pass": self.overall_pass,
            "overall_status": self.overall_status.value,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "proof_receipts": [r.to_dict() for r in self.proof_receipts],
            "reason_codes": list(self.reason_codes),
            "requirements_compilation_id": self.requirements_compilation_id,
            "result_id": self.result_id,
            "review_state": self.review_state.value,
            "reviewer_actions": [a.to_dict() for a in self.reviewer_actions],
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "support_map_entry_count": self.support_map_entry_count,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "assessment_count": len(self.assessments),
            "assessments": [a.public_projection() for a in self.assessments],
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "evidence_map_id": self.evidence_map_id,
            "labels": dict(self.labels),
            "mandatory_satisfied_count": self.mandatory_satisfied_count,
            "mandatory_unknown_count": self.mandatory_unknown_count,
            "mandatory_unsatisfied_count": self.mandatory_unsatisfied_count,
            "matter_id": self.matter_id,
            "not_applicable_count": self.not_applicable_count,
            "overall_pass": self.overall_pass,
            "overall_status": self.overall_status.value,
            "package_id": self.package_id,
            "parser_versions": dict(self.parser_versions),
            "proof_receipt_count": len(self.proof_receipts),
            "reason_codes": list(self.reason_codes),
            "requirements_compilation_id": self.requirements_compilation_id,
            "result_id": self.result_id,
            "review_state": self.review_state.value,
            "reviewer_action_count": len(self.reviewer_actions),
            "reviewer_action_kinds": [a.kind.value for a in self.reviewer_actions],
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "support_map_entry_count": self.support_map_entry_count,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionComplianceResult":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionComplianceResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SUBMISSION_COMPLIANCE_SCHEMA_VERSION
            ),
            result_id=value.get("result_id", ""),
            package_id=value.get("package_id", ""),
            disposition=value.get("disposition", ComplianceDisposition.UNKNOWN.value),
            overall_status=value.get(
                "overall_status", ComplianceStatus.UNKNOWN.value
            ),
            overall_pass=bool(value.get("overall_pass", False)),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            assessments=tuple(
                RequirementAssessment.from_dict(a)
                for a in (value.get("assessments") or ())
            ),
            proof_receipts=tuple(
                ProofExecutionReceipt.from_dict(r)
                for r in (value.get("proof_receipts") or ())
            ),
            reviewer_actions=tuple(
                ReviewerAction.from_dict(a)
                for a in (value.get("reviewer_actions") or ())
            ),
            ruleset_versions=value.get("ruleset_versions") or {},
            parser_versions=value.get("parser_versions") or {},
            labels=value.get("labels") or {},
            matter_id=value.get("matter_id"),
            analysis_id=value.get("analysis_id"),
            requirements_compilation_id=value.get("requirements_compilation_id"),
            evidence_map_id=value.get("evidence_map_id"),
            support_map_entry_count=int(value.get("support_map_entry_count") or 0),
            mandatory_unknown_count=int(value.get("mandatory_unknown_count") or 0),
            mandatory_unsatisfied_count=int(
                value.get("mandatory_unsatisfied_count") or 0
            ),
            mandatory_satisfied_count=int(value.get("mandatory_satisfied_count") or 0),
            not_applicable_count=int(value.get("not_applicable_count") or 0),
        )


# ---------------------------------------------------------------------------
# Evidence matching helpers
# ---------------------------------------------------------------------------


def admissible_fact_types_for(
    *,
    scope: RequirementScope | str,
    requirement_type: str,
) -> frozenset[str]:
    """Return fact types that may support a requirement of the given scope."""
    scope_val = scope.value if isinstance(scope, RequirementScope) else str(scope)
    types: set[str] = set(_SCOPE_FACT_TYPES.get(scope_val, frozenset()))
    rt = (requirement_type or "").lower()
    for hint, fts in _REQUIREMENT_TYPE_FACT_HINTS.items():
        if hint in rt:
            types |= set(fts)
    # Signature presence is always admissible for signature-ish requirements.
    if "signature" in rt or "sign" in rt:
        types.add(SubmissionFactType.SIGNATURE_PRESENCE.value)
    return frozenset(types)


def match_evidence_for_requirement(
    *,
    requirement_id: str,
    scope: RequirementScope | str,
    requirement_type: str,
    affected_claims: Sequence[str],
    evidence: SubmissionEvidenceMap | None,
) -> tuple[
    tuple[AdmittedSubmissionFact, ...],
    tuple[EvidenceEdge, ...],
    tuple[EvidenceEdge, ...],
]:
    """Select admitted support/counter facts and edges for one requirement."""
    if evidence is None or evidence.is_empty:
        return (), (), ()

    admissible = admissible_fact_types_for(
        scope=scope, requirement_type=requirement_type
    )
    claim_set = {c.strip() for c in affected_claims if c and str(c).strip()}
    matched_facts: list[AdmittedSubmissionFact] = []

    for admitted in evidence.admitted_facts:
        ft = admitted.fact.fact_type
        if admissible and ft not in admissible:
            # When scope is general with empty admissible (unknown), skip filter.
            if admissible:
                continue
        if claim_set:
            fact_claims = {c.strip() for c in admitted.fact.affected_claims if c}
            # Claim-specific requirements only match overlapping claims, unless
            # the fact has no claim binding (package-level fee/form/etc.).
            if fact_claims and fact_claims.isdisjoint(claim_set):
                continue
        matched_facts.append(admitted)

    # If scope-based filter found nothing and claims empty, fall back to all
    # admitted facts only when scope is general; otherwise remain empty
    # (evidence_absent → fail closed).
    support_edges: list[EvidenceEdge] = []
    counter_edges: list[EvidenceEdge] = []
    for admitted in matched_facts:
        support_edges.extend(evidence.support_edges_for_fact(admitted.fact_id))
        counter_edges.extend(evidence.counter_edges_for_fact(admitted.fact_id))

    return tuple(matched_facts), tuple(support_edges), tuple(counter_edges)


def build_citations(
    *,
    id_factory: Callable[[], str],
    instruction_span_id: str | None,
    instruction_artifact_id: str | None,
    instruction_digest: str | None,
    authority: AuthoritySnapshot,
    support_edges: Sequence[EvidenceEdge],
    counter_edges: Sequence[EvidenceEdge],
    evidence: SubmissionEvidenceMap | None,
    span_catalog: Mapping[str, ExtractedSpan] | None = None,
) -> tuple[SourceCitation, ...]:
    """Cite every source span and version used by an assessment explanation."""
    citations: list[SourceCitation] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    def _add(cite: SourceCitation) -> None:
        key = (cite.role.value, cite.span_id, cite.content_sha256 or cite.authority_version)
        if key in seen:
            return
        seen.add(key)
        citations.append(cite)

    if instruction_span_id:
        content_sha = None
        artifact_id = instruction_artifact_id
        version_label = None
        if evidence is not None and artifact_id:
            binding = evidence.artifact_binding(artifact_id)
            if binding is not None:
                content_sha = binding.content_sha256
                version_label = binding.version_label
        if content_sha is None and instruction_digest:
            content_sha = None  # instruction digest is text, not artifact
        _add(
            SourceCitation(
                citation_id=f"cite:{id_factory()}",
                role=CitationRole.REQUIREMENT,
                span_id=instruction_span_id,
                artifact_id=artifact_id,
                content_sha256=content_sha,
                version_label=version_label,
                authority_node_id=None,
                authority_version=None,
                fact_id=None,
                edge_id=None,
                labels={"instruction_text_digest": instruction_digest or ""}
                if instruction_digest
                else {},
            )
        )

    for node_id, version in zip(
        authority.selected_node_ids, authority.selected_versions
    ) if authority.selected_versions else (
        (n, None) for n in authority.selected_node_ids
    ):
        _add(
            SourceCitation(
                citation_id=f"cite:{id_factory()}",
                role=CitationRole.AUTHORITY,
                span_id=None,
                artifact_id=None,
                content_sha256=None,
                version_label=None,
                authority_node_id=node_id,
                authority_version=version,
                fact_id=None,
                edge_id=None,
                labels={},
            )
        )
    # Versions without matching node (length mismatch) still get cited.
    if len(authority.selected_versions) > len(authority.selected_node_ids):
        for version in authority.selected_versions[len(authority.selected_node_ids) :]:
            _add(
                SourceCitation(
                    citation_id=f"cite:{id_factory()}",
                    role=CitationRole.AUTHORITY,
                    span_id=None,
                    artifact_id=None,
                    content_sha256=None,
                    version_label=None,
                    authority_node_id=None,
                    authority_version=version,
                    fact_id=None,
                    edge_id=None,
                    labels={},
                )
            )

    for edge, role in (
        *[(e, CitationRole.SUPPORT) for e in support_edges],
        *[(e, CitationRole.COUNTER) for e in counter_edges],
    ):
        version_label = None
        if evidence is not None:
            binding = evidence.artifact_binding(edge.artifact_id)
            if binding is not None:
                version_label = binding.version_label
        _add(
            SourceCitation(
                citation_id=f"cite:{id_factory()}",
                role=role,
                span_id=edge.span_id,
                artifact_id=edge.artifact_id,
                content_sha256=edge.content_sha256,
                version_label=version_label,
                authority_node_id=None,
                authority_version=None,
                fact_id=edge.fact_id,
                edge_id=edge.edge_id,
                labels={},
            )
        )

    if len(citations) > DEFAULT_MAX_CITATIONS:
        citations = citations[:DEFAULT_MAX_CITATIONS]
    return tuple(citations)


def build_explanation(
    *,
    status: ComplianceStatus,
    requirement_id: str,
    reason_codes: Sequence[str],
    citations: Sequence[SourceCitation],
    proof_status: ProofExecutionStatus | None,
) -> str:
    """Deterministic, body-text-free explanation citing spans and versions."""
    span_ids = sorted({c.span_id for c in citations if c.span_id})
    versions = sorted(
        {
            *(c.content_sha256[:12] for c in citations if c.content_sha256),
            *(
                f"{c.authority_node_id}@{c.authority_version}"
                for c in citations
                if c.authority_node_id or c.authority_version
            ),
        }
    )
    parts = [
        f"status={status.value}",
        f"requirement={requirement_id}",
        f"reasons={','.join(reason_codes) if reason_codes else 'none'}",
        f"proof={proof_status.value if proof_status else 'none'}",
        f"spans={','.join(span_ids) if span_ids else 'none'}",
        f"versions={','.join(versions) if versions else 'none'}",
        f"citation_count={len(citations)}",
    ]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Proof executor protocol
# ---------------------------------------------------------------------------

ProofExecutor = Callable[
    [str, Mapping[str, Any]],
    ProofExecutionReceipt | Mapping[str, Any] | ProofExecutionStatus | str,
]


def _coerce_proof_status(value: Any) -> ProofExecutionStatus:
    if isinstance(value, ProofExecutionStatus):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        # Accept common aliases from ProofStatus / form verifier.
        aliases = {
            "success": ProofExecutionStatus.SUCCESS,
            "satisfied": ProofExecutionStatus.SUCCESS,
            "failure": ProofExecutionStatus.FAILURE,
            "failed": ProofExecutionStatus.FAILURE,
            "violated": ProofExecutionStatus.FAILURE,
            "unsatisfied": ProofExecutionStatus.FAILURE,
            "timeout": ProofExecutionStatus.TIMEOUT,
            "error": ProofExecutionStatus.ERROR,
            "review_required": ProofExecutionStatus.ERROR,
            "unsupported": ProofExecutionStatus.UNSUPPORTED,
            "skipped": ProofExecutionStatus.SKIPPED,
            "unknown": ProofExecutionStatus.UNSUPPORTED,
        }
        if normalized in aliases:
            return aliases[normalized]
        return _coerce_enum(ProofExecutionStatus, normalized, "proof_status")
    raise TypeError(f"unsupported proof status type: {type(value).__name__}")


def default_evidence_prover(
    requirement_id: str,
    context: Mapping[str, Any],
    *,
    id_factory: Callable[[], str],
) -> ProofExecutionReceipt:
    """Deterministic evidence-backed prover (no external theorem prover).

    Maps support / counter / authority / applicability context into a proof
    receipt. Complex composition without child resolution is unsupported.
    """
    statement = canonical_json(
        {
            "requirement_id": requirement_id,
            "support_edge_ids": list(context.get("support_edge_ids") or ()),
            "counter_edge_ids": list(context.get("counter_edge_ids") or ()),
            "authority_state": context.get("authority_state"),
            "applicability_state": context.get("applicability_state"),
            "composition": context.get("composition"),
        }
    )
    digest = sha256_hex(statement)

    # Forced status (tests / injected overrides).
    forced = context.get("forced_status")
    if forced is not None:
        status = _coerce_proof_status(forced)
        return ProofExecutionReceipt(
            receipt_id=f"proof:{id_factory()}",
            requirement_id=requirement_id,
            status=status,
            prover=str(context.get("prover") or "evidence-prover@1"),
            statement_digest=digest,
            proof_output_digest=sha256_hex(status.value),
            execution_time_ms=int(context.get("execution_time_ms") or 0),
            errors=tuple(context.get("errors") or ()),
            warnings=tuple(context.get("warnings") or ()),
            metadata={"mode": "forced"},
        )

    composition = str(context.get("composition") or "atomic")
    support = list(context.get("support_edge_ids") or ())
    counter = list(context.get("counter_edge_ids") or ())
    authority_state = str(context.get("authority_state") or "unknown")
    applicability_state = str(context.get("applicability_state") or "unknown")
    unsupported = bool(context.get("unsupported_semantics"))

    if unsupported:
        status = ProofExecutionStatus.UNSUPPORTED
    elif applicability_state == ApplicabilityState.NOT_APPLICABLE.value:
        # N/A requirements do not execute proof; treat as success of exclusion.
        status = ProofExecutionStatus.SUCCESS
    elif applicability_state == ApplicabilityState.UNKNOWN.value:
        status = ProofExecutionStatus.UNSUPPORTED
    elif authority_state in (
        AuthorityResolutionState.UNKNOWN.value,
        AuthorityResolutionState.AMBIGUOUS.value,
    ):
        # Missing authority cannot be proved.
        status = ProofExecutionStatus.UNSUPPORTED
    elif composition in (
        RequirementComposition.ALTERNATIVE.value,
        RequirementComposition.CONDITIONAL.value,
        RequirementComposition.DISJUNCTIVE.value,
    ) and not context.get("children_resolved"):
        status = ProofExecutionStatus.UNSUPPORTED
    elif support and counter:
        status = ProofExecutionStatus.ERROR  # contradiction requires review
    elif support and not counter:
        status = ProofExecutionStatus.SUCCESS
    elif counter and not support:
        status = ProofExecutionStatus.FAILURE
    else:
        # No evidence: explicit absence is a failure for presence obligations.
        status = ProofExecutionStatus.FAILURE

    return ProofExecutionReceipt(
        receipt_id=f"proof:{id_factory()}",
        requirement_id=requirement_id,
        status=status,
        prover=str(context.get("prover") or "evidence-prover@1"),
        statement_digest=digest,
        proof_output_digest=sha256_hex(status.value),
        execution_time_ms=int(context.get("execution_time_ms") or 0),
        errors=(
            ("unresolved_contradiction",)
            if status is ProofExecutionStatus.ERROR and support and counter
            else ()
        ),
        warnings=(),
        metadata={
            "authority_state": authority_state,
            "applicability_state": applicability_state,
            "composition": composition,
            "support_count": str(len(support)),
            "counter_count": str(len(counter)),
        },
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class SubmissionComplianceProcessor:
    """Evaluate requirements against exact evidence with fail-closed aggregation.

    Parameters
    ----------
    id_factory:
        Deterministic ID factory for stable test fixtures.
    proof_executor:
        Optional callable ``(requirement_id, context) -> receipt``. When
        omitted, :func:`default_evidence_prover` is used.
    form_verifier:
        Optional :class:`FormRequirementsVerifier` instance for form-scoped
        checks. When form inputs are supplied without a verifier and the
        class is importable, a default instance is created.
    max_assessments / max_reviewer_actions:
        Hard bounds (fail closed by truncation + warning).
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        proof_executor: ProofExecutor | None = None,
        form_verifier: Any | None = None,
        max_assessments: int = DEFAULT_MAX_ASSESSMENTS,
        max_reviewer_actions: int = DEFAULT_MAX_REVIEWER_ACTIONS,
        support_map_adapter: PatentSupportMapAdapter | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory
        self._proof_executor = proof_executor
        self._form_verifier = form_verifier
        self._max_assessments = max(1, int(max_assessments))
        self._max_reviewer_actions = max(1, int(max_reviewer_actions))
        self._support_adapter = support_map_adapter or PatentSupportMapAdapter()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"

    # -- public API ---------------------------------------------------------

    def analyze(
        self,
        value: SubmissionComplianceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SubmissionComplianceResult:
        """Run fail-closed compliance analysis."""
        inp = self._coerce_input(value, **kwargs)
        return self._analyze(inp)

    def analyze_many(
        self, values: Sequence[SubmissionComplianceInput | Mapping[str, Any]]
    ) -> tuple[SubmissionComplianceResult, ...]:
        return tuple(self.analyze(v) for v in values)

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: SubmissionComplianceInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> SubmissionComplianceInput:
        if value is None and not kwargs:
            raise SubmissionComplianceError(
                "compliance input is required", code="missing_input"
            )
        if isinstance(value, SubmissionComplianceInput):
            if kwargs:
                # Allow light overrides via kwargs for convenience.
                data = {
                    "package_id": value.package_id,
                    "requirements": value.requirements,
                    "evidence": value.evidence,
                    "predicates": value.predicates,
                    "government_requirements": value.government_requirements,
                    "uncompiled": value.uncompiled,
                    "form_values": value.form_values,
                    "form_rule_set": value.form_rule_set,
                    "form_id": value.form_id,
                    "classification": value.classification,
                    "labels": dict(value.labels),
                    "matter_id": value.matter_id,
                    "analysis_id": value.analysis_id,
                    "proof_overrides": dict(value.proof_overrides),
                }
                data.update(kwargs)
                return SubmissionComplianceInput(**data)
            return value
        if value is None:
            return SubmissionComplianceInput(**kwargs)
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.update(kwargs)
            return self._input_from_mapping(merged)
        raise TypeError(
            "value must be SubmissionComplianceInput, mapping, or None with kwargs"
        )

    def _input_from_mapping(self, value: Mapping[str, Any]) -> SubmissionComplianceInput:
        reqs = value.get("requirements")
        if isinstance(reqs, Mapping):
            reqs = RequirementCompilationResult.from_dict(reqs)
        evidence = value.get("evidence")
        if isinstance(evidence, Mapping):
            evidence = SubmissionEvidenceMap.from_dict(evidence)
        predicates = value.get("predicates") or ()
        coerced_preds = tuple(
            p if isinstance(p, CompiledPredicate) else CompiledPredicate.from_dict(p)
            for p in predicates
        )
        gov = value.get("government_requirements") or ()
        coerced_gov = tuple(
            g if isinstance(g, GovernmentRequirement) else GovernmentRequirement.from_dict(g)
            for g in gov
        )
        uncompiled = value.get("uncompiled") or ()
        coerced_unc = tuple(
            u if isinstance(u, UncompiledClause) else UncompiledClause.from_dict(u)
            for u in uncompiled
        )
        return SubmissionComplianceInput(
            package_id=value.get("package_id", ""),
            requirements=reqs,
            evidence=evidence,
            predicates=coerced_preds,
            government_requirements=coerced_gov,
            uncompiled=coerced_unc,
            form_values=value.get("form_values"),
            form_rule_set=value.get("form_rule_set"),
            form_id=value.get("form_id"),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER
            ),
            labels=value.get("labels") or {},
            matter_id=value.get("matter_id"),
            analysis_id=value.get("analysis_id"),
            proof_overrides=value.get("proof_overrides") or {},
        )

    # -- core analysis ------------------------------------------------------

    def _analyze(self, inp: SubmissionComplianceInput) -> SubmissionComplianceResult:
        reason_codes: list[str] = []
        warnings: list[str] = []
        assessments: list[RequirementAssessment] = []
        receipts: list[ProofExecutionReceipt] = []
        actions: list[ReviewerAction] = []

        classification = inp.classification
        evidence = inp.evidence
        requirements = inp.requirements

        predicates = list(inp.predicates)
        uncompiled = list(inp.uncompiled)
        gov_requirements = list(inp.government_requirements)
        compilation_id: str | None = None
        evidence_map_id: str | None = None
        ruleset_versions: dict[str, str] = {
            "submission_compliance": COMPLIANCE_RULESET_VERSION,
            "submission_compliance_schema": SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
            "contracts": CONTRACTS_SCHEMA_VERSION,
        }

        if requirements is not None:
            compilation_id = requirements.compilation_id
            predicates = list(requirements.predicates) + predicates
            uncompiled = list(requirements.uncompiled) + uncompiled
            gov_requirements = (
                list(requirements.government_requirements) + gov_requirements
            )
            ruleset_versions.update(dict(requirements.ruleset_versions))
            if requires_quarantine(requirements.classification):
                classification = requirements.classification

        if evidence is not None:
            evidence_map_id = evidence.map_id
            if requires_quarantine(evidence.classification):
                classification = evidence.classification
            if not evidence.all_edges_round_trip():
                reason_codes.append(ComplianceReasonCode.EDGE_ROUND_TRIP_FAILED.value)
                warnings.append("evidence_edge_round_trip_failed")

        # De-duplicate predicates by predicate_id (stable first-wins).
        seen_pred: set[str] = set()
        unique_preds: list[CompiledPredicate] = []
        for p in predicates:
            if p.predicate_id in seen_pred:
                continue
            seen_pred.add(p.predicate_id)
            unique_preds.append(p)
        predicates = unique_preds

        # Support map consultation (informational; does not invent evidence).
        support_map_entry_count = 0
        if evidence is not None:
            try:
                smap: MotionSupportMap = self._support_adapter.to_motion_support_map(
                    evidence
                )
                support_map_entry_count = len(smap.entries)
                if support_map_entry_count:
                    reason_codes.append(
                        ComplianceReasonCode.SUPPORT_MAP_CONSULTED.value
                    )
            except Exception:
                warnings.append("support_map_adaptation_failed")

        no_requirements = not predicates and not gov_requirements
        no_evidence = evidence is None or evidence.is_empty

        if no_requirements:
            reason_codes.append(ComplianceReasonCode.NO_REQUIREMENTS.value)
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.REVIEW_PACKAGE,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.NO_REQUIREMENTS.value,),
                    priority=10,
                    message="no_typed_requirements_present",
                    labels={},
                )
            )

        if no_evidence:
            reason_codes.append(ComplianceReasonCode.NO_EVIDENCE.value)

        if uncompiled:
            reason_codes.append(ComplianceReasonCode.UNCOMPILED_RETAINED.value)
            for clause in uncompiled[: self._max_reviewer_actions]:
                actions.append(
                    ReviewerAction(
                        action_id=self._new_id("action"),
                        kind=ReviewerActionKind.COMPILE_REQUIREMENT,
                        requirement_id=clause.clause_id,
                        reason_codes=(
                            ComplianceReasonCode.UNCOMPILED_RETAINED.value,
                            ComplianceReasonCode.UNSUPPORTED_SEMANTICS.value,
                        ),
                        priority=20,
                        message="uncompiled_clause_requires_review",
                        labels={"clause_id": clause.clause_id},
                    )
                )

        # Assess each admitted predicate.
        for pred in predicates:
            if len(assessments) >= self._max_assessments:
                warnings.append("assessment_limit_reached")
                break
            assessment, receipt, action = self._assess_predicate(
                pred, inp=inp, evidence=evidence
            )
            assessments.append(assessment)
            if receipt is not None:
                receipts.append(receipt)
            if action is not None:
                actions.append(action)

        # GovernmentRequirement-only items (no compiled predicate twin).
        pred_ids = {p.predicate_id for p in predicates}
        for gov in gov_requirements:
            if gov.requirement_id in pred_ids:
                continue
            if len(assessments) >= self._max_assessments:
                warnings.append("assessment_limit_reached")
                break
            assessment, receipt, action = self._assess_government_requirement(
                gov, inp=inp, evidence=evidence
            )
            assessments.append(assessment)
            if receipt is not None:
                receipts.append(receipt)
            if action is not None:
                actions.append(action)

        # Optional form verifier fold-in (fail-closed).
        form_actions, form_reasons, form_warnings = self._run_form_verifier(inp)
        actions.extend(form_actions)
        reason_codes.extend(form_reasons)
        warnings.extend(form_warnings)

        if assessments:
            reason_codes.append(ComplianceReasonCode.PREDICATES_ASSESSED.value)
            reason_codes.append(ComplianceReasonCode.CITATIONS_EMITTED.value)

        # Aggregate fail-closed.
        overall_pass, overall_status, disposition, review_state, agg_reasons, counts = (
            self._aggregate_fail_closed(
                assessments=assessments,
                no_requirements=no_requirements,
                no_evidence=no_evidence,
                uncompiled=bool(uncompiled),
                form_fail_closed=any(
                    r
                    in {
                        ComplianceReasonCode.FORM_VERIFIER_FAIL.value,
                        ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value,
                        ComplianceReasonCode.FORM_VERIFIER_EMPTY.value,
                    }
                    for r in form_reasons
                ),
                quarantined=requires_quarantine(classification),
                edge_round_trip_failed=(
                    ComplianceReasonCode.EDGE_ROUND_TRIP_FAILED.value in reason_codes
                ),
            )
        )
        reason_codes.extend(agg_reasons)

        # Cap reviewer actions.
        if len(actions) > self._max_reviewer_actions:
            actions = actions[: self._max_reviewer_actions]
            warnings.append("reviewer_action_limit_reached")

        # Ensure package-level review action when overall is non-pass.
        if not overall_pass and not actions:
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.REVIEW_PACKAGE,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.OVERALL_FAIL_CLOSED.value,),
                    priority=100,
                    message="package_failed_closed",
                    labels={},
                )
            )

        # Deduplicate reason codes while preserving order.
        seen_rc: set[str] = set()
        ordered_rc: list[str] = []
        for rc in reason_codes:
            if rc not in seen_rc:
                seen_rc.add(rc)
                ordered_rc.append(rc)

        parser_versions = {
            "submission_compliance": PARSER_VERSION,
            "submission_evidence": EVIDENCE_PARSER_VERSION,
            "requirement_processor": REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        }
        if evidence is not None:
            for k, v in evidence.parser_versions.items():
                parser_versions.setdefault(k, v)

        return SubmissionComplianceResult(
            schema_version=SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
            result_id=self._new_id("cmpl"),
            package_id=inp.package_id,
            disposition=disposition,
            overall_status=overall_status,
            overall_pass=overall_pass,
            review_state=review_state,
            classification=classification,
            reason_codes=tuple(ordered_rc),
            warnings=tuple(dict.fromkeys(warnings)),
            assessments=tuple(assessments),
            proof_receipts=tuple(receipts),
            reviewer_actions=tuple(actions),
            ruleset_versions=ruleset_versions,
            parser_versions=parser_versions,
            labels=dict(inp.labels),
            matter_id=inp.matter_id
            or (evidence.matter_id if evidence is not None else None),
            analysis_id=inp.analysis_id
            or (evidence.analysis_id if evidence is not None else None),
            requirements_compilation_id=compilation_id,
            evidence_map_id=evidence_map_id,
            support_map_entry_count=support_map_entry_count,
            mandatory_unknown_count=counts["mandatory_unknown"],
            mandatory_unsatisfied_count=counts["mandatory_unsatisfied"],
            mandatory_satisfied_count=counts["mandatory_satisfied"],
            not_applicable_count=counts["not_applicable"],
        )

    # -- per-requirement assessment -----------------------------------------

    def _assess_predicate(
        self,
        pred: CompiledPredicate,
        *,
        inp: SubmissionComplianceInput,
        evidence: SubmissionEvidenceMap | None,
    ) -> tuple[
        RequirementAssessment,
        ProofExecutionReceipt | None,
        ReviewerAction | None,
    ]:
        authority = AuthoritySnapshot.from_binding(pred.authority)
        applicability = pred.applicability.state
        reasons: list[str] = []

        # Not applicable short-circuit (source-supported exclusion).
        if applicability is ApplicabilityState.NOT_APPLICABLE:
            reasons.append(ComplianceReasonCode.APPLICABILITY_NOT_APPLICABLE.value)
            citations = build_citations(
                id_factory=self._id_factory,
                instruction_span_id=pred.source_span_id,
                instruction_artifact_id=None,
                instruction_digest=pred.instruction_text_digest,
                authority=authority,
                support_edges=(),
                counter_edges=(),
                evidence=evidence,
            )
            explanation = build_explanation(
                status=ComplianceStatus.NOT_APPLICABLE,
                requirement_id=pred.predicate_id,
                reason_codes=reasons,
                citations=citations,
                proof_status=None,
            )
            return (
                RequirementAssessment(
                    schema_version=SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
                    assessment_id=self._new_id("assess"),
                    requirement_id=pred.predicate_id,
                    status=ComplianceStatus.NOT_APPLICABLE,
                    mandatory=False,
                    instruction_span_id=pred.source_span_id,
                    instruction_text_digest=pred.instruction_text_digest,
                    requirement_type=pred.requirement_type,
                    scope=pred.scope.value,
                    composition=pred.composition.value,
                    affected_claims=pred.affected_claims,
                    support_span_ids=(),
                    counter_span_ids=(),
                    support_fact_ids=(),
                    counter_fact_ids=(),
                    support_edge_ids=(),
                    counter_edge_ids=(),
                    authority=authority,
                    applicability_state=applicability,
                    proof_receipt_id=None,
                    proof_status=None,
                    confidence=pred.parser_confidence,
                    reason_codes=tuple(reasons),
                    citations=citations,
                    reviewer_action=None,
                    review_state=ReviewState.NOT_REQUIRED,
                    classification=pred.classification,
                    labels=dict(pred.labels),
                    explanation=explanation,
                ),
                None,
                None,
            )

        matched_facts, support_edges, counter_edges = match_evidence_for_requirement(
            requirement_id=pred.predicate_id,
            scope=pred.scope,
            requirement_type=pred.requirement_type,
            affected_claims=pred.affected_claims,
            evidence=evidence,
        )

        support_span_ids = tuple(dict.fromkeys(e.span_id for e in support_edges))
        counter_span_ids = tuple(dict.fromkeys(e.span_id for e in counter_edges))
        support_fact_ids = tuple(dict.fromkeys(f.fact_id for f in matched_facts if f.support_edge_ids))
        counter_fact_ids = tuple(
            dict.fromkeys(
                f.fact_id
                for f in matched_facts
                if f.counter_edge_ids
            )
        )
        # Also include facts that only appear via counter edges.
        for e in counter_edges:
            if e.fact_id not in counter_fact_ids:
                counter_fact_ids = counter_fact_ids + (e.fact_id,)
        support_edge_ids = tuple(e.edge_id for e in support_edges)
        counter_edge_ids = tuple(e.edge_id for e in counter_edges)

        if support_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_SUPPORT.value)
        if counter_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_COUNTER.value)
        if not support_edges and not counter_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_ABSENT.value)
            if evidence is None or evidence.is_empty:
                reasons.append(ComplianceReasonCode.NO_EVIDENCE.value)

        if support_edges and counter_edges:
            reasons.append(ComplianceReasonCode.CONTRADICTION.value)
            reasons.append(ComplianceReasonCode.UNRESOLVED_CONTRADICTION.value)

        # Authority fail-closed.
        if authority.state is AuthorityResolutionState.UNKNOWN:
            reasons.append(ComplianceReasonCode.MISSING_AUTHORITY.value)
        elif authority.state is AuthorityResolutionState.AMBIGUOUS:
            reasons.append(ComplianceReasonCode.AUTHORITY_AMBIGUOUS.value)
            reasons.append(ComplianceReasonCode.MISSING_AUTHORITY.value)
        elif authority.state is AuthorityResolutionState.RESOLVED:
            reasons.append(ComplianceReasonCode.AUTHORITY_RESOLVED.value)

        if applicability is ApplicabilityState.UNKNOWN:
            reasons.append(ComplianceReasonCode.APPLICABILITY_UNKNOWN.value)
        elif applicability is ApplicabilityState.CONDITIONAL:
            reasons.append(ComplianceReasonCode.APPLICABILITY_CONDITIONAL.value)

        composition_reason = {
            RequirementComposition.ALTERNATIVE: ComplianceReasonCode.COMPOSITION_ALTERNATIVE,
            RequirementComposition.CONDITIONAL: ComplianceReasonCode.COMPOSITION_CONDITIONAL,
            RequirementComposition.CONJUNCTIVE: ComplianceReasonCode.COMPOSITION_CONJUNCTIVE,
            RequirementComposition.DISJUNCTIVE: ComplianceReasonCode.COMPOSITION_DISJUNCTIVE,
        }.get(pred.composition)
        if composition_reason is not None:
            reasons.append(composition_reason.value)

        unsupported_semantics = pred.composition in (
            RequirementComposition.ALTERNATIVE,
            RequirementComposition.CONDITIONAL,
            RequirementComposition.DISJUNCTIVE,
        ) and not pred.child_predicate_ids

        if unsupported_semantics:
            reasons.append(ComplianceReasonCode.UNSUPPORTED_SEMANTICS.value)

        # Proof execution.
        proof_context: dict[str, Any] = {
            "support_edge_ids": support_edge_ids,
            "counter_edge_ids": counter_edge_ids,
            "authority_state": authority.state.value,
            "applicability_state": applicability.value,
            "composition": pred.composition.value,
            "children_resolved": bool(pred.child_predicate_ids),
            "unsupported_semantics": unsupported_semantics,
            "requirement_type": pred.requirement_type,
            "scope": pred.scope.value,
        }
        if pred.predicate_id in inp.proof_overrides:
            proof_context["forced_status"] = inp.proof_overrides[pred.predicate_id]

        receipt = self._execute_proof(pred.predicate_id, proof_context)
        reasons.append(self._proof_reason(receipt.status))

        status, action_kind, review_state = self._decide_status(
            proof_status=receipt.status,
            authority=authority,
            applicability=applicability,
            has_support=bool(support_edges),
            has_counter=bool(counter_edges),
            unsupported_semantics=unsupported_semantics,
        )

        citations = build_citations(
            id_factory=self._id_factory,
            instruction_span_id=pred.source_span_id,
            instruction_artifact_id=None,
            instruction_digest=pred.instruction_text_digest,
            authority=authority,
            support_edges=support_edges,
            counter_edges=counter_edges,
            evidence=evidence,
        )
        # Prefer artifact from first support/counter edge for instruction
        # artifact binding when available (instruction may live on OA artifact).
        if evidence is not None and pred.source_span_id:
            span = evidence.span_by_id(pred.source_span_id)
            if span is not None:
                # Rebuild citations with instruction artifact known.
                citations = build_citations(
                    id_factory=self._id_factory,
                    instruction_span_id=pred.source_span_id,
                    instruction_artifact_id=span.artifact_id,
                    instruction_digest=pred.instruction_text_digest,
                    authority=authority,
                    support_edges=support_edges,
                    counter_edges=counter_edges,
                    evidence=evidence,
                )

        explanation = build_explanation(
            status=status,
            requirement_id=pred.predicate_id,
            reason_codes=reasons,
            citations=citations,
            proof_status=receipt.status,
        )

        action: ReviewerAction | None = None
        if action_kind is not ReviewerActionKind.NONE:
            action = ReviewerAction(
                action_id=self._new_id("action"),
                kind=action_kind,
                requirement_id=pred.predicate_id,
                reason_codes=tuple(reasons[:8]),
                priority=self._action_priority(action_kind),
                message=f"{action_kind.value}_for_{pred.predicate_id}",
                labels={"scope": pred.scope.value, "status": status.value},
            )
            reasons.append(ComplianceReasonCode.REVIEW_REQUIRED.value)

        assessment = RequirementAssessment(
            schema_version=SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
            assessment_id=self._new_id("assess"),
            requirement_id=pred.predicate_id,
            status=status,
            mandatory=True,
            instruction_span_id=pred.source_span_id,
            instruction_text_digest=pred.instruction_text_digest,
            requirement_type=pred.requirement_type,
            scope=pred.scope.value,
            composition=pred.composition.value,
            affected_claims=pred.affected_claims,
            support_span_ids=support_span_ids,
            counter_span_ids=counter_span_ids,
            support_fact_ids=support_fact_ids,
            counter_fact_ids=counter_fact_ids,
            support_edge_ids=support_edge_ids,
            counter_edge_ids=counter_edge_ids,
            authority=authority,
            applicability_state=applicability,
            proof_receipt_id=receipt.receipt_id,
            proof_status=receipt.status,
            confidence=pred.parser_confidence,
            reason_codes=tuple(dict.fromkeys(reasons)),
            citations=citations,
            reviewer_action=action,
            review_state=review_state,
            classification=pred.classification,
            labels=dict(pred.labels),
            explanation=explanation,
        )
        return assessment, receipt, action

    def _assess_government_requirement(
        self,
        gov: GovernmentRequirement,
        *,
        inp: SubmissionComplianceInput,
        evidence: SubmissionEvidenceMap | None,
    ) -> tuple[
        RequirementAssessment,
        ProofExecutionReceipt | None,
        ReviewerAction | None,
    ]:
        """Assess a shared GovernmentRequirement without compiled metadata."""
        # Shared GovernmentRequirement lacks authority-node resolution; cite
        # surfaces alone remain unknown (fail-closed missing authority).
        if gov.legal_citations:
            authority = AuthoritySnapshot(
                state=AuthorityResolutionState.UNKNOWN,
                citation_surfaces=gov.legal_citations,
                citation_keys=(),
                selected_node_ids=(),
                selected_versions=(),
                match_kinds=(),
                authority_tiers=(),
                reasons=("authority_nodes_unresolved",),
            )
        else:
            authority = AuthoritySnapshot(
                state=AuthorityResolutionState.UNKNOWN,
                citation_surfaces=(),
                citation_keys=(),
                selected_node_ids=(),
                selected_versions=(),
                match_kinds=(),
                authority_tiers=(),
                reasons=("no_citations",),
            )

        scope = RequirementScope.GENERAL
        rt = (gov.requirement_type or "").lower()
        if "fee" in rt:
            scope = RequirementScope.FEE
        elif "form" in rt:
            scope = RequirementScope.FORM
        elif gov.affected_claims:
            scope = RequirementScope.CLAIM_SPECIFIC
        elif "response" in rt:
            scope = RequirementScope.RESPONSE

        matched_facts, support_edges, counter_edges = match_evidence_for_requirement(
            requirement_id=gov.requirement_id,
            scope=scope,
            requirement_type=gov.requirement_type,
            affected_claims=gov.affected_claims,
            evidence=evidence,
        )
        reasons: list[str] = []
        if not gov.legal_citations:
            reasons.append(ComplianceReasonCode.MISSING_AUTHORITY.value)
        else:
            reasons.append(ComplianceReasonCode.MISSING_AUTHORITY.value)

        if support_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_SUPPORT.value)
        if counter_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_COUNTER.value)
        if not support_edges and not counter_edges:
            reasons.append(ComplianceReasonCode.EVIDENCE_ABSENT.value)

        proof_context: dict[str, Any] = {
            "support_edge_ids": tuple(e.edge_id for e in support_edges),
            "counter_edge_ids": tuple(e.edge_id for e in counter_edges),
            "authority_state": authority.state.value,
            "applicability_state": ApplicabilityState.APPLICABLE.value,
            "composition": RequirementComposition.ATOMIC.value,
            "children_resolved": True,
            "unsupported_semantics": False,
        }
        if gov.requirement_id in inp.proof_overrides:
            proof_context["forced_status"] = inp.proof_overrides[gov.requirement_id]

        receipt = self._execute_proof(gov.requirement_id, proof_context)
        reasons.append(self._proof_reason(receipt.status))

        status, action_kind, review_state = self._decide_status(
            proof_status=receipt.status,
            authority=authority,
            applicability=ApplicabilityState.APPLICABLE,
            has_support=bool(support_edges),
            has_counter=bool(counter_edges),
            unsupported_semantics=False,
        )

        citations = build_citations(
            id_factory=self._id_factory,
            instruction_span_id=gov.source_span_id,
            instruction_artifact_id=None,
            instruction_digest=gov.instruction_text_digest,
            authority=authority,
            support_edges=support_edges,
            counter_edges=counter_edges,
            evidence=evidence,
        )
        explanation = build_explanation(
            status=status,
            requirement_id=gov.requirement_id,
            reason_codes=reasons,
            citations=citations,
            proof_status=receipt.status,
        )
        action: ReviewerAction | None = None
        if action_kind is not ReviewerActionKind.NONE:
            action = ReviewerAction(
                action_id=self._new_id("action"),
                kind=action_kind,
                requirement_id=gov.requirement_id,
                reason_codes=tuple(reasons[:8]),
                priority=self._action_priority(action_kind),
                message=f"{action_kind.value}_for_{gov.requirement_id}",
                labels={"status": status.value},
            )

        assessment = RequirementAssessment(
            schema_version=SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
            assessment_id=self._new_id("assess"),
            requirement_id=gov.requirement_id,
            status=status,
            mandatory=True,
            instruction_span_id=gov.source_span_id,
            instruction_text_digest=gov.instruction_text_digest,
            requirement_type=gov.requirement_type,
            scope=scope.value,
            composition=RequirementComposition.ATOMIC.value,
            affected_claims=gov.affected_claims,
            support_span_ids=tuple(dict.fromkeys(e.span_id for e in support_edges)),
            counter_span_ids=tuple(dict.fromkeys(e.span_id for e in counter_edges)),
            support_fact_ids=tuple(f.fact_id for f in matched_facts if f.support_edge_ids),
            counter_fact_ids=tuple(e.fact_id for e in counter_edges),
            support_edge_ids=tuple(e.edge_id for e in support_edges),
            counter_edge_ids=tuple(e.edge_id for e in counter_edges),
            authority=authority,
            applicability_state=ApplicabilityState.APPLICABLE,
            proof_receipt_id=receipt.receipt_id,
            proof_status=receipt.status,
            confidence=gov.parser_confidence,
            reason_codes=tuple(dict.fromkeys(reasons)),
            citations=citations,
            reviewer_action=action,
            review_state=review_state,
            classification=gov.classification,
            labels={},
            explanation=explanation,
        )
        return assessment, receipt, action

    def _execute_proof(
        self, requirement_id: str, context: Mapping[str, Any]
    ) -> ProofExecutionReceipt:
        if self._proof_executor is not None:
            try:
                raw = self._proof_executor(requirement_id, context)
            except Exception as exc:
                return ProofExecutionReceipt(
                    receipt_id=self._new_id("proof"),
                    requirement_id=requirement_id,
                    status=ProofExecutionStatus.ERROR,
                    prover="injected-executor",
                    statement_digest=sha256_hex(requirement_id),
                    proof_output_digest=None,
                    execution_time_ms=0,
                    errors=(f"executor_error:{type(exc).__name__}",),
                    warnings=(),
                    metadata={},
                )
            if isinstance(raw, ProofExecutionReceipt):
                return raw
            if isinstance(raw, Mapping):
                return ProofExecutionReceipt.from_dict(raw)
            status = _coerce_proof_status(raw)
            return ProofExecutionReceipt(
                receipt_id=self._new_id("proof"),
                requirement_id=requirement_id,
                status=status,
                prover="injected-executor",
                statement_digest=sha256_hex(requirement_id),
                proof_output_digest=sha256_hex(status.value),
                execution_time_ms=0,
                errors=(),
                warnings=(),
                metadata={},
            )
        return default_evidence_prover(
            requirement_id, context, id_factory=self._id_factory
        )

    @staticmethod
    def _proof_reason(status: ProofExecutionStatus) -> str:
        return {
            ProofExecutionStatus.SUCCESS: ComplianceReasonCode.PROOF_SUCCESS.value,
            ProofExecutionStatus.FAILURE: ComplianceReasonCode.PROOF_FAILURE.value,
            ProofExecutionStatus.TIMEOUT: ComplianceReasonCode.PROOF_TIMEOUT.value,
            ProofExecutionStatus.ERROR: ComplianceReasonCode.PROOF_ERROR.value,
            ProofExecutionStatus.UNSUPPORTED: ComplianceReasonCode.PROOF_UNSUPPORTED.value,
            ProofExecutionStatus.SKIPPED: ComplianceReasonCode.PROOF_SKIPPED.value,
        }[status]

    @staticmethod
    def _action_priority(kind: ReviewerActionKind) -> int:
        return {
            ReviewerActionKind.RESOLVE_CONTRADICTION: 5,
            ReviewerActionKind.RESOLVE_AUTHORITY: 10,
            ReviewerActionKind.RESOLVE_PROOF: 15,
            ReviewerActionKind.SUPPLY_EVIDENCE: 20,
            ReviewerActionKind.RESOLVE_APPLICABILITY: 25,
            ReviewerActionKind.COMPILE_REQUIREMENT: 30,
            ReviewerActionKind.REVIEW_EVIDENCE: 40,
            ReviewerActionKind.CONFIRM_NOT_APPLICABLE: 50,
            ReviewerActionKind.REVIEW_PACKAGE: 100,
            ReviewerActionKind.NONE: 0,
        }.get(kind, 50)

    def _decide_status(
        self,
        *,
        proof_status: ProofExecutionStatus,
        authority: AuthoritySnapshot,
        applicability: ApplicabilityState,
        has_support: bool,
        has_counter: bool,
        unsupported_semantics: bool,
    ) -> tuple[ComplianceStatus, ReviewerActionKind, ReviewState]:
        """Map evidence + authority + proof into a fail-closed status."""
        if applicability is ApplicabilityState.NOT_APPLICABLE:
            return (
                ComplianceStatus.NOT_APPLICABLE,
                ReviewerActionKind.NONE,
                ReviewState.NOT_REQUIRED,
            )

        # Missing / ambiguous authority always wins as the primary review action
        # (even when the prover also reports unsupported for the same reason).
        if authority.is_unknown:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_AUTHORITY,
                ReviewState.REQUIRED,
            )

        # Proof non-definitive outcomes force unknown.
        if proof_status is ProofExecutionStatus.TIMEOUT:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_PROOF,
                ReviewState.REQUIRED,
            )
        if proof_status is ProofExecutionStatus.ERROR:
            if has_support and has_counter:
                return (
                    ComplianceStatus.UNKNOWN,
                    ReviewerActionKind.RESOLVE_CONTRADICTION,
                    ReviewState.REQUIRED,
                )
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_PROOF,
                ReviewState.REQUIRED,
            )
        if proof_status is ProofExecutionStatus.UNSUPPORTED:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_PROOF
                if not unsupported_semantics
                else ReviewerActionKind.COMPILE_REQUIREMENT,
                ReviewState.REQUIRED,
            )
        if proof_status is ProofExecutionStatus.SKIPPED:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_PROOF,
                ReviewState.REQUIRED,
            )

        if applicability is ApplicabilityState.UNKNOWN:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_APPLICABILITY,
                ReviewState.REQUIRED,
            )

        if applicability is ApplicabilityState.CONDITIONAL:
            # Conditional applicability without resolved condition → unknown.
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_APPLICABILITY,
                ReviewState.REQUIRED,
            )

        if has_support and has_counter:
            return (
                ComplianceStatus.UNKNOWN,
                ReviewerActionKind.RESOLVE_CONTRADICTION,
                ReviewState.REQUIRED,
            )

        if proof_status is ProofExecutionStatus.FAILURE:
            if has_counter and not has_support:
                return (
                    ComplianceStatus.UNSATISFIED,
                    ReviewerActionKind.REVIEW_EVIDENCE,
                    ReviewState.REQUIRED,
                )
            if not has_support:
                return (
                    ComplianceStatus.UNSATISFIED,
                    ReviewerActionKind.SUPPLY_EVIDENCE,
                    ReviewState.REQUIRED,
                )
            return (
                ComplianceStatus.UNSATISFIED,
                ReviewerActionKind.REVIEW_EVIDENCE,
                ReviewState.REQUIRED,
            )

        if proof_status is ProofExecutionStatus.SUCCESS and has_support and not has_counter:
            # Authority not_applicable is allowed when no legal source is cited.
            if authority.state in (
                AuthorityResolutionState.RESOLVED,
                AuthorityResolutionState.NOT_APPLICABLE,
            ):
                return (
                    ComplianceStatus.SATISFIED,
                    ReviewerActionKind.NONE,
                    ReviewState.NOT_REQUIRED,
                )

        # Default fail-closed.
        return (
            ComplianceStatus.UNKNOWN,
            ReviewerActionKind.REVIEW_EVIDENCE,
            ReviewState.REQUIRED,
        )

    # -- form verifier ------------------------------------------------------

    def _run_form_verifier(
        self, inp: SubmissionComplianceInput
    ) -> tuple[list[ReviewerAction], list[str], list[str]]:
        actions: list[ReviewerAction] = []
        reasons: list[str] = []
        warnings: list[str] = []
        if inp.form_values is None and inp.form_rule_set is None:
            return actions, reasons, warnings

        if inp.form_rule_set is None or inp.form_values is None:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_EMPTY.value)
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.REVIEW_PACKAGE,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.FORM_VERIFIER_EMPTY.value,),
                    priority=15,
                    message="form_verifier_inputs_incomplete",
                    labels={},
                )
            )
            return actions, reasons, warnings

        verifier = self._form_verifier
        if verifier is None and FormRequirementsVerifier is not None:
            try:
                verifier = FormRequirementsVerifier(prover="z3", timeout=5)
            except Exception:
                verifier = None

        if verifier is None:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value)
            warnings.append("form_verifier_unavailable")
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.RESOLVE_PROOF,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value,),
                    priority=15,
                    message="form_verifier_unavailable",
                    labels={},
                )
            )
            return actions, reasons, warnings

        try:
            report = verifier.verify(
                form_id=inp.form_id or inp.package_id,
                source_pdf="submission_package",
                values=dict(inp.form_values),
                rule_set=inp.form_rule_set,
            )
        except Exception as exc:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value)
            warnings.append(f"form_verifier_error:{type(exc).__name__}")
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.RESOLVE_PROOF,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value,),
                    priority=15,
                    message="form_verifier_raised",
                    labels={},
                )
            )
            return actions, reasons, warnings

        overall_pass = bool(getattr(report, "overall_pass", False))
        review_required = bool(getattr(report, "review_required", True))
        results = list(getattr(report, "results", None) or [])

        if not results:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_EMPTY.value)
            actions.append(
                ReviewerAction(
                    action_id=self._new_id("action"),
                    kind=ReviewerActionKind.REVIEW_PACKAGE,
                    requirement_id=None,
                    reason_codes=(ComplianceReasonCode.FORM_VERIFIER_EMPTY.value,),
                    priority=15,
                    message="form_verifier_no_formulas",
                    labels={},
                )
            )
            return actions, reasons, warnings

        if overall_pass and not review_required:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_PASS.value)
            return actions, reasons, warnings

        # Map non-pass form results into fail-closed reasons.
        any_unknown = False
        any_fail = False
        for r in results:
            status = getattr(r, "status", FORM_STATUS_UNKNOWN)
            if status == FORM_STATUS_SATISFIED:
                continue
            if status == FORM_STATUS_VIOLATED:
                any_fail = True
            else:
                any_unknown = True

        if any_fail:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_FAIL.value)
        if any_unknown or review_required or not overall_pass:
            reasons.append(ComplianceReasonCode.FORM_VERIFIER_UNKNOWN.value)

        actions.append(
            ReviewerAction(
                action_id=self._new_id("action"),
                kind=ReviewerActionKind.RESOLVE_PROOF,
                requirement_id=None,
                reason_codes=tuple(reasons[-2:]) if reasons else (),
                priority=15,
                message="form_verifier_failed_closed",
                labels={"form_id": inp.form_id or inp.package_id},
            )
        )
        return actions, reasons, warnings

    # -- package aggregation ------------------------------------------------

    def _aggregate_fail_closed(
        self,
        *,
        assessments: Sequence[RequirementAssessment],
        no_requirements: bool,
        no_evidence: bool,
        uncompiled: bool,
        form_fail_closed: bool,
        quarantined: bool,
        edge_round_trip_failed: bool,
    ) -> tuple[
        bool,
        ComplianceStatus,
        ComplianceDisposition,
        ReviewState,
        list[str],
        dict[str, int],
    ]:
        reasons: list[str] = []
        counts = {
            "mandatory_unknown": 0,
            "mandatory_unsatisfied": 0,
            "mandatory_satisfied": 0,
            "not_applicable": 0,
        }

        for a in assessments:
            if a.status is ComplianceStatus.NOT_APPLICABLE:
                counts["not_applicable"] += 1
                continue
            if not a.mandatory:
                continue
            if a.status is ComplianceStatus.SATISFIED:
                counts["mandatory_satisfied"] += 1
            elif a.status is ComplianceStatus.UNSATISFIED:
                counts["mandatory_unsatisfied"] += 1
            else:
                counts["mandatory_unknown"] += 1

        overall_pass = True
        review_state = ReviewState.NOT_REQUIRED
        disposition = ComplianceDisposition.ASSESSED
        overall_status = ComplianceStatus.SATISFIED

        if no_requirements:
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN
            disposition = ComplianceDisposition.EMPTY
            review_state = ReviewState.REQUIRED
            reasons.append(ComplianceReasonCode.OVERALL_FAIL_CLOSED.value)

        if not assessments and not no_requirements:
            # Requirements present but none assessed (should not happen).
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN
            disposition = ComplianceDisposition.UNKNOWN
            review_state = ReviewState.REQUIRED
            reasons.append(ComplianceReasonCode.OVERALL_FAIL_CLOSED.value)

        if no_evidence and assessments:
            # Evidence absence alone does not force unknown if assessments
            # already recorded unsatisfied; still blocks pass.
            overall_pass = False
            if overall_status is ComplianceStatus.SATISFIED:
                overall_status = ComplianceStatus.UNKNOWN
            reasons.append(ComplianceReasonCode.NO_EVIDENCE.value)

        if uncompiled:
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN
            disposition = ComplianceDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            reasons.append(ComplianceReasonCode.UNSUPPORTED_SEMANTICS.value)

        if form_fail_closed:
            overall_pass = False
            if overall_status is ComplianceStatus.SATISFIED:
                overall_status = ComplianceStatus.UNKNOWN
            review_state = ReviewState.REQUIRED
            disposition = ComplianceDisposition.REVIEW

        if edge_round_trip_failed:
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN
            review_state = ReviewState.REQUIRED
            disposition = ComplianceDisposition.REVIEW

        if quarantined:
            overall_pass = False
            disposition = ComplianceDisposition.QUARANTINE
            review_state = ReviewState.REQUIRED
            reasons.append(ComplianceReasonCode.QUARANTINED.value)

        if counts["mandatory_unknown"] > 0:
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN
            review_state = ReviewState.REQUIRED
            reasons.append(ComplianceReasonCode.MANDATORY_UNKNOWN.value)
            if disposition is ComplianceDisposition.ASSESSED:
                disposition = ComplianceDisposition.PARTIAL

        if counts["mandatory_unsatisfied"] > 0:
            overall_pass = False
            reasons.append(ComplianceReasonCode.MANDATORY_UNSATISFIED.value)
            # Unsatisfied without unknowns yields overall unsatisfied.
            if counts["mandatory_unknown"] == 0 and not uncompiled:
                overall_status = ComplianceStatus.UNSATISFIED
            else:
                overall_status = ComplianceStatus.UNKNOWN
            if review_state is ReviewState.NOT_REQUIRED:
                review_state = ReviewState.REQUIRED
            if disposition is ComplianceDisposition.ASSESSED:
                disposition = ComplianceDisposition.PARTIAL

        # Vacuous pass forbidden: need at least one mandatory satisfied.
        if counts["mandatory_satisfied"] == 0:
            overall_pass = False
            if overall_status is ComplianceStatus.SATISFIED:
                overall_status = ComplianceStatus.UNKNOWN
            if not no_requirements:
                reasons.append(ComplianceReasonCode.OVERALL_FAIL_CLOSED.value)

        # Any assessment that blocks pass.
        if any(a.blocks_overall_pass for a in assessments):
            overall_pass = False

        if overall_pass:
            if counts["mandatory_satisfied"] > 0 and counts["mandatory_unknown"] == 0:
                overall_status = ComplianceStatus.SATISFIED
                disposition = ComplianceDisposition.ASSESSED
                review_state = ReviewState.NOT_REQUIRED
                reasons.append(ComplianceReasonCode.ALL_SATISFIED.value)
                reasons.append(ComplianceReasonCode.OVERALL_PASS.value)
            else:
                overall_pass = False
                overall_status = ComplianceStatus.UNKNOWN
                reasons.append(ComplianceReasonCode.OVERALL_FAIL_CLOSED.value)

        # Defensive final gate.
        if overall_status is not ComplianceStatus.SATISFIED:
            overall_pass = False
        if counts["mandatory_unknown"] > 0:
            overall_pass = False
            overall_status = ComplianceStatus.UNKNOWN

        return (
            overall_pass,
            overall_status,
            disposition,
            review_state,
            reasons,
            counts,
        )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def analyze_submission_compliance(
    value: SubmissionComplianceInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> SubmissionComplianceResult:
    """Module-level wrapper around :class:`SubmissionComplianceProcessor`."""
    id_factory = kwargs.pop("id_factory", None)
    proof_executor = kwargs.pop("proof_executor", None)
    form_verifier = kwargs.pop("form_verifier", None)
    return SubmissionComplianceProcessor(
        id_factory=id_factory,
        proof_executor=proof_executor,
        form_verifier=form_verifier,
    ).analyze(value, **kwargs)


__all__ = [
    "COMPLIANCE_RULESET_VERSION",
    "PARSER_VERSION",
    "SUBMISSION_COMPLIANCE_INTERFACE",
    "SUBMISSION_COMPLIANCE_SCHEMA_VERSION",
    "AuthoritySnapshot",
    "CitationRole",
    "ComplianceDisposition",
    "ComplianceReasonCode",
    "ComplianceStatus",
    "ProofExecutionReceipt",
    "ProofExecutionStatus",
    "RequirementAssessment",
    "ReviewerAction",
    "ReviewerActionKind",
    "SourceCitation",
    "SubmissionComplianceError",
    "SubmissionComplianceInput",
    "SubmissionComplianceProcessor",
    "SubmissionComplianceResult",
    "admissible_fact_types_for",
    "analyze_submission_compliance",
    "build_citations",
    "build_explanation",
    "compliance_status_to_assessment",
    "default_evidence_prover",
    "match_evidence_for_requirement",
    "proof_status_blocks_pass",
    "proof_status_to_compliance",
    "sha256_hex",
]
