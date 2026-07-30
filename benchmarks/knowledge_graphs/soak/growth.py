"""Resource-growth analysis for soak runs (KGP-031).

Detects statistically significant unbounded growth in RSS, open FDs, cache
bytes, WAL entry count, and active lease count. Uses ordinary least-squares
slope with a noise-aware threshold so short CI soaks do not false-positive
on normal allocator noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

JSONDict = Dict[str, Any]

# Default series keys tracked during soak.
DEFAULT_SERIES_KEYS: Tuple[str, ...] = (
    "rss_bytes",
    "open_fds",
    "cache_bytes",
    "wal_entries",
    "lease_count",
)


@dataclass(frozen=True, slots=True)
class SeriesGrowth:
    """Growth diagnostic for one metric series."""

    name: str
    n: int
    slope_per_s: float
    intercept: float
    r_squared: float
    start: float
    end: float
    max_value: float
    min_value: float
    relative_growth: float
    unbounded: bool
    reason: str

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "n": self.n,
            "slope_per_s": self.slope_per_s,
            "intercept": self.intercept,
            "r_squared": self.r_squared,
            "start": self.start,
            "end": self.end,
            "max_value": self.max_value,
            "min_value": self.min_value,
            "relative_growth": self.relative_growth,
            "unbounded": self.unbounded,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GrowthReport:
    """Aggregate growth verdict across tracked series."""

    series: Tuple[SeriesGrowth, ...]
    unbounded: bool
    data_errors: int
    security_errors: int
    ok: bool
    summary: str

    def to_json_dict(self) -> JSONDict:
        return {
            "series": [s.to_json_dict() for s in self.series],
            "unbounded": self.unbounded,
            "data_errors": self.data_errors,
            "security_errors": self.security_errors,
            "ok": self.ok,
            "summary": self.summary,
        }


def _ols_slope(
    xs: Sequence[float], ys: Sequence[float]
) -> Tuple[float, float, float]:
    """Return (slope, intercept, r_squared) for simple OLS."""
    n = len(xs)
    if n < 2:
        y0 = float(ys[0]) if ys else 0.0
        return 0.0, y0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den <= 0.0:
        return 0.0, mean_y, 0.0
    slope = num / den
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if ss_tot <= 0.0 else max(0.0, 1.0 - (ss_res / ss_tot))
    return slope, intercept, r2


def analyze_series(
    name: str,
    timestamps: Sequence[float],
    values: Sequence[float],
    *,
    # Absolute slope (units/second) above which growth is concerning.
    max_slope_per_s: float,
    # Relative end/start growth fraction that is still acceptable.
    max_relative_growth: float = 0.5,
    # Require positive correlation for "unbounded" classification.
    min_r_squared: float = 0.35,
    # Floor: if max stays under this, never flag (noise).
    absolute_floor: float = 0.0,
) -> SeriesGrowth:
    if len(timestamps) != len(values):
        raise ValueError(f"{name}: timestamps/values length mismatch")
    if not values:
        return SeriesGrowth(
            name=name,
            n=0,
            slope_per_s=0.0,
            intercept=0.0,
            r_squared=0.0,
            start=0.0,
            end=0.0,
            max_value=0.0,
            min_value=0.0,
            relative_growth=0.0,
            unbounded=False,
            reason="empty",
        )

    t0 = float(timestamps[0])
    xs = [float(t) - t0 for t in timestamps]
    ys = [float(v) for v in values]
    slope, intercept, r2 = _ols_slope(xs, ys)
    start, end = ys[0], ys[-1]
    max_v, min_v = max(ys), min(ys)
    if start > 0:
        rel = (end - start) / start
    elif end > 0:
        rel = float("inf") if end > absolute_floor else 0.0
    else:
        rel = 0.0

    unbounded = False
    reason = "stable"
    if max_v <= absolute_floor:
        reason = "below_floor"
    elif slope > max_slope_per_s and r2 >= min_r_squared and rel > max_relative_growth:
        unbounded = True
        reason = (
            f"slope={slope:.6g}/s > {max_slope_per_s:.6g}/s "
            f"with r2={r2:.3f} and rel_growth={rel:.3f}"
        )
    elif slope > max_slope_per_s and r2 < min_r_squared:
        reason = "noisy_positive_slope"
    elif rel > max_relative_growth and slope <= max_slope_per_s:
        reason = "transient_spike"
    return SeriesGrowth(
        name=name,
        n=len(ys),
        slope_per_s=slope,
        intercept=intercept,
        r_squared=r2,
        start=start,
        end=end,
        max_value=max_v,
        min_value=min_v,
        relative_growth=rel if math.isfinite(rel) else 1e9,
        unbounded=unbounded,
        reason=reason,
    )


# Per-metric thresholds tuned for CI short soaks and 24h runs.
DEFAULT_THRESHOLDS: Mapping[str, Mapping[str, float]] = {
    "rss_bytes": {
        "max_slope_per_s": 50_000.0,  # ~50 KB/s sustained
        "max_relative_growth": 2.0,
        "absolute_floor": 1_000_000.0,
        "min_r_squared": 0.5,
    },
    "open_fds": {
        "max_slope_per_s": 0.05,  # 3 FD/min sustained
        "max_relative_growth": 1.0,
        "absolute_floor": 8.0,
        "min_r_squared": 0.5,
    },
    "cache_bytes": {
        # Live heads/leases/staged/idempotency only (excludes revision history).
        "max_slope_per_s": 5_000.0,
        "max_relative_growth": 3.0,
        "absolute_floor": 8_000.0,
        "min_r_squared": 0.55,
    },
    "wal_entries": {
        # Compaction should keep the live entry counter from climbing forever.
        "max_slope_per_s": 2.0,
        "max_relative_growth": 10.0,
        "absolute_floor": 200.0,
        "min_r_squared": 0.55,
    },
    "lease_count": {
        # Leases converge to O(graph_count); flag only large sustained growth.
        "max_slope_per_s": 0.5,
        "max_relative_growth": 5.0,
        "absolute_floor": 64.0,
        "min_r_squared": 0.6,
    },
}


def analyze_growth(
    samples: Sequence[Mapping[str, Any]],
    *,
    thresholds: Optional[Mapping[str, Mapping[str, float]]] = None,
    data_errors: int = 0,
    security_errors: int = 0,
) -> GrowthReport:
    """
    Analyze a list of resource samples.

    Each sample is a mapping with at least ``timestamp`` and the metric keys
    listed in :data:`DEFAULT_SERIES_KEYS`.
    """
    if not samples:
        return GrowthReport(
            series=(),
            unbounded=False,
            data_errors=data_errors,
            security_errors=security_errors,
            ok=data_errors == 0 and security_errors == 0,
            summary="no samples",
        )

    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for k, v in thresholds.items():
            thr[k] = {**thr.get(k, {}), **dict(v)}

    timestamps = [float(s["timestamp"]) for s in samples]
    series_out: List[SeriesGrowth] = []
    for key in DEFAULT_SERIES_KEYS:
        if key not in samples[0] and not any(key in s for s in samples):
            continue
        values = [float(s.get(key, 0.0) or 0.0) for s in samples]
        cfg = thr.get(key, {})
        series_out.append(
            analyze_series(
                key,
                timestamps,
                values,
                max_slope_per_s=float(cfg.get("max_slope_per_s", 1e12)),
                max_relative_growth=float(cfg.get("max_relative_growth", 10.0)),
                min_r_squared=float(cfg.get("min_r_squared", 0.5)),
                absolute_floor=float(cfg.get("absolute_floor", 0.0)),
            )
        )

    unbounded = any(s.unbounded for s in series_out)
    ok = (not unbounded) and data_errors == 0 and security_errors == 0
    if ok:
        summary = "soak growth bounds held; no data/security errors"
    else:
        bad = [s.name for s in series_out if s.unbounded]
        parts = []
        if bad:
            parts.append(f"unbounded={bad}")
        if data_errors:
            parts.append(f"data_errors={data_errors}")
        if security_errors:
            parts.append(f"security_errors={security_errors}")
        summary = "; ".join(parts) or "failed"
    return GrowthReport(
        series=tuple(series_out),
        unbounded=unbounded,
        data_errors=int(data_errors),
        security_errors=int(security_errors),
        ok=ok,
        summary=summary,
    )


def synthesize_unbounded_samples(
    *,
    n: int = 20,
    start_rss: float = 10_000_000.0,
    rss_per_step: float = 500_000.0,
    step_s: float = 1.0,
) -> List[JSONDict]:
    """Test helper: produce an obviously unbounded RSS series."""
    t0 = 1_700_000_000.0
    out: List[JSONDict] = []
    for i in range(n):
        out.append(
            {
                "timestamp": t0 + i * step_s,
                "rss_bytes": start_rss + i * rss_per_step,
                "open_fds": 20.0,
                "cache_bytes": 1000.0,
                "wal_entries": 5.0,
                "lease_count": 1.0,
            }
        )
    return out


def synthesize_stable_samples(
    *,
    n: int = 20,
    rss: float = 40_000_000.0,
    step_s: float = 1.0,
    noise: float = 50_000.0,
) -> List[JSONDict]:
    """Test helper: bounded series with light noise."""
    t0 = 1_700_000_000.0
    out: List[JSONDict] = []
    for i in range(n):
        # Deterministic alternating noise (no RNG dependency).
        jitter = noise if (i % 2 == 0) else -noise
        out.append(
            {
                "timestamp": t0 + i * step_s,
                "rss_bytes": rss + jitter,
                "open_fds": 24.0 + (1 if i % 5 == 0 else 0),
                "cache_bytes": 8_000.0 + (200 if i % 3 == 0 else 0),
                "wal_entries": float(3 + (i % 4)),  # bounded oscillation
                "lease_count": 1.0,
            }
        )
    return out
