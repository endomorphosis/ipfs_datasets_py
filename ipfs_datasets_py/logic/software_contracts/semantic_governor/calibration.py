"""Empirical capsule, analyzer, task-class, and route calibration (SCG-016).

Pure, deterministic calibration updates over sealed audit cases and current
profiles defined by ``calibration_contracts``. Empirical statistics may change
routing and audit frequency only; they never upgrade formal proof
classification to ``exact``.

Normative rules:

* Simulated execution outputs are excluded from live quality counters.
* Concurrent or replayed inputs are idempotent by sealed audit-case CID.
* ``false_exact_classification_count`` and ``stale_failure_count`` remain
  explicit counters and are never folded only into a generic rate.
* Rates and confidence intervals use integer basis points (no durable floats).
* Canonical identity uses ``software_contracts.content`` only.
* Identical verified inputs yield identical update identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import ceil, floor, sqrt
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
    CalibrationContractError,
    CapsuleCalibrationRecord,
    ClassificationSource,
    EmpiricalRate,
    EvidencePartition,
    ModelRouteCalibrationProfile,
    ProofClassification,
    TaskClassCalibrationProfile,
    assert_proof_classification_allowed,
    ratio_to_basis_points,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

UPDATE_CALIBRATION_INTERFACE: Final[str] = "update_calibration@1"
MERGE_CALIBRATION_PROFILES_INTERFACE: Final[str] = "merge_calibration_profiles@1"
CALIBRATION_UPDATE_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-calibration-update@1"
)
CALIBRATION_OBSERVATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-calibration-observation@1"
)
CALIBRATION_MERGE_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-calibration-merge@1"
)

GENERATOR_ID: Final[str] = "calibration_updater"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "calibration.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_REVISION: Final[int] = 2**63 - 1
MAX_COUNTER: Final[int] = 2**63 - 1

# Wilson score z for ~95% two-sided interval, scaled to avoid durable floats.
# z ≈ 1.96; work in units of 1/1000 so z_milli = 1960.
_WILSON_Z_MILLI: Final[int] = 1960
_WILSON_Z2_MICRO: Final[int] = _WILSON_Z_MILLI * _WILSON_Z_MILLI  # 3_841_600
_INTERVAL_METHOD: Final[str] = "wilson_score_95"

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")

CalibrationProfile = Union[
    CapsuleCalibrationRecord,
    AnalyzerCalibrationProfile,
    TaskClassCalibrationProfile,
    ModelRouteCalibrationProfile,
]


# ---------------------------------------------------------------------------
# Errors and closed enumerations
# ---------------------------------------------------------------------------


class CalibrationError(SemanticGovernorBaseError):
    """Raised when empirical calibration fails closed."""


class CalibrationKind(str, Enum):
    """Which durable calibration artifact is being updated or merged."""

    CAPSULE = "capsule"
    ANALYZER = "analyzer"
    TASK_CLASS = "task_class"
    MODEL_ROUTE = "model_route"


class CalibrationDisposition(str, Enum):
    """Closed dispositions for a single calibration update attempt."""

    APPLIED = "applied"
    SKIPPED_SIMULATED = "skipped_simulated"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"
    SKIPPED_PARTITION_MISMATCH = "skipped_partition_mismatch"
    REJECTED_STALE_REVISION = "rejected_stale_revision"
    REJECTED_KEY_MISMATCH = "rejected_key_mismatch"


class ComparativeOutcome(str, Enum):
    """Closed comparative outcomes used to attribute calibration counters."""

    EQUIVALENT_SUCCESS = "equivalent_success"
    COMPRESSED_BETTER = "compressed_better"
    EXPANDED_BETTER = "expanded_better"
    BOTH_VALID_DIFFERENT = "both_valid_different"
    COMPRESSED_FAILED_EXPANDED_SUCCEEDED = "compressed_failed_expanded_succeeded"
    COMPRESSED_SUCCEEDED_EXPANDED_FAILED = "compressed_succeeded_expanded_failed"
    BOTH_FAILED_SAME_REASON = "both_failed_same_reason"
    BOTH_FAILED_DIFFERENT_REASON = "both_failed_different_reason"
    VERIFICATION_INCONCLUSIVE = "verification_inconclusive"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


_COMPRESSED_SUCCESS_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        ComparativeOutcome.EQUIVALENT_SUCCESS.value,
        ComparativeOutcome.COMPRESSED_BETTER.value,
        ComparativeOutcome.BOTH_VALID_DIFFERENT.value,
        ComparativeOutcome.COMPRESSED_SUCCEEDED_EXPANDED_FAILED.value,
    }
)
_EXPANDED_SUCCESS_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        ComparativeOutcome.EQUIVALENT_SUCCESS.value,
        ComparativeOutcome.EXPANDED_BETTER.value,
        ComparativeOutcome.BOTH_VALID_DIFFERENT.value,
        ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED.value,
    }
)
_OMISSION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED.value,
        ComparativeOutcome.EXPANDED_BETTER.value,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise CalibrationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise CalibrationError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise CalibrationError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise CalibrationError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CalibrationError(f"{name} must be a valid CID") from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CalibrationError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise CalibrationError(f"{name} must be a nonnegative integer")
    if value > MAX_COUNTER:
        raise CalibrationError(f"{name} exceeds maximum")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"{name} has unsupported value {value!r}") from exc


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
        raise CalibrationError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalibrationError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise CalibrationError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise CalibrationError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CalibrationError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise CalibrationError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise CalibrationError(f"{name} must not contain duplicates")
    return ordered


def _add_counter(left: int, right: int, name: str) -> int:
    total = _nonneg_int(left, name) + _nonneg_int(right, name)
    if total > MAX_COUNTER:
        raise CalibrationError(f"{name} overflow")
    return total


def _union_cids(
    left: Sequence[str],
    right: Sequence[str],
    name: str,
) -> tuple[str, ...]:
    merged = sorted(set(left) | set(right))
    if len(merged) > MAX_CID_LIST:
        raise CalibrationError(f"{name} exceeds maximum length")
    return tuple(merged)


# ---------------------------------------------------------------------------
# Empirical rate helpers (integer Wilson score)
# ---------------------------------------------------------------------------


def wilson_score_interval_bp(
    successes: int,
    trials: int,
) -> tuple[int, int, int]:
    """Return ``(rate_bp, lower_bp, upper_bp)`` for a Wilson 95% interval.

    Intermediate arithmetic may use host floats; the returned values are
    integers in ``[0, 10000]`` only. Empty populations yield ``(0, 0, 0)``.
    """

    successes = _nonneg_int(successes, "successes")
    trials = _nonneg_int(trials, "trials")
    if successes > trials:
        raise CalibrationError("successes must not exceed trials")
    if trials == 0:
        return 0, 0, 0
    rate_bp = ratio_to_basis_points(successes, trials)
    assert rate_bp is not None
    # Wilson score interval with z = 1.96.
    p = successes / trials
    z = _WILSON_Z_MILLI / 1000.0
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2.0 * trials)) / denom
    radius = (
        z
        * sqrt(p * (1.0 - p) / trials + z2 / (4.0 * trials * trials))
        / denom
    )
    lower = max(0.0, center - radius)
    upper = min(1.0, center + radius)
    lower_bp = max(0, min(BASIS_POINTS, floor(lower * BASIS_POINTS)))
    upper_bp = max(0, min(BASIS_POINTS, ceil(upper * BASIS_POINTS)))
    if lower_bp > rate_bp:
        lower_bp = rate_bp
    if upper_bp < rate_bp:
        upper_bp = rate_bp
    if lower_bp > upper_bp:
        lower_bp, upper_bp = upper_bp, lower_bp
    return rate_bp, lower_bp, upper_bp


def build_empirical_rate(successes: int, trials: int) -> EmpiricalRate:
    """Build an ``EmpiricalRate`` with Wilson 95% integer bounds."""

    rate_bp, lower_bp, upper_bp = wilson_score_interval_bp(successes, trials)
    try:
        return EmpiricalRate(
            successes=successes,
            trials=trials,
            rate_bp=rate_bp,
            interval_lower_bp=lower_bp,
            interval_upper_bp=upper_bp,
            interval_method=_INTERVAL_METHOD,
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _normalize_empirical_rate(
    value: EmpiricalRate | Mapping[str, Any],
    name: str,
) -> EmpiricalRate:
    if isinstance(value, EmpiricalRate):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return EmpiricalRate.from_dict(value)
            return build_empirical_rate(
                int(value.get("successes", 0)),
                int(value.get("trials", 0)),
            )
        except (TypeError, ValueError, CalibrationContractError) as exc:
            raise CalibrationError(f"{name} is not a valid EmpiricalRate") from exc
    raise CalibrationError(f"{name} must be EmpiricalRate or mapping")


# ---------------------------------------------------------------------------
# Observation (closed counters for one audit case)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    """Closed, integer-only observation derived from one audit evaluation.

    Explicit boolean failure flags keep false-exact and stale events distinct
    from generic omission failures. Simulated observations never contribute to
    live quality even when counters are present.
    """

    observation_id: str
    partition: EvidencePartition | str
    capsule_class: str
    language: str
    symbol_kind: str
    framework: str
    analyzer_feature: str
    analyzer_id: str
    analyzer_version: str
    repository_family: str
    task_class: str
    risk_class: str
    route_id: str
    route_tier: str
    proof_classification: ProofClassification | str
    classification_source: ClassificationSource | str
    comparative_outcome: ComparativeOutcome | str
    compressed_success: bool
    expanded_success: bool
    omission_failure: bool
    stale_failure: bool
    false_exact_classification: bool
    unnecessary_raw_fallback: bool
    review_disagreement: bool
    escalated: bool
    retried: bool
    shadow_sampled: bool
    token_savings: int
    verification_cost: int
    route_success: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "observation_id",
            "partition",
            "capsule_class",
            "language",
            "symbol_kind",
            "framework",
            "analyzer_feature",
            "analyzer_id",
            "analyzer_version",
            "repository_family",
            "task_class",
            "risk_class",
            "route_id",
            "route_tier",
            "proof_classification",
            "classification_source",
            "comparative_outcome",
            "compressed_success",
            "expanded_success",
            "omission_failure",
            "stale_failure",
            "false_exact_classification",
            "unnecessary_raw_fallback",
            "review_disagreement",
            "escalated",
            "retried",
            "shadow_sampled",
            "token_savings",
            "verification_cost",
            "route_success",
            "metadata",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _token(self.observation_id, "observation_id")
        )
        object.__setattr__(
            self, "partition", _enum(self.partition, EvidencePartition, "partition")
        )
        for name in (
            "capsule_class",
            "language",
            "symbol_kind",
            "framework",
            "analyzer_feature",
            "analyzer_id",
            "repository_family",
            "task_class",
            "risk_class",
            "route_id",
            "route_tier",
        ):
            object.__setattr__(self, name, _token(getattr(self, name), name))
        object.__setattr__(
            self, "analyzer_version", _text(self.analyzer_version, "analyzer_version")
        )
        classification = _enum(
            self.proof_classification, ProofClassification, "proof_classification"
        )
        source = _enum(
            self.classification_source, ClassificationSource, "classification_source"
        )
        try:
            assert_proof_classification_allowed(classification, source)
        except CalibrationContractError as exc:
            raise CalibrationError(str(exc)) from exc
        object.__setattr__(self, "proof_classification", classification)
        object.__setattr__(self, "classification_source", source)
        object.__setattr__(
            self,
            "comparative_outcome",
            _enum(self.comparative_outcome, ComparativeOutcome, "comparative_outcome"),
        )
        for name in (
            "compressed_success",
            "expanded_success",
            "omission_failure",
            "stale_failure",
            "false_exact_classification",
            "unnecessary_raw_fallback",
            "review_disagreement",
            "escalated",
            "retried",
            "shadow_sampled",
            "route_success",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        object.__setattr__(
            self, "token_savings", _nonneg_int(self.token_savings, "token_savings")
        )
        object.__setattr__(
            self,
            "verification_cost",
            _nonneg_int(self.verification_cost, "verification_cost"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        # Explicit false-exact / stale events must not be silently reclassified.
        if self.false_exact_classification and not self.stale_failure:
            # Allowed: false exact alone is still explicit.
            pass

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_OBSERVATION_SCHEMA,
            "observation_id": self.observation_id,
            "partition": self.partition,
            "capsule_class": self.capsule_class,
            "language": self.language,
            "symbol_kind": self.symbol_kind,
            "framework": self.framework,
            "analyzer_feature": self.analyzer_feature,
            "analyzer_id": self.analyzer_id,
            "analyzer_version": self.analyzer_version,
            "repository_family": self.repository_family,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "route_id": self.route_id,
            "route_tier": self.route_tier,
            "proof_classification": self.proof_classification,
            "classification_source": self.classification_source,
            "comparative_outcome": self.comparative_outcome,
            "compressed_success": self.compressed_success,
            "expanded_success": self.expanded_success,
            "omission_failure": self.omission_failure,
            "stale_failure": self.stale_failure,
            "false_exact_classification": self.false_exact_classification,
            "unnecessary_raw_fallback": self.unnecessary_raw_fallback,
            "review_disagreement": self.review_disagreement,
            "escalated": self.escalated,
            "retried": self.retried,
            "shadow_sampled": self.shadow_sampled,
            "token_savings": self.token_savings,
            "verification_cost": self.verification_cost,
            "route_success": self.route_success,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["observation_cid"] = self.observation_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationObservation":
        fields = set(cls._FIELDS)
        payload = dict(data)
        payload.pop("observation_cid", None)
        if set(payload) != fields:
            raise CalibrationError(
                "CalibrationObservation fields must be exactly "
                f"{sorted(fields)}, got {sorted(payload)}"
            )
        if payload.pop("schema") != CALIBRATION_OBSERVATION_SCHEMA:
            raise CalibrationError("unsupported CalibrationObservation schema version")
        return cls(**payload)


def observation_from_outcome(
    *,
    observation_id: str,
    partition: EvidencePartition | str,
    comparative_outcome: ComparativeOutcome | str,
    capsule_class: str = "function_capsule",
    language: str = "python",
    symbol_kind: str = "function",
    framework: str = "pytest",
    analyzer_feature: str = "callgraph",
    analyzer_id: str = "callgraph",
    analyzer_version: str = "1.0.0",
    repository_family: str = "default",
    task_class: str = "local_bug",
    risk_class: str = "low",
    route_id: str = "standard_v1",
    route_tier: str = "standard",
    proof_classification: ProofClassification | str = ProofClassification.HEURISTIC,
    classification_source: ClassificationSource | str = ClassificationSource.EMPIRICAL,
    stale_failure: bool = False,
    false_exact_classification: bool = False,
    unnecessary_raw_fallback: bool = False,
    review_disagreement: bool = False,
    escalated: bool = False,
    retried: bool = False,
    shadow_sampled: bool = False,
    token_savings: int = 0,
    verification_cost: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> CalibrationObservation:
    """Derive closed observation flags from a comparative outcome."""

    outcome = _enum(comparative_outcome, ComparativeOutcome, "comparative_outcome")
    compressed_success = outcome in _COMPRESSED_SUCCESS_OUTCOMES
    expanded_success = outcome in _EXPANDED_SUCCESS_OUTCOMES
    omission_failure = outcome in _OMISSION_OUTCOMES
    route_success = compressed_success or (
        outcome == ComparativeOutcome.EQUIVALENT_SUCCESS.value
    )
    return CalibrationObservation(
        observation_id=observation_id,
        partition=partition,
        capsule_class=capsule_class,
        language=language,
        symbol_kind=symbol_kind,
        framework=framework,
        analyzer_feature=analyzer_feature,
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        repository_family=repository_family,
        task_class=task_class,
        risk_class=risk_class,
        route_id=route_id,
        route_tier=route_tier,
        proof_classification=proof_classification,
        classification_source=classification_source,
        comparative_outcome=outcome,
        compressed_success=compressed_success,
        expanded_success=expanded_success,
        omission_failure=omission_failure,
        stale_failure=stale_failure,
        false_exact_classification=false_exact_classification,
        unnecessary_raw_fallback=unnecessary_raw_fallback,
        review_disagreement=review_disagreement,
        escalated=escalated,
        retried=retried,
        shadow_sampled=shadow_sampled,
        token_savings=token_savings,
        verification_cost=verification_cost,
        route_success=route_success,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Result envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalibrationUpdateResult:
    """Deterministic result of one ``update_calibration`` call."""

    header: GovernorArtifactHeader
    update_id: str
    kind: CalibrationKind | str
    disposition: CalibrationDisposition | str
    audit_case_cid: str
    observation_cid: str | None
    previous_revision: int
    next_revision: int
    previous_profile_cid: str
    next_profile_cid: str
    applied_to_live_quality: bool
    false_exact_classification_count: int
    stale_failure_count: int
    omission_failure_count: int
    profile: CalibrationProfile
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "update_id",
            "kind",
            "disposition",
            "audit_case_cid",
            "observation_cid",
            "previous_revision",
            "next_revision",
            "previous_profile_cid",
            "next_profile_cid",
            "applied_to_live_quality",
            "false_exact_classification_count",
            "stale_failure_count",
            "omission_failure_count",
            "profile",
            "notes",
            "metadata",
            "update_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.header, GovernorArtifactHeader):
            raise CalibrationError("header must be GovernorArtifactHeader")
        object.__setattr__(self, "update_id", _token(self.update_id, "update_id"))
        object.__setattr__(self, "kind", _enum(self.kind, CalibrationKind, "kind"))
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, CalibrationDisposition, "disposition"),
        )
        object.__setattr__(
            self, "audit_case_cid", _cid(self.audit_case_cid, "audit_case_cid")
        )
        if self.observation_cid is not None:
            object.__setattr__(
                self,
                "observation_cid",
                _cid(self.observation_cid, "observation_cid"),
            )
        object.__setattr__(
            self,
            "previous_revision",
            _nonneg_int(self.previous_revision, "previous_revision"),
        )
        object.__setattr__(
            self, "next_revision", _nonneg_int(self.next_revision, "next_revision")
        )
        object.__setattr__(
            self,
            "previous_profile_cid",
            _cid(self.previous_profile_cid, "previous_profile_cid"),
        )
        object.__setattr__(
            self, "next_profile_cid", _cid(self.next_profile_cid, "next_profile_cid")
        )
        object.__setattr__(
            self,
            "applied_to_live_quality",
            _bool(self.applied_to_live_quality, "applied_to_live_quality"),
        )
        for name in (
            "false_exact_classification_count",
            "stale_failure_count",
            "omission_failure_count",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        if not isinstance(
            self.profile,
            (
                CapsuleCalibrationRecord,
                AnalyzerCalibrationProfile,
                TaskClassCalibrationProfile,
                ModelRouteCalibrationProfile,
            ),
        ):
            raise CalibrationError("profile must be a calibration contract record")
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if (
            self.disposition == CalibrationDisposition.APPLIED.value
            and not self.applied_to_live_quality
        ):
            raise CalibrationError(
                "applied disposition requires applied_to_live_quality"
            )
        if (
            self.disposition == CalibrationDisposition.SKIPPED_SIMULATED.value
            and self.applied_to_live_quality
        ):
            raise CalibrationError(
                "simulated outputs must be excluded from live quality"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_UPDATE_RESULT_SCHEMA,
            "interface_id": UPDATE_CALIBRATION_INTERFACE,
            "header": self.header.identity_payload(),
            "update_id": self.update_id,
            "kind": self.kind,
            "disposition": self.disposition,
            "audit_case_cid": self.audit_case_cid,
            "observation_cid": self.observation_cid,
            "previous_revision": self.previous_revision,
            "next_revision": self.next_revision,
            "previous_profile_cid": self.previous_profile_cid,
            "next_profile_cid": self.next_profile_cid,
            "applied_to_live_quality": self.applied_to_live_quality,
            "false_exact_classification_count": self.false_exact_classification_count,
            "stale_failure_count": self.stale_failure_count,
            "omission_failure_count": self.omission_failure_count,
            "profile": _profile_identity(self.profile),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def update_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_UPDATE_RESULT_SCHEMA,
            "interface_id": UPDATE_CALIBRATION_INTERFACE,
            "header": self.header.to_dict(),
            "update_id": self.update_id,
            "kind": self.kind,
            "disposition": self.disposition,
            "audit_case_cid": self.audit_case_cid,
            "observation_cid": self.observation_cid,
            "previous_revision": self.previous_revision,
            "next_revision": self.next_revision,
            "previous_profile_cid": self.previous_profile_cid,
            "next_profile_cid": self.next_profile_cid,
            "applied_to_live_quality": self.applied_to_live_quality,
            "false_exact_classification_count": self.false_exact_classification_count,
            "stale_failure_count": self.stale_failure_count,
            "omission_failure_count": self.omission_failure_count,
            "profile": _profile_to_dict(self.profile),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "update_cid": self.update_cid,
        }


@dataclass(frozen=True, slots=True)
class CalibrationMergeResult:
    """Deterministic result of merging two same-kind calibration profiles."""

    header: GovernorArtifactHeader
    merge_id: str
    kind: CalibrationKind | str
    left_profile_cid: str
    right_profile_cid: str
    merged_revision: int
    profile: CalibrationProfile
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.header, GovernorArtifactHeader):
            raise CalibrationError("header must be GovernorArtifactHeader")
        object.__setattr__(self, "merge_id", _token(self.merge_id, "merge_id"))
        object.__setattr__(self, "kind", _enum(self.kind, CalibrationKind, "kind"))
        object.__setattr__(
            self, "left_profile_cid", _cid(self.left_profile_cid, "left_profile_cid")
        )
        object.__setattr__(
            self, "right_profile_cid", _cid(self.right_profile_cid, "right_profile_cid")
        )
        object.__setattr__(
            self, "merged_revision", _nonneg_int(self.merged_revision, "merged_revision")
        )
        if not isinstance(
            self.profile,
            (
                CapsuleCalibrationRecord,
                AnalyzerCalibrationProfile,
                TaskClassCalibrationProfile,
                ModelRouteCalibrationProfile,
            ),
        ):
            raise CalibrationError("profile must be a calibration contract record")
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_MERGE_RESULT_SCHEMA,
            "interface_id": MERGE_CALIBRATION_PROFILES_INTERFACE,
            "header": self.header.identity_payload(),
            "merge_id": self.merge_id,
            "kind": self.kind,
            "left_profile_cid": self.left_profile_cid,
            "right_profile_cid": self.right_profile_cid,
            "merged_revision": self.merged_revision,
            "profile": _profile_identity(self.profile),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def merge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CALIBRATION_MERGE_RESULT_SCHEMA,
            "interface_id": MERGE_CALIBRATION_PROFILES_INTERFACE,
            "header": self.header.to_dict(),
            "merge_id": self.merge_id,
            "kind": self.kind,
            "left_profile_cid": self.left_profile_cid,
            "right_profile_cid": self.right_profile_cid,
            "merged_revision": self.merged_revision,
            "profile": _profile_to_dict(self.profile),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "merge_cid": self.merge_cid,
        }


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------


def _profile_kind(profile: CalibrationProfile) -> str:
    if isinstance(profile, CapsuleCalibrationRecord):
        return CalibrationKind.CAPSULE.value
    if isinstance(profile, AnalyzerCalibrationProfile):
        return CalibrationKind.ANALYZER.value
    if isinstance(profile, TaskClassCalibrationProfile):
        return CalibrationKind.TASK_CLASS.value
    if isinstance(profile, ModelRouteCalibrationProfile):
        return CalibrationKind.MODEL_ROUTE.value
    raise CalibrationError("unsupported calibration profile type")


def _profile_cid(profile: CalibrationProfile) -> str:
    if isinstance(profile, CapsuleCalibrationRecord):
        return profile.record_cid
    return profile.profile_cid  # type: ignore[union-attr]


def _profile_revision(profile: CalibrationProfile) -> int:
    return int(profile.revision)


def _profile_partition(profile: CalibrationProfile) -> str:
    return str(profile.partition)


def _profile_source_cids(profile: CalibrationProfile) -> tuple[str, ...]:
    if isinstance(profile, CapsuleCalibrationRecord):
        return tuple(profile.source_audit_cids)
    return tuple(profile.record_cids)  # type: ignore[union-attr]


def _profile_identity(profile: CalibrationProfile) -> dict[str, Any]:
    return profile.identity_payload()


def _profile_to_dict(profile: CalibrationProfile) -> dict[str, Any]:
    return profile.to_dict()


def _normalize_profile(
    value: CalibrationProfile | Mapping[str, Any],
) -> CalibrationProfile:
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
    if not isinstance(value, Mapping):
        raise CalibrationError("current_profile must be a calibration profile mapping")
    schema = value.get("schema")
    try:
        from ipfs_datasets_py.logic.software_contracts.semantic_governor import (
            calibration_contracts as _cc,
        )

        if schema == _cc.CAPSULE_CALIBRATION_RECORD_SCHEMA:
            return CapsuleCalibrationRecord.from_dict(value)
        if schema == _cc.ANALYZER_CALIBRATION_PROFILE_SCHEMA:
            return AnalyzerCalibrationProfile.from_dict(value)
        if schema == _cc.TASK_CLASS_CALIBRATION_PROFILE_SCHEMA:
            return TaskClassCalibrationProfile.from_dict(value)
        if schema == _cc.MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA:
            return ModelRouteCalibrationProfile.from_dict(value)
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc
    raise CalibrationError(f"unsupported calibration profile schema {schema!r}")


def _normalize_audit_case(
    value: CompressionAuditCase | Mapping[str, Any],
) -> CompressionAuditCase:
    if isinstance(value, CompressionAuditCase):
        return value
    if isinstance(value, Mapping):
        try:
            return CompressionAuditCase.from_dict(value)
        except Exception as exc:
            raise CalibrationError(f"invalid CompressionAuditCase: {exc}") from exc
    raise CalibrationError("audit_case must be CompressionAuditCase or mapping")


def _normalize_observation(
    value: CalibrationObservation | Mapping[str, Any] | None,
    audit_case: CompressionAuditCase,
) -> CalibrationObservation:
    if value is None:
        meta = dict(audit_case.metadata)
        embedded = meta.get("calibration_observation")
        if isinstance(embedded, Mapping):
            return CalibrationObservation.from_dict(embedded)
        # Minimal conservative defaults bound to the audit case identity.
        return observation_from_outcome(
            observation_id=f"obs_{audit_case.case_id}",
            partition=audit_case.benchmark_partition
            if audit_case.benchmark_partition
            in {p.value for p in EvidencePartition}
            else EvidencePartition.CALIBRATION.value,
            comparative_outcome=ComparativeOutcome.EQUIVALENT_SUCCESS,
            task_class=audit_case.task_class,
            risk_class=audit_case.risk_class,
            metadata={"derived_from": "audit_case_defaults"},
        )
    if isinstance(value, CalibrationObservation):
        return value
    if isinstance(value, Mapping):
        return CalibrationObservation.from_dict(value)
    raise CalibrationError("observation must be CalibrationObservation or mapping")


def _is_simulated_audit_case(audit_case: CompressionAuditCase) -> bool:
    mode = audit_case.header.provenance.execution_mode
    status = audit_case.header.terminal_status
    return mode == ExecutionMode.SIMULATED.value or status == (
        GovernorTerminalStatus.SIMULATED.value
    )


def _bump_revision(current: int) -> int:
    nxt = _nonneg_int(current, "revision") + 1
    if nxt > MAX_REVISION:
        raise CalibrationError("revision exceeds maximum")
    return nxt


def _replace_header(
    header: GovernorArtifactHeader,
    *,
    artifact_kind: str,
    input_cids: Sequence[str],
    interface_id: str,
    terminal_status: str = GovernorTerminalStatus.COMPLETE.value,
    metadata: Mapping[str, Any] | None = None,
) -> GovernorArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    provenance = ArtifactProvenance(
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(sorted(set(input_cids))),
        tool_ids=(TOOL_ID,),
        policy_cid=header.provenance.policy_cid,
        notes=None,
    )
    try:
        return GovernorArtifactHeader(
            artifact_kind=artifact_kind,
            repository_state_cid=header.repository_state_cid,
            context_pack_cid=header.context_pack_cid,
            verification_bundle_cid=header.verification_bundle_cid,
            generator=generator,
            provenance=provenance,
            terminal_status=terminal_status,
            assumptions=header.assumptions,
            metadata=dict(metadata or {"track": "calibration"}),
        )
    except SemanticGovernorBaseError as exc:
        raise CalibrationError(str(exc)) from exc


def _explicit_counts(profile: CalibrationProfile) -> tuple[int, int, int]:
    """Return (false_exact, stale, omission) keeping failures explicit."""

    if isinstance(profile, CapsuleCalibrationRecord):
        return (
            profile.false_exact_classification_count,
            profile.stale_failure_count,
            profile.omission_failure_count,
        )
    if isinstance(profile, AnalyzerCalibrationProfile):
        return (
            profile.false_exact_classification_count,
            profile.stale_failure_count,
            profile.omission_rate.successes,
        )
    if isinstance(profile, TaskClassCalibrationProfile):
        return (0, 0, profile.omission_rate.successes)
    if isinstance(profile, ModelRouteCalibrationProfile):
        return (0, 0, 0)
    raise CalibrationError("unsupported profile type for explicit counts")


# ---------------------------------------------------------------------------
# Key matching
# ---------------------------------------------------------------------------


def _capsule_keys_match(
    record: CapsuleCalibrationRecord,
    obs: CalibrationObservation,
) -> bool:
    return (
        record.capsule_class == obs.capsule_class
        and record.language == obs.language
        and record.symbol_kind == obs.symbol_kind
        and record.framework == obs.framework
        and record.analyzer_feature == obs.analyzer_feature
        and record.repository_family == obs.repository_family
        and record.task_class == obs.task_class
        and record.risk_class == obs.risk_class
        and record.route_tier == obs.route_tier
    )


def _analyzer_keys_match(
    profile: AnalyzerCalibrationProfile,
    obs: CalibrationObservation,
) -> bool:
    return (
        profile.analyzer_id == obs.analyzer_id
        and profile.analyzer_version == obs.analyzer_version
    )


def _task_keys_match(
    profile: TaskClassCalibrationProfile,
    obs: CalibrationObservation,
) -> bool:
    return (
        profile.task_class == obs.task_class and profile.risk_class == obs.risk_class
    )


def _route_keys_match(
    profile: ModelRouteCalibrationProfile,
    obs: CalibrationObservation,
) -> bool:
    return profile.route_id == obs.route_id and profile.route_tier == obs.route_tier


# ---------------------------------------------------------------------------
# Apply observation to each profile kind
# ---------------------------------------------------------------------------


def _apply_capsule(
    record: CapsuleCalibrationRecord,
    obs: CalibrationObservation,
    audit_case_cid: str,
) -> CapsuleCalibrationRecord:
    use_count = _add_counter(record.use_count, 1, "use_count")
    compressed = _add_counter(
        record.compressed_success_count,
        1 if obs.compressed_success else 0,
        "compressed_success_count",
    )
    expanded = _add_counter(
        record.expanded_success_count,
        1 if obs.expanded_success else 0,
        "expanded_success_count",
    )
    omission = _add_counter(
        record.omission_failure_count,
        1 if obs.omission_failure else 0,
        "omission_failure_count",
    )
    stale = _add_counter(
        record.stale_failure_count,
        1 if obs.stale_failure else 0,
        "stale_failure_count",
    )
    false_exact = _add_counter(
        record.false_exact_classification_count,
        1 if obs.false_exact_classification else 0,
        "false_exact_classification_count",
    )
    raw_fb = _add_counter(
        record.unnecessary_raw_fallback_count,
        1 if obs.unnecessary_raw_fallback else 0,
        "unnecessary_raw_fallback_count",
    )
    review = _add_counter(
        record.review_disagreement_count,
        1 if obs.review_disagreement else 0,
        "review_disagreement_count",
    )
    tokens = _add_counter(
        record.token_savings_total, obs.token_savings, "token_savings_total"
    )
    vcost = _add_counter(
        record.verification_cost_total,
        obs.verification_cost,
        "verification_cost_total",
    )
    # Formal classification is never upgraded by empirical success.
    proof = record.proof_classification
    source = record.classification_source
    if (
        proof == ProofClassification.EXACT.value
        and source == ClassificationSource.EMPIRICAL.value
    ):
        raise CalibrationError(
            "empirical results cannot set proof classification to exact"
        )
    header = _replace_header(
        record.header,
        artifact_kind="capsule_calibration_record",
        input_cids=list(record.source_audit_cids) + [audit_case_cid],
        interface_id=UPDATE_CALIBRATION_INTERFACE,
    )
    try:
        return CapsuleCalibrationRecord(
            header=header,
            record_id=record.record_id,
            capsule_class=record.capsule_class,
            language=record.language,
            symbol_kind=record.symbol_kind,
            framework=record.framework,
            analyzer_feature=record.analyzer_feature,
            repository_family=record.repository_family,
            task_class=record.task_class,
            risk_class=record.risk_class,
            route_tier=record.route_tier,
            proof_classification=proof,
            classification_source=source,
            partition=record.partition,
            revision=_bump_revision(record.revision),
            use_count=use_count,
            compressed_success_count=compressed,
            expanded_success_count=expanded,
            omission_failure_count=omission,
            stale_failure_count=stale,
            false_exact_classification_count=false_exact,
            unnecessary_raw_fallback_count=raw_fb,
            review_disagreement_count=review,
            token_savings_total=tokens,
            verification_cost_total=vcost,
            omission_rate=build_empirical_rate(omission, use_count),
            source_audit_cids=_union_cids(
                record.source_audit_cids, (audit_case_cid,), "source_audit_cids"
            ),
            metadata=_thaw_structured(record.metadata),
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _apply_analyzer(
    profile: AnalyzerCalibrationProfile,
    obs: CalibrationObservation,
    audit_case_cid: str,
) -> AnalyzerCalibrationProfile:
    total_uses = _add_counter(profile.total_uses, 1, "total_uses")
    false_exact = _add_counter(
        profile.false_exact_classification_count,
        1 if obs.false_exact_classification else 0,
        "false_exact_classification_count",
    )
    stale = _add_counter(
        profile.stale_failure_count,
        1 if obs.stale_failure else 0,
        "stale_failure_count",
    )
    omission_successes = _add_counter(
        profile.omission_rate.successes,
        1 if obs.omission_failure else 0,
        "omission_rate.successes",
    )
    languages = tuple(
        sorted(set(profile.language_keys) | {obs.language})
    )
    header = _replace_header(
        profile.header,
        artifact_kind="analyzer_calibration_profile",
        input_cids=list(profile.record_cids) + [audit_case_cid],
        interface_id=UPDATE_CALIBRATION_INTERFACE,
    )
    try:
        return AnalyzerCalibrationProfile(
            header=header,
            profile_id=profile.profile_id,
            analyzer_id=profile.analyzer_id,
            analyzer_version=profile.analyzer_version,
            partition=profile.partition,
            revision=_bump_revision(profile.revision),
            total_uses=total_uses,
            false_exact_classification_count=false_exact,
            stale_failure_count=stale,
            omission_rate=build_empirical_rate(omission_successes, total_uses),
            record_cids=_union_cids(
                profile.record_cids, (audit_case_cid,), "record_cids"
            ),
            language_keys=languages,
            notes=profile.notes,
            metadata=_thaw_structured(profile.metadata),
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _apply_task_class(
    profile: TaskClassCalibrationProfile,
    obs: CalibrationObservation,
    audit_case_cid: str,
) -> TaskClassCalibrationProfile:
    total_uses = _add_counter(profile.total_uses, 1, "total_uses")
    compressed = _add_counter(
        profile.compressed_success_count,
        1 if obs.compressed_success else 0,
        "compressed_success_count",
    )
    expanded = _add_counter(
        profile.expanded_success_count,
        1 if obs.expanded_success else 0,
        "expanded_success_count",
    )
    review = _add_counter(
        profile.review_disagreement_count,
        1 if obs.review_disagreement else 0,
        "review_disagreement_count",
    )
    omission_successes = _add_counter(
        profile.omission_rate.successes,
        1 if obs.omission_failure else 0,
        "omission_rate.successes",
    )
    # Required proof posture is formal and never rewritten by empirical flags.
    classification = profile.required_proof_classification
    source = profile.classification_source
    if (
        classification == ProofClassification.EXACT.value
        and source == ClassificationSource.EMPIRICAL.value
    ):
        raise CalibrationError(
            "empirical results cannot set proof classification to exact"
        )
    header = _replace_header(
        profile.header,
        artifact_kind="task_class_calibration_profile",
        input_cids=list(profile.record_cids) + [audit_case_cid],
        interface_id=UPDATE_CALIBRATION_INTERFACE,
    )
    try:
        return TaskClassCalibrationProfile(
            header=header,
            profile_id=profile.profile_id,
            task_class=profile.task_class,
            risk_class=profile.risk_class,
            partition=profile.partition,
            revision=_bump_revision(profile.revision),
            total_uses=total_uses,
            compressed_success_count=compressed,
            expanded_success_count=expanded,
            review_disagreement_count=review,
            omission_rate=build_empirical_rate(omission_successes, total_uses),
            required_proof_classification=classification,
            classification_source=source,
            record_cids=_union_cids(
                profile.record_cids, (audit_case_cid,), "record_cids"
            ),
            notes=profile.notes,
            metadata=_thaw_structured(profile.metadata),
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _apply_route(
    profile: ModelRouteCalibrationProfile,
    obs: CalibrationObservation,
    audit_case_cid: str,
) -> ModelRouteCalibrationProfile:
    if profile.allows_empirical_exact_upgrade:
        raise CalibrationError(
            "empirical results cannot set proof classification to exact; "
            "allows_empirical_exact_upgrade must be false"
        )
    total_uses = _add_counter(profile.total_uses, 1, "total_uses")
    escalations = _add_counter(
        profile.escalation_count, 1 if obs.escalated else 0, "escalation_count"
    )
    retries = _add_counter(
        profile.retry_count, 1 if obs.retried else 0, "retry_count"
    )
    shadows = _add_counter(
        profile.shadow_sample_count,
        1 if obs.shadow_sampled else 0,
        "shadow_sample_count",
    )
    success_count = _add_counter(
        profile.success_rate.successes,
        1 if obs.route_success else 0,
        "success_rate.successes",
    )
    success_rate = build_empirical_rate(success_count, total_uses)
    escalation_rate_bp = ratio_to_basis_points(escalations, total_uses) or 0
    retry_rate_bp = ratio_to_basis_points(retries, total_uses) or 0
    shadow_rate_bp = ratio_to_basis_points(shadows, total_uses) or 0
    header = _replace_header(
        profile.header,
        artifact_kind="model_route_calibration_profile",
        input_cids=list(profile.record_cids) + [audit_case_cid],
        interface_id=UPDATE_CALIBRATION_INTERFACE,
    )
    try:
        return ModelRouteCalibrationProfile(
            header=header,
            profile_id=profile.profile_id,
            route_id=profile.route_id,
            route_tier=profile.route_tier,
            partition=profile.partition,
            revision=_bump_revision(profile.revision),
            total_uses=total_uses,
            escalation_count=escalations,
            retry_count=retries,
            shadow_sample_count=shadows,
            success_rate=success_rate,
            escalation_rate_bp=escalation_rate_bp,
            retry_rate_bp=retry_rate_bp,
            shadow_sample_rate_bp=shadow_rate_bp,
            allows_empirical_exact_upgrade=False,
            record_cids=_union_cids(
                profile.record_cids, (audit_case_cid,), "record_cids"
            ),
            notes=profile.notes,
            metadata=_thaw_structured(profile.metadata),
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _apply_observation(
    profile: CalibrationProfile,
    obs: CalibrationObservation,
    audit_case_cid: str,
) -> CalibrationProfile:
    if isinstance(profile, CapsuleCalibrationRecord):
        if not _capsule_keys_match(profile, obs):
            raise CalibrationError("observation keys do not match capsule record")
        return _apply_capsule(profile, obs, audit_case_cid)
    if isinstance(profile, AnalyzerCalibrationProfile):
        if not _analyzer_keys_match(profile, obs):
            raise CalibrationError("observation keys do not match analyzer profile")
        return _apply_analyzer(profile, obs, audit_case_cid)
    if isinstance(profile, TaskClassCalibrationProfile):
        if not _task_keys_match(profile, obs):
            raise CalibrationError("observation keys do not match task-class profile")
        return _apply_task_class(profile, obs, audit_case_cid)
    if isinstance(profile, ModelRouteCalibrationProfile):
        if not _route_keys_match(profile, obs):
            raise CalibrationError("observation keys do not match model-route profile")
        return _apply_route(profile, obs, audit_case_cid)
    raise CalibrationError("unsupported calibration profile type")


# ---------------------------------------------------------------------------
# Public: update_calibration
# ---------------------------------------------------------------------------


def update_calibration(
    audit_case: CompressionAuditCase | Mapping[str, Any],
    current_profile: CalibrationProfile | Mapping[str, Any],
    *,
    observation: CalibrationObservation | Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> CalibrationUpdateResult:
    """Update keyed empirical counters from one sealed audit case.

    Parameters
    ----------
    audit_case:
        Sealed ``CompressionAuditCase`` (or closed mapping).
    current_profile:
        Current capsule / analyzer / task-class / model-route profile.
    observation:
        Closed observation counters. When omitted, a minimal observation is
        derived from audit-case metadata or defaults.
    expected_revision:
        Optional CAS binding; when set and mismatched, the update is rejected
        without mutating counters.

    Returns
    -------
    CalibrationUpdateResult
        Disposition, revision binding, and resulting profile. Simulated cases
        never set ``applied_to_live_quality``. Replay of the same audit-case
        CID is idempotent.
    """

    case = _normalize_audit_case(audit_case)
    profile = _normalize_profile(current_profile)
    obs = _normalize_observation(observation, case)
    kind = _profile_kind(profile)
    prev_cid = _profile_cid(profile)
    prev_rev = _profile_revision(profile)
    case_cid = case.case_cid
    obs_cid = obs.observation_cid

    # Explicit CAS binding for concurrent writers.
    if expected_revision is not None:
        expected = _nonneg_int(expected_revision, "expected_revision")
        if expected != prev_rev:
            return _result(
                profile=profile,
                kind=kind,
                disposition=CalibrationDisposition.REJECTED_STALE_REVISION,
                audit_case_cid=case_cid,
                observation_cid=obs_cid,
                previous_revision=prev_rev,
                next_revision=prev_rev,
                previous_profile_cid=prev_cid,
                next_profile_cid=prev_cid,
                applied_to_live_quality=False,
                notes="expected_revision does not match current profile revision",
                audit_case=case,
            )

    # Partition binding: held-out must not silently update calibration.
    if obs.partition != _profile_partition(profile):
        return _result(
            profile=profile,
            kind=kind,
            disposition=CalibrationDisposition.SKIPPED_PARTITION_MISMATCH,
            audit_case_cid=case_cid,
            observation_cid=obs_cid,
            previous_revision=prev_rev,
            next_revision=prev_rev,
            previous_profile_cid=prev_cid,
            next_profile_cid=prev_cid,
            applied_to_live_quality=False,
            notes="observation partition does not match profile partition",
            audit_case=case,
        )

    # Simulated outputs are excluded from live quality.
    if _is_simulated_audit_case(case):
        return _result(
            profile=profile,
            kind=kind,
            disposition=CalibrationDisposition.SKIPPED_SIMULATED,
            audit_case_cid=case_cid,
            observation_cid=obs_cid,
            previous_revision=prev_rev,
            next_revision=prev_rev,
            previous_profile_cid=prev_cid,
            next_profile_cid=prev_cid,
            applied_to_live_quality=False,
            notes="simulated outputs are excluded from live quality",
            audit_case=case,
        )

    # Idempotency for concurrent/replayed inputs by sealed audit-case CID.
    if case_cid in _profile_source_cids(profile):
        return _result(
            profile=profile,
            kind=kind,
            disposition=CalibrationDisposition.SKIPPED_IDEMPOTENT,
            audit_case_cid=case_cid,
            observation_cid=obs_cid,
            previous_revision=prev_rev,
            next_revision=prev_rev,
            previous_profile_cid=prev_cid,
            next_profile_cid=prev_cid,
            applied_to_live_quality=False,
            notes="audit case already applied; concurrent/replay input is idempotent",
            audit_case=case,
        )

    # Key matching fails closed rather than silently cross-aggregating.
    try:
        updated = _apply_observation(profile, obs, case_cid)
    except CalibrationError as exc:
        message = str(exc)
        if "do not match" in message:
            return _result(
                profile=profile,
                kind=kind,
                disposition=CalibrationDisposition.REJECTED_KEY_MISMATCH,
                audit_case_cid=case_cid,
                observation_cid=obs_cid,
                previous_revision=prev_rev,
                next_revision=prev_rev,
                previous_profile_cid=prev_cid,
                next_profile_cid=prev_cid,
                applied_to_live_quality=False,
                notes=message,
                audit_case=case,
            )
        raise

    return _result(
        profile=updated,
        kind=kind,
        disposition=CalibrationDisposition.APPLIED,
        audit_case_cid=case_cid,
        observation_cid=obs_cid,
        previous_revision=prev_rev,
        next_revision=_profile_revision(updated),
        previous_profile_cid=prev_cid,
        next_profile_cid=_profile_cid(updated),
        applied_to_live_quality=True,
        notes=None,
        audit_case=case,
    )


def _result(
    *,
    profile: CalibrationProfile,
    kind: str,
    disposition: CalibrationDisposition,
    audit_case_cid: str,
    observation_cid: str | None,
    previous_revision: int,
    next_revision: int,
    previous_profile_cid: str,
    next_profile_cid: str,
    applied_to_live_quality: bool,
    notes: str | None,
    audit_case: CompressionAuditCase,
) -> CalibrationUpdateResult:
    false_exact, stale, omission = _explicit_counts(profile)
    input_cids = [audit_case_cid, previous_profile_cid]
    if observation_cid is not None:
        input_cids.append(observation_cid)
    header = _replace_header(
        audit_case.header,
        artifact_kind="calibration_update_result",
        input_cids=input_cids,
        interface_id=UPDATE_CALIBRATION_INTERFACE,
        terminal_status=(
            GovernorTerminalStatus.COMPLETE.value
            if disposition == CalibrationDisposition.APPLIED
            else GovernorTerminalStatus.INCONCLUSIVE.value
            if disposition
            in {
                CalibrationDisposition.SKIPPED_SIMULATED,
                CalibrationDisposition.SKIPPED_IDEMPOTENT,
                CalibrationDisposition.SKIPPED_PARTITION_MISMATCH,
            }
            else GovernorTerminalStatus.REJECTED.value
        ),
        metadata={
            "track": "calibration",
            "kind": kind,
            "disposition": disposition.value,
        },
    )
    update_id = f"upd_{kind}_{audit_case.case_id}"
    # Keep update_id token-shaped and bounded.
    update_id = re.sub(r"[^a-z0-9_.:/+-]", "_", update_id.lower())[:128]
    if not update_id or update_id[0] not in "abcdefghijklmnopqrstuvwxyz":
        update_id = f"u_{update_id}"[:128]
    return CalibrationUpdateResult(
        header=header,
        update_id=update_id,
        kind=kind,
        disposition=disposition,
        audit_case_cid=audit_case_cid,
        observation_cid=observation_cid,
        previous_revision=previous_revision,
        next_revision=next_revision,
        previous_profile_cid=previous_profile_cid,
        next_profile_cid=next_profile_cid,
        applied_to_live_quality=applied_to_live_quality,
        false_exact_classification_count=false_exact,
        stale_failure_count=stale,
        omission_failure_count=omission,
        profile=profile,
        notes=notes,
        metadata={
            "builder_schema": CALIBRATION_UPDATE_RESULT_SCHEMA,
            "interface_id": UPDATE_CALIBRATION_INTERFACE,
        },
    )


# ---------------------------------------------------------------------------
# Public: merge_calibration_profiles
# ---------------------------------------------------------------------------


def merge_calibration_profiles(
    left: CalibrationProfile | Mapping[str, Any],
    right: CalibrationProfile | Mapping[str, Any],
) -> CalibrationMergeResult:
    """Merge two same-kind profiles deterministically.

    Counters are summed, CIDs are unioned and sorted, rates are recomputed with
    Wilson bounds, and revision becomes ``max(left, right) + 1``. Formal proof
    classification fields must agree and remain non-empirical for ``exact``.
    """

    left_profile = _normalize_profile(left)
    right_profile = _normalize_profile(right)
    left_kind = _profile_kind(left_profile)
    right_kind = _profile_kind(right_profile)
    if left_kind != right_kind:
        raise CalibrationError(
            f"cannot merge heterogeneous calibration kinds {left_kind!r} and "
            f"{right_kind!r}"
        )
    if _profile_partition(left_profile) != _profile_partition(right_profile):
        raise CalibrationError("cannot merge profiles across evidence partitions")

    if isinstance(left_profile, CapsuleCalibrationRecord):
        merged = _merge_capsule(left_profile, right_profile)  # type: ignore[arg-type]
    elif isinstance(left_profile, AnalyzerCalibrationProfile):
        merged = _merge_analyzer(left_profile, right_profile)  # type: ignore[arg-type]
    elif isinstance(left_profile, TaskClassCalibrationProfile):
        merged = _merge_task_class(left_profile, right_profile)  # type: ignore[arg-type]
    elif isinstance(left_profile, ModelRouteCalibrationProfile):
        merged = _merge_route(left_profile, right_profile)  # type: ignore[arg-type]
    else:  # pragma: no cover
        raise CalibrationError("unsupported profile type")

    left_cid = _profile_cid(left_profile)
    right_cid = _profile_cid(right_profile)
    header = _replace_header(
        left_profile.header,
        artifact_kind="calibration_merge_result",
        input_cids=[left_cid, right_cid],
        interface_id=MERGE_CALIBRATION_PROFILES_INTERFACE,
        metadata={
            "track": "calibration",
            "kind": left_kind,
            "left_profile_cid": left_cid,
            "right_profile_cid": right_cid,
        },
    )
    merge_id = f"merge_{left_kind}_{left_cid[-12:]}_{right_cid[-12:]}"
    merge_id = re.sub(r"[^a-z0-9_.:/+-]", "_", merge_id.lower())[:128]
    if not merge_id or merge_id[0] not in "abcdefghijklmnopqrstuvwxyz":
        merge_id = f"m_{merge_id}"[:128]
    return CalibrationMergeResult(
        header=header,
        merge_id=merge_id,
        kind=left_kind,
        left_profile_cid=left_cid,
        right_profile_cid=right_cid,
        merged_revision=_profile_revision(merged),
        profile=merged,
        notes=None,
        metadata={
            "builder_schema": CALIBRATION_MERGE_RESULT_SCHEMA,
            "interface_id": MERGE_CALIBRATION_PROFILES_INTERFACE,
        },
    )


def _require_same(left: Any, right: Any, name: str) -> Any:
    if left != right:
        raise CalibrationError(f"cannot merge profiles with differing {name}")
    return left


def _merge_revision(left: int, right: int) -> int:
    return _bump_revision(max(left, right))


def _merge_capsule(
    left: CapsuleCalibrationRecord,
    right: CapsuleCalibrationRecord,
) -> CapsuleCalibrationRecord:
    for name in (
        "record_id",
        "capsule_class",
        "language",
        "symbol_kind",
        "framework",
        "analyzer_feature",
        "repository_family",
        "task_class",
        "risk_class",
        "route_tier",
        "proof_classification",
        "classification_source",
        "partition",
    ):
        _require_same(getattr(left, name), getattr(right, name), name)
    if (
        left.proof_classification == ProofClassification.EXACT.value
        and left.classification_source == ClassificationSource.EMPIRICAL.value
    ):
        raise CalibrationError(
            "empirical results cannot set proof classification to exact"
        )
    use_count = _add_counter(left.use_count, right.use_count, "use_count")
    omission = _add_counter(
        left.omission_failure_count,
        right.omission_failure_count,
        "omission_failure_count",
    )
    header = _replace_header(
        left.header,
        artifact_kind="capsule_calibration_record",
        input_cids=list(left.source_audit_cids) + list(right.source_audit_cids),
        interface_id=MERGE_CALIBRATION_PROFILES_INTERFACE,
    )
    try:
        return CapsuleCalibrationRecord(
            header=header,
            record_id=left.record_id,
            capsule_class=left.capsule_class,
            language=left.language,
            symbol_kind=left.symbol_kind,
            framework=left.framework,
            analyzer_feature=left.analyzer_feature,
            repository_family=left.repository_family,
            task_class=left.task_class,
            risk_class=left.risk_class,
            route_tier=left.route_tier,
            proof_classification=left.proof_classification,
            classification_source=left.classification_source,
            partition=left.partition,
            revision=_merge_revision(left.revision, right.revision),
            use_count=use_count,
            compressed_success_count=_add_counter(
                left.compressed_success_count,
                right.compressed_success_count,
                "compressed_success_count",
            ),
            expanded_success_count=_add_counter(
                left.expanded_success_count,
                right.expanded_success_count,
                "expanded_success_count",
            ),
            omission_failure_count=omission,
            stale_failure_count=_add_counter(
                left.stale_failure_count,
                right.stale_failure_count,
                "stale_failure_count",
            ),
            false_exact_classification_count=_add_counter(
                left.false_exact_classification_count,
                right.false_exact_classification_count,
                "false_exact_classification_count",
            ),
            unnecessary_raw_fallback_count=_add_counter(
                left.unnecessary_raw_fallback_count,
                right.unnecessary_raw_fallback_count,
                "unnecessary_raw_fallback_count",
            ),
            review_disagreement_count=_add_counter(
                left.review_disagreement_count,
                right.review_disagreement_count,
                "review_disagreement_count",
            ),
            token_savings_total=_add_counter(
                left.token_savings_total,
                right.token_savings_total,
                "token_savings_total",
            ),
            verification_cost_total=_add_counter(
                left.verification_cost_total,
                right.verification_cost_total,
                "verification_cost_total",
            ),
            omission_rate=build_empirical_rate(omission, use_count),
            source_audit_cids=_union_cids(
                left.source_audit_cids, right.source_audit_cids, "source_audit_cids"
            ),
            metadata={},
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _merge_analyzer(
    left: AnalyzerCalibrationProfile,
    right: AnalyzerCalibrationProfile,
) -> AnalyzerCalibrationProfile:
    for name in ("profile_id", "analyzer_id", "analyzer_version", "partition"):
        _require_same(getattr(left, name), getattr(right, name), name)
    total_uses = _add_counter(left.total_uses, right.total_uses, "total_uses")
    omission = _add_counter(
        left.omission_rate.successes,
        right.omission_rate.successes,
        "omission_rate.successes",
    )
    languages = tuple(sorted(set(left.language_keys) | set(right.language_keys)))
    header = _replace_header(
        left.header,
        artifact_kind="analyzer_calibration_profile",
        input_cids=list(left.record_cids) + list(right.record_cids),
        interface_id=MERGE_CALIBRATION_PROFILES_INTERFACE,
    )
    try:
        return AnalyzerCalibrationProfile(
            header=header,
            profile_id=left.profile_id,
            analyzer_id=left.analyzer_id,
            analyzer_version=left.analyzer_version,
            partition=left.partition,
            revision=_merge_revision(left.revision, right.revision),
            total_uses=total_uses,
            false_exact_classification_count=_add_counter(
                left.false_exact_classification_count,
                right.false_exact_classification_count,
                "false_exact_classification_count",
            ),
            stale_failure_count=_add_counter(
                left.stale_failure_count,
                right.stale_failure_count,
                "stale_failure_count",
            ),
            omission_rate=build_empirical_rate(omission, total_uses),
            record_cids=_union_cids(
                left.record_cids, right.record_cids, "record_cids"
            ),
            language_keys=languages,
            notes=left.notes if left.notes == right.notes else None,
            metadata={},
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _merge_task_class(
    left: TaskClassCalibrationProfile,
    right: TaskClassCalibrationProfile,
) -> TaskClassCalibrationProfile:
    for name in (
        "profile_id",
        "task_class",
        "risk_class",
        "partition",
        "required_proof_classification",
        "classification_source",
    ):
        _require_same(getattr(left, name), getattr(right, name), name)
    if (
        left.required_proof_classification == ProofClassification.EXACT.value
        and left.classification_source == ClassificationSource.EMPIRICAL.value
    ):
        raise CalibrationError(
            "empirical results cannot set proof classification to exact"
        )
    total_uses = _add_counter(left.total_uses, right.total_uses, "total_uses")
    omission = _add_counter(
        left.omission_rate.successes,
        right.omission_rate.successes,
        "omission_rate.successes",
    )
    header = _replace_header(
        left.header,
        artifact_kind="task_class_calibration_profile",
        input_cids=list(left.record_cids) + list(right.record_cids),
        interface_id=MERGE_CALIBRATION_PROFILES_INTERFACE,
    )
    try:
        return TaskClassCalibrationProfile(
            header=header,
            profile_id=left.profile_id,
            task_class=left.task_class,
            risk_class=left.risk_class,
            partition=left.partition,
            revision=_merge_revision(left.revision, right.revision),
            total_uses=total_uses,
            compressed_success_count=_add_counter(
                left.compressed_success_count,
                right.compressed_success_count,
                "compressed_success_count",
            ),
            expanded_success_count=_add_counter(
                left.expanded_success_count,
                right.expanded_success_count,
                "expanded_success_count",
            ),
            review_disagreement_count=_add_counter(
                left.review_disagreement_count,
                right.review_disagreement_count,
                "review_disagreement_count",
            ),
            omission_rate=build_empirical_rate(omission, total_uses),
            required_proof_classification=left.required_proof_classification,
            classification_source=left.classification_source,
            record_cids=_union_cids(
                left.record_cids, right.record_cids, "record_cids"
            ),
            notes=left.notes if left.notes == right.notes else None,
            metadata={},
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


def _merge_route(
    left: ModelRouteCalibrationProfile,
    right: ModelRouteCalibrationProfile,
) -> ModelRouteCalibrationProfile:
    for name in ("profile_id", "route_id", "route_tier", "partition"):
        _require_same(getattr(left, name), getattr(right, name), name)
    if left.allows_empirical_exact_upgrade or right.allows_empirical_exact_upgrade:
        raise CalibrationError(
            "empirical results cannot set proof classification to exact; "
            "allows_empirical_exact_upgrade must be false"
        )
    total_uses = _add_counter(left.total_uses, right.total_uses, "total_uses")
    escalations = _add_counter(
        left.escalation_count, right.escalation_count, "escalation_count"
    )
    retries = _add_counter(left.retry_count, right.retry_count, "retry_count")
    shadows = _add_counter(
        left.shadow_sample_count, right.shadow_sample_count, "shadow_sample_count"
    )
    successes = _add_counter(
        left.success_rate.successes,
        right.success_rate.successes,
        "success_rate.successes",
    )
    header = _replace_header(
        left.header,
        artifact_kind="model_route_calibration_profile",
        input_cids=list(left.record_cids) + list(right.record_cids),
        interface_id=MERGE_CALIBRATION_PROFILES_INTERFACE,
    )
    try:
        return ModelRouteCalibrationProfile(
            header=header,
            profile_id=left.profile_id,
            route_id=left.route_id,
            route_tier=left.route_tier,
            partition=left.partition,
            revision=_merge_revision(left.revision, right.revision),
            total_uses=total_uses,
            escalation_count=escalations,
            retry_count=retries,
            shadow_sample_count=shadows,
            success_rate=build_empirical_rate(successes, total_uses),
            escalation_rate_bp=ratio_to_basis_points(escalations, total_uses) or 0,
            retry_rate_bp=ratio_to_basis_points(retries, total_uses) or 0,
            shadow_sample_rate_bp=ratio_to_basis_points(shadows, total_uses) or 0,
            allows_empirical_exact_upgrade=False,
            record_cids=_union_cids(
                left.record_cids, right.record_cids, "record_cids"
            ),
            notes=left.notes if left.notes == right.notes else None,
            metadata={},
        )
    except CalibrationContractError as exc:
        raise CalibrationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Vocabulary / interface pins
# ---------------------------------------------------------------------------


def update_calibration_interface_id() -> str:
    """Return the versioned public interface pin for calibration updates."""

    return UPDATE_CALIBRATION_INTERFACE


def merge_calibration_profiles_interface_id() -> str:
    """Return the versioned public interface pin for profile merges."""

    return MERGE_CALIBRATION_PROFILES_INTERFACE


def calibration_kinds() -> tuple[str, ...]:
    """Return the closed calibration-kind vocabulary."""

    return tuple(item.value for item in CalibrationKind)


def calibration_dispositions() -> tuple[str, ...]:
    """Return the closed calibration-disposition vocabulary."""

    return tuple(item.value for item in CalibrationDisposition)


def comparative_outcomes() -> tuple[str, ...]:
    """Return the closed comparative-outcome vocabulary."""

    return tuple(item.value for item in ComparativeOutcome)


__all__ = [
    "CALIBRATION_MERGE_RESULT_SCHEMA",
    "CALIBRATION_OBSERVATION_SCHEMA",
    "CALIBRATION_UPDATE_RESULT_SCHEMA",
    "MERGE_CALIBRATION_PROFILES_INTERFACE",
    "UPDATE_CALIBRATION_INTERFACE",
    "CalibrationDisposition",
    "CalibrationError",
    "CalibrationKind",
    "CalibrationMergeResult",
    "CalibrationObservation",
    "CalibrationUpdateResult",
    "ComparativeOutcome",
    "build_empirical_rate",
    "calibration_dispositions",
    "calibration_kinds",
    "comparative_outcomes",
    "merge_calibration_profiles",
    "merge_calibration_profiles_interface_id",
    "observation_from_outcome",
    "update_calibration",
    "update_calibration_interface_id",
    "wilson_score_interval_bp",
]
