"""Knowledge-graph soak / longevity harness (KGP-031).

Short CI profiles prove mixed multi-graph longevity and resource bounds.
The 24-hour profile is opt-in and only runs after short profiles pass.
"""

from __future__ import annotations

from .growth import (
    DEFAULT_SERIES_KEYS,
    GrowthReport,
    SeriesGrowth,
    analyze_growth,
    analyze_series,
    synthesize_stable_samples,
    synthesize_unbounded_samples,
)
from .profiles import (
    DAY,
    MEDIUM,
    PROFILE_NAMES,
    SHORT,
    SOAK_PROFILES,
    SoakProfile,
    get_soak_profile,
    resolve_duration_override,
    short_profiles_required,
)
from .runner import (
    SOAK_RECEIPT_SCHEMA,
    SOAK_RECEIPT_SCHEMA_VERSION,
    SoakRunResult,
    build_soak_receipt,
    run_soak,
    write_soak_receipt,
)

__all__ = [
    "DAY",
    "DEFAULT_SERIES_KEYS",
    "GrowthReport",
    "MEDIUM",
    "PROFILE_NAMES",
    "SHORT",
    "SOAK_PROFILES",
    "SOAK_RECEIPT_SCHEMA",
    "SOAK_RECEIPT_SCHEMA_VERSION",
    "SeriesGrowth",
    "SoakProfile",
    "SoakRunResult",
    "analyze_growth",
    "analyze_series",
    "build_soak_receipt",
    "get_soak_profile",
    "resolve_duration_override",
    "run_soak",
    "short_profiles_required",
    "synthesize_stable_samples",
    "synthesize_unbounded_samples",
    "write_soak_receipt",
]
