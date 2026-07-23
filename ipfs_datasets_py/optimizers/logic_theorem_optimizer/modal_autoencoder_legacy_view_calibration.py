"""Calibrated, fail-closed reuse of legacy feature-to-LegalIR-view logits.

The legacy ``feature_legal_ir_view_logits`` table is useful teacher evidence,
but copying the complete table into the current autoencoder is a known
cross-entropy regression.  This module keeps the table outside the accepted
state and exposes a bounded inference-time interpolation:

* alpha defaults to exactly zero and therefore returns the current logits
  without numerical transformation;
* temperature, interpolation, and confidence gates can be set per semantic
  head and overridden for an individual LegalIR view;
* calibration search is restricted to a lineage-bound development split and
  receives only a digest commitment for the hidden immutable canary;
* promotion evaluates every required head independently and rejects any
  family regression, non-finite/missing evidence, or full legacy transfer.

No source text, decoded samples, prompts, or legacy tensor rows are included in
the generated reports.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Optional

from .legal_ir_eval_splits import (
    LegalIRSplitManifest,
    require_hparam_selection_split,
)
from .modal_autoencoder import ModalAutoencoderTrainingState


LEGACY_VIEW_CALIBRATION_SCHEMA_VERSION: Final = (
    "modal-autoencoder-legacy-view-calibration-v1"
)
LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION: Final = (
    "modal-autoencoder-legacy-view-calibration-report-v1"
)
LEGACY_VIEW_CALIBRATION_LINEAGE_SCHEMA_VERSION: Final = (
    "modal-autoencoder-legacy-view-calibration-lineage-v1"
)
LEGACY_VIEW_CALIBRATION_FEATURE_FIELD: Final = (
    "feature_legal_ir_view_logits"
)
KNOWN_OMITTED_LEGACY_VIEW_LOGIT_ROWS: Final = 92_867

DEONTIC_HEAD: Final = "deontic"
FRAME_LOGIC_HEAD: Final = "frame_logic"
TDFOL_HEAD: Final = "tdfol"
KNOWLEDGE_GRAPH_HEAD: Final = "knowledge_graph"
CEC_HEAD: Final = "cec"
PROVER_HEAD: Final = "prover"
GLOBAL_HEAD: Final = "global"

LEGACY_VIEW_CALIBRATION_HEADS: Final[tuple[str, ...]] = (
    DEONTIC_HEAD,
    FRAME_LOGIC_HEAD,
    TDFOL_HEAD,
    KNOWLEDGE_GRAPH_HEAD,
    CEC_HEAD,
    PROVER_HEAD,
    GLOBAL_HEAD,
)

CROSS_ENTROPY: Final = "cross_entropy"
COSINE: Final = "cosine"
CALIBRATION_ERROR: Final = "calibration_error"
SEMANTIC_EQUIVALENCE: Final = "semantic_equivalence"
PROOF_RECONSTRUCTION: Final = "proof_reconstruction"
SOURCE_COPY: Final = "source_copy"
UNCERTAINTY: Final = "uncertainty"

LEGACY_VIEW_CALIBRATION_METRICS: Final[tuple[str, ...]] = (
    CROSS_ENTROPY,
    COSINE,
    CALIBRATION_ERROR,
    SEMANTIC_EQUIVALENCE,
    PROOF_RECONSTRUCTION,
    SOURCE_COPY,
    UNCERTAINTY,
)
LOWER_IS_BETTER_CALIBRATION_METRICS: Final = frozenset(
    {CROSS_ENTROPY, CALIBRATION_ERROR, SOURCE_COPY, UNCERTAINTY}
)
HIGHER_IS_BETTER_CALIBRATION_METRICS: Final = frozenset(
    {COSINE, SEMANTIC_EQUIVALENCE, PROOF_RECONSTRUCTION}
)

_HEAD_ALIASES: Final[Mapping[str, str]] = {
    "deontic": DEONTIC_HEAD,
    "deontic_ir": DEONTIC_HEAD,
    "legalnormir": DEONTIC_HEAD,
    "frame": FRAME_LOGIC_HEAD,
    "frame_logic": FRAME_LOGIC_HEAD,
    "flogic": FRAME_LOGIC_HEAD,
    "tdfol": TDFOL_HEAD,
    "fol": TDFOL_HEAD,
    "knowledge_graph": KNOWLEDGE_GRAPH_HEAD,
    "knowledge_graphs": KNOWLEDGE_GRAPH_HEAD,
    "kg": KNOWLEDGE_GRAPH_HEAD,
    "neo4j": KNOWLEDGE_GRAPH_HEAD,
    "cec": CEC_HEAD,
    "dcec": CEC_HEAD,
    "prover": PROVER_HEAD,
    "provers": PROVER_HEAD,
    "external_prover": PROVER_HEAD,
    "external_provers": PROVER_HEAD,
    "hammer": PROVER_HEAD,
    "lean": PROVER_HEAD,
    "z3": PROVER_HEAD,
    "global": GLOBAL_HEAD,
    "decompiler": GLOBAL_HEAD,
    "temporal": GLOBAL_HEAD,
    "provenance": GLOBAL_HEAD,
}


class LegacyViewCalibrationError(ValueError):
    """Raised when calibration evidence or configuration fails closed."""


def _finite(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LegacyViewCalibrationError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise LegacyViewCalibrationError(f"{name} must be finite")
    return result


def _unit(value: Any, *, name: str) -> float:
    result = _finite(value, name=name)
    if not 0.0 <= result <= 1.0:
        raise LegacyViewCalibrationError(f"{name} must be between zero and one")
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LegacyViewCalibrationError("report contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    raise LegacyViewCalibrationError(
        f"value of type {type(value).__name__} is not report-safe"
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _content_id(value: Any, *, name: str) -> str:
    text = str(value or "").strip().lower()
    body = text.removeprefix("sha256:")
    if len(body) != 64 or any(character not in "0123456789abcdef" for character in body):
        raise LegacyViewCalibrationError(
            f"{name} must be a sha256 content identifier"
        )
    return "sha256:" + body


def canonical_legacy_view_head(value: str) -> str:
    """Map a LegalIR view or family name to one of the seven gated heads."""

    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace("/", "_")
        .replace(":", "_")
    )
    if normalized in _HEAD_ALIASES:
        return _HEAD_ALIASES[normalized]
    for token, head in (
        ("frame_logic", FRAME_LOGIC_HEAD),
        ("flogic", FRAME_LOGIC_HEAD),
        ("deontic", DEONTIC_HEAD),
        ("tdfol", TDFOL_HEAD),
        ("knowledge_graph", KNOWLEDGE_GRAPH_HEAD),
        ("neo4j", KNOWLEDGE_GRAPH_HEAD),
        ("external_prover", PROVER_HEAD),
        ("prover", PROVER_HEAD),
        ("hammer", PROVER_HEAD),
        ("cec", CEC_HEAD),
        ("dcec", CEC_HEAD),
    ):
        if token in normalized:
            return head
    return GLOBAL_HEAD


def _declared_legacy_view_head(value: str, *, name: str) -> str:
    """Resolve an explicitly declared head without silently using global.

    Unknown LegalIR *views* intentionally fall back to the global head so a
    newly versioned view can retain the safe alpha-zero default.  Explicit
    configuration and report head names are a different trust boundary:
    accepting a typo there as ``global`` could bypass the intended family
    guardrail.
    """

    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace("/", "_")
        .replace(":", "_")
    )
    resolved = canonical_legacy_view_head(value)
    explicitly_global = normalized in _HEAD_ALIASES and (
        _HEAD_ALIASES[normalized] == GLOBAL_HEAD
    )
    recognized_non_global = resolved != GLOBAL_HEAD
    if not explicitly_global and not recognized_non_global:
        raise LegacyViewCalibrationError(
            f"unknown {name}: {value!r}"
        )
    return resolved


@dataclass(frozen=True, slots=True)
class HeadCalibration:
    """Temperature/interpolation/confidence policy for one semantic head."""

    temperature: float = 1.0
    alpha: float = 0.0
    minimum_confidence: float = 0.0
    confidence_power: float = 0.0

    def __post_init__(self) -> None:
        temperature = _finite(self.temperature, name="temperature")
        if temperature <= 0.0:
            raise LegacyViewCalibrationError("temperature must be positive")
        confidence_power = _finite(
            self.confidence_power, name="confidence_power"
        )
        if confidence_power < 0.0:
            raise LegacyViewCalibrationError(
                "confidence_power must be non-negative"
            )
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "alpha", _unit(self.alpha, name="alpha"))
        object.__setattr__(
            self,
            "minimum_confidence",
            _unit(self.minimum_confidence, name="minimum_confidence"),
        )
        object.__setattr__(self, "confidence_power", confidence_power)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HeadCalibration":
        return cls(
            temperature=value.get("temperature", 1.0),
            alpha=value.get("alpha", value.get("interpolation", 0.0)),
            minimum_confidence=value.get(
                "minimum_confidence",
                value.get("confidence_threshold", 0.0),
            ),
            confidence_power=value.get("confidence_power", 0.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "alpha": self.alpha,
            "confidence_power": self.confidence_power,
            "minimum_confidence": self.minimum_confidence,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class ViewCalibration:
    """Sparse per-view override; omitted values inherit the semantic head."""

    temperature: Optional[float] = None
    alpha: Optional[float] = None
    minimum_confidence: Optional[float] = None
    confidence_power: Optional[float] = None

    def __post_init__(self) -> None:
        if self.temperature is not None:
            value = _finite(self.temperature, name="view temperature")
            if value <= 0.0:
                raise LegacyViewCalibrationError(
                    "view temperature must be positive"
                )
            object.__setattr__(self, "temperature", value)
        if self.alpha is not None:
            object.__setattr__(
                self, "alpha", _unit(self.alpha, name="view alpha")
            )
        if self.minimum_confidence is not None:
            object.__setattr__(
                self,
                "minimum_confidence",
                _unit(
                    self.minimum_confidence,
                    name="view minimum_confidence",
                ),
            )
        if self.confidence_power is not None:
            value = _finite(
                self.confidence_power, name="view confidence_power"
            )
            if value < 0.0:
                raise LegacyViewCalibrationError(
                    "view confidence_power must be non-negative"
                )
            object.__setattr__(self, "confidence_power", value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ViewCalibration":
        return cls(
            temperature=value.get("temperature"),
            alpha=value.get("alpha", value.get("interpolation")),
            minimum_confidence=value.get(
                "minimum_confidence",
                value.get("confidence_threshold"),
            ),
            confidence_power=value.get("confidence_power"),
        )

    def resolve(self, head: HeadCalibration) -> HeadCalibration:
        return HeadCalibration(
            temperature=(
                head.temperature
                if self.temperature is None
                else self.temperature
            ),
            alpha=head.alpha if self.alpha is None else self.alpha,
            minimum_confidence=(
                head.minimum_confidence
                if self.minimum_confidence is None
                else self.minimum_confidence
            ),
            confidence_power=(
                head.confidence_power
                if self.confidence_power is None
                else self.confidence_power
            ),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            key: value
            for key, value in (
                ("alpha", self.alpha),
                ("confidence_power", self.confidence_power),
                ("minimum_confidence", self.minimum_confidence),
                ("temperature", self.temperature),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationConfig:
    """Complete calibration policy with a safe exact-zero default."""

    default: HeadCalibration = field(default_factory=HeadCalibration)
    heads: Mapping[str, HeadCalibration] = field(default_factory=dict)
    views: Mapping[str, ViewCalibration] = field(default_factory=dict)
    full_transfer_allowed: bool = False
    schema_version: str = LEGACY_VIEW_CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEGACY_VIEW_CALIBRATION_SCHEMA_VERSION:
            raise LegacyViewCalibrationError(
                "unsupported legacy view calibration schema version"
            )
        default = (
            self.default
            if isinstance(self.default, HeadCalibration)
            else HeadCalibration.from_mapping(self.default)
        )
        heads: dict[str, HeadCalibration] = {}
        for raw_head, raw_parameters in self.heads.items():
            head = _declared_legacy_view_head(
                str(raw_head),
                name="calibration head",
            )
            # Two aliases resolving to one head cannot be silently
            # last-write-wins, regardless of their insertion order.
            if head in heads:
                raise LegacyViewCalibrationError(
                    f"duplicate calibration head: {head}"
                )
            parameters = (
                raw_parameters
                if isinstance(raw_parameters, HeadCalibration)
                else HeadCalibration.from_mapping(raw_parameters)
            )
            heads[head] = parameters
        views: dict[str, ViewCalibration] = {}
        for raw_view, raw_parameters in self.views.items():
            view = str(raw_view).strip()
            if not view:
                raise LegacyViewCalibrationError(
                    "calibration view names may not be empty"
                )
            views[view] = (
                raw_parameters
                if isinstance(raw_parameters, ViewCalibration)
                else ViewCalibration.from_mapping(raw_parameters)
            )
        object.__setattr__(self, "default", default)
        object.__setattr__(
            self,
            "heads",
            MappingProxyType(dict(sorted(heads.items()))),
        )
        object.__setattr__(
            self,
            "views",
            MappingProxyType(dict(sorted(views.items()))),
        )
        if self.is_full_transfer and not self.full_transfer_allowed:
            raise LegacyViewCalibrationError(
                "full legacy view transfer is forbidden by policy"
            )

    @classmethod
    def alpha_zero(cls) -> "LegacyViewCalibrationConfig":
        """Return the accepted-state baseline with mathematically zero influence."""

        return cls()

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "LegacyViewCalibrationConfig":
        default_value = value.get("default")
        if default_value is None:
            default_value = {
                "alpha": value.get("default_alpha", 0.0),
                "temperature": value.get("default_temperature", 1.0),
                "minimum_confidence": value.get(
                    "default_minimum_confidence", 0.0
                ),
            }
        if not isinstance(default_value, Mapping):
            raise LegacyViewCalibrationError(
                "default calibration must be a mapping"
            )
        heads = value.get("heads", value.get("head_calibration", {}))
        views = value.get("views", value.get("view_calibration", {}))
        if not isinstance(heads, Mapping) or not isinstance(views, Mapping):
            raise LegacyViewCalibrationError(
                "heads and views calibration must be mappings"
            )
        return cls(
            default=HeadCalibration.from_mapping(default_value),
            heads=heads,
            views=views,
            full_transfer_allowed=bool(value.get("full_transfer_allowed", False)),
            schema_version=str(
                value.get(
                    "schema_version", LEGACY_VIEW_CALIBRATION_SCHEMA_VERSION
                )
            ),
        )

    def parameters_for(self, view: str) -> HeadCalibration:
        head = canonical_legacy_view_head(view)
        parameters = self.heads.get(head, self.default)
        override = self.views.get(str(view))
        return override.resolve(parameters) if override is not None else parameters

    @property
    def is_alpha_zero(self) -> bool:
        if self.default.alpha != 0.0:
            return False
        if any(parameters.alpha != 0.0 for parameters in self.heads.values()):
            return False
        return not any(
            parameters.alpha not in (None, 0.0)
            for parameters in self.views.values()
        )

    @property
    def is_full_transfer(self) -> bool:
        if self.default.alpha == 1.0:
            return True
        return (
            all(
                self.heads.get(head, self.default).alpha == 1.0
                for head in LEGACY_VIEW_CALIBRATION_HEADS
            )
            and all(
                override.alpha in (None, 1.0)
                for override in self.views.values()
            )
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def with_head(
        self, head: str, parameters: HeadCalibration
    ) -> "LegacyViewCalibrationConfig":
        values = dict(self.heads)
        values[
            _declared_legacy_view_head(head, name="calibration head")
        ] = parameters
        return LegacyViewCalibrationConfig(
            default=self.default,
            heads=values,
            views=self.views,
            full_transfer_allowed=self.full_transfer_allowed,
        )

    def with_view(
        self, view: str, parameters: ViewCalibration
    ) -> "LegacyViewCalibrationConfig":
        values = dict(self.views)
        values[str(view)] = parameters
        return LegacyViewCalibrationConfig(
            default=self.default,
            heads=self.heads,
            views=values,
            full_transfer_allowed=self.full_transfer_allowed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "default": self.default.to_dict(),
            "full_transfer_allowed": self.full_transfer_allowed,
            "heads": {
                head: parameters.to_dict()
                for head, parameters in self.heads.items()
            },
            "schema_version": self.schema_version,
            "views": {
                view: parameters.to_dict()
                for view, parameters in self.views.items()
            },
        }


@dataclass(frozen=True, slots=True)
class CalibratedLogits:
    """One calibrated vector plus auditable, source-free influence metadata."""

    logits: Mapping[str, float]
    confidence_by_view: Mapping[str, float]
    effective_alpha_by_view: Mapping[str, float]
    rejected_views: Mapping[str, str]

    @property
    def legacy_influence_applied(self) -> bool:
        return any(alpha > 0.0 for alpha in self.effective_alpha_by_view.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence_by_view": dict(self.confidence_by_view),
            "effective_alpha_by_view": dict(self.effective_alpha_by_view),
            "legacy_influence_applied": self.legacy_influence_applied,
            "logits": dict(self.logits),
            "rejected_views": dict(self.rejected_views),
        }


def _softmax(logits: Mapping[str, float]) -> dict[str, float]:
    if not logits:
        return {}
    values = {
        str(key): _finite(value, name=f"logit[{key}]")
        for key, value in logits.items()
    }
    maximum = max(values.values())
    exponentials = {
        key: math.exp(max(-700.0, min(700.0, value - maximum)))
        for key, value in values.items()
    }
    total = math.fsum(exponentials.values())
    if total <= 0.0 or not math.isfinite(total):
        raise LegacyViewCalibrationError("logits produce an invalid distribution")
    return {key: value / total for key, value in exponentials.items()}


def calibrate_legacy_view_logits(
    current_logits: Mapping[str, float],
    legacy_logits: Mapping[str, float],
    config: LegacyViewCalibrationConfig | None = None,
) -> CalibratedLogits:
    """Interpolate one legacy logit vector into the current vector.

    Alpha zero takes an early return.  This is intentional: even temperature
    normalization, softmax, key union, and float rounding are skipped, making
    the accepted-state baseline exact rather than merely numerically close.
    """

    policy = config or LegacyViewCalibrationConfig.alpha_zero()
    if policy.is_alpha_zero:
        return CalibratedLogits(
            logits={str(view): value for view, value in current_logits.items()},
            confidence_by_view={},
            effective_alpha_by_view={},
            rejected_views={},
        )
    current = {
        str(view): _finite(value, name=f"current logit[{view}]")
        for view, value in current_logits.items()
    }
    legacy = {
        str(view): _finite(value, name=f"legacy logit[{view}]")
        for view, value in legacy_logits.items()
    }
    if not legacy:
        return CalibratedLogits(
            logits=dict(current),
            confidence_by_view={},
            effective_alpha_by_view={},
            rejected_views={},
        )

    temperature_scaled = {
        view: value / policy.parameters_for(view).temperature
        for view, value in legacy.items()
    }
    confidence = _softmax(temperature_scaled)
    head_confidence: dict[str, float] = defaultdict(float)
    for view, probability in confidence.items():
        head_confidence[canonical_legacy_view_head(view)] += probability

    result = dict(current)
    effective: dict[str, float] = {}
    rejected: dict[str, str] = {}
    for view in sorted(legacy):
        parameters = policy.parameters_for(view)
        view_confidence = confidence.get(view, 0.0)
        combined_confidence = min(
            1.0,
            math.sqrt(
                max(0.0, view_confidence)
                * max(
                    0.0,
                    head_confidence[canonical_legacy_view_head(view)],
                )
            ),
        )
        alpha = parameters.alpha
        if combined_confidence < parameters.minimum_confidence:
            rejected[view] = "below_minimum_confidence"
            alpha = 0.0
        elif parameters.confidence_power > 0.0:
            alpha *= combined_confidence ** parameters.confidence_power
        effective[view] = alpha
        if alpha == 0.0:
            continue
        current_value = current.get(view, 0.0)
        result[view] = current_value + alpha * (
            temperature_scaled[view] - current_value
        )
    return CalibratedLogits(
        logits=result,
        confidence_by_view=dict(sorted(confidence.items())),
        effective_alpha_by_view=effective,
        rejected_views=rejected,
    )


def calibrate_feature_legal_ir_view_logits(
    current: Mapping[str, Mapping[str, float]],
    legacy: Mapping[str, Mapping[str, float]],
    config: LegacyViewCalibrationConfig | None = None,
) -> dict[str, dict[str, float]]:
    """Calibrate the complete nested feature table without mutating either input."""

    policy = config or LegacyViewCalibrationConfig.alpha_zero()
    if policy.is_alpha_zero:
        return {
            str(feature): {str(view): value for view, value in logits.items()}
            for feature, logits in current.items()
        }
    result: dict[str, dict[str, float]] = {}
    for feature in sorted(set(current) | set(legacy), key=str):
        calibrated = calibrate_legacy_view_logits(
            current.get(feature, {}),
            legacy.get(feature, {}),
            policy,
        )
        if calibrated.logits:
            result[str(feature)] = dict(calibrated.logits)
    return result


def apply_legacy_view_calibration(
    current_state: ModalAutoencoderTrainingState,
    legacy_state: ModalAutoencoderTrainingState,
    config: LegacyViewCalibrationConfig | None = None,
) -> ModalAutoencoderTrainingState:
    """Return a current-state copy with only the calibrated feature-view table changed."""

    candidate = current_state.generalizable_copy()
    candidate.feature_legal_ir_view_logits = (
        calibrate_feature_legal_ir_view_logits(
            current_state.feature_legal_ir_view_logits,
            legacy_state.feature_legal_ir_view_logits,
            config,
        )
    )
    return candidate


def aggregate_feature_legal_ir_view_logits(
    feature_logits: Mapping[str, Mapping[str, float]],
    active_features: Sequence[str],
) -> dict[str, float]:
    """Aggregate a sample's active sparse rows using the model's sqrt scaling."""

    features = tuple(dict.fromkeys(str(feature) for feature in active_features))
    present = [feature for feature in features if feature in feature_logits]
    if not present:
        return {}
    scale = 1.0 / math.sqrt(len(present))
    result: dict[str, float] = defaultdict(float)
    for feature in present:
        row = feature_logits[feature]
        if not isinstance(row, Mapping):
            raise LegacyViewCalibrationError(
                f"feature logit row {feature!r} must be a mapping"
            )
        for view, value in row.items():
            result[str(view)] += _finite(
                value, name=f"feature logit[{feature}][{view}]"
            ) * scale
    return dict(result)


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationLineage:
    """Immutable teacher/student/split/canary identity for one search."""

    teacher_state_sha256: str
    student_state_sha256: str
    split_manifest_sha256: str
    canary_artifact_sha256: str
    compiler_sha256: str
    schema_sha256: str
    seed: int
    development_split: str = "validation"
    feature_field: str = LEGACY_VIEW_CALIBRATION_FEATURE_FIELD
    schema_version: str = LEGACY_VIEW_CALIBRATION_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "teacher_state_sha256",
            "student_state_sha256",
            "split_manifest_sha256",
            "canary_artifact_sha256",
            "compiler_sha256",
            "schema_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _content_id(getattr(self, name), name=name),
            )
        if self.development_split != "validation":
            raise LegacyViewCalibrationError(
                "calibration search must use the validation development split"
            )
        if self.feature_field != LEGACY_VIEW_CALIBRATION_FEATURE_FIELD:
            raise LegacyViewCalibrationError(
                "lineage is not bound to feature_legal_ir_view_logits"
            )
        if self.schema_version != LEGACY_VIEW_CALIBRATION_LINEAGE_SCHEMA_VERSION:
            raise LegacyViewCalibrationError(
                "unsupported calibration lineage schema version"
            )
        object.__setattr__(self, "seed", int(self.seed))

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "LegacyViewCalibrationLineage":
        return cls(
            teacher_state_sha256=value.get(
                "teacher_state_sha256", value.get("legacy_state_sha256", "")
            ),
            student_state_sha256=value.get(
                "student_state_sha256", value.get("current_state_sha256", "")
            ),
            split_manifest_sha256=value.get(
                "split_manifest_sha256",
                value.get("split_manifest_digest", ""),
            ),
            canary_artifact_sha256=value.get(
                "canary_artifact_sha256", value.get("canary_sha256", "")
            ),
            compiler_sha256=value.get("compiler_sha256", ""),
            schema_sha256=value.get("schema_sha256", ""),
            seed=value.get("seed", 0),
            development_split=str(value.get("development_split", "validation")),
            feature_field=str(
                value.get(
                    "feature_field", LEGACY_VIEW_CALIBRATION_FEATURE_FIELD
                )
            ),
            schema_version=str(
                value.get(
                    "schema_version",
                    LEGACY_VIEW_CALIBRATION_LINEAGE_SCHEMA_VERSION,
                )
            ),
        )

    @property
    def lineage_id(self) -> str:
        return _digest(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        result = {
            "canary_artifact_sha256": self.canary_artifact_sha256,
            "compiler_sha256": self.compiler_sha256,
            "development_split": self.development_split,
            "feature_field": self.feature_field,
            "schema_sha256": self.schema_sha256,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "split_manifest_sha256": self.split_manifest_sha256,
            "student_state_sha256": self.student_state_sha256,
            "teacher_state_sha256": self.teacher_state_sha256,
        }
        if include_id:
            result["lineage_id"] = self.lineage_id
        return result


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationExample:
    """Source-free development observation used to score one calibration."""

    sample_id: str
    head: str
    target_distribution: Mapping[str, float]
    current_logits: Mapping[str, float]
    legacy_logits: Mapping[str, float]
    semantic_equivalence: Optional[float] = None
    proof_reconstruction: Optional[float] = None
    source_copy: Optional[float] = None
    outcomes_by_view: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.sample_id).strip():
            raise LegacyViewCalibrationError("calibration example needs sample_id")
        object.__setattr__(self, "sample_id", str(self.sample_id))
        object.__setattr__(
            self,
            "head",
            _declared_legacy_view_head(
                self.head,
                name="calibration example head",
            ),
        )
        target = {
            str(view): max(
                0.0, _finite(value, name=f"target_distribution[{view}]")
            )
            for view, value in self.target_distribution.items()
        }
        total = math.fsum(target.values())
        if total <= 0.0:
            raise LegacyViewCalibrationError(
                "target_distribution must have positive mass"
            )
        object.__setattr__(
            self,
            "target_distribution",
            MappingProxyType(
                {view: value / total for view, value in target.items()}
            ),
        )
        for field_name in ("current_logits", "legacy_logits"):
            raw_logits = getattr(self, field_name)
            if not isinstance(raw_logits, Mapping):
                raise LegacyViewCalibrationError(
                    f"{field_name} must be a mapping"
                )
            logits = {
                str(view): _finite(
                    value,
                    name=f"{field_name}[{view}]",
                )
                for view, value in raw_logits.items()
            }
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(sorted(logits.items()))),
            )
        for field_name in (
            "semantic_equivalence",
            "proof_reconstruction",
            "source_copy",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, _unit(value, name=field_name)
                )
        outcomes: dict[str, dict[str, float]] = {}
        for view, metrics in self.outcomes_by_view.items():
            if not isinstance(metrics, Mapping):
                raise LegacyViewCalibrationError(
                    f"outcomes_by_view[{view}] must be a mapping"
                )
            outcomes[str(view)] = {
                metric: _unit(metrics[metric], name=f"{view}.{metric}")
                for metric in (
                    SEMANTIC_EQUIVALENCE,
                    PROOF_RECONSTRUCTION,
                    SOURCE_COPY,
                )
                if metric in metrics
            }
        object.__setattr__(
            self,
            "outcomes_by_view",
            MappingProxyType(
                {
                    view: MappingProxyType(dict(sorted(metrics.items())))
                    for view, metrics in sorted(outcomes.items())
                }
            ),
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        current_feature_logits: Mapping[str, Mapping[str, float]] | None = None,
        legacy_feature_logits: Mapping[str, Mapping[str, float]] | None = None,
    ) -> "LegacyViewCalibrationExample":
        active_features = value.get("active_features", value.get("features", ()))
        if not isinstance(active_features, Sequence) or isinstance(
            active_features,
            (str, bytes, bytearray),
        ):
            raise LegacyViewCalibrationError(
                "example active_features must be a sequence"
            )
        current_logits = value.get("current_logits")
        legacy_logits = value.get("legacy_logits")
        if not isinstance(current_logits, Mapping):
            current_logits = aggregate_feature_legal_ir_view_logits(
                current_feature_logits or {},
                active_features,
            )
        if not isinstance(legacy_logits, Mapping):
            legacy_logits = aggregate_feature_legal_ir_view_logits(
                legacy_feature_logits or {},
                active_features,
            )
        target = value.get("target_distribution", value.get("target", {}))
        if not isinstance(target, Mapping):
            raise LegacyViewCalibrationError(
                "example target_distribution must be a mapping"
            )
        return cls(
            sample_id=str(value.get("sample_id", value.get("id", ""))),
            head=str(value.get("head", value.get("family", GLOBAL_HEAD))),
            target_distribution=target,
            current_logits=current_logits,
            legacy_logits=legacy_logits,
            semantic_equivalence=value.get(SEMANTIC_EQUIVALENCE),
            proof_reconstruction=value.get(PROOF_RECONSTRUCTION),
            source_copy=value.get(SOURCE_COPY),
            outcomes_by_view=(
                value.get("outcomes_by_view", {})
                if isinstance(value.get("outcomes_by_view", {}), Mapping)
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class FamilyCalibrationMetrics:
    """The seven independent promotion metrics for one semantic head."""

    sample_count: int
    cross_entropy: float
    cosine: float
    calibration_error: float
    semantic_equivalence: float
    proof_reconstruction: float
    source_copy: float
    uncertainty: float

    def __post_init__(self) -> None:
        if int(self.sample_count) < 1:
            raise LegacyViewCalibrationError("family sample_count must be positive")
        object.__setattr__(self, "sample_count", int(self.sample_count))
        cross_entropy = _finite(self.cross_entropy, name=CROSS_ENTROPY)
        if cross_entropy < 0.0:
            raise LegacyViewCalibrationError(
                "cross_entropy must be non-negative"
            )
        object.__setattr__(self, "cross_entropy", cross_entropy)
        for name in LEGACY_VIEW_CALIBRATION_METRICS[1:]:
            object.__setattr__(
                self, name, _unit(getattr(self, name), name=name)
            )

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "FamilyCalibrationMetrics":
        aliases = {
            CROSS_ENTROPY: (
                CROSS_ENTROPY,
                "ir_cross_entropy_loss",
                "cross_entropy_loss",
            ),
            COSINE: (COSINE, "ir_cosine_similarity", "cosine_similarity"),
            CALIBRATION_ERROR: (
                CALIBRATION_ERROR,
                "expected_calibration_error",
                "ece",
            ),
            SEMANTIC_EQUIVALENCE: (
                SEMANTIC_EQUIVALENCE,
                "semantic_equivalence_score",
            ),
            PROOF_RECONSTRUCTION: (
                PROOF_RECONSTRUCTION,
                "proof_reconstruction_rate",
                "reconstruction_success_rate",
            ),
            SOURCE_COPY: (
                SOURCE_COPY,
                "source_copy_penalty",
                "source_copy_rate",
            ),
            UNCERTAINTY: (
                UNCERTAINTY,
                "normalized_entropy",
                "uncertainty_score",
            ),
        }

        def get(name: str) -> Any:
            for alias in aliases[name]:
                if alias in value:
                    return value[alias]
            raise LegacyViewCalibrationError(f"missing family metric: {name}")

        return cls(
            sample_count=value.get("sample_count", value.get("count", 0)),
            **{name: get(name) for name in LEGACY_VIEW_CALIBRATION_METRICS},
        )

    def metric(self, name: str) -> float:
        return float(getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            CALIBRATION_ERROR: self.calibration_error,
            COSINE: self.cosine,
            CROSS_ENTROPY: self.cross_entropy,
            "expected_calibration_error": self.calibration_error,
            "ir_cosine_similarity": self.cosine,
            "ir_cross_entropy_loss": self.cross_entropy,
            "normalized_entropy": self.uncertainty,
            PROOF_RECONSTRUCTION: self.proof_reconstruction,
            "proof_reconstruction_rate": self.proof_reconstruction,
            "reconstruction_success_rate": self.proof_reconstruction,
            "sample_count": self.sample_count,
            SEMANTIC_EQUIVALENCE: self.semantic_equivalence,
            "semantic_equivalence_score": self.semantic_equivalence,
            SOURCE_COPY: self.source_copy,
            "source_copy_penalty": self.source_copy,
            UNCERTAINTY: self.uncertainty,
        }


@dataclass(frozen=True, slots=True)
class LegacyViewEvaluationReport:
    """Source-free, per-head evaluation output for one fixed configuration."""

    config_digest: str
    split: str
    family_metrics: Mapping[str, FamilyCalibrationMetrics]
    evaluation_id: str = ""
    schema_version: str = LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION:
            raise LegacyViewCalibrationError(
                "unsupported calibration report schema version"
            )
        object.__setattr__(
            self, "config_digest", _content_id(self.config_digest, name="config_digest")
        )
        metrics: dict[str, FamilyCalibrationMetrics] = {}
        for raw_head, raw_value in self.family_metrics.items():
            head = _declared_legacy_view_head(
                raw_head,
                name="evaluation report head",
            )
            if head in metrics:
                raise LegacyViewCalibrationError(
                    f"duplicate report head: {head}"
                )
            metrics[head] = (
                raw_value
                if isinstance(raw_value, FamilyCalibrationMetrics)
                else FamilyCalibrationMetrics.from_mapping(raw_value)
            )
        missing = set(LEGACY_VIEW_CALIBRATION_HEADS) - set(metrics)
        extra = set(metrics) - set(LEGACY_VIEW_CALIBRATION_HEADS)
        if missing or extra:
            raise LegacyViewCalibrationError(
                "report must contain exactly the required heads; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        object.__setattr__(
            self,
            "family_metrics",
            MappingProxyType(
                {
                    head: metrics[head]
                    for head in LEGACY_VIEW_CALIBRATION_HEADS
                }
            ),
        )
        expected_id = _digest(self.to_dict(include_id=False))
        if self.evaluation_id and self.evaluation_id != expected_id:
            raise LegacyViewCalibrationError("evaluation_id does not match report")
        object.__setattr__(self, "evaluation_id", expected_id)

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "LegacyViewEvaluationReport":
        metrics = value.get("family_metrics", value.get("heads", {}))
        if not isinstance(metrics, Mapping):
            raise LegacyViewCalibrationError(
                "family_metrics must be a mapping"
            )
        return cls(
            config_digest=value.get("config_digest", ""),
            split=str(value.get("split", "")),
            family_metrics=metrics,
            evaluation_id=str(value.get("evaluation_id", "")),
            schema_version=str(
                value.get(
                    "schema_version",
                    LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION,
                )
            ),
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        result = {
            "config_digest": self.config_digest,
            "families": list(LEGACY_VIEW_CALIBRATION_HEADS),
            "family_metrics": {
                head: metrics.to_dict()
                for head, metrics in self.family_metrics.items()
            },
            "metric_names": list(LEGACY_VIEW_CALIBRATION_METRICS),
            "schema_version": self.schema_version,
            "split": self.split,
        }
        if include_id:
            result["evaluation_id"] = self.evaluation_id
        return result


def _outcome_metric(
    example: LegacyViewCalibrationExample,
    predicted_view: str,
    metric: str,
    *,
    require_complete: bool,
    correctness: float,
) -> float:
    per_view = example.outcomes_by_view.get(predicted_view, {})
    if metric in per_view:
        return float(per_view[metric])
    explicit = getattr(example, metric)
    if explicit is not None:
        return float(explicit)
    if require_complete:
        raise LegacyViewCalibrationError(
            f"example {example.sample_id!r} lacks {metric} evidence"
        )
    if metric == SOURCE_COPY:
        return 0.0
    return correctness


def evaluate_legacy_view_calibration(
    examples: Sequence[LegacyViewCalibrationExample],
    config: LegacyViewCalibrationConfig | None = None,
    *,
    split: str = "validation",
    require_complete_metrics: bool = True,
    calibration_bins: int = 10,
) -> LegacyViewEvaluationReport:
    """Evaluate one config and report every metric independently by head."""

    policy = config or LegacyViewCalibrationConfig.alpha_zero()
    if calibration_bins < 1:
        raise LegacyViewCalibrationError("calibration_bins must be positive")
    observations: dict[str, list[dict[str, float]]] = {
        head: [] for head in LEGACY_VIEW_CALIBRATION_HEADS
    }
    for example in examples:
        if not isinstance(example, LegacyViewCalibrationExample):
            raise TypeError("examples must contain LegacyViewCalibrationExample")
        calibrated = calibrate_legacy_view_logits(
            example.current_logits,
            example.legacy_logits,
            policy,
        )
        views = sorted(
            set(calibrated.logits) | set(example.target_distribution)
        )
        logits = {
            view: float(calibrated.logits.get(view, 0.0))
            for view in views
        }
        predicted = _softmax(logits)
        target = {
            view: float(example.target_distribution.get(view, 0.0))
            for view in views
        }
        cross_entropy = -math.fsum(
            target[view] * math.log(max(predicted[view], 1.0e-15))
            for view in views
        )
        numerator = math.fsum(
            predicted[view] * target[view] for view in views
        )
        denominator = math.sqrt(
            math.fsum(value * value for value in predicted.values())
            * math.fsum(value * value for value in target.values())
        )
        cosine = numerator / denominator if denominator > 0.0 else 0.0
        predicted_view = max(views, key=lambda view: (predicted[view], view))
        target_view = max(views, key=lambda view: (target[view], view))
        correctness = 1.0 if predicted_view == target_view else 0.0
        confidence = predicted[predicted_view]
        normalized_entropy = 0.0
        if len(predicted) > 1:
            normalized_entropy = -math.fsum(
                probability * math.log(max(probability, 1.0e-15))
                for probability in predicted.values()
            ) / math.log(len(predicted))
            normalized_entropy = min(1.0, max(0.0, normalized_entropy))
        observations[example.head].append(
            {
                CALIBRATION_ERROR: abs(confidence - correctness),
                COSINE: cosine,
                CROSS_ENTROPY: cross_entropy,
                "confidence": confidence,
                "correctness": correctness,
                PROOF_RECONSTRUCTION: _outcome_metric(
                    example,
                    predicted_view,
                    PROOF_RECONSTRUCTION,
                    require_complete=require_complete_metrics,
                    correctness=correctness,
                ),
                SEMANTIC_EQUIVALENCE: _outcome_metric(
                    example,
                    predicted_view,
                    SEMANTIC_EQUIVALENCE,
                    require_complete=require_complete_metrics,
                    correctness=correctness,
                ),
                SOURCE_COPY: _outcome_metric(
                    example,
                    predicted_view,
                    SOURCE_COPY,
                    require_complete=require_complete_metrics,
                    correctness=correctness,
                ),
                UNCERTAINTY: normalized_entropy,
            }
        )

    family_metrics: dict[str, FamilyCalibrationMetrics] = {}
    for head in LEGACY_VIEW_CALIBRATION_HEADS:
        rows = observations[head]
        if not rows:
            raise LegacyViewCalibrationError(
                f"development evidence is missing required head: {head}"
            )
        # Expected calibration error is binned per head rather than computed
        # from a pooled macro confidence.
        bins: list[list[dict[str, float]]] = [
            [] for _ in range(calibration_bins)
        ]
        for row in rows:
            index = min(
                calibration_bins - 1,
                int(row["confidence"] * calibration_bins),
            )
            bins[index].append(row)
        ece = math.fsum(
            (len(bucket) / len(rows))
            * abs(
                math.fsum(item["confidence"] for item in bucket) / len(bucket)
                - math.fsum(item["correctness"] for item in bucket) / len(bucket)
            )
            for bucket in bins
            if bucket
        )

        def mean(name: str) -> float:
            return math.fsum(row[name] for row in rows) / len(rows)

        family_metrics[head] = FamilyCalibrationMetrics(
            sample_count=len(rows),
            cross_entropy=mean(CROSS_ENTROPY),
            cosine=mean(COSINE),
            calibration_error=ece,
            semantic_equivalence=mean(SEMANTIC_EQUIVALENCE),
            proof_reconstruction=mean(PROOF_RECONSTRUCTION),
            source_copy=mean(SOURCE_COPY),
            uncertainty=mean(UNCERTAINTY),
        )
    return LegacyViewEvaluationReport(
        config_digest=policy.digest,
        split=str(split),
        family_metrics=family_metrics,
    )


@dataclass(frozen=True, slots=True)
class CalibrationGate:
    """Family-specific comparison; aggregate scores have no admission authority."""

    accepted: bool
    failed_families: tuple[str, ...]
    reasons: tuple[str, ...]
    deltas_by_family: Mapping[str, Mapping[str, float]]
    any_improvement: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "aggregate_improvement_has_admission_authority": False,
            "any_improvement": self.any_improvement,
            "deltas_by_family": {
                family: dict(deltas)
                for family, deltas in self.deltas_by_family.items()
            },
            "failed_families": list(self.failed_families),
            "reasons": list(self.reasons),
        }


def compare_legacy_view_reports(
    baseline: LegacyViewEvaluationReport,
    candidate: LegacyViewEvaluationReport,
    *,
    tolerance: float = 0.0,
    require_improvement: bool = False,
) -> CalibrationGate:
    """Reject the candidate if any metric regresses in any required head."""

    tolerance = _finite(tolerance, name="tolerance")
    if tolerance < 0.0:
        raise LegacyViewCalibrationError("tolerance must be non-negative")
    reasons: list[str] = []
    failed: list[str] = []
    deltas: dict[str, dict[str, float]] = {}
    any_improvement = False
    if baseline.split != candidate.split:
        reasons.append("evaluation_split_mismatch")
    for head in LEGACY_VIEW_CALIBRATION_HEADS:
        before = baseline.family_metrics[head]
        after = candidate.family_metrics[head]
        head_failed = False
        head_deltas: dict[str, float] = {}
        if before.sample_count != after.sample_count:
            reasons.append(f"sample_count_mismatch:{head}")
            head_failed = True
        for metric in LEGACY_VIEW_CALIBRATION_METRICS:
            raw_delta = after.metric(metric) - before.metric(metric)
            improvement = (
                -raw_delta
                if metric in LOWER_IS_BETTER_CALIBRATION_METRICS
                else raw_delta
            )
            head_deltas[metric] = improvement
            if improvement < -tolerance:
                reasons.append(f"family_regression:{head}:{metric}")
                head_failed = True
            if improvement > tolerance:
                any_improvement = True
        deltas[head] = head_deltas
        if head_failed:
            failed.append(head)
    if require_improvement and not any_improvement:
        reasons.append("no_metric_improvement")
    return CalibrationGate(
        accepted=not reasons,
        failed_families=tuple(failed),
        reasons=tuple(reasons),
        deltas_by_family=deltas,
        any_improvement=any_improvement,
    )


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationSearchSpace:
    """Deterministic bounded coordinate-search grid."""

    alphas: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 0.75)
    temperatures: tuple[float, ...] = (0.5, 0.75, 1.0, 1.5, 2.0)
    minimum_confidences: tuple[float, ...] = (0.0, 0.25, 0.5)
    confidence_powers: tuple[float, ...] = (0.0, 1.0)
    refine_views: bool = True

    def __post_init__(self) -> None:
        alphas = tuple(sorted({_unit(value, name="search alpha") for value in self.alphas}))
        if 1.0 in alphas:
            raise LegacyViewCalibrationError(
                "search space may not include forbidden full-transfer alpha one"
            )
        temperatures = tuple(
            sorted(
                {
                    _finite(value, name="search temperature")
                    for value in self.temperatures
                }
            )
        )
        if not temperatures or temperatures[0] <= 0.0:
            raise LegacyViewCalibrationError(
                "search temperatures must be positive"
            )
        confidences = tuple(
            sorted(
                {
                    _unit(value, name="search minimum confidence")
                    for value in self.minimum_confidences
                }
            )
        )
        powers = tuple(
            sorted(
                {
                    _finite(value, name="search confidence power")
                    for value in self.confidence_powers
                }
            )
        )
        if not powers or powers[0] < 0.0:
            raise LegacyViewCalibrationError(
                "search confidence powers must be non-negative"
            )
        if not alphas or not confidences:
            raise LegacyViewCalibrationError("search grid dimensions may not be empty")
        object.__setattr__(self, "alphas", alphas)
        object.__setattr__(self, "temperatures", temperatures)
        object.__setattr__(self, "minimum_confidences", confidences)
        object.__setattr__(self, "confidence_powers", powers)

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "LegacyViewCalibrationSearchSpace":
        return cls(
            alphas=tuple(value.get("alphas", (0.0, 0.1, 0.25, 0.5, 0.75))),
            temperatures=tuple(
                value.get("temperatures", (0.5, 0.75, 1.0, 1.5, 2.0))
            ),
            minimum_confidences=tuple(
                value.get("minimum_confidences", (0.0, 0.25, 0.5))
            ),
            confidence_powers=tuple(
                value.get("confidence_powers", (0.0, 1.0))
            ),
            refine_views=bool(value.get("refine_views", True)),
        )


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationSearchResult:
    """Selected development configuration and all fail-closed search evidence."""

    lineage: LegacyViewCalibrationLineage
    config: LegacyViewCalibrationConfig
    baseline_report: LegacyViewEvaluationReport
    development_report: LegacyViewEvaluationReport
    development_gate: CalibrationGate
    evaluated_candidate_count: int
    rejected_candidate_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, LegacyViewCalibrationLineage):
            raise TypeError("lineage must be LegacyViewCalibrationLineage")
        if not isinstance(self.config, LegacyViewCalibrationConfig):
            raise TypeError("config must be LegacyViewCalibrationConfig")
        if self.baseline_report.split != self.lineage.development_split:
            raise LegacyViewCalibrationError(
                "baseline report is not from the lineage development split"
            )
        if self.development_report.split != self.lineage.development_split:
            raise LegacyViewCalibrationError(
                "candidate report is not from the lineage development split"
            )
        if self.development_report.config_digest != self.config.digest:
            raise LegacyViewCalibrationError(
                "development report does not match the selected config"
            )
        baseline_digest = LegacyViewCalibrationConfig.alpha_zero().digest
        if self.baseline_report.config_digest != baseline_digest:
            raise LegacyViewCalibrationError(
                "search baseline is not the exact alpha-zero config"
            )
        if int(self.evaluated_candidate_count) < 1:
            raise LegacyViewCalibrationError(
                "evaluated_candidate_count must be positive"
            )
        rejected = int(self.rejected_candidate_count)
        if rejected < 0 or rejected > int(self.evaluated_candidate_count):
            raise LegacyViewCalibrationError(
                "rejected_candidate_count is inconsistent"
            )
        if not isinstance(self.development_gate, CalibrationGate):
            raise TypeError("development_gate must be CalibrationGate")
        object.__setattr__(
            self, "evaluated_candidate_count", int(self.evaluated_candidate_count)
        )
        object.__setattr__(self, "rejected_candidate_count", rejected)

    @property
    def search_id(self) -> str:
        return _digest(
            {
                "config_digest": self.config.digest,
                "development_evaluation_id": self.development_report.evaluation_id,
                "lineage_id": self.lineage.lineage_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "baseline": self.baseline_report.to_dict(),
            "canary": {
                "artifact_sha256": self.lineage.canary_artifact_sha256,
                "hidden_during_search": True,
                "metrics_present": False,
            },
            "config": self.config.to_dict(),
            "config_digest": self.config.digest,
            "development": self.development_report.to_dict(),
            "development_gate": self.development_gate.to_dict(),
            "evaluated_candidate_count": self.evaluated_candidate_count,
            "full_transfer_allowed": False,
            "known_omitted_view_logit_rows": KNOWN_OMITTED_LEGACY_VIEW_LOGIT_ROWS,
            "lineage": self.lineage.to_dict(),
            "rejected_candidate_count": self.rejected_candidate_count,
            "schema_version": LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION,
            "search_id": self.search_id,
        }
        result["report_sha256"] = _digest(result)
        return result


def verify_legacy_view_calibration_report(
    report: Mapping[str, Any],
) -> str:
    """Verify and return a search report's full content address."""

    expected = _content_id(
        report.get("report_sha256", ""),
        name="report_sha256",
    )
    payload = dict(report)
    payload.pop("report_sha256", None)
    observed = _digest(payload)
    if expected != observed:
        raise LegacyViewCalibrationError(
            f"calibration report digest mismatch: {expected} != {observed}"
        )
    return observed


def _manifest_digest(manifest: LegalIRSplitManifest) -> str:
    return _content_id(manifest.digest, name="split manifest digest")


def _candidate_score(
    baseline: LegacyViewEvaluationReport,
    candidate: LegacyViewEvaluationReport,
    *,
    focus_head: str,
) -> tuple[float, ...]:
    before = baseline.family_metrics[focus_head]
    after = candidate.family_metrics[focus_head]
    # CE is deliberately the first tie breaker because full legacy reuse was
    # observed to regress it.  Remaining metrics are still independently gated.
    return (
        before.cross_entropy - after.cross_entropy,
        after.cosine - before.cosine,
        before.calibration_error - after.calibration_error,
        after.semantic_equivalence - before.semantic_equivalence,
        after.proof_reconstruction - before.proof_reconstruction,
        before.source_copy - after.source_copy,
        before.uncertainty - after.uncertainty,
    )


def search_legacy_view_calibration(
    examples: Sequence[LegacyViewCalibrationExample],
    *,
    lineage: LegacyViewCalibrationLineage,
    split_manifest: LegalIRSplitManifest | Mapping[str, Any],
    search_space: LegacyViewCalibrationSearchSpace | None = None,
    regression_tolerance: float = 0.0,
) -> LegacyViewCalibrationSearchResult:
    """Run deterministic per-head/per-view search without exposing the canary."""

    manifest = (
        split_manifest
        if isinstance(split_manifest, LegalIRSplitManifest)
        else LegalIRSplitManifest.from_mapping(split_manifest)
    )
    if _manifest_digest(manifest) != lineage.split_manifest_sha256:
        raise LegacyViewCalibrationError(
            "split manifest digest does not match calibration lineage"
        )
    require_hparam_selection_split(
        manifest,
        items=[{"sample_id": example.sample_id} for example in examples],
    )
    if any(
        manifest.assignments.get(example.sample_id) != lineage.development_split
        for example in examples
    ):
        raise LegacyViewCalibrationError(
            "search examples are not exclusively in the lineage development split"
        )

    grid = search_space or LegacyViewCalibrationSearchSpace()
    baseline_config = LegacyViewCalibrationConfig.alpha_zero()
    baseline = evaluate_legacy_view_calibration(
        examples, baseline_config, split=lineage.development_split
    )
    selected = baseline_config
    selected_report = baseline
    evaluated = 1
    rejected = 0

    parameter_grid = tuple(
        HeadCalibration(
            temperature=temperature,
            alpha=alpha,
            minimum_confidence=minimum_confidence,
            confidence_power=confidence_power,
        )
        for alpha in grid.alphas
        for temperature in grid.temperatures
        for minimum_confidence in grid.minimum_confidences
        for confidence_power in grid.confidence_powers
        if alpha > 0.0
    )
    for head in LEGACY_VIEW_CALIBRATION_HEADS:
        best_config = selected
        best_report = selected_report
        best_score = _candidate_score(baseline, best_report, focus_head=head)
        for parameters in parameter_grid:
            candidate_config = selected.with_head(head, parameters)
            candidate_report = evaluate_legacy_view_calibration(
                examples,
                candidate_config,
                split=lineage.development_split,
            )
            evaluated += 1
            gate = compare_legacy_view_reports(
                baseline,
                candidate_report,
                tolerance=regression_tolerance,
            )
            if not gate.accepted:
                rejected += 1
                continue
            score = _candidate_score(
                baseline, candidate_report, focus_head=head
            )
            if score > best_score or (
                score == best_score
                and candidate_config.digest < best_config.digest
            ):
                best_config = candidate_config
                best_report = candidate_report
                best_score = score
        selected = best_config
        selected_report = best_report

    if grid.refine_views:
        views_by_head: dict[str, set[str]] = defaultdict(set)
        for example in examples:
            for view in set(example.current_logits) | set(example.legacy_logits):
                views_by_head[canonical_legacy_view_head(view)].add(view)
        for head in LEGACY_VIEW_CALIBRATION_HEADS:
            for view in sorted(views_by_head[head]):
                best_config = selected
                best_report = selected_report
                best_score = _candidate_score(
                    baseline, best_report, focus_head=head
                )
                for parameters in parameter_grid:
                    candidate_config = selected.with_view(
                        view,
                        ViewCalibration(
                            temperature=parameters.temperature,
                            alpha=parameters.alpha,
                            minimum_confidence=parameters.minimum_confidence,
                            confidence_power=parameters.confidence_power,
                        ),
                    )
                    candidate_report = evaluate_legacy_view_calibration(
                        examples,
                        candidate_config,
                        split=lineage.development_split,
                    )
                    evaluated += 1
                    gate = compare_legacy_view_reports(
                        baseline,
                        candidate_report,
                        tolerance=regression_tolerance,
                    )
                    if not gate.accepted:
                        rejected += 1
                        continue
                    score = _candidate_score(
                        baseline, candidate_report, focus_head=head
                    )
                    if score > best_score or (
                        score == best_score
                        and candidate_config.digest < best_config.digest
                    ):
                        best_config = candidate_config
                        best_report = candidate_report
                        best_score = score
                selected = best_config
                selected_report = best_report

    gate = compare_legacy_view_reports(
        baseline,
        selected_report,
        tolerance=regression_tolerance,
    )
    return LegacyViewCalibrationSearchResult(
        lineage=lineage,
        config=selected,
        baseline_report=baseline,
        development_report=selected_report,
        development_gate=gate,
        evaluated_candidate_count=evaluated,
        rejected_candidate_count=rejected,
    )


@dataclass(frozen=True, slots=True)
class LegacyViewCalibrationPromotion:
    """Final decision after the selected config is evaluated on hidden canary."""

    accepted: bool
    reasons: tuple[str, ...]
    failed_families: tuple[str, ...]
    development_gate: CalibrationGate
    canary_gate: CalibrationGate
    selected_config_digest: str
    search_id: str
    canary_artifact_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "canary_artifact_sha256": self.canary_artifact_sha256,
            "canary_gate": self.canary_gate.to_dict(),
            "development_gate": self.development_gate.to_dict(),
            "failed_families": list(self.failed_families),
            "full_transfer_allowed": False,
            "reasons": list(self.reasons),
            "search_id": self.search_id,
            "selected_config_digest": self.selected_config_digest,
        }


def promote_legacy_view_calibration(
    search_result: LegacyViewCalibrationSearchResult,
    canary_baseline: LegacyViewEvaluationReport,
    canary_candidate: LegacyViewEvaluationReport,
    *,
    canary_artifact_sha256: str,
    regression_tolerance: float = 0.0,
) -> LegacyViewCalibrationPromotion:
    """Apply development and hidden-canary family gates to one selected config."""

    observed_canary = _content_id(
        canary_artifact_sha256, name="canary_artifact_sha256"
    )
    reasons: list[str] = []
    if observed_canary != search_result.lineage.canary_artifact_sha256:
        reasons.append("canary_lineage_mismatch")
    if canary_candidate.config_digest != search_result.config.digest:
        reasons.append("canary_config_mismatch")
    if canary_baseline.config_digest != LegacyViewCalibrationConfig.alpha_zero().digest:
        reasons.append("canary_baseline_not_alpha_zero")
    if canary_baseline.split != "canary":
        reasons.append("canary_baseline_split_mismatch")
    if canary_candidate.split != "canary":
        reasons.append("canary_candidate_split_mismatch")
    if search_result.config.is_full_transfer:
        reasons.append("full_legacy_transfer_forbidden")
    if search_result.config.is_alpha_zero:
        reasons.append("alpha_zero_baseline_is_not_a_promotion")
    development_gate = compare_legacy_view_reports(
        search_result.baseline_report,
        search_result.development_report,
        tolerance=regression_tolerance,
        require_improvement=True,
    )
    canary_gate = compare_legacy_view_reports(
        canary_baseline,
        canary_candidate,
        tolerance=regression_tolerance,
        require_improvement=True,
    )
    reasons.extend(
        f"development:{reason}" for reason in development_gate.reasons
    )
    reasons.extend(f"canary:{reason}" for reason in canary_gate.reasons)
    failed = tuple(
        dict.fromkeys(
            (*development_gate.failed_families, *canary_gate.failed_families)
        )
    )
    return LegacyViewCalibrationPromotion(
        accepted=not reasons,
        reasons=tuple(reasons),
        failed_families=failed,
        development_gate=development_gate,
        canary_gate=canary_gate,
        selected_config_digest=search_result.config.digest,
        search_id=search_result.search_id,
        canary_artifact_sha256=observed_canary,
    )


# Compatibility aliases use the task vocabulary and keep callers concise.
LegacyViewHeadCalibration = HeadCalibration
LegacyViewCalibrationParameters = HeadCalibration
LegacyViewCalibrationPolicy = LegacyViewCalibrationConfig
LegacyViewCalibrationResult = CalibratedLogits
calibrate_feature_to_legal_ir_view_logits = (
    calibrate_feature_legal_ir_view_logits
)
calibrate_legacy_feature_view_logits = calibrate_feature_legal_ir_view_logits
calibrate_legacy_feature_to_legal_ir_view_logits = (
    calibrate_feature_legal_ir_view_logits
)
evaluate_calibration = evaluate_legacy_view_calibration
search_calibration = search_legacy_view_calibration
promotion_gate = promote_legacy_view_calibration


__all__ = [
    "CALIBRATION_ERROR",
    "CEC_HEAD",
    "COSINE",
    "CROSS_ENTROPY",
    "CalibratedLogits",
    "CalibrationGate",
    "DEONTIC_HEAD",
    "FRAME_LOGIC_HEAD",
    "FamilyCalibrationMetrics",
    "GLOBAL_HEAD",
    "HeadCalibration",
    "KNOWN_OMITTED_LEGACY_VIEW_LOGIT_ROWS",
    "KNOWLEDGE_GRAPH_HEAD",
    "LEGACY_VIEW_CALIBRATION_FEATURE_FIELD",
    "LEGACY_VIEW_CALIBRATION_HEADS",
    "LEGACY_VIEW_CALIBRATION_LINEAGE_SCHEMA_VERSION",
    "LEGACY_VIEW_CALIBRATION_METRICS",
    "LEGACY_VIEW_CALIBRATION_REPORT_SCHEMA_VERSION",
    "LEGACY_VIEW_CALIBRATION_SCHEMA_VERSION",
    "LegacyViewCalibrationConfig",
    "LegacyViewCalibrationError",
    "LegacyViewCalibrationExample",
    "LegacyViewCalibrationLineage",
    "LegacyViewCalibrationParameters",
    "LegacyViewCalibrationPolicy",
    "LegacyViewCalibrationPromotion",
    "LegacyViewCalibrationResult",
    "LegacyViewCalibrationSearchResult",
    "LegacyViewCalibrationSearchSpace",
    "LegacyViewEvaluationReport",
    "LegacyViewHeadCalibration",
    "PROOF_RECONSTRUCTION",
    "PROVER_HEAD",
    "SEMANTIC_EQUIVALENCE",
    "SOURCE_COPY",
    "TDFOL_HEAD",
    "UNCERTAINTY",
    "ViewCalibration",
    "aggregate_feature_legal_ir_view_logits",
    "apply_legacy_view_calibration",
    "calibrate_feature_legal_ir_view_logits",
    "calibrate_feature_to_legal_ir_view_logits",
    "calibrate_legacy_view_logits",
    "calibrate_legacy_feature_to_legal_ir_view_logits",
    "calibrate_legacy_feature_view_logits",
    "canonical_legacy_view_head",
    "compare_legacy_view_reports",
    "evaluate_calibration",
    "evaluate_legacy_view_calibration",
    "promote_legacy_view_calibration",
    "promotion_gate",
    "search_calibration",
    "search_legacy_view_calibration",
    "verify_legacy_view_calibration_report",
]
