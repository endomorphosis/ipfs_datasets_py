"""Generate and validate bounded declarative rule proposals (SCG-017).

Pure, deterministic proposal generation over calibration profiles and
supporting audit cases. Proposals use the typed allowlisted DSL from
``policy_contracts`` — never executable model text, templates, shell,
import paths, provider IDs, keys, or promotion authority.

Normative rules:

* Arbitrary code cannot execute (typed DSL atoms only; executable text is
  rejected at construction and re-checked at validation).
* Full-suite fallback cannot be disabled by any proposal path.
* High-risk assurance cannot be reduced in a **normal** proposal (no
  external authorization). Authorized reductions require a distinct
  external authorization CID that is not the proposal or its inputs.
* Empirical evidence may raise sampling, tighten invalidation/inclusion, or
  adjust packing/route thresholds; it never upgrades formal exactness and
  never self-authorizes promotion.
* Candidate-generating evidence must not come from the held-out partition.
* Identical verified inputs yield identical proposal identities.
* Canonical identity uses ``software_contracts.content`` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence, Union

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    CompressionAuditCase,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration_contracts import (
    AnalyzerCalibrationProfile,
    BASIS_POINTS,
    CapsuleCalibrationRecord,
    EvidencePartition,
    ModelRouteCalibrationProfile,
    TaskClassCalibrationProfile,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    ALLOWED_RULE_TARGET_KEYS,
    PROTECTED_RULE_TARGET_KEYS,
    CompressionPolicy,
    DeclarativeRule,
    PolicyContractError,
    ProtectedThresholds,
    RuleCategory,
    RuleOperation,
    RuleProposal,
    validate_rule_dsl,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

PROPOSE_RULE_CHANGE_INTERFACE: Final[str] = "propose_rule_change@1"
VALIDATE_RULE_PROPOSAL_INTERFACE: Final[str] = "validate_rule_proposal@1"
RULE_PROPOSAL_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-rule-proposal-result@1"
)
RULE_PROPOSAL_VALIDATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-rule-proposal-validation@1"
)
RULE_SAFETY_ANALYSIS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-rule-safety-analysis@1"
)

GENERATOR_ID: Final[str] = "rule_proposer"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "rules.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_AUDIT_CASES: Final[int] = 4_096
MAX_RULES: Final[int] = 1_024
MAX_BLOCKING_REASONS: Final[int] = 256
MAX_ASSUMPTIONS: Final[int] = 512

# Evidence thresholds (integer basis points / counts).
OMISSION_RATE_PROPOSAL_BP: Final[int] = 1_000  # 10%
DEFAULT_CONTEXT_BUDGET_TOKENS: Final[int] = 8_192
DEFAULT_SHADOW_SAMPLE_RATE_BP: Final[int] = 250
MAX_SHADOW_SAMPLE_RATE_BP: Final[int] = 5_000
DEFAULT_ESCALATION_THRESHOLD_BP: Final[int] = 5_000
BUDGET_STEP_TOKENS: Final[int] = 1_024
MAX_CONTEXT_BUDGET_TOKENS: Final[int] = 65_536

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)

# Reject executable / template / shell content in free-text proposal fields.
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
    re.compile(r"\bgetattr\s*\(", re.IGNORECASE),
    re.compile(r"\b__builtins__\b", re.IGNORECASE),
)

# Reject provider IDs, secrets, and promotion-authority claims.
_FORBIDDEN_AUTHORITY_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bapi[_-]?key\b", re.IGNORECASE),
    re.compile(r"\bsecret[_-]?key\b", re.IGNORECASE),
    re.compile(r"\baccess[_-]?token\b", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
    re.compile(r"\bopenai\b", re.IGNORECASE),
    re.compile(r"\banthropic\b", re.IGNORECASE),
    re.compile(r"\bgemini[_-]?api\b", re.IGNORECASE),
    re.compile(r"\bprovider[_-]?id\b", re.IGNORECASE),
    re.compile(r"\bself[_-]?authori[sz]e\b", re.IGNORECASE),
    re.compile(r"\bpromote[_-]?policy\b", re.IGNORECASE),
    re.compile(r"\bpromotion[_-]?authority\b", re.IGNORECASE),
    re.compile(r"\bmodel[_-]?authority\b", re.IGNORECASE),
)

# Bool targets that disable assurance when set to False.
_ASSURANCE_BOOL_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "full_suite_fallback_enabled",
        "require_selected_tests",
        "require_static_checks",
        "require_type_checks",
        "require_proofs",
        "require_human_review",
    }
)

# Numeric targets where lower values reduce assurance.
_ASSURANCE_FLOOR_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "shadow_sample_rate_bp",
        "audit_sample_rate_bp",
        "context_budget_tokens",
    }
)

# Numeric targets where higher values reduce assurance (harder to escalate).
_ASSURANCE_CEILING_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "escalation_threshold_bp",
    }
)

CalibrationProfile = Union[
    CapsuleCalibrationRecord,
    AnalyzerCalibrationProfile,
    TaskClassCalibrationProfile,
    ModelRouteCalibrationProfile,
]


# ---------------------------------------------------------------------------
# Errors and closed enumerations
# ---------------------------------------------------------------------------


class RuleProposalError(SemanticGovernorBaseError):
    """Raised when rule proposal generation or validation fails closed."""


class ProposalMode(str, Enum):
    """Whether a proposal may reduce protected high-risk assurance."""

    NORMAL = "normal"
    AUTHORIZED = "authorized"


class RuleProposalDisposition(str, Enum):
    """Closed outcomes for propose_rule_change."""

    PROPOSED = "proposed"
    REJECTED = "rejected"
    NO_CHANGE = "no_change"
    INCONCLUSIVE = "inconclusive"


class AssuranceImpact(str, Enum):
    """Net effect of a rule (or proposal) on high-risk assurance."""

    INCREASE = "increase"
    NEUTRAL = "neutral"
    REDUCE = "reduce"


class ValidationVerdict(str, Enum):
    """Closed outcomes for validate_rule_proposal."""

    ACCEPT = "accept"
    REJECT = "reject"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise RuleProposalError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise RuleProposalError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise RuleProposalError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise RuleProposalError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise RuleProposalError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise RuleProposalError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise RuleProposalError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise RuleProposalError(f"{name} must be a nonnegative integer")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise RuleProposalError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise RuleProposalError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    if value < 0 or value > BASIS_POINTS:
        raise RuleProposalError(
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
        raise RuleProposalError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise RuleProposalError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise RuleProposalError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuleProposalError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RuleProposalError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise RuleProposalError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RuleProposalError(f"{name} must not contain duplicates")
    return ordered


def _reject_executable_text(value: str, name: str) -> str:
    for pattern in _FORBIDDEN_VALUE_RES:
        if pattern.search(value) is not None:
            raise RuleProposalError(
                f"{name} rejects expressions, imports, commands, or templates; "
                "arbitrary code cannot execute"
            )
    return value


def _reject_authority_text(value: str, name: str) -> str:
    for pattern in _FORBIDDEN_AUTHORITY_RES:
        if pattern.search(value) is not None:
            raise RuleProposalError(
                f"{name} rejects provider IDs, keys, secrets, or promotion authority"
            )
    return value


def _scan_text_fields(value: Any, path: str) -> None:
    """Walk structured values and reject executable or authority-bearing text."""

    if isinstance(value, str):
        _reject_executable_text(value, path)
        _reject_authority_text(value, path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if isinstance(key, str):
                _reject_executable_text(key, f"{key_path}#key")
                _reject_authority_text(key, f"{key_path}#key")
            _scan_text_fields(item, key_path)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_text_fields(item, f"{path}[{index}]")


def _header(value: Any, name: str = "header") -> GovernorArtifactHeader:
    if isinstance(value, GovernorArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return GovernorArtifactHeader.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise RuleProposalError(str(exc)) from exc
    raise RuleProposalError(f"{name} must be GovernorArtifactHeader or mapping")


# ---------------------------------------------------------------------------
# Profile / audit normalization
# ---------------------------------------------------------------------------


def _normalize_profile(value: CalibrationProfile | Mapping[str, Any]) -> CalibrationProfile:
    if isinstance(
        value,
        (
            CapsuleCalibrationRecord,
            AnalyzerCalibrationProfile,
            TaskClassCalibrationProfile,
            ModelRouteCalibrationProfile,
        ),
    ):
        return value
    if isinstance(value, Mapping):
        schema = value.get("schema", "")
        if not isinstance(schema, str):
            raise RuleProposalError("calibration_profile schema must be a string")
        try:
            if "capsule-calibration" in schema or value.get("interface_id") == (
                "CapsuleCalibrationRecord@1"
            ):
                return CapsuleCalibrationRecord.from_dict(value)
            if "analyzer-calibration" in schema or value.get("interface_id") == (
                "AnalyzerCalibrationProfile@1"
            ):
                return AnalyzerCalibrationProfile.from_dict(value)
            if "task-class-calibration" in schema or value.get("interface_id") == (
                "TaskClassCalibrationProfile@1"
            ):
                return TaskClassCalibrationProfile.from_dict(value)
            if "model-route-calibration" in schema or value.get("interface_id") == (
                "ModelRouteCalibrationProfile@1"
            ):
                return ModelRouteCalibrationProfile.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise RuleProposalError(str(exc)) from exc
        raise RuleProposalError("unsupported calibration_profile schema")
    raise RuleProposalError(
        "calibration_profile must be a calibration record/profile or mapping"
    )


def _profile_cid(profile: CalibrationProfile) -> str:
    if isinstance(profile, CapsuleCalibrationRecord):
        return profile.record_cid
    return profile.profile_cid  # type: ignore[union-attr]


def _profile_partition(profile: CalibrationProfile) -> str:
    return str(profile.partition)


def _profile_header(profile: CalibrationProfile) -> GovernorArtifactHeader:
    return profile.header


def _normalize_audit_case(
    value: CompressionAuditCase | Mapping[str, Any],
) -> CompressionAuditCase:
    if isinstance(value, CompressionAuditCase):
        return value
    if isinstance(value, Mapping):
        try:
            return CompressionAuditCase.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise RuleProposalError(str(exc)) from exc
    raise RuleProposalError("audit_cases entries must be CompressionAuditCase or mapping")


def _normalize_audit_cases(
    values: Sequence[CompressionAuditCase | Mapping[str, Any]] | None,
) -> tuple[CompressionAuditCase, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise RuleProposalError("audit_cases must be a list")
    if len(values) > MAX_AUDIT_CASES:
        raise RuleProposalError("audit_cases exceeds maximum length")
    cases = [_normalize_audit_case(item) for item in values]
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise RuleProposalError("audit_cases must not contain duplicate case_id values")
    return tuple(sorted(cases, key=lambda case: case.case_id))


def _normalize_rules(
    values: Sequence[DeclarativeRule | Mapping[str, Any]] | None,
) -> tuple[DeclarativeRule, ...]:
    if values is None:
        return ()
    try:
        return validate_rule_dsl(list(values))
    except PolicyContractError as exc:
        raise RuleProposalError(str(exc)) from exc


def _normalize_thresholds(
    value: ProtectedThresholds | Mapping[str, Any] | None,
) -> ProtectedThresholds:
    if value is None:
        return ProtectedThresholds.default_production()
    if isinstance(value, ProtectedThresholds):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return ProtectedThresholds.from_dict(value)
            defaults = ProtectedThresholds.default_production().to_dict()
            defaults.pop("schema")
            defaults.update(dict(value))
            return ProtectedThresholds(**defaults)  # type: ignore[arg-type]
        except (PolicyContractError, TypeError, ValueError) as exc:
            raise RuleProposalError(str(exc)) from exc
    raise RuleProposalError("protected_thresholds must be ProtectedThresholds or mapping")


def _normalize_policy(
    value: CompressionPolicy | Mapping[str, Any] | None,
) -> CompressionPolicy | None:
    if value is None:
        return None
    if isinstance(value, CompressionPolicy):
        return value
    if isinstance(value, Mapping):
        try:
            return CompressionPolicy.from_dict(value)
        except (PolicyContractError, SemanticGovernorBaseError) as exc:
            raise RuleProposalError(str(exc)) from exc
    raise RuleProposalError("current_policy must be CompressionPolicy or mapping")


def _normalize_proposal(
    value: RuleProposal | Mapping[str, Any],
) -> RuleProposal:
    if isinstance(value, RuleProposal):
        return value
    if isinstance(value, Mapping):
        try:
            if "proposal_cid" in value and "schema" in value:
                return RuleProposal.from_dict(value)
            return RuleProposal(
                header=value["header"],
                proposal_id=value["proposal_id"],
                current_policy_version=value["current_policy_version"],
                current_policy_cid=value["current_policy_cid"],
                proposed_rules=value["proposed_rules"],
                supporting_audit_cids=value.get("supporting_audit_cids", ()),
                benefit_statement=value["benefit_statement"],
                safety_impact=value["safety_impact"],
                scope_token=value["scope_token"],
                benchmark_cid=value["benchmark_cid"],
                rollback_policy_cid=value["rollback_policy_cid"],
                calibration_profile_cids=value.get("calibration_profile_cids", ()),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        except (PolicyContractError, SemanticGovernorBaseError, KeyError, TypeError) as exc:
            raise RuleProposalError(str(exc)) from exc
    raise RuleProposalError("proposal must be RuleProposal or mapping")


def _baseline_value_map(
    rules: Sequence[DeclarativeRule],
) -> dict[str, Any]:
    """Latest baseline value per target_key (sorted rules; later id wins)."""

    mapping: dict[str, Any] = {}
    for rule in sorted(rules, key=lambda item: item.rule_id):
        mapping[rule.target_key] = rule.value
    return mapping


# ---------------------------------------------------------------------------
# Assurance impact analysis
# ---------------------------------------------------------------------------


def _rule_disables_full_suite(rule: DeclarativeRule) -> bool:
    if rule.target_key == "full_suite_fallback_enabled":
        if rule.operation == RuleOperation.SET_BOOL.value and rule.value is False:
            return True
    if rule.category == RuleCategory.FULL_SUITE_FALLBACK.value:
        if rule.operation == RuleOperation.SET_BOOL.value and rule.value is False:
            return True
    return False


def analyze_rule_assurance_impact(
    rule: DeclarativeRule | Mapping[str, Any],
    *,
    baseline_rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    protected_thresholds: ProtectedThresholds | Mapping[str, Any] | None = None,
) -> AssuranceImpact:
    """Classify one rule's effect on high-risk assurance.

    Reductions include disabling required verification, lowering protected
    sample/budget floors, raising escalation ceilings, or disabling full-suite
    fallback. Increases include enabling requirements or raising floors.
    """

    try:
        normalized = (
            rule
            if isinstance(rule, DeclarativeRule)
            else validate_rule_dsl([rule])[0]
        )
    except PolicyContractError as exc:
        raise RuleProposalError(str(exc)) from exc

    thresholds = _normalize_thresholds(protected_thresholds)
    baseline = _baseline_value_map(_normalize_rules(baseline_rules))

    if _rule_disables_full_suite(normalized):
        return AssuranceImpact.REDUCE

    target = normalized.target_key
    op = normalized.operation
    value = normalized.value

    if target in _ASSURANCE_BOOL_TARGETS and op == RuleOperation.SET_BOOL.value:
        if value is False:
            return AssuranceImpact.REDUCE
        if value is True:
            prior = baseline.get(target)
            if prior is False:
                return AssuranceImpact.INCREASE
            return AssuranceImpact.INCREASE if target == "full_suite_fallback_enabled" else (
                AssuranceImpact.INCREASE if prior is not True else AssuranceImpact.NEUTRAL
            )

    if target in _ASSURANCE_FLOOR_TARGETS and op in {
        RuleOperation.SET_BASIS_POINTS.value,
        RuleOperation.SET_SAMPLE_RATE.value,
        RuleOperation.SET_NONNEG_INT.value,
    }:
        if type(value) is not int or isinstance(value, bool):
            return AssuranceImpact.NEUTRAL
        prior = baseline.get(target)
        floor = 0
        if target == "shadow_sample_rate_bp":
            floor = thresholds.min_shadow_sample_rate_bp
        if type(prior) is int and not isinstance(prior, bool):
            if value < prior:
                return AssuranceImpact.REDUCE
            if value > prior:
                return AssuranceImpact.INCREASE
            return AssuranceImpact.NEUTRAL
        if value < floor:
            return AssuranceImpact.REDUCE
        if value > floor:
            return AssuranceImpact.INCREASE
        return AssuranceImpact.NEUTRAL

    if target in _ASSURANCE_CEILING_TARGETS and op in {
        RuleOperation.SET_BASIS_POINTS.value,
        RuleOperation.SET_SAMPLE_RATE.value,
        RuleOperation.SET_NONNEG_INT.value,
    }:
        if type(value) is not int or isinstance(value, bool):
            return AssuranceImpact.NEUTRAL
        prior = baseline.get(target, DEFAULT_ESCALATION_THRESHOLD_BP)
        if type(prior) is not int or isinstance(prior, bool):
            prior = DEFAULT_ESCALATION_THRESHOLD_BP
        if value > prior:
            return AssuranceImpact.REDUCE
        if value < prior:
            return AssuranceImpact.INCREASE
        return AssuranceImpact.NEUTRAL

    # Inclusion / invalidation requirements and ranking tokens tighten process.
    if op in {
        RuleOperation.REQUIRE_INCLUSION.value,
        RuleOperation.REQUIRE_INVALIDATION.value,
        RuleOperation.ADD_TOKEN.value,
    }:
        return AssuranceImpact.INCREASE

    if op == RuleOperation.REMOVE_TOKEN.value:
        # Removing extraction/invalidation tokens can weaken analysis.
        return AssuranceImpact.REDUCE

    return AssuranceImpact.NEUTRAL


def is_high_risk_assurance_reduction(
    rule: DeclarativeRule | Mapping[str, Any],
    *,
    baseline_rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    protected_thresholds: ProtectedThresholds | Mapping[str, Any] | None = None,
) -> bool:
    """Return True when a rule reduces high-risk assurance."""

    return (
        analyze_rule_assurance_impact(
            rule,
            baseline_rules=baseline_rules,
            protected_thresholds=protected_thresholds,
        )
        == AssuranceImpact.REDUCE
    )


def aggregate_assurance_impact(
    impacts: Sequence[AssuranceImpact | str],
) -> AssuranceImpact:
    """Aggregate per-rule impacts; any reduction dominates."""

    values = {
        item.value if isinstance(item, AssuranceImpact) else str(item) for item in impacts
    }
    if AssuranceImpact.REDUCE.value in values:
        return AssuranceImpact.REDUCE
    if AssuranceImpact.INCREASE.value in values:
        return AssuranceImpact.INCREASE
    return AssuranceImpact.NEUTRAL


# ---------------------------------------------------------------------------
# Safety analysis record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleSafetyAnalysis:
    """Closed safety summary for a proposal or draft rule set."""

    full_suite_fallback_disabled: bool
    high_risk_assurance_reduced: bool
    arbitrary_code_rejected: bool
    touches_protected_targets: bool
    assurance_impact: AssuranceImpact | str
    reduced_rule_ids: Sequence[str] = ()
    protected_target_keys: Sequence[str] = ()
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "full_suite_fallback_disabled",
            "high_risk_assurance_reduced",
            "arbitrary_code_rejected",
            "touches_protected_targets",
            "assurance_impact",
            "reduced_rule_ids",
            "protected_target_keys",
            "notes",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "full_suite_fallback_disabled",
            _bool(self.full_suite_fallback_disabled, "full_suite_fallback_disabled"),
        )
        object.__setattr__(
            self,
            "high_risk_assurance_reduced",
            _bool(self.high_risk_assurance_reduced, "high_risk_assurance_reduced"),
        )
        object.__setattr__(
            self,
            "arbitrary_code_rejected",
            _bool(self.arbitrary_code_rejected, "arbitrary_code_rejected"),
        )
        object.__setattr__(
            self,
            "touches_protected_targets",
            _bool(self.touches_protected_targets, "touches_protected_targets"),
        )
        object.__setattr__(
            self,
            "assurance_impact",
            _enum(self.assurance_impact, AssuranceImpact, "assurance_impact"),
        )
        if not isinstance(self.reduced_rule_ids, (list, tuple)):
            raise RuleProposalError("reduced_rule_ids must be a list")
        reduced = tuple(sorted(_token(item, "reduced_rule_ids") for item in self.reduced_rule_ids))
        if len(reduced) != len(set(reduced)):
            raise RuleProposalError("reduced_rule_ids must not contain duplicates")
        object.__setattr__(self, "reduced_rule_ids", reduced)
        if not isinstance(self.protected_target_keys, (list, tuple)):
            raise RuleProposalError("protected_target_keys must be a list")
        protected = tuple(
            sorted(_token(item, "protected_target_keys") for item in self.protected_target_keys)
        )
        if len(protected) != len(set(protected)):
            raise RuleProposalError("protected_target_keys must not contain duplicates")
        object.__setattr__(self, "protected_target_keys", protected)
        notes = _optional_text(self.notes, "notes")
        if notes is not None:
            notes = _reject_executable_text(notes, "notes")
            notes = _reject_authority_text(notes, "notes")
        object.__setattr__(self, "notes", notes)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RULE_SAFETY_ANALYSIS_SCHEMA,
            "full_suite_fallback_disabled": self.full_suite_fallback_disabled,
            "high_risk_assurance_reduced": self.high_risk_assurance_reduced,
            "arbitrary_code_rejected": self.arbitrary_code_rejected,
            "touches_protected_targets": self.touches_protected_targets,
            "assurance_impact": self.assurance_impact,
            "reduced_rule_ids": list(self.reduced_rule_ids),
            "protected_target_keys": list(self.protected_target_keys),
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleSafetyAnalysis":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != RULE_SAFETY_ANALYSIS_SCHEMA:
            raise RuleProposalError("unsupported RuleSafetyAnalysis schema version")
        return cls(**payload)


def analyze_rules_safety(
    rules: Sequence[DeclarativeRule | Mapping[str, Any]],
    *,
    baseline_rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    protected_thresholds: ProtectedThresholds | Mapping[str, Any] | None = None,
) -> RuleSafetyAnalysis:
    """Compute aggregate safety analysis for a rule list (fail closed)."""

    arbitrary_code_rejected = False
    try:
        normalized = validate_rule_dsl(list(rules))
    except PolicyContractError as exc:
        message = str(exc)
        if "full-suite fallback cannot be disabled" in message:
            return RuleSafetyAnalysis(
                full_suite_fallback_disabled=True,
                high_risk_assurance_reduced=True,
                arbitrary_code_rejected=False,
                touches_protected_targets=True,
                assurance_impact=AssuranceImpact.REDUCE,
                reduced_rule_ids=(),
                protected_target_keys=("full_suite_fallback_enabled",),
                notes=message,
            )
        if "expressions, imports, commands, or templates" in message:
            return RuleSafetyAnalysis(
                full_suite_fallback_disabled=False,
                high_risk_assurance_reduced=False,
                arbitrary_code_rejected=True,
                touches_protected_targets=False,
                assurance_impact=AssuranceImpact.NEUTRAL,
                reduced_rule_ids=(),
                protected_target_keys=(),
                notes=message,
            )
        raise RuleProposalError(message) from exc

    reduced_ids: list[str] = []
    protected_keys: list[str] = []
    impacts: list[AssuranceImpact] = []
    full_suite_disabled = False

    for rule in normalized:
        if rule.target_key in PROTECTED_RULE_TARGET_KEYS:
            protected_keys.append(rule.target_key)
        if _rule_disables_full_suite(rule):
            full_suite_disabled = True
            reduced_ids.append(rule.rule_id)
            impacts.append(AssuranceImpact.REDUCE)
            continue
        impact = analyze_rule_assurance_impact(
            rule,
            baseline_rules=baseline_rules,
            protected_thresholds=protected_thresholds,
        )
        impacts.append(impact)
        if impact == AssuranceImpact.REDUCE:
            reduced_ids.append(rule.rule_id)

    aggregate = aggregate_assurance_impact(impacts)
    return RuleSafetyAnalysis(
        full_suite_fallback_disabled=full_suite_disabled,
        high_risk_assurance_reduced=aggregate == AssuranceImpact.REDUCE,
        arbitrary_code_rejected=arbitrary_code_rejected,
        touches_protected_targets=bool(protected_keys),
        assurance_impact=aggregate,
        reduced_rule_ids=tuple(sorted(set(reduced_ids))),
        protected_target_keys=tuple(sorted(set(protected_keys))),
        notes=None,
    )


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleProposalValidationReport:
    """Result of validate_rule_proposal (no mutation, no promotion)."""

    header: GovernorArtifactHeader
    report_id: str
    proposal_cid: str | None
    proposal_mode: ProposalMode | str
    verdict: ValidationVerdict | str
    safety: RuleSafetyAnalysis
    blocking_reasons: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "report_id",
            "proposal_cid",
            "proposal_mode",
            "verdict",
            "safety",
            "blocking_reasons",
            "notes",
            "metadata",
            "report_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "rule_proposal_validation_report":
            raise RuleProposalError(
                "header.artifact_kind must be rule_proposal_validation_report"
            )
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(
            self, "proposal_cid", _optional_cid(self.proposal_cid, "proposal_cid")
        )
        object.__setattr__(
            self, "proposal_mode", _enum(self.proposal_mode, ProposalMode, "proposal_mode")
        )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, ValidationVerdict, "verdict")
        )
        if isinstance(self.safety, RuleSafetyAnalysis):
            safety = self.safety
        elif isinstance(self.safety, Mapping):
            safety = RuleSafetyAnalysis.from_dict(self.safety)
        else:
            raise RuleProposalError("safety must be RuleSafetyAnalysis or mapping")
        object.__setattr__(self, "safety", safety)
        if not isinstance(self.blocking_reasons, (list, tuple)):
            raise RuleProposalError("blocking_reasons must be a list")
        if len(self.blocking_reasons) > MAX_BLOCKING_REASONS:
            raise RuleProposalError("blocking_reasons exceeds maximum length")
        reasons = tuple(
            _reject_authority_text(
                _reject_executable_text(_text(item, "blocking_reasons"), "blocking_reasons"),
                "blocking_reasons",
            )
            for item in self.blocking_reasons
        )
        object.__setattr__(self, "blocking_reasons", reasons)
        notes = _optional_text(self.notes, "notes")
        if notes is not None:
            notes = _reject_executable_text(notes, "notes")
            notes = _reject_authority_text(notes, "notes")
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Consistency: accept cannot claim full-suite disable or arbitrary code.
        if self.verdict == ValidationVerdict.ACCEPT.value:
            if safety.full_suite_fallback_disabled:
                raise RuleProposalError(
                    "accept verdict cannot claim full_suite_fallback_disabled"
                )
            if safety.arbitrary_code_rejected:
                raise RuleProposalError(
                    "accept verdict cannot claim arbitrary_code_rejected"
                )
            if (
                self.proposal_mode == ProposalMode.NORMAL.value
                and safety.high_risk_assurance_reduced
            ):
                raise RuleProposalError(
                    "normal accept cannot claim high_risk_assurance_reduced"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_VALIDATION_SCHEMA,
            "interface_id": VALIDATE_RULE_PROPOSAL_INTERFACE,
            "header": self.header.identity_payload(),
            "report_id": self.report_id,
            "proposal_cid": self.proposal_cid,
            "proposal_mode": self.proposal_mode,
            "verdict": self.verdict,
            "safety": self.safety.identity_payload(),
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def report_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_VALIDATION_SCHEMA,
            "interface_id": VALIDATE_RULE_PROPOSAL_INTERFACE,
            "header": self.header.to_dict(),
            "report_id": self.report_id,
            "proposal_cid": self.proposal_cid,
            "proposal_mode": self.proposal_mode,
            "verdict": self.verdict,
            "safety": self.safety.to_dict(),
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "report_cid": self.report_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleProposalValidationReport":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("report_cid")
        if payload.pop("schema") != RULE_PROPOSAL_VALIDATION_SCHEMA:
            raise RuleProposalError(
                "unsupported RuleProposalValidationReport schema version"
            )
        if payload.pop("interface_id") != VALIDATE_RULE_PROPOSAL_INTERFACE:
            raise RuleProposalError(
                "unsupported RuleProposalValidationReport interface_id"
            )
        result = cls(**payload)
        if claimed != result.report_cid:
            raise RuleProposalError(
                "RuleProposalValidationReport report_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Proposal result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleProposalResult:
    """Sealed outcome of propose_rule_change."""

    header: GovernorArtifactHeader
    result_id: str
    disposition: RuleProposalDisposition | str
    proposal: RuleProposal | None
    safety: RuleSafetyAnalysis
    calibration_profile_cid: str
    supporting_audit_cids: Sequence[str] = ()
    blocking_reasons: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "result_id",
            "disposition",
            "proposal",
            "safety",
            "calibration_profile_cid",
            "supporting_audit_cids",
            "blocking_reasons",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "rule_proposal_result":
            raise RuleProposalError("header.artifact_kind must be rule_proposal_result")
        object.__setattr__(self, "result_id", _token(self.result_id, "result_id"))
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RuleProposalDisposition, "disposition"),
        )
        proposal: RuleProposal | None
        if self.proposal is None:
            proposal = None
        elif isinstance(self.proposal, RuleProposal):
            proposal = self.proposal
        elif isinstance(self.proposal, Mapping):
            proposal = _normalize_proposal(self.proposal)
        else:
            raise RuleProposalError("proposal must be RuleProposal, mapping, or null")
        object.__setattr__(self, "proposal", proposal)
        if isinstance(self.safety, RuleSafetyAnalysis):
            safety = self.safety
        elif isinstance(self.safety, Mapping):
            safety = RuleSafetyAnalysis.from_dict(self.safety)
        else:
            raise RuleProposalError("safety must be RuleSafetyAnalysis or mapping")
        object.__setattr__(self, "safety", safety)
        object.__setattr__(
            self,
            "calibration_profile_cid",
            _cid(self.calibration_profile_cid, "calibration_profile_cid"),
        )
        object.__setattr__(
            self,
            "supporting_audit_cids",
            _unique_sorted_cids(list(self.supporting_audit_cids), "supporting_audit_cids"),
        )
        if not isinstance(self.blocking_reasons, (list, tuple)):
            raise RuleProposalError("blocking_reasons must be a list")
        if len(self.blocking_reasons) > MAX_BLOCKING_REASONS:
            raise RuleProposalError("blocking_reasons exceeds maximum length")
        reasons = tuple(
            _reject_authority_text(
                _reject_executable_text(_text(item, "blocking_reasons"), "blocking_reasons"),
                "blocking_reasons",
            )
            for item in self.blocking_reasons
        )
        object.__setattr__(self, "blocking_reasons", reasons)
        notes = _optional_text(self.notes, "notes")
        if notes is not None:
            notes = _reject_executable_text(notes, "notes")
            notes = _reject_authority_text(notes, "notes")
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        if self.disposition == RuleProposalDisposition.PROPOSED.value:
            if proposal is None:
                raise RuleProposalError("proposed disposition requires a proposal")
            if safety.full_suite_fallback_disabled:
                raise RuleProposalError(
                    "proposed disposition cannot disable full-suite fallback"
                )
            if safety.arbitrary_code_rejected:
                raise RuleProposalError(
                    "proposed disposition cannot admit arbitrary code"
                )
            if safety.high_risk_assurance_reduced:
                raise RuleProposalError(
                    "normal proposal cannot reduce high-risk assurance"
                )
        if self.disposition != RuleProposalDisposition.PROPOSED.value and proposal is not None:
            # Allow rejected path to carry the attempted proposal for audit.
            pass

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_RESULT_SCHEMA,
            "interface_id": PROPOSE_RULE_CHANGE_INTERFACE,
            "header": self.header.identity_payload(),
            "result_id": self.result_id,
            "disposition": self.disposition,
            "proposal": None if self.proposal is None else self.proposal.identity_payload(),
            "safety": self.safety.identity_payload(),
            "calibration_profile_cid": self.calibration_profile_cid,
            "supporting_audit_cids": list(self.supporting_audit_cids),
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_PROPOSAL_RESULT_SCHEMA,
            "interface_id": PROPOSE_RULE_CHANGE_INTERFACE,
            "header": self.header.to_dict(),
            "result_id": self.result_id,
            "disposition": self.disposition,
            "proposal": None if self.proposal is None else self.proposal.to_dict(),
            "safety": self.safety.to_dict(),
            "calibration_profile_cid": self.calibration_profile_cid,
            "supporting_audit_cids": list(self.supporting_audit_cids),
            "blocking_reasons": list(self.blocking_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleProposalResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != RULE_PROPOSAL_RESULT_SCHEMA:
            raise RuleProposalError("unsupported RuleProposalResult schema version")
        if payload.pop("interface_id") != PROPOSE_RULE_CHANGE_INTERFACE:
            raise RuleProposalError("unsupported RuleProposalResult interface_id")
        result = cls(**payload)
        if claimed != result.result_cid:
            raise RuleProposalError("RuleProposalResult result_cid does not verify")
        return result


# ---------------------------------------------------------------------------
# Evidence extraction and rule generation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _EvidenceSignals:
    stale_failure_count: int = 0
    false_exact_classification_count: int = 0
    omission_failure_count: int = 0
    omission_rate_bp: int = 0
    unnecessary_raw_fallback_count: int = 0
    review_disagreement_count: int = 0
    shadow_sample_rate_bp: int | None = None
    escalation_rate_bp: int | None = None
    risk_class: str | None = None
    language: str | None = None
    route_tier: str | None = None
    analyzer_id: str | None = None
    total_uses: int = 0
    high_risk: bool = False


def _rate_bp(rate_obj: Any) -> int:
    if rate_obj is None:
        return 0
    value = getattr(rate_obj, "rate_bp", None)
    if type(value) is int and not isinstance(value, bool):
        return value
    if isinstance(rate_obj, Mapping):
        raw = rate_obj.get("rate_bp", 0)
        if type(raw) is int and not isinstance(raw, bool):
            return raw
    return 0


def _collect_signals(profile: CalibrationProfile) -> _EvidenceSignals:
    if isinstance(profile, CapsuleCalibrationRecord):
        risk = str(profile.risk_class)
        return _EvidenceSignals(
            stale_failure_count=profile.stale_failure_count,
            false_exact_classification_count=profile.false_exact_classification_count,
            omission_failure_count=profile.omission_failure_count,
            omission_rate_bp=_rate_bp(profile.omission_rate),
            unnecessary_raw_fallback_count=profile.unnecessary_raw_fallback_count,
            review_disagreement_count=profile.review_disagreement_count,
            risk_class=risk,
            language=str(profile.language),
            route_tier=str(profile.route_tier),
            analyzer_id=str(profile.analyzer_feature),
            total_uses=profile.use_count,
            high_risk=risk in {"high", "critical"},
        )
    if isinstance(profile, AnalyzerCalibrationProfile):
        return _EvidenceSignals(
            stale_failure_count=profile.stale_failure_count,
            false_exact_classification_count=profile.false_exact_classification_count,
            omission_rate_bp=_rate_bp(profile.omission_rate),
            language=profile.language_keys[0] if profile.language_keys else None,
            analyzer_id=str(profile.analyzer_id),
            total_uses=profile.total_uses,
        )
    if isinstance(profile, TaskClassCalibrationProfile):
        risk = str(profile.risk_class)
        return _EvidenceSignals(
            omission_rate_bp=_rate_bp(profile.omission_rate),
            review_disagreement_count=profile.review_disagreement_count,
            risk_class=risk,
            total_uses=profile.total_uses,
            high_risk=risk in {"high", "critical"},
        )
    if isinstance(profile, ModelRouteCalibrationProfile):
        return _EvidenceSignals(
            shadow_sample_rate_bp=profile.shadow_sample_rate_bp,
            escalation_rate_bp=profile.escalation_rate_bp,
            route_tier=str(profile.route_tier),
            total_uses=profile.total_uses,
        )
    raise RuleProposalError("unsupported calibration profile kind")


def _make_rule(
    rule_id: str,
    category: RuleCategory,
    operation: RuleOperation,
    target_key: str,
    value: Any,
    scope_token: str | None,
) -> DeclarativeRule:
    try:
        return DeclarativeRule(
            rule_id=rule_id,
            category=category,
            operation=operation,
            target_key=target_key,
            value=value,
            scope_token=scope_token,
        )
    except PolicyContractError as exc:
        raise RuleProposalError(str(exc)) from exc


def _generate_rules_from_evidence(
    signals: _EvidenceSignals,
    *,
    scope_token: str,
    thresholds: ProtectedThresholds,
    baseline_rules: Sequence[DeclarativeRule],
    max_rules: int,
) -> list[DeclarativeRule]:
    """Generate allowlisted safe rules driven by calibration evidence."""

    rules: list[DeclarativeRule] = []
    baseline = _baseline_value_map(baseline_rules)
    scope = scope_token

    def add(rule: DeclarativeRule) -> None:
        if len(rules) >= max_rules:
            return
        if any(existing.rule_id == rule.rule_id for existing in rules):
            return
        # Never admit a high-risk assurance reduction into generated output.
        if is_high_risk_assurance_reduction(
            rule,
            baseline_rules=baseline_rules,
            protected_thresholds=thresholds,
        ):
            return
        if _rule_disables_full_suite(rule):
            return
        rules.append(rule)

    # 1) Invalidation: stale failures require stronger invalidation.
    if signals.stale_failure_count > 0:
        add(
            _make_rule(
                "req_invalidate_stale_cone",
                RuleCategory.INVALIDATION,
                RuleOperation.REQUIRE_INVALIDATION,
                "invalidation_mode",
                "transitive_stale_cone",
                scope,
            )
        )

    # 2) Dependency extraction: omissions / false exact need broader extraction.
    if (
        signals.omission_rate_bp >= OMISSION_RATE_PROPOSAL_BP
        or signals.false_exact_classification_count > 0
        or signals.omission_failure_count > 0
    ):
        extractor = signals.analyzer_id or "callgraph"
        add(
            _make_rule(
                "add_dependency_extractor",
                RuleCategory.DEPENDENCY_EXTRACTION,
                RuleOperation.ADD_TOKEN,
                "dependency_extractor",
                extractor if _TOKEN_RE.fullmatch(extractor) else "callgraph",
                scope,
            )
        )

    # 3) Capsule completeness: false exact must not stay "exact" via heuristics.
    if signals.false_exact_classification_count > 0:
        add(
            _make_rule(
                "set_capsule_conservative",
                RuleCategory.CAPSULE_COMPLETENESS,
                RuleOperation.SET_TOKEN,
                "capsule_completeness_level",
                "conservative",
                scope,
            )
        )

    # 4) Raw-source inclusion for critical omissions / false exact.
    if (
        signals.false_exact_classification_count > 0
        or signals.omission_failure_count > 0
        or signals.omission_rate_bp >= OMISSION_RATE_PROPOSAL_BP
        or signals.high_risk
    ):
        add(
            _make_rule(
                "require_raw_critical_subjects",
                RuleCategory.RAW_SOURCE_INCLUSION,
                RuleOperation.REQUIRE_INCLUSION,
                "raw_source_mode",
                "critical_subjects",
                scope,
            )
        )

    # 5) Context ranking / packing: unnecessary raw fallbacks waste budget.
    if signals.unnecessary_raw_fallback_count > 0 or signals.omission_rate_bp > 0:
        add(
            _make_rule(
                "set_context_rank_criticality",
                RuleCategory.CONTEXT_RANKING,
                RuleOperation.SET_TOKEN,
                "context_rank_key",
                "criticality_then_cost",
                scope,
            )
        )
        add(
            _make_rule(
                "set_context_pack_affected_cone",
                RuleCategory.CONTEXT_PACKING,
                RuleOperation.SET_TOKEN,
                "context_pack_strategy",
                "affected_cone_first",
                scope,
            )
        )

    # 6) Budget: omissions with uses suggest more context before route escalations.
    if signals.omission_rate_bp >= OMISSION_RATE_PROPOSAL_BP and signals.total_uses > 0:
        current_budget = baseline.get("context_budget_tokens", DEFAULT_CONTEXT_BUDGET_TOKENS)
        if type(current_budget) is not int or isinstance(current_budget, bool):
            current_budget = DEFAULT_CONTEXT_BUDGET_TOKENS
        proposed_budget = min(
            MAX_CONTEXT_BUDGET_TOKENS, current_budget + BUDGET_STEP_TOKENS
        )
        if proposed_budget > current_budget:
            add(
                _make_rule(
                    "raise_context_budget",
                    RuleCategory.CONTEXT_BUDGET_THRESHOLD,
                    RuleOperation.SET_NONNEG_INT,
                    "context_budget_tokens",
                    proposed_budget,
                    scope,
                )
            )

    # 7) Route thresholds: high-risk / disagreement escalate route tier.
    if signals.high_risk or signals.review_disagreement_count > 0:
        add(
            _make_rule(
                "set_route_tier_frontier",
                RuleCategory.MODEL_ROUTE_THRESHOLD,
                RuleOperation.SET_ROUTE_TIER,
                "model_route_tier",
                "frontier",
                scope,
            )
        )
    elif signals.escalation_rate_bp is not None and signals.escalation_rate_bp >= 2_000:
        add(
            _make_rule(
                "set_route_tier_elevated",
                RuleCategory.MODEL_ROUTE_THRESHOLD,
                RuleOperation.SET_ROUTE_TIER,
                "model_route_tier",
                "elevated",
                scope,
            )
        )

    # 8) Shadow sampling: raise floor on false exact / low observed rate.
    min_shadow = thresholds.min_shadow_sample_rate_bp
    current_shadow = signals.shadow_sample_rate_bp
    if current_shadow is None:
        prior = baseline.get("shadow_sample_rate_bp")
        current_shadow = prior if type(prior) is int and not isinstance(prior, bool) else min_shadow
    target_shadow = max(min_shadow, DEFAULT_SHADOW_SAMPLE_RATE_BP)
    if signals.false_exact_classification_count > 0:
        target_shadow = max(target_shadow, min(MAX_SHADOW_SAMPLE_RATE_BP, current_shadow * 2 or DEFAULT_SHADOW_SAMPLE_RATE_BP))
    if current_shadow < target_shadow:
        add(
            _make_rule(
                "raise_shadow_sample_rate",
                RuleCategory.SHADOW_SAMPLING_RATE,
                RuleOperation.SET_SAMPLE_RATE,
                "shadow_sample_rate_bp",
                min(MAX_SHADOW_SAMPLE_RATE_BP, target_shadow),
                scope,
            )
        )

    # 9) Safe full-suite fallback reinforcement (never disable).
    add(
        _make_rule(
            "require_full_suite_fallback",
            RuleCategory.FULL_SUITE_FALLBACK,
            RuleOperation.SET_BOOL,
            "full_suite_fallback_enabled",
            True,
            scope,
        )
    )
    # require_selected_tests is allowlisted but not under full_suite_fallback
    # category coherence; emit as packing-adjacent acceptance tightening only
    # when omissions or high risk are present (SET_BOOL True is an increase).
    if (
        signals.omission_rate_bp >= OMISSION_RATE_PROPOSAL_BP
        or signals.high_risk
        or signals.false_exact_classification_count > 0
    ):
        add(
            _make_rule(
                "require_selected_tests",
                RuleCategory.CONTEXT_PACKING,
                RuleOperation.SET_BOOL,
                "require_selected_tests",
                True,
                scope,
            )
        )

    return rules[:max_rules]


def _scope_from_profile(profile: CalibrationProfile, signals: _EvidenceSignals) -> str:
    if signals.language and _TOKEN_RE.fullmatch(signals.language):
        return signals.language
    if isinstance(profile, TaskClassCalibrationProfile):
        return f"{profile.task_class}_{profile.risk_class}"[:128]
    if isinstance(profile, ModelRouteCalibrationProfile):
        return str(profile.route_tier)
    if isinstance(profile, AnalyzerCalibrationProfile):
        return str(profile.analyzer_id)
    return "default"


def _benefit_statement(signals: _EvidenceSignals, rules: Sequence[DeclarativeRule]) -> str:
    categories = sorted({rule.category for rule in rules})
    parts = [
        "Evidence-bound declarative adjustments for "
        + ", ".join(categories)
    ]
    if signals.stale_failure_count > 0:
        parts.append("strengthen invalidation after stale failures")
    if signals.false_exact_classification_count > 0:
        parts.append("tighten capsule completeness after false exact classifications")
    if signals.omission_rate_bp >= OMISSION_RATE_PROPOSAL_BP:
        parts.append("raise inclusion and packing after elevated omission rates")
    if signals.unnecessary_raw_fallback_count > 0:
        parts.append("prefer affected-cone packing over unnecessary raw fallbacks")
    parts.append("retain full-suite fallback and protected verification requirements")
    text = "; ".join(parts)
    return text[:MAX_TEXT_CHARS]


def _safety_impact_statement(safety: RuleSafetyAnalysis) -> str:
    if safety.high_risk_assurance_reduced:
        return (
            "Proposal would reduce high-risk assurance and must not be admitted "
            "as a normal proposal"
        )
    if safety.full_suite_fallback_disabled:
        return "Proposal disables full-suite fallback and is rejected"
    return (
        "No high-risk assurance reduction; full-suite fallback remains enabled; "
        "typed allowlisted operations only with no executable content"
    )


def _build_header(
    *,
    artifact_kind: str,
    source_header: GovernorArtifactHeader,
    input_cids: Sequence[str],
    interface_id: str,
    terminal_status: GovernorTerminalStatus | str,
    metadata: Mapping[str, Any],
) -> GovernorArtifactHeader:
    status = (
        terminal_status.value
        if isinstance(terminal_status, GovernorTerminalStatus)
        else _enum(terminal_status, GovernorTerminalStatus, "terminal_status")
    )
    assumptions = list(source_header.assumptions)
    if len(assumptions) > MAX_ASSUMPTIONS:
        assumptions = assumptions[:MAX_ASSUMPTIONS]
    if not any(item.assumption_id == "typed_dsl_only" for item in assumptions):
        assumptions.append(
            GovernorAssumption(
                assumption_id="typed_dsl_only",
                kind=AssumptionKind.VERIFICATION,
                statement=(
                    "Rule proposals use allowlisted typed operations only; "
                    "no executable model text, promotion authority, or provider keys"
                ),
                supporting_cids=tuple(sorted(input_cids))[:8] or (
                    source_header.repository_state_cid,
                ),
            )
        )
    return GovernorArtifactHeader(
        artifact_kind=artifact_kind,
        repository_state_cid=source_header.repository_state_cid,
        context_pack_cid=source_header.context_pack_cid,
        verification_bundle_cid=source_header.verification_bundle_cid,
        generator=GeneratorIdentity(
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            interface_id=interface_id,
        ),
        provenance=ArtifactProvenance(
            producer_id=PRODUCER_ID,
            producer_version=PRODUCER_VERSION,
            execution_mode=ExecutionMode.LIVE,
            authority_source=AuthoritySource.DETERMINISTIC,
            input_cids=tuple(sorted(set(input_cids))),
            tool_ids=(TOOL_ID,),
            policy_cid=source_header.provenance.policy_cid,
            notes=None,
        ),
        terminal_status=status,
        assumptions=tuple(assumptions),
        metadata=dict(metadata),
    )


# ---------------------------------------------------------------------------
# Public: validate_rule_proposal
# ---------------------------------------------------------------------------


def validate_rule_proposal(
    proposal: RuleProposal | Mapping[str, Any] | None = None,
    *,
    rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    proposal_mode: ProposalMode | str = ProposalMode.NORMAL,
    protected_thresholds: ProtectedThresholds | Mapping[str, Any] | None = None,
    baseline_rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    external_authorization_cid: str | None = None,
    forbidden_self_cids: Iterable[str] = (),
    source_header: GovernorArtifactHeader | Mapping[str, Any] | None = None,
    report_id: str | None = None,
) -> RuleProposalValidationReport:
    """Validate a proposal or draft rule list under normal/authorized mode.

    Acceptance invariants:

    * Arbitrary code cannot execute (DSL + text scanners).
    * Full-suite fallback cannot be disabled.
    * High-risk assurance cannot be reduced in a **normal** proposal.
    """

    mode = _enum(proposal_mode, ProposalMode, "proposal_mode")
    thresholds = _normalize_thresholds(protected_thresholds)
    blocking: list[str] = []
    proposal_obj: RuleProposal | None = None
    proposal_cid: str | None = None
    rule_list: tuple[DeclarativeRule, ...] = ()

    # Prefer full proposal when provided; otherwise validate a bare rule list.
    if proposal is not None:
        try:
            proposal_obj = _normalize_proposal(proposal)
            proposal_cid = proposal_obj.proposal_cid
            rule_list = tuple(proposal_obj.proposed_rules)
            # Free-text fields already scanned by RuleProposal; re-scan identity.
            _scan_text_fields(proposal_obj.benefit_statement, "benefit_statement")
            _scan_text_fields(proposal_obj.safety_impact, "safety_impact")
            if proposal_obj.notes is not None:
                _scan_text_fields(proposal_obj.notes, "notes")
            _scan_text_fields(_thaw_structured(proposal_obj.metadata), "metadata")
        except RuleProposalError as exc:
            message = str(exc)
            safety = RuleSafetyAnalysis(
                full_suite_fallback_disabled="full-suite fallback" in message,
                high_risk_assurance_reduced="full-suite fallback" in message,
                arbitrary_code_rejected=(
                    "arbitrary code" in message
                    or "expressions, imports" in message
                ),
                touches_protected_targets="full-suite fallback" in message,
                assurance_impact=(
                    AssuranceImpact.REDUCE
                    if "full-suite fallback" in message
                    else AssuranceImpact.NEUTRAL
                ),
                reduced_rule_ids=(),
                protected_target_keys=(
                    ("full_suite_fallback_enabled",)
                    if "full-suite fallback" in message
                    else ()
                ),
                notes=message[:MAX_TEXT_CHARS],
            )
            return _validation_report(
                source_header=(
                    _header(source_header) if source_header is not None else None
                ),
                proposal_cid=None,
                mode=mode,
                safety=safety,
                blocking=[message[:MAX_TEXT_CHARS]],
                report_id=report_id,
                notes="proposal construction failed closed",
            )
    elif rules is not None:
        try:
            rule_list = _normalize_rules(rules)
            for rule in rule_list:
                _scan_text_fields(rule.identity_payload(), f"rule.{rule.rule_id}")
        except RuleProposalError as exc:
            message = str(exc)
            safety = RuleSafetyAnalysis(
                full_suite_fallback_disabled="full-suite fallback" in message,
                high_risk_assurance_reduced="full-suite fallback" in message,
                arbitrary_code_rejected=(
                    "arbitrary code" in message
                    or "expressions, imports" in message
                ),
                touches_protected_targets="full-suite fallback" in message,
                assurance_impact=(
                    AssuranceImpact.REDUCE
                    if "full-suite fallback" in message
                    else AssuranceImpact.NEUTRAL
                ),
                notes=message[:MAX_TEXT_CHARS],
            )
            return _validation_report(
                source_header=_header(source_header) if source_header is not None else None,
                proposal_cid=None,
                mode=mode,
                safety=safety,
                blocking=[message[:MAX_TEXT_CHARS]],
                report_id=report_id,
                notes="rule list rejected",
            )
    else:
        raise RuleProposalError("validate_rule_proposal requires proposal or rules")

    safety = analyze_rules_safety(
        rule_list,
        baseline_rules=baseline_rules,
        protected_thresholds=thresholds,
    )

    if safety.arbitrary_code_rejected:
        blocking.append("arbitrary code cannot execute")
    if safety.full_suite_fallback_disabled:
        blocking.append("full-suite fallback cannot be disabled")
    if mode == ProposalMode.NORMAL.value and safety.high_risk_assurance_reduced:
        blocking.append(
            "high-risk assurance cannot be reduced in a normal proposal"
        )
    if mode == ProposalMode.AUTHORIZED.value and safety.high_risk_assurance_reduced:
        auth = _optional_cid(external_authorization_cid, "external_authorization_cid")
        if auth is None:
            blocking.append(
                "authorized assurance reduction requires distinct external authorization"
            )
        else:
            forbidden = {
                _cid(item, "forbidden_self_cids") for item in forbidden_self_cids
            }
            if proposal_cid is not None:
                forbidden.add(proposal_cid)
            if auth in forbidden:
                blocking.append(
                    "candidates cannot self-authorize high-risk assurance reduction"
                )

    # Threshold floor: require_full_suite_fallback must remain true on thresholds.
    if not thresholds.require_full_suite_fallback:
        blocking.append("protected thresholds require_full_suite_fallback must be true")
        safety = RuleSafetyAnalysis(
            full_suite_fallback_disabled=True,
            high_risk_assurance_reduced=True,
            arbitrary_code_rejected=safety.arbitrary_code_rejected,
            touches_protected_targets=True,
            assurance_impact=AssuranceImpact.REDUCE,
            reduced_rule_ids=safety.reduced_rule_ids,
            protected_target_keys=tuple(
                sorted(set(safety.protected_target_keys) | {"full_suite_fallback_enabled"})
            ),
            notes="protected thresholds disabled full-suite fallback",
        )

    if blocking:
        verdict = ValidationVerdict.REJECT
        terminal = GovernorTerminalStatus.REJECTED
    else:
        verdict = ValidationVerdict.ACCEPT
        terminal = GovernorTerminalStatus.COMPLETE

    header_source = None
    if proposal_obj is not None:
        header_source = proposal_obj.header
    elif source_header is not None:
        header_source = _header(source_header)

    return _validation_report(
        source_header=header_source,
        proposal_cid=proposal_cid,
        mode=mode,
        safety=safety,
        blocking=blocking,
        report_id=report_id,
        notes=None if not blocking else "validation rejected proposal",
        verdict=verdict,
        terminal=terminal,
    )


def _synthetic_cid_header_seed(label: str = "seed") -> str:
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes

    return cid_for_bytes(f"semantic-governor-rules-{label}".encode("utf-8"))


def _validation_report(
    *,
    source_header: GovernorArtifactHeader | None,
    proposal_cid: str | None,
    mode: str,
    safety: RuleSafetyAnalysis,
    blocking: Sequence[str],
    report_id: str | None,
    notes: str | None,
    verdict: ValidationVerdict | None = None,
    terminal: GovernorTerminalStatus | None = None,
) -> RuleProposalValidationReport:
    if verdict is None:
        verdict = (
            ValidationVerdict.REJECT if blocking else ValidationVerdict.ACCEPT
        )
    if terminal is None:
        terminal = (
            GovernorTerminalStatus.REJECTED
            if verdict == ValidationVerdict.REJECT
            else GovernorTerminalStatus.COMPLETE
        )
    if source_header is None:
        source_header = GovernorArtifactHeader(
            artifact_kind="rule_proposal",
            repository_state_cid=_synthetic_cid_header_seed("repo"),
            context_pack_cid=_synthetic_cid_header_seed("context"),
            verification_bundle_cid=_synthetic_cid_header_seed("verify"),
            generator=GeneratorIdentity(
                generator_id=GENERATOR_ID,
                generator_version=GENERATOR_VERSION,
                interface_id=VALIDATE_RULE_PROPOSAL_INTERFACE,
            ),
            provenance=ArtifactProvenance(
                producer_id=PRODUCER_ID,
                producer_version=PRODUCER_VERSION,
                execution_mode=ExecutionMode.LIVE,
                authority_source=AuthoritySource.DETERMINISTIC,
                input_cids=(_synthetic_cid_header_seed("input"),),
                tool_ids=(TOOL_ID,),
                policy_cid=_synthetic_cid_header_seed("policy"),
                notes=None,
            ),
            terminal_status=GovernorTerminalStatus.COMPLETE,
            assumptions=(),
            metadata={"track": "rule_proposals"},
        )
    input_cids = list(source_header.provenance.input_cids)
    if proposal_cid is not None:
        input_cids.append(proposal_cid)
    header = _build_header(
        artifact_kind="rule_proposal_validation_report",
        source_header=source_header,
        input_cids=input_cids,
        interface_id=VALIDATE_RULE_PROPOSAL_INTERFACE,
        terminal_status=terminal,
        metadata={
            "track": "rule_proposals",
            "verdict": verdict.value if isinstance(verdict, ValidationVerdict) else verdict,
            "proposal_mode": mode,
        },
    )
    rid = report_id or "rule_proposal_validation"
    rid = re.sub(r"[^a-z0-9_.:/+-]", "_", rid.lower())[:128]
    if not rid or rid[0] not in "abcdefghijklmnopqrstuvwxyz":
        rid = f"r_{rid}"[:128]
    return RuleProposalValidationReport(
        header=header,
        report_id=rid,
        proposal_cid=proposal_cid,
        proposal_mode=mode,
        verdict=verdict,
        safety=safety,
        blocking_reasons=tuple(blocking),
        notes=notes,
        metadata={"track": "rule_proposals"},
    )


# ---------------------------------------------------------------------------
# Public: propose_rule_change
# ---------------------------------------------------------------------------


def propose_rule_change(
    calibration_profile: CalibrationProfile | Mapping[str, Any],
    audit_cases: Sequence[CompressionAuditCase | Mapping[str, Any]] | None = None,
    *,
    current_policy: CompressionPolicy | Mapping[str, Any] | None = None,
    current_policy_version: str | None = None,
    current_policy_cid: str | None = None,
    benchmark_cid: str | None = None,
    rollback_policy_cid: str | None = None,
    scope_token: str | None = None,
    protected_thresholds: ProtectedThresholds | Mapping[str, Any] | None = None,
    draft_rules: Sequence[DeclarativeRule | Mapping[str, Any]] | None = None,
    proposal_mode: ProposalMode | str = ProposalMode.NORMAL,
    external_authorization_cid: str | None = None,
    max_rules: int = 32,
    proposal_id: str | None = None,
    return_result: bool = True,
) -> RuleProposalResult | RuleProposal:
    """Generate an evidence-bound bounded declarative rule proposal.

    Parameters
    ----------
    calibration_profile:
        Capsule / analyzer / task-class / model-route calibration artifact.
    audit_cases:
        Supporting sealed audit cases (CIDs bound into the proposal).
    current_policy / current_policy_version / current_policy_cid:
        Baseline policy identity. When a full policy is provided, its version,
        CID, rules, and protected thresholds are used as defaults.
    draft_rules:
        Optional explicit rules to package (still validated; normal mode
        rejects high-risk assurance reductions and full-suite disable).
    proposal_mode:
        ``normal`` (default) forbids assurance reduction; ``authorized``
        requires a distinct external authorization CID for reductions.

    Returns
    -------
    RuleProposalResult
        Disposition, safety analysis, and sealed proposal when admitted.
        Set ``return_result=False`` to receive only the ``RuleProposal`` on
        success (raises on rejection).
    """

    profile = _normalize_profile(calibration_profile)
    cases = _normalize_audit_cases(audit_cases)
    mode = _enum(proposal_mode, ProposalMode, "proposal_mode")
    policy = _normalize_policy(current_policy)
    thresholds = _normalize_thresholds(
        protected_thresholds
        if protected_thresholds is not None
        else (policy.protected_thresholds if policy is not None else None)
    )
    max_rules_n = _nonneg_int(max_rules, "max_rules")
    if max_rules_n == 0 or max_rules_n > MAX_RULES:
        raise RuleProposalError(f"max_rules must be in 1..{MAX_RULES}")

    profile_cid = _profile_cid(profile)
    source_header = _profile_header(profile)
    signals = _collect_signals(profile)

    # Held-out evidence cannot generate promotion candidates.
    if _profile_partition(profile) == EvidencePartition.HELD_OUT.value:
        safety = RuleSafetyAnalysis(
            full_suite_fallback_disabled=False,
            high_risk_assurance_reduced=False,
            arbitrary_code_rejected=False,
            touches_protected_targets=False,
            assurance_impact=AssuranceImpact.NEUTRAL,
            notes="held-out partition cannot generate rule proposals",
        )
        return _proposal_result(
            source_header=source_header,
            disposition=RuleProposalDisposition.REJECTED,
            proposal=None,
            safety=safety,
            profile_cid=profile_cid,
            audit_cids=tuple(case.case_cid for case in cases),
            blocking=["held-out partition cannot generate rule proposals"],
            notes="held-out partition cannot generate rule proposals",
            return_result=return_result,
        )

    # Reject simulated-only support as sole live evidence (if all cases simulated).
    live_cases = [
        case
        for case in cases
        if case.header.provenance.execution_mode != ExecutionMode.SIMULATED.value
        and case.header.terminal_status != GovernorTerminalStatus.SIMULATED.value
    ]
    supporting_cids = tuple(sorted({case.case_cid for case in live_cases}))
    # Also accept profile-linked source audits when cases omitted.
    if not supporting_cids:
        source_audits = getattr(profile, "source_audit_cids", ()) or ()
        supporting_cids = tuple(sorted(source_audits))

    baseline_rules: tuple[DeclarativeRule, ...] = ()
    if policy is not None:
        baseline_rules = tuple(policy.rules)
        policy_version = policy.policy_version
        policy_cid = policy.policy_cid
    else:
        policy_version = current_policy_version or "0.0.0"
        if current_policy_cid is not None:
            policy_cid = _cid(current_policy_cid, "current_policy_cid")
        elif source_header.provenance.policy_cid is not None:
            policy_cid = source_header.provenance.policy_cid
        else:
            policy_cid = _synthetic_cid_header_seed("policy")
    policy_version = _version(policy_version, "current_policy_version")

    scope = (
        _token(scope_token, "scope_token")
        if scope_token is not None
        else _token(_scope_from_profile(profile, signals), "scope_token")
    )

    if draft_rules is not None:
        try:
            generated = list(_normalize_rules(draft_rules))
        except RuleProposalError as exc:
            message = str(exc)
            safety = RuleSafetyAnalysis(
                full_suite_fallback_disabled="full-suite fallback" in message,
                high_risk_assurance_reduced="full-suite fallback" in message,
                arbitrary_code_rejected=(
                    "arbitrary code" in message or "expressions, imports" in message
                ),
                touches_protected_targets="full-suite fallback" in message,
                assurance_impact=(
                    AssuranceImpact.REDUCE
                    if "full-suite fallback" in message
                    else AssuranceImpact.NEUTRAL
                ),
                notes=message[:MAX_TEXT_CHARS],
            )
            return _proposal_result(
                source_header=source_header,
                disposition=RuleProposalDisposition.REJECTED,
                proposal=None,
                safety=safety,
                profile_cid=profile_cid,
                audit_cids=supporting_cids,
                blocking=[message[:MAX_TEXT_CHARS]],
                notes="draft_rules rejected",
                return_result=return_result,
            )
    else:
        generated = _generate_rules_from_evidence(
            signals,
            scope_token=scope,
            thresholds=thresholds,
            baseline_rules=baseline_rules,
            max_rules=max_rules_n,
        )

    if not generated:
        safety = RuleSafetyAnalysis(
            full_suite_fallback_disabled=False,
            high_risk_assurance_reduced=False,
            arbitrary_code_rejected=False,
            touches_protected_targets=False,
            assurance_impact=AssuranceImpact.NEUTRAL,
            notes="no evidence-bound rule changes generated",
        )
        return _proposal_result(
            source_header=source_header,
            disposition=RuleProposalDisposition.NO_CHANGE,
            proposal=None,
            safety=safety,
            profile_cid=profile_cid,
            audit_cids=supporting_cids,
            blocking=(),
            notes="no evidence-bound rule changes generated",
            return_result=return_result,
        )

    safety = analyze_rules_safety(
        generated,
        baseline_rules=baseline_rules,
        protected_thresholds=thresholds,
    )

    blocking: list[str] = []
    if safety.arbitrary_code_rejected:
        blocking.append("arbitrary code cannot execute")
    if safety.full_suite_fallback_disabled:
        blocking.append("full-suite fallback cannot be disabled")
    if mode == ProposalMode.NORMAL.value and safety.high_risk_assurance_reduced:
        blocking.append(
            "high-risk assurance cannot be reduced in a normal proposal"
        )
    if mode == ProposalMode.AUTHORIZED.value and safety.high_risk_assurance_reduced:
        auth = _optional_cid(external_authorization_cid, "external_authorization_cid")
        if auth is None:
            blocking.append(
                "authorized assurance reduction requires distinct external authorization"
            )

    if blocking:
        return _proposal_result(
            source_header=source_header,
            disposition=RuleProposalDisposition.REJECTED,
            proposal=None,
            safety=safety,
            profile_cid=profile_cid,
            audit_cids=supporting_cids,
            blocking=blocking,
            notes="proposal rejected by safety gates",
            return_result=return_result,
        )

    bench = (
        _cid(benchmark_cid, "benchmark_cid")
        if benchmark_cid is not None
        else (
            cases[0].coverage_manifest_cid
            if cases
            else _synthetic_cid_header_seed("benchmark")
        )
    )
    rollback = (
        _cid(rollback_policy_cid, "rollback_policy_cid")
        if rollback_policy_cid is not None
        else policy_cid
    )

    pid = proposal_id or f"prop_{scope}_{profile_cid[-8:]}"
    pid = re.sub(r"[^a-z0-9_.:/+-]", "_", pid.lower())[:128]
    if not pid or pid[0] not in "abcdefghijklmnopqrstuvwxyz":
        pid = f"p_{pid}"[:128]

    input_cids = [profile_cid, policy_cid, *supporting_cids]
    header = _build_header(
        artifact_kind="rule_proposal",
        source_header=source_header,
        input_cids=input_cids,
        interface_id=PROPOSE_RULE_CHANGE_INTERFACE,
        terminal_status=GovernorTerminalStatus.COMPLETE,
        metadata={
            "track": "rule_proposals",
            "scope": scope,
            "rule_count": len(generated),
            "proposal_mode": mode,
        },
    )

    try:
        proposal = RuleProposal(
            header=header,
            proposal_id=pid,
            current_policy_version=policy_version,
            current_policy_cid=policy_cid,
            proposed_rules=tuple(generated),
            supporting_audit_cids=supporting_cids,
            benefit_statement=_benefit_statement(signals, generated),
            safety_impact=_safety_impact_statement(safety),
            scope_token=scope,
            benchmark_cid=bench,
            rollback_policy_cid=rollback,
            calibration_profile_cids=(profile_cid,),
            notes=None,
            metadata={
                "track": "rule_proposals",
                "categories": sorted({rule.category for rule in generated}),
                "assurance_impact": safety.assurance_impact,
            },
        )
    except (PolicyContractError, SemanticGovernorBaseError) as exc:
        message = str(exc)
        return _proposal_result(
            source_header=source_header,
            disposition=RuleProposalDisposition.REJECTED,
            proposal=None,
            safety=RuleSafetyAnalysis(
                full_suite_fallback_disabled="full-suite fallback" in message,
                high_risk_assurance_reduced="full-suite fallback" in message,
                arbitrary_code_rejected="expressions, imports" in message,
                touches_protected_targets=True,
                assurance_impact=AssuranceImpact.NEUTRAL,
                notes=message[:MAX_TEXT_CHARS],
            ),
            profile_cid=profile_cid,
            audit_cids=supporting_cids,
            blocking=[message[:MAX_TEXT_CHARS]],
            notes="RuleProposal construction failed",
            return_result=return_result,
        )

    # Final gate: validate the sealed proposal.
    report = validate_rule_proposal(
        proposal,
        proposal_mode=mode,
        protected_thresholds=thresholds,
        baseline_rules=baseline_rules,
        external_authorization_cid=external_authorization_cid,
        forbidden_self_cids=(proposal.proposal_cid, profile_cid, policy_cid),
    )
    if report.verdict != ValidationVerdict.ACCEPT.value:
        return _proposal_result(
            source_header=source_header,
            disposition=RuleProposalDisposition.REJECTED,
            proposal=proposal,
            safety=report.safety,
            profile_cid=profile_cid,
            audit_cids=supporting_cids,
            blocking=list(report.blocking_reasons),
            notes="sealed proposal failed validate_rule_proposal",
            return_result=return_result,
        )

    return _proposal_result(
        source_header=source_header,
        disposition=RuleProposalDisposition.PROPOSED,
        proposal=proposal,
        safety=report.safety,
        profile_cid=profile_cid,
        audit_cids=supporting_cids,
        blocking=(),
        notes=None,
        return_result=return_result,
    )


def _proposal_result(
    *,
    source_header: GovernorArtifactHeader,
    disposition: RuleProposalDisposition,
    proposal: RuleProposal | None,
    safety: RuleSafetyAnalysis,
    profile_cid: str,
    audit_cids: Sequence[str],
    blocking: Sequence[str],
    notes: str | None,
    return_result: bool,
) -> RuleProposalResult | RuleProposal:
    if not return_result:
        if disposition == RuleProposalDisposition.PROPOSED and proposal is not None:
            return proposal
        raise RuleProposalError(
            notes or f"propose_rule_change disposition={disposition.value}"
        )

    terminal = {
        RuleProposalDisposition.PROPOSED: GovernorTerminalStatus.COMPLETE,
        RuleProposalDisposition.REJECTED: GovernorTerminalStatus.REJECTED,
        RuleProposalDisposition.NO_CHANGE: GovernorTerminalStatus.INCONCLUSIVE,
        RuleProposalDisposition.INCONCLUSIVE: GovernorTerminalStatus.INCONCLUSIVE,
    }[disposition]

    input_cids = [profile_cid, *audit_cids]
    if proposal is not None:
        input_cids.append(proposal.proposal_cid)
    header = _build_header(
        artifact_kind="rule_proposal_result",
        source_header=source_header,
        input_cids=input_cids,
        interface_id=PROPOSE_RULE_CHANGE_INTERFACE,
        terminal_status=terminal,
        metadata={
            "track": "rule_proposals",
            "disposition": disposition.value,
        },
    )
    result_id = f"res_{disposition.value}_{profile_cid[-10:]}"
    result_id = re.sub(r"[^a-z0-9_.:/+-]", "_", result_id.lower())[:128]
    if not result_id or result_id[0] not in "abcdefghijklmnopqrstuvwxyz":
        result_id = f"r_{result_id}"[:128]

    return RuleProposalResult(
        header=header,
        result_id=result_id,
        disposition=disposition,
        proposal=proposal,
        safety=safety,
        calibration_profile_cid=profile_cid,
        supporting_audit_cids=tuple(audit_cids),
        blocking_reasons=tuple(blocking),
        notes=notes,
        metadata={"track": "rule_proposals"},
    )


# ---------------------------------------------------------------------------
# Interface pins / vocabulary
# ---------------------------------------------------------------------------


def propose_rule_change_interface_id() -> str:
    """Return the versioned public interface pin for proposal generation."""

    return PROPOSE_RULE_CHANGE_INTERFACE


def validate_rule_proposal_interface_id() -> str:
    """Return the versioned public interface pin for proposal validation."""

    return VALIDATE_RULE_PROPOSAL_INTERFACE


def proposal_modes() -> tuple[str, ...]:
    """Return the closed proposal-mode vocabulary."""

    return tuple(item.value for item in ProposalMode)


def rule_proposal_dispositions() -> tuple[str, ...]:
    """Return the closed proposal-disposition vocabulary."""

    return tuple(item.value for item in RuleProposalDisposition)


def assurance_impacts() -> tuple[str, ...]:
    """Return the closed assurance-impact vocabulary."""

    return tuple(item.value for item in AssuranceImpact)


def validation_verdicts() -> tuple[str, ...]:
    """Return the closed validation-verdict vocabulary."""

    return tuple(item.value for item in ValidationVerdict)


def allowlisted_rule_target_keys() -> tuple[str, ...]:
    """Return sorted allowlisted declarative rule target keys."""

    return tuple(sorted(ALLOWED_RULE_TARGET_KEYS))


def protected_rule_target_keys() -> tuple[str, ...]:
    """Return sorted protected rule target keys."""

    return tuple(sorted(PROTECTED_RULE_TARGET_KEYS))


__all__ = [
    "PROPOSE_RULE_CHANGE_INTERFACE",
    "VALIDATE_RULE_PROPOSAL_INTERFACE",
    "RULE_PROPOSAL_RESULT_SCHEMA",
    "RULE_PROPOSAL_VALIDATION_SCHEMA",
    "RULE_SAFETY_ANALYSIS_SCHEMA",
    "AssuranceImpact",
    "ProposalMode",
    "RuleProposalDisposition",
    "RuleProposalError",
    "RuleProposalResult",
    "RuleProposalValidationReport",
    "RuleSafetyAnalysis",
    "ValidationVerdict",
    "aggregate_assurance_impact",
    "allowlisted_rule_target_keys",
    "analyze_rule_assurance_impact",
    "analyze_rules_safety",
    "assurance_impacts",
    "is_high_risk_assurance_reduction",
    "proposal_modes",
    "propose_rule_change",
    "propose_rule_change_interface_id",
    "protected_rule_target_keys",
    "rule_proposal_dispositions",
    "validate_rule_proposal",
    "validate_rule_proposal_interface_id",
    "validation_verdicts",
]
