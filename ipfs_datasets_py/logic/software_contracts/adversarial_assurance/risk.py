"""Risk-weighted scoring and bounded sampling for mutation targets (AAE-021).

Interface surface:

* ``rank_mutation_risk`` — deterministic ranking of candidate subjects by
  closed risk class plus measured risk signals.
* Supporting records: ``RiskSignals``, ``RiskScore``, ``SamplingBudget``.

Risk weighting prioritizes security/authorization, durability, financial or
legal consequence, distributed transitions, proof/receipt trust, fan-out,
recent change, capsule uncertainty, defects, execution frequency, and failure
cost (plan §8). Formatting, proven generated code, immutable dependencies, and
low-risk boilerplate are down-weighted and admitted only under explicit
bounded sampling.

This module performs pure, fail-closed scoring. It does not open a store,
mutate worktrees, or change production policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import blake2b
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_RISK_WEIGHT_BP,
    MAX_SEED,
    MAX_TARGETS,
    MutationRiskClass,
    PropertyClass,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

RISK_SCORING_INTERFACE: Final[str] = "rank_mutation_risk@1"
RISK_SIGNALS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-risk-signals@1"
)
RISK_SCORE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-risk-score@1"
)
SAMPLING_BUDGET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-sampling-budget@1"
)
RISK_RANKING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-risk-ranking@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CLAIMS: Final[int] = 4_096
MAX_FAN_OUT: Final[int] = 1_000_000
MAX_DEFECTS: Final[int] = 1_000_000

# Dimension contribution caps (basis points) applied after class base weight.
_CAP_FAN_OUT: Final[int] = 800
_CAP_RECENT_CHANGE: Final[int] = 600
_CAP_UNCERTAINTY: Final[int] = 800
_CAP_DEFECTS: Final[int] = 700
_CAP_FREQUENCY: Final[int] = 500
_CAP_FAILURE_COST: Final[int] = 900
_BONUS_MISSING_TESTS: Final[int] = 400

# Per-unit contribution rates.
_FAN_OUT_PER_DEPENDENT: Final[int] = 50
_DEFECT_PER_COUNT: Final[int] = 100

# Down-weight multipliers for low-value surface classes (basis points of weight).
_DOWNWEIGHT_FORMATTING_BP: Final[int] = 1_500
_DOWNWEIGHT_GENERATED_BP: Final[int] = 2_000
_DOWNWEIGHT_IMMUTABLE_BP: Final[int] = 1_000
_DOWNWEIGHT_BOILERPLATE_BP: Final[int] = 2_500

# Default sampling thresholds.
DEFAULT_ALWAYS_SELECT_MIN_RISK_BP: Final[int] = 6_000
DEFAULT_LOW_RISK_SAMPLE_RATE_BP: Final[int] = 1_500
DEFAULT_MAX_TARGETS: Final[int] = 32

# Priority risk classes always preferred when scores tie on weight.
_PRIORITY_RISK_CLASSES: Final[tuple[str, ...]] = (
    MutationRiskClass.CRITICAL_SECURITY.value,
    MutationRiskClass.AUTHORIZATION.value,
    MutationRiskClass.FINANCIAL_LEGAL.value,
    MutationRiskClass.DURABILITY.value,
    MutationRiskClass.DISTRIBUTED_TRANSITION.value,
    MutationRiskClass.PROOF_RECEIPT_TRUST.value,
    MutationRiskClass.CRITICAL_INVARIANT.value,
    MutationRiskClass.HIGH.value,
    MutationRiskClass.MEDIUM.value,
    MutationRiskClass.LOCAL_BUG.value,
    MutationRiskClass.LOW.value,
)

_RISK_CLASS_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {name: index for index, name in enumerate(_PRIORITY_RISK_CLASSES)}
)

# Base weight by closed risk class (basis points of 10_000).
RISK_CLASS_BASE_WEIGHT_BP: Final[Mapping[str, int]] = MappingProxyType(
    {
        MutationRiskClass.CRITICAL_SECURITY.value: 9_000,
        MutationRiskClass.AUTHORIZATION.value: 8_500,
        MutationRiskClass.FINANCIAL_LEGAL.value: 8_800,
        MutationRiskClass.DURABILITY.value: 8_000,
        MutationRiskClass.DISTRIBUTED_TRANSITION.value: 7_800,
        MutationRiskClass.PROOF_RECEIPT_TRUST.value: 7_600,
        MutationRiskClass.CRITICAL_INVARIANT.value: 7_000,
        MutationRiskClass.HIGH.value: 5_500,
        MutationRiskClass.MEDIUM.value: 3_500,
        MutationRiskClass.LOCAL_BUG.value: 2_500,
        MutationRiskClass.LOW.value: 1_000,
    }
)

# Property class → default risk class for claim binding.
PROPERTY_CLASS_RISK: Final[Mapping[str, str]] = MappingProxyType(
    {
        PropertyClass.AUTHORIZATION.value: MutationRiskClass.CRITICAL_SECURITY.value,
        PropertyClass.POLICY_CONSTRAINT.value: MutationRiskClass.AUTHORIZATION.value,
        PropertyClass.DURABILITY.value: MutationRiskClass.DURABILITY.value,
        PropertyClass.STORAGE_INTEGRITY.value: MutationRiskClass.DURABILITY.value,
        PropertyClass.STATE_TRANSITION.value: (
            MutationRiskClass.DISTRIBUTED_TRANSITION.value
        ),
        PropertyClass.IDEMPOTENCY.value: (
            MutationRiskClass.DISTRIBUTED_TRANSITION.value
        ),
        PropertyClass.COMPENSATION.value: (
            MutationRiskClass.DISTRIBUTED_TRANSITION.value
        ),
        PropertyClass.PROOF_ADEQUACY.value: (
            MutationRiskClass.PROOF_RECEIPT_TRUST.value
        ),
        PropertyClass.RECEIPT_AUTHENTICITY.value: (
            MutationRiskClass.PROOF_RECEIPT_TRUST.value
        ),
        PropertyClass.TEST_ADEQUACY.value: (
            MutationRiskClass.PROOF_RECEIPT_TRUST.value
        ),
        PropertyClass.CAPSULE_COMPLETENESS.value: MutationRiskClass.HIGH.value,
        PropertyClass.CONTROL_INVARIANT.value: (
            MutationRiskClass.CRITICAL_INVARIANT.value
        ),
        PropertyClass.DATA_INTEGRITY.value: (
            MutationRiskClass.CRITICAL_INVARIANT.value
        ),
        PropertyClass.SCHEMA_CONTRACT.value: (
            MutationRiskClass.CRITICAL_INVARIANT.value
        ),
        PropertyClass.ERROR_HANDLING.value: (
            MutationRiskClass.CRITICAL_INVARIANT.value
        ),
        PropertyClass.CANCELLATION.value: (
            MutationRiskClass.CRITICAL_INVARIANT.value
        ),
        PropertyClass.INTERFACE_CONTRACT.value: MutationRiskClass.HIGH.value,
        PropertyClass.SIDE_EFFECT_OBLIGATION.value: MutationRiskClass.HIGH.value,
        PropertyClass.RETRY_BUDGET.value: MutationRiskClass.HIGH.value,
        PropertyClass.GUI_ACTION_BINDING.value: MutationRiskClass.HIGH.value,
    }
)


class TargetRiskError(AssuranceBaseError):
    """Raised when risk scoring or sampling inputs fail closed verification."""


class RiskDimension(str, Enum):
    """Closed contribution dimensions for risk-weighted selection."""

    SECURITY = "security"
    DURABILITY = "durability"
    DISTRIBUTED_TRUST = "distributed_trust"
    PROOF_TRUST = "proof_trust"
    FAN_OUT = "fan_out"
    RECENT_CHANGE = "recent_change"
    UNCERTAINTY = "uncertainty"
    DEFECTS = "defects"
    FREQUENCY = "frequency"
    FAILURE_COST = "failure_cost"
    MISSING_TESTS = "missing_tests"
    BASE_CLASS = "base_class"
    DOWNWEIGHT = "downweight"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise TargetRiskError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise TargetRiskError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise TargetRiskError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise TargetRiskError(f"{name} has unsupported value {value!r}") from exc


def _nonneg_int(value: Any, name: str, *, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise TargetRiskError(f"{name} must be a nonnegative integer")
    if value > maximum:
        raise TargetRiskError(f"{name} exceeds maximum")
    return value


def _pos_int(value: Any, name: str, *, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise TargetRiskError(f"{name} must be a positive integer")
    if value > maximum:
        raise TargetRiskError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TargetRiskError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TargetRiskError(
            f"{name} must be an integer basis-point weight in "
            f"[0, {MAX_RISK_WEIGHT_BP}]"
        )
    if value < 0 or value > MAX_RISK_WEIGHT_BP:
        raise TargetRiskError(
            f"{name} must be an integer basis-point weight in "
            f"[0, {MAX_RISK_WEIGHT_BP}]"
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


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise TargetRiskError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise TargetRiskError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TargetRiskError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TargetRiskError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise TargetRiskError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _clamp_bp(value: int) -> int:
    if value < 0:
        return 0
    if value > MAX_RISK_WEIGHT_BP:
        return MAX_RISK_WEIGHT_BP
    return value


# ---------------------------------------------------------------------------
# Public helpers: class / property mapping
# ---------------------------------------------------------------------------


def risk_dimensions() -> tuple[str, ...]:
    """Return the closed risk-dimension vocabulary in stable order."""

    return tuple(item.value for item in RiskDimension)


def risk_class_base_weight_bp(risk_class: MutationRiskClass | str) -> int:
    """Return the closed base weight for a mutation risk class."""

    key = _enum(risk_class, MutationRiskClass, "risk_class")
    return RISK_CLASS_BASE_WEIGHT_BP[key]


def risk_class_for_property_class(
    property_class: PropertyClass | str,
) -> str:
    """Map a property class to its default mutation risk class."""

    key = _enum(property_class, PropertyClass, "property_class")
    mapped = PROPERTY_CLASS_RISK.get(key)
    if mapped is None:
        raise TargetRiskError(
            f"property_class {key!r} has no risk mapping"
        )
    return mapped


def highest_risk_class(risk_classes: Iterable[MutationRiskClass | str]) -> str:
    """Return the highest-priority risk class from a non-empty sequence."""

    values = [_enum(item, MutationRiskClass, "risk_class") for item in risk_classes]
    if not values:
        raise TargetRiskError("risk_classes must not be empty")
    return min(values, key=lambda name: _RISK_CLASS_RANK[name])


def primary_dimension_for_risk_class(risk_class: MutationRiskClass | str) -> str:
    """Return the primary selection dimension for a risk class."""

    key = _enum(risk_class, MutationRiskClass, "risk_class")
    if key in {
        MutationRiskClass.CRITICAL_SECURITY.value,
        MutationRiskClass.AUTHORIZATION.value,
        MutationRiskClass.FINANCIAL_LEGAL.value,
    }:
        return RiskDimension.SECURITY.value
    if key == MutationRiskClass.DURABILITY.value:
        return RiskDimension.DURABILITY.value
    if key == MutationRiskClass.DISTRIBUTED_TRANSITION.value:
        return RiskDimension.DISTRIBUTED_TRUST.value
    if key == MutationRiskClass.PROOF_RECEIPT_TRUST.value:
        return RiskDimension.PROOF_TRUST.value
    return RiskDimension.BASE_CLASS.value


# ---------------------------------------------------------------------------
# RiskSignals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskSignals:
    """Measured risk signals bound to a claim, symbol, or artifact subject.

    All continuous scores are integer basis points in ``[0, 10000]``. Boolean
    down-weight markers reduce effective weight for low-value surfaces.
    """

    fan_out: int = 0
    recent_change_bp: int = 0
    uncertainty_bp: int = 0
    defect_count: int = 0
    frequency_bp: int = 0
    failure_cost_bp: int = 0
    missing_tests: bool = False
    is_formatting: bool = False
    is_generated_proven: bool = False
    is_immutable_dependency: bool = False
    is_boilerplate: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "fan_out",
            "recent_change_bp",
            "uncertainty_bp",
            "defect_count",
            "frequency_bp",
            "failure_cost_bp",
            "missing_tests",
            "is_formatting",
            "is_generated_proven",
            "is_immutable_dependency",
            "is_boilerplate",
            "notes",
            "metadata",
            "signals_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fan_out",
            _nonneg_int(self.fan_out, "fan_out", maximum=MAX_FAN_OUT),
        )
        object.__setattr__(
            self,
            "recent_change_bp",
            _basis_points(self.recent_change_bp, "recent_change_bp"),
        )
        object.__setattr__(
            self,
            "uncertainty_bp",
            _basis_points(self.uncertainty_bp, "uncertainty_bp"),
        )
        object.__setattr__(
            self,
            "defect_count",
            _nonneg_int(self.defect_count, "defect_count", maximum=MAX_DEFECTS),
        )
        object.__setattr__(
            self,
            "frequency_bp",
            _basis_points(self.frequency_bp, "frequency_bp"),
        )
        object.__setattr__(
            self,
            "failure_cost_bp",
            _basis_points(self.failure_cost_bp, "failure_cost_bp"),
        )
        object.__setattr__(
            self, "missing_tests", _bool(self.missing_tests, "missing_tests")
        )
        object.__setattr__(
            self, "is_formatting", _bool(self.is_formatting, "is_formatting")
        )
        object.__setattr__(
            self,
            "is_generated_proven",
            _bool(self.is_generated_proven, "is_generated_proven"),
        )
        object.__setattr__(
            self,
            "is_immutable_dependency",
            _bool(self.is_immutable_dependency, "is_immutable_dependency"),
        )
        object.__setattr__(
            self, "is_boilerplate", _bool(self.is_boilerplate, "is_boilerplate")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RISK_SIGNALS_SCHEMA,
            "fan_out": self.fan_out,
            "recent_change_bp": self.recent_change_bp,
            "uncertainty_bp": self.uncertainty_bp,
            "defect_count": self.defect_count,
            "frequency_bp": self.frequency_bp,
            "failure_cost_bp": self.failure_cost_bp,
            "missing_tests": self.missing_tests,
            "is_formatting": self.is_formatting,
            "is_generated_proven": self.is_generated_proven,
            "is_immutable_dependency": self.is_immutable_dependency,
            "is_boilerplate": self.is_boilerplate,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def signals_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["signals_cid"] = self.signals_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RiskSignals":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("signals_cid")
        if payload.pop("schema") != RISK_SIGNALS_SCHEMA:
            raise TargetRiskError("unsupported RiskSignals schema version")
        result = cls(
            fan_out=payload["fan_out"],
            recent_change_bp=payload["recent_change_bp"],
            uncertainty_bp=payload["uncertainty_bp"],
            defect_count=payload["defect_count"],
            frequency_bp=payload["frequency_bp"],
            failure_cost_bp=payload["failure_cost_bp"],
            missing_tests=payload["missing_tests"],
            is_formatting=payload["is_formatting"],
            is_generated_proven=payload["is_generated_proven"],
            is_immutable_dependency=payload["is_immutable_dependency"],
            is_boilerplate=payload["is_boilerplate"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.signals_cid:
            raise TargetRiskError("RiskSignals signals_cid identity mismatch")
        return result

    @classmethod
    def normalize(cls, value: "RiskSignals | Mapping[str, Any] | None") -> "RiskSignals":
        if value is None:
            return cls()
        if isinstance(value, RiskSignals):
            return value
        if not isinstance(value, Mapping):
            raise TargetRiskError("risk signals must be RiskSignals or a mapping")
        # Permit partial mappings without schema/cid for call-site convenience.
        if "schema" in value or "signals_cid" in value:
            return cls.from_dict(value)
        fields = {
            "fan_out": value.get("fan_out", 0),
            "recent_change_bp": value.get("recent_change_bp", 0),
            "uncertainty_bp": value.get("uncertainty_bp", 0),
            "defect_count": value.get("defect_count", 0),
            "frequency_bp": value.get("frequency_bp", 0),
            "failure_cost_bp": value.get("failure_cost_bp", 0),
            "missing_tests": value.get("missing_tests", False),
            "is_formatting": value.get("is_formatting", False),
            "is_generated_proven": value.get("is_generated_proven", False),
            "is_immutable_dependency": value.get("is_immutable_dependency", False),
            "is_boilerplate": value.get("is_boilerplate", False),
            "notes": value.get("notes"),
            "metadata": value.get("metadata", {}),
        }
        unknown = set(value) - set(fields)
        if unknown:
            raise TargetRiskError(
                f"RiskSignals contains unknown fields: {', '.join(sorted(unknown))}"
            )
        return cls(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SamplingBudget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SamplingBudget:
    """Explicit bounded sampling controls for risk-weighted target selection.

    Subjects with ``risk_weight_bp >= always_select_min_risk_bp`` are always
    admitted (subject to ``max_targets``). Lower-weight subjects are admitted
    only when a deterministic hash sample falls under
    ``low_risk_sample_rate_bp`` scaled by weight.
    """

    max_targets: int = DEFAULT_MAX_TARGETS
    always_select_min_risk_bp: int = DEFAULT_ALWAYS_SELECT_MIN_RISK_BP
    low_risk_sample_rate_bp: int = DEFAULT_LOW_RISK_SAMPLE_RATE_BP
    seed: int = 0
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "max_targets",
            "always_select_min_risk_bp",
            "low_risk_sample_rate_bp",
            "seed",
            "notes",
            "budget_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_targets",
            _pos_int(self.max_targets, "max_targets", maximum=MAX_TARGETS),
        )
        object.__setattr__(
            self,
            "always_select_min_risk_bp",
            _basis_points(
                self.always_select_min_risk_bp, "always_select_min_risk_bp"
            ),
        )
        object.__setattr__(
            self,
            "low_risk_sample_rate_bp",
            _basis_points(
                self.low_risk_sample_rate_bp, "low_risk_sample_rate_bp"
            ),
        )
        object.__setattr__(
            self, "seed", _nonneg_int(self.seed, "seed", maximum=MAX_SEED)
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SAMPLING_BUDGET_SCHEMA,
            "max_targets": self.max_targets,
            "always_select_min_risk_bp": self.always_select_min_risk_bp,
            "low_risk_sample_rate_bp": self.low_risk_sample_rate_bp,
            "seed": self.seed,
            "notes": self.notes,
        }

    @property
    def budget_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["budget_cid"] = self.budget_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SamplingBudget":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("budget_cid")
        if payload.pop("schema") != SAMPLING_BUDGET_SCHEMA:
            raise TargetRiskError("unsupported SamplingBudget schema version")
        result = cls(
            max_targets=payload["max_targets"],
            always_select_min_risk_bp=payload["always_select_min_risk_bp"],
            low_risk_sample_rate_bp=payload["low_risk_sample_rate_bp"],
            seed=payload["seed"],
            notes=payload["notes"],
        )
        if claimed != result.budget_cid:
            raise TargetRiskError("SamplingBudget budget_cid identity mismatch")
        return result

    @classmethod
    def normalize(
        cls, value: "SamplingBudget | Mapping[str, Any] | None"
    ) -> "SamplingBudget":
        if value is None:
            return cls()
        if isinstance(value, SamplingBudget):
            return value
        if not isinstance(value, Mapping):
            raise TargetRiskError("sampling budget must be SamplingBudget or a mapping")
        if "schema" in value or "budget_cid" in value:
            return cls.from_dict(value)
        fields = {
            "max_targets": value.get("max_targets", DEFAULT_MAX_TARGETS),
            "always_select_min_risk_bp": value.get(
                "always_select_min_risk_bp", DEFAULT_ALWAYS_SELECT_MIN_RISK_BP
            ),
            "low_risk_sample_rate_bp": value.get(
                "low_risk_sample_rate_bp", DEFAULT_LOW_RISK_SAMPLE_RATE_BP
            ),
            "seed": value.get("seed", 0),
            "notes": value.get("notes"),
        }
        unknown = set(value) - set(fields)
        if unknown:
            raise TargetRiskError(
                f"SamplingBudget contains unknown fields: {', '.join(sorted(unknown))}"
            )
        return cls(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _signal_contributions(signals: RiskSignals) -> dict[str, int]:
    fan_out_bp = min(signals.fan_out * _FAN_OUT_PER_DEPENDENT, _CAP_FAN_OUT)
    recent_bp = min(signals.recent_change_bp, _CAP_RECENT_CHANGE)
    # Scale recent_change_bp (0-10000) into contribution room.
    recent_contrib = (recent_bp * _CAP_RECENT_CHANGE) // MAX_RISK_WEIGHT_BP
    uncertainty_contrib = (
        min(signals.uncertainty_bp, MAX_RISK_WEIGHT_BP) * _CAP_UNCERTAINTY
    ) // MAX_RISK_WEIGHT_BP
    defects_bp = min(signals.defect_count * _DEFECT_PER_COUNT, _CAP_DEFECTS)
    frequency_contrib = (
        min(signals.frequency_bp, MAX_RISK_WEIGHT_BP) * _CAP_FREQUENCY
    ) // MAX_RISK_WEIGHT_BP
    failure_contrib = (
        min(signals.failure_cost_bp, MAX_RISK_WEIGHT_BP) * _CAP_FAILURE_COST
    ) // MAX_RISK_WEIGHT_BP
    missing = _BONUS_MISSING_TESTS if signals.missing_tests else 0
    return {
        RiskDimension.FAN_OUT.value: fan_out_bp,
        RiskDimension.RECENT_CHANGE.value: recent_contrib,
        RiskDimension.UNCERTAINTY.value: uncertainty_contrib,
        RiskDimension.DEFECTS.value: defects_bp,
        RiskDimension.FREQUENCY.value: frequency_contrib,
        RiskDimension.FAILURE_COST.value: failure_contrib,
        RiskDimension.MISSING_TESTS.value: missing,
    }


def _downweight_multiplier_bp(signals: RiskSignals) -> int:
    """Return remaining weight fraction after low-value surface down-weights."""

    remaining = MAX_RISK_WEIGHT_BP
    if signals.is_formatting:
        remaining = (remaining * _DOWNWEIGHT_FORMATTING_BP) // MAX_RISK_WEIGHT_BP
    if signals.is_generated_proven:
        remaining = (remaining * _DOWNWEIGHT_GENERATED_BP) // MAX_RISK_WEIGHT_BP
    if signals.is_immutable_dependency:
        remaining = (remaining * _DOWNWEIGHT_IMMUTABLE_BP) // MAX_RISK_WEIGHT_BP
    if signals.is_boilerplate:
        remaining = (remaining * _DOWNWEIGHT_BOILERPLATE_BP) // MAX_RISK_WEIGHT_BP
    return remaining


def compute_risk_weight_bp(
    risk_class: MutationRiskClass | str,
    signals: RiskSignals | Mapping[str, Any] | None = None,
) -> tuple[int, Mapping[str, int]]:
    """Compute total risk weight and dimension contributions in basis points.

    Returns ``(risk_weight_bp, contributions)`` where contributions map closed
    dimension names to signed/positive contribution amounts. The
    ``downweight`` dimension records the residual multiplier applied after
    additive signals (as remaining fraction bp).
    """

    class_key = _enum(risk_class, MutationRiskClass, "risk_class")
    normalized = RiskSignals.normalize(signals)
    base = RISK_CLASS_BASE_WEIGHT_BP[class_key]
    contributions: dict[str, int] = {
        RiskDimension.BASE_CLASS.value: base,
        primary_dimension_for_risk_class(class_key): 0,
    }
    # Ensure the primary priority dimension is present even when zero-add.
    for dim, amount in _signal_contributions(normalized).items():
        contributions[dim] = amount
    additive = sum(
        amount
        for key, amount in contributions.items()
        if key != RiskDimension.BASE_CLASS.value
    )
    raw = base + additive
    multiplier = _downweight_multiplier_bp(normalized)
    contributions[RiskDimension.DOWNWEIGHT.value] = multiplier
    weighted = (raw * multiplier) // MAX_RISK_WEIGHT_BP
    return _clamp_bp(weighted), MappingProxyType(dict(sorted(contributions.items())))


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Deterministic risk score for one mutation subject."""

    subject_id: str
    risk_class: MutationRiskClass | str
    risk_weight_bp: int
    contributions: Mapping[str, int]
    signals: RiskSignals
    selected: bool = False
    selection_reason: str | None = None
    rank: int | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "subject_id",
            "risk_class",
            "risk_weight_bp",
            "contributions",
            "signals",
            "selected",
            "selection_reason",
            "rank",
            "notes",
            "metadata",
            "score_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, MutationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self,
            "risk_weight_bp",
            _basis_points(self.risk_weight_bp, "risk_weight_bp"),
        )
        if not isinstance(self.contributions, Mapping):
            raise TargetRiskError("contributions must be a mapping")
        frozen_contrib: dict[str, int] = {}
        for key, value in self.contributions.items():
            dim = _text(key, "contributions key")
            if dim not in {item.value for item in RiskDimension}:
                raise TargetRiskError(
                    f"contributions key {dim!r} is not a closed risk dimension"
                )
            frozen_contrib[dim] = _nonneg_int(
                value, f"contributions[{dim}]", maximum=MAX_RISK_WEIGHT_BP * 2
            )
        object.__setattr__(
            self,
            "contributions",
            MappingProxyType(dict(sorted(frozen_contrib.items()))),
        )
        object.__setattr__(
            self, "signals", RiskSignals.normalize(self.signals)
        )
        object.__setattr__(self, "selected", _bool(self.selected, "selected"))
        object.__setattr__(
            self,
            "selection_reason",
            _optional_text(self.selection_reason, "selection_reason"),
        )
        if self.rank is not None:
            object.__setattr__(
                self,
                "rank",
                _nonneg_int(self.rank, "rank", maximum=MAX_TARGETS * 4),
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RISK_SCORE_SCHEMA,
            "interface_id": RISK_SCORING_INTERFACE,
            "subject_id": self.subject_id,
            "risk_class": self.risk_class,
            "risk_weight_bp": self.risk_weight_bp,
            "contributions": dict(self.contributions),
            "signals": self.signals.identity_payload(),
            "selected": self.selected,
            "selection_reason": self.selection_reason,
            "rank": self.rank,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def score_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["signals"] = self.signals.to_dict()
        payload["score_cid"] = self.score_cid
        return payload

    def with_selection(
        self,
        *,
        selected: bool,
        selection_reason: str | None,
        rank: int | None,
    ) -> "RiskScore":
        return RiskScore(
            subject_id=self.subject_id,
            risk_class=self.risk_class,
            risk_weight_bp=self.risk_weight_bp,
            contributions=dict(self.contributions),
            signals=self.signals,
            selected=selected,
            selection_reason=selection_reason,
            rank=rank,
            notes=self.notes,
            metadata=_thaw_structured(self.metadata),
        )


@dataclass(frozen=True, slots=True)
class RiskCandidate:
    """Minimal subject descriptor accepted by ``rank_mutation_risk``."""

    subject_id: str
    risk_class: MutationRiskClass | str
    signals: RiskSignals | Mapping[str, Any] | None = None
    property_classes: Sequence[PropertyClass | str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id")
        )
        if self.property_classes:
            classes = [
                _enum(item, PropertyClass, "property_classes")
                for item in self.property_classes
            ]
            if len(classes) != len(set(classes)):
                raise TargetRiskError("property_classes must not contain duplicates")
            object.__setattr__(self, "property_classes", tuple(sorted(classes)))
            inferred = highest_risk_class(
                risk_class_for_property_class(item) for item in self.property_classes
            )
            if self.risk_class is None:  # pragma: no cover - dataclass always has value
                object.__setattr__(self, "risk_class", inferred)
            else:
                declared = _enum(self.risk_class, MutationRiskClass, "risk_class")
                # Keep the higher of declared and property-inferred priority.
                object.__setattr__(
                    self, "risk_class", highest_risk_class((declared, inferred))
                )
        else:
            object.__setattr__(
                self,
                "risk_class",
                _enum(self.risk_class, MutationRiskClass, "risk_class"),
            )
            object.__setattr__(self, "property_classes", ())
        object.__setattr__(
            self, "signals", RiskSignals.normalize(self.signals)
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))


def _normalize_candidate(
    value: RiskCandidate | Mapping[str, Any] | RiskScore,
) -> RiskCandidate:
    if isinstance(value, RiskScore):
        return RiskCandidate(
            subject_id=value.subject_id,
            risk_class=value.risk_class,
            signals=value.signals,
            metadata=_thaw_structured(value.metadata),
        )
    if isinstance(value, RiskCandidate):
        return value
    if not isinstance(value, Mapping):
        raise TargetRiskError(
            "candidates must be RiskCandidate, RiskScore, or mappings"
        )
    unknown = set(value) - {
        "subject_id",
        "risk_class",
        "signals",
        "property_classes",
        "metadata",
    }
    if unknown:
        raise TargetRiskError(
            f"RiskCandidate contains unknown fields: {', '.join(sorted(unknown))}"
        )
    if "subject_id" not in value:
        raise TargetRiskError("RiskCandidate requires subject_id")
    if "risk_class" not in value and not value.get("property_classes"):
        raise TargetRiskError(
            "RiskCandidate requires risk_class or property_classes"
        )
    return RiskCandidate(
        subject_id=value["subject_id"],
        risk_class=value.get("risk_class", MutationRiskClass.LOW.value),
        signals=value.get("signals"),
        property_classes=value.get("property_classes", ()),
        metadata=value.get("metadata", {}),
    )


def score_risk_candidate(
    candidate: RiskCandidate | Mapping[str, Any],
) -> RiskScore:
    """Score one candidate without applying sampling."""

    normalized = _normalize_candidate(candidate)
    weight, contributions = compute_risk_weight_bp(
        normalized.risk_class, normalized.signals
    )
    return RiskScore(
        subject_id=normalized.subject_id,
        risk_class=normalized.risk_class,
        risk_weight_bp=weight,
        contributions=dict(contributions),
        signals=normalized.signals,
        metadata=_thaw_structured(normalized.metadata),
    )


def _sort_key(score: RiskScore) -> tuple[int, int, str]:
    # Higher weight first; then higher-priority (lower rank index) class; then id.
    return (
        -score.risk_weight_bp,
        _RISK_CLASS_RANK[str(score.risk_class)],
        score.subject_id,
    )


def deterministic_sample_roll_bp(seed: int, subject_id: str) -> int:
    """Return a deterministic roll in ``[0, 10000)`` for bounded sampling."""

    if type(seed) is not int or isinstance(seed, bool) or seed < 0 or seed > MAX_SEED:
        raise TargetRiskError("seed must be a nonnegative integer within bounds")
    subject = _text(subject_id, "subject_id")
    digest = blake2b(
        f"{seed}\0{subject}".encode("utf-8"),
        digest_size=8,
    ).digest()
    value = int.from_bytes(digest, "big")
    return value % MAX_RISK_WEIGHT_BP


def apply_bounded_sampling(
    scores: Sequence[RiskScore],
    budget: SamplingBudget | Mapping[str, Any] | None = None,
) -> tuple[RiskScore, ...]:
    """Apply explicit bounded sampling to ranked scores.

    Returns all scores with ``selected``/``rank``/``selection_reason`` filled.
    Selected scores occupy ranks ``0..n-1`` in ranking order; non-selected keep
    ``rank=None``.
    """

    budget_n = SamplingBudget.normalize(budget)
    ordered = sorted(scores, key=_sort_key)
    selected_ids: list[str] = []
    updated: list[RiskScore] = []

    for score in ordered:
        reason: str | None = None
        choose = False
        if len(selected_ids) >= budget_n.max_targets:
            reason = "budget_exhausted"
        elif score.risk_weight_bp >= budget_n.always_select_min_risk_bp:
            choose = True
            reason = "always_select_threshold"
        else:
            roll = deterministic_sample_roll_bp(budget_n.seed, score.subject_id)
            # Scale sample rate by relative weight so higher residual risk is
            # more likely under the low-risk quota.
            scaled_rate = (
                budget_n.low_risk_sample_rate_bp * score.risk_weight_bp
            ) // MAX_RISK_WEIGHT_BP
            if roll < scaled_rate:
                choose = True
                reason = "low_risk_sample"
            else:
                reason = "low_risk_rejected"
        if choose:
            rank = len(selected_ids)
            selected_ids.append(score.subject_id)
            updated.append(
                score.with_selection(
                    selected=True, selection_reason=reason, rank=rank
                )
            )
        else:
            updated.append(
                score.with_selection(
                    selected=False, selection_reason=reason, rank=None
                )
            )
    return tuple(updated)


def rank_mutation_risk(
    candidates: Sequence[RiskCandidate | Mapping[str, Any] | RiskScore],
    *,
    budget: SamplingBudget | Mapping[str, Any] | None = None,
    apply_sampling: bool = True,
) -> tuple[RiskScore, ...]:
    """Score and rank mutation subjects under optional bounded sampling.

    Deterministic for identical candidates, signals, and budget. Fail-closed on
    unknown fields, duplicate subject IDs, and invalid enums. When
    ``apply_sampling`` is false, returns scores ordered by risk without
    selection marks (``selected=False``, ``rank=None``).
    """

    if not isinstance(candidates, (list, tuple)):
        raise TargetRiskError("candidates must be a sequence")
    if len(candidates) > MAX_CLAIMS:
        raise TargetRiskError("candidates exceeds maximum length")

    scored: list[RiskScore] = []
    seen: set[str] = set()
    for item in candidates:
        score = score_risk_candidate(item)
        if score.subject_id in seen:
            raise TargetRiskError(
                f"duplicate subject_id {score.subject_id!r} in candidates"
            )
        seen.add(score.subject_id)
        scored.append(score)

    ordered = tuple(sorted(scored, key=_sort_key))
    if not apply_sampling:
        return ordered
    return apply_bounded_sampling(ordered, budget)


def selected_risk_scores(
    ranking: Sequence[RiskScore],
) -> tuple[RiskScore, ...]:
    """Return selected scores in rank order."""

    selected = [score for score in ranking if score.selected]
    return tuple(sorted(selected, key=lambda item: (item.rank if item.rank is not None else 10**9, item.subject_id)))


__all__ = [
    "DEFAULT_ALWAYS_SELECT_MIN_RISK_BP",
    "DEFAULT_LOW_RISK_SAMPLE_RATE_BP",
    "DEFAULT_MAX_TARGETS",
    "MAX_CLAIMS",
    "MAX_DEFECTS",
    "MAX_FAN_OUT",
    "MAX_TEXT_CHARS",
    "PROPERTY_CLASS_RISK",
    "RISK_CLASS_BASE_WEIGHT_BP",
    "RISK_RANKING_SCHEMA",
    "RISK_SCORE_SCHEMA",
    "RISK_SCORING_INTERFACE",
    "RISK_SIGNALS_SCHEMA",
    "SAMPLING_BUDGET_SCHEMA",
    "RiskCandidate",
    "RiskDimension",
    "RiskScore",
    "RiskSignals",
    "SamplingBudget",
    "TargetRiskError",
    "apply_bounded_sampling",
    "compute_risk_weight_bp",
    "deterministic_sample_roll_bp",
    "highest_risk_class",
    "primary_dimension_for_risk_class",
    "rank_mutation_risk",
    "risk_class_base_weight_bp",
    "risk_class_for_property_class",
    "risk_dimensions",
    "score_risk_candidate",
    "selected_risk_scores",
]
