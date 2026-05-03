"""Privacy policy helpers for aggregate wallet analytics."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class AnalyticsPrivacyPolicy:
    """Release policy for one aggregate analytics query."""

    min_cohort_size: int = 10
    epsilon: Optional[float] = None
    sensitivity: float = 1.0
    budget_key: Optional[str] = None
    budget_limit: Optional[float] = None
    release_exact_count: bool = True


def deterministic_laplace_noise(
    *,
    epsilon: float,
    sensitivity: float = 1.0,
    seed_material: str,
) -> float:
    """Return deterministic Laplace noise for reproducible local analytics tests.

    Production deployments should replace deterministic seeding with a reviewed
    randomness source and query ledger. The interface mirrors the production
    shape while keeping the in-process test service stable.
    """

    if epsilon <= 0:
        raise ValueError("epsilon must be greater than zero")
    if sensitivity <= 0:
        raise ValueError("sensitivity must be greater than zero")

    digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], "big")
    # Map away from exactly 0, 0.5, and 1.0 so inverse-CDF math stays finite.
    p = (raw + 0.5) / (1 << 64)
    centered = p - 0.5
    if centered == 0:
        centered = 1.0 / (1 << 65)

    scale = sensitivity / epsilon
    return -scale * math.copysign(math.log(1 - 2 * abs(centered)), centered)


def noisy_count(
    *,
    count: int,
    epsilon: float,
    sensitivity: float = 1.0,
    seed_material: str,
) -> Tuple[float, float]:
    """Return a non-negative noisy count and the applied noise."""

    noise = deterministic_laplace_noise(
        epsilon=epsilon,
        sensitivity=sensitivity,
        seed_material=seed_material,
    )
    return max(0.0, float(count) + noise), noise
