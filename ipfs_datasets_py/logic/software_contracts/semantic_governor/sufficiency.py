"""Conservative pre-execution context sufficiency evaluation (SCG-012).

Pure, deterministic join of coverage, repository-state signals, verification
policy / task-class acceptance matrix, and calibration into one explained
``ContextSufficiencyClaim``.

Normative rules:

* Closed precedence table (most restrictive first); never invent authority.
* A verification pass is one optional input and never sole sufficiency authority.
* Opaque critical dependencies and stale capsules force expansion / raw
  regeneration rather than silent compressed acceptance.
* Absent or unknown task-class mapping fails closed (``invalid``).
* Missing required selected / full-suite / static / type / proof / review
  checks fail closed (``invalid``).
* Policy boundaries and conflicting evidence require human review.
* Complete-but-hard work may request frontier escalation without inventing
  coverage.
* Identical inputs yield identical ``claim_cid`` identities.
* Canonical identity uses ``software_contracts.content`` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    BASIS_POINTS,
    MAX_GAPS,
    MAX_REASON_CODES,
    AuditContractError,
    ContextCoverageManifest,
    ContextSufficiencyClaim,
    CoverageGap,
    CoverageGapKind,
    DecisionAction,
    ExclusionReason,
    InclusionKind,
    RouteTier,
    SufficiencyEvidenceBasis,
    assert_sufficiency_not_verification_only,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ContextSufficiencyState,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration_contracts import (
    EmpiricalRate,
    TaskClassCalibrationProfile,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    CompressionPolicy,
    PolicyContractError,
    TaskClassAcceptanceRequirements,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE: Final[str] = (
    "evaluate_context_sufficiency@1"
)
SUFFICIENCY_EVALUATOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-sufficiency-evaluator@1"
)
SUFFICIENCY_EVALUATION_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-sufficiency-evaluation-view@1"
)
VERIFICATION_POLICY_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-verification-policy-view@1"
)
REPOSITORY_STATE_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-repository-state-view@1"
)
CALIBRATION_PROFILE_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-calibration-profile-view@1"
)
CONTEXT_PACK_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-context-pack-view@1"
)

GENERATOR_ID: Final[str] = "sufficiency_evaluator"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "sufficiency.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ASSUMPTIONS: Final[int] = 512
MAX_STALE_IDS: Final[int] = 4_096
MAX_OBLIGATION_IDS: Final[int] = 4_096

# Empirical thresholds (basis points). Conservative defaults; not promotions.
_FRONTIER_COMPLEXITY_BP: Final[int] = 8_000
_FRONTIER_OMISSION_RATE_BP: Final[int] = 3_000
_FRONTIER_MIN_USES: Final[int] = 5
_CAVEAT_CONFIDENCE_FLOOR_BP: Final[int] = 5_000
_POSITIVE_CONFIDENCE_FLOOR_BP: Final[int] = 8_000
_HEURISTIC_CONFIDENCE_CEILING_BP: Final[int] = 5_000

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")

# Closed precedence: lower rank number is more restrictive / evaluated first.
_STATE_PRECEDENCE: Final[tuple[str, ...]] = (
    ContextSufficiencyState.EVALUATION_FAILED.value,
    ContextSufficiencyState.INVALID.value,
    ContextSufficiencyState.STALE.value,
    ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value,
    ContextSufficiencyState.EXPANSION_REQUIRED.value,
    ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value,
    ContextSufficiencyState.INCONCLUSIVE.value,
    ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
    ContextSufficiencyState.SUFFICIENT.value,
)

# Gap kinds that force expansion when critical (or always for stale).
_EXPANSION_GAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        CoverageGapKind.OPAQUE_DEPENDENCY.value,
        CoverageGapKind.DYNAMIC_IMPORT.value,
        CoverageGapKind.UNRESOLVED_INVALIDATION.value,
        CoverageGapKind.MISSING_PROOF.value,
        CoverageGapKind.MISSING_TEST.value,
        CoverageGapKind.MISSING_SCHEMA.value,
        CoverageGapKind.MISSING_FIXTURE.value,
        CoverageGapKind.MISSING_CONFIGURATION.value,
        CoverageGapKind.BUDGET_TRUNCATION.value,
        CoverageGapKind.LOW_CONFIDENCE.value,
    }
)

_STALE_GAP_KINDS: Final[frozenset[str]] = frozenset(
    {
        CoverageGapKind.STALE_CAPSULE.value,
    }
)

# Required-check attribute names on TaskClassAcceptanceRequirements /
# VerificationPolicyView (closed matrix surface).
_REQUIRED_CHECK_ATTRS: Final[tuple[tuple[str, str], ...]] = (
    ("require_selected_tests", "selected_tests"),
    ("require_full_suite_fallback", "full_suite"),
    ("require_static_checks", "static_checks"),
    ("require_type_checks", "type_checks"),
    ("require_proofs", "proofs"),
    ("require_human_review", "human_review"),
)


class SufficiencyEvaluatorError(SemanticGovernorBaseError):
    """Raised when sufficiency evaluation inputs are malformed or unsafe."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise SufficiencyEvaluatorError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SufficiencyEvaluatorError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise SufficiencyEvaluatorError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise SufficiencyEvaluatorError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SufficiencyEvaluatorError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise SufficiencyEvaluatorError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise SufficiencyEvaluatorError(f"{name} must be a nonnegative integer")
    return value


def _basis_points(value: Any, name: str) -> int:
    bp = _nonneg_int(value, name)
    if bp > BASIS_POINTS:
        raise SufficiencyEvaluatorError(f"{name} must be in 0..{BASIS_POINTS}")
    return bp


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise SufficiencyEvaluatorError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise SufficiencyEvaluatorError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SufficiencyEvaluatorError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SufficiencyEvaluatorError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise SufficiencyEvaluatorError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise SufficiencyEvaluatorError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SufficiencyEvaluatorError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise SufficiencyEvaluatorError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise SufficiencyEvaluatorError(f"{name} must not contain duplicates")
    return ordered


def _sort_reason_codes(codes: Iterable[str]) -> tuple[str, ...]:
    ordered = tuple(sorted(set(codes)))
    if len(ordered) > MAX_REASON_CODES:
        raise SufficiencyEvaluatorError("blocking_reason_codes exceeds maximum length")
    for code in ordered:
        _token(code, "blocking_reason_codes")
    return ordered


# ---------------------------------------------------------------------------
# Input views
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextPackView:
    """Bounded ContextPack projection consumed by pre-execution sufficiency."""

    context_pack_cid: str
    coverage_manifest: ContextCoverageManifest | Mapping[str, Any]
    task_class: str
    risk_class: str
    route_tier: RouteTier | str = RouteTier.SMALL
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "context_pack_cid", _cid(self.context_pack_cid, "context_pack_cid")
        )
        object.__setattr__(
            self,
            "coverage_manifest",
            _normalize_manifest(self.coverage_manifest),
        )
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        object.__setattr__(
            self, "route_tier", _enum(self.route_tier, RouteTier, "route_tier")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if self.coverage_manifest.header.context_pack_cid != self.context_pack_cid:
            raise SufficiencyEvaluatorError(
                "coverage_manifest.header.context_pack_cid must equal context_pack_cid"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_PACK_VIEW_SCHEMA,
            "context_pack_cid": self.context_pack_cid,
            "coverage_manifest": self.coverage_manifest.identity_payload(),
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "route_tier": self.route_tier,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RepositoryStateView:
    """Repository-state signals that affect pre-execution sufficiency."""

    repository_state_cid: str
    stale_capsule_ids: Sequence[str] = ()
    unresolved_invalidation_ids: Sequence[str] = ()
    opaque_critical_dependency_ids: Sequence[str] = ()
    conflicting_evidence: bool = False
    policy_boundary: bool = False
    disclosure_overflow: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self,
            "stale_capsule_ids",
            _unique_sorted_tokens(
                list(self.stale_capsule_ids),
                "stale_capsule_ids",
                max_items=MAX_STALE_IDS,
            ),
        )
        object.__setattr__(
            self,
            "unresolved_invalidation_ids",
            _unique_sorted_tokens(
                list(self.unresolved_invalidation_ids),
                "unresolved_invalidation_ids",
                max_items=MAX_OBLIGATION_IDS,
            ),
        )
        object.__setattr__(
            self,
            "opaque_critical_dependency_ids",
            _unique_sorted_tokens(
                list(self.opaque_critical_dependency_ids),
                "opaque_critical_dependency_ids",
                max_items=MAX_OBLIGATION_IDS,
            ),
        )
        object.__setattr__(
            self,
            "conflicting_evidence",
            _bool(self.conflicting_evidence, "conflicting_evidence"),
        )
        object.__setattr__(
            self, "policy_boundary", _bool(self.policy_boundary, "policy_boundary")
        )
        object.__setattr__(
            self,
            "disclosure_overflow",
            _bool(self.disclosure_overflow, "disclosure_overflow"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REPOSITORY_STATE_VIEW_SCHEMA,
            "repository_state_cid": self.repository_state_cid,
            "stale_capsule_ids": list(self.stale_capsule_ids),
            "unresolved_invalidation_ids": list(self.unresolved_invalidation_ids),
            "opaque_critical_dependency_ids": list(self.opaque_critical_dependency_ids),
            "conflicting_evidence": self.conflicting_evidence,
            "policy_boundary": self.policy_boundary,
            "disclosure_overflow": self.disclosure_overflow,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class VerificationPolicyView:
    """Planned verification / acceptance checks for the task class.

    Each flag means the named check is present in the verification plan for
    this run (pre-execution admission), not that it has already passed.
    """

    selected_tests: bool = False
    full_suite: bool = False
    static_checks: bool = False
    type_checks: bool = False
    proofs: bool = False
    human_review: bool = False
    # Optional durable policy carrying the task-class acceptance matrix.
    compression_policy: CompressionPolicy | Mapping[str, Any] | None = None
    # Explicit acceptance row when a full CompressionPolicy is not supplied.
    acceptance_requirements: (
        TaskClassAcceptanceRequirements | Mapping[str, Any] | None
    ) = None
    verification_passed: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "selected_tests",
            "full_suite",
            "static_checks",
            "type_checks",
            "proofs",
            "human_review",
            "verification_passed",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        policy = self.compression_policy
        if policy is not None:
            object.__setattr__(
                self, "compression_policy", _normalize_compression_policy(policy)
            )
        acceptance = self.acceptance_requirements
        if acceptance is not None:
            object.__setattr__(
                self,
                "acceptance_requirements",
                _normalize_acceptance(acceptance),
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        policy = self.compression_policy
        acceptance = self.acceptance_requirements
        return {
            "schema": VERIFICATION_POLICY_VIEW_SCHEMA,
            "selected_tests": self.selected_tests,
            "full_suite": self.full_suite,
            "static_checks": self.static_checks,
            "type_checks": self.type_checks,
            "proofs": self.proofs,
            "human_review": self.human_review,
            "compression_policy": (
                None if policy is None else policy.identity_payload()
            ),
            "acceptance_requirements": (
                None if acceptance is None else acceptance.identity_payload()
            ),
            "verification_passed": self.verification_passed,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    def planned_check(self, short_name: str) -> bool:
        return bool(getattr(self, short_name))


@dataclass(frozen=True, slots=True)
class CalibrationProfileView:
    """Bounded calibration signals used for frontier / confidence routing.

    Empirical rates never upgrade formal exactness or invent coverage.
    """

    profile_cid: str | None = None
    task_class: str | None = None
    risk_class: str | None = None
    total_uses: int = 0
    omission_rate_bp: int = 0
    complexity_bp: int = 0
    request_frontier: bool = False
    review_disagreement_count: int = 0
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_cid", _optional_cid(self.profile_cid, "profile_cid")
        )
        if self.task_class is not None:
            object.__setattr__(
                self, "task_class", _token(self.task_class, "task_class")
            )
        if self.risk_class is not None:
            object.__setattr__(
                self, "risk_class", _token(self.risk_class, "risk_class")
            )
        object.__setattr__(self, "total_uses", _nonneg_int(self.total_uses, "total_uses"))
        object.__setattr__(
            self,
            "omission_rate_bp",
            _basis_points(self.omission_rate_bp, "omission_rate_bp"),
        )
        object.__setattr__(
            self, "complexity_bp", _basis_points(self.complexity_bp, "complexity_bp")
        )
        object.__setattr__(
            self, "request_frontier", _bool(self.request_frontier, "request_frontier")
        )
        object.__setattr__(
            self,
            "review_disagreement_count",
            _nonneg_int(self.review_disagreement_count, "review_disagreement_count"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_PROFILE_VIEW_SCHEMA,
            "profile_cid": self.profile_cid,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "total_uses": self.total_uses,
            "omission_rate_bp": self.omission_rate_bp,
            "complexity_bp": self.complexity_bp,
            "request_frontier": self.request_frontier,
            "review_disagreement_count": self.review_disagreement_count,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SufficiencyEvaluationView:
    """Joined pre-execution view for ``evaluate_context_sufficiency``."""

    context_pack: ContextPackView | Mapping[str, Any]
    repository_state: RepositoryStateView | Mapping[str, Any]
    verification_policy: VerificationPolicyView | Mapping[str, Any]
    calibration_profile: CalibrationProfileView | Mapping[str, Any] | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "context_pack", _normalize_context_pack(self.context_pack)
        )
        object.__setattr__(
            self,
            "repository_state",
            _normalize_repository_state(self.repository_state),
        )
        object.__setattr__(
            self,
            "verification_policy",
            _normalize_verification_policy(self.verification_policy),
        )
        if self.calibration_profile is None:
            object.__setattr__(self, "calibration_profile", CalibrationProfileView())
        else:
            object.__setattr__(
                self,
                "calibration_profile",
                _normalize_calibration(self.calibration_profile),
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        pack = self.context_pack
        repo = self.repository_state
        if pack.coverage_manifest.header.repository_state_cid != repo.repository_state_cid:
            raise SufficiencyEvaluatorError(
                "coverage_manifest.header.repository_state_cid must equal "
                "repository_state.repository_state_cid"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SUFFICIENCY_EVALUATION_VIEW_SCHEMA,
            "context_pack": self.context_pack.identity_payload(),
            "repository_state": self.repository_state.identity_payload(),
            "verification_policy": self.verification_policy.identity_payload(),
            "calibration_profile": self.calibration_profile.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


def _normalize_manifest(
    value: ContextCoverageManifest | Mapping[str, Any],
) -> ContextCoverageManifest:
    if isinstance(value, ContextCoverageManifest):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value and "manifest_cid" in value:
                return ContextCoverageManifest.from_dict(value)
            # Allow identity_payload-shaped mappings without claimed cid.
            payload = dict(value)
            payload.pop("manifest_cid", None)
            return ContextCoverageManifest(**payload)
        except (AuditContractError, TypeError, ValueError) as exc:
            raise SufficiencyEvaluatorError(
                f"coverage_manifest is malformed: {exc}"
            ) from exc
    raise SufficiencyEvaluatorError(
        "coverage_manifest must be ContextCoverageManifest or mapping"
    )


def _normalize_acceptance(
    value: TaskClassAcceptanceRequirements | Mapping[str, Any],
) -> TaskClassAcceptanceRequirements:
    if isinstance(value, TaskClassAcceptanceRequirements):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return TaskClassAcceptanceRequirements.from_dict(value)
            return TaskClassAcceptanceRequirements(
                task_class=value.get("task_class", ""),
                risk_class=value.get("risk_class", ""),
                require_selected_tests=value.get("require_selected_tests", True),
                require_full_suite_fallback=value.get(
                    "require_full_suite_fallback", True
                ),
                require_static_checks=value.get("require_static_checks", True),
                require_type_checks=value.get("require_type_checks", True),
                require_proofs=value.get("require_proofs", False),
                require_human_review=value.get("require_human_review", False),
            )
        except (PolicyContractError, TypeError, ValueError) as exc:
            raise SufficiencyEvaluatorError(
                f"acceptance_requirements is malformed: {exc}"
            ) from exc
    raise SufficiencyEvaluatorError(
        "acceptance_requirements must be TaskClassAcceptanceRequirements or mapping"
    )


def _normalize_compression_policy(
    value: CompressionPolicy | Mapping[str, Any],
) -> CompressionPolicy:
    if isinstance(value, CompressionPolicy):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value and "policy_cid" in value:
                return CompressionPolicy.from_dict(value)
            payload = dict(value)
            payload.pop("policy_cid", None)
            return CompressionPolicy(**payload)
        except (PolicyContractError, TypeError, ValueError) as exc:
            raise SufficiencyEvaluatorError(
                f"compression_policy is malformed: {exc}"
            ) from exc
    raise SufficiencyEvaluatorError(
        "compression_policy must be CompressionPolicy or mapping"
    )


def _normalize_context_pack(
    value: ContextPackView | Mapping[str, Any],
) -> ContextPackView:
    if isinstance(value, ContextPackView):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("schema", None)
        return ContextPackView(**payload)
    raise SufficiencyEvaluatorError("context_pack must be ContextPackView or mapping")


def _normalize_repository_state(
    value: RepositoryStateView | Mapping[str, Any],
) -> RepositoryStateView:
    if isinstance(value, RepositoryStateView):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("schema", None)
        return RepositoryStateView(**payload)
    raise SufficiencyEvaluatorError(
        "repository_state must be RepositoryStateView or mapping"
    )


def _normalize_verification_policy(
    value: VerificationPolicyView | Mapping[str, Any],
) -> VerificationPolicyView:
    if isinstance(value, VerificationPolicyView):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("schema", None)
        return VerificationPolicyView(**payload)
    raise SufficiencyEvaluatorError(
        "verification_policy must be VerificationPolicyView or mapping"
    )


def _normalize_calibration(
    value: CalibrationProfileView | TaskClassCalibrationProfile | Mapping[str, Any],
) -> CalibrationProfileView:
    if isinstance(value, CalibrationProfileView):
        return value
    if isinstance(value, TaskClassCalibrationProfile):
        rate = value.omission_rate
        rate_bp = rate.rate_bp if isinstance(rate, EmpiricalRate) else 0
        return CalibrationProfileView(
            profile_cid=value.profile_cid,
            task_class=value.task_class,
            risk_class=value.risk_class,
            total_uses=value.total_uses,
            omission_rate_bp=rate_bp,
            complexity_bp=0,
            request_frontier=False,
            review_disagreement_count=value.review_disagreement_count,
            notes=value.notes,
        )
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("schema", None)
        # Accept TaskClassCalibrationProfile identity payloads.
        if "omission_rate" in payload and "omission_rate_bp" not in payload:
            omission = payload.pop("omission_rate")
            if isinstance(omission, Mapping):
                payload["omission_rate_bp"] = omission.get("rate_bp", 0)
            elif isinstance(omission, EmpiricalRate):
                payload["omission_rate_bp"] = omission.rate_bp
        for drop in (
            "header",
            "profile_id",
            "partition",
            "revision",
            "compressed_success_count",
            "expanded_success_count",
            "required_proof_classification",
            "classification_source",
            "record_cids",
            "profile_cid",
            "interface_id",
        ):
            # profile_cid is kept when present as a top-level cid string only.
            if drop == "profile_cid" and isinstance(payload.get("profile_cid"), str):
                continue
            if drop in payload and drop != "profile_cid":
                payload.pop(drop, None)
        # Re-add profile_cid carefully.
        if "profile_cid" in payload and not isinstance(payload["profile_cid"], str):
            payload.pop("profile_cid", None)
        allowed = {
            "profile_cid",
            "task_class",
            "risk_class",
            "total_uses",
            "omission_rate_bp",
            "complexity_bp",
            "request_frontier",
            "review_disagreement_count",
            "notes",
            "metadata",
        }
        filtered = {key: payload[key] for key in allowed if key in payload}
        return CalibrationProfileView(**filtered)
    raise SufficiencyEvaluatorError(
        "calibration_profile must be CalibrationProfileView, "
        "TaskClassCalibrationProfile, or mapping"
    )


# ---------------------------------------------------------------------------
# Precedence / decision helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Judgment:
    """Internal ranked judgment before claim assembly."""

    state: str
    reasons: tuple[str, ...]
    evidence_bases: tuple[str, ...]
    gap_ids: tuple[str, ...]
    confidence_bp: int
    notes: str | None = None


def sufficiency_state_precedence() -> tuple[str, ...]:
    """Return the closed sufficiency-state precedence (restrictive first)."""

    return _STATE_PRECEDENCE


def recommended_decision_action(
    sufficiency_state: str | ContextSufficiencyState,
) -> str:
    """Map a closed sufficiency state to the closed DecisionAction vocabulary."""

    state = (
        sufficiency_state.value
        if isinstance(sufficiency_state, ContextSufficiencyState)
        else str(sufficiency_state)
    )
    state = _enum(state, ContextSufficiencyState, "sufficiency_state")
    mapping = {
        ContextSufficiencyState.SUFFICIENT.value: DecisionAction.ACCEPT_COMPRESSED.value,
        ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value: (
            DecisionAction.ACCEPT_COMPRESSED.value
        ),
        ContextSufficiencyState.EXPANSION_REQUIRED.value: (
            DecisionAction.REQUIRE_EXPANSION.value
        ),
        ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value: (
            DecisionAction.ESCALATE_FRONTIER.value
        ),
        ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value: (
            DecisionAction.REQUIRE_HUMAN_REVIEW.value
        ),
        ContextSufficiencyState.INCONCLUSIVE.value: (
            DecisionAction.MARK_INCONCLUSIVE.value
        ),
        ContextSufficiencyState.INVALID.value: DecisionAction.MARK_INVALID.value,
        ContextSufficiencyState.STALE.value: DecisionAction.MARK_STALE.value,
        ContextSufficiencyState.EVALUATION_FAILED.value: (
            DecisionAction.EVALUATION_FAILED.value
        ),
    }
    return mapping[state]


def _resolve_acceptance(
    pack: ContextPackView,
    policy: VerificationPolicyView,
) -> TaskClassAcceptanceRequirements | None:
    """Return the closed acceptance row or None when mapping is absent/unknown."""

    if policy.acceptance_requirements is not None:
        row = policy.acceptance_requirements
        if row.task_class == pack.task_class and row.risk_class == pack.risk_class:
            return row
        # Explicit row for a different class is treated as unknown mapping.
        return None
    if policy.compression_policy is not None:
        return policy.compression_policy.acceptance_for(pack.task_class, pack.risk_class)
    return None


def _missing_required_checks(
    acceptance: TaskClassAcceptanceRequirements,
    policy: VerificationPolicyView,
) -> list[str]:
    missing: list[str] = []
    for require_attr, planned_attr in _REQUIRED_CHECK_ATTRS:
        if getattr(acceptance, require_attr) and not policy.planned_check(planned_attr):
            missing.append(f"missing_required_{planned_attr}")
    return missing


def _collect_stale_signals(
    manifest: ContextCoverageManifest,
    repo: RepositoryStateView,
) -> tuple[list[str], list[str]]:
    """Return (reason_codes, gap_ids) for stale capsules requiring raw regen."""

    reasons: list[str] = []
    gap_ids: list[str] = []
    if repo.stale_capsule_ids:
        reasons.append("stale_capsule_requires_raw_regeneration")
    for gap in manifest.known_gaps:
        if gap.gap_kind in _STALE_GAP_KINDS:
            reasons.append("stale_capsule_gap")
            gap_ids.append(gap.gap_id)
    return reasons, gap_ids


def _collect_opaque_critical(
    manifest: ContextCoverageManifest,
    repo: RepositoryStateView,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    gap_ids: list[str] = []
    if repo.opaque_critical_dependency_ids:
        reasons.append("opaque_critical_dependency")
    if manifest.opaque_dependency_ids:
        # Manifest-listed opaque deps expand when any matching critical gap exists,
        # or unconditionally when listed as opaque_critical on the state view.
        for gap in manifest.known_gaps:
            if (
                gap.gap_kind == CoverageGapKind.OPAQUE_DEPENDENCY.value
                and (gap.critical or gap.artifact_id in manifest.opaque_dependency_ids)
            ):
                reasons.append("opaque_critical_gap")
                gap_ids.append(gap.gap_id)
        # Critical opaque dependency ids on the pack always force expansion.
        if manifest.opaque_dependency_ids and not gap_ids:
            # Treat any declared opaque dependency without a non-critical-only
            # clearance as expansion pressure when critical state lists them.
            for dep_id in manifest.opaque_dependency_ids:
                if dep_id in repo.opaque_critical_dependency_ids:
                    reasons.append("opaque_critical_dependency")
                    break
    for gap in manifest.known_gaps:
        if (
            gap.gap_kind == CoverageGapKind.OPAQUE_DEPENDENCY.value
            and gap.critical
            and gap.gap_id not in gap_ids
        ):
            reasons.append("opaque_critical_gap")
            gap_ids.append(gap.gap_id)
    return reasons, gap_ids


def _collect_expansion_signals(
    manifest: ContextCoverageManifest,
    repo: RepositoryStateView,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    gap_ids: list[str] = []
    opaque_reasons, opaque_gaps = _collect_opaque_critical(manifest, repo)
    reasons.extend(opaque_reasons)
    gap_ids.extend(opaque_gaps)

    if repo.unresolved_invalidation_ids:
        reasons.append("unresolved_invalidation_obligations")

    for exclusion in manifest.exclusions:
        if (
            exclusion.critical
            and exclusion.exclusion_reason
            == ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
        ):
            reasons.append("critical_budget_exceeded_expansion_required")

    for gap in manifest.known_gaps:
        if gap.gap_kind in _STALE_GAP_KINDS:
            continue  # handled as stale precedence
        if gap.critical and gap.gap_kind in _EXPANSION_GAP_KINDS:
            reasons.append(f"critical_gap_{gap.gap_kind}")
            gap_ids.append(gap.gap_id)

    # Low-confidence capsule inclusions force expansion rather than acceptance.
    for inclusion in manifest.inclusions:
        if (
            inclusion.inclusion_kind
            in {
                InclusionKind.EXACT_CAPSULE.value,
                InclusionKind.CONSERVATIVE_CAPSULE.value,
            }
            and inclusion.confidence_bp <= _HEURISTIC_CONFIDENCE_CEILING_BP
        ):
            reasons.append("low_confidence_capsule_requires_expansion")
            break

    return reasons, gap_ids


def _coverage_complete(manifest: ContextCoverageManifest, repo: RepositoryStateView) -> bool:
    if repo.opaque_critical_dependency_ids:
        return False
    if repo.unresolved_invalidation_ids:
        return False
    if repo.stale_capsule_ids:
        return False
    for gap in manifest.known_gaps:
        if gap.critical:
            return False
        if gap.gap_kind in _STALE_GAP_KINDS:
            return False
    for exclusion in manifest.exclusions:
        if (
            exclusion.critical
            and exclusion.exclusion_reason
            == ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
        ):
            return False
    return True


def _noncritical_caveats(
    manifest: ContextCoverageManifest,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    gap_ids: list[str] = []
    for gap in manifest.known_gaps:
        if not gap.critical:
            reasons.append(f"noncritical_gap_{gap.gap_kind}")
            gap_ids.append(gap.gap_id)
    return reasons, gap_ids


def _confidence_bp(
    manifest: ContextCoverageManifest,
    calibration: CalibrationProfileView,
) -> int:
    confidences = [item.confidence_bp for item in manifest.inclusions]
    if not confidences:
        base = _CAVEAT_CONFIDENCE_FLOOR_BP
    else:
        base = min(confidences)
    # High historical omission slightly reduces reported confidence.
    if calibration.total_uses >= _FRONTIER_MIN_USES and calibration.omission_rate_bp:
        penalty = min(2_000, calibration.omission_rate_bp // 5)
        base = max(0, base - penalty)
    return base


def _structural_evidence_bases(
    *,
    include_freshness: bool,
    include_opaque: bool,
    include_invalidation: bool,
    include_budget: bool,
    include_calibration: bool,
    include_acceptance: bool,
    include_proof: bool,
    include_test: bool,
    include_confidence: bool,
    include_human_review: bool,
    include_verification: bool,
) -> list[str]:
    bases = [
        SufficiencyEvidenceBasis.COVERAGE_MANIFEST.value,
        SufficiencyEvidenceBasis.DEPENDENCY_GRAPH.value,
    ]
    if include_acceptance:
        bases.append(SufficiencyEvidenceBasis.ACCEPTANCE_MATRIX.value)
    if include_freshness:
        bases.append(SufficiencyEvidenceBasis.FRESHNESS.value)
    if include_confidence:
        bases.append(SufficiencyEvidenceBasis.CONFIDENCE.value)
    if include_proof:
        bases.append(SufficiencyEvidenceBasis.PROOF_COVERAGE.value)
    if include_test:
        bases.append(SufficiencyEvidenceBasis.TEST_COVERAGE.value)
    if include_calibration:
        bases.append(SufficiencyEvidenceBasis.CALIBRATION_HISTORY.value)
    if include_budget:
        bases.append(SufficiencyEvidenceBasis.BUDGET.value)
    if include_opaque:
        bases.append(SufficiencyEvidenceBasis.OPAQUE_DEPENDENCY_CHECK.value)
    if include_invalidation:
        bases.append(SufficiencyEvidenceBasis.INVALIDATION_OBLIGATIONS.value)
    if include_human_review:
        bases.append(SufficiencyEvidenceBasis.HUMAN_REVIEW.value)
    if include_verification:
        bases.append(SufficiencyEvidenceBasis.VERIFICATION_PASS.value)
    # Stable order by enum declaration.
    order = [item.value for item in SufficiencyEvidenceBasis]
    return [base for base in order if base in set(bases)]


def _judge(view: SufficiencyEvaluationView) -> _Judgment:
    pack = view.context_pack
    repo = view.repository_state
    policy = view.verification_policy
    calibration = view.calibration_profile
    manifest = pack.coverage_manifest

    conf = _confidence_bp(manifest, calibration)

    # --- 1. Invalid: absent/unknown task-class mapping ---------------------
    acceptance = _resolve_acceptance(pack, policy)
    if acceptance is None:
        bases = _structural_evidence_bases(
            include_freshness=False,
            include_opaque=False,
            include_invalidation=False,
            include_budget=False,
            include_calibration=False,
            include_acceptance=True,
            include_proof=False,
            include_test=False,
            include_confidence=False,
            include_human_review=False,
            include_verification=False,
        )
        return _Judgment(
            state=ContextSufficiencyState.INVALID.value,
            reasons=_sort_reason_codes(
                ("absent_or_unknown_task_class_mapping",)
            ),
            evidence_bases=tuple(bases),
            gap_ids=(),
            confidence_bp=0,
            notes="Absent/unknown task-class acceptance mapping fails closed",
        )

    # --- 2. Invalid: missing required selected/full/static/type/proof/review
    missing = _missing_required_checks(acceptance, policy)
    if missing:
        bases = _structural_evidence_bases(
            include_freshness=False,
            include_opaque=False,
            include_invalidation=False,
            include_budget=False,
            include_calibration=False,
            include_acceptance=True,
            include_proof=acceptance.require_proofs,
            include_test=acceptance.require_selected_tests
            or acceptance.require_full_suite_fallback,
            include_confidence=False,
            include_human_review=acceptance.require_human_review,
            include_verification=False,
        )
        return _Judgment(
            state=ContextSufficiencyState.INVALID.value,
            reasons=_sort_reason_codes(missing),
            evidence_bases=tuple(bases),
            gap_ids=(),
            confidence_bp=0,
            notes="Missing required verification checks fail closed",
        )

    # --- 3. Stale capsules → force raw regeneration ------------------------
    stale_reasons, stale_gaps = _collect_stale_signals(manifest, repo)
    if stale_reasons:
        bases = _structural_evidence_bases(
            include_freshness=True,
            include_opaque=False,
            include_invalidation=bool(repo.unresolved_invalidation_ids),
            include_budget=False,
            include_calibration=False,
            include_acceptance=True,
            include_proof=False,
            include_test=False,
            include_confidence=True,
            include_human_review=False,
            include_verification=policy.verification_passed,
        )
        return _Judgment(
            state=ContextSufficiencyState.STALE.value,
            reasons=_sort_reason_codes(stale_reasons),
            evidence_bases=tuple(bases),
            gap_ids=tuple(sorted(set(stale_gaps))),
            confidence_bp=min(conf, _HEURISTIC_CONFIDENCE_CEILING_BP),
            notes="Stale capsules force raw regeneration before compressed execution",
        )

    # --- 4. Human review: policy boundary / conflict / matrix review -------
    review_reasons: list[str] = []
    if repo.conflicting_evidence:
        review_reasons.append("conflicting_evidence")
    if repo.policy_boundary:
        review_reasons.append("policy_boundary")
    if repo.disclosure_overflow:
        review_reasons.append("disclosure_or_budget_overflow")
    if acceptance.require_human_review:
        review_reasons.append("task_class_requires_human_review")
    if policy.human_review and acceptance.require_human_review:
        # Planned review is presence, not a blocker by itself; matrix drives.
        pass
    # High-risk opaque without expansion path already covered → still review.
    if pack.risk_class in {"high", "critical"} and (
        repo.opaque_critical_dependency_ids or manifest.opaque_dependency_ids
    ):
        review_reasons.append("high_risk_opaque_requires_human_review")
    if review_reasons:
        bases = _structural_evidence_bases(
            include_freshness=True,
            include_opaque=bool(
                repo.opaque_critical_dependency_ids or manifest.opaque_dependency_ids
            ),
            include_invalidation=bool(repo.unresolved_invalidation_ids),
            include_budget=repo.disclosure_overflow,
            include_calibration=calibration.total_uses > 0,
            include_acceptance=True,
            include_proof=acceptance.require_proofs,
            include_test=acceptance.require_selected_tests,
            include_confidence=True,
            include_human_review=True,
            include_verification=policy.verification_passed,
        )
        return _Judgment(
            state=ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value,
            reasons=_sort_reason_codes(review_reasons),
            evidence_bases=tuple(bases),
            gap_ids=(),
            confidence_bp=conf,
            notes="Policy boundaries or conflicting evidence require human review",
        )

    # --- 5. Expansion required: opaque critical / critical gaps / obligations
    expand_reasons, expand_gaps = _collect_expansion_signals(manifest, repo)
    if expand_reasons:
        bases = _structural_evidence_bases(
            include_freshness=True,
            include_opaque=True,
            include_invalidation=bool(repo.unresolved_invalidation_ids),
            include_budget=any(
                r.startswith("critical_budget") or "budget" in r
                for r in expand_reasons
            ),
            include_calibration=calibration.total_uses > 0,
            include_acceptance=True,
            include_proof=any("missing_proof" in r for r in expand_reasons),
            include_test=any("missing_test" in r for r in expand_reasons),
            include_confidence=True,
            include_human_review=False,
            include_verification=policy.verification_passed,
        )
        return _Judgment(
            state=ContextSufficiencyState.EXPANSION_REQUIRED.value,
            reasons=_sort_reason_codes(expand_reasons),
            evidence_bases=tuple(bases),
            gap_ids=tuple(sorted(set(expand_gaps))),
            confidence_bp=min(conf, _HEURISTIC_CONFIDENCE_CEILING_BP),
            notes=(
                "Opaque critical or incomplete coverage forces expansion / "
                "raw regeneration"
            ),
        )

    # --- 6. Frontier: complete coverage but hard work ----------------------
    complete = _coverage_complete(manifest, repo)
    hard = False
    frontier_reasons: list[str] = []
    if complete and calibration.request_frontier:
        hard = True
        frontier_reasons.append("complete_but_hard_request_frontier")
    if complete and calibration.complexity_bp >= _FRONTIER_COMPLEXITY_BP:
        hard = True
        frontier_reasons.append("complete_but_high_complexity")
    if (
        complete
        and calibration.total_uses >= _FRONTIER_MIN_USES
        and calibration.omission_rate_bp >= _FRONTIER_OMISSION_RATE_BP
        and pack.route_tier
        in {
            RouteTier.DETERMINISTIC.value,
            RouteTier.SMALL.value,
            RouteTier.MEDIUM.value,
        }
    ):
        hard = True
        frontier_reasons.append("complete_but_high_historical_omission")
    if hard:
        bases = _structural_evidence_bases(
            include_freshness=True,
            include_opaque=True,
            include_invalidation=True,
            include_budget=True,
            include_calibration=True,
            include_acceptance=True,
            include_proof=acceptance.require_proofs,
            include_test=acceptance.require_selected_tests,
            include_confidence=True,
            include_human_review=False,
            include_verification=policy.verification_passed,
        )
        return _Judgment(
            state=ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value,
            reasons=_sort_reason_codes(frontier_reasons),
            evidence_bases=tuple(bases),
            gap_ids=(),
            confidence_bp=conf,
            notes="Coverage complete; escalate route tier (frontier) for hard work",
        )

    # --- 7. Caveats / sufficient / inconclusive ----------------------------
    caveat_reasons, caveat_gaps = _noncritical_caveats(manifest)
    bases = _structural_evidence_bases(
        include_freshness=True,
        include_opaque=True,
        include_invalidation=True,
        include_budget=True,
        include_calibration=calibration.total_uses > 0,
        include_acceptance=True,
        include_proof=acceptance.require_proofs or any(
            item.inclusion_kind == InclusionKind.PROOF.value
            for item in manifest.inclusions
        ),
        include_test=acceptance.require_selected_tests or any(
            item.inclusion_kind == InclusionKind.TEST.value
            for item in manifest.inclusions
        ),
        include_confidence=True,
        include_human_review=False,
        include_verification=policy.verification_passed,
    )

    # verification_pass alone cannot authorize positive states — bases above
    # always include structural coverage/graph evidence.
    assert_sufficiency_not_verification_only(
        ContextSufficiencyState.SUFFICIENT.value, bases
    )

    if conf < _CAVEAT_CONFIDENCE_FLOOR_BP:
        return _Judgment(
            state=ContextSufficiencyState.INCONCLUSIVE.value,
            reasons=_sort_reason_codes(("low_aggregate_confidence",)),
            evidence_bases=tuple(bases),
            gap_ids=tuple(sorted(set(caveat_gaps))),
            confidence_bp=conf,
            notes="Aggregate confidence too low for a positive sufficiency claim",
        )

    if caveat_reasons or conf < _POSITIVE_CONFIDENCE_FLOOR_BP:
        return _Judgment(
            state=ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
            reasons=_sort_reason_codes(
                caveat_reasons or ("confidence_below_exact_floor",)
            ),
            evidence_bases=tuple(bases),
            gap_ids=tuple(sorted(set(caveat_gaps))),
            confidence_bp=conf,
            notes="Sufficient with non-critical caveats; verification is not sole authority",
        )

    return _Judgment(
        state=ContextSufficiencyState.SUFFICIENT.value,
        reasons=(),
        evidence_bases=tuple(bases),
        gap_ids=(),
        confidence_bp=conf,
        notes="Structural coverage and acceptance checks admit compressed execution",
    )


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


def _build_header(
    view: SufficiencyEvaluationView,
    *,
    terminal_status: str,
    input_cids: Sequence[str],
    assumptions: Sequence[GovernorAssumption],
) -> GovernorArtifactHeader:
    pack = view.context_pack
    manifest = pack.coverage_manifest
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE,
    )
    provenance = ArtifactProvenance(
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(input_cids),
        tool_ids=(TOOL_ID,),
        policy_cid=manifest.policy_cid,
        notes=None,
    )
    return GovernorArtifactHeader(
        artifact_kind="context_sufficiency_claim",
        repository_state_cid=view.repository_state.repository_state_cid,
        context_pack_cid=pack.context_pack_cid,
        verification_bundle_cid=manifest.header.verification_bundle_cid,
        generator=generator,
        provenance=provenance,
        terminal_status=terminal_status,
        assumptions=tuple(assumptions),
        metadata={
            "evaluator_schema": SUFFICIENCY_EVALUATOR_SCHEMA,
            "view_cid": view.view_cid,
            "coverage_manifest_cid": manifest.manifest_cid,
        },
    )


def _build_assumptions(view: SufficiencyEvaluationView) -> tuple[GovernorAssumption, ...]:
    pack = view.context_pack
    manifest = pack.coverage_manifest
    items: list[GovernorAssumption] = [
        GovernorAssumption(
            assumption_id="coverage_manifest_verified",
            kind=AssumptionKind.VERIFICATION,
            statement=(
                "Coverage manifest is a verified structural inventory; "
                "this evaluator does not rescan or invent edges"
            ),
            supporting_cids=(manifest.manifest_cid,),
        ),
        GovernorAssumption(
            assumption_id="verification_pass_not_sole_authority",
            kind=AssumptionKind.VERIFICATION,
            statement=(
                "A verification pass alone cannot establish positive sufficiency"
            ),
            supporting_cids=(manifest.manifest_cid,),
        ),
        GovernorAssumption(
            assumption_id="closed_precedence_table",
            kind=AssumptionKind.COVERAGE,
            statement=(
                "Sufficiency uses a closed precedence table: invalid, stale, "
                "human_review, expansion, frontier, then positive states"
            ),
            supporting_cids=(manifest.manifest_cid,),
        ),
    ]
    return tuple(items)


def _claim_id_for(view: SufficiencyEvaluationView) -> str:
    digest = view.view_cid
    suffix = digest[-24:] if len(digest) >= 24 else digest
    cleaned = re.sub(r"[^a-z0-9_.:/+-]", "", suffix.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"c{cleaned}" if cleaned else "c0"
    return f"claim_{cleaned}"[:128]


def _terminal_for_state(state: str) -> str:
    if state in {
        ContextSufficiencyState.SUFFICIENT.value,
        ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
    }:
        return GovernorTerminalStatus.COMPLETE.value
    if state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value:
        return GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    if state == ContextSufficiencyState.STALE.value:
        return GovernorTerminalStatus.STALE.value
    if state == ContextSufficiencyState.INVALID.value:
        return GovernorTerminalStatus.INVALID.value
    if state == ContextSufficiencyState.EVALUATION_FAILED.value:
        return GovernorTerminalStatus.EVALUATION_FAILED.value
    if state == ContextSufficiencyState.INCONCLUSIVE.value:
        return GovernorTerminalStatus.INCONCLUSIVE.value
    # expansion / frontier still complete as a durable explained claim
    return GovernorTerminalStatus.COMPLETE.value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_context_sufficiency(
    context_pack: ContextPackView | Mapping[str, Any] | SufficiencyEvaluationView,
    repository_state: RepositoryStateView | Mapping[str, Any] | None = None,
    verification_policy: VerificationPolicyView | Mapping[str, Any] | None = None,
    calibration_profile: (
        CalibrationProfileView
        | TaskClassCalibrationProfile
        | Mapping[str, Any]
        | None
    ) = None,
    *,
    claim_id: str | None = None,
) -> ContextSufficiencyClaim:
    """Evaluate pre-execution context sufficiency conservatively.

    Parameters
    ----------
    context_pack:
        A :class:`ContextPackView` (coverage + task/risk/route) **or** a full
        :class:`SufficiencyEvaluationView` when the remaining arguments are
        omitted. Matches the public plan signature when all four arguments
        are supplied.
    repository_state:
        Freshness, opacity, invalidation, conflict, and policy-boundary
        signals bound to the same repository-state CID as the coverage
        manifest.
    verification_policy:
        Planned selected/full/static/type/proof/review checks plus the
        task-class acceptance matrix (or explicit row).
    calibration_profile:
        Empirical complexity / omission / frontier-request signals. Never
        upgrades formal exactness.
    claim_id:
        Optional explicit claim id; otherwise derived deterministically.

    Returns
    -------
    ContextSufficiencyClaim
        Content-addressed claim with a closed sufficiency state, structural
        evidence bases, and blocking reason codes. Identical inputs yield
        identical ``claim_cid``.

    Raises
    ------
    SufficiencyEvaluatorError
        On malformed, unbound, or authority-violating inputs.
    """

    try:
        if isinstance(context_pack, SufficiencyEvaluationView):
            view = context_pack
        elif (
            repository_state is None
            and verification_policy is None
            and isinstance(context_pack, Mapping)
            and "context_pack" in context_pack
            and "repository_state" in context_pack
            and "verification_policy" in context_pack
        ):
            payload = dict(context_pack)
            payload.pop("schema", None)
            payload.pop("view_cid", None)
            view = SufficiencyEvaluationView(**payload)
        else:
            if repository_state is None or verification_policy is None:
                raise SufficiencyEvaluatorError(
                    "repository_state and verification_policy are required "
                    "unless a SufficiencyEvaluationView is supplied"
                )
            view = SufficiencyEvaluationView(
                context_pack=context_pack,
                repository_state=repository_state,
                verification_policy=verification_policy,
                calibration_profile=calibration_profile,
            )

        judgment = _judge(view)
        pack = view.context_pack
        manifest = pack.coverage_manifest
        policy = view.verification_policy

        # Harden: verification-only positive claims are impossible here, but
        # re-assert for defense in depth.
        if judgment.state in {
            ContextSufficiencyState.SUFFICIENT.value,
            ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
        }:
            assert_sufficiency_not_verification_only(
                judgment.state, judgment.evidence_bases
            )

        assumptions = _build_assumptions(view)
        input_cids = [
            view.repository_state.repository_state_cid,
            pack.context_pack_cid,
            manifest.header.verification_bundle_cid,
            manifest.manifest_cid,
            view.view_cid,
        ]
        if manifest.policy_cid is not None:
            input_cids.append(manifest.policy_cid)
        if view.calibration_profile.profile_cid is not None:
            input_cids.append(view.calibration_profile.profile_cid)

        header = _build_header(
            view,
            terminal_status=_terminal_for_state(judgment.state),
            input_cids=input_cids,
            assumptions=assumptions,
        )

        cid = (
            _token(claim_id, "claim_id")
            if claim_id is not None
            else _claim_id_for(view)
        )

        gap_ids = judgment.gap_ids
        if len(gap_ids) > MAX_GAPS:
            gap_ids = gap_ids[:MAX_GAPS]

        metadata = {
            "evaluator_schema": SUFFICIENCY_EVALUATOR_SCHEMA,
            "view_cid": view.view_cid,
            "recommended_action": recommended_decision_action(judgment.state),
            "precedence": list(_STATE_PRECEDENCE),
            "coverage_complete": _coverage_complete(manifest, view.repository_state),
        }
        for key, value in _thaw_structured(view.metadata).items():
            if key not in metadata:
                metadata[key] = value

        claim = ContextSufficiencyClaim(
            header=header,
            claim_id=cid,
            sufficiency_state=judgment.state,
            evidence_bases=judgment.evidence_bases,
            coverage_manifest_cid=manifest.manifest_cid,
            route_tier=pack.route_tier,
            task_class=pack.task_class,
            risk_class=pack.risk_class,
            confidence_bp=judgment.confidence_bp,
            verification_passed=policy.verification_passed,
            blocking_reason_codes=judgment.reasons,
            known_gap_ids=gap_ids,
            policy_cid=manifest.policy_cid,
            notes=judgment.notes if judgment.notes is not None else view.notes,
            metadata=metadata,
        )
        return claim
    except SufficiencyEvaluatorError:
        raise
    except (AuditContractError, PolicyContractError, SemanticGovernorBaseError) as exc:
        raise SufficiencyEvaluatorError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — fail closed on unexpected faults
        raise SufficiencyEvaluatorError(
            f"evaluation_failed: {type(exc).__name__}: {exc}"
        ) from exc


def sufficiency_evaluator_interface_id() -> str:
    """Return the versioned public interface pin for this evaluator."""

    return EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE


def required_check_matrix_fields() -> tuple[str, ...]:
    """Return the closed required-check matrix attribute names."""

    return tuple(require for require, _ in _REQUIRED_CHECK_ATTRS)


def planned_check_fields() -> tuple[str, ...]:
    """Return the closed planned verification-check attribute names."""

    return tuple(planned for _, planned in _REQUIRED_CHECK_ATTRS)


__all__ = [
    "CALIBRATION_PROFILE_VIEW_SCHEMA",
    "CONTEXT_PACK_VIEW_SCHEMA",
    "EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "REPOSITORY_STATE_VIEW_SCHEMA",
    "SUFFICIENCY_EVALUATION_VIEW_SCHEMA",
    "SUFFICIENCY_EVALUATOR_SCHEMA",
    "VERIFICATION_POLICY_VIEW_SCHEMA",
    "CalibrationProfileView",
    "ContextPackView",
    "RepositoryStateView",
    "SufficiencyEvaluationView",
    "SufficiencyEvaluatorError",
    "VerificationPolicyView",
    "evaluate_context_sufficiency",
    "planned_check_fields",
    "recommended_decision_action",
    "required_check_matrix_fields",
    "sufficiency_evaluator_interface_id",
    "sufficiency_state_precedence",
]
