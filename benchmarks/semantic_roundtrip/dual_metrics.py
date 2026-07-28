"""Dual-metric bridge: structural forward/cycle/e2e + optional CE/cosine.

Interface: ``DualRoundTripMetrics@1``

The composition protocol's primary selection loss remains structural
end-to-end (``1 - S(gold, L2)`` with the frozen weighted assignment score).
This module always reports structural forward, cycle, and end-to-end losses
via the existing structural helpers.

When an embedding metric backend is present and successfully scores every
comparison leg, the report also attaches cross-entropy and cosine similarity
for the same legs. Missing, unavailable, or failing backends fail closed to
**structural-only** without inventing CE/cosine scores. CE/cosine never
substitute for structural losses in promotion decisions.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.metrics import (
    RoundTripLosses,
    round_trip_losses,
)


DUAL_ROUND_TRIP_METRICS_INTERFACE: Final = "DualRoundTripMetrics@1"
DUAL_ROUND_TRIP_METRICS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-dual-metrics.v1"
)

METRIC_MODE_STRUCTURAL_ONLY: Final = "structural_only"
METRIC_MODE_DUAL: Final = "dual"

PROMOTION_PRIMARY_METRIC: Final = "structural_end_to_end"
CE_COSINE_MAY_SUBSTITUTE_FOR_PROMOTION: Final = False
PROMOTION_POLICY_NOTE: Final = (
    "Promotion and selection use structural end-to-end loss only "
    f"({PROMOTION_PRIMARY_METRIC}). Cross-entropy and cosine similarity are "
    "optional research diagnostics shared with AE-loop residuals and Codex "
    "packets. Missing embedding backends fail closed to structural-only; "
    "CE/cosine are never invented and never silently substitute for "
    "structural losses in promotion."
)

RESIDUAL_ROW_DUAL_METRICS_FIELD: Final = "dual_metrics"


class DualMetricMode(str, Enum):
    """Whether optional embedding metrics were attached."""

    STRUCTURAL_ONLY = METRIC_MODE_STRUCTURAL_ONLY
    DUAL = METRIC_MODE_DUAL


@dataclass(frozen=True, slots=True)
class EmbeddingPairMetrics:
    """Cross-entropy and cosine for one reference/candidate IR pair.

    ``cross_entropy`` is a non-negative finite loss (lower is better).
    ``cosine_similarity`` is in ``[-1, 1]`` (higher is better).
    """

    cross_entropy: float
    cosine_similarity: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.cross_entropy, bool)
            or not isinstance(self.cross_entropy, (int, float))
            or not math.isfinite(float(self.cross_entropy))
            or float(self.cross_entropy) < 0.0
        ):
            raise ContractError(
                "cross_entropy must be a finite non-negative number"
            )
        object.__setattr__(self, "cross_entropy", float(self.cross_entropy))
        if (
            isinstance(self.cosine_similarity, bool)
            or not isinstance(self.cosine_similarity, (int, float))
            or not math.isfinite(float(self.cosine_similarity))
            or not -1.0 <= float(self.cosine_similarity) <= 1.0
        ):
            raise ContractError(
                "cosine_similarity must be a finite number from -1 to 1"
            )
        object.__setattr__(
            self, "cosine_similarity", float(self.cosine_similarity)
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "cross_entropy": self.cross_entropy,
            "cosine_similarity": self.cosine_similarity,
        }


@runtime_checkable
class EmbeddingMetricBackend(Protocol):
    """Optional backend that scores IR pairs with CE and cosine.

    Implementations must return ``None`` when they cannot produce real scores
    for a pair. The bridge never invents values when a backend is missing or
    returns ``None``.
    """

    @property
    def identity(self) -> str:
        """Stable backend identity string."""

    def available(self) -> bool:
        """Return whether the backend can score pairs right now."""

    def pair_metrics(
        self,
        reference: CanonicalRuleIR,
        candidate: CanonicalRuleIR,
    ) -> EmbeddingPairMetrics | None:
        """Score one reference/candidate pair, or ``None`` if unavailable."""


@dataclass(frozen=True, slots=True)
class DualRoundTripMetrics:
    """Structural always; CE/cosine only when a backend scores every leg.

    Promotion authority is permanently structural end-to-end. Optional
    embedding metrics are research diagnostics and residual-catalog attachments.
    """

    structural_forward: float
    structural_cycle: float
    structural_end_to_end: float
    metric_mode: DualMetricMode
    embedding_backend_present: bool
    embedding_backend_id: str | None
    cross_entropy_forward: float | None
    cross_entropy_cycle: float | None
    cross_entropy_end_to_end: float | None
    cosine_forward: float | None
    cosine_cycle: float | None
    cosine_end_to_end: float | None
    promotion_primary_metric: str = PROMOTION_PRIMARY_METRIC
    ce_cosine_may_substitute_for_promotion: bool = (
        CE_COSINE_MAY_SUBSTITUTE_FOR_PROMOTION
    )
    promotion_policy_note: str = PROMOTION_POLICY_NOTE
    silent_metric_substitution: bool = False

    def __post_init__(self) -> None:
        for field in (
            "structural_forward",
            "structural_cycle",
            "structural_end_to_end",
        ):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ContractError(
                    f"{field} must be a finite number from zero to one"
                )
            object.__setattr__(self, field, float(value))

        if not isinstance(self.metric_mode, DualMetricMode):
            raise ContractError(
                "metric_mode must be a DualMetricMode member"
            )
        if not isinstance(self.embedding_backend_present, bool):
            raise ContractError("embedding_backend_present must be a boolean")
        if self.embedding_backend_id is not None and (
            not isinstance(self.embedding_backend_id, str)
            or not self.embedding_backend_id.strip()
        ):
            raise ContractError(
                "embedding_backend_id must be None or a nonblank string"
            )

        optional_float_fields = (
            "cross_entropy_forward",
            "cross_entropy_cycle",
            "cross_entropy_end_to_end",
            "cosine_forward",
            "cosine_cycle",
            "cosine_end_to_end",
        )
        for field in optional_float_fields:
            value = getattr(self, field)
            if value is None:
                continue
            if field.startswith("cross_entropy"):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < 0.0
                ):
                    raise ContractError(
                        f"{field} must be None or a finite non-negative number"
                    )
                object.__setattr__(self, field, float(value))
            else:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not -1.0 <= float(value) <= 1.0
                ):
                    raise ContractError(
                        f"{field} must be None or a finite number from -1 to 1"
                    )
                object.__setattr__(self, field, float(value))

        ce_values = (
            self.cross_entropy_forward,
            self.cross_entropy_cycle,
            self.cross_entropy_end_to_end,
        )
        cosine_values = (
            self.cosine_forward,
            self.cosine_cycle,
            self.cosine_end_to_end,
        )
        all_optional_none = all(v is None for v in (*ce_values, *cosine_values))
        all_optional_present = all(
            v is not None for v in (*ce_values, *cosine_values)
        )

        if self.metric_mode is DualMetricMode.STRUCTURAL_ONLY:
            if not all_optional_none:
                raise ContractError(
                    "structural_only mode forbids CE/cosine scores; "
                    "missing backends must not invent values"
                )
            if self.embedding_backend_present:
                # Present but incomplete/failed scoring still fails closed.
                pass
        elif self.metric_mode is DualMetricMode.DUAL:
            if not self.embedding_backend_present:
                raise ContractError(
                    "dual mode requires embedding_backend_present=True"
                )
            if self.embedding_backend_id is None:
                raise ContractError(
                    "dual mode requires a non-null embedding_backend_id"
                )
            if not all_optional_present:
                raise ContractError(
                    "dual mode requires CE and cosine on every leg; "
                    "partial scores are not allowed"
                )
        else:  # pragma: no cover - enum exhaustiveness
            raise ContractError(f"unknown metric_mode {self.metric_mode!r}")

        if self.promotion_primary_metric != PROMOTION_PRIMARY_METRIC:
            raise ContractError(
                "promotion_primary_metric must remain structural_end_to_end; "
                "CE/cosine cannot become the promotion primary"
            )
        if self.ce_cosine_may_substitute_for_promotion is not False:
            raise ContractError(
                "ce_cosine_may_substitute_for_promotion must remain False"
            )
        if self.silent_metric_substitution is not False:
            raise ContractError(
                "silent_metric_substitution must remain False"
            )
        if (
            not isinstance(self.promotion_policy_note, str)
            or not self.promotion_policy_note.strip()
        ):
            raise ContractError("promotion_policy_note must be nonblank")

    @property
    def structural(self) -> RoundTripLosses:
        """Structural losses as the protocol ``RoundTripLosses`` triple."""

        return RoundTripLosses(
            forward=self.structural_forward,
            cycle=self.structural_cycle,
            end_to_end=self.structural_end_to_end,
        )

    @property
    def is_structural_only(self) -> bool:
        return self.metric_mode is DualMetricMode.STRUCTURAL_ONLY

    @property
    def is_dual(self) -> bool:
        return self.metric_mode is DualMetricMode.DUAL

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": DUAL_ROUND_TRIP_METRICS_INTERFACE,
            "schema": DUAL_ROUND_TRIP_METRICS_SCHEMA,
            "structural_forward": self.structural_forward,
            "structural_cycle": self.structural_cycle,
            "structural_end_to_end": self.structural_end_to_end,
            "metric_mode": self.metric_mode.value,
            "embedding_backend_present": self.embedding_backend_present,
            "embedding_backend_id": self.embedding_backend_id,
            "cross_entropy_forward": self.cross_entropy_forward,
            "cross_entropy_cycle": self.cross_entropy_cycle,
            "cross_entropy_end_to_end": self.cross_entropy_end_to_end,
            "cosine_forward": self.cosine_forward,
            "cosine_cycle": self.cosine_cycle,
            "cosine_end_to_end": self.cosine_end_to_end,
            "promotion_primary_metric": self.promotion_primary_metric,
            "ce_cosine_may_substitute_for_promotion": (
                self.ce_cosine_may_substitute_for_promotion
            ),
            "silent_metric_substitution": self.silent_metric_substitution,
            "promotion_policy_note": self.promotion_policy_note,
        }


def _coerce_ir(
    value: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    field_name: str,
) -> CanonicalRuleIR | None:
    if value is None:
        return None
    if isinstance(value, CanonicalRuleIR):
        return value
    if isinstance(value, Mapping):
        return CanonicalRuleIR.from_dict(value)
    raise ContractError(f"{field_name} must be CanonicalRuleIR or mapping")


def _structural_only(
    losses: RoundTripLosses,
    *,
    embedding_backend_present: bool,
    embedding_backend_id: str | None,
) -> DualRoundTripMetrics:
    return DualRoundTripMetrics(
        structural_forward=losses.forward,
        structural_cycle=losses.cycle,
        structural_end_to_end=losses.end_to_end,
        metric_mode=DualMetricMode.STRUCTURAL_ONLY,
        embedding_backend_present=embedding_backend_present,
        embedding_backend_id=embedding_backend_id,
        cross_entropy_forward=None,
        cross_entropy_cycle=None,
        cross_entropy_end_to_end=None,
        cosine_forward=None,
        cosine_cycle=None,
        cosine_end_to_end=None,
    )


def _score_leg(
    backend: EmbeddingMetricBackend,
    reference: CanonicalRuleIR | None,
    candidate: CanonicalRuleIR | None,
) -> EmbeddingPairMetrics | None:
    if reference is None or candidate is None:
        return None
    try:
        result = backend.pair_metrics(reference, candidate)
    except Exception:
        # Fail closed: backend errors never invent scores.
        return None
    if result is None:
        return None
    if not isinstance(result, EmbeddingPairMetrics):
        return None
    return result


def compute_dual_metrics(
    gold_ir: CanonicalRuleIR | Mapping[str, object],
    l1: CanonicalRuleIR | Mapping[str, object] | None,
    reconstruction: str | None,
    l2: CanonicalRuleIR | Mapping[str, object] | None,
    *,
    failed: bool = False,
    embedding_backend: EmbeddingMetricBackend | None = None,
) -> DualRoundTripMetrics:
    """Compute structural losses always; attach CE/cosine only when available.

    Structural losses reuse :func:`round_trip_losses` and therefore inherit the
    protocol fail-closed policy (missing artifacts → loss ``1.0`` on every
    structural leg).

    Embedding CE/cosine attach only when:

    1. ``embedding_backend`` is not ``None``;
    2. ``backend.available()`` is true;
    3. every of forward (gold→L1), cycle (L1→L2), and end-to-end (gold→L2)
       returns a real :class:`EmbeddingPairMetrics` (not ``None``).

    Otherwise the report is structural-only with CE/cosine fields set to
    ``None`` — never fabricated defaults such as ``0.0`` or ``1.0``.
    """

    gold = _coerce_ir(gold_ir, field_name="gold_ir")
    if gold is None:
        raise ContractError("gold_ir is required")
    first = _coerce_ir(l1, field_name="l1")
    second = _coerce_ir(l2, field_name="l2")
    losses = round_trip_losses(
        gold, first, reconstruction, second, failed=failed
    )

    if embedding_backend is None:
        return _structural_only(
            losses,
            embedding_backend_present=False,
            embedding_backend_id=None,
        )

    backend_id = getattr(embedding_backend, "identity", None)
    if not isinstance(backend_id, str) or not backend_id.strip():
        # Malformed backend identity → treat as missing (fail closed).
        return _structural_only(
            losses,
            embedding_backend_present=False,
            embedding_backend_id=None,
        )
    backend_id = backend_id.strip()

    try:
        is_available = bool(embedding_backend.available())
    except Exception:
        is_available = False

    if not is_available:
        return _structural_only(
            losses,
            embedding_backend_present=True,
            embedding_backend_id=backend_id,
        )

    forward_pair = _score_leg(embedding_backend, gold, first)
    cycle_pair = _score_leg(embedding_backend, first, second)
    e2e_pair = _score_leg(embedding_backend, gold, second)

    if forward_pair is None or cycle_pair is None or e2e_pair is None:
        return _structural_only(
            losses,
            embedding_backend_present=True,
            embedding_backend_id=backend_id,
        )

    return DualRoundTripMetrics(
        structural_forward=losses.forward,
        structural_cycle=losses.cycle,
        structural_end_to_end=losses.end_to_end,
        metric_mode=DualMetricMode.DUAL,
        embedding_backend_present=True,
        embedding_backend_id=backend_id,
        cross_entropy_forward=forward_pair.cross_entropy,
        cross_entropy_cycle=cycle_pair.cross_entropy,
        cross_entropy_end_to_end=e2e_pair.cross_entropy,
        cosine_forward=forward_pair.cosine_similarity,
        cosine_cycle=cycle_pair.cosine_similarity,
        cosine_end_to_end=e2e_pair.cosine_similarity,
    )


def dual_metrics_from_structural(
    structural: RoundTripLosses | Mapping[str, object],
    *,
    embedding_backend: EmbeddingMetricBackend | None = None,
    forward_pair: EmbeddingPairMetrics | None = None,
    cycle_pair: EmbeddingPairMetrics | None = None,
    end_to_end_pair: EmbeddingPairMetrics | None = None,
) -> DualRoundTripMetrics:
    """Bridge precomputed structural losses with optional CE/cosine pairs.

    Useful when residual-catalog rows already hold structural losses and a
    separate embedding pass produced pair metrics. Incomplete embedding pairs
    fail closed to structural-only.
    """

    if isinstance(structural, RoundTripLosses):
        losses = structural
    elif isinstance(structural, Mapping):
        losses = RoundTripLosses(
            forward=float(structural["forward"]),
            cycle=float(structural["cycle"]),
            end_to_end=float(structural["end_to_end"]),
        )
    else:
        raise ContractError(
            "structural must be RoundTripLosses or a mapping with "
            "forward/cycle/end_to_end"
        )

    if embedding_backend is None:
        if any(
            pair is not None
            for pair in (forward_pair, cycle_pair, end_to_end_pair)
        ):
            raise ContractError(
                "embedding pair metrics require an embedding_backend identity"
            )
        return _structural_only(
            losses,
            embedding_backend_present=False,
            embedding_backend_id=None,
        )

    backend_id = getattr(embedding_backend, "identity", None)
    if not isinstance(backend_id, str) or not backend_id.strip():
        return _structural_only(
            losses,
            embedding_backend_present=False,
            embedding_backend_id=None,
        )
    backend_id = backend_id.strip()

    try:
        is_available = bool(embedding_backend.available())
    except Exception:
        is_available = False

    if (
        not is_available
        or forward_pair is None
        or cycle_pair is None
        or end_to_end_pair is None
    ):
        return _structural_only(
            losses,
            embedding_backend_present=True,
            embedding_backend_id=backend_id,
        )

    return DualRoundTripMetrics(
        structural_forward=losses.forward,
        structural_cycle=losses.cycle,
        structural_end_to_end=losses.end_to_end,
        metric_mode=DualMetricMode.DUAL,
        embedding_backend_present=True,
        embedding_backend_id=backend_id,
        cross_entropy_forward=forward_pair.cross_entropy,
        cross_entropy_cycle=cycle_pair.cross_entropy,
        cross_entropy_end_to_end=end_to_end_pair.cross_entropy,
        cosine_forward=forward_pair.cosine_similarity,
        cosine_cycle=cycle_pair.cosine_similarity,
        cosine_end_to_end=end_to_end_pair.cosine_similarity,
    )


def attach_dual_metrics_to_residual_row(
    row: Mapping[str, object],
    metrics: DualRoundTripMetrics,
    *,
    field: str = RESIDUAL_ROW_DUAL_METRICS_FIELD,
) -> dict[str, object]:
    """Return a copy of a residual-catalog row with dual metrics attached.

    Never mutates the input row. Attachment is additive: structural losses on
    the row are not replaced by CE/cosine, and promotion authority remains
    structural end-to-end.
    """

    if not isinstance(row, Mapping):
        raise ContractError("row must be a mapping")
    if not isinstance(metrics, DualRoundTripMetrics):
        raise ContractError("metrics must be DualRoundTripMetrics")
    if not isinstance(field, str) or not field.strip():
        raise ContractError("field must be a nonblank string")
    attached = dict(row)
    attached[field] = metrics.to_dict()
    return attached


# ---------------------------------------------------------------------------
# Pure helpers for backends (self-contained; no torch / AE dependency)
# ---------------------------------------------------------------------------


def cosine_similarity(
    left: Sequence[float], right: Sequence[float]
) -> float:
    """Return cosine similarity of two equal-length vectors in ``[-1, 1]``."""

    if len(left) != len(right):
        raise ContractError("cosine vectors must have equal length")
    if not left:
        return 0.0
    left_vals = [float(v) for v in left]
    right_vals = [float(v) for v in right]
    if any(not math.isfinite(v) for v in (*left_vals, *right_vals)):
        raise ContractError("cosine vectors must be finite")
    left_norm = math.sqrt(sum(v * v for v in left_vals))
    right_norm = math.sqrt(sum(v * v for v in right_vals))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left_vals, right_vals)) / (
        left_norm * right_norm
    )


def cross_entropy_from_distributions(
    predicted: Mapping[str, float],
    target: Mapping[str, float],
    *,
    epsilon: float = 1.0e-12,
) -> float:
    """Return cross-entropy of ``predicted`` against a target distribution.

    Both maps are treated as non-negative unnormalized weights over a shared
    key union. Empty or zero-mass targets yield ``0.0``.
    """

    if epsilon <= 0.0 or not math.isfinite(epsilon):
        raise ContractError("epsilon must be a positive finite number")
    keys = sorted(set(predicted) | set(target))
    if not keys:
        return 0.0
    target_mass = sum(max(0.0, float(target.get(key, 0.0))) for key in keys)
    if target_mass <= 0.0:
        return 0.0
    pred_mass = sum(max(0.0, float(predicted.get(key, 0.0))) for key in keys)
    if pred_mass <= 0.0:
        # No predicted mass: maximum fail-closed CE against target support.
        return -math.log(epsilon)
    loss = 0.0
    for key in keys:
        t = max(0.0, float(target.get(key, 0.0))) / target_mass
        if t <= 0.0:
            continue
        p = max(0.0, float(predicted.get(key, 0.0))) / pred_mass
        loss += t * -math.log(max(p, epsilon))
    return loss


@dataclass(frozen=True, slots=True)
class CallableEmbeddingBackend:
    """Test/production adapter around a pure pair-scoring callable.

    The callable receives coerced :class:`CanonicalRuleIR` pairs and must
    return :class:`EmbeddingPairMetrics` or ``None``. Exceptions and ``None``
    fail closed at the bridge (no invented scores).
    """

    identity: str
    scorer: Callable[
        [CanonicalRuleIR, CanonicalRuleIR], EmbeddingPairMetrics | None
    ]
    is_available: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.identity, str) or not self.identity.strip():
            raise ContractError("identity must be a nonblank string")
        if not callable(self.scorer):
            raise ContractError("scorer must be callable")
        if not isinstance(self.is_available, bool):
            raise ContractError("is_available must be a boolean")
        object.__setattr__(self, "identity", self.identity.strip())

    def available(self) -> bool:
        return self.is_available

    def pair_metrics(
        self,
        reference: CanonicalRuleIR,
        candidate: CanonicalRuleIR,
    ) -> EmbeddingPairMetrics | None:
        if not self.is_available:
            return None
        result = self.scorer(reference, candidate)
        if result is None:
            return None
        if not isinstance(result, EmbeddingPairMetrics):
            raise ContractError(
                "scorer must return EmbeddingPairMetrics or None"
            )
        return result


@dataclass(frozen=True, slots=True)
class UnavailableEmbeddingBackend:
    """Explicit missing/unavailable backend (structural-only path)."""

    identity: str = "unavailable"

    def available(self) -> bool:
        return False

    def pair_metrics(
        self,
        reference: CanonicalRuleIR,
        candidate: CanonicalRuleIR,
    ) -> EmbeddingPairMetrics | None:
        return None


__all__ = [
    "DUAL_ROUND_TRIP_METRICS_INTERFACE",
    "DUAL_ROUND_TRIP_METRICS_SCHEMA",
    "METRIC_MODE_STRUCTURAL_ONLY",
    "METRIC_MODE_DUAL",
    "PROMOTION_PRIMARY_METRIC",
    "CE_COSINE_MAY_SUBSTITUTE_FOR_PROMOTION",
    "PROMOTION_POLICY_NOTE",
    "RESIDUAL_ROW_DUAL_METRICS_FIELD",
    "DualMetricMode",
    "EmbeddingPairMetrics",
    "EmbeddingMetricBackend",
    "DualRoundTripMetrics",
    "compute_dual_metrics",
    "dual_metrics_from_structural",
    "attach_dual_metrics_to_residual_row",
    "cosine_similarity",
    "cross_entropy_from_distributions",
    "CallableEmbeddingBackend",
    "UnavailableEmbeddingBackend",
]
