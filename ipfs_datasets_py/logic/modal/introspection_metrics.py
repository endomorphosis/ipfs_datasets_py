"""Frozen LegalIR introspection metric records and canary manifest validation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_STATE_SCHEMA_VERSION,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)


INTROSPECTION_METRIC_SCHEMA_VERSION = "legal-ir-introspection-metrics-v1"
INTROSPECTION_METRIC_CONFIG_VERSION = "legal-ir-introspection-metrics-config-v1"
LEANSTRAL_CANARY_MANIFEST_VERSION = "legal-ir-leanstral-canary-manifest-v1"
REQUIRED_LEGAL_LOGIC_FAMILIES = tuple(family.value for family in ModalLogicFamily)


class IntrospectionMetricSchemaError(ValueError):
    """Raised when a metric record or canary manifest is not schema-valid."""


@dataclass(frozen=True)
class CompilerIRMetrics:
    """Compiler IR reconstruction diagnostics."""

    cross_entropy_loss: float
    cross_entropy_excess_loss: float
    cosine_loss: float
    cosine_similarity: float

    def __post_init__(self) -> None:
        _require_non_negative_finite("compiler_ir.cross_entropy_loss", self.cross_entropy_loss)
        _require_non_negative_finite(
            "compiler_ir.cross_entropy_excess_loss",
            self.cross_entropy_excess_loss,
        )
        _require_non_negative_finite("compiler_ir.cosine_loss", self.cosine_loss)
        _require_finite("compiler_ir.cosine_similarity", self.cosine_similarity)

    def to_dict(self) -> Dict[str, float]:
        return {
            "cosine_loss": _stable_float(self.cosine_loss),
            "cosine_similarity": _stable_float(self.cosine_similarity),
            "cross_entropy_excess_loss": _stable_float(self.cross_entropy_excess_loss),
            "cross_entropy_loss": _stable_float(self.cross_entropy_loss),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompilerIRMetrics":
        return cls(
            cross_entropy_loss=_as_float(data, "cross_entropy_loss"),
            cross_entropy_excess_loss=_as_float(data, "cross_entropy_excess_loss"),
            cosine_loss=_as_float(data, "cosine_loss"),
            cosine_similarity=_as_float(data, "cosine_similarity"),
        )


@dataclass(frozen=True)
class LearnedIRViewFamilyMetrics:
    """Learned LegalIR view diagnostics for one modal family stratum."""

    family: str
    cross_entropy_loss: float
    cross_entropy_excess_loss: float
    cosine_loss: float
    cosine_similarity: float
    target_probability: float
    predicted_probability: float

    def __post_init__(self) -> None:
        _require_known_family(self.family)
        prefix = f"learned_ir_view_by_family.{self.family}"
        _require_non_negative_finite(f"{prefix}.cross_entropy_loss", self.cross_entropy_loss)
        _require_non_negative_finite(
            f"{prefix}.cross_entropy_excess_loss",
            self.cross_entropy_excess_loss,
        )
        _require_non_negative_finite(f"{prefix}.cosine_loss", self.cosine_loss)
        _require_finite(f"{prefix}.cosine_similarity", self.cosine_similarity)
        _require_probability(f"{prefix}.target_probability", self.target_probability)
        _require_probability(f"{prefix}.predicted_probability", self.predicted_probability)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cosine_loss": _stable_float(self.cosine_loss),
            "cosine_similarity": _stable_float(self.cosine_similarity),
            "cross_entropy_excess_loss": _stable_float(self.cross_entropy_excess_loss),
            "cross_entropy_loss": _stable_float(self.cross_entropy_loss),
            "family": self.family,
            "predicted_probability": _stable_float(self.predicted_probability),
            "target_probability": _stable_float(self.target_probability),
        }

    @classmethod
    def from_mapping(cls, family: str, data: Mapping[str, Any]) -> "LearnedIRViewFamilyMetrics":
        payload_family = str(data.get("family") or family)
        if payload_family != family:
            raise IntrospectionMetricSchemaError(
                f"learned_ir_view_by_family key {family!r} does not match family field {payload_family!r}"
            )
        return cls(
            family=family,
            cross_entropy_loss=_as_float(data, "cross_entropy_loss"),
            cross_entropy_excess_loss=_as_float(data, "cross_entropy_excess_loss"),
            cosine_loss=_as_float(data, "cosine_loss"),
            cosine_similarity=_as_float(data, "cosine_similarity"),
            target_probability=_as_float(data, "target_probability"),
            predicted_probability=_as_float(data, "predicted_probability"),
        )


@dataclass(frozen=True)
class SourceDecodedMetrics:
    """Source text to decoded structural text/embedding losses."""

    embedding_cosine_loss: float
    embedding_cosine_similarity: float
    token_loss: float
    token_similarity: float

    def __post_init__(self) -> None:
        _require_non_negative_finite("source_to_decoded.embedding_cosine_loss", self.embedding_cosine_loss)
        _require_finite("source_to_decoded.embedding_cosine_similarity", self.embedding_cosine_similarity)
        _require_non_negative_finite("source_to_decoded.token_loss", self.token_loss)
        _require_probability("source_to_decoded.token_similarity", self.token_similarity)

    def to_dict(self) -> Dict[str, float]:
        return {
            "embedding_cosine_loss": _stable_float(self.embedding_cosine_loss),
            "embedding_cosine_similarity": _stable_float(self.embedding_cosine_similarity),
            "token_loss": _stable_float(self.token_loss),
            "token_similarity": _stable_float(self.token_similarity),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SourceDecodedMetrics":
        return cls(
            embedding_cosine_loss=_as_float(data, "embedding_cosine_loss"),
            embedding_cosine_similarity=_as_float(data, "embedding_cosine_similarity"),
            token_loss=_as_float(data, "token_loss"),
            token_similarity=_as_float(data, "token_similarity"),
        )


@dataclass(frozen=True)
class StructuralProverValidity:
    """Structural and theorem-prover validity gates for one metric record."""

    structural_valid: bool
    modal_ir_valid: bool
    prover_compiles: bool
    proofs_valid: bool
    attempted_count: int
    valid_count: int
    proved_count: int
    failure_ratio: float

    def __post_init__(self) -> None:
        for key, value in (
            ("attempted_count", self.attempted_count),
            ("valid_count", self.valid_count),
            ("proved_count", self.proved_count),
        ):
            if not isinstance(value, int) or value < 0:
                raise IntrospectionMetricSchemaError(f"validity.{key} must be a non-negative integer")
        if self.valid_count > self.attempted_count:
            raise IntrospectionMetricSchemaError("validity.valid_count cannot exceed attempted_count")
        if self.proved_count > self.attempted_count:
            raise IntrospectionMetricSchemaError("validity.proved_count cannot exceed attempted_count")
        _require_probability("validity.failure_ratio", self.failure_ratio)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted_count": self.attempted_count,
            "failure_ratio": _stable_float(self.failure_ratio),
            "modal_ir_valid": bool(self.modal_ir_valid),
            "proofs_valid": bool(self.proofs_valid),
            "proved_count": self.proved_count,
            "prover_compiles": bool(self.prover_compiles),
            "structural_valid": bool(self.structural_valid),
            "valid_count": self.valid_count,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StructuralProverValidity":
        return cls(
            structural_valid=_as_bool(data, "structural_valid"),
            modal_ir_valid=_as_bool(data, "modal_ir_valid"),
            prover_compiles=_as_bool(data, "prover_compiles"),
            proofs_valid=_as_bool(data, "proofs_valid"),
            attempted_count=_as_int(data, "attempted_count"),
            valid_count=_as_int(data, "valid_count"),
            proved_count=_as_int(data, "proved_count"),
            failure_ratio=_as_float(data, "failure_ratio"),
        )


@dataclass(frozen=True)
class AntiCopyMetrics:
    """Reward-hacking guardrails for source-span copying."""

    source_copy_loss: float
    source_span_copy_ratio: float
    anti_copy_penalty: float

    def __post_init__(self) -> None:
        _require_non_negative_finite("anti_copy.source_copy_loss", self.source_copy_loss)
        _require_probability("anti_copy.source_span_copy_ratio", self.source_span_copy_ratio)
        _require_non_negative_finite("anti_copy.anti_copy_penalty", self.anti_copy_penalty)

    def to_dict(self) -> Dict[str, float]:
        return {
            "anti_copy_penalty": _stable_float(self.anti_copy_penalty),
            "source_copy_loss": _stable_float(self.source_copy_loss),
            "source_span_copy_ratio": _stable_float(self.source_span_copy_ratio),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AntiCopyMetrics":
        return cls(
            source_copy_loss=_as_float(data, "source_copy_loss"),
            source_span_copy_ratio=_as_float(data, "source_span_copy_ratio"),
            anti_copy_penalty=_as_float(data, "anti_copy_penalty"),
        )


@dataclass(frozen=True)
class StateConfigVersions:
    """Version stamps that make metric comparisons fail closed."""

    state_version: str = MODAL_AUTOENCODER_STATE_SCHEMA_VERSION
    config_version: str = INTROSPECTION_METRIC_CONFIG_VERSION
    architecture_version: str = MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    modal_ir_version: str = "modal-ir-v1"

    def __post_init__(self) -> None:
        for key, value in self.to_dict().items():
            if not str(value).strip():
                raise IntrospectionMetricSchemaError(f"versions.{key} must not be empty")

    def to_dict(self) -> Dict[str, str]:
        return {
            "architecture_version": str(self.architecture_version),
            "config_version": str(self.config_version),
            "modal_ir_version": str(self.modal_ir_version),
            "state_version": str(self.state_version),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StateConfigVersions":
        return cls(
            state_version=str(data.get("state_version") or ""),
            config_version=str(data.get("config_version") or ""),
            architecture_version=str(data.get("architecture_version") or ""),
            modal_ir_version=str(data.get("modal_ir_version") or ""),
        )


@dataclass(frozen=True)
class PhaseTiming:
    """Deterministic wall-clock budget slot for one pipeline phase."""

    phase: str
    duration_ms: float

    def __post_init__(self) -> None:
        if not self.phase.strip():
            raise IntrospectionMetricSchemaError("phase_timings[].phase must not be empty")
        _require_non_negative_finite(f"phase_timings.{self.phase}.duration_ms", self.duration_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration_ms": _stable_float(self.duration_ms),
            "phase": self.phase,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PhaseTiming":
        return cls(
            phase=str(data.get("phase") or ""),
            duration_ms=_as_float(data, "duration_ms"),
        )


@dataclass(frozen=True)
class IntrospectionMetricRecord:
    """Versioned metric baseline for one LegalIR canary case."""

    case_id: str
    family: str
    compiler_ir: CompilerIRMetrics
    learned_ir_view_by_family: Mapping[str, LearnedIRViewFamilyMetrics]
    source_to_decoded: SourceDecodedMetrics
    validity: StructuralProverValidity
    anti_copy: AntiCopyMetrics
    versions: StateConfigVersions
    phase_timings: Sequence[PhaseTiming]
    schema_version: str = INTROSPECTION_METRIC_SCHEMA_VERSION
    record_id: str = ""
    source_text_sha256: str = ""
    modal_ir_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != INTROSPECTION_METRIC_SCHEMA_VERSION:
            raise IntrospectionMetricSchemaError(f"unsupported metric schema_version: {self.schema_version}")
        if not self.case_id.strip():
            raise IntrospectionMetricSchemaError("case_id must not be empty")
        _require_known_family(self.family)
        if self.family not in self.learned_ir_view_by_family:
            raise IntrospectionMetricSchemaError(
                f"learned_ir_view_by_family must include the record family {self.family!r}"
            )
        for key, metric in self.learned_ir_view_by_family.items():
            _require_known_family(key)
            if metric.family != key:
                raise IntrospectionMetricSchemaError(
                    f"learned_ir_view_by_family[{key!r}].family does not match key"
                )
        phases = [timing.phase for timing in self.phase_timings]
        if not phases:
            raise IntrospectionMetricSchemaError("phase_timings must not be empty")
        if len(set(phases)) != len(phases):
            raise IntrospectionMetricSchemaError("phase_timings must not contain duplicate phases")
        if self.record_id and self.record_id != self.expected_record_id():
            raise IntrospectionMetricSchemaError(
                f"record_id {self.record_id!r} does not match frozen payload"
            )

    def to_dict(self, *, include_record_id: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "anti_copy": self.anti_copy.to_dict(),
            "case_id": self.case_id,
            "compiler_ir": self.compiler_ir.to_dict(),
            "family": self.family,
            "learned_ir_view_by_family": {
                family: metric.to_dict()
                for family, metric in sorted(self.learned_ir_view_by_family.items())
            },
            "modal_ir_hash": self.modal_ir_hash,
            "phase_timings": [timing.to_dict() for timing in self.phase_timings],
            "schema_version": self.schema_version,
            "source_text_sha256": self.source_text_sha256,
            "source_to_decoded": self.source_to_decoded.to_dict(),
            "validity": self.validity.to_dict(),
            "versions": self.versions.to_dict(),
        }
        if include_record_id:
            payload["record_id"] = self.record_id or self.expected_record_id()
        return payload

    def to_json(self) -> str:
        return _stable_json(self.to_dict())

    def expected_record_id(self) -> str:
        return "lir-metric-" + _hash_json(self.to_dict(include_record_id=False))[:16]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "IntrospectionMetricRecord":
        schema_version = str(data.get("schema_version") or "")
        if schema_version != INTROSPECTION_METRIC_SCHEMA_VERSION:
            raise IntrospectionMetricSchemaError(f"unsupported metric schema_version: {schema_version}")
        learned_raw = _as_mapping(data, "learned_ir_view_by_family")
        learned = {
            str(family): LearnedIRViewFamilyMetrics.from_mapping(str(family), _mapping(metric))
            for family, metric in sorted(learned_raw.items())
        }
        return cls(
            case_id=str(data.get("case_id") or ""),
            family=str(data.get("family") or ""),
            compiler_ir=CompilerIRMetrics.from_mapping(_as_mapping(data, "compiler_ir")),
            learned_ir_view_by_family=learned,
            source_to_decoded=SourceDecodedMetrics.from_mapping(_as_mapping(data, "source_to_decoded")),
            validity=StructuralProverValidity.from_mapping(_as_mapping(data, "validity")),
            anti_copy=AntiCopyMetrics.from_mapping(_as_mapping(data, "anti_copy")),
            versions=StateConfigVersions.from_mapping(_as_mapping(data, "versions")),
            phase_timings=tuple(
                PhaseTiming.from_mapping(_mapping(item))
                for item in _as_sequence(data, "phase_timings")
            ),
            schema_version=schema_version,
            record_id=str(data.get("record_id") or ""),
            source_text_sha256=str(data.get("source_text_sha256") or ""),
            modal_ir_hash=str(data.get("modal_ir_hash") or ""),
        )


@dataclass(frozen=True)
class LeanstralCanaryManifest:
    """Frozen, stratified canary baseline for Leanstral introspection metrics."""

    cases: Sequence[IntrospectionMetricRecord]
    manifest_version: str = LEANSTRAL_CANARY_MANIFEST_VERSION
    metric_schema_version: str = INTROSPECTION_METRIC_SCHEMA_VERSION
    required_families: Sequence[str] = REQUIRED_LEGAL_LOGIC_FAMILIES
    frozen: bool = True

    def __post_init__(self) -> None:
        if self.manifest_version != LEANSTRAL_CANARY_MANIFEST_VERSION:
            raise IntrospectionMetricSchemaError(
                f"unsupported manifest_version: {self.manifest_version}"
            )
        if self.metric_schema_version != INTROSPECTION_METRIC_SCHEMA_VERSION:
            raise IntrospectionMetricSchemaError(
                f"unsupported metric_schema_version: {self.metric_schema_version}"
            )
        if not self.frozen:
            raise IntrospectionMetricSchemaError("canary manifest must be frozen")
        required = tuple(str(family) for family in self.required_families)
        if tuple(required) != REQUIRED_LEGAL_LOGIC_FAMILIES:
            raise IntrospectionMetricSchemaError("required_families must match the frozen LegalIR family set")
        seen = {case.family for case in self.cases}
        missing = [family for family in required if family not in seen]
        if missing:
            raise IntrospectionMetricSchemaError(
                f"canary manifest missing required families: {', '.join(missing)}"
            )
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise IntrospectionMetricSchemaError("canary manifest contains duplicate case_id values")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cases": [case.to_dict() for case in self.cases],
            "frozen": self.frozen,
            "manifest_version": self.manifest_version,
            "metric_schema_version": self.metric_schema_version,
            "required_families": list(self.required_families),
        }

    def to_json(self) -> str:
        return _stable_json(self.to_dict())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralCanaryManifest":
        manifest_version = str(data.get("manifest_version") or "")
        if manifest_version != LEANSTRAL_CANARY_MANIFEST_VERSION:
            raise IntrospectionMetricSchemaError(
                f"unsupported manifest_version: {manifest_version}"
            )
        metric_schema_version = str(data.get("metric_schema_version") or "")
        if metric_schema_version != INTROSPECTION_METRIC_SCHEMA_VERSION:
            raise IntrospectionMetricSchemaError(
                f"unsupported metric_schema_version: {metric_schema_version}"
            )
        return cls(
            cases=tuple(
                IntrospectionMetricRecord.from_mapping(_mapping(item))
                for item in _as_sequence(data, "cases")
            ),
            manifest_version=manifest_version,
            metric_schema_version=metric_schema_version,
            required_families=tuple(str(value) for value in _as_sequence(data, "required_families")),
            frozen=_as_bool(data, "frozen"),
        )


def build_introspection_metric_record(
    *,
    case_id: str,
    family: str,
    losses: Mapping[str, Any],
    learned_ir_view_by_family: Mapping[str, Mapping[str, Any]],
    validity: Mapping[str, Any],
    phase_timings: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    versions: Optional[Mapping[str, Any]] = None,
    source_text: str = "",
    source_text_sha256: str = "",
    modal_ir_hash: str = "",
) -> IntrospectionMetricRecord:
    """Build a schema-valid record from codec/autoencoder loss payloads."""

    compiler_ir = CompilerIRMetrics(
        cross_entropy_loss=_float_from(losses, "cross_entropy_loss", 0.0),
        cross_entropy_excess_loss=_float_from(losses, "cross_entropy_excess_loss", 0.0),
        cosine_loss=_float_from(losses, "cosine_loss", 0.0),
        cosine_similarity=_float_from(losses, "cosine_similarity", 1.0),
    )
    source_to_decoded = SourceDecodedMetrics(
        embedding_cosine_loss=_float_from(
            losses,
            "source_decompiled_text_embedding_cosine_loss",
            _float_from(losses, "embedding_cosine_gap", 0.0),
        ),
        embedding_cosine_similarity=_float_from(
            losses,
            "source_decompiled_text_embedding_cosine_similarity",
            1.0
            - _float_from(
                losses,
                "source_decompiled_text_embedding_cosine_loss",
                _float_from(losses, "embedding_cosine_gap", 0.0),
            ),
        ),
        token_loss=_float_from(losses, "source_decompiled_text_token_loss", 0.0),
        token_similarity=_float_from(losses, "source_decompiled_text_token_similarity", 1.0),
    )
    anti_copy = AntiCopyMetrics(
        source_copy_loss=_float_from(losses, "source_copy_loss", 0.0),
        source_span_copy_ratio=_float_from(losses, "source_span_copy_ratio", 0.0),
        anti_copy_penalty=_float_from(
            losses,
            "source_copy_reward_hack_penalty",
            _float_from(losses, "anti_copy_penalty", 0.0),
        ),
    )
    timing_records = _phase_timings_from_input(phase_timings)
    version_record = StateConfigVersions.from_mapping(versions or StateConfigVersions().to_dict())
    source_hash = source_text_sha256 or (_hash_text(source_text) if source_text else "")
    record = IntrospectionMetricRecord(
        case_id=case_id,
        family=family,
        compiler_ir=compiler_ir,
        learned_ir_view_by_family={
            str(name): LearnedIRViewFamilyMetrics.from_mapping(str(name), _mapping(metric))
            for name, metric in learned_ir_view_by_family.items()
        },
        source_to_decoded=source_to_decoded,
        validity=StructuralProverValidity.from_mapping(validity),
        anti_copy=anti_copy,
        versions=version_record,
        phase_timings=timing_records,
        source_text_sha256=source_hash,
        modal_ir_hash=modal_ir_hash,
    )
    return IntrospectionMetricRecord.from_mapping(record.to_dict())


def load_introspection_metric_record(path: str | Path) -> IntrospectionMetricRecord:
    """Load and strictly validate one metric record from JSON."""

    return IntrospectionMetricRecord.from_mapping(_load_json_mapping(path))


def load_leanstral_canary_manifest(path: str | Path) -> LeanstralCanaryManifest:
    """Load and strictly validate a frozen Leanstral canary manifest."""

    return LeanstralCanaryManifest.from_mapping(_load_json_mapping(path))


def validate_leanstral_canary_manifest(data: Mapping[str, Any]) -> LeanstralCanaryManifest:
    """Validate manifest data and return the typed manifest."""

    return LeanstralCanaryManifest.from_mapping(data)


def _phase_timings_from_input(
    value: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[PhaseTiming, ...]:
    if isinstance(value, Mapping):
        return tuple(
            PhaseTiming(phase=str(phase), duration_ms=float(duration))
            for phase, duration in sorted(value.items())
        )
    return tuple(PhaseTiming.from_mapping(_mapping(item)) for item in value)


def _load_json_mapping(path: str | Path) -> Mapping[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise IntrospectionMetricSchemaError("JSON root must be an object")
    return data


def _stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _hash_json(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(data).encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_float(value: float) -> float:
    return round(float(value), 12)


def _require_known_family(family: str) -> None:
    if family not in REQUIRED_LEGAL_LOGIC_FAMILIES:
        raise IntrospectionMetricSchemaError(f"unknown LegalIR family: {family!r}")


def _require_finite(name: str, value: float) -> None:
    if not isinstance(value, (float, int)) or not math.isfinite(float(value)):
        raise IntrospectionMetricSchemaError(f"{name} must be finite")


def _require_non_negative_finite(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) < 0.0:
        raise IntrospectionMetricSchemaError(f"{name} must be non-negative")


def _require_probability(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) < 0.0 or float(value) > 1.0:
        raise IntrospectionMetricSchemaError(f"{name} must be between 0 and 1")


def _as_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise IntrospectionMetricSchemaError(f"{key} must be an object")
    return value


def _as_sequence(data: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = data.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise IntrospectionMetricSchemaError(f"{key} must be a list")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntrospectionMetricSchemaError("expected object")
    return value


def _as_float(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        raise IntrospectionMetricSchemaError(f"{key} must be a number")
    return float(value)


def _float_from(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return float(default)
    return float(value)


def _as_int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise IntrospectionMetricSchemaError(f"{key} must be an integer")
    return int(value)


def _as_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise IntrospectionMetricSchemaError(f"{key} must be a boolean")
    return value


__all__ = [
    "AntiCopyMetrics",
    "CompilerIRMetrics",
    "INTROSPECTION_METRIC_CONFIG_VERSION",
    "INTROSPECTION_METRIC_SCHEMA_VERSION",
    "IntrospectionMetricRecord",
    "IntrospectionMetricSchemaError",
    "LEANSTRAL_CANARY_MANIFEST_VERSION",
    "LeanstralCanaryManifest",
    "LearnedIRViewFamilyMetrics",
    "PhaseTiming",
    "REQUIRED_LEGAL_LOGIC_FAMILIES",
    "SourceDecodedMetrics",
    "StateConfigVersions",
    "StructuralProverValidity",
    "build_introspection_metric_record",
    "load_introspection_metric_record",
    "load_leanstral_canary_manifest",
    "validate_leanstral_canary_manifest",
]
