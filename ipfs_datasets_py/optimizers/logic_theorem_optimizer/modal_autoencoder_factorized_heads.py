"""Typed, factorized semantic interaction heads for the modal autoencoder.

The historical autoencoder learned a separate value for every
``family || semantic-slot || LegalIR-view`` tuple.  That representation grows
with the Cartesian product of three vocabularies and made both CUDA gathering
and checkpoints needlessly expensive.  This module stores the same function as
typed additive terms plus a configurable CP low-rank interaction::

    y(f, s, v) = bias + family[f] + slot[s] + view[v]
                 + sum_r F[f,r] S[s,r] V[v,r] O[r,:]
                 + verified_sparse_residual[f,s,v]

Only observed cells whose measured reconstruction error exceeds the declared
tolerance may enter the residual.  Every residual carries a verification
receipt and the map has a hard capacity; it can therefore never become a
second unbounded interaction table.

The implementation deliberately depends only on NumPy.  Arrays are contiguous
and JSON/checkpoint encodings are deterministic, making the object suitable as
both a CPU reference and a source for the packed CUDA state.
"""

from __future__ import annotations

import hashlib
import json
import math
import zlib
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np

from .modal_autoencoder_tensor_state import TensorKeyKind, TypedParameterKey


FACTORIZED_HEAD_SCHEMA_VERSION = "modal-autoencoder-factorized-head-v1"
FACTORIZED_HEADS_SCHEMA_VERSION = "modal-autoencoder-factorized-heads-v1"
FACTORIZED_HEAD_CHECKPOINT_MAGIC = b"LIRMAEFH1"
DEFAULT_INTERACTION_RANK = 8
DEFAULT_RESIDUAL_CAPACITY = 4096
DEFAULT_MIGRATION_TOLERANCE = 1.0e-6
MINIMUM_CANONICAL_STATE_REDUCTION = 4.0

TRIPLE_EMBEDDING_HEAD = "family_semantic_slot_legal_ir_view_embedding_weights"
LEGAL_IR_VIEW_LOGIT_HEAD = "family_semantic_slot_legal_ir_view_logits"
FAMILY_LOGIT_HEAD = "semantic_slot_legal_ir_view_family_logits"
LEGACY_FACTORIZED_FIELDS = (
    TRIPLE_EMBEDDING_HEAD,
    LEGAL_IR_VIEW_LOGIT_HEAD,
    FAMILY_LOGIT_HEAD,
)


class FactorizedHeadError(RuntimeError):
    """Base class for factorized-head contract failures."""


class FactorizedMigrationError(FactorizedHeadError):
    """Raised when a legacy table cannot be migrated within its contract."""


class ResidualCapacityError(FactorizedMigrationError, OverflowError):
    """Raised before a bounded residual could overflow."""


class UnverifiedResidualError(FactorizedHeadError, ValueError):
    """Raised when a caller attempts to add an unverified exception."""


class FactorizedQualityGateError(FactorizedHeadError):
    """Raised by the enforcing quality-gate API for an unsafe ablation."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _finite_array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.ascontiguousarray(np.asarray(value, dtype=np.float64))
    if result.size == 0 and math.prod(shape) == 0:
        result = np.ascontiguousarray(result.reshape(shape))
    if result.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {result.shape}")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result


def _typed_values(kind: TensorKeyKind, values: Iterable[str]) -> tuple[str, ...]:
    keys = {TypedParameterKey(kind, str(value)) for value in values}
    return tuple(key.value for key in sorted(keys, key=lambda item: item.stable_id))


def _triple(value: Sequence[Any]) -> tuple[str, str, str]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError("interaction key must be a (family, semantic_slot, legal_ir_view) triple")
    family = TypedParameterKey.family(str(value[0])).value
    slot = TypedParameterKey.semantic_slot(str(value[1])).value
    view = TypedParameterKey.legal_ir_view(str(value[2])).value
    return family, slot, view


@dataclass(frozen=True, slots=True)
class FactorizedHeadConfig:
    """Architecture and migration controls for one semantic head."""

    rank: int = DEFAULT_INTERACTION_RANK
    residual_capacity: int = DEFAULT_RESIDUAL_CAPACITY
    tolerance: float = DEFAULT_MIGRATION_TOLERANCE
    additive_enabled: bool = True
    low_rank_enabled: bool = True
    residual_enabled: bool = True
    fitting_steps: int = 600
    learning_rate: float = 0.035
    regularization: float = 1.0e-8
    seed: int = 0

    def __post_init__(self) -> None:
        if int(self.rank) < 0:
            raise ValueError("rank must be non-negative")
        if int(self.residual_capacity) < 0:
            raise ValueError("residual_capacity must be non-negative")
        if not math.isfinite(float(self.tolerance)) or float(self.tolerance) < 0.0:
            raise ValueError("tolerance must be finite and non-negative")
        if int(self.fitting_steps) < 0:
            raise ValueError("fitting_steps must be non-negative")
        if not math.isfinite(float(self.learning_rate)) or float(self.learning_rate) <= 0.0:
            raise ValueError("learning_rate must be finite and positive")
        if not math.isfinite(float(self.regularization)) or float(self.regularization) < 0.0:
            raise ValueError("regularization must be finite and non-negative")

    @property
    def effective_rank(self) -> int:
        return int(self.rank) if self.low_rank_enabled else 0

    @property
    def effective_residual_capacity(self) -> int:
        return int(self.residual_capacity) if self.residual_enabled else 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "additive_enabled": bool(self.additive_enabled),
            "fitting_steps": int(self.fitting_steps),
            "learning_rate": float(self.learning_rate),
            "low_rank_enabled": bool(self.low_rank_enabled),
            "rank": int(self.rank),
            "regularization": float(self.regularization),
            "residual_capacity": int(self.residual_capacity),
            "residual_enabled": bool(self.residual_enabled),
            "seed": int(self.seed),
            "tolerance": float(self.tolerance),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactorizedHeadConfig":
        return cls(
            rank=int(value.get("rank", DEFAULT_INTERACTION_RANK)),
            residual_capacity=int(value.get("residual_capacity", DEFAULT_RESIDUAL_CAPACITY)),
            tolerance=float(value.get("tolerance", DEFAULT_MIGRATION_TOLERANCE)),
            additive_enabled=bool(value.get("additive_enabled", True)),
            low_rank_enabled=bool(value.get("low_rank_enabled", True)),
            residual_enabled=bool(value.get("residual_enabled", True)),
            fitting_steps=int(value.get("fitting_steps", 600)),
            learning_rate=float(value.get("learning_rate", 0.035)),
            regularization=float(value.get("regularization", 1.0e-8)),
            seed=int(value.get("seed", 0)),
        )


@dataclass(frozen=True, slots=True)
class VerifiedResidual:
    """One bounded exception, tied to measured migration evidence."""

    family: str
    semantic_slot: str
    legal_ir_view: str
    values: tuple[float, ...]
    verification_id: str
    observed_error: float
    tolerance: float

    def __post_init__(self) -> None:
        _triple((self.family, self.semantic_slot, self.legal_ir_view))
        if not str(self.verification_id).strip():
            raise UnverifiedResidualError("residual verification_id must be non-empty")
        if not self.values or not all(math.isfinite(float(value)) for value in self.values):
            raise ValueError("residual values must be a non-empty finite vector")
        if float(self.observed_error) <= float(self.tolerance):
            raise UnverifiedResidualError(
                "residual is not a verified exception: observed error does not exceed tolerance"
            )

    @property
    def key(self) -> tuple[str, str, str]:
        return self.family, self.semantic_slot, self.legal_ir_view

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "legal_ir_view": self.legal_ir_view,
            "observed_error": float(self.observed_error),
            "semantic_slot": self.semantic_slot,
            "tolerance": float(self.tolerance),
            "values": [float(value) for value in self.values],
            "verification_id": self.verification_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerifiedResidual":
        return cls(
            family=str(value["family"]),
            semantic_slot=str(value["semantic_slot"]),
            legal_ir_view=str(value["legal_ir_view"]),
            values=tuple(float(item) for item in value.get("values", ())),
            verification_id=str(value.get("verification_id") or ""),
            observed_error=float(value.get("observed_error", 0.0)),
            tolerance=float(value.get("tolerance", 0.0)),
        )


class FactorizedSemanticInteractionHead:
    """A bounded typed family/slot/view interaction head."""

    def __init__(
        self,
        *,
        name: str,
        families: Sequence[str],
        semantic_slots: Sequence[str],
        legal_ir_views: Sequence[str],
        output_labels: Sequence[str],
        config: Optional[FactorizedHeadConfig] = None,
        bias: Any = None,
        family_embeddings: Any = None,
        semantic_slot_embeddings: Any = None,
        legal_ir_view_embeddings: Any = None,
        family_factors: Any = None,
        semantic_slot_factors: Any = None,
        legal_ir_view_factors: Any = None,
        output_factors: Any = None,
        residuals: Sequence[VerifiedResidual] = (),
    ) -> None:
        self.name = str(name).strip()
        if not self.name:
            raise ValueError("head name must be non-empty")
        self.config = config or FactorizedHeadConfig()
        raw_families = tuple(TypedParameterKey.family(str(value)).value for value in families)
        raw_slots = tuple(TypedParameterKey.semantic_slot(str(value)).value for value in semantic_slots)
        raw_views = tuple(TypedParameterKey.legal_ir_view(str(value)).value for value in legal_ir_views)
        if len(set(raw_families)) != len(raw_families):
            raise ValueError("families must be unique")
        if len(set(raw_slots)) != len(raw_slots):
            raise ValueError("semantic_slots must be unique")
        if len(set(raw_views)) != len(raw_views):
            raise ValueError("legal_ir_views must be unique")
        self.families = _typed_values(TensorKeyKind.FAMILY, raw_families)
        self.semantic_slots = _typed_values(TensorKeyKind.SEMANTIC_SLOT, raw_slots)
        self.legal_ir_views = _typed_values(TensorKeyKind.LEGAL_IR_VIEW, raw_views)
        # Output dimensions are positional (embedding dimensions are commonly
        # named "0", "1", ...), so validate their type without reordering.
        self.output_labels = tuple(
            TypedParameterKey.target(str(value)).value for value in output_labels
        )
        if len(set(self.output_labels)) != len(self.output_labels):
            raise ValueError("output_labels must be unique")
        if not self.output_labels:
            raise ValueError("output_labels must be non-empty")
        self._family_index = {value: index for index, value in enumerate(self.families)}
        self._slot_index = {value: index for index, value in enumerate(self.semantic_slots)}
        self._view_index = {value: index for index, value in enumerate(self.legal_ir_views)}
        output_width = len(self.output_labels)
        rank = self.config.effective_rank
        zeros = lambda shape: np.zeros(shape, dtype=np.float64)
        self.bias = _finite_array(zeros((output_width,)) if bias is None else bias, (output_width,), "bias")
        def ordered_rows(value: Any, raw: tuple[str, ...], ordered: tuple[str, ...]) -> Any:
            if value is None:
                return None
            array = np.asarray(value, dtype=np.float64)
            if array.ndim != 2 or array.shape[0] != len(raw):
                return value
            index = {name: position for position, name in enumerate(raw)}
            return array[[index[name] for name in ordered]]

        family_embeddings = ordered_rows(family_embeddings, raw_families, self.families)
        semantic_slot_embeddings = ordered_rows(semantic_slot_embeddings, raw_slots, self.semantic_slots)
        legal_ir_view_embeddings = ordered_rows(legal_ir_view_embeddings, raw_views, self.legal_ir_views)
        family_factors = ordered_rows(family_factors, raw_families, self.families)
        semantic_slot_factors = ordered_rows(semantic_slot_factors, raw_slots, self.semantic_slots)
        legal_ir_view_factors = ordered_rows(legal_ir_view_factors, raw_views, self.legal_ir_views)
        self.family_embeddings = _finite_array(
            zeros((len(self.families), output_width)) if family_embeddings is None else family_embeddings,
            (len(self.families), output_width), "family_embeddings",
        )
        self.semantic_slot_embeddings = _finite_array(
            zeros((len(self.semantic_slots), output_width)) if semantic_slot_embeddings is None else semantic_slot_embeddings,
            (len(self.semantic_slots), output_width), "semantic_slot_embeddings",
        )
        self.legal_ir_view_embeddings = _finite_array(
            zeros((len(self.legal_ir_views), output_width)) if legal_ir_view_embeddings is None else legal_ir_view_embeddings,
            (len(self.legal_ir_views), output_width), "legal_ir_view_embeddings",
        )
        self.family_factors = _finite_array(
            zeros((len(self.families), rank)) if family_factors is None else family_factors,
            (len(self.families), rank), "family_factors",
        )
        self.semantic_slot_factors = _finite_array(
            zeros((len(self.semantic_slots), rank)) if semantic_slot_factors is None else semantic_slot_factors,
            (len(self.semantic_slots), rank), "semantic_slot_factors",
        )
        self.legal_ir_view_factors = _finite_array(
            zeros((len(self.legal_ir_views), rank)) if legal_ir_view_factors is None else legal_ir_view_factors,
            (len(self.legal_ir_views), rank), "legal_ir_view_factors",
        )
        self.output_factors = _finite_array(
            zeros((rank, output_width)) if output_factors is None else output_factors,
            (rank, output_width), "output_factors",
        )
        self._residuals: Dict[tuple[str, str, str], VerifiedResidual] = {}
        for residual in residuals:
            self.add_verified_residual(residual)

    @property
    def rank(self) -> int:
        return self.config.effective_rank

    @property
    def residual_count(self) -> int:
        return len(self._residuals)

    @property
    def residuals(self) -> tuple[VerifiedResidual, ...]:
        return tuple(self._residuals[key] for key in sorted(self._residuals))

    @property
    def typed_families(self) -> tuple[TypedParameterKey, ...]:
        return tuple(TypedParameterKey.family(value) for value in self.families)

    @property
    def typed_semantic_slots(self) -> tuple[TypedParameterKey, ...]:
        return tuple(TypedParameterKey.semantic_slot(value) for value in self.semantic_slots)

    @property
    def typed_legal_ir_views(self) -> tuple[TypedParameterKey, ...]:
        return tuple(TypedParameterKey.legal_ir_view(value) for value in self.legal_ir_views)

    @property
    def parameter_count(self) -> int:
        arrays = (
            self.bias,
            self.family_embeddings,
            self.semantic_slot_embeddings,
            self.legal_ir_view_embeddings,
            self.family_factors,
            self.semantic_slot_factors,
            self.legal_ir_view_factors,
            self.output_factors,
        )
        return sum(int(array.size) for array in arrays) + sum(len(item.values) for item in self._residuals.values())

    @property
    def parameter_bytes(self) -> int:
        return self.parameter_count * np.dtype(np.float64).itemsize

    def _indices(self, family: str, semantic_slot: str, legal_ir_view: str) -> tuple[int, int, int]:
        triple = _triple((family, semantic_slot, legal_ir_view))
        try:
            return (
                self._family_index[triple[0]],
                self._slot_index[triple[1]],
                self._view_index[triple[2]],
            )
        except KeyError as exc:
            raise KeyError(f"unknown typed interaction key for {self.name}: {exc.args[0]!r}") from exc

    def forward_base(self, family: str, semantic_slot: str, legal_ir_view: str) -> np.ndarray:
        """Evaluate additive and low-rank terms without the sparse residual."""

        family_index, slot_index, view_index = self._indices(family, semantic_slot, legal_ir_view)
        value = self.bias.copy()
        if self.config.additive_enabled:
            value += self.family_embeddings[family_index]
            value += self.semantic_slot_embeddings[slot_index]
            value += self.legal_ir_view_embeddings[view_index]
        if self.rank:
            latent = (
                self.family_factors[family_index]
                * self.semantic_slot_factors[slot_index]
                * self.legal_ir_view_factors[view_index]
            )
            value += latent @ self.output_factors
        return value

    def forward(self, family: str, semantic_slot: str, legal_ir_view: str) -> np.ndarray:
        """Evaluate one triple and return a defensive float64 vector."""

        key = _triple((family, semantic_slot, legal_ir_view))
        value = self.forward_base(*key)
        residual = self._residuals.get(key)
        if residual is not None:
            value += np.asarray(residual.values, dtype=np.float64)
        return value

    __call__ = forward

    def scalar(self, family: str, semantic_slot: str, legal_ir_view: str) -> float:
        if len(self.output_labels) != 1:
            raise ValueError(f"head {self.name!r} has {len(self.output_labels)} outputs")
        return float(self.forward(family, semantic_slot, legal_ir_view)[0])

    def forward_batch(self, triples: Sequence[Sequence[str]]) -> np.ndarray:
        if not triples:
            return np.empty((0, len(self.output_labels)), dtype=np.float64)
        return np.ascontiguousarray(np.vstack([self.forward(*_triple(item)) for item in triples]))

    def add_verified_residual(self, residual: VerifiedResidual) -> None:
        if not isinstance(residual, VerifiedResidual):
            raise TypeError("residual must be VerifiedResidual")
        key = residual.key
        self._indices(*key)
        if len(residual.values) != len(self.output_labels):
            raise ValueError("residual width does not match head output width")
        if key not in self._residuals and len(self._residuals) >= self.config.effective_residual_capacity:
            raise ResidualCapacityError(
                f"head {self.name!r} residual capacity {self.config.effective_residual_capacity} exceeded"
            )
        self._residuals[key] = residual

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arrays": {
                "bias": self.bias.tolist(),
                "family_embeddings": self.family_embeddings.tolist(),
                "family_factors": self.family_factors.tolist(),
                "legal_ir_view_embeddings": self.legal_ir_view_embeddings.tolist(),
                "legal_ir_view_factors": self.legal_ir_view_factors.tolist(),
                "output_factors": self.output_factors.tolist(),
                "semantic_slot_embeddings": self.semantic_slot_embeddings.tolist(),
                "semantic_slot_factors": self.semantic_slot_factors.tolist(),
            },
            "config": self.config.to_dict(),
            "families": list(self.families),
            "legal_ir_views": list(self.legal_ir_views),
            "name": self.name,
            "output_labels": list(self.output_labels),
            "residuals": [item.to_dict() for item in self.residuals],
            "schema_version": FACTORIZED_HEAD_SCHEMA_VERSION,
            "semantic_slots": list(self.semantic_slots),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactorizedSemanticInteractionHead":
        if str(value.get("schema_version") or "") != FACTORIZED_HEAD_SCHEMA_VERSION:
            raise ValueError("unsupported factorized head schema")
        arrays = value.get("arrays")
        if not isinstance(arrays, Mapping):
            raise ValueError("factorized head arrays are missing")
        return cls(
            name=str(value.get("name") or ""),
            families=tuple(str(item) for item in value.get("families", ())),
            semantic_slots=tuple(str(item) for item in value.get("semantic_slots", ())),
            legal_ir_views=tuple(str(item) for item in value.get("legal_ir_views", ())),
            output_labels=tuple(str(item) for item in value.get("output_labels", ())),
            config=FactorizedHeadConfig.from_dict(value.get("config", {})),
            bias=arrays.get("bias", ()),
            family_embeddings=arrays.get("family_embeddings", ()),
            semantic_slot_embeddings=arrays.get("semantic_slot_embeddings", ()),
            legal_ir_view_embeddings=arrays.get("legal_ir_view_embeddings", ()),
            family_factors=arrays.get("family_factors", ()),
            semantic_slot_factors=arrays.get("semantic_slot_factors", ()),
            legal_ir_view_factors=arrays.get("legal_ir_view_factors", ()),
            output_factors=arrays.get("output_factors", ()),
            residuals=tuple(VerifiedResidual.from_dict(item) for item in value.get("residuals", ())),
        )

    @property
    def identity(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class HeadMigrationReport:
    head_name: str
    observed_cell_count: int
    observed_scalar_count: int
    factorized_parameter_count: int
    legacy_parameter_bytes: int
    factorized_parameter_bytes: int
    legacy_checkpoint_bytes: int
    factorized_checkpoint_bytes: int
    max_absolute_error: float
    mean_absolute_error: float
    tolerance: float
    residual_count: int
    rank: int

    @property
    def parameter_reduction_ratio(self) -> float:
        if self.factorized_parameter_bytes <= 0:
            return math.inf if self.legacy_parameter_bytes else 0.0
        return self.legacy_parameter_bytes / self.factorized_parameter_bytes

    @property
    def checkpoint_reduction_ratio(self) -> float:
        if self.factorized_checkpoint_bytes <= 0:
            return math.inf if self.legacy_checkpoint_bytes else 0.0
        return self.legacy_checkpoint_bytes / self.factorized_checkpoint_bytes

    @property
    def logits_preserved(self) -> bool:
        return self.max_absolute_error <= self.tolerance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_reduction_ratio": round(self.checkpoint_reduction_ratio, 12),
            "factorized_checkpoint_bytes": self.factorized_checkpoint_bytes,
            "factorized_parameter_bytes": self.factorized_parameter_bytes,
            "factorized_parameter_count": self.factorized_parameter_count,
            "head_name": self.head_name,
            "legacy_checkpoint_bytes": self.legacy_checkpoint_bytes,
            "legacy_parameter_bytes": self.legacy_parameter_bytes,
            "logits_preserved": self.logits_preserved,
            "max_absolute_error": self.max_absolute_error,
            "mean_absolute_error": self.mean_absolute_error,
            "observed_cell_count": self.observed_cell_count,
            "observed_scalar_count": self.observed_scalar_count,
            "parameter_reduction_ratio": round(self.parameter_reduction_ratio, 12),
            "rank": self.rank,
            "residual_count": self.residual_count,
            "tolerance": self.tolerance,
        }


def _fit_additive(
    targets: np.ndarray,
    family_indices: np.ndarray,
    slot_indices: np.ndarray,
    view_indices: np.ndarray,
    counts: tuple[int, int, int],
    enabled: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    width = targets.shape[1]
    bias = targets.mean(axis=0) if len(targets) else np.zeros(width, dtype=np.float64)
    family = np.zeros((counts[0], width), dtype=np.float64)
    slot = np.zeros((counts[1], width), dtype=np.float64)
    view = np.zeros((counts[2], width), dtype=np.float64)
    if not enabled or not len(targets):
        return bias, family, slot, view
    # Backfitting is deterministic and handles sparse/non-Cartesian tables.
    for _ in range(24):
        for axis_indices, current, other_a, other_b in (
            (family_indices, family, slot[slot_indices], view[view_indices]),
            (slot_indices, slot, family[family_indices], view[view_indices]),
            (view_indices, view, family[family_indices], slot[slot_indices]),
        ):
            residual = targets - bias - other_a - other_b
            sums = np.zeros_like(current)
            axis_counts = np.zeros(len(current), dtype=np.float64)
            np.add.at(sums, axis_indices, residual)
            np.add.at(axis_counts, axis_indices, 1.0)
            current[:] = sums / np.maximum(axis_counts[:, None], 1.0)
            # Center identifiable terms so serialization is stable.
            populated = axis_counts > 0
            if populated.any():
                center = current[populated].mean(axis=0)
                current[populated] -= center
                bias += center
    return bias, family, slot, view


def _fit_cp_interaction(
    residual: np.ndarray,
    family_indices: np.ndarray,
    slot_indices: np.ndarray,
    view_indices: np.ndarray,
    counts: tuple[int, int, int],
    width: int,
    config: FactorizedHeadConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rank = config.effective_rank
    shapes = ((counts[0], rank), (counts[1], rank), (counts[2], rank), (rank, width))
    if rank == 0 or not len(residual) or not np.any(np.abs(residual) > config.tolerance):
        return tuple(np.zeros(shape, dtype=np.float64) for shape in shapes)  # type: ignore[return-value]
    rng = np.random.default_rng(int(config.seed))
    # Complete canonical products admit a substantially more stable tensor
    # power/deflation fit than generic sparse gradient descent.  It recovers an
    # exact rank-one interaction to floating-point precision and provides a
    # deterministic HOSVD-style initialization for higher ranks.
    product_size = counts[0] * counts[1] * counts[2]
    coordinate_count = len(
        set(zip(family_indices.tolist(), slot_indices.tolist(), view_indices.tolist()))
    )
    if len(residual) == product_size and coordinate_count == product_size:
        tensor = np.zeros((counts[0], counts[1], counts[2], width), dtype=np.float64)
        tensor[family_indices, slot_indices, view_indices, :] = residual
        family_result = np.zeros(shapes[0], dtype=np.float64)
        slot_result = np.zeros(shapes[1], dtype=np.float64)
        view_result = np.zeros(shapes[2], dtype=np.float64)
        output_result = np.zeros(shapes[3], dtype=np.float64)

        def unit(value: np.ndarray) -> np.ndarray:
            norm = float(np.linalg.norm(value))
            if norm <= 1.0e-15:
                return np.zeros_like(value)
            return value / norm

        working = tensor.copy()
        for component in range(rank):
            # Mode-wise singular vectors make initialization deterministic;
            # random fallback only applies to an entirely degenerate mode.
            vectors = []
            for axis, dimension in enumerate(working.shape):
                unfolded = np.moveaxis(working, axis, 0).reshape(dimension, -1)
                if np.any(unfolded):
                    vectors.append(unit(np.linalg.svd(unfolded, full_matrices=False)[0][:, 0]))
                else:
                    vectors.append(unit(rng.normal(size=dimension)))
            family_vector, slot_vector, view_vector, output_vector = vectors
            for _ in range(max(12, min(100, int(config.fitting_steps)))):
                prior = (
                    family_vector.copy(), slot_vector.copy(),
                    view_vector.copy(), output_vector.copy(),
                )
                family_vector = unit(np.einsum("fsvo,s,v,o->f", working, slot_vector, view_vector, output_vector, optimize=True))
                slot_vector = unit(np.einsum("fsvo,f,v,o->s", working, family_vector, view_vector, output_vector, optimize=True))
                view_vector = unit(np.einsum("fsvo,f,s,o->v", working, family_vector, slot_vector, output_vector, optimize=True))
                output_vector = unit(np.einsum("fsvo,f,s,v->o", working, family_vector, slot_vector, view_vector, optimize=True))
                change = max(
                    min(float(np.linalg.norm(current - old)), float(np.linalg.norm(current + old)))
                    for current, old in zip(
                        (family_vector, slot_vector, view_vector, output_vector), prior
                    )
                )
                if change <= 1.0e-12:
                    break
            coefficient = float(np.einsum(
                "fsvo,f,s,v,o->", working,
                family_vector, slot_vector, view_vector, output_vector,
                optimize=True,
            ))
            family_result[:, component] = family_vector
            slot_result[:, component] = slot_vector
            view_result[:, component] = view_vector
            output_result[component, :] = coefficient * output_vector
            working -= coefficient * np.einsum(
                "f,s,v,o->fsvo",
                family_vector, slot_vector, view_vector, output_vector,
                optimize=True,
            )
            if float(np.max(np.abs(working))) <= config.tolerance * 0.2:
                break
        return (
            np.ascontiguousarray(family_result),
            np.ascontiguousarray(slot_result),
            np.ascontiguousarray(view_result),
            np.ascontiguousarray(output_result),
        )
    scale = max(1.0e-3, float(np.std(residual)) ** 0.25 * 0.35)
    factors = [rng.normal(0.0, scale, size=shape) for shape in shapes]
    moments = [np.zeros_like(item) for item in factors]
    variances = [np.zeros_like(item) for item in factors]
    beta1, beta2 = 0.9, 0.999
    denominator = float(max(1, len(residual) * width))
    best_loss = math.inf
    best = [item.copy() for item in factors]
    stale = 0
    for step in range(1, int(config.fitting_steps) + 1):
        family, slot, view, output = factors
        latent = family[family_indices] * slot[slot_indices] * view[view_indices]
        prediction = latent @ output
        difference = prediction - residual
        loss = float(np.mean(difference * difference))
        if loss < best_loss:
            best_loss = loss
            best = [item.copy() for item in factors]
            stale = 0
        else:
            stale += 1
        if math.sqrt(max(0.0, loss)) <= config.tolerance * 0.2 or stale >= 100:
            break
        projected = difference @ output.T
        gradients = [np.zeros_like(family), np.zeros_like(slot), np.zeros_like(view)]
        np.add.at(gradients[0], family_indices, projected * slot[slot_indices] * view[view_indices])
        np.add.at(gradients[1], slot_indices, projected * family[family_indices] * view[view_indices])
        np.add.at(gradients[2], view_indices, projected * family[family_indices] * slot[slot_indices])
        gradients.append(latent.T @ difference)
        # Normalize gathered gradients by observations rather than vocabulary.
        gradients = [gradient / denominator + config.regularization * parameter for gradient, parameter in zip(gradients, factors)]
        learning_rate = float(config.learning_rate) * min(1.0, 20.0 / math.sqrt(step + 19.0))
        for index, gradient in enumerate(gradients):
            np.clip(gradient, -10.0, 10.0, out=gradient)
            moments[index] = beta1 * moments[index] + (1.0 - beta1) * gradient
            variances[index] = beta2 * variances[index] + (1.0 - beta2) * gradient * gradient
            corrected_m = moments[index] / (1.0 - beta1**step)
            corrected_v = variances[index] / (1.0 - beta2**step)
            factors[index] -= learning_rate * corrected_m / (np.sqrt(corrected_v) + 1.0e-8)
    return tuple(np.ascontiguousarray(item) for item in best)  # type: ignore[return-value]


def factorize_interaction_records(
    records: Mapping[Sequence[str], Sequence[float] | float],
    *,
    name: str,
    config: Optional[FactorizedHeadConfig] = None,
    output_labels: Optional[Sequence[str]] = None,
    verified_exceptions: Optional[Mapping[Sequence[str], str]] = None,
) -> tuple[FactorizedSemanticInteractionHead, HeadMigrationReport]:
    """Fit one typed head and preserve observed values within ``tolerance``.

    Residual verification is intrinsic during migration: the receipt binds the
    source-table digest, tuple, measured error, and tolerance.  Supplying
    ``verified_exceptions`` changes this to an external allow-list and makes the
    migration fail closed for any other exception.
    """

    effective = config or FactorizedHeadConfig()
    normalized: Dict[tuple[str, str, str], tuple[float, ...]] = {}
    for raw_key, raw_value in records.items():
        key = _triple(raw_key)
        values = (float(raw_value),) if isinstance(raw_value, (int, float, np.number)) else tuple(float(item) for item in raw_value)
        if not values or not all(math.isfinite(item) for item in values):
            raise ValueError(f"record {key!r} must contain a non-empty finite value vector")
        if key in normalized:
            raise ValueError(f"duplicate interaction record: {key!r}")
        normalized[key] = values
    widths = {len(value) for value in normalized.values()}
    if len(widths) > 1:
        raise ValueError("all interaction records must have the same output width")
    width = next(iter(widths), len(tuple(output_labels or ())) or 1)
    labels = tuple(output_labels or tuple(str(index) for index in range(width)))
    if len(labels) != width:
        raise ValueError("output_labels width does not match records")
    families = _typed_values(TensorKeyKind.FAMILY, (key[0] for key in normalized))
    slots = _typed_values(TensorKeyKind.SEMANTIC_SLOT, (key[1] for key in normalized))
    views = _typed_values(TensorKeyKind.LEGAL_IR_VIEW, (key[2] for key in normalized))
    f_index = {value: index for index, value in enumerate(families)}
    s_index = {value: index for index, value in enumerate(slots)}
    v_index = {value: index for index, value in enumerate(views)}
    ordered = sorted(normalized, key=lambda key: (
        TypedParameterKey.family(key[0]).stable_id,
        TypedParameterKey.semantic_slot(key[1]).stable_id,
        TypedParameterKey.legal_ir_view(key[2]).stable_id,
    ))
    family_indices = np.asarray([f_index[key[0]] for key in ordered], dtype=np.int64)
    slot_indices = np.asarray([s_index[key[1]] for key in ordered], dtype=np.int64)
    view_indices = np.asarray([v_index[key[2]] for key in ordered], dtype=np.int64)
    targets = np.ascontiguousarray(np.asarray([normalized[key] for key in ordered], dtype=np.float64).reshape((-1, width)))
    def fit_head(mask: np.ndarray) -> FactorizedSemanticInteractionHead:
        selected_targets = targets[mask]
        selected_families = family_indices[mask]
        selected_slots = slot_indices[mask]
        selected_views = view_indices[mask]
        bias, family_add, slot_add, view_add = _fit_additive(
            selected_targets, selected_families, selected_slots, selected_views,
            (len(families), len(slots), len(views)), effective.additive_enabled,
        )
        additive_prediction = (
            bias
            + family_add[selected_families]
            + slot_add[selected_slots]
            + view_add[selected_views]
        )
        factors = _fit_cp_interaction(
            selected_targets - additive_prediction,
            selected_families, selected_slots, selected_views,
            (len(families), len(slots), len(views)), width, effective,
        )
        return FactorizedSemanticInteractionHead(
            name=name, families=families, semantic_slots=slots, legal_ir_views=views,
            output_labels=labels, config=effective, bias=bias,
            family_embeddings=family_add, semantic_slot_embeddings=slot_add,
            legal_ir_view_embeddings=view_add, family_factors=factors[0],
            semantic_slot_factors=factors[1], legal_ir_view_factors=factors[2],
            output_factors=factors[3],
        )

    active_mask = np.ones(len(ordered), dtype=np.bool_)
    head = fit_head(active_mask)
    source_digest = _digest({"name": name, "records": [[*key, list(normalized[key])] for key in ordered]})
    exception_receipts = {_triple(key): str(value) for key, value in (verified_exceptions or {}).items()}
    def measured_errors() -> list[tuple[tuple[str, str, str], np.ndarray, float]]:
        result = []
        for key in ordered:
            difference = np.asarray(normalized[key], dtype=np.float64) - head.forward_base(*key)
            error = float(np.max(np.abs(difference)))
            if error > effective.tolerance:
                result.append((key, difference, error))
        return result

    base_errors = measured_errors()
    capacity = effective.effective_residual_capacity
    # A genuine isolated exception biases least-squares additive terms and may
    # make several ordinary cells appear outside a tight tolerance.  Before
    # declaring overflow, trim at most the bounded residual capacity by largest
    # measured error and refit the factorized component.  The trimmed cells are
    # still re-measured and receipt-bound below; they never silently disappear.
    if len(base_errors) > capacity and capacity > 0:
        excluded = {
            key for key, _difference, _error in sorted(
                base_errors, key=lambda item: (-item[2], item[0])
            )[:capacity]
        }
        active_mask = np.asarray([key not in excluded for key in ordered], dtype=np.bool_)
        if active_mask.any():
            head = fit_head(active_mask)
            base_errors = measured_errors()
    if base_errors and not effective.residual_enabled:
        raise FactorizedMigrationError(
            f"head {name!r} has {len(base_errors)} cells above tolerance with residuals disabled"
        )
    if len(base_errors) > capacity:
        raise ResidualCapacityError(
            f"head {name!r} needs {len(base_errors)} verified residuals, capacity is {capacity}"
        )
    for key, difference, error in base_errors:
        if verified_exceptions is not None:
            receipt = exception_receipts.get(key, "")
            if not receipt:
                raise UnverifiedResidualError(f"interaction exception {key!r} is not externally verified")
        else:
            receipt = "migration-verification-" + _digest({
                "error": error, "key": key, "source_digest": source_digest,
                "tolerance": effective.tolerance,
            })[:32]
        head.add_verified_residual(VerifiedResidual(
            family=key[0], semantic_slot=key[1], legal_ir_view=key[2],
            values=tuple(float(item) for item in difference),
            verification_id=receipt, observed_error=error, tolerance=effective.tolerance,
        ))
    final_errors = [
        float(np.max(np.abs(head.forward(*key) - np.asarray(normalized[key], dtype=np.float64))))
        for key in ordered
    ]
    legacy_payload = {"records": [[*key, list(normalized[key])] for key in ordered]}
    factorized_payload = head.to_dict()
    report = HeadMigrationReport(
        head_name=name,
        observed_cell_count=len(ordered),
        observed_scalar_count=int(targets.size),
        factorized_parameter_count=head.parameter_count,
        legacy_parameter_bytes=int(targets.size) * 8,
        factorized_parameter_bytes=head.parameter_bytes,
        legacy_checkpoint_bytes=len(zlib.compress(_canonical_bytes(legacy_payload), 9)),
        factorized_checkpoint_bytes=len(zlib.compress(_canonical_bytes(factorized_payload), 9)),
        max_absolute_error=max(final_errors, default=0.0),
        mean_absolute_error=float(np.mean(final_errors)) if final_errors else 0.0,
        tolerance=float(effective.tolerance),
        residual_count=head.residual_count,
        rank=head.rank,
    )
    if not report.logits_preserved:
        raise FactorizedMigrationError(
            f"head {name!r} migration error {report.max_absolute_error} exceeds {report.tolerance}"
        )
    return head, report


@dataclass(frozen=True, slots=True)
class FactorizedSemanticInteractionHeads:
    """The three high-cardinality legacy views backed by typed heads."""

    heads: Mapping[str, FactorizedSemanticInteractionHead]
    migration_reports: Mapping[str, HeadMigrationReport] = field(default_factory=dict)
    source_state_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = {str(name): head for name, head in self.heads.items()}
        if any(not isinstance(head, FactorizedSemanticInteractionHead) for head in normalized.values()):
            raise TypeError("all heads must be FactorizedSemanticInteractionHead instances")
        object.__setattr__(self, "heads", dict(sorted(normalized.items())))
        object.__setattr__(self, "migration_reports", dict(sorted(self.migration_reports.items())))

    @property
    def parameter_count(self) -> int:
        return sum(head.parameter_count for head in self.heads.values())

    @property
    def parameter_bytes(self) -> int:
        return sum(head.parameter_bytes for head in self.heads.values())

    @property
    def ranks(self) -> Dict[str, int]:
        return {name: head.rank for name, head in self.heads.items()}

    @property
    def residual_counts(self) -> Dict[str, int]:
        return {name: head.residual_count for name, head in self.heads.items()}

    def embedding(self, family: str, semantic_slot: str, legal_ir_view: str) -> list[float]:
        head = self.heads[TRIPLE_EMBEDDING_HEAD]
        return [float(value) for value in head.forward(family, semantic_slot, legal_ir_view)]

    def legal_ir_view_logit(self, family: str, semantic_slot: str, legal_ir_view: str) -> float:
        return self.heads[LEGAL_IR_VIEW_LOGIT_HEAD].scalar(family, semantic_slot, legal_ir_view)

    def family_logit(self, family: str, semantic_slot: str, legal_ir_view: str) -> float:
        return self.heads[FAMILY_LOGIT_HEAD].scalar(family, semantic_slot, legal_ir_view)

    def legal_ir_view_logits(
        self, family: str, semantic_slot: str, legal_ir_views: Optional[Sequence[str]] = None,
    ) -> Dict[str, float]:
        head = self.heads[LEGAL_IR_VIEW_LOGIT_HEAD]
        return {view: head.scalar(family, semantic_slot, view) for view in (legal_ir_views or head.legal_ir_views)}

    def family_logits(
        self, semantic_slot: str, legal_ir_view: str, families: Optional[Sequence[str]] = None,
    ) -> Dict[str, float]:
        head = self.heads[FAMILY_LOGIT_HEAD]
        return {family: head.scalar(family, semantic_slot, legal_ir_view) for family in (families or head.families)}

    def to_dict(self, *, include_reports: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "heads": {name: head.to_dict() for name, head in self.heads.items()},
            "metadata": dict(self.metadata),
            "schema_version": FACTORIZED_HEADS_SCHEMA_VERSION,
            "source_state_digest": self.source_state_digest,
        }
        if include_reports:
            result["migration_reports"] = {name: report.to_dict() for name, report in self.migration_reports.items()}
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactorizedSemanticInteractionHeads":
        if str(value.get("schema_version") or "") != FACTORIZED_HEADS_SCHEMA_VERSION:
            raise ValueError("unsupported factorized heads schema")
        raw_heads = value.get("heads")
        if not isinstance(raw_heads, Mapping):
            raise ValueError("factorized heads payload is missing heads")
        # Reports are audit output and are intentionally not trusted on load;
        # callers can recompute verification against canonical observations.
        return cls(
            heads={str(name): FactorizedSemanticInteractionHead.from_dict(head) for name, head in raw_heads.items()},
            source_state_digest=str(value.get("source_state_digest") or ""),
            metadata=dict(value.get("metadata") or {}),
        )

    def to_checkpoint_bytes(self) -> bytes:
        payload = zlib.compress(_canonical_bytes(self.to_dict(include_reports=False)), 9)
        checksum = hashlib.sha256(payload).digest()
        return FACTORIZED_HEAD_CHECKPOINT_MAGIC + checksum + payload

    @classmethod
    def from_checkpoint_bytes(cls, value: bytes) -> "FactorizedSemanticInteractionHeads":
        if not value.startswith(FACTORIZED_HEAD_CHECKPOINT_MAGIC):
            raise ValueError("not a factorized semantic-head checkpoint")
        checksum_start = len(FACTORIZED_HEAD_CHECKPOINT_MAGIC)
        checksum = value[checksum_start : checksum_start + 32]
        payload = value[checksum_start + 32 :]
        if hashlib.sha256(payload).digest() != checksum:
            raise ValueError("factorized semantic-head checkpoint checksum mismatch")
        return cls.from_dict(json.loads(zlib.decompress(payload).decode("utf-8")))

    @property
    def checkpoint_bytes(self) -> int:
        return len(self.to_checkpoint_bytes())

    @property
    def identity(self) -> str:
        return _digest(self.to_dict(include_reports=False))


@dataclass(frozen=True, slots=True)
class FactorizedHeadQualityGateConfig:
    """Fail-closed non-tradeable metric policy for architecture ablations."""

    tolerance: float = 0.0
    require_semantic_equivalence: bool = True
    require_protected_categories: bool = True
    semantic_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.tolerance)) or float(self.tolerance) < 0.0:
            raise ValueError("quality tolerance must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class FactorizedHeadQualityReport:
    accepted: bool
    objective_improvements: Mapping[str, float]
    protected_regressions: Mapping[str, Mapping[str, float]]
    missing_categories: tuple[str, ...]
    semantic_equivalence: Mapping[str, Any]
    block_reasons: tuple[str, ...]

    @property
    def ce_or_cosine_improved(self) -> bool:
        return bool(self.objective_improvements)

    @property
    def disagreement(self) -> bool:
        return self.ce_or_cosine_improved and bool(self.protected_regressions or self.missing_categories or self.semantic_equivalence.get("accepted") is False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "block_reasons": list(self.block_reasons),
            "ce_or_cosine_improved": self.ce_or_cosine_improved,
            "disagreement": self.disagreement,
            "missing_categories": list(self.missing_categories),
            "objective_improvements": dict(self.objective_improvements),
            "protected_regressions": {key: dict(value) for key, value in self.protected_regressions.items()},
            "semantic_equivalence": dict(self.semantic_equivalence),
        }


_CATEGORY_METRICS: Mapping[str, Mapping[str, int]] = {
    "proof_validity": {
        "hammer_proof_success_rate": 1, "proof_validity_rate": 1,
        "symbolic_validity_success_rate": 1, "symbolic_validity_penalty": -1,
    },
    "provenance": {
        "provenance_alignment_success_rate": 1, "provenance_consistency_success_rate": 1,
        "provenance_coverage": 1, "missing_provenance_id_penalty": -1,
        "provenance_regression_penalty": -1,
    },
    "round_trip": {
        "round_trip_reconstruction_success_rate": 1, "hammer_reconstruction_success_rate": 1,
        "reconstruction_success_rate": 1, "round_trip_loss": -1,
        "structural_text_reconstruction_loss": -1,
    },
    "anti_copy": {
        "anti_copy_success_rate": 1, "source_copy_penalty": -1,
        "source_copy_reward_hack_penalty": -1, "round_trip_source_copy_guardrail_loss": -1,
    },
}
_OBJECTIVE_DIRECTIONS = {
    "cross_entropy_loss": -1,
    "autoencoder_cross_entropy_loss": -1,
    "ir_cross_entropy_loss": -1,
    "compiler_ir_cross_entropy_loss": -1,
    "cosine_similarity": 1,
    "autoencoder_cosine_similarity": 1,
    "ir_cosine_similarity": 1,
    "compiler_ir_cosine_similarity": 1,
    "embedding_cosine_similarity": 1,
}


def _flatten_metrics(value: Mapping[str, Any], prefix: str = "") -> Dict[str, float]:
    result: Dict[str, float] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(_flatten_metrics(item, path))
        elif isinstance(item, (int, float)) and math.isfinite(float(item)):
            result[path] = float(item)
    return result


def _matching_metrics(flat: Mapping[str, float], names: Mapping[str, int]) -> Dict[str, tuple[float, int]]:
    result: Dict[str, tuple[float, int]] = {}
    for path, value in flat.items():
        leaf = path.rsplit(".", 1)[-1]
        for name, direction in names.items():
            if leaf == name or leaf.endswith("_" + name):
                result[path] = (value, direction)
                break
    return result


def evaluate_factorized_head_quality(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    config: Optional[FactorizedHeadQualityGateConfig] = None,
) -> FactorizedHeadQualityReport:
    """Reject any CE/cosine trade for semantic or protected regressions."""

    effective = config or FactorizedHeadQualityGateConfig()
    before = _flatten_metrics(baseline_metrics)
    after = _flatten_metrics(candidate_metrics)
    improvements: Dict[str, float] = {}
    for path, (prior, direction) in _matching_metrics(before, _OBJECTIVE_DIRECTIONS).items():
        if path in after:
            delta = direction * (after[path] - prior)
            if delta > effective.tolerance:
                improvements[path] = float(delta)
    regressions: Dict[str, Dict[str, float]] = {}
    missing: list[str] = []
    for category, aliases in _CATEGORY_METRICS.items():
        prior_values = _matching_metrics(before, aliases)
        next_values = _matching_metrics(after, aliases)
        common = sorted(set(prior_values) & set(next_values))
        if not common:
            if effective.require_protected_categories:
                missing.append(category)
            continue
        for path in common:
            prior, direction = prior_values[path]
            current, _ = next_values[path]
            degradation = direction * (prior - current)
            if degradation > effective.tolerance:
                regressions.setdefault(category, {})[path] = float(degradation)
    semantic_payload: Dict[str, Any] = {}
    try:
        from .legal_ir_semantic_metrics import (
            LEGAL_IR_EVALUATION_FAMILIES,
            SemanticEquivalenceConfig,
            compare_legal_ir_semantic_equivalence,
        )
        families = effective.semantic_families or tuple(LEGAL_IR_EVALUATION_FAMILIES)
        semantic = compare_legal_ir_semantic_equivalence(
            baseline_metrics, candidate_metrics,
            config=SemanticEquivalenceConfig(
                families=families,
                regression_tolerance=effective.tolerance,
                require_complete_metrics=effective.require_semantic_equivalence,
            ),
        )
        semantic_payload = semantic.to_dict()
    except (ImportError, TypeError, ValueError) as exc:
        semantic_payload = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
    reasons = [f"protected_metric_regressed:{category}" for category in sorted(regressions)]
    reasons.extend(f"protected_metric_evidence_missing:{category}" for category in missing)
    if effective.require_semantic_equivalence and not bool(semantic_payload.get("accepted", False)):
        reasons.append("family_semantic_equivalence_failed")
    return FactorizedHeadQualityReport(
        accepted=not reasons,
        objective_improvements=dict(sorted(improvements.items())),
        protected_regressions={key: dict(sorted(value.items())) for key, value in sorted(regressions.items())},
        missing_categories=tuple(sorted(missing)),
        semantic_equivalence=semantic_payload,
        block_reasons=tuple(reasons),
    )


def require_factorized_head_quality(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    config: Optional[FactorizedHeadQualityGateConfig] = None,
) -> FactorizedHeadQualityReport:
    report = evaluate_factorized_head_quality(baseline_metrics, candidate_metrics, config=config)
    if not report.accepted:
        raise FactorizedQualityGateError("factorized head candidate rejected: " + ", ".join(report.block_reasons))
    return report


def factorized_head_ablation_configs(
    base: Optional[FactorizedHeadConfig] = None,
    *,
    ranks: Sequence[int] = (0, 4, 8, 16),
    include_residual_ablation: bool = True,
) -> Dict[str, FactorizedHeadConfig]:
    """Expose explicit rank and residual arms for causal evaluation."""

    source = base or FactorizedHeadConfig()
    result: Dict[str, FactorizedHeadConfig] = {}
    for rank in ranks:
        value = int(rank)
        if value < 0:
            raise ValueError("ablation ranks must be non-negative")
        result[f"rank_{value}_residual_on"] = replace(
            source, rank=value, low_rank_enabled=value > 0, residual_enabled=True,
        )
        if include_residual_ablation:
            result[f"rank_{value}_residual_off"] = replace(
                source, rank=value, low_rank_enabled=value > 0, residual_enabled=False,
            )
    return result


# Readable aliases used by experiment manifests.
FactorizedInteractionHead = FactorizedSemanticInteractionHead
FactorizedInteractionHeads = FactorizedSemanticInteractionHeads
FactorizedHeadQualityGateError = FactorizedQualityGateError
factorized_head_quality_gate = evaluate_factorized_head_quality
rank_and_residual_ablations = factorized_head_ablation_configs


__all__ = [
    "DEFAULT_INTERACTION_RANK",
    "DEFAULT_MIGRATION_TOLERANCE",
    "DEFAULT_RESIDUAL_CAPACITY",
    "FACTORIZED_HEAD_CHECKPOINT_MAGIC",
    "FACTORIZED_HEAD_SCHEMA_VERSION",
    "FACTORIZED_HEADS_SCHEMA_VERSION",
    "FAMILY_LOGIT_HEAD",
    "FactorizedHeadConfig",
    "FactorizedHeadError",
    "FactorizedHeadQualityGateConfig",
    "FactorizedHeadQualityGateError",
    "FactorizedHeadQualityReport",
    "FactorizedInteractionHead",
    "FactorizedInteractionHeads",
    "FactorizedMigrationError",
    "FactorizedSemanticInteractionHead",
    "FactorizedSemanticInteractionHeads",
    "HeadMigrationReport",
    "LEGAL_IR_VIEW_LOGIT_HEAD",
    "LEGACY_FACTORIZED_FIELDS",
    "MINIMUM_CANONICAL_STATE_REDUCTION",
    "ResidualCapacityError",
    "TRIPLE_EMBEDDING_HEAD",
    "UnverifiedResidualError",
    "VerifiedResidual",
    "evaluate_factorized_head_quality",
    "factorize_interaction_records",
    "factorized_head_ablation_configs",
    "factorized_head_quality_gate",
    "rank_and_residual_ablations",
    "require_factorized_head_quality",
]
