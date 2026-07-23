"""Profiling utilities for LegalIR projection training.

The modal autoencoder projection loop is intentionally sparse and guarded: it
does many small candidate updates, then evaluates whether a candidate can be
accepted without regressing deterministic compiler quality.  CUDA makes the
dense metric portions faster, but tiny host/device transfers and synchronization
points can dominate the guarded line-search loop.  This module records those
costs without requiring CUDA to be available in unit tests.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, DefaultDict, Dict, Iterator, List, Mapping, Optional, Sequence


PROJECTION_PROFILE_SCHEMA_VERSION = "legal-ir-projection-profile-v1"
PROJECTION_PROFILE_COST_FAMILIES = (
    "host_device_transfer",
    "kernel",
    "synchronization",
    "python_loop",
    "optimizer",
    "feature_head",
)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentile)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bucket(values: Sequence[float]) -> Dict[str, float]:
    numeric = [max(0.0, float(value)) for value in values]
    total = sum(numeric)
    return {
        "count": float(len(numeric)),
        "seconds": total,
        "p50_seconds": _percentile(numeric, 0.50),
        "p95_seconds": _percentile(numeric, 0.95),
        "max_seconds": max(numeric, default=0.0),
    }


@dataclass(frozen=True)
class ProjectionProfileEvent:
    """One timed projection-training observation."""

    cost_family: str
    seconds: float
    stage: str = ""
    legal_family: str = ""
    feature_head: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cost_family": self.cost_family,
            "feature_head": self.feature_head,
            "legal_family": self.legal_family,
            "metadata": dict(self.metadata),
            "seconds": round(max(0.0, float(self.seconds)), 12),
            "stage": self.stage,
        }


@dataclass
class ProjectionProfiler:
    """Low-overhead wall-clock profiler for guarded projection training."""

    enabled: bool = True
    synchronize_cuda_events: bool = False
    cuda_synchronizer: Optional[Any] = None
    events: List[ProjectionProfileEvent] = field(default_factory=list)
    counters: DefaultDict[str, int] = field(default_factory=lambda: defaultdict(int))

    @contextmanager
    def phase(
        self,
        cost_family: str,
        *,
        stage: str = "",
        legal_family: str = "",
        feature_head: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Iterator[None]:
        """Time a projection phase.

        CUDA synchronization is opt-in.  Production training avoids forced
        synchronizations here; benchmark runs that need exact kernel timing can
        pass ``synchronize_cuda_events=True``.
        """
        if not self.enabled:
            yield
            return
        normalized = self._normalize_cost_family(cost_family)
        if normalized == "synchronization" and self.synchronize_cuda_events:
            self.synchronize(stage=stage, legal_family=legal_family)
        started = time.perf_counter()
        try:
            yield
        finally:
            if normalized == "kernel" and self.synchronize_cuda_events:
                self.synchronize(stage=stage, legal_family=legal_family)
            elapsed = time.perf_counter() - started
            self.record(
                normalized,
                elapsed,
                stage=stage,
                legal_family=legal_family,
                feature_head=feature_head,
                metadata=metadata,
            )

    def record(
        self,
        cost_family: str,
        seconds: float,
        *,
        stage: str = "",
        legal_family: str = "",
        feature_head: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        normalized = self._normalize_cost_family(cost_family)
        self.events.append(
            ProjectionProfileEvent(
                cost_family=normalized,
                seconds=max(0.0, float(seconds)),
                stage=str(stage or ""),
                legal_family=str(legal_family or ""),
                feature_head=str(feature_head or ""),
                metadata=dict(metadata or {}),
            )
        )

    def count(
        self,
        name: str,
        amount: int = 1,
        *,
        legal_family: str = "",
        feature_head: str = "",
    ) -> None:
        if not self.enabled:
            return
        key = str(name)
        self.counters[key] += int(amount)
        if legal_family:
            self.counters[f"{key}.family.{legal_family}"] += int(amount)
        if feature_head:
            self.counters[f"{key}.feature_head.{feature_head}"] += int(amount)

    def transfer(
        self,
        seconds: float = 0.0,
        *,
        stage: str = "",
        legal_family: str = "",
        count: int = 1,
        bytes_moved: int = 0,
    ) -> None:
        self.count("host_device_transfer_count", count, legal_family=legal_family)
        self.count("host_device_transfer_bytes", bytes_moved, legal_family=legal_family)
        self.record(
            "host_device_transfer",
            seconds,
            stage=stage,
            legal_family=legal_family,
            metadata={"bytes": int(bytes_moved), "count": int(count)},
        )

    def kernel(
        self,
        seconds: float = 0.0,
        *,
        stage: str = "",
        legal_family: str = "",
        count: int = 1,
    ) -> None:
        self.count("kernel_launch_count", count, legal_family=legal_family)
        self.record(
            "kernel",
            seconds,
            stage=stage,
            legal_family=legal_family,
            metadata={"count": int(count)},
        )

    def synchronize(
        self,
        *,
        stage: str = "",
        legal_family: str = "",
    ) -> None:
        if not self.enabled:
            return
        started = time.perf_counter()
        synchronizer = self.cuda_synchronizer
        if synchronizer is not None:
            synchronizer()
        elapsed = time.perf_counter() - started
        self.count("synchronization_count", 1, legal_family=legal_family)
        self.record(
            "synchronization",
            elapsed,
            stage=stage,
            legal_family=legal_family,
        )

    def family_for_sample(self, sample: Any) -> str:
        value = getattr(sample, "selected_frame", "") or getattr(sample, "logic_family", "")
        if value:
            return str(value)
        modal_ir = getattr(sample, "modal_ir", None)
        if modal_ir is not None:
            family = getattr(modal_ir, "family", "")
            if family:
                return str(family)
        return "unknown"

    def summarize(self) -> Dict[str, Any]:
        by_cost: Dict[str, List[float]] = {name: [] for name in PROJECTION_PROFILE_COST_FAMILIES}
        by_family: DefaultDict[str, List[float]] = defaultdict(list)
        by_feature_head: DefaultDict[str, List[float]] = defaultdict(list)
        by_stage: DefaultDict[str, List[float]] = defaultdict(list)
        for event in self.events:
            by_cost.setdefault(event.cost_family, []).append(event.seconds)
            if event.legal_family:
                by_family[event.legal_family].append(event.seconds)
            if event.feature_head:
                by_feature_head[event.feature_head].append(event.seconds)
            if event.stage:
                by_stage[event.stage].append(event.seconds)

        cost_summary = {
            name: _bucket(by_cost.get(name, ()))
            for name in PROJECTION_PROFILE_COST_FAMILIES
        }
        total_seconds = sum(event.seconds for event in self.events)
        return {
            "schema_version": PROJECTION_PROFILE_SCHEMA_VERSION,
            "cost_families": list(PROJECTION_PROFILE_COST_FAMILIES),
            "event_count": len(self.events),
            "total_seconds": round(total_seconds, 12),
            "warm_p95_projection_seconds": round(
                cost_summary["optimizer"]["p95_seconds"]
                + cost_summary["feature_head"]["p95_seconds"]
                + cost_summary["kernel"]["p95_seconds"]
                + cost_summary["host_device_transfer"]["p95_seconds"]
                + cost_summary["synchronization"]["p95_seconds"],
                12,
            ),
            "by_cost_family": cost_summary,
            "by_legal_family": {
                family: _bucket(values)
                for family, values in sorted(by_family.items())
            },
            "by_feature_head": {
                head: _bucket(values)
                for head, values in sorted(by_feature_head.items())
            },
            "by_stage": {
                stage: _bucket(values)
                for stage, values in sorted(by_stage.items())
            },
            "counters": dict(sorted(self.counters.items())),
            "events": [event.to_dict() for event in self.events],
        }

    def _normalize_cost_family(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in PROJECTION_PROFILE_COST_FAMILIES:
            raise ValueError(f"unknown projection profile cost family: {value!r}")
        return normalized


def summarize_projection_profiles(
    *,
    baseline: Mapping[str, Any],
    optimized: Mapping[str, Any],
    tolerance: float = 1.0e-9,
) -> Dict[str, Any]:
    """Compare baseline and optimized projection profiles."""

    baseline_p95 = float(baseline.get("warm_p95_projection_seconds", 0.0) or 0.0)
    optimized_p95 = float(optimized.get("warm_p95_projection_seconds", 0.0) or 0.0)
    reduction = 0.0
    if baseline_p95 > 0.0:
        reduction = max(0.0, (baseline_p95 - optimized_p95) / baseline_p95)
    return {
        "schema_version": PROJECTION_PROFILE_SCHEMA_VERSION,
        "baseline_warm_p95_projection_seconds": round(baseline_p95, 12),
        "optimized_warm_p95_projection_seconds": round(optimized_p95, 12),
        "warm_p95_reduction_ratio": round(reduction, 12),
        "warm_p95_reduction_percent": round(reduction * 100.0, 6),
        "meets_40_percent_target": reduction + float(tolerance) >= 0.40,
    }
