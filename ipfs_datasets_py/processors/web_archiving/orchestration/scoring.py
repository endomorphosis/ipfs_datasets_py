"""Provider scoring utilities for throughput-aware orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from ..contracts import OperationMode
from ..metrics.registry import MetricsRegistry


@dataclass(frozen=True)
class ScoringWeights:
    """Weight profile used to compute provider ranking scores."""

    throughput: float
    success_rate: float
    latency: float
    quality: float
    cost: float


@dataclass(frozen=True)
class ScoringTargets:
    """Normalization targets used for score components."""

    target_throughput_items_per_sec: float = 1.0
    latency_ceiling_ms: float = 2000.0
    max_cost_hint: float = 1.0


@dataclass
class ProviderScore:
    """Final score object for one provider candidate."""

    provider: str
    operation: str
    profile: OperationMode
    score: float
    components: Dict[str, float] = field(default_factory=dict)
    window_seconds: int = 300


DEFAULT_WEIGHTS_BY_MODE: Dict[OperationMode, ScoringWeights] = {
    OperationMode.MAX_THROUGHPUT: ScoringWeights(throughput=0.40, success_rate=0.20, latency=0.15, quality=0.15, cost=0.10),
    OperationMode.BALANCED: ScoringWeights(throughput=0.25, success_rate=0.25, latency=0.20, quality=0.20, cost=0.10),
    OperationMode.MAX_QUALITY: ScoringWeights(throughput=0.10, success_rate=0.20, latency=0.15, quality=0.45, cost=0.10),
    OperationMode.LOW_COST: ScoringWeights(throughput=0.15, success_rate=0.20, latency=0.15, quality=0.10, cost=0.40),
}


DEFAULT_TARGETS_BY_MODE: Dict[OperationMode, ScoringTargets] = {
    OperationMode.MAX_THROUGHPUT: ScoringTargets(target_throughput_items_per_sec=3.0, latency_ceiling_ms=2500.0, max_cost_hint=1.0),
    OperationMode.BALANCED: ScoringTargets(target_throughput_items_per_sec=2.0, latency_ceiling_ms=2000.0, max_cost_hint=1.0),
    OperationMode.MAX_QUALITY: ScoringTargets(target_throughput_items_per_sec=1.0, latency_ceiling_ms=3000.0, max_cost_hint=1.0),
    OperationMode.LOW_COST: ScoringTargets(target_throughput_items_per_sec=1.5, latency_ceiling_ms=3000.0, max_cost_hint=1.0),
}


class ProviderScorer:
    """Score and rank providers using rolling operational metrics."""

    def __init__(
        self,
        metrics_registry: MetricsRegistry,
        default_window_seconds: int = 300,
        weights_by_mode: Optional[Dict[OperationMode, ScoringWeights]] = None,
        targets_by_mode: Optional[Dict[OperationMode, ScoringTargets]] = None,
    ):
        if default_window_seconds <= 0:
            raise ValueError("default_window_seconds must be > 0")
        self.metrics_registry = metrics_registry
        self.default_window_seconds = default_window_seconds
        self.weights_by_mode = dict(weights_by_mode or DEFAULT_WEIGHTS_BY_MODE)
        self.targets_by_mode = dict(targets_by_mode or DEFAULT_TARGETS_BY_MODE)

    def score_provider(
        self,
        provider: str,
        operation: str,
        mode: OperationMode = OperationMode.MAX_THROUGHPUT,
        window_seconds: Optional[int] = None,
        cost_hint: float = 0.0,
    ) -> ProviderScore:
        """Compute the composite score for a provider."""
        if not provider:
            raise ValueError("provider must be non-empty")
        if not operation:
            raise ValueError("operation must be non-empty")
        if cost_hint < 0:
            raise ValueError("cost_hint must be >= 0")

        window = int(window_seconds or self.default_window_seconds)
        if window <= 0:
            raise ValueError("window_seconds must be > 0")

        weights = self.weights_by_mode[mode]
        targets = self.targets_by_mode[mode]
        snap = self.metrics_registry.snapshot(provider, operation, window_seconds=window)

        throughput_norm = _clamp01(snap["throughput_items_per_sec"] / targets.target_throughput_items_per_sec)
        success_norm = _clamp01(snap["success_rate"])
        latency_norm = _clamp01(1.0 - (snap["avg_latency_ms"] / targets.latency_ceiling_ms))
        quality_norm = _clamp01(snap["avg_quality_score"])
        cost_norm = _clamp01(1.0 - (cost_hint / targets.max_cost_hint))

        score = (
            weights.throughput * throughput_norm
            + weights.success_rate * success_norm
            + weights.latency * latency_norm
            + weights.quality * quality_norm
            + weights.cost * cost_norm
        )

        components = {
            "throughput_norm": throughput_norm,
            "success_norm": success_norm,
            "latency_norm": latency_norm,
            "quality_norm": quality_norm,
            "cost_norm": cost_norm,
        }

        return ProviderScore(
            provider=provider,
            operation=operation,
            profile=mode,
            score=float(score),
            components=components,
            window_seconds=window,
        )

    def rank_providers(
        self,
        providers: Iterable[str],
        operation: str,
        mode: OperationMode = OperationMode.MAX_THROUGHPUT,
        window_seconds: Optional[int] = None,
        cost_hints: Optional[Dict[str, float]] = None,
    ) -> List[ProviderScore]:
        """Score and rank providers by descending composite score."""
        scored: List[ProviderScore] = []
        hints = cost_hints or {}

        for provider in providers:
            scored.append(
                self.score_provider(
                    provider=provider,
                    operation=operation,
                    mode=mode,
                    window_seconds=window_seconds,
                    cost_hint=float(hints.get(provider, 0.0)),
                )
            )

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


__all__ = [
    "ScoringWeights",
    "ScoringTargets",
    "ProviderScore",
    "DEFAULT_WEIGHTS_BY_MODE",
    "DEFAULT_TARGETS_BY_MODE",
    "ProviderScorer",
]
