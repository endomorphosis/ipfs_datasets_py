"""Bounded teacher distillation for legacy-only autoencoder embedding tails.

The accepted proof-aware autoencoder deliberately does not bulk-copy embedding
rows from the legacy checkpoint: the measured direct transfer reduced
autoencoder cosine.  This module provides the narrower migration path.  It
reads legacy-only embedding rows once, fits an independently bounded low-rank
adapter for each embedding head, and then discards the teacher object.

An adapter is a conventional two-factor matrix ``C @ B``.  ``C`` contains one
coefficient row per eligible semantic key and ``B`` is a shared embedding
basis.  The factors are initialized by deterministic SVD, confidence gated,
norm bounded, and held outside :class:`ModalAutoencoderTrainingState`.  The
student's dense maps are therefore never replaced or extended.  Runtime
influence defaults to exactly zero and can only be enabled after the
multi-seed held-out promotion gate passes.

Sample memory (``decoded_embeddings`` and ``family_logits``), source text,
decoded text, prompts, proof drafts, and arbitrary state fields are not inputs
to this path.  Reports contain aggregate counts and content digests rather
than feature keys or vectors.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np

from .modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    ModalAutoencoderTrainingState,
)


LEGACY_DISTILLATION_SCHEMA_VERSION = (
    "modal-autoencoder-legacy-embedding-distillation-v1"
)
LEGACY_ADAPTER_SCHEMA_VERSION = "modal-autoencoder-bounded-low-rank-adapter-v1"
LEGACY_ADAPTER_BUNDLE_SCHEMA_VERSION = (
    "modal-autoencoder-legacy-adapter-bundle-v1"
)
LEGACY_DISTILLATION_PROMOTION_SCHEMA_VERSION = (
    "modal-autoencoder-legacy-distillation-promotion-v1"
)
DEFAULT_LEGACY_ADAPTER_RANK = 8
DEFAULT_LEGACY_ADAPTER_MAX_ROWS = 8192
DEFAULT_LEGACY_ADAPTER_MAX_COUNT = 13
DEFAULT_LEGACY_ADAPTER_MINIMUM_SEEDS = 3
DEFAULT_LEGACY_ADAPTER_INFLUENCE = 0.0

# This closed list is the complete reusable embedding surface of the current
# architecture.  In particular, decoded_embeddings is intentionally absent.
LEGACY_DISTILLABLE_EMBEDDING_FIELDS = (
    "compiler_quality_embedding_weights",
    "logic_signature_embedding_weights",
    "round_trip_signal_embedding_weights",
    "decompiler_plan_embedding_weights",
    "predicate_argument_embedding_weights",
    "feature_embedding_weights",
    "family_embedding_weights",
    "family_semantic_slot_embedding_weights",
    "family_semantic_slot_legal_ir_view_embedding_weights",
    "family_legal_ir_view_embedding_weights",
    "semantic_slot_embedding_weights",
    "legal_ir_view_embedding_weights",
    "semantic_slot_legal_ir_view_embedding_weights",
)
LEGACY_SAMPLE_MEMORY_FIELDS = frozenset({"decoded_embeddings", "family_logits"})
_FORBIDDEN_TEXT_MARKERS = (
    "decoded_text",
    "decoded-text",
    "source_text",
    "source-text",
    "raw_prompt",
    "raw-prompt",
)
_SOURCE_MEMORY_PREFIX = re.compile(
    r"^(?:raw[-_: ]?(?:source|text)|source[-_: ]?(?:span|text)|"
    r"(?:sample|example)[-_:#]|document[-_:#]?id[-_:#])",
    re.IGNORECASE,
)


class LegacyDistillationError(RuntimeError):
    """Base class for fail-closed legacy distillation errors."""


class DirectBulkEmbeddingTransferError(LegacyDistillationError, ValueError):
    """Raised when a caller requests the known-regressive direct transfer."""


class LegacyDistillationLineageError(LegacyDistillationError, ValueError):
    """Raised when teacher, student, split, or adapter lineage is invalid."""


class LegacyAdapterCapacityError(LegacyDistillationError, OverflowError):
    """Raised before an adapter can exceed a configured hard bound."""


class LegacyDistillationPromotionError(LegacyDistillationError):
    """Raised by the enforcing promotion API when a candidate is unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _finite_float(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _bounded_unit(value: Any, *, name: str) -> float:
    number = _finite_float(value, name=name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _finite_array(value: Any, *, ndim: int, name: str) -> np.ndarray:
    result = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if result.ndim != ndim:
        raise ValueError(f"{name} must be a {ndim}-dimensional array")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result


def _state_binding(state: ModalAutoencoderTrainingState) -> str:
    identity = str(state.state_identity())
    return identity if identity.startswith("sha256:") else f"sha256:{identity}"


def _safe_checkpoint_binding(value: str, fallback: str) -> str:
    binding = str(value or fallback).strip()
    if not binding:
        raise LegacyDistillationLineageError(
            "checkpoint binding must be non-empty"
        )
    return binding


def _key_digest(keys: Iterable[str]) -> str:
    return _digest(sorted(str(key) for key in keys))


def _key_is_source_memory(value: str) -> bool:
    text = str(value).strip()
    if _SOURCE_MEMORY_PREFIX.search(text):
        return True
    words = text.split()
    return (
        len(text.encode("utf-8")) > 2_048
        or len(words) >= 4
        or (len(words) >= 3 and text.endswith((".", ";", "?", "!")))
    )


def _optimizer_digest(value: Mapping[str, Any]) -> str:
    return _digest(value)


@dataclass(frozen=True, slots=True)
class LegacyDistillationLineage:
    """Immutable bindings for one teacher/student/split/seed experiment."""

    teacher_checkpoint_sha256: str
    student_checkpoint_sha256: str
    split_id: str
    seed: int
    teacher_architecture: str = MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
    student_architecture: str = MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    inventory_sha256: str = ""
    parent_lineage_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "teacher_checkpoint_sha256",
            "student_checkpoint_sha256",
            "split_id",
        ):
            if not str(getattr(self, name)).strip():
                raise LegacyDistillationLineageError(
                    f"{name} must be non-empty"
                )
        if not str(self.teacher_architecture).strip():
            raise LegacyDistillationLineageError(
                "teacher_architecture must be non-empty"
            )
        if not str(self.student_architecture).strip():
            raise LegacyDistillationLineageError(
                "student_architecture must be non-empty"
            )

    @property
    def lineage_id(self) -> str:
        return _digest(self.to_dict(include_lineage_id=False))

    @property
    def teacher(self) -> str:
        return self.teacher_checkpoint_sha256

    @property
    def student(self) -> str:
        return self.student_checkpoint_sha256

    @property
    def split(self) -> str:
        return self.split_id

    def to_dict(self, *, include_lineage_id: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "inventory_sha256": self.inventory_sha256,
            "parent_lineage_id": self.parent_lineage_id,
            "seed": int(self.seed),
            "split_id": self.split_id,
            "student_architecture": self.student_architecture,
            "student_checkpoint_sha256": self.student_checkpoint_sha256,
            "teacher_architecture": self.teacher_architecture,
            "teacher_checkpoint_sha256": self.teacher_checkpoint_sha256,
        }
        if include_lineage_id:
            payload["lineage_id"] = self.lineage_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyDistillationLineage":
        return cls(
            teacher_checkpoint_sha256=str(
                value.get("teacher_checkpoint_sha256") or value.get("teacher") or ""
            ),
            student_checkpoint_sha256=str(
                value.get("student_checkpoint_sha256") or value.get("student") or ""
            ),
            split_id=str(value.get("split_id") or value.get("split") or ""),
            seed=int(value.get("seed", 0)),
            teacher_architecture=str(
                value.get("teacher_architecture")
                or MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION
            ),
            student_architecture=str(
                value.get("student_architecture")
                or MODAL_AUTOENCODER_ARCHITECTURE_VERSION
            ),
            inventory_sha256=str(value.get("inventory_sha256") or ""),
            parent_lineage_id=str(value.get("parent_lineage_id") or ""),
        )


@dataclass(frozen=True, slots=True)
class LegacyDistillationConfig:
    """Hard bounds and confidence policy for adapter fitting."""

    rank: int = DEFAULT_LEGACY_ADAPTER_RANK
    max_rows_per_adapter: int = DEFAULT_LEGACY_ADAPTER_MAX_ROWS
    max_adapters: int = DEFAULT_LEGACY_ADAPTER_MAX_COUNT
    minimum_confidence: float = 0.0
    confidence_threshold: Optional[float] = None
    default_confidence: float = 1.0
    influence: float = DEFAULT_LEGACY_ADAPTER_INFLUENCE
    max_adjustment_norm: float = 1.0
    gradient_clip_norm: float = 1.0
    source_field_allowlist: tuple[str, ...] = ()
    direct_bulk_embedding_replacement: bool = False
    direct_bulk_transfer_allowed: bool = False
    scale_by_confidence: bool = True
    seed: int = 0

    def __post_init__(self) -> None:
        if int(self.rank) < 0:
            raise ValueError("rank must be non-negative")
        if int(self.max_rows_per_adapter) < 0:
            raise ValueError("max_rows_per_adapter must be non-negative")
        if int(self.max_adapters) < 0:
            raise ValueError("max_adapters must be non-negative")
        if self.confidence_threshold is not None:
            threshold = _bounded_unit(
                self.confidence_threshold,
                name="confidence_threshold",
            )
            if (
                float(self.minimum_confidence) != 0.0
                and float(self.minimum_confidence) != threshold
            ):
                raise ValueError(
                    "minimum_confidence and confidence_threshold disagree"
                )
            object.__setattr__(self, "minimum_confidence", threshold)
        _bounded_unit(self.minimum_confidence, name="minimum_confidence")
        _bounded_unit(self.default_confidence, name="default_confidence")
        _bounded_unit(self.influence, name="influence")
        if _finite_float(
            self.max_adjustment_norm, name="max_adjustment_norm"
        ) < 0.0:
            raise ValueError("max_adjustment_norm must be non-negative")
        if _finite_float(self.gradient_clip_norm, name="gradient_clip_norm") <= 0.0:
            raise ValueError("gradient_clip_norm must be positive")
        unknown = set(self.source_field_allowlist) - set(
            LEGACY_DISTILLABLE_EMBEDDING_FIELDS
        )
        if unknown:
            raise ValueError(
                "unknown legacy embedding adapter fields: "
                + ", ".join(sorted(unknown))
            )
        if (
            self.direct_bulk_embedding_replacement
            or self.direct_bulk_transfer_allowed
        ):
            raise DirectBulkEmbeddingTransferError(
                "direct bulk embedding replacement is forbidden because the "
                "measured direct transfer regressed autoencoder cosine"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_confidence": float(self.default_confidence),
            "direct_bulk_embedding_replacement": False,
            "direct_bulk_transfer_allowed": False,
            "gradient_clip_norm": float(self.gradient_clip_norm),
            "influence": float(self.influence),
            "max_adapters": int(self.max_adapters),
            "max_adjustment_norm": float(self.max_adjustment_norm),
            "max_rows_per_adapter": int(self.max_rows_per_adapter),
            "minimum_confidence": float(self.minimum_confidence),
            "confidence_threshold": float(self.minimum_confidence),
            "rank": int(self.rank),
            "scale_by_confidence": bool(self.scale_by_confidence),
            "seed": int(self.seed),
            "source_field_allowlist": list(self.source_field_allowlist),
        }


@dataclass(slots=True)
class BoundedLowRankLegacyAdapter:
    """One independently trainable and confidence-gated embedding adapter."""

    name: str
    keys: tuple[str, ...]
    coefficients: np.ndarray
    basis: np.ndarray
    confidences: np.ndarray
    lineage_id: str
    influence: float = 0.0
    minimum_confidence: float = 0.0
    max_adjustment_norm: float = 1.0
    gradient_clip_norm: float = 1.0
    scale_by_confidence: bool = True
    _optimizer_state: Dict[str, Any] = field(
        default_factory=dict,
        repr=False,
    )
    _key_index: Dict[str, int] = field(
        init=False,
        repr=False,
        default_factory=dict,
    )

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        if self.name not in LEGACY_DISTILLABLE_EMBEDDING_FIELDS:
            raise ValueError(f"unsupported legacy adapter head: {self.name!r}")
        self.keys = tuple(str(key) for key in self.keys)
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("adapter keys must be unique")
        self.coefficients = _finite_array(
            self.coefficients,
            ndim=2,
            name="coefficients",
        )
        self.basis = _finite_array(self.basis, ndim=2, name="basis")
        self.confidences = _finite_array(
            self.confidences,
            ndim=1,
            name="confidences",
        )
        if self.coefficients.shape[0] != len(self.keys):
            raise ValueError("coefficient row count must match keys")
        if self.coefficients.shape[1] != self.basis.shape[0]:
            raise ValueError("coefficient rank must match basis rank")
        if self.confidences.shape != (len(self.keys),):
            raise ValueError("confidence count must match keys")
        if np.any(self.confidences < 0.0) or np.any(self.confidences > 1.0):
            raise ValueError("adapter confidences must be between 0 and 1")
        self.influence = _bounded_unit(self.influence, name="influence")
        self.minimum_confidence = _bounded_unit(
            self.minimum_confidence,
            name="minimum_confidence",
        )
        if _finite_float(
            self.max_adjustment_norm, name="max_adjustment_norm"
        ) < 0.0:
            raise ValueError("max_adjustment_norm must be non-negative")
        if _finite_float(self.gradient_clip_norm, name="gradient_clip_norm") <= 0:
            raise ValueError("gradient_clip_norm must be positive")
        if not str(self.lineage_id).strip():
            raise LegacyDistillationLineageError(
                "adapter lineage_id must be non-empty"
            )
        self._key_index = {key: index for index, key in enumerate(self.keys)}
        self._validate_optimizer_state()

    @property
    def rank(self) -> int:
        return int(self.basis.shape[0])

    @property
    def dimension(self) -> int:
        return int(self.basis.shape[1]) if self.basis.ndim == 2 else 0

    @property
    def row_count(self) -> int:
        return len(self.keys)

    @property
    def adapter_id(self) -> str:
        return _digest(self.to_dict(include_optimizer_state=False))

    @property
    def optimizer_state_id(self) -> str:
        return _optimizer_digest(self.optimizer_state_dict())

    @property
    def zero_influence(self) -> bool:
        return self.influence == 0.0

    def _validate_optimizer_state(self) -> None:
        if not self._optimizer_state:
            self._optimizer_state = {
                "basis_first_moment": np.zeros_like(self.basis),
                "basis_second_moment": np.zeros_like(self.basis),
                "coefficient_first_moment": np.zeros_like(self.coefficients),
                "coefficient_second_moment": np.zeros_like(self.coefficients),
                "step": 0,
            }
            return
        for name, shape in (
            ("basis_first_moment", self.basis.shape),
            ("basis_second_moment", self.basis.shape),
            ("coefficient_first_moment", self.coefficients.shape),
            ("coefficient_second_moment", self.coefficients.shape),
        ):
            array = _finite_array(
                self._optimizer_state.get(name),
                ndim=2,
                name=name,
            )
            if array.shape != shape:
                raise ValueError(f"{name} has incompatible shape")
            self._optimizer_state[name] = array
        step = int(self._optimizer_state.get("step", 0))
        if step < 0:
            raise ValueError("optimizer step must be non-negative")
        self._optimizer_state["step"] = step

    def set_influence(self, influence: float) -> None:
        """Set bounded runtime influence without changing learned factors."""

        self.influence = _bounded_unit(influence, name="influence")

    def reconstruct(self, key: str, *, gated: bool = True) -> np.ndarray:
        """Reconstruct one row, optionally applying confidence and influence."""

        index = self._key_index.get(str(key))
        if index is None:
            return np.zeros(self.dimension, dtype=np.float64)
        confidence = float(self.confidences[index])
        if confidence < self.minimum_confidence:
            return np.zeros(self.dimension, dtype=np.float64)
        vector = np.asarray(
            self.coefficients[index] @ self.basis,
            dtype=np.float64,
        )
        if gated:
            gate = self.influence
            if self.scale_by_confidence:
                gate *= confidence
            vector = vector * gate
        return np.ascontiguousarray(vector)

    def adjustment(
        self,
        weighted_keys: Mapping[str, float] | Iterable[str],
        *,
        dimensions: Optional[int] = None,
    ) -> list[float]:
        """Return a norm-bounded weighted adjustment for active semantic keys."""

        return self._adjustment_at_influence(
            weighted_keys,
            dimensions=dimensions,
            influence=self.influence,
        )

    def _adjustment_at_influence(
        self,
        weighted_keys: Mapping[str, float] | Iterable[str],
        *,
        dimensions: Optional[int],
        influence: float,
    ) -> list[float]:
        """Evaluate an adjustment without mutating the adapter's runtime gate."""

        expected_dimension = self.dimension if dimensions is None else int(dimensions)
        if expected_dimension != self.dimension or expected_dimension < 0:
            return [0.0 for _ in range(max(0, expected_dimension))]
        effective_influence = _bounded_unit(influence, name="influence")
        if effective_influence == 0.0 or self.rank == 0 or self.row_count == 0:
            return [0.0 for _ in range(expected_dimension)]
        if isinstance(weighted_keys, Mapping):
            items = weighted_keys.items()
        else:
            items = ((key, 1.0) for key in weighted_keys)
        adjustment = np.zeros(self.dimension, dtype=np.float64)
        for key, raw_weight in items:
            weight = _finite_float(raw_weight, name="adapter activation weight")
            if weight <= 0.0:
                continue
            index = self._key_index.get(str(key))
            if index is None:
                continue
            confidence = float(self.confidences[index])
            if confidence < self.minimum_confidence:
                continue
            gate = effective_influence
            if self.scale_by_confidence:
                gate *= confidence
            adjustment += (
                weight
                * gate
                * np.asarray(
                    self.coefficients[index] @ self.basis,
                    dtype=np.float64,
                )
            )
        norm = float(np.linalg.norm(adjustment))
        limit = float(self.max_adjustment_norm)
        if limit == 0.0:
            adjustment.fill(0.0)
        elif norm > limit and norm > 0.0:
            adjustment *= limit / norm
        return [float(value) for value in adjustment.tolist()]

    def shadow_adjustment(
        self,
        weighted_keys: Mapping[str, float] | Iterable[str],
        *,
        dimensions: Optional[int] = None,
    ) -> list[float]:
        """Return the confidence-gated counterfactual at unit influence."""

        return self._adjustment_at_influence(
            weighted_keys,
            dimensions=dimensions,
            influence=1.0,
        )

    def train_step(
        self,
        targets: Mapping[str, Sequence[float]],
        *,
        learning_rate: float = 1.0e-3,
        beta1: float = 0.9,
        beta2: float = 0.999,
        epsilon: float = 1.0e-8,
    ) -> Dict[str, Any]:
        """Apply one isolated Adam step to this adapter only.

        Targets are transient teacher residuals.  They are neither retained nor
        emitted in the returned report.
        """

        rate = _finite_float(learning_rate, name="learning_rate")
        if rate <= 0.0:
            raise ValueError("learning_rate must be positive")
        first_decay = _bounded_unit(beta1, name="beta1")
        second_decay = _bounded_unit(beta2, name="beta2")
        eps = _finite_float(epsilon, name="epsilon")
        if eps <= 0.0:
            raise ValueError("epsilon must be positive")

        selected: list[tuple[int, np.ndarray]] = []
        for key in sorted(targets):
            index = self._key_index.get(str(key))
            if index is None:
                continue
            target = _finite_array(
                targets[key],
                ndim=1,
                name="adapter target",
            )
            if target.shape != (self.dimension,):
                raise ValueError("adapter target has incompatible dimension")
            selected.append((index, target))
        if not selected or self.rank == 0:
            return {
                "adapter_id": self.adapter_id,
                "adapter_name": self.name,
                "loss": 0.0,
                "optimizer_state_id": self.optimizer_state_id,
                "step": int(self._optimizer_state["step"]),
                "trained_row_count": 0,
            }

        coefficient_gradient = np.zeros_like(self.coefficients)
        basis_gradient = np.zeros_like(self.basis)
        losses: list[float] = []
        normalization = float(len(selected) * max(1, self.dimension))
        for index, target in selected:
            prediction = self.coefficients[index] @ self.basis
            error = prediction - target
            losses.append(float(np.mean(error * error)))
            coefficient_gradient[index] += (2.0 / normalization) * (
                error @ self.basis.T
            )
            basis_gradient += (2.0 / normalization) * np.outer(
                self.coefficients[index],
                error,
            )

        combined_norm = math.sqrt(
            float(np.sum(coefficient_gradient * coefficient_gradient))
            + float(np.sum(basis_gradient * basis_gradient))
        )
        clipped = False
        if combined_norm > self.gradient_clip_norm and combined_norm > 0.0:
            scale = self.gradient_clip_norm / combined_norm
            coefficient_gradient *= scale
            basis_gradient *= scale
            clipped = True

        state = self._optimizer_state
        state["step"] = int(state["step"]) + 1
        step = int(state["step"])
        updates = (
            (
                "coefficient",
                self.coefficients,
                coefficient_gradient,
                state["coefficient_first_moment"],
                state["coefficient_second_moment"],
            ),
            (
                "basis",
                self.basis,
                basis_gradient,
                state["basis_first_moment"],
                state["basis_second_moment"],
            ),
        )
        for _, parameter, gradient, first_moment, second_moment in updates:
            first_moment *= first_decay
            first_moment += (1.0 - first_decay) * gradient
            second_moment *= second_decay
            second_moment += (1.0 - second_decay) * (gradient * gradient)
            corrected_first = first_moment / (1.0 - first_decay**step)
            corrected_second = second_moment / (1.0 - second_decay**step)
            parameter -= rate * corrected_first / (
                np.sqrt(corrected_second) + eps
            )
        return {
            "adapter_id": self.adapter_id,
            "adapter_name": self.name,
            "gradient_clipped": clipped,
            "gradient_norm": round(combined_norm, 12),
            "loss": round(float(np.mean(losses)), 12),
            "optimizer_state_id": self.optimizer_state_id,
            "step": step,
            "trained_row_count": len(selected),
        }

    def optimizer_state_dict(self) -> Dict[str, Any]:
        return {
            "basis_first_moment": self._optimizer_state[
                "basis_first_moment"
            ].tolist(),
            "basis_second_moment": self._optimizer_state[
                "basis_second_moment"
            ].tolist(),
            "coefficient_first_moment": self._optimizer_state[
                "coefficient_first_moment"
            ].tolist(),
            "coefficient_second_moment": self._optimizer_state[
                "coefficient_second_moment"
            ].tolist(),
            "step": int(self._optimizer_state["step"]),
        }

    def to_dict(self, *, include_optimizer_state: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "basis": self.basis.tolist(),
            "coefficients": self.coefficients.tolist(),
            "confidences": self.confidences.tolist(),
            "dimension": self.dimension,
            "gradient_clip_norm": float(self.gradient_clip_norm),
            "influence": float(self.influence),
            "key_digest": _key_digest(self.keys),
            "keys": list(self.keys),
            "lineage_id": self.lineage_id,
            "max_adjustment_norm": float(self.max_adjustment_norm),
            "minimum_confidence": float(self.minimum_confidence),
            "name": self.name,
            "rank": self.rank,
            "row_count": self.row_count,
            "scale_by_confidence": bool(self.scale_by_confidence),
            "schema_version": LEGACY_ADAPTER_SCHEMA_VERSION,
            "zero_influence": self.zero_influence,
        }
        if include_optimizer_state:
            payload["optimizer_state"] = self.optimizer_state_dict()
            payload["optimizer_state_id"] = self.optimizer_state_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundedLowRankLegacyAdapter":
        if value.get("schema_version") not in (None, LEGACY_ADAPTER_SCHEMA_VERSION):
            raise ValueError("unsupported legacy adapter schema")
        result = cls(
            name=str(value.get("name") or ""),
            keys=tuple(str(key) for key in value.get("keys", ())),
            coefficients=np.asarray(value.get("coefficients", ()), dtype=np.float64),
            basis=np.asarray(value.get("basis", ()), dtype=np.float64),
            confidences=np.asarray(value.get("confidences", ()), dtype=np.float64),
            lineage_id=str(value.get("lineage_id") or ""),
            influence=float(value.get("influence", 0.0)),
            minimum_confidence=float(value.get("minimum_confidence", 0.0)),
            max_adjustment_norm=float(value.get("max_adjustment_norm", 1.0)),
            gradient_clip_norm=float(value.get("gradient_clip_norm", 1.0)),
            scale_by_confidence=bool(value.get("scale_by_confidence", True)),
            _optimizer_state=dict(value.get("optimizer_state") or {}),
        )
        expected = str(value.get("key_digest") or "")
        if expected and expected != _key_digest(result.keys):
            raise LegacyDistillationLineageError("adapter key digest mismatch")
        return result


@dataclass(slots=True)
class LegacyEmbeddingAdapterBundle:
    """Lineage-bound collection with optimizer isolation by adapter."""

    lineage: LegacyDistillationLineage
    adapters: Dict[str, BoundedLowRankLegacyAdapter]
    direct_bulk_embedding_replacement: bool = False
    promotion_evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direct_bulk_embedding_replacement:
            raise DirectBulkEmbeddingTransferError(
                "direct bulk embedding replacement is forbidden"
            )
        self.adapters = dict(sorted(self.adapters.items()))
        if len(self.adapters) > DEFAULT_LEGACY_ADAPTER_MAX_COUNT:
            raise LegacyAdapterCapacityError("adapter bundle count exceeds hard maximum")
        for name, adapter in self.adapters.items():
            if name != adapter.name:
                raise ValueError("adapter bundle name mismatch")
            if adapter.lineage_id != self.lineage.lineage_id:
                raise LegacyDistillationLineageError(
                    f"adapter {name!r} lineage mismatch"
                )
        if self.promotion_evidence:
            minimum_seeds = int(
                self.promotion_evidence.get("minimum_seeds", 0)
            )
            if (
                self.promotion_evidence.get("schema_version")
                != LEGACY_DISTILLATION_PROMOTION_SCHEMA_VERSION
                or not self.promotion_evidence.get("promotion_allowed")
                or str(self.promotion_evidence.get("lineage_id") or "")
                != self.lineage.lineage_id
                or minimum_seeds < 2
                or int(self.promotion_evidence.get("seed_count", 0))
                < minimum_seeds
            ):
                raise LegacyDistillationPromotionError(
                    "serialized legacy adapter promotion evidence is invalid"
                )
            expected_digest = str(
                self.promotion_evidence.get("report_sha256") or ""
            )
            comparison = dict(self.promotion_evidence)
            comparison.pop("report_sha256", None)
            if expected_digest != _digest(comparison):
                raise LegacyDistillationPromotionError(
                    "serialized legacy adapter promotion digest mismatch"
                )

    @property
    def bundle_id(self) -> str:
        return _digest(self.to_dict(include_optimizer_state=False))

    @property
    def zero_influence(self) -> bool:
        return all(adapter.zero_influence for adapter in self.adapters.values())

    @property
    def promotion_allowed(self) -> bool:
        return bool(self.promotion_evidence.get("promotion_allowed"))

    @property
    def total_rows(self) -> int:
        return sum(adapter.row_count for adapter in self.adapters.values())

    def set_influence(
        self,
        influence: float,
        *,
        adapter_name: Optional[str] = None,
    ) -> None:
        """Set promoted runtime influence; counterfactuals use shadow APIs."""

        effective_influence = _bounded_unit(influence, name="influence")
        if effective_influence > 0.0 and not self.promotion_allowed:
            raise LegacyDistillationPromotionError(
                "nonzero runtime influence requires a passing lineage-bound "
                "multi-seed promotion report"
            )
        if adapter_name is None:
            for adapter in self.adapters.values():
                adapter.set_influence(effective_influence)
            return
        try:
            self.adapters[str(adapter_name)].set_influence(effective_influence)
        except KeyError as exc:
            raise KeyError(f"unknown legacy adapter: {adapter_name!r}") from exc

    def promote(
        self,
        promotion_report: Mapping[str, Any],
        *,
        influence: float,
    ) -> Dict[str, Any]:
        """Bind passing held-out evidence before enabling runtime influence."""

        if (
            promotion_report.get("schema_version")
            != LEGACY_DISTILLATION_PROMOTION_SCHEMA_VERSION
        ):
            raise LegacyDistillationPromotionError(
                "unsupported legacy distillation promotion evidence"
            )
        if not promotion_report.get("promotion_allowed"):
            raise LegacyDistillationPromotionError(
                "legacy distillation promotion evidence did not pass"
            )
        if str(promotion_report.get("lineage_id") or "") != self.lineage.lineage_id:
            raise LegacyDistillationPromotionError(
                "legacy distillation promotion lineage mismatch"
            )
        minimum_seeds = int(promotion_report.get("minimum_seeds", 0))
        if minimum_seeds < 2 or int(
            promotion_report.get("seed_count", 0)
        ) < minimum_seeds:
            raise LegacyDistillationPromotionError(
                "legacy distillation promotion has insufficient seeds"
            )
        report_digest = str(promotion_report.get("report_sha256") or "")
        comparison = dict(promotion_report)
        comparison.pop("report_sha256", None)
        if report_digest != _digest(comparison):
            raise LegacyDistillationPromotionError(
                "legacy distillation promotion report digest mismatch"
            )
        self.promotion_evidence = dict(promotion_report)
        self.set_influence(influence)
        return {
            "bundle_id": self.bundle_id,
            "influence": _bounded_unit(influence, name="influence"),
            "lineage_id": self.lineage.lineage_id,
            "promotion_allowed": True,
            "promotion_report_sha256": report_digest,
            "seed_count": int(promotion_report["seed_count"]),
        }

    def adjustment_for(
        self,
        adapter_name: str,
        weighted_keys: Mapping[str, float] | Iterable[str],
        *,
        dimensions: Optional[int] = None,
        shadow: bool = False,
    ) -> list[float]:
        adapter = self.adapters.get(str(adapter_name))
        if adapter is None:
            return [0.0 for _ in range(max(0, int(dimensions or 0)))]
        if shadow:
            return adapter.shadow_adjustment(
                weighted_keys,
                dimensions=dimensions,
            )
        return adapter.adjustment(weighted_keys, dimensions=dimensions)

    def train_adapter(
        self,
        adapter_name: str,
        targets: Mapping[str, Sequence[float]],
        **optimizer_kwargs: Any,
    ) -> Dict[str, Any]:
        """Train exactly one adapter and verify sibling parameter/state isolation."""

        name = str(adapter_name)
        if name not in self.adapters:
            raise KeyError(f"unknown legacy adapter: {name!r}")
        sibling_before = {
            other_name: (
                other.adapter_id,
                other.optimizer_state_id,
            )
            for other_name, other in self.adapters.items()
            if other_name != name
        }
        report = self.adapters[name].train_step(targets, **optimizer_kwargs)
        sibling_after = {
            other_name: (
                other.adapter_id,
                other.optimizer_state_id,
            )
            for other_name, other in self.adapters.items()
            if other_name != name
        }
        if sibling_before != sibling_after:
            raise LegacyDistillationError(
                "adapter gradient or optimizer state escaped its isolation boundary"
            )
        return {
            **report,
            "isolated_adapter": name,
            "sibling_adapter_count": len(sibling_before),
            "sibling_optimizer_state_unchanged": True,
        }

    def report(self) -> Dict[str, Any]:
        """Return a key-free runtime and capacity summary."""

        return {
            "adapter_count": len(self.adapters),
            "adapters": {
                name: {
                    "adapter_id": adapter.adapter_id,
                    "confidence_max": round(
                        float(np.max(adapter.confidences)), 12
                    )
                    if adapter.row_count
                    else 0.0,
                    "confidence_mean": round(
                        float(np.mean(adapter.confidences)), 12
                    )
                    if adapter.row_count
                    else 0.0,
                    "confidence_min": round(
                        float(np.min(adapter.confidences)), 12
                    )
                    if adapter.row_count
                    else 0.0,
                    "dimension": adapter.dimension,
                    "influence": adapter.influence,
                    "key_digest": _key_digest(adapter.keys),
                    "optimizer_state_id": adapter.optimizer_state_id,
                    "rank": adapter.rank,
                    "row_count": adapter.row_count,
                    "zero_influence": adapter.zero_influence,
                }
                for name, adapter in sorted(self.adapters.items())
            },
            "bundle_id": self.bundle_id,
            "direct_bulk_embedding_replacement": False,
            "lineage": self.lineage.to_dict(),
            "promotion_allowed": self.promotion_allowed,
            "promotion_report_sha256": str(
                self.promotion_evidence.get("report_sha256") or ""
            ),
            "runtime_activation_authorized": self.promotion_allowed,
            "sample_memory_included": False,
            "schema_version": LEGACY_ADAPTER_BUNDLE_SCHEMA_VERSION,
            "shadow_mode": not self.promotion_allowed,
            "total_rows": self.total_rows,
            "zero_influence": self.zero_influence,
        }

    def to_dict(self, *, include_optimizer_state: bool = True) -> Dict[str, Any]:
        return {
            "adapters": {
                name: adapter.to_dict(
                    include_optimizer_state=include_optimizer_state
                )
                for name, adapter in sorted(self.adapters.items())
            },
            "direct_bulk_embedding_replacement": False,
            "direct_bulk_transfer_allowed": False,
            "lineage": self.lineage.to_dict(),
            "promotion_evidence": dict(self.promotion_evidence),
            "sample_memory_included": False,
            "schema_version": LEGACY_ADAPTER_BUNDLE_SCHEMA_VERSION,
        }

    def to_json(self, *, include_optimizer_state: bool = True) -> str:
        return _canonical_bytes(
            self.to_dict(include_optimizer_state=include_optimizer_state)
        ).decode("utf-8")

    def save_json(
        self,
        path: str | Path,
        *,
        include_optimizer_state: bool = True,
    ) -> Path:
        """Atomically persist a lineage-bound adapter sidecar."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.tmp-",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(
                    self.to_json(
                        include_optimizer_state=include_optimizer_state
                    )
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return target

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyEmbeddingAdapterBundle":
        if value.get("schema_version") not in (
            None,
            LEGACY_ADAPTER_BUNDLE_SCHEMA_VERSION,
        ):
            raise ValueError("unsupported legacy adapter bundle schema")
        if value.get("sample_memory_included"):
            raise LegacyDistillationError(
                "legacy adapter bundle contains forbidden sample memory"
            )
        if value.get("direct_bulk_embedding_replacement") or value.get(
            "direct_bulk_transfer_allowed"
        ):
            raise DirectBulkEmbeddingTransferError(
                "serialized bundle requests direct bulk embedding replacement"
            )
        raw_adapters = value.get("adapters", {})
        if not isinstance(raw_adapters, Mapping):
            raise ValueError("adapter bundle adapters must be a mapping")
        return cls(
            lineage=LegacyDistillationLineage.from_dict(
                value.get("lineage", {})
            ),
            adapters={
                str(name): BoundedLowRankLegacyAdapter.from_dict(adapter)
                for name, adapter in raw_adapters.items()
            },
            promotion_evidence=dict(value.get("promotion_evidence") or {}),
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> "LegacyEmbeddingAdapterBundle":
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("legacy adapter bundle is invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("legacy adapter bundle JSON must be an object")
        return cls.from_dict(payload)

    @classmethod
    def load_json(cls, path: str | Path) -> "LegacyEmbeddingAdapterBundle":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class LegacyDistillationResult:
    """Distilled adapters plus privacy-preserving fit evidence."""

    bundle: LegacyEmbeddingAdapterBundle
    report: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return bool(self.report.get("accepted"))

    @property
    def adapters(self) -> Mapping[str, BoundedLowRankLegacyAdapter]:
        return self.bundle.adapters


def _confidence_for(
    confidence_by_adapter: Mapping[str, Any],
    field_name: str,
    key: str,
    default: float,
) -> float:
    raw: Any = default
    field_confidence = confidence_by_adapter.get(field_name)
    if isinstance(field_confidence, Mapping):
        raw = field_confidence.get(key, default)
    elif key in confidence_by_adapter:
        raw = confidence_by_adapter[key]
    return _bounded_unit(raw, name="legacy row confidence")


def _eligible_embedding_fields(config: LegacyDistillationConfig) -> tuple[str, ...]:
    if config.source_field_allowlist:
        return tuple(config.source_field_allowlist)
    return LEGACY_DISTILLABLE_EMBEDDING_FIELDS


def _fit_adapter(
    *,
    field_name: str,
    rows: Sequence[tuple[str, Sequence[float], float]],
    config: LegacyDistillationConfig,
    lineage_id: str,
) -> tuple[BoundedLowRankLegacyAdapter, Dict[str, Any]]:
    dimensions = {len(vector) for _, vector, _ in rows}
    if len(dimensions) != 1:
        raise LegacyDistillationError(
            f"legacy adapter {field_name!r} has incompatible dimensions"
        )
    dimension = dimensions.pop()
    matrix = _finite_array(
        [vector for _, vector, _ in rows],
        ndim=2,
        name=f"{field_name} teacher matrix",
    )
    effective_rank = min(int(config.rank), len(rows), dimension)
    if effective_rank:
        left, singular_values, right = np.linalg.svd(
            matrix,
            full_matrices=False,
        )
        # Canonicalize the otherwise arbitrary SVD signs so equal inputs yield
        # byte-identical adapters across BLAS implementations.
        for component in range(effective_rank):
            basis_row = right[component]
            pivot = int(np.argmax(np.abs(basis_row)))
            if basis_row[pivot] < 0.0:
                right[component] *= -1.0
                left[:, component] *= -1.0
        coefficients = (
            left[:, :effective_rank] * singular_values[:effective_rank]
        )
        basis = right[:effective_rank, :]
    else:
        coefficients = np.zeros((len(rows), 0), dtype=np.float64)
        basis = np.zeros((0, dimension), dtype=np.float64)
    reconstructed = coefficients @ basis
    residual = matrix - reconstructed
    denominator = float(np.linalg.norm(matrix))
    relative_error = (
        float(np.linalg.norm(residual)) / denominator
        if denominator > 0.0
        else 0.0
    )
    row_cosines: list[float] = []
    for original, fitted in zip(matrix, reconstructed):
        norm_product = float(np.linalg.norm(original) * np.linalg.norm(fitted))
        row_cosines.append(
            float(np.dot(original, fitted) / norm_product)
            if norm_product > 0.0
            else 0.0
        )
    adapter = BoundedLowRankLegacyAdapter(
        name=field_name,
        keys=tuple(key for key, _, _ in rows),
        coefficients=coefficients,
        basis=basis,
        confidences=np.asarray(
            [confidence for _, _, confidence in rows],
            dtype=np.float64,
        ),
        lineage_id=lineage_id,
        influence=config.influence,
        minimum_confidence=config.minimum_confidence,
        max_adjustment_norm=config.max_adjustment_norm,
        gradient_clip_norm=config.gradient_clip_norm,
        scale_by_confidence=config.scale_by_confidence,
    )
    return adapter, {
        "adapter_id": adapter.adapter_id,
        "confidence_max": round(max(row[2] for row in rows), 12),
        "confidence_mean": round(
            math.fsum(row[2] for row in rows) / len(rows),
            12,
        ),
        "confidence_min": round(min(row[2] for row in rows), 12),
        "dense_scalar_count": int(matrix.size),
        "dimension": dimension,
        "key_digest": _key_digest(key for key, _, _ in rows),
        "low_rank_scalar_count": int(
            coefficients.size + basis.size
        ),
        "rank": effective_rank,
        "reconstruction_cosine_mean": round(
            math.fsum(row_cosines) / len(row_cosines),
            12,
        ),
        "relative_frobenius_error": round(relative_error, 12),
        "row_count": len(rows),
        "zero_influence": adapter.zero_influence,
    }


def distill_legacy_embedding_tails(
    teacher: ModalAutoencoderTrainingState,
    student: ModalAutoencoderTrainingState,
    *,
    config: Optional[LegacyDistillationConfig] = None,
    confidence_by_adapter: Optional[Mapping[str, Any]] = None,
    confidence_by_field: Optional[Mapping[str, Any]] = None,
    lineage: Optional[LegacyDistillationLineage] = None,
    teacher_checkpoint_sha256: str = "",
    student_checkpoint_sha256: str = "",
    split_id: str = "heldout",
    seed: Optional[int] = None,
    inventory_sha256: str = "",
) -> LegacyDistillationResult:
    """Fit bounded adapters from legacy-only rows without mutating either state."""

    policy = config or LegacyDistillationConfig()
    if confidence_by_adapter is not None and confidence_by_field is not None:
        raise ValueError(
            "provide only one of confidence_by_adapter and confidence_by_field"
        )
    confidences = dict(
        confidence_by_adapter
        if confidence_by_adapter is not None
        else confidence_by_field
        or {}
    )
    unknown_confidence_fields = {
        key
        for key, value in confidences.items()
        if isinstance(value, Mapping)
        and key not in LEGACY_DISTILLABLE_EMBEDDING_FIELDS
    }
    if unknown_confidence_fields:
        raise ValueError(
            "unknown confidence adapter fields: "
            + ", ".join(sorted(unknown_confidence_fields))
        )

    teacher_before = _state_binding(teacher)
    student_before = _state_binding(student)
    effective_seed = int(
        lineage.seed
        if lineage is not None and seed is None
        else policy.seed
        if seed is None
        else seed
    )
    effective_lineage = lineage or LegacyDistillationLineage(
        teacher_checkpoint_sha256=_safe_checkpoint_binding(
            teacher_checkpoint_sha256,
            teacher_before,
        ),
        student_checkpoint_sha256=_safe_checkpoint_binding(
            student_checkpoint_sha256,
            student_before,
        ),
        split_id=str(split_id),
        seed=effective_seed,
        teacher_architecture=teacher.architecture_version,
        student_architecture=student.architecture_version,
        inventory_sha256=str(inventory_sha256),
    )
    if (
        lineage is not None
        and teacher_checkpoint_sha256
        and effective_lineage.teacher_checkpoint_sha256
        != teacher_checkpoint_sha256
    ):
        raise LegacyDistillationLineageError(
            "teacher checkpoint lineage conflicts with the supplied binding"
        )
    if (
        lineage is not None
        and student_checkpoint_sha256
        and effective_lineage.student_checkpoint_sha256
        != student_checkpoint_sha256
    ):
        raise LegacyDistillationLineageError(
            "student checkpoint lineage conflicts with the supplied binding"
        )
    if effective_lineage.seed != effective_seed:
        raise LegacyDistillationLineageError("lineage seed mismatch")
    if effective_lineage.teacher_architecture != teacher.architecture_version:
        raise LegacyDistillationLineageError("teacher architecture mismatch")
    if effective_lineage.student_architecture != student.architecture_version:
        raise LegacyDistillationLineageError("student architecture mismatch")

    adapters: Dict[str, BoundedLowRankLegacyAdapter] = {}
    adapter_reports: Dict[str, Dict[str, Any]] = {}
    excluded_low_confidence = 0
    excluded_incompatible = 0
    excluded_shared = 0
    eligible_tail_rows = 0
    selected_tail_rows = 0
    fields = _eligible_embedding_fields(policy)
    if len(fields) > policy.max_adapters:
        fields = fields[: int(policy.max_adapters)]

    teacher_maps = teacher.embedding_weight_maps()
    student_maps = student.embedding_weight_maps()
    for field_name in fields:
        teacher_map = teacher_maps[field_name]
        student_map = student_maps[field_name]

        def eligible_rows() -> Iterable[
            tuple[str, Sequence[float], float, float]
        ]:
            nonlocal excluded_shared
            nonlocal excluded_incompatible
            nonlocal excluded_low_confidence
            nonlocal eligible_tail_rows
            for raw_key, raw_vector in teacher_map.items():
                key = str(raw_key)
                if key in student_map:
                    excluded_shared += 1
                    continue
                if _key_is_source_memory(key) or any(
                    marker in key.lower() for marker in _FORBIDDEN_TEXT_MARKERS
                ):
                    # Key material is not copied into the report, but these
                    # memory-lane markers are also excluded from learned state.
                    excluded_incompatible += 1
                    continue
                try:
                    vector = [
                        _finite_float(value, name="legacy embedding value")
                        for value in raw_vector
                    ]
                except (TypeError, ValueError):
                    excluded_incompatible += 1
                    continue
                if not vector:
                    excluded_incompatible += 1
                    continue
                confidence = _confidence_for(
                    confidences,
                    field_name,
                    key,
                    policy.default_confidence,
                )
                if confidence < policy.minimum_confidence:
                    excluded_low_confidence += 1
                    continue
                norm = math.sqrt(
                    math.fsum(value * value for value in vector)
                )
                eligible_tail_rows += 1
                yield key, vector, confidence, norm

        # ``heapq.nsmallest`` keeps only max_rows candidates while scanning the
        # potentially 569k-row legacy tail.  The ranking is equivalent to a
        # full stable sort but memory stays bounded by the adapter capacity.
        row_limit = int(policy.max_rows_per_adapter)
        if row_limit:
            selected = heapq.nsmallest(
                row_limit,
                eligible_rows(),
                key=lambda row: (-row[2], -row[3], row[0]),
            )
        else:
            for _ in eligible_rows():
                pass
            selected = []
        if not selected:
            continue
        dimensions: Dict[int, list[tuple[str, Sequence[float], float, float]]] = {}
        for row in selected:
            dimensions.setdefault(len(row[1]), []).append(row)
        # One adapter cannot mix dimensions.  Keep the strongest deterministic
        # dimension cohort and account for every incompatible row.
        dimension, dimension_rows = min(
            dimensions.items(),
            key=lambda item: (
                -len(item[1]),
                -math.fsum(row[2] for row in item[1]),
                item[0],
            ),
        )
        del dimension
        excluded_incompatible += len(selected) - len(dimension_rows)
        fit_rows = [(key, vector, confidence) for key, vector, confidence, _ in dimension_rows]
        adapter, adapter_report = _fit_adapter(
            field_name=field_name,
            rows=fit_rows,
            config=policy,
            lineage_id=effective_lineage.lineage_id,
        )
        adapters[field_name] = adapter
        adapter_reports[field_name] = adapter_report
        selected_tail_rows += adapter.row_count

    teacher_after = _state_binding(teacher)
    student_after = _state_binding(student)
    if teacher_after != teacher_before:
        raise LegacyDistillationError(
            "immutable teacher state changed during distillation"
        )
    if student_after != student_before:
        raise LegacyDistillationError(
            "student state changed during adapter distillation"
        )
    bundle = LegacyEmbeddingAdapterBundle(
        lineage=effective_lineage,
        adapters=adapters,
    )
    dense_scalars = sum(
        int(report["dense_scalar_count"]) for report in adapter_reports.values()
    )
    low_rank_scalars = sum(
        int(report["low_rank_scalar_count"])
        for report in adapter_reports.values()
    )
    report: Dict[str, Any] = {
        "accepted": True,
        "adapter_count": len(adapters),
        "adapters": adapter_reports,
        "bundle_id": bundle.bundle_id,
        "confidence": {
            "default": float(policy.default_confidence),
            "minimum": float(policy.minimum_confidence),
            "scale_by_confidence": bool(policy.scale_by_confidence),
        },
        "config": policy.to_dict(),
        "dense_scalar_count": dense_scalars,
        "direct_bulk_embedding_replacement": False,
        "direct_bulk_transfer_allowed": False,
        "eligible_tail_row_count": eligible_tail_rows,
        "excluded_incompatible_or_text_memory_row_count": excluded_incompatible,
        "excluded_low_confidence_row_count": excluded_low_confidence,
        "excluded_shared_student_row_count": excluded_shared,
        "lineage": effective_lineage.to_dict(),
        "lineage_id": effective_lineage.lineage_id,
        "low_rank_scalar_count": low_rank_scalars,
        "minimum_confidence": float(policy.minimum_confidence),
        "optimizer_state_isolated_by_adapter": True,
        "rank": int(policy.rank),
        "sample_memory_fields_excluded": sorted(LEGACY_SAMPLE_MEMORY_FIELDS),
        "sample_memory_included": False,
        "scalar_compression_ratio": round(
            dense_scalars / low_rank_scalars,
            12,
        )
        if low_rank_scalars
        else 0.0,
        "schema_version": LEGACY_DISTILLATION_SCHEMA_VERSION,
        "seed": int(effective_lineage.seed),
        "selected_tail_row_count": selected_tail_rows,
        "shadow_mode": True,
        "split_id": effective_lineage.split_id,
        "student_checkpoint_sha256": (
            effective_lineage.student_checkpoint_sha256
        ),
        "student_parameter_rows_changed": 0,
        "student_state_sha256": student_before,
        "student_state_immutable": student_after == student_before,
        "teacher_checkpoint_sha256": (
            effective_lineage.teacher_checkpoint_sha256
        ),
        "teacher_role": "immutable_read_only_distillation_teacher",
        "teacher_state_sha256": teacher_before,
        "teacher_state_immutable": teacher_after == teacher_before,
        "zero_influence_baseline": bundle.zero_influence,
    }
    report["report_sha256"] = _digest(report)
    return LegacyDistillationResult(bundle=bundle, report=report)


# Singular compatibility spelling for callers that model one conceptual tail.
distill_legacy_embedding_tail = distill_legacy_embedding_tails


def forbid_direct_bulk_embedding_replacement(*_: Any, **__: Any) -> None:
    """Explicit fail-closed API for the measured-regressive migration path."""

    raise DirectBulkEmbeddingTransferError(
        "direct bulk embedding replacement is forbidden; use bounded "
        "legacy teacher distillation with a zero-influence baseline"
    )


@dataclass(frozen=True, slots=True)
class LegacyDistillationPromotionConfig:
    """Multi-seed held-out quality gate with hard no-regression categories."""

    minimum_seeds: int = DEFAULT_LEGACY_ADAPTER_MINIMUM_SEEDS
    minimum_objective_improvement: float = 0.0
    regression_tolerance: float = 0.0
    require_each_seed_improvement: bool = True
    required_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if int(self.minimum_seeds) < 2:
            raise ValueError("minimum_seeds must be at least two")
        if _finite_float(
            self.minimum_objective_improvement,
            name="minimum_objective_improvement",
        ) < 0.0:
            raise ValueError("minimum_objective_improvement must be non-negative")
        if _finite_float(
            self.regression_tolerance,
            name="regression_tolerance",
        ) < 0.0:
            raise ValueError("regression_tolerance must be non-negative")


# A category passes when at least one alias is present in both baseline and
# candidate and none of the available aliases regresses.
LEGACY_DISTILLATION_GUARDRAIL_ALIASES: Mapping[str, tuple[str, ...]] = {
    "ir": (
        "ir_cross_entropy_loss",
        "ir_cosine_similarity",
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
    ),
    "semantic": (
        "semantic_equivalence",
        "semantic_equivalence_score",
        "obligation_equivalence",
        "operator_equivalence",
    ),
    "proof": (
        "hammer_proof_success_rate",
        "proof_success_rate",
        "symbolic_validity_success_rate",
    ),
    "reconstruction": (
        "reconstruction_loss",
        "reconstruction_success_rate",
    ),
    "round_trip": (
        "round_trip_reconstruction_success_rate",
        "round_trip_success_rate",
        "round_trip_loss",
    ),
    "provenance": (
        "provenance_alignment_success_rate",
        "provenance_success_rate",
        "provenance_loss",
    ),
    "uncertainty": (
        "uncertainty_calibration_error",
        "expected_calibration_error",
        "uncertainty_loss",
        "uncertainty_gate_passed",
    ),
    "holdout": (
        "holdout_loss",
        "holdout_cross_entropy_loss",
        "holdout_success_rate",
        "holdout_gate_passed",
    ),
    "anti_copy": (
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "anti_copy_penalty",
        "source_copy_guardrail_passed",
    ),
}
LEGACY_DISTILLATION_OBJECTIVE_ALIASES = {
    "ce": (
        "autoencoder_cross_entropy_loss",
        "autoencoder_ce_loss",
        "cross_entropy_loss",
    ),
    "cosine": (
        "autoencoder_cosine",
        "autoencoder_cosine_similarity",
        "embedding_cosine_similarity",
    ),
}


def _flatten_metrics(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
) -> Dict[str, float]:
    flattened: Dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(raw_value, Mapping):
            flattened.update(_flatten_metrics(raw_value, prefix=path))
            continue
        if isinstance(raw_value, bool):
            flattened[path] = 1.0 if raw_value else 0.0
            continue
        try:
            number = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            flattened[path] = number
    return flattened


def _metric_matches(name: str, aliases: Sequence[str]) -> bool:
    leaf = str(name).rsplit(".", 1)[-1]
    return leaf in aliases


def _lower_is_better(name: str) -> bool:
    leaf = str(name).lower().rsplit(".", 1)[-1]
    return any(
        marker in leaf
        for marker in ("loss", "error", "penalty", "regression", "excess")
    ) and "success" not in leaf


def _metric_improvement(
    name: str,
    baseline: float,
    candidate: float,
) -> float:
    return baseline - candidate if _lower_is_better(name) else candidate - baseline


def _packet_metrics(
    packet: Mapping[str, Any],
    side: str,
) -> Dict[str, float]:
    candidates = (
        packet.get(side),
        packet.get(f"{side}_metrics"),
        packet.get(f"{side}_evaluation"),
    )
    for value in candidates:
        if isinstance(value, Mapping):
            return _flatten_metrics(value)
    return {}


def _packet_side(
    packet: Mapping[str, Any],
    side: str,
) -> Mapping[str, Any]:
    for value in (
        packet.get(side),
        packet.get(f"{side}_metrics"),
        packet.get(f"{side}_evaluation"),
    ):
        if isinstance(value, Mapping):
            return value
    return {}


def _per_family_comparisons(
    packet: Mapping[str, Any],
) -> Dict[str, Dict[str, Mapping[str, Any]]]:
    """Normalize common per-family before/after packet layouts."""

    comparisons: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    direct = (
        packet.get("per_family")
        or packet.get("view_family_metrics")
        or packet.get("family_metrics")
        or {}
    )
    if isinstance(direct, Mapping):
        if isinstance(direct.get("baseline"), Mapping) and isinstance(
            direct.get("candidate"), Mapping
        ):
            baseline_block = direct["baseline"]
            candidate_block = direct["candidate"]
            for family in sorted(set(baseline_block) | set(candidate_block)):
                comparisons[str(family)] = {
                    "baseline": baseline_block.get(family, {}),
                    "candidate": candidate_block.get(family, {}),
                }
        else:
            for family, family_packet in direct.items():
                if not isinstance(family_packet, Mapping):
                    comparisons[str(family)] = {
                        "baseline": {},
                        "candidate": {},
                    }
                    continue
                comparisons[str(family)] = {
                    "baseline": _packet_side(family_packet, "baseline"),
                    "candidate": _packet_side(family_packet, "candidate"),
                    "raw": family_packet,
                }

    # Evaluators also commonly nest each family block inside the two complete
    # baseline/candidate quality packets.
    baseline_side = _packet_side(packet, "baseline")
    candidate_side = _packet_side(packet, "candidate")
    baseline_families = (
        baseline_side.get("per_family")
        or baseline_side.get("view_family_metrics")
        or baseline_side.get("family_metrics")
        or {}
    )
    candidate_families = (
        candidate_side.get("per_family")
        or candidate_side.get("view_family_metrics")
        or candidate_side.get("family_metrics")
        or {}
    )
    if isinstance(baseline_families, Mapping) and isinstance(
        candidate_families, Mapping
    ):
        for family in sorted(set(baseline_families) | set(candidate_families)):
            comparisons[str(family)] = {
                "baseline": baseline_families.get(family, {}),
                "candidate": candidate_families.get(family, {}),
            }
    return comparisons


def evaluate_legacy_distillation_promotion(
    seed_evaluations: Sequence[Mapping[str, Any]],
    *,
    config: Optional[LegacyDistillationPromotionConfig] = None,
    lineage_id: str = "",
) -> Dict[str, Any]:
    """Evaluate multi-seed held-out improvement and every hard guardrail."""

    policy = config or LegacyDistillationPromotionConfig()
    reasons: list[str] = []
    seed_reports: list[Dict[str, Any]] = []
    observed_seeds: set[int] = set()
    observed_splits: set[str] = set()
    all_ce_improvements: list[float] = []
    all_cosine_improvements: list[float] = []
    observed_families: set[str] = set()

    for packet_index, packet in enumerate(seed_evaluations):
        try:
            seed = int(packet.get("seed"))
        except (TypeError, ValueError):
            reasons.append(f"evaluation_{packet_index}:missing_seed")
            continue
        if seed in observed_seeds:
            reasons.append(f"seed_{seed}:duplicate_seed")
            continue
        observed_seeds.add(seed)
        split = str(
            packet.get("split_id")
            or packet.get("split")
            or ""
        ).strip()
        if "heldout" not in split.lower() and "holdout" not in split.lower():
            reasons.append(f"seed_{seed}:not_held_out")
        if split:
            observed_splits.add(split)
        packet_lineage = str(packet.get("lineage_id") or "")
        if lineage_id and packet_lineage != lineage_id:
            reasons.append(f"seed_{seed}:lineage_mismatch")

        baseline = _packet_metrics(packet, "baseline")
        candidate = _packet_metrics(packet, "candidate")
        objective_improvements: Dict[str, float] = {}
        for objective, aliases in LEGACY_DISTILLATION_OBJECTIVE_ALIASES.items():
            names = sorted(
                name
                for name in set(baseline) & set(candidate)
                if _metric_matches(name, aliases)
            )
            if not names:
                continue
            improvements = [
                _metric_improvement(name, baseline[name], candidate[name])
                for name in names
            ]
            objective_improvements[objective] = min(improvements)
        ce_improvement = objective_improvements.get("ce")
        cosine_improvement = objective_improvements.get("cosine")
        if ce_improvement is not None:
            all_ce_improvements.append(ce_improvement)
        if cosine_improvement is not None:
            all_cosine_improvements.append(cosine_improvement)
        objective_passed = (
            (
                ce_improvement is not None
                and ce_improvement > policy.minimum_objective_improvement
            )
            or (
                cosine_improvement is not None
                and cosine_improvement > policy.minimum_objective_improvement
            )
        )
        if ce_improvement is None and cosine_improvement is None:
            reasons.append(f"seed_{seed}:missing_autoencoder_objective")
        if policy.require_each_seed_improvement and not objective_passed:
            reasons.append(f"seed_{seed}:no_autoencoder_improvement")

        category_reports: Dict[str, Any] = {}
        for category, aliases in LEGACY_DISTILLATION_GUARDRAIL_ALIASES.items():
            names = sorted(
                name
                for name in set(baseline) & set(candidate)
                if _metric_matches(name, aliases)
            )
            regressions = {
                name: round(
                    -_metric_improvement(
                        name,
                        baseline[name],
                        candidate[name],
                    ),
                    12,
                )
                for name in names
                if _metric_improvement(
                    name,
                    baseline[name],
                    candidate[name],
                )
                < -policy.regression_tolerance
            }
            if not names:
                reasons.append(f"seed_{seed}:missing_{category}_guardrail")
            if regressions:
                reasons.append(f"seed_{seed}:{category}_regression")
            category_reports[category] = {
                "evidence_metric_count": len(names),
                "passed": bool(names) and not regressions,
                "regressions": regressions,
            }

        raw_family_blocks = _per_family_comparisons(packet)
        family_reports: Dict[str, Any] = {}
        if not raw_family_blocks:
            reasons.append(f"seed_{seed}:missing_per_family_semantic_guardrail")
        else:
            missing_seed_families = set(policy.required_families) - set(
                str(family) for family in raw_family_blocks
            )
            if missing_seed_families:
                reasons.append(f"seed_{seed}:missing_required_families")
            for family, family_packet in sorted(raw_family_blocks.items()):
                family_name = str(family)
                observed_families.add(family_name)
                if not isinstance(family_packet, Mapping):
                    reasons.append(
                        f"seed_{seed}:family_{family_name}_invalid_evidence"
                    )
                    continue
                raw_family_baseline = family_packet.get("baseline", {})
                raw_family_candidate = family_packet.get("candidate", {})
                family_baseline = (
                    _flatten_metrics(raw_family_baseline)
                    if isinstance(raw_family_baseline, Mapping)
                    else {}
                )
                family_candidate = (
                    _flatten_metrics(raw_family_candidate)
                    if isinstance(raw_family_candidate, Mapping)
                    else {}
                )
                if not family_baseline and not family_candidate:
                    # Also accept {metric: {baseline: x, candidate: y}}.
                    raw_comparisons = family_packet.get(
                        "raw", family_packet
                    )
                    if not isinstance(raw_comparisons, Mapping):
                        raw_comparisons = {}
                    for metric, comparison in raw_comparisons.items():
                        if not isinstance(comparison, Mapping):
                            continue
                        if "baseline" in comparison and "candidate" in comparison:
                            family_baseline[str(metric)] = _finite_float(
                                comparison["baseline"],
                                name="family baseline metric",
                            )
                            family_candidate[str(metric)] = _finite_float(
                                comparison["candidate"],
                                name="family candidate metric",
                            )
                names = sorted(set(family_baseline) & set(family_candidate))
                semantic_names = [
                    name
                    for name in names
                    if _metric_matches(
                        name,
                        LEGACY_DISTILLATION_GUARDRAIL_ALIASES["semantic"],
                    )
                ]
                regressions = {
                    name: round(
                        -_metric_improvement(
                            name,
                            family_baseline[name],
                            family_candidate[name],
                        ),
                        12,
                    )
                    for name in names
                    if _metric_improvement(
                        name,
                        family_baseline[name],
                        family_candidate[name],
                    )
                    < -policy.regression_tolerance
                }
                if not names:
                    reasons.append(
                        f"seed_{seed}:family_{family_name}_missing_metrics"
                    )
                if not semantic_names:
                    reasons.append(
                        f"seed_{seed}:family_{family_name}_"
                        "missing_semantic_guardrail"
                    )
                if regressions:
                    reasons.append(
                        f"seed_{seed}:family_{family_name}_regression"
                    )
                family_reports[family_name] = {
                    "evidence_metric_count": len(names),
                    "passed": (
                        bool(names)
                        and bool(semantic_names)
                        and not regressions
                    ),
                    "regressions": regressions,
                    "semantic_evidence_metric_count": len(semantic_names),
                }
        seed_reports.append(
            {
                "autoencoder_ce_improvement": (
                    round(ce_improvement, 12)
                    if ce_improvement is not None
                    else None
                ),
                "autoencoder_cosine_improvement": (
                    round(cosine_improvement, 12)
                    if cosine_improvement is not None
                    else None
                ),
                "guardrails": category_reports,
                "objective_passed": objective_passed,
                "per_family": family_reports,
                "seed": seed,
                "split_id": split,
            }
        )

    if len(observed_seeds) < policy.minimum_seeds:
        reasons.append("insufficient_unique_seeds")
    if len(observed_splits) > 1:
        reasons.append("inconsistent_held_out_splits")
    missing_families = set(policy.required_families) - observed_families
    if missing_families:
        reasons.append("missing_required_families")
    aggregate_improvement = (
        (
            len(all_ce_improvements) == len(observed_seeds)
            and all_ce_improvements
            and math.fsum(all_ce_improvements) / len(all_ce_improvements)
            > policy.minimum_objective_improvement
        )
        or (
            len(all_cosine_improvements) == len(observed_seeds)
            and all_cosine_improvements
            and math.fsum(all_cosine_improvements) / len(all_cosine_improvements)
            > policy.minimum_objective_improvement
        )
    )
    if not aggregate_improvement:
        reasons.append("no_multi_seed_aggregate_autoencoder_improvement")
    reasons = list(dict.fromkeys(reasons))
    report: Dict[str, Any] = {
        "aggregate_autoencoder_ce_improvement": round(
            math.fsum(all_ce_improvements) / len(all_ce_improvements),
            12,
        )
        if all_ce_improvements
        else None,
        "aggregate_autoencoder_cosine_improvement": round(
            math.fsum(all_cosine_improvements) / len(all_cosine_improvements),
            12,
        )
        if all_cosine_improvements
        else None,
        "direct_bulk_embedding_replacement": False,
        "lineage_id": lineage_id,
        "minimum_seeds": int(policy.minimum_seeds),
        "missing_required_families": sorted(missing_families),
        "promotion_allowed": not reasons,
        "reasons": reasons,
        "required_guardrail_categories": sorted(
            LEGACY_DISTILLATION_GUARDRAIL_ALIASES
        ),
        "schema_version": LEGACY_DISTILLATION_PROMOTION_SCHEMA_VERSION,
        "seed_count": len(observed_seeds),
        "seed_reports": seed_reports,
        "zero_influence_baseline_required": True,
    }
    report["report_sha256"] = _digest(report)
    return report


def require_legacy_distillation_promotion(
    seed_evaluations: Sequence[Mapping[str, Any]],
    *,
    config: Optional[LegacyDistillationPromotionConfig] = None,
    lineage_id: str = "",
) -> Dict[str, Any]:
    """Return promotion evidence or raise without enabling adapter influence."""

    report = evaluate_legacy_distillation_promotion(
        seed_evaluations,
        config=config,
        lineage_id=lineage_id,
    )
    if not report["promotion_allowed"]:
        raise LegacyDistillationPromotionError(
            "legacy adapter promotion rejected: "
            + ", ".join(report["reasons"])
        )
    return report


# Discoverable aliases used by rollout callers.
legacy_distillation_promotion_gate = evaluate_legacy_distillation_promotion
require_legacy_embedding_adapter_promotion = require_legacy_distillation_promotion
LegacyEmbeddingDistillationConfig = LegacyDistillationConfig
LegacyEmbeddingDistillationLineage = LegacyDistillationLineage
LegacyEmbeddingDistillationResult = LegacyDistillationResult
LowRankLegacyEmbeddingAdapter = BoundedLowRankLegacyAdapter
distill_legacy_only_embedding_tails = distill_legacy_embedding_tails


__all__ = [
    "BoundedLowRankLegacyAdapter",
    "DEFAULT_LEGACY_ADAPTER_MAX_COUNT",
    "DEFAULT_LEGACY_ADAPTER_MAX_ROWS",
    "DEFAULT_LEGACY_ADAPTER_MINIMUM_SEEDS",
    "DEFAULT_LEGACY_ADAPTER_RANK",
    "DEFAULT_LEGACY_ADAPTER_INFLUENCE",
    "DirectBulkEmbeddingTransferError",
    "LEGACY_ADAPTER_BUNDLE_SCHEMA_VERSION",
    "LEGACY_ADAPTER_SCHEMA_VERSION",
    "LEGACY_DISTILLABLE_EMBEDDING_FIELDS",
    "LEGACY_DISTILLATION_GUARDRAIL_ALIASES",
    "LEGACY_DISTILLATION_OBJECTIVE_ALIASES",
    "LEGACY_DISTILLATION_PROMOTION_SCHEMA_VERSION",
    "LEGACY_DISTILLATION_SCHEMA_VERSION",
    "LEGACY_SAMPLE_MEMORY_FIELDS",
    "LegacyAdapterCapacityError",
    "LegacyDistillationConfig",
    "LegacyDistillationError",
    "LegacyDistillationLineage",
    "LegacyDistillationLineageError",
    "LegacyDistillationPromotionConfig",
    "LegacyDistillationPromotionError",
    "LegacyDistillationResult",
    "LegacyEmbeddingAdapterBundle",
    "LegacyEmbeddingDistillationConfig",
    "LegacyEmbeddingDistillationLineage",
    "LegacyEmbeddingDistillationResult",
    "LowRankLegacyEmbeddingAdapter",
    "distill_legacy_embedding_tail",
    "distill_legacy_embedding_tails",
    "distill_legacy_only_embedding_tails",
    "evaluate_legacy_distillation_promotion",
    "forbid_direct_bulk_embedding_replacement",
    "legacy_distillation_promotion_gate",
    "require_legacy_distillation_promotion",
    "require_legacy_embedding_adapter_promotion",
]
