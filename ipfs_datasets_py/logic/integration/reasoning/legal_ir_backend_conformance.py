"""Backend conformance checks for LegalIR target projections.

LegalIR has several backend-facing projections: frame logic, deontic IR,
TDFOL, knowledge graphs, CEC/event calculus, external prover translations, and
the decompiler.  This module gives promotion gates a deterministic way to ask
whether those projections preserve the same obligations and shared semantic
features, or whether a backend explicitly reported a typed unsupported feature.
Silent drops are always blocking.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Optional


LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION: Final = (
    "legal-ir-backend-conformance-v1"
)


class LegalIRBackendTarget(str, Enum):
    """Canonical LegalIR backend targets checked by the conformance gate."""

    FRAME_LOGIC = "frame_logic"
    DEONTIC = "deontic"
    TDFOL = "tdfol"
    KG = "kg"
    CEC = "cec"
    EXTERNAL_PROVER = "external_prover"
    DECOMPILER = "decompiler"


class LegalIRBackendFeature(str, Enum):
    """Shared semantic features surfaced by one or more backends."""

    FRAME_LOGIC = "frame_logic"
    DEONTIC = "deontic"
    TDFOL = "tdfol"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CEC = "cec"
    EXTERNAL_PROOF = "external_proof"
    DECOMPILER_ROUND_TRIP = "decompiler_round_trip"
    OBLIGATION_PRESERVATION = "obligation_preservation"
    PROVENANCE = "provenance"
    EXCEPTION_SCOPE = "exception_scope"
    COUNTEREXAMPLE = "counterexample"


class LegalIRBackendDiagnosticSeverity(str, Enum):
    """Severity values used by conformance diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LegalIRBackendConformanceDiagnosticType(str, Enum):
    """Stable diagnostic codes emitted by backend conformance checks."""

    UNSUPPORTED_FEATURE = "unsupported_feature"
    INVALID_UNSUPPORTED_DIAGNOSTIC = "invalid_unsupported_diagnostic"
    MISSING_BACKEND = "missing_backend"
    DUPLICATE_BACKEND_PROJECTION = "duplicate_backend_projection"
    SUPPORTED_FEATURE_WITHOUT_PROJECTION = "supported_feature_without_projection"
    SILENT_OBLIGATION_DROP = "silent_obligation_drop"
    SHARED_SEMANTICS_MISMATCH = "shared_semantics_mismatch"
    REQUIRED_FEATURE_WITHOUT_COVERAGE = "required_feature_without_coverage"


DEFAULT_LEGAL_IR_BACKEND_TARGETS: Final[tuple[str, ...]] = tuple(
    target.value for target in LegalIRBackendTarget
)

DEFAULT_LEGAL_IR_BACKEND_FEATURES: Final[tuple[str, ...]] = tuple(
    feature.value for feature in LegalIRBackendFeature
)

DEFAULT_LEGAL_IR_BACKEND_CAPABILITIES: Final[Mapping[str, tuple[str, ...]]] = {
    LegalIRBackendTarget.FRAME_LOGIC.value: (
        LegalIRBackendFeature.FRAME_LOGIC.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
        LegalIRBackendFeature.PROVENANCE.value,
    ),
    LegalIRBackendTarget.DEONTIC.value: (
        LegalIRBackendFeature.DEONTIC.value,
        LegalIRBackendFeature.EXCEPTION_SCOPE.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
        LegalIRBackendFeature.PROVENANCE.value,
    ),
    LegalIRBackendTarget.TDFOL.value: (
        LegalIRBackendFeature.TDFOL.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    ),
    LegalIRBackendTarget.KG.value: (
        LegalIRBackendFeature.KNOWLEDGE_GRAPH.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
        LegalIRBackendFeature.PROVENANCE.value,
    ),
    LegalIRBackendTarget.CEC.value: (
        LegalIRBackendFeature.CEC.value,
        LegalIRBackendFeature.COUNTEREXAMPLE.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    ),
    LegalIRBackendTarget.EXTERNAL_PROVER.value: (
        LegalIRBackendFeature.EXTERNAL_PROOF.value,
        LegalIRBackendFeature.COUNTEREXAMPLE.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    ),
    LegalIRBackendTarget.DECOMPILER.value: (
        LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value,
        LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
        LegalIRBackendFeature.PROVENANCE.value,
    ),
}

_BACKEND_ALIASES: Final[Mapping[str, str]] = {
    "frame": LegalIRBackendTarget.FRAME_LOGIC.value,
    "frame_logic": LegalIRBackendTarget.FRAME_LOGIC.value,
    "flogic": LegalIRBackendTarget.FRAME_LOGIC.value,
    "deontic": LegalIRBackendTarget.DEONTIC.value,
    "deontic_ir": LegalIRBackendTarget.DEONTIC.value,
    "tdfol": LegalIRBackendTarget.TDFOL.value,
    "temporal": LegalIRBackendTarget.TDFOL.value,
    "temporal_deontic_fol": LegalIRBackendTarget.TDFOL.value,
    "kg": LegalIRBackendTarget.KG.value,
    "knowledge_graph": LegalIRBackendTarget.KG.value,
    "knowledge_graphs": LegalIRBackendTarget.KG.value,
    "cec": LegalIRBackendTarget.CEC.value,
    "event_calculus": LegalIRBackendTarget.CEC.value,
    "external": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "external_proof": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "external_prover": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "external_provers": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "hammer": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "prover": LegalIRBackendTarget.EXTERNAL_PROVER.value,
    "decompiler": LegalIRBackendTarget.DECOMPILER.value,
    "round_trip": LegalIRBackendTarget.DECOMPILER.value,
}

_FEATURE_ALIASES: Final[Mapping[str, str]] = {
    "frame": LegalIRBackendFeature.FRAME_LOGIC.value,
    "frame_logic": LegalIRBackendFeature.FRAME_LOGIC.value,
    "flogic": LegalIRBackendFeature.FRAME_LOGIC.value,
    "modal_frame": LegalIRBackendFeature.FRAME_LOGIC.value,
    "deontic": LegalIRBackendFeature.DEONTIC.value,
    "deontic_ir": LegalIRBackendFeature.DEONTIC.value,
    "modality": LegalIRBackendFeature.DEONTIC.value,
    "modal_force": LegalIRBackendFeature.DEONTIC.value,
    "tdfol": LegalIRBackendFeature.TDFOL.value,
    "temporal": LegalIRBackendFeature.TDFOL.value,
    "temporal_window": LegalIRBackendFeature.TDFOL.value,
    "temporal_deontic_fol": LegalIRBackendFeature.TDFOL.value,
    "kg": LegalIRBackendFeature.KNOWLEDGE_GRAPH.value,
    "graph": LegalIRBackendFeature.KNOWLEDGE_GRAPH.value,
    "knowledge_graph": LegalIRBackendFeature.KNOWLEDGE_GRAPH.value,
    "knowledge_graphs": LegalIRBackendFeature.KNOWLEDGE_GRAPH.value,
    "cec": LegalIRBackendFeature.CEC.value,
    "event_calculus": LegalIRBackendFeature.CEC.value,
    "lifecycle": LegalIRBackendFeature.CEC.value,
    "external": LegalIRBackendFeature.EXTERNAL_PROOF.value,
    "external_proof": LegalIRBackendFeature.EXTERNAL_PROOF.value,
    "external_prover": LegalIRBackendFeature.EXTERNAL_PROOF.value,
    "hammer": LegalIRBackendFeature.EXTERNAL_PROOF.value,
    "prover": LegalIRBackendFeature.EXTERNAL_PROOF.value,
    "decompiler": LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value,
    "round_trip": LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value,
    "decompiler_round_trip": LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value,
    "obligation": LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    "obligations": LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    "obligation_preservation": LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    "proof_obligation": LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    "proof_obligations": LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
    "provenance": LegalIRBackendFeature.PROVENANCE.value,
    "source_map": LegalIRBackendFeature.PROVENANCE.value,
    "exception": LegalIRBackendFeature.EXCEPTION_SCOPE.value,
    "exceptions": LegalIRBackendFeature.EXCEPTION_SCOPE.value,
    "exception_scope": LegalIRBackendFeature.EXCEPTION_SCOPE.value,
    "counterexample": LegalIRBackendFeature.COUNTEREXAMPLE.value,
    "counterexamples": LegalIRBackendFeature.COUNTEREXAMPLE.value,
    "cex": LegalIRBackendFeature.COUNTEREXAMPLE.value,
}


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _unique_text(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item)))


def _canonical_token(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")
    return text


def canonical_legal_ir_backend_target(value: Any) -> str:
    """Return the canonical backend target name for a user or tool value."""

    token = _canonical_token(value)
    if token in _BACKEND_ALIASES:
        return _BACKEND_ALIASES[token]
    if token in DEFAULT_LEGAL_IR_BACKEND_TARGETS:
        return token
    raise ValueError(f"unknown LegalIR backend target: {value!r}")


def canonical_legal_ir_backend_feature(value: Any) -> str:
    """Return the canonical backend feature name for a user or tool value."""

    token = _canonical_token(value)
    if token in _FEATURE_ALIASES:
        return _FEATURE_ALIASES[token]
    if token in DEFAULT_LEGAL_IR_BACKEND_FEATURES:
        return token
    raise ValueError(f"unknown LegalIR backend feature: {value!r}")


@dataclass(frozen=True, slots=True)
class LegalIRBackendUnsupportedDiagnostic:
    """Typed unsupported-feature declaration emitted by a backend."""

    backend: str
    feature: str
    reason_code: str
    message: str = ""
    obligation_ids: tuple[str, ...] = ()
    severity: str = LegalIRBackendDiagnosticSeverity.WARNING.value
    diagnostic_type: str = (
        LegalIRBackendConformanceDiagnosticType.UNSUPPORTED_FEATURE.value
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend", canonical_legal_ir_backend_target(self.backend)
        )
        object.__setattr__(
            self, "feature", canonical_legal_ir_backend_feature(self.feature)
        )
        object.__setattr__(
            self,
            "obligation_ids",
            _unique_text(tuple(self.obligation_ids)),
        )
        object.__setattr__(
            self,
            "severity",
            _canonical_token(self.severity)
            or LegalIRBackendDiagnosticSeverity.WARNING.value,
        )
        object.__setattr__(
            self,
            "diagnostic_type",
            _canonical_token(self.diagnostic_type)
            or LegalIRBackendConformanceDiagnosticType.UNSUPPORTED_FEATURE.value,
        )

    @property
    def typed(self) -> bool:
        return (
            self.diagnostic_type
            == LegalIRBackendConformanceDiagnosticType.UNSUPPORTED_FEATURE.value
        )

    @property
    def valid(self) -> bool:
        return bool(self.typed and self.backend and self.feature and self.reason_code)

    def applies_to(self, feature: str, obligation_id: str = "") -> bool:
        normalized_feature = canonical_legal_ir_backend_feature(feature)
        if normalized_feature != self.feature:
            return False
        if not obligation_id or not self.obligation_ids:
            return True
        return obligation_id in self.obligation_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "diagnostic_type": self.diagnostic_type,
            "feature": self.feature,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "obligation_ids": list(self.obligation_ids),
            "reason_code": self.reason_code,
            "severity": self.severity,
            "typed": self.typed,
            "valid": self.valid,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "LegalIRBackendUnsupportedDiagnostic":
        feature = (
            data.get("feature")
            or data.get("backend_feature")
            or data.get("unsupported_feature")
            or ""
        )
        reason = (
            data.get("reason_code")
            or data.get("code")
            or data.get("reason")
            or data.get("unsupported_reason")
            or ""
        )
        obligation_ids = data.get("obligation_ids")
        if obligation_ids is None and data.get("obligation_id"):
            obligation_ids = (data.get("obligation_id"),)
        return cls(
            backend=str(data.get("backend") or data.get("target") or ""),
            feature=str(feature),
            reason_code=str(reason),
            message=str(data.get("message") or ""),
            obligation_ids=tuple(str(item) for item in _sequence(obligation_ids)),
            severity=str(
                data.get("severity") or LegalIRBackendDiagnosticSeverity.WARNING.value
            ),
            diagnostic_type=str(
                data.get("diagnostic_type")
                or data.get("type")
                or LegalIRBackendConformanceDiagnosticType.UNSUPPORTED_FEATURE.value
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class LegalIRBackendConformanceDiagnostic:
    """One deterministic conformance finding."""

    code: str
    message: str
    severity: str = LegalIRBackendDiagnosticSeverity.ERROR.value
    backend: str = ""
    peer_backend: str = ""
    feature: str = ""
    obligation_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> bool:
        return self.severity == LegalIRBackendDiagnosticSeverity.ERROR.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "code": self.code,
            "feature": self.feature,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "obligation_id": self.obligation_id,
            "peer_backend": self.peer_backend,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class LegalIRBackendProjection:
    """Normalized semantic projection emitted by one backend target."""

    backend: str
    semantics: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    emitted_obligation_ids: tuple[str, ...] = ()
    supported_features: tuple[str, ...] = ()
    emitted_features: tuple[str, ...] = ()
    unsupported_diagnostics: tuple[LegalIRBackendUnsupportedDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        backend = canonical_legal_ir_backend_target(self.backend)
        object.__setattr__(self, "backend", backend)

        supported = self.supported_features or DEFAULT_LEGAL_IR_BACKEND_CAPABILITIES.get(
            backend, ()
        )
        object.__setattr__(
            self,
            "supported_features",
            tuple(canonical_legal_ir_backend_feature(item) for item in supported),
        )

        semantics: dict[str, tuple[str, ...]] = {}
        for raw_feature, raw_values in dict(self.semantics or {}).items():
            feature = canonical_legal_ir_backend_feature(raw_feature)
            semantics[feature] = _unique_text(
                tuple(_canonical_signature(value) for value in _sequence(raw_values))
            )
        object.__setattr__(self, "semantics", dict(sorted(semantics.items())))

        emitted = set(
            canonical_legal_ir_backend_feature(item) for item in self.emitted_features
        )
        emitted.update(feature for feature, values in semantics.items() if values)
        if self.emitted_obligation_ids:
            emitted.add(LegalIRBackendFeature.OBLIGATION_PRESERVATION.value)
        object.__setattr__(self, "emitted_features", tuple(sorted(emitted)))
        object.__setattr__(
            self,
            "emitted_obligation_ids",
            tuple(sorted(_unique_text(tuple(self.emitted_obligation_ids)))),
        )

        diagnostics: list[LegalIRBackendUnsupportedDiagnostic] = []
        for item in self.unsupported_diagnostics:
            diagnostic = (
                item
                if isinstance(item, LegalIRBackendUnsupportedDiagnostic)
                else LegalIRBackendUnsupportedDiagnostic.from_dict(_mapping(item))
            )
            if diagnostic.backend != backend:
                diagnostic = LegalIRBackendUnsupportedDiagnostic(
                    backend=backend,
                    feature=diagnostic.feature,
                    reason_code=diagnostic.reason_code,
                    message=diagnostic.message,
                    obligation_ids=diagnostic.obligation_ids,
                    severity=diagnostic.severity,
                    diagnostic_type=diagnostic.diagnostic_type,
                    metadata=diagnostic.metadata,
                )
            diagnostics.append(diagnostic)
        object.__setattr__(self, "unsupported_diagnostics", tuple(diagnostics))

    def supports(self, feature: str) -> bool:
        return canonical_legal_ir_backend_feature(feature) in self.supported_features

    def emits(self, feature: str) -> bool:
        normalized = canonical_legal_ir_backend_feature(feature)
        return normalized in self.emitted_features or bool(self.semantics.get(normalized))

    def typed_unsupported(
        self, feature: str, obligation_id: str = ""
    ) -> LegalIRBackendUnsupportedDiagnostic | None:
        for diagnostic in self.unsupported_diagnostics:
            if diagnostic.valid and diagnostic.applies_to(feature, obligation_id):
                return diagnostic
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "emitted_features": list(self.emitted_features),
            "emitted_obligation_ids": list(self.emitted_obligation_ids),
            "metadata": _json_ready(self.metadata),
            "semantics": {
                feature: list(values) for feature, values in self.semantics.items()
            },
            "supported_features": list(self.supported_features),
            "unsupported_diagnostics": [
                diagnostic.to_dict() for diagnostic in self.unsupported_diagnostics
            ],
        }


@dataclass(frozen=True, slots=True)
class LegalIRBackendFeatureCoverage:
    """Coverage row for one backend feature."""

    feature: str
    required: bool
    supporting_backends: tuple[str, ...] = ()
    emitted_backends: tuple[str, ...] = ()
    unsupported_backends: tuple[str, ...] = ()
    silent_drop_backends: tuple[str, ...] = ()
    mismatch_backend_pairs: tuple[tuple[str, str], ...] = ()
    obligation_ids: tuple[str, ...] = ()
    missing_obligation_ids_by_backend: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    @property
    def covered(self) -> bool:
        return bool(self.emitted_backends)

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered": self.covered,
            "emitted_backend_count": len(self.emitted_backends),
            "emitted_backends": list(self.emitted_backends),
            "feature": self.feature,
            "mismatch_backend_pairs": [list(pair) for pair in self.mismatch_backend_pairs],
            "missing_obligation_ids_by_backend": {
                backend: list(ids)
                for backend, ids in sorted(self.missing_obligation_ids_by_backend.items())
            },
            "obligation_ids": list(self.obligation_ids),
            "required": self.required,
            "silent_drop_backends": list(self.silent_drop_backends),
            "supporting_backend_count": len(self.supporting_backends),
            "supporting_backends": list(self.supporting_backends),
            "unsupported_backends": list(self.unsupported_backends),
        }


@dataclass(frozen=True, slots=True)
class LegalIRBackendConformanceConfig:
    """Policy knobs for backend conformance validation."""

    required_backends: tuple[str, ...] = DEFAULT_LEGAL_IR_BACKEND_TARGETS
    required_features: tuple[str, ...] = DEFAULT_LEGAL_IR_BACKEND_FEATURES
    min_supporting_backends: int = 1
    require_typed_unsupported: bool = True
    require_projection_for_supported_feature: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_backends",
            tuple(canonical_legal_ir_backend_target(item) for item in self.required_backends),
        )
        object.__setattr__(
            self,
            "required_features",
            tuple(canonical_legal_ir_backend_feature(item) for item in self.required_features),
        )
        minimum = int(self.min_supporting_backends)
        if minimum < 0:
            raise ValueError("min_supporting_backends must be non-negative")
        object.__setattr__(self, "min_supporting_backends", minimum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_supporting_backends": self.min_supporting_backends,
            "require_projection_for_supported_feature": self.require_projection_for_supported_feature,
            "require_typed_unsupported": self.require_typed_unsupported,
            "required_backends": list(self.required_backends),
            "required_features": list(self.required_features),
        }


@dataclass(frozen=True, slots=True)
class LegalIRBackendConformanceReport:
    """Promotion-facing conformance report across backend projections."""

    projections: Mapping[str, LegalIRBackendProjection]
    coverage_by_feature: Mapping[str, LegalIRBackendFeatureCoverage]
    diagnostics: tuple[LegalIRBackendConformanceDiagnostic, ...]
    block_reasons: tuple[str, ...]
    gate_id: str
    config: LegalIRBackendConformanceConfig = field(
        default_factory=LegalIRBackendConformanceConfig
    )
    schema_version: str = LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION

    @property
    def promotion_allowed(self) -> bool:
        return not self.block_reasons

    @property
    def backend_count(self) -> int:
        return len(self.projections)

    @property
    def covered_feature_count(self) -> int:
        return sum(1 for item in self.coverage_by_feature.values() if item.covered)

    @property
    def required_feature_count(self) -> int:
        return sum(1 for item in self.coverage_by_feature.values() if item.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_count": self.backend_count,
            "block_reasons": list(self.block_reasons),
            "config": self.config.to_dict(),
            "covered_feature_count": self.covered_feature_count,
            "coverage_by_feature": {
                feature: coverage.to_dict()
                for feature, coverage in self.coverage_by_feature.items()
            },
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "gate_id": self.gate_id,
            "hard_promotion_gate": True,
            "promotion_allowed": self.promotion_allowed,
            "projections": {
                backend: projection.to_dict()
                for backend, projection in self.projections.items()
            },
            "required_feature_count": self.required_feature_count,
            "schema_version": self.schema_version,
            "status": "accepted" if self.promotion_allowed else "blocked",
        }


def legal_ir_backend_capabilities_manifest() -> dict[str, Any]:
    """Return the stable feature matrix used by default conformance checks."""

    return {
        "backend_targets": list(DEFAULT_LEGAL_IR_BACKEND_TARGETS),
        "capabilities": {
            backend: list(features)
            for backend, features in DEFAULT_LEGAL_IR_BACKEND_CAPABILITIES.items()
        },
        "features": list(DEFAULT_LEGAL_IR_BACKEND_FEATURES),
        "schema_version": LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION,
    }


def legal_ir_backend_projection(
    backend: str,
    payload: Any,
    *,
    supported_features: Optional[Sequence[str]] = None,
    unsupported_diagnostics: Sequence[LegalIRBackendUnsupportedDiagnostic | Mapping[str, Any]] = (),
    metadata: Optional[Mapping[str, Any]] = None,
) -> LegalIRBackendProjection:
    """Build a normalized projection from a backend payload or serialized record."""

    if isinstance(payload, LegalIRBackendProjection):
        return payload

    source = _mapping(payload)
    if source.get("backend") and source.get("semantics") is not None:
        backend = str(source.get("backend") or backend)
        supported_features = supported_features or tuple(
            str(item) for item in _sequence(source.get("supported_features"))
        )
        unsupported_diagnostics = (
            *tuple(unsupported_diagnostics),
            *tuple(
                _mapping(item)
                for item in _sequence(source.get("unsupported_diagnostics"))
                if _mapping(item)
            ),
        )
        metadata = metadata or _mapping(source.get("metadata"))

    normalized_backend = canonical_legal_ir_backend_target(backend)
    semantics = _extract_semantic_projection(source or payload)
    emitted_obligation_ids = _extract_obligation_ids(source or payload)
    if emitted_obligation_ids:
        existing = set(semantics.get(LegalIRBackendFeature.OBLIGATION_PRESERVATION.value, ()))
        existing.update(emitted_obligation_ids)
        semantics[LegalIRBackendFeature.OBLIGATION_PRESERVATION.value] = tuple(sorted(existing))

    diagnostics = list(unsupported_diagnostics)
    diagnostics.extend(_extract_unsupported_diagnostics(normalized_backend, source or payload))

    return LegalIRBackendProjection(
        backend=normalized_backend,
        semantics=semantics,
        emitted_obligation_ids=emitted_obligation_ids,
        supported_features=tuple(supported_features or ()),
        emitted_features=tuple(semantics),
        unsupported_diagnostics=tuple(diagnostics),
        metadata=dict(metadata or {}),
    )


def validate_legal_ir_backend_conformance(
    projections: Mapping[str, Any] | Sequence[Any],
    *,
    obligations: Optional[Sequence[Any]] = None,
    config: Optional[LegalIRBackendConformanceConfig] = None,
) -> LegalIRBackendConformanceReport:
    """Validate shared semantics and obligation preservation across backends."""

    policy = config or LegalIRBackendConformanceConfig()
    projection_map, duplicate_diagnostics = _normalize_projection_map(projections)
    diagnostics: list[LegalIRBackendConformanceDiagnostic] = list(duplicate_diagnostics)

    for backend in policy.required_backends:
        if backend not in projection_map:
            diagnostics.append(
                LegalIRBackendConformanceDiagnostic(
                    code=LegalIRBackendConformanceDiagnosticType.MISSING_BACKEND.value,
                    backend=backend,
                    message=f"Required backend {backend!r} did not emit a conformance projection.",
                )
            )

    for projection in projection_map.values():
        for unsupported in projection.unsupported_diagnostics:
            if not unsupported.valid:
                diagnostics.append(
                    LegalIRBackendConformanceDiagnostic(
                        code=LegalIRBackendConformanceDiagnosticType.INVALID_UNSUPPORTED_DIAGNOSTIC.value,
                        backend=projection.backend,
                        feature=unsupported.feature,
                        message=(
                            "Unsupported backend diagnostic is not typed or is missing "
                            "a reason code."
                        ),
                        metadata=unsupported.to_dict(),
                    )
                )

    obligations_by_feature = _obligations_by_feature(obligations or ())
    all_features = set(policy.required_features)
    all_features.update(obligations_by_feature)
    for projection in projection_map.values():
        all_features.update(projection.supported_features)
        all_features.update(projection.emitted_features)
        all_features.update(projection.semantics)
        all_features.update(
            diagnostic.feature for diagnostic in projection.unsupported_diagnostics
        )

    coverage: dict[str, LegalIRBackendFeatureCoverage] = {}
    for feature in sorted(all_features):
        feature_obligation_ids = obligations_by_feature.get(feature, ())
        supporting_backends: list[str] = []
        emitted_backends: list[str] = []
        unsupported_backends: list[str] = []
        silent_drop_backends: list[str] = []
        missing_by_backend: dict[str, tuple[str, ...]] = {}

        for backend, projection in sorted(projection_map.items()):
            supports = projection.supports(feature)
            emits = projection.emits(feature)
            unsupported = projection.typed_unsupported(feature)
            if supports:
                supporting_backends.append(backend)
            if emits:
                emitted_backends.append(backend)
            if unsupported is not None:
                unsupported_backends.append(backend)

            if (
                supports
                and policy.require_projection_for_supported_feature
                and not emits
                and unsupported is None
            ):
                diagnostics.append(
                    LegalIRBackendConformanceDiagnostic(
                        code=LegalIRBackendConformanceDiagnosticType.SUPPORTED_FEATURE_WITHOUT_PROJECTION.value,
                        backend=backend,
                        feature=feature,
                        message=(
                            f"Backend {backend!r} declares support for feature "
                            f"{feature!r} but emitted no semantic projection and no "
                            "typed unsupported diagnostic."
                        ),
                    )
                )

            if not supports or not feature_obligation_ids:
                continue
            missing_ids = tuple(
                obligation_id
                for obligation_id in feature_obligation_ids
                if obligation_id not in projection.emitted_obligation_ids
                and projection.typed_unsupported(feature, obligation_id) is None
                and projection.typed_unsupported(
                    LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
                    obligation_id,
                )
                is None
            )
            if missing_ids:
                silent_drop_backends.append(backend)
                missing_by_backend[backend] = missing_ids
                for obligation_id in missing_ids:
                    diagnostics.append(
                        LegalIRBackendConformanceDiagnostic(
                            code=LegalIRBackendConformanceDiagnosticType.SILENT_OBLIGATION_DROP.value,
                            backend=backend,
                            feature=feature,
                            obligation_id=obligation_id,
                            message=(
                                f"Backend {backend!r} silently dropped obligation "
                                f"{obligation_id!r} for feature {feature!r}."
                            ),
                        )
                    )

        mismatch_pairs = _semantic_mismatch_pairs(feature, projection_map)
        for left, right in mismatch_pairs:
            diagnostics.append(
                LegalIRBackendConformanceDiagnostic(
                    code=LegalIRBackendConformanceDiagnosticType.SHARED_SEMANTICS_MISMATCH.value,
                    backend=left,
                    peer_backend=right,
                    feature=feature,
                    message=(
                        f"Backends {left!r} and {right!r} disagree on shared "
                        f"semantic feature {feature!r}."
                    ),
                    metadata={
                        "left_signature_count": len(
                            projection_map[left].semantics.get(feature, ())
                        ),
                        "right_signature_count": len(
                            projection_map[right].semantics.get(feature, ())
                        ),
                    },
                )
            )

        coverage[feature] = LegalIRBackendFeatureCoverage(
            feature=feature,
            required=feature in policy.required_features,
            supporting_backends=tuple(sorted(supporting_backends)),
            emitted_backends=tuple(sorted(emitted_backends)),
            unsupported_backends=tuple(sorted(unsupported_backends)),
            silent_drop_backends=tuple(sorted(set(silent_drop_backends))),
            mismatch_backend_pairs=tuple(mismatch_pairs),
            obligation_ids=feature_obligation_ids,
            missing_obligation_ids_by_backend=missing_by_backend,
        )

    for feature in policy.required_features:
        feature_coverage = coverage.get(feature)
        emitted_count = len(feature_coverage.emitted_backends) if feature_coverage else 0
        if emitted_count < policy.min_supporting_backends:
            diagnostics.append(
                LegalIRBackendConformanceDiagnostic(
                    code=LegalIRBackendConformanceDiagnosticType.REQUIRED_FEATURE_WITHOUT_COVERAGE.value,
                    feature=feature,
                    message=(
                        f"Required feature {feature!r} has {emitted_count} emitting "
                        f"backend(s), below the configured minimum "
                        f"{policy.min_supporting_backends}."
                    ),
                )
            )

    block_reasons = _block_reasons(diagnostics)
    descriptor = {
        "block_reasons": block_reasons,
        "coverage": {feature: item.to_dict() for feature, item in coverage.items()},
        "projections": {key: value.to_dict() for key, value in projection_map.items()},
    }
    return LegalIRBackendConformanceReport(
        projections=dict(sorted(projection_map.items())),
        coverage_by_feature=dict(sorted(coverage.items())),
        diagnostics=tuple(diagnostics),
        block_reasons=tuple(block_reasons),
        gate_id="lir-backend-conformance-" + _stable_hash(descriptor)[:24],
        config=policy,
    )


def legal_ir_backend_conformance_gate(
    projections: Mapping[str, Any] | Sequence[Any],
    *,
    obligations: Optional[Sequence[Any]] = None,
    config: Optional[LegalIRBackendConformanceConfig] = None,
) -> dict[str, Any]:
    """Dictionary API for promotion callers."""

    return validate_legal_ir_backend_conformance(
        projections,
        obligations=obligations,
        config=config,
    ).to_dict()


def _normalize_projection_map(
    projections: Mapping[str, Any] | Sequence[Any],
) -> tuple[dict[str, LegalIRBackendProjection], tuple[LegalIRBackendConformanceDiagnostic, ...]]:
    normalized: dict[str, LegalIRBackendProjection] = {}
    diagnostics: list[LegalIRBackendConformanceDiagnostic] = []

    if isinstance(projections, Mapping):
        iterator = projections.items()
    else:
        iterator = []
        rows: list[tuple[str, Any]] = []
        for item in _sequence(projections):
            if isinstance(item, LegalIRBackendProjection):
                rows.append((item.backend, item))
            else:
                data = _mapping(item)
                rows.append((str(data.get("backend") or data.get("target") or ""), item))
        iterator = rows

    for backend, payload in iterator:
        try:
            projection = legal_ir_backend_projection(str(backend), payload)
        except ValueError as exc:
            diagnostics.append(
                LegalIRBackendConformanceDiagnostic(
                    code="invalid_backend_projection",
                    backend=str(backend or ""),
                    message=str(exc),
                )
            )
            continue
        if projection.backend in normalized:
            diagnostics.append(
                LegalIRBackendConformanceDiagnostic(
                    code=LegalIRBackendConformanceDiagnosticType.DUPLICATE_BACKEND_PROJECTION.value,
                    backend=projection.backend,
                    message=f"Backend {projection.backend!r} emitted multiple projections.",
                )
            )
        normalized[projection.backend] = projection
    return normalized, tuple(diagnostics)


def _semantic_mismatch_pairs(
    feature: str,
    projections: Mapping[str, LegalIRBackendProjection],
) -> tuple[tuple[str, str], ...]:
    emitted = [
        (backend, projection.semantics.get(feature, ()))
        for backend, projection in sorted(projections.items())
        if projection.semantics.get(feature)
    ]
    pairs: list[tuple[str, str]] = []
    for index, (left_backend, left_values) in enumerate(emitted):
        for right_backend, right_values in emitted[index + 1 :]:
            left_set = set(left_values)
            right_set = set(right_values)
            left_only = {
                value
                for value in left_set - right_set
                if projections[right_backend].typed_unsupported(feature, value) is None
                and projections[right_backend].typed_unsupported(
                    LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
                    value,
                )
                is None
            }
            right_only = {
                value
                for value in right_set - left_set
                if projections[left_backend].typed_unsupported(feature, value) is None
                and projections[left_backend].typed_unsupported(
                    LegalIRBackendFeature.OBLIGATION_PRESERVATION.value,
                    value,
                )
                is None
            }
            if left_only or right_only:
                pairs.append((left_backend, right_backend))
    return tuple(pairs)


def _block_reasons(
    diagnostics: Sequence[LegalIRBackendConformanceDiagnostic],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for diagnostic in diagnostics:
        if not diagnostic.error:
            continue
        parts = [diagnostic.code]
        if diagnostic.backend:
            parts.append(diagnostic.backend)
        if diagnostic.peer_backend:
            parts.append(diagnostic.peer_backend)
        if diagnostic.feature:
            parts.append(diagnostic.feature)
        if diagnostic.obligation_id:
            parts.append(diagnostic.obligation_id)
        reasons.append(":".join(parts))
    return tuple(dict.fromkeys(reasons))


def _obligations_by_feature(obligations: Sequence[Any]) -> dict[str, tuple[str, ...]]:
    by_feature: dict[str, list[str]] = {}
    all_ids: list[str] = []
    for obligation in obligations:
        obligation_id = _obligation_id(obligation)
        if not obligation_id:
            continue
        all_ids.append(obligation_id)
        feature = _feature_for_obligation(obligation)
        by_feature.setdefault(feature, []).append(obligation_id)
    if all_ids:
        by_feature.setdefault(
            LegalIRBackendFeature.OBLIGATION_PRESERVATION.value, []
        ).extend(all_ids)
    return {
        feature: tuple(sorted(_unique_text(ids)))
        for feature, ids in sorted(by_feature.items())
    }


def _obligation_id(obligation: Any) -> str:
    data = _mapping(obligation)
    return str(
        getattr(obligation, "obligation_id", "")
        or data.get("obligation_id")
        or data.get("id")
        or ""
    )


def _feature_for_obligation(obligation: Any) -> str:
    data = _mapping(obligation)
    metadata = _mapping(getattr(obligation, "metadata", None) or data.get("metadata"))
    for key in ("backend_feature", "conformance_feature", "feature"):
        if metadata.get(key):
            return canonical_legal_ir_backend_feature(metadata[key])

    text = " ".join(
        str(value or "").lower()
        for value in (
            getattr(obligation, "kind", ""),
            getattr(obligation, "legal_ir_view", ""),
            getattr(obligation, "logic_family", ""),
            data.get("kind", ""),
            data.get("legal_ir_view", ""),
            data.get("logic_family", ""),
            metadata.get("coverage_scope", ""),
            metadata.get("obligation_family", ""),
            metadata.get("contract_view", ""),
            metadata.get("required_field", ""),
        )
    )
    if "provenance" in text or "source_map" in text:
        return LegalIRBackendFeature.PROVENANCE.value
    if "round_trip" in text or "decompiler" in text:
        return LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value
    if "counterexample" in text or "cex" in text:
        return LegalIRBackendFeature.COUNTEREXAMPLE.value
    if "graph" in text or "knowledge_graph" in text or " kg" in f" {text}":
        return LegalIRBackendFeature.KNOWLEDGE_GRAPH.value
    if "event" in text or "cec" in text or "lifecycle" in text:
        return LegalIRBackendFeature.CEC.value
    if "tdfol" in text or "temporal" in text or "deadline" in text:
        return LegalIRBackendFeature.TDFOL.value
    if "exception" in text:
        return LegalIRBackendFeature.EXCEPTION_SCOPE.value
    if "deontic" in text or "polarity" in text or "modal" in text:
        return LegalIRBackendFeature.DEONTIC.value
    if "external" in text or "prover" in text or "smt" in text or "hammer" in text:
        return LegalIRBackendFeature.EXTERNAL_PROOF.value
    if "frame" in text:
        return LegalIRBackendFeature.FRAME_LOGIC.value
    return LegalIRBackendFeature.OBLIGATION_PRESERVATION.value


def _extract_semantic_projection(payload: Any) -> dict[str, tuple[str, ...]]:
    source = _mapping(payload)
    semantics: dict[str, set[str]] = {}

    for key in (
        "semantics",
        "semantic_projection",
        "semantic_features",
        "feature_signatures",
    ):
        nested = source.get(key)
        if isinstance(nested, Mapping):
            _merge_semantic_mapping(semantics, nested)

    features = source.get("features")
    if isinstance(features, Mapping):
        _merge_semantic_mapping(semantics, features)
    elif features is not None:
        for item in _sequence(features):
            try:
                feature = canonical_legal_ir_backend_feature(item)
            except ValueError:
                continue
            semantics.setdefault(feature, set()).add(f"feature:{feature}")

    _extract_structural_semantics(semantics, source)
    return {
        feature: tuple(sorted(values))
        for feature, values in sorted(semantics.items())
        if values
    }


def _merge_semantic_mapping(
    semantics: dict[str, set[str]],
    nested: Mapping[str, Any],
) -> None:
    for raw_feature, raw_values in nested.items():
        try:
            feature = canonical_legal_ir_backend_feature(raw_feature)
        except ValueError:
            continue
        values = _semantic_values(raw_values)
        if not values:
            values = (f"feature:{feature}",)
        semantics.setdefault(feature, set()).update(values)


def _semantic_values(value: Any) -> tuple[str, ...]:
    data = _mapping(value)
    if data:
        for key in ("signatures", "semantic_signatures", "values", "ids"):
            if key in data:
                return tuple(_canonical_signature(item) for item in _sequence(data[key]))
        if "proof_obligation_ids" in data:
            return tuple(
                _canonical_signature(item) for item in _sequence(data["proof_obligation_ids"])
            )
        return (_canonical_signature(data),)
    return tuple(_canonical_signature(item) for item in _sequence(value))


def _extract_structural_semantics(
    semantics: dict[str, set[str]],
    source: Mapping[str, Any],
) -> None:
    formulas = _sequence(source.get("formulas") or source.get("rules"))
    for formula in formulas:
        data = _mapping(formula)
        if not data:
            continue
        operator = _mapping(data.get("operator"))
        predicate = _mapping(data.get("predicate"))
        modality = (
            data.get("modality")
            or data.get("norm_type")
            or operator.get("symbol")
            or operator.get("label")
            or operator.get("family")
            or ""
        )
        actor = data.get("subject") or data.get("actor") or data.get("agent") or ""
        action = data.get("action") or predicate.get("name") or data.get("predicate") or ""
        condition = data.get("condition") or data.get("conditions") or ""
        if modality or action:
            semantics.setdefault(LegalIRBackendFeature.DEONTIC.value, set()).add(
                "deontic:"
                + _canonical_signature(
                    {
                        "action": action,
                        "actor": actor,
                        "condition": condition,
                        "modality": modality,
                    }
                )
            )
        if data.get("exceptions"):
            semantics.setdefault(LegalIRBackendFeature.EXCEPTION_SCOPE.value, set()).add(
                _canonical_signature(data.get("exceptions"))
            )
        if _contains_temporal_signal(data):
            semantics.setdefault(LegalIRBackendFeature.TDFOL.value, set()).add(
                _canonical_signature(data.get("temporal_window") or condition or data)
            )

    frame_logic = _mapping(source.get("frame_logic"))
    for triple in _sequence(frame_logic.get("triples")):
        semantics.setdefault(LegalIRBackendFeature.FRAME_LOGIC.value, set()).add(
            _triple_signature(triple)
        )

    graph = _mapping(source.get("graph") or source.get("knowledge_graph"))
    for triple in _sequence(graph.get("triples") or graph.get("kg_triples")):
        semantics.setdefault(LegalIRBackendFeature.KNOWLEDGE_GRAPH.value, set()).add(
            _triple_signature(triple)
        )
    for edge in _sequence(graph.get("edges") or graph.get("relationships")):
        semantics.setdefault(LegalIRBackendFeature.KNOWLEDGE_GRAPH.value, set()).add(
            _edge_signature(edge)
        )

    for key in ("events", "event_calculus", "cec"):
        if key in source:
            semantics.setdefault(LegalIRBackendFeature.CEC.value, set()).add(
                _canonical_signature(source[key])
            )

    for key in ("counterexamples", "counterexample", "cex"):
        if key in source:
            semantics.setdefault(LegalIRBackendFeature.COUNTEREXAMPLE.value, set()).add(
                _canonical_signature(source[key])
            )

    round_trip = _mapping(source.get("round_trip") or source.get("decompiler_round_trip"))
    if round_trip:
        semantics.setdefault(LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value, set()).add(
            _canonical_signature(round_trip)
        )

    for key in ("proof_results", "external_proof", "external_prover"):
        if key in source:
            semantics.setdefault(LegalIRBackendFeature.EXTERNAL_PROOF.value, set()).add(
                _canonical_signature(source[key])
            )


def _extract_obligation_ids(payload: Any) -> tuple[str, ...]:
    source = _mapping(payload)
    ids: list[str] = []
    for key in (
        "proof_obligation_ids",
        "obligation_ids",
        "emitted_obligation_ids",
        "obligations",
        "proof_obligations",
    ):
        if key not in source:
            continue
        for item in _sequence(source[key]):
            if isinstance(item, (str, int)):
                ids.append(str(item))
            else:
                obligation_id = _obligation_id(item)
                if obligation_id:
                    ids.append(obligation_id)
    return tuple(sorted(_unique_text(ids)))


def _extract_unsupported_diagnostics(
    backend: str,
    payload: Any,
) -> tuple[LegalIRBackendUnsupportedDiagnostic, ...]:
    source = _mapping(payload)
    diagnostics: list[LegalIRBackendUnsupportedDiagnostic] = []
    for key in ("unsupported_diagnostics", "unsupported_features", "diagnostics"):
        for item in _sequence(source.get(key)):
            data = _mapping(item)
            if not data:
                try:
                    feature = canonical_legal_ir_backend_feature(item)
                except ValueError:
                    continue
                data = {
                    "backend": backend,
                    "feature": feature,
                    "reason_code": "declared_unsupported",
                }
            diagnostic_type = _canonical_token(
                data.get("diagnostic_type") or data.get("type") or ""
            )
            if key == "diagnostics" and diagnostic_type not in {
                LegalIRBackendConformanceDiagnosticType.UNSUPPORTED_FEATURE.value,
                "unsupported",
                "unsupported_feature",
            }:
                continue
            data = {**data, "backend": data.get("backend") or backend}
            try:
                diagnostics.append(LegalIRBackendUnsupportedDiagnostic.from_dict(data))
            except ValueError:
                continue
    return tuple(diagnostics)


def _canonical_signature(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text else ""
    if isinstance(value, (int, bool)):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else repr(value)
    return _stable_json(value)


def _triple_signature(value: Any) -> str:
    data = _mapping(value)
    if not data:
        seq = _sequence(value)
        if len(seq) >= 3:
            return "|".join(_canonical_token(item) for item in seq[:3])
        return _canonical_signature(value)
    return "|".join(
        _canonical_token(data.get(key, ""))
        for key in ("subject", "predicate", "object")
    )


def _edge_signature(value: Any) -> str:
    data = _mapping(value)
    if not data:
        return _canonical_signature(value)
    return "|".join(
        _canonical_token(data.get(key, ""))
        for key in ("source", "label", "target")
    )


def _contains_temporal_signal(value: Any) -> bool:
    text = _stable_json(value).lower()
    return bool(
        re.search(r"\b(after|before|deadline|during|until|when|within)\b", text)
    )


__all__ = [
    "DEFAULT_LEGAL_IR_BACKEND_CAPABILITIES",
    "DEFAULT_LEGAL_IR_BACKEND_FEATURES",
    "DEFAULT_LEGAL_IR_BACKEND_TARGETS",
    "LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION",
    "LegalIRBackendConformanceConfig",
    "LegalIRBackendConformanceDiagnostic",
    "LegalIRBackendConformanceDiagnosticType",
    "LegalIRBackendConformanceReport",
    "LegalIRBackendDiagnosticSeverity",
    "LegalIRBackendFeature",
    "LegalIRBackendFeatureCoverage",
    "LegalIRBackendProjection",
    "LegalIRBackendTarget",
    "LegalIRBackendUnsupportedDiagnostic",
    "canonical_legal_ir_backend_feature",
    "canonical_legal_ir_backend_target",
    "legal_ir_backend_capabilities_manifest",
    "legal_ir_backend_conformance_gate",
    "legal_ir_backend_projection",
    "validate_legal_ir_backend_conformance",
]
