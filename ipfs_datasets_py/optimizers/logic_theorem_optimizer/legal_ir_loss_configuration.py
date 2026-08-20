"""Versioned composite loss and sampling contracts for proof-grounded IR learning.

``IRLossConfiguration@1`` is the fixed-point owner of signs, normalization,
proof gating, and anti-shortcut exclusions.  Family-specific experimental
objectives do not become this contract.  Durable weights are rationals so
checkpoints never persist IEEE floats.  Proof outcomes stay
non-differentiable labels, ranking, or curriculum signals and never enter
the ordinary gradient path.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Optional

from .legal_ir_grammar_decoder import LEGAL_IR_TOKEN_CLASSES


IR_LOSS_CONFIGURATION_SCHEMA: Final = "IRLossConfiguration@1"
IR_LOSS_CONFIGURATION_INTERFACE: Final = (
    "proof-grounded-ir-learning/loss-configuration/v1"
)
IR_LOSS_CONFIGURATION_SCHEMA_VERSION: Final = "ir-loss-configuration-v1"
IR_LOSS_SAMPLER_SCHEMA: Final = "IRLossSampler@1"
IR_LOSS_MEMORY_BANK_SCHEMA: Final = "IRLossMemoryBank@1"
IR_LOSS_SCHEDULE_SCHEMA: Final = "IRLossSchedule@1"
IR_LOSS_PRECISION_SCHEMA: Final = "IRLossPrecision@1"

IR_LOSS_COMPONENT_NAMES: Final[tuple[str, ...]] = (
    "token_class_ce",
    "normalized_cosine",
    "supervised_contrastive",
    "cycle",
    "structural",
    "relation",
    "semantic",
    "proof",
    "source_span",
    "calibration",
    "regularization",
)

IR_LOSS_REPORTED_TOKEN_CLASSES: Final[tuple[str, ...]] = (
    "padding",
    "binder",
    "operator",
    "type",
    "source",
    "family",
    "proof",
    "tactic",
)
if any(name not in LEGAL_IR_TOKEN_CLASSES for name in IR_LOSS_REPORTED_TOKEN_CLASSES):
    raise RuntimeError("reported token classes must be a subset of LEGAL_IR_TOKEN_CLASSES")

IR_LOSS_TOKEN_CLASS_ALIASES: Final[Mapping[str, str]] = {
    "binders": "binder",
    "operators": "operator",
    "types": "type",
    "source_surface": "source",
}

IR_LOSS_DECODE_MODES: Final[tuple[str, ...]] = (
    "teacher_forcing",
    "free_run",
)

IR_LOSS_FALSE_NEGATIVE_CLASSES: Final[tuple[str, ...]] = (
    "same_lineage",
    "alpha_equivalent",
    "alternate_notation",
    "translation_sibling",
    "proof_equivalent",
)

IR_LOSS_EXCLUSIONS: Final[tuple[str, ...]] = (
    "proof_calls_in_gradient_path",
    "floats_in_durable_weights",
    "aggregate_ce_hiding_token_classes",
    "all_record_cosine_maximization",
    "source_surface_in_canonical_ce",
    "unfiltered_false_negatives",
    "mixed_teacher_forcing_free_run_total",
)

DEFAULT_CONTRASTIVE_TEMPERATURE_RATIONAL: Final = (1, 1)
DEFAULT_MEMORY_BANK_CAPACITY: Final = 64
DEFAULT_SAMPLER_SEED: Final = 32
LOG_CLAMP: Final = 1.0e-12
SOFTMAX_FLOOR: Final = 1.0e-12


class IRLossConfigurationError(ValueError):
    """Base error for the versioned composite-loss contract."""


class IRLossNonfiniteError(IRLossConfigurationError):
    """Raised when a loss input or output is NaN or infinite."""


class AllRecordCosineMaximizationError(IRLossConfigurationError):
    """Raised when cosine is requested over an unadmitted all-record set."""


class ProofInGradientPathError(IRLossConfigurationError):
    """Raised when a proof call or differentiable proof term is requested."""


class DurableFloatWeightError(IRLossConfigurationError):
    """Raised when a durable weight payload contains an IEEE float."""


class IsolatedLossMissingError(IRLossConfigurationError):
    """Raised when an isolation request names an unknown component."""


class MemoryBankCheckpointMismatchError(IRLossConfigurationError):
    """Raised when a memory bank is reused against another checkpoint."""


class AdaptiveWeightBoundError(IRLossConfigurationError):
    """Raised when an adaptive weight escapes its declared bounds."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise DurableFloatWeightError("IEEE floats are forbidden in durable loss payloads")
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    return repr(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _content_cid(value: Any) -> str:
    return f"sha256:{_digest(value)}"


def _require_finite(value: float, *, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise IRLossNonfiniteError(f"{name} is not finite")
    return number


def _gcd(left: int, right: int) -> int:
    while right:
        left, right = right, left % right
    return abs(left) or 1


def canonical_token_class(name: str) -> str:
    raw = str(name or "").strip()
    return IR_LOSS_TOKEN_CLASS_ALIASES.get(raw, raw)


def reported_token_classes() -> tuple[str, ...]:
    return IR_LOSS_REPORTED_TOKEN_CLASSES


@dataclass(frozen=True, slots=True)
class FixedPointWeight:
    """Durable rational weight.  Never serialized as an IEEE float."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        num = int(self.numerator)
        den = int(self.denominator)
        if den == 0:
            raise IRLossConfigurationError("weight denominator must be non-zero")
        if den < 0:
            num = -num
            den = -den
        divisor = _gcd(num, den)
        object.__setattr__(self, "numerator", num // divisor)
        object.__setattr__(self, "denominator", den // divisor)

    @classmethod
    def from_parts(cls, numerator: int, denominator: int = 1) -> "FixedPointWeight":
        return cls(int(numerator), int(denominator))

    @classmethod
    def zero(cls) -> "FixedPointWeight":
        return cls(0, 1)

    @classmethod
    def one(cls) -> "FixedPointWeight":
        return cls(1, 1)

    @classmethod
    def parse(cls, value: Any) -> "FixedPointWeight":
        if isinstance(value, FixedPointWeight):
            return value
        if isinstance(value, bool):
            raise DurableFloatWeightError("boolean is not a durable weight")
        if isinstance(value, int):
            return cls(int(value), 1)
        if isinstance(value, float):
            raise DurableFloatWeightError("IEEE floats are forbidden in durable weights")
        if isinstance(value, Mapping):
            if any(isinstance(item, float) for item in value.values()):
                raise DurableFloatWeightError("IEEE floats are forbidden in durable weights")
            return cls(int(value["numerator"]), int(value.get("denominator", 1)))
        text = str(value).strip()
        if "/" in text:
            left, right = text.split("/", 1)
            return cls(int(left), int(right))
        return cls(int(text), 1)

    def as_float(self) -> float:
        return float(self.numerator) / float(self.denominator)

    def clamp(self, minimum: "FixedPointWeight", maximum: "FixedPointWeight") -> "FixedPointWeight":
        value = self.as_float()
        if value < minimum.as_float():
            return minimum
        if value > maximum.as_float():
            return maximum
        return self

    def to_dict(self) -> dict[str, int | str]:
        return {
            "denominator": int(self.denominator),
            "numerator": int(self.numerator),
            "rational": f"{int(self.numerator)}/{int(self.denominator)}",
        }


@dataclass(frozen=True, slots=True)
class IRLossPrecisionIdentity:
    """Pinned compute/durable precision contract."""

    compute_dtype: str = "float64"
    durable_weight_encoding: str = "rational"
    accumulator: str = "ieee754_float64"
    log_clamp_numerator: int = 1
    log_clamp_denominator: int = 1_000_000_000_000
    schema: str = IR_LOSS_PRECISION_SCHEMA

    def __post_init__(self) -> None:
        if self.durable_weight_encoding != "rational":
            raise IRLossConfigurationError("durable weights must use rational encoding")
        if self.compute_dtype not in {"float32", "float64"}:
            raise IRLossConfigurationError("compute dtype must be float32 or float64")

    def identity(self) -> str:
        return _content_cid(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "accumulator": self.accumulator,
            "compute_dtype": self.compute_dtype,
            "durable_weight_encoding": self.durable_weight_encoding,
            "log_clamp": {
                "denominator": int(self.log_clamp_denominator),
                "numerator": int(self.log_clamp_numerator),
            },
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True)
class IRLossSchedule:
    """Teacher-forcing and free-run remain distinct decode contracts."""

    teacher_forcing: bool = True
    free_run: bool = True
    scheduled_sampling: bool = False
    scheduled_sampling_numerator: int = 0
    scheduled_sampling_denominator: int = 1
    schema: str = IR_LOSS_SCHEDULE_SCHEMA

    def __post_init__(self) -> None:
        if not self.teacher_forcing and not self.free_run:
            raise IRLossConfigurationError("at least one decode mode is required")
        if self.scheduled_sampling_denominator <= 0:
            raise IRLossConfigurationError("scheduled sampling denominator must be positive")
        if self.scheduled_sampling_numerator < 0:
            raise IRLossConfigurationError("scheduled sampling numerator must be non-negative")
        if self.scheduled_sampling_numerator > self.scheduled_sampling_denominator:
            raise IRLossConfigurationError("scheduled sampling ratio must be at most one")
        if self.scheduled_sampling and self.scheduled_sampling_numerator == 0:
            raise IRLossConfigurationError("scheduled sampling cannot be enabled at ratio 0")

    @property
    def decode_modes(self) -> tuple[str, ...]:
        modes: list[str] = []
        if self.teacher_forcing:
            modes.append("teacher_forcing")
        if self.free_run:
            modes.append("free_run")
        return tuple(modes)

    def identity(self) -> str:
        return _content_cid(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decode_modes": list(self.decode_modes),
            "free_run": self.free_run,
            "scheduled_sampling": self.scheduled_sampling,
            "scheduled_sampling_ratio": {
                "denominator": int(self.scheduled_sampling_denominator),
                "numerator": int(self.scheduled_sampling_numerator),
            },
            "schema": self.schema,
            "teacher_forcing": self.teacher_forcing,
        }


@dataclass(frozen=True, slots=True)
class IRLossSamplerContract:
    """Reproducible contrastive/InfoNCE sampler identity."""

    algorithm: str = "seeded_infonce_v1"
    seed: int = DEFAULT_SAMPLER_SEED
    false_negative_filter: str = "lineage_alpha_notation_translation_proof_v1"
    false_negative_classes: tuple[str, ...] = IR_LOSS_FALSE_NEGATIVE_CLASSES
    memory_bank_bound: bool = True
    allow_all_record_negatives: bool = False
    schema: str = IR_LOSS_SAMPLER_SCHEMA

    def __post_init__(self) -> None:
        if self.allow_all_record_negatives:
            raise AllRecordCosineMaximizationError(
                "all-record negative sampling is excluded from IRLossConfiguration@1"
            )
        classes = tuple(str(item) for item in self.false_negative_classes)
        if classes != IR_LOSS_FALSE_NEGATIVE_CLASSES:
            raise IRLossConfigurationError(
                "false-negative classes must match the frozen filter vocabulary"
            )
        object.__setattr__(self, "false_negative_classes", classes)

    def identity(self) -> str:
        return _content_cid(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "allow_all_record_negatives": False,
            "false_negative_classes": list(self.false_negative_classes),
            "false_negative_filter": self.false_negative_filter,
            "memory_bank_bound": self.memory_bank_bound,
            "schema": self.schema,
            "seed": int(self.seed),
        }


@dataclass(frozen=True, slots=True)
class IRLossMemoryBank:
    """Checkpoint-bound contrastive memory bank."""

    checkpoint_id: str
    capacity: int = DEFAULT_MEMORY_BANK_CAPACITY
    keys: tuple[str, ...] = ()
    vectors: tuple[tuple[str, ...], ...] = ()
    schema: str = IR_LOSS_MEMORY_BANK_SCHEMA

    def __post_init__(self) -> None:
        if not str(self.checkpoint_id or "").strip():
            raise IRLossConfigurationError("memory bank must bind a checkpoint identity")
        if int(self.capacity) <= 0:
            raise IRLossConfigurationError("memory bank capacity must be positive")
        if len(self.keys) != len(self.vectors):
            raise IRLossConfigurationError("memory bank keys and vectors must align")
        if len(self.keys) > int(self.capacity):
            raise IRLossConfigurationError("memory bank exceeds its declared capacity")

    def identity(self) -> str:
        return _content_cid(self.to_dict())

    def bind(self, checkpoint_id: str) -> "IRLossMemoryBank":
        if str(checkpoint_id) != str(self.checkpoint_id):
            raise MemoryBankCheckpointMismatchError(
                "memory bank is bound to a different checkpoint"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity": int(self.capacity),
            "checkpoint_id": self.checkpoint_id,
            "count": len(self.keys),
            "keys": list(self.keys),
            "schema": self.schema,
            "vectors": [list(vector) for vector in self.vectors],
        }


@dataclass(frozen=True, slots=True)
class IRLossComponentSpec:
    """One isolatable composite-loss term."""

    name: str
    weight: FixedPointWeight
    sign: str
    in_gradient_path: bool
    normalization: str
    role: str
    adaptive_minimum: FixedPointWeight = field(default_factory=FixedPointWeight.zero)
    adaptive_maximum: FixedPointWeight = field(default_factory=FixedPointWeight.one)

    def __post_init__(self) -> None:
        if self.name not in IR_LOSS_COMPONENT_NAMES:
            raise IsolatedLossMissingError(f"unknown loss component {self.name!r}")
        if self.sign not in {"minimize", "maximize_as_ranking"}:
            raise IRLossConfigurationError(f"unsupported sign {self.sign!r}")
        if self.name == "proof" and self.in_gradient_path:
            raise ProofInGradientPathError("proof signals cannot enter the gradient path")
        if self.adaptive_maximum.as_float() < self.adaptive_minimum.as_float():
            raise AdaptiveWeightBoundError(f"{self.name} adaptive bounds are inverted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptive_maximum": self.adaptive_maximum.to_dict(),
            "adaptive_minimum": self.adaptive_minimum.to_dict(),
            "in_gradient_path": self.in_gradient_path,
            "name": self.name,
            "normalization": self.normalization,
            "role": self.role,
            "sign": self.sign,
            "weight": self.weight.to_dict(),
        }


def _baseline_component_specs() -> dict[str, IRLossComponentSpec]:
    return {
        "token_class_ce": IRLossComponentSpec(
            name="token_class_ce",
            weight=FixedPointWeight(1, 1),
            sign="minimize",
            in_gradient_path=True,
            normalization="masked_mean_per_token_class",
            role="reconstruction",
            adaptive_minimum=FixedPointWeight(1, 2),
            adaptive_maximum=FixedPointWeight(3, 1),
        ),
        "normalized_cosine": IRLossComponentSpec(
            name="normalized_cosine",
            weight=FixedPointWeight(1, 2),
            sign="minimize",
            in_gradient_path=True,
            normalization="l2_unit_admitted_pairs_only",
            role="alignment",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(2, 1),
        ),
        "supervised_contrastive": IRLossComponentSpec(
            name="supervised_contrastive",
            weight=FixedPointWeight(1, 2),
            sign="minimize",
            in_gradient_path=True,
            normalization="infonce_filtered_negatives",
            role="retrieval",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(2, 1),
        ),
        "cycle": IRLossComponentSpec(
            name="cycle",
            weight=FixedPointWeight(1, 4),
            sign="minimize",
            in_gradient_path=True,
            normalization="mean_reconstruction",
            role="cycle",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(1, 1),
        ),
        "structural": IRLossComponentSpec(
            name="structural",
            weight=FixedPointWeight(1, 2),
            sign="minimize",
            in_gradient_path=True,
            normalization="mean_slot_penalty",
            role="structure",
            adaptive_minimum=FixedPointWeight(1, 4),
            adaptive_maximum=FixedPointWeight(2, 1),
        ),
        "relation": IRLossComponentSpec(
            name="relation",
            weight=FixedPointWeight(1, 4),
            sign="minimize",
            in_gradient_path=True,
            normalization="mean_relation_penalty",
            role="relation",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(1, 1),
        ),
        "semantic": IRLossComponentSpec(
            name="semantic",
            weight=FixedPointWeight(1, 2),
            sign="minimize",
            in_gradient_path=True,
            normalization="admitted_semantic_gap",
            role="semantic",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(2, 1),
        ),
        "proof": IRLossComponentSpec(
            name="proof",
            weight=FixedPointWeight(0, 1),
            sign="maximize_as_ranking",
            in_gradient_path=False,
            normalization="nondifferentiable_label",
            role="curriculum",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(0, 1),
        ),
        "source_span": IRLossComponentSpec(
            name="source_span",
            weight=FixedPointWeight(1, 2),
            sign="minimize",
            in_gradient_path=True,
            normalization="anti_copy_span_penalty",
            role="anti_shortcut",
            adaptive_minimum=FixedPointWeight(1, 4),
            adaptive_maximum=FixedPointWeight(2, 1),
        ),
        "calibration": IRLossComponentSpec(
            name="calibration",
            weight=FixedPointWeight(1, 8),
            sign="minimize",
            in_gradient_path=False,
            normalization="brier_ece_detached",
            role="calibration",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(1, 2),
        ),
        "regularization": IRLossComponentSpec(
            name="regularization",
            weight=FixedPointWeight(1, 16),
            sign="minimize",
            in_gradient_path=True,
            normalization="mean_l2",
            role="regularizer",
            adaptive_minimum=FixedPointWeight(0, 1),
            adaptive_maximum=FixedPointWeight(1, 4),
        ),
    }


@dataclass(frozen=True, slots=True)
class IRLossConfiguration:
    """Fixed-point ``IRLossConfiguration@1`` contract."""

    components: Mapping[str, IRLossComponentSpec]
    precision: IRLossPrecisionIdentity
    schedule: IRLossSchedule
    sampler: IRLossSamplerContract
    tokenizer_vocabulary_cid: str = ""
    architecture_initialization_root: str = ""
    adaptive_weights_enabled: bool = False
    exclusions: tuple[str, ...] = IR_LOSS_EXCLUSIONS
    schema: str = IR_LOSS_CONFIGURATION_SCHEMA
    interface: str = IR_LOSS_CONFIGURATION_INTERFACE
    schema_version: str = IR_LOSS_CONFIGURATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        missing = [name for name in IR_LOSS_COMPONENT_NAMES if name not in self.components]
        extra = [name for name in self.components if name not in IR_LOSS_COMPONENT_NAMES]
        if missing or extra:
            raise IRLossConfigurationError(
                f"component set must be exactly {IR_LOSS_COMPONENT_NAMES}"
            )
        if tuple(self.exclusions) != IR_LOSS_EXCLUSIONS:
            raise IRLossConfigurationError("anti-shortcut exclusions are frozen")
        object.__setattr__(self, "components", dict(self.components))

    def identity(self) -> str:
        return _content_cid(self.to_dict())

    def component(self, name: str) -> IRLossComponentSpec:
        if name not in self.components:
            raise IsolatedLossMissingError(f"unknown loss component {name!r}")
        return self.components[name]

    def weight_for(self, name: str, *, adaptive: Optional[FixedPointWeight] = None) -> float:
        spec = self.component(name)
        weight = spec.weight
        if adaptive is not None:
            if not self.adaptive_weights_enabled:
                raise AdaptiveWeightBoundError("adaptive weights are disabled on this contract")
            if adaptive.as_float() < spec.adaptive_minimum.as_float() or (
                adaptive.as_float() > spec.adaptive_maximum.as_float()
            ):
                raise AdaptiveWeightBoundError(
                    f"{name} adaptive weight {adaptive.to_dict()} is out of bounds"
                )
            weight = adaptive.clamp(spec.adaptive_minimum, spec.adaptive_maximum)
        return weight.as_float()

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptive_weights_enabled": self.adaptive_weights_enabled,
            "architecture_initialization_root": self.architecture_initialization_root,
            "components": {
                name: self.components[name].to_dict() for name in IR_LOSS_COMPONENT_NAMES
            },
            "exclusions": list(self.exclusions),
            "interface": self.interface,
            "precision": self.precision.to_dict(),
            "precision_identity": self.precision.identity(),
            "sampler": self.sampler.to_dict(),
            "sampler_identity": self.sampler.identity(),
            "schedule": self.schedule.to_dict(),
            "schedule_identity": self.schedule.identity(),
            "schema": self.schema,
            "schema_version": self.schema_version,
            "tokenizer_vocabulary_cid": self.tokenizer_vocabulary_cid,
        }


def canonical_ir_loss_configuration(
    *,
    tokenizer_vocabulary_cid: str = "",
    architecture_initialization_root: str = "",
    adaptive_weights_enabled: bool = False,
    sampler_seed: int = DEFAULT_SAMPLER_SEED,
) -> IRLossConfiguration:
    """Return the frozen static-baseline ``IRLossConfiguration@1``."""

    return IRLossConfiguration(
        components=_baseline_component_specs(),
        precision=IRLossPrecisionIdentity(),
        schedule=IRLossSchedule(),
        sampler=IRLossSamplerContract(seed=int(sampler_seed)),
        tokenizer_vocabulary_cid=str(tokenizer_vocabulary_cid or ""),
        architecture_initialization_root=str(architecture_initialization_root or ""),
        adaptive_weights_enabled=bool(adaptive_weights_enabled),
    )


def bind_memory_bank_to_checkpoint(
    checkpoint_id: str,
    *,
    capacity: int = DEFAULT_MEMORY_BANK_CAPACITY,
    keys: Sequence[str] = (),
    vectors: Sequence[Sequence[Any]] = (),
) -> IRLossMemoryBank:
    encoded_vectors = tuple(
        tuple(_rational_coordinate(value) for value in vector) for vector in vectors
    )
    return IRLossMemoryBank(
        checkpoint_id=str(checkpoint_id),
        capacity=int(capacity),
        keys=tuple(str(key) for key in keys),
        vectors=encoded_vectors,
    )


def _rational_coordinate(value: Any) -> str:
    if isinstance(value, float):
        raise DurableFloatWeightError("memory-bank vectors must use rational coordinates")
    if isinstance(value, FixedPointWeight):
        return value.to_dict()["rational"]
    if isinstance(value, int):
        return f"{int(value)}/1"
    text = str(value).strip()
    return FixedPointWeight.parse(text).to_dict()["rational"]


@dataclass(frozen=True, slots=True)
class IRLossPairAdmission:
    """One admitted pair for cosine or contrastive terms."""

    left_id: str
    right_id: str
    pair_class: str
    admitted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "left_id": self.left_id,
            "pair_class": self.pair_class,
            "right_id": self.right_id,
        }


@dataclass(frozen=True, slots=True)
class IRLossRecord:
    """One training record consumed by the composite loss."""

    record_id: str
    lineage_id: str
    token_ids: tuple[int, ...] = ()
    token_classes: tuple[str, ...] = ()
    teacher_forcing_logits: tuple[tuple[float, ...], ...] = ()
    free_run_logits: tuple[tuple[float, ...], ...] = ()
    latent: tuple[float, ...] = ()
    reconstruction: tuple[float, ...] = ()
    cycle_target: tuple[float, ...] = ()
    structural_penalty: float = 0.0
    relation_penalty: float = 0.0
    semantic_gap: float = 0.0
    proof_label: str = "unchecked"
    proof_success: float = 0.0
    source_span_penalty: float = 0.0
    confidence: float = 0.0
    correctness: float = 0.0
    parameter_l2: float = 0.0
    false_negative_class: str = ""
    pair_ids: tuple[str, ...] = ()

    def decoded_logits(self, mode: str) -> tuple[tuple[float, ...], ...]:
        if mode == "teacher_forcing":
            return self.teacher_forcing_logits
        if mode == "free_run":
            return self.free_run_logits
        raise IRLossConfigurationError(f"unknown decode mode {mode!r}")


@dataclass(frozen=True, slots=True)
class IRLossBatch:
    """Closed batch consumed by ``evaluate_ir_composite_loss``."""

    records: tuple[IRLossRecord, ...]
    pair_admissions: tuple[IRLossPairAdmission, ...] = ()
    decode_mode: str = "teacher_forcing"
    checkpoint_id: str = "unbound-checkpoint"
    memory_bank: Optional[IRLossMemoryBank] = None
    adaptive_weights: Mapping[str, FixedPointWeight] = field(default_factory=dict)
    isolate: tuple[str, ...] = ()
    proof_callable: Any = None

    def __post_init__(self) -> None:
        if self.decode_mode not in IR_LOSS_DECODE_MODES:
            raise IRLossConfigurationError(f"decode mode must be one of {IR_LOSS_DECODE_MODES}")
        if self.proof_callable is not None:
            raise ProofInGradientPathError(
                "proof callables are forbidden on the ordinary gradient path"
            )
        isolates = tuple(str(name) for name in self.isolate)
        unknown = [name for name in isolates if name not in IR_LOSS_COMPONENT_NAMES]
        if unknown:
            raise IsolatedLossMissingError(f"unknown isolate components {unknown!r}")
        object.__setattr__(self, "isolate", isolates)
        object.__setattr__(self, "adaptive_weights", dict(self.adaptive_weights))


@dataclass(frozen=True, slots=True)
class IRLossComponentMetrics:
    """Isolatable component metrics, including token-class CE breakdown."""

    name: str
    raw: float
    weighted: float
    in_gradient_path: bool
    token_class_ce: Mapping[str, float] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "in_gradient_path": self.in_gradient_path,
            "name": self.name,
            "raw": self.raw,
            "weighted": self.weighted,
        }
        if self.token_class_ce:
            payload["token_class_ce"] = {
                name: float(self.token_class_ce[name]) for name in sorted(self.token_class_ce)
            }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True, slots=True)
class IRCompositeLossResult:
    """Exact composite evaluation with identities and component metrics."""

    total: float
    gradient_total: float
    decode_mode: str
    configuration_identity: str
    precision_identity: str
    schedule_identity: str
    sampler_identity: str
    memory_bank_identity: str
    components: Mapping[str, IRLossComponentMetrics]
    isolated: tuple[str, ...]
    proof_in_gradient_path: bool
    nonfinite_policy: str
    schema: str = IR_LOSS_CONFIGURATION_SCHEMA

    def component(self, name: str) -> IRLossComponentMetrics:
        if name not in self.components:
            raise IsolatedLossMissingError(f"unknown loss component {name!r}")
        return self.components[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": {
                name: self.components[name].to_dict() for name in IR_LOSS_COMPONENT_NAMES
            },
            "configuration_identity": self.configuration_identity,
            "decode_mode": self.decode_mode,
            "gradient_total": self.gradient_total,
            "isolated": list(self.isolated),
            "memory_bank_identity": self.memory_bank_identity,
            "nonfinite_policy": self.nonfinite_policy,
            "precision_identity": self.precision_identity,
            "proof_in_gradient_path": self.proof_in_gradient_path,
            "sampler_identity": self.sampler_identity,
            "schedule_identity": self.schedule_identity,
            "schema": self.schema,
            "total": self.total,
        }


def softmax(logits: Sequence[float]) -> list[float]:
    values = [_require_finite(value, name="logit") for value in logits]
    if not values:
        return []
    peak = max(values)
    shifted = [math.exp(value - peak) for value in values]
    total = sum(shifted)
    if total <= 0.0:
        raise IRLossNonfiniteError("softmax denominator is not positive")
    return [max(item / total, SOFTMAX_FLOOR) for item in shifted]


def masked_token_class_cross_entropy(
    logits: Sequence[Sequence[float]],
    targets: Sequence[int],
    token_classes: Sequence[str],
    *,
    include_padding_in_total: bool = False,
) -> tuple[float, dict[str, float], dict[str, int]]:
    """Return mean CE, per-class CE, and per-class counts.

    Padding, binders, operators, types, source, family, proof, and tactic
    tokens are reported separately.  Aggregate CE never hides those classes.
    Source-surface tokens are excluded from the canonical training mean.
    """

    if len(logits) != len(targets) or len(targets) != len(token_classes):
        raise IRLossConfigurationError("logits, targets, and token classes must align")
    per_class_sums = {name: 0.0 for name in IR_LOSS_REPORTED_TOKEN_CLASSES}
    per_class_counts = {name: 0 for name in IR_LOSS_REPORTED_TOKEN_CLASSES}
    training_sum = 0.0
    training_count = 0
    for row, target, raw_class in zip(logits, targets, token_classes):
        token_class = canonical_token_class(raw_class)
        probabilities = softmax(row)
        if target < 0 or target >= len(probabilities):
            raise IRLossConfigurationError("target token id is outside the logit row")
        nll = -math.log(max(probabilities[int(target)], LOG_CLAMP))
        _require_finite(nll, name="token_class_ce")
        if token_class in per_class_sums:
            per_class_sums[token_class] += nll
            per_class_counts[token_class] += 1
        exclude = token_class == "source" or (
            token_class == "padding" and not include_padding_in_total
        )
        if not exclude:
            training_sum += nll
            training_count += 1
    per_class = {
        name: (per_class_sums[name] / per_class_counts[name] if per_class_counts[name] else 0.0)
        for name in IR_LOSS_REPORTED_TOKEN_CLASSES
    }
    mean = training_sum / training_count if training_count else 0.0
    return mean, per_class, per_class_counts


def l2_normalize(vector: Sequence[float]) -> list[float]:
    values = [_require_finite(value, name="vector") for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        raise IRLossConfigurationError("zero vectors cannot be L2-normalized for cosine")
    return [value / norm for value in values]


def normalized_cosine_loss(left: Sequence[float], right: Sequence[float]) -> float:
    unit_left = l2_normalize(left)
    unit_right = l2_normalize(right)
    similarity = sum(a * b for a, b in zip(unit_left, unit_right))
    return _require_finite(1.0 - similarity, name="normalized_cosine")


def supervised_contrastive_loss(
    anchor: Sequence[float],
    positive: Sequence[float],
    negatives: Sequence[Sequence[float]],
    *,
    temperature: float = 1.0,
) -> float:
    if temperature <= 0.0:
        raise IRLossConfigurationError("contrastive temperature must be positive")
    anchor_unit = l2_normalize(anchor)
    positive_sim = sum(a * b for a, b in zip(anchor_unit, l2_normalize(positive))) / temperature
    scores = [positive_sim]
    for negative in negatives:
        scores.append(
            sum(a * b for a, b in zip(anchor_unit, l2_normalize(negative))) / temperature
        )
    probabilities = softmax(scores)
    return _require_finite(-math.log(max(probabilities[0], LOG_CLAMP)), name="supervised_contrastive")


def mean_squared_error(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise IRLossConfigurationError("cycle vectors must have the same length")
    if not left:
        return 0.0
    total = 0.0
    for a, b in zip(left, right):
        delta = _require_finite(a, name="cycle") - _require_finite(b, name="cycle")
        total += delta * delta
    return total / len(left)


def brier_score(confidence: float, correctness: float) -> float:
    delta = _require_finite(confidence, name="confidence") - _require_finite(
        correctness, name="correctness"
    )
    return delta * delta


def filter_false_negatives(
    anchor: IRLossRecord,
    candidates: Sequence[IRLossRecord],
    admissions: Sequence[IRLossPairAdmission],
) -> tuple[tuple[IRLossRecord, ...], tuple[IRLossRecord, ...]]:
    """Return (admitted_negatives, filtered_false_negatives)."""

    admitted_ids = {
        (item.left_id, item.right_id)
        for item in admissions
        if item.admitted
    }
    admitted_ids.update((item.right_id, item.left_id) for item in admissions if item.admitted)
    kept: list[IRLossRecord] = []
    filtered: list[IRLossRecord] = []
    for candidate in candidates:
        if candidate.record_id == anchor.record_id:
            continue
        reason = _false_negative_reason(anchor, candidate)
        pair_admitted = (anchor.record_id, candidate.record_id) in admitted_ids
        if reason or not pair_admitted:
            filtered.append(candidate)
            continue
        kept.append(candidate)
    return tuple(kept), tuple(filtered)


def _false_negative_reason(anchor: IRLossRecord, candidate: IRLossRecord) -> str:
    if candidate.false_negative_class in IR_LOSS_FALSE_NEGATIVE_CLASSES:
        return candidate.false_negative_class
    if anchor.lineage_id and candidate.lineage_id == anchor.lineage_id:
        return "same_lineage"
    if candidate.record_id in set(anchor.pair_ids):
        return "proof_equivalent"
    return ""


def sample_contrastive_negatives(
    anchor: IRLossRecord,
    candidates: Sequence[IRLossRecord],
    admissions: Sequence[IRLossPairAdmission],
    sampler: IRLossSamplerContract,
    *,
    memory_bank: Optional[IRLossMemoryBank] = None,
    checkpoint_id: str = "",
    limit: int = 8,
) -> tuple[tuple[IRLossRecord, ...], tuple[IRLossRecord, ...], str]:
    kept, filtered = filter_false_negatives(anchor, candidates, admissions)
    if memory_bank is not None:
        memory_bank.bind(checkpoint_id or memory_bank.checkpoint_id)
    ordered = sorted(kept, key=lambda item: item.record_id)
    selected: list[IRLossRecord] = []
    cursor = int(sampler.seed)
    pool = list(ordered)
    while pool and len(selected) < int(limit):
        cursor = (cursor * 1103515245 + 12345) & 0x7FFFFFFF
        index = cursor % len(pool)
        selected.append(pool.pop(index))
    return tuple(selected), filtered, sampler.identity()


def evaluate_ir_composite_loss(
    batch: IRLossBatch,
    configuration: Optional[IRLossConfiguration] = None,
) -> IRCompositeLossResult:
    """Evaluate the isolatable composite under ``IRLossConfiguration@1``."""

    config = configuration or canonical_ir_loss_configuration()
    if batch.proof_callable is not None:
        raise ProofInGradientPathError("proof calls are forbidden in the ordinary gradient path")
    if batch.memory_bank is not None:
        batch.memory_bank.bind(batch.checkpoint_id)
    isolate = batch.isolate
    components: dict[str, IRLossComponentMetrics] = {}
    token_metrics = _evaluate_token_class_ce(batch)
    components["token_class_ce"] = _finalize_component(
        config,
        batch,
        name="token_class_ce",
        raw=token_metrics[0],
        token_class_ce=token_metrics[1],
        details={"token_class_counts": token_metrics[2], "decode_mode": batch.decode_mode},
        isolate=isolate,
    )
    cosine_raw, cosine_details = _evaluate_normalized_cosine(batch)
    components["normalized_cosine"] = _finalize_component(
        config, batch, name="normalized_cosine", raw=cosine_raw, details=cosine_details, isolate=isolate
    )
    contrastive_raw, contrastive_details = _evaluate_supervised_contrastive(batch, config)
    components["supervised_contrastive"] = _finalize_component(
        config,
        batch,
        name="supervised_contrastive",
        raw=contrastive_raw,
        details=contrastive_details,
        isolate=isolate,
    )
    components["cycle"] = _finalize_component(
        config, batch, name="cycle", raw=_mean_record_value(batch, "cycle"), isolate=isolate
    )
    components["structural"] = _finalize_component(
        config,
        batch,
        name="structural",
        raw=_mean_attr(batch, "structural_penalty"),
        isolate=isolate,
    )
    components["relation"] = _finalize_component(
        config,
        batch,
        name="relation",
        raw=_mean_attr(batch, "relation_penalty"),
        isolate=isolate,
    )
    components["semantic"] = _finalize_component(
        config, batch, name="semantic", raw=_mean_attr(batch, "semantic_gap"), isolate=isolate
    )
    proof_raw, proof_details = _evaluate_proof_signal(batch)
    components["proof"] = _finalize_component(
        config, batch, name="proof", raw=proof_raw, details=proof_details, isolate=isolate
    )
    components["source_span"] = _finalize_component(
        config,
        batch,
        name="source_span",
        raw=_mean_attr(batch, "source_span_penalty"),
        isolate=isolate,
    )
    components["calibration"] = _finalize_component(
        config, batch, name="calibration", raw=_mean_calibration(batch), isolate=isolate
    )
    components["regularization"] = _finalize_component(
        config,
        batch,
        name="regularization",
        raw=_mean_attr(batch, "parameter_l2"),
        isolate=isolate,
    )
    total = sum(item.weighted for item in components.values())
    gradient_total = sum(
        item.weighted for item in components.values() if item.in_gradient_path
    )
    memory_identity = (
        batch.memory_bank.identity()
        if batch.memory_bank is not None
        else _content_cid({"checkpoint_id": batch.checkpoint_id, "empty": True})
    )
    return IRCompositeLossResult(
        total=_require_finite(total, name="total"),
        gradient_total=_require_finite(gradient_total, name="gradient_total"),
        decode_mode=batch.decode_mode,
        configuration_identity=config.identity(),
        precision_identity=config.precision.identity(),
        schedule_identity=config.schedule.identity(),
        sampler_identity=config.sampler.identity(),
        memory_bank_identity=memory_identity,
        components=components,
        isolated=isolate,
        proof_in_gradient_path=False,
        nonfinite_policy="reject",
    )


def _active(name: str, isolate: Sequence[str]) -> bool:
    return (not isolate) or name in isolate


def _finalize_component(
    config: IRLossConfiguration,
    batch: IRLossBatch,
    *,
    name: str,
    raw: float,
    isolate: Sequence[str],
    token_class_ce: Optional[Mapping[str, float]] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> IRLossComponentMetrics:
    spec = config.component(name)
    finite_raw = _require_finite(raw, name=name)
    adaptive = batch.adaptive_weights.get(name)
    weight = config.weight_for(name, adaptive=adaptive) if _active(name, isolate) else 0.0
    if spec.name == "proof":
        weighted = 0.0
        in_path = False
    else:
        in_path = bool(spec.in_gradient_path and _active(name, isolate) and weight != 0.0)
        weighted = finite_raw * weight if _active(name, isolate) else 0.0
    return IRLossComponentMetrics(
        name=name,
        raw=finite_raw,
        weighted=_require_finite(weighted, name=f"{name}.weighted"),
        in_gradient_path=in_path,
        token_class_ce=dict(token_class_ce or {}),
        details=dict(details or {}),
    )


def _evaluate_token_class_ce(
    batch: IRLossBatch,
) -> tuple[float, dict[str, float], dict[str, int]]:
    class_sums = {name: 0.0 for name in IR_LOSS_REPORTED_TOKEN_CLASSES}
    class_counts = {name: 0 for name in IR_LOSS_REPORTED_TOKEN_CLASSES}
    totals: list[float] = []
    for record in batch.records:
        logits = record.decoded_logits(batch.decode_mode)
        if not logits:
            continue
        mean, per_class, counts = masked_token_class_cross_entropy(
            logits,
            record.token_ids,
            record.token_classes,
        )
        totals.append(mean)
        for name in IR_LOSS_REPORTED_TOKEN_CLASSES:
            if counts[name]:
                class_sums[name] += per_class[name] * counts[name]
                class_counts[name] += counts[name]
    merged = {
        name: (class_sums[name] / class_counts[name] if class_counts[name] else 0.0)
        for name in IR_LOSS_REPORTED_TOKEN_CLASSES
    }
    mean = sum(totals) / len(totals) if totals else 0.0
    return mean, merged, class_counts


def _evaluate_normalized_cosine(batch: IRLossBatch) -> tuple[float, dict[str, Any]]:
    records = {record.record_id: record for record in batch.records}
    admitted = [pair for pair in batch.pair_admissions if pair.admitted]
    if not admitted:
        if len(batch.records) > 1:
            raise AllRecordCosineMaximizationError(
                "normalized cosine requires explicit pair admissions"
            )
        return 0.0, {"admitted_pair_count": 0}
    losses: list[float] = []
    for pair in admitted:
        left = records.get(pair.left_id)
        right = records.get(pair.right_id)
        if left is None or right is None or not left.latent or not right.latent:
            continue
        losses.append(normalized_cosine_loss(left.latent, right.latent))
    mean = sum(losses) / len(losses) if losses else 0.0
    return mean, {"admitted_pair_count": len(admitted), "evaluated_pair_count": len(losses)}


def _evaluate_supervised_contrastive(
    batch: IRLossBatch,
    config: IRLossConfiguration,
) -> tuple[float, dict[str, Any]]:
    positives = [
        pair for pair in batch.pair_admissions if pair.admitted and pair.pair_class == "positive"
    ]
    if not positives:
        return 0.0, {"filtered_false_negatives": 0, "negative_count": 0}
    records = {record.record_id: record for record in batch.records}
    losses: list[float] = []
    filtered_count = 0
    negative_count = 0
    for pair in positives:
        anchor = records.get(pair.left_id)
        positive = records.get(pair.right_id)
        if anchor is None or positive is None or not anchor.latent or not positive.latent:
            continue
        sampled, filtered, _identity = sample_contrastive_negatives(
            anchor,
            batch.records,
            batch.pair_admissions,
            config.sampler,
            memory_bank=batch.memory_bank,
            checkpoint_id=batch.checkpoint_id,
        )
        filtered_count += len(filtered)
        negatives = [item.latent for item in sampled if item.latent]
        negative_count += len(negatives)
        if not negatives:
            continue
        losses.append(
            supervised_contrastive_loss(
                anchor.latent,
                positive.latent,
                negatives,
                temperature=1.0,
            )
        )
    mean = sum(losses) / len(losses) if losses else 0.0
    return mean, {
        "filtered_false_negatives": filtered_count,
        "negative_count": negative_count,
        "positive_pair_count": len(positives),
    }


def _evaluate_proof_signal(batch: IRLossBatch) -> tuple[float, dict[str, Any]]:
    labels = []
    for record in batch.records:
        labels.append(
            {
                "label": record.proof_label,
                "record_id": record.record_id,
                "success": _require_finite(record.proof_success, name="proof_success"),
            }
        )
    if not labels:
        return 0.0, {"labels": [], "in_gradient_path": False}
    mean_failure = sum(1.0 - float(item["success"]) for item in labels) / len(labels)
    return mean_failure, {"in_gradient_path": False, "labels": labels, "role": "curriculum"}


def _mean_attr(batch: IRLossBatch, name: str) -> float:
    if not batch.records:
        return 0.0
    total = 0.0
    for record in batch.records:
        total += _require_finite(getattr(record, name), name=name)
    return total / len(batch.records)


def _mean_record_value(batch: IRLossBatch, name: str) -> float:
    if name != "cycle":
        raise IRLossConfigurationError(f"unsupported derived component {name!r}")
    values: list[float] = []
    for record in batch.records:
        if record.reconstruction and record.cycle_target:
            values.append(mean_squared_error(record.reconstruction, record.cycle_target))
        elif record.reconstruction and record.latent:
            values.append(mean_squared_error(record.reconstruction, record.latent))
    return sum(values) / len(values) if values else 0.0


def _mean_calibration(batch: IRLossBatch) -> float:
    if not batch.records:
        return 0.0
    total = 0.0
    for record in batch.records:
        total += brier_score(record.confidence, record.correctness)
    return total / len(batch.records)


def isolate_ir_loss_component(
    batch: IRLossBatch,
    component: str,
    configuration: Optional[IRLossConfiguration] = None,
) -> IRCompositeLossResult:
    isolated = IRLossBatch(
        records=batch.records,
        pair_admissions=batch.pair_admissions,
        decode_mode=batch.decode_mode,
        checkpoint_id=batch.checkpoint_id,
        memory_bank=batch.memory_bank,
        adaptive_weights=batch.adaptive_weights,
        isolate=(component,),
    )
    return evaluate_ir_composite_loss(isolated, configuration)


def teacher_forcing_and_free_run_results(
    records: Sequence[IRLossRecord],
    configuration: Optional[IRLossConfiguration] = None,
    **kwargs: Any,
) -> dict[str, IRCompositeLossResult]:
    results = {
        mode: evaluate_ir_composite_loss(
            IRLossBatch(records=tuple(records), decode_mode=mode, **kwargs),
            configuration,
        )
        for mode in IR_LOSS_DECODE_MODES
    }
    if results["teacher_forcing"].decode_mode == results["free_run"].decode_mode:
        raise IRLossConfigurationError("teacher forcing and free run must remain distinct")
    return results


CANONICAL_IR_LOSS_CONFIGURATION_CID: Final = (
    "sha256:7cc9465cea6412b63f2ae32dae4b6cab0c765d6086db5a3dba8315602a1702a5"
)
if canonical_ir_loss_configuration().identity() != CANONICAL_IR_LOSS_CONFIGURATION_CID:
    raise RuntimeError("canonical IRLossConfiguration@1 identity drifted")


__all__ = [
    "AllRecordCosineMaximizationError",
    "AdaptiveWeightBoundError",
    "CANONICAL_IR_LOSS_CONFIGURATION_CID",
    "DEFAULT_MEMORY_BANK_CAPACITY",
    "DEFAULT_SAMPLER_SEED",
    "DurableFloatWeightError",
    "FixedPointWeight",
    "IRCompositeLossResult",
    "IRLossBatch",
    "IRLossComponentMetrics",
    "IRLossComponentSpec",
    "IRLossConfiguration",
    "IRLossConfigurationError",
    "IRLossMemoryBank",
    "IRLossNonfiniteError",
    "IRLossPairAdmission",
    "IRLossPrecisionIdentity",
    "IRLossRecord",
    "IRLossSamplerContract",
    "IRLossSchedule",
    "IR_LOSS_COMPONENT_NAMES",
    "IR_LOSS_CONFIGURATION_INTERFACE",
    "IR_LOSS_CONFIGURATION_SCHEMA",
    "IR_LOSS_CONFIGURATION_SCHEMA_VERSION",
    "IR_LOSS_DECODE_MODES",
    "IR_LOSS_EXCLUSIONS",
    "IR_LOSS_FALSE_NEGATIVE_CLASSES",
    "IR_LOSS_MEMORY_BANK_SCHEMA",
    "IR_LOSS_PRECISION_SCHEMA",
    "IR_LOSS_REPORTED_TOKEN_CLASSES",
    "IR_LOSS_SAMPLER_SCHEMA",
    "IR_LOSS_SCHEDULE_SCHEMA",
    "IsolatedLossMissingError",
    "MemoryBankCheckpointMismatchError",
    "ProofInGradientPathError",
    "bind_memory_bank_to_checkpoint",
    "brier_score",
    "canonical_ir_loss_configuration",
    "canonical_token_class",
    "evaluate_ir_composite_loss",
    "filter_false_negatives",
    "isolate_ir_loss_component",
    "l2_normalize",
    "masked_token_class_cross_entropy",
    "mean_squared_error",
    "normalized_cosine_loss",
    "reported_token_classes",
    "sample_contrastive_negatives",
    "softmax",
    "supervised_contrastive_loss",
    "teacher_forcing_and_free_run_results",
]
