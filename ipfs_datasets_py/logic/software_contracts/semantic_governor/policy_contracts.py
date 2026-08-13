"""Bounded declarative rule DSL and compression-policy contracts (SCG-009).

Defines closed, versioned durable models for rule proposals, evaluation
reports, compression policies, candidates, and promotion receipts.

Authority rules (normative):

* DSL is typed data with an operation allowlist only — no expressions,
  imports, commands, templates, or executable model output.
* Full-suite fallback cannot be disabled by a normal proposal.
* Candidates cannot self-authorize promotion.
* Protected thresholds cannot be reduced without a distinct external
  authorization CID (not the candidate, proposal, evaluation, or policy).
* Canonical identity uses ``software_contracts.content`` only.
* Strict DAG-JSON (no floats); private data and model-written authority fail
  closed.
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    GovernorArtifactHeader,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration_contracts import (
    BASIS_POINTS,
    EvidencePartition,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

DECLARATIVE_RULE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-declarative-rule@1"
)
RULE_PROPOSAL_INTERFACE: Final[str] = "RuleProposal@1"
RULE_PROPOSAL_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-rule-proposal@1"
)
RULE_EVALUATION_REPORT_INTERFACE: Final[str] = "RuleEvaluationReport@1"
RULE_EVALUATION_REPORT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-rule-evaluation-report@1"
)
COMPRESSION_POLICY_INTERFACE: Final[str] = "CompressionPolicy@1"
COMPRESSION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-compression-policy@1"
)
COMPRESSION_POLICY_CANDIDATE_INTERFACE: Final[str] = "CompressionPolicyCandidate@1"
COMPRESSION_POLICY_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-compression-policy-candidate@1"
)
COMPRESSION_POLICY_PROMOTION_RECEIPT_INTERFACE: Final[str] = (
    "CompressionPolicyPromotionReceipt@1"
)
COMPRESSION_POLICY_PROMOTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-compression-policy-promotion-receipt@1"
)
TASK_CLASS_ACCEPTANCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-task-class-acceptance@1"
)
PROTECTED_THRESHOLDS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-protected-thresholds@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_RULES: Final[int] = 1_024
MAX_ACCEPTANCE_ROWS: Final[int] = 512
MAX_BLOCKING_REASONS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)

# Reject executable / template content in declarative string values.
_FORBIDDEN_VALUE_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b__import__\b", re.IGNORECASE),
    re.compile(r"\bimport\b", re.IGNORECASE),
    re.compile(r"\bexec\b", re.IGNORECASE),
    re.compile(r"\beval\b", re.IGNORECASE),
    re.compile(r"\bsubprocess\b", re.IGNORECASE),
    re.compile(r"\bos\.system\b", re.IGNORECASE),
    re.compile(r"\bcompile\b", re.IGNORECASE),
    re.compile(r"\{\{"),
    re.compile(r"\}\}"),
    re.compile(r"\$\{"),
    re.compile(r"<%"),
    re.compile(r"%>"),
    re.compile(r"`"),
    re.compile(r"\$\("),
    re.compile(r"\brequire\s*\(", re.IGNORECASE),
    re.compile(r"\bfrom\s+\S+\s+import\b", re.IGNORECASE),
)


class PolicyContractError(SemanticGovernorBaseError):
    """Raised when a policy/rule contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class RuleCategory(str, Enum):
    """Allowlisted declarative rule categories (plan §9)."""

    DEPENDENCY_EXTRACTION = "dependency_extraction"
    INVALIDATION = "invalidation"
    CAPSULE_COMPLETENESS = "capsule_completeness"
    RAW_SOURCE_INCLUSION = "raw_source_inclusion"
    CONTEXT_RANKING = "context_ranking"
    CONTEXT_PACKING = "context_packing"
    CONTEXT_BUDGET_THRESHOLD = "context_budget_threshold"
    MODEL_ROUTE_THRESHOLD = "model_route_threshold"
    SHADOW_SAMPLING_RATE = "shadow_sampling_rate"
    FULL_SUITE_FALLBACK = "full_suite_fallback"


class RuleOperation(str, Enum):
    """Allowlisted typed operations — no expressions or host commands."""

    SET_TOKEN = "set_token"
    SET_NONNEG_INT = "set_nonneg_int"
    SET_BASIS_POINTS = "set_basis_points"
    SET_BOOL = "set_bool"
    ADD_TOKEN = "add_token"
    REMOVE_TOKEN = "remove_token"
    REQUIRE_INCLUSION = "require_inclusion"
    REQUIRE_INVALIDATION = "require_invalidation"
    SET_ROUTE_TIER = "set_route_tier"
    SET_SAMPLE_RATE = "set_sample_rate"


class EvaluationVerdict(str, Enum):
    """Closed evaluation outcomes for a rule/policy candidate."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


# Target keys that may appear on declarative rules (closed allowlist).
ALLOWED_RULE_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "dependency_extractor",
        "invalidation_mode",
        "capsule_completeness_level",
        "raw_source_mode",
        "context_rank_key",
        "context_pack_strategy",
        "context_budget_tokens",
        "model_route_tier",
        "shadow_sample_rate_bp",
        "full_suite_fallback_enabled",
        "require_selected_tests",
        "require_static_checks",
        "require_type_checks",
        "require_proofs",
        "require_human_review",
        "audit_sample_rate_bp",
        "escalation_threshold_bp",
    }
)

# Target keys whose weakening reduces a protected threshold.
PROTECTED_RULE_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "full_suite_fallback_enabled",
        "shadow_sample_rate_bp",
        "require_selected_tests",
        "require_static_checks",
        "require_type_checks",
        "require_proofs",
        "require_human_review",
        "escalation_threshold_bp",
        "audit_sample_rate_bp",
        "context_budget_tokens",
    }
)

# Protected threshold field names on ProtectedThresholds.
PROTECTED_THRESHOLD_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "min_critical_omission_detection_bp",
        "max_critical_omission_accepted",
        "min_median_context_reduction_bp",
        "max_accepted_regression_bp",
        "min_shadow_sample_rate_bp",
        "require_full_suite_fallback",
        "allow_heuristic_as_exact",
        "allow_assurance_reduction",
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise PolicyContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise PolicyContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise PolicyContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise PolicyContractError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise PolicyContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise PolicyContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise PolicyContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise PolicyContractError(f"{name} must be a nonnegative integer")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise PolicyContractError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise PolicyContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    if value < 0 or value > BASIS_POINTS:
        raise PolicyContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    return value


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


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise PolicyContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise PolicyContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise PolicyContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise PolicyContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise PolicyContractError(f"{name} must not contain duplicates")
    return ordered


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise PolicyContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PolicyContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _header(value: Any, name: str = "header") -> GovernorArtifactHeader:
    if isinstance(value, GovernorArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return GovernorArtifactHeader.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise PolicyContractError(str(exc)) from exc
    raise PolicyContractError(f"{name} must be GovernorArtifactHeader or mapping")


def _reject_executable_text(value: str, name: str) -> str:
    for pattern in _FORBIDDEN_VALUE_RES:
        if pattern.search(value) is not None:
            raise PolicyContractError(
                f"{name} rejects expressions, imports, commands, or templates"
            )
    return value


def _rule_value(value: Any, operation: str, name: str) -> Any:
    """Validate a typed rule value for the allowlisted operation."""

    if operation == RuleOperation.SET_TOKEN.value:
        text = _token(value, name)
        return _reject_executable_text(text, name)
    if operation == RuleOperation.SET_NONNEG_INT.value:
        return _nonneg_int(value, name)
    if operation in {
        RuleOperation.SET_BASIS_POINTS.value,
        RuleOperation.SET_SAMPLE_RATE.value,
    }:
        return _basis_points(value, name)
    if operation == RuleOperation.SET_BOOL.value:
        return _bool(value, name)
    if operation in {
        RuleOperation.ADD_TOKEN.value,
        RuleOperation.REMOVE_TOKEN.value,
        RuleOperation.REQUIRE_INCLUSION.value,
        RuleOperation.REQUIRE_INVALIDATION.value,
        RuleOperation.SET_ROUTE_TIER.value,
    }:
        text = _token(value, name)
        return _reject_executable_text(text, name)
    raise PolicyContractError(f"unsupported rule operation {operation!r}")


# ---------------------------------------------------------------------------
# Protected thresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtectedThresholds:
    """Safety thresholds that may not be weakened without distinct authorization."""

    min_critical_omission_detection_bp: int
    max_critical_omission_accepted: int
    min_median_context_reduction_bp: int
    max_accepted_regression_bp: int
    min_shadow_sample_rate_bp: int
    require_full_suite_fallback: bool
    allow_heuristic_as_exact: bool
    allow_assurance_reduction: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "min_critical_omission_detection_bp",
            "max_critical_omission_accepted",
            "min_median_context_reduction_bp",
            "max_accepted_regression_bp",
            "min_shadow_sample_rate_bp",
            "require_full_suite_fallback",
            "allow_heuristic_as_exact",
            "allow_assurance_reduction",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_critical_omission_detection_bp",
            _basis_points(
                self.min_critical_omission_detection_bp,
                "min_critical_omission_detection_bp",
            ),
        )
        object.__setattr__(
            self,
            "max_critical_omission_accepted",
            _nonneg_int(
                self.max_critical_omission_accepted, "max_critical_omission_accepted"
            ),
        )
        object.__setattr__(
            self,
            "min_median_context_reduction_bp",
            _basis_points(
                self.min_median_context_reduction_bp,
                "min_median_context_reduction_bp",
            ),
        )
        object.__setattr__(
            self,
            "max_accepted_regression_bp",
            _basis_points(
                self.max_accepted_regression_bp, "max_accepted_regression_bp"
            ),
        )
        object.__setattr__(
            self,
            "min_shadow_sample_rate_bp",
            _basis_points(
                self.min_shadow_sample_rate_bp, "min_shadow_sample_rate_bp"
            ),
        )
        object.__setattr__(
            self,
            "require_full_suite_fallback",
            _bool(self.require_full_suite_fallback, "require_full_suite_fallback"),
        )
        allow_exact = _bool(self.allow_heuristic_as_exact, "allow_heuristic_as_exact")
        if allow_exact:
            raise PolicyContractError(
                "allow_heuristic_as_exact must be false; "
                "empirical results cannot set proof classification to exact"
            )
        object.__setattr__(self, "allow_heuristic_as_exact", allow_exact)
        object.__setattr__(
            self,
            "allow_assurance_reduction",
            _bool(self.allow_assurance_reduction, "allow_assurance_reduction"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROTECTED_THRESHOLDS_SCHEMA,
            "min_critical_omission_detection_bp": self.min_critical_omission_detection_bp,
            "max_critical_omission_accepted": self.max_critical_omission_accepted,
            "min_median_context_reduction_bp": self.min_median_context_reduction_bp,
            "max_accepted_regression_bp": self.max_accepted_regression_bp,
            "min_shadow_sample_rate_bp": self.min_shadow_sample_rate_bp,
            "require_full_suite_fallback": self.require_full_suite_fallback,
            "allow_heuristic_as_exact": self.allow_heuristic_as_exact,
            "allow_assurance_reduction": self.allow_assurance_reduction,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProtectedThresholds":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != PROTECTED_THRESHOLDS_SCHEMA:
            raise PolicyContractError("unsupported ProtectedThresholds schema version")
        return cls(
            min_critical_omission_detection_bp=payload[
                "min_critical_omission_detection_bp"
            ],
            max_critical_omission_accepted=payload["max_critical_omission_accepted"],
            min_median_context_reduction_bp=payload[
                "min_median_context_reduction_bp"
            ],
            max_accepted_regression_bp=payload["max_accepted_regression_bp"],
            min_shadow_sample_rate_bp=payload["min_shadow_sample_rate_bp"],
            require_full_suite_fallback=payload["require_full_suite_fallback"],
            allow_heuristic_as_exact=payload["allow_heuristic_as_exact"],
            allow_assurance_reduction=payload["allow_assurance_reduction"],
        )

    @classmethod
    def default_production(cls) -> "ProtectedThresholds":
        """Conservative production defaults from plan targets."""

        return cls(
            min_critical_omission_detection_bp=9_500,
            max_critical_omission_accepted=0,
            min_median_context_reduction_bp=5_000,
            max_accepted_regression_bp=0,
            min_shadow_sample_rate_bp=100,
            require_full_suite_fallback=True,
            allow_heuristic_as_exact=False,
            allow_assurance_reduction=False,
        )


def _normalize_protected_thresholds(
    value: ProtectedThresholds | Mapping[str, Any],
    name: str = "protected_thresholds",
) -> ProtectedThresholds:
    if isinstance(value, ProtectedThresholds):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return ProtectedThresholds.from_dict(value)
        return ProtectedThresholds(
            min_critical_omission_detection_bp=value.get(
                "min_critical_omission_detection_bp", 9_500
            ),
            max_critical_omission_accepted=value.get(
                "max_critical_omission_accepted", 0
            ),
            min_median_context_reduction_bp=value.get(
                "min_median_context_reduction_bp", 5_000
            ),
            max_accepted_regression_bp=value.get("max_accepted_regression_bp", 0),
            min_shadow_sample_rate_bp=value.get("min_shadow_sample_rate_bp", 100),
            require_full_suite_fallback=value.get("require_full_suite_fallback", True),
            allow_heuristic_as_exact=value.get("allow_heuristic_as_exact", False),
            allow_assurance_reduction=value.get("allow_assurance_reduction", False),
        )
    raise PolicyContractError(f"{name} must be ProtectedThresholds or mapping")


def protected_threshold_reductions(
    baseline: ProtectedThresholds | Mapping[str, Any],
    proposed: ProtectedThresholds | Mapping[str, Any],
) -> tuple[str, ...]:
    """Return protected fields weakened by ``proposed`` relative to ``baseline``."""

    base = _normalize_protected_thresholds(baseline, "baseline")
    prop = _normalize_protected_thresholds(proposed, "proposed")
    reduced: list[str] = []
    # Higher mins are stricter.
    if prop.min_critical_omission_detection_bp < base.min_critical_omission_detection_bp:
        reduced.append("min_critical_omission_detection_bp")
    if prop.min_median_context_reduction_bp < base.min_median_context_reduction_bp:
        reduced.append("min_median_context_reduction_bp")
    if prop.min_shadow_sample_rate_bp < base.min_shadow_sample_rate_bp:
        reduced.append("min_shadow_sample_rate_bp")
    # Lower maxes are stricter.
    if prop.max_critical_omission_accepted > base.max_critical_omission_accepted:
        reduced.append("max_critical_omission_accepted")
    if prop.max_accepted_regression_bp > base.max_accepted_regression_bp:
        reduced.append("max_accepted_regression_bp")
    # True requirements are stricter.
    if base.require_full_suite_fallback and not prop.require_full_suite_fallback:
        reduced.append("require_full_suite_fallback")
    # False flags are stricter for dangerous allowances.
    if (not base.allow_heuristic_as_exact) and prop.allow_heuristic_as_exact:
        reduced.append("allow_heuristic_as_exact")
    if (not base.allow_assurance_reduction) and prop.allow_assurance_reduction:
        reduced.append("allow_assurance_reduction")
    return tuple(sorted(reduced))


def assert_protected_threshold_change_authorized(
    baseline: ProtectedThresholds | Mapping[str, Any],
    proposed: ProtectedThresholds | Mapping[str, Any],
    authorization_cid: str | None,
    *,
    forbidden_self_cids: Iterable[str] = (),
) -> None:
    """Reject unprotected weakening of protected thresholds.

    Reducing a protected threshold requires a distinct external authorization
    CID that is not the candidate, proposal, evaluation report, or policy.
    """

    reductions = protected_threshold_reductions(baseline, proposed)
    if not reductions:
        return
    if authorization_cid is None:
        raise PolicyContractError(
            "cannot reduce protected thresholds without distinct authorization; "
            f"reduced={list(reductions)}"
        )
    auth = _cid(authorization_cid, "authorization_cid")
    forbidden = {_cid(item, "forbidden_self_cids") for item in forbidden_self_cids}
    if auth in forbidden:
        raise PolicyContractError(
            "candidates cannot self-authorize or reduce protected thresholds "
            "without distinct authorization"
        )


# ---------------------------------------------------------------------------
# Task-class acceptance matrix row
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskClassAcceptanceRequirements:
    """Closed acceptance requirements for one task/risk class."""

    task_class: str
    risk_class: str
    require_selected_tests: bool
    require_full_suite_fallback: bool
    require_static_checks: bool
    require_type_checks: bool
    require_proofs: bool
    require_human_review: bool

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "task_class",
            "risk_class",
            "require_selected_tests",
            "require_full_suite_fallback",
            "require_static_checks",
            "require_type_checks",
            "require_proofs",
            "require_human_review",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        for name in (
            "require_selected_tests",
            "require_full_suite_fallback",
            "require_static_checks",
            "require_type_checks",
            "require_proofs",
            "require_human_review",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TASK_CLASS_ACCEPTANCE_SCHEMA,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "require_selected_tests": self.require_selected_tests,
            "require_full_suite_fallback": self.require_full_suite_fallback,
            "require_static_checks": self.require_static_checks,
            "require_type_checks": self.require_type_checks,
            "require_proofs": self.require_proofs,
            "require_human_review": self.require_human_review,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaskClassAcceptanceRequirements":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != TASK_CLASS_ACCEPTANCE_SCHEMA:
            raise PolicyContractError(
                "unsupported TaskClassAcceptanceRequirements schema version"
            )
        return cls(
            task_class=payload["task_class"],
            risk_class=payload["risk_class"],
            require_selected_tests=payload["require_selected_tests"],
            require_full_suite_fallback=payload["require_full_suite_fallback"],
            require_static_checks=payload["require_static_checks"],
            require_type_checks=payload["require_type_checks"],
            require_proofs=payload["require_proofs"],
            require_human_review=payload["require_human_review"],
        )


def _normalize_acceptance_row(
    value: TaskClassAcceptanceRequirements | Mapping[str, Any],
) -> TaskClassAcceptanceRequirements:
    if isinstance(value, TaskClassAcceptanceRequirements):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return TaskClassAcceptanceRequirements.from_dict(value)
        return TaskClassAcceptanceRequirements(
            task_class=value.get("task_class", ""),
            risk_class=value.get("risk_class", ""),
            require_selected_tests=value.get("require_selected_tests", True),
            require_full_suite_fallback=value.get("require_full_suite_fallback", True),
            require_static_checks=value.get("require_static_checks", True),
            require_type_checks=value.get("require_type_checks", True),
            require_proofs=value.get("require_proofs", False),
            require_human_review=value.get("require_human_review", False),
        )
    raise PolicyContractError(
        "acceptance matrix entries must be TaskClassAcceptanceRequirements or mapping"
    )


def _normalize_acceptance_matrix(
    values: Sequence[TaskClassAcceptanceRequirements | Mapping[str, Any]],
) -> tuple[TaskClassAcceptanceRequirements, ...]:
    if not isinstance(values, (list, tuple)):
        raise PolicyContractError("task_class_acceptance_matrix must be a list")
    if len(values) > MAX_ACCEPTANCE_ROWS:
        raise PolicyContractError("task_class_acceptance_matrix exceeds maximum length")
    rows = [_normalize_acceptance_row(item) for item in values]
    keys = [(row.task_class, row.risk_class) for row in rows]
    if len(keys) != len(set(keys)):
        raise PolicyContractError(
            "task_class_acceptance_matrix must not contain duplicate task/risk pairs"
        )
    return tuple(sorted(rows, key=lambda row: (row.task_class, row.risk_class)))


# ---------------------------------------------------------------------------
# Declarative rule (bounded DSL atom)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeclarativeRule:
    """One allowlisted typed rule atom — never executable model text."""

    rule_id: str
    category: RuleCategory | str
    operation: RuleOperation | str
    target_key: str
    value: Any
    scope_token: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "rule_id",
            "category",
            "operation",
            "target_key",
            "value",
            "scope_token",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _token(self.rule_id, "rule_id"))
        category = _enum(self.category, RuleCategory, "category")
        operation = _enum(self.operation, RuleOperation, "operation")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "operation", operation)
        target = _token(self.target_key, "target_key")
        if target not in ALLOWED_RULE_TARGET_KEYS:
            raise PolicyContractError(
                f"target_key {target!r} is not in the declarative rule allowlist"
            )
        object.__setattr__(self, "target_key", target)
        object.__setattr__(
            self, "value", _rule_value(self.value, operation, "value")
        )
        if self.scope_token is not None:
            object.__setattr__(
                self, "scope_token", _token(self.scope_token, "scope_token")
            )
        # Full-suite fallback cannot be disabled by a normal proposal rule.
        if (
            category == RuleCategory.FULL_SUITE_FALLBACK.value
            or target == "full_suite_fallback_enabled"
        ):
            if operation == RuleOperation.SET_BOOL.value and self.value is False:
                raise PolicyContractError(
                    "full-suite fallback cannot be disabled by declarative rule"
                )
        # Category/target coherence for fallback.
        if category == RuleCategory.FULL_SUITE_FALLBACK.value and target not in {
            "full_suite_fallback_enabled",
        }:
            raise PolicyContractError(
                "full_suite_fallback category requires full_suite_fallback_enabled target"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DECLARATIVE_RULE_SCHEMA,
            "rule_id": self.rule_id,
            "category": self.category,
            "operation": self.operation,
            "target_key": self.target_key,
            "value": self.value,
            "scope_token": self.scope_token,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeclarativeRule":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != DECLARATIVE_RULE_SCHEMA:
            raise PolicyContractError("unsupported DeclarativeRule schema version")
        return cls(
            rule_id=payload["rule_id"],
            category=payload["category"],
            operation=payload["operation"],
            target_key=payload["target_key"],
            value=payload["value"],
            scope_token=payload["scope_token"],
        )

    def touches_protected_threshold(self) -> bool:
        """Return True when this rule can weaken a protected threshold."""

        return self.target_key in PROTECTED_RULE_TARGET_KEYS


def _normalize_rule(value: DeclarativeRule | Mapping[str, Any]) -> DeclarativeRule:
    if isinstance(value, DeclarativeRule):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return DeclarativeRule.from_dict(value)
        return DeclarativeRule(
            rule_id=value.get("rule_id", ""),
            category=value.get("category", ""),
            operation=value.get("operation", ""),
            target_key=value.get("target_key", ""),
            value=value.get("value"),
            scope_token=value.get("scope_token"),
        )
    raise PolicyContractError("rules entries must be DeclarativeRule or mapping")


def _normalize_rules(
    values: Sequence[DeclarativeRule | Mapping[str, Any]],
) -> tuple[DeclarativeRule, ...]:
    if not isinstance(values, (list, tuple)):
        raise PolicyContractError("rules must be a list")
    if len(values) > MAX_RULES:
        raise PolicyContractError("rules exceeds maximum length")
    rules = [_normalize_rule(item) for item in values]
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise PolicyContractError("rules must not contain duplicate rule_id values")
    return tuple(sorted(rules, key=lambda rule: rule.rule_id))


def validate_rule_dsl(rules: Sequence[DeclarativeRule | Mapping[str, Any]]) -> tuple[DeclarativeRule, ...]:
    """Validate a bounded declarative rule list and return normalized rules."""

    return _normalize_rules(rules)


# ---------------------------------------------------------------------------
# RuleProposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleProposal:
    """Evidence-bound proposal of allowlisted declarative rules."""

    header: GovernorArtifactHeader
    proposal_id: str
    current_policy_version: str
    current_policy_cid: str
    proposed_rules: Sequence[DeclarativeRule]
    supporting_audit_cids: Sequence[str]
    benefit_statement: str
    safety_impact: str
    scope_token: str
    benchmark_cid: str
    rollback_policy_cid: str
    calibration_profile_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "proposal_id",
            "current_policy_version",
            "current_policy_cid",
            "proposed_rules",
            "supporting_audit_cids",
            "benefit_statement",
            "safety_impact",
            "scope_token",
            "benchmark_cid",
            "rollback_policy_cid",
            "calibration_profile_cids",
            "notes",
            "metadata",
            "proposal_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "rule_proposal":
            raise PolicyContractError("header.artifact_kind must be rule_proposal")
        object.__setattr__(self, "proposal_id", _token(self.proposal_id, "proposal_id"))
        object.__setattr__(
            self,
            "current_policy_version",
            _version(self.current_policy_version, "current_policy_version"),
        )
        object.__setattr__(
            self, "current_policy_cid", _cid(self.current_policy_cid, "current_policy_cid")
        )
        rules = _normalize_rules(list(self.proposed_rules))
        if not rules:
            raise PolicyContractError("proposed_rules must not be empty")
        object.__setattr__(self, "proposed_rules", rules)
        object.__setattr__(
            self,
            "supporting_audit_cids",
            _unique_sorted_cids(list(self.supporting_audit_cids), "supporting_audit_cids"),
        )
        object.__setattr__(
            self,
            "benefit_statement",
            _reject_executable_text(
                _text(self.benefit_statement, "benefit_statement"), "benefit_statement"
            ),
        )
        object.__setattr__(
            self,
            "safety_impact",
            _reject_executable_text(
                _text(self.safety_impact, "safety_impact"), "safety_impact"
            ),
        )
        object.__setattr__(self, "scope_token", _token(self.scope_token, "scope_token"))
        object.__setattr__(self, "benchmark_cid", _cid(self.benchmark_cid, "benchmark_cid"))
        object.__setattr__(
            self, "rollback_policy_cid", _cid(self.rollback_policy_cid, "rollback_policy_cid")
        )
        object.__setattr__(
            self,
            "calibration_profile_cids",
            _unique_sorted_cids(
                list(self.calibration_profile_cids), "calibration_profile_cids"
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_SCHEMA,
            "interface_id": RULE_PROPOSAL_INTERFACE,
            "header": self.header.identity_payload(),
            "proposal_id": self.proposal_id,
            "current_policy_version": self.current_policy_version,
            "current_policy_cid": self.current_policy_cid,
            "proposed_rules": [rule.identity_payload() for rule in self.proposed_rules],
            "supporting_audit_cids": list(self.supporting_audit_cids),
            "benefit_statement": self.benefit_statement,
            "safety_impact": self.safety_impact,
            "scope_token": self.scope_token,
            "benchmark_cid": self.benchmark_cid,
            "rollback_policy_cid": self.rollback_policy_cid,
            "calibration_profile_cids": list(self.calibration_profile_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def proposal_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_SCHEMA,
            "interface_id": RULE_PROPOSAL_INTERFACE,
            "header": self.header.to_dict(),
            "proposal_id": self.proposal_id,
            "current_policy_version": self.current_policy_version,
            "current_policy_cid": self.current_policy_cid,
            "proposed_rules": [rule.to_dict() for rule in self.proposed_rules],
            "supporting_audit_cids": list(self.supporting_audit_cids),
            "benefit_statement": self.benefit_statement,
            "safety_impact": self.safety_impact,
            "scope_token": self.scope_token,
            "benchmark_cid": self.benchmark_cid,
            "rollback_policy_cid": self.rollback_policy_cid,
            "calibration_profile_cids": list(self.calibration_profile_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "proposal_cid": self.proposal_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleProposal":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("proposal_cid")
        if payload.pop("schema") != RULE_PROPOSAL_SCHEMA:
            raise PolicyContractError("unsupported RuleProposal schema version")
        if payload.pop("interface_id") != RULE_PROPOSAL_INTERFACE:
            raise PolicyContractError("unsupported RuleProposal interface_id")
        result = cls(
            header=payload["header"],
            proposal_id=payload["proposal_id"],
            current_policy_version=payload["current_policy_version"],
            current_policy_cid=payload["current_policy_cid"],
            proposed_rules=payload["proposed_rules"],
            supporting_audit_cids=payload["supporting_audit_cids"],
            benefit_statement=payload["benefit_statement"],
            safety_impact=payload["safety_impact"],
            scope_token=payload["scope_token"],
            benchmark_cid=payload["benchmark_cid"],
            rollback_policy_cid=payload["rollback_policy_cid"],
            calibration_profile_cids=payload["calibration_profile_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.proposal_cid:
            raise PolicyContractError("RuleProposal proposal_cid does not verify")
        return result


# ---------------------------------------------------------------------------
# RuleEvaluationReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleEvaluationReport:
    """Held-out evaluation of a policy/rule candidate (no mutation)."""

    header: GovernorArtifactHeader
    report_id: str
    candidate_cid: str
    held_out_benchmark_cid: str
    baseline_policy_cid: str
    partition: EvidencePartition | str
    verdict: EvaluationVerdict | str
    critical_omission_detection_bp: int
    stale_rejection_rate_bp: int
    accepted_regression_bp: int
    high_risk_assurance_reduced: bool
    declared_thresholds_applied: bool
    blocking_reasons: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "report_id",
            "candidate_cid",
            "held_out_benchmark_cid",
            "baseline_policy_cid",
            "partition",
            "verdict",
            "critical_omission_detection_bp",
            "stale_rejection_rate_bp",
            "accepted_regression_bp",
            "high_risk_assurance_reduced",
            "declared_thresholds_applied",
            "blocking_reasons",
            "notes",
            "metadata",
            "report_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "rule_evaluation_report":
            raise PolicyContractError(
                "header.artifact_kind must be rule_evaluation_report"
            )
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid"))
        object.__setattr__(
            self,
            "held_out_benchmark_cid",
            _cid(self.held_out_benchmark_cid, "held_out_benchmark_cid"),
        )
        object.__setattr__(
            self, "baseline_policy_cid", _cid(self.baseline_policy_cid, "baseline_policy_cid")
        )
        partition = _enum(self.partition, EvidencePartition, "partition")
        if partition != EvidencePartition.HELD_OUT.value:
            raise PolicyContractError(
                "rule evaluation partition must be held_out and disjoint from "
                "calibration/development"
            )
        object.__setattr__(self, "partition", partition)
        object.__setattr__(
            self, "verdict", _enum(self.verdict, EvaluationVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "critical_omission_detection_bp",
            _basis_points(
                self.critical_omission_detection_bp, "critical_omission_detection_bp"
            ),
        )
        object.__setattr__(
            self,
            "stale_rejection_rate_bp",
            _basis_points(self.stale_rejection_rate_bp, "stale_rejection_rate_bp"),
        )
        object.__setattr__(
            self,
            "accepted_regression_bp",
            _basis_points(self.accepted_regression_bp, "accepted_regression_bp"),
        )
        object.__setattr__(
            self,
            "high_risk_assurance_reduced",
            _bool(self.high_risk_assurance_reduced, "high_risk_assurance_reduced"),
        )
        object.__setattr__(
            self,
            "declared_thresholds_applied",
            _bool(self.declared_thresholds_applied, "declared_thresholds_applied"),
        )
        if not isinstance(self.blocking_reasons, (list, tuple)):
            raise PolicyContractError("blocking_reasons must be a list")
        reasons = tuple(
            _reject_executable_text(_text(item, "blocking_reasons"), "blocking_reasons")
            for item in self.blocking_reasons
        )
        if len(reasons) > MAX_BLOCKING_REASONS:
            raise PolicyContractError("blocking_reasons exceeds maximum length")
        object.__setattr__(self, "blocking_reasons", reasons)
        if (
            self.verdict == EvaluationVerdict.PASS.value
            and self.high_risk_assurance_reduced
        ):
            raise PolicyContractError(
                "pass verdict cannot claim high_risk_assurance_reduced"
            )
        if self.verdict == EvaluationVerdict.PASS.value and not self.declared_thresholds_applied:
            raise PolicyContractError(
                "pass verdict requires declared_thresholds_applied"
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RULE_EVALUATION_REPORT_SCHEMA,
            "interface_id": RULE_EVALUATION_REPORT_INTERFACE,
            "header": self.header.identity_payload(),
            "report_id": self.report_id,
            "candidate_cid": self.candidate_cid,
            "held_out_benchmark_cid": self.held_out_benchmark_cid,
            "baseline_policy_cid": self.baseline_policy_cid,
            "partition": self.partition,
            "verdict": self.verdict,
            "critical_omission_detection_bp": self.critical_omission_detection_bp,
            "stale_rejection_rate_bp": self.stale_rejection_rate_bp,
            "accepted_regression_bp": self.accepted_regression_bp,
            "high_risk_assurance_reduced": self.high_risk_assurance_reduced,
            "declared_thresholds_applied": self.declared_thresholds_applied,
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def report_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_EVALUATION_REPORT_SCHEMA,
            "interface_id": RULE_EVALUATION_REPORT_INTERFACE,
            "header": self.header.to_dict(),
            "report_id": self.report_id,
            "candidate_cid": self.candidate_cid,
            "held_out_benchmark_cid": self.held_out_benchmark_cid,
            "baseline_policy_cid": self.baseline_policy_cid,
            "partition": self.partition,
            "verdict": self.verdict,
            "critical_omission_detection_bp": self.critical_omission_detection_bp,
            "stale_rejection_rate_bp": self.stale_rejection_rate_bp,
            "accepted_regression_bp": self.accepted_regression_bp,
            "high_risk_assurance_reduced": self.high_risk_assurance_reduced,
            "declared_thresholds_applied": self.declared_thresholds_applied,
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "report_cid": self.report_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleEvaluationReport":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("report_cid")
        if payload.pop("schema") != RULE_EVALUATION_REPORT_SCHEMA:
            raise PolicyContractError(
                "unsupported RuleEvaluationReport schema version"
            )
        if payload.pop("interface_id") != RULE_EVALUATION_REPORT_INTERFACE:
            raise PolicyContractError(
                "unsupported RuleEvaluationReport interface_id"
            )
        result = cls(
            header=payload["header"],
            report_id=payload["report_id"],
            candidate_cid=payload["candidate_cid"],
            held_out_benchmark_cid=payload["held_out_benchmark_cid"],
            baseline_policy_cid=payload["baseline_policy_cid"],
            partition=payload["partition"],
            verdict=payload["verdict"],
            critical_omission_detection_bp=payload["critical_omission_detection_bp"],
            stale_rejection_rate_bp=payload["stale_rejection_rate_bp"],
            accepted_regression_bp=payload["accepted_regression_bp"],
            high_risk_assurance_reduced=payload["high_risk_assurance_reduced"],
            declared_thresholds_applied=payload["declared_thresholds_applied"],
            blocking_reasons=payload["blocking_reasons"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.report_cid:
            raise PolicyContractError(
                "RuleEvaluationReport report_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# CompressionPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompressionPolicy:
    """Versioned compression policy with acceptance matrix and protected thresholds."""

    header: GovernorArtifactHeader
    policy_id: str
    policy_version: str
    task_class_acceptance_matrix: Sequence[TaskClassAcceptanceRequirements]
    protected_thresholds: ProtectedThresholds
    rules: Sequence[DeclarativeRule] = ()
    calibration_profile_cids: Sequence[str] = ()
    parent_policy_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "policy_id",
            "policy_version",
            "task_class_acceptance_matrix",
            "protected_thresholds",
            "rules",
            "calibration_profile_cids",
            "parent_policy_cid",
            "notes",
            "metadata",
            "policy_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "compression_policy":
            raise PolicyContractError(
                "header.artifact_kind must be compression_policy"
            )
        object.__setattr__(self, "policy_id", _token(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_version", _version(self.policy_version, "policy_version")
        )
        matrix = _normalize_acceptance_matrix(list(self.task_class_acceptance_matrix))
        if not matrix:
            raise PolicyContractError(
                "task_class_acceptance_matrix must not be empty; "
                "absent/unknown mappings fail closed"
            )
        object.__setattr__(self, "task_class_acceptance_matrix", matrix)
        thresholds = _normalize_protected_thresholds(self.protected_thresholds)
        if not thresholds.require_full_suite_fallback:
            raise PolicyContractError(
                "compression policy require_full_suite_fallback must be true"
            )
        object.__setattr__(self, "protected_thresholds", thresholds)
        object.__setattr__(self, "rules", _normalize_rules(list(self.rules)))
        object.__setattr__(
            self,
            "calibration_profile_cids",
            _unique_sorted_cids(
                list(self.calibration_profile_cids), "calibration_profile_cids"
            ),
        )
        object.__setattr__(
            self, "parent_policy_cid", _optional_cid(self.parent_policy_cid, "parent_policy_cid")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_SCHEMA,
            "interface_id": COMPRESSION_POLICY_INTERFACE,
            "header": self.header.identity_payload(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "task_class_acceptance_matrix": [
                row.identity_payload() for row in self.task_class_acceptance_matrix
            ],
            "protected_thresholds": self.protected_thresholds.identity_payload(),
            "rules": [rule.identity_payload() for rule in self.rules],
            "calibration_profile_cids": list(self.calibration_profile_cids),
            "parent_policy_cid": self.parent_policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_SCHEMA,
            "interface_id": COMPRESSION_POLICY_INTERFACE,
            "header": self.header.to_dict(),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "task_class_acceptance_matrix": [
                row.to_dict() for row in self.task_class_acceptance_matrix
            ],
            "protected_thresholds": self.protected_thresholds.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
            "calibration_profile_cids": list(self.calibration_profile_cids),
            "parent_policy_cid": self.parent_policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "policy_cid": self.policy_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompressionPolicy":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("policy_cid")
        if payload.pop("schema") != COMPRESSION_POLICY_SCHEMA:
            raise PolicyContractError("unsupported CompressionPolicy schema version")
        if payload.pop("interface_id") != COMPRESSION_POLICY_INTERFACE:
            raise PolicyContractError("unsupported CompressionPolicy interface_id")
        result = cls(
            header=payload["header"],
            policy_id=payload["policy_id"],
            policy_version=payload["policy_version"],
            task_class_acceptance_matrix=payload["task_class_acceptance_matrix"],
            protected_thresholds=payload["protected_thresholds"],
            rules=payload["rules"],
            calibration_profile_cids=payload["calibration_profile_cids"],
            parent_policy_cid=payload["parent_policy_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.policy_cid:
            raise PolicyContractError("CompressionPolicy policy_cid does not verify")
        return result

    def acceptance_for(
        self, task_class: str, risk_class: str
    ) -> TaskClassAcceptanceRequirements | None:
        """Return the closed acceptance row, or None (fail closed at call site)."""

        task = _token(task_class, "task_class")
        risk = _token(risk_class, "risk_class")
        for row in self.task_class_acceptance_matrix:
            if row.task_class == task and row.risk_class == risk:
                return row
        return None


# ---------------------------------------------------------------------------
# CompressionPolicyCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompressionPolicyCandidate:
    """Policy candidate for held-out evaluation — cannot self-authorize."""

    header: GovernorArtifactHeader
    candidate_id: str
    base_policy_cid: str
    base_policy_version: str
    proposal_cid: str
    proposed_policy_cid: str
    proposed_protected_thresholds: ProtectedThresholds
    baseline_protected_thresholds: ProtectedThresholds
    evaluation_partition: EvidencePartition | str
    # Optional external authorization for protected-threshold reductions only.
    # Must be distinct from candidate/proposal/policy/evaluation identities.
    external_authorization_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "base_policy_cid",
            "base_policy_version",
            "proposal_cid",
            "proposed_policy_cid",
            "proposed_protected_thresholds",
            "baseline_protected_thresholds",
            "evaluation_partition",
            "external_authorization_cid",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "compression_policy_candidate":
            raise PolicyContractError(
                "header.artifact_kind must be compression_policy_candidate"
            )
        object.__setattr__(self, "candidate_id", _token(self.candidate_id, "candidate_id"))
        object.__setattr__(
            self, "base_policy_cid", _cid(self.base_policy_cid, "base_policy_cid")
        )
        object.__setattr__(
            self,
            "base_policy_version",
            _version(self.base_policy_version, "base_policy_version"),
        )
        object.__setattr__(self, "proposal_cid", _cid(self.proposal_cid, "proposal_cid"))
        object.__setattr__(
            self, "proposed_policy_cid", _cid(self.proposed_policy_cid, "proposed_policy_cid")
        )
        proposed = _normalize_protected_thresholds(
            self.proposed_protected_thresholds, "proposed_protected_thresholds"
        )
        baseline = _normalize_protected_thresholds(
            self.baseline_protected_thresholds, "baseline_protected_thresholds"
        )
        object.__setattr__(self, "proposed_protected_thresholds", proposed)
        object.__setattr__(self, "baseline_protected_thresholds", baseline)
        partition = _enum(
            self.evaluation_partition, EvidencePartition, "evaluation_partition"
        )
        if partition != EvidencePartition.HELD_OUT.value:
            raise PolicyContractError(
                "candidate evaluation_partition must be held_out"
            )
        object.__setattr__(self, "evaluation_partition", partition)
        auth = _optional_cid(
            self.external_authorization_cid, "external_authorization_cid"
        )
        object.__setattr__(self, "external_authorization_cid", auth)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Protected-threshold reductions require distinct authorization.
        # Forbidden self identities exclude the candidate's own future CID,
        # proposal, base/proposed policies. Evaluation report is unknown here.
        provisional_cid = cid_for_structured(self._identity_payload_body())
        forbidden = {
            provisional_cid,
            self.proposal_cid,
            self.base_policy_cid,
            self.proposed_policy_cid,
        }
        assert_protected_threshold_change_authorized(
            baseline,
            proposed,
            auth,
            forbidden_self_cids=forbidden,
        )
        # Candidate must never carry self-referential authorization.
        if auth is not None and auth == provisional_cid:
            raise PolicyContractError(
                "candidates cannot self-authorize"
            )

    def _identity_payload_body(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_CANDIDATE_SCHEMA,
            "interface_id": COMPRESSION_POLICY_CANDIDATE_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "base_policy_cid": self.base_policy_cid,
            "base_policy_version": self.base_policy_version,
            "proposal_cid": self.proposal_cid,
            "proposed_policy_cid": self.proposed_policy_cid,
            "proposed_protected_thresholds": (
                self.proposed_protected_thresholds.identity_payload()
            ),
            "baseline_protected_thresholds": (
                self.baseline_protected_thresholds.identity_payload()
            ),
            "evaluation_partition": self.evaluation_partition,
            "external_authorization_cid": self.external_authorization_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    def identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_body()

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_CANDIDATE_SCHEMA,
            "interface_id": COMPRESSION_POLICY_CANDIDATE_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "base_policy_cid": self.base_policy_cid,
            "base_policy_version": self.base_policy_version,
            "proposal_cid": self.proposal_cid,
            "proposed_policy_cid": self.proposed_policy_cid,
            "proposed_protected_thresholds": (
                self.proposed_protected_thresholds.to_dict()
            ),
            "baseline_protected_thresholds": (
                self.baseline_protected_thresholds.to_dict()
            ),
            "evaluation_partition": self.evaluation_partition,
            "external_authorization_cid": self.external_authorization_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompressionPolicyCandidate":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != COMPRESSION_POLICY_CANDIDATE_SCHEMA:
            raise PolicyContractError(
                "unsupported CompressionPolicyCandidate schema version"
            )
        if payload.pop("interface_id") != COMPRESSION_POLICY_CANDIDATE_INTERFACE:
            raise PolicyContractError(
                "unsupported CompressionPolicyCandidate interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            base_policy_cid=payload["base_policy_cid"],
            base_policy_version=payload["base_policy_version"],
            proposal_cid=payload["proposal_cid"],
            proposed_policy_cid=payload["proposed_policy_cid"],
            proposed_protected_thresholds=payload["proposed_protected_thresholds"],
            baseline_protected_thresholds=payload["baseline_protected_thresholds"],
            evaluation_partition=payload["evaluation_partition"],
            external_authorization_cid=payload["external_authorization_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise PolicyContractError(
                "CompressionPolicyCandidate candidate_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# CompressionPolicyPromotionReceipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompressionPolicyPromotionReceipt:
    """Neutral promotion receipt payload (datasets-owned; kit stores envelopes).

    Authorization must be a distinct external CID — not the candidate,
    evaluation report, proposal, or promoted policy itself.
    """

    header: GovernorArtifactHeader
    receipt_id: str
    candidate_cid: str
    evaluation_report_cid: str
    authorization_cid: str
    proposal_cid: str
    previous_policy_cid: str
    previous_policy_version: str
    promoted_policy_cid: str
    promoted_policy_version: str
    rollback_policy_cid: str
    cas_expected_version: str
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "receipt_id",
            "candidate_cid",
            "evaluation_report_cid",
            "authorization_cid",
            "proposal_cid",
            "previous_policy_cid",
            "previous_policy_version",
            "promoted_policy_cid",
            "promoted_policy_version",
            "rollback_policy_cid",
            "cas_expected_version",
            "notes",
            "metadata",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "compression_policy_promotion_receipt":
            raise PolicyContractError(
                "header.artifact_kind must be compression_policy_promotion_receipt"
            )
        object.__setattr__(self, "receipt_id", _token(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid"))
        object.__setattr__(
            self,
            "evaluation_report_cid",
            _cid(self.evaluation_report_cid, "evaluation_report_cid"),
        )
        object.__setattr__(
            self, "authorization_cid", _cid(self.authorization_cid, "authorization_cid")
        )
        object.__setattr__(self, "proposal_cid", _cid(self.proposal_cid, "proposal_cid"))
        object.__setattr__(
            self, "previous_policy_cid", _cid(self.previous_policy_cid, "previous_policy_cid")
        )
        object.__setattr__(
            self,
            "previous_policy_version",
            _version(self.previous_policy_version, "previous_policy_version"),
        )
        object.__setattr__(
            self, "promoted_policy_cid", _cid(self.promoted_policy_cid, "promoted_policy_cid")
        )
        object.__setattr__(
            self,
            "promoted_policy_version",
            _version(self.promoted_policy_version, "promoted_policy_version"),
        )
        object.__setattr__(
            self, "rollback_policy_cid", _cid(self.rollback_policy_cid, "rollback_policy_cid")
        )
        object.__setattr__(
            self,
            "cas_expected_version",
            _version(self.cas_expected_version, "cas_expected_version"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Self-authorization is always rejected.
        forbidden = {
            self.candidate_cid,
            self.evaluation_report_cid,
            self.proposal_cid,
            self.previous_policy_cid,
            self.promoted_policy_cid,
            self.rollback_policy_cid,
        }
        if self.authorization_cid in forbidden:
            raise PolicyContractError(
                "candidates cannot self-authorize; authorization_cid must be a "
                "distinct external authorization"
            )
        # Provisional receipt identity also cannot authorize itself.
        provisional = cid_for_structured(self._identity_payload_body())
        if self.authorization_cid == provisional:
            raise PolicyContractError(
                "promotion receipt cannot self-authorize"
            )

    def _identity_payload_body(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_PROMOTION_RECEIPT_SCHEMA,
            "interface_id": COMPRESSION_POLICY_PROMOTION_RECEIPT_INTERFACE,
            "header": self.header.identity_payload(),
            "receipt_id": self.receipt_id,
            "candidate_cid": self.candidate_cid,
            "evaluation_report_cid": self.evaluation_report_cid,
            "authorization_cid": self.authorization_cid,
            "proposal_cid": self.proposal_cid,
            "previous_policy_cid": self.previous_policy_cid,
            "previous_policy_version": self.previous_policy_version,
            "promoted_policy_cid": self.promoted_policy_cid,
            "promoted_policy_version": self.promoted_policy_version,
            "rollback_policy_cid": self.rollback_policy_cid,
            "cas_expected_version": self.cas_expected_version,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    def identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_body()

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_POLICY_PROMOTION_RECEIPT_SCHEMA,
            "interface_id": COMPRESSION_POLICY_PROMOTION_RECEIPT_INTERFACE,
            "header": self.header.to_dict(),
            "receipt_id": self.receipt_id,
            "candidate_cid": self.candidate_cid,
            "evaluation_report_cid": self.evaluation_report_cid,
            "authorization_cid": self.authorization_cid,
            "proposal_cid": self.proposal_cid,
            "previous_policy_cid": self.previous_policy_cid,
            "previous_policy_version": self.previous_policy_version,
            "promoted_policy_cid": self.promoted_policy_cid,
            "promoted_policy_version": self.promoted_policy_version,
            "rollback_policy_cid": self.rollback_policy_cid,
            "cas_expected_version": self.cas_expected_version,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompressionPolicyPromotionReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("receipt_cid")
        if payload.pop("schema") != COMPRESSION_POLICY_PROMOTION_RECEIPT_SCHEMA:
            raise PolicyContractError(
                "unsupported CompressionPolicyPromotionReceipt schema version"
            )
        if payload.pop("interface_id") != COMPRESSION_POLICY_PROMOTION_RECEIPT_INTERFACE:
            raise PolicyContractError(
                "unsupported CompressionPolicyPromotionReceipt interface_id"
            )
        result = cls(
            header=payload["header"],
            receipt_id=payload["receipt_id"],
            candidate_cid=payload["candidate_cid"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            authorization_cid=payload["authorization_cid"],
            proposal_cid=payload["proposal_cid"],
            previous_policy_cid=payload["previous_policy_cid"],
            previous_policy_version=payload["previous_policy_version"],
            promoted_policy_cid=payload["promoted_policy_cid"],
            promoted_policy_version=payload["promoted_policy_version"],
            rollback_policy_cid=payload["rollback_policy_cid"],
            cas_expected_version=payload["cas_expected_version"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.receipt_cid:
            raise PolicyContractError(
                "CompressionPolicyPromotionReceipt receipt_cid does not verify"
            )
        return result


def rule_categories() -> tuple[str, ...]:
    """Return the closed rule-category vocabulary."""

    return tuple(item.value for item in RuleCategory)


def rule_operations() -> tuple[str, ...]:
    """Return the closed rule-operation vocabulary."""

    return tuple(item.value for item in RuleOperation)


def evaluation_verdicts() -> tuple[str, ...]:
    """Return the closed evaluation-verdict vocabulary."""

    return tuple(item.value for item in EvaluationVerdict)


__all__ = [
    "ALLOWED_RULE_TARGET_KEYS",
    "COMPRESSION_POLICY_CANDIDATE_INTERFACE",
    "COMPRESSION_POLICY_CANDIDATE_SCHEMA",
    "COMPRESSION_POLICY_INTERFACE",
    "COMPRESSION_POLICY_PROMOTION_RECEIPT_INTERFACE",
    "COMPRESSION_POLICY_PROMOTION_RECEIPT_SCHEMA",
    "COMPRESSION_POLICY_SCHEMA",
    "DECLARATIVE_RULE_SCHEMA",
    "PROTECTED_RULE_TARGET_KEYS",
    "PROTECTED_THRESHOLD_FIELD_NAMES",
    "PROTECTED_THRESHOLDS_SCHEMA",
    "RULE_EVALUATION_REPORT_INTERFACE",
    "RULE_EVALUATION_REPORT_SCHEMA",
    "RULE_PROPOSAL_INTERFACE",
    "RULE_PROPOSAL_SCHEMA",
    "TASK_CLASS_ACCEPTANCE_SCHEMA",
    "CompressionPolicy",
    "CompressionPolicyCandidate",
    "CompressionPolicyPromotionReceipt",
    "DeclarativeRule",
    "EvaluationVerdict",
    "PolicyContractError",
    "ProtectedThresholds",
    "RuleCategory",
    "RuleEvaluationReport",
    "RuleOperation",
    "RuleProposal",
    "TaskClassAcceptanceRequirements",
    "assert_protected_threshold_change_authorized",
    "evaluation_verdicts",
    "protected_threshold_reductions",
    "rule_categories",
    "rule_operations",
    "validate_rule_dsl",
]
